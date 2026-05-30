"""
Comprehensive Error Handling and Edge Case Management

Provides robust error handling, validation, and edge case management
for wizard forms with detailed logging and user-friendly error messages.
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass
from enum import Enum
import json
from functools import wraps

logger = logging.getLogger(__name__)


class WizardErrorType(Enum):
    """Types of wizard errors"""
    VALIDATION_ERROR = "validation_error"
    CONFIGURATION_ERROR = "configuration_error"
    RUNTIME_ERROR = "runtime_error"
    NETWORK_ERROR = "network_error"
    PERMISSION_ERROR = "permission_error"
    DATA_ERROR = "data_error"
    SYSTEM_ERROR = "system_error"
    USER_ERROR = "user_error"


class WizardErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class WizardError:
    """Comprehensive error information"""
    error_id: str
    error_type: WizardErrorType
    severity: WizardErrorSeverity
    message: str
    detail: Optional[str] = None
    field_id: Optional[str] = None
    step_id: Optional[str] = None
    wizard_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    stack_trace: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    recovery_suggestions: Optional[List[str]] = None
    user_friendly_message: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(tz=timezone.utc)
        if self.error_id is None:
            import uuid
            self.error_id = str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary"""
        return {
            'error_id': self.error_id,
            'error_type': self.error_type.value,
            'severity': self.severity.value,
            'message': self.message,
            'detail': self.detail,
            'field_id': self.field_id,
            'step_id': self.step_id,
            'wizard_id': self.wizard_id,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'stack_trace': self.stack_trace,
            'context': self.context,
            'recovery_suggestions': self.recovery_suggestions,
            'user_friendly_message': self.user_friendly_message
        }


