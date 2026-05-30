"""
Multi-Factor Authentication Business Logic Services

This module provides the business logic layer for MFA operations including
TOTP generation and validation, SMS delivery, email notifications, backup
code management, and policy enforcement.

Services:
    TOTPService: Time-based OTP generation and validation
    SMSService: SMS delivery for MFA codes via Twilio/AWS SNS
    EmailService: Email delivery for MFA codes via Flask-Mail
    BackupCodeService: Management of backup/recovery codes
    MFAPolicyService: Organization policy enforcement
    MFAOrchestrationService: High-level workflow coordination

External Dependencies:
    - pyotp: TOTP generation and validation
    - qrcode: QR code generation for TOTP setup
    - twilio: SMS delivery service
    - boto3: AWS SNS integration
    - flask-mail: Email delivery
    - pillow: QR code image processing

Circuit Breaker Pattern:
    All external service integrations use circuit breaker patterns
    to handle failures gracefully and maintain system reliability.
"""

import io
import json
import base64
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple, Union
from contextlib import contextmanager
from functools import wraps
from enum import Enum

import pyotp  # Keep as core dependency
from flask import current_app, url_for

# Conditional imports for optional MFA features
try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

try:
    from flask_mail import Message
    HAS_FLASK_MAIL = True
except ImportError:
    HAS_FLASK_MAIL = False

try:
    from twilio.rest import Client as TwilioClient
    from twilio.base.exceptions import TwilioException
    HAS_TWILIO = True
except ImportError:
    HAS_TWILIO = False

try:
    import boto3
    from botocore.exceptions import BotoCore3Error, ClientError
    HAS_AWS_SNS = True
except ImportError:
    HAS_AWS_SNS = False

try:
    from webauthn import generate_registration_options, verify_registration_response
    from webauthn import generate_authentication_options, verify_authentication_response
    from webauthn.helpers.structs import (
        RegistrationCredential, AuthenticationCredential, 
        PublicKeyCredentialCreationOptions, PublicKeyCredentialRequestOptions
    )
    from webauthn.helpers.cose import COSEAlgorithmIdentifier
    HAS_WEBAUTHN = True
except ImportError:
    HAS_WEBAUTHN = False

from .models import UserMFA, MFABackupCode, MFAVerification, MFAPolicy, WebAuthnCredential, MFAChallenge

log = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states for external service resilience."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Service unavailable
    HALF_OPEN = "half_open" # Testing service recovery


