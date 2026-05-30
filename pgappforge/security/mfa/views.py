"""
Multi-Factor Authentication Views and Forms

This module provides PgAppForge views and forms for MFA functionality
including setup wizards, challenge/response interfaces, and management views.

Classes:
    MFAView: Main MFA challenge and verification interface
    MFASetupView: MFA setup wizard and configuration interface
    MFAManagementView: User MFA settings management
    MFAForm: Base form for MFA operations
    MFASetupForm: Form for MFA setup and configuration
    MFAChallengeForm: Form for MFA challenge verification

Features:
    - Responsive HTML5 templates with Bootstrap styling
    - AJAX endpoints for seamless user experience
    - QR code generation for TOTP setup
    - Progressive setup wizard with validation
    - Real-time form validation and feedback
    - Accessibility compliance (WCAG 2.1)
"""

import logging
import qrcode
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from flask import (
    request, redirect, url_for, flash, render_template,
    jsonify, session, current_app, abort
)
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import (
    StringField, SelectField, HiddenField, TextAreaField,
    BooleanField, PasswordField, validators
)
from wtforms.validators import DataRequired, Length, ValidationError
from flask_babel import lazy_gettext as _

from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge._compat import as_unicode

from .models import UserMFA, MFAPolicy, WebAuthnCredential
from .services import MFAOrchestrationService, WebAuthnService, ValidationError as MFAValidationError
from .manager_mixin import MFASessionState, MFAAuthenticationHandler

log = logging.getLogger(__name__)


class MFABaseForm(FlaskForm):
    """Base form class for MFA operations with common functionality."""
    
    def __init__(self, *args, **kwargs):
        """Initialize form with CSRF protection."""
        super().__init__(*args, **kwargs)
    
    def validate_on_submit(self):
        """Override to add custom validation logic."""
        return super().validate_on_submit()


class MFASetupForm(MFABaseForm):
    """Form for MFA setup and configuration."""
    
    phone_number = StringField(
        _('Phone Number'),
        validators=[
            Length(min=10, max=20, message=_('Phone number must be between 10-20 characters')),
        ],
        description=_('Phone number for SMS verification (E.164 format: +1234567890)'),
        render_kw={
            'placeholder': '+1234567890',
            'pattern': r'^\+\d{1,3}\d{4,14}$',
            'title': 'Enter phone number in international format'
        }
    )
    
    backup_phone = StringField(
        _('Backup Phone Number'),
        validators=[
            Length(min=10, max=20, message=_('Backup phone number must be between 10-20 characters')),
        ],
        description=_('Optional backup phone number'),
        render_kw={
            'placeholder': '+1987654321',
            'pattern': r'^\+\d{1,3}\d{4,14}$',
            'title': 'Enter backup phone number in international format'
        }
    )
    
    recovery_email = StringField(
        _('Recovery Email'),
        validators=[
            validators.Email(message=_('Invalid email address')),
        ],
        description=_('Email address for MFA codes and recovery'),
        render_kw={
            'placeholder': 'recovery@example.com',
            'type': 'email'
        }
    )
    
    preferred_method = SelectField(
        _('Preferred MFA Method'),
        choices=[
            ('totp', _('Authenticator App (TOTP)')),
            ('sms', _('SMS Text Message')),
            ('email', _('Email Code')),
        ],
        default='totp',
        validators=[DataRequired()],
        description=_('Primary method for MFA verification')
    )
    
    setup_token = HiddenField()
    
    def validate_phone_number(self, field):
        """Validate phone number format."""
        if field.data:
            if not field.data.startswith('+'):
                raise ValidationError(_('Phone number must be in international format starting with +'))
            
            # Remove + and check if remaining characters are digits
            digits = field.data[1:]
            if not digits.isdigit():
                raise ValidationError(_('Phone number must contain only digits after the + symbol'))
            
            if len(digits) < 7 or len(digits) > 15:
                raise ValidationError(_('Phone number must have 7-15 digits after country code'))
    
    def validate_backup_phone(self, field):
        """Validate backup phone number format."""
        if field.data:
            # Use same validation as primary phone
            self.validate_phone_number(field)


