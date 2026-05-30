#!/usr/bin/env python3
"""
Edge Cases and Integration Test Suite for Approval Workflow

Tests edge cases, boundary conditions, and integration scenarios:
1. Malformed data handling
2. Boundary value testing for financial amounts
3. Network timeout scenarios
4. Database connection failures
5. Invalid workflow configurations
6. Memory pressure conditions
7. Large dataset handling

Environment: PgAppForge with fault injection testing
"""

import pytest
import unittest
from unittest.mock import Mock, MagicMock, patch, call
import json
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Flask

# Import system under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pgappforge.process.approval.views import ApprovalWorkflowView
from pgappforge.process.approval.chain_manager import ApprovalChainManager
from pgappforge.process.approval.workflow_engine import (
    ApprovalWorkflowEngine, ApprovalTransactionError
)
from pgappforge.process.security.approval_security_config import (
    ApprovalSecurityConfig, SecurityError
)


class TestApprovalWorkflowEdgeCases(unittest.TestCase):
    """Test suite for approval workflow edge cases and boundary conditions."""
    
    def setUp(self):
        """Set up test environment for edge case testing."""
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        # Mock components
        self.mock_appbuilder = Mock()
        self.mock_db_session = Mock()
        self.mock_appbuilder.get_session.return_value = self.mock_db_session
        
        # Initialize components
        self.security_config = ApprovalSecurityConfig(self.mock_appbuilder)
        self.workflow_engine = ApprovalWorkflowEngine(self.mock_appbuilder)
        self.chain_manager = ApprovalChainManager(self.mock_appbuilder, self.security_config)
        
        # Mock user
        self.mock_user = Mock()
        self.mock_user.id = 123
        self.mock_user.username = 'test_user'
        
    def test_extreme_financial_amounts(self):
        """Test handling of extreme financial amounts."""
        # Test maximum safe integer
        max_amount_request = Mock()
        max_amount_request.amount = 9223372036854775807  # Max 64-bit signed int
        max_amount_request.id = 1
        max_amount_request.user_id = 999
        
        # Should handle without overflow
        violations = self.security_config.validate_self_approval_comprehensive(
            max_amount_request, self.mock_user
        )
        self.assertIsInstance(violations, list)
        
        # Test zero amount
        zero_amount_request = Mock()
        zero_amount_request.amount = 0
        zero_amount_request.id = 2
        zero_amount_request.user_id = 999
        
        violations = self.security_config.validate_self_approval_comprehensive(
            zero_amount_request, self.mock_user
        )
        self.assertIsInstance(violations, list)
        
        # Test negative amount
        negative_amount_request = Mock()
        negative_amount_request.amount = -1000.0
        negative_amount_request.id = 3
        negative_amount_request.user_id = 999
        
        violations = self.security_config.validate_self_approval_comprehensive(
            negative_amount_request, self.mock_user
        )
        self.assertIsInstance(violations, list)
        
    def test_malformed_workflow_configuration(self):
        """Test handling of malformed workflow configurations."""
        # Test empty workflow config
        empty_config = {}
        
        with self.assertRaises((KeyError, ValueError)):
            self.workflow_engine.register_model_workflow(
                Mock, 'invalid_workflow', {'invalid_workflow': empty_config}
            )
        
        # Test workflow with missing steps
        malformed_config = {'approved_state': 'approved'}  # Missing 'steps'
        
        with patch('pgappforge.process.approval.workflow_engine.log') as mock_log:
            result = self.workflow_engine.register_model_workflow(
                Mock, 'malformed', {'malformed': malformed_config}
            )
            # Should handle gracefully and log warning
            self.assertTrue(mock_log.error.called or mock_log.warning.called)
            
    def test_database_connection_failure_scenarios(self):
        """Test handling of database connection failures."""
        from sqlalchemy.exc import OperationalError, DisconnectionError
        
        # Test connection timeout
        self.mock_db_session.query.side_effect = OperationalError(
            "Connection timeout", None, None
        )
        
        with self.assertRaises(ApprovalTransactionError):
            self.workflow_engine.process_approval_transaction(
                Mock(id=123, status='pending'),
                self.mock_user,
                0,
                {'name': 'test_step'},
                "Test comments",
                {'steps': [{'name': 'test_step'}]}
            )
        
        # Verify rollback was attempted
        self.mock_db_session.rollback.assert_called()
        
    def test_json_injection_in_comments(self):
        """Test prevention of JSON injection in approval comments."""
        # Malicious JSON payload in comments
        malicious_comments = '{"__proto__": {"isAdmin": true}, "script": "<script>alert(1)</script>"}'
        
        mock_instance = Mock()
        mock_instance.id = 123
        mock_instance.status = 'pending'
        
        # Test that malicious JSON is handled safely
        with patch.object(self.workflow_engine, 'get_approval_history') as mock_history:
            mock_history.return_value = []
            
            with patch.object(self.workflow_engine, 'update_approval_history') as mock_update:
                with patch.object(self.workflow_engine, 'is_step_complete') as mock_complete:
                    mock_complete.return_value = True
                    
                    with patch.object(self.workflow_engine, 'advance_workflow_step'):
                        result = self.workflow_engine._execute_approval_transaction(
                            self.mock_db_session,
                            mock_instance,
                            self.mock_user,
                            0,
                            {'name': 'test_step'},
                            malicious_comments,
                            {'steps': [{'name': 'test_step'}]}
                        )
                        
                        # Verify transaction completed safely
                        self.assertTrue(result[0])
                        
                        # Check that update_approval_history was called
                        mock_update.assert_called_once()
                        
                        # Verify comments were stored safely
                        call_args = mock_update.call_args[0]
                        approval_data = call_args[1]
                        self.assertEqual(approval_data['comments'], malicious_comments)
                        
    def test_concurrent_workflow_state_changes(self):
        """Test handling of concurrent workflow state changes."""
        mock_instance = Mock()
        mock_instance.id = 123
        mock_instance.status = 'pending'
        mock_instance.current_state = 'step_0'
        
        # Simulate concurrent state change
        def simulate_concurrent_change(*args, **kwargs):
            mock_instance.status = 'approved'  # Changed by another process
            return mock_instance
        
        with patch.object(self.mock_db_session, 'query') as mock_query:
            mock_query.return_value.filter.return_value.params.return_value.first.side_effect = simulate_concurrent_change
            
            # Should detect concurrent modification
            with self.assertRaises(ValueError) as context:
                self.workflow_engine._execute_approval_transaction(
                    self.mock_db_session,
                    mock_instance,
                    self.mock_user,
                    0,
                    {'name': 'test_step'},
                    "Test approval",
                    {'steps': [{'name': 'test_step'}]}
                )
            
            self.assertIn("concurrent modification", str(context.exception))
            
    def test_memory_pressure_conditions(self):
        """Test behavior under memory pressure with large datasets."""
        # Create large approval history to simulate memory pressure
        large_history = [
            {
                'user_id': i,
                'timestamp': datetime.utcnow().isoformat(),
                'step': 'test_step',
                'comments': f'Large comment data {i} ' * 100  # Large comments
            }
            for i in range(1000)  # 1000 approval records
        ]
        
        mock_instance = Mock()
        mock_instance.id = 123
        mock_instance.status = 'pending'
        
        with patch.object(self.workflow_engine, 'get_approval_history') as mock_history:
            mock_history.return_value = large_history
            
            with patch.object(self.workflow_engine, 'update_approval_history') as mock_update:
                with patch.object(self.workflow_engine, 'is_step_complete') as mock_complete:
                    mock_complete.return_value = False  # Don't advance workflow
                    
                    # Should handle large datasets without memory issues
                    result = self.workflow_engine._execute_approval_transaction(
                        self.mock_db_session,
                        mock_instance,
                        self.mock_user,
                        0,
                        {'name': 'test_step'},
                        "Test approval with large history",
                        {'steps': [{'name': 'test_step'}]}
                    )
                    
                    self.assertTrue(result[0])  # Should succeed
                    
    def test_unicode_and_special_characters(self):
        """Test handling of Unicode and special characters in approval data."""
        # Test Unicode characters in comments
        unicode_comments = "Approval: ñáéíóú 中文 العربية עברית русский 🚀💰✅"
        
        mock_instance = Mock()
        mock_instance.id = 123
        mock_instance.status = 'pending'
        
        with patch.object(self.workflow_engine, 'get_approval_history') as mock_history:
            mock_history.return_value = []
            
            with patch.object(self.workflow_engine, 'update_approval_history') as mock_update:
                with patch.object(self.workflow_engine, 'is_step_complete') as mock_complete:
                    mock_complete.return_value = False
                    
                    result = self.workflow_engine._execute_approval_transaction(
                        self.mock_db_session,
                        mock_instance,
                        self.mock_user,
                        0,
                        {'name': 'test_step'},
                        unicode_comments,
                        {'steps': [{'name': 'test_step'}]}
                    )
                    
                    self.assertTrue(result[0])
                    
                    # Verify Unicode was preserved
                    call_args = mock_update.call_args[0]
                    approval_data = call_args[1]
                    self.assertEqual(approval_data['comments'], unicode_comments)
                    
    def test_timestamp_boundary_conditions(self):
        """Test timestamp handling at boundary conditions."""
        # Test very old timestamp
        old_timestamp = datetime(1900, 1, 1)
        
        # Test very future timestamp  
        future_timestamp = datetime(2100, 12, 31)
        
        # Test current timestamp
        current_timestamp = datetime.utcnow()
        
        for timestamp in [old_timestamp, future_timestamp, current_timestamp]:
            with patch('pgappforge.process.approval.workflow_engine.datetime') as mock_datetime:
                mock_datetime.utcnow.return_value = timestamp
                
                mock_instance = Mock()
                mock_instance.id = 123
                mock_instance.status = 'pending'
                mock_instance.workflow_completed_at = None
                
                with patch.object(self.workflow_engine, 'get_approval_history') as mock_history:
                    mock_history.return_value = []
                    
                    with patch.object(self.workflow_engine, 'update_approval_history'):
                        with patch.object(self.workflow_engine, 'is_step_complete') as mock_complete:
                            mock_complete.return_value = True
                            
                            with patch.object(self.workflow_engine, 'advance_workflow_step'):
                                result = self.workflow_engine._execute_approval_transaction(
                                    self.mock_db_session,
                                    mock_instance,
                                    self.mock_user,
                                    0,
                                    {'name': 'test_step'},
                                    "Test timestamp",
                                    {'steps': [{'name': 'test_step'}]}
                                )
                                
                                self.assertTrue(result[0])
                                # Verify timestamp was set
                                self.assertEqual(mock_instance.workflow_completed_at, timestamp)
                                
    def test_null_and_none_value_handling(self):
        """Test handling of null and None values."""
        # Test instance with None values
        null_instance = Mock()
        null_instance.id = None
        null_instance.status = None
        null_instance.amount = None
        null_instance.user_id = None
        null_instance.created_by = None
        
        # Should handle None values gracefully
        violations = self.security_config.validate_self_approval_comprehensive(
            null_instance, self.mock_user
        )
        self.assertIsInstance(violations, list)
        
        # Test with None user
        with self.assertRaises((AttributeError, TypeError)):
            violations = self.security_config.validate_self_approval_comprehensive(
                null_instance, None
            )
            
    def test_workflow_configuration_validation(self):
        """Test validation of workflow configuration edge cases."""
        # Test circular workflow
        circular_config = {
            'steps': [
                {'name': 'step1', 'next_step': 'step2'},
                {'name': 'step2', 'next_step': 'step1'}  # Circular reference
            ]
        }
        
        # Test empty steps
        empty_steps_config = {'steps': []}
        
        # Test duplicate step names
        duplicate_steps_config = {
            'steps': [
                {'name': 'approval'},
                {'name': 'approval'}  # Duplicate
            ]
        }
        
        for config_name, config in [
            ('circular', circular_config),
            ('empty_steps', empty_steps_config),
            ('duplicate_steps', duplicate_steps_config)
        ]:
            result = self.workflow_engine.register_model_workflow(
                Mock, config_name, {config_name: config}
            )
            
            # Should either succeed with warnings or fail gracefully
            self.assertIsInstance(result, bool)
            
    def tearDown(self):
        """Clean up test environment."""
        self.mock_appbuilder.reset_mock()
        self.mock_db_session.reset_mock()


if __name__ == '__main__':
    unittest.main(verbosity=2)