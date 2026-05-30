"""
Collaboration System for Graph Analytics

Provides comprehensive multi-user collaboration capabilities including
real-time sharing, version control, team management, and access control.
"""

import json
import logging
import threading
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union, Set
from dataclasses import dataclass, asdict, field
from enum import Enum
import hashlib
import weakref
from collections import defaultdict

try:
	import redis
	REDIS_AVAILABLE = True
except ImportError:
	REDIS_AVAILABLE = False

import numpy as np
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from .graph_manager import GraphDatabaseManager, get_graph_manager
from .multi_graph_manager import get_graph_registry
from .activity_tracker import track_database_activity, ActivityType
from .performance_optimizer import get_performance_monitor

logger = logging.getLogger(__name__)


class PermissionLevel(Enum):
	"""Permission levels for collaboration"""
	VIEWER = "viewer"
	EDITOR = "editor"
	ADMIN = "admin"
	OWNER = "owner"


class CollaborationType(Enum):
	"""Types of collaborative activities"""
	GRAPH_EDITING = "graph_editing"
	QUERY_SHARING = "query_sharing"
	ANALYSIS_SESSION = "analysis_session"
	ANNOTATION = "annotation"
	REVIEW = "review"


class ChangeType(Enum):
	"""Types of changes in version control"""
	NODE_CREATED = "node_created"
	NODE_UPDATED = "node_updated"
	NODE_DELETED = "node_deleted"
	EDGE_CREATED = "edge_created"
	EDGE_UPDATED = "edge_updated"
	EDGE_DELETED = "edge_deleted"
	PROPERTY_UPDATED = "property_updated"
	ANNOTATION_ADDED = "annotation_added"
	QUERY_SAVED = "query_saved"


class NotificationType(Enum):
	"""Types of collaboration notifications"""
	INVITE_RECEIVED = "invite_received"
	PERMISSION_CHANGED = "permission_changed"
	CONTENT_SHARED = "content_shared"
	COMMENT_ADDED = "comment_added"
	MENTION = "mention"
	REVIEW_REQUEST = "review_request"
	CHANGE_APPROVED = "change_approved"


@dataclass
class CollaborationUser:
	"""
	User information for collaboration
	
	Attributes:
		user_id: Unique user identifier
		username: User display name
		email: User email address
		avatar_url: Profile picture URL
		is_active: Whether user is currently active
		last_seen: Last activity timestamp
		preferences: User collaboration preferences
	"""
	
	user_id: str
	username: str
	email: str = ""
	avatar_url: str = ""
	is_active: bool = True
	last_seen: datetime = field(default_factory=datetime.utcnow)
	preferences: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["last_seen"] = self.last_seen.isoformat()
		return data


@dataclass
class CollaborationPermission:
	"""
	Permission settings for collaborative resources
	
	Attributes:
		resource_id: Resource identifier (graph, query, etc.)
		resource_type: Type of resource
		user_id: User identifier
		permission_level: Permission level
		granted_by: User who granted the permission
		granted_at: When permission was granted
		expires_at: When permission expires (optional)
		metadata: Additional permission metadata
	"""
	
	resource_id: str
	resource_type: str
	user_id: str
	permission_level: PermissionLevel
	granted_by: str
	granted_at: datetime = field(default_factory=datetime.utcnow)
	expires_at: Optional[datetime] = None
	metadata: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["permission_level"] = self.permission_level.value
		data["granted_at"] = self.granted_at.isoformat()
		data["expires_at"] = self.expires_at.isoformat() if self.expires_at else None
		return data
	
	def is_valid(self) -> bool:
		"""Check if permission is still valid"""
		if self.expires_at and datetime.now(tz=timezone.utc) > self.expires_at:
			return False
		return True


@dataclass
class CollaborationSession:
	"""
	Active collaboration session
	
	Tracks real-time collaborative editing sessions with multiple users.
	"""
	
	session_id: str
	resource_id: str
	resource_type: str
	owner_id: str
	participants: List[str] = field(default_factory=list)
	created_at: datetime = field(default_factory=datetime.utcnow)
	last_activity: datetime = field(default_factory=datetime.utcnow)
	session_metadata: Dict[str, Any] = field(default_factory=dict)
	is_active: bool = True
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["created_at"] = self.created_at.isoformat()
		data["last_activity"] = self.last_activity.isoformat()
		return data