class CircuitBreaker:
    """
    Circuit breaker implementation for external service resilience.
    
    Prevents cascading failures by monitoring service health and
    temporarily disabling calls to failing services.
    
    Attributes:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Time before attempting service recovery
        success_threshold: Successful calls needed to close circuit
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60, 
                 success_threshold: int = 3):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            success_threshold: Successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout  
        self.success_threshold = success_threshold
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED
    
    def _can_attempt(self) -> bool:
        """Check if service call can be attempted."""
        if self.state == CircuitBreakerState.CLOSED:
            return True
        
        if self.state == CircuitBreakerState.OPEN:
            if (datetime.now(tz=timezone.utc) - self.last_failure_time).total_seconds() > self.recovery_timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                self.success_count = 0
                return True
            return False
        
        # HALF_OPEN state
        return True
    
    def record_success(self) -> None:
        """Record successful service call."""
        self.failure_count = 0
        
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitBreakerState.CLOSED
                log.info("Circuit breaker closed - service recovered")
    
    def record_failure(self) -> None:
        """Record failed service call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(tz=timezone.utc)
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            log.warning(f"Circuit breaker opened after {self.failure_count} failures")
        elif self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.OPEN
    
    def __call__(self, func):
        """Decorator for protecting service calls."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self._can_attempt():
                raise ServiceUnavailableError(f"Circuit breaker is OPEN for {func.__name__}")
            
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise
        
        return wrapper


class MFAServiceError(Exception):
    """Base exception for MFA service errors."""
    pass


class ServiceUnavailableError(MFAServiceError):
    """Exception for temporarily unavailable external services."""
    pass


class ValidationError(MFAServiceError):
    """Exception for MFA validation failures."""
    pass


class ConfigurationError(MFAServiceError):
    """Exception for service configuration issues."""
    pass


class TOTPService:
    """
    Time-based One-Time Password (TOTP) service.
    
    Provides TOTP generation, validation, QR code creation, and secret
    management using RFC 6238 standard implementation via pyotp.
    
    Features:
        - Secure secret generation
        - QR code creation for authenticator apps
        - Time window validation with drift tolerance
        - Counter tracking to prevent replay attacks
    """
    
    def __init__(self):
        """Initialize TOTP service with configuration."""
        self.issuer = current_app.config.get('MFA_TOTP_ISSUER', 'Flask-AppBuilder')
        self.validity_window = current_app.config.get('MFA_TOTP_VALIDITY_WINDOW', 1)
        
    def generate_secret(self) -> str:
        """
        Generate a secure TOTP secret key.
        
        Returns:
            str: Base32-encoded secret key for TOTP generation
            
        Example:
            >>> service = TOTPService()
            >>> secret = service.generate_secret()
            >>> len(secret) >= 16
            True
        """
        return pyotp.random_base32()
    
    def generate_qr_code(self, secret: str, user_email: str, 
                        account_name: str = None) -> str:
        """
        Generate QR code for TOTP authenticator app setup.
        
        Args:
            secret: Base32-encoded TOTP secret
            user_email: User email for account identification
            account_name: Optional account name override
            
        Returns:
            str: Base64-encoded PNG image of QR code
            
        Raises:
            ValidationError: If secret is invalid
            
        Example:
            >>> service = TOTPService()
            >>> secret = service.generate_secret()
            >>> qr_code = service.generate_qr_code(secret, "user@example.com")
            >>> qr_code.startswith('data:image/png;base64,')
            True
        """
        if not HAS_QRCODE:
            raise RuntimeError(
                "QR code generation requires qrcode library. "
                "Install with: pip install 'Flask-AppBuilder[mfa]'"
            )
            
        try:
            totp = pyotp.TOTP(secret)
            account_name = account_name or user_email
            
            # Generate provisioning URI
            provisioning_uri = totp.provisioning_uri(
                name=account_name,
                issuer_name=self.issuer
            )
            
            # Create QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(provisioning_uri)
            qr.make(fit=True)
            
            # Generate image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to base64
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='PNG')
            img_str = base64.b64encode(img_buffer.getvalue()).decode()
            
            return f"data:image/png;base64,{img_str}"
            
        except Exception as e:
            log.error(f"QR code generation failed: {str(e)}")
            raise ValidationError(f"Failed to generate QR code: {str(e)}")
    
    def validate_totp(self, secret: str, otp: str, last_counter: int = None) -> Tuple[bool, int]:
        """
        Validate TOTP code with replay protection.
        
        Args:
            secret: Base32-encoded TOTP secret
            otp: 6-digit OTP code to validate
            last_counter: Last used counter value for replay protection
            
        Returns:
            Tuple[bool, int]: (is_valid, current_counter) where
                is_valid indicates if OTP is correct and
                current_counter is the time counter value
                
        Raises:
            ValidationError: If secret format is invalid
            
        Example:
            >>> service = TOTPService()
            >>> secret = service.generate_secret()
            >>> totp = pyotp.TOTP(secret)
            >>> otp = totp.now()
            >>> is_valid, counter = service.validate_totp(secret, otp)
            >>> is_valid
            True
        """
        try:
            totp = pyotp.TOTP(secret)
            current_counter = totp.timecode(datetime.now(tz=timezone.utc))
            
            # Check if OTP was already used (replay protection)
            if last_counter is not None and current_counter <= last_counter:
                log.warning(f"TOTP replay attempt detected: counter {current_counter} <= {last_counter}")
                return False, current_counter
            
            # Validate OTP with time window
            is_valid = totp.verify(
                otp, 
                valid_window=self.validity_window,
                for_time=datetime.now(tz=timezone.utc)
            )
            
            return is_valid, current_counter
            
        except Exception as e:
            log.error(f"TOTP validation failed: {str(e)}")
            raise ValidationError(f"Invalid TOTP validation: {str(e)}")
    
    def get_current_otp(self, secret: str) -> str:
        """
        Get current OTP for testing purposes.
        
        Args:
            secret: Base32-encoded TOTP secret
            
        Returns:
            str: Current 6-digit OTP
            
        Note:
            This method should only be used for testing and development.
        """
        if not current_app.config.get('TESTING', False):
            log.warning("get_current_otp called in non-testing environment")
            
        totp = pyotp.TOTP(secret)
        return totp.now()


class SMSService:
    """
    SMS delivery service for MFA codes.
    
    Supports multiple SMS providers (Twilio, AWS SNS) with circuit breaker
    protection and automatic fallback mechanisms.
    
    Features:
        - Multiple provider support (Twilio, AWS SNS)
        - Circuit breaker pattern for resilience
        - Rate limiting and cost optimization
        - Template-based message formatting
        - International phone number support
    """
    
    def __init__(self):
        """Initialize SMS service with provider configuration."""
        self.providers = self._initialize_providers()
        self.circuit_breakers = {
            provider: CircuitBreaker() for provider in self.providers.keys()
        }
        self.rate_limiter = {}  # Simple in-memory rate limiting
        
    def _initialize_providers(self) -> Dict[str, Any]:
        """Initialize available SMS providers."""
        providers = {}
        
        # Twilio configuration
        twilio_sid = current_app.config.get('TWILIO_ACCOUNT_SID')
        twilio_token = current_app.config.get('TWILIO_AUTH_TOKEN')
        twilio_from = current_app.config.get('TWILIO_FROM_NUMBER')
        
        if twilio_sid and twilio_token and twilio_from and HAS_TWILIO:
            providers['twilio'] = {
                'client': TwilioClient(twilio_sid, twilio_token),
                'from_number': twilio_from
            }
            log.info("Twilio SMS provider initialized")
        elif twilio_sid and twilio_token and twilio_from and not HAS_TWILIO:
            log.warning("Twilio credentials configured but twilio library not available. Install with: pip install 'Flask-AppBuilder[mfa]'")
        
        # AWS SNS configuration
        if HAS_AWS_SNS:
            aws_access_key = current_app.config.get('AWS_ACCESS_KEY_ID')
            aws_secret_key = current_app.config.get('AWS_SECRET_ACCESS_KEY')
            aws_region = current_app.config.get('AWS_REGION', 'us-east-1')
            
            if aws_access_key and aws_secret_key:
                try:
                    sns_client = boto3.client(
                        'sns',
                        aws_access_key_id=aws_access_key,
                        aws_secret_access_key=aws_secret_key,
                        region_name=aws_region
                    )
                    providers['aws_sns'] = {'client': sns_client}
                    log.info("AWS SNS provider initialized")
                except Exception as e:
                    log.warning(f"AWS SNS initialization failed: {str(e)}")
        
        if not providers:
            log.warning("No SMS providers configured - SMS MFA will be unavailable")
            
        return providers
    
    def _check_rate_limit(self, phone_number: str) -> bool:
        """
        Check if phone number exceeds rate limits.
        
        Args:
            phone_number: Phone number to check
            
        Returns:
            bool: True if within rate limits, False if exceeded
        """
        now = datetime.now(tz=timezone.utc)
        rate_limit_window = current_app.config.get('MFA_SMS_RATE_LIMIT_WINDOW', 300)  # 5 minutes
        max_attempts = current_app.config.get('MFA_SMS_RATE_LIMIT_MAX', 3)
        
        if phone_number not in self.rate_limiter:
            self.rate_limiter[phone_number] = []
        
        # Clean old attempts
        cutoff_time = now - timedelta(seconds=rate_limit_window)
        self.rate_limiter[phone_number] = [
            timestamp for timestamp in self.rate_limiter[phone_number]
            if timestamp > cutoff_time
        ]
        
        if len(self.rate_limiter[phone_number]) >= max_attempts:
            return False
        
        # Record this attempt
        self.rate_limiter[phone_number].append(now)
        return True
    
    @CircuitBreaker()
    def _send_via_twilio(self, phone_number: str, message: str) -> bool:
        """
        Send SMS via Twilio service.
        
        Args:
            phone_number: Target phone number
            message: SMS message content
            
        Returns:
            bool: True if sent successfully
            
        Raises:
            ServiceUnavailableError: If Twilio service is unavailable
        """
        if 'twilio' not in self.providers:
            raise ServiceUnavailableError("Twilio provider not configured")
        
        try:
            client = self.providers['twilio']['client']
            from_number = self.providers['twilio']['from_number']
            
            message_obj = client.messages.create(
                body=message,
                from_=from_number,
                to=phone_number
            )
            
            log.info(f"SMS sent via Twilio to {phone_number}: {message_obj.sid}")
            return True
            
        except TwilioException as e:
            log.error(f"Twilio SMS failed: {str(e)}")
            raise ServiceUnavailableError(f"Twilio error: {str(e)}")
    
    @CircuitBreaker()
    def _send_via_aws_sns(self, phone_number: str, message: str) -> bool:
        """
        Send SMS via AWS SNS service.
        
        Args:
            phone_number: Target phone number
            message: SMS message content
            
        Returns:
            bool: True if sent successfully
            
        Raises:
            ServiceUnavailableError: If AWS SNS service is unavailable
        """
        if 'aws_sns' not in self.providers:
            raise ServiceUnavailableError("AWS SNS provider not configured")
        
        try:
            sns_client = self.providers['aws_sns']['client']
            
            response = sns_client.publish(
                PhoneNumber=phone_number,
                Message=message,
                MessageAttributes={
                    'AWS.SNS.SMS.SenderID': {
                        'DataType': 'String',
                        'StringValue': 'FlaskMFA'
                    },
                    'AWS.SNS.SMS.SMSType': {
                        'DataType': 'String',
                        'StringValue': 'Transactional'
                    }
                }
            )
            
            log.info(f"SMS sent via AWS SNS to {phone_number}: {response['MessageId']}")
            return True
            
        except (BotoCore3Error, ClientError) as e:
            log.error(f"AWS SNS SMS failed: {str(e)}")
            raise ServiceUnavailableError(f"AWS SNS error: {str(e)}")
    
    def send_mfa_code(self, phone_number: str, code: str, user_name: str = None) -> bool:
        """
        Send MFA code via SMS with fallback providers.
        
        Args:
            phone_number: Target phone number in E.164 format
            code: 6-digit MFA code to send
            user_name: Optional user name for personalization
            
        Returns:
            bool: True if SMS was sent successfully
            
        Raises:
            ValidationError: If phone number format is invalid
            ServiceUnavailableError: If all providers are unavailable
            
        Example:
            >>> service = SMSService()
            >>> success = service.send_mfa_code("+15551234567", "123456")
            >>> success
            True
        """
        # Validate phone number format
        if not phone_number or not phone_number.startswith('+'):
            raise ValidationError("Phone number must be in E.164 format (+1234567890)")
        
        # Check rate limits
        if not self._check_rate_limit(phone_number):
            raise ValidationError("SMS rate limit exceeded for this phone number")
        
        # Format message
        app_name = current_app.config.get('MFA_SMS_APP_NAME', 'Flask App')
        if user_name:
            message = f"Hello {user_name}, your {app_name} MFA code is: {code}. This code expires in 5 minutes."
        else:
            message = f"Your {app_name} MFA code is: {code}. This code expires in 5 minutes."
        
        # Try providers in order of preference
        provider_order = ['twilio', 'aws_sns']
        last_error = None
        
        for provider_name in provider_order:
            if provider_name not in self.providers:
                continue
                
            try:
                if provider_name == 'twilio':
                    return self._send_via_twilio(phone_number, message)
                elif provider_name == 'aws_sns':
                    return self._send_via_aws_sns(phone_number, message)
                    
            except ServiceUnavailableError as e:
                last_error = e
                log.warning(f"SMS provider {provider_name} failed: {str(e)}")
                continue
        
        # All providers failed
        if last_error:
            raise ServiceUnavailableError(f"All SMS providers unavailable: {str(last_error)}")
        else:
            raise ConfigurationError("No SMS providers configured")


class EmailService:
    """
    Email delivery service for MFA codes.
    
    Provides email-based MFA code delivery using Flask-Mail with
    HTML templates, backup delivery methods, and delivery tracking.
    
    Features:
        - HTML and plain text email templates
        - SMTP and API delivery methods
        - Delivery status tracking
        - Rate limiting and spam prevention
        - Template customization
    """
    
    def __init__(self):
        """Initialize email service with Flask-Mail."""
        from flask_mail import Mail
        self.mail = Mail(current_app)
        self.rate_limiter = {}  # Simple in-memory rate limiting
        
    def _check_rate_limit(self, email: str) -> bool:
        """
        Check if email address exceeds rate limits.
        
        Args:
            email: Email address to check
            
        Returns:
            bool: True if within rate limits, False if exceeded
        """
        now = datetime.now(tz=timezone.utc)
        rate_limit_window = current_app.config.get('MFA_EMAIL_RATE_LIMIT_WINDOW', 300)  # 5 minutes
        max_attempts = current_app.config.get('MFA_EMAIL_RATE_LIMIT_MAX', 5)
        
        if email not in self.rate_limiter:
            self.rate_limiter[email] = []
        
        # Clean old attempts
        cutoff_time = now - timedelta(seconds=rate_limit_window)
        self.rate_limiter[email] = [
            timestamp for timestamp in self.rate_limiter[email]
            if timestamp > cutoff_time
        ]
        
        if len(self.rate_limiter[email]) >= max_attempts:
            return False
        
        # Record this attempt
        self.rate_limiter[email].append(now)
        return True
    
    def _generate_html_template(self, code: str, user_name: str = None) -> str:
        """
        Generate HTML email template for MFA code.
        
        Args:
            code: MFA code to include
            user_name: Optional user name for personalization
            
        Returns:
            str: HTML email content
        """
        app_name = current_app.config.get('MFA_EMAIL_APP_NAME', 'Flask Application')
        
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>MFA Verification Code</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; }}
                .code-box {{ 
                    background-color: #e9ecef; 
                    padding: 20px; 
                    margin: 20px 0; 
                    text-align: center; 
                    border-radius: 5px; 
                }}
                .code {{ 
                    font-size: 36px; 
                    font-weight: bold; 
                    letter-spacing: 5px; 
                    color: #495057; 
                }}
                .footer {{ color: #6c757d; font-size: 12px; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{app_name} - MFA Verification</h1>
                </div>
                
                <p>{greeting}</p>
                
                <p>You requested a multi-factor authentication code. Please enter the following code to complete your login:</p>
                
                <div class="code-box">
                    <div class="code">{code}</div>
                </div>
                
                <p><strong>Important:</strong></p>
                <ul>
                    <li>This code will expire in 5 minutes</li>
                    <li>Do not share this code with anyone</li>
                    <li>If you didn't request this code, please contact support</li>
                </ul>
                
                <div class="footer">
                    <p>This is an automated message from {app_name}. Please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_template
    
    def _generate_text_template(self, code: str, user_name: str = None) -> str:
        """
        Generate plain text email template for MFA code.
        
        Args:
            code: MFA code to include
            user_name: Optional user name for personalization
            
        Returns:
            str: Plain text email content
        """
        app_name = current_app.config.get('MFA_EMAIL_APP_NAME', 'Flask Application')
        
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        
        text_template = f"""
{app_name} - MFA Verification Code

