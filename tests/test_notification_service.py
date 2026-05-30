"""
Test NotificationService functionality.

Tests the email notification capabilities and integration with Flask-Mail and StateTrackingMixin.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from flask import Flask
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Test the NotificationService without complex PgAppForge imports
Base = declarative_base()


class MockUser:
    """Mock user for testing notifications."""
    
    def __init__(self, email="test@example.com", username="testuser"):
        self.id = 123
        self.email = email
        self.username = username


class StateTrackingMixin:
    """Mock StateTrackingMixin for testing."""
    
    status = Column(String(50), default='draft', nullable=False)
    status_reason = Column(Text)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'status') or self.status is None:
            self.status = 'draft'


class NotificationTestModel(StateTrackingMixin, Base):
    """Test model for notification testing."""
    
    __tablename__ = 'notification_test_models'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.created_by = None
        self.assigned_to = None


class MockMessage:
    """Mock Flask-Mail Message for testing."""
    
    def __init__(self, subject=None, sender=None, recipients=None):
        self.subject = subject
        self.sender = sender
        self.recipients = recipients or []
        self.body = ""
        self.html = ""


class MockMail:
    """Mock Flask-Mail instance for testing."""
    
    def __init__(self):
        self.sent_messages = []
        self.should_fail = False
    
    def send(self, message):
        if self.should_fail:
            raise Exception("Mail sending failed")
        self.sent_messages.append(message)


class MockSecurityManager:
    """Mock PgAppForge security manager."""
    
    def __init__(self):
        self.permissions = {
            'can_approve': Mock(),
            'approve_records': Mock()
        }
        self.roles = {
            'Admin': Mock()
        }
        self.roles['Admin'].user = [MockUser(email="admin@example.com", username="admin")]
        self.roles['Admin'].permissions = [self.permissions['can_approve']]
    
    def find_permission(self, perm_name):
        return self.permissions.get(perm_name)
    
    def find_role(self, role_name):
        return self.roles.get(role_name)
    
    def get_all_roles(self):
        return list(self.roles.values())


class MockAppBuilder:
    """Mock PgAppForge instance."""
    
    def __init__(self):
        self.sm = MockSecurityManager()


class MockApp:
    """Mock Flask app with extensions."""
    
    def __init__(self):
        self.extensions = {
            'mail': MockMail()
        }
        self.config = {
            'MAIL_DEFAULT_SENDER': 'noreply@example.com',
            'FAB_NOTIFICATION_TRANSITIONS': [
                ('custom_status', 'custom_new_status')
            ]
        }
        self.appbuilder = MockAppBuilder()


# Import the actual NotificationService from the services package
from pgappforge.services import NotificationService


class TestNotificationService(unittest.TestCase):
    """Test cases for NotificationService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_mail = MockMail()
        
        # Create mock app and patch current_app
        self.mock_app = MockApp()
        
        # Create service with mocked dependencies
        with patch('pgappforge.services.notification_service.current_app', self.mock_app):
            self.service = NotificationService(mail=self.mock_mail)
        
        # Create test model
        self.model = NotificationTestModel(name="Test Model")
        self.model.id = 1
        self.model.status = 'draft'
        
        # Create test user
        self.user = MockUser()
        self.model.created_by = self.user
    
    @patch('pgappforge.services.notification_service.current_app')
    def test_service_initialization(self, mock_current_app):
        """Test service initialization."""
        mock_current_app.extensions = {'mail': self.mock_mail}
        
        # With mail instance
        service = NotificationService(mail=self.mock_mail)
        self.assertEqual(service.mail, self.mock_mail)
        
        # Without mail instance (should get from app)
        service = NotificationService()
        self.assertEqual(service.mail, self.mock_mail)
    
    @patch('pgappforge.services.notification_service.current_app')
    @patch('pgappforge.services.notification_service.render_template_string')
    @patch('pgappforge.services.notification_service.Message', MockMessage)
    def test_send_status_notification_success(self, mock_render_template, mock_current_app):
        """Test successful status change notification."""
        mock_current_app.config = {'MAIL_DEFAULT_SENDER': 'noreply@example.com'}
        mock_render_template.side_effect = lambda template, **kwargs: f"<html>Mock HTML for {template}</html>"
        
        result = self.service.send_status_notification(
            self.model, 'draft', 'pending_approval', self.user
        )
        
        self.assertTrue(result)
        self.assertEqual(len(self.mock_mail.sent_messages), 1)
        
        # Check message content
        message = self.mock_mail.sent_messages[0]
        self.assertIn('Status Update:', message.subject)
        self.assertIn('Test Model', message.subject)
        self.assertEqual(message.recipients, [self.user.email])
        self.assertIn('Test Model', message.body)
        self.assertIn('Draft', message.body)
        self.assertIn('Pending Approval', message.body)
        self.assertIn('testuser', message.body)
    
    def test_send_status_notification_no_mail(self):
        """Test status notification with no mail instance."""
        # Create service with explicit None mail 
        service = NotificationService(mail=None)
        result = service.send_status_notification(
            self.model, 'draft', 'pending_approval', self.user
        )
        
        self.assertFalse(result)
    
    def test_send_status_notification_should_not_notify(self):
        """Test status notification for non-notifiable transitions."""
        result = self.service.send_status_notification(
            self.model, 'active', 'inactive', self.user
        )
        
        self.assertFalse(result)
        self.assertEqual(len(self.mock_mail.sent_messages), 0)
    
    def test_send_status_notification_no_recipients(self):
        """Test status notification with no recipients."""
        # Remove created_by to have no recipients
        self.model.created_by = None
        
        result = self.service.send_status_notification(
            self.model, 'draft', 'pending_approval', self.user
        )
        
        self.assertFalse(result)
        self.assertEqual(len(self.mock_mail.sent_messages), 0)
    
    def test_send_status_notification_mail_failure(self):
        """Test status notification with mail sending failure."""
        self.mock_mail.should_fail = True
        
        result = self.service.send_status_notification(
            self.model, 'draft', 'pending_approval', self.user
        )
        
        self.assertFalse(result)
    
    @patch('pgappforge.services.notification_service.current_app')
    @patch('pgappforge.services.notification_service.render_template_string')
    def test_send_approval_notification_approved(self, mock_render_template, mock_current_app):
        """Test approval notification."""
        mock_current_app.config = {'MAIL_DEFAULT_SENDER': 'noreply@example.com'}
        mock_current_app.appbuilder = self.mock_app.appbuilder
        mock_render_template.side_effect = lambda template, **kwargs: f"<html>Mock HTML for {template}</html>"
        
        result = self.service.send_approval_notification(
            self.model, 'approved', self.user
        )
        
        self.assertTrue(result)
        self.assertEqual(len(self.mock_mail.sent_messages), 1)
        
        # Check message content
        message = self.mock_mail.sent_messages[0]
        self.assertIn('Record Approved:', message.subject)
        self.assertIn('Test Model', message.subject)
        self.assertIn('test@example.com', message.recipients)  # creator
        self.assertIn('admin@example.com', message.recipients)  # admin
        self.assertEqual(len(message.recipients), 2)
        self.assertIn('Approved', message.body)
        self.assertIn('testuser', message.body)
    
    def test_send_approval_notification_rejected(self):
        """Test rejection notification."""
        result = self.service.send_approval_notification(
            self.model, 'rejected', self.user
        )
        
        self.assertTrue(result)
        self.assertEqual(len(self.mock_mail.sent_messages), 1)
        
        # Check message content
        message = self.mock_mail.sent_messages[0]
        self.assertIn('Record Rejected:', message.subject)
        self.assertIn('Rejected', message.body)
    
    def test_send_approval_notification_invalid_action(self):
        """Test approval notification with invalid action."""
        result = self.service.send_approval_notification(
            self.model, 'invalid_action', self.user
        )
        
        self.assertFalse(result)
        self.assertEqual(len(self.mock_mail.sent_messages), 0)
    
    @patch('pgappforge.services.notification_service.current_app')
    @patch('pgappforge.services.notification_service.render_template_string')
    def test_send_submission_notification_success(self, mock_render_template, mock_current_app):
        """Test successful submission notification."""
        mock_current_app.config = {'MAIL_DEFAULT_SENDER': 'noreply@example.com'}
        mock_current_app.appbuilder = self.mock_app.appbuilder
        mock_render_template.side_effect = lambda template, **kwargs: f"<html>Mock HTML for {template}</html>"
        
        result = self.service.send_submission_notification(self.model, self.user)
        
        self.assertTrue(result)
        self.assertEqual(len(self.mock_mail.sent_messages), 1)
        
        # Check message content
        message = self.mock_mail.sent_messages[0]
        self.assertIn('Approval Required:', message.subject)
        self.assertIn('Test Model', message.subject)
        self.assertIn('admin@example.com', message.recipients)
        self.assertIn('submitted for your approval', message.body)
        self.assertIn('testuser', message.body)
    
    def test_should_notify_default_transitions(self):
        """Test default notification transitions."""
        # Should notify
        self.assertTrue(self.service._should_notify('draft', 'pending_approval'))
        self.assertTrue(self.service._should_notify('pending_approval', 'approved'))
        self.assertTrue(self.service._should_notify('pending_approval', 'rejected'))
        self.assertTrue(self.service._should_notify('active', 'completed'))
        self.assertTrue(self.service._should_notify('completed', 'archived'))
        
        # Should not notify
        self.assertFalse(self.service._should_notify('draft', 'active'))
        self.assertFalse(self.service._should_notify('approved', 'archived'))
    
    def test_should_notify_custom_transitions(self):
        """Test custom notification transitions."""
        # Custom transition from mock config
        self.assertTrue(self.service._should_notify('custom_status', 'custom_new_status'))
    
    def test_get_notification_recipients_creator(self):
        """Test getting notification recipients - creator."""
        recipients = self.service._get_notification_recipients(self.model, 'status_change')
        self.assertIn(self.user.email, recipients)
    
    def test_get_notification_recipients_assigned(self):
        """Test getting notification recipients - assigned user."""
        assigned_user = MockUser(email="assigned@example.com")
        self.model.assigned_to = assigned_user
        
        recipients = self.service._get_notification_recipients(self.model, 'status_change')
        self.assertIn(self.user.email, recipients)  # creator
        self.assertIn(assigned_user.email, recipients)  # assigned
    
    def test_get_notification_recipients_approval_type(self):
        """Test getting notification recipients for approval."""
        recipients = self.service._get_notification_recipients(self.model, 'approval')
        self.assertIn(self.user.email, recipients)  # creator
        self.assertIn('admin@example.com', recipients)  # admin
    
    def test_get_notification_recipients_no_email(self):
        """Test getting notification recipients with no email."""
        self.model.created_by.email = None
        
        recipients = self.service._get_notification_recipients(self.model, 'status_change')
        self.assertEqual(recipients, [])
    
    def test_get_approvers_email_list(self):
        """Test getting approvers email list."""
        approvers = self.service._get_approvers_email_list()
        self.assertIn('admin@example.com', approvers)
        self.assertIn('approver@example.com', approvers)
    
    def test_get_admin_email_list(self):
        """Test getting admin email list."""
        admins = self.service._get_admin_email_list()
        self.assertIn('admin@example.com', admins)
    
    def test_generate_status_subject(self):
        """Test status change subject generation."""
        subject = self.service._generate_status_subject(
            self.model, 'draft', 'pending_approval'
        )
        
        self.assertEqual(subject, "Status Update: Test Model - Pending Approval")
    
    def test_generate_status_body(self):
        """Test status change body generation."""
        body = self.service._generate_status_body(
            self.model, 'draft', 'pending_approval', self.user
        )
        
        self.assertIn('Status Update Notification', body)
        self.assertIn('Test Model', body)
        self.assertIn('Draft → Pending Approval', body)
        self.assertIn('testuser', body)
    
    def test_generate_status_body_with_reason(self):
        """Test status change body generation with reason."""
        self.model.status_reason = "Required for approval workflow"
        
        body = self.service._generate_status_body(
            self.model, 'draft', 'pending_approval', self.user
        )
        
        self.assertIn('Reason: Required for approval workflow', body)
    
    def test_generate_status_html(self):
        """Test status change HTML generation."""
        html = self.service._generate_status_html(
            self.model, 'draft', 'pending_approval', self.user
        )
        
        self.assertIn('Status Update Notification', html)
        self.assertIn('Test Model', html)
        self.assertIn('Draft', html)
        self.assertIn('Pending Approval', html)
        self.assertIn('testuser', html)
        self.assertIn('font-family: Arial', html)  # Check HTML styling
    
    def test_generate_approval_subject(self):
        """Test approval subject generation."""
        subject = self.service._generate_approval_subject(self.model, 'approved')
        self.assertEqual(subject, "Record Approved: Test Model")
        
        subject = self.service._generate_approval_subject(self.model, 'rejected')
        self.assertEqual(subject, "Record Rejected: Test Model")
    
    def test_generate_approval_body(self):
        """Test approval body generation."""
        body = self.service._generate_approval_body(self.model, 'approved', self.user)
        
        self.assertIn('Approval Notification', body)
        self.assertIn('Test Model', body)
        self.assertIn('Approved', body)
        self.assertIn('testuser', body)
    
    def test_generate_approval_html(self):
        """Test approval HTML generation."""
        html = self.service._generate_approval_html(self.model, 'approved', self.user)
        
        self.assertIn('Approval Notification', html)
        self.assertIn('Test Model', html)
        self.assertIn('Approved', html)
        self.assertIn('testuser', html)
        self.assertIn('#28a745', html)  # Green color for approved
        
        html_rejected = self.service._generate_approval_html(self.model, 'rejected', self.user)
        self.assertIn('#dc3545', html_rejected)  # Red color for rejected
    
    def test_generate_submission_subject(self):
        """Test submission subject generation."""
        subject = self.service._generate_submission_subject(self.model)
        self.assertEqual(subject, "Approval Required: Test Model")
    
    def test_generate_submission_body(self):
        """Test submission body generation."""
        body = self.service._generate_submission_body(self.model, self.user)
        
        self.assertIn('Approval Request', body)
        self.assertIn('submitted for your approval', body)
        self.assertIn('Test Model', body)
        self.assertIn('testuser', body)
        self.assertIn('Please review and approve', body)
    
    def test_generate_submission_html(self):
        """Test submission HTML generation."""
        html = self.service._generate_submission_html(self.model, self.user)
        
        self.assertIn('Approval Required', html)
        self.assertIn('submitted for your approval', html)
        self.assertIn('Test Model', html)
        self.assertIn('testuser', html)
        self.assertIn('#fff3cd', html)  # Warning background color
        self.assertIn('Please review and approve', html)
    
    def test_email_content_without_user(self):
        """Test email content generation without user."""
        body = self.service._generate_status_body(
            self.model, 'draft', 'pending_approval', None
        )
        
        self.assertIn('Changed By: System', body)
        
        html = self.service._generate_status_html(
            self.model, 'draft', 'pending_approval', None
        )
        
        self.assertIn('Changed By:</strong> System', html)
    
    def test_email_content_without_model_name(self):
        """Test email content generation with object without name attribute."""
        model_no_name = Mock()
        model_no_name.id = 123
        del model_no_name.name  # Remove name attribute
        
        subject = self.service._generate_status_subject(
            model_no_name, 'draft', 'pending_approval'
        )
        
        # Should use string representation when no name
        self.assertIn('Status Update:', subject)


if __name__ == '__main__':
    unittest.main()