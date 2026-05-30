"""
Core integration tests for collaborative utilities.

Tests the integration of collaborative utilities without external dependencies,
focusing on validation, error handling, and core functionality.
"""

import unittest
import logging
import json
from datetime import datetime
from unittest.mock import Mock, MagicMock

# Test core collaborative utilities
from pgappforge.collaborative.utils.validation import (
    ValidationResult,
    FieldValidator,
    UserValidator,
    TokenValidator,
    MessageValidator,
    DataValidator,
    validate_complete_message,
)
from pgappforge.collaborative.utils.audit_logging import (
    AuditLogger,
    AuditEvent,
    AuditEventType,
    ErrorCategory,
    ErrorSeverity,
)
from pgappforge.collaborative.utils.error_handling import (
    CollaborativeError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    ConcurrencyError,
    ErrorHandlingMixin,
    create_error_response,
    ErrorContext,
)


class MockMessage:
    """Mock message object for testing."""

    def __init__(self, message_type="test", message_id="msg_123", sender_id=1):
        self.message_type = message_type
        self.message_id = message_id
        self.sender_id = sender_id
        self.data = {"content": "test message", "priority": "normal"}
        self.timestamp = datetime.now()


class MockUser:
    """Mock user object for testing."""

    def __init__(self, user_id: int = 1, username: str = "testuser"):
        self.id = user_id
        self.username = username


class TestServiceWithMixins(ErrorHandlingMixin):
    """Test service that uses error handling mixin."""

    def __init__(self):
        super().__init__()
        self.operations_log = []

    def risky_operation(self, should_fail=False):
        """Test operation that might fail."""
        if should_fail:
            raise ValueError("Intentional test failure")
        return "success"

    def safe_operation(self, should_fail=False):
        """Test operation using safe_execute."""
        return self.safe_execute(
            self.risky_operation, should_fail=should_fail, operation="test_operation"
        )