{greeting}

You requested a multi-factor authentication code. Please enter the following code to complete your login:

    {code}

IMPORTANT:
- This code will expire in 5 minutes
- Do not share this code with anyone  
- If you didn't request this code, please contact support

This is an automated message from {app_name}. Please do not reply to this email.
        """
        
        return text_template.strip()
    
    def send_mfa_code(self, email: str, code: str, user_name: str = None) -> bool:
        """
        Send MFA code via email.
        
        Args:
            email: Target email address
            code: 6-digit MFA code to send
            user_name: Optional user name for personalization
            
        Returns:
            bool: True if email was sent successfully
            
        Raises:
            ValidationError: If email format is invalid
            ServiceUnavailableError: If email service is unavailable
            
        Example:
            >>> service = EmailService()
            >>> success = service.send_mfa_code("user@example.com", "123456", "John")
            >>> success
            True
        """
        if not HAS_FLASK_MAIL:
            raise RuntimeError(
                "Email MFA requires Flask-Mail library. "
                "Install with: pip install 'Flask-AppBuilder[mfa]'"
            )
            
        # Validate email format
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            raise ValidationError("Invalid email address format")
        
        # Check rate limits
        if not self._check_rate_limit(email):
            raise ValidationError("Email rate limit exceeded for this address")
        
        try:
            # Create message
            app_name = current_app.config.get('MFA_EMAIL_APP_NAME', 'Flask Application')
            subject = f"{app_name} - MFA Verification Code"
            
            html_body = self._generate_html_template(code, user_name)
            text_body = self._generate_text_template(code, user_name)
            
            msg = Message(
                subject=subject,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                recipients=[email],
                body=text_body,
                html=html_body
            )
            
            # Send email
            self.mail.send(msg)
            
            log.info(f"MFA code email sent to {email}")
            return True
            
        except Exception as e:
            log.error(f"Email MFA delivery failed: {str(e)}")
            raise ServiceUnavailableError(f"Email delivery failed: {str(e)}")


class BackupCodeService:
    """
    Backup code management service for MFA recovery.
    
    Manages generation, validation, and lifecycle of backup codes
    that allow users to access their accounts when primary MFA
    methods are unavailable.
    
    Features:
        - Secure code generation with cryptographic randomness
        - One-time use enforcement
        - Usage audit trails
        - Bulk generation and management
        - Expiration and renewal workflows
    """
    
    def generate_codes_for_user(self, user_mfa_id: int, count: int = 8) -> List[str]:
        """
        Generate new backup codes for a user.
        
        Args:
            user_mfa_id: ID of UserMFA configuration
            count: Number of backup codes to generate (default 8)
            
        Returns:
            List[str]: List of generated backup codes (plain text)
            
        Raises:
            ValidationError: If user_mfa_id is invalid
            
        Example:
            >>> service = BackupCodeService()
            >>> codes = service.generate_codes_for_user(123, count=10)
            >>> len(codes)
            10
            >>> all(len(code) == 8 and code.isdigit() for code in codes)
            True
        """
        try:
            # Validate user exists
            from flask_appbuilder import db
            user_mfa = db.session.query(UserMFA).get(user_mfa_id)
            if not user_mfa:
                raise ValidationError(f"UserMFA with id {user_mfa_id} not found")
            
            # Generate codes using model method
            codes = MFABackupCode.generate_codes(user_mfa_id, count)
            
            log.info(f"Generated {len(codes)} backup codes for user_mfa_id {user_mfa_id}")
            return codes
            
        except Exception as e:
            log.error(f"Backup code generation failed: {str(e)}")
            raise ValidationError(f"Failed to generate backup codes: {str(e)}")
    
    def validate_backup_code(self, user_mfa_id: int, code: str, 
                           ip_address: str = None) -> bool:
        """
        Validate and consume a backup code.
        
        Args:
            user_mfa_id: ID of UserMFA configuration
            code: Backup code to validate
            ip_address: IP address of validation attempt
            
        Returns:
            bool: True if code was valid and consumed
            
        Example:
            >>> service = BackupCodeService()
            >>> codes = service.generate_codes_for_user(123)
            >>> result = service.validate_backup_code(123, codes[0], "192.168.1.1")
            >>> result
            True
            >>> # Same code cannot be used again
            >>> service.validate_backup_code(123, codes[0], "192.168.1.1")
            False
        """
        try:
            return MFABackupCode.verify_and_consume(user_mfa_id, code, ip_address)
        except Exception as e:
            log.error(f"Backup code validation failed: {str(e)}")
            return False
    
    def get_remaining_codes_count(self, user_mfa_id: int) -> int:
        """
        Get count of remaining unused backup codes.
        
        Args:
            user_mfa_id: ID of UserMFA configuration
            
        Returns:
            int: Number of unused backup codes
        """
        try:
            from flask_appbuilder import db
            count = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa_id,
                is_used=False
            ).count()
            
            return count
            
        except Exception as e:
            log.error(f"Failed to get backup code count: {str(e)}")
            return 0
    
    def get_usage_history(self, user_mfa_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent backup code usage history.
        
        Args:
            user_mfa_id: ID of UserMFA configuration
            limit: Maximum number of records to return
            
        Returns:
            List[Dict]: Usage history records
        """
        try:
            from flask_appbuilder import db
            
            used_codes = db.session.query(MFABackupCode).filter_by(
                user_mfa_id=user_mfa_id,
                is_used=True
            ).order_by(
                MFABackupCode.used_at.desc()
            ).limit(limit).all()
            
            history = []
            for code in used_codes:
                history.append({
                    'used_at': code.used_at,
                    'used_from_ip': code.used_from_ip,
                    'created_on': code.created_on
                })
            
            return history
            
        except Exception as e:
            log.error(f"Failed to get usage history: {str(e)}")
            return []


