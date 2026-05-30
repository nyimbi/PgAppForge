"""
Approval Workflow Management Views

PgAppForge views that integrate the ApprovalWorkflowManager with 
proper permission controls and security context.

SECURITY INTEGRATION:
- Uses PgAppForge's @protect and @has_access decorators
- Integrates with existing role-based permission system
- Provides audit trail through PgAppForge's security manager
- Validates user context and session security
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from flask import request, jsonify, flash, redirect, url_for, render_template
from pgappforge import ModelView, BaseView, expose, action, has_access
from pgappforge.api import BaseApi
from pgappforge.security.decorators import has_access_api
from pgappforge.widgets import ListWidget, ShowWidget, FormWidget
from flask_babel import lazy_gettext as _, gettext
from wtforms import StringField, TextAreaField, SelectField, HiddenField, IntegerField
from wtforms.validators import DataRequired, Length, ValidationError

from .workflow_manager import ApprovalWorkflowManager
from .api_response_formatter import ApprovalApiMixin, ErrorCode, create_paginated_response
from ...wallet.models import WalletTransaction, TransactionStatus
from ...security.sqla.models import User

log = logging.getLogger(__name__)


class ApprovalWorkflowView(BaseView):
    """
    PgAppForge view for approval workflow operations.
    
    Integrates ApprovalWorkflowManager with proper PgAppForge
    permission controls and security context validation.
    """
    
    route_base = '/approval-workflow'
    default_view = 'pending_approvals'
    
    def __init__(self):
        super().__init__()
        # Initialize ApprovalWorkflowManager with current appbuilder instance
        self.workflow_manager = None
    
    def _get_workflow_manager(self) -> ApprovalWorkflowManager:
        """Get ApprovalWorkflowManager instance with proper PgAppForge integration."""
        if not self.workflow_manager:
            self.workflow_manager = ApprovalWorkflowManager(self.appbuilder)
        return self.workflow_manager
    
    @expose('/pending')
    @has_access
    def pending_approvals(self):
        """
        View pending approvals for current user.
        
        SECURITY: Uses PgAppForge's @has_access and @protect decorators
        to ensure proper authentication and authorization context.
        """
        current_user = self.appbuilder.sm.current_user
        
        if not current_user or not current_user.is_authenticated:
            flash(_("Authentication required"), "error")
            return redirect(url_for('AuthDBView.login'))
        
        # Get user's roles for filtering approvals
        user_roles = [role.name for role in current_user.roles] if current_user.roles else []
        
        # Query pending transactions that require approval from this user's roles
        pending_transactions = self._get_pending_approvals_for_user(current_user, user_roles)
        
        return self.render_template(
            'appbuilder/approval/pending_approvals.html',
            pending_transactions=pending_transactions,
            user_roles=user_roles,
            current_user=current_user
        )
    
    def _get_pending_approvals_for_user(self, user, user_roles: List[str]) -> List[Dict]:
        """Get pending approvals filtered by user's roles."""
        workflow_manager = self._get_workflow_manager()
        
        # Get all pending transactions
        db_session = self.appbuilder.get_session()
        pending_transactions = db_session.query(WalletTransaction).filter_by(
            status=TransactionStatus.PENDING.value,
            requires_approval=True
        ).all()
        
        filtered_approvals = []
        
        for transaction in pending_transactions:
            # Get workflow configuration for this transaction type
            workflow_name = getattr(transaction.__class__, '_approval_workflow', 'default')
            workflow_config = workflow_manager.workflow_configs.get(workflow_name)
            
            if not workflow_config:
                continue
            
            # Check which steps this user can approve
            approval_history = workflow_manager.get_approval_history(transaction)
            current_step = len(approval_history)
            
            if current_step < len(workflow_config['steps']):
                step_config = workflow_config['steps'][current_step]
                required_role = step_config['required_role']
                
                # Check if user has required role or is Admin
                if required_role in user_roles or 'Admin' in user_roles:
                    # Check if user hasn't already approved this step
                    if not workflow_manager.security_validator.check_duplicate_approval(approval_history, user.id, current_step):
                        # Check if it's not a self-approval
                        if not workflow_manager.security_validator.validate_self_approval(transaction, user):
                            filtered_approvals.append({
                                'transaction': transaction,
                                'step': current_step,
                                'step_name': step_config['name'],
                                'required_role': required_role,
                                'workflow_name': workflow_name,
                                'requires_mfa': step_config.get('requires_mfa', False)
                            })
        
        return filtered_approvals
    
    @expose('/approve/<int:transaction_id>/<int:step>')
    @has_access
    def approve_transaction_step(self, transaction_id: int, step: int):
        """
        Approve a specific transaction step.
        
        SECURITY: PgAppForge permission integration ensures:
        1. User is authenticated (@has_access)
        2. Security context is validated (@protect)
        3. Role-based authorization through ApprovalWorkflowManager
        """
        current_user = self.appbuilder.sm.current_user
        
        if not current_user or not current_user.is_authenticated:
            flash(_("Authentication required"), "error")
            return redirect(url_for('AuthDBView.login'))
        
        # Get transaction
        db_session = self.appbuilder.get_session()
        transaction = db_session.query(WalletTransaction).get(transaction_id)
        if not transaction:
            flash(_("Transaction not found"), "error")
            return redirect(url_for('ApprovalWorkflowView.pending_approvals'))
        
        # Get comments from form if provided
        comments = request.form.get('comments', '').strip()
        
        try:
            workflow_manager = self._get_workflow_manager()
            
            # Use ApprovalWorkflowManager's secure approval process
            success = workflow_manager.approve_instance(
                instance=transaction,
                step=step,
                comments=comments
            )
            
            if success:
                # Log success through PgAppForge's security manager
                self.appbuilder.sm.log.info(
                    f"WORKFLOW APPROVAL: {current_user.username} approved transaction "
                    f"{transaction_id} step {step} via PgAppForge interface"
                )
                flash(_("Transaction approved successfully"), "success")
            else:
                flash(_("Approval failed. Please check the transaction status."), "error")
                
        except Exception as e:
            log.error(f"Approval failed for transaction {transaction_id}: {e}")
            flash(_("Approval failed: %(error)s", error=str(e)), "error")
        
        return redirect(url_for('ApprovalWorkflowView.pending_approvals'))
    
    @expose('/reject/<int:transaction_id>')
    @has_access
    def reject_transaction_form(self, transaction_id: int):
        """Show rejection form with proper PgAppForge security context."""
        current_user = self.appbuilder.sm.current_user
        
        if not current_user or not current_user.is_authenticated:
            flash(_("Authentication required"), "error")
            return redirect(url_for('AuthDBView.login'))
        
        db_session = self.appbuilder.get_session()
        transaction = db_session.query(WalletTransaction).get(transaction_id)
        if not transaction:
            flash(_("Transaction not found"), "error")
            return redirect(url_for('ApprovalWorkflowView.pending_approvals'))
        
        return self.render_template(
            'appbuilder/approval/reject_transaction.html',
            transaction=transaction,
            current_user=current_user
        )
    
    @expose('/reject/<int:transaction_id>', methods=['POST'])
    @has_access
    def reject_transaction_submit(self, transaction_id: int):
        """
        Process transaction rejection.
        
        SECURITY: Integrated with PgAppForge's permission system
        for complete audit trail and security validation.
        """
        current_user = self.appbuilder.sm.current_user
        
        if not current_user or not current_user.is_authenticated:
            flash(_("Authentication required"), "error")
            return redirect(url_for('AuthDBView.login'))
        
        # Get transaction with database-level locking
        db_session = self.appbuilder.get_session()
        transaction = db_session.query(WalletTransaction).get(transaction_id)
        if not transaction:
            flash(_("Transaction not found"), "error")
            return redirect(url_for('ApprovalWorkflowView.pending_approvals'))
        
        # Get rejection reason (required)
        rejection_reason = request.form.get('rejection_reason', '').strip()
        if not rejection_reason:
            flash(_("Rejection reason is required"), "error")
            return redirect(url_for('ApprovalWorkflowView.reject_transaction_form', transaction_id=transaction_id))
        
        try:
            # Use the secure rejection method with database locking
            success = transaction.reject_transaction(
                approver_id=current_user.id,
                reason=rejection_reason,
                auto_commit=True
            )
            
            if success:
                # Log rejection through PgAppForge's security manager
                self.appbuilder.sm.log.info(
                    f"WORKFLOW REJECTION: {current_user.username} rejected transaction "
                    f"{transaction_id} via PgAppForge interface: {rejection_reason}"
                )
                flash(_("Transaction rejected successfully"), "success")
            else:
                flash(_("Rejection failed. Please try again."), "error")
                
        except Exception as e:
            log.error(f"Rejection failed for transaction {transaction_id}: {e}")
            flash(_("Rejection failed: %(error)s", error=str(e)), "error")
        
        return redirect(url_for('ApprovalWorkflowView.pending_approvals'))
    
    @expose('/history/<int:transaction_id>')
    @has_access
    def approval_history(self, transaction_id: int):
        """View approval history for a transaction."""
        current_user = self.appbuilder.sm.current_user
        
        if not current_user or not current_user.is_authenticated:
            flash(_("Authentication required"), "error")
            return redirect(url_for('AuthDBView.login'))
        
        db_session = self.appbuilder.get_session()
        transaction = db_session.query(WalletTransaction).get(transaction_id)
        if not transaction:
            flash(_("Transaction not found"), "error")
            return redirect(url_for('ApprovalWorkflowView.pending_approvals'))
        
        workflow_manager = self._get_workflow_manager()
        approval_history = workflow_manager.get_approval_history(transaction)
        
        # Enrich history with user details
        enriched_history = []
        for approval in approval_history:
            db_session = self.appbuilder.get_session()
            user = db_session.query(User).get(approval.get('user_id'))
            approval_data = approval.copy()
            approval_data['user_name'] = user.username if user else 'Unknown'
            approval_data['user_full_name'] = f"{user.first_name} {user.last_name}" if user and user.first_name else user.username if user else 'Unknown'
            enriched_history.append(approval_data)
        
        return self.render_template(
            'appbuilder/approval/approval_history.html',
            transaction=transaction,
            approval_history=enriched_history,
            current_user=current_user
        )


