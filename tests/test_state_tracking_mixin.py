"""
Test StateTrackingMixin functionality.

Tests the state tracking capabilities and integration with PgAppForge patterns.
"""

import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.models.sqla import Model
from flask_login import current_user
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import sessionmaker

from pgappforge.mixins.fab_integration import StateTrackingMixin


class TestModel(StateTrackingMixin, Model):
    """Test model using StateTrackingMixin."""
    
    __tablename__ = 'test_models'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)


class TestStateTrackingMixin(unittest.TestCase):
    """Test cases for StateTrackingMixin."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
    
    def tearDown(self):
        """Clean up test fixtures."""
        with self.app.app_context():
            self.db.session.remove()
            self.db.drop_all()
    
    def test_default_status(self):
        """Test that models have default 'draft' status."""
        with self.app.app_context():
            model = TestModel(name="Test Model")
            self.assertEqual(model.status, 'draft')
    
    def test_status_transition(self):
        """Test basic status transition functionality."""
        with self.app.app_context():
            model = TestModel(name="Test Model")
            
            # Test transition
            result = model.transition_to('active', 'Activating for testing')
            
            self.assertEqual(model.status, 'active')
            self.assertEqual(model.status_reason, 'Activating for testing')
            self.assertEqual(result, "Status changed from draft to active")
    
    def test_transition_with_user(self):
        """Test status transition with user tracking."""
        with self.app.app_context():
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
        with self.app.app_context():
            model = TestModel(name="Test Model")
            
            # Test basic validation
            self.assertFalse(model.can_transition_to('draft'))  # Same status
            self.assertTrue(model.can_transition_to('active'))   # Different status
    
    def test_get_available_transitions(self):
        """Test getting available status transitions."""
        with self.app.app_context():
            model = TestModel(name="Test Model")
            
            transitions = model.get_available_transitions()
            
            # Should have transitions from 'draft' status
            transition_targets = [t['to'] for t in transitions]
            self.assertIn('active', transition_targets)
            self.assertIn('archived', transition_targets)
    
    def test_status_history_without_audit_trail(self):
        """Test status history when audit trail is not available."""
        with self.app.app_context():
            model = TestModel(name="Test Model")
            
            # Should return empty list when no audit trail available
            history = model.get_status_history()
            self.assertEqual(history, [])
    
    @patch.object(StateTrackingMixin, 'log_custom_event')
    def test_transition_logs_custom_event(self, mock_log_event):
        """Test that transitions log custom events when audit is available."""
        with self.app.app_context():
            model = TestModel(name="Test Model")
            model.log_custom_event = mock_log_event  # Add method
            
            mock_user = Mock()
            mock_user.id = 456
            
            model.transition_to('active', 'Testing logging', user=mock_user)
            
            # Verify custom event was logged
            mock_log_event.assert_called_once_with('status_change', {
                'old_status': 'draft',
                'new_status': 'active', 
                'reason': 'Testing logging',
                'changed_by': 456
            })
    
    def test_transition_validation_workflow(self):
        """Test complete transition workflow."""
        with self.app.app_context():
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


if __name__ == '__main__':
    unittest.main()