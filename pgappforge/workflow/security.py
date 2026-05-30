"""
Dynamic Security Integration for Workflow-Aware PgAppForge

Extends PgAppForge's security system to support workflow-driven permissions,
dynamic role assignment, and step-based access control.
"""

import logging
from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING
from functools import wraps
from datetime import datetime, timedelta, timezone

from flask import g, request, session
from flask_login import current_user
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from pgappforge.models.tenant_models import TenantAwareMixin
from pgappforge.security.manager import BaseSecurityManager
from pgappforge.security.sqla.models import PermissionView, Role
from pgappforge.security.decorators import has_access

if TYPE_CHECKING:
    from .core import WorkflowState, WorkflowStepDefinition

log = logging.getLogger(__name__)


def get_db_session():
    """Get the current database session."""
    from flask import current_app
    return current_app.appbuilder.get_session


class WorkflowPermission(TenantAwareMixin, AuditMixin, Model):
    """
    Dynamic workflow-based permissions.

    Defines permissions that change based on workflow state,
    step progression, and temporal constraints.
    """

    __tablename__ = 'ab_workflow_permissions'

    id = Column(Integer, primary_key=True)

    # Permission identification
    permission_name = Column(String(100), nullable=False)
    resource_name = Column(String(100), nullable=False)
    workflow_name = Column(String(100), nullable=False)

    # Workflow-specific constraints
    workflow_step = Column(String(100))  # Specific step (optional)
    step_range_start = Column(String(100))  # Step range start (optional)
    step_range_end = Column(String(100))  # Step range end (optional)

    # Conditions
    conditions = Column(JSONB, default=lambda: {})
    required_data = Column(JSONB, default=lambda: {})  # Required form data

    # Temporal constraints
    valid_from = Column(DateTime)
    valid_until = Column(DateTime)
    max_duration_minutes = Column(Integer)  # Max time to use permission

    # Role and user constraints
    required_roles = Column(JSONB, default=lambda: [])
    required_users = Column(JSONB, default=lambda: [])
    excluded_roles = Column(JSONB, default=lambda: [])
    excluded_users = Column(JSONB, default=lambda: [])

    # Status
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # Higher priority wins conflicts

    def is_valid_for_workflow_state(self, workflow_state: 'WorkflowState') -> bool:
        """Check if permission is valid for given workflow state."""
        if not self.is_active:
            return False

        # Check workflow name
        if self.workflow_name != workflow_state.workflow_name:
            return False

        # Check step constraints
        if self.workflow_step and self.workflow_step != workflow_state.current_step:
            return False

        if self.step_range_start or self.step_range_end:
            if not self._is_step_in_range(workflow_state.current_step, workflow_state):
                return False

        # Check temporal constraints
        if not self._is_temporally_valid():
            return False

        # Check conditions
        if self.conditions and not self._evaluate_conditions(workflow_state):
            return False

        # Check required data
        if self.required_data and not self._has_required_data(workflow_state):
            return False

        return True

    def _is_step_in_range(self, current_step: str, workflow_state: 'WorkflowState') -> bool:
        """Check if current step is within the allowed range."""
        from .core import get_workflow_engine

        engine = get_workflow_engine()
        workflow_def = engine.workflow_definitions.get(workflow_state.workflow_name)

        if not workflow_def:
            return False

        # Get step indices
        step_indices = {step.id: i for i, step in enumerate(workflow_def.steps)}

        current_index = step_indices.get(current_step, -1)
        start_index = step_indices.get(self.step_range_start, 0) if self.step_range_start else 0
        end_index = step_indices.get(self.step_range_end, len(workflow_def.steps) - 1) if self.step_range_end else len(workflow_def.steps) - 1

        return start_index <= current_index <= end_index

    def _is_temporally_valid(self) -> bool:
        """Check if permission is temporally valid."""
        now = datetime.now(tz=timezone.utc)

        if self.valid_from and now < self.valid_from:
            return False

        if self.valid_until and now > self.valid_until:
            return False

        return True

    def _evaluate_conditions(self, workflow_state: 'WorkflowState') -> bool:
        """Evaluate permission conditions."""
        for condition_type, condition_value in self.conditions.items():
            if condition_type == 'user_in_role':
                if not current_user or current_user.is_anonymous:
                    return False

                user_roles = [role.name for role in current_user.roles]
                required_roles = condition_value if isinstance(condition_value, list) else [condition_value]

                if not any(role in user_roles for role in required_roles):
                    return False

            elif condition_type == 'workflow_progress_min':
                if workflow_state.progress_percentage < condition_value:
                    return False

            elif condition_type == 'form_field_equals':
                field_name = condition_value.get('field')
                expected_value = condition_value.get('value')

                actual_value = None
                for step_data in workflow_state.form_data.values():
                    if field_name in step_data:
                        actual_value = step_data[field_name]
                        break

                if actual_value != expected_value:
                    return False

        return True

    def _has_required_data(self, workflow_state: 'WorkflowState') -> bool:
        """Check if workflow has required data."""
        for step_id, required_fields in self.required_data.items():
            step_data = workflow_state.form_data.get(step_id, {})

            for field_name in required_fields:
                if field_name not in step_data or not step_data[field_name]:
                    return False

        return True


