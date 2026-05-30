"""
Minimal unit tests for MFA service layer (avoiding circular import issues).

This module contains targeted unit tests for MFA services without importing
the full PgAppForge framework to avoid circular import issues.
"""

import pytest
import io
import base64
import secrets
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, '/Users/nyimbiodero/src/pjs/fab-ext')

# Import services directly
from pgappforge.security.mfa.services import (
    CircuitBreaker, CircuitBreakerState, 
    MFAServiceError, ServiceUnavailableError,
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


class TestMFAServiceExceptions:
    """Test cases for MFA service exceptions."""
    
    def test_mfa_service_error(self):
        """Test MFAServiceError base exception."""
        error = MFAServiceError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)
    
    def test_service_unavailable_error(self):
        """Test ServiceUnavailableError exception."""
        error = ServiceUnavailableError("Service down")
        assert str(error) == "Service down"
        assert isinstance(error, MFAServiceError)
    
    def test_validation_error(self):
        """Test ValidationError exception."""
        error = ValidationError("Invalid input")
        assert str(error) == "Invalid input"
        assert isinstance(error, MFAServiceError)
    
    def test_configuration_error(self):
        """Test ConfigurationError exception."""
        error = ConfigurationError("Bad config")
        assert str(error) == "Bad config"
        assert isinstance(error, MFAServiceError)


# Test the TOTP service with minimal mocks
class TestTOTPServiceMinimal:
    """Minimal TOTP service tests using mocks."""
    
    @patch('pgappforge.security.mfa.services.current_app')
    def test_totp_service_init(self, mock_app):
        """Test TOTP service initialization."""
        mock_app.config.get.side_effect = lambda key, default=None: {
            'MFA_TOTP_ISSUER': 'Test App',
            'MFA_TOTP_VALIDITY_WINDOW': 2
        }.get(key, default)
        
        from pgappforge.security.mfa.services import TOTPService
        
        service = TOTPService()
        assert service.issuer == 'Test App'
        assert service.validity_window == 2
    
    @patch('pgappforge.security.mfa.services.current_app')
    @patch('pgappforge.security.mfa.services.pyotp')
    def test_generate_secret(self, mock_pyotp, mock_app):
        """Test TOTP secret generation."""
        mock_app.config.get.return_value = 'Test App'
        mock_pyotp.random_base32.return_value = 'TESTSECRET123456'
        
        from pgappforge.security.mfa.services import TOTPService
        
        service = TOTPService()
        secret = service.generate_secret()
        
        assert secret == 'TESTSECRET123456'
        mock_pyotp.random_base32.assert_called_once()
    
    @patch('pgappforge.security.mfa.services.current_app')
    @patch('pgappforge.security.mfa.services.pyotp')
    @patch('pgappforge.security.mfa.services.qrcode')
    def test_generate_qr_code(self, mock_qrcode, mock_pyotp, mock_app):
        """Test QR code generation."""
        mock_app.config.get.return_value = 'Test App'
        
        # Mock TOTP object
        mock_totp = MagicMock()
        mock_totp.provisioning_uri.return_value = 'otpauth://totp/test'
        mock_pyotp.TOTP.return_value = mock_totp
        
        # Mock QR code generation
        mock_qr_instance = MagicMock()
        mock_qrcode.QRCode.return_value = mock_qr_instance
        
        mock_img = MagicMock()
        mock_qr_instance.make_image.return_value = mock_img
        
        from pgappforge.security.mfa.services import TOTPService
        
        service = TOTPService()
        
        # Mock the image buffer operations
        with patch('pgappforge.security.mfa.services.io.BytesIO') as mock_buffer:
            mock_buffer_instance = MagicMock()
            mock_buffer.return_value = mock_buffer_instance
            mock_buffer_instance.getvalue.return_value = b'fake_image_data'
            
            with patch('pgappforge.security.mfa.services.base64.b64encode') as mock_b64:
                mock_b64.return_value = b'ZmFrZV9pbWFnZV9kYXRh'
                
                qr_code = service.generate_qr_code('SECRET123', 'test@example.com')
                
                assert qr_code == 'data:image/png;base64,ZmFrZV9pbWFnZV9kYXRh'
    
    @patch('pgappforge.security.mfa.services.current_app')
    @patch('pgappforge.security.mfa.services.pyotp')
    @patch('pgappforge.security.mfa.services.datetime')
    def test_validate_totp_success(self, mock_datetime, mock_pyotp, mock_app):
        """Test successful TOTP validation."""
        mock_app.config.get.side_effect = lambda key, default=None: {
            'MFA_TOTP_VALIDITY_WINDOW': 1
        }.get(key, default)
        
        # Mock datetime
        fake_now = datetime(2024, 1, 1, 12, 0, 0)
        mock_datetime.utcnow.return_value = fake_now
        
        # Mock TOTP object
        mock_totp = MagicMock()
        mock_totp.timecode.return_value = 123456
        mock_totp.verify.return_value = True
        mock_pyotp.TOTP.return_value = mock_totp
        
        from pgappforge.security.mfa.services import TOTPService
        
        service = TOTPService()
        is_valid, counter = service.validate_totp('SECRET123', '123456')
        
        assert is_valid is True
        assert counter == 123456
        mock_totp.verify.assert_called_once()
    
    @patch('pgappforge.security.mfa.services.current_app')
    @patch('pgappforge.security.mfa.services.pyotp')
    @patch('pgappforge.security.mfa.services.datetime')
    def test_validate_totp_replay_protection(self, mock_datetime, mock_pyotp, mock_app):
        """Test TOTP replay protection."""
        mock_app.config.get.side_effect = lambda key, default=None: {
            'MFA_TOTP_VALIDITY_WINDOW': 1
        }.get(key, default)
        
        # Mock datetime
        fake_now = datetime(2024, 1, 1, 12, 0, 0)
        mock_datetime.utcnow.return_value = fake_now
        
        # Mock TOTP object
        mock_totp = MagicMock()
        mock_totp.timecode.return_value = 123456
        mock_pyotp.TOTP.return_value = mock_totp
        
        from pgappforge.security.mfa.services import TOTPService
        
        service = TOTPService()
        
        # Should reject replay (counter <= last_counter)
        is_valid, counter = service.validate_totp('SECRET123', '123456', last_counter=123456)
        
        assert is_valid is False
        assert counter == 123456
        mock_totp.verify.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])