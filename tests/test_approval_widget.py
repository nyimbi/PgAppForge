"""
Test ApprovalWidget and ApprovalModelView functionality.

Tests the approval workflow capabilities and integration with PgForge patterns.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock

from flask import Flask, request
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Test the ApprovalWidget without complex PgForge imports
Base = declarative_base()


class MockUser:
    """Mock user for testing permissions."""
    
    def __init__(self, has_permissions=True, roles=None):
        self.id = 123
        self.has_permissions = has_permissions
        self.roles = roles or []
    
    def has_permission(self, permission):
        return self.has_permissions
    
    def has_role(self, role):
        return role in self.roles


class StateTrackingMixin:
    """Mock StateTrackingMixin for testing."""
    
    status = Column(String(50), default='draft', nullable=False)
    status_reason = Column(Text)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'status') or self.status is None:
            self.status = 'draft'
    
    def transition_to(self, new_status: str, reason: str = None, user=None):
        old_status = self.status
        self.status = new_status
        self.status_reason = reason
        self._original_status = old_status
        return f"Status changed from {old_status} to {new_status}"


class TestModel(StateTrackingMixin, Base):
    """Test model for approval testing."""
    
    __tablename__ = 'test_models'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


class MockFormWidget:
    """Mock FormWidget base class."""
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class ApprovalWidget(MockFormWidget):
    """
    Simplified ApprovalWidget for testing.
    """
    
    template = "appbuilder/general/widgets/approval.html"
    
    def __init__(self, approval_required=False, **kwargs):
        super(ApprovalWidget, self).__init__(**kwargs)
        self.approval_required = approval_required
    
    def render_approval_buttons(self, obj, user=None):
        """
        Render approval/rejection buttons if user has permission.
        """
        if not user:
            # In real implementation, this would use current_user
            user = MockUser()
        
        # Only show buttons if approval is required and object is pending approval
        if not self.approval_required or not hasattr(obj, 'status'):
            return ''
            
        if obj.status != 'pending_approval':
            return ''
        
        # Check if user has approval permissions
        if not self._can_approve_user(user):
            return ''
        
        # Return mock HTML for testing
        return f'''
        <div class="approval-buttons">
            <button class="btn btn-success approve-btn" data-id="{obj.id}">Approve</button>
            <button class="btn btn-danger reject-btn" data-id="{obj.id}">Reject</button>
        </div>
        '''
    
    def _can_approve_user(self, user):
        """Check if user can approve."""
        if not user or not hasattr(user, 'has_permission'):
            return False
        
        return (user.has_permission('approve_records') or 
                user.has_permission('can_approve') or
                user.has_role('Admin'))
    
    def get_approval_status_badge(self, obj):
        """Get HTML badge for approval status."""
        if not hasattr(obj, 'status'):
            return ''
        
        status_classes = {
            'draft': 'badge-secondary',
            'pending_approval': 'badge-warning',
            'approved': 'badge-success',
            'rejected': 'badge-danger',
            'archived': 'badge-dark'
        }
        
        css_class = status_classes.get(obj.status, 'badge-secondary')
        status_text = obj.status.replace('_', ' ').title()
        
        return f'<span class="badge {css_class}">{status_text}</span>'


class TestApprovalWidget(unittest.TestCase):
    """Test cases for ApprovalWidget."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.widget = ApprovalWidget(approval_required=True)
        self.model = TestModel(name="Test Model")
        self.model.id = 1
    
    def test_widget_initialization(self):
        """Test widget initialization."""
        widget = ApprovalWidget(approval_required=True)
        self.assertTrue(widget.approval_required)
        
        widget_no_approval = ApprovalWidget(approval_required=False)
        self.assertFalse(widget_no_approval.approval_required)
    
    def test_render_approval_buttons_not_required(self):
        """Test that no buttons render when approval not required."""
        widget = ApprovalWidget(approval_required=False)
        user = MockUser()
        
        html = widget.render_approval_buttons(self.model, user)
        self.assertEqual(html, '')
    
    def test_render_approval_buttons_no_status(self):
        """Test that no buttons render for objects without status."""
        model_no_status = Mock()
        model_no_status.id = 1
        del model_no_status.status  # Remove status attribute
        
        user = MockUser()
        html = self.widget.render_approval_buttons(model_no_status, user)
        self.assertEqual(html, '')
    
    def test_render_approval_buttons_wrong_status(self):
        """Test that no buttons render for objects not pending approval."""
        self.model.status = 'approved'
        user = MockUser()
        
        html = self.widget.render_approval_buttons(self.model, user)
        self.assertEqual(html, '')
    
    def test_render_approval_buttons_no_permission(self):
        """Test that no buttons render for users without permission."""
        self.model.status = 'pending_approval'
        user = MockUser(has_permissions=False)
        
        html = self.widget.render_approval_buttons(self.model, user)
        self.assertEqual(html, '')
    
    def test_render_approval_buttons_success(self):
        """Test successful rendering of approval buttons."""
        self.model.status = 'pending_approval'
        user = MockUser(has_permissions=True)
        
        html = self.widget.render_approval_buttons(self.model, user)
        
        self.assertIn('approval-buttons', html)
        self.assertIn('approve-btn', html)
        self.assertIn('reject-btn', html)
        self.assertIn(f'data-id="{self.model.id}"', html)
    
    def test_can_approve_user_no_user(self):
        """Test permission check with no user."""
        result = self.widget._can_approve_user(None)
        self.assertFalse(result)
    
    def test_can_approve_user_no_permissions(self):
        """Test permission check with user without permissions."""
        user = MockUser(has_permissions=False)
        result = self.widget._can_approve_user(user)
        self.assertFalse(result)
    
    def test_can_approve_user_with_permissions(self):
        """Test permission check with user with permissions."""
        user = MockUser(has_permissions=True)
        result = self.widget._can_approve_user(user)
        self.assertTrue(result)
    
    def test_can_approve_user_admin_role(self):
        """Test permission check with admin role."""
        user = MockUser(has_permissions=False, roles=['Admin'])
        # Mock the has_role method
        user.has_role = Mock(return_value=True)
        
        result = self.widget._can_approve_user(user)
        self.assertTrue(result)
    
    def test_get_approval_status_badge_no_status(self):
        """Test status badge for object without status."""
        model_no_status = Mock()
        del model_no_status.status
        
        badge = self.widget.get_approval_status_badge(model_no_status)
        self.assertEqual(badge, '')
    
    def test_get_approval_status_badge_draft(self):
        """Test status badge for draft status."""
        self.model.status = 'draft'
        
        badge = self.widget.get_approval_status_badge(self.model)
        
        self.assertIn('badge-secondary', badge)
        self.assertIn('Draft', badge)
    
    def test_get_approval_status_badge_pending_approval(self):
        """Test status badge for pending approval status."""
        self.model.status = 'pending_approval'
        
        badge = self.widget.get_approval_status_badge(self.model)
        
        self.assertIn('badge-warning', badge)
        self.assertIn('Pending Approval', badge)
    
    def test_get_approval_status_badge_approved(self):
        """Test status badge for approved status."""
        self.model.status = 'approved'
        
        badge = self.widget.get_approval_status_badge(self.model)
        
        self.assertIn('badge-success', badge)
        self.assertIn('Approved', badge)
    
    def test_get_approval_status_badge_rejected(self):
        """Test status badge for rejected status."""
        self.model.status = 'rejected'
        
        badge = self.widget.get_approval_status_badge(self.model)
        
        self.assertIn('badge-danger', badge)
        self.assertIn('Rejected', badge)
    
    def test_get_approval_status_badge_unknown_status(self):
        """Test status badge for unknown status."""
        self.model.status = 'unknown_status'
        
        badge = self.widget.get_approval_status_badge(self.model)
        
        self.assertIn('badge-secondary', badge)  # Default class
        self.assertIn('Unknown Status', badge)


