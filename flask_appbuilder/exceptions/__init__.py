"""
Flask-AppBuilder Exceptions Package

This package provides standardized exception handling for Flask-AppBuilder with
backward compatibility for existing FABException classes.
"""

# Import existing exceptions for backward compatibility
# These are re-exported from the legacy exceptions module
from typing import Optional

class FABException(Exception):
    """Base FAB Exception"""

    def __init__(self, *args, exception: Optional[Exception] = None) -> None:
        self.exception = exception
        super().__init__(*args)

    def __str__(self):
        return (
            f"{self.__class__.__name__}: {self.exception.__class__.__name__}"
            if self.exception
            else super().__str__()
        )


class InvalidColumnFilterFABException(FABException):
    """Invalid column for filter"""
    ...


class InvalidOperationFilterFABException(FABException):
    """Invalid operation for filter"""
    ...


class InvalidOrderByColumnFABException(FABException):
    """Invalid order by column"""
    ...


class InvalidColumnArgsFABException(FABException):
    """Invalid combination of column arguments"""
    ...


class InterfaceQueryWithoutSession(FABException):
    """You need to setup a session on the interface to perform queries"""
    ...


class PasswordComplexityValidationError(FABException):
    """Raise this when implementing your own password complexity function"""
    ...


class ApplyFilterException(FABException):
    """When executing an apply filter a SQLAlchemy exception happens"""
    ...


class OAuthProviderUnknown(FABException):
    """When an OAuth provider is not supported/unknown"""
    ...


class InvalidLoginAttempt(FABException):
    """When the credentials entered could not be verified"""
    ...


class DeleteGroupWithUsersException(FABException):
    """When trying to delete a group with users"""
    ...


class DeleteRoleWithUsersException(FABException):
    """When trying to delete a role with users"""
    ...


class ValidationError(FABException):
    """Profile validation error"""
    ...

# Import new standardized exceptions
from .standardized import (
    # Core classes
    ErrorCategory,
    ErrorSeverity,
    RecoveryAction,
    ErrorContext,
    StandardizedFABException,

    # Specific exception types
    FABAuthenticationError,
    FABAuthorizationError,
    FABValidationError,
    FABDatabaseError,
    FABConfigurationError,
    FABSecurityError,
    FABPerformanceError,
    FABAPIError,

    # Error handling utilities
    ErrorHandler,
    fab_error_handler,
    get_error_stats,

    # Utility functions
    create_validation_error,
    create_security_error,
    create_database_error,
    create_api_error,
    get_request_context,
    add_user_context
)

# Maintain backward compatibility by creating aliases
FABException = StandardizedFABException

__all__ = [
    # Legacy exceptions (backward compatibility)
    'FABException',
    'InvalidColumnFilterFABException',
    'InvalidOperationFilterFABException',
    'InvalidOrderByColumnFABException',
    'InvalidColumnArgsFABException',
    'InterfaceQueryWithoutSession',
    'PasswordComplexityValidationError',
    'ApplyFilterException',
    'OAuthProviderUnknown',
    'InvalidLoginAttempt',
    'DeleteGroupWithUsersException',
    'DeleteRoleWithUsersException',
    'ValidationError',

    # New standardized exceptions
    'ErrorCategory',
    'ErrorSeverity',
    'RecoveryAction',
    'ErrorContext',
    'StandardizedFABException',
    'FABAuthenticationError',
    'FABAuthorizationError',
    'FABValidationError',
    'FABDatabaseError',
    'FABConfigurationError',
    'FABSecurityError',
    'FABPerformanceError',
    'FABAPIError',

    # Error handling utilities
    'ErrorHandler',
    'fab_error_handler',
    'get_error_stats',
    'create_validation_error',
    'create_security_error',
    'create_database_error',
    'create_api_error',
    'get_request_context',
    'add_user_context'
]