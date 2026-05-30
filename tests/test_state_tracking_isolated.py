"""
Isolated test for StateTrackingMixin functionality.

Tests the state tracking capabilities without complex imports.
"""

import unittest
from unittest.mock import Mock

from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Create a minimal PgForge compatible setup for testing
Base = declarative_base()


class AuditMixin:
    """Minimal AuditMixin for testing."""
    pass


class StateTrackingMixin(AuditMixin):
    """
    State tracking mixin for PgForge models.
    
    Extends AuditMixin to add status field and state transition capabilities.
    """
    
    status = Column(String(50), default='draft', nullable=False)
    status_reason = Column(Text)
    
    def __init__(self, *args, **kwargs):
        """Initialize the mixin with default status."""
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'status') or self.status is None:
            self.status = 'draft'
    
    def transition_to(self, new_status: str, reason: str = None, user=None):
        """
        Change status with automatic audit trail.
        
        Args:
            new_status: The new status to transition to
            reason: Optional reason for the status change
            user: User making the change (defaults to current_user)
            
        Returns:
            str: Description of the status change
        """
        old_status = self.status
        self.status = new_status
        self.status_reason = reason
        
        # Log the status change using existing audit capabilities
        if hasattr(self, 'log_custom_event'):
            self.log_custom_event('status_change', {
                'old_status': old_status,
                'new_status': new_status,
                'reason': reason,
                'changed_by': user.id if user else None
            })
        
        # Store original status for notification system
        self._original_status = old_status
        
        return f"Status changed from {old_status} to {new_status}"
    
    def can_transition_to(self, new_status: str, user=None) -> bool:
        """
        Check if status transition is allowed.
        
        Args:
            new_status: The status to check transition to
            user: User attempting the transition
            
        Returns:
            bool: True if transition is allowed
        """
        # Basic validation - can be extended by subclasses
        if self.status == new_status:
            return False  # No change needed
            
        # Check if user has permission to change status
        if user and hasattr(user, 'has_permission'):
            return user.has_permission('can_edit')
        
        return True  # Default to allowing transition
    
    def get_available_transitions(self, user=None) -> list:
        """
        Get list of available status transitions for the user.
        
        Args:
            user: User to check transitions for
            
        Returns:
            List of available transitions
        """
        # Default transitions - can be overridden by subclasses
        all_transitions = [
            {'from': 'draft', 'to': 'active', 'label': 'Activate'},
            {'from': 'draft', 'to': 'archived', 'label': 'Archive'},
            {'from': 'active', 'to': 'completed', 'label': 'Complete'},
            {'from': 'active', 'to': 'archived', 'label': 'Archive'},
            {'from': 'completed', 'to': 'archived', 'label': 'Archive'},
            {'from': 'archived', 'to': 'active', 'label': 'Reactivate'},
        ]
        
        # Filter transitions based on current status and permissions
        available = []
        for transition in all_transitions:
            if (transition['from'] == self.status and 
                self.can_transition_to(transition['to'], user)):
                available.append(transition)
        
        return available


class TestModel(StateTrackingMixin, Base):
    """Test model using StateTrackingMixin."""
    
    __tablename__ = 'test_models'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


class TestStateTrackingMixin(unittest.TestCase):
    """Test cases for StateTrackingMixin."""
    
    def setUp(self):
        """Set up test fixtures."""
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.session = Session()
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.session.close()
    
    def test_default_status(self):
        """Test that models have default 'draft' status."""
        model = TestModel(name="Test Model")
        self.assertEqual(model.status, 'draft')
    
    def test_status_transition(self):
        """Test basic status transition functionality."""
        model = TestModel(name="Test Model")
        
        # Test transition
        result = model.transition_to('active', 'Activating for testing')
        
        self.assertEqual(model.status, 'active')
        self.assertEqual(model.status_reason, 'Activating for testing')
        self.assertEqual(result, "Status changed from draft to active")
    
    def test_transition_with_user(self):
        """Test status transition with user tracking."""
        # Mock user
        mock_user = Mock()
        mock_user.id = 123
        
        model = TestModel(name="Test Model")
        
        result = model.transition_to('completed', 'Task finished', user=mock_user)
        
        self.assertEqual(model.status, 'completed')
        self.assertEqual(model.status_reason, 'Task finished')
        self.assertEqual(model._original_status, 'draft')
    
    def test_can_transition_to(self):
        """Test transition permission checking."""
        model = TestModel(name="Test Model")
        
        # Test basic validation
        self.assertFalse(model.can_transition_to('draft'))  # Same status
        self.assertTrue(model.can_transition_to('active'))   # Different status
    
    def test_can_transition_with_user_permissions(self):
        """Test transition permission checking with user."""
        model = TestModel(name="Test Model")
        
        # Mock user with permissions
        mock_user_with_perms = Mock()
        mock_user_with_perms.has_permission.return_value = True
        
        # Mock user without permissions
        mock_user_no_perms = Mock()
        mock_user_no_perms.has_permission.return_value = False
        
        # Test with permissions
        self.assertTrue(model.can_transition_to('active', mock_user_with_perms))
        
        # Test without permissions  
        self.assertFalse(model.can_transition_to('active', mock_user_no_perms))
    
    def test_get_available_transitions(self):
        """Test getting available status transitions."""
        model = TestModel(name="Test Model")
        
        transitions = model.get_available_transitions()
        
        # Should have transitions from 'draft' status
        transition_targets = [t['to'] for t in transitions]
        self.assertIn('active', transition_targets)
        self.assertIn('archived', transition_targets)
        
        # Check structure of transitions
        self.assertTrue(all('from' in t and 'to' in t and 'label' in t for t in transitions))
    
    def test_transition_workflow(self):
        """Test complete transition workflow."""
        model = TestModel(name="Test Model")
        
        # Test workflow: draft -> active -> completed -> archived
        self.assertEqual(model.status, 'draft')
        
        # Activate
        model.transition_to('active', 'Ready to use')
        self.assertEqual(model.status, 'active')
        
        # Complete
        model.transition_to('completed', 'Work finished')
        self.assertEqual(model.status, 'completed')
        
        # Archive
        model.transition_to('archived', 'No longer needed')
        self.assertEqual(model.status, 'archived')
        
        # Reactivate
        model.transition_to('active', 'Need to reuse')
        self.assertEqual(model.status, 'active')
    
    def test_transition_with_audit_logging(self):
        """Test that transitions call audit logging when available."""
        model = TestModel(name="Test Model")
        
        # Add mock audit logging method
        model.log_custom_event = Mock()
        
        mock_user = Mock()
        mock_user.id = 789
        
        model.transition_to('active', 'Testing audit', user=mock_user)
        
        # Verify audit event was logged
        model.log_custom_event.assert_called_once_with('status_change', {
            'old_status': 'draft',
            'new_status': 'active',
            'reason': 'Testing audit',
            'changed_by': 789
        })


if __name__ == '__main__':
    unittest.main()