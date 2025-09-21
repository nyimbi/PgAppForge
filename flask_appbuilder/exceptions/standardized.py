"""
Standardized Exception Handling for Flask-AppBuilder

This module provides a comprehensive, standardized error handling system that can be used
throughout the Flask-AppBuilder framework. It builds on the existing FABException structure
while adding sophisticated error categorization, context tracking, and recovery mechanisms.

Key Features:
- Structured error categorization and severity levels
- Automatic logging with appropriate severity
- User-friendly message generation
- Error context tracking for debugging
- Recovery action suggestions
- Integration with security monitoring
- Backward compatibility with existing FABException
"""

import logging
import traceback
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Callable, Type
from enum import Enum
from dataclasses import dataclass, field
from functools import wraps

from ..exceptions import FABException

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Error categories for systematic handling and routing."""
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
    USER_INPUT = "user_input"
    FILE_OPERATION = "file_operation"
    API = "api"


class ErrorSeverity(Enum):
    """Error severity levels for categorization and response priority."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecoveryAction(Enum):
    """Suggested recovery actions for different error types."""
    RETRY = "retry"
    ESCALATE = "escalate"
    FALLBACK = "fallback"
    ABORT = "abort"
    IGNORE = "ignore"
    MANUAL_INTERVENTION = "manual_intervention"
    REFRESH = "refresh"
    LOGOUT_LOGIN = "logout_login"
    CONTACT_SUPPORT = "contact_support"


@dataclass
class ErrorContext:
    """Structured error context information for debugging and monitoring."""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    operation: Optional[str] = None
    resource_id: Optional[str] = None
    component: Optional[str] = None
    module: Optional[str] = None
    correlation_id: Optional[str] = None
    client_info: Optional[Dict[str, str]] = None
    additional_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary for serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'request_id': self.request_id,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'operation': self.operation,
            'resource_id': self.resource_id,
            'component': self.component,
            'module': self.module,
            'correlation_id': self.correlation_id,
            'client_info': self.client_info,
            'additional_data': self.additional_data
        }


