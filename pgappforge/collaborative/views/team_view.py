"""
Team Management Views for PgAppForge collaborative features.

Provides administrative and user-facing views for team management,
including team creation, membership management, and team-based permissions.
"""

from flask import flash, redirect, url_for, request, jsonify
from pgappforge import ModelView, BaseView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import protect
from pgappforge.widgets import ListWidget, ShowWidget
from pgappforge.forms import DynamicForm
from wtforms import StringField, TextAreaField, BooleanField, SelectField
from wtforms.validators import DataRequired, Length
from sqlalchemy.exc import IntegrityError
from typing import Any, Dict, List

from ..core.team_manager import Team, TeamMember, TeamRole
from ..interfaces.base_interfaces import ITeamService
from ..utils.error_handling import CollaborativeError, ErrorHandlingMixin
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType
from ..utils.validation import ValidationHelper


class TeamForm(DynamicForm):
    """Form for creating and editing teams."""
    name = StringField(
        'Team Name', 
        validators=[DataRequired(), Length(min=1, max=100)],
        description="Name of the team"
    )
    description = TextAreaField(
        'Description',
        validators=[Length(max=500)],
        description="Brief description of the team's purpose"
    )
    is_private = BooleanField(
        'Private Team',
        default=False,
        description="Private teams are only visible to members"
    )


class TeamMemberForm(DynamicForm):
    """Form for adding team members."""
    user_id = SelectField(
        'User',
        coerce=int,
        validators=[DataRequired()],
        description="Select a user to add to the team"
    )
    role = SelectField(
        'Role',
        choices=[(role.value, role.value.title()) for role in TeamRole],
        validators=[DataRequired()],
        description="Role for the user in this team"
    )


