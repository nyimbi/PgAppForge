"""
Process Security Tests.

Comprehensive test suite for process security validation,
authorization, tenant isolation, and audit logging.
"""

import json
import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from flask import Flask
from flask_testing import TestCase

from pgappforge.process.security.validation import (
    ProcessValidator, ProcessAuthorization, TenantIsolationValidator,
    ProcessAuditLogger, RateLimiter, ProcessSecurityManager,
    ValidationError, AuthorizationError, TenantIsolationError, RateLimitExceededError
)
from pgappforge.process.security.integration import (
    secure_api_endpoint, secure_view_method, init_process_security
)
from pgappforge.process.models.process_models import (
    ProcessDefinition, ProcessInstance
)
from pgappforge.process.models.audit_models import (
    ProcessAuditLog, ProcessSecurityEvent
)


class ProcessSecurityTestCase(TestCase):
    """Base test case for process security tests."""
    
    def create_app(self):
        """Create test Flask app."""
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test_secret_key'
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['WTF_CSRF_ENABLED'] = False
        
        # Initialize security
        init_process_security(app)
        
        return app
    
    def setUp(self):
        """Set up test fixtures."""
        self.validator = ProcessValidator()
        self.security_manager = ProcessSecurityManager()
        self.rate_limiter = RateLimiter()


class TestProcessValidator(ProcessSecurityTestCase):
    """Test process input validation."""
    
    def test_validate_valid_process_definition(self):
        """Test validation of valid process definition."""
        valid_data = {
            'name': 'test_process',
            'description': 'A test process',
            'category': 'test',
            'definition': {
                'nodes': {
                    'start': {'type': 'start', 'name': 'Start'},
                    'task1': {'type': 'task', 'name': 'Task 1'},
                    'end': {'type': 'end', 'name': 'End'}
                },
                'edges': [
                    {'from': 'start', 'to': 'task1'},
                    {'from': 'task1', 'to': 'end'}
                ]
            }
        }
        
        # Should not raise exception
        result = ProcessValidator.validate_process_definition(valid_data)
        self.assertEqual(result['name'], 'test_process')
    
    def test_validate_invalid_process_name(self):
        """Test validation with invalid process name."""
        invalid_data = {
            'name': '123_invalid',  # Starts with number
            'description': 'A test process',
            'definition': {'nodes': {}, 'edges': []}
        }
        
        with self.assertRaises(ValidationError):
            ProcessValidator.validate_process_definition(invalid_data)
    
    def test_validate_missing_required_fields(self):
        """Test validation with missing required fields."""
        invalid_data = {
            'description': 'Missing name and definition'
        }
        
        with self.assertRaises(ValidationError):
            ProcessValidator.validate_process_definition(invalid_data)
    
    def test_validate_dangerous_expression(self):
        """Test detection of dangerous expressions."""
        dangerous_data = {
            'name': 'dangerous_process',
            'description': 'A process with dangerous expressions',
            'definition': {
                'nodes': {
                    'start': {'type': 'start', 'name': 'Start'},
                    'task1': {
                        'type': 'task',
                        'name': 'Dangerous Task',
                        'properties': {
                            'script': '__import__("os").system("rm -rf /")'
                        }
                    }
                },
                'edges': []
            }
        }
        
        with self.assertRaises(ValidationError):
            ProcessValidator.validate_process_definition(dangerous_data)
    
    def test_sanitize_html(self):
        """Test HTML sanitization."""
        dirty_html = '<script>alert("xss")</script><p>Safe content</p>'
        clean_html = ProcessValidator.sanitize_html(dirty_html)
        
        self.assertNotIn('<script>', clean_html)
        self.assertIn('<p>Safe content</p>', clean_html)
    
    def test_validate_process_instance_data(self):
        """Test process instance data validation."""
        valid_data = {
            'process_definition_id': 1,
            'context_data': {'key': 'value'}
        }
        
        result = ProcessValidator.validate_process_instance_data(valid_data)
        self.assertEqual(result['process_definition_id'], 1)
    
    def test_validate_oversized_context_data(self):
        """Test validation of oversized context data."""
        large_data = 'x' * (ProcessValidator.MAX_PROPERTIES_SIZE + 1)
        invalid_data = {
            'process_definition_id': 1,
            'context_data': {'large_field': large_data}
        }
        
        with self.assertRaises(ValidationError):
            ProcessValidator.validate_process_instance_data(invalid_data)


