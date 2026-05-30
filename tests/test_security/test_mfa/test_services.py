"""
Unit tests for MFA service layer.

This module contains comprehensive unit tests for all MFA-related services
including TOTP, SMS, Email, BackupCode, Policy, and Orchestration services.

Test Coverage:
    - Service initialization and configuration
    - External service integrations with mocking
    - Circuit breaker patterns and resilience
    - Rate limiting and security features
    - Error handling and edge cases
"""

import pytest
import secrets
import io
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call
from contextlib import contextmanager

from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.models.sqla import Base
from cryptography.fernet import Fernet

from pgappforge.security.mfa.models import UserMFA, MFABackupCode, MFAPolicy
from pgappforge.security.mfa.services import (
    TOTPService, SMSService, EmailService, BackupCodeService,
    MFAPolicyService, MFAOrchestrationService, CircuitBreaker,
    CircuitBreakerState, MFAServiceError, ServiceUnavailableError,
    ValidationError, ConfigurationError
)


class TestCircuitBreaker:
    """Test cases for Circuit Breaker implementation."""
    
    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initialization with defaults."""
        cb = CircuitBreaker()
        
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60
        assert cb.success_threshold == 3
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.last_failure_time is None
        assert cb.state == CircuitBreakerState.CLOSED
    
    def test_circuit_breaker_custom_parameters(self):
        """Test circuit breaker with custom parameters."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30, success_threshold=2)
        
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30
        assert cb.success_threshold == 2
    
    def test_circuit_breaker_can_attempt_closed(self):
        """Test can_attempt in CLOSED state."""
        cb = CircuitBreaker()
        assert cb._can_attempt() is True
    
    def test_circuit_breaker_record_success(self):
        """Test recording successful operations."""
        cb = CircuitBreaker()
        cb.failure_count = 3
        
        cb.record_success()
        
        assert cb.failure_count == 0
        assert cb.state == CircuitBreakerState.CLOSED
    
    def test_circuit_breaker_record_failure_opens(self):
        """Test circuit breaker opens after failure threshold."""
        cb = CircuitBreaker(failure_threshold=2)
        
        cb.record_failure()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 1
        
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.failure_count == 2
        assert cb.last_failure_time is not None
    
    def test_circuit_breaker_half_open_recovery(self):
        """Test circuit breaker half-open recovery mechanism."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1)
        
        # Open circuit
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        
        # Wait for recovery timeout
        import time
        time.sleep(1.1)
        
        # Should allow attempt and move to HALF_OPEN
        assert cb._can_attempt() is True
        assert cb.state == CircuitBreakerState.HALF_OPEN
    
    def test_circuit_breaker_decorator_success(self):
        """Test circuit breaker decorator with successful function."""
        cb = CircuitBreaker()
        
        @cb
        def test_function():
            return "success"
        
        result = test_function()
        assert result == "success"
        assert cb.failure_count == 0
    
    def test_circuit_breaker_decorator_failure(self):
        """Test circuit breaker decorator with failing function."""
        cb = CircuitBreaker(failure_threshold=1)
        
        @cb
        def failing_function():
            raise Exception("Test error")
        
        # First failure should open circuit
        with pytest.raises(Exception, match="Test error"):
            failing_function()
        
        assert cb.state == CircuitBreakerState.OPEN
        
        # Second call should be blocked
        with pytest.raises(ServiceUnavailableError):
            failing_function()


class TestTOTPService:
    """Test cases for TOTP service."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'MFA_TOTP_ISSUER': 'Test App',
            'MFA_TOTP_VALIDITY_WINDOW': 1,
            'TESTING': True
        })
        return app
    
    @pytest.fixture
    def totp_service(self, app):
        """Create TOTP service instance."""
        with app.app_context():
            return TOTPService()
    
    def test_totp_service_initialization(self, app, totp_service):
        """Test TOTP service initialization."""
        with app.app_context():
            assert totp_service.issuer == 'Test App'
            assert totp_service.validity_window == 1
    
    def test_generate_secret(self, app, totp_service):
        """Test TOTP secret generation."""
        with app.app_context():
            secret = totp_service.generate_secret()
            
            assert isinstance(secret, str)
            assert len(secret) >= 16  # Base32 encoded secret should be at least 16 chars
            
            # Should generate different secrets
            secret2 = totp_service.generate_secret()
            assert secret != secret2
    
    def test_generate_qr_code(self, app, totp_service):
        """Test QR code generation for TOTP setup."""
        with app.app_context():
            secret = totp_service.generate_secret()
            qr_code = totp_service.generate_qr_code(
                secret, 
                "test@example.com", 
                "Test User"
            )
            
            assert qr_code.startswith('data:image/png;base64,')
            assert len(qr_code) > 100  # QR code should be substantial
    
    def test_generate_qr_code_invalid_secret(self, app, totp_service):
        """Test QR code generation with invalid secret."""
        with app.app_context():
            with pytest.raises(ValidationError):
                totp_service.generate_qr_code(
                    "invalid-secret!@#", 
                    "test@example.com"
                )
    
    def test_validate_totp_success(self, app, totp_service):
        """Test successful TOTP validation."""
        with app.app_context():
            # Generate secret and current OTP
            secret = totp_service.generate_secret()
            current_otp = totp_service.get_current_otp(secret)
            
            is_valid, counter = totp_service.validate_totp(secret, current_otp)
            
            assert is_valid is True
            assert isinstance(counter, int)
            assert counter > 0
    
    def test_validate_totp_invalid_code(self, app, totp_service):
        """Test TOTP validation with invalid code."""
        with app.app_context():
            secret = totp_service.generate_secret()
            
            is_valid, counter = totp_service.validate_totp(secret, "000000")
            
            assert is_valid is False
            assert isinstance(counter, int)
    
    def test_validate_totp_replay_protection(self, app, totp_service):
        """Test TOTP replay protection mechanism."""
        with app.app_context():
            secret = totp_service.generate_secret()
            current_otp = totp_service.get_current_otp(secret)
            
            # First validation should succeed
            is_valid, counter = totp_service.validate_totp(secret, current_otp)
            assert is_valid is True
            
            # Same counter should be rejected
            is_valid_replay, counter_replay = totp_service.validate_totp(
                secret, current_otp, last_counter=counter
            )
            assert is_valid_replay is False
    
    def test_get_current_otp(self, app, totp_service):
        """Test getting current OTP for testing."""
        with app.app_context():
            secret = totp_service.generate_secret()
            otp = totp_service.get_current_otp(secret)
            
            assert isinstance(otp, str)
            assert len(otp) == 6
            assert otp.isdigit()
    
    def test_validate_totp_invalid_secret(self, app, totp_service):
        """Test TOTP validation with invalid secret format."""
        with app.app_context():
            with pytest.raises(ValidationError):
                totp_service.validate_totp("invalid-secret!@#", "123456")


