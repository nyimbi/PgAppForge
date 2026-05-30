"""
PgAppForge Multi-Factor Authentication Module

This module provides comprehensive multi-factor authentication capabilities
for PgAppForge applications, including TOTP, SMS, and Email MFA support
with backup codes and organizational policies.

Example Usage:
    from pgappforge.security.mfa import MFASecurityManagerMixin
    from pgappforge.security.mfa.services import TOTPService, SMSService
    
    # Enable MFA in your security manager
    class CustomSecurityManager(MFASecurityManagerMixin, SecurityManager):
        pass
    
    # Use MFA services
    totp_service = TOTPService()
    secret = totp_service.generate_secret()
    qr_code = totp_service.generate_qr_code(secret, 'user@example.com')

Dependencies:
    - pyotp: Time-based OTP generation and validation
    - qrcode: QR code generation for TOTP setup
    - cryptography: Secure secret storage and encryption
    - twilio: SMS delivery service integration
    - flask-mail: Email delivery for email-based MFA

Components:
    - models: Database models for MFA data storage
    - services: Business logic for MFA operations
    - views: Web interface for MFA management
    - manager_mixin: PgAppForge SecurityManager integration

Security Considerations:
    - All MFA secrets are encrypted at rest
    - Backup codes are hashed before storage
    - Rate limiting prevents brute force attacks
    - Audit trails track all MFA operations
"""

from .models import UserMFA, MFABackupCode, MFAVerification, MFAPolicy
from .services import (
    TOTPService, SMSService, EmailService, 
    BackupCodeService, MFAPolicyService, MFAOrchestrationService
)
from .manager_mixin import (
    MFASecurityManagerMixin, MFASessionState, 
    MFAAuthenticationHandler, mfa_required
)
from .views import (
    MFAView, MFASetupView, MFAManagementView,
    MFABaseForm, MFASetupForm, MFAChallengeForm, MFABackupCodesForm
)

__version__ = '1.0.0'

__all__ = [
    # Models
    'UserMFA',
    'MFABackupCode', 
    'MFAVerification',
    'MFAPolicy',
    
    # Services
    'TOTPService',
    'SMSService',
    'EmailService',
    'BackupCodeService',
    'MFAPolicyService',
    'MFAOrchestrationService',
    
    # Integration
    'MFASecurityManagerMixin',
    'MFASessionState',
    'MFAAuthenticationHandler',
    'mfa_required',
    
    # Views
    'MFAView',
    'MFASetupView',
    'MFAManagementView',
    'MFABaseForm',
    'MFASetupForm', 
    'MFAChallengeForm',
    'MFABackupCodesForm',
]