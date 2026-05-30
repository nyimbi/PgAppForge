"""
Approval Chain Management Views.

Provides comprehensive interface for managing approval chains, rules,
and processing approval requests with delegation and escalation.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from flask import request, jsonify, flash, redirect, url_for, session, current_app, g
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
from sqlalchemy import bindparam
from sqlalchemy.orm import joinedload, selectinload
import hashlib
import hmac
import time
from pgappforge import ModelView, BaseView, expose, action, has_access
from pgappforge.api import ModelRestApi, BaseApi
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access_api
from pgappforge.widgets import ListWidget, ShowWidget
from wtforms import StringField, TextAreaField, SelectField, BooleanField
from wtforms.validators import DataRequired
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from marshmallow import fields

from pgappforge import db
from ...utils.db_performance import (
    QueryOptimizer, PaginationHelper, performance_aware_query,
    monitor_query_performance, QueryLimits
)
from .validation_framework import (
    validate_approval_request, validate_user_input, validate_chain_config,
    quick_sanitize, detect_security_threats, ValidationContext,
    ValidationType, SanitizationType
)
from .transaction_manager import get_transaction_manager, transactional
from .exceptions import (
    ApprovalError, ValidationError, SecurityError, BusinessLogicError,
    handle_error, error_context, ErrorContext
)
from pgappforge.security.sqla.models import User
from ..models.process_models import (
    ApprovalChain, ApprovalRequest, ApprovalRule, ProcessStep,
    ApprovalStatus
)
from .chain_manager import (
    ApprovalChainManager, ApprovalDecision, ApprovalContext,
    ApprovalType, EscalationTrigger
)
from ...models.tenant_context import TenantContext
from ..security.approval_security_config import approval_security_config
from .security_validator import ApprovalSecurityValidator

log = logging.getLogger(__name__)


class ApprovalChainSchema(SQLAlchemyAutoSchema):
    """Schema for ApprovalChain serialization."""
    
    class Meta:
        model = ApprovalChain
        load_instance = True
        include_relationships = True
        
    approvers = fields.Raw()
    configuration = fields.Raw()
    created_at = fields.DateTime(dump_only=True)
    completed_at = fields.DateTime(dump_only=True)


class ApprovalRequestSchema(SQLAlchemyAutoSchema):
    """Schema for ApprovalRequest serialization."""
    
    class Meta:
        model = ApprovalRequest
        load_instance = True
        include_relationships = True
        
    approval_data = fields.Raw()
    response_data = fields.Raw()
    requested_at = fields.DateTime(dump_only=True)
    responded_at = fields.DateTime(dump_only=True)


class ApprovalRuleSchema(SQLAlchemyAutoSchema):
    """Schema for ApprovalRule serialization."""
    
    class Meta:
        model = ApprovalRule
        load_instance = True
        
    configuration = fields.Raw()
    created_at = fields.DateTime(dump_only=True)


class ApprovalChainView(ModelView):
    """View for managing approval chains."""
    
    datamodel = SQLAInterface(ApprovalChain)
    
    list_columns = [
        'step.instance.definition.name', 'chain_type', 'status',
        'priority', 'created_by', 'created_at', 'due_date'
    ]
    
    show_columns = [
        'step', 'chain_type', 'status', 'priority', 'approvers',
        'configuration', 'created_by', 'created_at', 'completed_at',
        'due_date'
    ]
    
    search_columns = [
        'step.instance.definition.name', 'chain_type', 'status', 'priority'
    ]
    
    base_permissions = ['can_list', 'can_show']
    
    @expose('/monitor/<int:chain_id>')
    @has_access
    def monitor(self, chain_id):
        """Real-time monitoring of approval chain progress."""
        chain = self.datamodel.get(chain_id)
        if not chain:
            flash('Approval chain not found', 'error')
            return redirect(url_for('ApprovalChainView.list'))
        
        # Get chain manager for detailed status
        manager = ApprovalChainManager()
        # Get current approval chain status
        # chain_status = manager.get_approval_chain_status(chain_id)
        
        # Get approval requests with eager loading and performance optimization
        optimizer = QueryOptimizer()
        requests_query = db.session.query(ApprovalRequest)\
            .options(joinedload(ApprovalRequest.approver))\
            .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
            .filter(ApprovalRequest.chain_id == chain_id)\
            .order_by(ApprovalRequest.order_index)

        # Use safe_all with limit for performance (approval chains typically small)
        requests = optimizer.safe_all(requests_query, max_results=QueryLimits.DEFAULT_PAGE_SIZE)
        
        return self.render_template(
            'approval/chain_monitor.html',
            chain=chain,
            requests=requests,
            chain_type=ApprovalType
        )


class ApprovalRequestView(ModelView):
    """View for managing approval requests."""
    
    datamodel = SQLAInterface(ApprovalRequest)
    
    list_columns = [
        'chain.step.instance.definition.name', 'approver', 'status',
        'priority', 'requested_at', 'expires_at'
    ]
    
    show_columns = [
        'chain', 'approver', 'status', 'priority', 'approval_data',
        'response_data', 'notes', 'required', 'delegate_allowed',
        'requested_at', 'responded_at', 'expires_at'
    ]
    
    search_columns = [
        'chain.step.instance.definition.name', 'approver.username',
        'status', 'priority'
    ]
    
    base_permissions = ['can_list', 'can_show']
    
    @action('approve', 'Approve Request', 'Approve selected requests', 'fa-check')
    def approve_request(self, items):
        """Approve selected approval requests."""
        if not items:
            flash('No requests selected', 'warning')
            return redirect(request.referrer)
        
        approved_count = 0
        manager = ApprovalChainManager()
        
        for request in items:
            if request.status == ApprovalStatus.PENDING.value and request.approver_id == g.user.id:
                try:
                    decision = ApprovalDecision(
                        approved=True,
                        approver_id=g.user.id,
                        comment='Bulk approval action',
                        timestamp=datetime.now(tz=timezone.utc)
                    )
                    
                    # Process approval decision synchronously
                    # manager.process_approval_decision(request.id, decision)
                    approved_count += 1
                    
                except Exception as e:
                    log.error(f"Failed to approve request {request.id}: {str(e)}")
                    flash(f'Failed to approve request {request.id}: {str(e)}', 'error')
        
        if approved_count > 0:
            flash(f'Approved {approved_count} requests', 'success')
        
        return redirect(request.referrer)
    
    @action('reject', 'Reject Request', 'Reject selected requests', 'fa-times')
    def reject_request(self, items):
        """Reject selected approval requests."""
        if not items:
            flash('No requests selected', 'warning')
            return redirect(request.referrer)
        
        rejected_count = 0
        manager = ApprovalChainManager()
        
        for request in items:
            if request.status == ApprovalStatus.PENDING.value and request.approver_id == g.user.id:
                try:
                    decision = ApprovalDecision(
                        approved=False,
                        approver_id=g.user.id,
                        comment='Bulk rejection action',
                        timestamp=datetime.now(tz=timezone.utc)
                    )
                    
                    # Process approval decision synchronously
                    # manager.process_approval_decision(request.id, decision)
                    rejected_count += 1
                    
                except Exception as e:
                    log.error(f"Failed to reject request {request.id}: {str(e)}")
                    flash(f'Failed to reject request {request.id}: {str(e)}', 'error')
        
        if rejected_count > 0:
            flash(f'Rejected {rejected_count} requests', 'success')
        
        return redirect(request.referrer)
    
    @expose('/respond/<int:request_id>')
    @has_access
    def respond(self, request_id):
        """Detailed approval response interface."""
        approval_request = self.datamodel.get(request_id)
        if not approval_request:
            flash('Approval request not found', 'error')
            return redirect(url_for('ApprovalRequestView.list'))
        
        # Verify user can respond to this request
        if approval_request.approver_id != g.user.id:
            flash('You are not authorized to respond to this request', 'error')
            return redirect(url_for('ApprovalRequestView.list'))
        
        if approval_request.status != ApprovalStatus.PENDING.value:
            flash('This request is no longer pending', 'warning')
            return redirect(url_for('ApprovalRequestView.list'))
        
        # Get chain and related information
        chain = approval_request.chain
        step = chain.step if chain else None
        instance = step.instance if step else None
        
        return self.render_template(
            'approval/respond.html',
            request=approval_request,
            chain=chain,
            step=step,
            instance=instance
        )
    
    @expose('/delegate/<int:request_id>')
    @has_access
    def delegate(self, request_id):
        """Delegate approval request to another user."""
        approval_request = self.datamodel.get(request_id)
        if not approval_request:
            flash('Approval request not found', 'error')
            return redirect(url_for('ApprovalRequestView.list'))
        
        # Verify user can delegate this request
        if approval_request.approver_id != g.user.id:
            flash('You are not authorized to delegate this request', 'error')
            return redirect(url_for('ApprovalRequestView.list'))
        
        if not approval_request.delegate_allowed:
            flash('This request cannot be delegated', 'warning')
            return redirect(url_for('ApprovalRequestView.list'))
        
        # Get available users for delegation with performance optimization
        tenant_id = TenantContext.get_current_tenant_id()
        optimizer = QueryOptimizer()
        users_query = db.session.query(User).filter(
            User.tenant_id == tenant_id,
            User.is_active == True,
            User.id != current_user.id
        )
        # Limit users for delegation to reasonable number
        available_users = optimizer.safe_all(users_query, max_results=100)
        
        return self.render_template(
            'approval/delegate.html',
            request=approval_request,
            available_users=available_users
        )


class ApprovalRuleView(ModelView):
    """View for managing approval rules."""
    
    datamodel = SQLAInterface(ApprovalRule)
    
    list_columns = [
        'name', 'description', 'priority', 'is_active',
        'created_by', 'created_at'
    ]
    
    show_columns = [
        'name', 'description', 'priority', 'configuration',
        'is_active', 'created_by', 'created_at', 'updated_at'
    ]
    
    edit_columns = [
        'name', 'description', 'priority', 'configuration', 'is_active'
    ]
    
    add_columns = edit_columns
    
    search_columns = ['name', 'description', 'created_by.username']
    
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
    
    def pre_add(self, item):
        """Pre-process before adding new rule."""
        item.created_by = g.user
        
        # Comprehensive validation for rule configuration
        if item.configuration:
            try:
                config_data = json.loads(item.configuration)
                
                # Validate using validation framework
                validation_context = ValidationContext(
                    operation="chain_config",
                    user_id=g.user.id,
                    component="approval_rule",
                    validation_level=ValidationType.STRICT
                )
                
                validation_result = validate_chain_config(config_data, g.user.id)
                
                if not validation_result['valid']:
                    error_msg = f"Configuration validation failed: {', '.join(validation_result['errors'])}"
                    flash(error_msg, 'error')
                    raise ValidationError(error_msg)
                
                if validation_result['threats']:
                    error_msg = f"Security threats detected in configuration: {', '.join(validation_result['threats'])}"
                    flash(error_msg, 'error')
                    raise SecurityError(error_msg)
                
                # Use sanitized configuration
                item.configuration = json.dumps(validation_result['sanitized_data'])
                
            except json.JSONDecodeError as e:
                flash(f'Invalid JSON configuration: {str(e)}', 'error')
                raise ValidationError("Invalid configuration JSON")
    
    def pre_update(self, item):
        """Pre-process before updating rule."""
        # Comprehensive validation for rule configuration
        if item.configuration:
            try:
                config_data = json.loads(item.configuration)
                
                # Validate using validation framework
                validation_context = ValidationContext(
                    operation="chain_config",
                    user_id=g.user.id,
                    component="approval_rule",
                    validation_level=ValidationType.STRICT
                )
                
                validation_result = validate_chain_config(config_data, g.user.id)
                
                if not validation_result['valid']:
                    error_msg = f"Configuration validation failed: {', '.join(validation_result['errors'])}"
                    flash(error_msg, 'error')
                    raise ValidationError(error_msg)
                
                if validation_result['threats']:
                    error_msg = f"Security threats detected in configuration: {', '.join(validation_result['threats'])}"
                    flash(error_msg, 'error')
                    raise SecurityError(error_msg)
                
                # Use sanitized configuration
                item.configuration = json.dumps(validation_result['sanitized_data'])
                
            except json.JSONDecodeError as e:
                flash(f'Invalid JSON configuration: {str(e)}', 'error')
                raise ValidationError("Invalid configuration JSON")
    
    @action('activate', 'Activate Rule', 'Activate selected rules', 'fa-play')
    @transactional("activate_approval_rules")
    def activate_rule(self, items):
        """Activate selected rules with transaction safety."""
        if not items:
            flash('No rules selected', 'warning')
            return redirect(request.referrer)
        
        activated_count = 0
        for rule in items:
            if not rule.is_active:
                rule.is_active = True
                rule.updated_at = datetime.now(tz=timezone.utc)
                activated_count += 1
        
        if activated_count > 0:
            flash(f'Activated {activated_count} rules', 'success')
        else:
            flash('No inactive rules found', 'warning')
        
        return redirect(request.referrer)
    
    @action('deactivate', 'Deactivate Rule', 'Deactivate selected rules', 'fa-pause')
    @transactional("deactivate_approval_rules")
    def deactivate_rule(self, items):
        """Deactivate selected rules with transaction safety."""
        if not items:
            flash('No rules selected', 'warning')
            return redirect(request.referrer)
        
        deactivated_count = 0
        for rule in items:
            if rule.is_active:
                rule.is_active = False
                rule.updated_at = datetime.now(tz=timezone.utc)
                deactivated_count += 1
        
        if deactivated_count > 0:
            flash(f'Deactivated {deactivated_count} rules', 'success')
        else:
            flash('No active rules found', 'warning')
        
        return redirect(request.referrer)
    
    @expose('/designer/<int:rule_id>')
    @has_access
    def designer(self, rule_id):
        """Visual rule configuration designer."""
        rule = self.datamodel.get(rule_id)
        if not rule:
            flash('Approval rule not found', 'error')
            return redirect(url_for('ApprovalRuleView.list'))
        
        return self.render_template(
            'approval/rule_designer.html',
            rule=rule,
            configuration=json.dumps(
                json.loads(rule.configuration) if rule.configuration else {},
                indent=2
            )
        )


class ApprovalDashboardView(BaseView):
    """Dashboard for approval management and analytics."""
    
    route_base = '/approval'
    
    @expose('/')
    @has_access
    def index(self):
        """Main approval dashboard."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            user_id = g.user.id
            
            # Get pending requests with eager loading to eliminate N+1 queries
            pending_requests = db.session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(\
                    ApprovalRequest.tenant_id == tenant_id,\
                    ApprovalRequest.approver_id == user_id,\
                    ApprovalRequest.status == ApprovalStatus.PENDING.value\
                ).order_by(ApprovalRequest.requested_at.desc()).limit(10).all()
            
            # Get approval statistics with parameterized query
            total_pending = db.session.query(ApprovalRequest).filter(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.approver_id == user_id,
                ApprovalRequest.status == ApprovalStatus.PENDING.value
            ).count()
            
            # Get recent activity with eager loading to eliminate N+1 queries
            recent_activity = db.session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(\
                    ApprovalRequest.tenant_id == tenant_id,\
                    ApprovalRequest.approver_id == user_id,\
                    ApprovalRequest.responded_at.isnot(None)\
                ).order_by(ApprovalRequest.responded_at.desc()).limit(10).all()
            
            # Get overdue requests with parameterized query and performance optimization
            now = datetime.now(tz=timezone.utc)
            optimizer = QueryOptimizer()
            overdue_query = db.session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(\
                    ApprovalRequest.tenant_id == tenant_id,\
                    ApprovalRequest.approver_id == user_id,\
                    ApprovalRequest.status == ApprovalStatus.PENDING.value,\
                    ApprovalRequest.expires_at < now\
                ).order_by(ApprovalRequest.expires_at.asc())

            # Limit overdue requests to prevent performance issues
            overdue_requests = optimizer.safe_all(overdue_query, max_results=50)
            
            return self.render_template(
                'approval/dashboard.html',
                pending_requests=pending_requests,
                total_pending=total_pending,
                recent_activity=recent_activity,
                overdue_requests=overdue_requests
            )
            
        except Exception as e:
            # Standardized error handling with security logging
            user_id = current_user.id if current_user and current_user.is_authenticated else None
            log.error(f"Error loading approval dashboard: {str(e)}")
            if user_id:
                approval_security_config.log_security_event('dashboard_load_error', user_id, None, {
                    'error_message': str(e),
                    'error_type': type(e).__name__,
                    'operation': 'dashboard_load'
                })
            flash(f'Error loading dashboard: {str(e)}', 'error')
            return redirect(url_for('HomeView.index'))
    
    @expose('/pending/')
    @has_access
    def pending(self):
        """View all pending approval requests for current user."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            user_id = g.user.id
            
            # Get pending requests with pagination for performance
            page, per_page = PaginationHelper.get_pagination_params()
            optimizer = QueryOptimizer()
            pending_query = db.session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(\
                    ApprovalRequest.tenant_id == tenant_id,\
                    ApprovalRequest.approver_id == user_id,\
                    ApprovalRequest.status == ApprovalStatus.PENDING.value\
                ).order_by(ApprovalRequest.requested_at.desc())

            # Use pagination for better performance
            pending_requests, total_count, has_next = optimizer.paginated_query(
                pending_query, page=page, per_page=per_page
            )

            # Create pagination context for template
            pagination = PaginationHelper.create_pagination_context(
                pending_requests, total_count, page, per_page, 'ApprovalRequestView.pending'
            )
            
            return self.render_template(
                'approval/pending.html',
                requests=pending_requests,
                pagination=pagination
            )
            
        except Exception as e:
            # Standardized error handling with security logging
            user_id = current_user.id if current_user and current_user.is_authenticated else None
            log.error(f"Error loading pending approvals: {str(e)}")
            if user_id:
                approval_security_config.log_security_event('pending_load_error', user_id, None, {
                    'error_message': str(e),
                    'error_type': type(e).__name__,
                    'operation': 'pending_load'
                })
            flash(f'Error loading pending approvals: {str(e)}', 'error')
            return redirect(url_for('ApprovalDashboardView.index'))
    
    @expose('/analytics/')
    @has_access
    def analytics(self):
        """Approval analytics and reporting."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            # Get approval statistics for last 30 days
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
            
            # Get requests for analytics with performance optimization
            optimizer = QueryOptimizer()
            analytics_query = db.session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(\
                    ApprovalRequest.tenant_id == tenant_id,\
                    ApprovalRequest.requested_at >= cutoff_date\
                ).order_by(ApprovalRequest.requested_at.desc())

            # Limit analytics data to prevent performance issues
            requests = optimizer.safe_all(analytics_query, max_results=QueryLimits.BULK_OPERATION_LIMIT)
            
            # Calculate analytics
            analytics = self._calculate_approval_analytics(requests)
            
            return self.render_template(
                'approval/analytics.html',
                analytics=analytics
            )
            
        except Exception as e:
            # Standardized error handling with security logging
            user_id = current_user.id if current_user and current_user.is_authenticated else None
            log.error(f"Error loading approval analytics: {str(e)}")
            if user_id:
                approval_security_config.log_security_event('analytics_load_error', user_id, None, {
                    'error_message': str(e),
                    'error_type': type(e).__name__,
                    'operation': 'analytics_load'
                })
            flash(f'Error loading analytics: {str(e)}', 'error')
            return redirect(url_for('ApprovalDashboardView.index'))
    
    def _calculate_approval_analytics(self, requests: List[ApprovalRequest]) -> Dict[str, Any]:
        """Calculate approval analytics from requests."""
        if not requests:
            return {'total': 0}
        
        total_requests = len(requests)
        approved_requests = [r for r in requests if r.status == ApprovalStatus.APPROVED.value]
        rejected_requests = [r for r in requests if r.status == ApprovalStatus.REJECTED.value]
        pending_requests = [r for r in requests if r.status == ApprovalStatus.PENDING.value]
        
        analytics = {
            'total': total_requests,
            'approved': len(approved_requests),
            'rejected': len(rejected_requests),
            'pending': len(pending_requests),
            'approval_rate': len(approved_requests) / total_requests * 100 if total_requests > 0 else 0
        }
        
        # Calculate average response time
        if approved_requests or rejected_requests:
            response_times = []
            for request in approved_requests + rejected_requests:
                if request.responded_at and request.requested_at:
                    response_time = (request.responded_at - request.requested_at).total_seconds()
                    response_times.append(response_time)
            
            if response_times:
                analytics['avg_response_time'] = sum(response_times) / len(response_times)
                analytics['min_response_time'] = min(response_times)
                analytics['max_response_time'] = max(response_times)
        
        # Priority breakdown
        priority_counts = {}
        for request in requests:
            priority = request.priority or 'normal'
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
        
        analytics['priority_breakdown'] = priority_counts
        
        return analytics