class MFAChallengeForm(MFABaseForm):
    """Form for MFA challenge verification."""
    
    method = SelectField(
        _('Verification Method'),
        validators=[DataRequired()],
        description=_('Choose your preferred verification method')
    )
    
    verification_code = StringField(
        _('Verification Code'),
        validators=[
            DataRequired(message=_('Verification code is required')),
            Length(min=6, max=8, message=_('Verification code must be 6-8 characters'))
        ],
        description=_('Enter the verification code from your chosen method'),
        render_kw={
            'placeholder': '123456',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': r'\d{6,8}',
            'maxlength': '8',
            'class': 'form-control text-center',
            'style': 'font-size: 1.5rem; letter-spacing: 0.5rem;'
        }
    )
    
    def validate_verification_code(self, field):
        """Validate verification code format."""
        if field.data:
            # Allow both numeric codes and backup codes
            if not field.data.isdigit():
                # Check if it looks like a backup code (8 digits)
                if len(field.data) != 8 or not field.data.isdigit():
                    raise ValidationError(_('Verification code must be 6-8 digits'))


class MFABackupCodesForm(MFABaseForm):
    """Form for backup codes management."""
    
    confirmation = BooleanField(
        _('I understand'),
        validators=[DataRequired(message=_('You must confirm understanding'))],
        description=_('I understand that these backup codes should be stored securely and each can only be used once')
    )


