"""
Comprehensive tests for the security framework.

Tests all security utilities, validators, auditing, and error handling
to ensure production-ready security across all mixins.
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from pgappforge.mixins.security_framework import (
    # Exceptions
    MixinSecurityError, MixinPermissionError, MixinValidationError,
    MixinDataError, MixinConfigurationError, MixinExternalServiceError,
    MixinDatabaseError,
    # Utilities
    SecurityValidator, InputValidator, SecurityAuditor, ErrorRecovery,
    # Decorators
    secure_operation, database_operation
)


class TestSecurityExceptions:
    """Test custom exception classes."""
    
    def test_mixin_security_error(self):
        """Test MixinSecurityError with details and user context."""
        details = {"action": "unauthorized_access", "resource": "sensitive_data"}
        error = MixinSecurityError("Security violation", details=details, user_id=123)
        
        assert str(error) == "Security violation"
        assert error.details == details
        assert error.user_id == 123
        assert isinstance(error.timestamp, datetime)
    
    def test_mixin_permission_error_inheritance(self):
        """Test MixinPermissionError inherits from MixinSecurityError."""
        error = MixinPermissionError("Permission denied", user_id=456)
        
        assert isinstance(error, MixinSecurityError)
        assert error.user_id == 456
    
    def test_mixin_validation_error(self):
        """Test MixinValidationError with field and value context."""
        error = MixinValidationError("Invalid email", field="email", value="invalid@")
        
        assert str(error) == "Invalid email"
        assert error.field == "email"
        assert error.value == "invalid@"
    
    def test_mixin_external_service_error(self):
        """Test MixinExternalServiceError with service context."""
        error = MixinExternalServiceError("API timeout", service="geocoding", response_code=504)
        
        assert error.service == "geocoding"
        assert error.response_code == 504
    
    def test_mixin_database_error_retryable(self):
        """Test MixinDatabaseError with retry context."""
        error = MixinDatabaseError("Connection lost", retryable=True, operation="insert")
        
        assert error.retryable is True
        assert error.operation == "insert"


class TestSecurityValidator:
    """Test SecurityValidator functionality."""
    
    @patch('pgappforge.mixins.security_framework.current_user')
    @patch('pgappforge.mixins.security_framework.db')
    def test_validate_user_context_current_user(self, mock_db, mock_current_user):
        """Test validating current user context."""
        # Setup mocks
        mock_user = Mock()
        mock_user.id = 123
        mock_user.active = True
        mock_current_user._get_current_object.return_value = mock_user
        
        # Test successful validation
        result = SecurityValidator.validate_user_context()
        
        assert result == mock_user
    
    @patch('pgappforge.mixins.security_framework.db')
    def test_validate_user_context_by_id(self, mock_db):
        """Test validating user by ID."""
        # Setup mocks
        mock_user = Mock()
        mock_user.id = 456
        mock_user.active = True
        mock_db.session.query.return_value.filter.return_value.first.return_value = mock_user
        
        # Test successful validation
        result = SecurityValidator.validate_user_context(user_id=456)
        
        assert result == mock_user
        mock_db.session.query.assert_called_once()
    
    @patch('pgappforge.mixins.security_framework.db')
    def test_validate_user_context_inactive_user(self, mock_db):
        """Test validation fails for inactive user."""
        # Setup inactive user
        mock_user = Mock()
        mock_user.id = 789
        mock_user.active = False
        mock_db.session.query.return_value.filter.return_value.first.return_value = mock_user
        
        # Test validation failure
        with pytest.raises(MixinPermissionError) as exc_info:
            SecurityValidator.validate_user_context(user_id=789)
        
        assert "not active" in str(exc_info.value)
        assert exc_info.value.details['active'] is False
    
    @patch('pgappforge.mixins.security_framework.db')
    def test_validate_user_context_locked_account(self, mock_db):
        """Test validation fails for locked account."""
        # Setup locked user
        mock_user = Mock()
        mock_user.id = 999
        mock_user.active = True
        mock_user.failed_login_count = 6
        mock_db.session.query.return_value.filter.return_value.first.return_value = mock_user
        
        # Test validation failure
        with pytest.raises(MixinPermissionError) as exc_info:
            SecurityValidator.validate_user_context(user_id=999)
        
        assert "account is locked" in str(exc_info.value)
        assert exc_info.value.details['failed_login_count'] == 6
    
    def test_validate_permission_success(self):
        """Test successful permission validation."""
        # Setup user with permission
        mock_user = Mock()
        mock_user.id = 123
        mock_user.has_permission.return_value = True
        
        # Test successful validation
        result = SecurityValidator.validate_permission(mock_user, "can_approve")
        
        assert result is True
        mock_user.has_permission.assert_called_once_with("can_approve")
    
    @patch('pgappforge.mixins.security_framework.SecurityAuditor')
    def test_validate_permission_denied(self, mock_auditor):
        """Test permission validation failure with audit logging."""
        # Setup user without permission
        mock_user = Mock()
        mock_user.id = 456
        mock_user.has_permission.return_value = False
        mock_user.roles = [Mock(name="basic_user")]
        
        # Test validation failure
        with pytest.raises(MixinPermissionError) as exc_info:
            SecurityValidator.validate_permission(mock_user, "can_delete", "sensitive_data")
        
        assert "lacks permission 'can_delete'" in str(exc_info.value)
        assert exc_info.value.details['permission'] == 'can_delete'
        assert exc_info.value.details['resource'] == 'sensitive_data'
        
        # Verify audit logging was called
        mock_auditor.log_security_event.assert_called_once()


class TestInputValidator:
    """Test InputValidator functionality."""
    
    def test_sanitize_string_basic(self):
        """Test basic string sanitization."""
        result = InputValidator.sanitize_string("  Hello World  ")
        assert result == "Hello World"
    
    def test_sanitize_string_max_length(self):
        """Test string length validation."""
        long_string = "x" * 1001
        
        with pytest.raises(MixinValidationError) as exc_info:
            InputValidator.sanitize_string(long_string, max_length=1000)
        
        assert "String too long" in str(exc_info.value)
        assert exc_info.value.value.endswith("...")
    
    def test_sanitize_string_html_removal(self):
        """Test HTML tag removal."""
        malicious_input = "<script>alert('xss')</script>Hello<b>World</b>"
        result = InputValidator.sanitize_string(malicious_input, allow_html=False)
        
        assert result == "HelloWorld"
        assert "<script>" not in result
        assert "<b>" not in result
    
    def test_sanitize_string_dangerous_chars(self):
        """Test removal of dangerous characters."""
        dangerous_input = "Hello<>&'\"World;"
        result = InputValidator.sanitize_string(dangerous_input, allow_html=False)
        
        assert result == "HelloWorld"
        for char in ['<', '>', '&', "'", '"', ';']:
            assert char not in result
    
    def test_sanitize_string_allow_html(self):
        """Test HTML preservation when allowed."""
        html_input = "<p>Hello <strong>World</strong></p>"
        result = InputValidator.sanitize_string(html_input, allow_html=True)
        
        assert result == html_input
    
    def test_validate_email_valid(self):
        """Test valid email validation."""
        valid_emails = [
            "user@example.com",
            "test.user+tag@domain.co.uk",
            "user123@test-domain.org"
        ]
        
        for email in valid_emails:
            result = InputValidator.validate_email(email)
            assert result == email.lower()
    
    def test_validate_email_invalid(self):
        """Test invalid email validation."""
        invalid_emails = [
            "invalid-email",
            "@domain.com",
            "user@",
            "user space@domain.com",
            "user@domain",
        ]
        
        for email in invalid_emails:
            with pytest.raises(MixinValidationError) as exc_info:
                InputValidator.validate_email(email)
            
            assert "Invalid email format" in str(exc_info.value)
            assert exc_info.value.field == 'email'
    
    def test_validate_json_data_valid(self):
        """Test valid JSON validation."""
        valid_json = '{"name": "test", "value": 123, "active": true}'
        result = InputValidator.validate_json_data(valid_json)
        
        expected = {"name": "test", "value": 123, "active": True}
        assert result == expected
    
    def test_validate_json_data_invalid(self):
        """Test invalid JSON validation."""
        invalid_json = '{"name": "test", "value": 123'  # Missing closing brace
        
        with pytest.raises(MixinValidationError) as exc_info:
            InputValidator.validate_json_data(invalid_json)
        
        assert "Invalid JSON data" in str(exc_info.value)
        assert exc_info.value.field == 'json_data'
    
    def test_validate_json_data_too_large(self):
        """Test JSON size limit validation."""
        large_json = '{"data": "' + 'x' * (1024 * 1024 + 1) + '"}'  # > 1MB
        
        with pytest.raises(MixinValidationError) as exc_info:
            InputValidator.validate_json_data(large_json)
        
        assert "JSON data too large" in str(exc_info.value)


class TestSecurityAuditor:
    """Test SecurityAuditor functionality."""
    
    @patch('pgappforge.mixins.security_framework.request')
    @patch('pgappforge.mixins.security_framework.logging')
    def test_log_security_event_with_request_context(self, mock_logging, mock_request):
        """Test security event logging with request context."""
        # Setup request mock
        mock_request.remote_addr = "192.168.1.100"
        mock_request.headers = {"User-Agent": "TestBot/1.0"}
        
        # Setup logger mocks
        mock_main_logger = Mock()
        mock_security_logger = Mock()
        mock_logging.getLogger.side_effect = lambda name: (
            mock_security_logger if name == 'security' else mock_main_logger
        )
        
        # Test event logging
        details = {"resource": "sensitive_data", "action": "unauthorized_access"}
        SecurityAuditor.log_security_event("permission_denied", user_id=123, details=details)
        
        # Verify both loggers were called
        assert mock_main_logger.warning.called
        assert mock_security_logger.warning.called
        
        # Verify log message contains expected data
        log_call_args = mock_main_logger.warning.call_args[0][0]
        assert "SECURITY_EVENT:" in log_call_args
        assert "permission_denied" in log_call_args
        assert "192.168.1.100" in log_call_args
        assert "TestBot/1.0" in log_call_args
    
    @patch('pgappforge.mixins.security_framework.request', None)
    @patch('pgappforge.mixins.security_framework.logging')
    def test_log_security_event_no_request_context(self, mock_logging):
        """Test security event logging without request context."""
        mock_logger = Mock()
        mock_logging.getLogger.return_value = mock_logger
        
        # Test event logging without request
        SecurityAuditor.log_security_event("data_export", user_id=456)
        
        # Verify logging was called
        assert mock_logger.warning.called
        
        # Verify log message handles missing request gracefully
        log_call_args = mock_logger.warning.call_args[0][0]
        assert "data_export" in log_call_args
        assert "null" in log_call_args  # IP address should be null


class TestErrorRecovery:
    """Test ErrorRecovery functionality."""
    
    def test_retry_with_backoff_success_first_try(self):
        """Test successful operation on first try."""
        operation = Mock(return_value="success")
        
        result = ErrorRecovery.retry_with_backoff(operation)
        
        assert result == "success"
        operation.assert_called_once()
    
    @patch('time.sleep')
    def test_retry_with_backoff_success_after_retries(self, mock_sleep):
        """Test successful operation after retries."""
        operation = Mock()
        operation.side_effect = [ConnectionError(), ConnectionError(), "success"]
        
        result = ErrorRecovery.retry_with_backoff(operation, max_retries=2)
        
        assert result == "success"
        assert operation.call_count == 3
        assert mock_sleep.call_count == 2
        
        # Verify exponential backoff
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert sleep_calls[0] == 1.0  # First retry
        assert sleep_calls[1] == 2.0  # Second retry
    
    @patch('time.sleep')
    def test_retry_with_backoff_max_delay(self, mock_sleep):
        """Test max delay is respected."""
        operation = Mock(side_effect=ConnectionError())
        
        with pytest.raises(ConnectionError):
            ErrorRecovery.retry_with_backoff(
                operation, 
                max_retries=5, 
                base_delay=10.0, 
                max_delay=30.0
            )
        
        # Verify max delay cap
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert all(delay <= 30.0 for delay in sleep_calls)
    
    def test_retry_with_backoff_non_retryable_exception(self):
        """Test non-retryable exception fails immediately."""
        operation = Mock(side_effect=ValueError("Invalid input"))
        
        with pytest.raises(ValueError):
            ErrorRecovery.retry_with_backoff(
                operation, 
                retryable_exceptions=(ConnectionError,)
            )
        
        operation.assert_called_once()  # Should not retry


class TestSecurityDecorators:
    """Test security decorator functionality."""
    
    @patch('pgappforge.mixins.security_framework.SecurityValidator')
    def test_secure_operation_decorator(self, mock_validator):
        """Test secure_operation decorator with permissions."""
        # Setup mocks
        mock_user = Mock()
        mock_user.id = 123
        mock_validator.validate_user_context.return_value = mock_user
        mock_validator.validate_permission.return_value = True
        
        # Create decorated function
        @secure_operation(permission='can_edit', log_access=True)
        def test_function(self, value):
            return f"result: {value}"
        
        # Create test instance
        test_instance = Mock()
        test_instance.__class__.__name__ = "TestModel"
        
        # Test function execution
        result = test_function(test_instance, "test_value")
        
        assert result == "result: test_value"
        mock_validator.validate_user_context.assert_called_once()
        mock_validator.validate_permission.assert_called_once_with(mock_user, 'can_edit')
    
    @patch('pgappforge.mixins.security_framework.db')
    def test_database_operation_decorator_success(self, mock_db):
        """Test database_operation decorator with successful transaction."""
        @database_operation(transaction=True)
        def test_function():
            return "success"
        
        result = test_function()
        
        assert result == "success"
        mock_db.session.commit.assert_called_once()
        mock_db.session.rollback.assert_not_called()
    
    @patch('pgappforge.mixins.security_framework.db')
    def test_database_operation_decorator_rollback(self, mock_db):
        """Test database_operation decorator with transaction rollback."""
        @database_operation(transaction=True)
        def test_function():
            raise ValueError("Test error")
        
        with pytest.raises(MixinDataError):
            test_function()
        
        mock_db.session.commit.assert_not_called()
        mock_db.session.rollback.assert_called_once()


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    @patch('pgappforge.mixins.security_framework.SecurityValidator')
    @patch('pgappforge.mixins.security_framework.SecurityAuditor')
    def test_approval_workflow_security_integration(self, mock_auditor, mock_validator):
        """Test complete approval workflow with security integration."""
        # Setup security mocks
        mock_user = Mock()
        mock_user.id = 123
        mock_validator.validate_user_context.return_value = mock_user
        mock_validator.validate_permission.return_value = True
        
        # Simulate approval operation
        @secure_operation(permission='can_approve', log_access=True)
        @database_operation(transaction=True)
        def approve_item(self, comments):
            return f"approved with comments: {comments}"
        
        # Test execution
        test_instance = Mock()
        result = approve_item(test_instance, "Looks good to approve")
        
        assert "approved with comments: Looks good to approve" in result
        
        # Verify security chain was executed
        mock_validator.validate_user_context.assert_called_once()
        mock_validator.validate_permission.assert_called_once_with(mock_user, 'can_approve')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])