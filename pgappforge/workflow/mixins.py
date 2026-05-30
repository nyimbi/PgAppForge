"""
Workflow Mixins for PgForge Models

Provides mixins that make any PgForge model workflow-aware,
enabling automatic workflow integration and form sequencing.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, TYPE_CHECKING

from flask import session, request
from flask_login import current_user
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, declared_attr
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import event

if TYPE_CHECKING:
    from .core import WorkflowState, WorkflowDefinition

log = logging.getLogger(__name__)


class WorkflowMixin:
    """
    Mixin to make any PgForge model workflow-aware.

    Adds workflow state tracking, form sequencing capabilities,
    and automatic workflow integration to any model.

    Usage:
        class Employee(WorkflowMixin, Model):
            # Your model fields
            name = Column(String(100))
            email = Column(String(100))

            # Workflow configuration
            workflow_enabled = True
            workflow_name = 'employee_onboarding'
    """

    # Workflow configuration (override in subclasses)
    workflow_enabled = False
    workflow_name = None
    workflow_auto_start = True
    workflow_require_completion = False

    @declared_attr
    def workflow_state_id(cls):
        """Reference to current workflow state."""
        return Column(String(36), ForeignKey('ab_workflow_states.id'), nullable=True)

    @declared_attr
    def workflow_status(cls):
        """Current workflow status."""
        return Column(String(20), default='not_started')

    @declared_attr
    def workflow_started_at(cls):
        """When workflow was started."""
        return Column(DateTime, nullable=True)

    @declared_attr
    def workflow_completed_at(cls):
        """When workflow was completed."""
        return Column(DateTime, nullable=True)

    @declared_attr
    def workflow_data(cls):
        """Additional workflow-specific data."""
        return Column(JSONB, default=lambda: {})

    @declared_attr
    def workflow_state(cls):
        """Relationship to workflow state."""
        return relationship("WorkflowState", backref=f"{cls.__name__.lower()}_entities")

    @hybrid_property
    def is_workflow_active(self):
        """Check if entity has an active workflow."""
        return self.workflow_state_id is not None and self.workflow_completed_at is None

    @hybrid_property
    def workflow_progress_percentage(self):
        """Get workflow completion percentage."""
        if not self.workflow_state:
            return 0
        return self.workflow_state.progress_percentage

    def start_workflow(self, initial_data: Optional[Dict[str, Any]] = None) -> 'WorkflowState':
        """Start a workflow for this entity."""
        if not self.workflow_enabled or not self.workflow_name:
            raise ValueError("Workflow not enabled for this model")

        if self.is_workflow_active:
            raise ValueError("Workflow already active for this entity")

        from .core import get_workflow_engine

        engine = get_workflow_engine()

        # Create workflow state
        workflow_state = engine.create_workflow_state(
            workflow_name=self.workflow_name,
            entity_type=self.__class__.__name__,
            entity_id=self.id,
            initial_data=initial_data
        )

        # Update entity
        self.workflow_state_id = workflow_state.id
        self.workflow_status = 'in_progress'
        self.workflow_started_at = datetime.now(tz=timezone.utc)

        return workflow_state

    def complete_workflow(self):
        """Mark workflow as completed."""
        if not self.workflow_state:
            return

        self.workflow_status = 'completed'
        self.workflow_completed_at = datetime.now(tz=timezone.utc)

        # Update workflow state
        if self.workflow_state:
            self.workflow_state.completed_at = datetime.now(tz=timezone.utc)
            self.workflow_state.status = 'completed'

    def get_current_workflow_step(self) -> Optional[str]:
        """Get current workflow step."""
        if not self.workflow_state:
            return None
        return self.workflow_state.current_step

    def get_workflow_form_data(self, step_id: Optional[str] = None) -> Dict[str, Any]:
        """Get form data for a specific step or all steps."""
        if not self.workflow_state:
            return {}

        if step_id:
            return self.workflow_state.get_form_data_for_step(step_id)
        else:
            return self.workflow_state.form_data or {}

    def set_workflow_form_data(self, step_id: str, data: Dict[str, Any]):
        """Set form data for a specific step."""
        if not self.workflow_state:
            return

        self.workflow_state.set_form_data_for_step(step_id, data)

    def can_advance_workflow(self, next_step_id: str) -> bool:
        """Check if workflow can advance to next step."""
        if not self.workflow_state:
            return False

        from .core import get_workflow_engine
        engine = get_workflow_engine()

        workflow_def = engine.workflow_definitions.get(self.workflow_name)
        if not workflow_def:
            return False

        current_step_def = engine._find_step_definition(workflow_def, self.workflow_state.current_step)
        next_step_def = engine._find_step_definition(workflow_def, next_step_id)

        if not current_step_def or not next_step_def:
            return False

        return engine._validate_step_transition(self.workflow_state, current_step_def, next_step_def)

    def advance_workflow(self, next_step_id: str, form_data: Optional[Dict[str, Any]] = None) -> bool:
        """Advance workflow to next step."""
        if not self.workflow_state:
            return False

        from .core import get_workflow_engine
        engine = get_workflow_engine()

        success = engine.advance_workflow(self.workflow_state, next_step_id, form_data)

        if success and not self.workflow_state.available_next_steps:
            # Workflow completed
            self.complete_workflow()

        return success


class WorkflowStateMixin:
    """
    Mixin that provides workflow state tracking for views and forms.

    Adds session-based workflow state management and form navigation
    capabilities to PgForge views.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._workflow_state_cache = {}

    def get_workflow_state_from_session(self, workflow_name: str) -> Optional['WorkflowState']:
        """Get workflow state from session."""
        state_id = session.get(f'workflow_state_{workflow_name}')
        if not state_id:
            return None

        # Check cache first
        if state_id in self._workflow_state_cache:
            return self._workflow_state_cache[state_id]

        from .core import get_workflow_engine
        engine = get_workflow_engine()

        state = engine.get_workflow_state(state_id)
        if state:
            self._workflow_state_cache[state_id] = state

        return state

    def set_workflow_state_in_session(self, workflow_state: 'WorkflowState'):
        """Store workflow state ID in session."""
        session[f'workflow_state_{workflow_state.workflow_name}'] = workflow_state.id
        self._workflow_state_cache[workflow_state.id] = workflow_state

    def clear_workflow_state_from_session(self, workflow_name: str):
        """Clear workflow state from session."""
        state_id = session.pop(f'workflow_state_{workflow_name}', None)
        if state_id and state_id in self._workflow_state_cache:
            del self._workflow_state_cache[state_id]

    def get_or_create_workflow_state(self, workflow_name: str, entity_type: str,
                                   entity_id: Optional[int] = None,
                                   initial_data: Optional[Dict[str, Any]] = None) -> 'WorkflowState':
        """Get existing workflow state or create new one."""

        from .core import get_workflow_engine
        engine = get_workflow_engine()

        # Try to get from session first
        state = self.get_workflow_state_from_session(workflow_name)
        if state and not state.is_expired:
            return state

        # Try to get current state for entity
        if entity_id:
            state = engine.get_current_workflow_state(workflow_name, entity_type, entity_id)
            if state and not state.is_expired:
                self.set_workflow_state_in_session(state)
                return state

        # Create new workflow state
        state = engine.create_workflow_state(workflow_name, entity_type, entity_id, initial_data)
        self.set_workflow_state_in_session(state)

        return state

    def get_workflow_context(self, workflow_name: str) -> Dict[str, Any]:
        """Get workflow context for templates."""
        state = self.get_workflow_state_from_session(workflow_name)
        if not state:
            return {}

        from .core import get_workflow_engine
        engine = get_workflow_engine()

        workflow_def = engine.workflow_definitions.get(workflow_name)
        current_step_def = engine.get_step_definition(workflow_name, state.current_step)

        return {
            'workflow_state': state,
            'workflow_definition': workflow_def,
            'current_step': current_step_def,
            'progress_percentage': state.progress_percentage,
            'completed_steps': state.completed_steps or [],
            'available_next_steps': state.available_next_steps or [],
            'can_navigate_back': len(state.completed_steps or []) > 0,
            'form_data': state.form_data or {},
            'is_completed': state.is_completed
        }


