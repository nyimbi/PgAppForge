"""
Workspace Management Views for PgAppForge collaborative features.

Provides administrative and user-facing views for workspace management,
including workspace creation, collaborator management, and access control.
"""

from flask import flash, redirect, url_for, request, jsonify
from pgappforge import ModelView, BaseView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import protect
from pgappforge.widgets import ListWidget, ShowWidget
from pgappforge.forms import DynamicForm
from wtforms import StringField, TextAreaField, SelectField, HiddenField
from wtforms.validators import DataRequired, Length
from sqlalchemy.exc import IntegrityError
from typing import Any, Dict, List

from ..core.workspace_manager import Workspace, WorkspaceType, AccessLevel
from ..interfaces.base_interfaces import IWorkspaceService, ITeamService
from ..utils.error_handling import CollaborativeError, ErrorHandlingMixin
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType
from ..utils.validation import ValidationHelper


class WorkspaceForm(DynamicForm):
    """Form for creating and editing workspaces."""
    name = StringField(
        'Workspace Name', 
        validators=[DataRequired(), Length(min=1, max=100)],
        description="Name of the workspace"
    )
    description = TextAreaField(
        'Description',
        validators=[Length(max=500)],
        description="Brief description of the workspace's purpose"
    )
    workspace_type = SelectField(
        'Type',
        choices=[(wtype.value, wtype.value.title()) for wtype in WorkspaceType],
        validators=[DataRequired()],
        description="Type of workspace"
    )
    team_id = SelectField(
        'Team',
        coerce=int,
        description="Optional: Associate workspace with a team"
    )


class CollaboratorForm(DynamicForm):
    """Form for adding workspace collaborators."""
    user_id = SelectField(
        'User',
        coerce=int,
        validators=[DataRequired()],
        description="Select a user to add as collaborator"
    )
    access_level = SelectField(
        'Access Level',
        choices=[(level.value, level.value.title()) for level in AccessLevel],
        validators=[DataRequired()],
        description="Access level for the user"
    )


