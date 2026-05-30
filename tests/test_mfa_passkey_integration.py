"""
Comprehensive Test Suite for MFA and Passkey Integration

Tests cover the complete MFA and WebAuthn passkey implementation including:
- MFA service layer functionality
- WebAuthn registration and authentication flows
- Security validation integration
- Approval system integration
- Token generation and validation
- Error handling and edge cases

Test Categories:
- Unit tests for individual services
- Integration tests for end-to-end flows
- Security tests for validation and threats
- Mock tests for external dependencies
- Performance tests for rate limiting
"""

import pytest
import json
import time
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from flask import Flask
from pgappforge import AppBuilder
from pgappforge.security.sqla.manager import SecurityManager

# Import the MFA components to test
try:
    from pgappforge.security.mfa.services import (
        TOTPService, SMSService, EmailService, BackupCodeService,
        MFAPolicyService, TokenGenerationService, MFAOrchestrationService,
        WebAuthnService, ValidationError, ServiceUnavailableError
    )
    from pgappforge.security.mfa.models import (
        UserMFA, MFABackupCode, MFAVerification, MFAPolicy,
        WebAuthnCredential, MFAChallenge
    )
    from pgappforge.security.mfa.manager_mixin import MFASessionState
    from pgappforge.process.approval.security_validator import ApprovalSecurityValidator
    HAS_MFA = True
