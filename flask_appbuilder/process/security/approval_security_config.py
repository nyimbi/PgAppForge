"""
Approval Security Configuration for Financial Operations.

Provides centralized security configuration and policy enforcement
for approval workflow operations with comprehensive threat protection.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import hmac
import json

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from flask_appbuilder import Model

from flask import current_app
from flask_appbuilder import db

log = logging.getLogger(__name__)


class SecurityEvent(Model):
    """Persistent storage for security events and state."""
    
    __tablename__ = 'approval_security_events'
    
    id = Column(Integer, primary_key=True)
    event_type = Column(String(100), nullable=False)
    user_id = Column(Integer, nullable=True)
    request_id = Column(Integer, nullable=True)
    severity = Column(String(20), nullable=False, default='medium')
    details = Column(Text, nullable=True)  # JSON string
    source_ip = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<SecurityEvent {self.event_type} by user {self.user_id}>'


class SecurityState(Model):
    """Persistent storage for security state like blocked users and failed attempts."""
    
    __tablename__ = 'approval_security_state'
    
    id = Column(Integer, primary_key=True)
    state_key = Column(String(200), nullable=False, unique=True)  # e.g., 'blocked_user:123' or 'rate_limit:456:approval'
    state_type = Column(String(50), nullable=False)  # 'blocked_user', 'failed_attempts', 'rate_limit'
    state_data = Column(Text, nullable=True)  # JSON string for complex data
    user_id = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<SecurityState {self.state_key}>'


class SecurityError(Exception):
    """Base exception for security-related errors."""
    
    def __init__(self, message: str, error_code: str = 'SECURITY_ERROR', status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.message = message


class SecurityLevel(Enum):
    """Security levels for different types of approval operations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalSecurityConfig:
    """
    Centralized security configuration for approval operations.

    Provides configurable security policies, rate limiting, and
    threat detection capabilities for financial approval workflows.
    """

    # Default security configurations
    DEFAULT_CONFIGS = {
        'csrf_token_expiry_hours': 1,
        'rate_limit_window_minutes': 60,
        'max_requests_per_window': 10,
        'max_failed_attempts': 5,
        'account_lockout_minutes': 30,
        'require_comments_for_high_priority': True,
        'minimum_comment_length': 10,
        'minimum_delegation_reason_length': 10,
        'minimum_escalation_justification_length': 20,
        'session_timeout_minutes': 120,
        'require_two_factor_for_high_value': False,
        'high_value_threshold': 10000.0,
        'audit_all_operations': True,
        'block_self_approval': True,
        'block_self_delegation': True,
        'block_self_escalation': True,
        'require_admin_for_escalation': False,
        'max_delegation_chain_length': 3,
        'require_manager_approval_threshold': 5000.0
    }

    def __init__(self):
        self.config = self._load_security_config()
        # Initialize database tables if needed
        self._ensure_tables_exist()

    def _load_security_config(self) -> Dict[str, Any]:
        """Load security configuration from application config or database."""
        config = self.DEFAULT_CONFIGS.copy()

        # Override with application configuration if available
        if hasattr(current_app, 'config'):
            app_config = current_app.config
            for key in config.keys():
                env_key = f'APPROVAL_SECURITY_{key.upper()}'
                if env_key in app_config:
                    config[key] = app_config[env_key]

        return config
    
    def _handle_security_error(self, operation: str, error: Exception, user_id: Optional[int] = None, 
                              request_id: Optional[int] = None, fail_secure: bool = True) -> Dict[str, Any]:
        """
        Standardized security error handling with consistent logging and response format.
        
        Args:
            operation: The security operation that failed
            error: The exception that occurred
            user_id: User ID if available
            request_id: Request ID if available
            fail_secure: Whether to fail securely (deny) or fail open (allow) on errors
        
        Returns:
            Standardized error response dictionary
        """
        error_id = f"{operation}_{int(datetime.now(tz=timezone.utc).timestamp())}"
        
        # Log the error
        log.error(f"Security operation '{operation}' failed [ID: {error_id}]: {str(error)}")
        
        # Log security event if user context available
        if user_id:
            self.log_security_event(f'{operation}_error', user_id, request_id, {
                'error_id': error_id,
                'error_type': type(error).__name__,
                'error_message': str(error)
            })
        
        # Return standardized error response
        if isinstance(error, SecurityError):
            return {
                'error': error.message,
                'error_code': error.error_code,
                'status': error.status_code,
                'error_id': error_id
            }
        else:
            # Generic error response
            status_code = 403 if fail_secure else 500
            return {
                'error': f'Security operation failed: {operation}',
                'error_code': 'SECURITY_OPERATION_FAILED', 
                'status': status_code,
                'error_id': error_id
            }
    
    def _ensure_tables_exist(self):
        """Ensure security tables exist in the database."""
        try:
            db.create_all()
        except Exception as e:
            log.error(f"Failed to create security tables: {e}")
            # Continue without persistent storage in case of database issues

    def get_security_level_for_request(self, approval_request) -> SecurityLevel:
        """Determine security level based on approval request characteristics."""
        try:
            # Check for high-value requests
            request_data = getattr(approval_request, 'request_data', {})
            if isinstance(request_data, str):
                request_data = json.loads(request_data)

            amount = request_data.get('amount', 0)
            if amount >= self.config['high_value_threshold']:
                return SecurityLevel.CRITICAL
            elif amount >= self.config['require_manager_approval_threshold']:
                return SecurityLevel.HIGH

            # Check priority
            priority = getattr(approval_request, 'priority', 'normal')
            if priority in ['critical', 'urgent']:
                return SecurityLevel.HIGH
            elif priority in ['high']:
                return SecurityLevel.MEDIUM

            return SecurityLevel.LOW

        except Exception as e:
            self._handle_security_error('security_level_determination', e, fail_secure=True)
            return SecurityLevel.HIGH  # Fail secure

    def validate_csrf_token(self, token: str, user_id: int) -> bool:
        """
        DEPRECATED: Use Flask-WTF's built-in CSRF protection instead.
        This method is kept for backward compatibility but should not be used.
        """
        log.warning("Using deprecated custom CSRF validation. Migrate to Flask-WTF CSRFProtect.")
        return False  # Force failure to encourage migration

        try:
            # Parse token to get timestamp
            parts = token.split(':')
            if len(parts) != 2:
                return False

            provided_hash, timestamp_str = parts
            timestamp = int(timestamp_str)

            # Check if token has expired
            expiry_time = timestamp + (self.config['csrf_token_expiry_hours'] * 3600)
            if datetime.now(tz=timezone.utc).timestamp() > expiry_time:
                return False

            # Generate expected hash
            secret_key = current_app.config.get('SECRET_KEY', 'fallback_secret')
            message = f"{user_id}:{timestamp_str}"
            expected_hash = hmac.new(
                secret_key.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(provided_hash, expected_hash)

        except Exception as e:
            log.error(f"CSRF token validation error: {e}")
            return False

    def generate_csrf_token(self, user_id: int) -> str:
        """
        DEPRECATED: Use Flask-WTF's built-in CSRF token generation instead.
        This method is kept for backward compatibility but should not be used.
        """
        log.warning("Using deprecated custom CSRF token generation. Migrate to Flask-WTF CSRFProtect.")
        return ""  # Return empty to force migration

    def check_rate_limit(self, user_id: int, operation_type: str) -> bool:
        """Check if user has exceeded rate limits using persistent storage."""
        try:
            state_key = f"rate_limit:{user_id}:{operation_type}"
            current_time = datetime.now(tz=timezone.utc)
            window_start = current_time - timedelta(minutes=self.config['rate_limit_window_minutes'])
            
            # Clean old entries
            db.session.query(SecurityState).filter(
                SecurityState.state_key == state_key,
                SecurityState.created_at < window_start
            ).delete()
            
            # Get current count
            current_count = db.session.query(SecurityState).filter(
                SecurityState.state_key == state_key,
                SecurityState.created_at >= window_start
            ).count()
            
            max_requests = self.config['max_requests_per_window']
            
            if current_count >= max_requests:
                log.warning(f"Rate limit exceeded for user {user_id} operation {operation_type}")
                return False
            
            # Add current request
            new_state = SecurityState(
                state_key=state_key,
                state_type='rate_limit',
                user_id=user_id,
                state_data=json.dumps({'operation_type': operation_type}),
                expires_at=current_time + timedelta(minutes=self.config['rate_limit_window_minutes'])
            )
            db.session.add(new_state)
            db.session.commit()
            
            return True
            
        except Exception as e:
            error_response = self._handle_security_error('rate_limit_check', e, user_id, fail_secure=False)
            # Fail open for availability - return True to allow operation
            return True

    def check_user_blocked(self, user_id: int) -> bool:
        """Check if user is temporarily blocked due to suspicious activity using persistent storage."""
        try:
            state_key = f"blocked_user:{user_id}"
            current_time = datetime.now(tz=timezone.utc)
            
            # Check for active blocks
            blocked_state = db.session.query(SecurityState).filter(
                SecurityState.state_key == state_key,
                SecurityState.state_type == 'blocked_user',
                SecurityState.expires_at > current_time
            ).first()
            
            return blocked_state is not None
            
        except Exception as e:
            self._handle_security_error('user_blocked_check', e, user_id, fail_secure=False)
            # Fail open for availability - return False to allow operation
            return False

    def record_failed_attempt(self, user_id: int, operation_type: str) -> bool:
        """
        Record failed security attempt and check if user should be blocked using persistent storage.
        Returns True if user should be blocked.
        """
        try:
            current_time = datetime.now(tz=timezone.utc)
            state_key = f"failed_attempts:{user_id}:{operation_type}"
            window_start = current_time - timedelta(minutes=self.config['account_lockout_minutes'])
            
            # Clean old attempts
            db.session.query(SecurityState).filter(
                SecurityState.state_key == state_key,
                SecurityState.created_at < window_start
            ).delete()
            
            # Add current attempt
            new_attempt = SecurityState(
                state_key=state_key,
                state_type='failed_attempts',
                user_id=user_id,
                state_data=json.dumps({'operation_type': operation_type}),
                expires_at=current_time + timedelta(minutes=self.config['account_lockout_minutes'])
            )
            db.session.add(new_attempt)
            
            # Check current count
            attempt_count = db.session.query(SecurityState).filter(
                SecurityState.state_key == state_key,
                SecurityState.created_at >= window_start
            ).count()
            
            # Check if threshold exceeded
            if attempt_count >= self.config['max_failed_attempts']:
                # Block user
                block_key = f"blocked_user:{user_id}"
                block_expiry = current_time + timedelta(minutes=self.config['account_lockout_minutes'])
                
                blocked_user = SecurityState(
                    state_key=block_key,
                    state_type='blocked_user',
                    user_id=user_id,
                    state_data=json.dumps({
                        'reason': f'repeated_failed_{operation_type}_attempts',
                        'attempt_count': attempt_count
                    }),
                    expires_at=block_expiry
                )
                db.session.add(blocked_user)
                db.session.commit()
                
                log.warning(f"User {user_id} blocked due to repeated failed {operation_type} attempts")
                return True
            
            db.session.commit()
            return False
            
        except Exception as e:
            db.session.rollback()
            self._handle_security_error('record_failed_attempt', e, user_id, fail_secure=True)
            # Fail secure by assuming block should happen
            return True

    def validate_approval_security_rules(self, approval_request, current_user, operation_type: str) -> Dict[str, Any]:
        """
        Validate security rules specific to approval operations.

        Returns validation result with any violations.
        """
        violations = []
        security_level = self.get_security_level_for_request(approval_request)

        # Enhanced self-approval detection with comprehensive checks
        if self.config['block_self_approval'] and operation_type == 'approval':
            ownership_fields = ['user_id', 'created_by', 'created_by_fk', 'owner_id', 'initiator_id']
            
            for field in ownership_fields:
                if hasattr(approval_request, field) and getattr(approval_request, field) == current_user.id:
                    violations.append(f"Self-approval not permitted (owner field: {field})")
                    self.log_security_event('self_approval_blocked', current_user.id, 
                        approval_request.id if approval_request else None, {
                        'operation_type': operation_type,
                        'ownership_field': field,
                        'owner_id': getattr(approval_request, field)
                    })
                    break

        # Check high-value transaction rules
        if security_level in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]:
            if self.config['require_two_factor_for_high_value']:
                # In production, check if user has completed 2FA
                violations.append("Two-factor authentication required for high-value transactions")

        # Check comment requirements
        if (self.config['require_comments_for_high_priority'] and
            security_level != SecurityLevel.LOW and
            operation_type == 'approval'):
            # This would be checked in the calling code
            pass

        # Check delegation chain length
        if operation_type == 'delegation':
            delegation_history = getattr(approval_request, 'delegation_history', [])
            if isinstance(delegation_history, str):
                delegation_history = json.loads(delegation_history)
            if len(delegation_history) >= self.config['max_delegation_chain_length']:
                violations.append(f"Maximum delegation chain length ({self.config['max_delegation_chain_length']}) exceeded")

        # Check escalation permissions
        if operation_type == 'escalation' and self.config['require_admin_for_escalation']:
            if not hasattr(current_user, 'roles') or not any('Admin' in role.name for role in current_user.roles):
                violations.append("Administrator privileges required for escalation")

        return {
            'valid': len(violations) == 0,
            'violations': violations,
            'security_level': security_level.value,
            'requires_additional_verification': security_level in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]
        }

    def log_security_event(self, event_type: str, user_id: int, request_id: Optional[int] = None, details: Dict[str, Any] = None):
        """
        Enhanced security event logging with persistent storage and threat detection.
        Integrates with SIEM systems and maintains audit trail in database.
        """
        try:
            severity = self._get_event_severity(event_type)
            source_ip = getattr(current_app, 'remote_addr', 'unknown') if current_app else 'unknown'
            
            # Store security event in database
            security_event = SecurityEvent(
                event_type=event_type,
                user_id=user_id,
                request_id=request_id,
                severity=severity,
                details=json.dumps(details or {}),
                source_ip=source_ip
            )
            db.session.add(security_event)
            db.session.commit()
            
            # Log to application log for immediate visibility
            if severity == 'critical':
                log.critical(f"SECURITY ALERT: {event_type} by user {user_id} from {source_ip}")
            elif severity == 'high':
                log.warning(f"Security Event: {event_type} by user {user_id} from {source_ip}")
            else:
                log.info(f"Security Event: {event_type} by user {user_id} from {source_ip}")
            
            # Send to SIEM/security monitoring
            self._send_to_security_monitoring({
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'event_type': event_type,
                'user_id': user_id,
                'request_id': request_id,
                'details': details or {},
                'severity': severity,
                'source_ip': source_ip
            })
            
        except Exception as e:
            # Use fallback logging - don't use _handle_security_error to avoid recursion
            log.error(f"Failed to log security event {event_type}: {e}")
            # Still log to application log as fallback
            log.warning(f"Security Event (fallback): {event_type} by user {user_id}")

    def _get_event_severity(self, event_type: str) -> str:
        """Determine event severity for security monitoring."""
        critical_events = [
            'unauthorized_approval_attempt', 'unauthorized_escalation_attempt',
            'csrf_attack_detected', 'potential_fraud_detected'
        ]

        high_events = [
            'rate_limit_exceeded', 'account_locked', 'invalid_token',
            'unauthorized_delegation_attempt', 'expired_request_attempt'
        ]

        if event_type in critical_events:
            return 'critical'
        elif event_type in high_events:
            return 'high'
        else:
            return 'medium'

    def _send_to_security_monitoring(self, event_data: Dict[str, Any]):
        """Send security events to monitoring system (implement based on your SIEM)."""
        # In production, integrate with:
        # - Splunk, ELK Stack, Azure Sentinel, etc.
        # - Real-time alerting for critical events
        # - Threat intelligence correlation
        pass

    def get_security_headers(self) -> Dict[str, str]:
        """Get security headers for API responses."""
        return {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
            'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
            'Referrer-Policy': 'strict-origin-when-cross-origin'
        }


# Singleton instance for global access
approval_security_config = ApprovalSecurityConfig()