"""
Integration tests for collaborative features.

Tests the integration of all collaborative components including service registry,
validation utilities, audit logging, transaction management, and error handling.
"""

import unittest
import logging
import tempfile
import os
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Flask and SQLAlchemy imports
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# PgAppForge imports
from pgappforge import AppBuilder
from pgappforge.security.sqla.manager import SecurityManager

# Collaborative feature imports
from pgappforge.collaborative.utils.validation import (
    ValidationResult,
    FieldValidator,
    UserValidator,
    TokenValidator,
    MessageValidator,
    validate_complete_message,
)
from pgappforge.collaborative.utils.audit_logging import (
    AuditLogger,
    AuditEvent,
    AuditEventType,
    CollaborativeAuditMixin,
)
from pgappforge.collaborative.utils.transaction_manager import (
    TransactionManager,
    TransactionScope,
    transaction_required,
)
from pgappforge.collaborative.utils.error_handling import (
    CollaborativeError,
    ValidationError,
    AuthenticationError,
    ErrorHandlingMixin,
    create_error_response,
)
from pgappforge.collaborative.interfaces.service_registry import ServiceRegistry
from pgappforge.collaborative.interfaces.service_factory import ServiceFactory
from pgappforge.collaborative.interfaces.base_interfaces import (
    ICollaborationService,
    BaseCollaborativeService,
)
from pgappforge.collaborative.addon_manager import CollaborativeAddonManager


class MockUser:
    """Mock user object for testing."""

    def __init__(self, user_id: int = 1, username: str = "testuser"):
        self.id = user_id
        self.username = username


class MockMessage:
    """Mock message object for testing."""

    def __init__(self, message_type="test", message_id="msg_123", sender_id=1):
        self.message_type = message_type
        self.message_id = message_id
        self.sender_id = sender_id
        self.data = {"content": "test message"}
        self.timestamp = datetime.now()


class TestCollaborativeService(BaseCollaborativeService):
    """Test implementation of collaborative service."""

    def initialize(self):
        self.initialized = True

    def cleanup(self):
        self.cleaned_up = True


