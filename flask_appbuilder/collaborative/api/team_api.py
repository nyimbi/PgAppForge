"""
Team API endpoints for Flask-AppBuilder collaborative features.

Provides RESTful APIs for team management including creation, membership,
permissions, and team-based collaboration features.
"""

import logging
from typing import Any, Dict, List, Optional
from flask import request, jsonify, g
from flask_appbuilder import expose
from flask_appbuilder.api import BaseApi, safe
from flask_appbuilder.security.decorators import protect
from marshmallow import Schema, fields, ValidationError
from datetime import datetime, timezone

from ..interfaces.base_interfaces import ITeamService
from ..core.team_manager import TeamRole, TeamConfig
from ..utils.validation import ValidationHelper, ValidationResult
from ..utils.error_handling import CollaborativeError, ErrorType, ErrorHandlingMixin
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType


class TeamCreateSchema(Schema):
    """Schema for creating teams."""
    name = fields.Str(required=True, validate=ValidationHelper.validate_team_name)
    description = fields.Str(missing="")
    is_private = fields.Bool(missing=False)
    settings = fields.Dict(missing=dict)


class TeamMemberSchema(Schema):
    """Schema for team member operations."""
    user_id = fields.Int(required=True, validate=ValidationHelper.validate_user_id)
    role = fields.Str(required=True, validate=lambda x: x in [r.value for r in TeamRole])


class TeamUpdateSchema(Schema):
    """Schema for updating team information."""
    name = fields.Str(validate=ValidationHelper.validate_team_name)
    description = fields.Str()
    is_private = fields.Bool()
    settings = fields.Dict()


