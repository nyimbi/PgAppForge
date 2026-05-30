"""
Workflow-Aware Widget System for Flask-AppBuilder

Provides intelligent widgets that understand workflow context and adapt
their behavior based on workflow state, step progression, and user permissions.
"""

import logging
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import json

from flask import url_for, request, session
from flask_babel import lazy_gettext, gettext
from markupsafe import Markup

from flask_appbuilder.widgets import (
    FormWidget, ListWidget, ShowWidget, SearchWidget
)
from flask_appbuilder.fieldwidgets import (
    BS3TextFieldWidget, BS3TextAreaFieldWidget, BS3PasswordFieldWidget
)

if TYPE_CHECKING:
    from .core import WorkflowState, WorkflowStepDefinition

log = logging.getLogger(__name__)


class WorkflowProgressWidget:
    """
    Widget that displays workflow progress with step indicators.

    Shows current step, completed steps, and available next steps
    with visual progress indicators and navigation capabilities.
    """

    template = 'workflow/widgets/progress_widget.html'

    def __init__(self, workflow_state: 'WorkflowState',
                 workflow_definition: 'WorkflowDefinition',
                 show_navigation: bool = True,
                 show_step_details: bool = True):
        self.workflow_state = workflow_state
        self.workflow_definition = workflow_definition
        self.show_navigation = show_navigation
        self.show_step_details = show_step_details

    def __call__(self, field, **kwargs):
        """Render the progress widget."""
        from flask import render_template

        context = self._build_context()
        return Markup(render_template(self.template, **context))

    def _build_context(self) -> Dict[str, Any]:
        """Build template context for the widget."""
        steps_info = []
        current_step_index = -1

        for i, step in enumerate(self.workflow_definition.steps):
            step_info = {
                'id': step.id,
                'name': step.name,
                'index': i,
                'is_current': step.id == self.workflow_state.current_step,
                'is_completed': step.id in (self.workflow_state.completed_steps or []),
                'is_accessible': self.workflow_state.can_navigate_to_step(step.id),
                'required_role': step.required_role,
                'description': getattr(step, 'description', None)
            }

            if step_info['is_current']:
                current_step_index = i

            steps_info.append(step_info)

        return {
            'workflow_state': self.workflow_state,
            'workflow_definition': self.workflow_definition,
            'steps_info': steps_info,
            'current_step_index': current_step_index,
            'progress_percentage': self.workflow_state.progress_percentage,
            'show_navigation': self.show_navigation,
            'show_step_details': self.show_step_details,
            'can_navigate_back': len(self.workflow_state.completed_steps or []) > 0,
            'can_navigate_forward': bool(self.workflow_state.available_next_steps)
        }


class WorkflowFormWidget(FormWidget):
    """
    Enhanced form widget with workflow navigation and state management.

    Extends Flask-AppBuilder's FormWidget to include workflow-specific
    navigation buttons, progress indicators, and state persistence.
    """

    template = 'workflow/widgets/form_widget.html'

    def __init__(self, extra_args=None):
        super().__init__(extra_args)
        self.workflow_context = {}

    def set_workflow_context(self, workflow_state: 'WorkflowState',
                           step_definition: 'WorkflowStepDefinition',
                           workflow_definition: 'WorkflowDefinition'):
        """Set workflow context for the widget."""
        self.workflow_context = {
            'workflow_state': workflow_state,
            'step_definition': step_definition,
            'workflow_definition': workflow_definition,
            'progress_widget': WorkflowProgressWidget(
                workflow_state, workflow_definition
            )
        }

    def __call__(self, form, extra_args=None, **kwargs):
        """Render the form widget with workflow enhancements."""
        extra_args = extra_args or {}
        extra_args.update(self.workflow_context)

        # Add workflow-specific CSS classes
        css_class = kwargs.get('class', '')
        css_class += ' workflow-form'
        kwargs['class'] = css_class

        return super().__call__(form, extra_args, **kwargs)