class MFAView(BaseView):
    """
    Main MFA challenge and verification interface.
    
    Provides endpoints for MFA challenge initiation, code verification,
    method selection, and status checking with responsive UI and AJAX support.
    """
    
    route_base = '/mfa'
    default_view = 'challenge'
    
    def __init__(self):
        """Initialize MFA view with services."""
        super().__init__()
        self.orchestration_service = MFAOrchestrationService()
        
    @expose('/challenge', methods=['GET', 'POST'])
    @login_required
    def challenge(self):
        """
        MFA challenge interface for code verification.
        
        Handles both challenge initiation and code verification with
        support for multiple MFA methods and real-time validation.
        
        Returns:
            Rendered template or JSON response for AJAX requests
        """
        # Check if user is authenticated
        if not current_user.is_authenticated:
            flash(_('Please log in to continue'), 'warning')
            return redirect(url_for('AuthView.login'))
        
        # Get security manager
        sm = current_app.appbuilder.sm
        
        # Check if MFA is required for this user
        if not hasattr(sm, 'is_mfa_required') or not sm.is_mfa_required(current_user):
            flash(_('MFA is not required for your account'), 'info')
            return redirect(url_for('AuthView.login'))
        
        # Check if already verified
        if MFASessionState.is_verified_and_valid():
            flash(_('MFA already verified for this session'), 'success')
            return redirect(url_for('AuthView.login'))
        
        # Check if session is locked
        if MFASessionState.is_locked():
            return render_template(
                'mfa/locked.html',
                title=_('Account Temporarily Locked'),
                message=_('Too many failed attempts. Please try again later.')
            )
        
        # Get available MFA methods
        available_methods = sm.get_user_mfa_methods(current_user)
        if not available_methods:
            # Redirect to setup if no methods configured
            return redirect(url_for('MFASetupView.setup'))
        
        # Handle form submission
        form = MFAChallengeForm()
        form.method.choices = [(method, self._get_method_display_name(method)) 
                              for method in available_methods]
        
        if request.method == 'POST':
            if request.is_json or request.headers.get('Content-Type') == 'application/json':
                return self._handle_ajax_verification(form, available_methods)
            else:
                return self._handle_form_verification(form, available_methods)
        
        # GET request - show challenge form
        current_method = MFASessionState.get_state()
        if current_method == MFASessionState.CHALLENGED:
            # Get the method from session
            challenge_method = session.get(MFASessionState.MFA_CHALLENGE_METHOD_KEY)
            if challenge_method:
                form.method.data = challenge_method
        
        return render_template(
            'mfa/challenge.html',
            form=form,
            available_methods=available_methods,
            current_method=current_method,
            title=_('Multi-Factor Authentication')
        )
    
    @expose('/initiate', methods=['POST'])
    @login_required
    @has_access
    def initiate(self):
        """
        AJAX endpoint for initiating MFA challenges.
        
        Handles challenge initiation for SMS and Email methods,
        returning JSON status for real-time UI updates.
        
        Returns:
            JSON response with challenge status
        """
        try:
            data = request.get_json()
            method = data.get('method')
            
            if not method:
                return jsonify({'success': False, 'message': _('Method is required')})
            
            # Get security manager
            sm = current_app.appbuilder.sm
            auth_handler = MFAAuthenticationHandler(sm)
            
            # Initiate challenge
            result = auth_handler.initiate_mfa_challenge(current_user, method)
            
            return jsonify({
                'success': True,
                'method': result['method'],
                'challenge_sent': result.get('challenge_sent', False),
                'message': result.get('message', _('Challenge initiated'))
            })
            
        except MFAValidationError as e:
            log.warning(f"MFA challenge initiation failed: {str(e)}")
            return jsonify({'success': False, 'message': str(e)})
        except Exception as e:
            log.error(f"MFA challenge initiation error: {str(e)}")
            return jsonify({'success': False, 'message': _('Service temporarily unavailable')})
    
    @expose('/verify', methods=['POST'])
    @login_required
    def verify(self):
        """
        AJAX endpoint for MFA code verification.
        
        Handles code verification with real-time feedback and
        automatic redirection on successful verification.
        
        Returns:
            JSON response with verification status
        """
        try:
            data = request.get_json()
            method = data.get('method')
            code = data.get('code')
            
            if not method or not code:
                return jsonify({
                    'success': False, 
                    'message': _('Method and verification code are required')
                })
            
            # Get security manager
            sm = current_app.appbuilder.sm
            auth_handler = MFAAuthenticationHandler(sm)
            
            # Verify code
            result = auth_handler.verify_mfa_response(current_user, method, code)
            
            if result['success']:
                # Successful verification
                return jsonify({
                    'success': True,
                    'message': result.get('message', _('Verification successful')),
                    'redirect': url_for('AuthView.login')
                })
            else:
                # Failed verification
                response_data = {
                    'success': False,
                    'message': result.get('message', _('Verification failed'))
                }
                
                if result.get('locked'):
                    response_data['locked'] = True
                    response_data['redirect'] = url_for('MFAView.challenge')
                elif 'attempts_remaining' in result:
                    response_data['attempts_remaining'] = result['attempts_remaining']
                
                return jsonify(response_data)
            
        except Exception as e:
            log.error(f"MFA verification error: {str(e)}")
            return jsonify({
                'success': False, 
                'message': _('Verification failed due to system error')
            })
    
    @expose('/status')
    @login_required
    def status(self):
        """
        AJAX endpoint for MFA status checking.
        
        Returns current MFA session state for UI updates
        and progressive enhancement.
        
        Returns:
            JSON response with current MFA status
        """
        try:
            state = MFASessionState.get_state()
            user_id = MFASessionState.get_user_id()
            
            status_info = {
                'state': state,
                'user_id': user_id,
                'is_verified': MFASessionState.is_verified_and_valid(),
                'is_locked': MFASessionState.is_locked()
            }
            
            if state == MFASessionState.CHALLENGED:
                challenge_method = session.get(MFASessionState.MFA_CHALLENGE_METHOD_KEY)
                status_info['challenge_method'] = challenge_method
            
            return jsonify({'success': True, 'status': status_info})
            
        except Exception as e:
            log.error(f"MFA status check error: {str(e)}")
            return jsonify({'success': False, 'message': _('Status check failed')})
    
    def _handle_ajax_verification(self, form, available_methods):
        """Handle AJAX form verification."""
        if form.validate_on_submit():
            method = form.method.data
            code = form.verification_code.data
            
            if method not in available_methods:
                return jsonify({
                    'success': False, 
                    'message': _('Invalid verification method')
                })
            
            # Use verify endpoint logic
            return self.verify()
        else:
            # Return form validation errors
            errors = {}
            for field, field_errors in form.errors.items():
                errors[field] = field_errors
            
            return jsonify({
                'success': False,
                'message': _('Form validation failed'),
                'errors': errors
            })
    
    def _handle_form_verification(self, form, available_methods):
        """Handle regular form submission verification."""
        if form.validate_on_submit():
            method = form.method.data
            code = form.verification_code.data
            
            if method not in available_methods:
                flash(_('Invalid verification method'), 'error')
                return render_template('mfa/challenge.html', form=form, available_methods=available_methods)
            
            try:
                # Get security manager and verify
                sm = current_app.appbuilder.sm
                auth_handler = MFAAuthenticationHandler(sm)
                result = auth_handler.verify_mfa_response(current_user, method, code)
                
                if result['success']:
                    flash(result.get('message', _('MFA verification successful')), 'success')
                    return redirect(url_for('AuthView.login'))
                else:
                    if result.get('locked'):
                        return redirect(url_for('MFAView.challenge'))
                    
                    message = result.get('message', _('Verification failed'))
                    if 'attempts_remaining' in result:
                        message += f" ({result['attempts_remaining']} {_('attempts remaining')})"
                    
                    flash(message, 'error')
                    
            except Exception as e:
                log.error(f"MFA verification error: {str(e)}")
                flash(_('Verification failed due to system error'), 'error')
        
        return render_template(
            'mfa/challenge.html', 
            form=form, 
            available_methods=available_methods,
            title=_('Multi-Factor Authentication')
        )
    
    def _get_method_display_name(self, method):
        """Get user-friendly display name for MFA method."""
        method_names = {
            'totp': _('Authenticator App'),
            'sms': _('SMS Text Message'),
            'email': _('Email Code'),
            'backup': _('Backup Code')
        }
        return method_names.get(method, method.title())