class TestProcessAuthorization(ProcessSecurityTestCase):
    """Test process authorization."""
    
    @patch('pgappforge.process.security.validation.current_user')
    def test_check_permission_authenticated_user(self, mock_user):
        """Test permission check for authenticated user."""
        mock_user.is_authenticated = True
        mock_user.has_permission.return_value = True
        
        result = ProcessAuthorization.check_permission('create')
        self.assertTrue(result)
    
    @patch('pgappforge.process.security.validation.current_user')
    def test_check_permission_unauthenticated_user(self, mock_user):
        """Test permission check for unauthenticated user."""
        mock_user = None
        
        result = ProcessAuthorization.check_permission('create')
        self.assertFalse(result)
    
    @patch('pgappforge.process.security.validation.current_user')
    def test_check_permission_insufficient_rights(self, mock_user):
        """Test permission check with insufficient rights."""
        mock_user.is_authenticated = True
        mock_user.has_permission.return_value = False
        
        result = ProcessAuthorization.check_permission('admin')
        self.assertFalse(result)
    
    def test_require_permission_decorator(self):
        """Test permission requirement decorator."""
        @ProcessAuthorization.require_permission('create')
        def protected_function():
            return "success"
        
        with patch('pgappforge.process.security.validation.current_user') as mock_user:
            mock_user.is_authenticated = True
            mock_user.has_permission.return_value = True
            
            result = protected_function()
            self.assertEqual(result, "success")
    
    def test_require_permission_decorator_unauthorized(self):
        """Test permission requirement decorator with unauthorized access."""
        @ProcessAuthorization.require_permission('create')
        def protected_function():
            return "success"
        
        with patch('pgappforge.process.security.validation.current_user') as mock_user:
            mock_user.is_authenticated = True
            mock_user.has_permission.return_value = False
            
            with self.assertRaises(AuthorizationError):
                protected_function()


class TestTenantIsolationValidator(ProcessSecurityTestCase):
    """Test tenant isolation validation."""
    
    @patch('pgappforge.process.security.validation.get_current_tenant_id')
    def test_validate_tenant_access_valid(self, mock_tenant_id):
        """Test valid tenant access validation."""
        mock_tenant_id.return_value = 1
        
        # Mock model query
        with patch.object(ProcessDefinition, 'query') as mock_query:
            mock_filter = mock_query.filter.return_value
            mock_filter.first.return_value = ProcessDefinition()
            
            result = TenantIsolationValidator.validate_tenant_access(ProcessDefinition, 1)
            self.assertTrue(result)
    
    @patch('pgappforge.process.security.validation.get_current_tenant_id')
    def test_validate_tenant_access_invalid(self, mock_tenant_id):
        """Test invalid tenant access validation."""
        mock_tenant_id.return_value = 1
        
        # Mock model query returning None
        with patch.object(ProcessDefinition, 'query') as mock_query:
            mock_filter = mock_query.filter.return_value
            mock_filter.first.return_value = None
            
            result = TenantIsolationValidator.validate_tenant_access(ProcessDefinition, 999)
            self.assertFalse(result)
    
    def test_require_tenant_access_decorator(self):
        """Test tenant access requirement decorator."""
        @TenantIsolationValidator.require_tenant_access(ProcessDefinition)
        def protected_function(id=1):
            return f"success for {id}"
        
        with patch.object(TenantIsolationValidator, 'validate_tenant_access', return_value=True):
            result = protected_function(id=1)
            self.assertEqual(result, "success for 1")
    
    def test_require_tenant_access_decorator_unauthorized(self):
        """Test tenant access requirement decorator with unauthorized access."""
        @TenantIsolationValidator.require_tenant_access(ProcessDefinition)
        def protected_function(id=1):
            return f"success for {id}"
        
        with patch.object(TenantIsolationValidator, 'validate_tenant_access', return_value=False):
            with self.assertRaises(TenantIsolationError):
                protected_function(id=999)


