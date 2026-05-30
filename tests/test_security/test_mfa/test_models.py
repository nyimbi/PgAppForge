"""
Unit tests for MFA database models.

This module contains comprehensive unit tests for all MFA-related database models
including UserMFA, MFABackupCode, MFAVerification, and MFAPolicy.

Test Coverage:
    - Model creation and validation
    - Encryption/decryption of sensitive fields
    - Business logic methods
    - Database constraints and relationships
    - Event listeners and triggers
"""

import pytest
import secrets
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.models.sqla import Base
from werkzeug.security import check_password_hash
from cryptography.fernet import Fernet

from pgappforge.security.mfa.models import (
    MFAEncryptionMixin, UserMFA, MFABackupCode, 
    MFAVerification, MFAPolicy
)


class TestMFAEncryptionMixin:
    """Test cases for MFA encryption functionality."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application with encryption key."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-secret-key'
        app.config['MFA_ENCRYPTION_KEY'] = Fernet.generate_key()
        app.config['TESTING'] = True
        return app
    
    @pytest.fixture
    def encryption_mixin(self, app):
        """Create MFAEncryptionMixin instance."""
        with app.app_context():
            return MFAEncryptionMixin()
    
    def test_get_encryption_key_configured(self, app, encryption_mixin):
        """Test encryption key retrieval when properly configured."""
        with app.app_context():
            key = encryption_mixin._get_encryption_key()
            assert key is not None
            assert len(key) == 44  # Fernet key length
    
    def test_get_encryption_key_missing_production(self, encryption_mixin):
        """Test encryption key error in production without key."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test'
        app.config['TESTING'] = False  # Production mode
        
        with app.app_context():
            with pytest.raises(ValueError, match="MFA_ENCRYPTION_KEY must be configured"):
                encryption_mixin._get_encryption_key()
    
    def test_get_encryption_key_debug_autogenerate(self, encryption_mixin):
        """Test auto-generation of encryption key in debug mode."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test'
        app.config['DEBUG'] = True
        
        with app.app_context():
            with patch('pgappforge.security.mfa.models.log') as mock_log:
                key = encryption_mixin._get_encryption_key()
                assert key is not None
                mock_log.warning.assert_called_once()
    
    def test_encrypt_decrypt_data(self, app, encryption_mixin):
        """Test data encryption and decryption roundtrip."""
        with app.app_context():
            test_data = "sensitive-secret-data"
            
            # Encrypt data
            encrypted = encryption_mixin._encrypt_data(test_data)
            assert encrypted != test_data
            assert len(encrypted) > len(test_data)
            
            # Decrypt data
            decrypted = encryption_mixin._decrypt_data(encrypted)
            assert decrypted == test_data
    
    def test_encrypt_decrypt_empty_data(self, app, encryption_mixin):
        """Test encryption/decryption of empty or None data."""
        with app.app_context():
            # Test None
            assert encryption_mixin._encrypt_data(None) is None
            assert encryption_mixin._decrypt_data(None) is None
            
            # Test empty string
            assert encryption_mixin._encrypt_data("") == ""
            assert encryption_mixin._decrypt_data("") == ""


class TestUserMFA:
    """Test cases for UserMFA model."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application with database."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'MFA_ENCRYPTION_KEY': Fernet.generate_key(),
            'MFA_MAX_FAILED_ATTEMPTS': 3,
            'MFA_LOCKOUT_DURATION': 300,  # 5 minutes
            'TESTING': True
        })
        
        db = SQLA(app)
        appbuilder = AppBuilder(app, db.session)
        
        with app.app_context():
            Base.metadata.create_all(db.engine)
            
        return app
    
    @pytest.fixture
    def db(self, app):
        """Get database session."""
        with app.app_context():
            from pgappforge import db
            return db
    
    @pytest.fixture
    def user_mfa(self, app, db):
        """Create test UserMFA instance."""
        with app.app_context():
            mfa = UserMFA(user_id=1)
            db.session.add(mfa)
            db.session.commit()
            return mfa
    
    def test_user_mfa_creation(self, app, db):
        """Test UserMFA model creation with defaults."""
        with app.app_context():
            mfa = UserMFA(user_id=1)
            
            assert mfa.user_id == 1
            assert mfa.is_enabled is False
            assert mfa.is_enforced is False
            assert mfa.setup_completed is False
            assert mfa.failed_attempts == 0
            assert mfa.locked_until is None
            assert mfa.setup_token is not None  # Generated by event listener
    
    def test_totp_secret_encryption(self, app, db, user_mfa):
        """Test TOTP secret encryption and decryption."""
        with app.app_context():
            secret = "JBSWY3DPEHPK3PXP"
            user_mfa.totp_secret = secret
            
            # Check encrypted storage
            assert user_mfa.totp_secret_encrypted is not None
            assert user_mfa.totp_secret_encrypted != secret
            
            # Check decryption
            assert user_mfa.totp_secret == secret
            
            db.session.commit()
            
            # Verify persistence
            db.session.refresh(user_mfa)
            assert user_mfa.totp_secret == secret
    
    def test_phone_number_encryption(self, app, db, user_mfa):
        """Test phone number encryption and decryption."""
        with app.app_context():
            phone = "+1234567890"
            user_mfa.phone_number = phone
            
            # Check encrypted storage
            assert user_mfa.phone_number_encrypted is not None
            assert user_mfa.phone_number_encrypted != phone
            
            # Check decryption
            assert user_mfa.phone_number == phone
    
    def test_backup_phone_encryption(self, app, db, user_mfa):
        """Test backup phone encryption and decryption."""
        with app.app_context():
            backup_phone = "+0987654321"
            user_mfa.backup_phone = backup_phone
            
            assert user_mfa.backup_phone_encrypted is not None
            assert user_mfa.backup_phone == backup_phone
    
    def test_recovery_email_encryption(self, app, db, user_mfa):
        """Test recovery email encryption and decryption."""
        with app.app_context():
            email = "recovery@example.com"
            user_mfa.recovery_email = email
            
            assert user_mfa.recovery_email_encrypted is not None
            assert user_mfa.recovery_email == email
    
    def test_preferred_method_validation(self, app, db):
        """Test validation of preferred MFA method."""
        with app.app_context():
            mfa = UserMFA(user_id=1)
            
            # Valid methods
            valid_methods = ['totp', 'sms', 'email', 'backup']
            for method in valid_methods:
                mfa.preferred_method = method
                assert mfa.preferred_method == method
            
            # Invalid method
            with pytest.raises(ValueError, match="Invalid MFA method"):
                mfa.preferred_method = "invalid_method"
    
    def test_is_locked_functionality(self, app, db, user_mfa):
        """Test account locking functionality."""
        with app.app_context():
            # Not locked initially
            assert user_mfa.is_locked() is False
            assert user_mfa.can_attempt_mfa() is True
            
            # Set lock in future
            user_mfa.locked_until = datetime.utcnow() + timedelta(minutes=10)
            assert user_mfa.is_locked() is True
            assert user_mfa.can_attempt_mfa() is False
            
            # Set lock in past
            user_mfa.locked_until = datetime.utcnow() - timedelta(minutes=10)
            assert user_mfa.is_locked() is False
            assert user_mfa.can_attempt_mfa() is True
    
    def test_record_failed_attempt(self, app, db, user_mfa):
        """Test recording failed MFA attempts and lockout."""
        with app.app_context():
            # First failed attempt
            user_mfa.record_failed_attempt()
            assert user_mfa.failed_attempts == 1
            assert user_mfa.locked_until is None
            
            # Second failed attempt
            user_mfa.record_failed_attempt()
            assert user_mfa.failed_attempts == 2
            assert user_mfa.locked_until is None
            
            # Third failed attempt (triggers lockout)
            user_mfa.record_failed_attempt()
            assert user_mfa.failed_attempts == 3
            assert user_mfa.locked_until is not None
            assert user_mfa.is_locked() is True
    
    def test_record_successful_attempt(self, app, db, user_mfa):
        """Test recording successful MFA attempts."""
        with app.app_context():
            # Set up failed attempts and lock
            user_mfa.failed_attempts = 5
            user_mfa.locked_until = datetime.utcnow() + timedelta(minutes=10)
            
            # Record successful attempt
            user_mfa.record_successful_attempt("totp")
            
            assert user_mfa.failed_attempts == 0
            assert user_mfa.locked_until is None
            assert user_mfa.last_used_method == "totp"
            assert user_mfa.last_success is not None
    
    def test_setup_token_generation(self, app, db, user_mfa):
        """Test setup token generation and verification."""
        with app.app_context():
            token = user_mfa.generate_setup_token()
            
            assert token is not None
            assert len(token) > 10  # URL-safe token should be reasonably long
            assert user_mfa.setup_token == token
            assert user_mfa.verify_setup_token(token) is True
            assert user_mfa.verify_setup_token("invalid") is False
            
            # Clear token
            user_mfa.clear_setup_token()
            assert user_mfa.setup_token is None
            assert user_mfa.verify_setup_token(token) is False
    
    def test_repr(self, app, db, user_mfa):
        """Test string representation."""
        with app.app_context():
            user_mfa.preferred_method = "totp"
            repr_str = repr(user_mfa)
            
            assert "UserMFA" in repr_str
            assert str(user_mfa.id) in repr_str
            assert str(user_mfa.user_id) in repr_str
            assert "totp" in repr_str


