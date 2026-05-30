# PgAppForge Security Deployment Guide

## Overview

This guide provides comprehensive security configuration for production deployment of PgAppForge with enhanced security features.

## Critical Security Configuration

### 1. Environment Variables

**Required for Production:**
```bash
# Flask Security
SECRET_KEY=your-very-long-random-secret-key-minimum-32-chars
FLASK_ENV=production
SSL_REQUIRE=true

# Database
SQLALCHEMY_DATABASE_URI=postgresql://user:password@host:5432/database

# Redis (Required for Production Rate Limiting)
REDIS_URL=redis://localhost:6379/0
RATE_LIMIT_BACKEND=redis

# Security Features
ENABLE_CSP_HEADERS=true
ENFORCE_HTTPS=true
SESSION_TIMEOUT=3600
```

### 2. Key Vault Configuration

**Option A: Environment Variables (Basic)**
```bash
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
```

**Option B: Azure Key Vault (Recommended)**
```bash
KEY_VAULT_BACKEND=azure
AZURE_KEY_VAULT_URL=https://your-vault.vault.azure.net/
# Use Azure managed identity or service principal
```

**Option C: AWS Secrets Manager**
```bash
KEY_VAULT_BACKEND=aws
AWS_REGION=us-east-1
# Use IAM roles or credentials
```

**Option D: HashiCorp Vault**
```bash
KEY_VAULT_BACKEND=hashicorp
VAULT_URL=https://vault.company.com
VAULT_TOKEN=your-vault-token
```

### 3. Content Security Policy Configuration

**Default (Restrictive):**
```python
# In your app configuration
CSP_POLICY = {
    'default-src': "'self'",
    'script-src': "'self' 'unsafe-inline'",  # Adjust as needed
    'style-src': "'self' 'unsafe-inline'",
    'img-src': "'self' data: blob:",
    'font-src': "'self' data:",
    'connect-src': "'self'",
    'frame-ancestors': "'none'"
}
```

**Custom CSP for Your Environment:**
```python
# Allow specific domains
CSP_POLICY = {
    'default-src': "'self'",
    'script-src': "'self' https://cdn.jsdelivr.net",
    'style-src': "'self' https://stackpath.bootstrapcdn.com 'unsafe-inline'",
    'img-src': "'self' data: https:",
    'connect-src': "'self' https://api.your-service.com"
}
```

### 4. MFA Configuration

**Production MFA Setup:**
```bash
# MFA Encryption (Required)
MFA_ENCRYPTION_KEY=your-32-byte-base64-encoded-key

# MFA Policy
MFA_REQUIRED=true
MFA_BACKUP_CODES_COUNT=10
MFA_TOKEN_VALIDITY=300  # 5 minutes

# Supported Methods
MFA_ENABLE_TOTP=true
MFA_ENABLE_SMS=true
MFA_ENABLE_EMAIL=true
MFA_ENABLE_WEBAUTHN=true
```

## Security Hardening

### 1. Database Security

**PostgreSQL Configuration:**
```sql
-- Create dedicated user with minimal privileges
CREATE USER fab_app WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE fab_production TO fab_app;
GRANT USAGE ON SCHEMA public TO fab_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fab_app;
```

### 2. Rate Limiting Configuration

**Redis Production Setup:**
```bash
# Redis Configuration
REDIS_URL=redis://redis.internal:6379/0
REDIS_SSL=true
REDIS_PASSWORD=your-redis-password

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_DEFAULT=100/hour
RATE_LIMIT_LOGIN_ATTEMPTS=5/minute
RATE_LIMIT_API_CALLS=1000/hour
```

### 3. Session Security

**Session Configuration:**
```python
# In your Flask config
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
```

### 4. HTTPS Configuration

**Nginx Configuration:**
```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Monitoring & Alerting

### 1. Security Event Monitoring

**Log Configuration:**
```python
LOGGING = {
    'version': 1,
    'handlers': {
        'security': {
            'class': 'logging.handlers.SysLogHandler',
            'address': ('log-server.internal', 514),
            'facility': 'auth'
        }
    },
    'loggers': {
        'pgappforge.security': {
            'handlers': ['security'],
            'level': 'INFO'
        }
    }
}
```

### 2. Health Checks

**Security Health Endpoints:**
```python
@app.route('/health/security')
def security_health():
    return {
        'mfa_enabled': current_app.config.get('MFA_REQUIRED', False),
        'rate_limiting': current_app.config.get('RATE_LIMIT_ENABLED', False),
        'https_enforced': current_app.config.get('ENFORCE_HTTPS', False),
        'csp_enabled': current_app.config.get('ENABLE_CSP_HEADERS', False)
    }
```

## Incident Response

### 1. Security Incident Procedures

**Immediate Actions for Security Incidents:**

1. **Identify the Threat**
   - Check security logs: `/var/log/fab-security.log`
   - Review rate limiting alerts
   - Check for suspicious login attempts

2. **Contain the Incident**
   ```bash
   # Disable affected user accounts
   flask fab user-disable --username suspicious_user

   # Clear suspicious sessions
   flask fab clear-sessions --user-id 123

   # Temporarily increase rate limits
   redis-cli SET rate_limit_emergency_mode 1
   ```

3. **Investigate and Remediate**
   - Review audit logs for affected resources
   - Check for data access or modification
   - Update security policies if needed

### 2. Emergency Contact Information

**Security Team Contacts:**
- Security Officer: security@company.com
- On-call Engineer: +1-xxx-xxx-xxxx
- Incident Response: incident@company.com

## Compliance & Auditing

### 1. Audit Log Configuration

**Comprehensive Audit Logging:**
```python
AUDIT_EVENTS = [
    'user.login',
    'user.logout',
    'user.failed_login',
    'admin.user_create',
    'admin.user_delete',
    'admin.permission_change',
    'data.access',
    'data.modify',
    'security.mfa_enable',
    'security.mfa_disable'
]
```

### 2. Regular Security Reviews

**Monthly Security Checklist:**
- [ ] Review user access permissions
- [ ] Check for unused admin accounts
- [ ] Validate MFA enrollment status
- [ ] Review API key rotation schedule
- [ ] Check security event logs
- [ ] Verify backup and recovery procedures
- [ ] Update security patches

## Testing & Validation

### 1. Security Testing

**Pre-deployment Security Tests:**
```bash
# Run security test suite
pytest tests/security/

# Check for SQL injection vulnerabilities
python -m pgappforge.security.scanner

# Validate XSS protection
python -m pgappforge.security.xss_test

# Test rate limiting
python -m pgappforge.security.rate_limit_test
```

### 2. Penetration Testing

**Recommended Security Assessments:**
- Annual penetration testing
- Quarterly vulnerability scans
- Code security reviews for major releases
- Third-party security audits

## Troubleshooting

### 1. Common Issues

**MFA Not Working:**
```bash
# Check MFA configuration
flask fab mfa-status

# Reset user MFA
flask fab mfa-reset --username user@company.com
```

**Rate Limiting Issues:**
```bash
# Check Redis connection
redis-cli ping

# View current rate limits
redis-cli KEYS "rate_limit:*"
```

**CSP Violations:**
```javascript
// Check browser console for CSP violations
// Adjust CSP policy in app configuration
```

### 2. Performance Optimization

**Security Feature Performance:**
- Use Redis for rate limiting (10x faster than memory)
- Enable MFA caching for repeated authentications
- Optimize XSS protection for large content

## Conclusion

This security deployment guide provides comprehensive configuration for production PgAppForge deployments. Regular review and updates of security configurations are essential for maintaining a secure environment.

For additional support, contact the security team or refer to the PgAppForge security documentation.