class TestSMSService:
    """Test cases for SMS service."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application with SMS configuration."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'TWILIO_ACCOUNT_SID': 'test-sid',
            'TWILIO_AUTH_TOKEN': 'test-token',
            'TWILIO_FROM_NUMBER': '+15551234567',
            'MFA_SMS_RATE_LIMIT_WINDOW': 300,
            'MFA_SMS_RATE_LIMIT_MAX': 3,
            'MFA_SMS_APP_NAME': 'Test App',
            'TESTING': True
        })
        return app
    
    @pytest.fixture
    def sms_service(self, app):
        """Create SMS service instance with mocked providers."""
        with app.app_context():
            with patch('pgappforge.security.mfa.services.TwilioClient') as mock_twilio:
                mock_client = MagicMock()
                mock_twilio.return_value = mock_client
                
                service = SMSService()
                return service, mock_client
    
    def test_sms_service_initialization_twilio(self, app):
        """Test SMS service initialization with Twilio."""
        with app.app_context():
            with patch('pgappforge.security.mfa.services.TwilioClient'):
                service = SMSService()
                assert 'twilio' in service.providers
                assert service.providers['twilio']['from_number'] == '+15551234567'
    
    def test_sms_service_no_providers(self):
        """Test SMS service with no providers configured."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test'
        
        with app.app_context():
            service = SMSService()
            assert len(service.providers) == 0
    
    def test_rate_limiting(self, app, sms_service):
        """Test SMS rate limiting functionality."""
        service, mock_client = sms_service
        
        with app.app_context():
            phone = "+15551234567"
            
            # First 3 attempts should pass rate limiting
            for i in range(3):
                assert service._check_rate_limit(phone) is True
            
            # 4th attempt should fail
            assert service._check_rate_limit(phone) is False
    
    @patch('pgappforge.security.mfa.services.TwilioClient')
    def test_send_via_twilio_success(self, mock_twilio_class, app):
        """Test successful SMS sending via Twilio."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.sid = 'test-message-sid'
        mock_client.messages.create.return_value = mock_message
        mock_twilio_class.return_value = mock_client
        
        with app.app_context():
            service = SMSService()
            result = service._send_via_twilio("+15551234567", "Test message")
            
            assert result is True
            mock_client.messages.create.assert_called_once()
    
    @patch('pgappforge.security.mfa.services.TwilioClient')
    def test_send_via_twilio_failure(self, mock_twilio_class, app):
        """Test SMS sending failure via Twilio."""
        from twilio.base.exceptions import TwilioException
        
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = TwilioException("API Error")
        mock_twilio_class.return_value = mock_client
        
        with app.app_context():
            service = SMSService()
            
            with pytest.raises(ServiceUnavailableError):
                service._send_via_twilio("+15551234567", "Test message")
    
    @patch('pgappforge.security.mfa.services.TwilioClient')
    def test_send_mfa_code_success(self, mock_twilio_class, app):
        """Test successful MFA code sending."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.sid = 'test-sid'
        mock_client.messages.create.return_value = mock_message
        mock_twilio_class.return_value = mock_client
        
        with app.app_context():
            service = SMSService()
            result = service.send_mfa_code("+15551234567", "123456", "John Doe")
            
            assert result is True
            mock_client.messages.create.assert_called_once()
            call_args = mock_client.messages.create.call_args
            assert "John Doe" in call_args[1]['body']
            assert "123456" in call_args[1]['body']
    
    def test_send_mfa_code_invalid_phone(self, app, sms_service):
        """Test MFA code sending with invalid phone number."""
        service, _ = sms_service
        
        with app.app_context():
            with pytest.raises(ValidationError, match="E.164 format"):
                service.send_mfa_code("555-1234", "123456")
    
    def test_send_mfa_code_rate_limited(self, app, sms_service):
        """Test MFA code sending when rate limited."""
        service, mock_client = sms_service
        
        with app.app_context():
            phone = "+15551234567"
            
            # Exhaust rate limit
            for _ in range(3):
                service._check_rate_limit(phone)
            
            with pytest.raises(ValidationError, match="rate limit exceeded"):
                service.send_mfa_code(phone, "123456")


