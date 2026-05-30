"""
Database Models for PgAppForge MFA and Passkey Support

Provides secure storage for WebAuthn credentials, MFA configurations,
backup codes, and audit logs with proper encryption and data protection.

SECURITY FEATURES:
- Encrypted credential storage
- Secure random token generation
- Audit trail for all MFA operations
- Rate limiting and abuse prevention
- Proper database constraints and validation
"""

import os
import json
import secrets
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from enum import Enum

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, LargeBinary, Index
from sqlalchemy import ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property
from pgappforge import Model
from pgappforge.security.sqla.models import User

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class MFAMethodType(Enum):
    """Supported MFA method types."""
    TOTP = "totp"
    SMS = "sms"
    EMAIL = "email"
    WEBAUTHN = "webauthn"
    BACKUP_CODE = "backup_code"
    APP_PASSWORD = "app_password"


class WebAuthnCredentialType(Enum):
    """WebAuthn credential types."""
    PLATFORM = "platform"  # Touch ID, Face ID, Windows Hello
    ROAMING = "cross-platform"  # Hardware keys, mobile devices
    UNKNOWN = "unknown"


class MFACredential(Model):
    """
    User MFA method configurations and credentials.
    
    Stores encrypted credential data for various MFA methods
    with proper security controls and audit trails.
    """
    
    __tablename__ = 'mfa_credentials'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    method_type = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)  # User-friendly name
    
    # Encrypted credential data (method-specific)
    encrypted_data = Column(LargeBinary, nullable=False)
    encryption_key_id = Column(String(64), nullable=False)
    
    # Status and configuration
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    
    # Security metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    verified_at = Column(DateTime)
    last_used_at = Column(DateTime)
    use_count = Column(Integer, default=0, nullable=False)
    
    # Rate limiting and security
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime)
    last_failure_at = Column(DateTime)
    
    # Device/location tracking
    created_ip = Column(String(45))  # IPv6 support
    created_user_agent = Column(String(500))
    last_used_ip = Column(String(45))
    last_used_user_agent = Column(String(500))
    
    # Relationships
    user = relationship("User", backref=backref("mfa_credentials", cascade="all, delete-orphan"))
    
    # Database constraints
    __table_args__ = (
        Index('idx_mfa_user_method', 'user_id', 'method_type'),
        Index('idx_mfa_active', 'is_active', 'method_type'),
        UniqueConstraint('user_id', 'method_type', 'name', name='uq_user_method_name'),
        CheckConstraint('failed_attempts >= 0', name='ck_failed_attempts_positive'),
        CheckConstraint('use_count >= 0', name='ck_use_count_positive'),
    )
    
    @hybrid_property
    def is_locked(self) -> bool:
        """Check if credential is temporarily locked due to failed attempts."""
        return (self.locked_until is not None and 
                self.locked_until > datetime.now(tz=timezone.utc))
    
    def get_decrypted_data(self) -> Dict[str, Any]:
        """
        Decrypt and return credential data.
        
        Returns:
            dict: Decrypted credential data
        """
        try:
            # Get encryption key (implement key management)
            key = self._get_encryption_key()
            if not key:
                raise ValueError("Encryption key not available")
            
            # Decrypt data
            fernet = Fernet(key)
            decrypted_bytes = fernet.decrypt(self.encrypted_data)
            
            return json.loads(decrypted_bytes.decode('utf-8'))
            
        except Exception as e:
            # Log security event
            from ..approval.audit_logger import ApprovalAuditLogger
            audit_logger = ApprovalAuditLogger()
            audit_logger.log_security_violation(
                'mfa_decryption_failed', self.user, None, {
                    'credential_id': self.id,
                    'method_type': self.method_type,
                    'error': str(e)
                }
            )
            raise
    
    def set_encrypted_data(self, data: Dict[str, Any]) -> None:
        """
        Encrypt and store credential data.
        
        Args:
            data: Credential data to encrypt
        """
        try:
            # Generate encryption key
            key, key_id = self._generate_encryption_key()
            
            # Encrypt data
            fernet = Fernet(key)
            json_data = json.dumps(data).encode('utf-8')
            encrypted_data = fernet.encrypt(json_data)
            
            self.encrypted_data = encrypted_data
            self.encryption_key_id = key_id
            
        except Exception as e:
            # Log security event
            from ..approval.audit_logger import ApprovalAuditLogger
            audit_logger = ApprovalAuditLogger()
            audit_logger.log_security_violation(
                'mfa_encryption_failed', self.user, None, {
                    'credential_id': self.id,
                    'method_type': self.method_type,
                    'error': str(e)
                }
            )
            raise
    
    def _get_encryption_key(self) -> Optional[bytes]:
        """Get encryption key for this credential."""
        # Implement secure key management (Azure Key Vault, AWS KMS, etc.)
        # For now, use environment-based key derivation
        master_key = os.environ.get('FLASK_APP_MFA_MASTER_KEY')
        if not master_key:
            return None
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.encryption_key_id.encode(),
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
    
    def _generate_encryption_key(self) -> tuple[bytes, str]:
        """Generate new encryption key and key ID."""
        key_id = secrets.token_hex(32)
        master_key = os.environ.get('FLASK_APP_MFA_MASTER_KEY')
        if not master_key:
            raise ValueError("Master key not configured")
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=key_id.encode(),
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
        
        return key, key_id
    
    def record_successful_use(self, ip_address: str = None, user_agent: str = None) -> None:
        """Record successful use of this credential."""
        self.use_count += 1
        self.last_used_at = datetime.now(tz=timezone.utc)
        self.failed_attempts = 0  # Reset on success
        self.locked_until = None
        
        if ip_address:
            self.last_used_ip = ip_address
        if user_agent:
            self.last_used_user_agent = user_agent
    
    def record_failed_attempt(self, ip_address: str = None) -> None:
        """Record failed authentication attempt."""
        self.failed_attempts += 1
        self.last_failure_at = datetime.now(tz=timezone.utc)
        
        # Lock credential after 5 failed attempts
        if self.failed_attempts >= 5:
            self.locked_until = datetime.now(tz=timezone.utc) + timedelta(minutes=15)
    
    def __repr__(self):
        return f"<MFACredential {self.user.username}:{self.method_type}:{self.name}>"