class TestRateLimiter(ProcessSecurityTestCase):
    """Test rate limiting."""
    
    def test_rate_limit_allowed(self):
        """Test requests within rate limit."""
        # First request should be allowed
        result = self.rate_limiter.is_allowed('test_key', limit=5, window=60)
        self.assertTrue(result)
        
        # Additional requests within limit should be allowed
        for i in range(4):
            result = self.rate_limiter.is_allowed('test_key', limit=5, window=60)
            self.assertTrue(result)
    
    def test_rate_limit_exceeded(self):
        """Test requests exceeding rate limit."""
        # Fill up the limit
        for i in range(5):
            self.rate_limiter.is_allowed('test_key', limit=5, window=60)
        
        # Next request should be denied
        result = self.rate_limiter.is_allowed('test_key', limit=5, window=60)
        self.assertFalse(result)
    
    def test_rate_limit_window_expiry(self):
        """Test rate limit window expiry."""
        import time
        
        # Fill up the limit with short window
        for i in range(3):
            self.rate_limiter.is_allowed('test_key', limit=3, window=1)
        
        # Wait for window to expire
        time.sleep(1.1)
        
        # Should be allowed again
        result = self.rate_limiter.is_allowed('test_key', limit=3, window=1)
        self.assertTrue(result)
    
    def test_rate_limit_decorator(self):
        """Test rate limiting decorator."""
        decorator = RateLimiter.create_rate_limit_decorator(limit=2, window=60)
        
        @decorator
        def limited_function():
            return "success"
        
        with patch('pgappforge.process.security.validation.current_user') as mock_user, \
             patch('pgappforge.process.security.validation.request') as mock_request:
            
            mock_user.id = 1
            mock_request.endpoint = 'test_endpoint'
            
            # First two calls should succeed
            result1 = limited_function()
            result2 = limited_function()
            
            self.assertEqual(result1, "success")
            self.assertEqual(result2, "success")
            
            # Third call should raise exception
            with self.assertRaises(RateLimitExceededError):
                limited_function()


class TestProcessAuditLogger(ProcessSecurityTestCase):
    """Test audit logging."""
    
    @patch('pgappforge.process.security.validation.current_user')
    @patch('pgappforge.process.security.validation.request')
    @patch('pgappforge.process.security.validation.get_current_tenant_id')
    def test_log_operation(self, mock_tenant_id, mock_request, mock_user):
        """Test audit log operation recording."""
        mock_user.id = 1
        mock_user.username = 'testuser'
        mock_request.remote_addr = '127.0.0.1'
        mock_request.headers.get.return_value = 'test-agent'
        mock_tenant_id.return_value = 1
        
        # Mock database operations
        with patch('pgappforge.process.security.validation.log') as mock_log:
            ProcessAuditLogger.log_operation(
                operation='test_operation',
                resource_type='process',
                resource_id=1,
                details={'test': 'data'},
                success=True
            )
            
            # Verify log was called
            mock_log.log.assert_called()
    
    def test_audit_decorator(self):
        """Test audit logging decorator."""
        @ProcessAuditLogger.audit('test_operation', 'process')
        def audited_function():
            return "success"
        
        with patch('pgappforge.process.security.validation.current_user'), \
             patch('pgappforge.process.security.validation.request'), \
             patch('pgappforge.process.security.validation.get_current_tenant_id'), \
             patch.object(ProcessAuditLogger, 'log_operation') as mock_log:
            
            result = audited_function()
            
            self.assertEqual(result, "success")
            mock_log.assert_called()
    
    def test_audit_decorator_with_exception(self):
        """Test audit logging decorator with exception."""
        @ProcessAuditLogger.audit('test_operation', 'process')
        def failing_function():
            raise ValueError("Test error")
        
        with patch('pgappforge.process.security.validation.current_user'), \
             patch('pgappforge.process.security.validation.request'), \
             patch('pgappforge.process.security.validation.get_current_tenant_id'), \
             patch.object(ProcessAuditLogger, 'log_operation') as mock_log:
            
            with self.assertRaises(ValueError):
                failing_function()
            
            # Verify failure was logged
            mock_log.assert_called()
            args, kwargs = mock_log.call_args
            self.assertFalse(kwargs['success'])