class ConditionalFieldWidget(BS3TextFieldWidget):
    """
    Widget that shows/hides fields based on workflow conditions.

    Dynamically shows or hides form fields based on:
    - Current workflow step
    - Other field values
    - User permissions
    - Workflow state
    """

    template = 'workflow/widgets/conditional_field_widget.html'

    def __init__(self, conditions: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.conditions = conditions or {}

    def __call__(self, field, **kwargs):
        """Render field with conditional logic."""
        # Check if field should be visible
        if not self._should_show_field(field):
            return Markup('')

        # Add conditional attributes
        kwargs.update(self._get_conditional_attributes(field))

        return super().__call__(field, **kwargs)

    def _should_show_field(self, field) -> bool:
        """Determine if field should be shown based on conditions."""
        if not self.conditions:
            return True

        condition_type = self.conditions.get('type', 'always')

        if condition_type == 'always':
            return True

        elif condition_type == 'workflow_step':
            # Show only on specific workflow steps
            allowed_steps = self.conditions.get('steps', [])
            current_step = session.get('current_workflow_step')
            return current_step in allowed_steps

        elif condition_type == 'field_value':
            # Show based on other field values
            dependent_field = self.conditions.get('field')
            expected_value = self.conditions.get('value')

            if dependent_field and hasattr(field.form, dependent_field):
                actual_value = getattr(field.form, dependent_field).data
                return actual_value == expected_value

        elif condition_type == 'user_role':
            # Show based on user role
            from flask_login import current_user
            required_roles = self.conditions.get('roles', [])

            if current_user and not current_user.is_anonymous:
                user_roles = [role.name for role in current_user.roles]
                return any(role in user_roles for role in required_roles)

        return True

    def _get_conditional_attributes(self, field) -> Dict[str, Any]:
        """Get HTML attributes for conditional behavior."""
        attributes = {}

        if self.conditions.get('type') == 'field_value':
            # Add data attributes for JavaScript conditional logic
            attributes['data-conditional'] = 'true'
            attributes['data-depends-on'] = self.conditions.get('field')
            attributes['data-depends-value'] = self.conditions.get('value')

        return attributes


class WorkflowStepFieldWidget(BS3TextFieldWidget):
    """
    Field widget that adapts based on current workflow step.

    Changes field behavior, validation, and appearance based on
    the current workflow step and step-specific configuration.
    """

    def __init__(self, step_configs: Optional[Dict[str, Dict[str, Any]]] = None):
        super().__init__()
        self.step_configs = step_configs or {}

    def __call__(self, field, **kwargs):
        """Render field with step-specific configuration."""
        current_step = session.get('current_workflow_step')

        if current_step and current_step in self.step_configs:
            step_config = self.step_configs[current_step]

            # Apply step-specific attributes
            kwargs.update(step_config.get('attributes', {}))

            # Override field properties
            if 'required' in step_config:
                field.flags.required = step_config['required']

            if 'placeholder' in step_config:
                kwargs['placeholder'] = step_config['placeholder']

            if 'help_text' in step_config:
                kwargs['title'] = step_config['help_text']

        return super().__call__(field, **kwargs)


class WorkflowButtonWidget:
    """
    Smart button widget that provides context-aware workflow navigation.

    Generates appropriate navigation buttons based on current workflow
    state, available actions, and user permissions.
    """

    template = 'workflow/widgets/button_widget.html'

    def __init__(self, workflow_state: 'WorkflowState',
                 workflow_definition: 'WorkflowDefinition',
                 show_save_draft: bool = True,
                 show_navigation: bool = True,
                 custom_buttons: Optional[List[Dict[str, Any]]] = None):
        self.workflow_state = workflow_state
        self.workflow_definition = workflow_definition
        self.show_save_draft = show_save_draft
        self.show_navigation = show_navigation
        self.custom_buttons = custom_buttons or []

    def __call__(self, **kwargs):
        """Render workflow buttons."""
        from flask import render_template

        buttons = self._build_buttons()
        context = {
            'buttons': buttons,
            'workflow_state': self.workflow_state,
            'workflow_definition': self.workflow_definition
        }

        return Markup(render_template(self.template, **context))

    def _build_buttons(self) -> List[Dict[str, Any]]:
        """Build list of available buttons."""
        buttons = []

        # Previous button
        if (self.show_navigation and
            self.workflow_state.completed_steps and
            self.workflow_definition.allow_navigation):

            buttons.append({
                'name': 'workflow_previous',
                'label': lazy_gettext('Previous'),
                'class': 'btn btn-secondary',
                'icon': 'fa fa-arrow-left',
                'type': 'submit'
            })

        # Save draft button
        if self.show_save_draft:
            buttons.append({
                'name': 'workflow_save_draft',
                'label': lazy_gettext('Save Draft'),
                'class': 'btn btn-info',
                'icon': 'fa fa-save',
                'type': 'submit'
            })

        # Next/Complete button
        if self.workflow_state.available_next_steps:
            buttons.append({
                'name': 'workflow_next',
                'label': lazy_gettext('Next'),
                'class': 'btn btn-primary',
                'icon': 'fa fa-arrow-right',
                'type': 'submit'
            })
        else:
            # Workflow completion
            buttons.append({
                'name': 'workflow_complete',
                'label': lazy_gettext('Complete'),
                'class': 'btn btn-success',
                'icon': 'fa fa-check',
                'type': 'submit'
            })

        # Custom buttons
        buttons.extend(self.custom_buttons)

        return buttons


class WorkflowListWidget(ListWidget):
    """
    Enhanced list widget that shows workflow status and progress.

    Extends Flask-AppBuilder's ListWidget to display workflow-specific
    information such as progress, current step, and workflow actions.
    """

    template = 'workflow/widgets/list_widget.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.show_workflow_status = kwargs.get('show_workflow_status', True)
        self.show_workflow_actions = kwargs.get('show_workflow_actions', True)

    def list_columns(self, list_columns, list_title, modelview_name, **kwargs):
        """Override to add workflow columns."""
        # Add workflow status column if enabled
        if self.show_workflow_status and hasattr(kwargs.get('datamodel'), 'obj'):
            model_class = kwargs['datamodel'].obj

            # Check if model has workflow capabilities
            if hasattr(model_class, 'workflow_enabled') and model_class.workflow_enabled:
                # Add workflow status columns
                if 'workflow_status' not in list_columns:
                    list_columns = list(list_columns) + ['workflow_status', 'workflow_progress_percentage']

        return super().list_columns(list_columns, list_title, modelview_name, **kwargs)


class WorkflowShowWidget(ShowWidget):
    """
    Enhanced show widget that displays workflow information.

    Extends Flask-AppBuilder's ShowWidget to show workflow progress,
    step history, and available workflow actions.
    """

    template = 'workflow/widgets/show_widget.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.show_workflow_info = kwargs.get('show_workflow_info', True)
        self.show_step_history = kwargs.get('show_step_history', True)

    def show_columns(self, show_columns, item, **kwargs):
        """Override to add workflow information."""
        if self.show_workflow_info and hasattr(item, 'workflow_state'):
            # Add workflow information section
            kwargs['workflow_state'] = item.workflow_state
            kwargs['show_step_history'] = self.show_step_history

        return super().show_columns(show_columns, item, **kwargs)


class WorkflowSearchWidget(SearchWidget):
    """
    Enhanced search widget with workflow-specific filters.

    Extends Flask-AppBuilder's SearchWidget to include workflow status,
    step, and progress filters.
    """

    template = 'workflow/widgets/search_widget.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.include_workflow_filters = kwargs.get('include_workflow_filters', True)

    def __call__(self, form, **kwargs):
        """Render search widget with workflow filters."""
        if self.include_workflow_filters:
            # Add workflow-specific search options
            kwargs['workflow_statuses'] = [
                ('not_started', lazy_gettext('Not Started')),
                ('in_progress', lazy_gettext('In Progress')),
                ('completed', lazy_gettext('Completed')),
                ('failed', lazy_gettext('Failed'))
            ]

        return super().__call__(form, **kwargs)


# Field widget mappings for workflow-aware forms
WORKFLOW_FIELD_WIDGETS = {
    'workflow_progress': WorkflowProgressWidget,
    'conditional': ConditionalFieldWidget,
    'workflow_step': WorkflowStepFieldWidget,
    'workflow_buttons': WorkflowButtonWidget
}


def get_workflow_widget(widget_type: str, **kwargs):
    """Get workflow widget instance by type."""
    widget_class = WORKFLOW_FIELD_WIDGETS.get(widget_type)

    if not widget_class:
        raise ValueError(f"Unknown workflow widget type: {widget_type}")

    return widget_class(**kwargs)


# Decorator for making existing widgets workflow-aware
def workflow_aware(widget_class):
    """
    Decorator to make existing widgets workflow-aware.

    Adds workflow context and conditional behavior to existing
    Flask-AppBuilder widgets.
    """

    class WorkflowAwareWidget(widget_class):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.workflow_conditions = kwargs.get('workflow_conditions', {})

        def __call__(self, *args, **kwargs):
            # Add workflow CSS classes
            css_class = kwargs.get('class', '')
            css_class += ' workflow-aware'

            # Add workflow data attributes
            if self.workflow_conditions:
                kwargs['data-workflow-conditions'] = json.dumps(self.workflow_conditions)

            kwargs['class'] = css_class
            return super().__call__(*args, **kwargs)

    return WorkflowAwareWidget