class CoreIntegrationTest(unittest.TestCase):
    """Core integration tests for collaborative utilities."""

    def setUp(self):
        """Set up test environment."""
        self.mock_user = MockUser()
        self.mock_message = MockMessage()

        # Configure logging for tests
        logging.basicConfig(level=logging.INFO)

    def test_validation_utilities_comprehensive(self):
        """Test comprehensive validation utility integration."""

        # Test field validation patterns
        test_cases = [
            # (value, field_name, expected_valid)
            ("valid_value", "test_field", True),
            ("", "test_field", False),
            (None, "test_field", False),
            ([], "test_list", False),
            (["item"], "test_list", True),
        ]

        for value, field_name, expected_valid in test_cases:
            result = FieldValidator.validate_required_field(value, field_name)
            self.assertEqual(
                result.is_valid, expected_valid, f"Failed for value: {value}"
            )

        # Test type validation
        result = FieldValidator.validate_field_type("string", str, "test_field")
        self.assertTrue(result.is_valid)

        result = FieldValidator.validate_field_type(123, str, "test_field")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "INVALID_TYPE")

        # Test string length validation
        result = FieldValidator.validate_string_length(
            "test", min_length=2, max_length=10
        )
        self.assertTrue(result.is_valid)

        result = FieldValidator.validate_string_length("a", min_length=2)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "LENGTH_TOO_SHORT")

    def test_user_validation_integration(self):
        """Test user validation utilities."""

        # Valid user validation
        result = UserValidator.validate_user_object(self.mock_user)
        self.assertTrue(result.is_valid)

        result = UserValidator.validate_user_id(self.mock_user.id)
        self.assertTrue(result.is_valid)

        # Invalid user validation
        result = UserValidator.validate_user_object(None)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "USER_REQUIRED")

        result = UserValidator.validate_user_id(-1)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "INVALID_USER_ID_VALUE")

        result = UserValidator.validate_user_id("not_a_number")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "INVALID_USER_ID_TYPE")

    def test_token_validation_integration(self):
        """Test token validation utilities."""

        # Valid token format
        long_token = "a" * 64
        result = TokenValidator.validate_token_format(long_token)
        self.assertTrue(result.is_valid)

        # Invalid token format
        result = TokenValidator.validate_token_format("short")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "TOKEN_TOO_SHORT")

        result = TokenValidator.validate_token_format(None)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "TOKEN_REQUIRED")

        result = TokenValidator.validate_token_format(123)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "INVALID_TOKEN_TYPE")

    def test_data_validation_integration(self):
        """Test data validation utilities."""

        # JSON serializable data
        valid_data = {"key": "value", "number": 123, "list": [1, 2, 3]}
        result = DataValidator.validate_json_serializable(valid_data)
        self.assertTrue(result.is_valid)

        # Non-serializable data
        class NonSerializable:
            pass

        invalid_data = {"object": NonSerializable()}
        result = DataValidator.validate_json_serializable(invalid_data)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "DATA_NOT_SERIALIZABLE")

        # Data size validation
        small_data = {"key": "value"}
        result = DataValidator.validate_data_size(small_data, max_size_bytes=1000)
        self.assertTrue(result.is_valid)

        # Large data (simulated)
        large_data = {"key": "x" * 2000}  # Large string
        result = DataValidator.validate_data_size(large_data, max_size_bytes=1000)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "DATA_TOO_LARGE")

        # Dictionary structure validation
        data = {"required_key": "value", "optional_key": "value"}
        result = DataValidator.validate_dictionary_structure(
            data, required_keys=["required_key"], optional_keys=["optional_key"]
        )
        self.assertTrue(result.is_valid)

        # Missing required key
        incomplete_data = {"optional_key": "value"}
        result = DataValidator.validate_dictionary_structure(
            incomplete_data, required_keys=["required_key"]
        )
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "MISSING_REQUIRED_KEY")

    def test_message_validation_integration(self):
        """Test message validation utilities."""

        # Valid message
        result = MessageValidator.validate_message_base_fields(self.mock_message)
        self.assertTrue(result.is_valid)

        result = MessageValidator.validate_message_with_user(self.mock_message)
        self.assertTrue(result.is_valid)

        result = MessageValidator.validate_message_with_data(self.mock_message)
        self.assertTrue(result.is_valid)

        result = MessageValidator.validate_message_with_timestamp(self.mock_message)
        self.assertTrue(result.is_valid)

        # Comprehensive validation
        result = validate_complete_message(self.mock_message)
        self.assertTrue(result.is_valid)

        # Invalid message - missing required field
        invalid_message = MockMessage()
        delattr(invalid_message, "message_type")

        result = MessageValidator.validate_message_base_fields(invalid_message)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "MISSING_MESSAGE_FIELD")

    def test_error_handling_integration(self):
        """Test error handling utilities integration."""

        # Test basic error creation
        error = ValidationError(
            "Test validation error",
            field_name="test_field",
            field_value="invalid_value",
        )

        self.assertEqual(error.error_code, "VALIDATION")
        self.assertEqual(error.category, ErrorCategory.VALIDATION)
        self.assertEqual(error.severity, ErrorSeverity.LOW)
        self.assertEqual(error.field_name, "test_field")
        self.assertEqual(error.field_value, "invalid_value")

        # Test error response creation
        response = create_error_response(error)
        self.assertTrue(response["error"])
        self.assertEqual(response["error_code"], "VALIDATION")
        self.assertEqual(response["category"], "validation")
        self.assertTrue(response["recoverable"])

        # Test debug response
        debug_response = create_error_response(error, include_debug=True)
        self.assertIn("debug_message", debug_response)
        self.assertIn("context", debug_response)

        # Test different error types
        auth_error = AuthenticationError("Login failed")
        self.assertEqual(auth_error.category, ErrorCategory.AUTHENTICATION)
        self.assertFalse(auth_error.recoverable)

        authz_error = AuthorizationError("Access denied", required_permission="admin")
        self.assertEqual(authz_error.required_permission, "admin")

        concurrency_error = ConcurrencyError(
            "Version conflict", conflict_type="optimistic_lock"
        )
        self.assertEqual(concurrency_error.conflict_type, "optimistic_lock")
        self.assertTrue(concurrency_error.recoverable)

    def test_error_handling_mixin_integration(self):
        """Test error handling mixin functionality."""

        service = TestServiceWithMixins()

        # Test successful operation
        result = service.safe_operation(should_fail=False)
        self.assertEqual(result, "success")

        # Test error handling
        with self.assertRaises(ValidationError):
            service.safe_operation(should_fail=True)

        # Test error context setting
        service.set_error_context(
            user_id=123, session_id="test_session", operation="test_op"
        )

        self.assertIsNotNone(service._error_context)
        self.assertEqual(service._error_context.user_id, 123)
        self.assertEqual(service._error_context.session_id, "test_session")

        # Test error conversion
        try:
            raise ValueError("Test error")
        except Exception as e:
            collaborative_error = service.handle_error(e, log_error=False)
            self.assertIsInstance(collaborative_error, ValidationError)
            self.assertEqual(collaborative_error.cause, e)

    def test_audit_logging_structure(self):
        """Test audit logging data structures and basic functionality."""

        # Test audit event creation
        event = AuditEvent(
            event_type=AuditEventType.USER_LOGIN,
            timestamp=datetime.now(),
            user_id=123,
            session_id="test_session",
            details={"login_method": "password"},
        )

        # Test event serialization
        event_dict = event.to_dict()
        self.assertEqual(event_dict["event_type"], "user_login")
        self.assertEqual(event_dict["user_id"], 123)
        self.assertEqual(event_dict["session_id"], "test_session")

        event_json = event.to_json()
        parsed = json.loads(event_json)
        self.assertEqual(parsed["event_type"], "user_login")

    def test_comprehensive_workflow_integration(self):
        """Test a comprehensive workflow using multiple utilities."""

        class WorkflowProcessor(ErrorHandlingMixin):
            def __init__(self):
                super().__init__()
                self.processed_messages = []

            def process_user_message(self, user, message):
                """Process a user message with full validation and error handling."""

                # Set error context
                self.set_error_context(
                    user_id=user.id, operation="process_user_message"
                )

                # Validate user
                user_result = UserValidator.validate_user_object(user)
                if not user_result.is_valid:
                    raise ValidationError(user_result.error_message)

                # Validate message
                message_result = validate_complete_message(message)
                if not message_result.is_valid:
                    raise ValidationError(message_result.error_message)

                # Process message (simulate)
                processed = {
                    "user_id": user.id,
                    "message_id": message.message_id,
                    "processed_at": datetime.now().isoformat(),
                    "content_length": len(json.dumps(message.data)),
                }

                self.processed_messages.append(processed)
                return processed

        # Test the workflow
        processor = WorkflowProcessor()

        # Valid processing
        result = processor.process_user_message(self.mock_user, self.mock_message)
        self.assertEqual(result["user_id"], self.mock_user.id)
        self.assertEqual(result["message_id"], self.mock_message.message_id)
        self.assertEqual(len(processor.processed_messages), 1)

        # Invalid user processing
        with self.assertRaises(ValidationError):
            processor.process_user_message(None, self.mock_message)

        # Invalid message processing
        invalid_message = MockMessage()
        invalid_message.message_type = None

        with self.assertRaises(ValidationError):
            processor.process_user_message(self.mock_user, invalid_message)

        # Verify processing count didn't increase for invalid cases
        self.assertEqual(len(processor.processed_messages), 1)

    def test_import_structure_validation(self):
        """Test that all imports work correctly and modules are structured properly."""

        # Test that we can import all main utilities
        from pgappforge.collaborative.utils import (
            ValidationResult,
            FieldValidator,
            UserValidator,
            AuditLogger,
            AuditEventType,
            CollaborativeError,
            ErrorHandlingMixin,
        )

        # Test that classes are properly instantiable
        result = ValidationResult.success()
        self.assertTrue(result.is_valid)

        error = CollaborativeError("Test error")
        self.assertIsInstance(error, Exception)

        # Test that enums work properly
        self.assertEqual(AuditEventType.USER_LOGIN.value, "user_login")

        print("✅ All core integration tests passed!")


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