class TestEmailService:
    """Test cases for Email service."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application with email configuration."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'MAIL_SERVER': 'smtp.test.com',
            'MAIL_PORT': 587,
            'MAIL_USE_TLS': True,
            'MAIL_DEFAULT_SENDER': 'noreply@test.com',
            'MFA_EMAIL_RATE_LIMIT_WINDOW': 300,
            'MFA_EMAIL_RATE_LIMIT_MAX': 5,
            'MFA_EMAIL_APP_NAME': 'Test Application',
            'TESTING': True
        })
        return app
    
    @pytest.fixture
    def email_service(self, app):
        """Create Email service instance."""
        with app.app_context():
            return EmailService()
    
    def test_email_service_initialization(self, app, email_service):
        """Test email service initialization."""
        with app.app_context():
            assert hasattr(email_service, 'mail')
            assert hasattr(email_service, 'rate_limiter')
    
    def test_generate_html_template(self, app, email_service):
        """Test HTML email template generation."""
        with app.app_context():
            html = email_service._generate_html_template("123456", "John Doe")
            
            assert "123456" in html
            assert "John Doe" in html
            assert "Test Application" in html
            assert "<!DOCTYPE html>" in html
    
    def test_generate_text_template(self, app, email_service):
        """Test plain text email template generation."""
        with app.app_context():
            text = email_service._generate_text_template("123456", "Jane Smith")
            
            assert "123456" in text
            assert "Jane Smith" in text
            assert "Test Application" in text
    
    def test_email_rate_limiting(self, app, email_service):
        """Test email rate limiting."""
        with app.app_context():
            email = "test@example.com"
            
            # First 5 attempts should pass
            for _ in range(5):
                assert email_service._check_rate_limit(email) is True
            
            # 6th attempt should fail
            assert email_service._check_rate_limit(email) is False
    
    @patch('flask_mail.Mail.send')
    def test_send_mfa_code_success(self, mock_send, app, email_service):
        """Test successful MFA code email sending."""
        with app.app_context():
            result = email_service.send_mfa_code(
                "test@example.com", 
                "123456", 
                "Test User"
            )
            
            assert result is True
            mock_send.assert_called_once()
    
    def test_send_mfa_code_invalid_email(self, app, email_service):
        """Test MFA code sending with invalid email."""
        with app.app_context():
            with pytest.raises(ValidationError, match="Invalid email"):
                email_service.send_mfa_code("invalid-email", "123456")
    
    def test_send_mfa_code_rate_limited(self, app, email_service):
        """Test MFA code sending when rate limited."""
        with app.app_context():
            email = "test@example.com"
            
            # Exhaust rate limit
            for _ in range(5):
                email_service._check_rate_limit(email)
            
            with pytest.raises(ValidationError, match="rate limit exceeded"):
                email_service.send_mfa_code(email, "123456")
    
    @patch('flask_mail.Mail.send')
    def test_send_mfa_code_mail_failure(self, mock_send, app, email_service):
        """Test email sending failure."""
        mock_send.side_effect = Exception("SMTP Error")
        
        with app.app_context():
            with pytest.raises(ServiceUnavailableError):
                email_service.send_mfa_code("test@example.com", "123456")


class TestBackupCodeService:
    """Test cases for Backup Code service."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application with database."""
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
        """Create UserMFA for testing."""
        with app.app_context():
            mfa = UserMFA(user_id=1)
            db.session.add(mfa)
            db.session.commit()
            return mfa
    
    @pytest.fixture
    def backup_service(self, app):
        """Create Backup Code service instance."""
        with app.app_context():
            return BackupCodeService()
    
    def test_generate_codes_for_user(self, app, db, user_mfa, backup_service):
        """Test backup code generation for user."""
        with app.app_context():
            codes = backup_service.generate_codes_for_user(user_mfa.id, count=5)
            
            assert len(codes) == 5
            for code in codes:
                assert len(code) == 8
                assert code.isdigit()
            
            # Check database storage
            stored_codes = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa.id
            ).count()
            assert stored_codes == 5
    
    def test_generate_codes_invalid_user(self, app, backup_service):
        """Test backup code generation with invalid user."""
        with app.app_context():
            with pytest.raises(ValidationError, match="not found"):
                backup_service.generate_codes_for_user(999, count=5)
    
    def test_validate_backup_code_success(self, app, db, user_mfa, backup_service):
        """Test successful backup code validation."""
        with app.app_context():
            codes = backup_service.generate_codes_for_user(user_mfa.id, count=3)
            test_code = codes[0]
            
            result = backup_service.validate_backup_code(
                user_mfa.id, 
                test_code, 
                "192.168.1.1"
            )
            
            assert result is True
            
            # Code should be marked as used
            used_codes = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa.id,
                is_used=True
            ).count()
            assert used_codes == 1
    
    def test_validate_backup_code_invalid(self, app, user_mfa, backup_service):
        """Test backup code validation with invalid code."""
        with app.app_context():
            backup_service.generate_codes_for_user(user_mfa.id, count=3)
            
            result = backup_service.validate_backup_code(
                user_mfa.id, 
                "00000000", 
                "192.168.1.1"
            )
            
            assert result is False
    
    def test_validate_backup_code_already_used(self, app, user_mfa, backup_service):
        """Test backup code validation with already used code."""
        with app.app_context():
            codes = backup_service.generate_codes_for_user(user_mfa.id, count=3)
            test_code = codes[0]
            
            # Use code first time
            result1 = backup_service.validate_backup_code(user_mfa.id, test_code)
            assert result1 is True
            
            # Try to use same code again
            result2 = backup_service.validate_backup_code(user_mfa.id, test_code)
            assert result2 is False
    
    def test_get_remaining_codes_count(self, app, user_mfa, backup_service):
        """Test getting remaining backup codes count."""
        with app.app_context():
            # Initially no codes
            count = backup_service.get_remaining_codes_count(user_mfa.id)
            assert count == 0
            
            # Generate codes
            codes = backup_service.generate_codes_for_user(user_mfa.id, count=5)
            count = backup_service.get_remaining_codes_count(user_mfa.id)
            assert count == 5
            
            # Use one code
            backup_service.validate_backup_code(user_mfa.id, codes[0])
            count = backup_service.get_remaining_codes_count(user_mfa.id)
            assert count == 4
    
    def test_get_usage_history(self, app, user_mfa, backup_service):
        """Test getting backup code usage history."""
        with app.app_context():
            # Initially no history
            history = backup_service.get_usage_history(user_mfa.id)
            assert len(history) == 0
            
            # Generate and use some codes
            codes = backup_service.generate_codes_for_user(user_mfa.id, count=3)
            backup_service.validate_backup_code(user_mfa.id, codes[0], "192.168.1.1")
            backup_service.validate_backup_code(user_mfa.id, codes[1], "10.0.0.1")
            
            history = backup_service.get_usage_history(user_mfa.id)
            assert len(history) == 2
            
            # Check history details
            assert history[0]['used_from_ip'] in ["192.168.1.1", "10.0.0.1"]
            assert history[0]['used_at'] is not None