class TeamModelView(ModelView, ErrorHandlingMixin, CollaborativeAuditMixin):
    """
    ModelView for Team management.
    
    Provides administrative interface for team creation, editing,
    member management, and team-based collaborative features.
    """

    datamodel = SQLAInterface(Team)
    
    # List view configuration
    list_title = "Teams"
    list_columns = ['name', 'description', 'is_private', 'created_by', 'created_at', 'member_count']
    list_template = 'collaborative/team_list.html'
    
    # Search configuration
    search_columns = ['name', 'description', 'created_by.username']
    search_form_query_rel_fields = {'created_by': [['username', 'contains', '']]}
    
    # Show view configuration
    show_title = "Team Details"
    show_columns = ['name', 'slug', 'description', 'is_private', 'created_by', 'created_at', 'updated_at']
    show_template = 'collaborative/team_show.html'
    
    # Edit view configuration
    edit_title = "Edit Team"
    edit_columns = ['name', 'description', 'is_private']
    edit_form = TeamForm
    edit_template = 'collaborative/team_edit.html'
    
    # Add view configuration
    add_title = "Create Team"
    add_columns = ['name', 'description', 'is_private']
    add_form = TeamForm
    add_template = 'collaborative/team_add.html'
    
    # Ordering
    base_order = ('created_at', 'desc')
    
    # Permissions
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
    
    def __init__(self):
        super().__init__()
        self._team_service: ITeamService = None

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
                        context={"error": str(e)}
                    )
        return self._team_service

    def pre_add(self, item: Team) -> None:
        """Pre-processing before adding a team."""
        try:
            # Set created_by to current user
            item.created_by_user_id = self.appbuilder.sm.user.id
            
            # Generate slug from name
            item.slug = ValidationHelper.generate_slug(item.name)
            
            # Validate team name is unique
            existing = self.datamodel.get_first(name=item.name)
            if existing:
                flash("A team with this name already exists", "error")
                raise IntegrityError("Team name must be unique", None, None)
                
        except Exception as e:
            self.logger.error(f"Error in pre_add: {e}")
            raise

    def post_add(self, item: Team) -> None:
        """Post-processing after adding a team."""
        try:
            # Automatically add the creator as a team owner
            if hasattr(self, 'team_service') and self.team_service:
                self.team_service.add_team_member(
                    team_id=item.id,
                    user_id=item.created_by_user_id,
                    role=TeamRole.OWNER,
                    invited_by_user_id=item.created_by_user_id
                )
            
            # Audit team creation
            self.audit_user_action(
                "team_created",
                user_id=item.created_by_user_id,
                resource_type="team",
                resource_id=str(item.id),
                outcome="success"
            )
            
            flash(f"Team '{item.name}' created successfully", "success")
            
        except Exception as e:
            self.logger.error(f"Error in post_add: {e}")
            flash("Team created but there was an error setting up membership", "warning")

    def pre_update(self, item: Team) -> None:
        """Pre-processing before updating a team."""
        try:
            # Check if user has permission to edit this team
            if hasattr(self, 'team_service') and self.team_service:
                if not self.team_service.has_team_permission(
                    self.appbuilder.sm.user.id, 
                    item.id, 
                    "can_edit"
                ):
                    flash("You don't have permission to edit this team", "error")
                    raise PermissionError("Insufficient permissions to edit team")
            
            # Update slug if name changed
            if item.name:
                item.slug = ValidationHelper.generate_slug(item.name)
                
        except Exception as e:
            self.logger.error(f"Error in pre_update: {e}")
            raise

    def pre_delete(self, item: Team) -> None:
        """Pre-processing before deleting a team."""
        try:
            # Check if user has permission to delete this team
            if hasattr(self, 'team_service') and self.team_service:
                if not self.team_service.has_team_permission(
                    self.appbuilder.sm.user.id, 
                    item.id, 
                    "can_delete"
                ):
                    flash("You don't have permission to delete this team", "error")
                    raise PermissionError("Insufficient permissions to delete team")
            
            # Audit team deletion
            self.audit_user_action(
                "team_deleted",
                user_id=self.appbuilder.sm.user.id,
                resource_type="team",
                resource_id=str(item.id),
                outcome="success"
            )
            
        except Exception as e:
            self.logger.error(f"Error in pre_delete: {e}")
            raise

    @expose('/members/<int:team_id>')
    @has_access
    def team_members(self, team_id: int):
        """Show team members and manage membership."""
        try:
            # Get team details
            team = self.datamodel.get(team_id)
            if not team:
                flash("Team not found", "error")
                return redirect(url_for('TeamModelView.list'))
            
            # Check if user has permission to view team members
            if hasattr(self, 'team_service') and self.team_service:
                if not self.team_service.has_team_permission(
                    self.appbuilder.sm.user.id, 
                    team_id, 
                    "can_view_members"
                ):
                    flash("You don't have permission to view team members", "error")
                    return redirect(url_for('TeamModelView.list'))
            
            # Get team members (would need to be implemented in team service)
            members = []  # self.team_service.get_team_members(team_id)
            
            # Get available users for adding new members
            available_users = self.appbuilder.sm.get_all_users()
            
            return self.render_template(
                'collaborative/team_members.html',
                team=team,
                members=members,
                available_users=available_users,
                team_roles=TeamRole,
                add_member_form=TeamMemberForm()
            )
            
        except Exception as e:
            self.logger.error(f"Error in team_members: {e}")
            flash("An error occurred while loading team members", "error")
            return redirect(url_for('TeamModelView.list'))

    @expose('/add_member/<int:team_id>', methods=['POST'])
    @has_access
    def add_member(self, team_id: int):
        """Add a member to the team."""
        try:
            form = TeamMemberForm()
            
            if form.validate_on_submit():
                # Check permissions
                if hasattr(self, 'team_service') and self.team_service:
                    if not self.team_service.has_team_permission(
                        self.appbuilder.sm.user.id, 
                        team_id, 
                        "can_add_members"
                    ):
                        flash("You don't have permission to add team members", "error")
                        return redirect(url_for('TeamModelView.team_members', team_id=team_id))
                    
                    # Add team member
                    success = self.team_service.add_team_member(
                        team_id=team_id,
                        user_id=form.user_id.data,
                        role=TeamRole(form.role.data),
                        invited_by_user_id=self.appbuilder.sm.user.id
                    )
                    
                    if success:
                        flash("Team member added successfully", "success")
                        
                        # Audit member addition
                        self.audit_user_action(
                            "team_member_added",
                            user_id=self.appbuilder.sm.user.id,
                            resource_type="team",
                            resource_id=str(team_id),
                            outcome="success",
                            target_user_id=form.user_id.data
                        )
                    else:
                        flash("Failed to add team member", "error")
                else:
                    flash("Team service not available", "error")
            else:
                flash("Invalid form data", "error")
                
        except Exception as e:
            self.logger.error(f"Error adding team member: {e}")
            flash("An error occurred while adding the team member", "error")
            
        return redirect(url_for('TeamModelView.team_members', team_id=team_id))

    @expose('/remove_member/<int:team_id>/<int:user_id>', methods=['POST'])
    @has_access
    def remove_member(self, team_id: int, user_id: int):
        """Remove a member from the team."""
        try:
            # Check permissions
            if hasattr(self, 'team_service') and self.team_service:
                if not self.team_service.has_team_permission(
                    self.appbuilder.sm.user.id, 
                    team_id, 
                    "can_remove_members"
                ):
                    flash("You don't have permission to remove team members", "error")
                    return redirect(url_for('TeamModelView.team_members', team_id=team_id))
                
                # Remove team member
                success = self.team_service.remove_team_member(
                    team_id=team_id,
                    user_id=user_id,
                    removed_by_user_id=self.appbuilder.sm.user.id
                )
                
                if success:
                    flash("Team member removed successfully", "success")
                    
                    # Audit member removal
                    self.audit_user_action(
                        "team_member_removed",
                        user_id=self.appbuilder.sm.user.id,
                        resource_type="team",
                        resource_id=str(team_id),
                        outcome="success",
                        target_user_id=user_id
                    )
                else:
                    flash("Failed to remove team member", "error")
            else:
                flash("Team service not available", "error")
                
        except Exception as e:
            self.logger.error(f"Error removing team member: {e}")
            flash("An error occurred while removing the team member", "error")
            
        return redirect(url_for('TeamModelView.team_members', team_id=team_id))

    def list_query_filter(self, query):
        """Filter teams based on user permissions."""
        try:
            # If user is admin, show all teams
            if self.appbuilder.sm.has_access("can_list_all", "Team"):
                return query
            
            # Otherwise, show only teams where user is a member
            user_id = self.appbuilder.sm.user.id
            
            # This would need to be implemented with proper SQL joins
            # For now, return the query as-is
            return query
            
        except Exception as e:
            self.logger.error(f"Error in list_query_filter: {e}")
            return query

    @expose('/my_teams')
    @has_access
    def my_teams(self):
        """Show teams where the current user is a member."""
        try:
            user_id = self.appbuilder.sm.user.id
            
            # Get user's teams
            if hasattr(self, 'team_service') and self.team_service:
                teams = self.team_service.get_user_teams(user_id)
            else:
                teams = []
            
            return self.render_template(
                'collaborative/my_teams.html',
                teams=teams
            )
            
        except Exception as e:
            self.logger.error(f"Error in my_teams: {e}")
            flash("An error occurred while loading your teams", "error")
            return redirect(url_for('TeamModelView.list'))

    def _get_list_query(self, filters=None, order_column='', order_direction=''):
        """Override to add custom filtering logic."""
        query = super()._get_list_query(filters, order_column, order_direction)
        return self.list_query_filter(query)

    @property
    def _prettify_name(self):
        """Return a prettier name for the view."""
        return "Teams"

    @property
    def _prettify_column(self):
        """Return prettier column names."""
        return {
            'created_by': 'Created By',
            'created_at': 'Created At',
            'updated_at': 'Updated At',
            'is_private': 'Private',
            'member_count': 'Members'
        }