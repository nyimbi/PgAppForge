"""
Workflow-Aware Views for PgAppForge

Extends PgAppForge's ModelView and FormView to support workflow-driven
form sequencing, state management, and intelligent routing.
"""

import logging
import json
from typing import Dict, List, Any, Optional, TYPE_CHECKING

from flask import flash, redirect, url_for, request, session, render_template, jsonify
from flask_babel import lazy_gettext
from pgappforge import ModelView, SimpleFormView, expose, action, has_access
from pgappforge.const import FLAMSG_ERR_SEC_ACCESS_DENIED
from pgappforge.security.decorators import has_access, permission_name
from pgappforge.widgets import ListWidget, ShowWidget, FormWidget
from pgappforge.forms import DynamicForm
from wtforms import Form, StringField, HiddenField
from wtforms.validators import DataRequired

from .mixins import WorkflowStateMixin
from .core import get_workflow_engine, WorkflowDefinition, WorkflowStepDefinition, WorkflowStepType
from .collaboration import CollaborationMixin, get_collaboration_manager

if TYPE_CHECKING:
    from .core import WorkflowState

log = logging.getLogger(__name__)


class WorkflowFormWidget(FormWidget):
    """
    Enhanced form widget that supports workflow navigation and progress tracking.
    """
    template = 'workflow/form_widget.html'

    def __init__(self, extra_args=None):
        super().__init__(extra_args)
        self.extra_args = extra_args or {}


class WorkflowListWidget(ListWidget):
    """
    Enhanced list widget that shows workflow status and progress.
    """
    template = 'workflow/list_widget.html'


class WorkflowShowWidget(ShowWidget):
    """
    Enhanced show widget that displays workflow information.
    """
    template = 'workflow/show_widget.html'


