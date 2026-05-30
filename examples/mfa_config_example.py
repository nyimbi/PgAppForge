"""
Example PgAppForge configuration with MFA enabled.

This file demonstrates how to configure Multi-Factor Authentication
in your PgAppForge application.

Copy the relevant settings to your config.py file and modify as needed.
"""

# PgAppForge MFA Configuration
# =================================

# Enable MFA
FAB_MFA_ENABLED = True

# TOTP (Authenticator App) Configuration
FAB_MFA_TOTP_ISSUER = "My Flask App"  # Name shown in authenticator apps
FAB_MFA_TOTP_WINDOW = 1  # Time window tolerance (±30 seconds per window)

# SMS Configuration (choose one provider)
# -------------------------------------

# Option 1: Twilio SMS Provider
FAB_MFA_SMS_PROVIDER = "twilio"
FAB_TWILIO_ACCOUNT_SID = "your_twilio_account_sid"
FAB_TWILIO_AUTH_TOKEN = "your_twilio_auth_token"
FAB_TWILIO_FROM_NUMBER = "+1234567890"  # Your Twilio phone number

# Option 2: AWS SNS SMS Provider (uncomment to use)
# FAB_MFA_SMS_PROVIDER = "aws_sns"
# FAB_AWS_REGION = "us-east-1"
# AWS_ACCESS_KEY_ID = "your_aws_access_key"  # Or use IAM roles
# AWS_SECRET_ACCESS_KEY = "your_aws_secret_key"

# Email Configuration (choose one provider)
# ----------------------------------------

# Option 1: Flask-Mail (SMTP)
FAB_MFA_EMAIL_PROVIDER = "flask_mail"
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = "your_email@gmail.com"
MAIL_PASSWORD = "your_app_password"  # Use app password, not account password
MAIL_DEFAULT_SENDER = "your_email@gmail.com"

# Option 2: SendGrid (uncomment to use)
# FAB_MFA_EMAIL_PROVIDER = "sendgrid"
# FAB_SENDGRID_API_KEY = "your_sendgrid_api_key"
# FAB_SENDGRID_FROM_EMAIL = "noreply@yourdomain.com"

# Option 3: AWS SES (uncomment to use)
# FAB_MFA_EMAIL_PROVIDER = "ses"
# FAB_AWS_SES_FROM_EMAIL = "noreply@yourdomain.com"
# FAB_AWS_REGION = "us-east-1"
# # AWS credentials via environment or IAM roles

# MFA Code Settings
# ----------------
FAB_MFA_SMS_CODE_EXPIRES = 300      # SMS code expiry in seconds (5 minutes)
FAB_MFA_EMAIL_CODE_EXPIRES = 600    # Email code expiry in seconds (10 minutes)
FAB_MFA_MAX_ATTEMPTS = 5            # Maximum verification attempts before lockout
FAB_MFA_LOCKOUT_DURATION = 30       # Lockout duration in minutes

# MFA Policy Settings
# ------------------
FAB_MFA_REQUIRE_BACKUP_CODES = True  # Require backup codes for MFA setup
FAB_MFA_BACKUP_CODE_COUNT = 10       # Number of backup codes to generate
FAB_MFA_GRACE_PERIOD_DAYS = 7        # Grace period before MFA enforcement
FAB_MFA_REMINDER_DAYS = 3            # Days before grace period ends to send reminders

# Security Settings
# ----------------
FAB_MFA_RATE_LIMIT_ENABLED = True          # Enable rate limiting for MFA endpoints
FAB_MFA_RATE_LIMIT_WINDOW = 300            # Rate limit window in seconds (5 minutes)
FAB_MFA_RATE_LIMIT_MAX_ATTEMPTS = 10       # Max attempts per window per IP

# Session Settings
# ---------------
FAB_MFA_SESSION_TIMEOUT = 900              # MFA session timeout in seconds (15 minutes)
FAB_MFA_REMEMBER_DEVICE = False            # Allow "remember this device" option
FAB_MFA_REMEMBER_DEVICE_DAYS = 30          # Days to remember device


# Required Dependencies
# ====================
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


# Sample PgAppForge App with MFA
# ===================================

if __name__ == "__main__":
    """
    Sample PgAppForge application with MFA enabled.
    
    This demonstrates how to create a basic PgAppForge app
    with MFA functionality.
    """
    
    from flask import Flask
    from pgappforge import AppBuilder, SQLA
    from pgappforge.security.sqla.models import User
    
    # Create Flask app
    app = Flask(__name__)
    app.config.from_object(__name__)  # Load config from this file
    
    # Add required Flask settings
    app.config['SECRET_KEY'] = 'your-secret-key-change-this'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize PgAppForge
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)
    
    # Create initial admin user (only for testing)
    @app.before_first_request
    def create_admin():
        if not appbuilder.sm.find_user(username='admin'):
            appbuilder.sm.add_user(
                username='admin',
                first_name='Admin',
                last_name='User',
                email='admin@example.com',
                role=appbuilder.sm.find_role('Admin'),
                password='admin'
            )
    
    # Run the app
    app.run(host='0.0.0.0', port=8080, debug=True)