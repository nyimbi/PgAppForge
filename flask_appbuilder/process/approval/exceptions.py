"""
Comprehensive Exception Hierarchy for Approval Workflows

Standardized exception handling system with structured error context,
categorization, logging integration, and recovery mechanisms.
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels for categorization and response."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for systematic handling."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    DATABASE = "database"
    NETWORK = "network"
    CONFIGURATION = "configuration"
    BUSINESS_LOGIC = "business_logic"
    PERFORMANCE = "performance"
    SECURITY = "security"
    INTEGRATION = "integration"
    SYSTEM = "system"


class RecoveryAction(Enum):
    """Suggested recovery actions for different error types."""
    RETRY = "retry"
    ESCALATE = "escalate"
    FALLBACK = "fallback"
    ABORT = "abort"
    IGNORE = "ignore"
    MANUAL_INTERVENTION = "manual_intervention"


@dataclass
class ErrorContext:
    """Structured error context information."""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    operation: Optional[str] = None
    resource_id: Optional[str] = None
    component: Optional[str] = None
    correlation_id: Optional[str] = None
    additional_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'request_id': self.request_id,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'operation': self.operation,
            'resource_id': self.resource_id,
            'component': self.component,
            'correlation_id': self.correlation_id,
            'additional_data': self.additional_data
        }


class ApprovalError(Exception):
    """
    Base exception class for all approval workflow errors.
    
    Provides structured error information, categorization, and recovery guidance.
    """
    
    def __init__(self, 
                 message: str,
                 error_code: Optional[str] = None,
                 category: ErrorCategory = ErrorCategory.SYSTEM,
                 severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                 recovery_action: RecoveryAction = RecoveryAction.ABORT,
                 context: Optional[ErrorContext] = None,
                 cause: Optional[Exception] = None,
                 user_message: Optional[str] = None):
        """
        Initialize approval error.
        
        Args:
            message: Technical error message for developers
            error_code: Unique error code for tracking
            category: Error category for systematic handling
            severity: Error severity level
            recovery_action: Suggested recovery action
            context: Additional error context
            cause: Original exception that caused this error
            user_message: User-friendly error message
        """
        super().__init__(message)
        
        self.message = message
        self.error_code = error_code or self._generate_error_code()
        self.category = category
        self.severity = severity
        self.recovery_action = recovery_action
        self.context = context or ErrorContext()
        self.cause = cause
        self.user_message = user_message or self._generate_user_message()
        
        # Auto-log based on severity
        self._auto_log()
    
    def _generate_error_code(self) -> str:
        """Generate unique error code based on class name."""
        class_name = self.__class__.__name__
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{class_name.upper()}_{timestamp}"
    
    def _generate_user_message(self) -> str:
        """Generate user-friendly error message."""
        if self.category == ErrorCategory.AUTHENTICATION:
            return "Authentication required. Please log in and try again."
        elif self.category == ErrorCategory.AUTHORIZATION:
            return "You don't have permission to perform this action."
        elif self.category == ErrorCategory.VALIDATION:
            return "The provided information is invalid. Please check and try again."
        elif self.category == ErrorCategory.DATABASE:
            return "A database error occurred. Please try again later."
        elif self.category == ErrorCategory.NETWORK:
            return "A network error occurred. Please check your connection and try again."
        elif self.category == ErrorCategory.CONFIGURATION:
            return "A configuration error was detected. Please contact support."
        elif self.category == ErrorCategory.BUSINESS_LOGIC:
            return "This operation cannot be completed due to business rules."
        elif self.category == ErrorCategory.PERFORMANCE:
            return "The request is taking too long. Please try again later."
        elif self.category == ErrorCategory.SECURITY:
            return "A security issue was detected. Access has been denied."
        elif self.category == ErrorCategory.INTEGRATION:
            return "An integration error occurred. Please try again later."
        else:
            return "An unexpected error occurred. Please try again later."
    
    def _auto_log(self):
        """Automatically log error based on severity."""
        log_message = f"[{self.error_code}] {self.message}"
        
        if self.context:
            log_message += f" | Context: {self.context.to_dict()}"
        
        if self.cause:
            log_message += f" | Caused by: {str(self.cause)}"
        
        if self.severity == ErrorSeverity.CRITICAL:
            log.critical(log_message, exc_info=True)
        elif self.severity == ErrorSeverity.HIGH:
            log.error(log_message)
        elif self.severity == ErrorSeverity.MEDIUM:
            log.warning(log_message)
        else:
            log.info(log_message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            'error': {
                'code': self.error_code,
                'message': self.user_message,
                'technical_message': self.message,
                'category': self.category.value,
                'severity': self.severity.value,
                'recovery_action': self.recovery_action.value,
                'timestamp': self.context.timestamp.isoformat(),
                'context': self.context.to_dict() if self.context else None
            }
        }
    
    def should_retry(self) -> bool:
        """Check if operation should be retried."""
        return self.recovery_action == RecoveryAction.RETRY
    
    def is_recoverable(self) -> bool:
        """Check if error is recoverable."""
        return self.recovery_action in [
            RecoveryAction.RETRY,
            RecoveryAction.FALLBACK,
            RecoveryAction.ESCALATE
        ]


# Authentication and Authorization Errors
class AuthenticationError(ApprovalError):
    """Authentication-related errors."""
    
    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.ABORT,
            **kwargs
        )


class AuthorizationError(ApprovalError):
    """Authorization-related errors."""
    
    def __init__(self, message: str = "Access denied", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.ABORT,
            **kwargs
        )


class PermissionDeniedError(AuthorizationError):
    """Specific permission denied error."""
    
    def __init__(self, resource: str, action: str, **kwargs):
        message = f"Permission denied for {action} on {resource}"
        super().__init__(message=message, **kwargs)


# Validation Errors
class ValidationError(ApprovalError):
    """Data validation errors."""
    
    def __init__(self, message: str = "Validation failed", 
                 field: Optional[str] = None,
                 value: Optional[Any] = None,
                 errors: Optional[List[str]] = None,
                 **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            recovery_action=RecoveryAction.ABORT,
            **kwargs
        )
        self.field = field
        self.value = value
        self.errors = errors or []


class RequiredFieldError(ValidationError):
    """Required field missing error."""
    
    def __init__(self, field: str, **kwargs):
        message = f"Required field '{field}' is missing"
        super().__init__(message=message, field=field, **kwargs)


class InvalidFormatError(ValidationError):
    """Invalid format error."""
    
    def __init__(self, field: str, expected_format: str, **kwargs):
        message = f"Field '{field}' has invalid format. Expected: {expected_format}"
        super().__init__(message=message, field=field, **kwargs)


class ValueOutOfRangeError(ValidationError):
    """Value out of range error."""
    
    def __init__(self, field: str, value: Any, min_value: Any = None, max_value: Any = None, **kwargs):
        message = f"Field '{field}' value {value} is out of range"
        if min_value is not None and max_value is not None:
            message += f" (valid range: {min_value}-{max_value})"
        super().__init__(message=message, field=field, value=value, **kwargs)


# Database Errors
class DatabaseError(ApprovalError):
    """Database operation errors."""
    
    def __init__(self, message: str = "Database error occurred", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.DATABASE,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )


class ConnectionError(DatabaseError):
    """Database connection errors."""
    
    def __init__(self, message: str = "Database connection failed", **kwargs):
        super().__init__(
            message=message,
            severity=ErrorSeverity.CRITICAL,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )


class TransactionError(DatabaseError):
    """Database transaction errors."""
    
    def __init__(self, message: str = "Database transaction failed", **kwargs):
        super().__init__(
            message=message,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )


class ConstraintViolationError(DatabaseError):
    """Database constraint violation errors."""
    
    def __init__(self, constraint: str, **kwargs):
        message = f"Database constraint violation: {constraint}"
        super().__init__(
            message=message,
            severity=ErrorSeverity.MEDIUM,
            recovery_action=RecoveryAction.ABORT,
            **kwargs
        )


# Business Logic Errors
class BusinessLogicError(ApprovalError):
    """Business rule and logic errors."""
    
    def __init__(self, message: str = "Business rule violation", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.BUSINESS_LOGIC,
            severity=ErrorSeverity.MEDIUM,
            recovery_action=RecoveryAction.ABORT,
            **kwargs
        )


class WorkflowError(BusinessLogicError):
    """Workflow-specific errors."""
    
    def __init__(self, workflow_id: str, step: int, message: str, **kwargs):
        full_message = f"Workflow {workflow_id} step {step}: {message}"
        super().__init__(message=full_message, **kwargs)
        self.workflow_id = workflow_id
        self.step = step


class ApprovalNotAllowedError(BusinessLogicError):
    """Approval not allowed error."""
    
    def __init__(self, reason: str, **kwargs):
        message = f"Approval not allowed: {reason}"
        super().__init__(message=message, **kwargs)


class SelfApprovalError(BusinessLogicError):
    """Self-approval attempt error."""
    
    def __init__(self, user_id: int, **kwargs):
        message = f"User {user_id} cannot approve their own request"
        super().__init__(message=message, **kwargs)


class DuplicateApprovalError(BusinessLogicError):
    """Duplicate approval attempt error."""
    
    def __init__(self, request_id: str, user_id: int, **kwargs):
        message = f"User {user_id} has already approved request {request_id}"
        super().__init__(message=message, **kwargs)


# Performance Errors
class PerformanceError(ApprovalError):
    """Performance-related errors."""
    
    def __init__(self, message: str = "Performance issue detected", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.PERFORMANCE,
            severity=ErrorSeverity.MEDIUM,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )


class TimeoutError(PerformanceError):
    """Operation timeout errors."""
    
    def __init__(self, operation: str, timeout: float, **kwargs):
        message = f"Operation '{operation}' timed out after {timeout} seconds"
        super().__init__(
            message=message,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )


class ResourceExhaustionError(PerformanceError):
    """Resource exhaustion errors."""
    
    def __init__(self, resource: str, **kwargs):
        message = f"Resource exhausted: {resource}"
        super().__init__(
            message=message,
            severity=ErrorSeverity.CRITICAL,
            recovery_action=RecoveryAction.FALLBACK,
            **kwargs
        )


# Security Errors
class SecurityError(ApprovalError):
    """Security-related errors."""
    
    def __init__(self, message: str = "Security violation detected", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL,
            recovery_action=RecoveryAction.ABORT,
            **kwargs
        )


class CSRFError(SecurityError):
    """CSRF token validation errors."""
    
    def __init__(self, **kwargs):
        super().__init__(
            message="CSRF token validation failed",
            **kwargs
        )


class RateLimitError(SecurityError):
    """Rate limiting errors."""
    
    def __init__(self, limit: int, window: str, **kwargs):
        message = f"Rate limit exceeded: {limit} requests per {window}"
        super().__init__(
            message=message,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )


class SuspiciousActivityError(SecurityError):
    """Suspicious activity detection errors."""
    
    def __init__(self, activity: str, **kwargs):
        message = f"Suspicious activity detected: {activity}"
        super().__init__(message=message, **kwargs)


# Configuration Errors
class ConfigurationError(ApprovalError):
    """Configuration-related errors."""
    
    def __init__(self, message: str = "Configuration error", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.MANUAL_INTERVENTION,
            **kwargs
        )


class MissingConfigurationError(ConfigurationError):
    """Missing configuration errors."""
    
    def __init__(self, setting: str, **kwargs):
        message = f"Required configuration setting '{setting}' is missing"
        super().__init__(message=message, **kwargs)


class InvalidConfigurationError(ConfigurationError):
    """Invalid configuration errors."""
    
    def __init__(self, setting: str, value: Any, **kwargs):
        message = f"Configuration setting '{setting}' has invalid value: {value}"
        super().__init__(message=message, **kwargs)


# Integration Errors
class IntegrationError(ApprovalError):
    """External integration errors."""
    
    def __init__(self, service: str, message: str = "Integration error", **kwargs):
        full_message = f"Integration with {service} failed: {message}"
        super().__init__(
            message=full_message,
            category=ErrorCategory.INTEGRATION,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )
        self.service = service


class ExternalServiceError(IntegrationError):
    """External service errors."""
    
    def __init__(self, service: str, status_code: Optional[int] = None, **kwargs):
        message = f"External service error"
        if status_code:
            message += f" (HTTP {status_code})"
        super().__init__(service=service, message=message, **kwargs)


class APIError(IntegrationError):
    """API call errors."""
    
    def __init__(self, api: str, endpoint: str, status_code: int, **kwargs):
        message = f"API call to {api}:{endpoint} failed with status {status_code}"
        super().__init__(service=api, message=message, **kwargs)


# Error Handler Registry
from abc import ABC, abstractmethod

class ErrorHandler(ABC):
    """Base error handler interface with safe default implementations."""

    @abstractmethod
    def can_handle(self, error: Exception) -> bool:
        """Check if this handler can handle the error."""
        # Default implementation for safety
        return isinstance(error, Exception)

    @abstractmethod
    def handle(self, error: Exception, context: Optional[ErrorContext] = None) -> ApprovalError:
        """Handle the error and return standardized error."""
        # Safe default implementation
        error_msg = f"Unhandled error: {type(error).__name__}: {str(error)}"
        return ApprovalError(error_msg, ApprovalErrorType.VALIDATION_ERROR, context)


class SQLAlchemyErrorHandler(ErrorHandler):
    """Handler for SQLAlchemy errors."""
    
    def can_handle(self, error: Exception) -> bool:
        from sqlalchemy.exc import SQLAlchemyError
        return isinstance(error, SQLAlchemyError)
    
    def handle(self, error: Exception, context: Optional[ErrorContext] = None) -> ApprovalError:
        from sqlalchemy.exc import (
            DisconnectionError, TimeoutError as SQLTimeoutError,
            IntegrityError, OperationalError
        )
        
        if isinstance(error, DisconnectionError):
            return ConnectionError(
                message=f"Database connection lost: {str(error)}",
                context=context,
                cause=error
            )
        elif isinstance(error, SQLTimeoutError):
            return TimeoutError(
                operation="database_query",
                timeout=30.0,  # Default timeout
                context=context,
                cause=error
            )
        elif isinstance(error, IntegrityError):
            return ConstraintViolationError(
                constraint=str(error),
                context=context,
                cause=error
            )
        elif isinstance(error, OperationalError):
            return DatabaseError(
                message=f"Database operational error: {str(error)}",
                context=context,
                cause=error
            )
        else:
            return DatabaseError(
                message=f"Database error: {str(error)}",
                context=context,
                cause=error
            )


class ValidationErrorHandler(ErrorHandler):
    """Handler for validation errors."""
    
    def can_handle(self, error: Exception) -> bool:
        return isinstance(error, (ValueError, TypeError))
    
    def handle(self, error: Exception, context: Optional[ErrorContext] = None) -> ApprovalError:
        if isinstance(error, ValueError):
            return ValidationError(
                message=f"Value validation failed: {str(error)}",
                context=context,
                cause=error
            )
        elif isinstance(error, TypeError):
            return ValidationError(
                message=f"Type validation failed: {str(error)}",
                context=context,
                cause=error
            )


class GenericErrorHandler(ErrorHandler):
    """Handler for generic exceptions."""
    
    def can_handle(self, error: Exception) -> bool:
        return True  # Catch-all handler
    
    def handle(self, error: Exception, context: Optional[ErrorContext] = None) -> ApprovalError:
        return ApprovalError(
            message=f"Unexpected error: {str(error)}",
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.ESCALATE,
            context=context,
            cause=error
        )


class ErrorHandlerRegistry:
    """Registry for error handlers."""
    
    def __init__(self):
        self.handlers: List[ErrorHandler] = [
            SQLAlchemyErrorHandler(),
            ValidationErrorHandler(),
            GenericErrorHandler()  # Must be last (catch-all)
        ]
    
    def register_handler(self, handler: ErrorHandler, priority: int = 0):
        """Register error handler with priority."""
        if priority == 0:
            self.handlers.insert(-1, handler)  # Insert before catch-all
        else:
            self.handlers.insert(priority, handler)
    
    def handle_error(self, error: Exception, context: Optional[ErrorContext] = None) -> ApprovalError:
        """Handle error using registered handlers."""
        for handler in self.handlers:
            if handler.can_handle(error):
                return handler.handle(error, context)
        
        # Fallback (should never reach here due to GenericErrorHandler)
        return ApprovalError(
            message=f"Unhandled error: {str(error)}",
            context=context,
            cause=error
        )


# Global error handler registry
_error_registry = ErrorHandlerRegistry()


def handle_error(error: Exception, context: Optional[ErrorContext] = None) -> ApprovalError:
    """Handle any error and return standardized ApprovalError."""
    return _error_registry.handle_error(error, context)


def register_error_handler(handler: ErrorHandler, priority: int = 0):
    """Register custom error handler."""
    _error_registry.register_handler(handler, priority)


# Decorator for automatic error handling
def handle_approval_errors(context_factory=None):
    """
    Decorator for automatic error handling in approval operations.
    
    Args:
        context_factory: Function to create error context
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ApprovalError:
                # Re-raise ApprovalErrors as-is
                raise
            except Exception as e:
                # Convert other exceptions to ApprovalError
                context = None
                if context_factory:
                    try:
                        context = context_factory(*args, **kwargs)
                    except Exception:
                        pass  # Ignore context creation errors
                
                approval_error = handle_error(e, context)
                raise approval_error from e
        
        return wrapper
    return decorator


# Context managers for error handling
class error_context:
    """Context manager for error handling with automatic context."""
    
    def __init__(self, operation: str, **context_data):
        self.context = ErrorContext(
            operation=operation,
            **context_data
        )
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type and not issubclass(exc_type, ApprovalError):
            # Convert exception to ApprovalError
            approval_error = handle_error(exc_val, self.context)
            raise approval_error from exc_val
        return False  # Don't suppress ApprovalErrors


# Utility functions
def create_error_response(error: ApprovalError, include_traceback: bool = False) -> Dict[str, Any]:
    """Create standardized error response for APIs."""
    response = error.to_dict()
    
    if include_traceback and error.cause:
        response['error']['traceback'] = traceback.format_exception(
            type(error.cause), error.cause, error.cause.__traceback__
        )
    
    return response


def log_error_metrics(error: ApprovalError):
    """Log error metrics for monitoring."""
    log.info(f"ERROR_METRIC: category={error.category.value} "
             f"severity={error.severity.value} "
             f"code={error.error_code} "
             f"recoverable={error.is_recoverable()}")