class WorkflowRole(TenantAwareMixin, AuditMixin, Model):
    """
    Dynamic workflow-based roles.

    Roles that are automatically assigned/removed based on
    workflow state and progression.
    """

    __tablename__ = 'ab_workflow_roles'

    id = Column(Integer, primary_key=True)

    # Role identification
    role_name = Column(String(100), nullable=False)
    base_role_name = Column(String(100))  # Base role to extend
    workflow_name = Column(String(100), nullable=False)

    # Assignment conditions
    assignment_trigger = Column(String(50))  # 'step_entry', 'step_completion', 'workflow_start'
    trigger_step = Column(String(100))  # Specific step for trigger
    assignment_conditions = Column(JSONB, default=lambda: {})

    # Duration and expiry
    duration_minutes = Column(Integer)  # Auto-expire after duration
    expires_on_step_exit = Column(Boolean, default=True)
    expires_on_workflow_completion = Column(Boolean, default=True)

    # Status
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)


class DynamicRoleAssignment(TenantAwareMixin, AuditMixin, Model):
    """
    Active dynamic role assignments.

    Tracks currently active workflow-based role assignments
    with expiration and cleanup capabilities.
    """

    __tablename__ = 'ab_workflow_role_assignments'

    id = Column(Integer, primary_key=True)

    # Assignment details
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    role_id = Column(Integer, ForeignKey('ab_role.id'), nullable=False)
    workflow_role_id = Column(Integer, ForeignKey('ab_workflow_roles.id'), nullable=False)
    workflow_state_id = Column(String(36), ForeignKey('ab_workflow_states.id'), nullable=False)

    # Timing
    assigned_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    revoked_at = Column(DateTime)

    # Metadata
    assignment_reason = Column(String(200))
    assignment_metadata = Column(JSONB, default=lambda: {})

    # Relationships
    user = relationship("User", backref="dynamic_role_assignments")
    role = relationship("Role", backref="dynamic_assignments")
    workflow_role = relationship("WorkflowRole", backref="assignments")
    workflow_state = relationship("WorkflowState", backref="role_assignments")

    @property
    def is_expired(self) -> bool:
        """Check if assignment has expired."""
        return (self.expires_at and datetime.now(tz=timezone.utc) > self.expires_at) or bool(self.revoked_at)


