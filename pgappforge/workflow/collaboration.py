"""
Real-Time Collaboration Engine for PgForge Workflows

Provides live collaboration capabilities including:
- Real-time workflow state synchronization
- Concurrent editing with conflict resolution
- User presence tracking
- Live comments and notifications
- WebSocket integration
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING
from dataclasses import dataclass, asdict
from enum import Enum
import asyncio
from threading import Lock
import redis
from contextlib import contextmanager
import time

from flask import current_app, session, request, g
from flask_login import current_user
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from flask_babel import gettext as _
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

from ..models.mixins import AuditMixin
from .core import WorkflowState, get_workflow_engine

if TYPE_CHECKING:
    from .core import WorkflowDefinition

log = logging.getLogger(__name__)

# Global collaboration manager instance
_collaboration_manager = None
_presence_lock = Lock()


class DistributedFieldLock:
    """Distributed lock for field-level conflict prevention using Redis."""

    def __init__(self, redis_client: redis.Redis, lock_timeout: int = 30):
        self.redis = redis_client
        self.lock_timeout = lock_timeout

    @contextmanager
    def acquire_field_lock(self, workflow_id: str, step_id: str, field_name: str, user_id: str):
        """Acquire distributed lock for specific field editing."""
        lock_key = f"field_lock:{workflow_id}:{step_id}:{field_name}"
        lock_value = f"{user_id}:{time.time()}"

        try:
            # Try to acquire lock with expiration
            if self.redis.set(lock_key, lock_value, nx=True, ex=self.lock_timeout):
                log.debug(f"Acquired field lock: {lock_key} by {user_id}")
                yield True
            else:
                # Check if lock is stale (previous holder might have crashed)
                existing_lock = self.redis.get(lock_key)
                if existing_lock:
                    existing_user, lock_time = existing_lock.decode().split(':', 1)
                    if time.time() - float(lock_time) > self.lock_timeout:
                        # Force release stale lock and try again
                        self.redis.delete(lock_key)
                        if self.redis.set(lock_key, lock_value, nx=True, ex=self.lock_timeout):
                            log.debug(f"Acquired stale field lock: {lock_key} by {user_id}")
                            yield True
                        else:
                            log.warning(f"Failed to acquire field lock: {lock_key} by {user_id}")
                            yield False
                    else:
                        log.warning(f"Field lock held by {existing_user}: {lock_key}")
                        yield False
                else:
                    yield False
        except redis.RedisError as e:
            log.error(f"Redis error acquiring field lock {lock_key}: {e}")
            # Fallback to allow operation without distributed locking
            yield True
        finally:
            # Release lock only if we hold it
            try:
                current_lock = self.redis.get(lock_key)
                if current_lock and current_lock.decode().startswith(f"{user_id}:"):
                    self.redis.delete(lock_key)
                    log.debug(f"Released field lock: {lock_key} by {user_id}")
            except redis.RedisError as e:
                log.error(f"Redis error releasing field lock {lock_key}: {e}")

    def check_field_conflicts(self, workflow_id: str, step_id: str, field_name: str) -> List[str]:
        """Check which users are currently editing this field."""
        lock_key = f"field_lock:{workflow_id}:{step_id}:{field_name}"
        try:
            lock_value = self.redis.get(lock_key)
            if lock_value:
                user_id, lock_time = lock_value.decode().split(':', 1)
                # Check if lock is still valid
                if time.time() - float(lock_time) <= self.lock_timeout:
                    return [user_id]
            return []
        except (redis.RedisError, ValueError) as e:
            log.error(f"Error checking field conflicts for {lock_key}: {e}")
            return []


class CollaborationEventType(Enum):
    """Types of collaboration events."""
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    STEP_CHANGED = "step_changed"
    FORM_UPDATED = "form_updated"
    COMMENT_ADDED = "comment_added"
    WORKFLOW_COMPLETED = "workflow_completed"
    CONFLICT_DETECTED = "conflict_detected"
    PRESENCE_UPDATE = "presence_update"
    NOTIFICATION = "notification"


@dataclass
class CollaborationEvent:
    """Represents a collaboration event."""
    event_type: CollaborationEventType
    workflow_id: str
    user_id: str
    user_name: str
    timestamp: datetime
    data: Dict[str, Any]
    step_id: Optional[str] = None


@dataclass
class UserPresence:
    """Represents user presence in a workflow."""
    user_id: str
    user_name: str
    current_step: Optional[str]
    last_activity: datetime
    is_editing: bool = False
    cursor_position: Optional[Dict[str, Any]] = None


class WorkflowCollaborationSession(AuditMixin):
    """
    Tracks collaboration sessions for workflows.
    """
    __tablename__ = 'ab_workflow_collaboration_sessions'

    id = Column(String(36), primary_key=True)
    workflow_state_id = Column(String(36), ForeignKey('ab_workflow_states.id'), nullable=False)
    user_id = Column(Integer, nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    left_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    last_activity = Column(DateTime, default=datetime.utcnow)
    current_step = Column(String(100), nullable=True)
    session_data = Column(JSON, default=lambda: {})

    # Relationships
    workflow_state = relationship("WorkflowState", backref="collaboration_sessions")


class WorkflowComment(AuditMixin):
    """
    Comments and annotations on workflow steps.
    """
    __tablename__ = 'ab_workflow_comments'

    id = Column(String(36), primary_key=True)
    workflow_state_id = Column(String(36), ForeignKey('ab_workflow_states.id'), nullable=False)
    step_id = Column(String(100), nullable=False)
    user_id = Column(Integer, nullable=False)
    comment_text = Column(Text, nullable=False)
    comment_type = Column(String(20), default='comment')  # comment, suggestion, approval, rejection
    resolved = Column(Boolean, default=False)
    resolved_by = Column(Integer, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    metadata = Column(JSON, default=lambda: {})

    # Relationships
    workflow_state = relationship("WorkflowState", backref="comments")


class ConflictResolution(AuditMixin):
    """
    Tracks and resolves conflicts in collaborative editing.
    """
    __tablename__ = 'ab_workflow_conflicts'

    id = Column(String(36), primary_key=True)
    workflow_state_id = Column(String(36), ForeignKey('ab_workflow_states.id'), nullable=False)
    step_id = Column(String(100), nullable=False)
    field_name = Column(String(100), nullable=False)
    conflict_type = Column(String(50), default='concurrent_edit')
    user1_id = Column(Integer, nullable=False)
    user2_id = Column(Integer, nullable=False)
    user1_value = Column(Text, nullable=True)
    user2_value = Column(Text, nullable=True)
    resolved_value = Column(Text, nullable=True)
    resolution_strategy = Column(String(50), nullable=True)  # manual, auto_merge, last_wins, first_wins
    resolved = Column(Boolean, default=False)
    resolved_by = Column(Integer, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    # Relationships
    workflow_state = relationship("WorkflowState", backref="conflicts")


class WorkflowCollaborationManager:
    """
    Manages real-time collaboration for workflows.
    """

    def __init__(self, socketio: Optional[SocketIO] = None):
        self.socketio = socketio
        self.active_sessions: Dict[str, Dict[str, UserPresence]] = {}  # workflow_id -> user_id -> presence
        self.conflict_handlers: Dict[str, callable] = {}
        self.event_handlers: Dict[CollaborationEventType, List[callable]] = {}

        # Initialize Redis connection for distributed locking
        try:
            redis_host = current_app.config.get('REDIS_HOST', 'localhost')
            redis_port = current_app.config.get('REDIS_PORT', 6379)
            redis_db = current_app.config.get('REDIS_DB', 0)
            self.redis_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=False)
            self.field_lock = DistributedFieldLock(self.redis_client)
            log.info("Initialized distributed field locking with Redis")
        except Exception as e:
            log.warning(f"Failed to initialize Redis for distributed locking: {e}")
            self.redis_client = None
            self.field_lock = None

        self._setup_default_handlers()

    def _setup_default_handlers(self):
        """Setup default event handlers."""
        self.register_event_handler(CollaborationEventType.CONFLICT_DETECTED, self._handle_conflict_detection)
        self.register_event_handler(CollaborationEventType.FORM_UPDATED, self._handle_form_update_conflict_check)

    def register_event_handler(self, event_type: CollaborationEventType, handler: callable):
        """Register event handler."""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    def emit_event(self, event: CollaborationEvent):
        """Emit collaboration event to all relevant users."""
        # Store event in database for offline users
        self._store_event(event)

        # Handle event with registered handlers
        handlers = self.event_handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                log.error(f"Error in collaboration event handler: {e}")

        # Emit via WebSocket if available
        if self.socketio:
            room = f"workflow_{event.workflow_id}"
            self.socketio.emit('collaboration_event', {
                'event_type': event.event_type.value,
                'workflow_id': event.workflow_id,
                'user_id': event.user_id,
                'user_name': event.user_name,
                'timestamp': event.timestamp.isoformat(),
                'data': event.data,
                'step_id': event.step_id
            }, room=room)

    def join_workflow(self, workflow_id: str, user_id: str, user_name: str, step_id: Optional[str] = None):
        """User joins workflow collaboration session."""
        with _presence_lock:
            if workflow_id not in self.active_sessions:
                self.active_sessions[workflow_id] = {}

            presence = UserPresence(
                user_id=user_id,
                user_name=user_name,
                current_step=step_id,
                last_activity=datetime.now(tz=timezone.utc)
            )

            self.active_sessions[workflow_id][user_id] = presence

            # Join WebSocket room
            if self.socketio:
                join_room(f"workflow_{workflow_id}")

            # Emit join event
            event = CollaborationEvent(
                event_type=CollaborationEventType.USER_JOINED,
                workflow_id=workflow_id,
                user_id=user_id,
                user_name=user_name,
                timestamp=datetime.now(tz=timezone.utc),
                data={'step_id': step_id},
                step_id=step_id
            )
            self.emit_event(event)

            log.info(f"User {user_name} joined workflow {workflow_id}")

    def leave_workflow(self, workflow_id: str, user_id: str, user_name: str):
        """User leaves workflow collaboration session."""
        with _presence_lock:
            if workflow_id in self.active_sessions and user_id in self.active_sessions[workflow_id]:
                del self.active_sessions[workflow_id][user_id]

                # Clean up empty workflows
                if not self.active_sessions[workflow_id]:
                    del self.active_sessions[workflow_id]

            # Leave WebSocket room
            if self.socketio:
                leave_room(f"workflow_{workflow_id}")

            # Emit leave event
            event = CollaborationEvent(
                event_type=CollaborationEventType.USER_LEFT,
                workflow_id=workflow_id,
                user_id=user_id,
                user_name=user_name,
                timestamp=datetime.now(tz=timezone.utc),
                data={}
            )
            self.emit_event(event)

            log.info(f"User {user_name} left workflow {workflow_id}")

    def update_user_step(self, workflow_id: str, user_id: str, user_name: str, step_id: str):
        """Update user's current step."""
        with _presence_lock:
            if workflow_id in self.active_sessions and user_id in self.active_sessions[workflow_id]:
                presence = self.active_sessions[workflow_id][user_id]
                old_step = presence.current_step
                presence.current_step = step_id
                presence.last_activity = datetime.now(tz=timezone.utc)

                # Emit step change event
                event = CollaborationEvent(
                    event_type=CollaborationEventType.STEP_CHANGED,
                    workflow_id=workflow_id,
                    user_id=user_id,
                    user_name=user_name,
                    timestamp=datetime.now(tz=timezone.utc),
                    data={'old_step': old_step, 'new_step': step_id},
                    step_id=step_id
                )
                self.emit_event(event)

    def update_form_data(self, workflow_id: str, user_id: str, user_name: str,
                        step_id: str, field_name: str, field_value: Any):
        """Update form field data with distributed conflict detection."""

        # Use distributed locking to prevent race conditions
        if self.field_lock:
            with self.field_lock.acquire_field_lock(workflow_id, step_id, field_name, user_id) as lock_acquired:
                if lock_acquired:
                    # Successfully acquired lock, proceed with update
                    self._perform_form_update(workflow_id, user_id, user_name, step_id, field_name, field_value)
                else:
                    # Failed to acquire lock, another user is editing this field
                    conflicting_users = self.field_lock.check_field_conflicts(workflow_id, step_id, field_name)
                    self._emit_field_conflict_event(workflow_id, user_id, user_name, step_id, field_name,
                                                  field_value, conflicting_users)
        else:
            # Fallback to original conflict detection if Redis is not available
            log.warning("Distributed locking not available, falling back to basic conflict detection")
            conflict = self._detect_field_conflict(workflow_id, step_id, field_name, user_id, field_value)
            if conflict:
                self._emit_conflict_event(workflow_id, user_id, user_name, step_id, field_name,
                                        field_value, conflict)
            else:
                self._perform_form_update(workflow_id, user_id, user_name, step_id, field_name, field_value)

    def _perform_form_update(self, workflow_id: str, user_id: str, user_name: str,
                           step_id: str, field_name: str, field_value: Any):
        """Perform the actual form update after acquiring lock."""
        # Emit form update event
        event = CollaborationEvent(
            event_type=CollaborationEventType.FORM_UPDATED,
            workflow_id=workflow_id,
            user_id=user_id,
            user_name=user_name,
            timestamp=datetime.now(tz=timezone.utc),
            data={
                'field_name': field_name,
                'field_value': field_value
            },
            step_id=step_id
        )
        self.emit_event(event)

        # Update presence
        self._update_user_activity(workflow_id, user_id)
        log.debug(f"Updated form field {field_name} in workflow {workflow_id} by user {user_name}")

    def _emit_field_conflict_event(self, workflow_id: str, user_id: str, user_name: str,
                                 step_id: str, field_name: str, field_value: Any,
                                 conflicting_users: List[str]):
        """Emit conflict event when distributed lock cannot be acquired."""
        conflicting_user = conflicting_users[0] if conflicting_users else "unknown"

        event = CollaborationEvent(
            event_type=CollaborationEventType.CONFLICT_DETECTED,
            workflow_id=workflow_id,
            user_id=user_id,
            user_name=user_name,
            timestamp=datetime.now(tz=timezone.utc),
            data={
                'field_name': field_name,
                'conflict_type': 'concurrent_edit_locked',
                'conflicting_user': conflicting_user,
                'user_value': field_value,
                'message': f'Field {field_name} is currently being edited by another user'
            },
            step_id=step_id
        )
        self.emit_event(event)
        log.info(f"Field conflict detected: {field_name} in workflow {workflow_id}, users: {user_id} vs {conflicting_user}")

    def _emit_conflict_event(self, workflow_id: str, user_id: str, user_name: str,
                           step_id: str, field_name: str, field_value: Any,
                           conflict: 'ConflictResolution'):
        """Emit conflict event for legacy conflict resolution."""
        event = CollaborationEvent(
            event_type=CollaborationEventType.CONFLICT_DETECTED,
            workflow_id=workflow_id,
            user_id=user_id,
            user_name=user_name,
            timestamp=datetime.now(tz=timezone.utc),
            data={
                'field_name': field_name,
                'conflict_type': conflict.conflict_type,
                'conflicting_user': conflict.user2_id,
                'user_value': field_value,
                'conflicting_value': conflict.user2_value
            },
            step_id=step_id
        )
        self.emit_event(event)

    def add_comment(self, workflow_id: str, step_id: str, user_id: str, user_name: str, 
                   comment_text: str, comment_type: str = 'comment') -> str:
        """Add comment to workflow step."""
        from ..models import db
        from uuid_extensions import uuid7str

        comment = WorkflowComment(
            id=uuid7str(),
            workflow_state_id=workflow_id,
            step_id=step_id,
            user_id=user_id,
            comment_text=comment_text,
            comment_type=comment_type
        )

        db.session.add(comment)
        db.session.commit()

        # Emit comment event
        event = CollaborationEvent(
            event_type=CollaborationEventType.COMMENT_ADDED,
            workflow_id=workflow_id,
            user_id=user_id,
            user_name=user_name,
            timestamp=datetime.now(tz=timezone.utc),
            data={
                'comment_id': comment.id,
                'comment_text': comment_text,
                'comment_type': comment_type
            },
            step_id=step_id
        )
        self.emit_event(event)

        return comment.id

    def get_active_users(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get list of active users in workflow."""
        if workflow_id not in self.active_sessions:
            return []

        users = []
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(minutes=5)  # Consider inactive after 5 minutes

        for user_id, presence in self.active_sessions[workflow_id].items():
            if presence.last_activity > cutoff_time:
                users.append({
                    'user_id': presence.user_id,
                    'user_name': presence.user_name,
                    'current_step': presence.current_step,
                    'last_activity': presence.last_activity.isoformat(),
                    'is_editing': presence.is_editing
                })

        return users

    def get_workflow_comments(self, workflow_id: str, step_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get comments for workflow or specific step."""
        from ..models import db

        query = db.session.query(WorkflowComment).filter(
            WorkflowComment.workflow_state_id == workflow_id
        )

        if step_id:
            query = query.filter(WorkflowComment.step_id == step_id)

        comments = query.order_by(WorkflowComment.created_on.desc()).all()

        return [
            {
                'id': comment.id,
                'step_id': comment.step_id,
                'user_id': comment.user_id,
                'comment_text': comment.comment_text,
                'comment_type': comment.comment_type,
                'created_on': comment.created_on.isoformat(),
                'resolved': comment.resolved,
                'resolved_by': comment.resolved_by,
                'resolved_at': comment.resolved_at.isoformat() if comment.resolved_at else None
            }
            for comment in comments
        ]

    def resolve_conflict(self, conflict_id: str, resolution_strategy: str, 
                        resolved_value: Any, resolver_user_id: str) -> bool:
        """Resolve a collaboration conflict."""
        from ..models import db

        conflict = db.session.query(ConflictResolution).filter(
            ConflictResolution.id == conflict_id
        ).first()

        if not conflict:
            return False

        conflict.resolved = True
        conflict.resolved_by = resolver_user_id
        conflict.resolved_at = datetime.now(tz=timezone.utc)
        conflict.resolution_strategy = resolution_strategy
        conflict.resolved_value = str(resolved_value)

        db.session.commit()

        # Emit resolution event
        if conflict.workflow_state_id in self.active_sessions:
            for user_id, presence in self.active_sessions[conflict.workflow_state_id].items():
                event = CollaborationEvent(
                    event_type=CollaborationEventType.NOTIFICATION,
                    workflow_id=conflict.workflow_state_id,
                    user_id=user_id,
                    user_name=presence.user_name,
                    timestamp=datetime.now(tz=timezone.utc),
                    data={
                        'message': f'Conflict resolved in {conflict.field_name}',
                        'conflict_id': conflict_id,
                        'resolution_strategy': resolution_strategy
                    },
                    step_id=conflict.step_id
                )
                self.emit_event(event)

        return True

    def _detect_field_conflict(self, workflow_id: str, step_id: str, field_name: str, 
                              user_id: str, field_value: Any) -> Optional[ConflictResolution]:
        """Detect conflicts in concurrent field editing."""
        # Check if another user is currently editing the same field
        if workflow_id not in self.active_sessions:
            return None

        conflict_threshold = timedelta(seconds=30)  # Conflict if edited within 30 seconds
        current_time = datetime.now(tz=timezone.utc)

        # Check for recent edits by other users
        for other_user_id, presence in self.active_sessions[workflow_id].items():
            if (other_user_id != user_id and 
                presence.current_step == step_id and
                presence.is_editing and
                current_time - presence.last_activity < conflict_threshold):
                
                # Create conflict record
                from ..models import db
                from uuid_extensions import uuid7str

                conflict = ConflictResolution(
                    id=uuid7str(),
                    workflow_state_id=workflow_id,
                    step_id=step_id,
                    field_name=field_name,
                    conflict_type='concurrent_edit',
                    user1_id=user_id,
                    user2_id=other_user_id,
                    user1_value=str(field_value),
                    user2_value='<unknown>'  # Would need to track field values per user
                )

                db.session.add(conflict)
                db.session.commit()

                return conflict

        return None

    def _update_user_activity(self, workflow_id: str, user_id: str):
        """Update user's last activity timestamp."""
        with _presence_lock:
            if workflow_id in self.active_sessions and user_id in self.active_sessions[workflow_id]:
                self.active_sessions[workflow_id][user_id].last_activity = datetime.now(tz=timezone.utc)

    def _store_event(self, event: CollaborationEvent):
        """Store collaboration event for audit and offline users."""
        # This could store events in database for later retrieval
        # For now, just log the event
        log.info(f"Collaboration event: {event.event_type.value} in workflow {event.workflow_id} by {event.user_name}")

    def _handle_conflict_detection(self, event: CollaborationEvent):
        """Handle conflict detection events."""
        log.warning(f"Conflict detected in workflow {event.workflow_id}: {event.data}")

    def _handle_form_update_conflict_check(self, event: CollaborationEvent):
        """Handle form update events with conflict checking."""
        # Additional conflict checking logic can be added here
        pass

    def cleanup_inactive_sessions(self):
        """Clean up inactive collaboration sessions."""
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=1)  # Clean up after 1 hour of inactivity

        with _presence_lock:
            workflows_to_remove = []
            
            for workflow_id, users in self.active_sessions.items():
                users_to_remove = []
                
                for user_id, presence in users.items():
                    if presence.last_activity < cutoff_time:
                        users_to_remove.append(user_id)
                
                for user_id in users_to_remove:
                    del users[user_id]
                
                if not users:
                    workflows_to_remove.append(workflow_id)
            
            for workflow_id in workflows_to_remove:
                del self.active_sessions[workflow_id]


