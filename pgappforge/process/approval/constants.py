"""
Approval System Constants

Centralized configuration constants for the PgForge approval system.
Addresses code quality issues by consolidating hardcoded values.
"""


class SecurityConstants:
    """Security-related configuration constants."""

    # Cryptographic security
    MIN_SECRET_KEY_LENGTH = 32
    RECOMMENDED_SECRET_KEY_LENGTH = 64
    HMAC_ALGORITHM = 'sha256'

    # Session management
    DEFAULT_SESSION_TIMEOUT_MINUTES = 30
    MFA_SESSION_TIMEOUT_MINUTES = 5
    MAX_SESSION_RENEWAL_ATTEMPTS = 3

    # Rate limiting
    RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes
    BURST_LIMIT_WINDOW_SECONDS = 60  # 1 minute
    MAX_APPROVAL_ATTEMPTS_PER_WINDOW = 10
    MAX_BULK_OPERATIONS = 50

    # Input validation
    MAX_COMMENT_LENGTH = 1000
    MIN_DELEGATION_REASON_LENGTH = 10
    MAX_FIELD_NAME_LENGTH = 100

    # Authentication
    MAX_LOGIN_ATTEMPTS = 5
    ACCOUNT_LOCKOUT_DURATION_MINUTES = 15
    MFA_CODE_VALIDITY_MINUTES = 10
    
    # Backwards compatibility settings
    ENABLE_LEGACY_ADMIN_OVERRIDE = False  # DEPRECATED: For backwards compatibility only
    ADMIN_OVERRIDE_ROLES = ['Admin', 'SuperAdmin']  # Roles that can override (if enabled)
    REQUIRE_EXPLICIT_ADMIN_OVERRIDE = True  # Require explicit override parameter
    LOG_ADMIN_OVERRIDE_USAGE = True  # Log all admin override usage for audit
    DEPRECATION_WARNING_LEVEL = 'WARNING'  # Log level for deprecation warnings


class DatabaseConstants:
    """Database-related configuration constants."""

    # Transaction management
    DEFAULT_TRANSACTION_TIMEOUT_SECONDS = 30
    MAX_RETRY_ATTEMPTS = 3
    DEADLOCK_RETRY_ATTEMPTS = 5
    BASE_RETRY_DELAY_SECONDS = 0.1
    MAX_RETRY_DELAY_SECONDS = 2.0

    # Connection pooling
    DEFAULT_POOL_SIZE = 10
    MAX_OVERFLOW = 20
    POOL_RECYCLE_SECONDS = 3600

    # Query limits
    MAX_BULK_INSERT_SIZE = 1000
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 1000


class WorkflowConstants:
    """Workflow-related configuration constants."""

    # Approval chains
    MAX_CHAIN_STEPS = 10
    DEFAULT_STEP_TIMEOUT_HOURS = 24
    MAX_PARALLEL_APPROVERS = 5

    # Escalation
    DEFAULT_ESCALATION_TIMEOUT_HOURS = 48
    MAX_ESCALATION_LEVELS = 3
    AUTO_ESCALATION_ENABLED = True

    # Delegation
    MAX_DELEGATION_DEPTH = 2
    DELEGATION_EXPIRY_HOURS = 72

    # Notifications
    NOTIFICATION_BATCH_SIZE = 100
    EMAIL_RETRY_ATTEMPTS = 3
    SMS_RETRY_ATTEMPTS = 2


class ValidationConstants:
    """Input validation configuration constants."""

    # Field validation
    ALLOWED_FIELD_TYPES = ['string', 'integer', 'float', 'boolean', 'date', 'datetime']

    # Approval request validation
    REQUIRED_APPROVAL_FIELDS = ['workflow_type', 'priority', 'request_data']
    OPTIONAL_APPROVAL_FIELDS = ['comments', 'due_date', 'escalation_config']

    # Dynamic expression evaluation
    MAX_EXPRESSION_LENGTH = 500
    ALLOWED_OPERATORS = ['==', '!=', '>', '<', '>=', '<=', 'in', 'not in']
    ALLOWED_FUNCTIONS = ['len', 'str', 'int', 'float']

    # Sanitization
    HTML_ALLOWED_TAGS = []  # No HTML tags allowed
    HTML_ALLOWED_ATTRIBUTES = {}
    XSS_PROTECTION_ENABLED = True


