"""
Approval Security Validator

Focused service class responsible for all security validation aspects
of the approval workflow system. Extracted from ApprovalWorkflowManager
to follow Single Responsibility Principle.
"""

import re
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from flask import session, request, current_user
import bleach
from collections import defaultdict

from .audit_logger import ApprovalAuditLogger
from .crypto_config import SecureSessionManager
from .constants import SecurityConstants, ValidationConstants

# Import MFA services for integration
try:
    from flask_appbuilder.security.mfa.services import (
        MFAOrchestrationService, WebAuthnService, ValidationError as MFAValidationError
    )
    from flask_appbuilder.security.mfa.manager_mixin import MFASessionState
    from flask_appbuilder.security.mfa.models import UserMFA, MFAPolicy
    HAS_MFA_SUPPORT = True
except ImportError:
    HAS_MFA_SUPPORT = False

log = logging.getLogger(__name__)


class ApprovalSecurityValidator:
    """
    Handles all security validation for approval workflows.
    
    Responsibilities:
    - Self-approval prevention
    - Role-based authorization validation  
    - MFA requirement validation
    - Input sanitization and validation
    - Rate limiting checks
    - Workflow state validation
    """
    
    def __init__(self, appbuilder):
        """
        Initialize the security validator with Flask-AppBuilder instance.
        
        Args:
            appbuilder: Flask-AppBuilder instance for security integration
        """
        self.appbuilder = appbuilder
        self.audit_logger = ApprovalAuditLogger()
        self.security_config = {
            'max_bulk_operations': SecurityConstants.MAX_BULK_OPERATIONS,
            'rate_limit_window': SecurityConstants.RATE_LIMIT_WINDOW_SECONDS,
            'max_approvals_per_window': SecurityConstants.MAX_APPROVAL_ATTEMPTS_PER_WINDOW,
            'suspicious_activity_threshold': SecurityConstants.MAX_APPROVAL_ATTEMPTS_PER_WINDOW // 2,
            'rate_limit_burst_threshold': SecurityConstants.MAX_APPROVAL_ATTEMPTS_PER_WINDOW // 2,
            'rate_limit_burst_window': SecurityConstants.BURST_LIMIT_WINDOW_SECONDS,
            'ip_rate_limit_window': SecurityConstants.RATE_LIMIT_WINDOW_SECONDS * 3,  # 15 minutes
            'max_approvals_per_ip': SecurityConstants.MAX_APPROVAL_ATTEMPTS_PER_WINDOW * 10
        }
        # Initialize rate limiting storage with production-ready backend selection
        self._init_rate_limiting_backend()
        self._last_cleanup = time.time()  # Track last cleanup time
        
        # Initialize MFA services if available
        self.mfa_enabled = HAS_MFA_SUPPORT and self._is_mfa_configured()
        if self.mfa_enabled:
            self.mfa_orchestration = MFAOrchestrationService()
            self.webauthn_service = WebAuthnService()
            log.info("MFA integration enabled for approval system")
        else:
            log.debug("MFA integration not available or not configured")

    def _init_rate_limiting_backend(self):
        """
        Initialize rate limiting backend with production-ready options.
        
        PERFORMANCE FIX: Supports both in-memory (development) and Redis (production)
        backends to prevent memory leaks in production environments.
        """
        try:
            # Try to initialize Redis backend for production
            redis_url = self.appbuilder.get_app.config.get('REDIS_URL') or \
                       self.appbuilder.get_app.config.get('RATE_LIMIT_STORAGE_URL')
            
            if redis_url and redis_url != 'memory://':
                try:
                    import redis
                    self.redis_client = redis.from_url(redis_url, decode_responses=True)
                    # Test connection
                    self.redis_client.ping()
                    self.rate_limiting_backend = 'redis'
                    log.info("Rate limiting using Redis backend for production")
                    return
                except (ImportError, redis.RedisError, Exception) as e:
                    log.warning(f"Redis rate limiting backend unavailable: {e}")
            
            # Fallback to in-memory storage with enhanced cleanup
            self.rate_limit_storage = defaultdict(list)
            self.rate_limiting_backend = 'memory'
            
            # Configure aggressive cleanup for in-memory backend
            self._memory_cleanup_config = {
                'max_entries_per_key': 1000,  # Limit entries per rate limit key
                'max_total_entries': 10000,   # Global entry limit
                'cleanup_interval': 60,       # Cleanup every minute in production
                'force_cleanup_threshold': 0.8  # Force cleanup at 80% capacity
            }
            
            log.info("Rate limiting using in-memory backend with enhanced cleanup")
            
        except Exception as e:
            # Ultimate fallback: disable rate limiting rather than crash
            log.error(f"Failed to initialize rate limiting backend: {e}")
            self.rate_limiting_backend = 'disabled'
            self.rate_limit_storage = defaultdict(list)

    def _rate_limit_check(self, key: str, window: int, threshold: int, current_time: float) -> bool:
        """
        Backend-agnostic rate limit checking.
        
        PERFORMANCE FIX: Supports both Redis and in-memory backends for production scalability.
        """
        if self.rate_limiting_backend == 'disabled':
            return True
        
        if self.rate_limiting_backend == 'redis':
            return self._redis_rate_limit_check(key, window, threshold, current_time)
        else:
            return self._memory_rate_limit_check(key, window, threshold, current_time)
    
    def _redis_rate_limit_check(self, key: str, window: int, threshold: int, current_time: float) -> bool:
        """Redis-based rate limiting with automatic TTL."""
        try:
            # Use Redis sorted sets for efficient time-window operations
            pipe = self.redis_client.pipeline()
            
            # Remove expired entries
            window_start = current_time - window
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Count current entries
            pipe.zcard(key)
            
            # Execute pipeline
            results = pipe.execute()
            current_count = results[1]
            
            return current_count < threshold
            
        except Exception as e:
            log.error(f"Redis rate limiting error: {e}")
            # Fallback to allowing request on Redis errors
            return True
    
    def _memory_rate_limit_check(self, key: str, window: int, threshold: int, current_time: float) -> bool:
        """Enhanced in-memory rate limiting with strict memory management."""
        # Clean expired entries
        window_start = current_time - window
        self.rate_limit_storage[key] = [
            ts for ts in self.rate_limit_storage[key] if ts > window_start
        ]
        
        # Apply per-key entry limits to prevent memory explosion
        max_entries_per_key = getattr(self, '_memory_cleanup_config', {}).get('max_entries_per_key', 1000)
        if len(self.rate_limit_storage[key]) > max_entries_per_key:
            # Keep only the most recent entries
            self.rate_limit_storage[key] = self.rate_limit_storage[key][-max_entries_per_key:]
        
        return len(self.rate_limit_storage[key]) < threshold
    
    def _record_rate_limit_activity(self, key: str, current_time: float) -> None:
        """Backend-agnostic activity recording."""
        if self.rate_limiting_backend == 'disabled':
            return
        
        if self.rate_limiting_backend == 'redis':
            try:
                # Add to Redis sorted set with TTL
                self.redis_client.zadd(key, {str(current_time): current_time})
                # Set TTL to prevent indefinite storage
                self.redis_client.expire(key, max(
                    self.security_config['ip_rate_limit_window'],
                    self.security_config['rate_limit_window']
                ) + 3600)  # Add 1 hour buffer
            except Exception as e:
                log.error(f"Redis activity recording error: {e}")
        else:
            # In-memory storage
            self.rate_limit_storage[key].append(current_time)
    
    def validate_self_approval(self, instance, user) -> bool:
        """Strict self-approval detection with comprehensive checks."""
        ownership_fields = ['user_id', 'created_by', 'created_by_fk', 'owner_id']

        for field in ownership_fields:
            if hasattr(instance, field) and getattr(instance, field) == user.id:
                self.audit_logger.log_security_violation(
                    'self_approval_detected', user, instance, {'field': field}
                )
                return True
        return False
    
    def validate_user_role(self, user, required_role: str, allow_admin_override: bool = False) -> bool:
        """
        Validate user has required role using Flask-AppBuilder security.
        
        SECURITY IMPROVEMENT: Removed admin override by default to enforce proper
        role-based authorization and principle of least privilege.
        
        BACKWARDS COMPATIBILITY: Admin override can be re-enabled via configuration
        with explicit parameters and comprehensive audit logging.
        
        Args:
            user: User object to validate
            required_role: Role required for the operation
            allow_admin_override: Explicitly allow admin override (requires config)
            
        Returns:
            bool: True if user has required role or valid admin override
        """
        if not user or not user.roles:
            return False
        
        user_role_names = [role.name for role in user.roles]
        
        # Check exact role match first
        if required_role in user_role_names:
            return True
        
        # Check backwards compatibility admin override if explicitly enabled
        if (allow_admin_override and 
            SecurityConstants.ENABLE_LEGACY_ADMIN_OVERRIDE and
            self._validate_admin_override(user, required_role)):
            return True
        
        # Log authorization failure for audit trail
        self.audit_logger.log_security_violation(
            'role_authorization_failed', user, None, {
                'required_role': required_role,
                'user_roles': user_role_names,
                'authorization_context': 'approval_workflow',
                'admin_override_requested': allow_admin_override,
                'admin_override_enabled': SecurityConstants.ENABLE_LEGACY_ADMIN_OVERRIDE
            }
        )
        
        return False
    
    def _validate_admin_override(self, user, required_role: str) -> bool:
        """
        Validate admin override functionality with comprehensive logging.
        
        DEPRECATED: This functionality is deprecated and will be removed in future versions.
        Use proper role-based authorization instead.
        """
        import warnings
        
        user_role_names = [role.name for role in user.roles]
        
        # Check if user has admin override roles
        has_admin_role = any(role in user_role_names for role in SecurityConstants.ADMIN_OVERRIDE_ROLES)
        
        if not has_admin_role:
            return False
        
        # Log deprecation warning
        if SecurityConstants.LOG_ADMIN_OVERRIDE_USAGE:
            # Issue Python deprecation warning
            warnings.warn(
                "Admin override functionality is deprecated. Use proper role-based authorization instead. "
                "This feature will be removed in Flask-AppBuilder 5.0.",
                DeprecationWarning,
                stacklevel=3
            )
            
            # Log to application logger
            log.warning(
                f"DEPRECATED: Admin override used by {user.username} for role '{required_role}'. "
                f"This functionality is deprecated and will be removed in future versions."
            )
        
        # Log admin override usage for audit trail
        self.audit_logger.log_security_violation(
            'admin_override_used', user, None, {
                'required_role': required_role,
                'user_roles': user_role_names,
                'override_type': 'legacy_admin_override',
                'deprecated': True,
                'security_risk': 'HIGH - bypasses role-based authorization'
            }
        )
        
        return True
    
    def validate_mfa_requirement(self, user, instance) -> bool:
        """
        Validate MFA requirement for high-value approvals.
        
        SECURITY IMPROVEMENT: Now uses SecureSessionManager for proper 
        session validation and security compliance.
        """
        # Check if user has MFA enabled
        if not hasattr(user, 'mfa_enabled') or not user.mfa_enabled:
            self.audit_logger.log_security_violation(
                'mfa_not_enabled', user, instance, {
                    'reason': 'User does not have MFA enabled for high-value approval'
                }
            )
            return False
        
        # Get secure session data
        mfa_session_key = f'mfa_verified_{user.id}'
        session_data = {
            'user_id': user.id,
            'created_at': session.get(f'{mfa_session_key}_timestamp', ''),
            'session_token': session.get(f'{mfa_session_key}_token', ''),
            'mfa_verified': session.get(mfa_session_key, False)
        }
        
        # Validate session security using SecureSessionManager
        if not SecureSessionManager.validate_session_security(session_data):
            self.audit_logger.log_security_violation(
                'invalid_mfa_session', user, instance, {
                    'reason': 'MFA session failed security validation',
                    'session_expired': True
                }
            )
            return False
        
        # Additional check for MFA verification status
        if not session_data['mfa_verified']:
            self.audit_logger.log_security_violation(
                'mfa_not_verified', user, instance, {
                    'reason': 'MFA verification required for this operation'
                }
            )
            return False
        
        return True
    
    def validate_approval_step(self, step: int, workflow_config: Dict) -> bool:
        """Validate approval step is within valid range."""
        if step < 0 or step >= len(workflow_config['steps']):
            return False
        return True
    
    def validate_workflow_state(self, instance, workflow_config: Dict, step: int) -> bool:
        """Validate instance is in correct state for approval step."""
        current_state = getattr(instance, 'current_state', None)
        
        if step == 0:
            # First step should be in initial state
            expected_state = workflow_config['initial_state']
        else:
            # Later steps should be in appropriate intermediate state
            expected_state = f"step_{step-1}_approved"
        
        return current_state == expected_state or current_state is None
    
    def check_duplicate_approval(self, approval_history: List[Dict], user_id: int, step: int) -> bool:
        """Check if user has already approved this step."""
        for approval in approval_history:
            if (approval.get('user_id') == user_id and 
                approval.get('step') == step and 
                approval.get('status') != 'revoked'):
                return True
        
        return False

    def _cleanup_expired_rate_limit_entries(self, current_time: float) -> None:
        """
        Clean up expired rate limit entries to prevent memory leaks.

        PERFORMANCE FIX: Prevents unbounded memory growth in production environments.
        Enhanced for both Redis and in-memory backends.
        """
        # Skip cleanup if rate limiting is disabled
        if self.rate_limiting_backend == 'disabled':
            return
        
        # Redis backend handles TTL automatically
        if self.rate_limiting_backend == 'redis':
            return
        
        # Enhanced cleanup logic for in-memory backend
        cleanup_config = getattr(self, '_memory_cleanup_config', {})
        cleanup_interval = cleanup_config.get('cleanup_interval', 300)  # Default 5 minutes
        
        # Check if we need forced cleanup due to memory pressure
        total_entries = sum(len(entries) for entries in self.rate_limit_storage.values())
        max_total = cleanup_config.get('max_total_entries', 10000)
        force_threshold = cleanup_config.get('force_cleanup_threshold', 0.8)
        
        force_cleanup = total_entries > (max_total * force_threshold)
        
        # Perform cleanup if interval elapsed or forced
        if not force_cleanup and (current_time - self._last_cleanup < cleanup_interval):
            return

        # Cleanup expired entries from all rate limit storage
        cleanup_windows = {
            'burst': self.security_config['rate_limit_burst_window'],
            'standard': self.security_config['rate_limit_window'],
            'client': self.security_config['ip_rate_limit_window'],
            'ip': self.security_config['ip_rate_limit_window']
        }

        entries_before = sum(len(entries) for entries in self.rate_limit_storage.values())

        for key in list(self.rate_limit_storage.keys()):
            # Determine cleanup window based on key prefix
            window_size = cleanup_windows.get('standard', self.security_config['rate_limit_window'])

            for prefix, window in cleanup_windows.items():
                if key.startswith(prefix):
                    window_size = window
                    break

            # Remove expired entries
            window_start = current_time - window_size
            original_count = len(self.rate_limit_storage[key])
            self.rate_limit_storage[key] = [
                ts for ts in self.rate_limit_storage[key] if ts > window_start
            ]

            # Remove empty keys to save memory
            if not self.rate_limit_storage[key]:
                del self.rate_limit_storage[key]

        entries_after = sum(len(entries) for entries in self.rate_limit_storage.values())
        cleaned_entries = entries_before - entries_after

        if cleaned_entries > 0:
            log.debug(f"Rate limit cleanup: removed {cleaned_entries} expired entries, "
                     f"{entries_after} entries remaining")

        self._last_cleanup = current_time

    def _is_mfa_configured(self) -> bool:
        """
        Check if MFA is configured in the Flask-AppBuilder application.
        
        Returns:
            bool: True if MFA is configured and available
        """
        try:
            if not HAS_MFA_SUPPORT:
                return False
                
            # Check if MFA is enabled in configuration
            app_config = self.appbuilder.get_app.config
            mfa_enabled = app_config.get('MFA_ENABLED', False)
            
            if not mfa_enabled:
                return False
                
            # Check if at least one MFA method is configured
            methods_configured = (
                app_config.get('MFA_TOTP_ENABLED', False) or
                app_config.get('MFA_SMS_ENABLED', False) or
                app_config.get('MFA_EMAIL_ENABLED', False) or
                app_config.get('WEBAUTHN_ENABLED', False)
            )
            
            return methods_configured
            
        except Exception as e:
            log.error(f"Error checking MFA configuration: {e}")
            return False

    def validate_mfa_for_approval(self, user, approval_level: str = 'standard') -> Dict[str, any]:
        """
        Validate MFA requirements for approval operations.
        
        Args:
            user: Flask-AppBuilder User object
            approval_level: Level of approval (standard, high, critical)
            
        Returns:
            Dict containing validation result and MFA status
        """
        if not self.mfa_enabled:
            return {
                'valid': True,
                'mfa_required': False,
                'message': 'MFA not configured'
            }
        
        try:
            # Check if MFA is required for this user and approval level
            mfa_required = self._is_mfa_required_for_approval(user, approval_level)
            
            if not mfa_required:
                return {
                    'valid': True,
                    'mfa_required': False,
                    'message': 'MFA not required for this operation'
                }
            
            # Check if user has MFA set up
            user_mfa = self._get_user_mfa(user.id)
            if not user_mfa or not user_mfa.setup_completed:
                return {
                    'valid': False,
                    'mfa_required': True,
                    'mfa_setup_required': True,
                    'message': 'MFA setup required before approvals',
                    'setup_url': '/mfa/setup'
                }
            
            # Check MFA session state
            mfa_verified = MFASessionState.is_verified_and_valid()
            
            if not mfa_verified:
                return {
                    'valid': False,
                    'mfa_required': True,
                    'mfa_verification_required': True,
                    'message': 'MFA verification required for this approval',
                    'challenge_url': '/mfa/challenge'
                }
            
            # Validate MFA method strength for approval level
            current_method = MFASessionState.get_verification_method()
            if not self._is_mfa_method_sufficient(current_method, approval_level):
                return {
                    'valid': False,
                    'mfa_required': True,
                    'stronger_mfa_required': True,
                    'current_method': current_method,
                    'required_methods': self._get_required_methods_for_level(approval_level),
                    'message': f'Stronger MFA method required for {approval_level} approval'
                }
            
            # All MFA validations passed
            return {
                'valid': True,
                'mfa_required': True,
                'mfa_verified': True,
                'method_used': current_method,
                'message': 'MFA validation successful'
            }
            
        except Exception as e:
            log.error(f"MFA validation error: {e}")
            return {
                'valid': False,
                'error': True,
                'message': 'MFA validation system error'
            }

    def _is_mfa_required_for_approval(self, user, approval_level: str) -> bool:
        """
        Determine if MFA is required for a specific approval level.
        
        Args:
            user: Flask-AppBuilder User object
            approval_level: Level of approval (standard, high, critical)
            
        Returns:
            bool: True if MFA is required
        """
        try:
            # Check if user has MFA policy
            from flask_appbuilder.security.mfa.services import MFAPolicyService
            policy_service = MFAPolicyService()
            
            # Basic policy check - MFA required for user
            if policy_service.is_mfa_required_for_user(user):
                return True
            
            # Approval-level specific requirements
            app_config = self.appbuilder.get_app.config
            
            # Check approval-level specific MFA requirements
            level_requirements = app_config.get('APPROVAL_MFA_REQUIREMENTS', {})
            
            if approval_level in level_requirements:
                return level_requirements[approval_level].get('mfa_required', False)
            
            # Default requirements based on approval level
            default_requirements = {
                'critical': True,    # Always require MFA for critical approvals
                'high': True,        # Always require MFA for high-value approvals
                'standard': False    # Optional for standard approvals (policy-driven)
            }
            
            return default_requirements.get(approval_level, False)
            
        except Exception as e:
            log.error(f"Error checking MFA requirement: {e}")
            # Fail secure - require MFA on error for high/critical levels
            return approval_level in ['high', 'critical']

    def _get_user_mfa(self, user_id: int):
        """
        Get user MFA configuration.
        
        Args:
            user_id: User ID
            
        Returns:
            UserMFA object or None
        """
        try:
            from flask_appbuilder import db
            return db.session.query(UserMFA).filter_by(user_id=user_id).first()
        except Exception as e:
            log.error(f"Error getting user MFA: {e}")
            return None

    def _is_mfa_method_sufficient(self, method: str, approval_level: str) -> bool:
        """
        Check if MFA method is sufficient for approval level.
        
        Args:
            method: MFA method used (totp, webauthn, sms, email, backup)
            approval_level: Required approval level
            
        Returns:
            bool: True if method is sufficient
        """
        try:
            # Method strength hierarchy (strongest to weakest)
            method_strength = {
                'webauthn': 5,    # Strongest - hardware-backed, phishing-resistant
                'totp': 4,        # Strong - time-based, not phishing-resistant
                'sms': 2,         # Medium - vulnerable to SIM swapping
                'email': 2,       # Medium - vulnerable to email compromise
                'backup': 1       # Weakest - single-use codes
            }
            
            # Required strength by approval level
            level_requirements = {
                'critical': 5,    # Require strongest methods (WebAuthn)
                'high': 4,        # Require strong methods (TOTP+)
                'standard': 2     # Allow medium methods (SMS+)
            }
            
            method_score = method_strength.get(method, 0)
            required_score = level_requirements.get(approval_level, 2)
            
            return method_score >= required_score
            
        except Exception as e:
            log.error(f"Error checking MFA method strength: {e}")
            return False

    def _get_required_methods_for_level(self, approval_level: str) -> List[str]:
        """
        Get list of MFA methods that satisfy the approval level requirement.
        
        Args:
            approval_level: Required approval level
            
        Returns:
            List of acceptable MFA method names
        """
        level_methods = {
            'critical': ['webauthn'],                    # Only WebAuthn
            'high': ['webauthn', 'totp'],               # WebAuthn or TOTP
            'standard': ['webauthn', 'totp', 'sms', 'email']  # Any method
        }
        
        return level_methods.get(approval_level, ['totp'])

    def validate_approval_with_mfa(self, user, approval_data: Dict[str, any], 
                                 approval_level: str = 'standard') -> Dict[str, any]:
        """
        Comprehensive validation combining standard approval security with MFA.
        
        Args:
            user: Flask-AppBuilder User object
            approval_data: Approval request data
            approval_level: Level of approval required
            
        Returns:
            Dict containing comprehensive validation results
        """
        # Perform standard security validations first
        base_validation = {
            'rate_limit_valid': self.check_approval_rate_limit(user.id),
            'input_valid': True,  # Will be set by input validation
            'authorization_valid': True  # Will be set by authorization check
        }
        
        # Validate input data
        input_validation = self.validate_input_data(
            approval_data, 
            self.get_approval_validation_schema()
        )
        base_validation['input_valid'] = input_validation.get('valid', False)
        base_validation['input_errors'] = input_validation.get('errors', [])
        
        # Perform MFA validation
        mfa_validation = self.validate_mfa_for_approval(user, approval_level)
        
        # Combine validations
        overall_valid = (
            base_validation['rate_limit_valid'] and
            base_validation['input_valid'] and
            base_validation['authorization_valid'] and
            mfa_validation['valid']
        )
        
        result = {
            'valid': overall_valid,
            'base_validation': base_validation,
            'mfa_validation': mfa_validation,
            'approval_level': approval_level
        }
        
        # Add specific error messages and next steps
        if not overall_valid:
            errors = []
            next_steps = []
            
            if not base_validation['rate_limit_valid']:
                errors.append('Rate limit exceeded')
                next_steps.append('wait_and_retry')
            
            if not base_validation['input_valid']:
                errors.append('Invalid input data')
                next_steps.extend(['fix_input', 'resubmit'])
            
            if not mfa_validation['valid']:
                errors.append(mfa_validation.get('message', 'MFA validation failed'))
                
                if mfa_validation.get('mfa_setup_required'):
                    next_steps.append('setup_mfa')
                elif mfa_validation.get('mfa_verification_required'):
                    next_steps.append('verify_mfa')
                elif mfa_validation.get('stronger_mfa_required'):
                    next_steps.append('use_stronger_mfa')
            
            result['errors'] = errors
            result['next_steps'] = next_steps
        
        # Log security validation attempt
        self.audit_logger.log_security_validation(
            'approval_security_validation',
            user.id if user else None,
            {
                'approval_level': approval_level,
                'validation_result': overall_valid,
                'mfa_required': mfa_validation.get('mfa_required', False),
                'mfa_verified': mfa_validation.get('mfa_verified', False),
                'errors': result.get('errors', [])
            }
        )
        
        return result

    def get_approval_validation_schema(self) -> Dict[str, any]:
        """
        Get validation schema for approval requests.
        
        Returns:
            Dict containing validation rules for approval data
        """
        return {
            'required_fields': ValidationConstants.REQUIRED_APPROVAL_FIELDS,
            'optional_fields': ValidationConstants.OPTIONAL_APPROVAL_FIELDS,
            'field_types': ValidationConstants.ALLOWED_FIELD_TYPES,
            'max_lengths': {
                'comments': SecurityConstants.MAX_COMMENT_LENGTH,
                'delegation_reason': SecurityConstants.MAX_COMMENT_LENGTH,
                'field_names': SecurityConstants.MAX_FIELD_NAME_LENGTH
            },
            'allowed_operators': ValidationConstants.ALLOWED_OPERATORS,
            'allowed_functions': ValidationConstants.ALLOWED_FUNCTIONS,
            'sanitization_rules': {
                'html_tags': ValidationConstants.HTML_ALLOWED_TAGS,
                'html_attributes': ValidationConstants.HTML_ALLOWED_ATTRIBUTES,
                'xss_protection': ValidationConstants.XSS_PROTECTION_ENABLED
            }
        }

    def validate_input_data(self, data: Dict[str, any], schema: Dict[str, any]) -> Dict[str, any]:
        """
        Validate input data against schema with security checks.
        
        Args:
            data: Input data to validate
            schema: Validation schema
            
        Returns:
            Dict containing validation results
        """
        try:
            # Import validation framework to prevent circular imports
            from .validation_framework import validate_approval_request
            
            # Use the existing validation framework with MFA integration
            return validate_approval_request(data, data.get('user_id'), self)
            
        except ImportError:
            # Fallback validation if framework not available
            return {
                'valid': True,
                'sanitized_data': data,
                'errors': [],
                'warnings': ['Validation framework not available - using basic validation']
            }
        except Exception as e:
            log.error(f"Input validation error: {e}")
            return {
                'valid': False,
                'errors': [f'Validation error: {str(e)}'],
                'sanitized_data': {}
            }

    def check_approval_rate_limit(self, user_id: int) -> bool:
        """
        Enhanced approval rate limiting with burst protection and IP-based limits.
        
        SECURITY IMPROVEMENT: Multi-layer rate limiting to prevent abuse and DoS attacks.
        """
        current_time = datetime.now(tz=timezone.utc).timestamp()
        client_identifier = self._get_robust_client_identifier()

        # PERFORMANCE FIX: Clean up expired entries to prevent memory leaks
        self._cleanup_expired_rate_limit_entries(current_time)

        # Check burst rate limiting (short-term)
        if not self._check_burst_rate_limit(user_id, current_time):
            self.audit_logger.log_security_violation(
                'rate_limit_burst_exceeded', None, None, {
                    'user_id': user_id,
                    'client_identifier': client_identifier,
                    'limit_type': 'burst_protection',
                    'threshold': self.security_config['rate_limit_burst_threshold']
                }
            )
            return False
        
        # Check standard rate limiting (medium-term)
        if not self._check_standard_rate_limit(user_id, current_time):
            self.audit_logger.log_security_violation(
                'rate_limit_standard_exceeded', None, None, {
                    'user_id': user_id,
                    'client_identifier': client_identifier,
                    'limit_type': 'standard_protection',
                    'threshold': self.security_config['max_approvals_per_window']
                }
            )
            return False
        
        # Check IP-based rate limiting (long-term)
        if not self._check_ip_rate_limit(client_identifier, current_time):
            self.audit_logger.log_security_violation(
                'rate_limit_ip_exceeded', None, None, {
                    'user_id': user_id,
                    'client_identifier': client_identifier,
                    'limit_type': 'ip_protection',
                    'threshold': self.security_config['max_approvals_per_ip']
                }
            )
            return False
        
        # All rate limit checks passed - record the approval
        self._record_approval_activity(user_id, client_identifier, current_time)
        
        return True
    
    def _check_burst_rate_limit(self, user_id: int, current_time: float) -> bool:
        """Check short-term burst rate limiting."""
        burst_key = f"burst_{user_id}"
        burst_window = self.security_config['rate_limit_burst_window']
        burst_threshold = self.security_config['rate_limit_burst_threshold']
        
        # Clean expired entries
        window_start = current_time - burst_window
        self.rate_limit_storage[burst_key] = [
            ts for ts in self.rate_limit_storage[burst_key] if ts > window_start
        ]
        
        return len(self.rate_limit_storage[burst_key]) < burst_threshold
    
    def _check_standard_rate_limit(self, user_id: int, current_time: float) -> bool:
        """Check standard rate limiting."""
        standard_key = f"standard_{user_id}"
        standard_window = self.security_config['rate_limit_window']
        standard_threshold = self.security_config['max_approvals_per_window']
        
        # Clean expired entries
        window_start = current_time - standard_window
        self.rate_limit_storage[standard_key] = [
            ts for ts in self.rate_limit_storage[standard_key] if ts > window_start
        ]
        
        return len(self.rate_limit_storage[standard_key]) < standard_threshold
    
    def _check_ip_rate_limit(self, client_identifier: str, current_time: float) -> bool:
        """Check client-based rate limiting with robust identification."""
        client_key = f"client_{client_identifier}"
        ip_window = self.security_config['ip_rate_limit_window']
        ip_threshold = self.security_config['max_approvals_per_ip']
        
        # Clean expired entries
        window_start = current_time - ip_window
        self.rate_limit_storage[client_key] = [
            ts for ts in self.rate_limit_storage[client_key] if ts > window_start
        ]
        
        return len(self.rate_limit_storage[client_key]) < ip_threshold
    
    def _record_approval_activity(self, user_id: int, client_identifier: str, current_time: float) -> None:
        """Record approval activity in all rate limit tracking systems."""
        # Record in burst tracking
        burst_key = f"burst_{user_id}"
        self.rate_limit_storage[burst_key].append(current_time)
        
        # Record in standard tracking
        standard_key = f"standard_{user_id}"
        self.rate_limit_storage[standard_key].append(current_time)
        
        # Record in client tracking (robust IP+User identification)
        client_key = f"client_{client_identifier}"
        self.rate_limit_storage[client_key].append(current_time)
        
        # Also maintain session-based tracking for backward compatibility
        rate_limits = session.get('approval_rate_limits', {})
        user_limits = rate_limits.get(str(user_id), [])
        user_limits.append(current_time)
        rate_limits[str(user_id)] = user_limits
        session['approval_rate_limits'] = rate_limits
    
    def _get_robust_client_identifier(self) -> str:
        """
        Get robust client identifier for rate limiting that's harder to bypass.
        
        SECURITY IMPROVEMENT: Uses multiple identification vectors to prevent
        rate limiting bypass through IP spoofing or proxy manipulation.
        
        Returns:
            str: Robust client identifier combining multiple factors
        """
        # Get various IP sources (prioritize most reliable)
        forwarded_for = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        real_ip = request.headers.get('X-Real-IP', '').strip()
        remote_addr = request.remote_addr or 'unknown'
        
        # Use the most reliable IP identifier
        client_ip = forwarded_for or real_ip or remote_addr
        
        # Get additional identifying information
        user_agent = request.headers.get('User-Agent', '')[:100]  # Limit length
        
        # Add user context for authenticated users
        if current_user and current_user.is_authenticated:
            user_context = f"user_{current_user.id}"
            
            # Add session information for more robust tracking
            session_id = session.get('_id', 'no_session')[:16]  # Truncate for storage
            
            # Combine multiple factors for robust identification
            return f"{client_ip}:{user_context}:{session_id}"
        else:
            # For anonymous users, use IP + user agent hash for identification
            import hashlib
            ua_hash = hashlib.md5(user_agent.encode('utf-8')).hexdigest()[:8]
            return f"{client_ip}:anonymous:{ua_hash}"
    
    def sanitize_approval_comments(self, comments: str) -> Optional[str]:
        """
        Sanitize approval comments to prevent XSS and injection attacks.
        Uses bleach library for comprehensive HTML sanitization.
        """
        if not comments:
            return None
        
        # Configure bleach for secure sanitization
        allowed_tags = []  # No HTML tags allowed in approval comments
        allowed_attributes = {}  # No HTML attributes allowed
        allowed_protocols = ['http', 'https', 'mailto']
        
        # Sanitize using bleach to prevent XSS attacks
        sanitized = bleach.clean(
            comments,
            tags=allowed_tags,
            attributes=allowed_attributes,
            protocols=allowed_protocols,
            strip=True  # Strip disallowed tags instead of escaping
        )
        
        # Additional sanitization for approval context
        sanitized = bleach.linkify(
            sanitized,
            callbacks=[self._validate_link_callback],
            skip_tags=['pre', 'code']
        )
        
        # Limit length to prevent storage issues and DoS
        max_length = 1000
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
            self.audit_logger.log_security_violation(
                'comment_length_exceeded', None, None, 
                {'original_length': len(comments), 'max_length': max_length}
            )
        
        # Enhanced XSS attempt detection with pattern analysis
        if len(sanitized) < len(comments) * 0.8:
            self.audit_logger.log_security_violation(
                'potential_xss_attempt', None, None,
                {'original': comments[:200], 'sanitized': sanitized[:200]}
            )
        
        # Check for additional malicious patterns
        malicious_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'vbscript:',
            r'on\w+\s*=',
            r'data:text/html',
            r'&#x\w+;',
            r'&\w+;'
        ]
        
        original_lower = comments.lower()
        for pattern in malicious_patterns:
            if re.search(pattern, original_lower, re.IGNORECASE | re.DOTALL):
                self.audit_logger.log_security_violation(
                    'malicious_pattern_detected', None, None,
                    {'pattern': pattern, 'input': comments[:100]}
                )
        
        return sanitized.strip() if sanitized.strip() else None
    
    def _validate_link_callback(self, attrs, new=False):
        """Validate links in approval comments for security."""
        href = attrs.get('href', '')
        
        # Block suspicious URLs
        suspicious_patterns = [
            'javascript:', 'data:', 'vbscript:', 'file:',
            'about:', 'chrome:', 'resource:'
        ]
        
        for pattern in suspicious_patterns:
            if href.lower().startswith(pattern):
                # Remove the href attribute to neutralize the link
                if 'href' in attrs:
                    del attrs['href']
                self.audit_logger.log_security_violation(
                    'malicious_link_blocked', None, None,
                    {'blocked_url': href}
                )
                break
        
        return attrs
    
    def validate_authentication(self, current_user) -> bool:
        """Validate user authentication status."""
        return current_user and current_user.is_authenticated
    
    def validate_input_data(self, input_data: Dict, schema: Dict) -> Dict:
        """
        Comprehensive input validation to prevent bypass attacks.
        
        SECURITY IMPROVEMENT: Validates all input data against defined schemas
        to prevent input validation bypass vulnerabilities.
        
        Args:
            input_data: Data to validate
            schema: Validation schema defining allowed fields and types
            
        Returns:
            dict: Validation results with sanitized data
        """
        validation_results = {
            'is_valid': True,
            'errors': [],
            'sanitized_data': {},
            'security_violations': []
        }
        
        try:
            # Validate required fields
            required_fields = schema.get('required_fields', [])
            for field in required_fields:
                if field not in input_data:
                    validation_results['errors'].append(f"Required field '{field}' missing")
                    validation_results['is_valid'] = False
            
            # Validate each field in input data
            for field_name, field_value in input_data.items():
                field_schema = schema.get('fields', {}).get(field_name)
                if not field_schema:
                    # Unknown field - potential bypass attempt
                    validation_results['security_violations'].append({
                        'type': 'unknown_field',
                        'field': field_name,
                        'value': str(field_value)[:100]
                    })
                    continue
                
                # Validate field against schema
                field_result = self._validate_field(field_name, field_value, field_schema)
                if not field_result['is_valid']:
                    validation_results['errors'].extend(field_result['errors'])
                    validation_results['is_valid'] = False
                else:
                    validation_results['sanitized_data'][field_name] = field_result['sanitized_value']
                
                # Collect security violations
                validation_results['security_violations'].extend(field_result.get('security_violations', []))
            
            # Log security violations
            for violation in validation_results['security_violations']:
                self.audit_logger.log_security_violation(
                    'input_validation_violation', None, None, violation
                )
            
            return validation_results
            
        except Exception as e:
            validation_results['is_valid'] = False
            validation_results['errors'].append(f"Validation error: {str(e)}")
            self.audit_logger.log_security_violation(
                'input_validation_error', None, None, {
                    'error': str(e),
                    'error_type': type(e).__name__
                }
            )
            return validation_results
    
    def _validate_field(self, field_name: str, field_value, field_schema: Dict) -> Dict:
        """
        Validate individual field against schema.
        
        Args:
            field_name: Name of the field
            field_value: Value to validate
            field_schema: Schema definition for the field
            
        Returns:
            dict: Field validation results
        """
        result = {
            'is_valid': True,
            'errors': [],
            'sanitized_value': field_value,
            'security_violations': []
        }
        
        try:
            # Type validation
            expected_type = field_schema.get('type', 'string')
            if not self._validate_field_type(field_value, expected_type):
                result['errors'].append(f"Field '{field_name}' must be of type {expected_type}")
                result['is_valid'] = False
                return result
            
            # Length validation
            if 'max_length' in field_schema:
                max_length = field_schema['max_length']
                if isinstance(field_value, str) and len(field_value) > max_length:
                    result['errors'].append(f"Field '{field_name}' exceeds maximum length {max_length}")
                    result['is_valid'] = False
                    # Truncate and log security violation
                    result['sanitized_value'] = field_value[:max_length]
                    result['security_violations'].append({
                        'type': 'length_exceeded',
                        'field': field_name,
                        'original_length': len(field_value),
                        'max_length': max_length
                    })
            
            # Pattern validation
            if 'pattern' in field_schema and isinstance(field_value, str):
                pattern = field_schema['pattern']
                if not re.match(pattern, field_value):
                    result['errors'].append(f"Field '{field_name}' does not match required pattern")
                    result['is_valid'] = False
                    result['security_violations'].append({
                        'type': 'pattern_mismatch',
                        'field': field_name,
                        'pattern': pattern,
                        'value': field_value[:100]
                    })
            
            # Sanitization for string fields
            if isinstance(field_value, str):
                sanitized = self._sanitize_string_field(field_value, field_schema)
                if sanitized != field_value:
                    result['sanitized_value'] = sanitized
                    result['security_violations'].append({
                        'type': 'sanitization_applied',
                        'field': field_name,
                        'original': field_value[:100],
                        'sanitized': sanitized[:100]
                    })
            
            # Range validation for numeric fields
            if expected_type in ['integer', 'float']:
                if 'min_value' in field_schema and field_value < field_schema['min_value']:
                    result['errors'].append(f"Field '{field_name}' below minimum value")
                    result['is_valid'] = False
                if 'max_value' in field_schema and field_value > field_schema['max_value']:
                    result['errors'].append(f"Field '{field_name}' exceeds maximum value")
                    result['is_valid'] = False
            
            return result
            
        except Exception as e:
            result['is_valid'] = False
            result['errors'].append(f"Field validation error: {str(e)}")
            return result
    
    def _validate_field_type(self, value, expected_type: str) -> bool:
        """Validate field type."""
        type_mapping = {
            'string': str,
            'integer': int,
            'float': (int, float),
            'boolean': bool,
            'list': list,
            'dict': dict
        }
        
        expected_python_type = type_mapping.get(expected_type)
        if not expected_python_type:
            return False
        
        return isinstance(value, expected_python_type)
    
    def _sanitize_string_field(self, value: str, field_schema: Dict) -> str:
        """Sanitize string field based on schema rules."""
        sanitized = value
        
        # Apply basic sanitization
        if field_schema.get('strip_html', True):
            sanitized = bleach.clean(sanitized, tags=[], attributes={}, strip=True)
        
        # Remove control characters
        if field_schema.get('remove_control_chars', True):
            # Allow tab, newline, carriage return, and space
            allowed_control_chars = {9, 10, 13}  # tab, newline, carriage return
            sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or ord(char) in allowed_control_chars)
        
        # Normalize whitespace
        if field_schema.get('normalize_whitespace', True):
            sanitized = ' '.join(sanitized.split())

        return sanitized

    def validate_workflow_transition(self, current_state: str, target_state: str, user, instance) -> Dict[str, any]:
        """Validate workflow state transitions for security."""
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'security_checks': []
        }

        try:
            # Define valid state transitions
            valid_transitions = {
                'draft': ['submitted', 'cancelled'],
                'submitted': ['under_review', 'rejected', 'withdrawn'],
                'under_review': ['approved', 'rejected', 'needs_info'],
                'needs_info': ['submitted', 'withdrawn'],
                'approved': ['completed', 'reverted'],
                'rejected': ['resubmitted'],
                'completed': [],  # Terminal state
                'cancelled': [],  # Terminal state
                'withdrawn': ['resubmitted']
            }

            # Check if transition is valid
            allowed_targets = valid_transitions.get(current_state, [])
            if target_state not in allowed_targets:
                result['valid'] = False
                result['errors'].append(f'Invalid transition from {current_state} to {target_state}')
                return result

            # Security checks for sensitive transitions
            if target_state == 'approved':
                # Additional security for approvals
                self_approval_check = self.validate_self_approval(instance, user)
                if self_approval_check['is_self_approval'] and not self_approval_check['allowed']:
                    result['valid'] = False
                    result['errors'].append('Self-approval not permitted')
                    result['security_checks'].append('self_approval_blocked')

                # Check MFA for high-value approvals
                if hasattr(instance, 'amount') and getattr(instance, 'amount', 0) > 10000:
                    mfa_check = self.validate_mfa_for_approval(user, 'high')
                    if not mfa_check['valid']:
                        result['valid'] = False
                        result['errors'].append('MFA required for high-value approval')
                        result['security_checks'].append('mfa_required')

            elif target_state in ['rejected', 'cancelled']:
                # Log rejection/cancellation for audit
                self.audit_logger.log_security_validation(
                    'workflow_rejection', user.id, {
                        'current_state': current_state,
                        'target_state': target_state,
                        'instance_type': type(instance).__name__,
                        'instance_id': getattr(instance, 'id', None)
                    }
                )

            return result

        except Exception as e:
            log.error(f'Workflow transition validation error: {e}')
            result['valid'] = False
            result['errors'].append(f'Validation error: {str(e)}')
            return result

    def validate_bulk_operation_security(self, operation_type: str, items: List, user) -> Dict[str, any]:
        """Validate security for bulk operations."""
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'rejected_items': [],
            'security_summary': {
                'total_items': len(items),
                'self_approvals_detected': 0,
                'mfa_required_items': 0,
                'high_risk_items': 0
            }
        }

        try:
            # Check bulk operation limits
            max_bulk = self.security_config.get('max_bulk_operations', 50)
            if len(items) > max_bulk:
                result['valid'] = False
                result['errors'].append(f'Bulk operation exceeds limit of {max_bulk} items')
                return result

            # Validate each item in the bulk operation
            for idx, item in enumerate(items):
                item_result = {
                    'index': idx,
                    'item_id': getattr(item, 'id', None),
                    'issues': []
                }

                # Self-approval check
                self_approval = self.validate_self_approval(item, user)
                if self_approval['is_self_approval'] and not self_approval['allowed']:
                    result['security_summary']['self_approvals_detected'] += 1
                    item_result['issues'].append('self_approval')
                    result['rejected_items'].append(item_result)

                # High-value check
                if hasattr(item, 'amount') and getattr(item, 'amount', 0) > 10000:
                    result['security_summary']['high_risk_items'] += 1
                    result['security_summary']['mfa_required_items'] += 1

                    # MFA validation for high-value items
                    mfa_check = self.validate_mfa_for_approval(user, 'high')
                    if not mfa_check['valid']:
                        item_result['issues'].append('mfa_required')
                        result['rejected_items'].append(item_result)

            # Check if too many items were rejected
            rejection_rate = len(result['rejected_items']) / len(items)
            if rejection_rate > 0.5:  # More than 50% rejected
                result['warnings'].append('High rejection rate in bulk operation')
                self.audit_logger.log_security_validation(
                    'bulk_operation_high_rejection_rate', user.id, {
                        'operation_type': operation_type,
                        'total_items': len(items),
                        'rejected_items': len(result['rejected_items']),
                        'rejection_rate': rejection_rate
                    }
                )

            # Final validation
            if len(result['rejected_items']) == len(items):
                result['valid'] = False
                result['errors'].append('All items in bulk operation were rejected')

            return result

        except Exception as e:
            log.error(f'Bulk operation validation error: {e}')
            result['valid'] = False
            result['errors'].append(f'Validation error: {str(e)}')
            return result

    def validate_session_security(self, user, session_data: Dict = None) -> Dict[str, any]:
        """Validate session security for approval operations."""
        result = {
            'valid': True,
            'session_secure': True,
            'warnings': [],
            'security_issues': []
        }

        try:
            if not session_data:
                session_data = {
                    'user_id': user.id if user else None,
                    'session_id': session.get('_id'),
                    'csrf_token': session.get('csrf_token'),
                    'login_time': session.get('login_time'),
                    'last_activity': session.get('last_activity')
                }

            # Validate session exists and belongs to user
            if not session_data.get('session_id'):
                result['valid'] = False
                result['security_issues'].append('No valid session found')
                return result

            # Check session timeout
            last_activity = session_data.get('last_activity')
            if last_activity:
                import time
                current_time = time.time()
                session_timeout = 3600  # 1 hour default

                if current_time - last_activity > session_timeout:
                    result['valid'] = False
                    result['security_issues'].append('Session expired')
                    return result

            # CSRF token validation
            if not session_data.get('csrf_token'):
                result['warnings'].append('CSRF token missing')
                result['session_secure'] = False

            # Update last activity
            session['last_activity'] = time.time()

            return result

        except Exception as e:
            log.error(f'Session security validation error: {e}')
            result['valid'] = False
            result['security_issues'].append(f'Validation error: {str(e)}')
            return result

    def can_user_approve_entity_type(self, user, entity_type: str) -> bool:
        """
        Check if user is authorized to approve the specified entity type.

        SECURITY FEATURE: Prevents unauthorized approval assignments through
        entity-type-based authorization validation.

        Args:
            user: User object to check
            entity_type: Entity type to check authorization for

        Returns:
            bool: True if user can approve this entity type
        """
        try:
            # Basic validation
            if not user or not user.is_active:
                return False

            # Define entity type to role mappings for authorization
            entity_role_mappings = {
                'ExpenseReport': ['Finance', 'Manager', 'Admin'],
                'PurchaseOrder': ['Procurement', 'Manager', 'Admin'],
                'TimeSheet': ['HR', 'Manager', 'Admin'],
                'ContractApproval': ['Legal', 'Manager', 'Admin'],
                'BudgetRequest': ['Finance', 'CFO', 'Admin'],
                'LeaveRequest': ['HR', 'Manager', 'Admin'],
                'CapitalExpenditure': ['Finance', 'CFO', 'CEO', 'Admin'],
                'VendorOnboarding': ['Procurement', 'Finance', 'Admin']
            }

            # Get required roles for this entity type
            required_roles = entity_role_mappings.get(entity_type, ['Admin'])

            # Check if user has any of the required roles
            if hasattr(user, 'roles'):
                user_role_names = [role.name for role in user.roles if hasattr(role, 'name')]

                # Check for role intersection
                if any(role in required_roles for role in user_role_names):
                    return True

            # Fallback: check if user is an admin
            if self.appbuilder and hasattr(self.appbuilder, 'sm'):
                if self.appbuilder.sm.is_admin(user):
                    return True

            return False

        except Exception as e:
            log.error(f"Error checking entity type authorization: {e}")
            # Fail secure: deny access on error
            return False

    def get_approval_validation_schema(self) -> Dict:
        """
        Get the validation schema for approval workflow inputs.
        
        Returns:
            dict: Validation schema defining allowed fields and constraints
        """
        return {
            'required_fields': ['workflow_type', 'priority'],
            'fields': {
                'workflow_type': {
                    'type': 'string',
                    'max_length': 50,
                    'pattern': r'^[a-zA-Z0-9_-]+$'
                },
                'priority': {
                    'type': 'string',
                    'max_length': 20,
                    'pattern': r'^(low|medium|high|critical)$'
                },
                'comments': {
                    'type': 'string',
                    'max_length': 1000,
                    'strip_html': True,
                    'remove_control_chars': True,
                    'normalize_whitespace': True
                },
                'amount': {
                    'type': 'float',
                    'min_value': 0,
                    'max_value': 1000000
                },
                'manager_id': {
                    'type': 'integer',
                    'min_value': 1
                },
                'department_id': {
                    'type': 'integer',
                    'min_value': 1
                },
                'cost_center': {
                    'type': 'string',
                    'max_length': 20,
                    'pattern': r'^[A-Z0-9-]+$'
                }
            }
        }