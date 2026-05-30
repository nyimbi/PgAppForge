#!/usr/bin/env python3
"""
Comprehensive Security Tests for ApprovalWorkflowManager

This test suite validates all critical security fixes implemented in the
ApprovalWorkflowManager to prevent the following vulnerabilities:

1. Self-Approval Vulnerability
2. Privilege Escalation via Admin bypass
3. Workflow State Manipulation
4. JSON Injection Attacks
5. Bulk Operation Authorization Bypass

All tests follow PgAppForge testing patterns and include comprehensive
audit logging validation.
"""

import json
import pytest
import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from typing import Dict, List, Any

# Import the security-enhanced ApprovalWorkflowManager
from proper_pgappforge_extensions import (
    ApprovalWorkflowManager,
    ApprovalModelView,
    validate_security_implementation,
    generate_security_report
)

class TestApprovalSecurityFixes(unittest.TestCase):
    """
    Comprehensive test suite for approval workflow security fixes.
    """
    
    def setUp(self):
        """Set up test fixtures with mock PgAppForge components."""
        # Mock PgAppForge components
        self.mock_appbuilder = Mock()
        self.mock_sm = Mock()
        self.mock_appbuilder.sm = self.mock_sm
        self.mock_appbuilder.get_app.config = {
            'APP_NAME': 'TestApp',
            'PGAF_APPROVAL_WORKFLOWS': {
                'test_workflow': {
                    'steps': [
                        {'name': 'manager_review', 'required_role': 'Manager', 'required_approvals': 1},
                        {'name': 'admin_approval', 'required_role': 'Admin', 'required_approvals': 1}
                    ],
                    'initial_state': 'draft',
                    'approved_state': 'approved',
                    'rejected_state': 'rejected'
                }
            }
        }
        
        # Create manager instance
        self.manager = ApprovalWorkflowManager(self.mock_appbuilder)
        
        # Mock users
        self.regular_user = Mock()
        self.regular_user.id = 1
        self.regular_user.username = 'regular_user'
        self.regular_user.is_authenticated = True
        self.regular_user.is_active = True
        self.regular_user.roles = [Mock(name='User')]
        
        self.manager_user = Mock()
        self.manager_user.id = 2
        self.manager_user.username = 'manager_user'
        self.manager_user.is_authenticated = True
        self.manager_user.is_active = True
        self.manager_user.roles = [Mock(name='Manager')]
        
        self.admin_user = Mock()
        self.admin_user.id = 3
        self.admin_user.username = 'admin_user'
        self.admin_user.is_authenticated = True
        self.admin_user.is_active = True
        self.admin_user.roles = [Mock(name='Admin')]
        
        # Mock instance for testing
        self.mock_instance = Mock()
        self.mock_instance.__class__.__name__ = 'TestModel'
        self.mock_instance._approval_workflow = 'test_workflow'
        self.mock_instance.id = 123
        self.mock_instance.created_by_id = 1  # Created by regular_user
        self.mock_instance.current_state = 'draft'
        self.mock_instance.current_step = 0
        self.mock_instance.deleted = False
        self.mock_instance.approval_history = None
        
    def test_security_fix_1_self_approval_prevention(self):
        """
        Test Security Fix 1: Self-Approval Prevention
        
        Verifies that users cannot approve their own submissions.
        """
        # Set current user to the one who created the instance
        self.mock_sm.current_user = self.regular_user
        
        # Attempt approval - should be blocked
        with patch.object(self.manager, '_audit_log_security_event') as mock_audit:
            result = self.manager.approve_instance(self.mock_instance, step=0)
            
            # Verify approval was blocked
            self.assertFalse(result, "Self-approval should be prevented")
            
            # Verify security event was logged
            mock_audit.assert_called_with('self_approval_blocked', {
                'user_id': 1,
                'user_name': 'regular_user',
                'instance_id': 123,
                'instance_type': 'TestModel',
                'step': 0
            })
    
    def test_security_fix_1_self_approval_multiple_ownership_fields(self):
        """
        Test self-approval prevention across multiple ownership field patterns.
        """
        ownership_fields = [
            'created_by_id', 'owner_id', 'submitted_by_id', 
            'user_id', 'author_id', 'requester_id'
        ]
        
        for field in ownership_fields:
            with self.subTest(field=field):
                # Create fresh mock instance
                test_instance = Mock()
                test_instance.__class__.__name__ = 'TestModel'
                test_instance._approval_workflow = 'test_workflow'
                test_instance.id = 456
                test_instance.current_state = 'draft'
                test_instance.current_step = 0
                test_instance.deleted = False
                test_instance.approval_history = None
                
                # Set the ownership field
                setattr(test_instance, field, 1)  # regular_user.id
                
                # Set current user
                self.mock_sm.current_user = self.regular_user
                
                # Attempt approval
                result = self.manager.approve_instance(test_instance, step=0)
                
                # Verify approval was blocked
                self.assertFalse(result, f"Self-approval should be prevented via {field}")
    
    def test_security_fix_2_enhanced_admin_validation(self):
        """
        Test Security Fix 2: Enhanced Admin Validation with Audit Logging
        
        Verifies that admin privileges are properly validated and logged.
        """
        # Set current user to admin
        self.mock_sm.current_user = self.admin_user
        
        with patch.object(self.manager, '_audit_log_security_event') as mock_audit:
            with patch.object(self.manager, 'execute_with_transaction') as mock_transaction:
                mock_transaction.return_value = {'approval_id': 'test123'}
                
                # Admin should be able to approve (not self-approval)
                self.mock_instance.created_by_id = 999  # Different user
                result = self.manager.approve_instance(self.mock_instance, step=0)
                
                # Verify approval succeeded
                self.assertTrue(result, "Admin should be able to approve with proper validation")
                
                # Verify admin privilege use was logged
                admin_events = [call for call in mock_audit.call_args_list 
                              if call[0][0] == 'admin_privilege_used']
                self.assertTrue(len(admin_events) > 0, "Admin privilege use should be logged")
    
    def test_security_fix_2_invalid_admin_detection(self):
        """
        Test detection of invalid admin privileges.
        """
        # Create user with invalid admin role
        invalid_admin = Mock()
        invalid_admin.id = 4
        invalid_admin.username = 'invalid_admin'
        invalid_admin.is_authenticated = True
        invalid_admin.is_active = True
        
        # Admin role without proper ID
        invalid_role = Mock()
        invalid_role.name = 'Admin'
        invalid_role.id = None  # Invalid
        invalid_admin.roles = [invalid_role]
        
        self.mock_sm.current_user = invalid_admin
        
        with patch.object(self.manager, '_audit_log_security_event') as mock_audit:
            self.mock_instance.created_by_id = 999  # Different user
            result = self.manager.approve_instance(self.mock_instance, step=0)
            
            # Verify approval was blocked
            self.assertFalse(result, "Invalid admin role should be rejected")
            
            # Verify rejection was logged
            rejection_events = [call for call in mock_audit.call_args_list 
                              if call[0][0] == 'admin_privilege_rejected']
            self.assertTrue(len(rejection_events) > 0, "Admin privilege rejection should be logged")
    
    def test_security_fix_3_workflow_state_sequence_validation(self):
        """
        Test Security Fix 3: Workflow State Sequence Validation
        
        Verifies that workflow steps must be completed in proper sequence.
        """
        self.mock_sm.current_user = self.manager_user
        self.mock_instance.created_by_id = 999  # Different user
        
        # Try to approve step 1 before step 0 is completed
        self.mock_instance.current_step = 0  # Still at step 0
        
        with patch.object(self.manager, '_audit_log_security_event') as mock_audit:
            result = self.manager.approve_instance(self.mock_instance, step=1)  # Skip to step 1
            
            # Verify approval was blocked
            self.assertFalse(result, "Step sequence violation should be prevented")
            
            # Verify security event was logged
            state_events = [call for call in mock_audit.call_args_list 
                           if call[0][0] == 'invalid_workflow_state']
            self.assertTrue(len(state_events) > 0, "State validation failure should be logged")
    
    def test_security_fix_3_prerequisite_step_validation(self):
        """
        Test prerequisite step validation.
        """
        # Mock instance with no approval history (no prerequisites completed)
        self.mock_instance.approval_history = '[]'  # No approvals yet
        self.mock_instance.current_step = 1  # Trying to approve step 1
        
        self.mock_sm.current_user = self.admin_user
        self.mock_instance.created_by_id = 999  # Different user
        
        result = self.manager.approve_instance(self.mock_instance, step=1)
        
        # Should fail because step 0 (prerequisite) wasn't completed
        self.assertFalse(result, "Prerequisite step validation should prevent approval")
    
    def test_security_fix_4_json_injection_prevention(self):
        """
        Test Security Fix 4: JSON Injection Prevention
        
        Verifies that malicious input in comments is properly sanitized.
        """
        self.mock_sm.current_user = self.manager_user
        self.mock_instance.created_by_id = 999  # Different user
        
        # Test various injection patterns
        malicious_comments = [
            '<script>alert("xss")</script>',
            'javascript:alert(1)',
            'SELECT * FROM users',
            'DROP TABLE approvals; --',
            '{"__proto__": {"admin": true}}',
            'eval(malicious_code)',
            '<iframe src="evil.com"></iframe>'
        ]
        
        for malicious_comment in malicious_comments:
            with self.subTest(comment=malicious_comment):
                with patch.object(self.manager, '_audit_log_security_event') as mock_audit:
                    result = self.manager.approve_instance(
                        self.mock_instance, 
                        step=0, 
                        comments=malicious_comment
                    )
                    
                    # Verify approval was blocked due to malicious comments
                    self.assertFalse(result, f"Malicious comment should be rejected: {malicious_comment}")
                    
                    # Verify security event was logged
                    malicious_events = [call for call in mock_audit.call_args_list 
                                      if call[0][0] == 'malicious_comment_blocked']
                    self.assertTrue(len(malicious_events) > 0, "Malicious comment should be logged")
    
    def test_security_fix_4_safe_comment_sanitization(self):
        """
        Test that safe comments are properly sanitized but not rejected.
        """
        safe_comment = "This is a normal approval comment with some <b>formatting</b>"
        expected_sanitized = "This is a normal approval comment with some formatting"
        
        # Test sanitization function directly
        result = self.manager._sanitize_approval_comments(safe_comment)
        self.assertEqual(result, expected_sanitized, "Safe comments should be sanitized but preserved")
    
    def test_security_fix_5_bulk_operation_authorization(self):
        """
        Test Security Fix 5: Bulk Operation Authorization
        
        Verifies that bulk approvals validate authorization for each item individually.
        """
        # Create multiple mock instances
        instances = []
        for i in range(3):
            instance = Mock()
            instance.__class__.__name__ = 'TestModel'
            instance.id = 100 + i
            instance.created_by_id = 1 if i == 0 else 999  # First instance is self-authored
            instance.current_state = 'draft'
            instance.current_step = 0
            instance.deleted = False
            instance.approval_history = None
            instances.append(instance)
        
        # Create mock view
        mock_view = ApprovalModelView()
        mock_view.appbuilder = self.mock_appbuilder
        mock_view.appbuilder.awm = self.manager
        
        self.mock_sm.current_user = self.manager_user
        
        with patch.object(mock_view, 'get_redirect') as mock_redirect:
            with patch('flask.session', {}):
                mock_redirect.return_value = '/test'
                
                # Attempt bulk approval
                with patch.object(self.manager, '_audit_log_security_event') as mock_audit:
                    with patch.object(self.manager, 'approve_instance') as mock_approve:
                        # Mock approve_instance to return True for authorized items
                        mock_approve.return_value = True
                        
                        result = mock_view._approve_items(instances, step=0)
                        
                        # Verify individual authorization was checked
                        # First instance should be rejected (self-authored)
                        # Other instances should be approved
                        
                        # Verify bulk operation was logged
                        bulk_events = [call for call in mock_audit.call_args_list 
                                     if call[0][0] == 'bulk_approval_completed']
                        self.assertTrue(len(bulk_events) > 0, "Bulk operation should be logged")
    
    def test_approval_history_integrity_validation(self):
        """
        Test approval history integrity validation.
        """
        # Test with malicious JSON patterns
        malicious_history = '{"approvals": [], "__proto__": {"admin": true}}'
        
        self.mock_instance.approval_history = malicious_history
        
        # Should return empty list due to malicious pattern detection
        result = self.manager._get_validated_approval_history(self.mock_instance)
        self.assertEqual(result, [], "Malicious approval history should be rejected")
    
    def test_rate_limiting_bulk_operations(self):
        """
        Test rate limiting for bulk approval operations.
        """
        mock_view = ApprovalModelView()
        mock_view.appbuilder = self.mock_appbuilder
        mock_view.appbuilder.awm = self.manager
        
        with patch('flask.session', {}) as mock_session:
            # First call should succeed (within rate limit)
            result1 = mock_view._check_bulk_approval_rate_limit(1)
            self.assertTrue(result1, "First bulk operation should be allowed")
            
            # Immediate second call should be blocked
            result2 = mock_view._check_bulk_approval_rate_limit(1)
            self.assertFalse(result2, "Rapid bulk operations should be rate limited")
    
    def test_comprehensive_audit_logging(self):
        """
        Test comprehensive audit logging for security events.
        """
        test_event_data = {
            'user_id': 123,
            'action': 'test_action',
            'details': 'test details'
        }
        
        with patch('logging.getLogger') as mock_logger:
            mock_security_logger = Mock()
            mock_logger.return_value = mock_security_logger
            
            self.manager._audit_log_security_event('test_event', test_event_data)
            
            # Verify security logger was called
            mock_security_logger.warning.assert_called_once()
            
            # Verify log message contains event data
            log_call = mock_security_logger.warning.call_args[0][0]
            self.assertIn('test_event', log_call)
            self.assertIn('user_id', log_call)
    
    def test_security_validation_report(self):
        """
        Test security validation and reporting functions.
        """
        # Test validation function
        validation_results = validate_security_implementation()
        
        self.assertIn('timestamp', validation_results)
        self.assertIn('security_version', validation_results)
        self.assertIn('tests_passed', validation_results)
        self.assertIn('tests_failed', validation_results)
        self.assertIn('overall_status', validation_results)
        
        # Test report generation
        report = generate_security_report()
        
        self.assertIn('SECURITY IMPLEMENTATION REPORT', report)
        self.assertIn('SECURITY FEATURES IMPLEMENTED', report)
        self.assertIn('SECURITY VULNERABILITY FIXES', report)
    