class DynamicRoleManager:
    """
    Manages dynamic role assignment and permission evaluation.

    Handles automatic role assignment/removal based on workflow
    state and provides permission checking capabilities.
    """

    def __init__(self, security_manager: BaseSecurityManager):
        self.security_manager = security_manager
        self._permission_cache = {}
        self._role_cache = {}

    def evaluate_workflow_permissions(self, permission_name: str, resource_name: str,
                                    workflow_state: 'WorkflowState') -> bool:
        """Evaluate if user has permission in current workflow context."""
        if not current_user or current_user.is_anonymous:
            return False

        # Check static permissions first
        if self.security_manager.has_access(permission_name, resource_name):
            return True

        # Check dynamic workflow permissions
        workflow_permissions = get_db_session().query(WorkflowPermission).filter_by(
            permission_name=permission_name,
            resource_name=resource_name,
            is_active=True
        ).order_by(WorkflowPermission.priority.desc()).all()

        for wp in workflow_permissions:
            if wp.is_valid_for_workflow_state(workflow_state):
                # Check role constraints
                if wp.required_roles:
                    user_roles = [role.name for role in current_user.roles]
                    if not any(role in user_roles for role in wp.required_roles):
                        continue

                if wp.excluded_roles:
                    user_roles = [role.name for role in current_user.roles]
                    if any(role in user_roles for role in wp.excluded_roles):
                        continue

                # Check user constraints
                if wp.required_users and current_user.id not in wp.required_users:
                    continue

                if wp.excluded_users and current_user.id in wp.excluded_users:
                    continue

                return True

        return False

    def assign_workflow_roles(self, workflow_state: 'WorkflowState', trigger: str,
                            step_id: Optional[str] = None):
        """Assign dynamic roles based on workflow state."""
        if not current_user or current_user.is_anonymous:
            return

        # Find applicable workflow roles
        query = get_db_session().query(WorkflowRole).filter_by(
            workflow_name=workflow_state.workflow_name,
            assignment_trigger=trigger,
            is_active=True
        )

        if step_id:
            query = query.filter(
                (WorkflowRole.trigger_step == step_id) | (WorkflowRole.trigger_step.is_(None))
            )

        workflow_roles = query.all()

        for wr in workflow_roles:
            if self._should_assign_role(wr, workflow_state):
                self._assign_dynamic_role(wr, workflow_state)

    def revoke_expired_roles(self, workflow_state: 'WorkflowState'):
        """Revoke expired dynamic role assignments."""
        now = datetime.now(tz=timezone.utc)

        # Find expired assignments
        expired_assignments = get_db_session().query(DynamicRoleAssignment).filter(
            DynamicRoleAssignment.workflow_state_id == workflow_state.id,
            DynamicRoleAssignment.revoked_at.is_(None),
            (DynamicRoleAssignment.expires_at <= now) |
            (DynamicRoleAssignment.workflow_role.has(expires_on_workflow_completion=True) &
             (workflow_state.completed_at.isnot(None)))
        ).all()

        for assignment in expired_assignments:
            assignment.revoked_at = now
            log.info(f"Revoked dynamic role assignment {assignment.id}")

        if expired_assignments:
            get_db_session().commit()

    def cleanup_user_workflow_roles(self, user_id: int, workflow_state_id: str):
        """Clean up all workflow roles for a user/workflow combination."""
        assignments = get_db_session().query(DynamicRoleAssignment).filter_by(
            user_id=user_id,
            workflow_state_id=workflow_state_id,
            revoked_at=None
        ).all()

        for assignment in assignments:
            assignment.revoked_at = datetime.now(tz=timezone.utc)

        if assignments:
            get_db_session().commit()
            log.info(f"Cleaned up {len(assignments)} workflow role assignments")

    def get_user_workflow_roles(self, user_id: int, workflow_state_id: str) -> List[str]:
        """Get active workflow roles for a user."""
        assignments = get_db_session().query(DynamicRoleAssignment).filter_by(
            user_id=user_id,
            workflow_state_id=workflow_state_id,
            revoked_at=None
        ).filter(
            (DynamicRoleAssignment.expires_at.is_(None)) |
            (DynamicRoleAssignment.expires_at > datetime.now(tz=timezone.utc))
        ).all()

        return [assignment.role.name for assignment in assignments]

    def _should_assign_role(self, workflow_role: WorkflowRole, workflow_state: 'WorkflowState') -> bool:
        """Check if workflow role should be assigned."""
        # Check if already assigned
        existing = get_db_session().query(DynamicRoleAssignment).filter_by(
            user_id=current_user.id,
            workflow_role_id=workflow_role.id,
            workflow_state_id=workflow_state.id,
            revoked_at=None
        ).filter(
            (DynamicRoleAssignment.expires_at.is_(None)) |
            (DynamicRoleAssignment.expires_at > datetime.now(tz=timezone.utc))
        ).first()

        if existing:
            return False

        # Check assignment conditions
        if workflow_role.assignment_conditions:
            return self._evaluate_assignment_conditions(
                workflow_role.assignment_conditions,
                workflow_state
            )

        return True

    def _assign_dynamic_role(self, workflow_role: WorkflowRole, workflow_state: 'WorkflowState'):
        """Assign a dynamic role to the current user."""
        # Find or create the role
        role = self.security_manager.find_role(workflow_role.role_name)
        if not role:
            # Create dynamic role based on base role
            base_role = self.security_manager.find_role(workflow_role.base_role_name)
            if base_role:
                role = self._create_dynamic_role(workflow_role, base_role)
            else:
                log.error(f"Base role not found: {workflow_role.base_role_name}")
                return

        # Calculate expiration
        expires_at = None
        if workflow_role.duration_minutes:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=workflow_role.duration_minutes)

        # Create assignment
        assignment = DynamicRoleAssignment(
            user_id=current_user.id,
            role_id=role.id,
            workflow_role_id=workflow_role.id,
            workflow_state_id=workflow_state.id,
            expires_at=expires_at,
            assignment_reason=f"Workflow {workflow_state.workflow_name} trigger: {workflow_role.assignment_trigger}"
        )

        get_db_session().add(assignment)
        get_db_session().commit()

        log.info(f"Assigned dynamic role {workflow_role.role_name} to user {current_user.id}")

    def _create_dynamic_role(self, workflow_role: WorkflowRole, base_role: Role) -> Role:
        """Create a dynamic role based on a base role."""
        # Check if dynamic role already exists
        existing_role = self.security_manager.find_role(workflow_role.role_name)
        if existing_role:
            return existing_role

        # Create new role
        new_role = self.security_manager.add_role(workflow_role.role_name)

        # Copy permissions from base role
        for permission_view in base_role.permissions:
            new_role.permissions.append(permission_view)

        get_db_session().commit()
        return new_role

    def _evaluate_assignment_conditions(self, conditions: Dict[str, Any],
                                      workflow_state: 'WorkflowState') -> bool:
        """Evaluate conditions for role assignment."""
        for condition_type, condition_value in conditions.items():
            if condition_type == 'progress_min':
                if workflow_state.progress_percentage < condition_value:
                    return False

            elif condition_type == 'step_completed':
                required_steps = condition_value if isinstance(condition_value, list) else [condition_value]
                completed_steps = workflow_state.completed_steps or []

                if not all(step in completed_steps for step in required_steps):
                    return False

            elif condition_type == 'form_data_exists':
                required_fields = condition_value if isinstance(condition_value, list) else [condition_value]

                for field_name in required_fields:
                    found = False
                    for step_data in workflow_state.form_data.values():
                        if field_name in step_data and step_data[field_name]:
                            found = True
                            break

                    if not found:
                        return False

        return True


