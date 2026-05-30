"""
Notification Service for PgAppForge

Provides email notification functionality that integrates with existing Flask-Mail
and works with StateTrackingMixin for status change notifications.
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

from flask import current_app, render_template_string
from flask_login import current_user

# Try to import Flask-Mail Message, with graceful fallback
try:
    from flask_mail import Message
    FLASK_MAIL_AVAILABLE = True
except ImportError:
    FLASK_MAIL_AVAILABLE = False
    Message = None

log = logging.getLogger(__name__)


class NotificationService:
    """
    Simple notification service using existing Flask-Mail.
    
    Provides email notifications for status changes and approval workflows
    that integrate with StateTrackingMixin and ApprovalWidget.
    """
    
    def __init__(self, mail=None):
        """
        Initialize notification service.
        
        :param mail: Flask-Mail instance (defaults to app extension)
        """
        if not FLASK_MAIL_AVAILABLE:
            log.warning("Flask-Mail not available - NotificationService disabled")
            self.mail = None
            return
        
        self.mail = mail or self._get_mail_instance()
    
    def _get_mail_instance(self):
        """Get Flask-Mail instance from current app."""
        try:
            return current_app.extensions.get('mail')
        except (RuntimeError, AttributeError):
            # No app context or mail not configured
            return None
    
    def send_status_notification(self, obj, old_status: str, new_status: str, user=None):
        """
        Send email notification for status changes.
        
        :param obj: Object that changed status
        :param old_status: Previous status
        :param new_status: New status
        :param user: User who made the change
        :return: True if notification sent successfully
        """
        if not self.mail or not self._should_notify(old_status, new_status):
            return False
        
        try:
            # Get notification recipients
            recipients = self._get_notification_recipients(obj, 'status_change')
            if not recipients:
                log.debug(f"No recipients for status change notification: {obj}")
                return False
            
            # Create message using existing Flask-Mail patterns
            msg = Message(
                subject=self._generate_status_subject(obj, old_status, new_status),
                sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                recipients=recipients
            )
            
            # Generate email body
            msg.body = self._generate_status_body(obj, old_status, new_status, user)
            msg.html = self._generate_status_html(obj, old_status, new_status, user)
            
            # Send notification
            self.mail.send(msg)
            log.info(f"Status change notification sent for {obj} to {len(recipients)} recipients")
            return True
            
        except Exception as e:
            log.error(f"Failed to send status notification: {e}")
            return False
    
    def send_approval_notification(self, obj, action: str, user=None):
        """
        Send email notification for approval actions.
        
        :param obj: Object that was approved/rejected
        :param action: Action taken ('approved', 'rejected')
        :param user: User who performed the action
        :return: True if notification sent successfully
        """
        if not self.mail or action not in ['approved', 'rejected']:
            return False
        
        try:
            # Get notification recipients (notify the creator)
            recipients = self._get_notification_recipients(obj, 'approval')
            if not recipients:
                log.debug(f"No recipients for approval notification: {obj}")
                return False
            
            msg = Message(
                subject=self._generate_approval_subject(obj, action),
                sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                recipients=recipients
            )
            
            # Generate email body
            msg.body = self._generate_approval_body(obj, action, user)
            msg.html = self._generate_approval_html(obj, action, user)
            
            # Send notification
            self.mail.send(msg)
            log.info(f"Approval notification ({action}) sent for {obj} to {len(recipients)} recipients")
            return True
            
        except Exception as e:
            log.error(f"Failed to send approval notification: {e}")
            return False
    
    def send_submission_notification(self, obj, user=None):
        """
        Send notification when record is submitted for approval.
        
        :param obj: Object submitted for approval
        :param user: User who submitted
        :return: True if notification sent successfully
        """
        if not self.mail:
            return False
        
        try:
            # Get approvers to notify
            recipients = self._get_approvers_email_list()
            if not recipients:
                log.debug(f"No approvers to notify for submission: {obj}")
                return False
            
            msg = Message(
                subject=self._generate_submission_subject(obj),
                sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                recipients=recipients
            )
            
            # Generate email body
            msg.body = self._generate_submission_body(obj, user)
            msg.html = self._generate_submission_html(obj, user)
            
            # Send notification
            self.mail.send(msg)
            log.info(f"Submission notification sent for {obj} to {len(recipients)} approvers")
            return True
            
        except Exception as e:
            log.error(f"Failed to send submission notification: {e}")
            return False
    
    def _should_notify(self, old_status: str, new_status: str) -> bool:
        """
        Determine if notification should be sent for status change.
        
        :param old_status: Previous status
        :param new_status: New status
        :return: True if notification should be sent
        """
        # Default notification transitions
        notify_transitions = [
            ('pending_approval', 'approved'),
            ('pending_approval', 'rejected'),
            ('draft', 'pending_approval'),
            ('active', 'completed'),
            ('completed', 'archived')
        ]
        
        # Check app config for custom transitions
        custom_transitions = current_app.config.get('FAB_NOTIFICATION_TRANSITIONS', [])
        all_transitions = notify_transitions + custom_transitions
        
        return (old_status, new_status) in all_transitions
    
    def _get_notification_recipients(self, obj, notification_type: str) -> List[str]:
        """
        Get email recipients for notifications.
        
        :param obj: Object to get recipients for
        :param notification_type: Type of notification ('status_change', 'approval')
        :return: List of email addresses
        """
        recipients = []
        
        try:
            # Notify creator (uses existing AuditMixin relationships)
            if hasattr(obj, 'created_by') and obj.created_by:
                if hasattr(obj.created_by, 'email') and obj.created_by.email:
                    recipients.append(obj.created_by.email)
            
            # Notify assigned users if applicable
            if hasattr(obj, 'assigned_to') and obj.assigned_to:
                if hasattr(obj.assigned_to, 'email') and obj.assigned_to.email:
                    recipients.append(obj.assigned_to.email)
            
            # For approval notifications, also notify managers/admins
            if notification_type == 'approval':
                admin_emails = self._get_admin_email_list()
                recipients.extend(admin_emails)
            
            # Remove duplicates and filter out empty emails
            recipients = list(set(filter(None, recipients)))
            
        except Exception as e:
            log.warning(f"Error getting notification recipients: {e}")
        
        return recipients
    
    def _get_approvers_email_list(self) -> List[str]:
        """Get list of email addresses for users who can approve."""
        try:
            # Get users with approval permissions using PgAppForge security
            from pgappforge import current_app
            
            if hasattr(current_app, 'appbuilder') and current_app.appbuilder:
                sm = current_app.appbuilder.sm
                
                # Find users with approval permissions
                approver_emails = []
                
                # Check for approve permission
                approve_perm = sm.find_permission('can_approve')
                if approve_perm:
                    for role in sm.get_all_roles():
                        if approve_perm in role.permissions:
                            for user in role.user:
                                if user.email:
                                    approver_emails.append(user.email)
                
                # Also include admin users
                admin_role = sm.find_role('Admin')
                if admin_role:
                    for user in admin_role.user:
                        if user.email:
                            approver_emails.append(user.email)
                
                return list(set(approver_emails))
                
        except Exception as e:
            log.warning(f"Error getting approver emails: {e}")
        
        return []
    
    def _get_admin_email_list(self) -> List[str]:
        """Get list of admin email addresses."""
        try:
            from pgappforge import current_app
            
            if hasattr(current_app, 'appbuilder') and current_app.appbuilder:
                sm = current_app.appbuilder.sm
                admin_role = sm.find_role('Admin')
                
                if admin_role:
                    return [user.email for user in admin_role.user if user.email]
                    
        except Exception as e:
            log.warning(f"Error getting admin emails: {e}")
        
        return []
    
    def _generate_status_subject(self, obj, old_status: str, new_status: str) -> str:
        """Generate email subject for status change."""
        obj_name = getattr(obj, 'name', str(obj))
        return f"Status Update: {obj_name} - {new_status.replace('_', ' ').title()}"
    
    def _generate_status_body(self, obj, old_status: str, new_status: str, user=None) -> str:
        """Generate plain text email body for status change."""
        obj_name = getattr(obj, 'name', str(obj))
        user_name = getattr(user, 'username', 'System') if user else 'System'
        
        body = f"""
