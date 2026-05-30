"""
MFA Configuration Template for PgForge.

This module contains configuration settings and templates for Multi-Factor Authentication.
Copy these settings to your Flask application's config.py file and modify as needed.
"""

# MFA Configuration Settings
# ========================

# Enable/Disable MFA
FAB_MFA_ENABLED = True

# TOTP Configuration
# -----------------
FAB_MFA_TOTP_ISSUER = "PgForge"  # Name shown in authenticator apps
FAB_MFA_TOTP_WINDOW = 1  # Time window tolerance (±30 seconds per window)

# SMS Configuration (Twilio)
# -------------------------
FAB_MFA_SMS_PROVIDER = "twilio"  # Options: "twilio", "aws_sns"
FAB_TWILIO_ACCOUNT_SID = "your_twilio_account_sid"
FAB_TWILIO_AUTH_TOKEN = "your_twilio_auth_token" 
FAB_TWILIO_FROM_NUMBER = "+1234567890"  # Your Twilio phone number

# SMS Configuration (AWS SNS)
# --------------------------
# FAB_MFA_SMS_PROVIDER = "aws_sns"
# FAB_AWS_REGION = "us-east-1"
# AWS_ACCESS_KEY_ID = "your_aws_access_key"  # Or use IAM roles
# AWS_SECRET_ACCESS_KEY = "your_aws_secret_key"

# Email Configuration (Flask-Mail)
# -------------------------------
FAB_MFA_EMAIL_PROVIDER = "flask_mail"  # Options: "flask_mail", "sendgrid", "ses"
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = "your_email@gmail.com"
MAIL_PASSWORD = "your_app_password"
MAIL_DEFAULT_SENDER = "your_email@gmail.com"

# Email Configuration (SendGrid)
# -----------------------------
# FAB_MFA_EMAIL_PROVIDER = "sendgrid"
# FAB_SENDGRID_API_KEY = "your_sendgrid_api_key"
# FAB_SENDGRID_FROM_EMAIL = "noreply@yourdomain.com"

# Email Configuration (AWS SES)
# ----------------------------
# FAB_MFA_EMAIL_PROVIDER = "ses"
# FAB_AWS_SES_FROM_EMAIL = "noreply@yourdomain.com"
# FAB_AWS_REGION = "us-east-1"

# MFA Code Settings
# ---------------
FAB_MFA_SMS_CODE_EXPIRES = 300  # SMS code expiry in seconds (5 minutes)
FAB_MFA_EMAIL_CODE_EXPIRES = 600  # Email code expiry in seconds (10 minutes)
FAB_MFA_MAX_ATTEMPTS = 5  # Maximum verification attempts before lockout
FAB_MFA_LOCKOUT_DURATION = 30  # Lockout duration in minutes

# MFA Policy Settings
# -----------------
FAB_MFA_REQUIRE_BACKUP_CODES = True  # Require backup codes for MFA setup
FAB_MFA_BACKUP_CODE_COUNT = 10  # Number of backup codes to generate
FAB_MFA_GRACE_PERIOD_DAYS = 7  # Grace period before MFA enforcement
FAB_MFA_REMINDER_DAYS = 3  # Days before grace period ends to send reminders

# Security Settings
# ---------------
FAB_MFA_RATE_LIMIT_ENABLED = True  # Enable rate limiting for MFA endpoints
FAB_MFA_RATE_LIMIT_WINDOW = 300  # Rate limit window in seconds (5 minutes)
FAB_MFA_RATE_LIMIT_MAX_ATTEMPTS = 10  # Max attempts per window per IP

# Session Settings
# --------------
FAB_MFA_SESSION_TIMEOUT = 900  # MFA session timeout in seconds (15 minutes)
FAB_MFA_REMEMBER_DEVICE = False  # Allow "remember this device" option
FAB_MFA_REMEMBER_DEVICE_DAYS = 30  # Days to remember device

# Dependencies Installation Commands
# ================================
"""
To use MFA functionality, install the required dependencies:

# Basic MFA (TOTP only)
pip install pyotp qrcode[pil] Pillow

# SMS MFA with Twilio
pip install twilio

# SMS MFA with AWS SNS
pip install boto3

# Email MFA with SendGrid
pip install sendgrid

# Email MFA with Flask-Mail (usually already installed)
pip install Flask-Mail

# All MFA providers
pip install pyotp qrcode[pil] Pillow twilio boto3 sendgrid Flask-Mail
"""

