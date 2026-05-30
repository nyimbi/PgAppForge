"""
Unit tests for MFA Views and Forms.

This module contains comprehensive unit tests for the MFA views layer
including form validation, view functionality, AJAX endpoints, and
template rendering with complete coverage of user flows.

Test Coverage:
    - Form validation and field validation
    - View method functionality and routing
    - AJAX endpoint responses and error handling
    - Template rendering and context variables
    - Setup wizard flow and state management
    - Authentication and authorization checks
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call
from flask import Flask, session, url_for, current_app

# Test minimal imports to verify core functionality
import sys
import os
sys.path.insert(0, '/Users/nyimbiodero/src/pjs/fab-ext')

# Import specific components with error handling
try:
    from pgappforge.security.mfa.manager_mixin import MFASessionState
    from pgappforge.security.mfa.services import ValidationError as MFAValidationError
    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_AVAILABLE = False
    
    # Create mock classes for testing
    class MFASessionState:
        NOT_REQUIRED = "not_required"
        REQUIRED = "required"
        CHALLENGED = "challenged"
        VERIFIED = "verified"
        LOCKED = "locked"
    
    class MFAValidationError(Exception):
        pass


class TestMFABaseForm:
    """Test cases for MFA base form class."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
            'TESTING': True
        })
        return app
    
    def test_form_initialization(self, app):
        """Test MFA base form initialization."""
        with app.test_request_context():
            form = MFABaseForm()
            assert form is not None
            assert hasattr(form, 'validate_on_submit')
    
    def test_form_validation_override(self, app):
        """Test form validation override method."""
        with app.test_request_context():
            form = MFABaseForm()
            
            # Mock form submission
            with patch.object(form, 'is_submitted', return_value=True):
                with patch.object(form, 'validate', return_value=True):
                    assert form.validate_on_submit() is True


class TestMFASetupForm:
    """Test cases for MFA setup form."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
            'TESTING': True
        })
        return app
    
    def test_form_fields_present(self, app):
        """Test that all required form fields are present."""
        with app.test_request_context():
            form = MFASetupForm()
            
            assert hasattr(form, 'phone_number')
            assert hasattr(form, 'backup_phone')
            assert hasattr(form, 'recovery_email')
            assert hasattr(form, 'preferred_method')
            assert hasattr(form, 'setup_token')
    
    def test_phone_number_validation_valid(self, app):
        """Test valid phone number validation."""
        with app.test_request_context():
            form = MFASetupForm(data={
                'phone_number': '+15551234567',
                'preferred_method': 'totp'
            })
            
            # Test validation method directly
            form.phone_number.data = '+15551234567'
            try:
                form.validate_phone_number(form.phone_number)
            except Exception:
                pytest.fail("Valid phone number should not raise validation error")
    
    def test_phone_number_validation_invalid_format(self, app):
        """Test invalid phone number format validation."""
        with app.test_request_context():
            form = MFASetupForm()
            
            # Test without + prefix
            form.phone_number.data = '15551234567'
            with pytest.raises(Exception):
                form.validate_phone_number(form.phone_number)
            
            # Test with letters
            form.phone_number.data = '+1555abc4567'
            with pytest.raises(Exception):
                form.validate_phone_number(form.phone_number)
            
            # Test too short
            form.phone_number.data = '+1555'
            with pytest.raises(Exception):
                form.validate_phone_number(form.phone_number)
    
    def test_backup_phone_validation(self, app):
        """Test backup phone number validation."""
        with app.test_request_context():
            form = MFASetupForm()
            
            # Valid backup phone
            form.backup_phone.data = '+19876543210'
            try:
                form.validate_backup_phone(form.backup_phone)
            except Exception:
                pytest.fail("Valid backup phone should not raise validation error")
            
            # Empty backup phone should be valid
            form.backup_phone.data = ''
            try:
                form.validate_backup_phone(form.backup_phone)
            except Exception:
                pytest.fail("Empty backup phone should be valid")


class TestMFAChallengeForm:
    """Test cases for MFA challenge form."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
            'TESTING': True
        })
        return app
    
    def test_form_fields_present(self, app):
        """Test that all required form fields are present."""
        with app.test_request_context():
            form = MFAChallengeForm()
            
            assert hasattr(form, 'method')
            assert hasattr(form, 'verification_code')
    
    def test_verification_code_validation_valid(self, app):
        """Test valid verification code validation."""
        with app.test_request_context():
            form = MFAChallengeForm()
            
            # Test 6-digit code
            form.verification_code.data = '123456'
            try:
                form.validate_verification_code(form.verification_code)
            except Exception:
                pytest.fail("Valid 6-digit code should not raise validation error")
            
            # Test 8-digit backup code
            form.verification_code.data = '12345678'
            try:
                form.validate_verification_code(form.verification_code)
            except Exception:
                pytest.fail("Valid 8-digit backup code should not raise validation error")
    
    def test_verification_code_validation_invalid(self, app):
        """Test invalid verification code validation."""
        with app.test_request_context():
            form = MFAChallengeForm()
            
            # Test too short
            form.verification_code.data = '123'
            with pytest.raises(Exception):
                form.validate_verification_code(form.verification_code)
            
            # Test with letters
            form.verification_code.data = '12345a'
            with pytest.raises(Exception):
                form.validate_verification_code(form.verification_code)


