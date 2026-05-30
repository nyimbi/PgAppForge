# Multi-Factor Authentication (MFA) Setup Guide

## Overview

PgAppForge now includes built-in Multi-Factor Authentication (MFA) support with the following features:

- **TOTP Authentication** - Authenticator apps (Google Authenticator, Authy, etc.)
- **SMS Authentication** - via Twilio or AWS SNS
- **Email Authentication** - via Flask-Mail, SendGrid, or AWS SES
- **Backup Codes** - for account recovery
- **Security Policies** - configurable MFA requirements
- **Audit Trail** - comprehensive logging of MFA events

## Quick Start

### 1. Install Dependencies

```bash
# Basic MFA support (TOTP only)
pip install pyotp qrcode[pil] Pillow

# SMS support via Twilio
pip install twilio

# SMS support via AWS SNS
pip install boto3

# Email support via SendGrid
pip install sendgrid

# All providers
pip install pyotp qrcode[pil] Pillow twilio boto3 sendgrid
```

### 2. Configure Your Application

Add the following to your PgAppForge `config.py`:

```python
# Enable MFA
PGAF_MFA_ENABLED = True
PGAF_MFA_TOTP_ISSUER = "Your App Name"

# SMS Configuration (Twilio)
PGAF_MFA_SMS_PROVIDER = "twilio"
PGAF_TWILIO_ACCOUNT_SID = "your_account_sid"
PGAF_TWILIO_AUTH_TOKEN = "your_auth_token"
PGAF_TWILIO_FROM_NUMBER = "+1234567890"

# Email Configuration (Flask-Mail)
PGAF_MFA_EMAIL_PROVIDER = "flask_mail"
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = "your_email@gmail.com"
MAIL_PASSWORD = "your_app_password"
MAIL_DEFAULT_SENDER = "your_email@gmail.com"
```

### 3. Initialize Database

The MFA tables will be created automatically when you start your application. If you need to run migrations manually:

```bash
# If using Flask-Migrate
flask db upgrade

# Or recreate database (development only)
rm app.db  # Delete existing database
python app.py  # Restart application
```

### 4. Access MFA Settings

Once configured, users can access MFA settings at:
- `/mfa/setup/` - Set up new MFA methods
- `/mfa/verify/` - Verify MFA during login

## Configuration Options

### Core Settings

```python
PGAF_MFA_ENABLED = True                    # Enable/disable MFA
PGAF_MFA_TOTP_ISSUER = "Your App Name"    # Name in authenticator apps
PGAF_MFA_TOTP_WINDOW = 1                  # Time window tolerance
```

### Security Settings

```python
PGAF_MFA_MAX_ATTEMPTS = 5                 # Max attempts before lockout
PGAF_MFA_LOCKOUT_DURATION = 30            # Lockout duration (minutes)
PGAF_MFA_SMS_CODE_EXPIRES = 300           # SMS code expiry (seconds)
PGAF_MFA_EMAIL_CODE_EXPIRES = 600         # Email code expiry (seconds)
```

### Policy Settings

```python
PGAF_MFA_REQUIRE_BACKUP_CODES = True      # Require backup codes
PGAF_MFA_BACKUP_CODE_COUNT = 10           # Number of backup codes
PGAF_MFA_GRACE_PERIOD_DAYS = 7            # Grace period for new users
PGAF_MFA_REMINDER_DAYS = 3                # Reminder days before enforcement
```

### Rate Limiting

```python
PGAF_MFA_RATE_LIMIT_ENABLED = True        # Enable rate limiting
PGAF_MFA_RATE_LIMIT_WINDOW = 300          # Rate limit window (seconds)
PGAF_MFA_RATE_LIMIT_MAX_ATTEMPTS = 10     # Max attempts per window
```

### Session Settings

```python
PGAF_MFA_SESSION_TIMEOUT = 900            # MFA session timeout (seconds)
PGAF_MFA_REMEMBER_DEVICE = False          # Allow device remembering
PGAF_MFA_REMEMBER_DEVICE_DAYS = 30        # Remember device duration
```

## Provider Configuration

### SMS Providers

#### Twilio
```python
PGAF_MFA_SMS_PROVIDER = "twilio"
PGAF_TWILIO_ACCOUNT_SID = "your_account_sid"
PGAF_TWILIO_AUTH_TOKEN = "your_auth_token"
PGAF_TWILIO_FROM_NUMBER = "+1234567890"
```

#### AWS SNS
```python
PGAF_MFA_SMS_PROVIDER = "aws_sns"
PGAF_AWS_REGION = "us-east-1"
AWS_ACCESS_KEY_ID = "your_access_key"        # Or use IAM roles
AWS_SECRET_ACCESS_KEY = "your_secret_key"
```

### Email Providers

