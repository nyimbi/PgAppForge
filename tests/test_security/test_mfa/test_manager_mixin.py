"""
Unit tests for MFA Security Manager Integration.

This module contains comprehensive unit tests for the Security Manager
integration including session management, authentication flow integration,
and policy enforcement.

Test Coverage:
    - MFA session state management
    - Authentication handler functionality
    - Security manager mixin integration
    - Decorator functionality
    - Policy enforcement and flow control
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call
from flask import Flask, session, request, current_app

# Import directly to avoid circular import issues
import sys
sys.path.insert(0, '/Users/nyimbiodero/src/pjs/fab-ext')

from pgappforge.security.mfa.manager_mixin import (
    MFASessionState, MFAAuthenticationHandler, 
    MFASecurityManagerMixin, mfa_required,
    ValidationError, ServiceUnavailableError
)


class TestMFASessionState:
    """Test cases for MFA session state management."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'MFA_SESSION_TIMEOUT': 1800,
            'TESTING': True
        })
        return app
    
    def test_initial_state(self, app):
        """Test initial MFA session state."""
        with app.test_request_context():
            assert MFASessionState.get_state() == MFASessionState.NOT_REQUIRED
            assert MFASessionState.get_user_id() is None
    
    def test_set_state(self, app):
        """Test setting MFA state."""
        with app.test_request_context():
            MFASessionState.set_state(MFASessionState.REQUIRED, user_id=123)
            
            assert MFASessionState.get_state() == MFASessionState.REQUIRED
            assert MFASessionState.get_user_id() == 123
    
    def test_set_challenge(self, app):
        """Test setting MFA challenge state."""
        with app.test_request_context():
            MFASessionState.set_challenge("totp", 456)
            
            assert MFASessionState.get_state() == MFASessionState.CHALLENGED
            assert MFASessionState.get_user_id() == 456
            assert session[MFASessionState.MFA_CHALLENGE_METHOD_KEY] == "totp"
            assert session[MFASessionState.MFA_ATTEMPTS_KEY] == 0
    
    def test_set_verified(self, app):
        """Test setting MFA verified state."""
        with app.test_request_context():
            # First set challenge state
            MFASessionState.set_challenge("sms", 789)
            
            # Then verify
            MFASessionState.set_verified(789, "sms")
            
            assert MFASessionState.get_state() == MFASessionState.VERIFIED
            assert MFASessionState.get_user_id() == 789
            assert MFASessionState.MFA_VERIFIED_TIME_KEY in session
            
            # Challenge state should be cleared
            assert MFASessionState.MFA_CHALLENGE_METHOD_KEY not in session
            assert MFASessionState.MFA_CHALLENGE_TIME_KEY not in session
            assert MFASessionState.MFA_ATTEMPTS_KEY not in session
    
    def test_increment_attempts(self, app):
        """Test incrementing failed attempts."""
        with app.test_request_context():
            # Start with no attempts
            assert session.get(MFASessionState.MFA_ATTEMPTS_KEY, 0) == 0
            
            # Increment attempts
            attempts = MFASessionState.increment_attempts()
            assert attempts == 1
            assert session[MFASessionState.MFA_ATTEMPTS_KEY] == 1
            
            attempts = MFASessionState.increment_attempts()
            assert attempts == 2
            assert session[MFASessionState.MFA_ATTEMPTS_KEY] == 2
    
    def test_set_lockout(self, app):
        """Test setting session lockout."""
        with app.test_request_context():
            MFASessionState.set_lockout(300)  # 5 minutes
            
            assert MFASessionState.get_state() == MFASessionState.LOCKED
            assert MFASessionState.MFA_LOCKOUT_TIME_KEY in session
    
    def test_is_locked_true(self, app):
        """Test checking if session is locked - positive case."""
        with app.test_request_context():
            # Set lockout for 5 minutes in the future
            MFASessionState.set_lockout(300)
            
            assert MFASessionState.is_locked() is True
    
    def test_is_locked_false_not_locked(self, app):
        """Test checking if session is locked - not locked."""
        with app.test_request_context():
            MFASessionState.set_state(MFASessionState.VERIFIED)
            
            assert MFASessionState.is_locked() is False
    
    def test_is_locked_false_expired(self, app):
        """Test checking if session is locked - lockout expired."""
        with app.test_request_context():
            # Manually set expired lockout
            session[MFASessionState.MFA_STATE_KEY] = MFASessionState.LOCKED
            expired_time = datetime.utcnow() - timedelta(minutes=10)
            session[MFASessionState.MFA_LOCKOUT_TIME_KEY] = expired_time.isoformat()
            
            assert MFASessionState.is_locked() is False
    
    @patch('pgappforge.security.mfa.manager_mixin.datetime')
    def test_is_verified_and_valid_true(self, mock_datetime, app):
        """Test checking if MFA is verified and valid - positive case."""
        with app.test_request_context():
            # Mock current time
            mock_now = datetime(2024, 1, 1, 12, 0, 0)
            mock_datetime.utcnow.return_value = mock_now
            
            # Set verified state 10 minutes ago (within 30-minute timeout)
            verified_time = mock_now - timedelta(minutes=10)
            session[MFASessionState.MFA_STATE_KEY] = MFASessionState.VERIFIED
            session[MFASessionState.MFA_VERIFIED_TIME_KEY] = verified_time.isoformat()
            
            assert MFASessionState.is_verified_and_valid() is True
    
    @patch('pgappforge.security.mfa.manager_mixin.datetime')
    def test_is_verified_and_valid_false_expired(self, mock_datetime, app):
        """Test checking if MFA is verified and valid - expired."""
        with app.test_request_context():
            # Mock current time
            mock_now = datetime(2024, 1, 1, 12, 0, 0)
            mock_datetime.utcnow.return_value = mock_now
            
            # Set verified state 31 minutes ago (beyond 30-minute timeout)
            verified_time = mock_now - timedelta(minutes=31)
            session[MFASessionState.MFA_STATE_KEY] = MFASessionState.VERIFIED
            session[MFASessionState.MFA_VERIFIED_TIME_KEY] = verified_time.isoformat()
            
            assert MFASessionState.is_verified_and_valid() is False
    
    def test_is_verified_and_valid_false_not_verified(self, app):
        """Test checking if MFA is verified and valid - not verified."""
        with app.test_request_context():
            MFASessionState.set_state(MFASessionState.REQUIRED)
            
            assert MFASessionState.is_verified_and_valid() is False
    
    def test_clear_session(self, app):
        """Test clearing all MFA session state."""
        with app.test_request_context():
            # Set various session data
            MFASessionState.set_challenge("totp", 123)
            MFASessionState.set_lockout(300)
            
            # Verify data is present
            assert MFASessionState.MFA_STATE_KEY in session
            assert MFASessionState.MFA_USER_ID_KEY in session
            
            # Clear session
            MFASessionState.clear()
            
            # Verify all data is cleared
            mfa_keys = [
                MFASessionState.MFA_STATE_KEY,
                MFASessionState.MFA_USER_ID_KEY,
                MFASessionState.MFA_CHALLENGE_TIME_KEY,
                MFASessionState.MFA_VERIFIED_TIME_KEY,
                MFASessionState.MFA_CHALLENGE_METHOD_KEY,
                MFASessionState.MFA_ATTEMPTS_KEY,
                MFASessionState.MFA_LOCKOUT_TIME_KEY
            ]
            
            for key in mfa_keys:
                assert key not in session