# Decorators for workflow-aware security
def workflow_permission_required(permission_name: str, resource_name: str):
    """
    Decorator that checks both static and dynamic workflow permissions.

    Usage:
        @workflow_permission_required('can_approve', 'Employee')
        def approve_employee(self, employee_id):
            # Function implementation
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get workflow state from various sources
            workflow_state = None

            # Try to get from request context
            if hasattr(g, 'workflow_state'):
                workflow_state = g.workflow_state

            # Try to get from session
            elif 'current_workflow_state_id' in session:
                from .core import get_workflow_engine
                engine = get_workflow_engine()
                workflow_state = engine.get_workflow_state(session['current_workflow_state_id'])

            # Try to get from function arguments (if available)
            elif len(args) > 1 and hasattr(args[1], 'workflow_state'):
                workflow_state = args[1].workflow_state

            # Check permissions
            if workflow_state:
                role_manager = get_dynamic_role_manager()
                if role_manager.evaluate_workflow_permissions(permission_name, resource_name, workflow_state):
                    return f(*args, **kwargs)
            else:
                # Fall back to static permission check
                from pgappforge.security.decorators import has_access
                if has_access(permission_name, resource_name):
                    return f(*args, **kwargs)

            # Permission denied
            from flask import abort
            abort(403)

        return decorated_function
    return decorator


def workflow_step_required(allowed_steps: List[str]):
    """
    Decorator that restricts access to specific workflow steps.

    Usage:
        @workflow_step_required(['review', 'approval'])
        def review_form(self):
            # Function implementation
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            workflow_state = getattr(g, 'workflow_state', None)

            if not workflow_state:
                from flask import abort
                abort(403)

            if workflow_state.current_step not in allowed_steps:
                from flask import abort
                abort(403)

            return f(*args, **kwargs)

        return decorated_function
    return decorator


# Global dynamic role manager instance
_dynamic_role_manager = None


def get_dynamic_role_manager() -> DynamicRoleManager:
    """Get the global dynamic role manager instance."""
    global _dynamic_role_manager

    if _dynamic_role_manager is None:
        from flask import current_app
        if hasattr(current_app, 'appbuilder'):
            _dynamic_role_manager = DynamicRoleManager(current_app.appbuilder.sm)

    return _dynamic_role_manager


def init_workflow_security(appbuilder):
    """Initialize workflow security integration."""
    global _dynamic_role_manager

    _dynamic_role_manager = DynamicRoleManager(appbuilder.sm)

    # Register event handlers for automatic role management
    from .core import WorkflowState
    from sqlalchemy import event

    @event.listens_for(WorkflowState, 'after_update')
    def handle_workflow_state_update(mapper, connection, target):
        """Handle workflow state updates for role management."""
        if _dynamic_role_manager:
            # Check for expired roles
            _dynamic_role_manager.revoke_expired_roles(target)

            # Assign new roles based on current state
            _dynamic_role_manager.assign_workflow_roles(target, 'step_entry', target.current_step)

    log.info("Workflow security integration initialized")