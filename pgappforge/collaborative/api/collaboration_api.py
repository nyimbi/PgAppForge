"""
Collaboration API endpoints for PgAppForge collaborative features.

Provides RESTful APIs for collaboration sessions, real-time events,
resource locking, and user session management.
"""

import logging
from typing import Any, Dict, List, Optional, Union
from flask import request, jsonify, g
from pgappforge import expose
from pgappforge.api import BaseApi, safe
from pgappforge.security.decorators import protect
from marshmallow import Schema, fields, ValidationError

from ..interfaces.base_interfaces import ICollaborationService
from ..utils.validation import ValidationHelper, ValidationResult
from ..utils.error_handling import CollaborativeError, ErrorType, ErrorHandlingMixin
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType
from ..utils.async_bridge import AsyncServiceMixin


class SessionCreateSchema(Schema):
    """Schema for creating collaboration sessions."""
    workspace_id = fields.Str(required=True, validate=ValidationHelper.validate_workspace_id)
    session_type = fields.Str(missing="general", validate=lambda x: x in ["general", "document", "meeting"])
    settings = fields.Dict(missing=dict)


class SessionJoinSchema(Schema):
    """Schema for joining collaboration sessions."""
    session_id = fields.Str(required=True, validate=ValidationHelper.validate_session_id)


class EventEmitSchema(Schema):
    """Schema for emitting collaboration events."""
    session_id = fields.Str(required=True, validate=ValidationHelper.validate_session_id) 
    event_type = fields.Str(required=True, validate=lambda x: x in ["cursor", "selection", "edit", "comment", "presence"])
    data = fields.Dict(required=True)


class ResourceLockSchema(Schema):
    """Schema for resource locking operations."""
    session_id = fields.Str(required=True, validate=ValidationHelper.validate_session_id)
    resource_id = fields.Str(required=True, validate=ValidationHelper.validate_resource_id)