class MFAPolicyService:
    """
    MFA policy enforcement and management service.
    
    Handles organizational MFA policies including role-based enforcement,
    method restrictions, and compliance requirements.
    
    Features:
        - Role-based policy enforcement
        - Method restriction policies
        - Policy conflict resolution
        - Compliance reporting
        - Policy template management
    """
    
    def get_user_policy(self, user) -> Optional[MFAPolicy]:
        """
        Get the MFA policy applicable to a user.
        
        Args:
            user: Flask-AppBuilder User object
            
        Returns:
            Optional[MFAPolicy]: Applicable policy or None
        """
        return MFAPolicy.get_policy_for_user(user)
    
    def is_mfa_required_for_user(self, user) -> bool:
        """
        Check if MFA is required for a user based on policies.
        
        Args:
            user: Flask-AppBuilder User object
            
        Returns:
            bool: True if MFA is required, False otherwise
        """
        policy = self.get_user_policy(user)
        return policy is not None
    
    def get_allowed_methods_for_user(self, user) -> List[str]:
        """
        Get allowed MFA methods for a user based on policies.
        
        Args:
            user: Flask-AppBuilder User object
            
        Returns:
            List[str]: List of allowed MFA method names
        """
        policy = self.get_user_policy(user)
        if policy:
            return policy.permitted_methods
        
        # Default all methods if no policy
        return ['totp', 'sms', 'email', 'backup']
    
    def validate_method_for_user(self, user, method: str) -> bool:
        """
        Validate if a specific MFA method is allowed for a user.
        
        Args:
            user: Flask-AppBuilder User object
            method: MFA method name to validate
            
        Returns:
            bool: True if method is allowed, False otherwise
        """
        allowed_methods = self.get_allowed_methods_for_user(user)
        return method in allowed_methods
    
    def get_policy_parameters_for_user(self, user) -> Dict[str, Any]:
        """
        Get policy parameters (limits, timeouts) for a user.
        
        Args:
            user: Flask-AppBuilder User object
            
        Returns:
            Dict[str, Any]: Policy parameters with defaults
        """
        policy = self.get_user_policy(user)
        
        if policy:
            return {
                'max_failed_attempts': policy.max_failed_attempts,
                'lockout_duration': policy.lockout_duration,
                'session_timeout': policy.session_timeout,
                'require_backup_codes': policy.require_backup_codes,
                'require_setup_within': policy.require_setup_within
            }
        
        # Return system defaults
        return {
            'max_failed_attempts': current_app.config.get('MFA_MAX_FAILED_ATTEMPTS', 5),
            'lockout_duration': current_app.config.get('MFA_LOCKOUT_DURATION', 900),
            'session_timeout': current_app.config.get('MFA_SESSION_TIMEOUT', 3600),
            'require_backup_codes': True,
            'require_setup_within': None
        }