class StandardizedFABException(FABException):
    """
    Enhanced FAB exception with standardized error handling patterns.

    Extends the existing FABException to maintain backward compatibility while
    adding sophisticated error handling features.
    """

    def __init__(self,
                 message: str,
                 error_code: Optional[str] = None,
                 category: ErrorCategory = ErrorCategory.SYSTEM,
                 severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                 recovery_action: RecoveryAction = RecoveryAction.ABORT,
                 context: Optional[ErrorContext] = None,
                 cause: Optional[Exception] = None,
                 user_message: Optional[str] = None,
                 technical_details: Optional[Dict[str, Any]] = None,
                 **kwargs):
        """
        Initialize standardized FAB exception.

        Args:
            message: Technical error message for developers
            error_code: Unique error code for tracking and documentation
            category: Error category for systematic handling
            severity: Error severity level for prioritization
            recovery_action: Suggested recovery action
            context: Additional error context for debugging
            cause: Original exception that caused this error
            user_message: User-friendly error message
            technical_details: Additional technical information
            **kwargs: Additional arguments passed to parent FABException
        """
        # Initialize parent FABException with backward compatibility
        super().__init__(message, exception=cause, **kwargs)

        self.message = message
        self.error_code = error_code or self._generate_error_code()
        self.category = category
        self.severity = severity
        self.recovery_action = recovery_action
        self.context = context or ErrorContext()
        self.cause = cause
        self.user_message = user_message or self._generate_user_message()
        self.technical_details = technical_details or {}

        # Ensure context has basic information
        if not self.context.component:
            self.context.component = self.__class__.__name__

        # Auto-log based on severity
        self._auto_log()

        # Track security events if applicable
        if self.category == ErrorCategory.SECURITY:
            self._log_security_event()

    def _generate_error_code(self) -> str:
        """Generate unique error code based on class name and timestamp."""
        class_name = self.__class__.__name__.replace('Exception', '').replace('Error', '')
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        return f"FAB_{class_name.upper()}_{timestamp}_{unique_id}"

    def _generate_user_message(self) -> str:
        """Generate user-friendly error message based on category."""
        user_messages = {
            ErrorCategory.AUTHENTICATION: "Please log in to access this resource.",
            ErrorCategory.AUTHORIZATION: "You don't have permission to perform this action.",
            ErrorCategory.VALIDATION: "Please check your input and try again.",
            ErrorCategory.DATABASE: "A database error occurred. Please try again later.",
            ErrorCategory.NETWORK: "A network error occurred. Please check your connection.",
            ErrorCategory.CONFIGURATION: "A configuration error was detected. Please contact support.",
            ErrorCategory.BUSINESS_LOGIC: "This operation cannot be completed due to business rules.",
            ErrorCategory.PERFORMANCE: "The request is taking too long. Please try again later.",
            ErrorCategory.SECURITY: "A security issue was detected. Access has been denied.",
            ErrorCategory.INTEGRATION: "An integration error occurred. Please try again later.",
            ErrorCategory.SYSTEM: "A system error occurred. Please try again later.",
            ErrorCategory.USER_INPUT: "Please check your input and correct any errors.",
            ErrorCategory.FILE_OPERATION: "File operation failed. Please check the file and try again.",
            ErrorCategory.API: "API request failed. Please try again later."
        }

        return user_messages.get(self.category, "An unexpected error occurred. Please try again later.")

    def _auto_log(self):
        """Automatically log error based on severity level."""
        log_data = {
            'error_code': self.error_code,
            'category': self.category.value,
            'severity': self.severity.value,
            'recovery_action': self.recovery_action.value,
            'context': self.context.to_dict() if self.context else {}
        }

        log_message = f"[{self.error_code}] {self.message}"

        if self.context:
            context_str = f"Component: {self.context.component}, Operation: {self.context.operation}"
            if self.context.user_id:
                context_str += f", User: {self.context.user_id}"
            log_message += f" | {context_str}"

        if self.cause:
            log_message += f" | Caused by: {str(self.cause)}"

        # Log with appropriate severity
        if self.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message, extra=log_data, exc_info=True)
        elif self.severity == ErrorSeverity.HIGH:
            logger.error(log_message, extra=log_data)
        elif self.severity == ErrorSeverity.MEDIUM:
            logger.warning(log_message, extra=log_data)
        else:
            logger.info(log_message, extra=log_data)

    def _log_security_event(self):
        """Log security events for monitoring and compliance."""
        security_logger = logging.getLogger('flask_appbuilder.security.events')
        security_event = {
            'event_type': 'security_exception',
            'error_code': self.error_code,
            'error_message': self.message,
            'user_id': self.context.user_id if self.context else None,
            'timestamp': datetime.utcnow().isoformat(),
            'severity': self.severity.value,
            'client_info': self.context.client_info if self.context else None
        }
        security_logger.warning(f"Security event: {self.error_code}", extra=security_event)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            'error': {
                'code': self.error_code,
                'message': self.user_message,
                'technical_message': self.message,
                'category': self.category.value,
                'severity': self.severity.value,
                'recovery_action': self.recovery_action.value,
                'timestamp': self.context.timestamp.isoformat() if self.context else None,
                'context': self.context.to_dict() if self.context else None,
                'technical_details': self.technical_details
            }
        }

    def get_recovery_suggestions(self) -> List[str]:
        """Get recovery suggestions based on error category and recovery action."""
        suggestions = []

        # Category-specific suggestions
        if self.category == ErrorCategory.AUTHENTICATION:
            suggestions = [
                "Please log in with valid credentials",
                "Check if your session has expired",
                "Contact your administrator if login issues persist"
            ]
        elif self.category == ErrorCategory.AUTHORIZATION:
            suggestions = [
                "Contact your administrator to request access",
                "Verify you are logged in with the correct account",
                "Check if your account permissions have changed"
            ]
        elif self.category == ErrorCategory.VALIDATION:
            suggestions = [
                "Double-check your input format",
                "Make sure all required fields are filled",
                "Review field requirements and try again"
            ]
        elif self.category == ErrorCategory.DATABASE:
            suggestions = [
                "Try the operation again in a few moments",
                "Check if you have the necessary permissions",
                "Contact support if the issue persists"
            ]
        elif self.category == ErrorCategory.NETWORK:
            suggestions = [
                "Check your internet connection",
                "Try again in a few moments",
                "Refresh the page and retry the operation"
            ]
        elif self.category == ErrorCategory.SECURITY:
            suggestions = [
                "Ensure you're accessing the system securely",
                "Contact security team if you believe this is an error",
                "Log out and log back in to refresh your session"
            ]
        else:
            # Generic suggestions based on recovery action
            if self.recovery_action == RecoveryAction.RETRY:
                suggestions = ["Try the operation again", "Wait a moment and retry"]
            elif self.recovery_action == RecoveryAction.REFRESH:
                suggestions = ["Refresh the page", "Clear browser cache and reload"]
            elif self.recovery_action == RecoveryAction.CONTACT_SUPPORT:
                suggestions = [f"Contact support with error code: {self.error_code}"]
            else:
                suggestions = ["Review your input and try again"]

        return suggestions


