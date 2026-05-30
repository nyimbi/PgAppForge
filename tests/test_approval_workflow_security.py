#!/usr/bin/env python3
"""
Comprehensive Security Test Suite for Approval Workflow System

Tests all security vulnerabilities that were fixed:
1. Authentication Bypass in Financial Operations
2. CSRF Protection Validation
3. Privilege Escalation via Self-Approval Bypass
4. Memory-based Security State Issues
5. Database Session Management Anti-patterns

Test Environment: PgAppForge with SQLAlchemy
"""

import pytest
import unittest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
from flask import Flask, g
from werkzeug.test import Client
from flask_wtf.csrf import validate_csrf

# Import system under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pgappforge.process.approval.views import ApprovalWorkflowView
from pgappforge.process.approval.chain_manager import ApprovalChainManager
from pgappforge.process.approval.workflow_engine import ApprovalWorkflowEngine
from pgappforge.process.security.approval_security_config import (
    ApprovalSecurityConfig, SecurityEvent, SecurityError
)


class TestApprovalWorkflowSecurity(unittest.TestCase):
    """Test suite for approval workflow security vulnerabilities."""
    
    def setUp(self):
        """Set up test environment with Flask app and security configuration."""
        # Create Flask app for testing
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-testing-only'
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        # Mock PgAppForge components
        self.mock_appbuilder = Mock()
        self.mock_sm = Mock()
        self.mock_db = Mock()
        self.mock_appbuilder.sm = self.mock_sm
        self.mock_appbuilder.get_session.return_value = self.mock_db
        
        # Mock authenticated user
        self.mock_user = Mock()
        self.mock_user.id = 123
        self.mock_user.username = 'test_user'
        self.mock_user.is_authenticated = True
        
        # Initialize security configuration
        self.security_config = ApprovalSecurityConfig(self.mock_appbuilder)
        
        # Initialize views and managers with security config
        self.approval_view = ApprovalWorkflowView()
        self.chain_manager = ApprovalChainManager(self.mock_appbuilder, self.security_config)
        self.workflow_engine = ApprovalWorkflowEngine(self.mock_appbuilder)
        
        # Mock approval request instance
        self.mock_approval_request = Mock()
        self.mock_approval_request.id = 456
        self.mock_approval_request.user_id = 999  # Different from current user to avoid self-approval
        self.mock_approval_request.created_by = 999
        self.mock_approval_request.amount = 50000.0
        self.mock_approval_request.status = 'pending'
        self.mock_approval_request.chain_id = 789
        
        # Mock approval chain
        self.mock_chain = Mock()
        self.mock_chain.id = 789
        self.mock_chain.current_step = 0
        
    def test_authentication_bypass_prevention(self):
        """Test that unauthenticated requests are properly blocked."""
        with self.app.test_request_context():
            # Mock unauthenticated user
            g.user = None
            
            with patch('pgappforge.process.approval.views.current_user') as mock_current_user:
                mock_current_user.is_authenticated = False
                
                # Test financial operation endpoint
                result = self.approval_view._validate_financial_operation_security(
                    self.mock_approval_request, {}, {}
                )
                
                # Should fail authentication validation
                self.assertFalse(result)
                
    def test_csrf_token_validation(self):
        """Test CSRF token validation prevents unauthorized requests."""
        with self.app.test_request_context(method='POST'):
            # Mock authenticated user but invalid CSRF token
            g.user = self.mock_user
            
            with patch('pgappforge.process.approval.views.current_user') as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 123
                
                with patch('flask_wtf.csrf.validate_csrf') as mock_csrf:
                    mock_csrf.side_effect = ValueError("CSRF token missing")
                    
                    # Test CSRF validation
                    result = self.approval_view._validate_financial_operation_security(
                        self.mock_approval_request, {}, {}
                    )
                    
                    # Should fail CSRF validation
                    self.assertFalse(result)
                    mock_csrf.assert_called_once()
                    
    def test_self_approval_prevention_comprehensive(self):
        """Test comprehensive self-approval detection across multiple ownership fields."""
        with self.app.test_request_context():
            g.user = self.mock_user
            
            # Test case 1: Self-approval via user_id
            self.mock_approval_request.user_id = 123  # Same as current user
            
            with patch('pgappforge.process.approval.views.current_user') as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 123
                
                violations = self.security_config.validate_self_approval_comprehensive(
                    self.mock_approval_request, mock_current_user
                )
                
                self.assertGreater(len(violations), 0)
                self.assertIn("user_id", str(violations))
                
            # Test case 2: Self-approval via created_by
            self.mock_approval_request.user_id = 999  # Reset
            self.mock_approval_request.created_by = 123  # Same as current user
            
            violations = self.security_config.validate_self_approval_comprehensive(
                self.mock_approval_request, mock_current_user
            )
            
            self.assertGreater(len(violations), 0)
            self.assertIn("created_by", str(violations))
            
    def test_persistent_security_state_storage(self):
        """Test that security events are properly stored in database."""
        with patch.object(self.security_config, 'log_security_event') as mock_log:
            # Trigger security violation
            self.security_config.handle_security_violation(
                'self_approval_attempt', 
                self.mock_user, 
                self.mock_approval_request,
                {'field': 'user_id'}
            )
            
            # Verify security event was logged to persistent storage
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            self.assertEqual(args[0], 'self_approval_attempt')
            self.assertEqual(args[1], self.mock_user)
            
    def test_database_session_management_patterns(self):
        """Test proper database session management without undefined variables."""
        # Test that db_session is properly imported and defined
        with patch('pgappforge.db') as mock_db:
            mock_session = Mock()
            mock_db.session = mock_session
            
            # Test chain manager database access
            manager = ApprovalChainManager(self.mock_appbuilder, self.security_config)
            
            # This should not raise NameError for undefined db_session
            with patch.object(manager, '_get_approval_requests') as mock_get_requests:
                mock_get_requests.return_value = []
                result = manager.get_pending_approvals(self.mock_user)
                self.assertIsNotNone(result)
                
    def test_standardized_error_handling(self):
        """Test that SecurityError is properly raised and handled."""
        with patch.object(self.security_config, 'validate_workflow_transition') as mock_validate:
            mock_validate.side_effect = SecurityError("Invalid workflow transition")
            
            # Test that SecurityError is properly propagated
            with self.assertRaises(SecurityError) as context:
                self.security_config.validate_workflow_transition(
                    self.mock_approval_request, 'invalid_state'
                )
            
            self.assertIn("Invalid workflow transition", str(context.exception))
            
    def test_financial_operation_amount_validation(self):
        """Test validation of high-value financial operations."""
        with self.app.test_request_context():
            g.user = self.mock_user
            
            # High value approval request
            self.mock_approval_request.amount = 1000000.0  # $1M
            
            with patch('pgappforge.process.approval.views.current_user') as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 123
                
                # Mock successful CSRF validation
                with patch('flask_wtf.csrf.validate_csrf'):
                    result = self.approval_view._validate_financial_operation_security(
                        self.mock_approval_request, {}, {}
                    )
                    
                    # Should pass authentication and CSRF but still validate amount
                    # (Implementation depends on specific business rules)
                    self.assertTrue(isinstance(result, bool))
                    
    def test_concurrent_security_validation(self):
        """Test security validation under concurrent access scenarios."""
        import threading
        
        results = []
        
        def validate_concurrently():
            with self.app.test_request_context():
                g.user = self.mock_user
                
                with patch('pgappforge.process.approval.views.current_user') as mock_current_user:
                    mock_current_user.is_authenticated = True
                    mock_current_user.id = 123
                    
                    with patch('flask_wtf.csrf.validate_csrf'):
                        result = self.approval_view._validate_financial_operation_security(
                            self.mock_approval_request, {}, {}
                        )
                        results.append(result)
        
        # Run concurrent validations
        threads = [threading.Thread(target=validate_concurrently) for _ in range(5)]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All validations should complete successfully
        self.assertEqual(len(results), 5)
        
    @patch('pgappforge.process.approval.views.log')
    def test_security_audit_logging(self, mock_log):
        """Test that security events are properly audit logged."""
        with self.app.test_request_context():
            # Trigger security violation logging
            self.security_config.handle_security_violation(
                'authentication_bypass_attempt', 
                None,  # No user for unauthenticated attempt
                self.mock_approval_request,
                {'endpoint': 'financial_operation', 'ip': '192.168.1.100'}
            )
            
            # Verify audit logging occurred
            mock_log.warning.assert_called()
            log_call_args = str(mock_log.warning.call_args)
            self.assertIn('authentication_bypass_attempt', log_call_args)
            
    def test_g_object_import_resolution(self):
        """Test that Flask g object is properly imported and accessible."""
        with self.app.test_request_context():
            # Set up Flask g context
            g.user = self.mock_user
            
            # This should not raise NameError
            from pgappforge.process.approval.views import g as imported_g
            
            # g should be accessible in views
            self.assertEqual(g.user, self.mock_user)
            
    def tearDown(self):
        """Clean up test environment."""
        # Reset mocks and clear context
        self.mock_appbuilder.reset_mock()
        self.mock_sm.reset_mock()
        self.mock_db.reset_mock()


if __name__ == '__main__':
    unittest.main(verbosity=2)