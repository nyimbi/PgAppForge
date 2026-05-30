"""
Shared error handling utilities for collaborative features.

Provides standardized exception classes, error handling mixins, and
consistent error response patterns across all collaborative modules.
"""

import logging
import traceback
from typing import Dict, Any, Optional, List, Union, Type
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime


logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error category classifications."""

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    CONCURRENCY = "concurrency"
    NETWORK = "network"
    DATABASE = "database"
    CONFIGURATION = "configuration"
    BUSINESS_LOGIC = "business_logic"
    SYSTEM = "system"
    EXTERNAL_SERVICE = "external_service"


@dataclass
class ErrorContext:
    """Error context information."""

    timestamp: datetime
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    operation: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert error context to dictionary."""
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        return result


class CollaborativeError(Exception):
    """
    Base exception class for all collaborative feature errors.

    Provides structured error information with context, categorization,
    and consistent error handling patterns.
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        category: ErrorCategory = ErrorCategory.SYSTEM,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
        recoverable: bool = True,
        user_message: Optional[str] = None,
    ):
        """
        Initialize collaborative error.

        Args:
            message: Technical error message for logging
            error_code: Unique error code for identification
            category: Error category classification
            severity: Error severity level
            context: Error context information
            cause: Underlying exception that caused this error
            recoverable: Whether the error is potentially recoverable
            user_message: User-friendly error message for display
        """
        super().__init__(message)

        self.message = message
        self.error_code = error_code or self._generate_error_code()
        self.category = category
        self.severity = severity
        self.context = context or ErrorContext(timestamp=datetime.now())
        self.cause = cause
        self.recoverable = recoverable
        self.user_message = user_message or self._generate_user_message()

        # Capture stack trace
        self.stack_trace = traceback.format_exc()

    def _generate_error_code(self) -> str:
        """Generate default error code based on class name."""
        class_name = self.__class__.__name__
        # Convert CamelCase to UPPER_SNAKE_CASE
        import re

        error_code = re.sub("([a-z0-9])([A-Z])", r"\1_\2", class_name).upper()
        return error_code.replace("_ERROR", "")

    def _generate_user_message(self) -> str:
        """Generate user-friendly error message."""
        if self.category == ErrorCategory.VALIDATION:
            return "Please check your input and try again."
        elif self.category == ErrorCategory.AUTHENTICATION:
            return "Please log in to continue."
        elif self.category == ErrorCategory.AUTHORIZATION:
            return "You don't have permission to perform this action."
        elif self.category == ErrorCategory.NETWORK:
            return "Network connection issue. Please try again."
        elif self.category == ErrorCategory.DATABASE:
            return "Data storage issue. Please try again later."
        else:
            return "An unexpected error occurred. Please try again later."

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary representation."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "user_message": self.user_message,
            "category": self.category.value,
            "severity": self.severity.value,
            "recoverable": self.recoverable,
            "context": self.context.to_dict() if self.context else None,
            "cause": str(self.cause) if self.cause else None,
            "stack_trace": self.stack_trace
            if logger.isEnabledFor(logging.DEBUG)
            else None,
        }

    def log_error(self, logger_instance: Optional[logging.Logger] = None) -> None:
        """Log the error with appropriate level based on severity."""
        log = logger_instance or logger

        log_level_map = {
            ErrorSeverity.LOW: logging.INFO,
            ErrorSeverity.MEDIUM: logging.WARNING,
            ErrorSeverity.HIGH: logging.ERROR,
            ErrorSeverity.CRITICAL: logging.CRITICAL,
        }

        log_level = log_level_map.get(self.severity, logging.ERROR)

        log_message = f"{self.error_code}: {self.message}"
        if self.context and self.context.user_id:
            log_message += f" | User: {self.context.user_id}"
        if self.context and self.context.operation:
            log_message += f" | Operation: {self.context.operation}"

        extra_data = {
            "error_code": self.error_code,
            "error_category": self.category.value,
            "error_severity": self.severity.value,
            "error_context": self.context.to_dict() if self.context else None,
        }

        log.log(log_level, log_message, extra=extra_data, exc_info=self.cause)


class ValidationError(CollaborativeError):
    """Error raised when data validation fails."""

    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        **kwargs,
    ):
        """
        Initialize validation error.

        Args:
            message: Validation error message
            field_name: Name of the field that failed validation
            field_value: Value that failed validation
            **kwargs: Additional error parameters
        """
        super().__init__(
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            **kwargs,
        )

        self.field_name = field_name
        self.field_value = field_value

        # Add field information to context
        if self.context and self.context.additional_data is None:
            self.context.additional_data = {}
        if self.context and self.context.additional_data is not None:
            self.context.additional_data.update(
                {
                    "field_name": field_name,
                    "field_value": str(field_value)
                    if field_value is not None
                    else None,
                }
            )


class AuthenticationError(CollaborativeError):
    """Error raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.HIGH,
            recoverable=False,
            user_message="Please log in to continue.",
            **kwargs,
        )