# Specific exception classes for common Flask-AppBuilder scenarios

class FABAuthenticationError(StandardizedFABException):
    """Authentication-related errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.LOGOUT_LOGIN,
            **kwargs
        )


class FABAuthorizationError(StandardizedFABException):
    """Authorization-related errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.ESCALATE,
            **kwargs
        )


class FABValidationError(StandardizedFABException):
    """Validation-related errors."""
    def __init__(self, message: str, field_name: Optional[str] = None, **kwargs):
        context = kwargs.get('context', ErrorContext())
        if field_name:
            context.additional_data['field_name'] = field_name

        super().__init__(
            message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            recovery_action=RecoveryAction.RETRY,
            context=context,
            **kwargs
        )


class FABDatabaseError(StandardizedFABException):
    """Database-related errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.DATABASE,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )


class FABConfigurationError(StandardizedFABException):
    """Configuration-related errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.HIGH,
            recovery_action=RecoveryAction.MANUAL_INTERVENTION,
            **kwargs
        )


class FABSecurityError(StandardizedFABException):
    """Security-related errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL,
            recovery_action=RecoveryAction.ABORT,
            **kwargs
        )


class FABPerformanceError(StandardizedFABException):
    """Performance-related errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.PERFORMANCE,
            severity=ErrorSeverity.MEDIUM,
            recovery_action=RecoveryAction.RETRY,
            **kwargs
        )