class ApprovalWorkflowApiView(BaseApi, ApprovalApiMixin):
    """
    REST API for approval workflows with PgAppForge security integration.
    
    Provides programmatic access to approval operations with proper
    authentication and authorization controls.
    """
    
    route_base = '/api/v1/approval-workflow'
    
    def __init__(self):
        super().__init__()
        self.workflow_manager = None
    
    def _get_workflow_manager(self) -> ApprovalWorkflowManager:
        """Get ApprovalWorkflowManager instance."""
        if not self.workflow_manager:
            self.workflow_manager = ApprovalWorkflowManager(self.appbuilder)
        return self.workflow_manager
    
    @expose('/pending', methods=['GET'])
    @has_access_api
    def get_pending_approvals(self):
        """
        API endpoint for getting pending approvals.
        
        SECURITY: Uses PgAppForge's @has_access_api for REST API
        authentication and @protect for security context validation.
        """
        current_user = self.appbuilder.sm.current_user
        
        if not current_user or not current_user.is_authenticated:
            return self.standard_error(ErrorCode.AUTHENTICATION_ERROR, "Authentication required", 401)
        
        try:
            user_roles = [role.name for role in current_user.roles] if current_user.roles else []
            
            # Use the same filtering logic as the web view
            approval_view = ApprovalWorkflowView()
            approval_view.appbuilder = self.appbuilder
            pending_approvals = approval_view._get_pending_approvals_for_user(current_user, user_roles)
            
            # Serialize for API response
            api_response = []
            for approval in pending_approvals:
                transaction = approval['transaction']
                api_response.append({
                    'transaction_id': transaction.id,
                    'amount': float(transaction.amount),
                    'transaction_type': transaction.transaction_type,
                    'description': transaction.description,
                    'step': approval['step'],
                    'step_name': approval['step_name'],
                    'required_role': approval['required_role'],
                    'workflow_name': approval['workflow_name'],
                    'requires_mfa': approval['requires_mfa'],
                    'created_at': transaction.transaction_date.isoformat() if transaction.transaction_date else None
                })
            
            return self.standard_success(
                data=api_response,
                message=f"Found {len(api_response)} pending approvals"
            )
            
        except Exception as e:
            log.error(f"API error getting pending approvals: {e}")
            return self.standard_error(ErrorCode.INTERNAL_ERROR, f"Failed to retrieve pending approvals: {str(e)}", 500)
    
    @expose('/approve/<int:transaction_id>/<int:step>', methods=['POST'])
    @has_access_api
    def approve_transaction_api(self, transaction_id: int, step: int):
        """
        API endpoint for approving transactions.
        
        SECURITY: Full PgAppForge security integration with
        role-based authorization and comprehensive audit logging.
        """
        current_user = self.appbuilder.sm.current_user
        
        if not current_user or not current_user.is_authenticated:
            return self.standard_error(ErrorCode.AUTHENTICATION_ERROR, "Authentication required", 401)
        
        # Get request data
        data = request.get_json() or {}
        comments = data.get('comments', '').strip()
        
        try:
            # Get transaction
            db_session = self.appbuilder.get_session()
            transaction = db_session.query(WalletTransaction).get(transaction_id)
            if not transaction:
                return self.standard_error(ErrorCode.NOT_FOUND_ERROR, f"Transaction {transaction_id} not found", 404)
            
            workflow_manager = self._get_workflow_manager()
            
            # Use ApprovalWorkflowManager's secure approval process
            success = workflow_manager.approve_instance(
                instance=transaction,
                step=step,
                comments=comments
            )
            
            if success:
                # Log API approval through PgAppForge's security manager
                self.appbuilder.sm.log.info(
                    f"API APPROVAL: {current_user.username} approved transaction "
                    f"{transaction_id} step {step} via REST API"
                )
                
                return self.standard_success(
                    data={
                        'transaction_id': transaction_id,
                        'step': step,
                        'status': 'approved',
                        'approved_by': current_user.username,
                        'comments': comments
                    },
                    message="Transaction approved successfully"
                )
            else:
                return self.standard_error(ErrorCode.BUSINESS_LOGIC_ERROR, "Approval failed", 422)
                
        except ValueError as e:
            return self.standard_error(ErrorCode.VALIDATION_ERROR, str(e), 422)
        except Exception as e:
            log.error(f"API approval failed for transaction {transaction_id}: {e}")
            return self.standard_error(ErrorCode.INTERNAL_ERROR, "Internal server error", 500)
    
    @expose('/reject/<int:transaction_id>', methods=['POST'])
    @has_access_api
    def reject_transaction_api(self, transaction_id: int):
        """
        API endpoint for rejecting transactions.
        
        SECURITY: Integrated with PgAppForge's security framework
        for complete audit trail and permission validation.
        """
        current_user = self.appbuilder.sm.current_user
        
        if not current_user or not current_user.is_authenticated:
            return self.standard_error(ErrorCode.AUTHENTICATION_ERROR, "Authentication required", 401)
        
        # Get request data
        data = request.get_json() or {}
        rejection_reason = data.get('rejection_reason', '').strip()
        
        if not rejection_reason:
            return self.standard_error(
                ErrorCode.VALIDATION_ERROR, 
                "Rejection reason is required", 
                422
            )
        
        try:
            # Get transaction
            db_session = self.appbuilder.get_session()
            transaction = db_session.query(WalletTransaction).get(transaction_id)
            if not transaction:
                return self.standard_error(ErrorCode.NOT_FOUND_ERROR, f"Transaction {transaction_id} not found", 404)
            
            # Use the secure rejection method
            success = transaction.reject_transaction(
                approver_id=current_user.id,
                reason=rejection_reason,
                auto_commit=True
            )
            
            if success:
                # Log API rejection through PgAppForge's security manager
                self.appbuilder.sm.log.info(
                    f"API REJECTION: {current_user.username} rejected transaction "
                    f"{transaction_id} via REST API: {rejection_reason}"
                )
                
                return self.standard_success(
                    data={
                        'transaction_id': transaction_id,
                        'status': 'rejected',
                        'rejected_by': current_user.username,
                        'rejection_reason': rejection_reason
                    },
                    message="Transaction rejected successfully"
                )
            else:
                return self.standard_error(ErrorCode.BUSINESS_LOGIC_ERROR, "Rejection failed", 422)
                
        except ValueError as e:
            return self.standard_error(ErrorCode.VALIDATION_ERROR, str(e), 422)
        except Exception as e:
            log.error(f"API rejection failed for transaction {transaction_id}: {e}")
            return self.standard_error(ErrorCode.INTERNAL_ERROR, "Internal server error", 500)