class WebAuthnCredential(Model):
    """
    WebAuthn passkey credentials for passwordless authentication.
    
    Stores WebAuthn credential data with proper security controls
    and device management capabilities.
    """
    
    __tablename__ = 'webauthn_credentials'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    
    # WebAuthn credential data
    credential_id = Column(LargeBinary, nullable=False, unique=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, default=0, nullable=False)
    
    # Credential metadata
    name = Column(String(100), nullable=False)  # User-friendly name
    credential_type = Column(String(20), default=WebAuthnCredentialType.UNKNOWN.value)
    
    # Attestation data (optional)
    attestation_object = Column(LargeBinary)
    attestation_format = Column(String(50))
    attestation_trust = Column(String(20))  # verified, self, none
    
    # Device information
    device_type = Column(String(50))  # mobile, desktop, hardware_key
    device_name = Column(String(100))
    browser_name = Column(String(50))
    os_name = Column(String(50))
    
    # Status and security
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_backup_eligible = Column(Boolean, default=False, nullable=False)
    is_backup_state = Column(Boolean, default=False, nullable=False)
    
    # Usage tracking
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime)
    use_count = Column(Integer, default=0, nullable=False)
    
    # Security tracking
    created_ip = Column(String(45))
    created_user_agent = Column(String(500))
    last_used_ip = Column(String(45))
    last_used_user_agent = Column(String(500))
    
    # Relationships
    user = relationship("User", backref=backref("webauthn_credentials", cascade="all, delete-orphan"))
    
    # Database constraints
    __table_args__ = (
        Index('idx_webauthn_user', 'user_id'),
        Index('idx_webauthn_credential_id', 'credential_id'),
        Index('idx_webauthn_active', 'is_active'),
        CheckConstraint('sign_count >= 0', name='ck_sign_count_positive'),
        CheckConstraint('use_count >= 0', name='ck_use_count_positive'),
    )
    
    @hybrid_property
    def credential_id_b64(self) -> str:
        """Get base64-encoded credential ID."""
        return base64.urlsafe_b64encode(self.credential_id).decode('utf-8').rstrip('=')
    
    @hybrid_property
    def public_key_b64(self) -> str:
        """Get base64-encoded public key."""
        return base64.urlsafe_b64encode(self.public_key).decode('utf-8').rstrip('=')
    
    def update_sign_count(self, new_count: int) -> bool:
        """
        Update sign count with replay attack protection.
        
        Args:
            new_count: New sign count from authenticator
            
        Returns:
            bool: True if update is valid, False if potential replay attack
        """
        if new_count <= self.sign_count:
            # Potential replay attack
            from ..approval.audit_logger import ApprovalAuditLogger
            audit_logger = ApprovalAuditLogger()
            audit_logger.log_security_violation(
                'webauthn_replay_attack', self.user, None, {
                    'credential_id': self.credential_id_b64,
                    'current_count': self.sign_count,
                    'received_count': new_count
                }
            )
            return False
        
        self.sign_count = new_count
        return True
    
    def record_use(self, ip_address: str = None, user_agent: str = None) -> None:
        """Record successful use of this credential."""
        self.use_count += 1
        self.last_used_at = datetime.now(tz=timezone.utc)
        
        if ip_address:
            self.last_used_ip = ip_address
        if user_agent:
            self.last_used_user_agent = user_agent
    
    def __repr__(self):
        return f"<WebAuthnCredential {self.user.username}:{self.name}>"


