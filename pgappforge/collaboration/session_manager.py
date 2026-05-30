"""
Collaboration Session Manager

Manages collaboration sessions, participant tracking, presence indicators,
and session lifecycle with database persistence and Redis caching.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Set, List, Optional, Any
from collections import defaultdict
import json

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from flask import current_app
from sqlalchemy.orm import sessionmaker
from .models import (
    CollaborationSession,
    CollaborationEvent,
    CollaborationPresence,
    CollaborationComment
)

log = logging.getLogger(__name__)


class CollaborationSessionManager:
    """
    Manages collaboration sessions with database persistence and Redis caching.
    
    Provides session lifecycle management, participant tracking, presence indicators,
    and integration with the WebSocket manager for real-time updates.
    """
    
    def __init__(self, db_session, redis_client=None, websocket_manager=None):
        self.db = db_session
        self.redis = redis_client
        self.websocket_manager = websocket_manager
        
        # In-memory caches for performance
        self.active_sessions: Dict[str, CollaborationSession] = {}
        self.session_participants: Dict[str, Set[str]] = defaultdict(set)
        self.user_sessions: Dict[str, Set[str]] = defaultdict(set)
        self.presence_cache: Dict[str, Dict[str, Any]] = {}
        
        # Configuration
        self.session_timeout = timedelta(hours=24)  # Sessions expire after 24 hours
        self.presence_timeout = timedelta(minutes=5)  # Presence expires after 5 minutes
        
        log.info("Collaboration session manager initialized")
        
    def create_collaboration_session(self, model_name: str, record_id: Optional[str],
                                   user_id: int, permissions: List[str] = None) -> str:
        """
        Create a new collaboration session.
        
        :param model_name: Name of the model being collaborated on
        :param record_id: ID of the specific record (None for new records)
        :param user_id: ID of the user creating the session
        :param permissions: List of permissions for the session
        :return: Session ID
        """
        try:
            session_id = str(uuid.uuid4())
            
            # Create database record
            collab_session = CollaborationSession(
                session_id=session_id,
                model_name=model_name,
                record_id=record_id,
                created_by=user_id,
                status='active',
                settings={
                    'permissions': permissions or ['can_edit'],
                    'created_by': user_id
                },
                participants=[user_id]
            )
            
            self.db.add(collab_session)
            self.db.commit()
            
            # Cache session data
            self.active_sessions[session_id] = collab_session
            self.session_participants[session_id].add(str(user_id))
            self.user_sessions[str(user_id)].add(session_id)
            
            # Store in Redis for multi-server access
            if self.redis:
                session_data = {
                    'session_id': session_id,
                    'model_name': model_name,
                    'record_id': record_id or '',
                    'created_by': str(user_id),
                    'created_at': datetime.now(tz=timezone.utc).isoformat(),
                    'participants': [str(user_id)],
                    'status': 'active'
                }
                self.redis.hset(f"collab:session:{session_id}", mapping=session_data)
                self.redis.expire(f"collab:session:{session_id}", int(self.session_timeout.total_seconds()))
                
            log.info(f"Created collaboration session {session_id} for {model_name}:{record_id} by user {user_id}")
            return session_id
            
        except Exception as e:
            log.error(f"Error creating collaboration session: {e}")
            self.db.rollback()
            raise
            
    def join_collaboration_session(self, session_id: str, user_id: int) -> bool:
        """
        Join an existing collaboration session.
        
        :param session_id: ID of the session to join
        :param user_id: ID of the user joining
        :return: True if successfully joined
        """
        try:
            # Get session from cache or database
            session = self._get_session(session_id)
            if not session or session.status != 'active':
                log.warning(f"Cannot join inactive or non-existent session: {session_id}")
                return False
                
            # Add participant if not already present
            if not session.is_participant(user_id):
                session.add_participant(user_id)
                self.db.commit()
                
            # Update caches
            self.session_participants[session_id].add(str(user_id))
            self.user_sessions[str(user_id)].add(session_id)
            
            # Update Redis
            if self.redis:
                self.redis.sadd(f"collab:session:{session_id}:participants", str(user_id))
                
            # Create presence record
            self._update_presence(session_id, user_id, 'active')
            
            # Log event
            self._log_event(session_id, 'user_joined', user_id, metadata={
                'username': self._get_username(user_id)
            })
            
            # Notify WebSocket room
            if self.websocket_manager:
                room_id = f"collaboration_{session.model_name}_{session.record_id or 'new'}"
                self.websocket_manager.broadcast_to_room(room_id, 'participant_joined', {
                    'user_id': user_id,
                    'username': self._get_username(user_id),
                    'session_id': session_id,
                    'timestamp': datetime.now(tz=timezone.utc).isoformat()
                })
                
            log.info(f"User {user_id} joined collaboration session {session_id}")
            return True
            
        except Exception as e:
            log.error(f"Error joining collaboration session: {e}")
            return False
            
    def leave_collaboration_session(self, session_id: str, user_id: int):
        """
        Leave a collaboration session.
        
        :param session_id: ID of the session to leave
        :param user_id: ID of the user leaving
        """
        try:
            session = self._get_session(session_id)
            if not session:
                return
                
            # Remove from participant list
            session.remove_participant(user_id)
            self.db.commit()
            
            # Update caches
            self.session_participants[session_id].discard(str(user_id))
            self.user_sessions[str(user_id)].discard(session_id)
            
            # Update Redis
            if self.redis:
                self.redis.srem(f"collab:session:{session_id}:participants", str(user_id))
                
            # Remove presence
            self._remove_presence(session_id, user_id)
            
            # Log event
            self._log_event(session_id, 'user_left', user_id)
            
            # Check if session should be archived (no active participants)
            if not self.session_participants[session_id]:
                self._archive_session(session_id)
                
            log.info(f"User {user_id} left collaboration session {session_id}")
            
        except Exception as e:
            log.error(f"Error leaving collaboration session: {e}")
            
    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a collaboration session.
        
        :param session_id: Session ID
        :return: Session information dictionary or None
        """
        try:
            session = self._get_session(session_id)
            if not session:
                return None
                
            participants = []
            for user_id in session.participants or []:
                user_info = {
                    'user_id': user_id,
                    'username': self._get_username(user_id),
                    'online': self._is_user_online(user_id),
                    'presence': self._get_presence(session_id, user_id)
                }
                participants.append(user_info)
                
            return {
                'session_id': session_id,
                'model_name': session.model_name,
                'record_id': session.record_id,
                'created_by': session.created_by,
                'created_at': session.created_at.isoformat(),
                'status': session.status,
                'participants': participants,
                'participant_count': len(participants),
                'settings': session.settings or {}
            }
            
        except Exception as e:
            log.error(f"Error getting session info: {e}")
            return None
            
    def update_presence(self, session_id: str, user_id: int, field_name: str = None,
                       cursor_position: int = None, status: str = 'active') -> bool:
        """
        Update user presence in a collaboration session.
        
        :param session_id: Session ID
        :param user_id: User ID
        :param field_name: Current field being edited
        :param cursor_position: Cursor position within field
        :param status: Presence status (active, away, typing, etc.)
        :return: True if updated successfully
        """
        return self._update_presence(session_id, user_id, status, field_name, cursor_position)
        
    def get_session_participants(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get list of participants in a collaboration session.
        
        :param session_id: Session ID
        :return: List of participant information
        """
        try:
            session = self._get_session(session_id)
            if not session:
                return []
                
            participants = []
            for user_id in session.participants or []:
                presence = self._get_presence(session_id, user_id)
                participant_info = {
                    'user_id': user_id,
                    'username': self._get_username(user_id),
                    'online': self._is_user_online(user_id),
                    'status': presence.get('status', 'inactive'),
                    'current_field': presence.get('current_field'),
                    'last_activity': presence.get('last_activity')
                }
                participants.append(participant_info)
                
            return participants
            
        except Exception as e:
            log.error(f"Error getting session participants: {e}")
            return []
            
    def find_sessions_for_record(self, model_name: str, record_id: str) -> List[str]:
        """
        Find active collaboration sessions for a specific record.
        
        :param model_name: Model name
        :param record_id: Record ID
        :return: List of active session IDs
        """
        try:
            sessions = self.db.query(CollaborationSession).filter(
                CollaborationSession.model_name == model_name,
                CollaborationSession.record_id == record_id,
                CollaborationSession.status == 'active'
            ).all()
            
            return [session.session_id for session in sessions]
            
        except Exception as e:
            log.error(f"Error finding sessions for record: {e}")
            return []
            
    def cleanup_expired_sessions(self):
        """Clean up expired and inactive sessions"""
        try:
            cutoff_time = datetime.now(tz=timezone.utc) - self.session_timeout
            
            # Find expired sessions
            expired_sessions = self.db.query(CollaborationSession).filter(
                CollaborationSession.updated_at < cutoff_time,
                CollaborationSession.status == 'active'
            ).all()
            
            for session in expired_sessions:
                self._archive_session(session.session_id)
                
            log.info(f"Cleaned up {len(expired_sessions)} expired collaboration sessions")
            
        except Exception as e:
            log.error(f"Error cleaning up expired sessions: {e}")
            
    def _get_session(self, session_id: str) -> Optional[CollaborationSession]:
        """Get session from cache or database"""
        try:
            # Check cache first
            if session_id in self.active_sessions:
                return self.active_sessions[session_id]
                
            # Query database
            session = self.db.query(CollaborationSession).filter(
                CollaborationSession.session_id == session_id
            ).first()
            
            if session:
                self.active_sessions[session_id] = session
                
            return session
            
        except Exception as e:
            log.error(f"Error getting session {session_id}: {e}")
            return None
            
    def _update_presence(self, session_id: str, user_id: int, status: str,
                        field_name: str = None, cursor_position: int = None) -> bool:
        """Update user presence information"""
        try:
            # Update or create presence record
            presence = self.db.query(CollaborationPresence).filter(
                CollaborationPresence.session_id == session_id,
                CollaborationPresence.user_id == user_id
            ).first()
            
            if not presence:
                presence = CollaborationPresence(
                    session_id=session_id,
                    user_id=user_id
                )
                self.db.add(presence)
                
            presence.status = status
            presence.current_field = field_name
            presence.cursor_position = cursor_position
            presence.update_activity()
            
            self.db.commit()
            
            # Update cache
            presence_key = f"{session_id}:{user_id}"
            self.presence_cache[presence_key] = {
                'status': status,
                'current_field': field_name,
                'cursor_position': cursor_position,
                'last_activity': presence.last_activity.isoformat()
            }
            
            # Update Redis
            if self.redis:
                presence_data = self.presence_cache[presence_key]
                self.redis.hset(f"collab:presence:{session_id}:{user_id}", mapping=presence_data)
                self.redis.expire(f"collab:presence:{session_id}:{user_id}", 
                                int(self.presence_timeout.total_seconds()))
                
            return True
            
        except Exception as e:
            log.error(f"Error updating presence: {e}")
            return False
            
    def _get_presence(self, session_id: str, user_id: int) -> Dict[str, Any]:
        """Get user presence information"""
        try:
            presence_key = f"{session_id}:{user_id}"
            
            # Check cache first
            if presence_key in self.presence_cache:
                return self.presence_cache[presence_key]
                
            # Check Redis
            if self.redis:
                presence_data = self.redis.hgetall(f"collab:presence:{session_id}:{user_id}")
                if presence_data:
                    self.presence_cache[presence_key] = presence_data
                    return presence_data
                    
            # Query database
            presence = self.db.query(CollaborationPresence).filter(
                CollaborationPresence.session_id == session_id,
                CollaborationPresence.user_id == user_id
            ).first()
            
            if presence:
                presence_data = {
                    'status': presence.status,
                    'current_field': presence.current_field,
                    'cursor_position': presence.cursor_position,
                    'last_activity': presence.last_activity.isoformat()
                }
                self.presence_cache[presence_key] = presence_data
                return presence_data
                
            return {}
            
        except Exception as e:
            log.error(f"Error getting presence: {e}")
            return {}
            
    def _remove_presence(self, session_id: str, user_id: int):
        """Remove user presence information"""
        try:
            # Remove from database
            self.db.query(CollaborationPresence).filter(
                CollaborationPresence.session_id == session_id,
                CollaborationPresence.user_id == user_id
            ).delete()
            self.db.commit()
            
            # Remove from cache
            presence_key = f"{session_id}:{user_id}"
            self.presence_cache.pop(presence_key, None)
            
            # Remove from Redis
            if self.redis:
                self.redis.delete(f"collab:presence:{session_id}:{user_id}")
                
        except Exception as e:
            log.error(f"Error removing presence: {e}")
            
    def _archive_session(self, session_id: str):
        """Archive an inactive session"""
        try:
            session = self._get_session(session_id)
            if session:
                session.status = 'archived'
                self.db.commit()
                
                # Clean up caches
                self.active_sessions.pop(session_id, None)
                self.session_participants.pop(session_id, None)
                
                # Clean up Redis
                if self.redis:
                    self.redis.delete(f"collab:session:{session_id}")
                    self.redis.delete(f"collab:session:{session_id}:participants")
                    
                log.info(f"Archived collaboration session {session_id}")
                
        except Exception as e:
            log.error(f"Error archiving session: {e}")
            
    def _log_event(self, session_id: str, event_type: str, user_id: int,
                   field_name: str = None, old_value: Any = None, 
                   new_value: Any = None, metadata: Dict[str, Any] = None):
        """Log collaboration event"""
        try:
            session = self._get_session(session_id)
            if not session:
                return
                
            event = CollaborationEvent(
                session_id=session_id,
                event_type=event_type,
                user_id=user_id,
                model_name=session.model_name,
                record_id=session.record_id,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                metadata=metadata or {}
            )
            
            self.db.add(event)
            self.db.commit()
            
        except Exception as e:
            log.error(f"Error logging event: {e}")
            
    def _is_user_online(self, user_id: int) -> bool:
        """Check if user is currently online"""
        if self.websocket_manager:
            return self.websocket_manager.is_user_online(str(user_id))
        return False
        
    def _get_username(self, user_id: int) -> str:
        """Get username from user ID"""
        # This would integrate with PgForge's user system
        return f"User{user_id}"  # Placeholder


class MockSessionManager:
    """Mock session manager for testing or when Redis is unavailable"""
    
    def __init__(self, db_session, redis_client=None, websocket_manager=None):
        self.db = db_session
        log.warning("Using mock session manager - limited functionality")
        
    def create_collaboration_session(self, model_name: str, record_id: Optional[str],
                                   user_id: int, permissions: List[str] = None) -> str:
        return str(uuid.uuid4())
        
    def join_collaboration_session(self, session_id: str, user_id: int) -> bool:
        return True
        
    def leave_collaboration_session(self, session_id: str, user_id: int):
        pass
        
    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        return None
        
    def update_presence(self, session_id: str, user_id: int, field_name: str = None,
                       cursor_position: int = None, status: str = 'active') -> bool:
        return True
        
    def get_session_participants(self, session_id: str) -> List[Dict[str, Any]]:
        return []
        
    def find_sessions_for_record(self, model_name: str, record_id: str) -> List[str]:
        return []
        
    def cleanup_expired_sessions(self):
        pass