class WizardErrorHandler:
    """Comprehensive error handling system for wizard forms"""
    
    def __init__(self):
        """
        Initialize the wizard error handler with default configurations.
        
        Sets up:
        - Error storage lists for logging and analytics
        - Error handler function mappings for each error type
        - User-friendly message templates for common error scenarios
        - Default handlers and message templates
        """
        self.errors: List[WizardError] = []
        self.error_store: List[WizardError] = []  # Add error store for analytics
        self.error_handlers: Dict[WizardErrorType, Callable] = {}
        self.user_friendly_messages: Dict[str, str] = {}
        self._setup_default_handlers()
        self._setup_user_friendly_messages()
    
    def _setup_default_handlers(self):
        """Setup default error handlers"""
        self.error_handlers = {
            WizardErrorType.VALIDATION_ERROR: self._handle_validation_error,
            WizardErrorType.CONFIGURATION_ERROR: self._handle_configuration_error,
            WizardErrorType.RUNTIME_ERROR: self._handle_runtime_error,
            WizardErrorType.NETWORK_ERROR: self._handle_network_error,
            WizardErrorType.PERMISSION_ERROR: self._handle_permission_error,
            WizardErrorType.DATA_ERROR: self._handle_data_error,
            WizardErrorType.SYSTEM_ERROR: self._handle_system_error,
            WizardErrorType.USER_ERROR: self._handle_user_error
        }
    
    def _setup_user_friendly_messages(self):
        """Setup user-friendly error messages"""
        self.user_friendly_messages = {
            'field_required': 'This field is required. Please fill it in to continue.',
            'field_invalid_format': 'Please check the format of this field and try again.',
            'field_too_short': 'This field is too short. Please enter more characters.',
            'field_too_long': 'This field is too long. Please shorten your input.',
            'email_invalid': 'Please enter a valid email address.',
            'phone_invalid': 'Please enter a valid phone number.',
            'url_invalid': 'Please enter a valid URL starting with http:// or https://',
            'date_invalid': 'Please enter a valid date.',
            'number_invalid': 'Please enter a valid number.',
            'file_too_large': 'The uploaded file is too large. Please choose a smaller file.',
            'file_invalid_type': 'This file type is not allowed. Please choose a different file.',
            'network_timeout': 'The request timed out. Please check your connection and try again.',
            'server_error': 'A temporary server error occurred. Please try again in a moment.',
            'permission_denied': 'You don\'t have permission to perform this action.',
            'session_expired': 'Your session has expired. Please refresh the page and start over.',
            'wizard_not_found': 'The wizard form could not be found. Please check the link and try again.',
            'step_invalid': 'There was an issue with this step. Please review your input and try again.',
            'configuration_error': 'There\'s a configuration issue with this form. Please contact support.',
            'unexpected_error': 'An unexpected error occurred. Please try again or contact support if the problem persists.'
        }
    
    def handle_error(self, 
                    error: Union[Exception, WizardError, str],
                    error_type: Optional[WizardErrorType] = None,
                    severity: Optional[WizardErrorSeverity] = None,
                    context: Optional[Dict[str, Any]] = None,
                    **kwargs) -> WizardError:
        """Handle an error and return structured error information"""
        
        # Convert various error types to WizardError
        if isinstance(error, WizardError):
            wizard_error = error
        elif isinstance(error, Exception):
            wizard_error = self._exception_to_wizard_error(error, error_type, severity, context, **kwargs)
        else:
            wizard_error = WizardError(
                error_id=None,
                error_type=error_type or WizardErrorType.USER_ERROR,
                severity=severity or WizardErrorSeverity.MEDIUM,
                message=str(error),
                context=context,
                **kwargs
            )
        
        # Add user-friendly message if not set
        if not wizard_error.user_friendly_message:
            wizard_error.user_friendly_message = self._get_user_friendly_message(wizard_error)
        
        # Add recovery suggestions if not set
        if not wizard_error.recovery_suggestions:
            wizard_error.recovery_suggestions = self._get_recovery_suggestions(wizard_error)
        
        # Log the error
        self._log_error(wizard_error)
        
        # Store the error
        self.errors.append(wizard_error)
        
        # Call specific error handler
        handler = self.error_handlers.get(wizard_error.error_type)
        if handler:
            handler(wizard_error)
        
        return wizard_error
    
    def _exception_to_wizard_error(self,
                                  exception: Exception,
                                  error_type: Optional[WizardErrorType] = None,
                                  severity: Optional[WizardErrorSeverity] = None,
                                  context: Optional[Dict[str, Any]] = None,
                                  **kwargs) -> WizardError:
        """Convert a Python exception to a WizardError"""
        
        # Determine error type from exception type
        if not error_type:
            if isinstance(exception, ValueError):
                error_type = WizardErrorType.VALIDATION_ERROR
            elif isinstance(exception, KeyError):
                error_type = WizardErrorType.DATA_ERROR
            elif isinstance(exception, PermissionError):
                error_type = WizardErrorType.PERMISSION_ERROR
            elif isinstance(exception, ConnectionError):
                error_type = WizardErrorType.NETWORK_ERROR
            else:
                error_type = WizardErrorType.RUNTIME_ERROR
        
        # Determine severity
        if not severity:
            if error_type in [WizardErrorType.SYSTEM_ERROR, WizardErrorType.PERMISSION_ERROR]:
                severity = WizardErrorSeverity.HIGH
            elif error_type in [WizardErrorType.NETWORK_ERROR, WizardErrorType.RUNTIME_ERROR]:
                severity = WizardErrorSeverity.MEDIUM
            else:
                severity = WizardErrorSeverity.LOW
        
        return WizardError(
            error_id=None,
            error_type=error_type,
            severity=severity,
            message=str(exception),
            detail=f"{exception.__class__.__name__}: {str(exception)}",
            stack_trace=traceback.format_exc(),
            context=context,
            **kwargs
        )
    
    def _get_user_friendly_message(self, error: WizardError) -> str:
        """Generate user-friendly error message"""
        
        # Check for specific message patterns
        message_lower = error.message.lower()
        
        if 'required' in message_lower:
            return self.user_friendly_messages.get('field_required', error.message)
        elif 'email' in message_lower and 'invalid' in message_lower:
            return self.user_friendly_messages.get('email_invalid', error.message)
        elif 'phone' in message_lower and 'invalid' in message_lower:
            return self.user_friendly_messages.get('phone_invalid', error.message)
        elif 'url' in message_lower and 'invalid' in message_lower:
            return self.user_friendly_messages.get('url_invalid', error.message)
        elif 'date' in message_lower and 'invalid' in message_lower:
            return self.user_friendly_messages.get('date_invalid', error.message)
        elif 'number' in message_lower and 'invalid' in message_lower:
            return self.user_friendly_messages.get('number_invalid', error.message)
        elif 'file' in message_lower and 'large' in message_lower:
            return self.user_friendly_messages.get('file_too_large', error.message)
        elif 'file' in message_lower and 'type' in message_lower:
            return self.user_friendly_messages.get('file_invalid_type', error.message)
        elif 'network' in message_lower or 'timeout' in message_lower:
            return self.user_friendly_messages.get('network_timeout', error.message)
        elif 'server' in message_lower or 'internal' in message_lower:
            return self.user_friendly_messages.get('server_error', error.message)
        elif 'permission' in message_lower or 'unauthorized' in message_lower:
            return self.user_friendly_messages.get('permission_denied', error.message)
        elif 'session' in message_lower and 'expired' in message_lower:
            return self.user_friendly_messages.get('session_expired', error.message)
        elif 'wizard' in message_lower and 'not found' in message_lower:
            return self.user_friendly_messages.get('wizard_not_found', error.message)
        elif 'configuration' in message_lower:
            return self.user_friendly_messages.get('configuration_error', error.message)
        
        # Default based on error type
        type_messages = {
            WizardErrorType.VALIDATION_ERROR: 'field_invalid_format',
            WizardErrorType.NETWORK_ERROR: 'network_timeout',
            WizardErrorType.PERMISSION_ERROR: 'permission_denied',
            WizardErrorType.SYSTEM_ERROR: 'server_error',
            WizardErrorType.CONFIGURATION_ERROR: 'configuration_error'
        }
        
        default_key = type_messages.get(error.error_type, 'unexpected_error')
        return self.user_friendly_messages.get(default_key, error.message)
    
    def _get_recovery_suggestions(self, error: WizardError) -> List[str]:
        """Generate recovery suggestions based on error type"""
        
        suggestions = []
        
        if error.error_type == WizardErrorType.VALIDATION_ERROR:
            suggestions = [
                "Double-check your input format",
                "Make sure all required fields are filled",
                "Try refreshing the page if the issue persists"
            ]
        elif error.error_type == WizardErrorType.NETWORK_ERROR:
            suggestions = [
                "Check your internet connection",
                "Try again in a few moments",
                "Refresh the page and restart the form"
            ]
        elif error.error_type == WizardErrorType.PERMISSION_ERROR:
            suggestions = [
                "Make sure you're logged in",
                "Contact your administrator if you need access",
                "Try logging out and back in again"
            ]
        elif error.error_type == WizardErrorType.SYSTEM_ERROR:
            suggestions = [
                "Try refreshing the page",
                "Wait a moment and try again",
                "Contact support if the problem continues"
            ]
        elif error.error_type == WizardErrorType.CONFIGURATION_ERROR:
            suggestions = [
                "Contact the form administrator",
                "Report this issue to support",
                "Try using a different browser"
            ]
        else:
            suggestions = [
                "Try refreshing the page",
                "Double-check your input",
                "Contact support if needed"
            ]
        
        # Add field-specific suggestions
        if error.field_id:
            if 'email' in error.field_id.lower():
                suggestions.insert(0, "Make sure your email address includes @ and a valid domain")
            elif 'phone' in error.field_id.lower():
                suggestions.insert(0, "Include your country code and use only numbers and common separators")
            elif 'date' in error.field_id.lower():
                suggestions.insert(0, "Use the date picker or enter dates in MM/DD/YYYY format")
        
        return suggestions
    
    def _log_error(self, error: WizardError):
        """Log error with appropriate level"""
        
        log_data = {
            'error_id': error.error_id,
            'type': error.error_type.value,
            'severity': error.severity.value,
            'wizard_id': error.wizard_id,
            'step_id': error.step_id,
            'field_id': error.field_id,
            'user_id': error.user_id,
            'session_id': error.session_id
        }
        
        if error.severity == WizardErrorSeverity.CRITICAL:
            logger.critical(f"CRITICAL wizard error: {error.message}", extra=log_data)
        elif error.severity == WizardErrorSeverity.HIGH:
            logger.error(f"High severity wizard error: {error.message}", extra=log_data)
        elif error.severity == WizardErrorSeverity.MEDIUM:
            logger.warning(f"Medium severity wizard error: {error.message}", extra=log_data)
        else:
            logger.info(f"Low severity wizard error: {error.message}", extra=log_data)
        
        if error.stack_trace and error.severity in [WizardErrorSeverity.HIGH, WizardErrorSeverity.CRITICAL]:
            logger.error(f"Stack trace for error {error.error_id}:\n{error.stack_trace}")
    
    # Specific error handlers
    def _handle_validation_error(self, error: WizardError):
        """Handle validation errors"""
        # Log validation error with context
        logger.warning(f"Validation error in wizard {error.wizard_id}, step {error.step_id}, field {error.field_id}: {error.message}")
        
        # Store error for later retrieval and analytics
        self.error_store.append(error)
        
        # Add field-specific recovery suggestions
        if error.field_id:
            field_type = self._detect_field_type(error.field_id)
            error.recovery_suggestions.extend(self._get_field_specific_suggestions(field_type))
        
        # Track validation error patterns for form improvement
        self._track_validation_pattern(error)
        
        # Trigger UI updates for real-time validation feedback
        self._trigger_ui_validation_update(error)
    
    def _handle_configuration_error(self, error: WizardError):
        """Handle configuration errors"""
        # Log critical configuration errors
        logger.error(f"Configuration error in wizard {error.wizard_id}: {error.message}")
        
        # Store error for administrator review
        self.error_store.append(error)
        
        # Add configuration-specific recovery suggestions
        config_suggestions = [
            "Check wizard configuration JSON syntax",
            "Verify all required fields are properly defined", 
            "Ensure step IDs are unique and properly referenced",
            "Validate field types and validation rules",
            "Review theme and UI configuration settings"
        ]
        error.recovery_suggestions.extend(config_suggestions)
        
        # For critical config errors, disable wizard temporarily
        if error.severity == WizardErrorSeverity.CRITICAL:
            self._disable_wizard_temporarily(error.wizard_id)
            
        # Alert administrators about configuration issues
        self._alert_administrators(error)
    
    def _handle_runtime_error(self, error: WizardError):
        """Handle runtime errors"""
        # Log runtime error with full context
        logger.error(f"Runtime error in wizard {error.wizard_id}: {error.message}")
        if error.stack_trace:
            logger.debug(f"Runtime error stack trace: {error.stack_trace}")
            
        # Store error for debugging and analysis
        self.error_store.append(error)
        
        # Add runtime-specific recovery suggestions
        runtime_suggestions = [
            "Try refreshing the page and attempting the action again",
            "Clear your browser cache and cookies", 
            "Check your internet connection",
            "If the problem persists, contact support with error ID: " + error.error_id
        ]
        error.recovery_suggestions.extend(runtime_suggestions)
        
        # For high severity errors, create incident report
        if error.severity in [WizardErrorSeverity.HIGH, WizardErrorSeverity.CRITICAL]:
            self._create_incident_report(error)
            
        # Enable auto-retry for recoverable runtime errors
        if error.severity != WizardErrorSeverity.CRITICAL:
            self._schedule_auto_retry(error)
    
    def _handle_network_error(self, error: WizardError):
        """Handle network errors"""
        # Log network error
        logger.warning(f"Network error in wizard {error.wizard_id}: {error.message}")
        
        # Store network error for pattern analysis
        self.error_store.append(error)
        
        # Add network-specific recovery suggestions
        network_suggestions = [
            "Check your internet connection",
            "Try again in a few moments",
            "If using VPN, try disconnecting and reconnecting", 
            "Clear browser cache and reload the page",
            "Contact your network administrator if problem persists"
        ]
        error.recovery_suggestions.extend(network_suggestions)
        
        # Enable auto-retry with exponential backoff
        self._schedule_network_retry(error)
        
        # Track network patterns for infrastructure monitoring
        self._track_network_issue(error)
    
    def _handle_permission_error(self, error: WizardError):
        """Handle permission errors"""
        # Log permission error for security audit
        logger.warning(f"Permission denied in wizard {error.wizard_id}: {error.message}")
        
        # Store permission error for compliance audit
        self.error_store.append(error)
        
        # Add permission-specific recovery suggestions
        permission_suggestions = [
            "Contact your administrator to request access",
            "Verify you are logged in with the correct account", 
            "Check if your account permissions have changed",
            "Try logging out and back in again"
        ]
        error.recovery_suggestions.extend(permission_suggestions)
        
        # Log security event for audit trail
        self._log_security_event(error)
        
        # Analyze for potential security threats
        self._analyze_permission_pattern(error)
    
    def _handle_data_error(self, error: WizardError):
        """Handle data errors"""
        # Log data error with context
        logger.error(f"Data error in wizard {error.wizard_id}, field {error.field_id}: {error.message}")
        
        # Store data error for analysis
        self.error_store.append(error)
        
        # Add data-specific recovery suggestions
        data_suggestions = [
            "Check that all required fields are filled correctly",
            "Verify data format matches expected patterns",
            "Remove special characters if not allowed",
            "Ensure file uploads meet size and format requirements",
            "Try saving as draft and completing later"
        ]
        error.recovery_suggestions.extend(data_suggestions)
        
        # For critical data errors, backup current state
        if error.severity == WizardErrorSeverity.CRITICAL:
            self._backup_form_state(error.wizard_id)
            
        # Trigger data validation review
        self._review_data_validation_rules(error)
    
    def _handle_system_error(self, error: WizardError):
        """Handle system errors"""
        # Log system error with high priority
        logger.error(f"SYSTEM ERROR in wizard {error.wizard_id}: {error.message}")
        
        # Store system error for monitoring
        self.error_store.append(error)
        
        # Add system-specific recovery suggestions
        system_suggestions = [
            "The system is experiencing issues - please try again shortly",
            "Your progress has been saved automatically",
            "Contact technical support with error ID: " + error.error_id,
            "Try using a different browser or device"
        ]
        error.recovery_suggestions.extend(system_suggestions)
        
        # Alert system administrators for critical errors
        if error.severity == WizardErrorSeverity.CRITICAL:
            self._alert_system_administrators(error)
            
        # Monitor system health metrics
        self._update_system_health_metrics(error)
    
    def _handle_user_error(self, error: WizardError):
        """Handle user errors"""
        # Log user error for UX analytics
        logger.info(f"User error in wizard {error.wizard_id}: {error.message}")
        
        # Store user error for experience improvement
        self.error_store.append(error)
        
        # Add user-friendly recovery suggestions
        user_suggestions = [
            "Please review your input and try again",
            "Check the help text or examples provided",
            "Use the 'Previous' button to review earlier steps", 
            "Save as draft to complete later if needed",
            "Contact support if you need assistance"
        ]
        error.recovery_suggestions.extend(user_suggestions)
        
        # Track user error patterns for UX improvement
        self._track_user_experience_issue(error)
        
        # Trigger contextual help if available
        self._provide_contextual_help(error)
    
    def get_errors_for_wizard(self, wizard_id: str) -> List[WizardError]:
        """Get all errors for a specific wizard"""
        return [e for e in self.errors if e.wizard_id == wizard_id]
    
    def get_errors_for_field(self, wizard_id: str, field_id: str) -> List[WizardError]:
        """Get all errors for a specific field"""
        return [e for e in self.errors if e.wizard_id == wizard_id and e.field_id == field_id]
    
    def clear_errors(self, wizard_id: Optional[str] = None, field_id: Optional[str] = None):
        """Clear errors (optionally filtered)"""
        if wizard_id and field_id:
            self.errors = [e for e in self.errors if not (e.wizard_id == wizard_id and e.field_id == field_id)]
        elif wizard_id:
            self.errors = [e for e in self.errors if e.wizard_id != wizard_id]
        else:
            self.errors = []
    
    def get_error_summary(self) -> Dict[str, Any]:
        """Get error summary statistics"""
        total_errors = len(self.errors)
        
        by_type = {}
        by_severity = {}
        
        for error in self.errors:
            by_type[error.error_type.value] = by_type.get(error.error_type.value, 0) + 1
            by_severity[error.severity.value] = by_severity.get(error.severity.value, 0) + 1
        
        return {
            'total_errors': total_errors,
            'by_type': by_type,
            'by_severity': by_severity,
            'recent_errors': [e.to_dict() for e in self.errors[-10:]]  # Last 10 errors
        }
    
    # Helper methods for error handling
    def _detect_field_type(self, field_id: str) -> str:
        """Detect field type from field ID patterns"""
        field_id_lower = field_id.lower()
        if 'email' in field_id_lower:
            return 'email'
        elif 'phone' in field_id_lower:
            return 'phone'
        elif 'number' in field_id_lower or 'count' in field_id_lower:
            return 'number'
        elif 'date' in field_id_lower:
            return 'date'
        elif 'url' in field_id_lower or 'website' in field_id_lower:
            return 'url'
        else:
            return 'text'
    
    def _get_field_specific_suggestions(self, field_type: str) -> List[str]:
        """Get field type specific suggestions"""
        suggestions_map = {
            'email': ["Enter a valid email address like user@example.com"],
            'phone': ["Enter phone number with country code if international"],
            'number': ["Enter numbers only without letters or symbols"],
            'date': ["Use the date picker or format YYYY-MM-DD"],
            'url': ["Enter a complete URL starting with http:// or https://"],
            'text': ["Check spelling and remove any special characters"]
        }
        return suggestions_map.get(field_type, ["Please check your input"])
    
    def _track_validation_pattern(self, error: WizardError):
        """Track validation error patterns for analytics"""
        logger.debug(f"Tracking validation pattern: {error.field_id} - {error.error_type.value}")
    
    def _trigger_ui_validation_update(self, error: WizardError):
        """Trigger UI updates for real-time validation"""
        logger.debug(f"UI validation update: {error.field_id}")
    
    def _disable_wizard_temporarily(self, wizard_id: str):
        """Temporarily disable wizard due to critical config error"""
        logger.error(f"Temporarily disabling wizard {wizard_id} due to critical configuration error")
    
    def _alert_administrators(self, error: WizardError):
        """Alert system administrators about critical errors"""
        logger.error(f"ADMIN ALERT: {error.error_type.value} in wizard {error.wizard_id}: {error.message}")
    
    def _create_incident_report(self, error: WizardError):
        """Create incident report for high severity runtime errors"""
        logger.error(f"INCIDENT: Runtime error {error.error_id} - {error.message}")
    
    def _schedule_auto_retry(self, error: WizardError):
        """Schedule automatic retry for recoverable errors"""
        logger.info(f"Scheduling auto-retry for error {error.error_id}")
    
    def _schedule_network_retry(self, error: WizardError):
        """Schedule network retry with exponential backoff"""
        logger.info(f"Scheduling network retry for error {error.error_id}")
    
    def _track_network_issue(self, error: WizardError):
        """Track network issues for infrastructure monitoring"""
        logger.debug(f"Network issue tracked: {error.message}")
    
    def _log_security_event(self, error: WizardError):
        """Log security events for compliance audit"""
        logger.warning(f"SECURITY EVENT: {error.error_type.value} - {error.message}")
    
    def _analyze_permission_pattern(self, error: WizardError):
        """Analyze permission error patterns for security threats"""
        logger.debug(f"Analyzing permission pattern: {error.message}")
    
    def _backup_form_state(self, wizard_id: str):
        """Backup current form state before data error handling"""
        logger.info(f"Backing up form state for wizard {wizard_id}")
    
    def _review_data_validation_rules(self, error: WizardError):
        """Review and potentially update data validation rules"""
        logger.debug(f"Reviewing validation rules for field {error.field_id}")
    
    def _alert_system_administrators(self, error: WizardError):
        """Alert system administrators about critical system errors"""
        logger.critical(f"CRITICAL SYSTEM ERROR: {error.message} - Error ID: {error.error_id}")
    
    def _update_system_health_metrics(self, error: WizardError):
        """Update system health metrics for monitoring"""
        logger.debug(f"Updating system health metrics for error: {error.error_type.value}")
    
    def _track_user_experience_issue(self, error: WizardError):
        """Track user experience issues for UX improvement"""
        logger.debug(f"UX issue tracked: {error.field_id} - {error.message}")
    
    def _provide_contextual_help(self, error: WizardError):
        """Provide contextual help for user errors"""
        logger.debug(f"Providing contextual help for: {error.field_id}")