class AuditConstants:
    """Audit and logging configuration constants."""

    # Log retention
    AUDIT_LOG_RETENTION_DAYS = 2555  # 7 years for compliance
    SECURITY_LOG_RETENTION_DAYS = 365
    DEBUG_LOG_RETENTION_DAYS = 30

    # Log levels
    DEFAULT_LOG_LEVEL = 'INFO'
    SECURITY_LOG_LEVEL = 'WARNING'
    AUDIT_LOG_LEVEL = 'INFO'

    # Event categories
    SECURITY_EVENTS = [
        'authentication_failure',
        'authorization_violation',
        'rate_limit_exceeded',
        'session_hijacking_attempt',
        'sql_injection_attempt',
        'xss_attempt'
    ]

    AUDIT_EVENTS = [
        'approval_granted',
        'approval_denied',
        'delegation_processed',
        'escalation_triggered',
        'workflow_completed'
    ]

    # File limits
    MAX_LOG_FILE_SIZE_MB = 100
    MAX_LOG_FILES = 10


class PerformanceConstants:
    """Performance and monitoring configuration constants."""

    # Response time thresholds (milliseconds)
    FAST_RESPONSE_THRESHOLD = 100
    ACCEPTABLE_RESPONSE_THRESHOLD = 500
    SLOW_RESPONSE_THRESHOLD = 1000

    # Memory usage thresholds (MB)
    LOW_MEMORY_THRESHOLD = 512
    HIGH_MEMORY_THRESHOLD = 1024
    CRITICAL_MEMORY_THRESHOLD = 2048

    # Monitoring intervals
    HEALTH_CHECK_INTERVAL_SECONDS = 30
    METRICS_COLLECTION_INTERVAL_SECONDS = 60
    ALERT_CHECK_INTERVAL_SECONDS = 120

    # Cache configuration
    DEFAULT_CACHE_TTL_SECONDS = 300
    USER_CACHE_TTL_SECONDS = 900
    CONFIG_CACHE_TTL_SECONDS = 3600


class ErrorConstants:
    """Error handling configuration constants."""

    # Error codes
    VALIDATION_ERROR = 'VALIDATION_ERROR'
    AUTHORIZATION_ERROR = 'AUTHORIZATION_ERROR'
    RATE_LIMIT_ERROR = 'RATE_LIMIT_ERROR'
    SECURITY_VIOLATION = 'SECURITY_VIOLATION'
    DATABASE_ERROR = 'DATABASE_ERROR'
    WORKFLOW_ERROR = 'WORKFLOW_ERROR'

    # Error messages
    GENERIC_ERROR_MESSAGE = 'An error occurred processing your request'
    UNAUTHORIZED_MESSAGE = 'You are not authorized to perform this action'
    RATE_LIMIT_MESSAGE = 'Too many requests. Please try again later'
    VALIDATION_ERROR_MESSAGE = 'Invalid input data provided'

    # Error handling behavior
    EXPOSE_STACK_TRACES = False  # Should be False in production
    LOG_FULL_ERRORS = True
    SANITIZE_ERROR_RESPONSES = True


# Backward compatibility aliases for existing code
MAX_BULK_OPERATIONS = SecurityConstants.MAX_BULK_OPERATIONS
MIN_SECRET_KEY_LENGTH = SecurityConstants.MIN_SECRET_KEY_LENGTH
DEFAULT_SESSION_TIMEOUT = SecurityConstants.DEFAULT_SESSION_TIMEOUT_MINUTES * 60
RATE_LIMIT_WINDOW = SecurityConstants.RATE_LIMIT_WINDOW_SECONDS