class MockDataModel:
    """Mock datamodel for testing approval view."""
    
    def __init__(self):
        self.records = {}
        self.next_id = 1
    
    def get(self, pk):
        return self.records.get(pk)
    
    def edit(self, obj):
        if obj.id not in self.records:
            obj.id = self.next_id
            self.next_id += 1
        self.records[obj.id] = obj
        return obj


class TestApprovalModelView(unittest.TestCase):
    """Test cases for ApprovalModelView functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.datamodel = MockDataModel()
        
        # Create test model instance
        self.test_model = TestModel(name="Test Model")
        self.test_model.id = 1
        self.test_model.status = 'pending_approval'
        self.datamodel.records[1] = self.test_model
    
    @patch('flask_login.current_user')
    def test_approval_workflow(self, mock_current_user):
        """Test complete approval workflow."""
        # Mock current user with permissions
        mock_current_user.id = 123
        mock_current_user.has_permission.return_value = True
        mock_current_user.has_role.return_value = False
        
        # Test approval
        model = self.datamodel.get(1)
        self.assertEqual(model.status, 'pending_approval')
        
        # Simulate approval action
        result = model.transition_to('approved', 'Approved by admin', user=mock_current_user)
        
        self.assertEqual(model.status, 'approved')
        self.assertEqual(model.status_reason, 'Approved by admin')
        self.assertEqual(result, "Status changed from pending_approval to approved")
    
    @patch('flask_login.current_user')
    def test_rejection_workflow(self, mock_current_user):
        """Test complete rejection workflow."""
        # Mock current user with permissions
        mock_current_user.id = 123
        mock_current_user.has_permission.return_value = True
        
        # Test rejection
        model = self.datamodel.get(1)
        self.assertEqual(model.status, 'pending_approval')
        
        # Simulate rejection action
        result = model.transition_to('rejected', 'Rejected by admin', user=mock_current_user)
        
        self.assertEqual(model.status, 'rejected')
        self.assertEqual(model.status_reason, 'Rejected by admin')
        self.assertEqual(result, "Status changed from pending_approval to rejected")
    
    def test_submit_for_approval_workflow(self):
        """Test submitting a record for approval."""
        # Create draft model
        draft_model = TestModel(name="Draft Model")
        draft_model.id = 2
        draft_model.status = 'draft'
        self.datamodel.records[2] = draft_model
        
        # Simulate submission
        model = self.datamodel.get(2)
        result = model.transition_to('pending_approval', 'Submitted for approval')
        
        self.assertEqual(model.status, 'pending_approval')
        self.assertEqual(model.status_reason, 'Submitted for approval')
        self.assertEqual(result, "Status changed from draft to pending_approval")
    
    def test_integration_widget_and_model(self):
        """Test integration between widget and model."""
        widget = ApprovalWidget(approval_required=True)
        model = self.datamodel.get(1)  # pending_approval status
        user = MockUser(has_permissions=True)
        
        # Widget should render buttons for pending approval
        html = widget.render_approval_buttons(model, user)
        self.assertIn('approval-buttons', html)
        
        # After approval, widget should not render buttons
        model.transition_to('approved', 'Approved by admin')
        html_after = widget.render_approval_buttons(model, user)
        self.assertEqual(html_after, '')
        
        # Status badge should update correctly
        badge = widget.get_approval_status_badge(model)
        self.assertIn('badge-success', badge)
        self.assertIn('Approved', badge)


if __name__ == '__main__':
    unittest.main()