@dataclass
class CollaborationChange:
	"""
	Version control change record
	
	Tracks individual changes made during collaboration for version control.
	"""
	
	change_id: str
	session_id: str
	user_id: str
	change_type: ChangeType
	resource_id: str
	change_data: Dict[str, Any]
	timestamp: datetime = field(default_factory=datetime.utcnow)
	is_approved: bool = False
	approved_by: Optional[str] = None
	approved_at: Optional[datetime] = None
	parent_change_id: Optional[str] = None
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["change_type"] = self.change_type.value
		data["timestamp"] = self.timestamp.isoformat()
		data["approved_at"] = self.approved_at.isoformat() if self.approved_at else None
		return data


@dataclass
class CollaborationComment:
	"""
	Comment or annotation on collaborative content
	
	Enables discussion and feedback on graphs, queries, and analyses.
	"""
	
	comment_id: str
	resource_id: str
	resource_type: str
	user_id: str
	content: str
	position: Optional[Dict[str, Any]] = None  # Spatial position for graph annotations
	created_at: datetime = field(default_factory=datetime.utcnow)
	updated_at: Optional[datetime] = None
	parent_comment_id: Optional[str] = None
	mentions: List[str] = field(default_factory=list)
	is_resolved: bool = False
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["created_at"] = self.created_at.isoformat()
		data["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
		return data


@dataclass
class CollaborationNotification:
	"""
	Notification for collaboration events
	
	Manages notifications for invitations, mentions, and other collaborative activities.
	"""
	
	notification_id: str
	user_id: str
	notification_type: NotificationType
	title: str
	message: str
	resource_id: Optional[str] = None
	from_user_id: Optional[str] = None
	created_at: datetime = field(default_factory=datetime.utcnow)
	is_read: bool = False
	read_at: Optional[datetime] = None
	metadata: Dict[str, Any] = field(default_factory=dict)
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		data = asdict(self)
		data["notification_type"] = self.notification_type.value
		data["created_at"] = self.created_at.isoformat()
		data["read_at"] = self.read_at.isoformat() if self.read_at else None
		return data


class RealTimeCollaborationEngine:
	"""
	Real-time collaboration engine
	
	Manages real-time synchronization of changes across multiple users
	using WebSocket connections and change broadcasting.
	"""
	
	def __init__(self):
		self.active_sessions: Dict[str, CollaborationSession] = {}
		self.user_connections: Dict[str, Set[str]] = defaultdict(set)  # user_id -> session_ids
		self.session_participants: Dict[str, Set[str]] = defaultdict(set)  # session_id -> user_ids
		self.change_queue: Dict[str, List[CollaborationChange]] = defaultdict(list)
		self._lock = threading.RLock()
		
		# WebSocket-like event broadcasting (simplified implementation)
		self.event_callbacks: Dict[str, List[callable]] = defaultdict(list)
	
	def create_session(self, resource_id: str, resource_type: str, 
					  owner_id: str, metadata: Dict[str, Any] = None) -> str:
		"""Create new collaboration session"""
		session_id = str(uuid.uuid4())
		
		session = CollaborationSession(
			session_id=session_id,
			resource_id=resource_id,
			resource_type=resource_type,
			owner_id=owner_id,
			participants=[owner_id],
			session_metadata=metadata or {}
		)
		
		with self._lock:
			self.active_sessions[session_id] = session
			self.user_connections[owner_id].add(session_id)
			self.session_participants[session_id].add(owner_id)
		
		logger.info(f"Created collaboration session {session_id} for {resource_type} {resource_id}")
		return session_id
	
	def join_session(self, session_id: str, user_id: str) -> bool:
		"""Join existing collaboration session"""
		with self._lock:
			session = self.active_sessions.get(session_id)
			if not session or not session.is_active:
				return False
			
			if user_id not in session.participants:
				session.participants.append(user_id)
			
			self.user_connections[user_id].add(session_id)
			self.session_participants[session_id].add(user_id)
			session.last_activity = datetime.now(tz=timezone.utc)
		
		# Broadcast join event
		self._broadcast_event(session_id, "user_joined", {
			"user_id": user_id,
			"session_id": session_id
		})
		
		logger.info(f"User {user_id} joined session {session_id}")
		return True
	
	def leave_session(self, session_id: str, user_id: str) -> bool:
		"""Leave collaboration session"""
		with self._lock:
			session = self.active_sessions.get(session_id)
			if not session:
				return False
			
			if user_id in session.participants:
				session.participants.remove(user_id)
			
			self.user_connections[user_id].discard(session_id)
			self.session_participants[session_id].discard(user_id)
			session.last_activity = datetime.now(tz=timezone.utc)
			
			# Close session if no participants left
			if not session.participants:
				session.is_active = False
		
		# Broadcast leave event
		self._broadcast_event(session_id, "user_left", {
			"user_id": user_id,
			"session_id": session_id
		})
		
		logger.info(f"User {user_id} left session {session_id}")
		return True
	
	def record_change(self, session_id: str, user_id: str, change_type: ChangeType,
					 resource_id: str, change_data: Dict[str, Any],
					 parent_change_id: str = None) -> str:
		"""Record a change in the collaboration session"""
		change_id = str(uuid.uuid4())
		
		change = CollaborationChange(
			change_id=change_id,
			session_id=session_id,
			user_id=user_id,
			change_type=change_type,
			resource_id=resource_id,
			change_data=change_data,
			parent_change_id=parent_change_id
		)
		
		with self._lock:
			self.change_queue[session_id].append(change)
			
			# Update session activity
			session = self.active_sessions.get(session_id)
			if session:
				session.last_activity = datetime.now(tz=timezone.utc)
		
		# Broadcast change to all session participants
		self._broadcast_event(session_id, "change_recorded", {
			"change": change.to_dict(),
			"user_id": user_id
		})
		
		return change_id
	
	def get_session_changes(self, session_id: str, since: datetime = None) -> List[CollaborationChange]:
		"""Get changes for a session since a specific time"""
		with self._lock:
			changes = self.change_queue.get(session_id, [])
			if since:
				changes = [c for c in changes if c.timestamp > since]
			return changes.copy()
	
	def broadcast_cursor_position(self, session_id: str, user_id: str, 
								 position: Dict[str, Any]):
		"""Broadcast user cursor position to other participants"""
		self._broadcast_event(session_id, "cursor_moved", {
			"user_id": user_id,
			"position": position
		})
	
	def broadcast_selection(self, session_id: str, user_id: str,
						   selection: Dict[str, Any]):
		"""Broadcast user selection to other participants"""
		self._broadcast_event(session_id, "selection_changed", {
			"user_id": user_id,
			"selection": selection
		})
	
	def _broadcast_event(self, session_id: str, event_type: str, data: Dict[str, Any]):
		"""Broadcast event to all session participants"""
		with self._lock:
			participants = self.session_participants.get(session_id, set())
			
		# Call registered event callbacks
		for callback in self.event_callbacks.get(event_type, []):
			try:
				callback(session_id, participants, data)
			except Exception as e:
				logger.error(f"Error in event callback: {e}")
	
	def register_event_callback(self, event_type: str, callback: callable):
		"""Register callback for collaboration events"""
		self.event_callbacks[event_type].append(callback)
	
	def get_active_sessions(self, user_id: str = None) -> List[CollaborationSession]:
		"""Get active collaboration sessions"""
		with self._lock:
			if user_id:
				user_sessions = self.user_connections.get(user_id, set())
				return [self.active_sessions[sid] for sid in user_sessions 
						if sid in self.active_sessions and self.active_sessions[sid].is_active]
			else:
				return [s for s in self.active_sessions.values() if s.is_active]
	
	def cleanup_inactive_sessions(self, max_idle_hours: int = 24):
		"""Clean up inactive sessions"""
		cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=max_idle_hours)
		
		with self._lock:
			inactive_sessions = []
			for session_id, session in self.active_sessions.items():
				if session.last_activity < cutoff_time:
					inactive_sessions.append(session_id)
			
			for session_id in inactive_sessions:
				session = self.active_sessions[session_id]
				session.is_active = False
				
				# Clean up connections
				for user_id in session.participants:
					self.user_connections[user_id].discard(session_id)
				self.session_participants[session_id].clear()
		
		logger.info(f"Cleaned up {len(inactive_sessions)} inactive sessions")


