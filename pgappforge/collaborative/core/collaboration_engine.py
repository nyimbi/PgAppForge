"""
Collaboration Engine

Core orchestration engine for real-time collaborative features in PgAppForge.
Manages collaborative sessions, user presence, event coordination, and integration
with PgAppForge's security and database systems.
"""

import asyncio
import json
import uuid
from typing import Dict, List, Any, Optional, Set, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging
from collections import defaultdict
import weakref

from flask import Flask, g, request, session
from pgappforge import AppBuilder
from pgappforge.security import BaseSecurityManager
from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class CollaborativeEventType(Enum):
    """Types of collaborative events"""

    USER_JOIN = "user_join"
    USER_LEAVE = "user_leave"
    USER_ACTIVITY = "user_activity"
    DATA_CHANGE = "data_change"
    CURSOR_MOVE = "cursor_move"
    SELECTION_CHANGE = "selection_change"
    FORM_EDIT = "form_edit"
    VIEW_CHANGE = "view_change"
    COMMENT_ADD = "comment_add"
    MESSAGE_SEND = "message_send"
    LOCK_ACQUIRE = "lock_acquire"
    LOCK_RELEASE = "lock_release"


class UserPresenceStatus(Enum):
    """User presence status"""

    ONLINE = "online"
    AWAY = "away"
    BUSY = "busy"
    OFFLINE = "offline"


@dataclass
class CollaborativeUser:
    """Collaborative user information"""

    user_id: int
    username: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: UserPresenceStatus = UserPresenceStatus.ONLINE
    last_activity: datetime = field(default_factory=datetime.now)
    current_workspace: Optional[str] = None
    current_view: Optional[str] = None
    permissions: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CollaborativeEvent:
    """Collaborative event data structure"""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: CollaborativeEventType = CollaborativeEventType.USER_ACTIVITY
    user_id: int = 0
    workspace_id: str = ""
    resource_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CollaborativeSession:
    """Collaborative session management"""

    session_id: str
    workspace_id: str
    users: Dict[int, CollaborativeUser] = field(default_factory=dict)
    active_resources: Set[str] = field(default_factory=set)
    resource_locks: Dict[str, int] = field(
        default_factory=dict
    )  # resource_id -> user_id
    event_history: List[CollaborativeEvent] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)