# Event handlers for automatic workflow management
@event.listens_for(WorkflowMixin, 'after_insert', propagate=True)
def auto_start_workflow(mapper, connection, target):
    """Automatically start workflow after entity creation."""
    if (hasattr(target, 'workflow_enabled') and target.workflow_enabled and
        hasattr(target, 'workflow_auto_start') and target.workflow_auto_start and
        hasattr(target, 'workflow_name') and target.workflow_name):

        # We need to start workflow in a post-commit hook since we need the entity ID
        @event.listens_for(connection, 'after_commit', once=True)
        def start_workflow_after_commit():
            try:
                target.start_workflow()
                log.info(f"Auto-started workflow {target.workflow_name} for {target.__class__.__name__} {target.id}")
            except Exception as e:
                log.error(f"Failed to auto-start workflow: {e}")


@event.listens_for(WorkflowMixin, 'before_update', propagate=True)
def update_workflow_data(mapper, connection, target):
    """Update workflow data when entity is modified."""
    if target.workflow_state and hasattr(target, '_workflow_form_data'):
        # Store current form data in workflow state
        current_step = target.get_current_workflow_step()
        if current_step:
            target.set_workflow_form_data(current_step, target._workflow_form_data)


# Decorator for workflow-enabled models
def workflow_enabled(workflow_name: str, auto_start: bool = True, require_completion: bool = False):
    """
    Decorator to enable workflow for a model.

    Usage:
        @workflow_enabled('employee_onboarding')
        class Employee(WorkflowMixin, Model):
            name = Column(String(100))
    """
    def decorator(cls):
        cls.workflow_enabled = True
        cls.workflow_name = workflow_name
        cls.workflow_auto_start = auto_start
        cls.workflow_require_completion = require_completion
        return cls

    return decorator