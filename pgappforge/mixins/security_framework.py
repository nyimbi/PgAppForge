"""
Security and Error Handling Framework for PgAppForge Mixins

This module provides:
- Specific exception classes for better error context
- Security validation utilities
- Input sanitization and validation
- Audit logging for security events
- Error recovery strategies
"""

import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union

from flask import current_app, current_user, request
from pgappforge import db
from sqlalchemy.exc import IntegrityError, OperationalError, DataError

log = logging.getLogger(__name__)


# ========== Exception Classes ==========

class MixinSecurityError(Exception):
    """Base exception for security-related errors."""
    def __init__(self, message: str, details: Dict = None, user_id: int = None):
        super().__init__(message)
        self.details = details or {}
        self.user_id = user_id
        self.timestamp = datetime.now(tz=timezone.utc)


class MixinPermissionError(MixinSecurityError):
    """Raised when user lacks required permissions."""
    pass


class MixinValidationError(Exception):
    """Base exception for validation errors."""
    def __init__(self, message: str, field: str = None, value: Any = None):
        super().__init__(message)
        self.field = field
        self.value = value


class MixinDataError(Exception):
    """Base exception for data-related errors."""
    pass


class MixinConfigurationError(Exception):
    """Raised when mixin configuration is invalid."""
    pass


class MixinExternalServiceError(Exception):
    """Raised when external service calls fail."""
    def __init__(self, message: str, service: str, response_code: int = None):
        super().__init__(message)
        self.service = service
        self.response_code = response_code


class MixinDatabaseError(Exception):
    """Raised for database-related errors with retry capability."""
    def __init__(self, message: str, retryable: bool = False, operation: str = None):
        super().__init__(message)
        self.retryable = retryable
        self.operation = operation


# ========== Security Validation ==========

class SecurityValidator:
    """Security validation utilities for mixins."""
    
    @staticmethod
    def validate_user_context(user_id: Optional[int] = None, require_active: bool = True) -> 'User':
        """
        Validate user context with comprehensive security checks.
        
        Args:
            user_id: User ID to validate (uses current_user if None)
            require_active: Require user to be active
            
        Returns:
            Validated user object
            
        Raises:
            MixinPermissionError: If user validation fails
        """
        try:
            from pgappforge.security.sqla.models import User
            
            # Get user object
            if user_id:
                user = db.session.query(User).filter(User.id == user_id).first()
                if not user:
                    raise MixinPermissionError(
                        f"User {user_id} not found",
                        details={'user_id': user_id}
                    )
            else:
                user = getattr(current_user, '_get_current_object', lambda: current_user)()
                if not user or not hasattr(user, 'id'):
                    raise MixinPermissionError(
                        "No authenticated user context available",
                        details={'has_current_user': bool(current_user)}
                    )
            
            # Validate user is active
            if require_active and not getattr(user, 'active', True):
                SecurityAuditor.log_security_event(
                    'inactive_user_access_attempt',
                    user_id=getattr(user, 'id', None),
                    details={'reason': 'inactive_user'}
                )
                raise MixinPermissionError(
                    f"User {getattr(user, 'id', 'unknown')} is not active",
                    details={'user_id': getattr(user, 'id', None), 'active': False}
                )
            
            # Check for account lockout
            if hasattr(user, 'failed_login_count') and user.failed_login_count >= 5:
                raise MixinPermissionError(
                    f"User {user.id} account is locked due to failed login attempts",
                    details={'user_id': user.id, 'failed_login_count': user.failed_login_count}
                )
            
            return user
            
        except ImportError as e:
            log.error(f"PgAppForge security models not available: {e}")
            raise MixinConfigurationError("Security models not properly configured")
        except Exception as e:
            if isinstance(e, (MixinPermissionError, MixinConfigurationError)):
                raise
            log.error(f"User context validation failed: {e}")
            raise MixinPermissionError(f"User validation failed: {str(e)}")
    
    @staticmethod
    def validate_permission(user: 'User', permission_name: str, resource: str = None) -> bool:
        """
        Validate user has specific permission.
        
        Args:
            user: User object to check
            permission_name: Permission name to validate
            resource: Optional resource name
            
        Returns:
            True if user has permission
            
        Raises:
            MixinPermissionError: If permission check fails
        """
        try:
            if not hasattr(user, 'has_permission'):
                raise MixinPermissionError(
                    "User object does not support permission checking",
                    details={'user_id': getattr(user, 'id', None)}
                )
            
            if resource:
                has_permission = user.has_permission(permission_name, resource)
            else:
                has_permission = user.has_permission(permission_name)
            
            if not has_permission:
                SecurityAuditor.log_security_event(
                    'permission_denied',
                    user_id=user.id,
                    details={
                        'permission': permission_name,
                        'resource': resource,
                        'user_roles': [role.name for role in getattr(user, 'roles', [])]
                    }
                )
                raise MixinPermissionError(
                    f"User {user.id} lacks permission '{permission_name}'{f' on {resource}' if resource else ''}",
                    details={
                        'user_id': user.id,
                        'permission': permission_name,
                        'resource': resource
                    }
                )
            
            return True
            
        except MixinPermissionError:
            raise
        except Exception as e:
            log.error(f"Permission validation failed: {e}")
            raise MixinPermissionError(f"Permission check error: {str(e)}")


