"""
Real-time Collaboration and Sharing System

Provides advanced collaboration features for wizard forms including
real-time editing, sharing, commenting, and version control.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class CollaborationPermission(Enum):
    """Permission levels for wizard collaboration"""
    VIEW = "view"
    COMMENT = "comment"
    EDIT = "edit"
    ADMIN = "admin"
    OWNER = "owner"


class ShareScope(Enum):
    """Scope of wizard sharing"""
    PRIVATE = "private"
    TEAM = "team"
    ORGANIZATION = "organization"
    PUBLIC = "public"
    LINK_SHARING = "link_sharing"


class ActivityType(Enum):
    """Types of collaborative activities"""
    WIZARD_CREATED = "wizard_created"
    WIZARD_UPDATED = "wizard_updated"
    WIZARD_SHARED = "wizard_shared"
    WIZARD_PUBLISHED = "wizard_published"
    STEP_ADDED = "step_added"
    STEP_REMOVED = "step_removed"
    STEP_MODIFIED = "step_modified"
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    FIELD_MODIFIED = "field_modified"
    COMMENT_ADDED = "comment_added"
    COMMENT_REPLIED = "comment_replied"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    VERSION_CREATED = "version_created"
    VERSION_RESTORED = "version_restored"


@dataclass
class CollaborationUser:
    """User information for collaboration"""
    user_id: str
    name: str
    email: str
    avatar_url: Optional[str] = None
    last_active: Optional[datetime] = None
    is_online: bool = False
    current_step: Optional[str] = None
    cursor_position: Optional[Dict[str, Any]] = None


@dataclass
class WizardPermission:
    """Permission entry for wizard access"""
    user_id: str
    permission: CollaborationPermission
    granted_by: str
    granted_at: datetime
    expires_at: Optional[datetime] = None


@dataclass
class WizardComment:
    """Comment on wizard elements"""
    comment_id: str
    wizard_id: str
    user_id: str
    content: str
    created_at: datetime
    step_id: Optional[str] = None
    field_id: Optional[str] = None
    position: Optional[Dict[str, Any]] = None  # For UI positioning
    resolved: bool = False
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    replies: List['WizardComment'] = None
    reactions: Dict[str, List[str]] = None  # emoji -> [user_ids]
    
    def __post_init__(self):
        if self.replies is None:
            self.replies = []
        if self.reactions is None:
            self.reactions = {}


@dataclass
class WizardVersion:
    """Version snapshot of a wizard"""
    version_id: str
    wizard_id: str
    version_number: int
    created_by: str
    created_at: datetime
    description: str
    configuration: Dict[str, Any]
    changes_summary: List[str]
    is_published: bool = False
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class CollaborationActivity:
    """Activity in the collaboration system"""
    activity_id: str
    wizard_id: str
    user_id: str
    activity_type: ActivityType
    timestamp: datetime
    description: str
    details: Dict[str, Any]
    affected_users: List[str] = None
    
    def __post_init__(self):
        if self.affected_users is None:
            self.affected_users = []


@dataclass
class WizardShare:
    """Sharing configuration for a wizard"""
    share_id: str
    wizard_id: str
    created_by: str
    created_at: datetime
    scope: ShareScope
    permissions: CollaborationPermission
    access_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    password_protected: bool = False
    password_hash: Optional[str] = None
    max_uses: Optional[int] = None
    current_uses: int = 0
    allowed_domains: List[str] = None
    
    def __post_init__(self):
        if self.allowed_domains is None:
            self.allowed_domains = []


class WizardCollaborationManager:
    """Manages real-time collaboration for wizard forms"""
    
    def __init__(self):
        """
        Initialize the wizard collaboration manager with empty storage dictionaries.
        
        Sets up in-memory storage for:
        - Active user sessions per wizard
        - User location tracking
        - Permission assignments
        - Comments and replies
        - Version history
        - Activity logs
        - Share configurations
        - Collaboration settings
        
        In production, these would typically be backed by persistent storage.
        """
        self.active_sessions: Dict[str, Set[str]] = {}  # wizard_id -> set of user_ids
        self.user_locations: Dict[str, Dict[str, Any]] = {}  # session_id -> location info
        self.permissions: Dict[str, List[WizardPermission]] = {}  # wizard_id -> permissions
        self.comments: Dict[str, List[WizardComment]] = {}  # wizard_id -> comments
        self.versions: Dict[str, List[WizardVersion]] = {}  # wizard_id -> versions
        self.activities: Dict[str, List[CollaborationActivity]] = {}  # wizard_id -> activities
        self.shares: Dict[str, WizardShare] = {}  # share_id -> share config
        self.collaboration_settings: Dict[str, Dict[str, Any]] = {}  # wizard_id -> settings
    
    # Session Management
    def join_session(self, wizard_id: str, user_id: str, session_id: str) -> Dict[str, Any]:
        """User joins a collaborative editing session"""
        if wizard_id not in self.active_sessions:
            self.active_sessions[wizard_id] = set()
        
        self.active_sessions[wizard_id].add(user_id)
        
        self.user_locations[session_id] = {
            'wizard_id': wizard_id,
            'user_id': user_id,
            'joined_at': datetime.now(tz=timezone.utc),
            'last_activity': datetime.now(tz=timezone.utc),
            'current_step': None,
            'cursor_position': None
        }
        
        # Log activity
        self._log_activity(
            wizard_id, user_id, ActivityType.USER_JOINED,
            f"User joined the collaborative session",
            {'session_id': session_id}
        )
        
        # Get current collaboration state
        return self.get_collaboration_state(wizard_id, user_id)
    
    def leave_session(self, session_id: str) -> bool:
        """User leaves a collaborative editing session"""
        if session_id not in self.user_locations:
            return False
        
        location_info = self.user_locations[session_id]
        wizard_id = location_info['wizard_id']
        user_id = location_info['user_id']
        
        # Remove from active sessions
        if wizard_id in self.active_sessions:
            self.active_sessions[wizard_id].discard(user_id)
        
        # Remove location tracking
        del self.user_locations[session_id]
        
        # Log activity
        self._log_activity(
            wizard_id, user_id, ActivityType.USER_LEFT,
            f"User left the collaborative session",
            {'session_id': session_id}
        )
        
        return True
    
    def update_user_location(self, session_id: str, step_id: Optional[str] = None, 
                           field_id: Optional[str] = None, cursor_position: Optional[Dict] = None):
        """Update user's current location in the wizard"""
        if session_id in self.user_locations:
            self.user_locations[session_id].update({
                'current_step': step_id,
                'current_field': field_id,
                'cursor_position': cursor_position,
                'last_activity': datetime.now(tz=timezone.utc)
            })
    
    def get_active_users(self, wizard_id: str) -> List[CollaborationUser]:
        """Get list of currently active users for a wizard"""
        active_user_ids = self.active_sessions.get(wizard_id, set())
        
        users = []
        for session_id, location_info in self.user_locations.items():
            if (location_info['wizard_id'] == wizard_id and 
                location_info['user_id'] in active_user_ids):
                
                # In a real implementation, would fetch user details from database
                users.append(CollaborationUser(
                    user_id=location_info['user_id'],
                    name=f"User {location_info['user_id'][:8]}",
                    email=f"user{location_info['user_id'][:4]}@example.com",
                    last_active=location_info['last_activity'],
                    is_online=True,
                    current_step=location_info.get('current_step'),
                    cursor_position=location_info.get('cursor_position')
                ))
        
        return users
    
    # Permission Management
    def grant_permission(self, wizard_id: str, user_id: str, permission: CollaborationPermission,
                        granted_by: str, expires_at: Optional[datetime] = None) -> bool:
        """Grant permission to a user for a wizard"""
        if wizard_id not in self.permissions:
            self.permissions[wizard_id] = []
        
        # Remove existing permission for this user
        self.permissions[wizard_id] = [
            p for p in self.permissions[wizard_id] if p.user_id != user_id
        ]
        
        # Add new permission
        new_permission = WizardPermission(
            user_id=user_id,
            permission=permission,
            granted_by=granted_by,
            granted_at=datetime.now(tz=timezone.utc),
            expires_at=expires_at
        )
        
        self.permissions[wizard_id].append(new_permission)
        
        # Log activity
        self._log_activity(
            wizard_id, granted_by, ActivityType.WIZARD_SHARED,
            f"Granted {permission.value} permission to user {user_id}",
            {'target_user': user_id, 'permission': permission.value}
        )
        
        return True
    
    def revoke_permission(self, wizard_id: str, user_id: str, revoked_by: str) -> bool:
        """Revoke user's permission for a wizard"""
        if wizard_id not in self.permissions:
            return False
        
        original_count = len(self.permissions[wizard_id])
        self.permissions[wizard_id] = [
            p for p in self.permissions[wizard_id] if p.user_id != user_id
        ]
        
        if len(self.permissions[wizard_id]) < original_count:
            self._log_activity(
                wizard_id, revoked_by, ActivityType.WIZARD_SHARED,
                f"Revoked permission from user {user_id}",
                {'target_user': user_id}
            )
            return True
        
        return False
    
    def get_user_permission(self, wizard_id: str, user_id: str) -> Optional[CollaborationPermission]:
        """Get user's permission level for a wizard"""
        if wizard_id not in self.permissions:
            return None
        
        for permission in self.permissions[wizard_id]:
            if permission.user_id == user_id:
                # Check if permission has expired
                if permission.expires_at and datetime.now(tz=timezone.utc) > permission.expires_at:
                    return None
                return permission.permission
        
        return None
    
    def has_permission(self, wizard_id: str, user_id: str, 
                      required_permission: CollaborationPermission) -> bool:
        """Check if user has required permission level"""
        user_permission = self.get_user_permission(wizard_id, user_id)
        if not user_permission:
            return False
        
        # Permission hierarchy
        permission_levels = {
            CollaborationPermission.VIEW: 0,
            CollaborationPermission.COMMENT: 1,
            CollaborationPermission.EDIT: 2,
            CollaborationPermission.ADMIN: 3,
            CollaborationPermission.OWNER: 4
        }
        
        return permission_levels[user_permission] >= permission_levels[required_permission]
    
    # Comment System
    def add_comment(self, wizard_id: str, user_id: str, content: str,
                   step_id: Optional[str] = None, field_id: Optional[str] = None,
                   position: Optional[Dict[str, Any]] = None) -> str:
        """Add a comment to a wizard element"""
        if not self.has_permission(wizard_id, user_id, CollaborationPermission.COMMENT):
            raise PermissionError("User does not have permission to comment")
        
        comment_id = str(uuid.uuid4())
        comment = WizardComment(
            comment_id=comment_id,
            wizard_id=wizard_id,
            user_id=user_id,
            content=content,
            created_at=datetime.now(tz=timezone.utc),
            step_id=step_id,
            field_id=field_id,
            position=position
        )
        
        if wizard_id not in self.comments:
            self.comments[wizard_id] = []
        
        self.comments[wizard_id].append(comment)
        
        # Log activity
        self._log_activity(
            wizard_id, user_id, ActivityType.COMMENT_ADDED,
            f"Added comment: {content[:50]}...",
            {
                'comment_id': comment_id,
                'step_id': step_id,
                'field_id': field_id
            }
        )
        
        return comment_id
    
    def reply_to_comment(self, comment_id: str, user_id: str, content: str) -> str:
        """Reply to an existing comment"""
        # Find the original comment
        original_comment = None
        wizard_id = None
        
        for wid, comments in self.comments.items():
            for comment in comments:
                if comment.comment_id == comment_id:
                    original_comment = comment
                    wizard_id = wid
                    break
            if original_comment:
                break
        
        if not original_comment or not wizard_id:
            raise ValueError("Comment not found")
        
        if not self.has_permission(wizard_id, user_id, CollaborationPermission.COMMENT):
            raise PermissionError("User does not have permission to comment")
        
        reply_id = str(uuid.uuid4())
        reply = WizardComment(
            comment_id=reply_id,
            wizard_id=wizard_id,
            user_id=user_id,
            content=content,
            created_at=datetime.now(tz=timezone.utc)
        )
        
        original_comment.replies.append(reply)
        
        # Log activity
        self._log_activity(
            wizard_id, user_id, ActivityType.COMMENT_REPLIED,
            f"Replied to comment: {content[:50]}...",
            {
                'original_comment_id': comment_id,
                'reply_id': reply_id
            }
        )
        
        return reply_id
    
    def resolve_comment(self, comment_id: str, user_id: str) -> bool:
        """Mark a comment as resolved"""
        for wizard_id, comments in self.comments.items():
            for comment in comments:
                if comment.comment_id == comment_id:
                    if not self.has_permission(wizard_id, user_id, CollaborationPermission.EDIT):
                        return False
                    
                    comment.resolved = True
                    comment.resolved_by = user_id
                    comment.resolved_at = datetime.now(tz=timezone.utc)
                    return True
        
        return False
    
    def add_reaction(self, comment_id: str, user_id: str, emoji: str) -> bool:
        """Add a reaction to a comment"""
        for comments in self.comments.values():
            for comment in comments:
                if comment.comment_id == comment_id:
                    if emoji not in comment.reactions:
                        comment.reactions[emoji] = []
                    if user_id not in comment.reactions[emoji]:
                        comment.reactions[emoji].append(user_id)
                    return True
        
        return False
    
    def get_comments(self, wizard_id: str, step_id: Optional[str] = None,
                    field_id: Optional[str] = None) -> List[WizardComment]:
        """Get comments for wizard, optionally filtered by step/field"""
        if wizard_id not in self.comments:
            return []
        
        comments = self.comments[wizard_id]
        
        if step_id:
            comments = [c for c in comments if c.step_id == step_id]
        
        if field_id:
            comments = [c for c in comments if c.field_id == field_id]
        
        return comments
    
    # Version Control
    def create_version(self, wizard_id: str, user_id: str, description: str,
                      configuration: Dict[str, Any], changes_summary: List[str],
                      tags: List[str] = None) -> str:
        """Create a new version of the wizard"""
        if not self.has_permission(wizard_id, user_id, CollaborationPermission.EDIT):
            raise PermissionError("User does not have permission to create versions")
        
        if wizard_id not in self.versions:
            self.versions[wizard_id] = []
        
        version_number = len(self.versions[wizard_id]) + 1
        version_id = str(uuid.uuid4())
        
        version = WizardVersion(
            version_id=version_id,
            wizard_id=wizard_id,
            version_number=version_number,
            created_by=user_id,
            created_at=datetime.now(tz=timezone.utc),
            description=description,
            configuration=configuration,
            changes_summary=changes_summary,
            tags=tags or []
        )
        
        self.versions[wizard_id].append(version)
        
        # Log activity
        self._log_activity(
            wizard_id, user_id, ActivityType.VERSION_CREATED,
            f"Created version {version_number}: {description}",
            {
                'version_id': version_id,
                'version_number': version_number,
                'changes_count': len(changes_summary)
            }
        )
        
        return version_id
    
    def restore_version(self, version_id: str, user_id: str) -> Dict[str, Any]:
        """Restore a wizard to a specific version"""
        # Find the version
        for wizard_id, versions in self.versions.items():
            for version in versions:
                if version.version_id == version_id:
                    if not self.has_permission(wizard_id, user_id, CollaborationPermission.ADMIN):
                        raise PermissionError("User does not have permission to restore versions")
                    
                    # Log activity
                    self._log_activity(
                        wizard_id, user_id, ActivityType.VERSION_RESTORED,
                        f"Restored to version {version.version_number}: {version.description}",
                        {
                            'version_id': version_id,
                            'version_number': version.version_number
                        }
                    )
                    
                    return version.configuration
        
        raise ValueError("Version not found")
    
    def get_versions(self, wizard_id: str) -> List[WizardVersion]:
        """Get all versions for a wizard"""
        return self.versions.get(wizard_id, [])
    
    def compare_versions(self, version_id_1: str, version_id_2: str) -> Dict[str, Any]:
        """Compare two versions and return differences"""
        # Implement version comparison using diff algorithm
        try:
            version_1 = None
            version_2 = None
            
            # Get version data
            for version in self.version_history.get('versions', []):
                if version['version_id'] == version_id_1:
                    version_1 = version
                elif version['version_id'] == version_id_2:
                    version_2 = version
            
            if not version_1 or not version_2:
                return {
                    'added': [],
                    'modified': [],
                    'removed': [],
                    'summary': "One or both versions not found",
                    'error': True
                }
            
            # Compare the versions
            added = []
            modified = []
            removed = []
            
            config_1 = version_1.get('config', {})
            config_2 = version_2.get('config', {})
            
            # Compare steps
            steps_1 = {step.get('id'): step for step in config_1.get('steps', [])}
            steps_2 = {step.get('id'): step for step in config_2.get('steps', [])}
            
            # Find added steps
            for step_id in steps_2:
                if step_id not in steps_1:
                    added.append({
                        'type': 'step',
                        'id': step_id,
                        'name': steps_2[step_id].get('title', 'Untitled Step')
                    })
            
            # Find removed steps
            for step_id in steps_1:
                if step_id not in steps_2:
                    removed.append({
                        'type': 'step',
                        'id': step_id,
                        'name': steps_1[step_id].get('title', 'Untitled Step')
                    })
            
            # Find modified steps
            for step_id in steps_1:
                if step_id in steps_2:
                    if steps_1[step_id] != steps_2[step_id]:
                        modified.append({
                            'type': 'step',
                            'id': step_id,
                            'name': steps_2[step_id].get('title', 'Untitled Step'),
                            'changes': self._get_step_changes(steps_1[step_id], steps_2[step_id])
                        })
            
            # Compare other properties
            if config_1.get('title') != config_2.get('title'):
                modified.append({
                    'type': 'title',
                    'old_value': config_1.get('title'),
                    'new_value': config_2.get('title')
                })
            
            if config_1.get('theme') != config_2.get('theme'):
                modified.append({
                    'type': 'theme',
                    'old_value': config_1.get('theme'),
                    'new_value': config_2.get('theme')
                })
            
            total_changes = len(added) + len(modified) + len(removed)
            
            return {
                'added': added,
                'modified': modified,
                'removed': removed,
                'summary': f"Found {total_changes} changes between versions",
                'version_1': version_1.get('timestamp'),
                'version_2': version_2.get('timestamp'),
                'total_changes': total_changes
            }
            
        except Exception as e:
            logger.error(f"Error comparing versions: {e}")
            return {
                'added': [],
                'modified': [],
                'removed': [],
                'summary': f"Error during comparison: {str(e)}",
                'error': True
            }
    
    def _get_step_changes(self, step_1: Dict[str, Any], step_2: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get detailed changes between two steps"""
        changes = []
        
        if step_1.get('title') != step_2.get('title'):
            changes.append({
                'property': 'title',
                'old_value': step_1.get('title'),
                'new_value': step_2.get('title')
            })
        
        # Compare fields
        fields_1 = {field.get('id'): field for field in step_1.get('fields', [])}
        fields_2 = {field.get('id'): field for field in step_2.get('fields', [])}
        
        # Added fields
        for field_id in fields_2:
            if field_id not in fields_1:
                changes.append({
                    'property': 'field_added',
                    'field_id': field_id,
                    'field_label': fields_2[field_id].get('label')
                })
        
        # Removed fields
        for field_id in fields_1:
            if field_id not in fields_2:
                changes.append({
                    'property': 'field_removed',
                    'field_id': field_id,
                    'field_label': fields_1[field_id].get('label')
                })
        
        # Modified fields
        for field_id in fields_1:
            if field_id in fields_2 and fields_1[field_id] != fields_2[field_id]:
                changes.append({
                    'property': 'field_modified',
                    'field_id': field_id,
                    'field_label': fields_2[field_id].get('label')
                })
        
        return changes
    
    # Sharing
    def create_share(self, wizard_id: str, user_id: str, scope: ShareScope,
                    permissions: CollaborationPermission,
                    expires_at: Optional[datetime] = None,
                    password: Optional[str] = None,
                    max_uses: Optional[int] = None,
                    allowed_domains: List[str] = None) -> str:
        """Create a shareable link for a wizard"""
        if not self.has_permission(wizard_id, user_id, CollaborationPermission.ADMIN):
            raise PermissionError("User does not have permission to create shares")
        
        share_id = str(uuid.uuid4())
        access_token = str(uuid.uuid4()) if scope == ShareScope.LINK_SHARING else None
        
        share = WizardShare(
            share_id=share_id,
            wizard_id=wizard_id,
            created_by=user_id,
            created_at=datetime.now(tz=timezone.utc),
            scope=scope,
            permissions=permissions,
            access_token=access_token,
            expires_at=expires_at,
            password_protected=password is not None,
            password_hash=self._hash_password(password) if password else None,
            max_uses=max_uses,
            allowed_domains=allowed_domains or []
        )
        
        self.shares[share_id] = share
        
        return share_id
    
    def access_shared_wizard(self, share_id: str, user_id: Optional[str] = None,
                           password: Optional[str] = None) -> Dict[str, Any]:
        """Access a shared wizard"""
        if share_id not in self.shares:
            raise ValueError("Share not found")
        
        share = self.shares[share_id]
        
        # Check if expired
        if share.expires_at and datetime.now(tz=timezone.utc) > share.expires_at:
            raise ValueError("Share link has expired")
        
        # Check max uses
        if share.max_uses and share.current_uses >= share.max_uses:
            raise ValueError("Share link has reached maximum usage limit")
        
        # Check password
        if share.password_protected:
            if not password or not self._verify_password(password, share.password_hash):
                raise ValueError("Invalid password")
        
        # Increment usage counter
        share.current_uses += 1
        
        return {
            'wizard_id': share.wizard_id,
            'permissions': share.permissions.value,
            'share_info': {
                'created_by': share.created_by,
                'created_at': share.created_at.isoformat(),
                'scope': share.scope.value
            }
        }
    
    # Activity and History
    def _log_activity(self, wizard_id: str, user_id: str, activity_type: ActivityType,
                     description: str, details: Dict[str, Any]):
        """Log an activity"""
        if wizard_id not in self.activities:
            self.activities[wizard_id] = []
        
        activity = CollaborationActivity(
            activity_id=str(uuid.uuid4()),
            wizard_id=wizard_id,
            user_id=user_id,
            activity_type=activity_type,
            timestamp=datetime.now(tz=timezone.utc),
            description=description,
            details=details
        )
        
        self.activities[wizard_id].append(activity)
        
        # Keep only last 1000 activities
        if len(self.activities[wizard_id]) > 1000:
            self.activities[wizard_id] = self.activities[wizard_id][-1000:]
    
    def get_activities(self, wizard_id: str, limit: int = 50,
                      activity_types: List[ActivityType] = None) -> List[CollaborationActivity]:
        """Get recent activities for a wizard"""
        if wizard_id not in self.activities:
            return []
        
        activities = self.activities[wizard_id]
        
        if activity_types:
            activities = [a for a in activities if a.activity_type in activity_types]
        
        return sorted(activities, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    def get_collaboration_state(self, wizard_id: str, user_id: str) -> Dict[str, Any]:
        """Get current collaboration state for a wizard"""
        return {
            'active_users': [asdict(u) for u in self.get_active_users(wizard_id)],
            'user_permission': self.get_user_permission(wizard_id, user_id).value if self.get_user_permission(wizard_id, user_id) else None,
            'comments': [asdict(c) for c in self.get_comments(wizard_id)],
            'recent_activities': [asdict(a) for a in self.get_activities(wizard_id, 20)],
            'versions_count': len(self.get_versions(wizard_id)),
            'collaboration_enabled': wizard_id in self.collaboration_settings
        }
    
    def _hash_password(self, password: str) -> str:
        """Hash a password (simplified)"""
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash"""
        return self._hash_password(password) == password_hash


# Global collaboration manager
wizard_collaboration = WizardCollaborationManager()