class MFASetupView(BaseView):
    """
    MFA setup wizard and configuration interface.
    
    Provides a progressive setup wizard for configuring MFA including
    TOTP setup with QR codes, contact information, and backup codes.
    """
    
    route_base = '/mfa/setup'
    default_view = 'setup'
    
    def __init__(self):
        """Initialize MFA setup view with services."""
        super().__init__()
        self.orchestration_service = MFAOrchestrationService()
    
    @expose('/', methods=['GET', 'POST'])
    @login_required
    def setup(self):
        """
        Main MFA setup wizard interface.
        
        Handles the complete MFA setup flow including method selection,
        contact information, TOTP configuration, and backup codes.
        
        Returns:
            Rendered template with setup wizard
        """
        # Check if user already has MFA configured
        sm = current_app.appbuilder.sm
        user_mfa = sm.get_user_mfa(current_user.id)
        
        if user_mfa and user_mfa.setup_completed:
            flash(_('MFA is already configured for your account'), 'info')
            return redirect(url_for('MFAManagementView.index'))
        
        form = MFASetupForm()
        
        if form.validate_on_submit():
            try:
                # Begin MFA setup
                setup_info = self.orchestration_service.initiate_mfa_setup(current_user)
                
                # Store setup information in session for wizard
                session['_mfa_setup_info'] = {
                    'user_mfa_id': setup_info['user_mfa_id'],
                    'totp_secret': setup_info['totp_secret'],
                    'qr_code': setup_info['qr_code'],
                    'setup_token': setup_info['setup_token'],
                    'allowed_methods': setup_info['allowed_methods']
                }
                
                # Update user MFA with contact information
                if user_mfa is None:
                    from pgappforge import db
                    user_mfa = db.session.query(UserMFA).get(setup_info['user_mfa_id'])
                
                if form.phone_number.data:
                    user_mfa.phone_number = form.phone_number.data
                if form.backup_phone.data:
                    user_mfa.backup_phone = form.backup_phone.data
                if form.recovery_email.data:
                    user_mfa.recovery_email = form.recovery_email.data
                
                user_mfa.preferred_method = form.preferred_method.data
                
                from pgappforge import db
                db.session.commit()
                
                flash(_('MFA setup initiated. Please complete verification.'), 'info')
                return redirect(url_for('MFASetupView.verify'))
                
            except Exception as e:
                log.error(f"MFA setup initiation error: {str(e)}")
                flash(_('Setup failed. Please try again.'), 'error')
        
        return render_template(
            'mfa/setup.html',
            form=form,
            title=_('Set Up Multi-Factor Authentication')
        )
    
    @expose('/verify', methods=['GET', 'POST'])
    @login_required
    def verify(self):
        """
        TOTP verification step of setup wizard.
        
        Displays QR code and handles TOTP verification to complete
        the MFA setup process.
        
        Returns:
            Rendered template with verification interface
        """
        # Get setup info from session
        setup_info = session.get('_mfa_setup_info')
        if not setup_info:
            flash(_('Setup session expired. Please start again.'), 'warning')
            return redirect(url_for('MFASetupView.setup'))
        
        if request.method == 'POST':
            verification_code = request.form.get('verification_code', '').strip()
            
            if not verification_code:
                flash(_('Verification code is required'), 'error')
            elif len(verification_code) != 6 or not verification_code.isdigit():
                flash(_('Verification code must be 6 digits'), 'error')
            else:
                try:
                    # Complete MFA setup
                    result = self.orchestration_service.complete_mfa_setup(
                        current_user,
                        verification_code,
                        setup_info['setup_token']
                    )
                    
                    if result['setup_completed']:
                        # Store backup codes for display
                        session['_mfa_backup_codes'] = result['backup_codes']
                        
                        # Clear setup info
                        session.pop('_mfa_setup_info', None)
                        
                        flash(_('MFA setup completed successfully!'), 'success')
                        return redirect(url_for('MFASetupView.backup_codes'))
                    
                except MFAValidationError as e:
                    flash(str(e), 'error')
                except Exception as e:
                    log.error(f"MFA setup completion error: {str(e)}")
                    flash(_('Setup verification failed. Please try again.'), 'error')
        
        return render_template(
            'mfa/setup_verify.html',
            setup_info=setup_info,
            title=_('Verify Authenticator Setup')
        )
    
    @expose('/backup-codes')
    @login_required
    def backup_codes(self):
        """
        Display backup codes after successful setup.
        
        Shows generated backup codes with instructions for secure storage
        and usage guidelines.
        
        Returns:
            Rendered template with backup codes
        """
        backup_codes = session.get('_mfa_backup_codes')
        if not backup_codes:
            flash(_('No backup codes available'), 'warning')
            return redirect(url_for('MFAManagementView.index'))
        
        form = MFABackupCodesForm()
        
        if form.validate_on_submit():
            # Clear backup codes from session after confirmation
            session.pop('_mfa_backup_codes', None)
            flash(_('MFA setup is now complete. You can now access protected resources.'), 'success')
            return redirect(url_for('AuthView.login'))
        
        return render_template(
            'mfa/backup_codes.html',
            backup_codes=backup_codes,
            form=form,
            title=_('Your MFA Backup Codes')
        )
    
    @expose('/qr-code')
    @login_required
    def qr_code(self):
        """
        AJAX endpoint for QR code generation.
        
        Generates and returns QR code image data for TOTP setup
        with proper caching headers.
        
        Returns:
            JSON response with QR code data
        """
        setup_info = session.get('_mfa_setup_info')
        if not setup_info:
            return jsonify({'success': False, 'message': _('Setup session expired')})
        
        return jsonify({
            'success': True,
            'qr_code': setup_info['qr_code'],
            'secret': setup_info['totp_secret']
        })