# Sample Complete Configuration
# ===========================
SAMPLE_CONFIG = {
    # PgForge MFA Configuration
    'FAB_MFA_ENABLED': True,
    'FAB_MFA_TOTP_ISSUER': 'Your App Name',
    
    # Twilio SMS Configuration
    'FAB_MFA_SMS_PROVIDER': 'twilio',
    'FAB_TWILIO_ACCOUNT_SID': 'your_account_sid',
    'FAB_TWILIO_AUTH_TOKEN': 'your_auth_token',
    'FAB_TWILIO_FROM_NUMBER': '+1234567890',
    
    # Flask-Mail Configuration
    'FAB_MFA_EMAIL_PROVIDER': 'flask_mail',
    'MAIL_SERVER': 'smtp.gmail.com',
    'MAIL_PORT': 587,
    'MAIL_USE_TLS': True,
    'MAIL_USERNAME': 'your_email@gmail.com',
    'MAIL_PASSWORD': 'your_app_password',
    'MAIL_DEFAULT_SENDER': 'your_email@gmail.com',
    
    # MFA Settings
    'FAB_MFA_MAX_ATTEMPTS': 5,
    'FAB_MFA_LOCKOUT_DURATION': 30,
    'FAB_MFA_SMS_CODE_EXPIRES': 300,
    'FAB_MFA_EMAIL_CODE_EXPIRES': 600,
}


def get_mfa_config_template():
    """
    Get a template configuration dictionary for MFA.
    
    Returns:
        Dictionary with MFA configuration template
    """
    return {
        # Core MFA Settings
        'FAB_MFA_ENABLED': False,  # Set to True to enable MFA
        'FAB_MFA_TOTP_ISSUER': 'PgForge',
        
        # Provider Settings (configure based on your needs)
        'FAB_MFA_SMS_PROVIDER': 'twilio',  # or 'aws_sns'
        'FAB_MFA_EMAIL_PROVIDER': 'flask_mail',  # or 'sendgrid', 'ses'
        
        # Security Settings
        'FAB_MFA_MAX_ATTEMPTS': 5,
        'FAB_MFA_LOCKOUT_DURATION': 30,
        'FAB_MFA_SMS_CODE_EXPIRES': 300,
        'FAB_MFA_EMAIL_CODE_EXPIRES': 600,
        
        # Provider-specific settings (uncomment and configure as needed)
        # 'FAB_TWILIO_ACCOUNT_SID': 'your_twilio_account_sid',
        # 'FAB_TWILIO_AUTH_TOKEN': 'your_twilio_auth_token',
        # 'FAB_TWILIO_FROM_NUMBER': '+1234567890',
        # 'FAB_SENDGRID_API_KEY': 'your_sendgrid_api_key',
        # 'FAB_SENDGRID_FROM_EMAIL': 'noreply@yourdomain.com',
    }


def validate_mfa_config(config_dict):
    """
    Validate MFA configuration.
    
    Args:
        config_dict: Configuration dictionary to validate
        
    Returns:
        Tuple of (is_valid, errors_list)
    """
    errors = []
    
    if not config_dict.get('FAB_MFA_ENABLED'):
        return True, []  # If MFA is disabled, no validation needed
    
    # Check required settings
    if not config_dict.get('SECRET_KEY'):
        errors.append("SECRET_KEY is required for secure MFA operations")
    
    if not config_dict.get('FAB_MFA_TOTP_ISSUER'):
        errors.append("FAB_MFA_TOTP_ISSUER should be set to your application name")
    
    # Check SMS provider configuration
    sms_provider = config_dict.get('FAB_MFA_SMS_PROVIDER', 'twilio')
    if sms_provider == 'twilio':
        twilio_settings = ['FAB_TWILIO_ACCOUNT_SID', 'FAB_TWILIO_AUTH_TOKEN', 'FAB_TWILIO_FROM_NUMBER']
        missing_twilio = [s for s in twilio_settings if not config_dict.get(s)]
        if missing_twilio:
            errors.append(f"Twilio SMS requires: {', '.join(missing_twilio)}")
    
    # Check email provider configuration
    email_provider = config_dict.get('FAB_MFA_EMAIL_PROVIDER', 'flask_mail')
    if email_provider == 'flask_mail':
        mail_settings = ['MAIL_SERVER', 'MAIL_DEFAULT_SENDER']
        missing_mail = [s for s in mail_settings if not config_dict.get(s)]
        if missing_mail:
            errors.append(f"Flask-Mail requires: {', '.join(missing_mail)}")
    elif email_provider == 'sendgrid':
        if not config_dict.get('FAB_SENDGRID_API_KEY'):
            errors.append("SendGrid requires FAB_SENDGRID_API_KEY")
    
    return len(errors) == 0, errors


def get_required_packages():
    """
    Get list of required packages for MFA functionality.
    
    Returns:
        Dictionary with package requirements by feature
    """
    return {
        'totp': ['pyotp', 'qrcode[pil]', 'Pillow'],
        'sms_twilio': ['twilio'],
        'sms_aws': ['boto3'],
        'email_sendgrid': ['sendgrid'],
        'email_flask_mail': ['Flask-Mail'],
        'email_aws_ses': ['boto3'],
        'all': ['pyotp', 'qrcode[pil]', 'Pillow', 'twilio', 'boto3', 'sendgrid', 'Flask-Mail']
    }