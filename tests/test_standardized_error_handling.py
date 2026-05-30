"""
Tests for standardized error handling system.

These tests ensure that the new standardized error handling patterns work correctly,
integrate properly with existing PgAppForge components, and maintain backward
compatibility with existing FABException usage.
"""

import pytest
import logging
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from pgappforge.exceptions.standardized import (
    ErrorCategory, ErrorSeverity, RecoveryAction, ErrorContext,
    StandardizedFABException, FABAuthenticationError, FABAuthorizationError,
    FABValidationError, FABDatabaseError, FABConfigurationError,
    FABSecurityError, FABPerformanceError, FABAPIError,
    ErrorHandler, fab_error_handler, get_error_stats,
    create_validation_error, create_security_error, create_database_error,
    create_api_error, get_request_context, add_user_context
)


class TestErrorCategories:
    """Test error category and severity enums."""

    def test_error_categories_exist(self):
        """Test that all expected error categories are defined."""
        expected_categories = [
            'AUTHENTICATION', 'AUTHORIZATION', 'VALIDATION', 'DATABASE',
            'NETWORK', 'CONFIGURATION', 'BUSINESS_LOGIC', 'PERFORMANCE',
            'SECURITY', 'INTEGRATION', 'SYSTEM', 'USER_INPUT',
            'FILE_OPERATION', 'API'
        ]

        for category in expected_categories:
            assert hasattr(ErrorCategory, category)
            assert isinstance(getattr(ErrorCategory, category), ErrorCategory)

    def test_error_severities_exist(self):
        """Test that all expected error severities are defined."""
        expected_severities = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

        for severity in expected_severities:
            assert hasattr(ErrorSeverity, severity)
            assert isinstance(getattr(ErrorSeverity, severity), ErrorSeverity)

    def test_recovery_actions_exist(self):
        """Test that all expected recovery actions are defined."""
        expected_actions = [
            'RETRY', 'ESCALATE', 'FALLBACK', 'ABORT', 'IGNORE',
            'MANUAL_INTERVENTION', 'REFRESH', 'LOGOUT_LOGIN', 'CONTACT_SUPPORT'
        ]

        for action in expected_actions:
            assert hasattr(RecoveryAction, action)
            assert isinstance(getattr(RecoveryAction, action), RecoveryAction)


class TestErrorContext:
    """Test error context functionality."""

    def test_error_context_creation(self):
        """Test creating error context with default values."""
        context = ErrorContext()

        assert isinstance(context.timestamp, datetime)
        assert context.user_id is None
        assert context.session_id is None
        assert context.operation is None
        assert isinstance(context.additional_data, dict)

    def test_error_context_with_values(self):
        """Test creating error context with specific values."""
        timestamp = datetime.utcnow()
        context = ErrorContext(
            timestamp=timestamp,
            user_id=123,
            session_id="session_456",
            operation="test_operation",
            component="test_component"
        )

        assert context.timestamp == timestamp
        assert context.user_id == 123
        assert context.session_id == "session_456"
        assert context.operation == "test_operation"
        assert context.component == "test_component"

    def test_error_context_to_dict(self):
        """Test converting error context to dictionary."""
        context = ErrorContext(
            user_id=123,
            operation="test_op",
            additional_data={"key": "value"}
        )

        context_dict = context.to_dict()

        assert isinstance(context_dict, dict)
        assert context_dict['user_id'] == 123
        assert context_dict['operation'] == "test_op"
        assert context_dict['additional_data'] == {"key": "value"}
        assert 'timestamp' in context_dict