class WorkspaceModelView(ModelView, ErrorHandlingMixin, CollaborativeAuditMixin):
    """
    ModelView for Workspace management.
    
    Provides administrative interface for workspace creation, editing,
    collaborator management, and workspace-based collaborative features.
    """

    datamodel = SQLAInterface(Workspace)
    
    # List view configuration
    list_title = "Workspaces"
    list_columns = ['name', 'workspace_type', 'owner', 'team', 'created_at', 'collaborator_count']
    list_template = 'collaborative/workspace_list.html'
    
    # Search configuration
    search_columns = ['name', 'description', 'owner.username', 'team.name']
    search_form_query_rel_fields = {
        'owner': [['username', 'contains', '']],
        'team': [['name', 'contains', '']]
    }
    
    # Show view configuration
    show_title = "Workspace Details"
    show_columns = ['name', 'slug', 'description', 'workspace_type', 'owner', 'team', 'created_at', 'updated_at']
    show_template = 'collaborative/workspace_show.html'
    
    # Edit view configuration
    edit_title = "Edit Workspace"
    edit_columns = ['name', 'description', 'workspace_type']
    edit_form = WorkspaceForm
    edit_template = 'collaborative/workspace_edit.html'
    
    # Add view configuration
    add_title = "Create Workspace"
    add_columns = ['name', 'description', 'workspace_type', 'team_id']
    add_form = WorkspaceForm
    add_template = 'collaborative/workspace_add.html'
    
    # Ordering
    base_order = ('created_at', 'desc')
    
    # Permissions
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
    
    def __init__(self):
        super().__init__()
        self._workspace_service: IWorkspaceService = None
        self._team_service: ITeamService = None

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
                        context={"error": str(e)}
                    )
        return self._workspace_service

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

    def pre_add(self, item: Workspace) -> None:
        """Pre-processing before adding a workspace."""
        try:
            # Set owner to current user
            item.owner_id = self.appbuilder.sm.user.id
            
            # Generate slug from name
            item.slug = ValidationHelper.generate_slug(item.name)
            
            # Validate workspace name is unique for the user
            existing = self.datamodel.get_first(name=item.name, owner_id=item.owner_id)
            if existing:
                flash("You already have a workspace with this name", "error")
                raise IntegrityError("Workspace name must be unique per user", None, None)
                
        except Exception as e:
            self.logger.error(f"Error in pre_add: {e}")
            raise

    def post_add(self, item: Workspace) -> None:
        """Post-processing after adding a workspace."""
        try:
            # Automatically add the owner as a collaborator with admin access
            if hasattr(self, 'workspace_service') and self.workspace_service:
                self.workspace_service.add_workspace_collaborator(
                    workspace_id=item.id,
                    user_id=item.owner_id,
                    access_level=AccessLevel.ADMIN,
                    added_by_user_id=item.owner_id
                )
            
            # Audit workspace creation
            self.audit_user_action(
                "workspace_created",
                user_id=item.owner_id,
                resource_type="workspace",
                resource_id=str(item.id),
                outcome="success"
            )
            
            flash(f"Workspace '{item.name}' created successfully", "success")
            
        except Exception as e:
            self.logger.error(f"Error in post_add: {e}")
            flash("Workspace created but there was an error setting up access", "warning")

    def pre_update(self, item: Workspace) -> None:
        """Pre-processing before updating a workspace."""
        try:
            # Check if user has permission to edit this workspace
            if hasattr(self, 'workspace_service') and self.workspace_service:
                if not self.workspace_service.has_workspace_access(
                    self.appbuilder.sm.user.id, 
                    item.id, 
                    AccessLevel.ADMIN
                ):
                    flash("You don't have permission to edit this workspace", "error")
                    raise PermissionError("Insufficient permissions to edit workspace")
            
            # Update slug if name changed
            if item.name:
                item.slug = ValidationHelper.generate_slug(item.name)
                
        except Exception as e:
            self.logger.error(f"Error in pre_update: {e}")
            raise

    def pre_delete(self, item: Workspace) -> None:
        """Pre-processing before deleting a workspace."""
        try:
            # Check if user has permission to delete this workspace
            if hasattr(self, 'workspace_service') and self.workspace_service:
                if not self.workspace_service.has_workspace_access(
                    self.appbuilder.sm.user.id, 
                    item.id, 
                    AccessLevel.ADMIN
                ):
                    flash("You don't have permission to delete this workspace", "error")
                    raise PermissionError("Insufficient permissions to delete workspace")
            
            # Audit workspace deletion
            self.audit_user_action(
                "workspace_deleted",
                user_id=self.appbuilder.sm.user.id,
                resource_type="workspace",
                resource_id=str(item.id),
                outcome="success"
            )
            
        except Exception as e:
            self.logger.error(f"Error in pre_delete: {e}")
            raise

    @expose('/collaborators/<int:workspace_id>')
    @has_access
    def workspace_collaborators(self, workspace_id: int):
        """Show workspace collaborators and manage access."""
        try:
            # Get workspace details
            workspace = self.datamodel.get(workspace_id)
            if not workspace:
                flash("Workspace not found", "error")
                return redirect(url_for('WorkspaceModelView.list'))
            
            # Check if user has permission to view collaborators
            if hasattr(self, 'workspace_service') and self.workspace_service:
                if not self.workspace_service.has_workspace_access(
                    self.appbuilder.sm.user.id, 
                    workspace_id, 
                    AccessLevel.READ
                ):
                    flash("You don't have permission to view this workspace", "error")
                    return redirect(url_for('WorkspaceModelView.list'))
            
            # Get workspace collaborators (would need to be implemented in workspace service)
            collaborators = []  # self.workspace_service.get_workspace_collaborators(workspace_id)
            
            # Get available users for adding new collaborators
            available_users = self.appbuilder.sm.get_all_users()
            
            # Check if user can add collaborators
            can_add_collaborators = False
            if hasattr(self, 'workspace_service') and self.workspace_service:
                can_add_collaborators = self.workspace_service.has_workspace_access(
                    self.appbuilder.sm.user.id, 
                    workspace_id, 
                    AccessLevel.ADMIN
                )
            
            return self.render_template(
                'collaborative/workspace_collaborators.html',
                workspace=workspace,
                collaborators=collaborators,
                available_users=available_users,
                access_levels=AccessLevel,
                add_collaborator_form=CollaboratorForm(),
                can_add_collaborators=can_add_collaborators
            )
            
        except Exception as e:
            self.logger.error(f"Error in workspace_collaborators: {e}")
            flash("An error occurred while loading workspace collaborators", "error")
            return redirect(url_for('WorkspaceModelView.list'))

    @expose('/add_collaborator/<int:workspace_id>', methods=['POST'])
    @has_access
    def add_collaborator(self, workspace_id: int):
        """Add a collaborator to the workspace."""
        try:
            form = CollaboratorForm()
            
            if form.validate_on_submit():
                # Check permissions
                if hasattr(self, 'workspace_service') and self.workspace_service:
                    if not self.workspace_service.has_workspace_access(
                        self.appbuilder.sm.user.id, 
                        workspace_id, 
                        AccessLevel.ADMIN
                    ):
                        flash("You don't have permission to add collaborators", "error")
                        return redirect(url_for('WorkspaceModelView.workspace_collaborators', workspace_id=workspace_id))
                    
                    # Add workspace collaborator
                    success = self.workspace_service.add_workspace_collaborator(
                        workspace_id=workspace_id,
                        user_id=form.user_id.data,
                        access_level=AccessLevel(form.access_level.data),
                        added_by_user_id=self.appbuilder.sm.user.id
                    )
                    
                    if success:
                        flash("Collaborator added successfully", "success")
                        
                        # Audit collaborator addition
                        self.audit_user_action(
                            "workspace_collaborator_added",
                            user_id=self.appbuilder.sm.user.id,
                            resource_type="workspace",
                            resource_id=str(workspace_id),
                            outcome="success",
                            target_user_id=form.user_id.data
                        )
                    else:
                        flash("Failed to add collaborator", "error")
                else:
                    flash("Workspace service not available", "error")
            else:
                flash("Invalid form data", "error")
                
        except Exception as e:
            self.logger.error(f"Error adding collaborator: {e}")
            flash("An error occurred while adding the collaborator", "error")
            
        return redirect(url_for('WorkspaceModelView.workspace_collaborators', workspace_id=workspace_id))

    @expose('/remove_collaborator/<int:workspace_id>/<int:user_id>', methods=['POST'])
    @has_access
    def remove_collaborator(self, workspace_id: int, user_id: int):
        """Remove a collaborator from the workspace."""
        try:
            # Check permissions
            if hasattr(self, 'workspace_service') and self.workspace_service:
                if not self.workspace_service.has_workspace_access(
                    self.appbuilder.sm.user.id, 
                    workspace_id, 
                    AccessLevel.ADMIN
                ):
                    flash("You don't have permission to remove collaborators", "error")
                    return redirect(url_for('WorkspaceModelView.workspace_collaborators', workspace_id=workspace_id))
                
                # Remove workspace collaborator
                success = self.workspace_service.remove_workspace_collaborator(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    removed_by_user_id=self.appbuilder.sm.user.id
                )
                
                if success:
                    flash("Collaborator removed successfully", "success")
                    
                    # Audit collaborator removal
                    self.audit_user_action(
                        "workspace_collaborator_removed",
                        user_id=self.appbuilder.sm.user.id,
                        resource_type="workspace",
                        resource_id=str(workspace_id),
                        outcome="success",
                        target_user_id=user_id
                    )
                else:
                    flash("Failed to remove collaborator", "error")
            else:
                flash("Workspace service not available", "error")
                
        except Exception as e:
            self.logger.error(f"Error removing collaborator: {e}")
            flash("An error occurred while removing the collaborator", "error")
            
        return redirect(url_for('WorkspaceModelView.workspace_collaborators', workspace_id=workspace_id))

    @expose('/my_workspaces')
    @has_access
    def my_workspaces(self):
        """Show workspaces where the current user is a collaborator."""
        try:
            user_id = self.appbuilder.sm.user.id
            
            # Get user's workspaces
            if hasattr(self, 'workspace_service') and self.workspace_service:
                workspaces = self.workspace_service.get_user_workspaces(user_id)
            else:
                workspaces = []
            
            return self.render_template(
                'collaborative/my_workspaces.html',
                workspaces=workspaces
            )
            
        except Exception as e:
            self.logger.error(f"Error in my_workspaces: {e}")
            flash("An error occurred while loading your workspaces", "error")
            return redirect(url_for('WorkspaceModelView.list'))

    @expose('/workspace_dashboard/<int:workspace_id>')
    @has_access
    def workspace_dashboard(self, workspace_id: int):
        """Show collaborative dashboard for a specific workspace."""
        try:
            # Check access
            if hasattr(self, 'workspace_service') and self.workspace_service:
                if not self.workspace_service.has_workspace_access(
                    self.appbuilder.sm.user.id, 
                    workspace_id, 
                    AccessLevel.READ
                ):
                    flash("You don't have permission to view this workspace", "error")
                    return redirect(url_for('WorkspaceModelView.list'))
            
            # Get workspace details
            workspace = self.datamodel.get(workspace_id)
            if not workspace:
                flash("Workspace not found", "error")
                return redirect(url_for('WorkspaceModelView.list'))
            
            # Get dashboard data (would need to be implemented)
            dashboard_data = {
                'recent_activity': [],
                'active_collaborators': [],
                'recent_comments': [],
                'shared_resources': []
            }
            
            return self.render_template(
                'collaborative/workspace_dashboard.html',
                workspace=workspace,
                dashboard_data=dashboard_data
            )
            
        except Exception as e:
            self.logger.error(f"Error in workspace_dashboard: {e}")
            flash("An error occurred while loading the workspace dashboard", "error")
            return redirect(url_for('WorkspaceModelView.list'))

    def list_query_filter(self, query):
        """Filter workspaces based on user permissions."""
        try:
            # If user is admin, show all workspaces
            if self.appbuilder.sm.has_access("can_list_all", "Workspace"):
                return query
            
            # Otherwise, show only workspaces where user is a collaborator
            user_id = self.appbuilder.sm.user.id
            
            # This would need to be implemented with proper SQL joins
            # For now, return workspaces owned by the user
            return query.filter(Workspace.owner_id == user_id)
            
        except Exception as e:
            self.logger.error(f"Error in list_query_filter: {e}")
            return query

    def _get_list_query(self, filters=None, order_column='', order_direction=''):
        """Override to add custom filtering logic."""
        query = super()._get_list_query(filters, order_column, order_direction)
        return self.list_query_filter(query)

    def _init_forms(self):
        """Initialize forms with dynamic choices."""
        super()._init_forms()
        
        # Add team choices to the form
        if hasattr(self, 'team_service') and self.team_service:
            try:
                user_teams = self.team_service.get_user_teams(self.appbuilder.sm.user.id)
                team_choices = [(0, "No Team")] + [(team['id'], team['name']) for team in user_teams]
                
                if hasattr(self.add_form, 'team_id'):
                    self.add_form.team_id.choices = team_choices
                if hasattr(self.edit_form, 'team_id'):
                    self.edit_form.team_id.choices = team_choices
            except Exception as e:
                self.logger.error(f"Error loading team choices: {e}")

    @property
    def _prettify_name(self):
        """Return a prettier name for the view."""
        return "Workspaces"

    @property
    def _prettify_column(self):
        """Return prettier column names."""
        return {
            'owner': 'Owner',
            'created_at': 'Created At',
            'updated_at': 'Updated At',
            'workspace_type': 'Type',
            'collaborator_count': 'Collaborators'
        }