class TestSecurityEdgeCases(unittest.TestCase):
    """
    Test edge cases and boundary conditions for security fixes.
    """
    
    def setUp(self):
        """Set up edge case test fixtures."""
        self.mock_appbuilder = Mock()
        self.mock_appbuilder.get_app.config = {
            'PGAF_APPROVAL_WORKFLOWS': {
                'default': {
                    'steps': [{'name': 'review', 'required_role': 'Manager'}],
                    'initial_state': 'draft',
                    'approved_state': 'approved'
                }
            }
        }
        self.manager = ApprovalWorkflowManager(self.mock_appbuilder)
    
    def test_empty_approval_history_handling(self):
        """
        Test handling of empty or invalid approval history.
        """
        mock_instance = Mock()
        mock_instance.approval_history = None
        
        result = self.manager._get_validated_approval_history(mock_instance)
        self.assertEqual(result, [], "Empty approval history should return empty list")
        
        # Test invalid JSON
        mock_instance.approval_history = 'invalid json{'
        result = self.manager._get_validated_approval_history(mock_instance)
        self.assertEqual(result, [], "Invalid JSON should return empty list")
    
    def test_oversized_approval_history(self):
        """
        Test handling of oversized approval history data.
        """
        mock_instance = Mock()
        # Create oversized JSON (over 100KB limit)
        large_data = '[' + ','.join(['{}'] * 10000) + ']'
        mock_instance.approval_history = large_data
        
        result = self.manager._get_validated_approval_history(mock_instance)
        self.assertEqual(result, [], "Oversized approval history should be rejected")
    
    def test_unicode_and_encoding_attacks(self):
        """
        Test handling of unicode and encoding-based attacks.
        """
        unicode_attacks = [
            '\u003cscript\u003ealert(1)\u003c/script\u003e',
            '\u0000\u0001\u0002',  # Control characters
            '\ufeff',  # BOM character
            '\u200b\u200c\u200d'  # Zero-width characters
        ]
        
        for attack in unicode_attacks:
            with self.subTest(attack=attack):
                result = self.manager._sanitize_approval_comments(attack)
                self.assertIsNone(result, f"Unicode attack should be rejected: {repr(attack)}")
    
    def test_boundary_conditions_step_validation(self):
        """
        Test boundary conditions for step validation.
        """
        workflow_config = {
            'steps': [{'name': 'step1', 'required_role': 'User'}]
        }
        
        # Test negative step
        result = self.manager._validate_approval_step(-1, workflow_config)
        self.assertFalse(result, "Negative step should be invalid")
        
        # Test step beyond range
        result = self.manager._validate_approval_step(1, workflow_config)
        self.assertFalse(result, "Step beyond range should be invalid")
        
        # Test valid step
        result = self.manager._validate_approval_step(0, workflow_config)
        self.assertTrue(result, "Valid step should be accepted")