class PermissionManager:
	"""
	Permission management system
	
	Manages user permissions for collaborative resources with fine-grained
	access control and inheritance.
	"""
	
	def __init__(self):
		self.permissions: Dict[str, List[CollaborationPermission]] = defaultdict(list)  # resource_id -> permissions
		self.user_permissions: Dict[str, List[CollaborationPermission]] = defaultdict(list)  # user_id -> permissions
		self._lock = threading.RLock()
	
	def grant_permission(self, resource_id: str, resource_type: str, user_id: str,
						permission_level: PermissionLevel, granted_by: str,
						expires_at: datetime = None, metadata: Dict[str, Any] = None) -> bool:
		"""Grant permission to user for resource"""
		
		# Check if granting user has sufficient permissions
		if not self.has_permission(resource_id, granted_by, PermissionLevel.ADMIN):
			logger.warning(f"User {granted_by} does not have admin permission to grant access")
			return False
		
		permission = CollaborationPermission(
			resource_id=resource_id,
			resource_type=resource_type,
			user_id=user_id,
			permission_level=permission_level,
			granted_by=granted_by,
			expires_at=expires_at,
			metadata=metadata or {}
		)
		
		with self._lock:
			# Remove any existing permission for this user/resource
			self.permissions[resource_id] = [
				p for p in self.permissions[resource_id] 
				if p.user_id != user_id
			]
			self.user_permissions[user_id] = [
				p for p in self.user_permissions[user_id]
				if p.resource_id != resource_id
			]
			
			# Add new permission
			self.permissions[resource_id].append(permission)
			self.user_permissions[user_id].append(permission)
		
		logger.info(f"Granted {permission_level.value} permission to {user_id} for {resource_id}")
		return True
	
	def revoke_permission(self, resource_id: str, user_id: str, revoked_by: str) -> bool:
		"""Revoke user permission for resource"""
		
		# Check if revoking user has sufficient permissions
		if not self.has_permission(resource_id, revoked_by, PermissionLevel.ADMIN):
			logger.warning(f"User {revoked_by} does not have admin permission to revoke access")
			return False
		
		with self._lock:
			# Remove permissions
			self.permissions[resource_id] = [
				p for p in self.permissions[resource_id] 
				if p.user_id != user_id
			]
			self.user_permissions[user_id] = [
				p for p in self.user_permissions[user_id]
				if p.resource_id != resource_id
			]
		
		logger.info(f"Revoked permission for {user_id} on {resource_id}")
		return True
	
	def has_permission(self, resource_id: str, user_id: str, 
					  required_level: PermissionLevel) -> bool:
		"""Check if user has required permission level for resource"""
		
		permission_hierarchy = {
			PermissionLevel.VIEWER: 1,
			PermissionLevel.EDITOR: 2,
			PermissionLevel.ADMIN: 3,
			PermissionLevel.OWNER: 4
		}
		
		required_level_value = permission_hierarchy.get(required_level, 0)
		
		with self._lock:
			user_perms = self.user_permissions.get(user_id, [])
			for perm in user_perms:
				if perm.resource_id == resource_id and perm.is_valid():
					user_level_value = permission_hierarchy.get(perm.permission_level, 0)
					if user_level_value >= required_level_value:
						return True
		
		return False
	
	def get_user_permissions(self, user_id: str) -> List[CollaborationPermission]:
		"""Get all permissions for a user"""
		with self._lock:
			return [p for p in self.user_permissions.get(user_id, []) if p.is_valid()]
	
	def get_resource_permissions(self, resource_id: str) -> List[CollaborationPermission]:
		"""Get all permissions for a resource"""
		with self._lock:
			return [p for p in self.permissions.get(resource_id, []) if p.is_valid()]
	
	def cleanup_expired_permissions(self):
		"""Remove expired permissions"""
		now = datetime.now(tz=timezone.utc)
		
		with self._lock:
			# Clean up resource permissions
			for resource_id in list(self.permissions.keys()):
				self.permissions[resource_id] = [
					p for p in self.permissions[resource_id]
					if p.is_valid()
				]
				if not self.permissions[resource_id]:
					del self.permissions[resource_id]
			
			# Clean up user permissions
			for user_id in list(self.user_permissions.keys()):
				self.user_permissions[user_id] = [
					p for p in self.user_permissions[user_id]
					if p.is_valid()
				]
				if not self.user_permissions[user_id]:
					del self.user_permissions[user_id]