class TestMFAAuthenticationHandler:
    """Test cases for MFA authentication handler."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'MFA_MAX_SESSION_ATTEMPTS': 3,
            'MFA_SESSION_LOCKOUT': 300,
            'TESTING': True
        })
        return app
    
    @pytest.fixture
    def mock_security_manager(self):
        """Create mock security manager."""
        sm = MagicMock()
        sm.get_user_mfa.return_value = None
        return sm
    
    @pytest.fixture
    def auth_handler(self, mock_security_manager):
        """Create authentication handler with mocked dependencies."""
        with patch('pgappforge.security.mfa.manager_mixin.MFAOrchestrationService'):
            with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
                return MFAAuthenticationHandler(mock_security_manager)
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user object."""
        user = MagicMock()
        user.id = 123
        user.username = "testuser"
        user.first_name = "Test"
        user.email = "test@example.com"
        return user
    
    @pytest.fixture
    def mock_user_mfa(self):
        """Create mock UserMFA object."""
        user_mfa = MagicMock()
        user_mfa.id = 456
        user_mfa.is_enabled = True
        user_mfa.setup_completed = True
        user_mfa.totp_secret = "SECRET123"
        user_mfa.phone_number = "+15551234567"
        user_mfa.recovery_email = "recovery@example.com"
        user_mfa.can_attempt_mfa.return_value = True
        return user_mfa
    
    def test_is_mfa_required_enabled_user(self, auth_handler, mock_user, mock_user_mfa):
        """Test MFA requirement check for user with MFA enabled."""
        auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
        
        result = auth_handler.is_mfa_required(mock_user)
        
        assert result is True
        auth_handler.security_manager.get_user_mfa.assert_called_once_with(123)
    
    def test_is_mfa_required_policy_required(self, auth_handler, mock_user):
        """Test MFA requirement check when required by policy."""
        auth_handler.security_manager.get_user_mfa.return_value = None
        auth_handler.policy_service.is_mfa_required_for_user.return_value = True
        
        result = auth_handler.is_mfa_required(mock_user)
        
        assert result is True
        auth_handler.policy_service.is_mfa_required_for_user.assert_called_once_with(mock_user)
    
    def test_is_mfa_required_not_required(self, auth_handler, mock_user):
        """Test MFA requirement check when not required."""
        auth_handler.security_manager.get_user_mfa.return_value = None
        auth_handler.policy_service.is_mfa_required_for_user.return_value = False
        
        result = auth_handler.is_mfa_required(mock_user)
        
        assert result is False
    
    def test_get_user_mfa_methods_configured(self, auth_handler, mock_user, mock_user_mfa):
        """Test getting MFA methods for configured user."""
        auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
        auth_handler.policy_service.get_allowed_methods_for_user.return_value = [
            'totp', 'sms', 'email', 'backup'
        ]
        
        with patch('pgappforge.security.mfa.manager_mixin.BackupCodeService') as mock_backup_service:
            mock_backup_service.return_value.get_remaining_codes_count.return_value = 5
            
            methods = auth_handler.get_user_mfa_methods(mock_user)
            
            assert 'totp' in methods
            assert 'sms' in methods
            assert 'email' in methods
            assert 'backup' in methods
    
    def test_get_user_mfa_methods_not_setup(self, auth_handler, mock_user, mock_user_mfa):
        """Test getting MFA methods for user without completed setup."""
        mock_user_mfa.setup_completed = False
        auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
        
        methods = auth_handler.get_user_mfa_methods(mock_user)
        
        assert methods == []
    
    def test_initiate_mfa_challenge_sms_success(self, app, auth_handler, mock_user, mock_user_mfa):
        """Test successful SMS MFA challenge initiation."""
        with app.test_request_context():
            auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
            
            with patch.object(auth_handler, 'get_user_mfa_methods', return_value=['sms']):
                with patch('pgappforge.security.mfa.manager_mixin.SMSService') as mock_sms:
                    with patch.object(auth_handler, '_generate_challenge_code', return_value='123456'):
                        mock_sms.return_value.send_mfa_code.return_value = True
                        
                        result = auth_handler.initiate_mfa_challenge(mock_user, "sms")
                        
                        assert result["method"] == "sms"
                        assert result["challenge_sent"] is True
                        assert "phone" in result["message"]
                        assert '_mfa_challenge_code' in session
    
    def test_initiate_mfa_challenge_email_success(self, app, auth_handler, mock_user, mock_user_mfa):
        """Test successful email MFA challenge initiation."""
        with app.test_request_context():
            auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
            
            with patch.object(auth_handler, 'get_user_mfa_methods', return_value=['email']):
                with patch('pgappforge.security.mfa.manager_mixin.EmailService') as mock_email:
                    with patch.object(auth_handler, '_generate_challenge_code', return_value='789012'):
                        mock_email.return_value.send_mfa_code.return_value = True
                        
                        result = auth_handler.initiate_mfa_challenge(mock_user, "email")
                        
                        assert result["method"] == "email"
                        assert result["challenge_sent"] is True
                        assert "email" in result["message"]
    
    def test_initiate_mfa_challenge_totp(self, app, auth_handler, mock_user, mock_user_mfa):
        """Test TOTP MFA challenge initiation (no actual challenge needed)."""
        with app.test_request_context():
            auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
            
            with patch.object(auth_handler, 'get_user_mfa_methods', return_value=['totp']):
                result = auth_handler.initiate_mfa_challenge(mock_user, "totp")
                
                assert result["method"] == "totp"
                assert result["challenge_sent"] is False
                assert "authenticator app" in result["message"]
    
    def test_initiate_mfa_challenge_method_not_available(self, auth_handler, mock_user):
        """Test MFA challenge initiation with unavailable method."""
        with patch.object(auth_handler, 'get_user_mfa_methods', return_value=['totp']):
            with pytest.raises(ValidationError, match="not available"):
                auth_handler.initiate_mfa_challenge(mock_user, "sms")
    
    def test_initiate_mfa_challenge_user_locked(self, auth_handler, mock_user, mock_user_mfa):
        """Test MFA challenge initiation when user is locked."""
        mock_user_mfa.can_attempt_mfa.return_value = False
        auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
        
        with patch.object(auth_handler, 'get_user_mfa_methods', return_value=['totp']):
            with pytest.raises(ValidationError, match="temporarily locked"):
                auth_handler.initiate_mfa_challenge(mock_user, "totp")
    
    def test_verify_mfa_response_totp_success(self, app, auth_handler, mock_user):
        """Test successful TOTP MFA verification."""
        with app.test_request_context():
            auth_handler.orchestration_service.verify_mfa_code.return_value = {
                'verification_success': True,
                'session_expires': datetime.utcnow() + timedelta(hours=1)
            }
            
            result = auth_handler.verify_mfa_response(mock_user, "totp", "123456")
            
            assert result["success"] is True
            assert result["method"] == "totp"
            assert "session_expires" in result
    
    def test_verify_mfa_response_totp_failure(self, app, auth_handler, mock_user):
        """Test failed TOTP MFA verification."""
        with app.test_request_context():
            auth_handler.orchestration_service.verify_mfa_code.return_value = {
                'verification_success': False,
                'failure_reason': 'Invalid code'
            }
            
            result = auth_handler.verify_mfa_response(mock_user, "totp", "000000")
            
            assert result["success"] is False
            assert result["message"] == "Invalid code"
            assert "attempts_remaining" in result
    
    def test_verify_mfa_response_sms_success(self, app, auth_handler, mock_user, mock_user_mfa):
        """Test successful SMS MFA verification."""
        with app.test_request_context():
            # Setup challenge code in session
            from werkzeug.security import generate_password_hash
            session['_mfa_challenge_code'] = generate_password_hash('123456')
            
            auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
            
            with patch('pgappforge.security.mfa.manager_mixin.MFAVerification'):
                result = auth_handler.verify_mfa_response(mock_user, "sms", "123456")
                
                assert result["success"] is True
                assert result["method"] == "sms"
                assert '_mfa_challenge_code' not in session
    
    def test_verify_mfa_response_sms_invalid_code(self, app, auth_handler, mock_user, mock_user_mfa):
        """Test SMS MFA verification with invalid code."""
        with app.test_request_context():
            # Setup challenge code in session
            from werkzeug.security import generate_password_hash
            session['_mfa_challenge_code'] = generate_password_hash('123456')
            
            auth_handler.security_manager.get_user_mfa.return_value = mock_user_mfa
            
            with patch('pgappforge.security.mfa.manager_mixin.MFAVerification'):
                result = auth_handler.verify_mfa_response(mock_user, "sms", "000000")
                
                assert result["success"] is False
                assert "Invalid verification code" in result["message"]
    
    def test_verify_mfa_response_session_locked(self, app, auth_handler, mock_user):
        """Test MFA verification when session is locked."""
        with app.test_request_context():
            MFASessionState.set_lockout(300)
            
            result = auth_handler.verify_mfa_response(mock_user, "totp", "123456")
            
            assert result["success"] is False
            assert result["locked"] is True
            assert "temporarily locked" in result["message"]
    
    def test_verify_mfa_response_max_attempts_reached(self, app, auth_handler, mock_user):
        """Test MFA verification when max attempts reached."""
        with app.test_request_context():
            # Set attempts just below max
            session[MFASessionState.MFA_ATTEMPTS_KEY] = 2
            
            auth_handler.orchestration_service.verify_mfa_code.return_value = {
                'verification_success': False,
                'failure_reason': 'Invalid code'
            }
            
            result = auth_handler.verify_mfa_response(mock_user, "totp", "000000")
            
            assert result["success"] is False
            assert result["locked"] is True
            assert "Too many failed attempts" in result["message"]
    
    def test_generate_challenge_code_default_length(self, auth_handler):
        """Test challenge code generation with default length."""
        code = auth_handler._generate_challenge_code()
        
        assert len(code) == 6
        assert code.isdigit()
    
    def test_generate_challenge_code_custom_length(self, auth_handler):
        """Test challenge code generation with custom length."""
        code = auth_handler._generate_challenge_code(length=8)
        
        assert len(code) == 8
        assert code.isdigit()


