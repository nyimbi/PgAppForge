"""
Shared utilities for collaborative features.

Provides common validation, logging, transaction management, and error handling
utilities used across all collaborative modules.
"""

from .validation import (
    ValidationResult,
    FieldValidator,
    TokenValidator,
    TimestampValidator,
    DataValidator,
    MessageValidator,
    UserValidator,
)

from .audit_logging import (
    AuditLogger,
    AuditEvent,
    AuditEventType,
    CollaborativeAuditMixin,
)

from .transaction_manager import (
    TransactionManager,
    TransactionScope,
    transaction_required,
    retry_on_deadlock,
)

from .error_handling import (
    CollaborativeError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    ConcurrencyError,
    ErrorHandlingMixin,
)

__all__ = [
    # Validation
    "ValidationResult",
    "FieldValidator",
    "TokenValidator",
    "TimestampValidator",
    "DataValidator",
    "MessageValidator",
    "UserValidator",
    # Audit Logging
    "AuditLogger",
    "AuditEvent",
    "AuditEventType",
    "CollaborativeAuditMixin",
    # Transaction Management
    "TransactionManager",
    "TransactionScope",
    "transaction_required",
    "retry_on_deadlock",
    # Error Handling
    "CollaborativeError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "ConcurrencyError",
    "ErrorHandlingMixin",
]