class TestMFAPolicyService:
    """Test cases for MFA Policy service."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application with database."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'MFA_MAX_FAILED_ATTEMPTS': 3,
            'MFA_LOCKOUT_DURATION': 600,
            'MFA_SESSION_TIMEOUT': 1800,
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
    def policy_service(self, app):
        """Create MFA Policy service instance."""
        with app.app_context():
            return MFAPolicyService()
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user with roles."""
        user = MagicMock()
        user.id = 1
        
        admin_role = MagicMock()
        admin_role.name = "Admin"
        
        user_role = MagicMock()
        user_role.name = "User"
        
        user.roles = [admin_role, user_role]
        return user
    
    @pytest.fixture
    def test_policy(self, app, db):
        """Create test MFA policy."""
        with app.app_context():
            policy = MFAPolicy(
                name="Test Policy",
                description="Test MFA policy",
                is_active=True
            )
            policy.enforced_roles = ["Admin", "Manager"]
            policy.permitted_methods = ["totp", "backup"]
            
            db.session.add(policy)
            db.session.commit()
            return policy
    
    def test_get_user_policy_exists(self, app, db, policy_service, mock_user, test_policy):
        """Test getting existing policy for user."""
        with app.app_context():
            policy = policy_service.get_user_policy(mock_user)
            assert policy is not None
            assert policy.name == "Test Policy"
    
    def test_get_user_policy_none(self, app, policy_service):
        """Test getting policy for user with no applicable policies."""
        user = MagicMock()
        guest_role = MagicMock()
        guest_role.name = "Guest"
        user.roles = [guest_role]
        
        with app.app_context():
            policy = policy_service.get_user_policy(user)
            assert policy is None
    
    def test_is_mfa_required_for_user(self, app, policy_service, mock_user, test_policy):
        """Test checking if MFA is required for user."""
        with app.app_context():
            required = policy_service.is_mfa_required_for_user(mock_user)
            assert required is True
    
    def test_is_mfa_not_required(self, app, policy_service):
        """Test checking MFA requirement for user with no policies."""
        user = MagicMock()
        guest_role = MagicMock()
        guest_role.name = "Guest"
        user.roles = [guest_role]
        
        with app.app_context():
            required = policy_service.is_mfa_required_for_user(user)
            assert required is False
    
    def test_get_allowed_methods_for_user(self, app, policy_service, mock_user, test_policy):
        """Test getting allowed MFA methods for user."""
        with app.app_context():
            methods = policy_service.get_allowed_methods_for_user(mock_user)
            assert methods == ["totp", "backup"]
    
    def test_get_allowed_methods_default(self, app, policy_service):
        """Test getting default allowed methods when no policy."""
        user = MagicMock()
        guest_role = MagicMock()
        guest_role.name = "Guest"
        user.roles = [guest_role]
        
        with app.app_context():
            methods = policy_service.get_allowed_methods_for_user(user)
            assert methods == ['totp', 'sms', 'email', 'backup']
    
    def test_validate_method_for_user_allowed(self, app, policy_service, mock_user, test_policy):
        """Test validating allowed MFA method for user."""
        with app.app_context():
            is_allowed = policy_service.validate_method_for_user(mock_user, "totp")
            assert is_allowed is True
    
    def test_validate_method_for_user_not_allowed(self, app, policy_service, mock_user, test_policy):
        """Test validating disallowed MFA method for user."""
        with app.app_context():
            is_allowed = policy_service.validate_method_for_user(mock_user, "sms")
            assert is_allowed is False
    
    def test_get_policy_parameters_with_policy(self, app, policy_service, mock_user, test_policy):
        """Test getting policy parameters when policy exists."""
        with app.app_context():
            params = policy_service.get_policy_parameters_for_user(mock_user)
            
            assert params['max_failed_attempts'] == 5  # Policy default
            assert params['lockout_duration'] == 900   # Policy default
            assert params['session_timeout'] == 3600   # Policy default
            assert params['require_backup_codes'] is True
    
    def test_get_policy_parameters_default(self, app, policy_service):
        """Test getting default policy parameters when no policy."""
        user = MagicMock()
        guest_role = MagicMock()
        guest_role.name = "Guest"
        user.roles = [guest_role]
        
        with app.app_context():
            params = policy_service.get_policy_parameters_for_user(user)
            
            assert params['max_failed_attempts'] == 3   # App config
            assert params['lockout_duration'] == 600    # App config  
            assert params['session_timeout'] == 1800    # App config
            assert params['require_backup_codes'] is True


