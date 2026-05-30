"""
Collaboration Security Integration

Integrates the real-time collaboration system with Flask-AppBuilder's security framework,
ensuring proper permission checks, role-based access control, and secure collaboration sessions.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from flask import g, session, request
from flask_appbuilder.security.manager import BaseSecurityManager
from flask_appbuilder.models.sqla import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

log = logging.getLogger(__name__)

# Collaboration-specific permissions
COLLABORATION_PERMISSIONS = [
    ('can_collaborate', 'Collaboration'),
    ('can_create_session', 'Collaboration'),
    ('can_join_session', 'Collaboration'),
    ('can_moderate_session', 'Collaboration'),
    ('can_view_participants', 'Collaboration'),
    ('can_comment', 'Collaboration'),
    ('can_resolve_conflicts', 'Collaboration'),
    ('can_admin_collaboration', 'Collaboration'),
]

# Default collaboration roles
COLLABORATION_ROLES = {
    'Collaboration User': [
        'can_collaborate',
        'can_join_session',
        'can_comment',
        'can_view_participants'
    ],
    'Collaboration Moderator': [
        'can_collaborate',
        'can_create_session',
        'can_join_session',
        'can_moderate_session',
        'can_view_participants',
        'can_comment',
        'can_resolve_conflicts'
    ],
    'Collaboration Admin': [
        'can_collaborate',
        'can_create_session',
        'can_join_session',
        'can_moderate_session',
        'can_view_participants',
        'can_comment',
        'can_resolve_conflicts',
        'can_admin_collaboration'
    ]
}


class CollaborationSecuritySession(Base):
    """Database model for collaboration sessions with security metadata"""
    
    __tablename__ = 'collaboration_session'
    
    id = Column(String(36), primary_key=True)
    model_name = Column(String(100), nullable=False)
    record_id = Column(String(50))  # Optional for new records
    created_by = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    created_at = Column(DateTime, default=func.now())
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    max_participants = Column(Integer, default=10)
    permissions_required = Column(Text)  # JSON list of required permissions
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    participants = relationship("CollaborationParticipant", back_populates="session", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<CollaborationSecuritySession {self.id}>'


class CollaborationParticipant(Base):
    """Database model for collaboration session participants"""
    
    __tablename__ = 'collaboration_participant'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(36), ForeignKey('collaboration_session.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    joined_at = Column(DateTime, default=func.now())
    last_active = Column(DateTime, default=func.now())
    role = Column(String(50), default='participant')  # participant, moderator
    permissions = Column(Text)  # JSON list of granted permissions
    
    # Relationships
    session = relationship("CollaborationSecuritySession", back_populates="participants")
    user = relationship("User", foreign_keys=[user_id])
    
    def __repr__(self):
        return f'<CollaborationParticipant {self.user_id}@{self.session_id}>'


class CollaborationSecurityManager:
    """
    Security manager for collaboration features.
    Integrates with Flask-AppBuilder's security system to provide
    permission checking, role validation, and secure session management.
    """
    
    def __init__(self, security_manager: BaseSecurityManager, db_session=None):
        self.security_manager = security_manager
        self.db = db_session
        self.app = security_manager.appbuilder.app if security_manager.appbuilder else None
        
        # Register collaboration permissions
        self._register_collaboration_permissions()
        
    def _register_collaboration_permissions(self):
        """Register collaboration-specific permissions with the security manager"""
        try:
            if not self.security_manager or not hasattr(self.security_manager, 'add_permissions_menu'):
                return
                
            # Add collaboration permissions
            for permission_name, menu_name in COLLABORATION_PERMISSIONS:
                try:
                    self.security_manager.add_permissions_menu(menu_name)
                    self.security_manager.add_permission(permission_name)
                    log.debug(f"Registered collaboration permission: {permission_name}")
                except Exception as e:
                    log.warning(f"Failed to register permission {permission_name}: {e}")
                    
        except Exception as e:
            log.error(f"Error registering collaboration permissions: {e}")
    
    def create_default_roles(self):
        """Create default collaboration roles if they don't exist"""
        try:
            if not self.security_manager:
                return
                
            for role_name, permissions in COLLABORATION_ROLES.items():
                role = self.security_manager.find_role(role_name)
                
                if not role:
                    # Create role
                    role = self.security_manager.add_role(role_name)
                    log.info(f"Created collaboration role: {role_name}")
                
                if role:
                    # Add permissions to role
                    for permission_name in permissions:
                        try:
                            perm = self.security_manager.find_permission(permission_name)
                            if perm and perm not in role.permissions:
                                role.permissions.append(perm)
                                log.debug(f"Added permission {permission_name} to role {role_name}")
                        except Exception as e:
                            log.warning(f"Failed to add permission {permission_name} to role {role_name}: {e}")
                    
                    self.db.session.commit()
                    
        except Exception as e:
            log.error(f"Error creating default collaboration roles: {e}")
    
    def check_collaboration_permission(self, permission_name: str, user_id: int = None) -> bool:
        """Check if current user (or specific user) has collaboration permission"""
        try:
            if user_id:
                user = self.security_manager.get_user_by_id(user_id)
            else:
                user = g.user if hasattr(g, 'user') else None
                
            if not user:
                return False
                
            # Check permission
            return self.security_manager.has_access(permission_name, 'Collaboration', user)
            
        except Exception as e:
            log.error(f"Error checking collaboration permission {permission_name}: {e}")
            return False
    
    def can_create_session(self, model_name: str, record_id: str = None, user_id: int = None) -> bool:
        """Check if user can create a collaboration session for the given model/record"""
        try:
            # Basic permission check
            if not self.check_collaboration_permission('can_create_session', user_id):
                return False
            
            # Additional model-specific checks could be added here
            # For example, checking if user has edit permission on the specific model
            user = self.security_manager.get_user_by_id(user_id) if user_id else g.user
            if not user:
                return False
                
            # Check if user has access to edit the specific model
            # This would integrate with the model view permissions
            return True
            
        except Exception as e:
            log.error(f"Error checking session creation permission: {e}")
            return False
    
    def can_join_session(self, session_id: str, user_id: int = None) -> bool:
        """Check if user can join a specific collaboration session"""
        try:
            # Basic permission check
            if not self.check_collaboration_permission('can_join_session', user_id):
                return False
            
            # Get session details
            session_obj = self.db.session.query(CollaborationSecuritySession).filter_by(
                id=session_id, is_active=True
            ).first()
            
            if not session_obj:
                return False
                
            # Check if session has expired
            from datetime import datetime, timezone
            if session_obj.expires_at and session_obj.expires_at < datetime.now(tz=timezone.utc):
                return False
            
            # Check maximum participants
            current_participants = len(session_obj.participants)
            if current_participants >= session_obj.max_participants:
                # Check if user is already a participant
                user_id = user_id or (g.user.id if hasattr(g, 'user') and g.user else None)
                if user_id:
                    existing_participant = next((p for p in session_obj.participants if p.user_id == user_id), None)
                    if not existing_participant:
                        return False
            
            # Check session-specific permissions if configured
            if session_obj.permissions_required:
                try:
                    import json
                    required_perms = json.loads(session_obj.permissions_required)
                    for perm in required_perms:
                        if not self.check_collaboration_permission(perm, user_id):
                            return False
                except Exception as e:
                    log.warning(f"Error checking session permissions: {e}")
            
            return True
            
        except Exception as e:
            log.error(f"Error checking session join permission: {e}")
            return False
    
    def can_moderate_session(self, session_id: str, user_id: int = None) -> bool:
        """Check if user can moderate a specific collaboration session"""
        try:
            # Check basic moderation permission
            if not self.check_collaboration_permission('can_moderate_session', user_id):
                return False
            
            # Get session details
            session_obj = self.db.session.query(CollaborationSecuritySession).filter_by(
                id=session_id, is_active=True
            ).first()
            
            if not session_obj:
                return False
                
            user_id = user_id or (g.user.id if hasattr(g, 'user') and g.user else None)
            if not user_id:
                return False
            
            # Session creator can always moderate
            if session_obj.created_by == user_id:
                return True
            
            # Check if user is a participant with moderator role
            participant = next((p for p in session_obj.participants 
                              if p.user_id == user_id and p.role == 'moderator'), None)
            
            return participant is not None
            
        except Exception as e:
            log.error(f"Error checking session moderation permission: {e}")
            return False
    
    def get_user_collaboration_info(self, user_id: int = None) -> Dict[str, Any]:
        """Get collaboration-relevant information for a user"""
        try:
            user_id = user_id or (g.user.id if hasattr(g, 'user') and g.user else None)
            if not user_id:
                return {}
            
            user = self.security_manager.get_user_by_id(user_id)
            if not user:
                return {}
            
            # Get user permissions
            permissions = []
            for perm_name, _ in COLLABORATION_PERMISSIONS:
                if self.check_collaboration_permission(perm_name, user_id):
                    permissions.append(perm_name)
            
            # Get active sessions
            active_sessions = []
            if self.db:
                try:
                    sessions = self.db.session.query(CollaborationParticipant).filter_by(
                        user_id=user_id
                    ).join(CollaborationSecuritySession).filter(
                        CollaborationSecuritySession.is_active == True
                    ).all()
                    
                    active_sessions = [p.session_id for p in sessions]
                except Exception as e:
                    log.warning(f"Error getting active sessions: {e}")
            
            return {
                'user_id': user_id,
                'username': user.username,
                'display_name': f"{user.first_name} {user.last_name}".strip() or user.username,
                'email': getattr(user, 'email', ''),
                'avatar_url': getattr(user, 'avatar_url', '/static/appbuilder/img/default-avatar.png'),
                'permissions': permissions,
                'active_sessions': active_sessions,
                'can_collaborate': 'can_collaborate' in permissions,
                'can_create_session': 'can_create_session' in permissions,
                'can_moderate': 'can_moderate_session' in permissions
            }
            
        except Exception as e:
            log.error(f"Error getting user collaboration info: {e}")
            return {}
    
    def create_secure_session(self, model_name: str, record_id: str = None, 
                            permissions_required: List[str] = None, 
                            max_participants: int = 10) -> Optional[str]:
        """Create a new collaboration session with security validation"""
        try:
            # Check permissions
            if not self.can_create_session(model_name, record_id):
                log.warning("User lacks permission to create collaboration session")
                return None
            
            user_id = g.user.id if hasattr(g, 'user') and g.user else None
            if not user_id:
                log.warning("No authenticated user for session creation")
                return None
            
            # Generate session ID
            import uuid
            session_id = str(uuid.uuid4())
            
            # Calculate expiration (default 4 hours from now)
            from datetime import datetime, timedelta
            expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=4)
            
            # Create session record
            import json
            session_obj = CollaborationSecuritySession(
                id=session_id,
                model_name=model_name,
                record_id=record_id,
                created_by=user_id,
                expires_at=expires_at,
                max_participants=max_participants,
                permissions_required=json.dumps(permissions_required) if permissions_required else None
            )
            
            self.db.session.add(session_obj)
            
            # Add creator as first participant with moderator role
            participant = CollaborationParticipant(
                session_id=session_id,
                user_id=user_id,
                role='moderator',
                permissions=json.dumps(['can_moderate_session', 'can_resolve_conflicts'])
            )
            
            self.db.session.add(participant)
            self.db.session.commit()
            
            log.info(f"Created secure collaboration session {session_id} for model {model_name}")
            return session_id
            
        except Exception as e:
            log.error(f"Error creating secure collaboration session: {e}")
            self.db.session.rollback()
            return None
    
    def validate_session_access(self, session_id: str, user_id: int = None) -> Dict[str, Any]:
        """Validate and return session access information for a user"""
        try:
            user_id = user_id or (g.user.id if hasattr(g, 'user') and g.user else None)
            
            result = {
                'can_join': False,
                'can_moderate': False,
                'session_info': None,
                'user_role': None,
                'permissions': []
            }
            
            if not user_id:
                return result
            
            # Check basic access
            if not self.can_join_session(session_id, user_id):
                return result
            
            # Get session details
            session_obj = self.db.session.query(CollaborationSecuritySession).filter_by(
                id=session_id, is_active=True
            ).first()
            
            if not session_obj:
                return result
            
            result['can_join'] = True
            result['can_moderate'] = self.can_moderate_session(session_id, user_id)
            
            # Get or create participant record
            participant = next((p for p in session_obj.participants if p.user_id == user_id), None)
            if not participant:
                # Create new participant
                import json
                participant = CollaborationParticipant(
                    session_id=session_id,
                    user_id=user_id,
                    role='participant',
                    permissions=json.dumps(['can_collaborate', 'can_comment'])
                )
                self.db.session.add(participant)
                self.db.session.commit()
            
            result['user_role'] = participant.role
            
            # Get permissions
            try:
                import json
                if participant.permissions:
                    result['permissions'] = json.loads(participant.permissions)
            except Exception:
                result['permissions'] = ['can_collaborate']
            
            # Session info
            result['session_info'] = {
                'id': session_obj.id,
                'model_name': session_obj.model_name,
                'record_id': session_obj.record_id,
                'created_at': session_obj.created_at.isoformat() if session_obj.created_at else None,
                'expires_at': session_obj.expires_at.isoformat() if session_obj.expires_at else None,
                'max_participants': session_obj.max_participants,
                'current_participants': len(session_obj.participants)
            }
            
            return result
            
        except Exception as e:
            log.error(f"Error validating session access: {e}")
            return {'can_join': False, 'can_moderate': False}
    
    def cleanup_expired_sessions(self):
        """Clean up expired collaboration sessions"""
        try:
            from datetime import datetime
            
            expired_sessions = self.db.session.query(CollaborationSecuritySession).filter(
                CollaborationSecuritySession.expires_at < datetime.now(tz=timezone.utc),
                CollaborationSecuritySession.is_active == True
            ).all()
            
            for session_obj in expired_sessions:
                session_obj.is_active = False
                log.info(f"Marked session {session_obj.id} as expired")
            
            self.db.session.commit()
            
            return len(expired_sessions)
            
        except Exception as e:
            log.error(f"Error cleaning up expired sessions: {e}")
            return 0
    
    def get_session_security_context(self, session_id: str) -> Dict[str, Any]:
        """Get security context for a collaboration session"""
        try:
            session_obj = self.db.session.query(CollaborationSecuritySession).filter_by(
                id=session_id, is_active=True
            ).first()
            
            if not session_obj:
                return {}
            
            # Get all participants with their permissions
            participants = []
            for participant in session_obj.participants:
                try:
                    import json
                    participant_permissions = json.loads(participant.permissions) if participant.permissions else []
                except Exception:
                    participant_permissions = []
                
                participants.append({
                    'user_id': participant.user_id,
                    'username': participant.user.username if participant.user else 'Unknown',
                    'role': participant.role,
                    'permissions': participant_permissions,
                    'joined_at': participant.joined_at.isoformat() if participant.joined_at else None,
                    'last_active': participant.last_active.isoformat() if participant.last_active else None
                })
            
            return {
                'session_id': session_id,
                'model_name': session_obj.model_name,
                'record_id': session_obj.record_id,
                'created_by': session_obj.created_by,
                'creator_username': session_obj.creator.username if session_obj.creator else 'Unknown',
                'participants': participants,
                'total_participants': len(participants),
                'max_participants': session_obj.max_participants,
                'created_at': session_obj.created_at.isoformat() if session_obj.created_at else None,
                'expires_at': session_obj.expires_at.isoformat() if session_obj.expires_at else None
            }
            
        except Exception as e:
            log.error(f"Error getting session security context: {e}")
            return {}