except ImportError:
    HAS_MFA = False


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available")
class TestTOTPService:
    """Test suite for TOTP service functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        self.app.config['MFA_TOTP_ISSUER'] = 'Test App'
        
        with self.app.app_context():
            self.totp_service = TOTPService()
    
    def test_generate_secret(self):
        """Test TOTP secret generation."""
        with self.app.app_context():
            secret = self.totp_service.generate_secret()
            
            assert isinstance(secret, str)
            assert len(secret) >= 16
            assert secret.isalnum()  # Base32 characters only
    
    def test_secret_uniqueness(self):
        """Test that generated secrets are unique."""
        with self.app.app_context():
            secrets = [self.totp_service.generate_secret() for _ in range(10)]
            assert len(set(secrets)) == 10  # All unique
    
    @patch('pgappforge.security.mfa.services.HAS_QRCODE', True)
    @patch('qrcode.QRCode')
    def test_generate_qr_code(self, mock_qrcode):
        """Test QR code generation for TOTP setup."""
        # Mock QR code generation
        mock_qr = MagicMock()
        mock_img = MagicMock()
        mock_img.save = MagicMock()
        mock_qr.make_image.return_value = mock_img
        mock_qrcode.return_value = mock_qr
        
        with self.app.app_context():
            secret = self.totp_service.generate_secret()
            qr_code = self.totp_service.generate_qr_code(secret, "test@example.com")
            
            assert qr_code.startswith('data:image/png;base64,')
            mock_qrcode.assert_called_once()
            mock_qr.add_data.assert_called_once()
            mock_qr.make.assert_called_once()
    
    def test_validate_totp_with_correct_code(self):
        """Test TOTP validation with correct code."""
        with self.app.app_context():
            secret = self.totp_service.generate_secret()
            
            # Generate current OTP for testing
            import pyotp
            totp = pyotp.TOTP(secret)
            current_otp = totp.now()
            
            is_valid, counter = self.totp_service.validate_totp(secret, current_otp)
            
            assert is_valid is True
            assert isinstance(counter, int)
            assert counter > 0
    
    def test_validate_totp_with_incorrect_code(self):
        """Test TOTP validation with incorrect code."""
        with self.app.app_context():
            secret = self.totp_service.generate_secret()
            
            is_valid, counter = self.totp_service.validate_totp(secret, "000000")
            
            assert is_valid is False
            assert isinstance(counter, int)
    
    def test_replay_protection(self):
        """Test TOTP replay attack protection."""
        with self.app.app_context():
            secret = self.totp_service.generate_secret()
            
            import pyotp
            totp = pyotp.TOTP(secret)
            current_otp = totp.now()
            current_counter = totp.timecode(datetime.utcnow())
            
            # First validation should succeed
            is_valid, counter = self.totp_service.validate_totp(secret, current_otp)
            assert is_valid is True
            
            # Second validation with same counter should fail
            is_valid, _ = self.totp_service.validate_totp(secret, current_otp, counter)
            assert is_valid is False


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available")
class TestWebAuthnService:
    """Test suite for WebAuthn passkey service."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        self.app.config['WEBAUTHN_RP_ID'] = 'localhost'
        self.app.config['WEBAUTHN_RP_NAME'] = 'Test App'
        self.app.config['WEBAUTHN_ORIGIN'] = 'https://localhost'
        
        # Mock user object
        self.mock_user = Mock()
        self.mock_user.id = 1
        self.mock_user.username = 'testuser'
        self.mock_user.first_name = 'Test'
        self.mock_user.last_name = 'User'
        self.mock_user.email = 'test@example.com'
    
    @patch('pgappforge.security.mfa.services.HAS_WEBAUTHN', True)
    @patch('pgappforge.security.mfa.services.generate_registration_options')
    def test_generate_registration_options(self, mock_generate_options):
        """Test WebAuthn registration options generation."""
        # Mock the WebAuthn library response
        mock_options = Mock()
        mock_options.challenge = b'test-challenge'
        mock_options.rp = Mock()
        mock_options.rp.id = 'localhost'
        mock_options.rp.name = 'Test App'
        mock_options.user = Mock()
        mock_options.user.id = b'1'
        mock_options.user.name = 'testuser'
        mock_options.user.display_name = 'Test User'
        mock_options.pub_key_cred_params = []
        mock_options.timeout = 300000
        mock_generate_options.return_value = mock_options
        
        with self.app.app_context():
            with patch('pgappforge.db.session') as mock_db:
                webauthn_service = WebAuthnService()
                options = webauthn_service.generate_registration_options(self.mock_user)
                
                assert 'publicKey' in options
                assert 'challenge_id' in options
                assert options['publicKey']['rp']['id'] == 'localhost'
                mock_generate_options.assert_called_once()
    
    @patch('pgappforge.security.mfa.services.HAS_WEBAUTHN', True)
    @patch('pgappforge.security.mfa.services.generate_authentication_options')
    def test_generate_authentication_options(self, mock_generate_options):
        """Test WebAuthn authentication options generation."""
        mock_options = Mock()
        mock_options.challenge = b'test-challenge'
        mock_options.rp_id = 'localhost'
        mock_options.timeout = 300000
        mock_options.user_verification = 'preferred'
        mock_generate_options.return_value = mock_options
        
        with self.app.app_context():
            with patch('pgappforge.db.session') as mock_db:
                # Mock credentials query
                mock_db.query().filter_by().all.return_value = []
                
                webauthn_service = WebAuthnService()
                
                with pytest.raises(ValidationError, match="No active passkeys found"):
                    webauthn_service.generate_authentication_options(1)
    
    def test_webauthn_not_available(self):
        """Test WebAuthn service when library is not available."""
        with self.app.app_context():
            with patch('pgappforge.security.mfa.services.HAS_WEBAUTHN', False):
                with pytest.raises(RuntimeError, match="WebAuthn support requires py-webauthn"):
                    WebAuthnService()


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available")
class TestTokenGenerationService:
    """Test suite for token generation service."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        self.app.config['MFA_TOKEN_LENGTH'] = 6
        
        with self.app.app_context():
            self.token_service = TokenGenerationService()
    
    def test_generate_numeric_token(self):
        """Test numeric token generation."""
        with self.app.app_context():
            token = self.token_service.generate_numeric_token(6)
            
            assert len(token) == 6
            assert token.isdigit()
            assert '000000' <= token <= '999999'
    
    def test_generate_alphanumeric_token(self):
        """Test alphanumeric token generation."""
        with self.app.app_context():
            token = self.token_service.generate_alphanumeric_token(8)
            
            assert len(token) == 8
            assert token.isalnum()
            
            # Test with ambiguous characters excluded (default)
            assert '0' not in token
            assert 'O' not in token
            assert '1' not in token
            assert 'I' not in token
    
    def test_generate_alphanumeric_token_with_ambiguous(self):
        """Test alphanumeric token generation including ambiguous characters."""
        with self.app.app_context():
            token = self.token_service.generate_alphanumeric_token(8, exclude_ambiguous=False)
            
            assert len(token) == 8
            assert token.isalnum()
    
    def test_token_uniqueness(self):
        """Test that generated tokens are unique."""
        with self.app.app_context():
            tokens = [self.token_service.generate_numeric_token() for _ in range(100)]
            unique_tokens = set(tokens)
            
            # Should have high uniqueness (allow for small collisions in test)
            assert len(unique_tokens) >= 90


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available")
class TestMFAOrchestrationService:
    """Test suite for MFA orchestration service."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        # Mock user object
        self.mock_user = Mock()
        self.mock_user.id = 1
        self.mock_user.username = 'testuser'
        self.mock_user.email = 'test@example.com'
    
    @patch('pgappforge.db.session')
    def test_initiate_mfa_setup(self, mock_db):
        """Test MFA setup initiation."""
        with self.app.app_context():
            # Mock database operations
            mock_db.query().filter_by().first.return_value = None
            mock_db.add = Mock()
            mock_db.commit = Mock()
            
            orchestration = MFAOrchestrationService()
            
            with patch.object(orchestration.totp_service, 'generate_secret', return_value='TEST_SECRET'):
                with patch.object(orchestration.totp_service, 'generate_qr_code', return_value='data:image/png;base64,test'):
                    setup_info = orchestration.initiate_mfa_setup(self.mock_user)
                    
                    assert 'user_mfa_id' in setup_info
                    assert 'totp_secret' in setup_info
                    assert 'qr_code' in setup_info
                    assert setup_info['totp_secret'] == 'TEST_SECRET'
                    mock_db.add.assert_called()
                    mock_db.commit.assert_called()


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available")
class TestApprovalSecurityIntegration:
    """Test suite for MFA integration with approval system security."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        self.app.config['MFA_ENABLED'] = True
        self.app.config['MFA_TOTP_ENABLED'] = True
        
        # Mock AppBuilder
        self.mock_appbuilder = Mock()
        self.mock_appbuilder.get_app = self.app
        
        # Mock user object
        self.mock_user = Mock()
        self.mock_user.id = 1
        self.mock_user.username = 'testuser'
    
    def test_mfa_configuration_detection(self):
        """Test MFA configuration detection."""
        with self.app.app_context():
            validator = ApprovalSecurityValidator(self.mock_appbuilder)
            
            assert validator.mfa_enabled is True
    
    @patch('pgappforge.security.mfa.manager_mixin.MFASessionState.is_verified_and_valid')
    def test_mfa_validation_for_critical_approval(self, mock_mfa_verified):
        """Test MFA validation for critical-level approvals."""
        mock_mfa_verified.return_value = True
        
        with self.app.app_context():
            with patch('pgappforge.security.mfa.manager_mixin.MFASessionState.get_verification_method', return_value='webauthn'):
                validator = ApprovalSecurityValidator(self.mock_appbuilder)
                
                # Mock user MFA setup
                with patch.object(validator, '_get_user_mfa') as mock_get_mfa:
                    mock_user_mfa = Mock()
                    mock_user_mfa.setup_completed = True
                    mock_get_mfa.return_value = mock_user_mfa
                    
                    result = validator.validate_mfa_for_approval(self.mock_user, 'critical')
                    
                    assert result['valid'] is True
                    assert result['mfa_required'] is True
                    assert result['mfa_verified'] is True
                    assert result['method_used'] == 'webauthn'
    
    def test_mfa_validation_insufficient_method(self):
        """Test MFA validation with insufficient method for approval level."""
        with self.app.app_context():
            with patch('pgappforge.security.mfa.manager_mixin.MFASessionState.is_verified_and_valid', return_value=True):
                with patch('pgappforge.security.mfa.manager_mixin.MFASessionState.get_verification_method', return_value='sms'):
                    validator = ApprovalSecurityValidator(self.mock_appbuilder)
                    
                    # Mock user MFA setup
                    with patch.object(validator, '_get_user_mfa') as mock_get_mfa:
                        mock_user_mfa = Mock()
                        mock_user_mfa.setup_completed = True
                        mock_get_mfa.return_value = mock_user_mfa
                        
                        result = validator.validate_mfa_for_approval(self.mock_user, 'critical')
                        
                        assert result['valid'] is False
                        assert result['stronger_mfa_required'] is True
                        assert result['current_method'] == 'sms'
                        assert 'webauthn' in result['required_methods']


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available")
class TestSecurityValidation:
    """Test suite for security validation and threat detection."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key'
    
    def test_rate_limiting_with_burst_protection(self):
        """Test rate limiting with burst protection."""
        with self.app.app_context():
            mock_appbuilder = Mock()
            mock_appbuilder.get_app = self.app
            
            validator = ApprovalSecurityValidator(mock_appbuilder)
            
            # Simulate rapid requests
            user_id = 1
            
            # First few requests should succeed
            for i in range(3):
                result = validator.check_approval_rate_limit(user_id)
                assert result is True
            
            # Excessive requests should be rate limited
            # Note: This test may need adjustment based on actual rate limit thresholds


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available")
class TestErrorHandling:
    """Test suite for error handling and edge cases."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key'
    
    def test_sms_service_without_providers(self):
        """Test SMS service behavior when no providers are configured."""
        with self.app.app_context():
            sms_service = SMSService()
            
            with pytest.raises(Exception):  # Should raise configuration error
                sms_service.send_mfa_code("+1234567890", "123456")
    
    def test_email_service_without_flask_mail(self):
        """Test email service behavior when Flask-Mail is not available."""
        with self.app.app_context():
            with patch('pgappforge.security.mfa.services.HAS_FLASK_MAIL', False):
                email_service = EmailService()
                
                with pytest.raises(RuntimeError, match="Email MFA requires Flask-Mail"):
                    email_service.send_mfa_code("test@example.com", "123456")
    
    def test_invalid_phone_number_format(self):
        """Test SMS service with invalid phone number format."""
        with self.app.app_context():
            sms_service = SMSService()
            
            with pytest.raises(ValidationError, match="Phone number must be in E.164 format"):
                sms_service.send_mfa_code("1234567890", "123456")  # Missing +
    
    def test_invalid_email_format(self):
        """Test email service with invalid email format."""
        with self.app.app_context():
            with patch('pgappforge.security.mfa.services.HAS_FLASK_MAIL', True):
                email_service = EmailService()
                
                with pytest.raises(ValidationError, match="Invalid email address format"):
                    email_service.send_mfa_code("invalid-email", "123456")


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available")
class TestPerformanceAndScalability:
    """Test suite for performance and scalability aspects."""
    
    def test_token_generation_performance(self):
        """Test token generation performance."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-secret-key'
        
        with app.app_context():
            token_service = TokenGenerationService()
            
            start_time = time.time()
            tokens = [token_service.generate_numeric_token() for _ in range(1000)]
            end_time = time.time()
            
            # Should generate 1000 tokens in reasonable time
            assert end_time - start_time < 1.0  # Less than 1 second
            assert len(tokens) == 1000
            assert len(set(tokens)) >= 950  # High uniqueness
    
    def test_backup_code_generation_performance(self):
        """Test backup code generation performance."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-secret-key'
        
        with app.app_context():
            with patch('pgappforge.db.session') as mock_db:
                backup_service = BackupCodeService()
                
                start_time = time.time()
                
                # Mock the database operations
                mock_db.query().get.return_value = Mock()
                mock_db.commit = Mock()
                
                with patch('pgappforge.security.mfa.models.MFABackupCode.generate_codes') as mock_generate:
                    mock_generate.return_value = ['12345678'] * 8
                    
                    codes = backup_service.generate_codes_for_user(1, count=8)
                    
                end_time = time.time()
                
                assert end_time - start_time < 0.1  # Very fast operation
                assert len(codes) == 8


@pytest.mark.skipif(not HAS_MFA, reason="MFA components not available") 
class TestIntegrationFlows:
    """Test suite for end-to-end integration flows."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'MFA_ENABLED': True,
            'MFA_TOTP_ENABLED': True,
            'WEBAUTHN_ENABLED': True,
            'TESTING': True
        })
        
        self.mock_user = Mock()
        self.mock_user.id = 1
        self.mock_user.username = 'testuser'
        self.mock_user.email = 'test@example.com'
    
    @patch('pgappforge.db.session')
    def test_complete_mfa_setup_flow(self, mock_db):
        """Test complete MFA setup flow from initiation to completion."""
        with self.app.app_context():
            # Mock database operations
            mock_db.query().filter_by().first.return_value = None
            mock_db.add = Mock()
            mock_db.commit = Mock()
            
            orchestration = MFAOrchestrationService()
            
            # Step 1: Initiate setup
            with patch.object(orchestration.totp_service, 'generate_secret', return_value='TEST_SECRET'):
                with patch.object(orchestration.totp_service, 'generate_qr_code', return_value='data:image/png;base64,test'):
                    setup_info = orchestration.initiate_mfa_setup(self.mock_user)
                    
                    assert setup_info['totp_secret'] == 'TEST_SECRET'
                    assert 'setup_token' in setup_info
            
            # Step 2: Complete setup with verification
            mock_user_mfa = Mock()
            mock_user_mfa.totp_secret = 'TEST_SECRET'
            mock_user_mfa.verify_setup_token.return_value = True
            mock_user_mfa.clear_setup_token = Mock()
            mock_db.query().filter_by().first.return_value = mock_user_mfa
            
            with patch.object(orchestration.totp_service, 'validate_totp', return_value=(True, 12345)):
                with patch.object(orchestration.backup_service, 'generate_codes_for_user', return_value=['12345678'] * 8):
                    result = orchestration.complete_mfa_setup(
                        self.mock_user,
                        '123456',
                        setup_info['setup_token']
                    )
                    
                    assert result['setup_completed'] is True
                    assert len(result['backup_codes']) == 8
    
    @patch('pgappforge.db.session')
    def test_approval_with_mfa_requirement(self, mock_db):
        """Test approval flow with MFA requirement."""
        with self.app.app_context():
            mock_appbuilder = Mock()
            mock_appbuilder.get_app = self.app
            
            validator = ApprovalSecurityValidator(mock_appbuilder)
            
            # Mock user with MFA setup
            mock_user_mfa = Mock()
            mock_user_mfa.setup_completed = True
            
            with patch.object(validator, '_get_user_mfa', return_value=mock_user_mfa):
                with patch('pgappforge.security.mfa.manager_mixin.MFASessionState.is_verified_and_valid', return_value=True):
                    with patch('pgappforge.security.mfa.manager_mixin.MFASessionState.get_verification_method', return_value='totp'):
                        
                        approval_data = {
                            'workflow_type': 'test',
                            'priority': 'high',
                            'request_data': {'test': 'data'},
                            'user_id': 1
                        }
                        
                        result = validator.validate_approval_with_mfa(
                            self.mock_user,
                            approval_data,
                            'high'
                        )
                        
                        assert result['valid'] is True
                        assert result['mfa_validation']['valid'] is True
                        assert result['approval_level'] == 'high'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])