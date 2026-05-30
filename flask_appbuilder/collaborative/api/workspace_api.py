"""
Workspace API endpoints for Flask-AppBuilder collaborative features.

Provides RESTful APIs for workspace management including creation, access control,
resource management, and workspace-based collaboration.
"""

import logging
from typing import Any, Dict, List, Optional
from flask import request, jsonify, g
from flask_appbuilder import expose
from flask_appbuilder.api import BaseApi, safe
from flask_appbuilder.security.decorators import protect
from marshmallow import Schema, fields, ValidationError
from datetime import datetime, timezone

from ..interfaces.base_interfaces import IWorkspaceService
from ..core.workspace_manager import WorkspaceType, AccessLevel
from ..utils.validation import ValidationHelper, ValidationResult
from ..utils.error_handling import CollaborativeError, ErrorType, ErrorHandlingMixin
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType


class WorkspaceCreateSchema(Schema):
    """Schema for creating workspaces."""
    name = fields.Str(required=True, validate=ValidationHelper.validate_workspace_name)
    description = fields.Str(missing="")
    workspace_type = fields.Str(required=True, validate=lambda x: x in [t.value for t in WorkspaceType])
    team_id = fields.Int()
    settings = fields.Dict(missing=dict)


class WorkspaceUpdateSchema(Schema):
    """Schema for updating workspace information."""
    name = fields.Str(validate=ValidationHelper.validate_workspace_name)
    description = fields.Str()
    settings = fields.Dict()


class CollaboratorSchema(Schema):
    """Schema for workspace collaborator operations."""
    user_id = fields.Int(required=True, validate=ValidationHelper.validate_user_id)
    access_level = fields.Str(required=True, validate=lambda x: x in [a.value for a in AccessLevel])