class FABAPIError(StandardizedFABException):
    """API-related errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, **kwargs):
        context = kwargs.get('context', ErrorContext())
        if status_code:
            context.additional_data['status_code'] = status_code

        super().__init__(
            message,
            category=ErrorCategory.API,
            severity=ErrorSeverity.MEDIUM,
            recovery_action=RecoveryAction.RETRY,
            context=context,
            **kwargs
        )


# Error handling utilities and decorators

class ErrorHandler:
    """Centralized error handler for Flask-AppBuilder operations."""

    def __init__(self):
        self.error_count = 0
        self.error_history: List[StandardizedFABException] = []
        self.max_history = 1000

    def handle_exception(self,
                        exception: Exception,
                        context: Optional[ErrorContext] = None,
                        category: Optional[ErrorCategory] = None,
                        severity: Optional[ErrorSeverity] = None) -> StandardizedFABException:
        """
        Handle any exception and convert it to a standardized FAB exception.

        Args:
            exception: The original exception
            context: Error context information
            category: Override error category
            severity: Override error severity

        Returns:
            Standardized FAB exception
        """
        # If it's already a standardized exception, return as-is
        if isinstance(exception, StandardizedFABException):
            self._track_error(exception)
            return exception

        # Convert exception to appropriate FAB exception type
        fab_exception = self._convert_exception(exception, context, category, severity)
        self._track_error(fab_exception)
        return fab_exception

    def _convert_exception(self,
                          exception: Exception,
                          context: Optional[ErrorContext] = None,
                          category: Optional[ErrorCategory] = None,
                          severity: Optional[ErrorSeverity] = None) -> StandardizedFABException:
        """Convert a generic exception to a standardized FAB exception."""

        # Determine category from exception type if not provided
        if not category:
            if isinstance(exception, (ValueError, TypeError)):
                category = ErrorCategory.VALIDATION
            elif isinstance(exception, PermissionError):
                category = ErrorCategory.AUTHORIZATION
            elif isinstance(exception, ConnectionError):
                category = ErrorCategory.NETWORK
            elif isinstance(exception, FileNotFoundError):
                category = ErrorCategory.FILE_OPERATION
            elif "SQL" in str(exception) or "database" in str(exception).lower():
                category = ErrorCategory.DATABASE
            else:
                category = ErrorCategory.SYSTEM

        # Determine severity if not provided
        if not severity:
            if category in [ErrorCategory.SECURITY, ErrorCategory.CONFIGURATION]:
                severity = ErrorSeverity.HIGH
            elif category in [ErrorCategory.DATABASE, ErrorCategory.AUTHENTICATION]:
                severity = ErrorSeverity.HIGH
            elif category in [ErrorCategory.NETWORK, ErrorCategory.VALIDATION]:
                severity = ErrorSeverity.MEDIUM
            else:
                severity = ErrorSeverity.MEDIUM

        return StandardizedFABException(
            message=str(exception),
            category=category,
            severity=severity,
            context=context,
            cause=exception,
            technical_details={'exception_type': exception.__class__.__name__}
        )

    def _track_error(self, error: StandardizedFABException):
        """Track error for monitoring and analytics."""
        self.error_count += 1
        self.error_history.append(error)

        # Maintain history size
        if len(self.error_history) > self.max_history:
            self.error_history = self.error_history[-self.max_history:]

    def get_error_stats(self) -> Dict[str, Any]:
        """Get error statistics for monitoring."""
        if not self.error_history:
            return {'total_errors': 0}

        category_counts = {}
        severity_counts = {}
        recent_errors = []

        for error in self.error_history[-100:]:  # Last 100 errors
            category_counts[error.category.value] = category_counts.get(error.category.value, 0) + 1
            severity_counts[error.severity.value] = severity_counts.get(error.severity.value, 0) + 1

            recent_errors.append({
                'error_code': error.error_code,
                'category': error.category.value,
                'severity': error.severity.value,
                'timestamp': error.context.timestamp.isoformat() if error.context else None
            })

        return {
            'total_errors': self.error_count,
            'category_distribution': category_counts,
            'severity_distribution': severity_counts,
            'recent_errors': recent_errors[-10:]  # Last 10 errors
        }


# Global error handler instance
_global_error_handler = ErrorHandler()


def fab_error_handler(category: Optional[ErrorCategory] = None,
                     severity: Optional[ErrorSeverity] = None,
                     operation: Optional[str] = None):
    """
    Decorator for standardized error handling in Flask-AppBuilder operations.

    Args:
        category: Override error category
        severity: Override error severity
        operation: Operation name for context

    Example:
        @fab_error_handler(category=ErrorCategory.DATABASE, operation="user_creation")
        def create_user(self, user_data):
            # Function implementation
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            context = ErrorContext(
                operation=operation or func.__name__,
                component=func.__module__,
                additional_data={'function': func.__qualname__}
            )

            try:
                return func(*args, **kwargs)
            except Exception as e:
                fab_exception = _global_error_handler.handle_exception(
                    e, context=context, category=category, severity=severity
                )
                raise fab_exception from e

        return wrapper
    return decorator


def get_error_stats() -> Dict[str, Any]:
    """Get global error statistics."""
    return _global_error_handler.get_error_stats()


# Utility functions for common error patterns

def create_validation_error(message: str, field_name: Optional[str] = None, **kwargs) -> FABValidationError:
    """Create a standardized validation error."""
    return FABValidationError(message, field_name=field_name, **kwargs)


def create_security_error(message: str, **kwargs) -> FABSecurityError:
    """Create a standardized security error."""
    return FABSecurityError(message, **kwargs)


def create_database_error(message: str, **kwargs) -> FABDatabaseError:
    """Create a standardized database error."""
    return FABDatabaseError(message, **kwargs)


def create_api_error(message: str, status_code: Optional[int] = None, **kwargs) -> FABAPIError:
    """Create a standardized API error."""
    return FABAPIError(message, status_code=status_code, **kwargs)


# Error context utilities

def get_request_context() -> ErrorContext:
    """Get error context from current Flask request."""
    try:
        from flask import request, g

        context = ErrorContext()

        if request:
            context.request_id = getattr(g, 'request_id', None)
            context.client_info = {
                'user_agent': request.user_agent.string if request.user_agent else None,
                'remote_addr': request.remote_addr,
                'method': request.method,
                'url': request.url
            }

        return context
    except ImportError:
        # Flask not available
        return ErrorContext()


def add_user_context(context: ErrorContext, user_id: Optional[int] = None,
                    session_id: Optional[str] = None) -> ErrorContext:
    """Add user information to error context."""
    if user_id:
        context.user_id = user_id
    if session_id:
        context.session_id = session_id

    try:
        from flask_login import current_user
        if hasattr(current_user, 'id') and current_user.is_authenticated:
            context.user_id = current_user.id
    except ImportError:
        pass

    return context