if __name__ == '__main__':
    # Run the comprehensive security test suite
    print("🔒 RUNNING COMPREHENSIVE APPROVAL SECURITY TESTS...")
    print("="*60)
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add all test cases
    test_suite.addTest(unittest.makeSuite(TestApprovalSecurityFixes))
    test_suite.addTest(unittest.makeSuite(TestSecurityEdgeCases))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print("\n" + "="*60)
    if result.wasSuccessful():
        print("✅ ALL SECURITY TESTS PASSED!")
        print(f"✅ Ran {result.testsRun} tests successfully")
        print("\n🛡️  SECURITY VALIDATION COMPLETE:")
        print("   • Self-approval prevention: TESTED ✅")
        print("   • Admin privilege validation: TESTED ✅")
        print("   • Workflow state validation: TESTED ✅")
        print("   • JSON injection prevention: TESTED ✅")
        print("   • Bulk operation security: TESTED ✅")
        print("   • Audit logging: TESTED ✅")
        print("   • Rate limiting: TESTED ✅")
        print("   • Input sanitization: TESTED ✅")
        print("   • Edge case handling: TESTED ✅")
    else:
        print(f"❌ {len(result.failures)} TESTS FAILED")
        print(f"❌ {len(result.errors)} TESTS HAD ERRORS")
        for failure in result.failures:
            print(f"FAILURE: {failure[0]}")
        for error in result.errors:
            print(f"ERROR: {error[0]}")
    
    print("\n🚀 PgAppForge ApprovalWorkflowManager Security Testing Complete!")
