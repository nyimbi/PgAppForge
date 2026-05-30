# MFA and Passkeys

PgAppForge supports TOTP (Google Authenticator/Authy), SMS, email OTP, and
WebAuthn passkeys (Touch ID, Face ID, Windows Hello, YubiKey). All methods
share the same `PGAF_MFA_ENABLED` gate and work together — users can enroll
multiple methods and use any one of them to log in.

## Quick start — TOTP only

```python
# config.py
PGAF_MFA_ENABLED = True
PGAF_MFA_TOTP_ISSUER = "MyApp"   # shown in authenticator app
```

```bash
pip install pgappforge[mfa]   # pulls in pyotp, qrcode, py-webauthn
```

Restart the app. PgAppForge auto-creates the MFA tables and registers:

| Route | Purpose |
|-------|---------|
| `/mfa/setup` | User enrols TOTP / SMS / email / passkey |
| `/mfa/verify` | Challenge page after primary login |
| `/passkey/register` | Add a passkey credential |
| `/passkey/authenticate` | Passwordless passkey login |

Users see "Set up two-factor authentication" in their profile menu as soon as
`PGAF_MFA_ENABLED = True`.

---

## Enforcing MFA

```python
PGAF_MFA_ENABLED = True

# Require every user to enrol before they can proceed
PGAF_MFA_REQUIRED = True

# Grace period: users have 7 days to set up before they are blocked
PGAF_MFA_GRACE_PERIOD_DAYS = 7

# Or require only specific roles
PGAF_MFA_REQUIRED_ROLES = ["Admin", "Finance"]
```

---

## TOTP (authenticator app)

Works out of the box — no extra config needed beyond `PGAF_MFA_ENABLED = True`.

```python
# Optional tuning
PGAF_MFA_TOTP_ISSUER       = "Acme Corp"  # label in the authenticator app
PGAF_MFA_TOTP_WINDOW       = 1            # ±1 time-step tolerance (30s each)
PGAF_MFA_BACKUP_CODE_COUNT = 10           # backup codes generated at enrolment
```

### How it works for the user

1. User visits `/mfa/setup`, scans the QR code with Google Authenticator/Authy.
2. Confirms setup by entering the first 6-digit code.
3. Downloads backup codes.
4. On next login, after password they are redirected to `/mfa/verify` and enter
   the 6-digit code.

---

## Passkeys / WebAuthn

Passkeys let users authenticate with Touch ID, Face ID, Windows Hello, or a
hardware key (YubiKey) — no password or OTP needed.

### Requirements

```bash
pip install py-webauthn
```

### Config

```python
PGAF_MFA_ENABLED = True

# Your domain — must match the browser's origin exactly
PGAF_WEBAUTHN_RP_ID     = "app.example.com"   # no https://, no port
PGAF_WEBAUTHN_RP_NAME   = "Acme App"
PGAF_WEBAUTHN_ORIGIN    = "https://app.example.com"

# For local development:
# PGAF_WEBAUTHN_RP_ID  = "localhost"
# PGAF_WEBAUTHN_ORIGIN = "http://localhost:5000"
```

### Passwordless login

To allow users to log in with a passkey instead of a password:

```python
PGAF_WEBAUTHN_PASSWORDLESS = True    # show "Sign in with passkey" on login page
PGAF_WEBAUTHN_USER_VERIFICATION = "required"  # preferred | required | discouraged
```

### Registering a passkey (user flow)

1. User is logged in (via password or TOTP first time).
2. Goes to `/passkey/register`.
3. Browser shows biometric/hardware prompt.
4. Credential is stored — user can now sign in with biometrics alone.

---

## SMS codes

```bash
pip install twilio          # or boto3 for AWS SNS
```

```python
PGAF_MFA_ENABLED      = True
PGAF_MFA_SMS_PROVIDER = "twilio"          # twilio | aws_sns

# Twilio
PGAF_TWILIO_ACCOUNT_SID  = os.environ["TWILIO_SID"]
PGAF_TWILIO_AUTH_TOKEN   = os.environ["TWILIO_TOKEN"]
PGAF_TWILIO_FROM_NUMBER  = "+15555550100"

# AWS SNS (alternative)
# PGAF_MFA_SMS_PROVIDER = "aws_sns"
# AWS_ACCESS_KEY_ID     = os.environ["AWS_KEY"]
# AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET"]
# PGAF_AWS_REGION       = "us-east-1"

# Code settings
PGAF_MFA_SMS_CODE_EXPIRES = 300    # seconds (5 minutes)
PGAF_MFA_MAX_ATTEMPTS     = 5      # lock out after 5 bad codes
PGAF_MFA_LOCKOUT_DURATION = 30     # minutes
```