class TestMFAOrchestrationService:
    """Test cases for MFA Orchestration service."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application with database."""
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
    def mock_user(self):
        """Create mock user."""
        user = MagicMock()
        user.id = 1
        user.email = "test@example.com"
        user.username = "testuser"
        user.roles = []
        return user
    
    @pytest.fixture
    def orchestration_service(self, app):
        """Create MFA Orchestration service instance."""
        with app.app_context():
            return MFAOrchestrationService()
    
    def test_orchestration_service_initialization(self, app, orchestration_service):
        """Test orchestration service initialization."""
        with app.app_context():
            assert hasattr(orchestration_service, 'totp_service')
            assert hasattr(orchestration_service, 'sms_service')
            assert hasattr(orchestration_service, 'email_service')
            assert hasattr(orchestration_service, 'backup_service')
            assert hasattr(orchestration_service, 'policy_service')
    
    def test_initiate_mfa_setup_new_user(self, app, db, mock_user, orchestration_service):
        """Test MFA setup initiation for new user."""
        with app.app_context():
            setup_info = orchestration_service.initiate_mfa_setup(mock_user)
            
            assert 'user_mfa_id' in setup_info
            assert 'totp_secret' in setup_info
            assert 'qr_code' in setup_info
            assert 'setup_token' in setup_info
            assert 'allowed_methods' in setup_info
            
            # Check database record created
            user_mfa = db.session.query(UserMFA).filter_by(user_id=mock_user.id).first()
            assert user_mfa is not None
            assert user_mfa.setup_token is not None
    
    def test_initiate_mfa_setup_already_configured(self, app, db, mock_user, orchestration_service):
        """Test MFA setup initiation for user with existing configuration."""
        with app.app_context():
            # Create existing MFA configuration
            user_mfa = UserMFA(user_id=mock_user.id, setup_completed=True)
            db.session.add(user_mfa)
            db.session.commit()
            
            with pytest.raises(ConfigurationError, match="already configured"):
                orchestration_service.initiate_mfa_setup(mock_user)
    
    def test_complete_mfa_setup_success(self, app, db, mock_user, orchestration_service):
        """Test successful MFA setup completion."""
        with app.app_context():
            # Initiate setup
            setup_info = orchestration_service.initiate_mfa_setup(mock_user)
            setup_token = setup_info['setup_token']
            totp_secret = setup_info['totp_secret']
            
            # Get current TOTP code
            from pyotp import TOTP
            totp = TOTP(totp_secret)
            current_code = totp.now()
            
            # Complete setup
            result = orchestration_service.complete_mfa_setup(
                mock_user, 
                current_code, 
                setup_token
            )
            
            assert result['setup_completed'] is True
            assert 'backup_codes' in result
            assert len(result['backup_codes']) > 0
            assert result['enabled_methods'] == ['totp']
            
            # Check database state
            user_mfa = db.session.query(UserMFA).filter_by(user_id=mock_user.id).first()
            assert user_mfa.setup_completed is True
            assert user_mfa.is_enabled is True
            assert user_mfa.setup_token is None
    
    def test_complete_mfa_setup_invalid_token(self, app, db, mock_user, orchestration_service):
        """Test MFA setup completion with invalid token."""
        with app.app_context():
            setup_info = orchestration_service.initiate_mfa_setup(mock_user)
            totp_secret = setup_info['totp_secret']
            
            from pyotp import TOTP
            totp = TOTP(totp_secret)
            current_code = totp.now()
            
            with pytest.raises(ValidationError, match="Invalid or expired setup token"):
                orchestration_service.complete_mfa_setup(
                    mock_user, 
                    current_code, 
                    "invalid-token"
                )
    
    def test_complete_mfa_setup_invalid_code(self, app, db, mock_user, orchestration_service):
        """Test MFA setup completion with invalid TOTP code."""
        with app.app_context():
            setup_info = orchestration_service.initiate_mfa_setup(mock_user)
            setup_token = setup_info['setup_token']
            
            with pytest.raises(ValidationError, match="Invalid verification code"):
                orchestration_service.complete_mfa_setup(
                    mock_user, 
                    "000000", 
                    setup_token
                )
    
    def test_verify_mfa_code_totp_success(self, app, db, mock_user, orchestration_service):
        """Test successful TOTP verification."""
        with app.app_context():
            # Set up MFA
            setup_info = orchestration_service.initiate_mfa_setup(mock_user)
            setup_token = setup_info['setup_token']
            totp_secret = setup_info['totp_secret']
            
            from pyotp import TOTP
            totp = TOTP(totp_secret)
            current_code = totp.now()
            
            orchestration_service.complete_mfa_setup(mock_user, current_code, setup_token)
            
            # Test verification with new code
            new_code = totp.now()
            result = orchestration_service.verify_mfa_code(
                mock_user, 
                'totp', 
                new_code,
                '192.168.1.1'
            )
            
            assert result['verification_success'] is True
            assert result['method_used'] == 'totp'
            assert 'session_expires' in result
    
    def test_verify_mfa_code_backup_success(self, app, db, mock_user, orchestration_service):
        """Test successful backup code verification."""
        with app.app_context():
            # Set up MFA
            setup_info = orchestration_service.initiate_mfa_setup(mock_user)
            setup_token = setup_info['setup_token']
            totp_secret = setup_info['totp_secret']
            
            from pyotp import TOTP
            totp = TOTP(totp_secret)
            current_code = totp.now()
            
            completion_result = orchestration_service.complete_mfa_setup(
                mock_user, current_code, setup_token
            )
            backup_codes = completion_result['backup_codes']
            
            # Test backup code verification
            result = orchestration_service.verify_mfa_code(
                mock_user, 
                'backup', 
                backup_codes[0],
                '192.168.1.1'
            )
            
            assert result['verification_success'] is True
            assert result['method_used'] == 'backup'
    
    def test_verify_mfa_code_failure(self, app, db, mock_user, orchestration_service):
        """Test failed MFA verification."""
        with app.app_context():
            # Set up MFA
            setup_info = orchestration_service.initiate_mfa_setup(mock_user)
            setup_token = setup_info['setup_token']
            totp_secret = setup_info['totp_secret']
            
            from pyotp import TOTP
            totp = TOTP(totp_secret)
            current_code = totp.now()
            
            orchestration_service.complete_mfa_setup(mock_user, current_code, setup_token)
            
            # Test with invalid code
            result = orchestration_service.verify_mfa_code(
                mock_user, 
                'totp', 
                '000000',
                '192.168.1.1'
            )
            
            assert result['verification_success'] is False
            assert 'failure_reason' in result
            assert 'remaining_attempts' in result
    
    def test_verify_mfa_code_user_not_enabled(self, app, mock_user, orchestration_service):
        """Test MFA verification for user without MFA enabled."""
        with app.app_context():
            with pytest.raises(ValidationError, match="MFA is not enabled"):
                orchestration_service.verify_mfa_code(
                    mock_user, 
                    'totp', 
                    '123456'
                )
    
    def test_verify_mfa_code_unsupported_method(self, app, db, mock_user, orchestration_service):
        """Test MFA verification with unsupported method."""
        with app.app_context():
            # Set up MFA
            setup_info = orchestration_service.initiate_mfa_setup(mock_user)
            setup_token = setup_info['setup_token']
            totp_secret = setup_info['totp_secret']
            
            from pyotp import TOTP
            totp = TOTP(totp_secret)
            current_code = totp.now()
            
            orchestration_service.complete_mfa_setup(mock_user, current_code, setup_token)
            
            with pytest.raises(ValidationError, match="not implemented for method"):
                orchestration_service.verify_mfa_code(
                    mock_user, 
                    'sms', 
                    '123456'
                )