class CollaborationEngine:
    """
    Core collaboration engine for PgAppForge.

    Features:
    - Real-time user presence and activity tracking
    - Event-driven collaborative actions
    - Resource locking and conflict resolution
    - Integration with PgAppForge security
    - Scalable session management
    - Extensible event system
    """

    def __init__(self, app_builder: AppBuilder):
        self.app_builder = app_builder
        self.app = app_builder.app
        self.security_manager = app_builder.sm

        # Core collaborative state
        self.active_sessions: Dict[str, CollaborativeSession] = {}
        self.user_sessions: Dict[int, Set[str]] = defaultdict(
            set
        )  # user_id -> session_ids
        self.workspace_sessions: Dict[str, Set[str]] = defaultdict(
            set
        )  # workspace_id -> session_ids

        # Event system
        self.event_handlers: Dict[CollaborativeEventType, List[Callable]] = defaultdict(
            list
        )
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self.event_processor_task: Optional[asyncio.Task] = None

        # Configuration
        self.config = {
            "session_timeout": timedelta(hours=24),
            "activity_timeout": timedelta(minutes=30),
            "max_event_history": 1000,
            "enable_presence": True,
            "enable_locking": True,
            "lock_timeout": timedelta(minutes=15),
            "event_batch_size": 50,
        }

        # Integration hooks
        self._setup_flask_integration()
        self._setup_security_integration()
        self._setup_database_integration()

        # Start background tasks
        self._start_background_tasks()

    def _setup_flask_integration(self) -> None:
        """Setup Flask request/response integration"""

        @self.app.before_request
        def before_request():
            """Track user activity on each request"""
            if hasattr(g, "user") and g.user and g.user.is_authenticated:
                self._update_user_activity(g.user.id)

        @self.app.after_request
        def after_request(response):
            """Process any pending collaborative events"""
            # Flush any pending events for this request
            if hasattr(g, "collaborative_events"):
                for event in g.collaborative_events:
                    asyncio.create_task(self.emit_event(event))
            return response

    def _setup_security_integration(self) -> None:
        """Setup integration with PgAppForge security"""

        # Hook into login/logout events
        if hasattr(self.security_manager, "oauth_user_info"):
            original_oauth = self.security_manager.oauth_user_info

            def wrapped_oauth_user_info(*args, **kwargs):
                result = original_oauth(*args, **kwargs)
                if result and hasattr(g, "user") and g.user:
                    self._handle_user_login(g.user)
                return result

            self.security_manager.oauth_user_info = wrapped_oauth

    def _setup_database_integration(self) -> None:
        """Setup database event integration for collaborative features"""

        @event.listens_for(Session, "after_commit")
        def after_commit(session):
            """Track database changes for collaborative features"""
            if hasattr(g, "user") and g.user and g.user.is_authenticated:
                # Emit data change events for modified objects
                for obj in session.dirty:
                    if hasattr(obj, "__collaborative_tracked__"):
                        self._emit_data_change_event(g.user.id, obj)

    def _start_background_tasks(self) -> None:
        """Start background tasks for collaborative features"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Start event processor
        self.event_processor_task = loop.create_task(self._process_events())

        # Schedule cleanup tasks
        loop.create_task(self._periodic_cleanup())

    async def create_session(self, workspace_id: str, user: Any) -> str:
        """
        Create a new collaborative session.

        Args:
            workspace_id: Unique identifier for the workspace
            user: PgAppForge user object

        Returns:
            Session ID for the collaborative session
        """
        session_id = str(uuid.uuid4())

        collaborative_user = CollaborativeUser(
            user_id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name or user.username,
            current_workspace=workspace_id,
            permissions=set(self._get_user_permissions(user)),
        )

        session = CollaborativeSession(
            session_id=session_id,
            workspace_id=workspace_id,
            users={user.id: collaborative_user},
        )

        # Store session references
        self.active_sessions[session_id] = session
        self.user_sessions[user.id].add(session_id)
        self.workspace_sessions[workspace_id].add(session_id)

        # Emit user join event
        await self.emit_event(
            CollaborativeEvent(
                event_type=CollaborativeEventType.USER_JOIN,
                user_id=user.id,
                workspace_id=workspace_id,
                data={
                    "session_id": session_id,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "full_name": collaborative_user.full_name,
                    },
                },
            )
        )

        logger.info(
            f"Created collaborative session {session_id} for user {user.username} in workspace {workspace_id}"
        )
        return session_id

    async def join_session(self, session_id: str, user: Any) -> bool:
        """
        Join an existing collaborative session.

        Args:
            session_id: Session to join
            user: PgAppForge user object

        Returns:
            True if successfully joined, False otherwise
        """
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        # Check if user has permission to join this workspace
        if not self._can_access_workspace(user, session.workspace_id):
            return False

        collaborative_user = CollaborativeUser(
            user_id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name or user.username,
            current_workspace=session.workspace_id,
            permissions=set(self._get_user_permissions(user)),
        )

        # Add user to session
        session.users[user.id] = collaborative_user
        self.user_sessions[user.id].add(session_id)
        session.last_activity = datetime.now()

        # Emit user join event
        await self.emit_event(
            CollaborativeEvent(
                event_type=CollaborativeEventType.USER_JOIN,
                user_id=user.id,
                workspace_id=session.workspace_id,
                data={
                    "session_id": session_id,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "full_name": collaborative_user.full_name,
                    },
                },
            )
        )

        logger.info(f"User {user.username} joined collaborative session {session_id}")
        return True

    async def leave_session(self, session_id: str, user_id: int) -> bool:
        """
        Leave a collaborative session.

        Args:
            session_id: Session to leave
            user_id: User leaving the session

        Returns:
            True if successfully left, False otherwise
        """
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        if user_id not in session.users:
            return False

        user = session.users[user_id]

        # Release any locks held by this user
        await self._release_user_locks(session_id, user_id)

        # Remove user from session
        del session.users[user_id]
        self.user_sessions[user_id].discard(session_id)

        # Emit user leave event
        await self.emit_event(
            CollaborativeEvent(
                event_type=CollaborativeEventType.USER_LEAVE,
                user_id=user_id,
                workspace_id=session.workspace_id,
                data={
                    "session_id": session_id,
                    "user": {"id": user_id, "username": user.username},
                },
            )
        )

        # Clean up empty session
        if not session.users:
            await self._cleanup_session(session_id)

        logger.info(f"User {user_id} left collaborative session {session_id}")
        return True

    async def emit_event(self, event: CollaborativeEvent) -> None:
        """
        Emit a collaborative event to all relevant users.

        Args:
            event: Event to emit
        """
        # Add to event queue for processing
        await self.event_queue.put(event)

    async def acquire_lock(
        self, session_id: str, user_id: int, resource_id: str
    ) -> bool:
        """
        Acquire a lock on a resource for collaborative editing.

        Args:
            session_id: Session ID
            user_id: User requesting the lock
            resource_id: Resource to lock

        Returns:
            True if lock acquired, False otherwise
        """
        if not self.config["enable_locking"]:
            return True

        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        # Check if resource is already locked
        if resource_id in session.resource_locks:
            current_holder = session.resource_locks[resource_id]
            if current_holder != user_id:
                return False

        # Acquire lock
        session.resource_locks[resource_id] = user_id
        session.active_resources.add(resource_id)

        # Emit lock event
        await self.emit_event(
            CollaborativeEvent(
                event_type=CollaborativeEventType.LOCK_ACQUIRE,
                user_id=user_id,
                workspace_id=session.workspace_id,
                resource_id=resource_id,
                data={
                    "session_id": session_id,
                    "resource_id": resource_id,
                    "locked_by": user_id,
                },
            )
        )

        logger.debug(
            f"User {user_id} acquired lock on {resource_id} in session {session_id}"
        )
        return True

    async def release_lock(
        self, session_id: str, user_id: int, resource_id: str
    ) -> bool:
        """
        Release a lock on a resource.

        Args:
            session_id: Session ID
            user_id: User releasing the lock
            resource_id: Resource to unlock

        Returns:
            True if lock released, False otherwise
        """
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        # Check if user holds the lock
        if resource_id not in session.resource_locks:
            return False

        if session.resource_locks[resource_id] != user_id:
            return False

        # Release lock
        del session.resource_locks[resource_id]
        session.active_resources.discard(resource_id)

        # Emit unlock event
        await self.emit_event(
            CollaborativeEvent(
                event_type=CollaborativeEventType.LOCK_RELEASE,
                user_id=user_id,
                workspace_id=session.workspace_id,
                resource_id=resource_id,
                data={
                    "session_id": session_id,
                    "resource_id": resource_id,
                    "released_by": user_id,
                },
            )
        )

        logger.debug(
            f"User {user_id} released lock on {resource_id} in session {session_id}"
        )
        return True

    def register_event_handler(
        self, event_type: CollaborativeEventType, handler: Callable
    ) -> None:
        """
        Register an event handler for collaborative events.

        Args:
            event_type: Type of event to handle
            handler: Async function to handle the event
        """
        self.event_handlers[event_type].append(handler)
        logger.debug(f"Registered handler for {event_type}")

    def get_session_users(self, session_id: str) -> List[CollaborativeUser]:
        """Get all users in a collaborative session"""
        if session_id not in self.active_sessions:
            return []

        return list(self.active_sessions[session_id].users.values())

    def get_user_sessions(self, user_id: int) -> List[str]:
        """Get all sessions a user is participating in"""
        return list(self.user_sessions[user_id])

    def get_workspace_sessions(self, workspace_id: str) -> List[str]:
        """Get all sessions in a workspace"""
        return list(self.workspace_sessions[workspace_id])

    def is_resource_locked(
        self, session_id: str, resource_id: str
    ) -> tuple[bool, Optional[int]]:
        """
        Check if a resource is locked.

        Returns:
            (is_locked, user_id_holding_lock)
        """
        if session_id not in self.active_sessions:
            return False, None

        session = self.active_sessions[session_id]
        if resource_id in session.resource_locks:
            return True, session.resource_locks[resource_id]

        return False, None

    async def _process_events(self) -> None:
        """Background task to process collaborative events"""
        while True:
            try:
                # Process events in batches for efficiency
                events = []
                try:
                    # Get first event (blocking)
                    event = await self.event_queue.get()
                    events.append(event)

                    # Get additional events (non-blocking)
                    for _ in range(self.config["event_batch_size"] - 1):
                        try:
                            event = self.event_queue.get_nowait()
                            events.append(event)
                        except asyncio.QueueEmpty:
                            break

                except asyncio.QueueEmpty:
                    continue

                # Process batch of events
                for event in events:
                    await self._handle_event(event)

            except Exception as e:
                logger.error(f"Error processing collaborative events: {e}")
                await asyncio.sleep(1)  # Prevent tight error loop

    async def _handle_event(self, event: CollaborativeEvent) -> None:
        """Handle a single collaborative event"""
        try:
            # Store event in session history
            if event.workspace_id:
                for session_id in self.workspace_sessions[event.workspace_id]:
                    if session_id in self.active_sessions:
                        session = self.active_sessions[session_id]
                        session.event_history.append(event)

                        # Trim history if too long
                        if (
                            len(session.event_history)
                            > self.config["max_event_history"]
                        ):
                            session.event_history = session.event_history[
                                -self.config["max_event_history"] :
                            ]

            # Call registered handlers
            handlers = self.event_handlers.get(event.event_type, [])
            for handler in handlers:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"Error in event handler for {event.event_type}: {e}")

        except Exception as e:
            logger.error(f"Error handling event {event.event_id}: {e}")

    async def _periodic_cleanup(self) -> None:
        """Periodic cleanup of inactive sessions and expired locks"""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                current_time = datetime.now()
                inactive_sessions = []

                # Find inactive sessions
                for session_id, session in self.active_sessions.items():
                    if (current_time - session.last_activity) > self.config[
                        "session_timeout"
                    ]:
                        inactive_sessions.append(session_id)

                    # Check for expired locks
                    expired_locks = []
                    for resource_id, user_id in session.resource_locks.items():
                        user = session.users.get(user_id)
                        if (
                            user
                            and (current_time - user.last_activity)
                            > self.config["lock_timeout"]
                        ):
                            expired_locks.append(resource_id)

                    # Release expired locks
                    for resource_id in expired_locks:
                        await self.release_lock(
                            session_id, session.resource_locks[resource_id], resource_id
                        )

                # Clean up inactive sessions
                for session_id in inactive_sessions:
                    await self._cleanup_session(session_id)

                if inactive_sessions:
                    logger.info(
                        f"Cleaned up {len(inactive_sessions)} inactive collaborative sessions"
                    )

            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")

    async def _cleanup_session(self, session_id: str) -> None:
        """Clean up a collaborative session"""
        if session_id not in self.active_sessions:
            return

        session = self.active_sessions[session_id]

        # Remove from all tracking dictionaries
        for user_id in session.users:
            self.user_sessions[user_id].discard(session_id)

        self.workspace_sessions[session.workspace_id].discard(session_id)
        del self.active_sessions[session_id]

        logger.info(f"Cleaned up collaborative session {session_id}")

    async def _release_user_locks(self, session_id: str, user_id: int) -> None:
        """Release all locks held by a user in a session"""
        if session_id not in self.active_sessions:
            return

        session = self.active_sessions[session_id]

        # Find all resources locked by this user
        user_locks = [
            resource_id
            for resource_id, lock_user_id in session.resource_locks.items()
            if lock_user_id == user_id
        ]

        # Release all locks
        for resource_id in user_locks:
            await self.release_lock(session_id, user_id, resource_id)

    def _update_user_activity(self, user_id: int) -> None:
        """Update user activity timestamp"""
        current_time = datetime.now()

        # Update activity in all user sessions
        for session_id in self.user_sessions[user_id]:
            if session_id in self.active_sessions:
                session = self.active_sessions[session_id]
                if user_id in session.users:
                    session.users[user_id].last_activity = current_time
                session.last_activity = current_time

    def _handle_user_login(self, user: Any) -> None:
        """Handle user login for collaborative features"""
        # This can be extended to auto-join workspaces, restore sessions, etc.
        logger.debug(
            f"User {user.username} logged in, collaborative features available"
        )

    def _emit_data_change_event(self, user_id: int, obj: Any) -> None:
        """Emit a data change event for collaborative tracking"""
        # Add event to current request context
        if not hasattr(g, "collaborative_events"):
            g.collaborative_events = []

        event = CollaborativeEvent(
            event_type=CollaborativeEventType.DATA_CHANGE,
            user_id=user_id,
            data={
                "object_type": obj.__class__.__name__,
                "object_id": getattr(obj, "id", None),
                "changes": self._get_object_changes(obj),
            },
        )

        g.collaborative_events.append(event)

    def _get_object_changes(self, obj: Any) -> Dict[str, Any]:
        """Get changes made to a database object"""
        # This would analyze SQLAlchemy object changes
        # For now, return basic information
        return {
            "modified_at": datetime.now().isoformat(),
            "object_type": obj.__class__.__name__,
        }

    def _get_user_permissions(self, user: Any) -> List[str]:
        """Get user permissions for collaborative features"""
        permissions = []

        if hasattr(user, "roles"):
            for role in user.roles:
                if hasattr(role, "permissions"):
                    permissions.extend(
                        [perm.permission.name for perm in role.permissions]
                    )

        return permissions

    def _can_access_workspace(self, user: Any, workspace_id: str) -> bool:
        """Check if user can access a workspace"""
        # Basic permission check - can be extended
        # For now, allow access if user is authenticated
        return user and hasattr(user, "is_authenticated") and user.is_authenticated

    def get_collaboration_stats(self) -> Dict[str, Any]:
        """Get collaboration engine statistics"""
        return {
            "active_sessions": len(self.active_sessions),
            "total_users": sum(
                len(session.users) for session in self.active_sessions.values()
            ),
            "active_workspaces": len(self.workspace_sessions),
            "total_locks": sum(
                len(session.resource_locks) for session in self.active_sessions.values()
            ),
            "event_queue_size": self.event_queue.qsize(),
            "uptime": datetime.now()
            - min(
                [session.created_at for session in self.active_sessions.values()],
                default=datetime.now(),
            ),
        }