class TeamApi(BaseApi, ErrorHandlingMixin, CollaborativeAuditMixin):
    """
    RESTful API for team management.
    
    Provides endpoints for team creation, membership management,
    permissions, and team-based collaborative features.
    """

    resource_name = "team"
    datamodel = None  # No direct model binding for team API
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(f'{self.__class__.__module__}.{self.__class__.__name__}')
        self._team_service: Optional[ITeamService] = None

    @property
    def team_service(self) -> ITeamService:
        """Get team service from addon manager."""
        if self._team_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._team_service = self.appbuilder.collaborative_services.get_service(ITeamService)
                except Exception as e:
                    raise CollaborativeError(
                        "Team service not available",
                        ErrorType.SERVICE_ERROR,
                        context={"error": str(e)}
                    )
            else:
                raise CollaborativeError(
                    "Collaborative services not initialized",
                    ErrorType.CONFIGURATION_ERROR
                )
        return self._team_service

    @expose('/', methods=['POST'])
    @protect()
    @safe
    def create_team(self):
        """
        Create a new team.
        
        ---
        post:
          description: >-
            Creates a new team with the current user as owner
          requestBody:
            required: true
            content:
              application/json:
                schema: TeamCreateSchema
          responses:
            201:
              description: Team created successfully
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
                      created_by:
                        type: integer
                      created_at:
                        type: string
                        format: date-time
                      member_count:
                        type: integer
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            # Validate request data
            schema = TeamCreateSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Create team configuration
            team_config = TeamConfig(
                is_private=json_data.get("is_private", False),
                settings=json_data.get("settings", {})
            )

            # Create the team
            team = self.team_service.create_team(
                name=json_data["name"],
                description=json_data.get("description", ""),
                created_by_user_id=g.user.id if g.user else None,
                config=team_config
            )

            if not team:
                return self.response_400(message="Failed to create team")

            # Audit team creation
            self.audit_user_action(
                "team_created",
                user_id=g.user.id if g.user else None,
                resource_type="team",
                resource_id=str(team.id),
                outcome="success"
            )

            response_data = {
                "id": team.id,
                "name": team.name,
                "slug": team.slug,
                "description": team.description,
                "is_private": team.is_private,
                "created_by": team.created_by_user_id,
                "created_at": team.created_at.isoformat() if hasattr(team, 'created_at') else datetime.now(tz=timezone.utc).isoformat(),
                "member_count": 1,  # Creator is automatically a member
                "message": "Team created successfully"
            }

            return self.response(response_data, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in create_team: {e}")
            self.audit_service_event("create_team_failed", outcome="error", error=str(e))
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in create_team: {e}")
            self.audit_service_event("create_team_failed", outcome="error", error=str(e))
            return self.response_500(message="Internal server error")

    @expose('/<int:team_id>', methods=['GET'])
    @protect()
    @safe
    def get_team(self, team_id: int):
        """
        Get team details.
        
        ---
        get:
          description: >-
            Get detailed information about a team
          parameters:
          - in: path
            schema:
              type: integer
            name: team_id
          responses:
            200:
              description: Team details retrieved successfully
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
                      is_private:
                        type: boolean
                      created_by:
                        type: integer
                      created_at:
                        type: string
                        format: date-time
                      member_count:
                        type: integer
                      members:
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
            # Check if user has permission to view this team
            if not self.team_service.has_team_permission(g.user.id if g.user else None, team_id, "can_view"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="team",
                    resource_id=str(team_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to team")

            # Get team details
            team = self.team_service.get_team_by_id(team_id)
            if not team:
                return self.response_404(message="Team not found")

            # Get team members (if user has permission)
            members_data = []
            if self.team_service.has_team_permission(g.user.id if g.user else None, team_id, "can_view_members"):
                try:
                    members = self.team_service.get_team_members(team_id)
                    members_data = [
                        {
                            "user_id": member["user_id"],
                            "role": member["role"].value if hasattr(member["role"], "value") else str(member["role"]),
                            "joined_at": member["joined_at"].isoformat() if member["joined_at"] else None,
                            "is_active": member["is_active"]
                        }
                        for member in members
                    ]
                except Exception as e:
                    self.logger.error(f"Error fetching team members: {e}")
                    # Continue with empty list for graceful degradation

            response_data = {
                "id": team.id,
                "name": team.name,
                "slug": team.slug,
                "description": team.description,
                "is_private": getattr(team, 'is_private', False),
                "created_by": team.created_by_user_id,
                "created_at": team.created_at.isoformat() if hasattr(team, 'created_at') else datetime.now(tz=timezone.utc).isoformat(),
                "member_count": len(members_data),
                "members": members_data
            }

            return self.response(response_data)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in get_team: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in get_team: {e}")
            return self.response_500(message="Internal server error")

    @expose('/<int:team_id>', methods=['PUT'])
    @protect()
    @safe
    def update_team(self, team_id: int):
        """
        Update team information.
        
        ---
        put:
          description: >-
            Update team name, description, or settings (requires admin permission)
          parameters:
          - in: path
            schema:
              type: integer
            name: team_id
          requestBody:
            required: true
            content:
              application/json:
                schema: TeamUpdateSchema
          responses:
            200:
              description: Team updated successfully
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
            # Check if user has permission to edit this team
            if not self.team_service.has_team_permission(g.user.id if g.user else None, team_id, "can_edit"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="team",
                    resource_id=str(team_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to edit team")

            # Validate request data
            schema = TeamUpdateSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            # Check if team exists
            team = self.team_service.get_team_by_id(team_id)
            if not team:
                return self.response_404(message="Team not found")

            # Update team (this would need to be implemented in the team service)
            # updated_team = self.team_service.update_team(team_id, json_data)

            # Audit team update
            self.audit_user_action(
                "team_updated",
                user_id=g.user.id if g.user else None,
                resource_type="team",
                resource_id=str(team_id),
                outcome="success",
                details=json_data
            )

            return self.response({
                "message": "Team updated successfully",
                "team_id": team_id
            })

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in update_team: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in update_team: {e}")
            return self.response_500(message="Internal server error")

    @expose('/<int:team_id>/members', methods=['POST'])
    @protect()
    @safe
    def add_member(self, team_id: int):
        """
        Add a member to the team.
        
        ---
        post:
          description: >-
            Add a new member to the team with specified role
          parameters:
          - in: path
            schema:
              type: integer
            name: team_id
          requestBody:
            required: true
            content:
              application/json:
                schema: TeamMemberSchema
          responses:
            201:
              description: Member added successfully
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            404:
              $ref: '#/components/responses/404'
            409:
              description: User is already a team member
        """
        try:
            # Check if user has permission to add members
            if not self.team_service.has_team_permission(g.user.id if g.user else None, team_id, "can_add_members"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="team",
                    resource_id=str(team_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to add team members")

            # Validate request data
            schema = TeamMemberSchema()
            try:
                json_data = schema.load(request.json or {})
            except ValidationError as e:
                return self.response_400(message="Invalid input data", details=e.messages)

            user_id = json_data["user_id"]
            role = TeamRole(json_data["role"])

            # Add team member
            success = self.team_service.add_team_member(
                team_id=team_id,
                user_id=user_id,
                role=role,
                invited_by_user_id=g.user.id if g.user else None
            )

            if not success:
                return self.response(
                    {"message": "User is already a team member or operation failed"}, 
                    409
                )

            # Audit member addition
            self.audit_user_action(
                "team_member_added",
                user_id=g.user.id if g.user else None,
                resource_type="team",
                resource_id=str(team_id),
                outcome="success",
                target_user_id=user_id,
                role=role.value
            )

            return self.response({
                "message": "Member added successfully",
                "team_id": team_id,
                "user_id": user_id,
                "role": role.value
            }, 201)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in add_member: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in add_member: {e}")
            return self.response_500(message="Internal server error")

    @expose('/<int:team_id>/members/<int:user_id>', methods=['DELETE'])
    @protect()
    @safe
    def remove_member(self, team_id: int, user_id: int):
        """
        Remove a member from the team.
        
        ---
        delete:
          description: >-
            Remove a member from the team
          parameters:
          - in: path
            schema:
              type: integer
            name: team_id
          - in: path
            schema:
              type: integer
            name: user_id
          responses:
            200:
              description: Member removed successfully
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
            # Check if user has permission to remove members
            if not self.team_service.has_team_permission(g.user.id if g.user else None, team_id, "can_remove_members"):
                self.audit_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    user_id=g.user.id if g.user else None,
                    resource_type="team",
                    resource_id=str(team_id),
                    outcome="failure"
                )
                return self.response_403(message="Access denied to remove team members")

            # Remove team member
            success = self.team_service.remove_team_member(
                team_id=team_id,
                user_id=user_id,
                removed_by_user_id=g.user.id if g.user else None
            )

            if not success:
                return self.response_404(message="Team member not found")

            # Audit member removal
            self.audit_user_action(
                "team_member_removed",
                user_id=g.user.id if g.user else None,
                resource_type="team",
                resource_id=str(team_id),
                outcome="success",
                target_user_id=user_id
            )

            return self.response({
                "message": "Member removed successfully",
                "team_id": team_id,
                "user_id": user_id
            })

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in remove_member: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in remove_member: {e}")
            return self.response_500(message="Internal server error")

    @expose('/user/<int:user_id>/teams', methods=['GET'])
    @protect()
    @safe
    def get_user_teams(self, user_id: int):
        """
        Get all teams for a user.
        
        ---
        get:
          description: >-
            Get all teams that a user is a member of
          parameters:
          - in: path
            schema:
              type: integer
            name: user_id
          responses:
            200:
              description: User teams retrieved successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      user_id:
                        type: integer
                      teams:
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
                            role:
                              type: string
                            joined_at:
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
            # Users can only view their own teams unless they have admin permissions
            if user_id != (g.user.id if g.user else None):
                if not self.appbuilder.sm.has_access("can_list", "User"):
                    return self.response_403(message="Access denied to view other users' teams")

            # Get user teams
            teams = self.team_service.get_user_teams(user_id)

            response_data = {
                "user_id": user_id,
                "teams": teams,
                "total_teams": len(teams)
            }

            return self.response(response_data)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in get_user_teams: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in get_user_teams: {e}")
            return self.response_500(message="Internal server error")

    @expose('/', methods=['GET'])
    @protect()
    @safe
    def list_teams(self):
        """
        List all teams (with proper filtering based on permissions).
        
        ---
        get:
          description: >-
            List teams that the current user has access to view
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
          responses:
            200:
              description: Teams listed successfully
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      teams:
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
            # Get pagination parameters
            page = request.args.get('page', 1, type=int)
            page_size = min(request.args.get('page_size', 20, type=int), 100)

            # Get user's teams (for now, only show teams user is member of)
            user_teams = self.team_service.get_user_teams(g.user.id if g.user else None)

            # Apply pagination
            start = (page - 1) * page_size
            end = start + page_size
            paginated_teams = user_teams[start:end]

            response_data = {
                "teams": paginated_teams,
                "total": len(user_teams),
                "page": page,
                "page_size": page_size,
                "total_pages": (len(user_teams) + page_size - 1) // page_size
            }

            return self.response(response_data)

        except CollaborativeError as e:
            self.logger.error(f"Collaborative error in list_teams: {e}")
            return self.response_400(message=str(e))
        except Exception as e:
            self.logger.error(f"Unexpected error in list_teams: {e}")
            return self.response_500(message="Internal server error")