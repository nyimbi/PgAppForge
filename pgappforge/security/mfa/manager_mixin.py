"""
Multi-Factor Authentication Security Manager Integration

This module provides PgAppForge SecurityManager integration for MFA
functionality, extending the authentication flow with multi-factor verification,
session management, and policy enforcement.

Classes:
    MFASecurityManagerMixin: Mixin to add MFA capabilities to SecurityManager
    MFASessionManager: Session state management for MFA flows
    MFAAuthenticationHandler: Authentication flow integration
    MFAPolicyEnforcer: Policy-based access control

Integration:
    class CustomSecurityManager(MFASecurityManagerMixin, SecurityManager):
        pass
        
    appbuilder = AppBuilder(app, db.session, security_manager_class=CustomSecurityManager)

Features:
    - Seamless integration with existing authentication flows
    - Session-based MFA state management
    - Policy enforcement at login and route access
    - Configurable MFA challenge mechanisms
    - Complete audit trail integration
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple, Union
from functools import wraps

from flask import (
    session, request, redirect, url_for, flash, 
    current_app, render_template, jsonify, g
)
from flask_login import current_user, login_required
from hmac import compare_digest as safe_str_cmp

from pgappforge.security.manager import BaseSecurityManager
from pgappforge.const import LOGMSG_ERR_SEC_AUTH_USERNAME

from .models import UserMFA, MFAVerification, MFAPolicy
from .services import (
    MFAOrchestrationService, TOTPService, SMSService, 
    EmailService, BackupCodeService, MFAPolicyService,
    ValidationError, ServiceUnavailableError
)

log = logging.getLogger(__name__)


class MFASessionState:
    """
    MFA session state management.
    
    Tracks user progress through multi-factor authentication flows
    including verification status, challenge state, and session timeouts.
    """
    
    # Session state constants
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    CHALLENGED = "challenged"
    VERIFIED = "verified"
    LOCKED = "locked"
    
    # Session keys
    MFA_STATE_KEY = "_mfa_state"
    MFA_USER_ID_KEY = "_mfa_user_id"
    MFA_CHALLENGE_TIME_KEY = "_mfa_challenge_time"
    MFA_VERIFIED_TIME_KEY = "_mfa_verified_time"
    MFA_CHALLENGE_METHOD_KEY = "_mfa_challenge_method"
    MFA_ATTEMPTS_KEY = "_mfa_attempts"
    MFA_LOCKOUT_TIME_KEY = "_mfa_lockout_time"
    
    @staticmethod
    def get_state() -> str:
        """
        Get current MFA state from session.
        
        Returns:
            str: Current MFA state
        """
        return session.get(MFASessionState.MFA_STATE_KEY, MFASessionState.NOT_REQUIRED)
    
    @staticmethod
    def set_state(state: str, user_id: int = None) -> None:
        """
        Set MFA state in session.
        
        Args:
            state: MFA state to set
            user_id: Optional user ID to associate with state
        """
        session[MFASessionState.MFA_STATE_KEY] = state
        if user_id is not None:
            session[MFASessionState.MFA_USER_ID_KEY] = user_id
        
        log.debug(f"MFA state changed to {state} for user {user_id}")
    
    @staticmethod
    def get_user_id() -> Optional[int]:
        """
        Get user ID associated with current MFA session.
        
        Returns:
            Optional[int]: User ID or None if not set
        """
        return session.get(MFASessionState.MFA_USER_ID_KEY)
    
    @staticmethod
    def set_challenge(method: str, user_id: int) -> None:
        """
        Set MFA challenge state.
        
        Args:
            method: MFA method being challenged
            user_id: User ID being challenged
        """
        session[MFASessionState.MFA_STATE_KEY] = MFASessionState.CHALLENGED
        session[MFASessionState.MFA_USER_ID_KEY] = user_id
        session[MFASessionState.MFA_CHALLENGE_METHOD_KEY] = method
        session[MFASessionState.MFA_CHALLENGE_TIME_KEY] = datetime.now(tz=timezone.utc).isoformat()
        session[MFASessionState.MFA_ATTEMPTS_KEY] = 0
    
    @staticmethod
    def set_verified(user_id: int, method: str) -> None:
        """
        Set MFA as verified.
        
        Args:
            user_id: User ID that was verified
            method: MFA method that succeeded
        """
        session[MFASessionState.MFA_STATE_KEY] = MFASessionState.VERIFIED
        session[MFASessionState.MFA_USER_ID_KEY] = user_id
        session[MFASessionState.MFA_VERIFIED_TIME_KEY] = datetime.now(tz=timezone.utc).isoformat()
        
        # Clear challenge state
        session.pop(MFASessionState.MFA_CHALLENGE_METHOD_KEY, None)
        session.pop(MFASessionState.MFA_CHALLENGE_TIME_KEY, None)
        session.pop(MFASessionState.MFA_ATTEMPTS_KEY, None)
        session.pop(MFASessionState.MFA_LOCKOUT_TIME_KEY, None)
    
    @staticmethod
    def increment_attempts() -> int:
        """
        Increment failed attempt counter.
        
        Returns:
            int: New attempt count
        """
        attempts = session.get(MFASessionState.MFA_ATTEMPTS_KEY, 0) + 1
        session[MFASessionState.MFA_ATTEMPTS_KEY] = attempts
        return attempts
    
    @staticmethod
    def set_lockout(duration_seconds: int) -> None:
        """
        Set session lockout state.
        
        Args:
            duration_seconds: Duration of lockout in seconds
        """
        session[MFASessionState.MFA_STATE_KEY] = MFASessionState.LOCKED
        lockout_until = datetime.now(tz=timezone.utc) + timedelta(seconds=duration_seconds)
        session[MFASessionState.MFA_LOCKOUT_TIME_KEY] = lockout_until.isoformat()
    
    @staticmethod
    def is_locked() -> bool:
        """
        Check if session is currently locked.
        
        Returns:
            bool: True if session is locked
        """
        if session.get(MFASessionState.MFA_STATE_KEY) != MFASessionState.LOCKED:
            return False
        
        lockout_time_str = session.get(MFASessionState.MFA_LOCKOUT_TIME_KEY)
        if not lockout_time_str:
            return False
        
        lockout_time = datetime.fromisoformat(lockout_time_str)
        return datetime.now(tz=timezone.utc) < lockout_time
    
    @staticmethod
    def is_verified_and_valid() -> bool:
        """
        Check if MFA is verified and still within session timeout.
        
        Returns:
            bool: True if verified and valid
        """
        if session.get(MFASessionState.MFA_STATE_KEY) != MFASessionState.VERIFIED:
            return False
        
        verified_time_str = session.get(MFASessionState.MFA_VERIFIED_TIME_KEY)
        if not verified_time_str:
            return False
        
        verified_time = datetime.fromisoformat(verified_time_str)
        timeout_seconds = current_app.config.get('MFA_SESSION_TIMEOUT', 3600)
        session_expires = verified_time + timedelta(seconds=timeout_seconds)
        
        return datetime.now(tz=timezone.utc) < session_expires
    
    @staticmethod
    def clear() -> None:
        """Clear all MFA session state."""
        keys_to_remove = [
            MFASessionState.MFA_STATE_KEY,
            MFASessionState.MFA_USER_ID_KEY,
            MFASessionState.MFA_CHALLENGE_TIME_KEY,
            MFASessionState.MFA_VERIFIED_TIME_KEY,
            MFASessionState.MFA_CHALLENGE_METHOD_KEY,
            MFASessionState.MFA_ATTEMPTS_KEY,
            MFASessionState.MFA_LOCKOUT_TIME_KEY
        ]
        
        for key in keys_to_remove:
            session.pop(key, None)


class MFAAuthenticationHandler:
    """
    Handles MFA authentication flow integration.
    
    Manages the multi-step authentication process including challenge
    generation, verification, and session state transitions.
    """
    
    def __init__(self, security_manager):
        """
        Initialize authentication handler.
        
        Args:
            security_manager: PgAppForge security manager instance
        """
        self.security_manager = security_manager
        self.orchestration_service = MFAOrchestrationService()
        self.policy_service = MFAPolicyService()
        
    def is_mfa_required(self, user) -> bool:
        """
        Check if MFA is required for a user.
        
        Args:
            user: PgAppForge User object
            
        Returns:
            bool: True if MFA is required
        """
        # Check if user has MFA enabled
        user_mfa = self.security_manager.get_user_mfa(user.id)
        if not user_mfa or not user_mfa.is_enabled:
            # Check if MFA is required by policy
            return self.policy_service.is_mfa_required_for_user(user)
        
        return True
    
    def get_user_mfa_methods(self, user) -> List[str]:
        """
        Get available MFA methods for a user.
        
        Args:
            user: PgAppForge User object
            
        Returns:
            List[str]: Available MFA method names
        """
        user_mfa = self.security_manager.get_user_mfa(user.id)
        if not user_mfa or not user_mfa.setup_completed:
            return []
        
        methods = []
        allowed_methods = self.policy_service.get_allowed_methods_for_user(user)
        
        # Check what methods are configured and allowed
        if 'totp' in allowed_methods and user_mfa.totp_secret:
            methods.append('totp')
        
        if 'sms' in allowed_methods and user_mfa.phone_number:
            methods.append('sms')
        
        if 'email' in allowed_methods and user_mfa.recovery_email:
            methods.append('email')
        
        if 'backup' in allowed_methods:
            # Check if user has unused backup codes
            backup_service = BackupCodeService()
            remaining_codes = backup_service.get_remaining_codes_count(user_mfa.id)
            if remaining_codes > 0:
                methods.append('backup')
        
        return methods
    
    def initiate_mfa_challenge(self, user, method: str) -> Dict[str, Any]:
        """
        Initiate MFA challenge for specified method.
        
        Args:
            user: PgAppForge User object
            method: MFA method to challenge
            
        Returns:
            Dict[str, Any]: Challenge initiation result
            
        Raises:
            ValidationError: If method is not available or configured
        """
        available_methods = self.get_user_mfa_methods(user)
        if method not in available_methods:
            raise ValidationError(f"MFA method '{method}' is not available for this user")
        
        user_mfa = self.security_manager.get_user_mfa(user.id)
        
        # Check if user is locked
        if not user_mfa.can_attempt_mfa():
            raise ValidationError("Account is temporarily locked due to failed attempts")
        
        result = {"method": method, "challenge_sent": False}
        
        try:
            if method == "sms":
                # Generate and send SMS code
                sms_service = SMSService()
                code = self._generate_challenge_code()
                
                success = sms_service.send_mfa_code(
                    user_mfa.phone_number,
                    code,
                    user.first_name or user.username
                )
                
                if success:
                    # Store code hash in session for verification
                    from werkzeug.security import generate_password_hash
                    session['_mfa_challenge_code'] = generate_password_hash(code)
                    result["challenge_sent"] = True
                    result["message"] = "Verification code sent to your phone"
                else:
                    raise ServiceUnavailableError("SMS delivery failed")
            
            elif method == "email":
                # Generate and send email code
                email_service = EmailService()
                code = self._generate_challenge_code()
                
                success = email_service.send_mfa_code(
                    user_mfa.recovery_email or user.email,
                    code,
                    user.first_name or user.username
                )
                
                if success:
                    from werkzeug.security import generate_password_hash
                    session['_mfa_challenge_code'] = generate_password_hash(code)
                    result["challenge_sent"] = True
                    result["message"] = "Verification code sent to your email"
                else:
                    raise ServiceUnavailableError("Email delivery failed")
            
            elif method == "totp":
                # TOTP doesn't need challenge initiation
                result["message"] = "Enter the 6-digit code from your authenticator app"
            
            elif method == "backup":
                # Backup codes don't need challenge initiation
                result["message"] = "Enter one of your backup recovery codes"
            
            # Set session challenge state
            MFASessionState.set_challenge(method, user.id)
            
            log.info(f"MFA challenge initiated for user {user.id} with method {method}")
            return result
            
        except Exception as e:
            log.error(f"MFA challenge initiation failed: {str(e)}")
            raise
    
    def verify_mfa_response(self, user, method: str, code: str) -> Dict[str, Any]:
        """
        Verify MFA response code.
        
        Args:
            user: PgAppForge User object
            method: MFA method used
            code: Verification code provided
            
        Returns:
            Dict[str, Any]: Verification result
        """
        try:
            # Get client IP
            ip_address = request.remote_addr or "unknown"
            
            # Check session lockout
            if MFASessionState.is_locked():
                return {
                    "success": False,
                    "message": "Session is temporarily locked. Please try again later.",
                    "locked": True
                }
            
            # Verify using orchestration service for TOTP and backup codes
            if method in ['totp', 'backup']:
                result = self.orchestration_service.verify_mfa_code(
                    user, method, code, ip_address
                )
                
                if result['verification_success']:
                    MFASessionState.set_verified(user.id, method)
                    return {
                        "success": True,
                        "message": "MFA verification successful",
                        "method": method,
                        "session_expires": result.get('session_expires')
                    }
                else:
                    # Handle failed attempt
                    attempts = MFASessionState.increment_attempts()
                    max_attempts = current_app.config.get('MFA_MAX_SESSION_ATTEMPTS', 3)
                    
                    if attempts >= max_attempts:
                        lockout_duration = current_app.config.get('MFA_SESSION_LOCKOUT', 300)
                        MFASessionState.set_lockout(lockout_duration)
                        return {
                            "success": False,
                            "message": "Too many failed attempts. Session locked.",
                            "locked": True
                        }
                    
                    return {
                        "success": False,
                        "message": result.get('failure_reason', 'Verification failed'),
                        "attempts_remaining": max_attempts - attempts
                    }
            
            # Verify SMS/Email codes from session
            elif method in ['sms', 'email']:
                challenge_code_hash = session.get('_mfa_challenge_code')
                if not challenge_code_hash:
                    return {
                        "success": False,
                        "message": "No challenge code found. Please request a new code."
                    }
                
                from werkzeug.security import check_password_hash
                if check_password_hash(challenge_code_hash, code):
                    # Record successful verification
                    user_mfa = self.security_manager.get_user_mfa(user.id)
                    user_mfa.record_successful_attempt(method)
                    
                    MFAVerification.record_attempt(
                        user_mfa_id=user_mfa.id,
                        method=method,
                        success=True,
                        ip_address=ip_address
                    )
                    
                    MFASessionState.set_verified(user.id, method)
                    session.pop('_mfa_challenge_code', None)
                    
                    return {
                        "success": True,
                        "message": "MFA verification successful",
                        "method": method
                    }
                else:
                    # Record failed verification
                    user_mfa = self.security_manager.get_user_mfa(user.id)
                    
                    MFAVerification.record_attempt(
                        user_mfa_id=user_mfa.id,
                        method=method,
                        success=False,
                        failure_reason="Invalid code",
                        otp_used=code,
                        ip_address=ip_address
                    )
                    
                    attempts = MFASessionState.increment_attempts()
                    max_attempts = current_app.config.get('MFA_MAX_SESSION_ATTEMPTS', 3)
                    
                    if attempts >= max_attempts:
                        lockout_duration = current_app.config.get('MFA_SESSION_LOCKOUT', 300)
                        MFASessionState.set_lockout(lockout_duration)
                        user_mfa.record_failed_attempt()
                        
                        return {
                            "success": False,
                            "message": "Too many failed attempts. Session locked.",
                            "locked": True
                        }
                    
                    return {
                        "success": False,
                        "message": "Invalid verification code",
                        "attempts_remaining": max_attempts - attempts
                    }
            
            return {
                "success": False,
                "message": f"Unsupported MFA method: {method}"
            }
            
        except Exception as e:
            log.error(f"MFA verification failed: {str(e)}")
            return {
                "success": False,
                "message": "Verification failed due to system error"
            }
    
    def _generate_challenge_code(self, length: int = 6) -> str:
        """
        Generate random challenge code.
        
        Args:
            length: Length of code to generate
            
        Returns:
            str: Random numeric code
        """
        import secrets
        return ''.join([str(secrets.randbelow(10)) for _ in range(length)])


def mfa_required(f):
    """
    Decorator to require MFA verification for route access.
    
    Usage:
        @app.route('/sensitive')
        @login_required
        @mfa_required
        def sensitive_view():
            return "Sensitive data"
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is authenticated
        if not current_user.is_authenticated:
            return redirect(url_for('AuthView.login'))
        
        # Get security manager
        security_manager = current_app.appbuilder.sm
        
        # Check if MFA is required
        if hasattr(security_manager, 'is_mfa_required'):
            if security_manager.is_mfa_required(current_user):
                # Check MFA session state
                if not MFASessionState.is_verified_and_valid():
                    # Redirect to MFA challenge
                    return redirect(url_for('MFAView.challenge'))
        
        return f(*args, **kwargs)
    
    return decorated_function