class MFAChallenge(Model):
    """
    Temporary storage for MFA challenges and verification codes.
    
    Stores time-limited challenges for various MFA methods with
    proper expiration and security controls.
    """
    
    __tablename__ = 'mfa_challenges'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    
    # Challenge data
    challenge_type = Column(String(50), nullable=False)  # totp, sms, email, webauthn
    challenge_data = Column(Text)  # Encrypted challenge-specific data
    response_required = Column(Boolean, default=True, nullable=False)
    
    # Verification code (for SMS/email)
    verification_code = Column(String(20))
    verification_code_hash = Column(String(128))
    
    # WebAuthn challenge data
    webauthn_challenge = Column(LargeBinary)
    webauthn_user_handle = Column(LargeBinary)
    
    # Status and timing
    is_completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    
    # Security tracking
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    
    # Relationships
    user = relationship("User", backref=backref("mfa_challenges", cascade="all, delete-orphan"))
    
    # Database constraints
    __table_args__ = (
        Index('idx_challenge_user', 'user_id'),
        Index('idx_challenge_expires', 'expires_at'),
        Index('idx_challenge_type', 'challenge_type'),
        CheckConstraint('attempts >= 0', name='ck_attempts_positive'),
        CheckConstraint('max_attempts > 0', name='ck_max_attempts_positive'),
        CheckConstraint('expires_at > created_at', name='ck_expires_after_created'),
    )
    
    @hybrid_property
    def is_expired(self) -> bool:
        """Check if challenge has expired."""
        return datetime.now(tz=timezone.utc) > self.expires_at
    
    @hybrid_property
    def is_exhausted(self) -> bool:
        """Check if challenge attempts are exhausted."""
        return self.attempts >= self.max_attempts
    
    @hybrid_property
    def is_valid(self) -> bool:
        """Check if challenge is valid for use."""
        return (not self.is_completed and 
                not self.is_expired and 
                not self.is_exhausted)
    
    def verify_code(self, provided_code: str) -> bool:
        """
        Verify the provided code against the challenge.
        
        Args:
            provided_code: Code provided by user
            
        Returns:
            bool: True if code is valid
        """
        import hashlib
        import hmac
        
        self.attempts += 1
        
        if not self.is_valid:
            return False
        
        # Time-constant comparison
        if self.verification_code_hash:
            provided_hash = hashlib.sha256(provided_code.encode()).hexdigest()
            is_valid = hmac.compare_digest(self.verification_code_hash, provided_hash)
        else:
            is_valid = hmac.compare_digest(self.verification_code or '', provided_code)
        
        if is_valid:
            self.is_completed = True
            self.completed_at = datetime.now(tz=timezone.utc)
        
        return is_valid
    
    def __repr__(self):
        return f"<MFAChallenge {self.user.username}:{self.challenge_type}>"