class MFAManagementView(BaseView):
    """
    User MFA settings management interface.
    
    Provides interface for users to manage their MFA settings including
    method preferences, contact information updates, and backup code regeneration.
    """
    
    route_base = '/mfa/manage'
    default_view = 'index'
    
    @expose('/')
    @login_required
    def index(self):
        """
        Main MFA management dashboard.
        
        Displays current MFA configuration, available methods,
        and management options for the authenticated user.
        
        Returns:
            Rendered template with MFA settings
        """
        # Get user MFA configuration
        sm = current_app.appbuilder.sm
        user_mfa = sm.get_user_mfa(current_user.id)
        
        if not user_mfa or not user_mfa.setup_completed:
            flash(_('MFA is not set up for your account'), 'info')
            return redirect(url_for('MFASetupView.setup'))
        
        # Get available methods
        available_methods = sm.get_user_mfa_methods(current_user)
        
        # Get backup codes count
        from .services import BackupCodeService
        backup_service = BackupCodeService()
        remaining_backup_codes = backup_service.get_remaining_codes_count(user_mfa.id)
        
        return render_template(
            'mfa/manage.html',
            user_mfa=user_mfa,
            available_methods=available_methods,
            remaining_backup_codes=remaining_backup_codes,
            title=_('Manage Multi-Factor Authentication')
        )
    
    @expose('/regenerate-backup-codes', methods=['POST'])
    @login_required
    def regenerate_backup_codes(self):
        """
        Regenerate backup codes for the user.
        
        Generates new backup codes, invalidating any existing unused codes,
        and displays them for secure storage.
        
        Returns:
            Rendered template with new backup codes
        """
        sm = current_app.appbuilder.sm
        user_mfa = sm.get_user_mfa(current_user.id)
        
        if not user_mfa or not user_mfa.setup_completed:
            flash(_('MFA must be set up before generating backup codes'), 'warning')
            return redirect(url_for('MFASetupView.setup'))
        
        try:
            from .services import BackupCodeService
            backup_service = BackupCodeService()
            new_codes = backup_service.generate_codes_for_user(user_mfa.id, count=8)
            
            flash(_('New backup codes generated. Previous codes are no longer valid.'), 'info')
            
            return render_template(
                'mfa/backup_codes.html',
                backup_codes=new_codes,
                regenerated=True,
                title=_('New MFA Backup Codes')
            )
            
        except Exception as e:
            log.error(f"Backup codes regeneration error: {str(e)}")
            flash(_('Failed to generate new backup codes'), 'error')
            return redirect(url_for('MFAManagementView.index'))
    
    @expose('/disable', methods=['GET', 'POST'])
    @login_required
    def disable(self):
        """
        Disable MFA for the user account.
        
        Provides interface for users to disable MFA with proper warnings
        and confirmation steps.
        
        Returns:
            Rendered template with disable confirmation
        """
        sm = current_app.appbuilder.sm
        user_mfa = sm.get_user_mfa(current_user.id)
        
        if not user_mfa or not user_mfa.is_enabled:
            flash(_('MFA is not currently enabled'), 'info')
            return redirect(url_for('MFAManagementView.index'))
        
        # Check if MFA is required by policy
        if hasattr(sm, 'is_mfa_required') and sm.is_mfa_required(current_user):
            flash(_('MFA cannot be disabled due to organizational policy'), 'error')
            return redirect(url_for('MFAManagementView.index'))
        
        if request.method == 'POST':
            confirmation = request.form.get('confirm_disable')
            if confirmation == 'DISABLE':
                try:
                    # Disable MFA
                    user_mfa.is_enabled = False
                    user_mfa.setup_completed = False
                    
                    # Clear sensitive data
                    user_mfa.totp_secret = None
                    user_mfa.phone_number = None
                    user_mfa.backup_phone = None
                    user_mfa.recovery_email = None
                    
                    from pgappforge import db
                    db.session.commit()
                    
                    # Clear MFA session state
                    MFASessionState.clear()
                    
                    flash(_('MFA has been disabled for your account'), 'success')
                    return redirect(url_for('AuthView.login'))
                    
                except Exception as e:
                    log.error(f"MFA disable error: {str(e)}")
                    flash(_('Failed to disable MFA'), 'error')
            else:
                flash(_('Please type DISABLE to confirm'), 'error')
        
        return render_template(
            'mfa/disable.html',
            title=_('Disable Multi-Factor Authentication')
        )