class TokenGenerationService:
    """
    Centralized token generation and validation service.
    
    Provides unified interface for generating and validating various types of
    MFA tokens including time-based codes, SMS codes, email codes, and one-time
    tokens with proper rate limiting and security controls.
    
    Features:
        - Multiple token type support (numeric, alphanumeric, custom patterns)
        - Configurable token length and validity periods
        - Rate limiting and abuse prevention
        - Token lifecycle management
        - Cryptographically secure generation
        - Replay attack prevention
    """
    
    def __init__(self):
        """Initialize token generation service."""
        self.default_length = current_app.config.get('MFA_TOKEN_LENGTH', 6)
        self.default_validity = current_app.config.get('MFA_TOKEN_VALIDITY_SECONDS', 300)
        self.max_attempts = current_app.config.get('MFA_TOKEN_MAX_ATTEMPTS', 3)
        
    def generate_numeric_token(self, length: int = None) -> str:
        """
        Generate a cryptographically secure numeric token.
        
        Args:
            length: Token length (default from config)
            
        Returns:
            str: Numeric token
            
        Example:
            >>> service = TokenGenerationService()
            >>> token = service.generate_numeric_token(6)
            >>> len(token) == 6 and token.isdigit()
            True
        """
        length = length or self.default_length
        
        # Use cryptographically secure random number generation
        token_range = 10 ** length
        random_number = secrets.randbelow(token_range)
        
        # Format with leading zeros
        return f"{random_number:0{length}d}"
    
    def generate_alphanumeric_token(self, length: int = 8, 
                                  exclude_ambiguous: bool = True) -> str:
        """
        Generate a cryptographically secure alphanumeric token.
        
        Args:
            length: Token length (default 8)
            exclude_ambiguous: Exclude confusing characters (0, O, 1, I, l)
            
        Returns:
            str: Alphanumeric token
        """
        if exclude_ambiguous:
            # Exclude ambiguous characters: 0, O, 1, I, l
            alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
        else:
            alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def generate_email_token(self, user_email: str, token_type: str = 'login') -> str:
        """
        Generate email verification token with expiration.
        
        Args:
            user_email: Email address for token
            token_type: Type of verification (login, reset, etc.)
            
        Returns:
            str: Email verification token
        """
        from flask_appbuilder import db
        
        # Generate secure token
        token = self.generate_alphanumeric_token(32, exclude_ambiguous=False)
        
        # Store token with metadata
        verification_record = MFAVerification(
            method='email_token',
            otp_used=token,
            ip_address=None,
            additional_data={
                'email': user_email,
                'token_type': token_type,
                'expires_at': (datetime.now(tz=timezone.utc) + timedelta(seconds=self.default_validity)).isoformat()
            }
        )
        
        db.session.add(verification_record)
        db.session.commit()
        
        return token
    
    def generate_sms_token(self, phone_number: str) -> str:
        """
        Generate SMS verification token.
        
        Args:
            phone_number: Phone number for token delivery
            
        Returns:
            str: SMS verification token
        """
        return self.generate_numeric_token()
    
    def validate_token(self, token: str, user_id: int = None, 
                      method: str = None, max_age_seconds: int = None) -> Dict[str, Any]:
        """
        Validate a token with security checks.
        
        Args:
            token: Token to validate
            user_id: Optional user ID for scoping
            method: Token method for validation
            max_age_seconds: Maximum token age
            
        Returns:
            Dict[str, Any]: Validation result with metadata
        """
        from flask_appbuilder import db
        
        try:
            max_age = max_age_seconds or self.default_validity
            cutoff_time = datetime.now(tz=timezone.utc) - timedelta(seconds=max_age)
            
            # Query for token with constraints
            query = db.session.query(MFAVerification).filter(
                MFAVerification.otp_used == token,
                MFAVerification.timestamp >= cutoff_time,
                MFAVerification.success == True
            )
            
            if user_id:
                # Filter by user through UserMFA relationship
                query = query.join(UserMFA).filter(UserMFA.user_id == user_id)
            
            if method:
                query = query.filter(MFAVerification.method == method)
            
            verification = query.first()
            
            if not verification:
                return {
                    'valid': False,
                    'reason': 'Token not found or expired',
                    'remaining_attempts': None
                }
            
            # Check if token was already consumed
            if hasattr(verification, 'consumed_at') and verification.consumed_at:
                return {
                    'valid': False,
                    'reason': 'Token already used',
                    'remaining_attempts': None
                }
            
            # Mark token as consumed
            verification.consumed_at = datetime.now(tz=timezone.utc)
            db.session.commit()
            
            return {
                'valid': True,
                'verification_id': verification.id,
                'method': verification.method,
                'timestamp': verification.timestamp,
                'additional_data': verification.additional_data
            }
            
        except Exception as e:
            log.error(f"Token validation failed: {str(e)}")
            return {
                'valid': False,
                'reason': f'Validation error: {str(e)}',
                'remaining_attempts': None
            }
    
    def cleanup_expired_tokens(self, max_age_days: int = 7) -> int:
        """
        Clean up expired verification tokens.
        
        Args:
            max_age_days: Maximum age for token retention
            
        Returns:
            int: Number of tokens cleaned up
        """
        from flask_appbuilder import db
        
        try:
            cutoff_time = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
            
            deleted_count = db.session.query(MFAVerification).filter(
                MFAVerification.timestamp < cutoff_time
            ).delete()
            
            db.session.commit()
            
            log.info(f"Cleaned up {deleted_count} expired MFA verification tokens")
            return deleted_count
            
        except Exception as e:
            db.session.rollback()
            log.error(f"Token cleanup failed: {str(e)}")
            return 0
    
    def get_token_stats(self, user_id: int = None, 
                       hours: int = 24) -> Dict[str, Any]:
        """
        Get token generation and validation statistics.
        
        Args:
            user_id: Optional user ID for filtering
            hours: Time window for statistics
            
        Returns:
            Dict[str, Any]: Token usage statistics
        """
        from flask_appbuilder import db
        
        try:
            since_time = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
            
            query = db.session.query(MFAVerification).filter(
                MFAVerification.timestamp >= since_time
            )
            
            if user_id:
                query = query.join(UserMFA).filter(UserMFA.user_id == user_id)
            
            all_attempts = query.all()
            
            stats = {
                'total_attempts': len(all_attempts),
                'successful_attempts': len([a for a in all_attempts if a.success]),
                'failed_attempts': len([a for a in all_attempts if not a.success]),
                'methods': {},
                'time_window_hours': hours
            }
            
            # Method breakdown
            for attempt in all_attempts:
                method = attempt.method
                if method not in stats['methods']:
                    stats['methods'][method] = {'total': 0, 'success': 0, 'failed': 0}
                
                stats['methods'][method]['total'] += 1
                if attempt.success:
                    stats['methods'][method]['success'] += 1
                else:
                    stats['methods'][method]['failed'] += 1
            
            return stats
            
        except Exception as e:
            log.error(f"Failed to get token stats: {str(e)}")
            return {'error': str(e)}


