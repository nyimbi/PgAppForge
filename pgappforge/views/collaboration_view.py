"""
Collaboration View for Multi-User Graph Analytics

Provides web interface for collaborative graph editing, sharing,
team management, and real-time synchronization.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.collaboration_system import (
	get_collaboration_system,
	CollaborationSystem,
	PermissionLevel,
	CollaborationType,
	NotificationType,
	CollaborationUser
)
from ..database.graph_manager import get_graph_manager
from ..database.multi_graph_manager import get_graph_registry
from ..database.activity_tracker import (
	track_database_activity,
	ActivityType,
	ActivitySeverity
)
from ..utils.error_handling import (
	WizardErrorHandler,
	WizardErrorType,
	WizardErrorSeverity
)

logger = logging.getLogger(__name__)


class CollaborationView(BaseView):
	"""
	Collaboration interface for multi-user graph analytics
	
	Provides comprehensive collaboration features including real-time editing,
	team management, permissions, and communication tools.
	"""
	
	route_base = "/graph/collaboration"
	default_view = "index"
	
	def __init__(self):
		"""Initialize collaboration view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		self.collaboration_system = None
	
	def _ensure_admin_access(self):
		"""Ensure current user has admin privileges"""
		try:
			from flask_login import current_user
			
			if not current_user or not current_user.is_authenticated:
				raise Forbidden("Authentication required")
			
			# Check if user has admin role
			if hasattr(current_user, "roles"):
				admin_roles = ["Admin", "admin", "Administrator", "administrator"]
				user_roles = [
					role.name if hasattr(role, "name") else str(role)
					for role in current_user.roles
				]
				
				if not any(role in admin_roles for role in user_roles):
					raise Forbidden("Administrator privileges required")
			else:
				# Fallback check for is_admin attribute
				if not getattr(current_user, "is_admin", False):
					raise Forbidden("Administrator privileges required")
					
		except Exception as e:
			logger.error(f"Admin access check failed: {e}")
			raise Forbidden("Access denied")
	
	def _get_current_user_id(self) -> str:
		"""Get current user ID"""
		try:
			from flask_login import current_user
			if current_user and current_user.is_authenticated:
				return str(current_user.id) if hasattr(current_user, 'id') else str(current_user)
			return "anonymous"
		except:
			return "anonymous"
	
	def _get_collaboration_system(self) -> CollaborationSystem:
		"""Get or initialize collaboration system"""
		try:
			return get_collaboration_system()
		except Exception as e:
			logger.error(f"Failed to initialize collaboration system: {e}")
			self.error_handler.handle_error(
				e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
			)
			raise
	
	@expose("/")
	@has_access
	@permission_name("can_collaborate")
	def index(self):
		"""Collaboration dashboard"""
		try:
			self._ensure_admin_access()
			
			collaboration_system = self._get_collaboration_system()
			user_id = self._get_current_user_id()
			
			# Register current user if not already registered
			self._ensure_user_registered(user_id)
			
			# Get collaboration overview
			overview = collaboration_system.get_collaboration_overview(user_id)
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			# Get all registered collaboration users
			all_users = list(collaboration_system.users.values())
			
			# Get permission levels
			permission_levels = [
				{
					"value": level.value,
					"name": level.value.replace("_", " ").title(),
					"description": self._get_permission_description(level)
				}
				for level in PermissionLevel
			]
			
			return render_template(
				"collaboration/index.html",
				title="Collaboration Dashboard",
				overview=overview,
				graphs=[graph.to_dict() for graph in graphs],
				users=[user.to_dict() for user in all_users],
				permission_levels=permission_levels,
				current_user_id=user_id
			)
			
		except Exception as e:
			logger.error(f"Error in collaboration dashboard: {e}")
			flash(f"Error loading collaboration dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/sessions/")
	@has_access
	@permission_name("can_collaborate")
	def sessions(self):
		"""Active collaboration sessions"""
		try:
			self._ensure_admin_access()
			
			collaboration_system = self._get_collaboration_system()
			user_id = self._get_current_user_id()
			
			# Get active sessions
			active_sessions = collaboration_system.realtime_engine.get_active_sessions(user_id)
			all_sessions = collaboration_system.realtime_engine.get_active_sessions()
			
			return render_template(
				"collaboration/sessions.html",
				title="Collaboration Sessions",
				user_sessions=[session.to_dict() for session in active_sessions],
				all_sessions=[session.to_dict() for session in all_sessions],
				current_user_id=user_id
			)
			
		except Exception as e:
			logger.error(f"Error in sessions interface: {e}")
			flash(f"Error loading sessions interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/permissions/")
	@has_access
	@permission_name("can_collaborate")
	def permissions(self):
		"""Permission management interface"""
		try:
			self._ensure_admin_access()
			
			collaboration_system = self._get_collaboration_system()
			user_id = self._get_current_user_id()
			
			# Get user permissions
			user_permissions = collaboration_system.permission_manager.get_user_permissions(user_id)
			
			# Get available graphs and users
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			users = list(collaboration_system.users.values())
			
			return render_template(
				"collaboration/permissions.html",
				title="Permission Management",
				user_permissions=[perm.to_dict() for perm in user_permissions],
				graphs=[graph.to_dict() for graph in graphs],
				users=[user.to_dict() for user in users],
				current_user_id=user_id
			)
			
		except Exception as e:
			logger.error(f"Error in permissions interface: {e}")
			flash(f"Error loading permissions interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/comments/")
	@has_access
	@permission_name("can_collaborate")
	def comments(self):
		"""Comments and annotations interface"""
		try:
			self._ensure_admin_access()
			
			collaboration_system = self._get_collaboration_system()
			user_id = self._get_current_user_id()
			
			# Get user's recent comments
			user_comments = collaboration_system.comment_system.get_user_comments(user_id)
			
			return render_template(
				"collaboration/comments.html",
				title="Comments & Annotations",
				user_comments=[comment.to_dict() for comment in user_comments],
				current_user_id=user_id
			)
			
		except Exception as e:
			logger.error(f"Error in comments interface: {e}")
			flash(f"Error loading comments interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	# API Endpoints
	
	@expose_api("post", "/api/start-collaboration/")
	@has_access
	@permission_name("can_collaborate")
	def api_start_collaboration(self):
		"""API endpoint to start collaboration session"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			resource_id = data.get("resource_id")
			resource_type = data.get("resource_type", "graph")
			collaborators = data.get("collaborators", {})  # user_id -> permission_level
			
			if not resource_id:
				raise BadRequest("resource_id is required")
			
			user_id = self._get_current_user_id()
			self._ensure_user_registered(user_id)
			
			# Convert permission strings to enums
			collaborator_permissions = {}
			for collab_user_id, permission_str in collaborators.items():
				try:
					collaborator_permissions[collab_user_id] = PermissionLevel(permission_str)
				except ValueError:
					raise BadRequest(f"Invalid permission level: {permission_str}")
			
			collaboration_system = self._get_collaboration_system()
			session_id = collaboration_system.start_collaboration(
				resource_id=resource_id,
				resource_type=resource_type,
				owner_id=user_id,
				collaborator_permissions=collaborator_permissions
			)
			
			return jsonify({
				"success": True,
				"session_id": session_id,
				"message": f"Collaboration session started: {session_id}"
			})
			
		except Exception as e:
			logger.error(f"API error starting collaboration: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/join-session/")
	@has_access
	@permission_name("can_collaborate")
	def api_join_session(self):
		"""API endpoint to join collaboration session"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			session_id = data.get("session_id")
			if not session_id:
				raise BadRequest("session_id is required")
			
			user_id = self._get_current_user_id()
			self._ensure_user_registered(user_id)
			
			collaboration_system = self._get_collaboration_system()
			success = collaboration_system.realtime_engine.join_session(session_id, user_id)
			
			if success:
				return jsonify({
					"success": True,
					"message": f"Joined session {session_id}"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Could not join session"
				}), 400
			
		except Exception as e:
			logger.error(f"API error joining session: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/leave-session/")
	@has_access
	@permission_name("can_collaborate")
	def api_leave_session(self):
		"""API endpoint to leave collaboration session"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			session_id = data.get("session_id")
			if not session_id:
				raise BadRequest("session_id is required")
			
			user_id = self._get_current_user_id()
			
			collaboration_system = self._get_collaboration_system()
			success = collaboration_system.realtime_engine.leave_session(session_id, user_id)
			
			if success:
				return jsonify({
					"success": True,
					"message": f"Left session {session_id}"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Could not leave session"
				}), 400
			
		except Exception as e:
			logger.error(f"API error leaving session: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/invite-collaborator/")
	@has_access
	@permission_name("can_collaborate")
	def api_invite_collaborator(self):
		"""API endpoint to invite collaborator"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			resource_id = data.get("resource_id")
			collaborator_user_id = data.get("user_id")
			permission_level_str = data.get("permission_level")
			
			if not all([resource_id, collaborator_user_id, permission_level_str]):
				raise BadRequest("resource_id, user_id, and permission_level are required")
			
			try:
				permission_level = PermissionLevel(permission_level_str)
			except ValueError:
				raise BadRequest(f"Invalid permission level: {permission_level_str}")
			
			user_id = self._get_current_user_id()
			
			collaboration_system = self._get_collaboration_system()
			success = collaboration_system.invite_collaborator(
				resource_id=resource_id,
				user_id=collaborator_user_id,
				permission_level=permission_level,
				invited_by=user_id
			)
			
			if success:
				return jsonify({
					"success": True,
					"message": f"Invited {collaborator_user_id} with {permission_level.value} access"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Could not invite collaborator"
				}), 400
			
		except Exception as e:
			logger.error(f"API error inviting collaborator: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/grant-permission/")
	@has_access
	@permission_name("can_collaborate")
	def api_grant_permission(self):
		"""API endpoint to grant permission"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			resource_id = data.get("resource_id")
			resource_type = data.get("resource_type", "graph")
			target_user_id = data.get("user_id")
			permission_level_str = data.get("permission_level")
			
			if not all([resource_id, target_user_id, permission_level_str]):
				raise BadRequest("resource_id, user_id, and permission_level are required")
			
			try:
				permission_level = PermissionLevel(permission_level_str)
			except ValueError:
				raise BadRequest(f"Invalid permission level: {permission_level_str}")
			
			user_id = self._get_current_user_id()
			
			collaboration_system = self._get_collaboration_system()
			success = collaboration_system.permission_manager.grant_permission(
				resource_id=resource_id,
				resource_type=resource_type,
				user_id=target_user_id,
				permission_level=permission_level,
				granted_by=user_id
			)
			
			if success:
				# Track activity
				track_database_activity(
					activity_type=ActivityType.PERMISSION_GRANTED,
					target=f"Resource: {resource_id}",
					description=f"Granted {permission_level.value} permission to {target_user_id}",
					details={
						"resource_id": resource_id,
						"target_user_id": target_user_id,
						"permission_level": permission_level.value
					}
				)
				
				return jsonify({
					"success": True,
					"message": f"Granted {permission_level.value} permission to {target_user_id}"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Could not grant permission"
				}), 400
			
		except Exception as e:
			logger.error(f"API error granting permission: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/revoke-permission/")
	@has_access
	@permission_name("can_collaborate")
	def api_revoke_permission(self):
		"""API endpoint to revoke permission"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			resource_id = data.get("resource_id")
			target_user_id = data.get("user_id")
			
			if not all([resource_id, target_user_id]):
				raise BadRequest("resource_id and user_id are required")
			
			user_id = self._get_current_user_id()
			
			collaboration_system = self._get_collaboration_system()
			success = collaboration_system.permission_manager.revoke_permission(
				resource_id=resource_id,
				user_id=target_user_id,
				revoked_by=user_id
			)
			
			if success:
				# Track activity
				track_database_activity(
					activity_type=ActivityType.PERMISSION_REVOKED,
					target=f"Resource: {resource_id}",
					description=f"Revoked permission for {target_user_id}",
					details={
						"resource_id": resource_id,
						"target_user_id": target_user_id
					}
				)
				
				return jsonify({
					"success": True,
					"message": f"Revoked permission for {target_user_id}"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Could not revoke permission"
				}), 400
			
		except Exception as e:
			logger.error(f"API error revoking permission: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/add-comment/")
	@has_access
	@permission_name("can_collaborate")
	def api_add_comment(self):
		"""API endpoint to add comment"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			resource_id = data.get("resource_id")
			resource_type = data.get("resource_type", "graph")
			content = data.get("content")
			position = data.get("position")  # Optional spatial position
			parent_comment_id = data.get("parent_comment_id")  # For replies
			
			if not all([resource_id, content]):
				raise BadRequest("resource_id and content are required")
			
			user_id = self._get_current_user_id()
			
			collaboration_system = self._get_collaboration_system()
			comment_id = collaboration_system.comment_system.add_comment(
				resource_id=resource_id,
				resource_type=resource_type,
				user_id=user_id,
				content=content,
				position=position,
				parent_comment_id=parent_comment_id
			)
			
			return jsonify({
				"success": True,
				"comment_id": comment_id,
				"message": "Comment added successfully"
			})
			
		except Exception as e:
			logger.error(f"API error adding comment: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/comments/<resource_id>/")
	@has_access
	@permission_name("can_collaborate")
	def api_get_comments(self, resource_id: str):
		"""API endpoint to get comments for resource"""
		try:
			self._ensure_admin_access()
			
			include_resolved = request.args.get("include_resolved", "true").lower() == "true"
			
			collaboration_system = self._get_collaboration_system()
			comments = collaboration_system.comment_system.get_resource_comments(
				resource_id=resource_id,
				include_resolved=include_resolved
			)
			
			return jsonify({
				"success": True,
				"comments": [comment.to_dict() for comment in comments]
			})
			
		except Exception as e:
			logger.error(f"API error getting comments: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/notifications/")
	@has_access
	@permission_name("can_collaborate")
	def api_get_notifications(self):
		"""API endpoint to get user notifications"""
		try:
			self._ensure_admin_access()
			
			unread_only = request.args.get("unread_only", "false").lower() == "true"
			limit = int(request.args.get("limit", 50))
			
			user_id = self._get_current_user_id()
			
			collaboration_system = self._get_collaboration_system()
			notifications = collaboration_system.notification_manager.get_user_notifications(
				user_id=user_id,
				unread_only=unread_only,
				limit=limit
			)
			
			return jsonify({
				"success": True,
				"notifications": [notification.to_dict() for notification in notifications],
				"unread_count": collaboration_system.notification_manager.get_unread_count(user_id)
			})
			
		except Exception as e:
			logger.error(f"API error getting notifications: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/notifications/<notification_id>/read/")
	@has_access
	@permission_name("can_collaborate")
	def api_mark_notification_read(self, notification_id: str):
		"""API endpoint to mark notification as read"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			
			collaboration_system = self._get_collaboration_system()
			success = collaboration_system.notification_manager.mark_as_read(
				notification_id=notification_id,
				user_id=user_id
			)
			
			if success:
				return jsonify({
					"success": True,
					"message": "Notification marked as read"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Could not mark notification as read"
				}), 400
			
		except Exception as e:
			logger.error(f"API error marking notification as read: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/collaboration-overview/")
	@has_access
	@permission_name("can_collaborate")
	def api_get_collaboration_overview(self):
		"""API endpoint to get collaboration overview"""
		try:
			self._ensure_admin_access()
			
			user_id = self._get_current_user_id()
			self._ensure_user_registered(user_id)
			
			collaboration_system = self._get_collaboration_system()
			overview = collaboration_system.get_collaboration_overview(user_id)
			
			return jsonify({
				"success": True,
				"overview": overview
			})
			
		except Exception as e:
			logger.error(f"API error getting collaboration overview: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/users/")
	@has_access
	@permission_name("can_collaborate")
	def api_get_users(self):
		"""API endpoint to get registered collaboration users"""
		try:
			self._ensure_admin_access()
			
			collaboration_system = self._get_collaboration_system()
			users = list(collaboration_system.users.values())
			
			return jsonify({
				"success": True,
				"users": [user.to_dict() for user in users]
			})
			
		except Exception as e:
			logger.error(f"API error getting users: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	def _ensure_user_registered(self, user_id: str):
		"""Ensure user is registered in collaboration system"""
		collaboration_system = self._get_collaboration_system()
		
		if user_id not in collaboration_system.users:
			# Try to get user info from Flask-Login
			try:
				from flask_login import current_user
				if current_user and current_user.is_authenticated:
					username = getattr(current_user, 'username', user_id)
					email = getattr(current_user, 'email', '')
				else:
					username = f"User_{user_id}"
					email = ""
			except:
				username = f"User_{user_id}"
				email = ""
			
			collaboration_system.register_user(
				user_id=user_id,
				username=username,
				email=email
			)
	
	def _get_permission_description(self, permission_level: PermissionLevel) -> str:
		"""Get description for permission level"""
		descriptions = {
			PermissionLevel.VIEWER: "Can view content but not make changes",
			PermissionLevel.EDITOR: "Can view and edit content",
			PermissionLevel.ADMIN: "Can manage permissions and settings",
			PermissionLevel.OWNER: "Full control including deletion rights"
		}
		return descriptions.get(permission_level, "Unknown permission level")