class WorkflowModelView(CollaborationMixin, WorkflowStateMixin, ModelView):
    """
    Workflow-aware ModelView that supports form sequencing and state management.

    This view extends PgAppForge's ModelView to provide:
    - Multi-step form workflows with navigation
    - Persistent state management
    - Conditional form routing
    - Progress tracking
    - Workflow-driven CRUD operations

    Usage:
        class EmployeeView(WorkflowModelView):
            datamodel = SQLAInterface(Employee)

            workflow_definition = {
                'name': 'employee_onboarding',
                'steps': [
                    {'form': 'personal_info', 'fields': ['name', 'email']},
                    {'form': 'employment_details', 'fields': ['position', 'salary']},
                    {'form': 'review', 'fields': ['review_comments']}
                ]
            }
    """

    # Workflow configuration (override in subclasses)
    workflow_definition = None
    workflow_auto_save = True
    workflow_allow_navigation = True
    workflow_require_completion = False
    workflow_validation_strict = True

    # Widget overrides
    list_widget = WorkflowListWidget
    show_widget = WorkflowShowWidget
    add_widget = WorkflowFormWidget
    edit_widget = WorkflowFormWidget

    # Additional workflow-specific permissions
    base_permissions = (ModelView.base_permissions or []) + [
        'can_navigate_workflow',
        'can_restart_workflow',
        'can_skip_workflow_step',
        'can_bypass_workflow',
        'can_workflow_admin'
    ]

    def __init__(self):
        super().__init__()
        self._workflow_steps_cache = {}
        self._setup_workflow()

    def _setup_workflow(self):
        """Initialize workflow configuration."""
        if not self.workflow_definition:
            return

        # Register workflow definition with engine
        engine = get_workflow_engine()

        # Convert dict to WorkflowDefinition if needed
        if isinstance(self.workflow_definition, dict):
            self.workflow_definition = self._dict_to_workflow_definition(self.workflow_definition)

        engine.register_workflow(self.workflow_definition)

    def _dict_to_workflow_definition(self, workflow_dict: Dict[str, Any]) -> WorkflowDefinition:
        """Convert dictionary configuration to WorkflowDefinition."""
        steps = []

        for i, step_config in enumerate(workflow_dict.get('steps', [])):
            step_def = WorkflowStepDefinition(
                id=step_config.get('id', f"step_{i}"),
                name=step_config.get('name', step_config.get('form', f"Step {i+1}")),
                step_type=WorkflowStepType.FORM,
                form_fields=step_config.get('fields'),
                required_role=step_config.get('required_role'),
                conditions=step_config.get('conditions'),
                next_steps=[f"step_{i+1}"] if i < len(workflow_dict.get('steps', [])) - 1 else None,
                auto_save=step_config.get('auto_save', self.workflow_auto_save),
                allow_skip=step_config.get('allow_skip', False)
            )
            steps.append(step_def)

        return WorkflowDefinition(
            name=workflow_dict['name'],
            description=workflow_dict.get('description', ''),
            version=workflow_dict.get('version', '1.0'),
            steps=steps,
            allow_navigation=workflow_dict.get('allow_navigation', self.workflow_allow_navigation)
        )

    # ===== WORKFLOW-DRIVEN CRUD OPERATIONS =====

    def can_create(self) -> bool:
        """Check if user can create new entities considering workflow state."""
        # Check basic ModelView permissions
        if not super().can_create():
            return False

        # Check workflow-specific permissions
        if self.workflow_definition and self.workflow_require_completion:
            # If workflow completion is required, check if user has completed prerequisites
            return self._check_workflow_prerequisites()

        return True

    def can_edit(self, item) -> bool:
        """Check if user can edit entity considering workflow state."""
        # Check basic ModelView permissions
        if not super().can_edit():
            return False

        # Check workflow state constraints
        if hasattr(item, 'workflow_state') and item.workflow_state:
            workflow_state = item.workflow_state
            
            # Check if workflow allows editing in current state
            if workflow_state.status == 'completed' and not self.has_access('can_edit_completed_workflow'):
                return False
                
            # Check if current user can access current step
            if not workflow_state.can_user_access_step(workflow_state.current_step):
                return False

        return True

    def can_delete(self, item) -> bool:
        """Check if user can delete entity considering workflow state."""
        # Check basic ModelView permissions
        if not super().can_delete():
            return False

        # Workflow state constraints
        if hasattr(item, 'workflow_state') and item.workflow_state:
            workflow_state = item.workflow_state
            
            # Prevent deletion of active workflows unless user has special permission
            if workflow_state.status == 'in_progress' and not self.has_access('can_delete_active_workflow'):
                return False

        return True

    def add(self):
        """Override add method to handle workflow-aware creation."""
        if not self.can_create():
            flash(FLAMSG_ERR_SEC_ACCESS_DENIED, "danger")
            return redirect(url_for(self.route_base + ".list"))

        # Check if this model uses workflows
        if self.workflow_definition:
            # Start with first workflow step
            first_step = self.workflow_definition.steps[0] if self.workflow_definition.steps else None
            if first_step:
                return redirect(url_for(f'{self.__class__.__name__}.add_step', step_id=first_step.id))

        # Fallback to standard add
        return super().add()

    def edit(self, pk):
        """Override edit method to handle workflow-aware editing."""
        item = self.datamodel.get(pk)
        if not item:
            flash(lazy_gettext('Record not found'), 'error')
            return redirect(self.get_redirect())

        if not self.can_edit(item):
            flash(FLAMSG_ERR_SEC_ACCESS_DENIED, "danger")
            return redirect(url_for(self.route_base + ".list"))

        # Check if item has active workflow
        if hasattr(item, 'workflow_state') and item.workflow_state and item.workflow_state.status == 'in_progress':
            # Redirect to workflow step editing
            current_step = item.workflow_state.current_step
            return redirect(url_for(f'{self.__class__.__name__}.edit_step', pk=pk, step_id=current_step))

        # Fallback to standard edit
        return super().edit(pk)

    def delete(self, pk):
        """Override delete method to handle workflow-aware deletion."""
        item = self.datamodel.get(pk)
        if not item:
            flash(lazy_gettext('Record not found'), 'error')
            return redirect(self.get_redirect())

        if not self.can_delete(item):
            flash(FLAMSG_ERR_SEC_ACCESS_DENIED, "danger")
            return redirect(url_for(self.route_base + ".list"))

        try:
            # Handle workflow cleanup before deletion
            if hasattr(item, 'workflow_state') and item.workflow_state:
                workflow_state = item.workflow_state
                
                # Log workflow termination
                workflow_state.add_to_history('system', 'workflow_terminated', {
                    'reason': 'entity_deleted',
                    'user_id': getattr(g.user, 'id', None) if hasattr(g, 'user') else None
                })
                
                # Clean up workflow state
                self.datamodel.session.delete(workflow_state)

            # Perform deletion
            self.datamodel.delete(item)
            flash(lazy_gettext('Record deleted successfully'), 'success')

        except Exception as e:
            flash(lazy_gettext('Error deleting record: %(error)s', error=str(e)), 'error')
            log.error(f"Error deleting entity with workflow: {e}")
            self.datamodel.session.rollback()

        return redirect(self.get_redirect())

    def _check_workflow_prerequisites(self) -> bool:
        """Check if user has completed required workflows."""
        # This can be customized per view to check specific prerequisites
        # For example, checking if user has completed training workflows
        return True

    def _validate_workflow_transition(self, workflow_state: 'WorkflowState', 
                                    from_step: str, to_step: str) -> bool:
        """Validate if workflow transition is allowed."""
        if not self.workflow_validation_strict:
            return True

        engine = get_workflow_engine()
        return engine.validate_step_transition(workflow_state, from_step, to_step)

    def _handle_workflow_violations(self, violation_type: str, details: Dict[str, Any]):
        """Handle workflow violations and security incidents."""
        log.warning(f"Workflow violation detected: {violation_type}", extra=details)
        
        # This could integrate with security monitoring systems
        # flash(lazy_gettext('Workflow violation detected'), 'warning')

    # ===== ENHANCED WORKFLOW METHODS =====

    def get_form_columns(self, form_name: Optional[str] = None) -> List[str]:
        """Get form columns for current workflow step."""
        if not self.workflow_definition or not form_name:
            return self.add_columns or self.edit_columns or []

        # Find step definition
        for step in self.workflow_definition.steps:
            if step.id == form_name and step.form_fields:
                return step.form_fields

        return self.add_columns or self.edit_columns or []

    def get_current_workflow_step(self, pk: Optional[int] = None) -> Optional[str]:
        """Get current workflow step for an entity."""
        if not self.workflow_definition:
            return None

        if pk:
            # Get step from entity's workflow state
            item = self.datamodel.get(pk)
            if hasattr(item, 'get_current_workflow_step'):
                return item.get_current_workflow_step()

        # Get step from session workflow state
        workflow_state = self.get_workflow_state_from_session(self.workflow_definition.name)
        return workflow_state.current_step if workflow_state else None

    def get_workflow_form_data(self, step_id: str, pk: Optional[int] = None) -> Dict[str, Any]:
        """Get form data for a workflow step."""
        if pk:
            # Get from entity's workflow state
            item = self.datamodel.get(pk)
            if hasattr(item, 'get_workflow_form_data'):
                return item.get_workflow_form_data(step_id)

        # Get from session workflow state
        workflow_state = self.get_workflow_state_from_session(self.workflow_definition.name)
        if workflow_state:
            return workflow_state.get_form_data_for_step(step_id)

        return {}

    @expose('/add/<step_id>')
    @has_access
    def add_step(self, step_id):
        """Add form with specific workflow step."""
        if not self.workflow_definition:
            return self.add()

        # Get or create workflow state
        workflow_state = self.get_or_create_workflow_state(
            workflow_name=self.workflow_definition.name,
            entity_type=self.datamodel.obj.__name__
        )

        # Check if step is accessible
        if step_id != workflow_state.current_step and not workflow_state.can_navigate_to_step(step_id):
            flash(lazy_gettext('Cannot access this workflow step'), 'error')
            return redirect(url_for(f'{self.__class__.__name__}.add_step', step_id=workflow_state.current_step))

        # Get step definition and form columns
        step_def = get_workflow_engine().get_step_definition(self.workflow_definition.name, step_id)
        if not step_def:
            flash(lazy_gettext('Invalid workflow step'), 'error')
            return self.add()

        # Override form columns for this step
        original_add_columns = self.add_columns
        self.add_columns = step_def.form_fields or self.add_columns

        try:
            # Get existing form data
            form_data = self.get_workflow_form_data(step_id)

            # Create form
            form = self.add_form.refresh()

            # Populate form with existing data
            if form_data:
                for field_name, value in form_data.items():
                    if hasattr(form, field_name):
                        getattr(form, field_name).data = value

            # Handle form submission
            if form.validate_on_submit():
                return self._handle_workflow_form_submission(form, step_id, workflow_state)

            # Render form with workflow context
            context = self.get_workflow_context(self.workflow_definition.name)
            context.update({
                'form': form,
                'current_step_id': step_id,
                'step_definition': step_def,
                'is_workflow_form': True
            })

            return self.render_template(
                self.add_template,
                title=lazy_gettext(f'Add {self.datamodel.obj.__name__} - {step_def.name}'),
                **context
            )

        finally:
            # Restore original columns
            self.add_columns = original_add_columns

    @expose('/edit/<pk>/<step_id>')
    @has_access
    def edit_step(self, pk, step_id):
        """Edit form with specific workflow step."""
        if not self.workflow_definition:
            return self.edit(pk)

        item = self.datamodel.get(pk)
        if not item:
            flash(lazy_gettext('Record not found'), 'error')
            return redirect(self.get_redirect())

        # Validate edit permissions with workflow awareness
        if not self.can_edit(item):
            flash(FLAMSG_ERR_SEC_ACCESS_DENIED, "danger")
            return redirect(self.get_redirect())

        # Get workflow state
        workflow_state = None
        if hasattr(item, 'workflow_state'):
            workflow_state = item.workflow_state
        else:
            workflow_state = self.get_workflow_state_from_session(self.workflow_definition.name)

        if not workflow_state:
            flash(lazy_gettext('No active workflow found'), 'error')
            return self.edit(pk)

        # Check step access
        if step_id != workflow_state.current_step and not workflow_state.can_navigate_to_step(step_id):
            flash(lazy_gettext('Cannot access this workflow step'), 'error')
            return redirect(url_for(f'{self.__class__.__name__}.edit_step',
                                  pk=pk, step_id=workflow_state.current_step))

        # Get step definition
        step_def = get_workflow_engine().get_step_definition(self.workflow_definition.name, step_id)
        if not step_def:
            flash(lazy_gettext('Invalid workflow step'), 'error')
            return self.edit(pk)

        # Override form columns
        original_edit_columns = self.edit_columns
        self.edit_columns = step_def.form_fields or self.edit_columns

        try:
            # Create and populate form
            form = self.edit_form.refresh(obj=item)

            # Populate with workflow data
            form_data = self.get_workflow_form_data(step_id, pk)
            if form_data:
                for field_name, value in form_data.items():
                    if hasattr(form, field_name):
                        getattr(form, field_name).data = value

            # Handle form submission
            if form.validate_on_submit():
                return self._handle_workflow_form_submission(form, step_id, workflow_state, item)

            # Render with workflow context
            context = self.get_workflow_context(self.workflow_definition.name)
            context.update({
                'form': form,
                'pk': pk,
                'current_step_id': step_id,
                'step_definition': step_def,
                'is_workflow_form': True
            })

            return self.render_template(
                self.edit_template,
                title=lazy_gettext(f'Edit {self.datamodel.obj.__name__} - {step_def.name}'),
                **context
            )

        finally:
            self.edit_columns = original_edit_columns

    def _handle_workflow_form_submission(self, form, step_id: str, workflow_state: 'WorkflowState',
                                       item=None) -> Any:
        """Handle form submission for workflow steps."""
        try:
            # Extract form data
            form_data = {}
            for field in form:
                if field.name != 'csrf_token':
                    form_data[field.name] = field.data

            # Validate workflow transition before processing
            if 'workflow_next' in request.form:
                next_steps = workflow_state.available_next_steps
                if next_steps and not self._validate_workflow_transition(workflow_state, step_id, next_steps[0]):
                    flash(lazy_gettext('Invalid workflow transition'), 'error')
                    return self.get_redirect()

            # Save form data to workflow state
            workflow_state.set_form_data_for_step(step_id, form_data)

            # Update entity if editing
            if item:
                # Apply form data to entity
                form.populate_obj(item)
                self.datamodel.edit(item)
                flash(lazy_gettext('Step data saved successfully'), 'success')
            else:
                # Store data for final entity creation
                if self.workflow_auto_save:
                    workflow_state.add_to_history(step_id, 'auto_saved', {'form_data': form_data})

            # Determine next action
            if 'workflow_next' in request.form:
                return self._handle_workflow_navigation(workflow_state, 'next', item)
            elif 'workflow_previous' in request.form:
                return self._handle_workflow_navigation(workflow_state, 'previous', item)
            elif 'workflow_save' in request.form:
                if item:
                    return redirect(url_for(f'{self.__class__.__name__}.show', pk=item.id))
                else:
                    # Create entity from all workflow data
                    return self._create_entity_from_workflow(workflow_state)

            # Default: advance to next step
            return self._handle_workflow_navigation(workflow_state, 'next', item)

        except Exception as e:
            flash(lazy_gettext('Error saving step data: %(error)s', error=str(e)), 'error')
            log.error(f"Error in workflow form submission: {e}")
            # Rollback any changes
            self.datamodel.session.rollback()
            return self.get_redirect()

    def _handle_workflow_navigation(self, workflow_state: 'WorkflowState', direction: str, item=None) -> Any:
        """Handle workflow navigation (next/previous)."""
        engine = get_workflow_engine()

        if direction == 'next':
            # Get next available step
            if workflow_state.available_next_steps:
                next_step_id = workflow_state.available_next_steps[0]
                
                # Validate transition
                if self._validate_workflow_transition(workflow_state, workflow_state.current_step, next_step_id):
                    if engine.advance_workflow(workflow_state, next_step_id):
                        if item:
                            return redirect(url_for(f'{self.__class__.__name__}.edit_step',
                                                  pk=item.id, step_id=next_step_id))
                        else:
                            return redirect(url_for(f'{self.__class__.__name__}.add_step',
                                                  step_id=next_step_id))
                    else:
                        flash(lazy_gettext('Cannot advance to next step'), 'error')
                else:
                    flash(lazy_gettext('Workflow transition not allowed'), 'error')
                    self._handle_workflow_violations('invalid_transition', {
                        'from_step': workflow_state.current_step,
                        'to_step': next_step_id,
                        'user_id': getattr(g.user, 'id', None) if hasattr(g, 'user') else None
                    })
            else:
                # Workflow completed
                if item:
                    # Mark workflow as completed
                    if hasattr(item, 'complete_workflow'):
                        item.complete_workflow()
                    flash(lazy_gettext('Workflow completed successfully'), 'success')
                    return redirect(url_for(f'{self.__class__.__name__}.show', pk=item.id))
                else:
                    return self._create_entity_from_workflow(workflow_state)

        elif direction == 'previous':
            # Navigate to previous step
            if workflow_state.completed_steps:
                prev_step_id = workflow_state.completed_steps[-1]
                if engine.navigate_to_step(workflow_state, prev_step_id):
                    if item:
                        return redirect(url_for(f'{self.__class__.__name__}.edit_step',
                                              pk=item.id, step_id=prev_step_id))
                    else:
                        return redirect(url_for(f'{self.__class__.__name__}.add_step',
                                              step_id=prev_step_id))

        return self.get_redirect()

    def _create_entity_from_workflow(self, workflow_state: 'WorkflowState') -> Any:
        """Create entity from workflow data with enhanced validation."""
        try:
            # Validate workflow completion
            if not workflow_state.is_completed and self.workflow_require_completion:
                flash(lazy_gettext('Workflow must be completed before creating entity'), 'error')
                return self.get_redirect()

            # Combine all form data
            combined_data = {}
            for step_data in workflow_state.form_data.values():
                combined_data.update(step_data)

            # Create new entity
            item = self.datamodel.obj()

            # Apply data to entity
            for field_name, value in combined_data.items():
                if hasattr(item, field_name):
                    setattr(item, field_name, value)

            # Set workflow state reference if entity supports it
            if hasattr(item, 'workflow_state_id'):
                item.workflow_state_id = workflow_state.id
                item.workflow_status = 'completed'

            # Save entity
            item = self.datamodel.add(item)

            # Complete workflow
            if hasattr(item, 'complete_workflow'):
                item.complete_workflow()
            else:
                workflow_state.completed_at = datetime.now(tz=timezone.utc)
                workflow_state.status = 'completed'

            # Clear workflow state from session
            self.clear_workflow_state_from_session(workflow_state.workflow_name)

            flash(lazy_gettext('Record created successfully'), 'success')
            return redirect(url_for(f'{self.__class__.__name__}.show', pk=item.id))

        except Exception as e:
            flash(lazy_gettext('Error creating record: %(error)s', error=str(e)), 'error')
            log.error(f"Error creating entity from workflow: {e}")
            return self.get_redirect()

    @action('restart_workflow', lazy_gettext('Restart Workflow'),
            lazy_gettext('Restart workflow for selected items'), 'fa-refresh')
    @permission_name('can_restart_workflow')
    @has_access
    def restart_workflow(self, items):
        """Restart workflow for selected items."""
        if not self.workflow_definition:
            flash(lazy_gettext('No workflow defined for this view'), 'warning')
            return redirect(self.get_redirect())

        restarted_count = 0

        for item in items:
            if hasattr(item, 'start_workflow'):
                try:
                    # Clear existing workflow
                    if hasattr(item, 'workflow_state_id'):
                        item.workflow_state_id = None
                        item.workflow_status = 'not_started'
                        item.workflow_completed_at = None

                    # Start new workflow
                    item.start_workflow()
                    restarted_count += 1

                except Exception as e:
                    flash(lazy_gettext('Error restarting workflow for %(item)s: %(error)s',
                                     item=str(item), error=str(e)), 'error')

        if restarted_count > 0:
            self.datamodel.session.commit()
            flash(lazy_gettext('Restarted workflows for %(count)d items', count=restarted_count), 'success')

        return redirect(self.get_redirect())

    @expose('/workflow_progress/<pk>')
    @has_access
    def workflow_progress(self, pk):
        """Show workflow progress for an item."""
        item = self.datamodel.get(pk)
        if not item:
            flash(lazy_gettext('Record not found'), 'error')
            return redirect(self.get_redirect())

        context = {}

        if hasattr(item, 'workflow_state'):
            context = self.get_workflow_context(self.workflow_definition.name)

        return self.render_template(
            'workflow/progress.html',
            item=item,
            **context
        )


