"""
Approval Chain Management System.

Provides sophisticated approval workflows with multi-level chains, delegation,
escalation, conditional routing, and parallel approval processing.
"""

import logging
import json

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple, Callable
from enum import Enum
from dataclasses import dataclass
import threading

from flask import current_app, g
from sqlalchemy import and_, or_, desc
from sqlalchemy.orm import joinedload

from ...utils.db_performance import (
    QueryOptimizer, QueryLimits, monitor_query_performance
)
from ..models.process_models import (
    ApprovalRequest, ApprovalChain, ApprovalRule, ProcessStep,
    ProcessInstance, ApprovalStatus
)
from ...models.tenant_context import TenantContext
from ...security.sqla.models import User
from ..engine.process_engine import ProcessEngine
from .exceptions import (
    ApprovalError, DatabaseError, ValidationError, BusinessLogicError,
    AuthorizationError, ConfigurationError, handle_error, error_context,
    ErrorContext, handle_approval_errors
)
from .secure_expression_evaluator import SecureExpressionEvaluator, ExpressionContext, SecurityViolation
from .transaction_manager import DatabaseTransactionManager, transactional, TransactionConfig

log = logging.getLogger(__name__)


class ApprovalType(Enum):
    """Types of approval processes."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    UNANIMOUS = "unanimous"
    MAJORITY = "majority"
    FIRST_RESPONSE = "first_response"


class EscalationTrigger(Enum):
    """Triggers for approval escalation."""
    TIMEOUT = "timeout"
    REJECTION = "rejection"
    NO_RESPONSE = "no_response"
    MANUAL = "manual"


@dataclass
class ApprovalContext:
    """Context information for approval processing."""
    step_id: int
    instance_id: int
    request_data: Dict[str, Any]
    initiator_id: int
    priority: str = 'normal'
    due_date: Optional[datetime] = None
    metadata: Dict[str, Any] = None


@dataclass
class ApprovalDecision:
    """Represents an approval decision."""
    approved: bool
    approver_id: int
    comment: Optional[str] = None
    timestamp: datetime = None
    response_data: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(tz=timezone.utc)


class ApprovalChainManager:
    """Manages approval chains and processes approval requests."""
    
    def __init__(self):
        self._lock = threading.RLock()
        self.rule_engine = ApprovalRuleEngine()
        self.escalation_manager = EscalationManager()
        self.notification_handler = None
        self.transaction_manager = DatabaseTransactionManager()
        self.expression_evaluator = SecureExpressionEvaluator()
        
    @handle_approval_errors()
    def create_approval_chain(self, context: ApprovalContext, 
                            chain_config: Dict[str, Any]) -> ApprovalChain:
        """Create a new approval chain based on configuration."""
        with self._lock:
            # Determine approvers based on rules and configuration
            approvers = self._determine_approvers(context, chain_config)
            
            if not approvers:
                raise BusinessLogicError("No approvers found for approval chain")
            
            # Use transaction manager for atomic operations
            with self.transaction_manager.transaction("create_approval_chain"):
                from flask_appbuilder import db
                
                chain = ApprovalChain(
                    tenant_id=TenantContext.get_current_tenant_id(),
                    step_id=context.step_id,
                    chain_type=chain_config.get('type', ApprovalType.SEQUENTIAL.value),
                    approvers=json.dumps(approvers),
                    configuration=json.dumps(chain_config),
                    status=ApprovalStatus.PENDING.value,
                    created_by=context.initiator_id,
                    priority=context.priority,
                    due_date=context.due_date
                )
                
                db.session.add(chain)
                db.session.flush()
                
                # Create individual approval requests
                requests = self._create_approval_requests(chain, context, approvers)
                
                log.info(f"Created approval chain {chain.id} with {len(requests)} requests")
                return chain
    
    def _determine_approvers(self, context: ApprovalContext, 
                           config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Determine approvers based on configuration and rules."""
        approvers = []
        
        # Get explicit approvers from configuration
        if 'approvers' in config:
            for approver_config in config['approvers']:
                approver_info = self._resolve_approver(approver_config, context)
                if approver_info:
                    approvers.append(approver_info)
        
        # Apply approval rules
        rule_based_approvers = self.rule_engine.get_approvers_for_context(context)
        approvers.extend(rule_based_approvers)
        
        # Remove duplicates and sort by order/priority
        unique_approvers = {}
        for approver in approvers:
            user_id = approver.get('user_id')
            if user_id and user_id not in unique_approvers:
                unique_approvers[user_id] = approver
        
        # Sort by order if specified
        sorted_approvers = sorted(
            unique_approvers.values(),
            key=lambda x: x.get('order', 999)
        )
        
        return sorted_approvers
    
    def _resolve_approver(self, approver_config: Dict[str, Any], 
                        context: ApprovalContext) -> Optional[Dict[str, Any]]:
        """Resolve approver configuration to actual user information."""
        try:
            from flask_appbuilder import db
            db_session = db.session
            approver_type = approver_config.get('type', 'user')
            
            if approver_type == 'user':
                user_id = approver_config.get('user_id')
                if user_id:
                    user = db_session.query(User).get(user_id)
                    if user and user.is_active:
                        return {
                            'user_id': user.id,
                            'username': user.username,
                            'email': user.email,
                            'order': approver_config.get('order', 0),
                            'required': approver_config.get('required', True),
                            'delegate_allowed': approver_config.get('delegate_allowed', False)
                        }
            
            elif approver_type == 'role':
                role_name = approver_config.get('role')
                if role_name:
                    # Use FAB's security manager for role-based user lookup
                    try:
                        from flask import current_app
                        sm = current_app.appbuilder.sm
                        
                        role = sm.find_role(role_name)
                        users = []
                        if role:
                            # Get active users with this role
                            users = [user for user in role.user if user.is_active]
                    except Exception as e:
                        log.error(f"Failed to resolve users by role '{role_name}': {str(e)}")
                        users = []
                    
                    # Return first available user or all users depending on configuration
                    if users:
                        selection_mode = approver_config.get('selection_mode', 'first')
                        if selection_mode == 'all':
                            return [
                                {
                                    'user_id': user.id,
                                    'username': user.username,
                                    'email': user.email,
                                    'order': approver_config.get('order', 0),
                                    'required': approver_config.get('required', True),
                                    'delegate_allowed': approver_config.get('delegate_allowed', False)
                                }
                                for user in users
                            ]
                        else:
                            user = users[0]  # First available
                            return {
                                'user_id': user.id,
                                'username': user.username,
                                'email': user.email,
                                'order': approver_config.get('order', 0),
                                'required': approver_config.get('required', True),
                                'delegate_allowed': approver_config.get('delegate_allowed', False)
                            }
            
            elif approver_type == 'dynamic':
                # Dynamic approver resolution based on process data
                expression = approver_config.get('expression')
                if expression:
                    # Evaluate expression to determine approver
                    # This would need a safe expression evaluator
                    resolved_user_id = self._evaluate_dynamic_approver(expression, context)
                    if resolved_user_id:
                        user = db_session.query(User).get(resolved_user_id)
                        if user and user.is_active:
                            # CRITICAL SECURITY FIX: Validate authorization before assigning dynamic approver
                            from .security_validator import ApprovalSecurityValidator
                            security_validator = ApprovalSecurityValidator(self.appbuilder)

                            # Check if resolved user has required role for this step
                            required_role = approver_config.get('required_role')
                            if required_role and not security_validator.validate_role_access(user, required_role):
                                log.warning(f"Dynamic approver {user.id} lacks required role '{required_role}' for step")
                                return None  # Skip this approver and return

                            # Additional authorization check: verify user can approve this entity type
                            entity_type = context.get('entity_type') or context.get('instance', {}).get('__class__', {}).get('__name__')
                            if entity_type and not security_validator.can_user_approve_entity_type(user, entity_type):
                                log.warning(f"Dynamic approver {user.id} not authorized for entity type '{entity_type}'")
                                return None

                            # Prevent privilege escalation through dynamic assignment
                            requester = context.get('instance', {}).get('created_by')
                            if requester and hasattr(requester, 'id'):
                                if user.id == requester.id:
                                    log.warning(f"Prevented self-approval attempt through dynamic assignment: user {user.id}")
                                    return None

                            return {
                                'user_id': user.id,
                                'username': user.username,
                                'email': user.email,
                                'order': approver_config.get('order', 0),
                                'required': approver_config.get('required', True),
                                'delegate_allowed': approver_config.get('delegate_allowed', False)
                            }
            
            return None
            
        except Exception as e:
            log.error(f"Error resolving approver: {str(e)}")
            return None
    
    def _evaluate_dynamic_approver(self, expression: str,
                                 context: ApprovalContext) -> Optional[int]:
        """
        Securely evaluate dynamic approver expression using SecureExpressionEvaluator.

        SECURITY IMPROVEMENT: Now uses SecureExpressionEvaluator to prevent
        SQL injection and code injection attacks, addressing CVE-2024-004.
        """
        try:
            # Create secure evaluation context
            evaluation_context = ExpressionContext(
                instance_id=context.instance_id,
                initiator_id=context.initiator_id,
                tenant_id=getattr(context, 'tenant_id', 0),
                priority=context.priority,
                request_data=context.request_data
            )

            # Use secure expression evaluator
            evaluator = SecureExpressionEvaluator()
            result = evaluator.evaluate_expression(expression, evaluation_context)

            return result

        except SecurityViolation as e:
            log.warning(f"Security violation in expression evaluation: {expression} - {e}")
            return None
        except Exception as e:
            log.error(f"Error evaluating dynamic approver expression: {expression} - {e}")
            return None
    
    def _create_approval_requests(self, chain: ApprovalChain, 
                                context: ApprovalContext,
                                approvers: List[Dict[str, Any]]) -> List[ApprovalRequest]:
        """Create individual approval requests for the chain."""
        requests = []
        
        chain_type = chain.chain_type
        
        for i, approver in enumerate(approvers):
            # Determine if this request should be created immediately
            create_immediately = True
            
            if chain_type == ApprovalType.SEQUENTIAL.value:
                # Only create first request for sequential approval
                create_immediately = (i == 0)
            
            if create_immediately:
                from flask_appbuilder import db
                db_session = db.session
                request = ApprovalRequest(
                    tenant_id=chain.tenant_id,
                    chain_id=chain.id,
                    step_id=context.step_id,
                    approver_id=approver['user_id'],
                    status=ApprovalStatus.PENDING.value,
                    priority=context.priority,
                    approval_data=context.request_data,
                    order_index=i,
                    required=approver.get('required', True),
                    delegate_allowed=approver.get('delegate_allowed', False),
                    requested_at=datetime.now(tz=timezone.utc),
                    expires_at=context.due_date
                )
                
                db_session.add(request)
                requests.append(request)
                
                # Send notification
                self._send_approval_notification(request, approver)
        
        return requests
    
    @handle_approval_errors()
    def process_approval_decision(self, request_id: int, 
                                decision: ApprovalDecision) -> Dict[str, Any]:
        """Process an approval decision and update chain status."""
        with self._lock:
            try:
                from flask_appbuilder import db
                db_session = db.session
                # Get approval request
                request = db_session.query(ApprovalRequest).get(request_id)
                if not request:
                    raise ValueError(f"Approval request {request_id} not found")
                
                if request.status != ApprovalStatus.PENDING.value:
                    raise ValueError(f"Request {request_id} is not pending")
                
                # Update request with decision
                request.status = ApprovalStatus.APPROVED.value if decision.approved else ApprovalStatus.REJECTED.value
                request.responded_at = decision.timestamp
                request.notes = decision.comment
                request.response_data = decision.response_data
                
                # Get the approval chain
                chain = db_session.query(ApprovalChain).get(request.chain_id)
                if not chain:
                    raise ValueError(f"Approval chain {request.chain_id} not found")
                
                # Process chain logic based on type
                chain_result = self._process_chain_decision(chain, request, decision)
                
                db_session.commit()
                
                # If chain is complete, continue process execution
                if chain_result['chain_complete']:
                    self._handle_chain_completion(chain, chain_result['approved'])
                
                log.info(f"Processed approval decision for request {request_id}: {decision.approved}")
                
                return chain_result
                
            except Exception as e:
                db_session.rollback()
                log.error(f"Failed to process approval decision: {str(e)}")
                raise
    
    def _process_chain_decision(self, chain: ApprovalChain, 
                              current_request: ApprovalRequest,
                              decision: ApprovalDecision) -> Dict[str, Any]:
        """Process approval decision based on chain type."""
        chain_type = chain.chain_type
        from flask_appbuilder import db
        db_session = db.session
        
        # Get all requests in the chain with performance optimization
        optimizer = QueryOptimizer()
        requests_query = db_session.query(ApprovalRequest)\
            .options(joinedload(ApprovalRequest.approver))\
            .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
            .filter_by(chain_id=chain.id)\
            .order_by(ApprovalRequest.order_index)

        # Approval chains are typically small, but add safety limit
        all_requests = optimizer.safe_all(requests_query, max_results=QueryLimits.DEFAULT_PAGE_SIZE)
        
        pending_requests = [r for r in all_requests if r.status == ApprovalStatus.PENDING.value]
        approved_requests = [r for r in all_requests if r.status == ApprovalStatus.APPROVED.value]
        rejected_requests = [r for r in all_requests if r.status == ApprovalStatus.REJECTED.value]
        
        chain_complete = False
        chain_approved = False
        next_actions = []
        
        if chain_type == ApprovalType.SEQUENTIAL.value:
            chain_complete, chain_approved, next_actions = self._process_sequential_chain(
                chain, all_requests, current_request, decision
            )
        
        elif chain_type == ApprovalType.PARALLEL.value:
            chain_complete, chain_approved = self._process_parallel_chain(
                chain, approved_requests, rejected_requests, pending_requests
            )
        
        elif chain_type == ApprovalType.UNANIMOUS.value:
            # All approvers must approve
            if not decision.approved:
                chain_complete = True
                chain_approved = False
            elif len(pending_requests) == 0:
                chain_complete = True
                chain_approved = len(rejected_requests) == 0
        
        elif chain_type == ApprovalType.MAJORITY.value:
            total_requests = len(all_requests)
            required_approvals = (total_requests // 2) + 1
            
            if len(approved_requests) >= required_approvals:
                chain_complete = True
                chain_approved = True
            elif len(rejected_requests) > (total_requests - required_approvals):
                chain_complete = True
                chain_approved = False
        
        elif chain_type == ApprovalType.FIRST_RESPONSE.value:
            # First response determines the outcome
            chain_complete = True
            chain_approved = decision.approved
            
            # Cancel remaining requests
            for req in pending_requests:
                if req.id != current_request.id:
                    req.status = ApprovalStatus.CANCELLED.value
                    next_actions.append(f"Cancelled request {req.id}")
        
        # Update chain status
        if chain_complete:
            chain.status = ApprovalStatus.APPROVED.value if chain_approved else ApprovalStatus.REJECTED.value
            chain.completed_at = datetime.now(tz=timezone.utc)
        
        return {
            'chain_complete': chain_complete,
            'approved': chain_approved,
            'next_actions': next_actions,
            'pending_requests': len(pending_requests),
            'approved_requests': len(approved_requests),
            'rejected_requests': len(rejected_requests)
        }
    
    def _process_sequential_chain(self, chain: ApprovalChain,
                                all_requests: List[ApprovalRequest],
                                current_request: ApprovalRequest,
                                decision: ApprovalDecision) -> Tuple[bool, bool, List[str]]:
        """Process sequential approval chain logic."""
        next_actions = []
        
        if not decision.approved:
            # Rejection stops the chain
            return True, False, next_actions
        
        # Find next request in sequence
        current_index = current_request.order_index
        next_requests = [r for r in all_requests if r.order_index > current_index]
        
        if not next_requests:
            # This was the last request, chain is complete
            return True, True, next_actions
        
        # Activate next request(s)
        next_request = min(next_requests, key=lambda r: r.order_index)
        
        if next_request.status == ApprovalStatus.PENDING.value:
            # Already exists, just send notification
            from flask_appbuilder import db
            db_session = db.session
            approver = db_session.query(User).get(next_request.approver_id)
            if approver:
                self._send_approval_notification(next_request, {
                    'user_id': approver.id,
                    'username': approver.username,
                    'email': approver.email
                })
                next_actions.append(f"Notified next approver: {approver.username}")
        else:
            # Create next request since it wasn't pre-created
            from flask_appbuilder import db
            db_session = db.session
            approver = db_session.query(User).get(next_request.approver_id)
            if approver:
                # Create the approval request
                new_request = ApprovalRequest(
                    tenant_id=next_request.tenant_id,
                    chain_id=next_request.chain_id,
                    step_id=next_request.step_id,
                    approver_id=next_request.approver_id,
                    status=ApprovalStatus.PENDING.value,
                    priority=next_request.priority,
                    approval_data=next_request.approval_data,
                    order_index=next_request.order_index,
                    required=next_request.required,
                    delegate_allowed=next_request.delegate_allowed,
                    requested_at=datetime.now(tz=timezone.utc),
                    expires_at=next_request.expires_at
                )
                db_session.add(new_request)
                self._send_approval_notification(new_request, {
                    'user_id': approver.id,
                    'username': approver.username,
                    'email': approver.email
                })
                next_actions.append(f"Created and notified next approver: {approver.username}")
            else:
                next_actions.append("Failed to find next approver user")
        
        return False, False, next_actions
    
    def _process_parallel_chain(self, chain: ApprovalChain,
                              approved_requests: List[ApprovalRequest],
                              rejected_requests: List[ApprovalRequest],
                              pending_requests: List[ApprovalRequest]) -> Tuple[bool, bool]:
        """Process parallel approval chain logic."""
        config = json.loads(chain.configuration) if chain.configuration else {}
        approval_threshold = config.get('approval_threshold', 1)  # Default: at least 1 approval
        
        # Check if we have enough approvals
        if len(approved_requests) >= approval_threshold:
            return True, True
        
        # Check if it's impossible to get enough approvals
        total_possible = len(approved_requests) + len(pending_requests)
        if total_possible < approval_threshold:
            return True, False
        
        # Chain continues
        return False, False
    
    def _handle_chain_completion(self, chain: ApprovalChain, approved: bool):
        """Handle completion of an approval chain."""
        try:
            from flask_appbuilder import db
            db_session = db.session
            # Get the process step
            step = db_session.query(ProcessStep).get(chain.step_id)
            if not step:
                log.error(f"Process step {chain.step_id} not found")
                return
            
            # Update step with approval result
            step_output = {
                'approval_result': 'approved' if approved else 'rejected',
                'approval_chain_id': chain.id,
                'completed_at': datetime.now(tz=timezone.utc).isoformat()
            }
            
            if approved:
                step.mark_completed(step_output)
            else:
                step.mark_failed('Approval was rejected', step_output)
            
            db_session.commit()
            
            # Continue process execution
            engine = ProcessEngine()
            # Note: Converted from async - engine.continue_from_step should be sync
            engine.continue_from_step(step.instance, step.node_id)
            
            log.info(f"Approval chain {chain.id} completed: {approved}")
            
        except Exception as e:
            log.error(f"Error handling chain completion: {str(e)}")
    
    def delegate_approval(self, request_id: int, delegate_to_id: int, 
                              delegated_by_id: int, reason: str = None) -> ApprovalRequest:
        """Delegate an approval request to another user."""
        with self._lock:
            try:
                from flask_appbuilder import db
                db_session = db.session
                # Get original request
                original_request = db_session.query(ApprovalRequest).get(request_id)
                if not original_request:
                    raise ValueError(f"Approval request {request_id} not found")
                
                if not original_request.delegate_allowed:
                    raise ValueError("Delegation is not allowed for this request")
                
                if original_request.status != ApprovalStatus.PENDING.value:
                    raise ValueError("Only pending requests can be delegated")
                
                # CRITICAL SECURITY FIX: Verify delegating user is authorized for this request
                delegating_user = db_session.query(User).get(delegated_by_id)
                if not delegating_user or not delegating_user.is_active:
                    raise ValueError(f"Delegating user {delegated_by_id} not found or inactive")

                # AUTHORIZATION CHECK: Verify delegating user is the assigned approver
                if original_request.approver_id != delegated_by_id:
                    raise ValueError(f"User {delegated_by_id} is not authorized to delegate request {request_id}")

                # ADDITIONAL CHECK: Verify delegating user has appropriate role
                from .security_validator import ApprovalSecurityValidator
                security_validator = ApprovalSecurityValidator(self.appbuilder)

                # Check if delegating user has the required role for this approval step
                workflow_config = self._get_workflow_config(original_request.approval_data.get('workflow_type', 'default'))
                if workflow_config and 'steps' in workflow_config:
                    current_step = None
                    for step in workflow_config['steps']:
                        if step.get('step_id') == original_request.step_id:
                            current_step = step
                            break

                    if current_step and 'required_role' in current_step:
                        if not security_validator.validate_role_access(delegating_user, current_step['required_role']):
                            raise ValueError(f"User {delegated_by_id} does not have required role '{current_step['required_role']}' for delegation")

                # Verify delegate_to user exists and is active
                delegate_user = db_session.query(User).get(delegate_to_id)
                if not delegate_user or not delegate_user.is_active:
                    raise ValueError(f"Delegate user {delegate_to_id} not found or inactive")

                # AUTHORIZATION CHECK: Verify delegate_to user has appropriate role
                if current_step and 'required_role' in current_step:
                    if not security_validator.validate_role_access(delegate_user, current_step['required_role']):
                        raise ValueError(f"Delegate user {delegate_to_id} does not have required role '{current_step['required_role']}'")
                
                # Update original request to delegated status
                original_request.status = ApprovalStatus.DELEGATED.value
                original_request.delegated_to_id = delegate_to_id
                original_request.delegated_by_id = delegated_by_id
                original_request.delegation_reason = reason
                original_request.delegated_at = datetime.now(tz=timezone.utc)
                
                # Create new request for delegate
                delegated_request = ApprovalRequest(
                    tenant_id=original_request.tenant_id,
                    chain_id=original_request.chain_id,
                    step_id=original_request.step_id,
                    approver_id=delegate_to_id,
                    status=ApprovalStatus.PENDING.value,
                    priority=original_request.priority,
                    approval_data=original_request.approval_data,
                    order_index=original_request.order_index,
                    required=original_request.required,
                    delegate_allowed=original_request.delegate_allowed,
                    requested_at=datetime.now(tz=timezone.utc),
                    expires_at=original_request.expires_at,
                    original_request_id=original_request.id
                )
                
                db_session.add(delegated_request)
                db_session.commit()
                
                # Send notification to delegate
                self._send_approval_notification(delegated_request, {
                    'user_id': delegate_user.id,
                    'username': delegate_user.username,
                    'email': delegate_user.email
                })
                
                log.info(f"Delegated approval request {request_id} to user {delegate_to_id}")
                
                return delegated_request
                
            except Exception as e:
                db_session.rollback()
                log.error(f"Failed to delegate approval: {str(e)}")
                raise
    
    def escalate_approval(self, request_id: int, escalation_reason: EscalationTrigger,
                              escalate_to_id: int = None) -> ApprovalRequest:
        """Escalate an approval request to a higher authority."""
        with self._lock:
            try:
                from flask_appbuilder import db
                db_session = db.session
                # Get original request
                original_request = db_session.query(ApprovalRequest).get(request_id)
                if not original_request:
                    raise ValueError(f"Approval request {request_id} not found")
                
                # Determine escalation target
                if not escalate_to_id:
                    escalate_to_id = self._determine_escalation_target(original_request)
                
                if not escalate_to_id:
                    raise ValueError("No escalation target found")
                
                # Verify escalation user exists
                escalation_user = db_session.query(User).get(escalate_to_id)
                if not escalation_user or not escalation_user.is_active:
                    raise ValueError(f"Escalation user {escalate_to_id} not found or inactive")
                
                # Update original request
                original_request.status = ApprovalStatus.ESCALATED.value
                original_request.escalated_to_id = escalate_to_id
                original_request.escalation_reason = escalation_reason.value
                original_request.escalated_at = datetime.now(tz=timezone.utc)
                
                # Create escalated request
                escalated_request = ApprovalRequest(
                    tenant_id=original_request.tenant_id,
                    chain_id=original_request.chain_id,
                    step_id=original_request.step_id,
                    approver_id=escalate_to_id,
                    status=ApprovalStatus.PENDING.value,
                    priority='high',  # Escalated requests are high priority
                    approval_data=original_request.approval_data,
                    order_index=original_request.order_index,
                    required=True,  # Escalated requests are always required
                    delegate_allowed=True,
                    requested_at=datetime.now(tz=timezone.utc),
                    expires_at=original_request.expires_at,
                    original_request_id=original_request.id,
                    is_escalated=True
                )
                
                db_session.add(escalated_request)
                db_session.commit()
                
                # Send notification
                self._send_approval_notification(escalated_request, {
                    'user_id': escalation_user.id,
                    'username': escalation_user.username,
                    'email': escalation_user.email
                })
                
                log.info(f"Escalated approval request {request_id} to user {escalate_to_id}")
                
                return escalated_request
                
            except Exception as e:
                db_session.rollback()
                log.error(f"Failed to escalate approval: {str(e)}")
                raise
    
    def _determine_escalation_target(self, request: ApprovalRequest) -> Optional[int]:
        """Determine the appropriate escalation target for a request."""
        try:
            from flask_appbuilder import db
            db_session = db.session
            # Get current approver
            approver = db_session.query(User).get(request.approver_id)
            if not approver:
                return None
            
            # Try to get manager
            if hasattr(approver, 'manager_id') and approver.manager_id:
                return approver.manager_id
            
            # Try to get users with higher roles
            # This would need role hierarchy configuration
            
            # Fallback: get tenant admin
            tenant_id = TenantContext.get_current_tenant_id()
            admin_users = db_session.query(User).join(User.roles).filter(
                User.roles.any(name='Admin'),
                User.tenant_id == tenant_id,
                User.is_active == True,
                User.id != request.approver_id
            ).first()
            
            return admin_users.id if admin_users else None
            
        except Exception as e:
            log.error(f"Error determining escalation target: {str(e)}")
            return None
    
    def _send_approval_notification(self, request: ApprovalRequest, 
                                  approver: Dict[str, Any]):
        """Send notification to approver about pending request."""
        try:
            if self.notification_handler:
                # Note: Converted from async - notification_handler should have sync methods
                self.notification_handler.send_approval_notification(request, approver)
            else:
                log.info(f"Would send approval notification to {approver['username']} for request {request.id}")
                
        except Exception as e:
            log.error(f"Failed to send approval notification: {str(e)}")
    
    def set_notification_handler(self, handler):
        """Set the notification handler for sending approval notifications."""
        self.notification_handler = handler
    
    def get_pending_approvals(self, user_id: int) -> List[ApprovalRequest]:
        """Get pending approval requests for a specific user."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            from flask_appbuilder import db
            db_session = db.session
            # Get pending requests with performance optimization
            optimizer = QueryOptimizer()
            requests_query = db_session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(\
                    ApprovalRequest.tenant_id == tenant_id,\
                    ApprovalRequest.approver_id == user_id,\
                    ApprovalRequest.status == ApprovalStatus.PENDING.value\
                ).order_by(desc(ApprovalRequest.requested_at))

            # Limit pending requests to prevent performance issues
            requests = optimizer.safe_all(requests_query, max_results=100)
            
            return requests
            
        except Exception as e:
            log.error(f"Error getting pending approvals: {str(e)}")
            return []
    
    def get_approval_chain_status(self, chain_id: int) -> Dict[str, Any]:
        """Get detailed status of an approval chain."""
        try:
            from flask_appbuilder import db
            db_session = db.session
            chain = db_session.query(ApprovalChain).get(chain_id)
            if not chain:
                return {}
            
            # Get requests with performance optimization
            optimizer = QueryOptimizer()
            requests_query = db_session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter_by(chain_id=chain_id)\
                .order_by(ApprovalRequest.order_index)

            # Approval chains are typically small, add safety limit
            requests = optimizer.safe_all(requests_query, max_results=QueryLimits.DEFAULT_PAGE_SIZE)
            
            request_details = []
            for request in requests:
                from flask_appbuilder import db
                db_session = db.session
                approver = db_session.query(User).get(request.approver_id)
                request_details.append({
                    'id': request.id,
                    'approver': {
                        'id': approver.id if approver else None,
                        'username': approver.username if approver else 'Unknown',
                        'email': approver.email if approver else None
                    },
                    'status': request.status,
                    'requested_at': request.requested_at.isoformat() if request.requested_at else None,
                    'responded_at': request.responded_at.isoformat() if request.responded_at else None,
                    'notes': request.notes,
                    'required': request.required,
                    'order_index': request.order_index
                })
            
            return {
                'chain_id': chain.id,
                'chain_type': chain.chain_type,
                'status': chain.status,
                'priority': chain.priority,
                'created_at': chain.created_at.isoformat() if chain.created_at else None,
                'completed_at': chain.completed_at.isoformat() if chain.completed_at else None,
                'due_date': chain.due_date.isoformat() if chain.due_date else None,
                'requests': request_details
            }
            
        except Exception as e:
            log.error(f"Error getting chain status: {str(e)}")
            return {}


class ApprovalRuleEngine:
    """Engine for evaluating approval rules and determining approvers."""
    
    def __init__(self):
        self.rules_cache = {}
        self.cache_timeout = 300  # 5 minutes
    
    def get_approvers_for_context(self, context: ApprovalContext) -> List[Dict[str, Any]]:
        """Get approvers based on approval rules for the given context."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            from flask_appbuilder import db
            db_session = db.session
            # Get applicable rules
            rules = db_session.query(ApprovalRule).filter(
                ApprovalRule.tenant_id == tenant_id,
                ApprovalRule.is_active == True
            ).order_by(ApprovalRule.priority.desc()).all()
            
            approvers = []
            
            for rule in rules:
                if self._evaluate_rule_conditions(rule, context):
                    rule_approvers = self._get_rule_approvers(rule, context)
                    approvers.extend(rule_approvers)
                    
                    # If rule is exclusive, don't process more rules
                    rule_config = json.loads(rule.configuration) if rule.configuration else {}
                    if rule_config.get('exclusive', False):
                        break
            
            return approvers
            
        except Exception as e:
            log.error(f"Error getting rule-based approvers: {str(e)}")
            return []
    
    def _evaluate_rule_conditions(self, rule: ApprovalRule, 
                                context: ApprovalContext) -> bool:
        """Evaluate if rule conditions are met for the context."""
        try:
            rule_config = json.loads(rule.configuration) if rule.configuration else {}
            conditions = rule_config.get('conditions', [])
            
            if not conditions:
                return True  # No conditions means rule applies
            
            from flask_appbuilder import db
            db_session = db.session
            # Get process data for condition evaluation with parameterized query
            from sqlalchemy import bindparam
            instance = db_session.query(ProcessInstance).filter(
                ProcessInstance.id == bindparam('context_instance_id')
            ).params(context_instance_id=context.instance_id).first()
            if not instance:
                return False
            
            evaluation_context = {
                'input_data': instance.input_data or {},
                'context_variables': instance.context_variables or {},
                'priority': context.priority,
                'initiator_id': context.initiator_id,
                'process_definition_id': instance.definition_id
            }
            
            # Evaluate each condition
            for condition in conditions:
                if not self._evaluate_condition(condition, evaluation_context):
                    return False
            
            return True
            
        except Exception as e:
            log.error(f"Error evaluating rule conditions: {str(e)}")
            return False
    
    def _evaluate_condition(self, condition: Dict[str, Any],
                          context: Dict[str, Any]) -> bool:
        """Evaluate a single rule condition with SQL injection prevention."""
        try:
            field = condition.get('field')
            operator = condition.get('operator', '==')
            value = condition.get('value')

            # Security validation: sanitize field names
            import re
            if not field or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_\.]*$', str(field)):
                log.warning(f"Potentially unsafe field name blocked: {field}")
                return False

            # Security validation: whitelist allowed operators
            ALLOWED_OPERATORS = ['==', '!=', '>', '<', '>=', '<=', 'in', 'not_in']
            if operator not in ALLOWED_OPERATORS:
                log.warning(f"Potentially unsafe operator blocked: {operator}")
                return False

            # Get field value from context
            field_value = self._get_field_value(field, context)

            # Compare values
            return self._compare_values(field_value, value, operator)
            
        except Exception as e:
            log.error(f"Error evaluating condition: {str(e)}")
            return False
    
    def _get_field_value(self, field_path: str, context: Dict[str, Any]) -> Any:
        """Get value from context using dot notation field path."""
        try:
            parts = field_path.split('.')
            value = context
            
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return None
            
            return value
            
        except Exception as e:
            log.error(f"Error getting field value: {str(e)}")
            return None
    
    def _compare_values(self, value1: Any, value2: Any, operator: str) -> bool:
        """Compare two values using the specified operator."""
        try:
            if operator == '==':
                return value1 == value2
            elif operator == '!=':
                return value1 != value2
            elif operator == '>':
                return float(value1) > float(value2)
            elif operator == '<':
                return float(value1) < float(value2)
            elif operator == '>=':
                return float(value1) >= float(value2)
            elif operator == '<=':
                return float(value1) <= float(value2)
            elif operator == 'contains':
                return str(value2) in str(value1)
            elif operator == 'startswith':
                return str(value1).startswith(str(value2))
            elif operator == 'in':
                return value1 in value2 if isinstance(value2, list) else False
            
            return False
            
        except (ValueError, TypeError):
            return False
    
    def _get_rule_approvers(self, rule: ApprovalRule, 
                          context: ApprovalContext) -> List[Dict[str, Any]]:
        """Get approvers defined by the rule."""
        try:
            rule_config = json.loads(rule.configuration) if rule.configuration else {}
            approver_configs = rule_config.get('approvers', [])
            
            approvers = []
            
            for approver_config in approver_configs:
                # Resolve approver similar to chain manager
                approver_info = self._resolve_rule_approver(approver_config, context)
                if approver_info:
                    if isinstance(approver_info, list):
                        approvers.extend(approver_info)
                    else:
                        approvers.append(approver_info)
            
            return approvers
            
        except Exception as e:
            log.error(f"Error getting rule approvers: {str(e)}")
            return []
    
    def _resolve_rule_approver(self, approver_config: Dict[str, Any],
                             context: ApprovalContext) -> Optional[Dict[str, Any]]:
        """Resolve rule-based approver configuration."""
        try:
            approver_type = approver_config.get('type', 'user')
            from flask_appbuilder import db
            db_session = db.session
            
            if approver_type == 'user':
                user_id = approver_config.get('user_id')
                if user_id:
                    user = db_session.query(User).get(user_id)
                    if user and user.is_active:
                        return {
                            'user_id': user.id,
                            'username': user.username,
                            'email': user.email,
                            'order': approver_config.get('order', 0),
                            'required': approver_config.get('required', True),
                            'delegate_allowed': approver_config.get('delegate_allowed', False)
                        }
            
            elif approver_type == 'role':
                role_name = approver_config.get('role')
                if role_name:
                    try:
                        sm = current_app.appbuilder.sm
                        role = sm.find_role(role_name)
                        users = []
                        if role:
                            users = [user for user in role.user if user.is_active]
                        
                        if users:
                            # Return first available user for rule-based selection
                            user = users[0]
                            return {
                                'user_id': user.id,
                                'username': user.username,
                                'email': user.email,
                                'order': approver_config.get('order', 0),
                                'required': approver_config.get('required', True),
                                'delegate_allowed': approver_config.get('delegate_allowed', False)
                            }
                    except Exception as e:
                        log.error(f"Failed to resolve users by role '{role_name}': {str(e)}")
            
            elif approver_type == 'rule_based':
                # Rule-specific logic for dynamic approver selection
                rule_expression = approver_config.get('expression')
                if rule_expression:
                    resolved_user_id = self._evaluate_rule_expression(rule_expression, context)
                    if resolved_user_id:
                        user = db_session.query(User).get(resolved_user_id)
                        if user and user.is_active:
                            return {
                                'user_id': user.id,
                                'username': user.username,
                                'email': user.email,
                                'order': approver_config.get('order', 0),
                                'required': approver_config.get('required', True),
                                'delegate_allowed': approver_config.get('delegate_allowed', False)
                            }
            
            return None
            
        except Exception as e:
            log.error(f"Error resolving rule approver: {str(e)}")
            return None
    
    def _evaluate_rule_expression(self, expression: str, context: ApprovalContext) -> Optional[int]:
        """Evaluate rule-based approver expression."""
        try:
            from flask_appbuilder import db
            db_session = db.session
            instance = db_session.query(ProcessInstance).get(context.instance_id)
            if not instance:
                return None
            
            variables = {
                'input_data': instance.input_data or {},
                'context_variables': instance.context_variables or {},
                'initiator_id': context.initiator_id,
                'priority': context.priority
            }
            
            # Safe expression evaluation for rule-based approver selection
            if 'workflow_owner' in expression:
                owner_id = variables['input_data'].get('workflow_owner_id')
                if owner_id:
                    return int(owner_id)
            elif 'department_head' in expression:
                dept_id = variables['input_data'].get('department_id')
                if dept_id:
                    # Find department head (this would be tenant-specific logic)
                    dept_head = db_session.query(User).filter(
                        User.department_id == dept_id,
                        User.is_department_head == True,
                        User.is_active == True
                    ).first()
                    if dept_head:
                        return dept_head.id
            elif 'amount_threshold' in expression:
                amount = variables['input_data'].get('amount', 0)
                # Find appropriate approver based on amount thresholds
                if amount > 10000:
                    # High amount requires senior approver
                    senior_approver = db_session.query(User).filter(
                        User.roles.any(name='Senior_Approver'),
                        User.is_active == True
                    ).first()
                    if senior_approver:
                        return senior_approver.id
            
            return None
            
        except Exception as e:
            log.error(f"Error evaluating rule expression: {str(e)}")
            return None