---

## Email codes

```bash
pip install Flask-Mail
```

```python
PGAF_MFA_ENABLED          = True
PGAF_MFA_EMAIL_PROVIDER   = "flask_mail"    # flask_mail | sendgrid | ses
PGAF_MFA_EMAIL_CODE_EXPIRES = 600           # seconds (10 minutes)

# Flask-Mail settings
MAIL_SERVER           = "smtp.gmail.com"
MAIL_PORT             = 587
MAIL_USE_TLS          = True
MAIL_USERNAME         = os.environ["MAIL_USER"]
MAIL_PASSWORD         = os.environ["MAIL_PASS"]
MAIL_DEFAULT_SENDER   = "noreply@example.com"

# SendGrid (alternative)
# PGAF_MFA_EMAIL_PROVIDER = "sendgrid"
# PGAF_SENDGRID_API_KEY   = os.environ["SENDGRID_KEY"]
# PGAF_SENDGRID_FROM_EMAIL = "noreply@example.com"
```

---

## Full production config example

```python
# config.py — production MFA with TOTP + passkeys + SMS fallback

SECRET_KEY = os.environ["SECRET_KEY"]

# --- MFA core ---
PGAF_MFA_ENABLED            = True
PGAF_MFA_REQUIRED           = True
PGAF_MFA_GRACE_PERIOD_DAYS  = 7
PGAF_MFA_BACKUP_CODE_COUNT  = 10
PGAF_MFA_MAX_ATTEMPTS       = 5
PGAF_MFA_LOCKOUT_DURATION   = 30        # minutes
PGAF_MFA_REMEMBER_DEVICE    = True
PGAF_MFA_REMEMBER_DEVICE_DAYS = 30

# --- TOTP ---
PGAF_MFA_TOTP_ISSUER = "Acme Corp"
PGAF_MFA_TOTP_WINDOW = 1

# --- Passkeys ---
PGAF_WEBAUTHN_RP_ID           = "app.acme.com"
PGAF_WEBAUTHN_RP_NAME         = "Acme App"
PGAF_WEBAUTHN_ORIGIN          = "https://app.acme.com"
PGAF_WEBAUTHN_PASSWORDLESS    = True
PGAF_WEBAUTHN_USER_VERIFICATION = "preferred"

# --- SMS fallback (Twilio) ---
PGAF_MFA_SMS_PROVIDER   = "twilio"
PGAF_TWILIO_ACCOUNT_SID = os.environ["TWILIO_SID"]
PGAF_TWILIO_AUTH_TOKEN  = os.environ["TWILIO_TOKEN"]
PGAF_TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM"]
```

---

## Migrating from FAB_ keys

If you previously used `FAB_MFA_*` keys (from the pre-0.90 `PGAF_` rename),
they still work — PgAppForge copies them automatically with a deprecation warning:

```
DeprecationWarning: Deprecated config keys (rename FAB_ → PGAF_): FAB_MFA_ENABLED, ...
```

Replace them at your convenience; both prefixes work indefinitely.

---

## Tables created automatically

| Table | Purpose |
|-------|---------|
| `ab_user_mfa` | Per-user MFA enrolment and method state |
| `ab_mfa_backup_codes` | Hashed backup codes |
| `ab_mfa_verification_attempts` | Rate-limiting and audit log |
| `ab_mfa_policies` | Per-role or per-user policy overrides |

These are created by `AppBuilder` on first start when `PGAF_MFA_ENABLED = True`.
No manual migration needed.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/mfa/setup` returns 404 | Set `PGAF_MFA_ENABLED = True` and restart |
| Passkey registration fails with "RP ID mismatch" | `PGAF_WEBAUTHN_RP_ID` must exactly match your domain (no port, no scheme) |
| TOTP code always rejected | Server clock out of sync; increase `PGAF_MFA_TOTP_WINDOW` to 2 |
| SMS not sent | Check Twilio credentials; verify `PGAF_MFA_SMS_PROVIDER = "twilio"` |
| Users not prompted for MFA | Set `PGAF_MFA_REQUIRED = True` |

See also: [Security Architecture](security_architecture.md) · [RBAC Configuration](rbac_configuration.md)