class WorkflowFormView(WorkflowStateMixin, SimpleFormView):
    """
    Standalone workflow form view for custom form sequences.
    """

    workflow_definition = None
    form_template = 'workflow/form.html'
    success_message = lazy_gettext('Form completed successfully')

    def __init__(self):
        super().__init__()
        if self.workflow_definition:
            engine = get_workflow_engine()
            if isinstance(self.workflow_definition, dict):
                self.workflow_definition = self._dict_to_workflow_definition(self.workflow_definition)
            engine.register_workflow(self.workflow_definition)

    @expose('/', methods=['GET', 'POST'])
    @expose('/<step_id>', methods=['GET', 'POST'])
    def form(self, step_id=None):
        """Display workflow form."""
        if not self.workflow_definition:
            flash(lazy_gettext('No workflow defined'), 'error')
            return redirect('/')

        # Get or create workflow state
        workflow_state = self.get_or_create_workflow_state(
            workflow_name=self.workflow_definition.name,
            entity_type='FormWorkflow'
        )

        # Use current step if no step specified
        if not step_id:
            step_id = workflow_state.current_step

        # Validate step access
        if step_id != workflow_state.current_step and not workflow_state.can_navigate_to_step(step_id):
            flash(lazy_gettext('Cannot access this step'), 'error')
            step_id = workflow_state.current_step

        # Get step definition
        step_def = get_workflow_engine().get_step_definition(self.workflow_definition.name, step_id)
        if not step_def:
            flash(lazy_gettext('Invalid step'), 'error')
            return redirect('/')

        # Create dynamic form
        form = self._create_step_form(step_def, workflow_state)

        # Handle form submission
        if form.validate_on_submit():
            return self._handle_form_submission(form, step_id, workflow_state)

        # Render form
        context = self.get_workflow_context(self.workflow_definition.name)
        context.update({
            'form': form,
            'step_definition': step_def,
            'current_step_id': step_id
        })

        return self.render_template(self.form_template, **context)

    def _create_step_form(self, step_def: WorkflowStepDefinition, workflow_state: 'WorkflowState') -> Form:
        """Create form for workflow step."""
        # This is a simplified implementation
        # In production, you'd want a more sophisticated form builder

        class StepForm(DynamicForm):
            pass

        # Add fields based on step definition
        if step_def.form_fields:
            for field_name in step_def.form_fields:
                setattr(StepForm, field_name, StringField(field_name.title(), validators=[DataRequired()]))

        # Add hidden field for step tracking
        setattr(StepForm, 'current_step', HiddenField(default=step_def.id))

        form = StepForm()

        # Populate with existing data
        form_data = workflow_state.get_form_data_for_step(step_def.id)
        if form_data:
            for field_name, value in form_data.items():
                if hasattr(form, field_name):
                    getattr(form, field_name).data = value

        return form

    def _handle_form_submission(self, form, step_id: str, workflow_state: 'WorkflowState') -> Any:
        """Handle form submission."""
        # Extract form data
        form_data = {field.name: field.data for field in form if field.name != 'csrf_token'}

        # Save to workflow state
        workflow_state.set_form_data_for_step(step_id, form_data)

        # Navigate based on button clicked
        if 'next' in request.form and workflow_state.available_next_steps:
            next_step = workflow_state.available_next_steps[0]
            engine = get_workflow_engine()
            if engine.advance_workflow(workflow_state, next_step):
                return redirect(url_for('.form', step_id=next_step))

        elif 'previous' in request.form and workflow_state.completed_steps:
            prev_step = workflow_state.completed_steps[-1]
            engine = get_workflow_engine()
            if engine.navigate_to_step(workflow_state, prev_step):
                return redirect(url_for('.form', step_id=prev_step))

        elif 'submit' in request.form:
            # Form completed
            workflow_state.completed_at = datetime.now(tz=timezone.utc)
            flash(self.success_message, 'success')
            return redirect('/')

        return redirect(url_for('.form', step_id=step_id))