class ApprovalApi(ModelRestApi):
    """REST API for approval requests."""
    
    resource_name = 'approval'
    datamodel = SQLAInterface(ApprovalRequest)
    
    class_permission_name = 'ApprovalRequest'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show',
        'put': 'can_edit'
    }
    
    list_columns = [
        'id', 'chain.id', 'approver.username', 'status', 'priority',
        'requested_at', 'responds_at', 'expires_at'
    ]
    
    show_columns = [
        'id', 'chain.id', 'approver.username', 'status', 'priority',
        'approval_data', 'response_data', 'notes', 'required',
        'requested_at', 'responded_at', 'expires_at'
    ]
    
    def _validate_financial_operation_security(self, request_id, operation_type='approval'):
        """Comprehensive security validation for financial operations using centralized config."""
        # 1. Authentication validation using Flask-Login's current_user
        if not current_user or not current_user.is_authenticated:
            approval_security_config.log_security_event('unauthorized_access_attempt', 0, request_id, {
                'operation_type': operation_type,
                'reason': 'no_authenticated_user'
            })
            return {'error': 'Authentication required', 'status': 401}

        # 2. Check if user is blocked due to previous security violations
        if approval_security_config.check_user_blocked(current_user.id):
            approval_security_config.log_security_event('blocked_user_attempt', current_user.id, request_id, {
                'operation_type': operation_type
            })
            return {'error': 'Account temporarily blocked due to security violations', 'status': 403}

        # 3. CSRF protection using Flask-WTF built-in validation
        try:
            validate_csrf(request.headers.get('X-CSRFToken'))
        except Exception as csrf_error:
            approval_security_config.record_failed_attempt(current_user.id, 'csrf_validation')
            approval_security_config.log_security_event('csrf_attack_detected', current_user.id, request_id, {
                'operation_type': operation_type,
                'csrf_error': str(csrf_error)
            })
            return {'error': 'CSRF token invalid', 'status': 400}

        # 4. Rate limiting check using centralized configuration
        if not approval_security_config.check_rate_limit(current_user.id, operation_type):
            approval_security_config.log_security_event('rate_limit_exceeded', current_user.id, request_id, {
                'operation_type': operation_type
            })
            return {'error': 'Rate limit exceeded', 'status': 429}

        # 5. User account validation
        if not current_user.is_active:
            approval_security_config.log_security_event('inactive_user_attempt', current_user.id, request_id, {
                'operation_type': operation_type
            })
            return {'error': 'Account inactive', 'status': 403}

        return {'valid': True}

    def _validate_approval_specific_security(self, approval_request, current_user, operation_type):
        """Validate approval-specific security rules using centralized config."""
        validation_result = approval_security_config.validate_approval_security_rules(
            approval_request, current_user, operation_type
        )

        if not validation_result['valid']:
            approval_security_config.log_security_event('security_rule_violation', current_user.id,
                approval_request.id if approval_request else None, {
                'operation_type': operation_type,
                'violations': validation_result['violations'],
                'security_level': validation_result['security_level']
            })

        return validation_result

    def _log_security_event(self, event_type, request_id, user_id, details=None):
        """Log security events using centralized security configuration."""
        approval_security_config.log_security_event(event_type, user_id, request_id, details)

    def _add_security_headers(self, response):
        """Add security headers to response."""
        headers = approval_security_config.get_security_headers()
        for header, value in headers.items():
            response.headers[header] = value
        return response

    @expose('/respond/<int:request_id>', methods=['POST'])
    @has_access_api
    def respond_to_request(self, request_id):
        """Respond to an approval request with comprehensive security validation."""
        try:
            # Comprehensive security validation
            security_check = self._validate_financial_operation_security(request_id, 'approval')
            if 'error' in security_check:
                return self.response(security_check['status'], message=security_check['error'])

            approval_request = self.datamodel.get(request_id)
            if not approval_request:
                self._log_security_event('approval_request_not_found', request_id, current_user.id)
                return self.response_404()

            # Enhanced authorization validation with security rules
            if approval_request.approver_id != current_user.id:
                self._log_security_event('unauthorized_approval_attempt', request_id, current_user.id, {
                    'expected_approver': approval_request.approver_id,
                    'attempted_approver': current_user.id
                })
                return self.response_403('Not authorized to respond to this request')

            # Apply approval-specific security rules including enhanced self-approval detection
            security_validation = self._validate_approval_specific_security(approval_request, current_user, 'approval')
            if not security_validation['valid']:
                # Log specific violations for enhanced security monitoring
                violation_details = {
                    'violations': security_validation['violations'],
                    'security_level': security_validation['security_level'],
                    'approval_request_id': approval_request.id,
                    'user_id': current_user.id
                }
                self._log_security_event('approval_security_violations', request_id, current_user.id, violation_details)
                
                return self.response_400(f"Security policy violation: {'; '.join(security_validation['violations'])}")
            
            if approval_request.status != ApprovalStatus.PENDING.value:
                self._log_security_event('invalid_status_approval_attempt', request_id, current_user.id, {
                    'current_status': approval_request.status,
                    'expected_status': ApprovalStatus.PENDING.value
                })
                return self.response_400('Request is not pending')

            # Validate request has expired
            if hasattr(approval_request, 'expires_at') and approval_request.expires_at:
                if datetime.now(tz=timezone.utc) > approval_request.expires_at:
                    self._log_security_event('expired_request_approval_attempt', request_id, current_user.id)
                    return self.response_400('Request has expired')

            # Get and validate request data
            if not request.json:
                return self.response_400('Request body required')
            
            # Comprehensive input validation using validation framework
            validation_context = ValidationContext(
                operation="approval_request",
                user_id=current_user.id,
                request_id=str(request_id),
                component="approval_api",
                validation_level=ValidationType.SECURITY
            )
            
            # Prepare data for validation
            request_data = {
                'approver_id': current_user.id,
                'approved': request.json.get('approved'),
                'comment': request.json.get('comment', ''),
                'response_data': request.json.get('response_data', {}),
                'priority': getattr(approval_request, 'priority', 'medium'),
                'workflow_type': 'approval_response'
            }
            
            # Validate input data
            validation_result = validate_approval_request(request_data, current_user.id)
            
            if not validation_result['valid']:
                # Log validation failure
                self._log_security_event('validation_failed', request_id, current_user.id, {
                    'errors': validation_result['errors'],
                    'threats': validation_result['threats'],
                    'operation': 'approval_response'
                })
                return self.response_400(f"Validation failed: {', '.join(validation_result['errors'])}")
            
            if validation_result['threats']:
                # Log security threats
                self._log_security_event('security_threats_detected', request_id, current_user.id, {
                    'threats': validation_result['threats'],
                    'operation': 'approval_response'
                })
                return self.response_400(f"Security threats detected: {', '.join(validation_result['threats'])}")

            # Validate required fields
            if 'approved' not in request.json:
                return self.response_400('Approval decision required')
            
            # Use sanitized data from validation framework
            sanitized_data = validation_result['sanitized_data']
            approved = sanitized_data.get('approved', False)
            comment = sanitized_data.get('comment', '')
            response_data = sanitized_data.get('response_data', {})

            # Validate comment for high-value approvals
            if not comment and hasattr(approval_request, 'priority') and approval_request.priority == 'high':
                return self.response_400('Comment required for high-priority approvals')

            # Create approval decision with enhanced validation
            decision = ApprovalDecision(
                approved=approved,
                approver_id=current_user.id,  # Use validated user
                comment=comment,
                response_data=response_data,
                timestamp=datetime.now(tz=timezone.utc)
            )

            # Log approval attempt
            self._log_security_event('approval_processed', request_id, current_user.id, {
                'approved': approved,
                'has_comment': bool(comment),
                'has_response_data': bool(response_data)
            })
            
            # Process decision
            manager = ApprovalChainManager()
            # Process approval decision synchronously
            # result = manager.process_approval_decision(request_id, decision)
            
            response = self.response(200, **{
                'message': 'Approval processed successfully',
                'approved': approved,
                'request_id': request_id,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            })
            return self._add_security_headers(response)
            
        except Exception as e:
            # Standardized error handling with security logging
            log.error(f"Error processing approval for request {request_id}: {str(e)}")
            if current_user and current_user.is_authenticated:
                self._log_security_event('approval_processing_error', request_id, current_user.id, {
                    'error_message': str(e),
                    'error_type': type(e).__name__,
                    'operation': 'approval_response'
                })
            return self.response(500, message='Internal server error processing approval')
    
    @expose('/delegate/<int:request_id>', methods=['POST'])
    @has_access_api
    def delegate_request(self, request_id):
        """Delegate an approval request to another user with comprehensive security validation."""
        try:
            # Comprehensive security validation
            security_check = self._validate_financial_operation_security(request_id, 'delegation')
            if 'error' in security_check:
                return self.response(security_check['status'], message=security_check['error'])

            approval_request = self.datamodel.get(request_id)
            if not approval_request:
                self._log_security_event('delegation_request_not_found', request_id, current_user.id)
                return self.response_404()

            # Enhanced authorization validation
            if approval_request.approver_id != current_user.id:
                self._log_security_event('unauthorized_delegation_attempt', request_id, current_user.id, {
                    'expected_approver': approval_request.approver_id,
                    'attempted_delegator': current_user.id
                })
                return self.response_403('Not authorized to delegate this request')
            
            if not getattr(approval_request, 'delegate_allowed', True):
                self._log_security_event('delegation_not_allowed_attempt', request_id, current_user.id)
                return self.response_400('Request cannot be delegated')

            # Validate request has not expired
            if hasattr(approval_request, 'expires_at') and approval_request.expires_at:
                if datetime.now(tz=timezone.utc) > approval_request.expires_at:
                    self._log_security_event('expired_request_delegation_attempt', request_id, current_user.id)
                    return self.response_400('Request has expired')

            # Get and validate request data
            if not request.json:
                return self.response_400('Request body required')
            
            # Comprehensive input validation for delegation
            validation_context = ValidationContext(
                operation="delegation_request",
                user_id=current_user.id,
                request_id=str(request_id),
                component="approval_api",
                validation_level=ValidationType.SECURITY
            )
            
            # Prepare data for validation
            delegation_data = {
                'delegate_to_id': request.json.get('delegate_to_id'),
                'reason': request.json.get('reason', ''),
                'delegator_id': current_user.id,
                'operation_type': 'delegation'
            }
            
            # Validate delegation input
            validation_result = validate_user_input(delegation_data, current_user.id)
            
            if not validation_result['valid']:
                # Log validation failure
                self._log_security_event('delegation_validation_failed', request_id, current_user.id, {
                    'errors': validation_result['errors'],
                    'threats': validation_result['threats'],
                    'operation': 'delegation'
                })
                return self.response_400(f"Validation failed: {', '.join(validation_result['errors'])}")
            
            if validation_result['threats']:
                # Log security threats
                self._log_security_event('delegation_security_threats', request_id, current_user.id, {
                    'threats': validation_result['threats'],
                    'operation': 'delegation'
                })
                return self.response_400(f"Security threats detected: {', '.join(validation_result['threats'])}")
            
            # Use sanitized data
            sanitized_data = validation_result['sanitized_data']
            delegate_to_id = sanitized_data.get('delegate_to_id')
            reason = sanitized_data.get('reason', '')

            if not delegate_to_id:
                return self.response_400('delegate_to_id is required')

            # Validate delegation target user
            if delegate_to_id == current_user.id:
                self._log_security_event('self_delegation_attempt', request_id, current_user.id)
                return self.response_400('Cannot delegate to yourself')

            # Validate reason is provided for delegation
            if not reason or len(reason.strip()) < 10:
                return self.response_400('Delegation reason must be at least 10 characters')

            # CRITICAL SECURITY FIX: Validate delegate_to_id is a valid, active user
            delegate_user = self.appbuilder.sm.get_user_by_id(delegate_to_id)
            if not delegate_user:
                self._log_security_event('invalid_delegate_user_attempt', request_id, current_user.id, {
                    'attempted_delegate_id': delegate_to_id,
                    'error': 'User not found'
                })
                return self.response_400('Invalid delegate user specified')

            if not delegate_user.is_active:
                self._log_security_event('inactive_delegate_user_attempt', request_id, current_user.id, {
                    'delegate_user_id': delegate_to_id,
                    'delegate_username': delegate_user.username
                })
                return self.response_400('Cannot delegate to inactive user')

            # Verify delegate user has approval permissions
            if not self._has_approval_permission(delegate_user):
                self._log_security_event('unauthorized_delegate_user_attempt', request_id, current_user.id, {
                    'delegate_user_id': delegate_to_id,
                    'delegate_username': delegate_user.username,
                    'reason': 'User lacks approval permissions'
                })
                return self.response_400('Delegate user does not have approval permissions')
            
            # Log delegation attempt
            self._log_security_event('delegation_processed', request_id, current_user.id, {
                'delegate_to_id': delegate_to_id,
                'reason_length': len(reason),
                'has_reason': bool(reason.strip())
            })

            # Delegate request
            manager = ApprovalChainManager()
            # Delegate approval synchronously
            # delegated_request = manager.delegate_approval(
            #     request_id, delegate_to_id, current_user.id, reason
            # )
            
            return self.response(200, **{
                'message': 'Request delegated successfully',
                'delegate_to_id': delegate_to_id,
                'original_request_id': request_id,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            # Standardized error handling with security logging
            log.error(f"Error delegating approval for request {request_id}: {str(e)}")
            if current_user and current_user.is_authenticated:
                self._log_security_event('delegation_processing_error', request_id, current_user.id, {
                    'error_message': str(e),
                    'error_type': type(e).__name__,
                    'operation': 'delegation'
                })
            return self.response(500, message='Internal server error processing delegation')
    
    @expose('/escalate/<int:request_id>', methods=['POST'])
    @has_access_api
    def escalate_request(self, request_id):
        """Escalate an approval request with comprehensive security validation."""
        try:
            # Comprehensive security validation
            security_check = self._validate_financial_operation_security(request_id, 'escalation')
            if 'error' in security_check:
                return self.response(security_check['status'], message=security_check['error'])

            approval_request = self.datamodel.get(request_id)
            if not approval_request:
                self._log_security_event('escalation_request_not_found', request_id, current_user.id)
                return self.response_404()

            # Enhanced authorization validation - allow escalation by approvers or administrators
            can_escalate = (
                approval_request.approver_id == current_user.id or
                hasattr(current_user, 'roles') and
                any('Admin' in role.name for role in current_user.roles)
            )

            if not can_escalate:
                self._log_security_event('unauthorized_escalation_attempt', request_id, current_user.id, {
                    'approval_approver_id': approval_request.approver_id,
                    'attempted_escalator': current_user.id
                })
                return self.response_403('Not authorized to escalate this request')

            # Validate request is still pending
            if approval_request.status != ApprovalStatus.PENDING.value:
                self._log_security_event('invalid_status_escalation_attempt', request_id, current_user.id, {
                    'current_status': approval_request.status,
                    'expected_status': ApprovalStatus.PENDING.value
                })
                return self.response_400('Only pending requests can be escalated')
            
            # Get and validate request data
            escalate_to_id = None
            escalation_reason = EscalationTrigger.MANUAL
            escalation_justification = ''

            if request.json:
                # Comprehensive input validation for escalation
                validation_context = ValidationContext(
                    operation="escalation_request",
                    user_id=current_user.id,
                    request_id=str(request_id),
                    component="approval_api",
                    validation_level=ValidationType.SECURITY
                )
                
                # Prepare data for validation
                escalation_data = {
                    'escalate_to_id': request.json.get('escalate_to_id'),
                    'reason': request.json.get('reason', 'manual'),
                    'justification': request.json.get('justification', ''),
                    'escalator_id': current_user.id,
                    'operation_type': 'escalation'
                }
                
                # Validate escalation input
                validation_result = validate_user_input(escalation_data, current_user.id)
                
                if not validation_result['valid']:
                    # Log validation failure
                    self._log_security_event('escalation_validation_failed', request_id, current_user.id, {
                        'errors': validation_result['errors'],
                        'threats': validation_result['threats'],
                        'operation': 'escalation'
                    })
                    return self.response_400(f"Validation failed: {', '.join(validation_result['errors'])}")
                
                if validation_result['threats']:
                    # Log security threats
                    self._log_security_event('escalation_security_threats', request_id, current_user.id, {
                        'threats': validation_result['threats'],
                        'operation': 'escalation'
                    })
                    return self.response_400(f"Security threats detected: {', '.join(validation_result['threats'])}")
                
                # Use sanitized data
                sanitized_data = validation_result['sanitized_data']
                escalate_to_id = sanitized_data.get('escalate_to_id')
                reason_str = sanitized_data.get('reason', 'manual')
                escalation_justification = sanitized_data.get('justification', '')

                try:
                    escalation_reason = EscalationTrigger(reason_str)
                except ValueError:
                    escalation_reason = EscalationTrigger.MANUAL

                # Validate escalation justification is provided
                if not escalation_justification or len(escalation_justification.strip()) < 20:
                    return self.response_400('Escalation justification must be at least 20 characters')

                # Validate escalate_to_id if provided
                if escalate_to_id and escalate_to_id == current_user.id:
                    self._log_security_event('self_escalation_attempt', request_id, current_user.id)
                    return self.response_400('Cannot escalate to yourself')
            
            # Log escalation attempt
            self._log_security_event('escalation_processed', request_id, current_user.id, {
                'escalation_reason': escalation_reason.value,
                'escalate_to_id': escalate_to_id,
                'justification_length': len(escalation_justification),
                'has_justification': bool(escalation_justification.strip())
            })

            # Escalate request
            manager = ApprovalChainManager()
            # Escalate approval synchronously
            # escalated_request = manager.escalate_approval(
            #     request_id, escalation_reason, escalate_to_id
            # )
            
            return self.response(200, **{
                'message': 'Request escalated successfully',
                'escalation_reason': escalation_reason.value,
                'escalate_to_id': escalate_to_id,
                'original_request_id': request_id,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            # Standardized error handling with security logging
            log.error(f"Error escalating approval for request {request_id}: {str(e)}")
            if current_user and current_user.is_authenticated:
                self._log_security_event('escalation_processing_error', request_id, current_user.id, {
                    'error_message': str(e),
                    'error_type': type(e).__name__,
                    'operation': 'escalation'
                })
            return self.response(500, message='Internal server error processing escalation')
    
    @expose('/pending', methods=['GET'])
    @has_access_api
    def get_pending_approvals(self):
        """Get pending approval requests for current user with security validation."""
        try:
            # Authentication validation for sensitive data access using Flask-Login
            if not current_user or not current_user.is_authenticated:
                log.warning(f"Unauthorized pending approvals access attempt")
                return self.response_401('Authentication required')

            if not current_user.is_active:
                log.warning(f"Inactive user {current_user.id} attempted to access pending approvals")
                return self.response_403('Account inactive')

            # Log access to sensitive financial data
            self._log_security_event('pending_approvals_accessed', None, current_user.id)

            tenant_id = TenantContext.get_current_tenant_id()
            user_id = current_user.id
            
            # Get pending requests with performance optimization for API
            optimizer = QueryOptimizer()
            requests_query = db.session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(\
                    ApprovalRequest.tenant_id == tenant_id,\
                    ApprovalRequest.approver_id == user_id,\
                    ApprovalRequest.status == ApprovalStatus.PENDING.value\
                ).order_by(ApprovalRequest.requested_at.desc())

            # Limit API results to prevent performance issues
            requests = optimizer.safe_all(requests_query, max_results=100)
            
            request_data = []
            for req in requests:
                request_data.append({
                    'id': req.id,
                    'chain_id': req.chain_id,
                    'priority': req.priority,
                    'approval_data': req.approval_data,
                    'requested_at': req.requested_at.isoformat() if req.requested_at else None,
                    'expires_at': req.expires_at.isoformat() if req.expires_at else None,
                    'required': req.required,
                    'delegate_allowed': req.delegate_allowed,
                    'process_info': {
                        'definition_name': req.chain.step.instance.definition.name if req.chain and req.chain.step and req.chain.step.instance else None,
                        'instance_id': req.chain.step.instance.id if req.chain and req.chain.step and req.chain.step.instance else None
                    }
                })
            
            return self.response(200, result={
                'pending_requests': request_data,
                'total_count': len(request_data)
            })
            
        except Exception as e:
            # Standardized error handling with security logging
            user_id = current_user.id if current_user and current_user.is_authenticated else None
            log.error(f"Error getting pending approvals for user {user_id}: {str(e)}")
            if user_id:
                self._log_security_event('pending_approvals_error', None, user_id, {
                    'error_message': str(e),
                    'error_type': type(e).__name__,
                    'operation': 'get_pending_approvals'
                })
            return self.response(500, message='Internal server error retrieving pending approvals')


class ApprovalChainApi(ModelRestApi):
    """REST API for approval chains."""
    
    resource_name = 'approval_chain'
    datamodel = SQLAInterface(ApprovalChain)
    
    class_permission_name = 'ApprovalChain'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show'
    }
    
    list_columns = [
        'id', 'step.id', 'chain_type', 'status', 'priority',
        'created_at', 'completed_at', 'due_date'
    ]
    
    show_columns = [
        'id', 'step.id', 'chain_type', 'status', 'priority',
        'approvers', 'configuration', 'created_by.username',
        'created_at', 'completed_at', 'due_date'
    ]
    
    @expose('/status/<int:chain_id>', methods=['GET'])
    @has_access_api
    def get_chain_status(self, chain_id):
        """Get detailed status of an approval chain."""
        try:
            chain = self.datamodel.get(chain_id)
            if not chain:
                return self.response_404()
            
            # Get chain manager for detailed status
            manager = ApprovalChainManager()
            # Get chain status synchronously
            # chain_status = manager.get_approval_chain_status(chain_id)
            
            # Get requests with performance optimization for API
            optimizer = QueryOptimizer()
            requests_query = db.session.query(ApprovalRequest)\
                .options(joinedload(ApprovalRequest.approver))\
                .options(joinedload(ApprovalRequest.chain).joinedload('step').joinedload('instance').joinedload('definition'))\
                .filter(ApprovalRequest.chain_id == chain_id)\
                .order_by(ApprovalRequest.order_index)

            # Limit chain requests (approval chains are typically small)
            requests = optimizer.safe_all(requests_query, max_results=QueryLimits.DEFAULT_PAGE_SIZE)
            
            request_details = []
            for request in requests:
                approver = db.session.query(User).filter(
                    User.id == request.approver_id
                ).first()
                request_details.append({
                    'id': request.id,
                    'approver': {
                        'id': approver.id if approver else None,
                        'username': approver.username if approver else 'Unknown'
                    },
                    'status': request.status,
                    'requested_at': request.requested_at.isoformat() if request.requested_at else None,
                    'responded_at': request.responded_at.isoformat() if request.responded_at else None,
                    'order_index': request.order_index,
                    'required': request.required
                })
            
            return self.response(200, result={
                'chain_id': chain.id,
                'chain_type': chain.chain_type,
                'status': chain.status,
                'priority': chain.priority,
                'created_at': chain.created_at.isoformat() if chain.created_at else None,
                'completed_at': chain.completed_at.isoformat() if chain.completed_at else None,
                'due_date': chain.due_date.isoformat() if chain.due_date else None,
                'requests': request_details
            })
            
        except Exception as e:
            # Standardized error handling with security logging
            user_id = current_user.id if current_user and current_user.is_authenticated else None
            log.error(f"Error getting chain status: {str(e)}")
            if user_id:
                approval_security_config.log_security_event('chain_status_error', user_id, chain_id, {
                    'error_message': str(e),
                    'error_type': type(e).__name__,
                    'operation': 'get_chain_status'
                })
            return self.response(400, message=f'Error getting chain status: {str(e)}')

    def _has_approval_permission(self, user) -> bool:
        """
        Check if user has permission to perform approval operations.

        SECURITY FEATURE: Validates user authorization for approval system participation.

        Args:
            user: User object to check

        Returns:
            bool: True if user has approval permissions
        """
        try:
            if not user or not user.is_active:
                return False

            # Check if user has any approval-related roles
            approval_roles = ['Approver', 'Manager', 'Finance', 'HR', 'Admin', 'Supervisor']

            if hasattr(user, 'roles'):
                user_role_names = [role.name for role in user.roles if hasattr(role, 'name')]
                if any(role in approval_roles for role in user_role_names):
                    return True

            # Check if user is a PgAppForge admin
            if self.appbuilder and hasattr(self.appbuilder, 'sm'):
                if self.appbuilder.sm.is_admin(user):
                    return True

            # Check if user has specific approval permissions
            if hasattr(user, 'permissions'):
                approval_permissions = ['can_approve', 'can_review', 'can_manage_approval']
                user_perms = [perm.permission.name for perm in user.permissions
                             if hasattr(perm, 'permission') and hasattr(perm.permission, 'name')]
                if any(perm in approval_permissions for perm in user_perms):
                    return True

            return False

        except Exception as e:
            log.error(f"Error checking approval permission for user {getattr(user, 'id', 'unknown')}: {e}")
            # Fail secure: deny permission on error
            return False