def get_collaboration_manager() -> WorkflowCollaborationManager:
    """Get the global collaboration manager instance."""
    global _collaboration_manager
    if _collaboration_manager is None:
        socketio = current_app.extensions.get('socketio')
        _collaboration_manager = WorkflowCollaborationManager(socketio)
    return _collaboration_manager


# Flask-SocketIO event handlers
def setup_socketio_handlers(socketio: SocketIO):
    """Setup WebSocket event handlers for collaboration."""

    @socketio.on('join_workflow')
    def handle_join_workflow(data):
        """Handle user joining workflow collaboration."""
        workflow_id = data.get('workflow_id')
        step_id = data.get('step_id')
        
        if not workflow_id:
            return {'error': 'workflow_id required'}

        user_id = str(current_user.id) if current_user.is_authenticated else 'anonymous'
        user_name = current_user.username if current_user.is_authenticated else 'Anonymous'

        manager = get_collaboration_manager()
        manager.join_workflow(workflow_id, user_id, user_name, step_id)

        # Send current active users to the joining user
        active_users = manager.get_active_users(workflow_id)
        emit('active_users_update', {'users': active_users})

    @socketio.on('leave_workflow')
    def handle_leave_workflow(data):
        """Handle user leaving workflow collaboration."""
        workflow_id = data.get('workflow_id')
        
        if not workflow_id:
            return {'error': 'workflow_id required'}

        user_id = str(current_user.id) if current_user.is_authenticated else 'anonymous'
        user_name = current_user.username if current_user.is_authenticated else 'Anonymous'

        manager = get_collaboration_manager()
        manager.leave_workflow(workflow_id, user_id, user_name)

    @socketio.on('update_step')
    def handle_update_step(data):
        """Handle user step updates."""
        workflow_id = data.get('workflow_id')
        step_id = data.get('step_id')
        
        if not workflow_id or not step_id:
            return {'error': 'workflow_id and step_id required'}

        user_id = str(current_user.id) if current_user.is_authenticated else 'anonymous'
        user_name = current_user.username if current_user.is_authenticated else 'Anonymous'

        manager = get_collaboration_manager()
        manager.update_user_step(workflow_id, user_id, user_name, step_id)

    @socketio.on('form_field_update')
    def handle_form_field_update(data):
        """Handle real-time form field updates."""
        workflow_id = data.get('workflow_id')
        step_id = data.get('step_id')
        field_name = data.get('field_name')
        field_value = data.get('field_value')
        
        if not all([workflow_id, step_id, field_name]):
            return {'error': 'workflow_id, step_id, and field_name required'}

        user_id = str(current_user.id) if current_user.is_authenticated else 'anonymous'
        user_name = current_user.username if current_user.is_authenticated else 'Anonymous'

        manager = get_collaboration_manager()
        manager.update_form_data(workflow_id, user_id, user_name, step_id, field_name, field_value)

    @socketio.on('add_comment')
    def handle_add_comment(data):
        """Handle adding comments to workflow steps."""
        workflow_id = data.get('workflow_id')
        step_id = data.get('step_id')
        comment_text = data.get('comment_text')
        comment_type = data.get('comment_type', 'comment')
        
        if not all([workflow_id, step_id, comment_text]):
            return {'error': 'workflow_id, step_id, and comment_text required'}

        user_id = current_user.id if current_user.is_authenticated else None
        user_name = current_user.username if current_user.is_authenticated else 'Anonymous'

        if not user_id:
            return {'error': 'Authentication required'}

        manager = get_collaboration_manager()
        comment_id = manager.add_comment(workflow_id, step_id, user_id, user_name, comment_text, comment_type)
        
        return {'comment_id': comment_id}

    @socketio.on('resolve_conflict')
    def handle_resolve_conflict(data):
        """Handle conflict resolution."""
        conflict_id = data.get('conflict_id')
        resolution_strategy = data.get('resolution_strategy')
        resolved_value = data.get('resolved_value')
        
        if not all([conflict_id, resolution_strategy]):
            return {'error': 'conflict_id and resolution_strategy required'}

        user_id = current_user.id if current_user.is_authenticated else None
        if not user_id:
            return {'error': 'Authentication required'}

        manager = get_collaboration_manager()
        success = manager.resolve_conflict(conflict_id, resolution_strategy, resolved_value, user_id)
        
        return {'success': success}


# Mixin for views to enable collaboration
class CollaborationMixin:
    """
    Mixin to add collaboration capabilities to workflow views.
    """

    def get_collaboration_context(self, workflow_id: str) -> Dict[str, Any]:
        """Get collaboration context for templates."""
        manager = get_collaboration_manager()
        
        return {
            'active_users': manager.get_active_users(workflow_id),
            'workflow_comments': manager.get_workflow_comments(workflow_id),
            'collaboration_enabled': True,
            'websocket_namespace': '/collaboration'
        }

    def join_collaboration_session(self, workflow_id: str, step_id: Optional[str] = None):
        """Join collaboration session for current user."""
        if not current_user.is_authenticated:
            return

        manager = get_collaboration_manager()
        manager.join_workflow(
            workflow_id=workflow_id,
            user_id=str(current_user.id),
            user_name=current_user.username,
            step_id=step_id
        )

    def leave_collaboration_session(self, workflow_id: str):
        """Leave collaboration session for current user."""
        if not current_user.is_authenticated:
            return

        manager = get_collaboration_manager()
        manager.leave_workflow(
            workflow_id=workflow_id,
            user_id=str(current_user.id),
            user_name=current_user.username
        )