class TestMFABackupCode:
    """Test cases for MFABackupCode model."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'TESTING': True
        })
        
        db = SQLA(app)
        appbuilder = AppBuilder(app, db.session)
        
        with app.app_context():
            Base.metadata.create_all(db.engine)
            
        return app
    
    @pytest.fixture
    def db(self, app):
        """Get database session."""
        with app.app_context():
            from pgappforge import db
            return db
    
    @pytest.fixture
    def user_mfa(self, app, db):
        """Create UserMFA for backup codes."""
        with app.app_context():
            mfa = UserMFA(user_id=1)
            db.session.add(mfa)
            db.session.commit()
            return mfa
    
    def test_generate_codes(self, app, db, user_mfa):
        """Test backup code generation."""
        with app.app_context():
            codes = MFABackupCode.generate_codes(user_mfa.id, count=5)
            
            assert len(codes) == 5
            for code in codes:
                assert len(code) == 8
                assert code.isdigit()
            
            # Check database storage
            stored_codes = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa.id
            ).all()
            
            assert len(stored_codes) == 5
            for stored_code in stored_codes:
                assert stored_code.is_used is False
                assert stored_code.code_hash is not None
    
    def test_generate_codes_replaces_existing(self, app, db, user_mfa):
        """Test that generating new codes replaces unused existing codes."""
        with app.app_context():
            # Generate initial codes
            initial_codes = MFABackupCode.generate_codes(user_mfa.id, count=3)
            
            # Generate new codes
            new_codes = MFABackupCode.generate_codes(user_mfa.id, count=5)
            
            # Should have only new codes
            stored_codes = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa.id,
                is_used=False
            ).all()
            
            assert len(stored_codes) == 5
    
    def test_verify_and_consume_valid_code(self, app, db, user_mfa):
        """Test verification and consumption of valid backup code."""
        with app.app_context():
            codes = MFABackupCode.generate_codes(user_mfa.id, count=3)
            test_code = codes[0]
            
            # Verify and consume code
            result = MFABackupCode.verify_and_consume(
                user_mfa.id, test_code, ip_address="127.0.0.1"
            )
            
            assert result is True
            
            # Check code is marked as used
            used_code = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa.id,
                is_used=True
            ).first()
            
            assert used_code is not None
            assert used_code.used_at is not None
            assert used_code.used_from_ip == "127.0.0.1"
            
            # Code cannot be used again
            result = MFABackupCode.verify_and_consume(
                user_mfa.id, test_code, ip_address="127.0.0.1"
            )
            assert result is False
    
    def test_verify_and_consume_invalid_code(self, app, db, user_mfa):
        """Test verification of invalid backup code."""
        with app.app_context():
            MFABackupCode.generate_codes(user_mfa.id, count=3)
            
            # Try invalid code
            result = MFABackupCode.verify_and_consume(
                user_mfa.id, "00000000", ip_address="127.0.0.1"
            )
            
            assert result is False
            
            # No codes should be marked as used
            used_codes = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa.id,
                is_used=True
            ).all()
            
            assert len(used_codes) == 0
    
    def test_code_hashing(self, app, db, user_mfa):
        """Test that backup codes are properly hashed."""
        with app.app_context():
            codes = MFABackupCode.generate_codes(user_mfa.id, count=1)
            plain_code = codes[0]
            
            stored_code = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa.id
            ).first()
            
            # Hash should not match plain text
            assert stored_code.code_hash != plain_code
            
            # But hash should verify
            assert check_password_hash(stored_code.code_hash, plain_code)
    
    def test_repr(self, app, db, user_mfa):
        """Test string representation."""
        with app.app_context():
            codes = MFABackupCode.generate_codes(user_mfa.id, count=1)
            backup_code = db.session.query(MFABackupCode).first()
            
            repr_str = repr(backup_code)
            assert "MFABackupCode" in repr_str
            assert str(backup_code.id) in repr_str
            assert str(user_mfa.id) in repr_str


class TestMFAVerification:
    """Test cases for MFAVerification model."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'MFA_ENCRYPTION_KEY': Fernet.generate_key(),
            'TESTING': True
        })
        
        db = SQLA(app)
        appbuilder = AppBuilder(app, db.session)
        
        with app.app_context():
            Base.metadata.create_all(db.engine)
            
        return app
    
    @pytest.fixture
    def db(self, app):
        """Get database session."""
        with app.app_context():
            from pgappforge import db
            return db
    
    @pytest.fixture
    def user_mfa(self, app, db):
        """Create UserMFA for verification tests."""
        with app.app_context():
            mfa = UserMFA(user_id=1)
            db.session.add(mfa)
            db.session.commit()
            return mfa
    
    def test_record_attempt_success(self, app, db, user_mfa):
        """Test recording successful verification attempt."""
        with app.app_context():
            verification = MFAVerification.record_attempt(
                user_mfa_id=user_mfa.id,
                method="totp",
                success=True,
                otp_used="123456",
                ip_address="192.168.1.1",
                user_agent="Test Browser"
            )
            
            assert verification.user_mfa_id == user_mfa.id
            assert verification.method == "totp"
            assert verification.success is True
            assert verification.failure_reason is None
            assert verification.otp_used == "123456"
            assert verification.ip_address == "192.168.1.1"
            assert verification.user_agent == "Test Browser"
            assert verification.verification_time is not None
    
    def test_record_attempt_failure(self, app, db, user_mfa):
        """Test recording failed verification attempt."""
        with app.app_context():
            verification = MFAVerification.record_attempt(
                user_mfa_id=user_mfa.id,
                method="sms",
                success=False,
                failure_reason="Invalid code",
                otp_used="wrong_code",
                ip_address="10.0.0.1"
            )
            
            assert verification.success is False
            assert verification.failure_reason == "Invalid code"
            assert verification.method == "sms"
    
    def test_otp_encryption(self, app, db, user_mfa):
        """Test OTP encryption in verification records."""
        with app.app_context():
            otp = "secret123"
            verification = MFAVerification(
                user_mfa_id=user_mfa.id,
                method="totp",
                success=True
            )
            verification.otp_used = otp
            
            # Check encryption
            assert verification.otp_used_encrypted is not None
            assert verification.otp_used_encrypted != otp
            
            # Check decryption
            assert verification.otp_used == otp
    
    def test_method_validation(self, app, db, user_mfa):
        """Test MFA method validation."""
        with app.app_context():
            verification = MFAVerification(
                user_mfa_id=user_mfa.id,
                method="totp",
                success=True
            )
            
            # Valid methods
            valid_methods = ['totp', 'sms', 'email', 'backup']
            for method in valid_methods:
                verification.method = method
                assert verification.method == method
            
            # Invalid method
            with pytest.raises(ValueError, match="Invalid MFA method"):
                verification.method = "invalid"
    
    def test_repr(self, app, db, user_mfa):
        """Test string representation."""
        with app.app_context():
            verification = MFAVerification(
                user_mfa_id=user_mfa.id,
                method="email",
                success=False
            )
            
            repr_str = repr(verification)
            assert "MFAVerification" in repr_str
            assert str(user_mfa.id) in repr_str
            assert "email" in repr_str
            assert "False" in repr_str