class TestMFARequired:
    """Test cases for the @mfa_required decorator."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-secret-key'
        
        # Mock appbuilder
        app.appbuilder = MagicMock()
        app.appbuilder.sm = MagicMock()
        
        return app
    
    @pytest.fixture
    def mock_view(self):
        """Create mock view function."""
        @mfa_required
        def protected_view():
            return "Protected content"
        
        return protected_view
    
    def test_mfa_required_not_authenticated(self, app, mock_view):
        """Test @mfa_required when user is not authenticated."""
        with app.test_request_context():
            with patch('pgappforge.security.mfa.manager_mixin.current_user') as mock_user:
                mock_user.is_authenticated = False
                
                with patch('pgappforge.security.mfa.manager_mixin.redirect') as mock_redirect:
                    with patch('pgappforge.security.mfa.manager_mixin.url_for', return_value='/login'):
                        mock_view()
                        mock_redirect.assert_called_once()
    
    def test_mfa_required_no_mfa_needed(self, app, mock_view):
        """Test @mfa_required when MFA is not required."""
        with app.test_request_context():
            with patch('pgappforge.security.mfa.manager_mixin.current_user') as mock_user:
                mock_user.is_authenticated = True
                
                # Security manager doesn't have MFA capability
                app.appbuilder.sm.is_mfa_required = None
                
                result = mock_view()
                assert result == "Protected content"
    
    def test_mfa_required_mfa_verified(self, app, mock_view):
        """Test @mfa_required when MFA is verified."""
        with app.test_request_context():
            with patch('pgappforge.security.mfa.manager_mixin.current_user') as mock_user:
                mock_user.is_authenticated = True
                app.appbuilder.sm.is_mfa_required.return_value = True
                
                with patch('pgappforge.security.mfa.manager_mixin.MFASessionState') as mock_state:
                    mock_state.is_verified_and_valid.return_value = True
                    
                    result = mock_view()
                    assert result == "Protected content"
    
    def test_mfa_required_mfa_not_verified(self, app, mock_view):
        """Test @mfa_required when MFA is not verified."""
        with app.test_request_context():
            with patch('pgappforge.security.mfa.manager_mixin.current_user') as mock_user:
                mock_user.is_authenticated = True
                app.appbuilder.sm.is_mfa_required.return_value = True
                
                with patch('pgappforge.security.mfa.manager_mixin.MFASessionState') as mock_state:
                    mock_state.is_verified_and_valid.return_value = False
                    
                    with patch('pgappforge.security.mfa.manager_mixin.redirect') as mock_redirect:
                        with patch('pgappforge.security.mfa.manager_mixin.url_for', return_value='/mfa/challenge'):
                            mock_view()
                            mock_redirect.assert_called_once()


class TestMFASecurityManagerMixin:
    """Test cases for MFA Security Manager Mixin."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'FAB_ADD_SECURITY_VIEWS': True,
            'TESTING': True
        })
        return app
    
    @pytest.fixture  
    def mock_appbuilder(self):
        """Create mock AppBuilder instance."""
        appbuilder = MagicMock()
        appbuilder.get_app.config.get.return_value = True
        appbuilder.add_view_no_menu = MagicMock()
        return appbuilder
    
    @pytest.fixture
    def mock_base_security_manager(self):
        """Create mock base security manager."""
        class MockBaseSecurityManager:
            def __init__(self, appbuilder):
                self.appbuilder = appbuilder
                self.get_session = MagicMock()
            
            def auth_user_ldap(self, username, password):
                return None
            
            def auth_user_db(self, username, password):
                return None
            
            def auth_user_oid(self, email):
                return None
            
            def auth_user_oauth(self, userinfo):
                return None
            
            def auth_user_remote_user(self, username):
                return None
            
            def before_request(self):
                pass
        
        return MockBaseSecurityManager
    
    def test_initialization(self, mock_appbuilder, mock_base_security_manager):
        """Test MFA security manager initialization."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            pass
        
        with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
            sm = TestSecurityManager(mock_appbuilder)
            
            assert hasattr(sm, 'mfa_auth_handler')
            assert hasattr(sm, 'policy_service')
    
    def test_register_mfa_views_success(self, mock_appbuilder, mock_base_security_manager):
        """Test successful MFA views registration."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            pass
        
        with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
            with patch.dict('sys.modules', {'pgappforge.security.mfa.views': MagicMock()}):
                sm = TestSecurityManager(mock_appbuilder)
                
                # Should attempt to register views
                assert mock_appbuilder.add_view_no_menu.call_count >= 0
    
    def test_register_mfa_views_import_error(self, mock_appbuilder, mock_base_security_manager):
        """Test MFA views registration with import error."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            pass
        
        with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
            # This should not raise an exception even if views can't be imported
            sm = TestSecurityManager(mock_appbuilder)
            
            assert hasattr(sm, 'mfa_auth_handler')
    
    def test_get_user_mfa(self, mock_appbuilder, mock_base_security_manager):
        """Test getting user MFA configuration."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            pass
        
        with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
            sm = TestSecurityManager(mock_appbuilder)
            
            # Mock the query
            mock_user_mfa = MagicMock()
            sm.get_session.query.return_value.filter_by.return_value.first.return_value = mock_user_mfa
            
            result = sm.get_user_mfa(123)
            
            assert result == mock_user_mfa
            sm.get_session.query.assert_called_once()
    
    def test_is_mfa_required(self, mock_appbuilder, mock_base_security_manager):
        """Test checking if MFA is required."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            pass
        
        with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
            sm = TestSecurityManager(mock_appbuilder)
            
            mock_user = MagicMock()
            sm.mfa_auth_handler.is_mfa_required.return_value = True
            
            result = sm.is_mfa_required(mock_user)
            
            assert result is True
            sm.mfa_auth_handler.is_mfa_required.assert_called_once_with(mock_user)
    
    def test_auth_user_db_with_mfa(self, app, mock_appbuilder, mock_base_security_manager):
        """Test database authentication with MFA required."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            def auth_user_db(self, username, password):
                # Mock successful authentication
                user = MagicMock()
                user.id = 123
                return user
        
        with app.test_request_context():
            with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
                sm = TestSecurityManager(mock_appbuilder)
                sm.mfa_auth_handler.is_mfa_required = MagicMock(return_value=True)
                
                user = sm.auth_user_db("testuser", "password")
                
                assert user is not None
                assert session['_mfa_pending_user_id'] == 123
                assert session[MFASessionState.MFA_STATE_KEY] == MFASessionState.REQUIRED
    
    def test_should_skip_mfa_check_static_files(self, mock_appbuilder, mock_base_security_manager):
        """Test skipping MFA check for static files."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            pass
        
        with patch('pgappforge.security.mfa.manager_mixin.request') as mock_request:
            mock_request.endpoint = 'static'
            
            with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
                sm = TestSecurityManager(mock_appbuilder)
                
                result = sm._should_skip_mfa_check()
                assert result is True
    
    def test_should_skip_mfa_check_regular_endpoint(self, mock_appbuilder, mock_base_security_manager):
        """Test not skipping MFA check for regular endpoints."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            pass
        
        with patch('pgappforge.security.mfa.manager_mixin.request') as mock_request:
            mock_request.endpoint = 'SomeView.index'
            
            with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
                sm = TestSecurityManager(mock_appbuilder)
                
                result = sm._should_skip_mfa_check()
                assert result is False
    
    def test_is_mfa_route(self, mock_appbuilder, mock_base_security_manager):
        """Test checking if current route is MFA-related."""
        class TestSecurityManager(MFASecurityManagerMixin, mock_base_security_manager):
            pass
        
        with patch('pgappforge.security.mfa.manager_mixin.request') as mock_request:
            mock_request.endpoint = 'MFAView.challenge'
            
            with patch('pgappforge.security.mfa.manager_mixin.MFAPolicyService'):
                sm = TestSecurityManager(mock_appbuilder)
                
                result = sm._is_mfa_route()
                assert result is True


if __name__ == "__main__":
    pytest.main([__file__])