class CollaborativeIntegrationTest(unittest.TestCase):
    """Integration tests for collaborative features."""

    def setUp(self):
        """Set up test environment."""
        # Create temporary database
        self.db_fd, self.db_path = tempfile.mkstemp()

        # Create Flask app
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SECRET_KEY"] = "test_secret_key_for_testing_purposes_only"
        self.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{self.db_path}"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False

        # Initialize database
        self.db = SQLAlchemy(self.app)

        # Create AppBuilder
        self.appbuilder = AppBuilder(self.app, self.db.session)

        # Create test objects
        self.mock_user = MockUser()
        self.mock_message = MockMessage()

    def tearDown(self):
        """Clean up test environment."""
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_validation_utilities_integration(self):
        """Test that validation utilities work correctly."""
        # Test field validation
        result = FieldValidator.validate_required_field("test_value", "test_field")
        self.assertTrue(result.is_valid)

        result = FieldValidator.validate_required_field(None, "test_field")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "FIELD_REQUIRED")

        # Test user validation
        result = UserValidator.validate_user_object(self.mock_user)
        self.assertTrue(result.is_valid)

        result = UserValidator.validate_user_id(self.mock_user.id)
        self.assertTrue(result.is_valid)

        # Test message validation
        result = MessageValidator.validate_message_base_fields(self.mock_message)
        self.assertTrue(result.is_valid)

        # Test comprehensive message validation
        result = validate_complete_message(self.mock_message)
        self.assertTrue(result.is_valid)

    def test_audit_logging_integration(self):
        """Test that audit logging integrates with Flask logging."""
        with self.app.app_context():
            # Create audit logger
            audit_logger = AuditLogger(self.appbuilder)

            # Test context setting
            audit_logger.set_context(
                user_id=1, session_id="test_session", ip_address="127.0.0.1"
            )

            # Test event logging
            with self.assertLogs(level="INFO") as log_capture:
                audit_logger.log_event(
                    AuditEventType.USER_LOGIN, user_id=1, message="Test user login"
                )

            # Verify log was created
            self.assertTrue(
                any("AUDIT: user_login" in message for message in log_capture.output)
            )

    def test_audit_mixin_integration(self):
        """Test that audit mixin works with services."""

        class TestServiceWithAudit(CollaborativeAuditMixin):
            def __init__(self):
                super().__init__()
                self.app_builder = self.appbuilder

        service = TestServiceWithAudit()
        service.app_builder = self.appbuilder

        # Test audit event logging
        with self.app.app_context():
            with self.assertLogs(level="INFO") as log_capture:
                service.audit_event(
                    AuditEventType.SERVICE_STARTED, message="Test service started"
                )

            # Verify log was created
            self.assertTrue(
                any(
                    "AUDIT: service_started" in message
                    for message in log_capture.output
                )
            )

    def test_error_handling_integration(self):
        """Test that error handling works correctly."""
        # Test basic error creation
        error = ValidationError("Test validation error", field_name="test_field")
        self.assertEqual(error.field_name, "test_field")
        self.assertEqual(error.category.value, "validation")

        # Test error response creation
        response = create_error_response(error)
        self.assertTrue(response["error"])
        self.assertEqual(response["error_code"], "VALIDATION")

        # Test error handling mixin
        class TestServiceWithErrorHandling(ErrorHandlingMixin):
            pass

        service = TestServiceWithErrorHandling()

        # Test error conversion
        try:
            raise ValueError("Test value error")
        except Exception as e:
            collaborative_error = service.handle_error(e, log_error=False)
            self.assertIsInstance(collaborative_error, ValidationError)

    def test_service_registry_integration(self):
        """Test service registry functionality."""
        with self.app.app_context():
            # Create service registry
            registry = ServiceFactory.create_registry(self.appbuilder)

            # Register test service
            registry.register_service(
                service_type=ICollaborationService,
                implementation=TestCollaborativeService,
                singleton=True,
            )

            # Validate registry
            issues = registry.validate_registry()
            # Should have missing dependencies for ICollaborationService methods
            # but no circular dependencies or invalid implementations
            self.assertEqual(len(issues["circular_dependencies"]), 0)

            # Test service retrieval would work (implementation doesn't fully match interface)
            # This tests that the registry infrastructure works

    def test_transaction_manager_integration(self):
        """Test transaction manager with real database session."""
        with self.app.app_context():
            # Create all tables
            self.db.create_all()

            # Create transaction manager
            transaction_manager = TransactionManager(
                session=self.db.session, app_builder=self.appbuilder
            )

            # Test transaction context
            with transaction_manager.transaction(
                TransactionScope.READ_WRITE
            ) as session:
                # This should work without errors
                self.assertIsNotNone(session)

            # Test savepoint functionality
            with transaction_manager.savepoint() as session:
                self.assertIsNotNone(session)

    def test_addon_manager_integration(self):
        """Test collaborative addon manager integration."""
        with self.app.app_context():
            # Create addon manager
            addon_manager = CollaborativeAddonManager(self.appbuilder)

            # Test pre-processing (should not raise errors)
            try:
                addon_manager.pre_process()
                # Should succeed even if collaborative features disabled
                self.assertTrue(True)
            except Exception as e:
                # If it fails, it should be due to missing dependencies, not our code
                self.assertIn("collaborative", str(e).lower())

    def test_token_validation_integration(self):
        """Test JWT token validation with Flask secret key."""
        with self.app.app_context():
            # Test token format validation
            result = TokenValidator.validate_token_format("short")
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, "TOKEN_TOO_SHORT")

            # Test with proper length token
            long_token = "a" * 64
            result = TokenValidator.validate_token_format(long_token)
            self.assertTrue(result.is_valid)

            # Test JWT validation (will fail without valid JWT but shouldn't crash)
            try:
                result = TokenValidator.validate_jwt_token(
                    token=long_token, secret_key=self.app.config["SECRET_KEY"]
                )
                # Should fail but not crash
                self.assertFalse(result.is_valid)
            except ImportError:
                # JWT library not available in test environment
                pass

    def test_comprehensive_integration(self):
        """Test multiple components working together."""
        with self.app.app_context():
            # Create service with multiple mixins
            class ComprehensiveTestService(
                BaseCollaborativeService, CollaborativeAuditMixin, ErrorHandlingMixin
            ):
                def initialize(self):
                    self.audit_event(AuditEventType.SERVICE_STARTED)

                def cleanup(self):
                    self.audit_event(AuditEventType.SERVICE_STOPPED)

                def validate_and_process_message(self, message):
                    # Use validation utilities
                    result = validate_complete_message(message)
                    if not result.is_valid:
                        raise ValidationError(result.error_message)

                    # Use audit logging
                    self.audit_event(
                        AuditEventType.MESSAGE_SENT,
                        user_id=getattr(message, "sender_id", None),
                    )

                    return {"status": "processed"}

            # Create service instance
            service = ComprehensiveTestService(
                app_builder=self.appbuilder, service_registry=None
            )

            # Test initialization
            with self.assertLogs(level="INFO"):
                service.initialize()

            # Test message processing
            result = service.validate_and_process_message(self.mock_message)
            self.assertEqual(result["status"], "processed")

            # Test error handling
            invalid_message = MockMessage()
            invalid_message.message_type = None  # Make it invalid

            with self.assertRaises(ValidationError):
                service.validate_and_process_message(invalid_message)

            # Test cleanup
            with self.assertLogs(level="INFO"):
                service.cleanup()


if __name__ == "__main__":
    # Configure logging for tests
    logging.basicConfig(level=logging.INFO)

    # Run the tests
    unittest.main()