class CommentSystem:
	"""
	Comment and annotation system
	
	Manages comments, annotations, and discussions on collaborative content.
	"""
	
	def __init__(self):
		self.comments: Dict[str, CollaborationComment] = {}
		self.resource_comments: Dict[str, List[str]] = defaultdict(list)  # resource_id -> comment_ids
		self.user_comments: Dict[str, List[str]] = defaultdict(list)  # user_id -> comment_ids
		self._lock = threading.RLock()
	
	def add_comment(self, resource_id: str, resource_type: str, user_id: str,
				   content: str, position: Dict[str, Any] = None,
				   parent_comment_id: str = None) -> str:
		"""Add comment or annotation"""
		comment_id = str(uuid.uuid4())
		
		# Extract mentions from content
		mentions = self._extract_mentions(content)
		
		comment = CollaborationComment(
			comment_id=comment_id,
			resource_id=resource_id,
			resource_type=resource_type,
			user_id=user_id,
			content=content,
			position=position,
			parent_comment_id=parent_comment_id,
			mentions=mentions
		)
		
		with self._lock:
			self.comments[comment_id] = comment
			self.resource_comments[resource_id].append(comment_id)
			self.user_comments[user_id].append(comment_id)
		
		logger.info(f"Added comment {comment_id} by {user_id} on {resource_id}")
		return comment_id
	
	def update_comment(self, comment_id: str, user_id: str, content: str) -> bool:
		"""Update existing comment"""
		with self._lock:
			comment = self.comments.get(comment_id)
			if not comment or comment.user_id != user_id:
				return False
			
			comment.content = content
			comment.updated_at = datetime.now(tz=timezone.utc)
			comment.mentions = self._extract_mentions(content)
		
		return True
	
	def resolve_comment(self, comment_id: str, user_id: str) -> bool:
		"""Mark comment as resolved"""
		with self._lock:
			comment = self.comments.get(comment_id)
			if not comment:
				return False
			
			comment.is_resolved = True
		
		return True
	
	def get_resource_comments(self, resource_id: str, include_resolved: bool = True) -> List[CollaborationComment]:
		"""Get all comments for a resource"""
		with self._lock:
			comment_ids = self.resource_comments.get(resource_id, [])
			comments = [self.comments[cid] for cid in comment_ids if cid in self.comments]
			
			if not include_resolved:
				comments = [c for c in comments if not c.is_resolved]
			
			return sorted(comments, key=lambda c: c.created_at)
	
	def get_user_comments(self, user_id: str) -> List[CollaborationComment]:
		"""Get all comments by a user"""
		with self._lock:
			comment_ids = self.user_comments.get(user_id, [])
			return [self.comments[cid] for cid in comment_ids if cid in self.comments]
	
	def _extract_mentions(self, content: str) -> List[str]:
		"""Extract @mentions from comment content"""
		import re
		mentions = re.findall(r'@(\w+)', content)
		return list(set(mentions))  # Remove duplicates