# ========== Input Validation ==========

class InputValidator:
    """Input validation and sanitization utilities."""
    
    @staticmethod
    def sanitize_string(value: str, max_length: int = 1000, allow_html: bool = False) -> str:
        """
        Sanitize string input.
        
        Args:
            value: String to sanitize
            max_length: Maximum allowed length
            allow_html: Whether to allow HTML tags
            
        Returns:
            Sanitized string
            
        Raises:
            MixinValidationError: If validation fails
        """
        if not isinstance(value, str):
            raise MixinValidationError(f"Expected string, got {type(value)}", value=value)
        
        # Length check
        if len(value) > max_length:
            raise MixinValidationError(
                f"String too long: {len(value)} > {max_length}",
                value=value[:100] + "..." if len(value) > 100 else value
            )
        
        # Basic sanitization
        sanitized = value.strip()
        
        if not allow_html:
            # Basic HTML/script tag removal
            import re
            sanitized = re.sub(r'<[^>]*>', '', sanitized)
            
            # Remove potentially dangerous characters
            dangerous_chars = ['<', '>', '"', "'", '&', ';']
            for char in dangerous_chars:
                if char in sanitized:
                    sanitized = sanitized.replace(char, '')
        
        return sanitized
    
    @staticmethod
    def validate_email(email: str) -> str:
        """
        Validate email format.
        
        Args:
            email: Email to validate
            
        Returns:
            Validated email
            
        Raises:
            MixinValidationError: If email is invalid
        """
        import re
        
        if not isinstance(email, str):
            raise MixinValidationError("Email must be a string", field='email', value=email)
        
        email = email.strip().lower()
        
        # Basic email regex
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if not re.match(email_pattern, email):
            raise MixinValidationError(
                "Invalid email format",
                field='email',
                value=email
            )
        
        return email
    
    @staticmethod
    def validate_json_data(data: str) -> Dict:
        """
        Validate and parse JSON data.
        
        Args:
            data: JSON string to validate
            
        Returns:
            Parsed JSON data
            
        Raises:
            MixinValidationError: If JSON is invalid
        """
        if not isinstance(data, str):
            raise MixinValidationError("JSON data must be a string", value=data)
        
        try:
            parsed_data = json.loads(data)
            
            # Size limit check (1MB)
            if len(data) > 1024 * 1024:
                raise MixinValidationError(
                    f"JSON data too large: {len(data)} bytes",
                    value=data[:100] + "..."
                )
            
            return parsed_data
            
        except json.JSONDecodeError as e:
            raise MixinValidationError(
                f"Invalid JSON data: {str(e)}",
                field='json_data',
                value=data[:100] + "..." if len(data) > 100 else data
            )


# ========== Security Auditing ==========

class SecurityAuditor:
    """Security event logging and auditing."""
    
    @staticmethod
    def log_security_event(event_type: str, user_id: int = None, details: Dict = None):
        """
        Log security-related events for auditing.
        
        Args:
            event_type: Type of security event
            user_id: User ID associated with event
            details: Additional event details
        """
        try:
            event_data = {
                'event_type': event_type,
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'user_id': user_id,
                'ip_address': getattr(request, 'remote_addr', None) if request else None,
                'user_agent': getattr(request, 'headers', {}).get('User-Agent') if request else None,
                'details': details or {}
            }
            
            # Log to application logger with security prefix
            log.warning(f"SECURITY_EVENT: {json.dumps(event_data)}")
            
            # Also log to security-specific logger if configured
            security_logger = logging.getLogger('security')
            security_logger.warning(f"{event_type}: {json.dumps(event_data)}")
            
        except Exception as e:
            # Don't let audit logging failures break the application
            log.error(f"Failed to log security event: {e}")