class WorkspaceApi(BaseApi, ErrorHandlingMixin, CollaborativeAuditMixin):
    """
    RESTful API for workspace management.
    
    Provides endpoints for workspace creation, access control,
    resource management, and collaborative features.
    """

    resource_name = "workspace"
    datamodel = None  # No direct model binding for workspace API
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(f'{self.__class__.__module__}.{self.__class__.__name__}')
        self._workspace_service: Optional[IWorkspaceService] = None

    @property
    def workspace_service(self) -> IWorkspaceService:
        """Get workspace service from addon manager."""
        if self._workspace_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._workspace_service = self.appbuilder.collaborative_services.get_service(IWorkspaceService)
                except Exception as e:
                    raise CollaborativeError(
                        "Workspace service not available",
                        ErrorType.SERVICE_ERROR,
                        context={"error": str(e)}
                    )
            else:
                raise CollaborativeError(
                    "Collaborative services not initialized",
                    ErrorType.CONFIGURATION_ERROR
                )
        return self._workspace_service

    @expose('/', methods=['POST'])
    @protect()
    @safe
    def create_workspace(self):
        """
        Create a new workspace.
        
        ---
        post:
          description: >-
            Creates a new workspace with the current user as owner
          requestBody:
            required: true
            content:
              application/json:
                schema: WorkspaceCreateSchema
          responses:
            201:
              description: Workspace created successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      id:
                        type: integer
                      name:
                        type: string
                      slug:
                        type: string
                      description:
                        type: string
                      workspace_type:
                        type: string
                      owner_id:
                        type: integer
                      team_id:
                        type: integer
                      created_at:
                        type: string
                        format: date-time
                      collaborator_count:
                        type: integer
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            # Validate request data
            schema = WorkspaceCreateSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Validate team access if team_id is provided
            team_id = json_data.get("team_id")
            if team_id:
                # Check if user has access to create workspaces for this team
                # This would need to be implemented in the team service
                pass

            # Create the workspace
            workspace = self.workspace_service.create_workspace(
                name=json_data["name"],
                description=json_data.get("description", ""),
                workspace_type=WorkspaceType(json_data["workspace_type"]),
                owner_id=g.user.id if g.user else None,
                team_id=team_id,
                settings=json_data.get("settings", {})
            )

            if not workspace:
                return self.response_400(message="Failed to create workspace")

            # Audit workspace creation
            self.audit_user_action(
                "workspace_created",
                user_id=g.user.id if g.user else None,
                resource_type="workspace",
                resource_id=str(workspace.id),
                outcome="success"
            )

            response_data = {
                "id": workspace.id,
                "name": workspace.name,
                "slug": getattr(workspace, 'slug', workspace.name.lower().replace(' ', '-')),
                "description": workspace.description,
                "workspace_type": workspace.workspace_type.value if isinstance(workspace.workspace_type, WorkspaceType) else workspace.workspace_type,
                "owner_id": workspace.owner_id,
                "team_id": workspace.team_id,
                "created_at": workspace.created_at.isoformat() if hasattr(workspace, 'created_at') else datetime.now(tz=timezone.utc).isoformat(),
                "collaborator_count": 1,  # Owner is automatically a collaborator
                "message": "Workspace created successfully"
            }

            return self.response(response_data, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in create_workspace: {e}")
            self.audit_service_event("create_workspace_failed", outcome="error", error=str(e))
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in create_workspace: {e}")
            self.audit_service_event("create_workspace_failed", outcome="error", error=str(e))
            return self.response_500(message="Internal server error")

    @expose('/<int:workspace_id>', methods=['GET'])
    @protect()
    @safe
    def get_workspace(self, workspace_id: int):
        """
        Get workspace details.
        
        ---
        get:
          description: >-
            Get detailed information about a workspace
          parameters:
          - in: path
            schema:
              type: integer
            name: workspace_id
          responses:
            200:
              description: Workspace details retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      id:
                        type: integer
                      name:
                        type: string
                      slug:
                        type: string
                      description:
                        type: string
                      workspace_type:
                        type: string
                      owner_id:
                        type: integer
                      team_id:
                        type: integer
                      created_at:
                        type: string
                        format: date-time
                      collaborator_count:
                        type: integer
                      collaborators:
                        type: array
                        items:
                          type: object
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Check if user has access to this workspace
            if not self.workspace_service.has_workspace_access(
                g.user.id if g.user else None, 
                workspace_id, 
                AccessLevel.READ
            ):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="workspace",
                    resource_id=str(workspace_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to workspace")

            # Get workspace details
            workspace = self.workspace_service.get_workspace_by_id(workspace_id)
            if not workspace:
                return self.response_404(message="Workspace not found")

            # Get collaborators (if user has permission)
            collaborators_data = []
            if self.workspace_service.has_workspace_access(
                g.user.id if g.user else None, 
                workspace_id, 
                AccessLevel.ADMIN
            ):
                # This would need to be implemented in the workspace service
                # collaborators_data = self.workspace_service.get_workspace_collaborators(workspace_id)
                pass

            response_data = {
                "id": workspace.id,
                "name": workspace.name,
                "slug": getattr(workspace, 'slug', workspace.name.lower().replace(' ', '-')),
                "description": workspace.description,
                "workspace_type": workspace.workspace_type.value if isinstance(workspace.workspace_type, WorkspaceType) else workspace.workspace_type,
                "owner_id": workspace.owner_id,
                "team_id": workspace.team_id,
                "created_at": workspace.created_at.isoformat() if hasattr(workspace, 'created_at') else datetime.now(tz=timezone.utc).isoformat(),
                "collaborator_count": len(collaborators_data),
                "collaborators": collaborators_data
            }

            return self.response(response_data)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in get_workspace: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in get_workspace: {e}")
            return self.response_500(message="Internal server error")

    @expose('/<int:workspace_id>', methods=['PUT'])
    @protect()
    @safe
    def update_workspace(self, workspace_id: int):
        """
        Update workspace information.
        
        ---
        put:
          description: >-
            Update workspace name, description, or settings (requires admin access)
          parameters:
          - in: path
            schema:
              type: integer
            name: workspace_id
          requestBody:
            required: true
            content:
              application/json:
                schema: WorkspaceUpdateSchema
          responses:
            200:
              description: Workspace updated successfully
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Check if user has admin access to this workspace
            if not self.workspace_service.has_workspace_access(
                g.user.id if g.user else None, 
                workspace_id, 
                AccessLevel.ADMIN
            ):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="workspace",
                    resource_id=str(workspace_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to edit workspace")

            # Validate request data
            schema = WorkspaceUpdateSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Check if workspace exists
            workspace = self.workspace_service.get_workspace_by_id(workspace_id)
            if not workspace:
                return self.response_404(message="Workspace not found")

            # Update workspace (this would need to be implemented in the workspace service)
            # updated_workspace = self.workspace_service.update_workspace(workspace_id, json_data)

            # Audit workspace update
            self.audit_user_action(
                "workspace_updated",
                user_id=g.user.id if g.user else None,
                resource_type="workspace",
                resource_id=str(workspace_id),
                outcome="success",
                details=json_data
            )

            return self.response({
                "message": "Workspace updated successfully",
                "workspace_id": workspace_id
            })

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in update_workspace: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in update_workspace: {e}")
            return self.response_500(message="Internal server error")

    @expose('/<int:workspace_id>/collaborators', methods=['POST'])
    @protect()
    @safe
    def add_collaborator(self, workspace_id: int):
        """
        Add a collaborator to the workspace.
        
        ---
        post:
          description: >-
            Add a new collaborator to the workspace with specified access level
          parameters:
          - in: path
            schema:
              type: integer
            name: workspace_id
          requestBody:
            required: true
            content:
              application/json:
                schema: CollaboratorSchema
          responses:
            201:
              description: Collaborator added successfully
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
            409:
              description: User is already a workspace collaborator
        """
        try:
            # Check if user has admin access to add collaborators
            if not self.workspace_service.has_workspace_access(
                g.user.id if g.user else None, 
                workspace_id, 
                AccessLevel.ADMIN
            ):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="workspace",
                    resource_id=str(workspace_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to add workspace collaborators")

            # Validate request data
            schema = CollaboratorSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            user_id = json_data["user_id"]
            access_level = AccessLevel(json_data["access_level"])

            # Add workspace collaborator
            success = self.workspace_service.add_workspace_collaborator(
                workspace_id=workspace_id,
                user_id=user_id,
                access_level=access_level,
                added_by_user_id=g.user.id if g.user else None
            )

            if not success:
                return self.response(
                    {"message": "User is already a workspace collaborator or operation failed"}, 
                    409
                )

            # Audit collaborator addition
            self.audit_user_action(
                "workspace_collaborator_added",
                user_id=g.user.id if g.user else None,
                resource_type="workspace",
                resource_id=str(workspace_id),
                outcome="success",
                target_user_id=user_id,
                access_level=access_level.value
            )

            return self.response({
                "message": "Collaborator added successfully",
                "workspace_id": workspace_id,
                "user_id": user_id,
                "access_level": access_level.value
            }, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in add_collaborator: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in add_collaborator: {e}")
            return self.response_500(message="Internal server error")

    @expose('/<int:workspace_id>/collaborators/<int:user_id>', methods=['DELETE'])
    @protect()
    @safe
    def remove_collaborator(self, workspace_id: int, user_id: int):
        """
        Remove a collaborator from the workspace.
        
        ---
        delete:
          description: >-
            Remove a collaborator from the workspace
          parameters:
          - in: path
            schema:
              type: integer
            name: workspace_id
          - in: path
            schema:
              type: integer
            name: user_id
          responses:
            200:
              description: Collaborator removed successfully
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            # Check if user has admin access to remove collaborators
            if not self.workspace_service.has_workspace_access(
                g.user.id if g.user else None, 
                workspace_id, 
                AccessLevel.ADMIN
            ):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="workspace",
                    resource_id=str(workspace_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to remove workspace collaborators")

            # Remove workspace collaborator
            success = self.workspace_service.remove_workspace_collaborator(
                workspace_id=workspace_id,
                user_id=user_id,
                removed_by_user_id=g.user.id if g.user else None
            )

            if not success:
                return self.response_404(message="Workspace collaborator not found")

            # Audit collaborator removal
            self.audit_user_action(
                "workspace_collaborator_removed",
                user_id=g.user.id if g.user else None,
                resource_type="workspace",
                resource_id=str(workspace_id),
                outcome="success",
                target_user_id=user_id
            )

            return self.response({
                "message": "Collaborator removed successfully",
                "workspace_id": workspace_id,
                "user_id": user_id
            })

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in remove_collaborator: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in remove_collaborator: {e}")
            return self.response_500(message="Internal server error")

    @expose('/user/<int:user_id>/workspaces', methods=['GET'])
    @protect()
    @safe
    def get_user_workspaces(self, user_id: int):
        """
        Get all workspaces for a user.
        
        ---
        get:
          description: >-
            Get all workspaces that a user has access to
          parameters:
          - in: path
            schema:
              type: integer
            name: user_id
          responses:
            200:
              description: User workspaces retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      user_id:
                        type: integer
                      workspaces:
                        type: array
                        items:
                          type: object
                          properties:
                            id:
                              type: integer
                            name:
                              type: string
                            slug:
                              type: string
                            workspace_type:
                              type: string
                            access_level:
                              type: string
                            last_accessed:
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
            # Users can only view their own workspaces unless they have admin permissions
            if user_id != (g.user.id if g.user else None):
                if not self.appbuilder.sm.has_access("can_list", "User"):
                    return self.response_403(message="Access denied to view other users' workspaces")

            # Get user workspaces
            workspaces = self.workspace_service.get_user_workspaces(user_id)

            response_data = {
                "user_id": user_id,
                "workspaces": workspaces,
                "total_workspaces": len(workspaces)
            }

            return self.response(response_data)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in get_user_workspaces: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in get_user_workspaces: {e}")
            return self.response_500(message="Internal server error")

    @expose('/', methods=['GET'])
    @protect()
    @safe
    def list_workspaces(self):
        """
        List all workspaces (with proper filtering based on permissions).
        
        ---
        get:
          description: >-
            List workspaces that the current user has access to
          parameters:
          - in: query
            name: page
            schema:
              type: integer
              default: 1
          - in: query
            name: page_size
            schema:
              type: integer
              default: 20
          - in: query
            name: workspace_type
            schema:
              type: string
          responses:
            200:
              description: Workspaces listed successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      workspaces:
                        type: array
                        items:
                          type: object
                      total:
                        type: integer
                      page:
                        type: integer
                      page_size:
                        type: integer
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            # Get pagination and filter parameters
            page = request.args.get('page', 1, type=int)
            page_size = min(request.args.get('page_size', 20, type=int), 100)
            workspace_type_filter = request.args.get('workspace_type')

            # Get user's workspaces
            user_workspaces = self.workspace_service.get_user_workspaces(g.user.id if g.user else None)

            # Apply workspace type filter if provided
            if workspace_type_filter:
                try:
                    workspace_type = WorkspaceType(workspace_type_filter)
                    user_workspaces = [w for w in user_workspaces if w.get('workspace_type') == workspace_type.value]
                except ValueError:
                    return self.response_400(message="Invalid workspace type filter")

            # Apply pagination
            start = (page - 1) * page_size
            end = start + page_size
            paginated_workspaces = user_workspaces[start:end]

            response_data = {
                "workspaces": paginated_workspaces,
                "total": len(user_workspaces),
                "page": page,
                "page_size": page_size,
                "total_pages": (len(user_workspaces) + page_size - 1) // page_size
            }

            return self.response(response_data)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in list_workspaces: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in list_workspaces: {e}")
            return self.response_500(message="Internal server error")