class AuthorizationError(CollaborativeError):
    """Error raised when authorization fails."""

    def __init__(
        self,
        message: str = "Access denied",
        required_permission: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.HIGH,
            recoverable=False,
            user_message="You don't have permission to perform this action.",
            **kwargs,
        )

        self.required_permission = required_permission

        # Add permission information to context
        if self.context and self.context.additional_data is None:
            self.context.additional_data = {}
        if self.context and self.context.additional_data is not None:
            self.context.additional_data["required_permission"] = required_permission


class ConcurrencyError(CollaborativeError):
    """Error raised when concurrency conflicts occur."""

    def __init__(
        self,
        message: str = "Concurrency conflict detected",
        conflict_type: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ErrorCategory.CONCURRENCY,
            severity=ErrorSeverity.MEDIUM,
            recoverable=True,
            user_message="Another user modified this data. Please refresh and try again.",
            **kwargs,
        )

        self.conflict_type = conflict_type

        # Add conflict information to context
        if self.context and self.context.additional_data is None:
            self.context.additional_data = {}
        if self.context and self.context.additional_data is not None:
            self.context.additional_data["conflict_type"] = conflict_type


class NetworkError(CollaborativeError):
    """Error raised when network operations fail."""

    def __init__(
        self,
        message: str = "Network operation failed",
        endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.MEDIUM,
            recoverable=True,
            user_message="Network connection issue. Please try again.",
            **kwargs,
        )

        self.endpoint = endpoint
        self.status_code = status_code

        # Add network information to context
        if self.context and self.context.additional_data is None:
            self.context.additional_data = {}
        if self.context and self.context.additional_data is not None:
            self.context.additional_data.update(
                {"endpoint": endpoint, "status_code": status_code}
            )


class DatabaseError(CollaborativeError):
    """Error raised when database operations fail."""

    def __init__(
        self,
        message: str = "Database operation failed",
        operation: Optional[str] = None,
        table: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ErrorCategory.DATABASE,
            severity=ErrorSeverity.HIGH,
            recoverable=True,
            user_message="Data storage issue. Please try again later.",
            **kwargs,
        )

        self.operation = operation
        self.table = table

        # Add database information to context
        if self.context and self.context.additional_data is None:
            self.context.additional_data = {}
        if self.context and self.context.additional_data is not None:
            self.context.additional_data.update(
                {"db_operation": operation, "db_table": table}
            )


class ConfigurationError(CollaborativeError):
    """Error raised when configuration is invalid."""

    def __init__(
        self,
        message: str = "Configuration error",
        config_key: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.CRITICAL,
            recoverable=False,
            user_message="System configuration issue. Please contact support.",
            **kwargs,
        )

        self.config_key = config_key

        # Add configuration information to context
        if self.context and self.context.additional_data is None:
            self.context.additional_data = {}
        if self.context and self.context.additional_data is not None:
            self.context.additional_data["config_key"] = config_key


class ExternalServiceError(CollaborativeError):
    """Error raised when external service calls fail."""

    def __init__(
        self,
        message: str = "External service error",
        service_name: Optional[str] = None,
        service_endpoint: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            category=ErrorCategory.EXTERNAL_SERVICE,
            severity=ErrorSeverity.MEDIUM,
            recoverable=True,
            user_message="External service unavailable. Please try again later.",
            **kwargs,
        )

        self.service_name = service_name
        self.service_endpoint = service_endpoint

        # Add service information to context
        if self.context and self.context.additional_data is None:
            self.context.additional_data = {}
        if self.context and self.context.additional_data is not None:
            self.context.additional_data.update(
                {"service_name": service_name, "service_endpoint": service_endpoint}
            )