class TestMFABackupCodesForm:
    """Test cases for MFA backup codes form."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
            'TESTING': True
        })
        return app
    
    def test_form_fields_present(self, app):
        """Test that all required form fields are present."""
        with app.test_request_context():
            form = MFABackupCodesForm()
            
            assert hasattr(form, 'confirmation')


class TestMFAView:
    """Test cases for MFA challenge view."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
            'TESTING': True
        })
        
        # Mock appbuilder
        app.appbuilder = MagicMock()
        app.appbuilder.sm = MagicMock()
        
        return app
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user object."""
        user = MagicMock()
        user.id = 123
        user.username = "testuser"
        user.is_authenticated = True
        return user
    
    @pytest.fixture
    def mfa_view(self):
        """Create MFA view instance."""
        with patch('pgappforge.security.mfa.views.MFAOrchestrationService'):
            return MFAView()
    
    def test_view_initialization(self, mfa_view):
        """Test MFA view initialization."""
        assert mfa_view is not None
        assert hasattr(mfa_view, 'orchestration_service')
        assert mfa_view.route_base == '/mfa'
        assert mfa_view.default_view == 'challenge'
    
    def test_challenge_get_unauthenticated(self, app, mfa_view):
        """Test challenge view GET request when user is not authenticated."""
        with app.test_request_context('/mfa/challenge'):
            with patch('pgappforge.security.mfa.views.current_user') as mock_user:
                mock_user.is_authenticated = False
                
                with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                    with patch('pgappforge.security.mfa.views.url_for', return_value='/login'):
                        with patch('pgappforge.security.mfa.views.flash'):
                            mfa_view.challenge()
                            mock_redirect.assert_called_once()
    
    def test_challenge_get_mfa_not_required(self, app, mfa_view, mock_user):
        """Test challenge view when MFA is not required."""
        with app.test_request_context('/mfa/challenge'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    # Mock security manager without MFA requirement
                    app.appbuilder.sm.is_mfa_required = MagicMock(return_value=False)
                    
                    with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                        with patch('pgappforge.security.mfa.views.url_for', return_value='/login'):
                            with patch('pgappforge.security.mfa.views.flash'):
                                mfa_view.challenge()
                                mock_redirect.assert_called_once()
    
    def test_challenge_get_already_verified(self, app, mfa_view, mock_user):
        """Test challenge view when MFA is already verified."""
        with app.test_request_context('/mfa/challenge'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    app.appbuilder.sm.is_mfa_required = MagicMock(return_value=True)
                    
                    with patch('pgappforge.security.mfa.views.MFASessionState') as mock_state:
                        mock_state.is_verified_and_valid.return_value = True
                        
                        with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                            with patch('pgappforge.security.mfa.views.url_for', return_value='/login'):
                                with patch('pgappforge.security.mfa.views.flash'):
                                    mfa_view.challenge()
                                    mock_redirect.assert_called_once()
    
    def test_challenge_get_session_locked(self, app, mfa_view, mock_user):
        """Test challenge view when session is locked."""
        with app.test_request_context('/mfa/challenge'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    app.appbuilder.sm.is_mfa_required = MagicMock(return_value=True)
                    
                    with patch('pgappforge.security.mfa.views.MFASessionState') as mock_state:
                        mock_state.is_verified_and_valid.return_value = False
                        mock_state.is_locked.return_value = True
                        
                        with patch('pgappforge.security.mfa.views.render_template') as mock_render:
                            mfa_view.challenge()
                            mock_render.assert_called_once_with(
                                'mfa/locked.html',
                                title='Account Temporarily Locked',
                                message='Too many failed attempts. Please try again later.'
                            )
    
    def test_challenge_get_no_methods_configured(self, app, mfa_view, mock_user):
        """Test challenge view when user has no MFA methods configured."""
        with app.test_request_context('/mfa/challenge'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    app.appbuilder.sm.is_mfa_required = MagicMock(return_value=True)
                    app.appbuilder.sm.get_user_mfa_methods = MagicMock(return_value=[])
                    
                    with patch('pgappforge.security.mfa.views.MFASessionState') as mock_state:
                        mock_state.is_verified_and_valid.return_value = False
                        mock_state.is_locked.return_value = False
                        
                        with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                            with patch('pgappforge.security.mfa.views.url_for', return_value='/mfa/setup'):
                                mfa_view.challenge()
                                mock_redirect.assert_called_once()
    
    def test_challenge_get_success(self, app, mfa_view, mock_user):
        """Test successful challenge view GET request."""
        with app.test_request_context('/mfa/challenge'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    app.appbuilder.sm.is_mfa_required = MagicMock(return_value=True)
                    app.appbuilder.sm.get_user_mfa_methods = MagicMock(return_value=['totp', 'sms'])
                    
                    with patch('pgappforge.security.mfa.views.MFASessionState') as mock_state:
                        mock_state.is_verified_and_valid.return_value = False
                        mock_state.is_locked.return_value = False
                        mock_state.get_state.return_value = MFASessionState.REQUIRED
                        
                        with patch('pgappforge.security.mfa.views.render_template') as mock_render:
                            mfa_view.challenge()
                            mock_render.assert_called_once()
                            
                            # Check template and context
                            call_args = mock_render.call_args
                            assert call_args[0][0] == 'mfa/challenge.html'
                            assert 'form' in call_args[1]
                            assert 'available_methods' in call_args[1]
    
    def test_initiate_ajax_success(self, app, mfa_view, mock_user):
        """Test successful MFA challenge initiation via AJAX."""
        with app.test_request_context('/mfa/initiate', method='POST', 
                                    data=json.dumps({'method': 'sms'}), 
                                    content_type='application/json'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    app.appbuilder.sm = MagicMock()
                    
                    with patch('pgappforge.security.mfa.views.MFAAuthenticationHandler') as mock_handler:
                        mock_auth_handler = MagicMock()
                        mock_handler.return_value = mock_auth_handler
                        mock_auth_handler.initiate_mfa_challenge.return_value = {
                            'method': 'sms',
                            'challenge_sent': True,
                            'message': 'Code sent'
                        }
                        
                        with patch('pgappforge.security.mfa.views.jsonify') as mock_jsonify:
                            mfa_view.initiate()
                            mock_jsonify.assert_called_once_with({
                                'success': True,
                                'method': 'sms',
                                'challenge_sent': True,
                                'message': 'Code sent'
                            })
    
    def test_initiate_ajax_missing_method(self, app, mfa_view, mock_user):
        """Test MFA challenge initiation with missing method."""
        with app.test_request_context('/mfa/initiate', method='POST', 
                                    data=json.dumps({}), 
                                    content_type='application/json'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.jsonify') as mock_jsonify:
                    mfa_view.initiate()
                    mock_jsonify.assert_called_once_with({
                        'success': False, 
                        'message': 'Method is required'
                    })
    
    def test_verify_ajax_success(self, app, mfa_view, mock_user):
        """Test successful MFA verification via AJAX."""
        with app.test_request_context('/mfa/verify', method='POST',
                                    data=json.dumps({'method': 'totp', 'code': '123456'}),
                                    content_type='application/json'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    app.appbuilder.sm = MagicMock()
                    
                    with patch('pgappforge.security.mfa.views.MFAAuthenticationHandler') as mock_handler:
                        mock_auth_handler = MagicMock()
                        mock_handler.return_value = mock_auth_handler
                        mock_auth_handler.verify_mfa_response.return_value = {
                            'success': True,
                            'message': 'Verification successful'
                        }
                        
                        with patch('pgappforge.security.mfa.views.jsonify') as mock_jsonify:
                            with patch('pgappforge.security.mfa.views.url_for', return_value='/login'):
                                mfa_view.verify()
                                mock_jsonify.assert_called_once_with({
                                    'success': True,
                                    'message': 'Verification successful',
                                    'redirect': '/login'
                                })
    
    def test_verify_ajax_failure(self, app, mfa_view, mock_user):
        """Test failed MFA verification via AJAX."""
        with app.test_request_context('/mfa/verify', method='POST',
                                    data=json.dumps({'method': 'totp', 'code': '000000'}),
                                    content_type='application/json'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    app.appbuilder.sm = MagicMock()
                    
                    with patch('pgappforge.security.mfa.views.MFAAuthenticationHandler') as mock_handler:
                        mock_auth_handler = MagicMock()
                        mock_handler.return_value = mock_auth_handler
                        mock_auth_handler.verify_mfa_response.return_value = {
                            'success': False,
                            'message': 'Invalid code',
                            'attempts_remaining': 2
                        }
                        
                        with patch('pgappforge.security.mfa.views.jsonify') as mock_jsonify:
                            mfa_view.verify()
                            mock_jsonify.assert_called_once_with({
                                'success': False,
                                'message': 'Invalid code',
                                'attempts_remaining': 2
                            })
    
    def test_status_endpoint(self, app, mfa_view, mock_user):
        """Test MFA status endpoint."""
        with app.test_request_context('/mfa/status'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.MFASessionState') as mock_state:
                    mock_state.get_state.return_value = MFASessionState.VERIFIED
                    mock_state.get_user_id.return_value = 123
                    mock_state.is_verified_and_valid.return_value = True
                    mock_state.is_locked.return_value = False
                    
                    with patch('pgappforge.security.mfa.views.jsonify') as mock_jsonify:
                        mfa_view.status()
                        
                        expected_status = {
                            'success': True,
                            'status': {
                                'state': MFASessionState.VERIFIED,
                                'user_id': 123,
                                'is_verified': True,
                                'is_locked': False
                            }
                        }
                        mock_jsonify.assert_called_once_with(expected_status)


class TestMFASetupView:
    """Test cases for MFA setup view."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
            'TESTING': True
        })
        
        # Mock appbuilder
        app.appbuilder = MagicMock()
        app.appbuilder.sm = MagicMock()
        
        return app
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user object."""
        user = MagicMock()
        user.id = 123
        user.username = "testuser"
        user.first_name = "Test"
        user.email = "test@example.com"
        user.is_authenticated = True
        return user
    
    @pytest.fixture
    def setup_view(self):
        """Create MFA setup view instance."""
        with patch('pgappforge.security.mfa.views.MFAOrchestrationService'):
            return MFASetupView()
    
    def test_view_initialization(self, setup_view):
        """Test MFA setup view initialization."""
        assert setup_view is not None
        assert hasattr(setup_view, 'orchestration_service')
        assert setup_view.route_base == '/mfa/setup'
        assert setup_view.default_view == 'setup'
    
    def test_setup_get_already_configured(self, app, setup_view, mock_user):
        """Test setup view when MFA is already configured."""
        with app.test_request_context('/mfa/setup/'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    mock_user_mfa = MagicMock()
                    mock_user_mfa.setup_completed = True
                    app.appbuilder.sm.get_user_mfa.return_value = mock_user_mfa
                    
                    with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                        with patch('pgappforge.security.mfa.views.url_for', return_value='/mfa/manage'):
                            with patch('pgappforge.security.mfa.views.flash'):
                                setup_view.setup()
                                mock_redirect.assert_called_once()
    
    def test_setup_get_not_configured(self, app, setup_view, mock_user):
        """Test setup view when MFA is not configured."""
        with app.test_request_context('/mfa/setup/'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    mock_user_mfa = MagicMock()
                    mock_user_mfa.setup_completed = False
                    app.appbuilder.sm.get_user_mfa.return_value = mock_user_mfa
                    
                    with patch('pgappforge.security.mfa.views.render_template') as mock_render:
                        setup_view.setup()
                        mock_render.assert_called_once()
                        
                        # Check template and context
                        call_args = mock_render.call_args
                        assert call_args[0][0] == 'mfa/setup.html'
                        assert 'form' in call_args[1]
                        assert call_args[1]['title'] == 'Set Up Multi-Factor Authentication'
    
    def test_setup_post_success(self, app, setup_view, mock_user):
        """Test successful MFA setup POST request."""
        with app.test_request_context('/mfa/setup/', method='POST',
                                    data={
                                        'phone_number': '+15551234567',
                                        'recovery_email': 'recovery@example.com',
                                        'preferred_method': 'totp',
                                        'csrf_token': 'test'
                                    }):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    app.appbuilder.sm.get_user_mfa.return_value = None
                    
                    # Mock orchestration service
                    setup_view.orchestration_service.initiate_mfa_setup.return_value = {
                        'user_mfa_id': 456,
                        'totp_secret': 'SECRET123',
                        'qr_code': 'data:image/png;base64,abc123',
                        'setup_token': 'TOKEN123',
                        'allowed_methods': ['totp', 'sms', 'email']
                    }
                    
                    with patch('pgappforge.security.mfa.views.session', {}) as mock_session:
                        with patch('pgappforge.security.mfa.views.db') as mock_db:
                            mock_user_mfa = MagicMock()
                            mock_db.session.query.return_value.get.return_value = mock_user_mfa
                            
                            with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                                with patch('pgappforge.security.mfa.views.url_for', return_value='/mfa/setup/verify'):
                                    with patch('pgappforge.security.mfa.views.flash'):
                                        setup_view.setup()
                                        mock_redirect.assert_called_once()
    
    def test_verify_get_no_session(self, app, setup_view, mock_user):
        """Test verify view when no setup session exists."""
        with app.test_request_context('/mfa/setup/verify'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.session', {}) as mock_session:
                    with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                        with patch('pgappforge.security.mfa.views.url_for', return_value='/mfa/setup'):
                            with patch('pgappforge.security.mfa.views.flash'):
                                setup_view.verify()
                                mock_redirect.assert_called_once()
    
    def test_verify_post_success(self, app, setup_view, mock_user):
        """Test successful setup verification POST request."""
        setup_info = {
            'user_mfa_id': 456,
            'totp_secret': 'SECRET123',
            'setup_token': 'TOKEN123'
        }
        
        with app.test_request_context('/mfa/setup/verify', method='POST',
                                    data={'verification_code': '123456'}):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.session', {'_mfa_setup_info': setup_info}) as mock_session:
                    # Mock successful completion
                    setup_view.orchestration_service.complete_mfa_setup.return_value = {
                        'setup_completed': True,
                        'backup_codes': ['12345678', '87654321']
                    }
                    
                    with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                        with patch('pgappforge.security.mfa.views.url_for', return_value='/mfa/setup/backup-codes'):
                            with patch('pgappforge.security.mfa.views.flash'):
                                setup_view.verify()
                                mock_redirect.assert_called_once()
    
    def test_backup_codes_display(self, app, setup_view, mock_user):
        """Test backup codes display after setup."""
        backup_codes = ['12345678', '87654321', '11111111']
        
        with app.test_request_context('/mfa/setup/backup-codes'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.session', {'_mfa_backup_codes': backup_codes}):
                    with patch('pgappforge.security.mfa.views.render_template') as mock_render:
                        setup_view.backup_codes()
                        mock_render.assert_called_once()
                        
                        # Check template and context
                        call_args = mock_render.call_args
                        assert call_args[0][0] == 'mfa/backup_codes.html'
                        assert call_args[1]['backup_codes'] == backup_codes
    
    def test_qr_code_endpoint_success(self, app, setup_view, mock_user):
        """Test QR code AJAX endpoint."""
        setup_info = {
            'qr_code': 'data:image/png;base64,abc123',
            'totp_secret': 'SECRET123'
        }
        
        with app.test_request_context('/mfa/setup/qr-code'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.session', {'_mfa_setup_info': setup_info}):
                    with patch('pgappforge.security.mfa.views.jsonify') as mock_jsonify:
                        setup_view.qr_code()
                        mock_jsonify.assert_called_once_with({
                            'success': True,
                            'qr_code': setup_info['qr_code'],
                            'secret': setup_info['totp_secret']
                        })


class TestMFAManagementView:
    """Test cases for MFA management view."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
            'TESTING': True
        })
        
        # Mock appbuilder
        app.appbuilder = MagicMock()
        app.appbuilder.sm = MagicMock()
        
        return app
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user object."""
        user = MagicMock()
        user.id = 123
        user.username = "testuser"
        user.is_authenticated = True
        return user
    
    @pytest.fixture
    def management_view(self):
        """Create MFA management view instance."""
        return MFAManagementView()
    
    def test_view_initialization(self, management_view):
        """Test MFA management view initialization."""
        assert management_view is not None
        assert management_view.route_base == '/mfa/manage'
        assert management_view.default_view == 'index'
    
    def test_index_mfa_not_setup(self, app, management_view, mock_user):
        """Test management index when MFA is not set up."""
        with app.test_request_context('/mfa/manage/'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    mock_user_mfa = MagicMock()
                    mock_user_mfa.setup_completed = False
                    app.appbuilder.sm.get_user_mfa.return_value = mock_user_mfa
                    
                    with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                        with patch('pgappforge.security.mfa.views.url_for', return_value='/mfa/setup'):
                            with patch('pgappforge.security.mfa.views.flash'):
                                management_view.index()
                                mock_redirect.assert_called_once()
    
    def test_index_mfa_configured(self, app, management_view, mock_user):
        """Test management index when MFA is configured."""
        with app.test_request_context('/mfa/manage/'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    mock_user_mfa = MagicMock()
                    mock_user_mfa.setup_completed = True
                    app.appbuilder.sm.get_user_mfa.return_value = mock_user_mfa
                    app.appbuilder.sm.get_user_mfa_methods.return_value = ['totp', 'sms']
                    
                    with patch('pgappforge.security.mfa.views.BackupCodeService') as mock_backup_service:
                        mock_backup_service.return_value.get_remaining_codes_count.return_value = 5
                        
                        with patch('pgappforge.security.mfa.views.render_template') as mock_render:
                            management_view.index()
                            mock_render.assert_called_once()
                            
                            # Check template and context
                            call_args = mock_render.call_args
                            assert call_args[0][0] == 'mfa/manage.html'
                            assert 'user_mfa' in call_args[1]
                            assert 'available_methods' in call_args[1]
                            assert 'remaining_backup_codes' in call_args[1]
    
    def test_regenerate_backup_codes_success(self, app, management_view, mock_user):
        """Test successful backup codes regeneration."""
        with app.test_request_context('/mfa/manage/regenerate-backup-codes', method='POST'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    mock_user_mfa = MagicMock()
                    mock_user_mfa.id = 456
                    mock_user_mfa.setup_completed = True
                    app.appbuilder.sm.get_user_mfa.return_value = mock_user_mfa
                    
                    with patch('pgappforge.security.mfa.views.BackupCodeService') as mock_backup_service:
                        mock_backup_service.return_value.generate_codes_for_user.return_value = [
                            '12345678', '87654321', '11111111'
                        ]
                        
                        with patch('pgappforge.security.mfa.views.render_template') as mock_render:
                            with patch('pgappforge.security.mfa.views.flash'):
                                management_view.regenerate_backup_codes()
                                mock_render.assert_called_once()
                                
                                # Check template and context
                                call_args = mock_render.call_args
                                assert call_args[0][0] == 'mfa/backup_codes.html'
                                assert call_args[1]['regenerated'] is True
    
    def test_disable_mfa_not_enabled(self, app, management_view, mock_user):
        """Test disable MFA when not currently enabled."""
        with app.test_request_context('/mfa/manage/disable'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    mock_user_mfa = MagicMock()
                    mock_user_mfa.is_enabled = False
                    app.appbuilder.sm.get_user_mfa.return_value = mock_user_mfa
                    
                    with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                        with patch('pgappforge.security.mfa.views.url_for', return_value='/mfa/manage'):
                            with patch('pgappforge.security.mfa.views.flash'):
                                management_view.disable()
                                mock_redirect.assert_called_once()
    
    def test_disable_mfa_policy_required(self, app, management_view, mock_user):
        """Test disable MFA when required by policy."""
        with app.test_request_context('/mfa/manage/disable'):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    mock_user_mfa = MagicMock()
                    mock_user_mfa.is_enabled = True
                    app.appbuilder.sm.get_user_mfa.return_value = mock_user_mfa
                    app.appbuilder.sm.is_mfa_required = MagicMock(return_value=True)
                    
                    with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                        with patch('pgappforge.security.mfa.views.url_for', return_value='/mfa/manage'):
                            with patch('pgappforge.security.mfa.views.flash'):
                                management_view.disable()
                                mock_redirect.assert_called_once()
    
    def test_disable_mfa_success(self, app, management_view, mock_user):
        """Test successful MFA disable."""
        with app.test_request_context('/mfa/manage/disable', method='POST',
                                    data={'confirm_disable': 'DISABLE'}):
            with patch('pgappforge.security.mfa.views.current_user', mock_user):
                with patch('pgappforge.security.mfa.views.current_app', app):
                    mock_user_mfa = MagicMock()
                    mock_user_mfa.is_enabled = True
                    app.appbuilder.sm.get_user_mfa.return_value = mock_user_mfa
                    app.appbuilder.sm.is_mfa_required = MagicMock(return_value=False)
                    
                    with patch('pgappforge.security.mfa.views.db') as mock_db:
                        with patch('pgappforge.security.mfa.views.MFASessionState') as mock_state:
                            with patch('pgappforge.security.mfa.views.redirect') as mock_redirect:
                                with patch('pgappforge.security.mfa.views.url_for', return_value='/login'):
                                    with patch('pgappforge.security.mfa.views.flash'):
                                        management_view.disable()
                                        
                                        # Check that MFA was disabled
                                        assert mock_user_mfa.is_enabled is False
                                        assert mock_user_mfa.setup_completed is False
                                        mock_db.session.commit.assert_called_once()
                                        mock_state.clear.assert_called_once()
                                        mock_redirect.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])