#### Flask-Mail (SMTP)
```python
PGAF_MFA_EMAIL_PROVIDER = "flask_mail"
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = "your_email@gmail.com"
MAIL_PASSWORD = "your_app_password"
MAIL_DEFAULT_SENDER = "your_email@gmail.com"
```

#### SendGrid
```python
PGAF_MFA_EMAIL_PROVIDER = "sendgrid"
PGAF_SENDGRID_API_KEY = "your_api_key"
PGAF_SENDGRID_FROM_EMAIL = "noreply@yourdomain.com"
```

#### AWS SES
```python
PGAF_MFA_EMAIL_PROVIDER = "ses"
PGAF_AWS_SES_FROM_EMAIL = "noreply@yourdomain.com"
PGAF_AWS_REGION = "us-east-1"
# AWS credentials via environment or IAM roles
```

## User Experience

### Setting Up MFA

1. **Login** to your PgAppForge application
2. **Navigate** to MFA Settings (usually in user profile/security)
3. **Choose** MFA method (Authenticator App, SMS, or Email)
4. **Follow** setup instructions:
   - **TOTP**: Scan QR code with authenticator app
   - **SMS**: Enter phone number and verify with sent code
   - **Email**: Verify with code sent to email
5. **Save** backup codes in a secure location
6. **Complete** setup by entering verification code

### Using MFA

1. **Enter** username and password as normal
2. **Choose** MFA method if multiple are configured
3. **Enter** verification code from:
   - Authenticator app (6-digit TOTP code)
   - SMS message
   - Email
4. **Access** application after successful verification

### Backup Codes

- Generated automatically when setting up MFA
- 8-character alphanumeric codes
- Each code can only be used once
- Store securely (password manager, safe, etc.)
- Use when primary MFA device is unavailable

## Security Best Practices

### For Administrators

1. **Enable rate limiting** to prevent brute force attacks
2. **Monitor MFA events** in application logs
3. **Set appropriate timeouts** for codes and sessions
4. **Require backup codes** to prevent lockouts
5. **Configure grace periods** for user adoption

### For Users

1. **Use authenticator apps** when possible (most secure)
2. **Store backup codes** securely and separately from devices
3. **Don't share** MFA codes or backup codes
4. **Update phone numbers** and email addresses when changed
5. **Test backup codes** periodically

## Troubleshooting

### Common Issues

#### MFA Not Appearing
```python
# Check configuration
PGAF_MFA_ENABLED = True  # Must be True

# Check logs for errors
tail -f app.log | grep -i mfa
```

#### Database Tables Missing
```bash
# Recreate database (development only)
rm app.db
python app.py

# Or run migrations
flask db upgrade
```

#### TOTP Codes Not Working
- Check device time synchronization
- Verify TOTP window setting (`PGAF_MFA_TOTP_WINDOW`)
- Ensure secret key is correctly entered

#### SMS/Email Not Sending
- Verify provider credentials
- Check rate limits and quotas
- Review provider-specific logs

### Debug Mode

Enable debug logging for MFA:

```python
import logging

# Enable debug logging
logging.getLogger('pgappforge.security.mfa').setLevel(logging.DEBUG)
```

### Getting Help

1. Check application logs for error messages
2. Verify all required dependencies are installed
3. Test provider credentials independently
4. Review configuration for typos
5. Check PgAppForge documentation for updates

## Example Complete Configuration

```python
# Complete MFA configuration example
from flask import Flask
from pgappforge import AppBuilder, SQLA

app = Flask(__name__)
app.config.update({
    # Flask settings
    'SECRET_KEY': 'your-secret-key',
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///app.db',
    
    # MFA Configuration
    'PGAF_MFA_ENABLED': True,
    'PGAF_MFA_TOTP_ISSUER': 'My Flask App',
    
    # Twilio SMS
    'PGAF_MFA_SMS_PROVIDER': 'twilio',
    'PGAF_TWILIO_ACCOUNT_SID': 'your_account_sid',
    'PGAF_TWILIO_AUTH_TOKEN': 'your_auth_token',
    'PGAF_TWILIO_FROM_NUMBER': '+1234567890',
    
    # Flask-Mail
    'PGAF_MFA_EMAIL_PROVIDER': 'flask_mail',
    'MAIL_SERVER': 'smtp.gmail.com',
    'MAIL_PORT': 587,
    'MAIL_USE_TLS': True,
    'MAIL_USERNAME': 'your_email@gmail.com',
    'MAIL_PASSWORD': 'your_app_password',
    'MAIL_DEFAULT_SENDER': 'your_email@gmail.com',
    
    # Security settings
    'PGAF_MFA_MAX_ATTEMPTS': 5,
    'PGAF_MFA_LOCKOUT_DURATION': 30,
    'PGAF_MFA_RATE_LIMIT_ENABLED': True,
})

# Initialize PgAppForge
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

if __name__ == '__main__':
    app.run(debug=True)
```

This configuration enables TOTP, SMS (Twilio), and Email (Flask-Mail) MFA methods with security features enabled.