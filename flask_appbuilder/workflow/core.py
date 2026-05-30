"""
Core Workflow Engine for Flask-AppBuilder Integration

Provides the foundation for workflow-aware ModelViews with form sequencing,
state management, and intelligent routing capabilities.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Callable, Union
from enum import Enum
from dataclasses import dataclass, asdict
import uuid

from flask import session, current_app, g, request
from flask_login import current_user
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from flask_appbuilder import Model
from flask_appbuilder.models.mixins import AuditMixin
from flask_appbuilder.models.tenant_models import TenantAwareMixin

log = logging.getLogger(__name__)


def get_db_session():
    """Get the current database session."""
    from flask import current_app
    return current_app.appbuilder.get_session


class WorkflowStepType(Enum):
    """Types of workflow steps."""
    FORM = "form"
    APPROVAL = "approval"
    VALIDATION = "validation"
    SERVICE_CALL = "service_call"
    CONDITIONAL = "conditional"
    PARALLEL = "parallel"
    MERGE = "merge"


class WorkflowStepStatus(Enum):
    """Status of workflow steps."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    WAITING = "waiting"


class WorkflowExecutionMode(Enum):
    """Workflow execution modes."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    USER_DRIVEN = "user_driven"


@dataclass
class WorkflowStepDefinition:
    """Definition of a workflow step."""
    id: str
    name: str
    step_type: WorkflowStepType
    form_fields: Optional[List[str]] = None
    required_role: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None
    next_steps: Optional[List[str]] = None
    timeout_minutes: Optional[int] = None
    auto_save: bool = True
    allow_skip: bool = False
    validation_rules: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowDefinition:
    """Complete workflow definition."""
    name: str
    description: str
    version: str
    steps: List[WorkflowStepDefinition]
    execution_mode: WorkflowExecutionMode = WorkflowExecutionMode.SEQUENTIAL
    auto_save_interval: int = 30  # seconds
    allow_navigation: bool = True
    require_completion: bool = True
    metadata: Optional[Dict[str, Any]] = None


class WorkflowState(TenantAwareMixin, AuditMixin, Model):
    """
    Persistent workflow state for form sequences.

    Stores the current state of a workflow execution including
    current step, form data, and navigation history.
    """

    __tablename__ = 'ab_workflow_states'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Workflow identification
    workflow_name = Column(String(100), nullable=False, index=True)
    workflow_version = Column(String(20), default="1.0")
    entity_type = Column(String(100), nullable=False)  # Model class name
    entity_id = Column(Integer)  # ID of the entity being processed

    # Current state
    current_step = Column(String(100), nullable=False)
    step_index = Column(Integer, default=0)
    status = Column(String(20), default=WorkflowStepStatus.PENDING.value)

    # Data storage
    form_data = Column(JSONB, default=lambda: {})
    step_history = Column(JSONB, default=lambda: [])
    context_variables = Column(JSONB, default=lambda: {})

    # Navigation and control
    completed_steps = Column(JSONB, default=lambda: [])
    skipped_steps = Column(JSONB, default=lambda: [])
    available_next_steps = Column(JSONB, default=lambda: [])

    # Timing and control
    started_at = Column(DateTime, default=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    expires_at = Column(DateTime)

    # User and session tracking
    user_id = Column(Integer, ForeignKey('ab_user.id'))
    session_id = Column(String(100))
    ip_address = Column(String(45))

    # Relationships
    user = relationship("User", backref="workflow_states")

    @hybrid_property
    def is_completed(self):
        """Check if workflow is completed."""
        return self.completed_at is not None

    @hybrid_property
    def is_expired(self):
        """Check if workflow has expired."""
        return self.expires_at and datetime.now(tz=timezone.utc) > self.expires_at

    @hybrid_property
    def progress_percentage(self):
        """Calculate completion percentage."""
        if not self.completed_steps:
            return 0
        total_steps = len(self.completed_steps) + len(self.available_next_steps)
        if total_steps == 0:
            return 100
        return int((len(self.completed_steps) / total_steps) * 100)

    def get_form_data_for_step(self, step_id: str) -> Dict[str, Any]:
        """Get form data for a specific step."""
        return self.form_data.get(step_id, {})

    def set_form_data_for_step(self, step_id: str, data: Dict[str, Any]):
        """Set form data for a specific step."""
        if not self.form_data:
            self.form_data = {}
        self.form_data[step_id] = data
        self.last_activity_at = datetime.now(tz=timezone.utc)

    def add_to_history(self, step_id: str, action: str, data: Optional[Dict[str, Any]] = None):
        """Add entry to step history."""
        if not self.step_history:
            self.step_history = []

        history_entry = {
            'step_id': step_id,
            'action': action,
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'user_id': getattr(current_user, 'id', None) if current_user and not current_user.is_anonymous else None,
            'data': data or {}
        }

        self.step_history.append(history_entry)

    def can_navigate_to_step(self, step_id: str) -> bool:
        """Check if user can navigate to a specific step."""
        return step_id in self.completed_steps or step_id == self.current_step


class WorkflowEngine:
    """
    Core workflow engine that manages form sequences and state transitions.

    Provides the foundation for workflow-aware ModelViews with intelligent
    routing, state persistence, and form orchestration.
    """

    def __init__(self, app=None):
        """Initialize the workflow engine."""
        self.app = app
        self.workflow_definitions: Dict[str, WorkflowDefinition] = {}
        self.step_handlers: Dict[str, Callable] = {}
        self.validation_rules: Dict[str, Callable] = {}

        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize the workflow engine with Flask app."""
        self.app = app

        # Set default configuration
        app.config.setdefault('WORKFLOW_AUTO_SAVE_INTERVAL', 30)
        app.config.setdefault('WORKFLOW_SESSION_TIMEOUT', 3600)  # 1 hour
        app.config.setdefault('WORKFLOW_ENABLE_CACHING', True)
        app.config.setdefault('WORKFLOW_CACHE_TIMEOUT', 300)  # 5 minutes

        # Store engine in app extensions
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['workflow_engine'] = self

    def register_workflow(self, definition: WorkflowDefinition):
        """Register a workflow definition."""
        log.info(f"Registering workflow: {definition.name}")
        self.workflow_definitions[definition.name] = definition

    def register_step_handler(self, step_type: str, handler: Callable):
        """Register a handler for a specific step type."""
        self.step_handlers[step_type] = handler

    def create_workflow_state(self, workflow_name: str, entity_type: str,
                            entity_id: Optional[int] = None,
                            initial_data: Optional[Dict[str, Any]] = None) -> WorkflowState:
        """Create a new workflow state instance."""

        workflow_def = self.workflow_definitions.get(workflow_name)
        if not workflow_def:
            raise ValueError(f"Workflow definition not found: {workflow_name}")

        # Calculate expiration time
        session_timeout = current_app.config.get('WORKFLOW_SESSION_TIMEOUT', 3600)
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=session_timeout)

        # Create workflow state
        state = WorkflowState(
            workflow_name=workflow_name,
            workflow_version=workflow_def.version,
            entity_type=entity_type,
            entity_id=entity_id,
            current_step=workflow_def.steps[0].id if workflow_def.steps else None,
            step_index=0,
            form_data=initial_data or {},
            session_id=session.get('session_id'),
            ip_address=request.remote_addr if request else None,
            expires_at=expires_at
        )

        # Set initial available next steps
        if workflow_def.steps:
            first_step = workflow_def.steps[0]
            state.available_next_steps = first_step.next_steps or []

        # Add to session and database with proper transaction management
        try:
            state.add_to_history(state.current_step, 'workflow_started', {'initial_data': initial_data})
            get_db_session().add(state)
            get_db_session().commit()
            log.info(f"Created workflow state {state.id} for {workflow_name}")
            return state
        except Exception as e:
            get_db_session().rollback()
            log.error(f"Failed to create workflow state for {workflow_name}: {e}")
            raise

    def get_workflow_state(self, state_id: str) -> Optional[WorkflowState]:
        """Get workflow state by ID."""
        return get_db_session().query(WorkflowState).filter_by(id=state_id).first()

    def get_current_workflow_state(self, workflow_name: str, entity_type: str,
                                 entity_id: Optional[int] = None) -> Optional[WorkflowState]:
        """Get current workflow state for an entity."""
        query = get_db_session().query(WorkflowState).filter_by(
            workflow_name=workflow_name,
            entity_type=entity_type
        )

        if entity_id:
            query = query.filter_by(entity_id=entity_id)

        # Get most recent non-completed state
        return query.filter(WorkflowState.completed_at.is_(None)).order_by(
            WorkflowState.created_at.desc()
        ).first()

    def advance_workflow(self, state: WorkflowState, next_step_id: str,
                        form_data: Optional[Dict[str, Any]] = None) -> bool:
        """Advance workflow to the next step."""

        workflow_def = self.workflow_definitions.get(state.workflow_name)
        if not workflow_def:
            log.error(f"Workflow definition not found: {state.workflow_name}")
            return False

        # Find current and next step definitions
        current_step_def = self._find_step_definition(workflow_def, state.current_step)
        next_step_def = self._find_step_definition(workflow_def, next_step_id)

        if not next_step_def:
            log.error(f"Next step definition not found: {next_step_id}")
            return False

        # Validate transition
        if not self._validate_step_transition(state, current_step_def, next_step_def):
            return False

        # Save form data if provided
        if form_data:
            state.set_form_data_for_step(state.current_step, form_data)

        # Mark current step as completed
        if state.current_step not in state.completed_steps:
            completed = list(state.completed_steps) if state.completed_steps else []
            completed.append(state.current_step)
            state.completed_steps = completed

        # Update state
        old_step = state.current_step
        state.current_step = next_step_id
        state.step_index = self._get_step_index(workflow_def, next_step_id)
        state.status = WorkflowStepStatus.IN_PROGRESS.value
        state.last_activity_at = datetime.now(tz=timezone.utc)

        # Update available next steps
        state.available_next_steps = next_step_def.next_steps or []

        # Add to history
        state.add_to_history(next_step_id, 'step_advanced', {
            'from_step': old_step,
            'to_step': next_step_id,
            'form_data_keys': list(form_data.keys()) if form_data else []
        })

        # Check if workflow is completed
        if not state.available_next_steps:
            state.completed_at = datetime.now(tz=timezone.utc)
            state.status = WorkflowStepStatus.COMPLETED.value
            state.add_to_history(next_step_id, 'workflow_completed')

        # Commit with proper transaction management
        try:
            get_db_session().commit()
            log.info(f"Advanced workflow {state.id} from {old_step} to {next_step_id}")
            return True
        except Exception as e:
            get_db_session().rollback()
            log.error(f"Failed to advance workflow {state.id} from {old_step} to {next_step_id}: {e}")
            return False

    def navigate_to_step(self, state: WorkflowState, step_id: str) -> bool:
        """Navigate to a specific step (if allowed)."""

        if not state.can_navigate_to_step(step_id):
            log.warning(f"Navigation to step {step_id} not allowed for workflow {state.id}")
            return False

        workflow_def = self.workflow_definitions.get(state.workflow_name)
        if not workflow_def or not workflow_def.allow_navigation:
            return False

        # Update current step
        old_step = state.current_step
        state.current_step = step_id
        state.step_index = self._get_step_index(workflow_def, step_id)
        state.last_activity_at = datetime.now(tz=timezone.utc)

        # Add to history
        state.add_to_history(step_id, 'step_navigation', {
            'from_step': old_step,
            'to_step': step_id
        })

        # Commit with proper transaction management
        try:
            get_db_session().commit()
            log.info(f"Navigated workflow {state.id} from {old_step} to {step_id}")
            return True
        except Exception as e:
            get_db_session().rollback()
            log.error(f"Failed to navigate workflow {state.id} from {old_step} to {step_id}: {e}")
            return False

    def save_step_data(self, state: WorkflowState, step_id: str, data: Dict[str, Any]):
        """Save data for a specific step."""
        try:
            state.set_form_data_for_step(step_id, data)
            state.add_to_history(step_id, 'data_saved', {'data_keys': list(data.keys())})
            get_db_session().commit()
            log.debug(f"Saved step data for workflow {state.id}, step {step_id}")
        except Exception as e:
            get_db_session().rollback()
            log.error(f"Failed to save step data for workflow {state.id}, step {step_id}: {e}")
            raise

    def get_step_definition(self, workflow_name: str, step_id: str) -> Optional[WorkflowStepDefinition]:
        """Get step definition by workflow and step ID."""
        workflow_def = self.workflow_definitions.get(workflow_name)
        if not workflow_def:
            return None

        return self._find_step_definition(workflow_def, step_id)

    def _find_step_definition(self, workflow_def: WorkflowDefinition, step_id: str) -> Optional[WorkflowStepDefinition]:
        """Find step definition by ID."""
        for step in workflow_def.steps:
            if step.id == step_id:
                return step
        return None

    def _get_step_index(self, workflow_def: WorkflowDefinition, step_id: str) -> int:
        """Get the index of a step in the workflow."""
        for i, step in enumerate(workflow_def.steps):
            if step.id == step_id:
                return i
        return -1

    def _validate_step_transition(self, state: WorkflowState,
                                current_step: Optional[WorkflowStepDefinition],
                                next_step: WorkflowStepDefinition) -> bool:
        """Validate if a step transition is allowed."""

        # Check role requirements
        if next_step.required_role:
            if not current_user or current_user.is_anonymous:
                return False

            user_roles = [role.name for role in current_user.roles]
            if next_step.required_role not in user_roles:
                return False

        # Check conditions
        if next_step.conditions:
            if not self._evaluate_conditions(state, next_step.conditions):
                return False

        # Check if next step is in allowed transitions
        if current_step and current_step.next_steps:
            if next_step.id not in current_step.next_steps:
                return False

        return True

    def _evaluate_conditions(self, state: WorkflowState, conditions: Dict[str, Any]) -> bool:
        """Evaluate step conditions."""
        # This is a simplified implementation
        # In production, you'd want a more sophisticated rule engine

        for condition_type, condition_value in conditions.items():
            if condition_type == 'field_equals':
                field_name = condition_value.get('field')
                expected_value = condition_value.get('value')
                actual_value = state.form_data.get(field_name)

                if actual_value != expected_value:
                    return False

            elif condition_type == 'field_not_empty':
                field_name = condition_value
                if not state.form_data.get(field_name):
                    return False

        return True


# Global workflow engine instance
workflow_engine = WorkflowEngine()


def get_workflow_engine() -> WorkflowEngine:
    """Get the global workflow engine instance."""
    return workflow_engine