class TestMFAPolicy:
    """Test cases for MFAPolicy model."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'TESTING': True
        })
        
        db = SQLA(app)
        appbuilder = AppBuilder(app, db.session)
        
        with app.app_context():
            Base.metadata.create_all(db.engine)
            
        return app
    
    @pytest.fixture
    def db(self, app):
        """Get database session."""
        with app.app_context():
            from pgappforge import db
            return db
    
    @pytest.fixture
    def policy(self, app, db):
        """Create test MFA policy."""
        with app.app_context():
            policy = MFAPolicy(
                name="Test Policy",
                description="Test MFA policy",
                is_active=True
            )
            db.session.add(policy)
            db.session.commit()
            return policy
    
    def test_policy_creation(self, app, db):
        """Test MFA policy creation with defaults."""
        with app.app_context():
            policy = MFAPolicy(name="Default Policy")
            
            assert policy.name == "Default Policy"
            assert policy.is_active is True
            assert policy.require_backup_codes is True
            assert policy.max_failed_attempts == 5
            assert policy.lockout_duration == 900
            assert policy.session_timeout == 3600
    
    def test_enforced_roles_property(self, app, db, policy):
        """Test enforced roles JSON property."""
        with app.app_context():
            # Initially empty
            assert policy.enforced_roles == []
            
            # Set roles
            roles = ["Admin", "Manager", "User"]
            policy.enforced_roles = roles
            
            assert policy.enforced_roles == roles
            assert policy.enforce_for_roles is not None  # JSON stored
            
            # Clear roles
            policy.enforced_roles = []
            assert policy.enforced_roles == []
    
    def test_permitted_methods_property(self, app, db, policy):
        """Test permitted methods JSON property."""
        with app.app_context():
            # Default all methods
            default_methods = ['totp', 'sms', 'email', 'backup']
            assert policy.permitted_methods == default_methods
            
            # Set specific methods
            methods = ["totp", "sms"]
            policy.permitted_methods = methods
            
            assert policy.permitted_methods == methods
            
            # Invalid method
            with pytest.raises(ValueError, match="Invalid MFA methods"):
                policy.permitted_methods = ["totp", "invalid_method"]
    
    def test_applies_to_user(self, app, db, policy):
        """Test policy application to users."""
        with app.app_context():
            # Mock user with roles
            user = MagicMock()
            user.roles = [MagicMock(name="Admin"), MagicMock(name="User")]
            
            # Policy with no enforced roles
            assert policy.applies_to_user(user) is False
            
            # Policy with matching role
            policy.enforced_roles = ["Admin", "Manager"]
            assert policy.applies_to_user(user) is True
            
            # Policy with non-matching role
            policy.enforced_roles = ["SuperAdmin"]
            assert policy.applies_to_user(user) is False
            
            # Inactive policy
            policy.is_active = False
            policy.enforced_roles = ["Admin"]
            assert policy.applies_to_user(user) is False
    
    def test_is_method_allowed(self, app, db, policy):
        """Test method permission checking."""
        with app.app_context():
            # Default allows all methods
            assert policy.is_method_allowed("totp") is True
            assert policy.is_method_allowed("sms") is True
            
            # Restrict to specific methods
            policy.permitted_methods = ["totp", "backup"]
            assert policy.is_method_allowed("totp") is True
            assert policy.is_method_allowed("sms") is False
            assert policy.is_method_allowed("backup") is True
    
    def test_get_policy_for_user(self, app, db):
        """Test finding applicable policy for user."""
        with app.app_context():
            # Create policies
            policy1 = MFAPolicy(
                name="Admin Policy",
                is_active=True
            )
            policy1.enforced_roles = ["Admin"]
            
            policy2 = MFAPolicy(
                name="User Policy", 
                is_active=True
            )
            policy2.enforced_roles = ["User"]
            
            inactive_policy = MFAPolicy(
                name="Inactive Policy",
                is_active=False
            )
            inactive_policy.enforced_roles = ["Admin"]
            
            db.session.add_all([policy1, policy2, inactive_policy])
            db.session.commit()
            
            # Mock user
            admin_user = MagicMock()
            admin_user.roles = [MagicMock(name="Admin")]
            
            # Should get active policy for admin
            found_policy = MFAPolicy.get_policy_for_user(admin_user)
            assert found_policy is not None
            assert found_policy.name == "Admin Policy"
            
            # User with no matching policies
            other_user = MagicMock()
            other_user.roles = [MagicMock(name="Guest")]
            
            found_policy = MFAPolicy.get_policy_for_user(other_user)
            assert found_policy is None
    
    def test_repr(self, app, db, policy):
        """Test string representation."""
        with app.app_context():
            repr_str = repr(policy)
            assert "MFAPolicy" in repr_str
            assert policy.name in repr_str
            assert str(policy.is_active) in repr_str


class TestMFAEventListeners:
    """Test cases for SQLAlchemy event listeners."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'TESTING': True
        })
        
        db = SQLA(app)
        appbuilder = AppBuilder(app, db.session)
        
        with app.app_context():
            Base.metadata.create_all(db.engine)
            
        return app
    
    @pytest.fixture
    def db(self, app):
        """Get database session."""
        with app.app_context():
            from pgappforge import db
            return db
    
    def test_setup_token_generation_on_insert(self, app, db):
        """Test automatic setup token generation on UserMFA creation."""
        with app.app_context():
            mfa = UserMFA(user_id=1)
            
            # Setup token should be generated before insert
            assert mfa.setup_token is None  # Not yet generated
            
            db.session.add(mfa)
            db.session.flush()  # Trigger before_insert
            
            assert mfa.setup_token is not None
            assert len(mfa.setup_token) > 0
    
    @patch('pgappforge.security.mfa.models.log')
    def test_mfa_status_change_logging(self, mock_log, app, db):
        """Test logging of MFA status changes."""
        with app.app_context():
            mfa = UserMFA(user_id=1, is_enabled=False)
            db.session.add(mfa)
            db.session.commit()
            
            # Change MFA status
            mfa.is_enabled = True
            db.session.commit()
            
            # Should log the change
            mock_log.info.assert_called_once()
            call_args = mock_log.info.call_args[0][0]
            assert "MFA status changed" in call_args
            assert "user 1" in call_args