class TestStandardizedFABException:
    """Test the main standardized exception class."""

    def test_basic_exception_creation(self):
        """Test creating a basic standardized exception."""
        exception = StandardizedFABException("Test error message")

        assert str(exception) == "Test error message"
        assert exception.message == "Test error message"
        assert exception.category == ErrorCategory.SYSTEM
        assert exception.severity == ErrorSeverity.MEDIUM
        assert exception.recovery_action == RecoveryAction.ABORT
        assert exception.error_code.startswith("PGAF_STANDARDIZEDFAB_")
        assert exception.user_message is not None

    def test_exception_with_all_parameters(self):
        """Test creating exception with all parameters."""
        context = ErrorContext(user_id=123, operation="test")
        cause = ValueError("Original error")

        exception = StandardizedFABException(
            message="Test error",
            error_code="TEST_001",
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.RETRY,
            context=context,
            cause=cause,
            user_message="User friendly message",
            technical_details={"detail": "value"}
        )

        assert exception.message == "Test error"
        assert exception.error_code == "TEST_001"
        assert exception.category == ErrorCategory.VALIDATION
        assert exception.severity == ErrorSeverity.HIGH
        assert exception.recovery_action == RecoveryAction.RETRY
        assert exception.context == context
        assert exception.cause == cause
        assert exception.user_message == "User friendly message"
        assert exception.technical_details == {"detail": "value"}

    def test_user_message_generation(self):
        """Test automatic user message generation based on category."""
        auth_error = StandardizedFABException(
            "Auth failed",
            category=ErrorCategory.AUTHENTICATION
        )
        assert "log in" in auth_error.user_message.lower()

        validation_error = StandardizedFABException(
            "Validation failed",
            category=ErrorCategory.VALIDATION
        )
        assert "check your input" in validation_error.user_message.lower()

    @patch('pgappforge.exceptions.standardized.logger')
    def test_auto_logging(self, mock_logger):
        """Test automatic logging based on severity."""
        # Test critical severity
        StandardizedFABException(
            "Critical error",
            severity=ErrorSeverity.CRITICAL
        )
        mock_logger.critical.assert_called_once()

        # Test high severity
        mock_logger.reset_mock()
        StandardizedFABException(
            "High error",
            severity=ErrorSeverity.HIGH
        )
        mock_logger.error.assert_called_once()

        # Test medium severity
        mock_logger.reset_mock()
        StandardizedFABException(
            "Medium error",
            severity=ErrorSeverity.MEDIUM
        )
        mock_logger.warning.assert_called_once()

    def test_to_dict_serialization(self):
        """Test converting exception to dictionary."""
        exception = StandardizedFABException(
            "Test error",
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.HIGH
        )

        error_dict = exception.to_dict()

        assert isinstance(error_dict, dict)
        assert 'error' in error_dict

        error_info = error_dict['error']
        assert error_info['message'] is not None
        assert error_info['technical_message'] == "Test error"
        assert error_info['category'] == "validation"
        assert error_info['severity'] == "high"
        assert 'timestamp' in error_info

    def test_recovery_suggestions(self):
        """Test recovery suggestions generation."""
        # Authentication error
        auth_error = StandardizedFABException(
            "Auth failed",
            category=ErrorCategory.AUTHENTICATION
        )
        suggestions = auth_error.get_recovery_suggestions()
        assert any("log in" in suggestion.lower() for suggestion in suggestions)

        # Validation error
        validation_error = StandardizedFABException(
            "Validation failed",
            category=ErrorCategory.VALIDATION
        )
        suggestions = validation_error.get_recovery_suggestions()
        assert any("input" in suggestion.lower() for suggestion in suggestions)


class TestSpecificExceptionTypes:
    """Test specific exception type classes."""

    def test_authentication_error(self):
        """Test FABAuthenticationError."""
        error = FABAuthenticationError("Login failed")

        assert error.category == ErrorCategory.AUTHENTICATION
        assert error.severity == ErrorSeverity.HIGH
        assert error.recovery_action == RecoveryAction.LOGOUT_LOGIN

    def test_authorization_error(self):
        """Test FABAuthorizationError."""
        error = FABAuthorizationError("Access denied")

        assert error.category == ErrorCategory.AUTHORIZATION
        assert error.severity == ErrorSeverity.HIGH
        assert error.recovery_action == RecoveryAction.ESCALATE

    def test_validation_error(self):
        """Test FABValidationError."""
        error = FABValidationError("Invalid input", field_name="email")

        assert error.category == ErrorCategory.VALIDATION
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.recovery_action == RecoveryAction.RETRY
        assert error.context.additional_data['field_name'] == "email"

    def test_database_error(self):
        """Test FABDatabaseError."""
        error = FABDatabaseError("Connection failed")

        assert error.category == ErrorCategory.DATABASE
        assert error.severity == ErrorSeverity.HIGH
        assert error.recovery_action == RecoveryAction.RETRY

    def test_security_error(self):
        """Test FABSecurityError."""
        error = FABSecurityError("Security violation")

        assert error.category == ErrorCategory.SECURITY
        assert error.severity == ErrorSeverity.CRITICAL
        assert error.recovery_action == RecoveryAction.ABORT

    def test_api_error(self):
        """Test FABAPIError."""
        error = FABAPIError("API request failed", status_code=500)

        assert error.category == ErrorCategory.API
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.recovery_action == RecoveryAction.RETRY
        assert error.context.additional_data['status_code'] == 500