class PasskeyRegistrationForm(MFABaseForm):
    """Form for passkey registration."""
    
    credential_name = StringField(
        _('Passkey Name'),
        validators=[
            DataRequired(message=_('Passkey name is required')),
            Length(min=1, max=64, message=_('Passkey name must be 1-64 characters'))
        ],
        description=_('Give your passkey a memorable name (e.g., "My iPhone", "Work Laptop")'),
        render_kw={
            'placeholder': _('My Device'),
            'maxlength': '64'
        }
    )


class PasskeyAuthenticationForm(MFABaseForm):
    """Form for passkey authentication."""
    
    # This form is primarily for CSRF protection as actual authentication is handled via WebAuthn JS API
    pass


class PasskeyView(BaseView):
    """
    WebAuthn/FIDO2 Passkey Management Interface.
    
    Provides complete passkey lifecycle management including registration,
    authentication, credential management, and WebAuthn protocol handling.
    
    Features:
        - WebAuthn credential registration with platform/roaming authenticator support
        - Passwordless authentication flows
        - Multi-credential management per user
        - Credential naming and organization
        - Security key and biometric authentication
        - Cross-platform compatibility (Windows Hello, Touch ID, etc.)
    """
    
    route_base = '/mfa/passkeys'
    default_view = 'index'
    
    def __init__(self):
        """Initialize passkey view with WebAuthn service."""
        super().__init__()
        self.webauthn_service = WebAuthnService()
    
    @expose('/')
    @login_required
    def index(self):
        """
        Main passkey management dashboard.
        
        Displays user's registered passkeys with management options
        including registration, renaming, and revocation.
        
        Returns:
            Rendered template with passkey dashboard
        """
        try:
            # Get user's passkey credentials
            credentials = self.webauthn_service.get_user_credentials(current_user.id)
            
            return render_template(
                'mfa/passkeys/index.html',
                credentials=credentials,
                title=_('Manage Passkeys')
            )
            
        except Exception as e:
            log.error(f"Passkey dashboard error: {str(e)}")
            flash(_('Unable to load passkey information'), 'error')
            return redirect(url_for('MFAManagementView.index'))
    
    @expose('/register', methods=['GET', 'POST'])
    @login_required
    def register(self):
        """
        Passkey registration interface.
        
        Handles WebAuthn credential creation flow including options generation,
        credential verification, and storage with proper error handling.
        
        Returns:
            Rendered template with registration interface
        """
        form = PasskeyRegistrationForm()
        
        if request.method == 'POST' and form.validate_on_submit():
            # This is handled via AJAX, but provide fallback
            flash(_('Please use a compatible browser for passkey registration'), 'warning')
        
        return render_template(
            'mfa/passkeys/register.html',
            form=form,
            title=_('Register New Passkey')
        )
    
    @expose('/register/options', methods=['POST'])
    @login_required
    def register_options(self):
        """
        Generate WebAuthn registration options.
        
        Creates WebAuthn credential creation options for the authenticated user
        with proper challenge generation and exclusion of existing credentials.
        
        Returns:
            JSON response with WebAuthn registration options
        """
        try:
            # Generate registration options
            options = self.webauthn_service.generate_registration_options(
                current_user, 
                exclude_existing=True
            )
            
            return jsonify({
                'success': True,
                'options': options
            })
            
        except Exception as e:
            log.error(f"Passkey registration options error: {str(e)}")
            return jsonify({
                'success': False,
                'message': _('Failed to generate registration options')
            }), 400
    
    @expose('/register/verify', methods=['POST'])
    @login_required
    def register_verify(self):
        """
        Verify WebAuthn registration response.
        
        Processes the WebAuthn credential creation response, verifies the attestation,
        and stores the new credential in the database.
        
        Returns:
            JSON response with verification result
        """
        try:
            data = request.get_json()
            
            credential_response = data.get('credential')
            challenge_id = data.get('challenge_id')
            credential_name = data.get('credential_name', _('New Passkey'))
            
            if not credential_response or not challenge_id:
                return jsonify({
                    'success': False,
                    'message': _('Missing required registration data')
                }), 400
            
            # Verify registration
            result = self.webauthn_service.verify_registration_response(
                current_user,
                credential_response,
                challenge_id,
                credential_name
            )
            
            if result['registration_verified']:
                return jsonify({
                    'success': True,
                    'message': _('Passkey registered successfully'),
                    'credential': {
                        'id': result['credential_id'],
                        'name': result['credential_name'],
                        'transports': result['transports']
                    }
                })
            else:
                return jsonify({
                    'success': False,
                    'message': _('Passkey registration failed')
                }), 400
            
        except Exception as e:
            log.error(f"Passkey registration verification error: {str(e)}")
            return jsonify({
                'success': False,
                'message': _('Registration verification failed')
            }), 500
    
    @expose('/authenticate', methods=['GET', 'POST'])
    def authenticate(self):
        """
        Passkey authentication interface.
        
        Provides WebAuthn authentication flow for passwordless login
        with support for both usernameless and username-first flows.
        
        Returns:
            Rendered template with authentication interface
        """
        form = PasskeyAuthenticationForm()
        
        return render_template(
            'mfa/passkeys/authenticate.html',
            form=form,
            title=_('Passkey Authentication')
        )
    
    @expose('/authenticate/options', methods=['POST'])
    def authenticate_options(self):
        """
        Generate WebAuthn authentication options.
        
        Creates WebAuthn credential request options for authentication
        with support for both user-specific and usernameless flows.
        
        Returns:
            JSON response with WebAuthn authentication options
        """
        try:
            data = request.get_json() or {}
            user_id = data.get('user_id')
            
            # For authenticated users or user-specific authentication
            if current_user.is_authenticated:
                user_id = current_user.id
            
            # Generate authentication options
            options = self.webauthn_service.generate_authentication_options(user_id)
            
            return jsonify({
                'success': True,
                'options': options
            })
            
        except Exception as e:
            log.error(f"Passkey authentication options error: {str(e)}")
            return jsonify({
                'success': False,
                'message': _('Failed to generate authentication options')
            }), 400
    
    @expose('/authenticate/verify', methods=['POST'])
    def authenticate_verify(self):
        """
        Verify WebAuthn authentication response.
        
        Processes the WebAuthn authentication assertion, verifies the signature,
        and establishes authenticated session on successful verification.
        
        Returns:
            JSON response with authentication result
        """
        try:
            data = request.get_json()
            
            credential_response = data.get('credential')
            challenge_id = data.get('challenge_id')
            
            if not credential_response or not challenge_id:
                return jsonify({
                    'success': False,
                    'message': _('Missing required authentication data')
                }), 400
            
            # Get client IP for audit
            ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
            
            # Verify authentication
            result = self.webauthn_service.verify_authentication_response(
                credential_response,
                challenge_id,
                ip_address
            )
            
            if result['authentication_verified']:
                # For MFA flow, mark as verified
                if current_user.is_authenticated:
                    MFASessionState.mark_verified(current_user.id, 'webauthn')
                    
                    return jsonify({
                        'success': True,
                        'message': _('Passkey authentication successful'),
                        'redirect': url_for('AuthView.login')
                    })
                else:
                    # For passwordless login, establish session
                    # This would integrate with PgAppForge's login flow
                    return jsonify({
                        'success': True,
                        'message': _('Authentication successful'),
                        'user_id': result['user_id'],
                        'username': result['username'],
                        'credential_name': result['credential_name']
                        # Note: Actual login integration would happen here
                    })
            else:
                return jsonify({
                    'success': False,
                    'message': _('Passkey authentication failed')
                }), 400
            
        except Exception as e:
            log.error(f"Passkey authentication verification error: {str(e)}")
            return jsonify({
                'success': False,
                'message': _('Authentication verification failed')
            }), 500
    
    @expose('/revoke/<credential_id>', methods=['POST'])
    @login_required
    def revoke(self, credential_id):
        """
        Revoke a passkey credential.
        
        Deactivates the specified passkey credential, preventing future use
        while maintaining audit trail of the revocation.
        
        Args:
            credential_id: ID of the credential to revoke
            
        Returns:
            JSON response with revocation result
        """
        try:
            success = self.webauthn_service.revoke_credential(
                current_user.id,
                credential_id
            )
            
            if success:
                return jsonify({
                    'success': True,
                    'message': _('Passkey revoked successfully')
                })
            else:
                return jsonify({
                    'success': False,
                    'message': _('Passkey not found or already revoked')
                }), 404
            
        except Exception as e:
            log.error(f"Passkey revocation error: {str(e)}")
            return jsonify({
                'success': False,
                'message': _('Failed to revoke passkey')
            }), 500
    
    @expose('/rename/<credential_id>', methods=['POST'])
    @login_required
    def rename(self, credential_id):
        """
        Rename a passkey credential.
        
        Updates the display name of the specified passkey credential
        for better user organization and identification.
        
        Args:
            credential_id: ID of the credential to rename
            
        Returns:
            JSON response with rename result
        """
        try:
            data = request.get_json()
            new_name = data.get('name', '').strip()
            
            if not new_name or len(new_name) > 64:
                return jsonify({
                    'success': False,
                    'message': _('Name must be 1-64 characters')
                }), 400
            
            success = self.webauthn_service.rename_credential(
                current_user.id,
                credential_id,
                new_name
            )
            
            if success:
                return jsonify({
                    'success': True,
                    'message': _('Passkey renamed successfully'),
                    'new_name': new_name
                })
            else:
                return jsonify({
                    'success': False,
                    'message': _('Passkey not found')
                }), 404
            
        except Exception as e:
            log.error(f"Passkey rename error: {str(e)}")
            return jsonify({
                'success': False,
                'message': _('Failed to rename passkey')
            }), 500


__all__ = [
    'MFAView',
    'MFASetupView', 
    'MFAManagementView',
    'PasskeyView',
    'MFABaseForm',
    'MFASetupForm',
    'MFAChallengeForm',
    'MFABackupCodesForm',
    'PasskeyRegistrationForm',
    'PasskeyAuthenticationForm'
]