class NotificationManager:
	"""
	Notification management system
	
	Manages notifications for collaboration events, mentions, and updates.
	"""
	
	def __init__(self):
		self.notifications: Dict[str, CollaborationNotification] = {}
		self.user_notifications: Dict[str, List[str]] = defaultdict(list)  # user_id -> notification_ids
		self._lock = threading.RLock()
	
	def create_notification(self, user_id: str, notification_type: NotificationType,
						   title: str, message: str, resource_id: str = None,
						   from_user_id: str = None, metadata: Dict[str, Any] = None) -> str:
		"""Create new notification"""
		notification_id = str(uuid.uuid4())
		
		notification = CollaborationNotification(
			notification_id=notification_id,
			user_id=user_id,
			notification_type=notification_type,
			title=title,
			message=message,
			resource_id=resource_id,
			from_user_id=from_user_id,
			metadata=metadata or {}
		)
		
		with self._lock:
			self.notifications[notification_id] = notification
			self.user_notifications[user_id].append(notification_id)
		
		logger.info(f"Created {notification_type.value} notification for {user_id}")
		return notification_id
	
	def mark_as_read(self, notification_id: str, user_id: str) -> bool:
		"""Mark notification as read"""
		with self._lock:
			notification = self.notifications.get(notification_id)
			if not notification or notification.user_id != user_id:
				return False
			
			notification.is_read = True
			notification.read_at = datetime.now(tz=timezone.utc)
		
		return True
	
	def get_user_notifications(self, user_id: str, unread_only: bool = False,
							  limit: int = 50) -> List[CollaborationNotification]:
		"""Get notifications for a user"""
		with self._lock:
			notification_ids = self.user_notifications.get(user_id, [])
			notifications = [self.notifications[nid] for nid in notification_ids if nid in self.notifications]
			
			if unread_only:
				notifications = [n for n in notifications if not n.is_read]
			
			# Sort by creation time (newest first)
			notifications.sort(key=lambda n: n.created_at, reverse=True)
			
			return notifications[:limit]
	
	def get_unread_count(self, user_id: str) -> int:
		"""Get count of unread notifications for user"""
		notifications = self.get_user_notifications(user_id, unread_only=True)
		return len(notifications)