class ErrorHandlingMixin:
    """
    Mixin class for adding consistent error handling capabilities.

    Provides standardized error handling methods that can be mixed into any
    collaborative service class.
    """

    def __init__(self, *args, **kwargs):
        """Initialize error handling mixin."""
        super().__init__(*args, **kwargs)
        self._error_context: Optional[ErrorContext] = None

    def set_error_context(
        self,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        operation: Optional[str] = None,
        **kwargs,
    ) -> None:
        """
        Set error context for subsequent error handling.

        Args:
            user_id: Current user ID
            session_id: Current session ID
            request_id: Current request ID
            operation: Current operation name
            **kwargs: Additional context data
        """
        self._error_context = ErrorContext(
            timestamp=datetime.now(),
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            operation=operation,
            additional_data=kwargs if kwargs else None,
        )

    def handle_error(
        self, error: Exception, operation: Optional[str] = None, log_error: bool = True
    ) -> CollaborativeError:
        """
        Convert and handle any exception as a CollaborativeError.

        Args:
            error: Exception to handle
            operation: Operation that caused the error
            log_error: Whether to log the error

        Returns:
            CollaborativeError instance
        """
        # If already a CollaborativeError, update context and return
        if isinstance(error, CollaborativeError):
            if operation and self._error_context:
                error.context.operation = operation
            if log_error:
                error.log_error()
            return error

        # Convert other exceptions to appropriate CollaborativeError
        collaborative_error = self._convert_exception(error, operation)

        if log_error:
            collaborative_error.log_error()

        return collaborative_error

    def _convert_exception(
        self, error: Exception, operation: Optional[str] = None
    ) -> CollaborativeError:
        """
        Convert generic exception to appropriate CollaborativeError.

        Args:
            error: Exception to convert
            operation: Operation that caused the error

        Returns:
            CollaborativeError instance
        """
        error_message = str(error)
        error_context = self._error_context or ErrorContext(timestamp=datetime.now())

        if operation:
            error_context.operation = operation

        # Classify error based on type and message
        if isinstance(error, (ValueError, TypeError)):
            return ValidationError(
                message=error_message, context=error_context, cause=error
            )
        elif isinstance(error, PermissionError):
            return AuthorizationError(
                message=error_message, context=error_context, cause=error
            )
        elif isinstance(error, ConnectionError):
            return NetworkError(
                message=error_message, context=error_context, cause=error
            )
        elif "database" in error_message.lower() or "sql" in error_message.lower():
            return DatabaseError(
                message=error_message, context=error_context, cause=error
            )
        elif "deadlock" in error_message.lower() or "lock" in error_message.lower():
            return ConcurrencyError(
                message=error_message,
                conflict_type="database_lock",
                context=error_context,
                cause=error,
            )
        else:
            # Generic system error
            return CollaborativeError(
                message=error_message,
                category=ErrorCategory.SYSTEM,
                severity=ErrorSeverity.MEDIUM,
                context=error_context,
                cause=error,
            )

    def safe_execute(
        self, func, *args, operation: Optional[str] = None, **kwargs
    ) -> Any:
        """
        Safely execute a function with error handling.

        Args:
            func: Function to execute
            *args: Function arguments
            operation: Operation name for error context
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CollaborativeError: If function execution fails
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            raise self.handle_error(e, operation=operation)

    def validate_and_execute(
        self,
        validation_func,
        execution_func,
        *args,
        operation: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """
        Validate input and execute function with error handling.

        Args:
            validation_func: Function to validate inputs
            execution_func: Function to execute after validation
            *args: Function arguments
            operation: Operation name for error context
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CollaborativeError: If validation or execution fails
        """
        try:
            # Validate inputs
            validation_result = validation_func(*args, **kwargs)
            if (
                hasattr(validation_result, "is_valid")
                and not validation_result.is_valid
            ):
                raise ValidationError(
                    message=validation_result.error_message or "Validation failed",
                    context=self._error_context,
                )

            # Execute function
            return execution_func(*args, **kwargs)

        except Exception as e:
            raise self.handle_error(e, operation=operation)


# Utility functions for error handling
def create_error_response(
    error: CollaborativeError, include_debug: bool = False
) -> Dict[str, Any]:
    """
    Create standardized error response dictionary.

    Args:
        error: CollaborativeError to convert to response
        include_debug: Whether to include debug information

    Returns:
        Error response dictionary
    """
    response = {
        "error": True,
        "error_code": error.error_code,
        "message": error.user_message,
        "category": error.category.value,
        "severity": error.severity.value,
        "recoverable": error.recoverable,
    }

    if include_debug:
        response.update(
            {
                "debug_message": error.message,
                "context": error.context.to_dict() if error.context else None,
                "stack_trace": error.stack_trace,
            }
        )

    return response


def log_error_with_context(
    error: Exception,
    logger_instance: logging.Logger,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log error with additional context information.

    Args:
        error: Exception to log
        logger_instance: Logger instance to use
        context: Additional context information
    """
    if isinstance(error, CollaborativeError):
        error.log_error(logger_instance)
    else:
        extra_data = {"error_context": context} if context else {}
        logger_instance.error(
            f"Unhandled error: {str(error)}", extra=extra_data, exc_info=True
        )