Status Update Notification

Record: {obj_name}
Status Changed: {old_status.replace('_', ' ').title()} → {new_status.replace('_', ' ').title()}
Changed By: {user_name}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        # Add reason if available
        if hasattr(obj, 'status_reason') and obj.status_reason:
            body += f"\nReason: {obj.status_reason}"
        
        return body.strip()
    
    def _generate_status_html(self, obj, old_status: str, new_status: str, user=None) -> str:
        """Generate HTML email body for status change."""
        obj_name = getattr(obj, 'name', str(obj))
        user_name = getattr(user, 'username', 'System') if user else 'System'
        
        # Status badge colors
        status_colors = {
            'draft': '#6c757d',
            'pending_approval': '#ffc107',
            'approved': '#28a745',
            'rejected': '#dc3545',
            'active': '#17a2b8',
            'completed': '#28a745',
            'archived': '#6c757d'
        }
        
        old_color = status_colors.get(old_status, '#6c757d')
        new_color = status_colors.get(new_status, '#6c757d')
        
        html_template = """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #333;">Status Update Notification</h2>
            
            <div style="background: #f8f9fa; padding: 20px; border-radius: 5px; margin: 20px 0;">
                <h3 style="margin-top: 0;">{{ obj_name }}</h3>
                
                <p><strong>Status Changed:</strong></p>
                <div style="display: inline-block; margin: 10px 0;">
                    <span style="background: {{ old_color }}; color: white; padding: 5px 10px; border-radius: 3px;">
                        {{ old_status_label }}
                    </span>
                    <span style="margin: 0 10px;">→</span>
                    <span style="background: {{ new_color }}; color: white; padding: 5px 10px; border-radius: 3px;">
                        {{ new_status_label }}
                    </span>
                </div>
                
                <p><strong>Changed By:</strong> {{ user_name }}</p>
                <p><strong>Date:</strong> {{ date }}</p>
                
                {% if reason %}
                <p><strong>Reason:</strong> {{ reason }}</p>
                {% endif %}
            </div>
        </div>
        """
        
        return render_template_string(html_template,
            obj_name=obj_name,
            old_color=old_color,
            new_color=new_color,
            old_status_label=old_status.replace('_', ' ').title(),
            new_status_label=new_status.replace('_', ' ').title(),
            user_name=user_name,
            date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            reason=getattr(obj, 'status_reason', None)
        )
    
    def _generate_approval_subject(self, obj, action: str) -> str:
        """Generate email subject for approval action."""
        obj_name = getattr(obj, 'name', str(obj))
        return f"Record {action.title()}: {obj_name}"
    
    def _generate_approval_body(self, obj, action: str, user=None) -> str:
        """Generate plain text email body for approval action."""
        obj_name = getattr(obj, 'name', str(obj))
        user_name = getattr(user, 'username', 'System') if user else 'System'
        
        body = f"""
Approval Notification

Record: {obj_name}
Action: {action.title()}
By: {user_name}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        # Add reason if available
        if hasattr(obj, 'status_reason') and obj.status_reason:
            body += f"\nReason: {obj.status_reason}"
        
        return body.strip()
    
    def _generate_approval_html(self, obj, action: str, user=None) -> str:
        """Generate HTML email body for approval action."""
        obj_name = getattr(obj, 'name', str(obj))
        user_name = getattr(user, 'username', 'System') if user else 'System'
        
        action_color = '#28a745' if action == 'approved' else '#dc3545'
        
        html_template = """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #333;">Approval Notification</h2>
            
            <div style="background: #f8f9fa; padding: 20px; border-radius: 5px; margin: 20px 0;">
                <h3 style="margin-top: 0;">{{ obj_name }}</h3>
                
                <div style="margin: 15px 0;">
                    <span style="background: {{ action_color }}; color: white; padding: 8px 15px; border-radius: 3px; font-size: 16px;">
                        {{ action_label }}
                    </span>
                </div>
                
                <p><strong>By:</strong> {{ user_name }}</p>
                <p><strong>Date:</strong> {{ date }}</p>
                
                {% if reason %}
                <p><strong>Reason:</strong> {{ reason }}</p>
                {% endif %}
            </div>
        </div>
        """
        
        return render_template_string(html_template,
            obj_name=obj_name,
            action_color=action_color,
            action_label=action.title(),
            user_name=user_name,
            date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            reason=getattr(obj, 'status_reason', None)
        )
    
    def _generate_submission_subject(self, obj) -> str:
        """Generate email subject for submission."""
        obj_name = getattr(obj, 'name', str(obj))
        return f"Approval Required: {obj_name}"
    
    def _generate_submission_body(self, obj, user=None) -> str:
        """Generate plain text email body for submission."""
        obj_name = getattr(obj, 'name', str(obj))
        user_name = getattr(user, 'username', 'System') if user else 'System'
        
        return f"""
Approval Request

A record has been submitted for your approval:

Record: {obj_name}
Submitted By: {user_name}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Please review and approve or reject this record.
        """.strip()
    
    def _generate_submission_html(self, obj, user=None) -> str:
        """Generate HTML email body for submission."""
        obj_name = getattr(obj, 'name', str(obj))
        user_name = getattr(user, 'username', 'System') if user else 'System'
        
        html_template = """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #333;">Approval Required</h2>
            
            <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 20px; border-radius: 5px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #856404;">{{ obj_name }}</h3>
                
                <p>A record has been submitted for your approval.</p>
                
                <p><strong>Submitted By:</strong> {{ user_name }}</p>
                <p><strong>Date:</strong> {{ date }}</p>
                
                <div style="margin-top: 20px;">
                    <p>Please review and approve or reject this record.</p>
                </div>
            </div>
        </div>
        """
        
        return render_template_string(html_template,
            obj_name=obj_name,
            user_name=user_name,
            date=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )