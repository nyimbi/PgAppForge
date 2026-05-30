# Flask-AppBuilder Passkeys and MFA Integration

## Overview

Comprehensive Multi-Factor Authentication (MFA) and WebAuthn passkey support for Flask-AppBuilder, providing modern passwordless authentication and enhanced security for high-value operations.

## Architecture

### Core Components

1. **WebAuthn Passkey System**
   - Hardware security keys (YubiKey, etc.)
   - Platform authenticators (Touch ID, Face ID, Windows Hello)
   - Cross-platform roaming authenticators
   - Passwordless and second-factor authentication

2. **Multi-Factor Authentication**
   - TOTP (Time-based One-Time Passwords)
   - SMS-based verification codes
   - Email-based verification codes
   - Recovery/backup codes
   - App-specific passwords

3. **Security Integration**
   - Approval workflow MFA requirements
   - Step-up authentication for sensitive operations
   - Risk-based authentication triggers
   - Session security enhancement

### Integration Points

- **Flask-AppBuilder Security Manager**: Extends existing auth system
- **Approval System**: Leverages MFA for high-value approvals
- **Cache Manager**: Caches credentials and validation states
- **Audit Logger**: Comprehensive MFA event logging

## Features

### Passkey Support
- ✅ Registration flow with attestation validation
- ✅ Authentication flow with assertion validation
- ✅ Credential management (rename, delete, view usage)
- ✅ Cross-device synchronization support
- ✅ Fallback to traditional authentication

### MFA Methods
- ✅ TOTP with QR code setup (Google Authenticator, Authy, etc.)
- ✅ SMS codes with rate limiting and fraud detection
- ✅ Email codes with secure token generation
- ✅ Recovery codes with secure storage
- ✅ App-specific passwords for API access

### Security Features
- ✅ Risk-based authentication (unusual location, device, behavior)
- ✅ Step-up authentication for sensitive operations
- ✅ Session binding and validation
- ✅ Comprehensive audit trails
- ✅ Rate limiting and abuse prevention

### User Experience
- ✅ Progressive enhancement (works without JavaScript)
- ✅ Mobile-responsive design
- ✅ Accessibility compliance (WCAG 2.1)
- ✅ Multi-language support
- ✅ Clear error messages and recovery flows

## Configuration

```python
# In your Flask-AppBuilder configuration
MFA_CONFIG = {
    'enabled': True,
    'required_for_roles': ['Admin', 'ApprovalManager'],
    'methods': {
        'passkey': {'enabled': True, 'required': False},
        'totp': {'enabled': True, 'required': False},
        'sms': {'enabled': True, 'provider': 'twilio'},
        'email': {'enabled': True, 'required': False},
        'backup_codes': {'enabled': True, 'count': 10}
    },
    'step_up_auth': {
        'enabled': True,
        'triggers': ['approval_operations', 'admin_actions'],
        'timeout_minutes': 15
    },
    'risk_assessment': {
        'enabled': True,
        'factors': ['location', 'device', 'time_of_day', 'velocity']
    }
}

WEBAUTHN_CONFIG = {
    'rp_name': 'Flask-AppBuilder Application',
    'rp_id': 'example.com',  # Your domain
    'origins': ['https://example.com'],
    'attestation_requirement': 'preferred',
    'user_verification': 'preferred',
    'timeout': 60000,  # 60 seconds
    'algorithms': [-7, -35, -36, -257, -258, -259, -37, -38, -39]
}
```

## Database Schema

### New Tables
- `mfa_credentials` - Stores MFA method configurations
- `webauthn_credentials` - Stores WebAuthn passkey data
- `mfa_challenges` - Temporary challenge storage
- `mfa_audit_log` - MFA-specific audit events
- `backup_codes` - Recovery code storage

### Extensions to Existing Tables
- `ab_user` - Add MFA preference fields
- `approval_request` - Add MFA validation tracking

## API Endpoints

### WebAuthn Passkey APIs
- `POST /api/v1/auth/passkey/register/begin` - Start passkey registration
- `POST /api/v1/auth/passkey/register/complete` - Complete passkey registration
- `POST /api/v1/auth/passkey/authenticate/begin` - Start passkey authentication
- `POST /api/v1/auth/passkey/authenticate/complete` - Complete passkey authentication
- `GET /api/v1/auth/passkey/credentials` - List user's passkeys
- `DELETE /api/v1/auth/passkey/credentials/{id}` - Delete a passkey

### MFA Management APIs
- `GET /api/v1/auth/mfa/status` - Get user's MFA status
- `POST /api/v1/auth/mfa/totp/setup` - Setup TOTP authentication
- `POST /api/v1/auth/mfa/totp/verify` - Verify TOTP code
- `POST /api/v1/auth/mfa/sms/send` - Send SMS verification code
- `POST /api/v1/auth/mfa/email/send` - Send email verification code
- `POST /api/v1/auth/mfa/verify` - Verify any MFA method
- `GET /api/v1/auth/mfa/backup-codes` - Generate recovery codes

## Security Considerations

### WebAuthn Security
- Proper origin validation
- Attestation statement verification
- Challenge uniqueness and timeout
- Credential source validation
- User presence and verification requirements

### MFA Security
- Secure random token generation
- Time-based validation windows
- Rate limiting and lockout policies
- Secure storage of secrets and recovery codes
- Protection against replay attacks

### Integration Security
- Session enhancement after MFA validation
- Step-up authentication for sensitive operations
- Risk-based triggers for additional verification
- Comprehensive audit logging
- Protection against social engineering

## Implementation Phases

### Phase 1: Core Infrastructure
- Database models and migrations
- Basic WebAuthn server implementation
- TOTP implementation with QR codes
- Integration with Flask-AppBuilder security

### Phase 2: Enhanced Features
- SMS and email MFA methods
- Backup/recovery codes
- Risk-based authentication
- Step-up authentication flows

### Phase 3: Advanced Features
- Cross-device passkey synchronization
- Advanced risk assessment
- Machine learning fraud detection
- Enterprise SSO integration

### Phase 4: Mobile and API
- Mobile app support
- API authentication with MFA
- Offline capability
- Biometric integration

## Dependencies

- `webauthn` - WebAuthn server library
- `qrcode` - QR code generation for TOTP
- `pyotp` - TOTP implementation
- `twilio` - SMS provider (optional)
- `cryptography` - Enhanced cryptographic operations
- `pycryptodome` - Additional crypto primitives

## Testing Strategy

- Unit tests for all MFA methods
- Integration tests with approval system
- Security penetration testing
- Cross-browser WebAuthn testing
- Mobile device testing
- Performance and load testing