class EscalationManager:
    """Manages approval escalations and timeouts."""
    
    def __init__(self):
        self.escalation_jobs = {}
    
    def schedule_escalation(self, request_id: int, escalation_time: datetime):
        """Schedule automatic escalation for a request."""
        try:
            from ...tasks import escalate_approval_request
            
            # Calculate delay in seconds
            delay = (escalation_time - datetime.now(tz=timezone.utc)).total_seconds()
            if delay <= 0:
                # Already past escalation time, escalate immediately
                self.escalate_request(request_id)
                return
            
            # Schedule Celery task
            task_result = escalate_approval_request.apply_async(
                args=[request_id],
                countdown=max(1, int(delay))
            )
            
            # Track escalation job for later cancellation
            self.escalation_jobs[request_id] = {
                'task_id': task_result.id,
                'scheduled_at': datetime.now(tz=timezone.utc),
                'escalation_time': escalation_time
            }
            
            log.info(f"Escalation scheduled for request {request_id} at {escalation_time} (task: {task_result.id})")
            
        except ImportError:
            log.warning("Celery tasks not available, escalation scheduling disabled")
        except Exception as e:
            log.error(f"Failed to schedule escalation for request {request_id}: {str(e)}")
            raise
    
    def cancel_escalation(self, request_id: int):
        """Cancel scheduled escalation for a request."""
        try:
            job_info = self.escalation_jobs.get(request_id)
            if not job_info:
                log.debug(f"No escalation scheduled for request {request_id}")
                return
            
            # Cancel Celery task
            from celery import current_app as celery_app
            celery_app.control.revoke(job_info['task_id'], terminate=True)
            
            # Remove from tracking
            del self.escalation_jobs[request_id]
            
            log.info(f"Escalation cancelled for request {request_id} (task: {job_info['task_id']})")
            
        except Exception as e:
            log.error(f"Failed to cancel escalation for request {request_id}: {str(e)}")
            # Don't re-raise - cancellation failures shouldn't break the approval flow
    
    def escalate_request(self, request_id: int):
        """Escalate an approval request to the next level."""
        try:
            from flask_appbuilder import db
            from ..models.process_models import ApprovalRequest
            db_session = db.session
            
            # Get the request
            request = db_session.query(ApprovalRequest).get(request_id)
            if not request:
                log.error(f"Approval request {request_id} not found for escalation")
                return
                
            # Check if still pending
            if request.status != 'pending':
                log.info(f"Request {request_id} no longer pending, skipping escalation")
                return
            
            # Mark as escalated
            request.status = 'escalated'
            request.escalated_at = datetime.now(tz=timezone.utc)
            request.escalation_level = getattr(request, 'escalation_level', 0) + 1
            
            # Create escalated request (would need to find next approver in chain)
            chain_manager = ApprovalChainManager()
            chain_manager.escalate_approval(request.id, 'timeout')
            
            db_session.commit()
            log.info(f"Request {request_id} escalated to level {request.escalation_level}")
            
        except Exception as e:
            log.error(f"Failed to escalate request {request_id}: {str(e)}")
            db_session.rollback()
    
    def check_expired_requests(self):
        """Check for and handle expired approval requests."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            now = datetime.now(tz=timezone.utc)
            
            from flask_appbuilder import db
            db_session = db.session
            # Get expired requests with eager loading to eliminate N+1 queries
            expired_requests = db_session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(\
                    ApprovalRequest.tenant_id == tenant_id,\
                    ApprovalRequest.status == ApprovalStatus.PENDING.value,\
                    ApprovalRequest.expires_at < now\
                ).all()
            
            for request in expired_requests:
                self._handle_expired_request(request)
                
        except Exception as e:
            log.error(f"Error checking expired requests: {str(e)}")
    
    def _handle_expired_request(self, request: ApprovalRequest):
        """Handle an expired approval request."""
        try:
            # Get chain configuration to determine timeout behavior
            from flask_appbuilder import db
            db_session = db.session
            chain = db_session.query(ApprovalChain).get(request.chain_id)
            if not chain:
                return
            
            chain_config = json.loads(chain.configuration) if chain.configuration else {}
            timeout_action = chain_config.get('timeout_action', 'escalate')
            
            if timeout_action == 'escalate':
                # Auto-escalate the request
                chain_manager = ApprovalChainManager()
                chain_manager.escalate_approval(
                    request.id, 
                    EscalationTrigger.TIMEOUT
                )
            elif timeout_action == 'reject':
                # Auto-reject the request
                decision = ApprovalDecision(
                    approved=False,
                    approver_id=0,  # System rejection
                    comment='Request timed out',
                    timestamp=datetime.now(tz=timezone.utc)
                )
                
                chain_manager = ApprovalChainManager()
                chain_manager.process_approval_decision(request.id, decision)
            elif timeout_action == 'approve':
                # Auto-approve the request
                decision = ApprovalDecision(
                    approved=True,
                    approver_id=0,  # System approval
                    comment='Request auto-approved due to timeout',
                    timestamp=datetime.now(tz=timezone.utc)
                )
                
                chain_manager = ApprovalChainManager()
                chain_manager.process_approval_decision(request.id, decision)
            
            log.info(f"Handled expired request {request.id} with action: {timeout_action}")
            
        except Exception as e:
            log.error(f"Error handling expired request: {str(e)}")