class BackupCode(Model):
    """
    Recovery backup codes for account access when MFA is unavailable.
    
    Stores securely hashed backup codes with usage tracking
    and proper security controls.
    """
    
    __tablename__ = 'backup_codes'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    
    # Code storage (hashed)
    code_hash = Column(String(128), nullable=False, unique=True)
    code_partial = Column(String(8), nullable=False)  # First few characters for display
    
    # Status tracking
    is_used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    used_at = Column(DateTime)
    
    # Security tracking
    used_ip = Column(String(45))
    used_user_agent = Column(String(500))
    
    # Relationships
    user = relationship("User", backref=backref("backup_codes", cascade="all, delete-orphan"))
    
    # Database constraints
    __table_args__ = (
        Index('idx_backup_user', 'user_id'),
        Index('idx_backup_hash', 'code_hash'),
        Index('idx_backup_unused', 'user_id', 'is_used'),
    )
    
    @classmethod
    def generate_codes_for_user(cls, user_id: int, count: int = 10) -> List[str]:
        """
        Generate backup codes for a user.
        
        Args:
            user_id: User ID to generate codes for
            count: Number of codes to generate
            
        Returns:
            list: List of generated codes (plain text)
        """
        import hashlib
        from pgappforge import db
        
        codes = []
        
        for _ in range(count):
            # Generate secure random code
            code = secrets.token_hex(8).upper()
            code_formatted = f"{code[:4]}-{code[4:]}"
            
            # Hash for storage
            code_hash = hashlib.sha256(code_formatted.encode()).hexdigest()
            
            # Create backup code record
            backup_code = cls(
                user_id=user_id,
                code_hash=code_hash,
                code_partial=code_formatted[:4]
            )
            db.session.add(backup_code)
            codes.append(code_formatted)
        
        return codes
    
    def verify_code(self, provided_code: str) -> bool:
        """
        Verify provided backup code.
        
        Args:
            provided_code: Code provided by user
            
        Returns:
            bool: True if code is valid and unused
        """
        import hashlib
        import hmac
        
        if self.is_used:
            return False
        
        # Hash provided code
        provided_hash = hashlib.sha256(provided_code.encode()).hexdigest()
        
        # Time-constant comparison
        if hmac.compare_digest(self.code_hash, provided_hash):
            self.is_used = True
            self.used_at = datetime.now(tz=timezone.utc)
            return True
        
        return False
    
    def __repr__(self):
        return f"<BackupCode {self.user.username}:{self.code_partial}***>"


class MFAAuditLog(Model):
    """
    Audit log for MFA-related security events.
    
    Comprehensive logging of all MFA operations for security
    monitoring and compliance requirements.
    """
    
    __tablename__ = 'mfa_audit_log'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'))
    
    # Event information
    event_type = Column(String(100), nullable=False)
    event_category = Column(String(50), nullable=False)  # auth, config, security
    event_result = Column(String(20), nullable=False)  # success, failure, error
    
    # Event details
    method_type = Column(String(50))
    credential_id = Column(String(100))
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    location = Column(String(100))
    
    # Additional context
    event_data = Column(Text)  # JSON data
    risk_score = Column(Integer)  # 0-100
    
    # Timing
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", backref=backref("mfa_audit_logs"))
    
    # Database constraints
    __table_args__ = (
        Index('idx_audit_user', 'user_id'),
        Index('idx_audit_event', 'event_type'),
        Index('idx_audit_created', 'created_at'),
        Index('idx_audit_result', 'event_result'),
    )
    
    def __repr__(self):
        username = self.user.username if self.user else 'system'
        return f"<MFAAuditLog {username}:{self.event_type}:{self.event_result}>"

# Compatibility aliases — mfa/__init__.py and security/sqla/models.py use these names
UserMFA = MFACredential
MFABackupCode = BackupCode
MFABackupCodes = BackupCode
MFAVerification = MFAChallenge
MFAVerificationAttempt = MFAChallenge
MFAPolicy = MFAAuditLog  # closest equivalent; MFAPolicy class does not exist