class TestProcessSecurityManager(ProcessSecurityTestCase):
    """Test the main security manager."""
    
    @patch('pgappforge.process.security.validation.current_user')
    @patch('pgappforge.process.security.validation.request')
    def test_validate_and_secure_operation_success(self, mock_request, mock_user):
        """Test successful security validation."""
        mock_user.is_authenticated = True
        mock_user.id = 1
        mock_user.username = 'testuser'
        mock_request.endpoint = 'test_endpoint'
        mock_request.remote_addr = '127.0.0.1'
        
        with patch.object(ProcessAuthorization, 'check_permission', return_value=True), \
             patch.object(ProcessAuditLogger, 'log_operation'):
            
            result = self.security_manager.validate_and_secure_operation(
                operation='read',
                data={'test': 'data'},
                resource_id=1
            )
            
            self.assertIsInstance(result, dict)
    
    @patch('pgappforge.process.security.validation.current_user')
    def test_validate_and_secure_operation_unauthorized(self, mock_user):
        """Test unauthorized access."""
        mock_user = None  # Unauthenticated
        
        with self.assertRaises(AuthorizationError):
            self.security_manager.validate_and_secure_operation(
                operation='read',
                resource_id=1
            )
    
    @patch('pgappforge.process.security.validation.current_user')
    @patch('pgappforge.process.security.validation.request')
    def test_rate_limit_check(self, mock_request, mock_user):
        """Test rate limiting in security manager."""
        mock_user.is_authenticated = True
        mock_user.id = 1
        mock_request.endpoint = 'test_endpoint'
        
        # Mock rate limiter to return False (rate limit exceeded)
        with patch.object(self.security_manager.rate_limiter, 'is_allowed', return_value=False):
            with self.assertRaises(RateLimitExceededError):
                self.security_manager.validate_and_secure_operation(
                    operation='read',
                    resource_id=1
                )


class TestSecurityIntegrationDecorators(ProcessSecurityTestCase):
    """Test security integration decorators."""
    
    def test_secure_api_endpoint_decorator(self):
        """Test secure API endpoint decorator."""
        @secure_api_endpoint('read', 'process')
        def test_api_endpoint():
            return {'status': 'success'}
        
        with patch('pgappforge.process.security.integration.security_manager') as mock_manager:
            mock_manager.validate_and_secure_operation.return_value = {}
            
            with patch('pgappforge.process.security.integration.ProcessAuditLogger') as mock_audit:
                result = test_api_endpoint()
                
                self.assertEqual(result, {'status': 'success'})
                mock_manager.validate_and_secure_operation.assert_called_once()
                mock_audit.log_operation.assert_called_once()
    
    def test_secure_view_method_decorator(self):
        """Test secure view method decorator."""
        @secure_view_method('read', 'process')
        def test_view_method(self):
            return "success"
        
        with patch('pgappforge.process.security.integration.security_manager') as mock_manager:
            mock_manager.validate_and_secure_operation.return_value = {}
            
            with patch('pgappforge.process.security.integration.ProcessAuditLogger') as mock_audit:
                result = test_view_method(None)
                
                self.assertEqual(result, "success")
                mock_manager.validate_and_secure_operation.assert_called_once()
                mock_audit.log_operation.assert_called_once()


class TestSecurityModels(ProcessSecurityTestCase):
    """Test security-related models."""
    
    def test_process_audit_log_model(self):
        """Test ProcessAuditLog model."""
        audit_log = ProcessAuditLog(
            operation='test_operation',
            resource_type='process',
            resource_id=1,
            user_id=1,
            username='testuser',
            tenant_id=1,
            ip_address='127.0.0.1',
            success=True,
            details='{"test": "data"}'
        )
        
        self.assertEqual(audit_log.operation, 'test_operation')
        self.assertEqual(audit_log.details_dict, {"test": "data"})
        
        # Test setting details_dict
        audit_log.details_dict = {"new": "data"}
        self.assertEqual(json.loads(audit_log.details), {"new": "data"})
    
    def test_process_security_event_model(self):
        """Test ProcessSecurityEvent model."""
        security_event = ProcessSecurityEvent(
            event_type=ProcessSecurityEvent.TYPE_AUTH_FAILURE,
            severity=ProcessSecurityEvent.SEVERITY_WARNING,
            message='Test security event',
            user_id=1,
            username='testuser'
        )
        
        self.assertEqual(security_event.event_type, 'auth_failure')
        self.assertEqual(security_event.severity, 'warning')
        self.assertFalse(security_event.resolved)
        
        # Test resolve method
        security_event.resolve(1, 'Resolved by admin')
        self.assertTrue(security_event.resolved)
        self.assertEqual(security_event.resolved_by, 1)


class TestSecurityHeaders(ProcessSecurityTestCase):
    """Test security headers."""
    
    def test_add_security_headers(self):
        """Test security headers are added to responses."""
        from pgappforge.process.security.integration import SecurityHeaders
        
        with self.app.test_client() as client:
            with patch('flask.Response') as mock_response:
                mock_response.headers = {}
                
                result = SecurityHeaders.add_security_headers(mock_response)
                
                # Verify security headers were added
                self.assertIn('X-Content-Type-Options', result.headers)
                self.assertIn('X-Frame-Options', result.headers)
                self.assertIn('X-XSS-Protection', result.headers)


if __name__ == '__main__':
    unittest.main()