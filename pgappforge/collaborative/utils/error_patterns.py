"""
Standardized error handling patterns for PgForge collaborative features.

Provides consistent error response formats, exception handling, and logging
patterns across all collaborative services and API endpoints.
"""

import logging
from typing import Any, Dict, Optional, Union, Type
from flask import jsonify
from functools import wraps

from .error_handling import (
    CollaborativeError, 
    ValidationError, 
    AuthenticationError, 
    AuthorizationError,
    ErrorCategory,
    ErrorSeverity,
    create_error_response
)
from .audit_logging import AuditEventType


logger = logging.getLogger(__name__)


class StandardizedErrorHandler:
    """
    Standardized error handler for collaborative features.
    
    Provides consistent error response formats and logging patterns
    across all PgForge collaborative APIs and views.
    """
    
    @staticmethod
    def handle_api_error(
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        include_debug: bool = False
    ) -> Dict[str, Any]:
        """
        Handle API errors with standardized response format.
        
        Args:
            error: Exception that occurred
            context: Additional context information
            user_id: User ID for audit logging
            include_debug: Whether to include debug information
            
        Returns:
            Standardized error response dictionary
        """
        # Convert generic exceptions to CollaborativeError
        if not isinstance(error, CollaborativeError):
            collaborative_error = ValidationError(
                str(error),
                cause=error,
                context=context
            )
        else:
            collaborative_error = error
        
        # Log the error
        logger.error(
            f"API Error: {collaborative_error.error_code} - {collaborative_error.message}",
            extra={
                "error_category": collaborative_error.category.value,
                "error_severity": collaborative_error.severity.value,
                "user_id": user_id,
                "context": context,
                "recoverable": collaborative_error.recoverable
            }
        )
        
        # Create standardized response
        return create_error_response(collaborative_error, include_debug=include_debug)
    
    @staticmethod
    def get_http_status_from_error(error: CollaborativeError) -> int:
        """
        Get appropriate HTTP status code from CollaborativeError.
        
        Args:
            error: CollaborativeError instance
            
        Returns:
            HTTP status code
        """
        status_map = {
            ErrorCategory.VALIDATION: 400,
            ErrorCategory.AUTHENTICATION: 401,
            ErrorCategory.AUTHORIZATION: 403,
            ErrorCategory.NOT_FOUND: 404,
            ErrorCategory.CONCURRENCY: 409,
            ErrorCategory.RATE_LIMIT: 429,
            ErrorCategory.EXTERNAL_SERVICE: 502,
            ErrorCategory.SYSTEM: 500,
        }
        
        return status_map.get(error.category, 500)


def api_error_handler(
    include_debug: bool = False,
    audit_failures: bool = True
):
    """
    Decorator for standardized API error handling.
    
    Args:
        include_debug: Whether to include debug information in responses
        audit_failures: Whether to audit error events
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                # Get user context if available
                user_id = None
                if hasattr(self, 'get_current_user'):
                    user = self.get_current_user()
                    user_id = user.id if user else None
                
                # Handle the error
                error_response = StandardizedErrorHandler.handle_api_error(
                    error=e,
                    context={
                        'endpoint': func.__name__,
                        'args': str(args),
                        'kwargs': str(kwargs)
                    },
                    user_id=user_id,
                    include_debug=include_debug
                )
                
                # Audit the failure if enabled
                if audit_failures and hasattr(self, 'audit_security_event'):
                    self.audit_security_event(
                        AuditEventType.API_ERROR,
                        user_id=user_id,
                        resource_type="api_endpoint",
                        resource_id=func.__name__,
                        outcome="failure",
                        details={'error_type': type(e).__name__, 'message': str(e)}
                    )
                
                # Get appropriate HTTP status
                if isinstance(e, CollaborativeError):
                    status_code = StandardizedErrorHandler.get_http_status_from_error(e)
                else:
                    status_code = 500
                
                # Return Flask response
                if hasattr(self, 'response'):
                    return self.response(error_response, status_code)
                else:
                    return jsonify(error_response), status_code
        
        return wrapper
    return decorator


def service_error_handler(
    fallback_value: Any = None,
    log_errors: bool = True,
    re_raise: bool = True
):
    """
    Decorator for standardized service error handling.
    
    Args:
        fallback_value: Value to return on error (if re_raise=False)
        log_errors: Whether to log errors
        re_raise: Whether to re-raise exceptions
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                if log_errors:
                    logger.error(
                        f"Service Error in {func.__name__}: {str(e)}",
                        extra={
                            'service': self.__class__.__name__,
                            'method': func.__name__,
                            'args': str(args),
                            'kwargs': str(kwargs)
                        },
                        exc_info=True
                    )
                
                if re_raise:
                    # Convert to CollaborativeError if needed
                    if not isinstance(e, CollaborativeError):
                        raise ValidationError(
                            f"Service error in {func.__name__}: {str(e)}",
                            cause=e
                        )
                    else:
                        raise
                else:
                    return fallback_value
        
        return wrapper
    return decorator


class ErrorPatternMixin:
    """
    Mixin for standardized error patterns in collaborative services.
    
    Provides common error handling methods that can be mixed into
    any collaborative service or API class.
    """
    
    def handle_validation_error(
        self,
        message: str,
        field_name: Optional[str] = None,
        field_value: Any = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationError:
        """Create and log validation error."""
        error = ValidationError(
            message,
            field_name=field_name,
            field_value=field_value,
            context=context
        )
        
        self._log_error(error)
        return error
    
    def handle_auth_error(
        self,
        message: str,
        required_permission: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> AuthorizationError:
        """Create and log authorization error."""
        error = AuthorizationError(
            message,
            required_permission=required_permission,
            context=context
        )
        
        self._log_error(error)
        return error
    
    def handle_not_found_error(
        self,
        resource_type: str,
        resource_id: Union[str, int],
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationError:
        """Create and log not found error."""
        error = ValidationError(
            f"{resource_type.title()} with ID {resource_id} not found",
            context=context or {}
        )
        error.category = ErrorCategory.NOT_FOUND
        
        self._log_error(error)
        return error
    
    def _log_error(self, error: CollaborativeError) -> None:
        """Log error with appropriate level based on severity."""
        log_message = f"{error.error_code}: {error.message}"
        
        if error.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message, extra={'error_context': error.context})
        elif error.severity == ErrorSeverity.HIGH:
            logger.error(log_message, extra={'error_context': error.context})
        elif error.severity == ErrorSeverity.MEDIUM:
            logger.warning(log_message, extra={'error_context': error.context})
        else:
            logger.info(log_message, extra={'error_context': error.context})


# Common error response templates
ERROR_TEMPLATES = {
    'validation_failed': {
        'message': 'Validation failed',
        'category': 'validation',
        'recoverable': True
    },
    'access_denied': {
        'message': 'Access denied',
        'category': 'authorization',
        'recoverable': False
    },
    'resource_not_found': {
        'message': 'Resource not found',
        'category': 'not_found',
        'recoverable': False
    },
    'service_unavailable': {
        'message': 'Service temporarily unavailable',
        'category': 'external_service',
        'recoverable': True
    },
    'rate_limit_exceeded': {
        'message': 'Rate limit exceeded',
        'category': 'rate_limit',
        'recoverable': True
    }
}


def get_error_template(template_name: str) -> Dict[str, Any]:
    """Get predefined error response template."""
    return ERROR_TEMPLATES.get(template_name, ERROR_TEMPLATES['validation_failed']).copy()