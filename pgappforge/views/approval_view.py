"""
Approval View for PgForge
Provides approval functionality that integrates with ApprovalWidget and StateTrackingMixin.
"""

import logging
from flask import flash, redirect, request, url_for
from flask_login import current_user

from ..baseviews import expose
from ..views import ModelView
from ..security.decorators import has_access, permission_name
from ..widgets import ApprovalWidget

log = logging.getLogger(__name__)


class ApprovalModelView(ModelView):
    """
    ModelView with approval capability.
    
    Extends the standard PgForge ModelView to provide
    approval/rejection functionality for records with status tracking.
    """
    
    edit_widget = ApprovalWidget
    
    def __init__(self, *args, **kwargs):
        """Initialize approval model view with widget configuration."""
        super(ApprovalModelView, self).__init__(*args, **kwargs)
        
        # Configure approval widget
        if hasattr(self, 'edit_widget'):
            self.edit_widget = ApprovalWidget(approval_required=True)
    
    @expose('/approve/<int:pk>')
    @has_access
    @permission_name('approve')
    def approve(self, pk):
        """
        Approve a record.
        
        :param pk: Primary key of the record to approve
        :return: Redirect response
        """
        obj = self.datamodel.get(pk)
        if not obj:
            flash('Record not found', 'error')
            return redirect(self.get_redirect())
        
        # Check if object has status field (StateTrackingMixin)
        if not hasattr(obj, 'status'):
            flash('This record does not support approval', 'error')
            return redirect(self.get_redirect())
        
        # Check if user can approve this record
        if not self._can_user_approve(obj):
            flash('You do not have permission to approve this record', 'error')
            return redirect(self.get_redirect())
        
        try:
            # Use StateTrackingMixin transition method if available
            if hasattr(obj, 'transition_to'):
                result = obj.transition_to('approved', 'Approved by admin', user=current_user)
            else:
                # Fallback to direct status update
                obj.status = 'approved'
                obj.status_reason = 'Approved by admin'
            
            # Save the changes
            self.datamodel.edit(obj)
            
            # Send notification if service is available
            self._send_approval_notification(obj, 'approved')
            
            flash(f'Record approved successfully', 'success')
            log.info(f"Record {pk} approved by user {current_user.id if current_user else 'unknown'}")
            
        except Exception as e:
            flash(f'Failed to approve record: {str(e)}', 'error')
            log.error(f"Failed to approve record {pk}: {e}")
        
        return redirect(self.get_redirect())
    
    @expose('/reject/<int:pk>')
    @has_access
    @permission_name('approve')  # Same permission for reject
    def reject(self, pk):
        """
        Reject a record.
        
        :param pk: Primary key of the record to reject
        :return: Redirect response
        """
        obj = self.datamodel.get(pk)
        if not obj:
            flash('Record not found', 'error')
            return redirect(self.get_redirect())
        
        # Check if object has status field (StateTrackingMixin)
        if not hasattr(obj, 'status'):
            flash('This record does not support rejection', 'error')
            return redirect(self.get_redirect())
        
        # Check if user can reject this record
        if not self._can_user_approve(obj):
            flash('You do not have permission to reject this record', 'error')
            return redirect(self.get_redirect())
        
        try:
            # Use StateTrackingMixin transition method if available
            if hasattr(obj, 'transition_to'):
                result = obj.transition_to('rejected', 'Rejected by admin', user=current_user)
            else:
                # Fallback to direct status update
                obj.status = 'rejected' 
                obj.status_reason = 'Rejected by admin'
            
            # Save the changes
            self.datamodel.edit(obj)
            
            # Send notification if service is available
            self._send_approval_notification(obj, 'rejected')
            
            flash(f'Record rejected successfully', 'warning')
            log.info(f"Record {pk} rejected by user {current_user.id if current_user else 'unknown'}")
            
        except Exception as e:
            flash(f'Failed to reject record: {str(e)}', 'error')
            log.error(f"Failed to reject record {pk}: {e}")
        
        return redirect(self.get_redirect())
    
    @expose('/submit_for_approval/<int:pk>')
    @has_access
    def submit_for_approval(self, pk):
        """
        Submit a record for approval.
        
        :param pk: Primary key of the record to submit
        :return: Redirect response  
        """
        obj = self.datamodel.get(pk)
        if not obj:
            flash('Record not found', 'error')
            return redirect(self.get_redirect())
        
        # Check if object has status field
        if not hasattr(obj, 'status'):
            flash('This record does not support approval workflow', 'error')
            return redirect(self.get_redirect())
        
        # Only allow submission from draft status
        if obj.status != 'draft':
            flash('Only draft records can be submitted for approval', 'warning')
            return redirect(self.get_redirect())
        
        try:
            # Use StateTrackingMixin transition method if available
            if hasattr(obj, 'transition_to'):
                result = obj.transition_to('pending_approval', 'Submitted for approval', user=current_user)
            else:
                # Fallback to direct status update
                obj.status = 'pending_approval'
                obj.status_reason = 'Submitted for approval'
            
            # Save the changes
            self.datamodel.edit(obj)
            
            # Send notification to approvers
            self._send_approval_notification(obj, 'submitted')
            
            flash('Record submitted for approval successfully', 'success')
            log.info(f"Record {pk} submitted for approval by user {current_user.id if current_user else 'unknown'}")
            
        except Exception as e:
            flash(f'Failed to submit record for approval: {str(e)}', 'error')
            log.error(f"Failed to submit record {pk} for approval: {e}")
        
        return redirect(self.get_redirect())
    
    def _can_user_approve(self, obj):
        """
        Check if current user can approve/reject this record.
        
        :param obj: Record to check approval permissions for
        :return: True if user can approve
        """
        if not current_user or not hasattr(current_user, 'has_permission'):
            return False
        
        # Check standard PgForge permissions
        return (current_user.has_permission('approve_records') or 
                current_user.has_permission('can_approve') or
                current_user.has_role('Admin'))
    
    def _send_approval_notification(self, obj, action):
        """
        Send notification for approval actions.
        
        :param obj: Record that was acted upon
        :param action: Action taken ('approved', 'rejected', 'submitted')
        """
        try:
            # Try to use NotificationService if available
            from ..services.notification_service import NotificationService
            
            notification_service = NotificationService()
            
            if action == 'approved':
                notification_service.send_approval_notification(obj, 'approved')
            elif action == 'rejected':
                notification_service.send_approval_notification(obj, 'rejected')
            elif action == 'submitted':
                notification_service.send_submission_notification(obj)
                
        except ImportError:
            # NotificationService not available, skip notifications
            log.debug("NotificationService not available, skipping notification")
        except Exception as e:
            # Log error but don't fail the approval process
            log.warning(f"Failed to send approval notification: {e}")
    
    def get_redirect(self):
        """Get redirect URL after approval actions."""
        # Try to redirect to the list view
        try:
            return url_for(f'{self.__class__.__name__}.list')
        except:
            # Fallback to referrer or index
            return request.referrer or url_for('IndexView.index')