class TestErrorHandler:
    """Test the ErrorHandler utility class."""

    def test_error_handler_creation(self):
        """Test creating an ErrorHandler instance."""
        handler = ErrorHandler()

        assert handler.error_count == 0
        assert len(handler.error_history) == 0

    def test_handle_standardized_exception(self):
        """Test handling an already standardized exception."""
        handler = ErrorHandler()
        original_error = StandardizedFABException("Test error")

        result = handler.handle_exception(original_error)

        assert result is original_error
        assert handler.error_count == 1
        assert len(handler.error_history) == 1

    def test_handle_generic_exception(self):
        """Test handling a generic Python exception."""
        handler = ErrorHandler()
        original_error = ValueError("Invalid value")

        result = handler.handle_exception(original_error)

        assert isinstance(result, StandardizedFABException)
        assert result.category == ErrorCategory.VALIDATION
        assert result.cause == original_error
        assert "Invalid value" in result.message

    def test_exception_type_mapping(self):
        """Test mapping of Python exception types to error categories."""
        handler = ErrorHandler()

        # Test ValueError -> VALIDATION
        result = handler.handle_exception(ValueError("test"))
        assert result.category == ErrorCategory.VALIDATION

        # Test PermissionError -> AUTHORIZATION
        result = handler.handle_exception(PermissionError("access denied"))
        assert result.category == ErrorCategory.AUTHORIZATION

        # Test ConnectionError -> NETWORK
        result = handler.handle_exception(ConnectionError("network error"))
        assert result.category == ErrorCategory.NETWORK

    def test_error_statistics(self):
        """Test error statistics collection."""
        handler = ErrorHandler()

        # Handle various errors
        handler.handle_exception(ValueError("validation error"))
        handler.handle_exception(ConnectionError("network error"))
        handler.handle_exception(StandardizedFABException(
            "custom error",
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL
        ))

        stats = handler.get_error_stats()

        assert stats['total_errors'] == 3
        assert 'category_distribution' in stats
        assert 'severity_distribution' in stats
        assert 'recent_errors' in stats
        assert len(stats['recent_errors']) == 3


class TestErrorHandlerDecorator:
    """Test the @fab_error_handler decorator."""

    def test_decorator_basic_usage(self):
        """Test basic decorator usage."""
        @fab_error_handler()
        def test_function():
            return "success"

        result = test_function()
        assert result == "success"

    def test_decorator_catches_exceptions(self):
        """Test that decorator catches and converts exceptions."""
        @fab_error_handler(category=ErrorCategory.VALIDATION)
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(StandardizedFABException) as exc_info:
            failing_function()

        exception = exc_info.value
        assert exception.category == ErrorCategory.VALIDATION
        assert "Test error" in exception.message

    def test_decorator_with_parameters(self):
        """Test decorator with custom parameters."""
        @fab_error_handler(
            category=ErrorCategory.DATABASE,
            severity=ErrorSeverity.HIGH,
            operation="database_operation"
        )
        def db_function():
            raise ConnectionError("DB connection failed")

        with pytest.raises(StandardizedFABException) as exc_info:
            db_function()

        exception = exc_info.value
        assert exception.category == ErrorCategory.DATABASE
        assert exception.severity == ErrorSeverity.HIGH
        assert exception.context.operation == "database_operation"

    def test_decorator_preserves_function_metadata(self):
        """Test that decorator preserves function metadata."""
        @fab_error_handler()
        def documented_function():
            """This function has documentation."""
            pass

        assert documented_function.__doc__ == "This function has documentation."
        assert documented_function.__name__ == "documented_function"


class TestUtilityFunctions:
    """Test utility functions for creating specific errors."""

    def test_create_validation_error(self):
        """Test create_validation_error utility."""
        error = create_validation_error("Invalid email", field_name="email")

        assert isinstance(error, FABValidationError)
        assert error.message == "Invalid email"
        assert error.context.additional_data['field_name'] == "email"

    def test_create_security_error(self):
        """Test create_security_error utility."""
        error = create_security_error("Security violation")

        assert isinstance(error, FABSecurityError)
        assert error.message == "Security violation"
        assert error.category == ErrorCategory.SECURITY

    def test_create_database_error(self):
        """Test create_database_error utility."""
        error = create_database_error("Connection timeout")

        assert isinstance(error, FABDatabaseError)
        assert error.message == "Connection timeout"
        assert error.category == ErrorCategory.DATABASE

    def test_create_api_error(self):
        """Test create_api_error utility."""
        error = create_api_error("API request failed", status_code=500)

        assert isinstance(error, FABAPIError)
        assert error.message == "API request failed"
        assert error.context.additional_data['status_code'] == 500