# ========== Error Recovery ==========

class ErrorRecovery:
    """Error recovery strategies for mixins."""
    
    @staticmethod
    def retry_with_backoff(operation: Callable, max_retries: int = 3, 
                          base_delay: float = 1.0, max_delay: float = 60.0,
                          retryable_exceptions: tuple = None):
        """
        Retry operation with exponential backoff.
        
        Args:
            operation: Operation to retry
            max_retries: Maximum number of retry attempts
            base_delay: Base delay between retries (seconds)
            max_delay: Maximum delay between retries (seconds)
            retryable_exceptions: Tuple of exceptions that should trigger retry
            
        Returns:
            Operation result
            
        Raises:
            Last exception encountered after all retries failed
        """
        import time
        
        if retryable_exceptions is None:
            retryable_exceptions = (OperationalError, ConnectionError, TimeoutError)
        
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                return operation()
            except Exception as e:
                last_exception = e
                
                if attempt == max_retries:
                    # Final attempt failed
                    break
                
                if not isinstance(e, retryable_exceptions):
                    # Non-retryable exception
                    break
                
                # Calculate delay with exponential backoff
                delay = min(base_delay * (2 ** attempt), max_delay)
                log.warning(f"Operation failed (attempt {attempt + 1}/{max_retries + 1}), "
                           f"retrying in {delay:.1f}s: {str(e)}")
                time.sleep(delay)
        
        # All retries failed
        raise last_exception


# ========== Decorator Utilities ==========

def secure_operation(permission: str = None, validate_input: bool = True, 
                    log_access: bool = True, require_active_user: bool = True):
    """
    Decorator for securing mixin operations.
    
    Args:
        permission: Required permission name
        validate_input: Whether to validate input parameters
        log_access: Whether to log access attempts
        require_active_user: Whether to require active user
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                # Validate user context
                user = SecurityValidator.validate_user_context(
                    require_active=require_active_user
                )
                
                # Check permissions if specified
                if permission:
                    SecurityValidator.validate_permission(user, permission)
                
                # Log access if enabled
                if log_access:
                    SecurityAuditor.log_security_event(
                        'mixin_operation_access',
                        user_id=user.id,
                        details={
                            'operation': f"{self.__class__.__name__}.{func.__name__}",
                            'permission': permission
                        }
                    )
                
                # Execute operation
                return func(self, *args, **kwargs)
                
            except (MixinSecurityError, MixinPermissionError, MixinValidationError):
                # Re-raise security/validation errors as-is
                raise
            except Exception as e:
                # Wrap unexpected errors with context
                log.error(f"Secure operation {func.__name__} failed: {e}\n{traceback.format_exc()}")
                raise MixinDataError(f"Operation failed: {str(e)}")
        
        return wrapper
    return decorator


def database_operation(retryable: bool = True, transaction: bool = True):
    """
    Decorator for database operations with error handling and retry logic.
    
    Args:
        retryable: Whether to retry on retryable database errors
        transaction: Whether to wrap in transaction
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            def operation():
                if transaction:
                    try:
                        result = func(*args, **kwargs)
                        db.session.commit()
                        return result
                    except Exception:
                        db.session.rollback()
                        raise
                else:
                    return func(*args, **kwargs)
            
            try:
                if retryable:
                    return ErrorRecovery.retry_with_backoff(
                        operation,
                        retryable_exceptions=(OperationalError, ConnectionError)
                    )
                else:
                    return operation()
                    
            except IntegrityError as e:
                log.warning(f"Database integrity error in {func.__name__}: {e}")
                raise MixinDataError(f"Data integrity violation: {str(e)}")
            except OperationalError as e:
                log.error(f"Database operational error in {func.__name__}: {e}")
                raise MixinDatabaseError(f"Database operation failed: {str(e)}", retryable=True)
            except Exception as e:
                log.error(f"Unexpected database error in {func.__name__}: {e}\n{traceback.format_exc()}")
                raise MixinDatabaseError(f"Database operation failed: {str(e)}")
        
        return wrapper
    return decorator


# ========== Export all classes ==========

__all__ = [
    # Exceptions
    'MixinSecurityError',
    'MixinPermissionError', 
    'MixinValidationError',
    'MixinDataError',
    'MixinConfigurationError',
    'MixinExternalServiceError',
    'MixinDatabaseError',
    
    # Utilities
    'SecurityValidator',
    'InputValidator',
    'SecurityAuditor',
    'ErrorRecovery',
    
    # Decorators
    'secure_operation',
    'database_operation'
]