class CollaborationApi(BaseApi, ErrorHandlingMixin, CollaborativeAuditMixin, AsyncServiceMixin):
    """
    RESTful API for collaboration features.
    
    Provides endpoints for session management, real-time events,
    resource locking, and collaborative editing features.
    """

    resource_name = "collaboration"
    datamodel = None  # No direct model binding for collaboration API
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(f'{self.__class__.__module__}.{self.__class__.__name__}')
        self._collaboration_service: Optional[ICollaborationService] = None

    @property
    def collaboration_service(self) -> ICollaborationService:
        """Get collaboration service from addon manager."""
        if self._collaboration_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._collaboration_service = self.appbuilder.collaborative_services.get_service(ICollaborationService)
                except Exception as e:
                    raise CollaborativeError(
                        "Collaboration service not available",
                        ErrorType.SERVICE_ERROR,
                        context={"error": str(e)}
                    )
            else:
                raise CollaborativeError(
                    "Collaborative services not initialized",
                    ErrorType.CONFIGURATION_ERROR
                )
        return self._collaboration_service

    @expose('/session', methods=['POST'])
    @protect()
    @safe
    def create_session(self):
        """
        Create a new collaboration session.
        
        ---
        post:
          description: >-
            Creates a new collaboration session for the specified workspace
          requestBody:
            required: true
            content:
              application/json:
                schema: SessionCreateSchema
          responses:
            201:
              description: Session created successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      session_id:
                        type: string
                      workspace_id:
                        type: string
                      created_by:
                        type: integer
                      created_at:
                        type: string
                        format: date-time
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            # Validate request data
            schema = SessionCreateSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            workspace_id = json_data["workspace_id"]
            
            # Check workspace access permissions
            if not self.appbuilder.sm.has_access("can_access", f"workspace_{workspace_id}"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="workspace",
                    resource_id=workspace_id,
                    outcome="failure"
                )
                return self.response_403(message="Access denied to workspace")

            # Create collaboration session
            session_id = self.call_async_service(
                self.collaboration_service.create_session,
                workspace_id=workspace_id,
                user=g.user
            )

            if not session_id:
                return self.response_400(message="Failed to create collaboration session")

            # Audit successful session creation
            self.audit_user_action(
                "session_created",
                user_id=g.user.id if g.user else None,
                resource_type="collaboration_session",
                resource_id=session_id,
                outcome="success"
            )

            response_data = {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "created_by": g.user.id if g.user else None,
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
                "message": "Collaboration session created successfully"
            }

            return self.response(response_data, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in create_session: {e}")
            self.audit_service_event("create_session_failed", outcome="error", error=str(e))
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in create_session: {e}")
            self.audit_service_event("create_session_failed", outcome="error", error=str(e))
            return self.response_500(message="Internal server error")

    @expose('/session/<session_id>/join', methods=['POST'])
    @protect()
    @safe
    def join_session(self, session_id: str):
        """
        Join an existing collaboration session.
        
        ---
        post:
          description: >-
            Join an existing collaboration session
          parameters:
          - in: path
            schema:
              type: string
            name: session_id
          responses:
            200:
              description: Successfully joined session
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      session_id:
                        type: string
                      user_id:
                        type: integer
                      joined_at:
                        type: string
                        format: date-time
                      active_users:
                        type: array
                        items:
                          type: object
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Validate session ID
            validation_result = ValidationHelper.validate_session_id(session_id)
            if not validation_result.is_valid:
                return self.response_400(message=validation_result.error_message)

            # Join the collaboration session
            success = self.call_async_service(
                self.collaboration_service.join_session,
                session_id=session_id,
                user=g.user
            )

            if not success:
                return self.response_404(message="Session not found or access denied")

            # Get current session users
            session_users = self.collaboration_service.get_session_users(session_id)

            # Audit successful join
            self.audit_user_action(
                "session_joined",
                user_id=g.user.id if g.user else None,
                resource_type="collaboration_session",
                resource_id=session_id,
                outcome="success"
            )

            response_data = {
                "session_id": session_id,
                "user_id": g.user.id if g.user else None,
                "joined_at": datetime.now(tz=timezone.utc).isoformat(),
                "active_users": [{"id": user.id, "username": user.username} for user in session_users],
                "message": "Successfully joined collaboration session"
            }

            return self.response(response_data)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in join_session: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in join_session: {e}")
            return self.response_500(message="Internal server error")

    @expose('/session/<session_id>/leave', methods=['POST'])
    @protect()
    @safe
    def leave_session(self, session_id: str):
        """
        Leave a collaboration session.
        
        ---
        post:
          description: >-
            Leave a collaboration session
          parameters:
          - in: path
            schema:
              type: string
            name: session_id
          responses:
            200:
              description: Successfully left session
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Validate session ID
            validation_result = ValidationHelper.validate_session_id(session_id)
            if not validation_result.is_valid:
                return self.response_400(message=validation_result.error_message)

            # Leave the collaboration session
            success = self.call_async_service(
                self.collaboration_service.leave_session,
                session_id=session_id,
                user_id=g.user.id if g.user else None
            )

            if not success:
                return self.response_404(message="Session not found")

            # Audit session leave
            self.audit_user_action(
                "session_left",
                user_id=g.user.id if g.user else None,
                resource_type="collaboration_session",
                resource_id=session_id,
                outcome="success"
            )

            return self.response({"message": "Successfully left collaboration session"})

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in leave_session: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in leave_session: {e}")
            return self.response_500(message="Internal server error")

    @expose('/event', methods=['POST'])
    @protect()
    @safe
    def emit_event(self):
        """
        Emit a collaboration event to session participants.
        
        ---
        post:
          description: >-
            Emit a real-time collaboration event to all session participants
          requestBody:
            required: true
            content:
              application/json:
                schema: EventEmitSchema
          responses:
            200:
              description: Event emitted successfully
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
        """
        try:
            # Validate request data
            schema = EventEmitSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Create collaborative event object
            event_data = {
                "session_id": json_data["session_id"],
                "event_type": json_data["event_type"],
                "data": json_data["data"],
                "user_id": g.user.id if g.user else None,
                "timestamp": datetime.now(tz=timezone.utc).isoformat()
            }

            # Emit the event to session participants
            self.call_async_service(
                self.collaboration_service.emit_event,
                event_data
            )

            # Audit event emission (only for important events, not cursor movements)
            if json_data["event_type"] not in ["cursor", "presence"]:
                self.audit_user_action(
                    f"event_{json_data['event_type']}_emitted",
                    user_id=g.user.id if g.user else None,
                    resource_type="collaboration_session",
                    resource_id=json_data["session_id"],
                    outcome="success"
                )

            return self.response({"message": "Event emitted successfully"})

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in emit_event: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in emit_event: {e}")
            return self.response_500(message="Internal server error")

    @expose('/lock', methods=['POST'])
    @protect()
    @safe
    def acquire_lock(self):
        """
        Acquire a lock on a resource for exclusive editing.
        
        ---
        post:
          description: >-
            Acquire an exclusive lock on a resource within a collaboration session
          requestBody:
            required: true
            content:
              application/json:
                schema: ResourceLockSchema
          responses:
            200:
              description: Lock acquired successfully
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            409:
              description: Resource already locked by another user
        """
        try:
            # Validate request data
            schema = ResourceLockSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Attempt to acquire the lock
            success = self.call_async_service(
                self.collaboration_service.acquire_lock,
                session_id=json_data["session_id"],
                user_id=g.user.id if g.user else None,
                resource_id=json_data["resource_id"]
            )

            if not success:
                return self.response(
                    {"message": "Resource is already locked by another user"}, 
                    409
                )

            # Audit lock acquisition
            self.audit_user_action(
                "resource_locked",
                user_id=g.user.id if g.user else None,
                resource_type="collaboration_resource",
                resource_id=json_data["resource_id"],
                outcome="success",
                session_id=json_data["session_id"]
            )

            return self.response({
                "message": "Lock acquired successfully",
                "resource_id": json_data["resource_id"],
                "locked_by": g.user.id if g.user else None,
                "locked_at": datetime.now(tz=timezone.utc).isoformat()
            })

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in acquire_lock: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in acquire_lock: {e}")
            return self.response_500(message="Internal server error")

    @expose('/lock', methods=['DELETE'])
    @protect()
    @safe
    def release_lock(self):
        """
        Release a lock on a resource.
        
        ---
        delete:
          description: >-
            Release an exclusive lock on a resource
          requestBody:
            required: true
            content:
              application/json:
                schema: ResourceLockSchema
          responses:
            200:
              description: Lock released successfully
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              description: User does not own this lock
        """
        try:
            # Validate request data
            schema = ResourceLockSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Attempt to release the lock
            success = self.call_async_service(
                self.collaboration_service.release_lock,
                session_id=json_data["session_id"],
                user_id=g.user.id if g.user else None,
                resource_id=json_data["resource_id"]
            )

            if not success:
                return self.response_403(message="Lock not found or not owned by current user")

            # Audit lock release
            self.audit_user_action(
                "resource_unlocked",
                user_id=g.user.id if g.user else None,
                resource_type="collaboration_resource",
                resource_id=json_data["resource_id"],
                outcome="success",
                session_id=json_data["session_id"]
            )

            return self.response({
                "message": "Lock released successfully",
                "resource_id": json_data["resource_id"]
            })

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in release_lock: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in release_lock: {e}")
            return self.response_500(message="Internal server error")

    @expose('/session/<session_id>/users', methods=['GET'])
    @protect()
    @safe
    def get_session_users(self, session_id: str):
        """
        Get all users currently in a collaboration session.
        
        ---
        get:
          description: >-
            Get list of all users currently active in a collaboration session
          parameters:
          - in: path
            schema:
              type: string
            name: session_id
          responses:
            200:
              description: Session users retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      session_id:
                        type: string
                      users:
                        type: array
                        items:
                          type: object
                          properties:
                            id:
                              type: integer
                            username:
                              type: string
                            full_name:
                              type: string
                            joined_at:
                              type: string
                              format: date-time
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Validate session ID
            validation_result = ValidationHelper.validate_session_id(session_id)
            if not validation_result.is_valid:
                return self.response_400(message=validation_result.error_message)

            # Get session users
            session_users = self.collaboration_service.get_session_users(session_id)

            if session_users is None:
                return self.response_404(message="Session not found")

            # Format user data for response
            users_data = []
            for user in session_users:
                users_data.append({
                    "id": user.id,
                    "username": user.username,
                    "full_name": getattr(user, 'full_name', user.username),
                    "joined_at": getattr(user, 'session_joined_at', datetime.now(tz=timezone.utc).isoformat())
                })

            return self.response({
                "session_id": session_id,
                "users": users_data,
                "total_users": len(users_data)
            })

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in get_session_users: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in get_session_users: {e}")
            return self.response_500(message="Internal server error")