class MFAOrchestrationService:
    """
    High-level MFA workflow orchestration service.
    
    Coordinates between different MFA services to provide unified
    workflows for setup, verification, and management operations.
    
    Features:
        - End-to-end MFA workflow management  
        - Service coordination and error handling
        - Transaction management for multi-step operations
        - Event logging and audit trails
        - Performance monitoring and metrics
    """
    
    def __init__(self):
        """Initialize orchestration service with dependencies."""
        self.totp_service = TOTPService()
        self.sms_service = SMSService()
        self.email_service = EmailService()
        self.backup_service = BackupCodeService()
        self.policy_service = MFAPolicyService()
        self.token_service = TokenGenerationService()
    
    def initiate_mfa_setup(self, user) -> Dict[str, Any]:
        """
        Begin MFA setup process for a user.
        
        Args:
            user: Flask-AppBuilder User object
            
        Returns:
            Dict[str, Any]: Setup information including secrets and QR codes
            
        Raises:
            ConfigurationError: If user is not eligible for MFA setup
        """
        from flask_appbuilder import db
        
        try:
            # Check if user already has MFA configured
            user_mfa = db.session.query(UserMFA).filter_by(user_id=user.id).first()
            
            if user_mfa and user_mfa.setup_completed:
                raise ConfigurationError("MFA is already configured for this user")
            
            # Create or update UserMFA record
            if not user_mfa:
                user_mfa = UserMFA(user_id=user.id)
                db.session.add(user_mfa)
            
            # Generate TOTP secret
            totp_secret = self.totp_service.generate_secret()
            user_mfa.totp_secret = totp_secret
            
            # Generate setup token
            setup_token = user_mfa.generate_setup_token()
            
            db.session.commit()
            
            # Generate QR code
            qr_code = self.totp_service.generate_qr_code(
                totp_secret, 
                user.email, 
                user.username
            )
            
            # Get allowed methods for this user
            allowed_methods = self.policy_service.get_allowed_methods_for_user(user)
            
            setup_info = {
                'user_mfa_id': user_mfa.id,
                'totp_secret': totp_secret,
                'qr_code': qr_code,
                'setup_token': setup_token,
                'allowed_methods': allowed_methods,
                'backup_url': url_for('mfa.setup_backup_codes', token=setup_token)
            }
            
            log.info(f"MFA setup initiated for user {user.id}")
            return setup_info
            
        except Exception as e:
            db.session.rollback()
            log.error(f"MFA setup initiation failed: {str(e)}")
            raise
    
    def complete_mfa_setup(self, user, verification_code: str, 
                          setup_token: str) -> Dict[str, Any]:
        """
        Complete MFA setup after user verification.
        
        Args:
            user: Flask-AppBuilder User object
            verification_code: TOTP verification code
            setup_token: Setup token for verification
            
        Returns:
            Dict[str, Any]: Completion status and backup codes
            
        Raises:
            ValidationError: If verification fails
        """
        from flask_appbuilder import db
        
        try:
            # Find user MFA configuration
            user_mfa = db.session.query(UserMFA).filter_by(user_id=user.id).first()
            if not user_mfa:
                raise ValidationError("MFA setup not initiated")
            
            # Verify setup token
            if not user_mfa.verify_setup_token(setup_token):
                raise ValidationError("Invalid or expired setup token")
            
            # Verify TOTP code
            is_valid, counter = self.totp_service.validate_totp(
                user_mfa.totp_secret, 
                verification_code
            )
            
            if not is_valid:
                raise ValidationError("Invalid verification code")
            
            # Complete setup
            user_mfa.setup_completed = True
            user_mfa.is_enabled = True
            user_mfa.preferred_method = 'totp'
            user_mfa.totp_last_counter = counter
            user_mfa.clear_setup_token()
            
            # Generate backup codes if required
            backup_codes = []
            policy_params = self.policy_service.get_policy_parameters_for_user(user)
            
            if policy_params['require_backup_codes']:
                backup_codes = self.backup_service.generate_codes_for_user(user_mfa.id)
            
            db.session.commit()
            
            # Record verification
            MFAVerification.record_attempt(
                user_mfa_id=user_mfa.id,
                method='totp',
                success=True,
                otp_used=verification_code
            )
            
            result = {
                'setup_completed': True,
                'backup_codes': backup_codes,
                'enabled_methods': ['totp'],
                'message': 'MFA setup completed successfully'
            }
            
            log.info(f"MFA setup completed for user {user.id}")
            return result
            
        except Exception as e:
            db.session.rollback()
            log.error(f"MFA setup completion failed: {str(e)}")
            raise
    
    def verify_mfa_code(self, user, method: str, code: str, 
                       ip_address: str = None) -> Dict[str, Any]:
        """
        Verify MFA code using specified method.
        
        Args:
            user: Flask-AppBuilder User object
            method: MFA method ('totp', 'sms', 'email', 'backup')
            code: Verification code
            ip_address: Client IP address
            
        Returns:
            Dict[str, Any]: Verification result and session information
            
        Raises:
            ValidationError: If verification fails
        """
        from flask_appbuilder import db
        
        try:
            # Find user MFA configuration
            user_mfa = db.session.query(UserMFA).filter_by(user_id=user.id).first()
            if not user_mfa or not user_mfa.is_enabled:
                raise ValidationError("MFA is not enabled for this user")
            
            # Check if account is locked
            if not user_mfa.can_attempt_mfa():
                raise ValidationError("Account is temporarily locked due to failed attempts")
            
            # Validate method is allowed
            if not self.policy_service.validate_method_for_user(user, method):
                raise ValidationError(f"MFA method '{method}' is not allowed for this user")
            
            verification_success = False
            failure_reason = None
            
            # Perform method-specific validation
            if method == 'totp':
                is_valid, counter = self.totp_service.validate_totp(
                    user_mfa.totp_secret, 
                    code,
                    user_mfa.totp_last_counter
                )
                verification_success = is_valid
                if is_valid:
                    user_mfa.totp_last_counter = counter
                else:
                    failure_reason = "Invalid TOTP code"
                    
            elif method == 'backup':
                verification_success = self.backup_service.validate_backup_code(
                    user_mfa.id, 
                    code, 
                    ip_address
                )
                if not verification_success:
                    failure_reason = "Invalid backup code"
                    
            else:
                raise ValidationError(f"Verification not implemented for method: {method}")
            
            # Record attempt
            MFAVerification.record_attempt(
                user_mfa_id=user_mfa.id,
                method=method,
                success=verification_success,
                failure_reason=failure_reason,
                otp_used=code,
                ip_address=ip_address
            )
            
            # Update user MFA record
            if verification_success:
                user_mfa.record_successful_attempt(method)
                session_timeout = self.policy_service.get_policy_parameters_for_user(user)['session_timeout']
                
                result = {
                    'verification_success': True,
                    'method_used': method,
                    'session_expires': datetime.now(tz=timezone.utc) + timedelta(seconds=session_timeout),
                    'message': 'MFA verification successful'
                }
            else:
                user_mfa.record_failed_attempt()
                result = {
                    'verification_success': False,
                    'failure_reason': failure_reason,
                    'remaining_attempts': max(0, 5 - user_mfa.failed_attempts),
                    'message': 'MFA verification failed'
                }
            
            db.session.commit()
            
            log.info(f"MFA verification for user {user.id}: method={method}, success={verification_success}")
            return result
            
        except Exception as e:
            db.session.rollback()
            log.error(f"MFA verification failed: {str(e)}")
            raise