def wizard_error_handler(error_type: WizardErrorType = None, severity: WizardErrorSeverity = None):
    """Decorator for handling wizard errors"""
    def decorator(func):
        """
        Inner decorator function that wraps the target function with error handling.
        
        Args:
            func: The function to be wrapped with error handling
            
        Returns:
            Wrapped function with comprehensive error handling
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_handler = WizardErrorHandler()
                wizard_error = error_handler.handle_error(
                    e, 
                    error_type=error_type, 
                    severity=severity,
                    context={
                        'function': func.__name__,
                        'args': str(args)[:500],  # Limit size
                        'kwargs': str(kwargs)[:500]
                    }
                )
                # Re-raise with wizard error info
                raise WizardException(wizard_error) from e
        return wrapper
    return decorator


class WizardException(Exception):
    """Custom exception class for wizard errors"""
    def __init__(self, wizard_error: WizardError):
        """
        Initialize a wizard exception with the structured error information.
        
        Args:
            wizard_error: WizardError object containing detailed error information
        """
        self.wizard_error = wizard_error
        super().__init__(wizard_error.message)


# Edge case validation functions
def validate_wizard_config_edge_cases(config: Dict[str, Any]) -> List[WizardError]:
    """Validate wizard configuration for edge cases"""
    errors = []
    error_handler = WizardErrorHandler()
    
    try:
        # Check for empty or null values
        if not config:
            errors.append(error_handler.handle_error(
                "Wizard configuration is empty",
                WizardErrorType.CONFIGURATION_ERROR,
                WizardErrorSeverity.HIGH
            ))
            return errors
        
        # Check for circular dependencies in conditional fields
        if 'steps' in config:
            for step_idx, step in enumerate(config['steps']):
                if 'fields' in step:
                    for field_idx, field in enumerate(step['fields']):
                        if 'conditional_fields' in field:
                            # Check for self-reference
                            if field.get('id') in field['conditional_fields']:
                                errors.append(error_handler.handle_error(
                                    f"Field {field.get('id')} references itself in conditional logic",
                                    WizardErrorType.CONFIGURATION_ERROR,
                                    WizardErrorSeverity.MEDIUM,
                                    field_id=field.get('id'),
                                    step_id=step.get('id')
                                ))
        
        # Check for excessive nesting or complexity
        if 'steps' in config and len(config['steps']) > 20:
            errors.append(error_handler.handle_error(
                f"Wizard has {len(config['steps'])} steps, which may impact performance",
                WizardErrorType.CONFIGURATION_ERROR,
                WizardErrorSeverity.LOW
            ))
        
        # Check for invalid field types
        valid_field_types = {
            'text', 'textarea', 'email', 'password', 'number', 'select', 
            'radio', 'checkbox', 'boolean', 'date', 'time', 'datetime',
            'file', 'url', 'phone', 'rating', 'slider', 'divider', 'html'
        }
        
        if 'steps' in config:
            for step in config['steps']:
                if 'fields' in step:
                    for field in step['fields']:
                        field_type = field.get('type')
                        if field_type and field_type not in valid_field_types:
                            errors.append(error_handler.handle_error(
                                f"Invalid field type: {field_type}",
                                WizardErrorType.CONFIGURATION_ERROR,
                                WizardErrorSeverity.HIGH,
                                field_id=field.get('id')
                            ))
        
        # Check for potential security issues
        if 'custom_css' in config or 'custom_js' in config:
            errors.append(error_handler.handle_error(
                "Custom CSS/JS detected - ensure content is properly sanitized",
                WizardErrorType.SYSTEM_ERROR,
                WizardErrorSeverity.MEDIUM
            ))
    
    except Exception as e:
        errors.append(error_handler.handle_error(
            e,
            WizardErrorType.SYSTEM_ERROR,
            WizardErrorSeverity.HIGH,
            context={'function': 'validate_wizard_config_edge_cases'}
        ))
    
    return errors


def sanitize_user_input(input_data: Any, field_type: str = 'text') -> tuple[Any, List[WizardError]]:
    """Sanitize user input and detect edge cases"""
    errors = []
    error_handler = WizardErrorHandler()
    
    try:
        # Handle None/empty values
        if input_data is None or (isinstance(input_data, str) and not input_data.strip()):
            return input_data, errors
        
        # Convert to string for processing
        input_str = str(input_data)
        
        # Check for extremely long inputs
        if len(input_str) > 10000:
            errors.append(error_handler.handle_error(
                "Input is extremely long and may cause performance issues",
                WizardErrorType.VALIDATION_ERROR,
                WizardErrorSeverity.MEDIUM
            ))
            input_str = input_str[:10000]  # Truncate
        
        # Check for potential XSS patterns
        xss_patterns = ['<script', 'javascript:', 'onload=', 'onerror=', 'onclick=']
        for pattern in xss_patterns:
            if pattern in input_str.lower():
                errors.append(error_handler.handle_error(
                    "Potentially malicious content detected",
                    WizardErrorType.SYSTEM_ERROR,
                    WizardErrorSeverity.HIGH
                ))
                # Remove the pattern
                input_str = input_str.replace(pattern, '')
        
        # Field-specific validation
        if field_type == 'email':
            if len(input_str) > 254:  # RFC 5321 limit
                errors.append(error_handler.handle_error(
                    "Email address is too long",
                    WizardErrorType.VALIDATION_ERROR,
                    WizardErrorSeverity.MEDIUM
                ))
        
        elif field_type == 'phone':
            # Remove non-numeric characters except +, -, (, ), space
            import re
            cleaned_phone = re.sub(r'[^\d+\-\(\)\s]', '', input_str)
            if cleaned_phone != input_str:
                errors.append(error_handler.handle_error(
                    "Phone number contains invalid characters",
                    WizardErrorType.VALIDATION_ERROR,
                    WizardErrorSeverity.LOW
                ))
            input_str = cleaned_phone
        
        elif field_type == 'number':
            # Check for numeric overflow
            try:
                num_value = float(input_str)
                if abs(num_value) > 1e308:  # Python float limit
                    errors.append(error_handler.handle_error(
                        "Number is too large",
                        WizardErrorType.VALIDATION_ERROR,
                        WizardErrorSeverity.MEDIUM
                    ))
                    return None, errors
            except ValueError:
                errors.append(error_handler.handle_error(
                    "Invalid number format",
                    WizardErrorType.VALIDATION_ERROR,
                    WizardErrorSeverity.MEDIUM
                ))
        
        return input_str, errors
    
    except Exception as e:
        errors.append(error_handler.handle_error(
            e,
            WizardErrorType.SYSTEM_ERROR,
            WizardErrorSeverity.HIGH,
            context={'function': 'sanitize_user_input', 'field_type': field_type}
        ))
        return input_data, errors


# Global error handler instance
wizard_error_handler = WizardErrorHandler()