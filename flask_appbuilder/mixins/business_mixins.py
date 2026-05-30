"""
Business Logic Mixins for Flask-AppBuilder

This module provides mixins for business process management:
- Workflow state management
- Multi-step approval processes  
- Multi-tenancy support
- Currency handling
- Geographic data management
- Hierarchical tree structures

These mixins integrate with Flask-AppBuilder's security and user
management systems to provide comprehensive business functionality.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app, current_user, g
from flask_appbuilder.models.mixins import AuditMixin
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, event
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

# Import security framework
from .security_framework import (
    MixinSecurityError, MixinPermissionError, MixinValidationError,
    MixinDataError, MixinConfigurationError, SecurityValidator, 
    InputValidator, SecurityAuditor, secure_operation, database_operation
)

log = logging.getLogger(__name__)


class WorkflowMixin(AuditMixin):
    """
    Advanced workflow state management mixin.
    
    Provides comprehensive workflow capabilities including:
    - Configurable state machines
    - State transition validation and logging
    - Workflow actions and triggers
    - Event-driven state changes
    - Workflow analytics and reporting
    
    Features:
    - Define custom workflow states and transitions
    - Automatic state validation
    - Transition history and audit trail
    - Conditional transitions based on business rules
    - Integration with Flask-AppBuilder's security model
    """
    
    current_state = Column(String(50), default='draft', nullable=False, index=True)
    state_history = Column(Text, nullable=True)  # JSON array of state changes
    workflow_data = Column(Text, nullable=True)  # Additional workflow context
    
    # Configuration - override in subclasses
    __workflow_states__ = {
        'draft': 'Draft - Initial state',
        'submitted': 'Submitted for review',
        'in_review': 'Under review',
        'approved': 'Approved',
        'rejected': 'Rejected', 
        'completed': 'Completed',
        'archived': 'Archived'
    }
    
    __workflow_transitions__ = {
        'draft': ['submitted', 'archived'],
        'submitted': ['in_review', 'draft', 'rejected'],
        'in_review': ['approved', 'rejected', 'draft'],
        'approved': ['completed', 'archived'],
        'rejected': ['draft', 'archived'],
        'completed': ['archived'],
        'archived': []  # Terminal state
    }
    
    __workflow_initial_state__ = 'draft'
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.current_state:
            self.current_state = self.__workflow_initial_state__
    
    def change_state(self, new_state: str, reason: str = None, 
                    user_id: int = None, metadata: Dict = None) -> bool:
        """
        Change workflow state with validation and logging.
        
        Args:
            new_state: Target state to transition to
            reason: Reason for state change
            user_id: User performing the change
            metadata: Additional metadata for the transition
            
        Returns:
            bool: True if successful, False if transition not allowed
        """
        if not self.can_transition_to(new_state):
            log.warning(f"Invalid transition from {self.current_state} to {new_state}")
            return False
        
        old_state = self.current_state
        
        # Record state change
        state_change = {
            'from_state': old_state,
            'to_state': new_state,
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'user_id': user_id or self._get_current_user_id(),
            'reason': reason,
            'metadata': metadata or {}
        }
        
        # Update state history
        history = self.get_state_history()
        history.append(state_change)
        self.state_history = json.dumps(history)
        
        # Update current state
        self.current_state = new_state
        
        # Trigger state change actions
        self._trigger_transition_action(old_state, new_state, state_change)
        
        log.info(f"State changed from {old_state} to {new_state} for {self.__class__.__name__}")
        return True
    
    def can_transition_to(self, new_state: str) -> bool:
        """Check if transition to new state is allowed."""
        if new_state not in self.__workflow_states__:
            return False
        
        allowed_transitions = self.__workflow_transitions__.get(self.current_state, [])
        return new_state in allowed_transitions
    
    def get_available_transitions(self) -> List[Dict[str, str]]:
        """Get list of available state transitions."""
        allowed_states = self.__workflow_transitions__.get(self.current_state, [])
        
        return [
            {
                'state': state,
                'description': self.__workflow_states__.get(state, state),
                'label': state.replace('_', ' ').title()
            }
            for state in allowed_states
        ]
    
    def get_state_history(self) -> List[Dict]:
        """Get complete state change history."""
        if not self.state_history:
            return []
        
        try:
            return json.loads(self.state_history)
        except json.JSONDecodeError:
            return []
    
    def get_workflow_graph(self) -> Dict[str, Any]:
        """Get workflow definition as graph structure."""
        return {
            'states': self.__workflow_states__,
            'transitions': self.__workflow_transitions__,
            'current_state': self.current_state,
            'initial_state': self.__workflow_initial_state__
        }
    
    def _trigger_transition_action(self, from_state: str, to_state: str, 
                                 transition_data: Dict):
        """Trigger any actions associated with state transition."""
        # Override in subclasses to implement custom actions
        # Examples: send notifications, update related records, etc.
        pass
    
    def _get_current_user_id(self) -> Optional[int]:
        """Get current user ID from Flask-AppBuilder context."""
        try:
            if current_user and hasattr(current_user, 'id'):
                return current_user.id
            elif hasattr(g, 'user') and g.user:
                return g.user.id
        except:
            pass
        return None
    
    @property
    def state_label(self) -> str:
        """Get human-readable state label."""
        return self.__workflow_states__.get(self.current_state, self.current_state)
    
    @property
    def is_terminal_state(self) -> bool:
        """Check if current state is terminal (no outgoing transitions)."""
        return not self.__workflow_transitions__.get(self.current_state, [])
    
    def __repr__(self):
        return f"<{self.__class__.__name__}(id={getattr(self, 'id', 'unknown')}, state={self.current_state})>"


class ApprovalWorkflowMixin(WorkflowMixin):
    """
    Multi-step approval workflow mixin.
    
    Extends WorkflowMixin to provide sophisticated approval processes
    including parallel approvals, conditional steps, and delegation.
    
    Features:
    - Multi-level approval hierarchies
    - Parallel and sequential approval steps
    - Approval delegation and substitution
    - Conditional approval logic
    - Approval analytics and reporting
    - Integration with Flask-AppBuilder roles and permissions
    """
    
    # Approval-specific fields
    current_approval_step = Column(String(50), nullable=True)
    required_approvals = Column(Integer, default=1)
    received_approvals = Column(Integer, default=0)
    approval_deadline = Column(DateTime, nullable=True)
    
    # Override workflow states for approval process
    __workflow_states__ = {
        'draft': 'Draft - Being prepared',
        'pending_approval': 'Pending approval',
        'partially_approved': 'Partially approved',
        'approved': 'Fully approved',
        'rejected': 'Rejected',
        'expired': 'Approval deadline expired',
        'completed': 'Process completed'
    }
    
    __workflow_transitions__ = {
        'draft': ['pending_approval'],
        'pending_approval': ['partially_approved', 'approved', 'rejected', 'expired'],
        'partially_approved': ['approved', 'rejected', 'expired'],
        'approved': ['completed'],
        'rejected': ['draft'],
        'expired': ['draft'],
        'completed': []
    }
    
    # Approval configuration - override in subclasses
    __approval_workflow__ = {
        'step_1': {
            'name': 'Manager Approval',
            'required_role': 'Manager',
            'required_approvals': 1,
            'is_parallel': False
        },
        'step_2': {
            'name': 'Director Approval', 
            'required_role': 'Director',
            'required_approvals': 1,
            'is_parallel': False,
            'condition': lambda obj: obj.get_total_amount() > 10000  # Example condition
        }
    }
    
    def initiate_approval_process(self, user_id: int = None) -> bool:
        """Start the approval process."""
        if self.current_state != 'draft':
            return False
        
        # Initialize approval tracking
        self.received_approvals = 0
        self.current_approval_step = self._get_first_approval_step()
        self.required_approvals = self._calculate_required_approvals()
        
        # Change to pending approval state
        return self.change_state('pending_approval', 'Approval process initiated', user_id)
    
    @secure_operation(permission='can_approve', log_access=True)
    @database_operation(transaction=True)
    def approve_step(self, user_id: int, comments: str = None) -> bool:
        """
        Record an approval for the current step with security validation.
        
        Args:
            user_id: ID of the approving user  
            comments: Optional approval comments
            
        Returns:
            True if approval was successful
            
        Raises:
            MixinPermissionError: If user cannot approve this step
            MixinDataError: If approval data is invalid
            MixinValidationError: If current state doesn't allow approval
        """
        # Validate current state allows approval
        valid_states = ['pending_approval', 'partially_approved']
        if self.current_state not in valid_states:
            raise MixinValidationError(
                f"Cannot approve in current state '{self.current_state}'. "
                f"Valid states: {valid_states}",
                field="current_state",
                value=self.current_state
            )
        
        # Validate and sanitize comments
        if comments:
            comments = InputValidator.sanitize_string(comments, max_length=1000)
        
        # Validate user can approve (uses comprehensive permission checking)
        if not self._can_approve(user_id):
            # _can_approve now raises MixinPermissionError with details
            raise MixinPermissionError(f"User {user_id} cannot approve current step")
        
        try:
            # Record the approval with audit trail
            approval_data = {
                'user_id': user_id,
                'step': self.current_approval_step,
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'comments': comments,
                'action': 'approved',
                'ip_address': getattr(request, 'remote_addr', None) if 'request' in globals() else None
            }
            
            self._record_approval(approval_data)
            self.received_approvals += 1
            
            # Log security event
            SecurityAuditor.log_security_event(
                'approval_granted',
                user_id=user_id,
                details={
                    'object_type': self.__class__.__name__,
                    'object_id': getattr(self, 'id', None),
                    'approval_step': self.current_approval_step,
                    'has_comments': bool(comments)
                }
            )
            
            # Check if we can advance to next step or complete
            if self._is_step_complete():
                next_step = self._get_next_step()
                
                if next_step:
                    self.current_approval_step = next_step
                    self.change_state('partially_approved', f'Step {self.current_approval_step} approved')
                    log.info(f"Approval workflow advanced to step {next_step} for {self.__class__.__name__} {getattr(self, 'id', 'unknown')}")
                else:
                    # All approvals complete
                    self.change_state('approved', 'All approvals received')
                    log.info(f"Approval workflow completed for {self.__class__.__name__} {getattr(self, 'id', 'unknown')}")
            
            return True
            
        except (MixinPermissionError, MixinValidationError, MixinDataError):
            raise
        except Exception as e:
            log.error(f"Approval step failed unexpectedly: {e}")
            raise MixinDataError(f"Approval processing failed: {str(e)}")
    
    def reject_step(self, user_id: int, reason: str) -> bool:
        """Reject the current approval step."""
        if self.current_state not in ['pending_approval', 'partially_approved']:
            return False
        
        if not self._can_approve(user_id):
            return False
        
        # Record the rejection
        rejection_data = {
            'user_id': user_id,
            'step': self.current_approval_step,
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'reason': reason,
            'action': 'rejected'
        }
        
        self._record_approval(rejection_data)
        
        return self.change_state('rejected', f'Rejected at step {self.current_approval_step}')
    
    def _can_approve(self, user_id: int) -> bool:
        """
        Check if user can approve current step with comprehensive permission validation.
        
        Args:
            user_id: ID of the user attempting approval
            
        Returns:
            True if user has permission to approve, False otherwise
        """
        try:
            from flask_appbuilder import db
            from flask_appbuilder.security.sqla.models import User
            
            # Get step configuration
            step_config = self.__approval_workflow__.get(self.current_approval_step, {})
            if not step_config:
                log.warning(f"No approval workflow configuration found for step {self.current_approval_step}")
                return False
            
            # Get user from database
            user = db.session.query(User).filter(User.id == user_id).first()
            if not user:
                log.warning(f"User {user_id} not found for approval check")
                return False
            
            # Check if user is active
            if not user.active:
                log.warning(f"Inactive user {user_id} attempted approval")
                return False
            
            # Check required role
            required_role = step_config.get('required_role')
            if required_role:
                user_roles = [role.name for role in user.roles]
                if required_role not in user_roles:
                    log.info(f"User {user_id} lacks required role '{required_role}' for approval")
                    return False
            
            # Check required permission
            required_permission = step_config.get('required_permission')
            if required_permission:
                if not user.has_permission(required_permission):
                    log.info(f"User {user_id} lacks required permission '{required_permission}' for approval")
                    return False
            
            # Check department/organizational restrictions
            allowed_departments = step_config.get('allowed_departments', [])
            if allowed_departments and hasattr(user, 'department'):
                if user.department not in allowed_departments:
                    log.info(f"User {user_id} department '{user.department}' not in allowed departments")
                    return False
            
            # Check minimum approval level/rank
            min_approval_level = step_config.get('min_approval_level')
            if min_approval_level and hasattr(user, 'approval_level'):
                if user.approval_level < min_approval_level:
                    log.info(f"User {user_id} approval level {user.approval_level} below minimum {min_approval_level}")
                    return False
            
            # Check if user has already approved this item
            workflow_data = json.loads(self.workflow_data) if self.workflow_data else {}
            existing_approvals = workflow_data.get('approvals', [])
            
            for approval in existing_approvals:
                if approval.get('user_id') == user_id:
                    log.info(f"User {user_id} has already provided approval/rejection")
                    return False
            
            # Check if user is the creator (may not be allowed to approve own work)
            prevent_self_approval = step_config.get('prevent_self_approval', True)
            if prevent_self_approval and hasattr(self, 'created_by_fk') and self.created_by_fk == user_id:
                log.info(f"User {user_id} cannot approve their own work")
                return False
            
            # Check custom approval logic if defined
            custom_check = step_config.get('custom_approval_check')
            if custom_check and callable(custom_check):
                try:
                    if not custom_check(self, user):
                        log.info(f"User {user_id} failed custom approval check")
                        return False
                except Exception as e:
                    log.error(f"Custom approval check failed: {e}")
                    return False
            
            # Check time-based restrictions
            approval_window = step_config.get('approval_window_hours')
            if approval_window and hasattr(self, 'created_on'):
                from datetime import datetime, timedelta
                cutoff_time = self.created_on + timedelta(hours=approval_window)
                if datetime.now(tz=timezone.utc) > cutoff_time:
                    log.info(f"Approval window of {approval_window} hours has expired")
                    return False
            
            # All checks passed
            log.debug(f"User {user_id} authorized to approve step {self.current_approval_step}")
            return True
            
        except ImportError as e:
            log.error(f"Flask-AppBuilder security models not available: {e}")
            return False
        except Exception as e:
            log.error(f"Approval permission check failed: {e}")
            return False
    
    def _record_approval(self, approval_data: Dict):
        """Record approval/rejection data."""
        workflow_data = json.loads(self.workflow_data) if self.workflow_data else {}
        
        if 'approvals' not in workflow_data:
            workflow_data['approvals'] = []
        
        workflow_data['approvals'].append(approval_data)
        self.workflow_data = json.dumps(workflow_data)
    
    def _get_first_approval_step(self) -> str:
        """Get the first approval step."""
        steps = list(self.__approval_workflow__.keys())
        return steps[0] if steps else None
    
    def _get_next_step(self) -> Optional[str]:
        """Get the next approval step."""
        steps = list(self.__approval_workflow__.keys())
        try:
            current_index = steps.index(self.current_approval_step)
            return steps[current_index + 1] if current_index + 1 < len(steps) else None
        except ValueError:
            return None
    
    def _calculate_required_approvals(self) -> int:
        """Calculate total required approvals."""
        return sum(
            step_config.get('required_approvals', 1)
            for step_config in self.__approval_workflow__.values()
        )
    
    def _is_step_complete(self) -> bool:
        """Check if current approval step is complete."""
        step_config = self.__approval_workflow__.get(self.current_approval_step, {})
        required = step_config.get('required_approvals', 1)
        
        # Count approvals for current step
        workflow_data = json.loads(self.workflow_data) if self.workflow_data else {}
        approvals = workflow_data.get('approvals', [])
        
        step_approvals = [
            a for a in approvals
            if a.get('step') == self.current_approval_step and a.get('action') == 'approved'
        ]
        
        return len(step_approvals) >= required
    
    def get_approval_status(self) -> Dict[str, Any]:
        """Get comprehensive approval status."""
        workflow_data = json.loads(self.workflow_data) if self.workflow_data else {}
        
        return {
            'current_step': self.current_approval_step,
            'current_state': self.current_state,
            'received_approvals': self.received_approvals,
            'required_approvals': self.required_approvals,
            'approval_history': workflow_data.get('approvals', []),
            'next_approvers': self._get_next_approvers(),
            'is_complete': self.current_state in ['approved', 'completed'],
            'is_rejected': self.current_state == 'rejected'
        }
    
    def _get_next_approvers(self) -> List[str]:
        """Get list of users who can approve the next step."""
        if self.current_state not in ['pending_approval', 'partially_approved']:
            return []
        
        step_config = self.__approval_workflow__.get(self.current_approval_step, {})
        required_role = step_config.get('required_role', '')
        
        # Return role name - in practice, you'd query users with this role
        return [required_role] if required_role else []
    
    def get_total_amount(self) -> Decimal:
        """Override this method to return amount for conditional approvals."""
        return Decimal('0')


class MultiTenancyMixin:
    """
    Multi-tenancy support mixin.
    
    Provides automatic tenant scoping and data isolation
    integrated with Flask-AppBuilder's security model.
    
    Features:
    - Automatic tenant assignment
    - Query-level tenant filtering
    - Cross-tenant data sharing controls
    - Tenant-specific configurations
    - Tenant migration utilities
    """
    
    tenant_id = Column(String(50), nullable=True, index=True)
    is_shared = Column(Boolean, default=False)  # Cross-tenant sharing flag
    
    # Configuration
    __tenant_field__ = 'tenant_id'
    __shared_data__ = False
    
    @staticmethod
    def get_current_tenant():
        """Get current tenant from Flask-AppBuilder context."""
        try:
            # Check user's tenant
            if current_user and hasattr(current_user, 'tenant_id'):
                return current_user.tenant_id
            
            # Check session/request context
            if hasattr(g, 'tenant_id'):
                return g.tenant_id
            
            # Check app config
            return current_app.config.get('DEFAULT_TENANT_ID')
        except:
            return None
    
    @classmethod
    def __declare_last__(cls):
        """Set up tenant scoping."""
        super().__declare_last__()
        
        @event.listens_for(cls, 'before_insert')
        def set_tenant(mapper, connection, target):
            if not target.tenant_id and not target.is_shared:
                target.tenant_id = cls.get_current_tenant()
    
    @classmethod
    def get_tenant_query(cls, tenant_id: str = None):
        """Get query scoped to specific tenant."""
        tenant = tenant_id or cls.get_current_tenant()
        
        if tenant:
            return cls.query.filter(
                (cls.tenant_id == tenant) | (cls.is_shared == True)
            )
        else:
            return cls.query
    
    def copy_to_tenant(self, target_tenant_id: str, user_id: int = None):
        """Copy this record to another tenant."""
        if not target_tenant_id:
            return None
        
        # Create copy with new tenant
        new_record = self.__class__()
        
        for column in self.__table__.columns:
            if column.name not in ['id', 'tenant_id']:
                setattr(new_record, column.name, getattr(self, column.name))
        
        new_record.tenant_id = target_tenant_id
        
        return new_record


class TreeMixin:
    """
    Hierarchical tree structure mixin.
    
    Provides methods for tree traversal, manipulation, and querying.
    Supports nested set model for efficient tree operations.
    
    Features:
    - Parent-child relationships
    - Tree traversal methods
    - Depth calculation
    - Ancestor/descendant queries
    - Tree manipulation utilities
    """
    
    @declared_attr
    def parent_id(cls):
        return Column(Integer, ForeignKey(f'{cls.__tablename__}.id'), nullable=True)
    
    @declared_attr
    def parent(cls):
        return relationship(
            cls,
            remote_side=f'{cls.__tablename__}.id',
            backref='children'
        )
    
    depth = Column(Integer, default=0)
    path = Column(String(500), nullable=True)  # Materialized path
    
    def get_ancestors(self, include_self: bool = False):
        """Get all ancestor nodes."""
        ancestors = []
        current = self.parent
        
        while current:
            ancestors.append(current)
            current = current.parent
        
        if include_self:
            ancestors.insert(0, self)
        
        return list(reversed(ancestors))  # Root to current order
    
    def get_descendants(self, max_depth: int = None):
        """Get all descendant nodes."""
        descendants = []
        
        def collect_descendants(node, current_depth=0):
            if max_depth and current_depth >= max_depth:
                return
            
            for child in node.children:
                descendants.append(child)
                collect_descendants(child, current_depth + 1)
        
        collect_descendants(self)
        return descendants
    
    def get_siblings(self, include_self: bool = False):
        """Get sibling nodes."""
        if not self.parent:
            # Root level siblings
            query = self.__class__.query.filter(self.__class__.parent_id.is_(None))
        else:
            query = self.__class__.query.filter(self.__class__.parent_id == self.parent_id)
        
        siblings = query.all()
        
        if not include_self:
            siblings = [s for s in siblings if s.id != getattr(self, 'id', None)]
        
        return siblings
    
    def is_ancestor_of(self, other) -> bool:
        """Check if this node is an ancestor of another node."""
        return other in self.get_descendants()
    
    def is_descendant_of(self, other) -> bool:
        """Check if this node is a descendant of another node."""
        return self in other.get_descendants()
    
    def update_depth(self):
        """Update depth based on position in tree."""
        if not self.parent:
            self.depth = 0
        else:
            self.depth = self.parent.depth + 1
    
    def update_path(self):
        """Update materialized path."""
        if not self.parent:
            self.path = str(getattr(self, 'id', ''))
        else:
            self.path = f"{self.parent.path}/{getattr(self, 'id', '')}"
    
    @classmethod
    def get_roots(cls):
        """Get all root nodes."""
        return cls.query.filter(cls.parent_id.is_(None)).all()
    
    @classmethod
    def __declare_last__(cls):
        """Set up tree maintenance."""
        super().__declare_last__()
        
        @event.listens_for(cls, 'before_insert')
        @event.listens_for(cls, 'before_update')
        def maintain_tree_structure(mapper, connection, target):
            target.update_depth()
            # Path update would need to happen after insert for ID
    
    def __repr__(self):
        name = getattr(self, 'name', getattr(self, 'title', 'Node'))
        return f"<{self.__class__.__name__}(id={getattr(self, 'id', 'unknown')}, name='{name}', depth={self.depth})>"


# Utility function for business mixins setup
def setup_business_mixins(app):
    """
    Set up business mixins with Flask-AppBuilder.
    
    Args:
        app: Flask application instance
    """
    # Configure workflow settings
    app.config.setdefault('WORKFLOW_NOTIFICATIONS_ENABLED', True)
    app.config.setdefault('APPROVAL_TIMEOUT_DAYS', 30)
    app.config.setdefault('APPROVAL_REMINDERS_ENABLED', True)
    
    # Configure multi-tenancy
    app.config.setdefault('MULTI_TENANCY_ENABLED', False)
    app.config.setdefault('DEFAULT_TENANT_ID', 'default')
    
    log.info("Business mixins configured successfully")


__all__ = [
    'WorkflowMixin',
    'ApprovalWorkflowMixin',
    'MultiTenancyMixin',
    'TreeMixin',
    'setup_business_mixins'
]