class TestContextUtilities:
    """Test context utility functions."""

    @patch('pgappforge.exceptions.standardized.request')
    @patch('pgappforge.exceptions.standardized.g')
    def test_get_request_context_with_flask(self, mock_g, mock_request):
        """Test getting request context when Flask is available."""
        # Mock Flask request and g objects
        mock_request.user_agent.string = "Mozilla/5.0"
        mock_request.remote_addr = "192.168.1.1"
        mock_request.method = "POST"
        mock_request.url = "http://example.com/test"
        mock_g.request_id = "req_123"

        context = get_request_context()

        assert context.request_id == "req_123"
        assert context.client_info['user_agent'] == "Mozilla/5.0"
        assert context.client_info['remote_addr'] == "192.168.1.1"
        assert context.client_info['method'] == "POST"

    def test_get_request_context_without_flask(self):
        """Test getting request context when Flask is not available."""
        # This should not raise an exception
        context = get_request_context()
        assert isinstance(context, ErrorContext)

    def test_add_user_context(self):
        """Test adding user context information."""
        context = ErrorContext()
        context = add_user_context(context, user_id=123, session_id="session_456")

        assert context.user_id == 123
        assert context.session_id == "session_456"

    @patch('pgappforge.exceptions.standardized.current_user')
    def test_add_user_context_from_flask_login(self, mock_current_user):
        """Test adding user context from Flask-Login current_user."""
        mock_current_user.id = 789
        mock_current_user.is_authenticated = True

        context = ErrorContext()
        context = add_user_context(context)

        assert context.user_id == 789


class TestBackwardCompatibility:
    """Test backward compatibility with existing FABException usage."""

    def test_standardized_exception_is_fab_exception(self):
        """Test that StandardizedFABException is compatible with FABException."""
        from pgappforge.exceptions import FABException

        error = StandardizedFABException("Test error")

        # Should be instance of both
        assert isinstance(error, StandardizedFABException)
        assert isinstance(error, FABException)

    def test_existing_exception_handling_still_works(self):
        """Test that existing code using FABException still works."""
        from pgappforge.exceptions import FABException

        # This should work as before
        try:
            raise FABException("Old style exception")
        except FABException as e:
            assert str(e) == "Old style exception"


class TestGlobalErrorStats:
    """Test global error statistics functionality."""

    def test_get_global_error_stats(self):
        """Test getting global error statistics."""
        # Trigger some errors to generate stats
        try:
            @fab_error_handler()
            def test_func():
                raise ValueError("test")
            test_func()
        except:
            pass

        stats = get_error_stats()
        assert isinstance(stats, dict)
        assert 'total_errors' in stats


class TestIntegrationScenarios:
    """Test integration scenarios with PgAppForge components."""

    def test_view_error_handling(self):
        """Test error handling in view methods."""
        @fab_error_handler(category=ErrorCategory.API)
        def mock_view_method(self):
            # Simulate view method that might fail
            raise ValueError("Invalid request data")

        with pytest.raises(StandardizedFABException) as exc_info:
            mock_view_method(None)

        exception = exc_info.value
        assert exception.category == ErrorCategory.API
        assert "Invalid request data" in exception.message

    def test_security_error_logging(self):
        """Test that security errors are properly logged."""
        with patch('pgappforge.exceptions.standardized.logging.getLogger') as mock_get_logger:
            mock_security_logger = Mock()
            mock_get_logger.return_value = mock_security_logger

            error = FABSecurityError("Security violation")

            # Should have logged to security logger
            mock_get_logger.assert_called_with('pgappforge.security.events')

    def test_error_context_in_web_request(self):
        """Test error context collection in web request scenario."""
        context = ErrorContext(
            request_id="req_123",
            user_id=456,
            operation="user_creation",
            client_info={
                'user_agent': 'Mozilla/5.0',
                'remote_addr': '192.168.1.1'
            }
        )

        error = StandardizedFABException(
            "User creation failed",
            category=ErrorCategory.DATABASE,
            context=context
        )

        error_dict = error.to_dict()
        assert error_dict['error']['context']['request_id'] == "req_123"
        assert error_dict['error']['context']['user_id'] == 456


if __name__ == "__main__":
    pytest.main([__file__, "-v"])