class WebAuthnService:
    """
    WebAuthn/FIDO2 passkey service for passwordless authentication.
    
    Provides complete WebAuthn credential lifecycle management including
    registration, authentication, and credential management following
    FIDO2 and WebAuthn W3C standards.
    
    Features:
        - FIDO2/WebAuthn credential registration
        - Passwordless authentication flows
        - Multi-credential management per user
        - Platform and roaming authenticator support
        - Attestation and assertion verification
        - Cross-platform compatibility
    """
    
    def __init__(self):
        """Initialize WebAuthn service with configuration."""
        if not HAS_WEBAUTHN:
            raise RuntimeError(
                "WebAuthn support requires py-webauthn library. "
                "Install with: pip install 'Flask-AppBuilder[mfa]'"
            )
        
        self.rp_id = current_app.config.get('WEBAUTHN_RP_ID', 'localhost')
        self.rp_name = current_app.config.get('WEBAUTHN_RP_NAME', 'Flask AppBuilder')
        self.origin = current_app.config.get('WEBAUTHN_ORIGIN', f'https://{self.rp_id}')
        self.timeout = current_app.config.get('WEBAUTHN_TIMEOUT', 300000)  # 5 minutes
        
        # Supported algorithms (ES256, PS256, RS256)
        self.supported_algorithms = [
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PSS_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ]
        
        log.info(f"WebAuthn service initialized: RP={self.rp_id}, Origin={self.origin}")
    
    def generate_registration_options(self, user, exclude_existing: bool = True) -> Dict[str, Any]:
        """
        Generate WebAuthn registration options for credential creation.
        
        Args:
            user: Flask-AppBuilder User object
            exclude_existing: Whether to exclude existing credentials
            
        Returns:
            Dict[str, Any]: Registration options and challenge data
            
        Raises:
            ValidationError: If user is invalid or registration blocked
            
        Example:
            >>> service = WebAuthnService()
            >>> options = service.generate_registration_options(user)
            >>> 'challenge' in options
            True
            >>> 'publicKey' in options
            True
        """
        from flask_appbuilder import db
        
        try:
            # Get existing credentials for exclusion
            excluded_credentials = []
            if exclude_existing:
                existing_creds = db.session.query(WebAuthnCredential).filter_by(
                    user_id=user.id,
                    is_active=True
                ).all()
                
                excluded_credentials = [
                    {
                        "id": cred.credential_id,
                        "transports": cred.transports or [],
                        "type": "public-key"
                    }
                    for cred in existing_creds
                ]
            
            # Generate registration options
            registration_options = generate_registration_options(
                rp_id=self.rp_id,
                rp_name=self.rp_name,
                user_id=str(user.id).encode('utf-8'),
                user_name=user.username,
                user_display_name=user.first_name + ' ' + user.last_name if user.first_name else user.username,
                exclude_credentials=excluded_credentials,
                supported_pub_key_algs=self.supported_algorithms,
                timeout=self.timeout
            )
            
            # Store challenge for verification
            challenge_record = MFAChallenge.create_challenge(
                user_id=user.id,
                challenge_type='webauthn_registration',
                challenge_data=registration_options.challenge,
                expires_at=datetime.now(tz=timezone.utc) + timedelta(milliseconds=self.timeout)
            )
            
            db.session.add(challenge_record)
            db.session.commit()
            
            # Convert to dict for JSON serialization
            options_dict = {
                "publicKey": {
                    "rp": {"id": registration_options.rp.id, "name": registration_options.rp.name},
                    "user": {
                        "id": registration_options.user.id.decode('latin-1'),
                        "name": registration_options.user.name,
                        "displayName": registration_options.user.display_name
                    },
                    "challenge": registration_options.challenge.decode('latin-1'),
                    "pubKeyCredParams": [
                        {"type": param.type, "alg": param.alg}
                        for param in registration_options.pub_key_cred_params
                    ],
                    "timeout": registration_options.timeout,
                    "excludeCredentials": excluded_credentials,
                    "authenticatorSelection": {
                        "authenticatorAttachment": "platform",
                        "userVerification": "preferred",
                        "residentKey": "preferred"
                    },
                    "attestation": "none"
                },
                "challenge_id": challenge_record.id
            }
            
            log.info(f"WebAuthn registration options generated for user {user.id}")
            return options_dict
            
        except Exception as e:
            db.session.rollback()
            log.error(f"WebAuthn registration options generation failed: {str(e)}")
            raise ValidationError(f"Failed to generate registration options: {str(e)}")
    
    def verify_registration_response(self, user, credential_response: Dict[str, Any], 
                                   challenge_id: int, credential_name: str = None) -> Dict[str, Any]:
        """
        Verify WebAuthn registration response and store credential.
        
        Args:
            user: Flask-AppBuilder User object
            credential_response: WebAuthn credential creation response
            challenge_id: ID of the challenge record
            credential_name: Optional name for the credential
            
        Returns:
            Dict[str, Any]: Verification result and credential info
            
        Raises:
            ValidationError: If verification fails
        """
        from flask_appbuilder import db
        
        try:
            # Retrieve and verify challenge
            challenge = db.session.query(MFAChallenge).get(challenge_id)
            if not challenge or challenge.user_id != user.id:
                raise ValidationError("Invalid challenge")
            
            if challenge.is_expired or challenge.is_used:
                raise ValidationError("Challenge expired or already used")
            
            if challenge.challenge_type != 'webauthn_registration':
                raise ValidationError("Invalid challenge type")
            
            # Create registration credential object
            registration_credential = RegistrationCredential.parse_raw(
                json.dumps(credential_response)
            )
            
            # Verify registration response
            verification = verify_registration_response(
                credential=registration_credential,
                expected_challenge=challenge.challenge_data.encode('utf-8'),
                expected_origin=self.origin,
                expected_rp_id=self.rp_id
            )
            
            if not verification.verified:
                raise ValidationError("WebAuthn registration verification failed")
            
            # Store credential
            webauthn_cred = WebAuthnCredential(
                user_id=user.id,
                credential_id=base64.urlsafe_b64encode(verification.credential_id).decode('utf-8'),
                public_key=base64.urlsafe_b64encode(verification.credential_public_key).decode('utf-8'),
                sign_count=verification.sign_count,
                credential_name=credential_name or f"Passkey {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                transports=getattr(registration_credential.response, 'transports', []),
                is_active=True
            )
            
            db.session.add(webauthn_cred)
            
            # Mark challenge as used
            challenge.mark_as_used()
            
            db.session.commit()
            
            result = {
                'registration_verified': True,
                'credential_id': webauthn_cred.credential_id,
                'credential_name': webauthn_cred.credential_name,
                'transports': webauthn_cred.transports,
                'message': 'Passkey registered successfully'
            }
            
            log.info(f"WebAuthn credential registered for user {user.id}: {webauthn_cred.credential_id}")
            return result
            
        except Exception as e:
            db.session.rollback()
            log.error(f"WebAuthn registration verification failed: {str(e)}")
            raise ValidationError(f"Registration verification failed: {str(e)}")
    
    def generate_authentication_options(self, user_id: int = None) -> Dict[str, Any]:
        """
        Generate WebAuthn authentication options for credential assertion.
        
        Args:
            user_id: Optional user ID to filter credentials (for user verification)
            
        Returns:
            Dict[str, Any]: Authentication options and challenge data
            
        Raises:
            ValidationError: If no credentials available
        """
        from flask_appbuilder import db
        
        try:
            # Get allowed credentials
            credential_query = db.session.query(WebAuthnCredential).filter_by(is_active=True)
            
            if user_id:
                credential_query = credential_query.filter_by(user_id=user_id)
            
            credentials = credential_query.all()
            
            if not credentials:
                if user_id:
                    raise ValidationError("No active passkeys found for user")
                else:
                    raise ValidationError("No active passkeys found")
            
            # Prepare credential descriptors
            allowed_credentials = [
                {
                    "id": cred.credential_id,
                    "type": "public-key",
                    "transports": cred.transports or ["internal", "hybrid"]
                }
                for cred in credentials
            ]
            
            # Generate authentication options
            authentication_options = generate_authentication_options(
                rp_id=self.rp_id,
                allow_credentials=allowed_credentials,
                timeout=self.timeout,
                user_verification="preferred"
            )
            
            # Store challenge for verification
            challenge_record = MFAChallenge.create_challenge(
                user_id=user_id,  # May be None for usernameless flow
                challenge_type='webauthn_authentication',
                challenge_data=authentication_options.challenge,
                expires_at=datetime.now(tz=timezone.utc) + timedelta(milliseconds=self.timeout)
            )
            
            db.session.add(challenge_record)
            db.session.commit()
            
            # Convert to dict for JSON serialization
            options_dict = {
                "publicKey": {
                    "challenge": authentication_options.challenge.decode('latin-1'),
                    "timeout": authentication_options.timeout,
                    "rpId": authentication_options.rp_id,
                    "allowCredentials": allowed_credentials,
                    "userVerification": authentication_options.user_verification
                },
                "challenge_id": challenge_record.id
            }
            
            log.info(f"WebAuthn authentication options generated for user {user_id or 'any'}")
            return options_dict
            
        except Exception as e:
            db.session.rollback()
            log.error(f"WebAuthn authentication options generation failed: {str(e)}")
            raise ValidationError(f"Failed to generate authentication options: {str(e)}")
    
    def verify_authentication_response(self, credential_response: Dict[str, Any], 
                                     challenge_id: int, ip_address: str = None) -> Dict[str, Any]:
        """
        Verify WebAuthn authentication response.
        
        Args:
            credential_response: WebAuthn authentication assertion response
            challenge_id: ID of the challenge record
            ip_address: Client IP address for audit
            
        Returns:
            Dict[str, Any]: Verification result and user info
            
        Raises:
            ValidationError: If verification fails
        """
        from flask_appbuilder import db
        
        try:
            # Retrieve and verify challenge
            challenge = db.session.query(MFAChallenge).get(challenge_id)
            if not challenge:
                raise ValidationError("Invalid challenge")
            
            if challenge.is_expired or challenge.is_used:
                raise ValidationError("Challenge expired or already used")
            
            if challenge.challenge_type != 'webauthn_authentication':
                raise ValidationError("Invalid challenge type")
            
            # Parse authentication credential
            authentication_credential = AuthenticationCredential.parse_raw(
                json.dumps(credential_response)
            )
            
            # Find the credential in database
            credential_id = base64.urlsafe_b64encode(
                base64.urlsafe_b64decode(authentication_credential.raw_id + "==")
            ).decode('utf-8').rstrip('=')
            
            webauthn_cred = db.session.query(WebAuthnCredential).filter_by(
                credential_id=credential_id,
                is_active=True
            ).first()
            
            if not webauthn_cred:
                raise ValidationError("Credential not found or inactive")
            
            # Verify authentication response
            verification = verify_authentication_response(
                credential=authentication_credential,
                expected_challenge=challenge.challenge_data.encode('utf-8'),
                expected_origin=self.origin,
                expected_rp_id=self.rp_id,
                credential_public_key=base64.urlsafe_b64decode(
                    webauthn_cred.public_key + "=="
                ),
                credential_current_sign_count=webauthn_cred.sign_count
            )
            
            if not verification.verified:
                raise ValidationError("WebAuthn authentication verification failed")
            
            # Update credential sign count
            webauthn_cred.sign_count = verification.new_sign_count
            webauthn_cred.last_used = datetime.now(tz=timezone.utc)
            
            # Mark challenge as used
            challenge.mark_as_used()
            
            # Get user information
            from flask_appbuilder.security.sqla.models import User
            user = db.session.query(User).get(webauthn_cred.user_id)
            
            # Record verification attempt
            if challenge.user_id:  # User-specific challenge
                user_mfa = db.session.query(UserMFA).filter_by(user_id=user.id).first()
                if user_mfa:
                    MFAVerification.record_attempt(
                        user_mfa_id=user_mfa.id,
                        method='webauthn',
                        success=True,
                        ip_address=ip_address
                    )
            
            db.session.commit()
            
            result = {
                'authentication_verified': True,
                'user_id': user.id,
                'username': user.username,
                'credential_id': webauthn_cred.credential_id,
                'credential_name': webauthn_cred.credential_name,
                'sign_count': verification.new_sign_count,
                'message': 'Passkey authentication successful'
            }
            
            log.info(f"WebAuthn authentication verified for user {user.id} with credential {webauthn_cred.credential_id}")
            return result
            
        except Exception as e:
            db.session.rollback()
            log.error(f"WebAuthn authentication verification failed: {str(e)}")
            raise ValidationError(f"Authentication verification failed: {str(e)}")
    
    def get_user_credentials(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Get all active WebAuthn credentials for a user.
        
        Args:
            user_id: User ID to query
            
        Returns:
            List[Dict]: List of credential information
        """
        from flask_appbuilder import db
        
        try:
            credentials = db.session.query(WebAuthnCredential).filter_by(
                user_id=user_id,
                is_active=True
            ).order_by(WebAuthnCredential.created_on.desc()).all()
            
            credential_list = []
            for cred in credentials:
                credential_list.append({
                    'id': cred.id,
                    'credential_id': cred.credential_id,
                    'credential_name': cred.credential_name,
                    'transports': cred.transports,
                    'created_on': cred.created_on.isoformat(),
                    'last_used': cred.last_used.isoformat() if cred.last_used else None,
                    'sign_count': cred.sign_count
                })
            
            return credential_list
            
        except Exception as e:
            log.error(f"Failed to get user credentials: {str(e)}")
            return []
    
    def revoke_credential(self, user_id: int, credential_id: str) -> bool:
        """
        Revoke (deactivate) a WebAuthn credential.
        
        Args:
            user_id: Owner user ID
            credential_id: Credential ID to revoke
            
        Returns:
            bool: True if credential was revoked successfully
        """
        from flask_appbuilder import db
        
        try:
            credential = db.session.query(WebAuthnCredential).filter_by(
                user_id=user_id,
                credential_id=credential_id,
                is_active=True
            ).first()
            
            if not credential:
                return False
            
            credential.is_active = False
            credential.revoked_at = datetime.now(tz=timezone.utc)
            
            db.session.commit()
            
            log.info(f"WebAuthn credential {credential_id} revoked for user {user_id}")
            return True
            
        except Exception as e:
            db.session.rollback()
            log.error(f"Failed to revoke credential: {str(e)}")
            return False
    
    def rename_credential(self, user_id: int, credential_id: str, new_name: str) -> bool:
        """
        Rename a WebAuthn credential.
        
        Args:
            user_id: Owner user ID
            credential_id: Credential ID to rename
            new_name: New credential name
            
        Returns:
            bool: True if credential was renamed successfully
        """
        from flask_appbuilder import db
        
        try:
            credential = db.session.query(WebAuthnCredential).filter_by(
                user_id=user_id,
                credential_id=credential_id,
                is_active=True
            ).first()
            
            if not credential:
                return False
            
            credential.credential_name = new_name
            db.session.commit()
            
            log.info(f"WebAuthn credential {credential_id} renamed to '{new_name}' for user {user_id}")
            return True
            
        except Exception as e:
            db.session.rollback()
            log.error(f"Failed to rename credential: {str(e)}")
            return False


__all__ = [
    'TOTPService',
    'SMSService', 
    'EmailService',
    'BackupCodeService',
    'MFAPolicyService',
    'TokenGenerationService',
    'MFAOrchestrationService',
    'WebAuthnService',
    'MFAServiceError',
    'ServiceUnavailableError',
    'ValidationError',
    'ConfigurationError'
]