class CollaborationSystem:
	"""
	Main collaboration system coordinator
	
	Integrates all collaboration components including real-time editing,
	permissions, comments, and notifications.
	"""
	
	def __init__(self):
		self.users: Dict[str, CollaborationUser] = {}
		self.realtime_engine = RealTimeCollaborationEngine()
		self.permission_manager = PermissionManager()
		self.comment_system = CommentSystem()
		self.notification_manager = NotificationManager()
		self._lock = threading.RLock()
		
		# Set up event handlers
		self.realtime_engine.register_event_callback("change_recorded", self._on_change_recorded)
		self.realtime_engine.register_event_callback("user_joined", self._on_user_joined)
		
		# Start cleanup thread
		self._start_cleanup_thread()
	
	def register_user(self, user_id: str, username: str, email: str = "",
					 avatar_url: str = "") -> CollaborationUser:
		"""Register user in collaboration system"""
		user = CollaborationUser(
			user_id=user_id,
			username=username,
			email=email,
			avatar_url=avatar_url
		)
		
		with self._lock:
			self.users[user_id] = user
		
		logger.info(f"Registered collaboration user: {username} ({user_id})")
		return user
	
	def start_collaboration(self, resource_id: str, resource_type: str, owner_id: str,
						   collaborator_permissions: Dict[str, PermissionLevel] = None) -> str:
		"""Start new collaboration session"""
		
		# Create collaboration session
		session_id = self.realtime_engine.create_session(resource_id, resource_type, owner_id)
		
		# Set owner permissions
		self.permission_manager.grant_permission(
			resource_id=resource_id,
			resource_type=resource_type,
			user_id=owner_id,
			permission_level=PermissionLevel.OWNER,
			granted_by=owner_id
		)
		
		# Grant permissions to collaborators
		if collaborator_permissions:
			for user_id, permission_level in collaborator_permissions.items():
				self.permission_manager.grant_permission(
					resource_id=resource_id,
					resource_type=resource_type,
					user_id=user_id,
					permission_level=permission_level,
					granted_by=owner_id
				)
				
				# Send invitation notification
				self.notification_manager.create_notification(
					user_id=user_id,
					notification_type=NotificationType.INVITE_RECEIVED,
					title="Collaboration Invitation",
					message=f"You've been invited to collaborate on {resource_type} {resource_id}",
					resource_id=resource_id,
					from_user_id=owner_id
				)
		
		# Track activity
		track_database_activity(
			activity_type=ActivityType.COLLABORATION_STARTED,
			target=f"{resource_type}: {resource_id}",
			description=f"Started collaboration session {session_id}",
			details={
				"session_id": session_id,
				"owner_id": owner_id,
				"collaborators": list(collaborator_permissions.keys()) if collaborator_permissions else []
			}
		)
		
		return session_id
	
	def invite_collaborator(self, resource_id: str, user_id: str, permission_level: PermissionLevel,
						   invited_by: str) -> bool:
		"""Invite user to collaborate"""
		
		# Grant permission
		success = self.permission_manager.grant_permission(
			resource_id=resource_id,
			resource_type="graph",  # Default to graph
			user_id=user_id,
			permission_level=permission_level,
			granted_by=invited_by
		)
		
		if success:
			# Send notification
			self.notification_manager.create_notification(
				user_id=user_id,
				notification_type=NotificationType.INVITE_RECEIVED,
				title="Collaboration Invitation",
				message=f"You've been invited to collaborate with {permission_level.value} access",
				resource_id=resource_id,
				from_user_id=invited_by
			)
		
		return success
	
	def get_collaboration_overview(self, user_id: str) -> Dict[str, Any]:
		"""Get collaboration overview for user"""
		
		# Get active sessions
		active_sessions = self.realtime_engine.get_active_sessions(user_id)
		
		# Get permissions
		permissions = self.permission_manager.get_user_permissions(user_id)
		
		# Get notifications
		notifications = self.notification_manager.get_user_notifications(user_id, limit=10)
		unread_count = self.notification_manager.get_unread_count(user_id)
		
		# Get recent comments
		recent_comments = self.comment_system.get_user_comments(user_id)[-10:]
		
		return {
			"active_sessions": [s.to_dict() for s in active_sessions],
			"permissions": [p.to_dict() for p in permissions],
			"notifications": [n.to_dict() for n in notifications],
			"unread_notifications": unread_count,
			"recent_comments": [c.to_dict() for c in recent_comments],
			"collaboration_stats": {
				"total_sessions": len(active_sessions),
				"total_permissions": len(permissions),
				"total_comments": len(recent_comments)
			}
		}
	
	def _on_change_recorded(self, session_id: str, participants: Set[str], data: Dict[str, Any]):
		"""Handle change recorded event"""
		change = data.get("change", {})
		user_id = data.get("user_id")
		
		# Notify other participants
		for participant_id in participants:
			if participant_id != user_id:
				self.notification_manager.create_notification(
					user_id=participant_id,
					notification_type=NotificationType.CONTENT_SHARED,
					title="Content Updated",
					message=f"Content was updated in collaboration session",
					resource_id=change.get("resource_id"),
					from_user_id=user_id
				)
	
	def _on_user_joined(self, session_id: str, participants: Set[str], data: Dict[str, Any]):
		"""Handle user joined event"""
		joining_user = data.get("user_id")
		
		# Notify other participants
		for participant_id in participants:
			if participant_id != joining_user:
				user = self.users.get(joining_user)
				username = user.username if user else joining_user
				
				self.notification_manager.create_notification(
					user_id=participant_id,
					notification_type=NotificationType.CONTENT_SHARED,
					title="User Joined",
					message=f"{username} joined the collaboration session",
					from_user_id=joining_user
				)
	
	def _start_cleanup_thread(self):
		"""Start background cleanup thread"""
		def cleanup_task():
			import time
			while True:
				try:
					time.sleep(3600)  # Run every hour
					
					# Cleanup expired permissions
					self.permission_manager.cleanup_expired_permissions()
					
					# Cleanup inactive sessions
					self.realtime_engine.cleanup_inactive_sessions()
					
				except Exception as e:
					logger.error(f"Cleanup task error: {e}")
		
		cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
		cleanup_thread.start()


# Global collaboration system instance
_collaboration_system = None


def get_collaboration_system() -> CollaborationSystem:
	"""Get or create global collaboration system instance"""
	global _collaboration_system
	if _collaboration_system is None:
		_collaboration_system = CollaborationSystem()
	return _collaboration_system