class MFASecurityManagerMixin:
    """
    Mixin to add MFA capabilities to PgAppForge SecurityManager.
    
    Extends the base SecurityManager with multi-factor authentication
    support including session management, policy enforcement, and
    authentication flow integration.
    
    Usage:
        class CustomSecurityManager(MFASecurityManagerMixin, SecurityManager):
            pass
    """
    
    def __init__(self, appbuilder):
        """
        Initialize MFA security manager.
        
        Args:
            appbuilder: PgAppForge instance
        """
        super().__init__(appbuilder)
        
        self.mfa_auth_handler = MFAAuthenticationHandler(self)
        self.policy_service = MFAPolicyService()
        
        # Register MFA views
        self._register_mfa_views()
        
        log.info("MFA Security Manager initialized")
    
    def _register_mfa_views(self):
        """Register MFA-related views with the application."""
        try:
            from .views import MFAView, MFASetupView
            
            if not self.appbuilder.get_app.config.get('FAB_ADD_SECURITY_VIEWS', True):
                return
            
            # Register MFA views
            self.appbuilder.add_view_no_menu(MFAView)
            self.appbuilder.add_view_no_menu(MFASetupView)
            
            log.debug("MFA views registered")
            
        except ImportError:
            log.warning("MFA views not available - views.py not implemented yet")
    
    def get_user_mfa(self, user_id: int) -> Optional[UserMFA]:
        """
        Get MFA configuration for a user.
        
        Args:
            user_id: User ID to lookup
            
        Returns:
            Optional[UserMFA]: User MFA configuration or None
        """
        return self.get_session.query(UserMFA).filter_by(user_id=user_id).first()
    
    def is_mfa_required(self, user) -> bool:
        """
        Check if MFA is required for a user.
        
        Args:
            user: PgAppForge User object
            
        Returns:
            bool: True if MFA is required
        """
        return self.mfa_auth_handler.is_mfa_required(user)
    
    def get_user_mfa_methods(self, user) -> List[str]:
        """
        Get available MFA methods for a user.
        
        Args:
            user: PgAppForge User object
            
        Returns:
            List[str]: Available MFA method names
        """
        return self.mfa_auth_handler.get_user_mfa_methods(user)
    
    def auth_user_ldap(self, username: str, password: str):
        """
        Override LDAP authentication to integrate MFA.
        
        Args:
            username: Username to authenticate
            password: Password to verify
            
        Returns:
            User object if authenticated, None otherwise
        """
        # First perform standard LDAP authentication
        user = super().auth_user_ldap(username, password)
        
        if user and self.is_mfa_required(user):
            # Set MFA required state
            MFASessionState.set_state(MFASessionState.REQUIRED, user.id)
            
            # Store user in session for MFA flow
            session['_mfa_pending_user_id'] = user.id
            
            log.info(f"LDAP authentication successful for {username}, MFA required")
        
        return user
    
    def auth_user_db(self, username: str, password: str):
        """
        Override database authentication to integrate MFA.
        
        Args:
            username: Username to authenticate
            password: Password to verify
            
        Returns:
            User object if authenticated, None otherwise
        """
        # First perform standard database authentication
        user = super().auth_user_db(username, password)
        
        if user and self.is_mfa_required(user):
            # Set MFA required state
            MFASessionState.set_state(MFASessionState.REQUIRED, user.id)
            
            # Store user in session for MFA flow
            session['_mfa_pending_user_id'] = user.id
            
            log.info(f"Database authentication successful for {username}, MFA required")
        
        return user
    
    def auth_user_oid(self, email: str):
        """
        Override OpenID authentication to integrate MFA.
        
        Args:
            email: Email to authenticate
            
        Returns:
            User object if authenticated, None otherwise
        """
        # First perform standard OpenID authentication
        user = super().auth_user_oid(email)
        
        if user and self.is_mfa_required(user):
            # Set MFA required state
            MFASessionState.set_state(MFASessionState.REQUIRED, user.id)
            
            # Store user in session for MFA flow
            session['_mfa_pending_user_id'] = user.id
            
            log.info(f"OpenID authentication successful for {email}, MFA required")
        
        return user
    
    def auth_user_oauth(self, userinfo):
        """
        Override OAuth authentication to integrate MFA.
        
        Args:
            userinfo: OAuth user information
            
        Returns:
            User object if authenticated, None otherwise
        """
        # First perform standard OAuth authentication
        user = super().auth_user_oauth(userinfo)
        
        if user and self.is_mfa_required(user):
            # Set MFA required state
            MFASessionState.set_state(MFASessionState.REQUIRED, user.id)
            
            # Store user in session for MFA flow
            session['_mfa_pending_user_id'] = user.id
            
            log.info(f"OAuth authentication successful for user {user.id}, MFA required")
        
        return user
    
    def auth_user_remote_user(self, username: str):
        """
        Override remote user authentication to integrate MFA.
        
        Args:
            username: Username from remote authentication
            
        Returns:
            User object if authenticated, None otherwise
        """
        # First perform standard remote user authentication
        user = super().auth_user_remote_user(username)
        
        if user and self.is_mfa_required(user):
            # Set MFA required state
            MFASessionState.set_state(MFASessionState.REQUIRED, user.id)
            
            # Store user in session for MFA flow
            session['_mfa_pending_user_id'] = user.id
            
            log.info(f"Remote user authentication successful for {username}, MFA required")
        
        return user
    
    def before_request(self):
        """
        Hook called before each request to enforce MFA policies.
        """
        super().before_request()
        
        # Skip MFA checks for certain routes
        if self._should_skip_mfa_check():
            return
        
        # Check if user needs MFA verification
        if current_user.is_authenticated and self.is_mfa_required(current_user):
            # Check if already verified
            if MFASessionState.is_verified_and_valid():
                return
            
            # Check if this is MFA-related route
            if self._is_mfa_route():
                return
            
            # Redirect to MFA challenge
            return redirect(url_for('MFAView.challenge'))
    
    def _should_skip_mfa_check(self) -> bool:
        """
        Check if MFA verification should be skipped for current request.
        
        Returns:
            bool: True if MFA check should be skipped
        """
        # Skip for static files, health checks, etc.
        skip_endpoints = [
            'static',
            'AuthView.logout', 
            'MFAView.challenge',
            'MFAView.verify',
            'MFASetupView.setup',
            'UtilView.back'
        ]
        
        return request.endpoint in skip_endpoints
    
    def _is_mfa_route(self) -> bool:
        """
        Check if current route is MFA-related.
        
        Returns:
            bool: True if this is an MFA route
        """
        mfa_endpoints = [
            'MFAView.challenge',
            'MFAView.verify', 
            'MFAView.methods',
            'MFASetupView.setup',
            'MFASetupView.complete'
        ]
        
        return request.endpoint in mfa_endpoints


__all__ = [
    'MFASecurityManagerMixin',
    'MFASessionState',
    'MFAAuthenticationHandler',
    'mfa_required'
]