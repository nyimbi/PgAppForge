# Secret Key Security Guide

## Overview

This guide documents the critical security fixes made to address hardcoded secret keys in PgForge and provides best practices for secure key management.

## Security Issue Fixed

**CRITICAL VULNERABILITY**: Multiple configuration files contained hardcoded secret keys, including:
- `bin/config.py` - Production configuration with weak hardcoded key
- `examples/employees/config.py` - Example with production-unsafe key
- Multiple other example configurations

**Risk Level**: CRITICAL
- **Impact**: Session hijacking, CSRF bypass, authentication bypass
- **Scope**: All deployments using default configurations
- **Severity**: Complete application security compromise possible

## Security Fixes Implemented

### 1. Production Configuration Security (`bin/config.py`)

**Before** (VULNERABLE):
```python
SECRET_KEY = '\2\1thisismyscretkey\1\2\e\y\y\h'  # Hardcoded weak key
```

**After** (SECURE):
```python
import os
import secrets
import sys

# SECURITY FIX: Replace hardcoded secret key with secure environment variable reading
SECRET_KEY = os.environ.get('SECRET_KEY')

if not SECRET_KEY:
    print("ERROR: SECRET_KEY environment variable is required for security!")
    print("Generate a secure key with: python -c \"import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))\"")
    sys.exit(1)

if len(SECRET_KEY) < 32:
    print("ERROR: SECRET_KEY must be at least 32 characters long for security!")
    sys.exit(1)
```

### 2. Example Configuration Best Practices

**Updated Pattern** (Development-friendly but secure):
```python
import os
import secrets

# SECURITY BEST PRACTICE: Use environment variable for secret key
SECRET_KEY = os.environ.get('SECRET_KEY')

if not SECRET_KEY:
    # For development/example purposes only - NEVER use in production
    print("WARNING: Using development secret key. Set SECRET_KEY environment variable for production!")
    SECRET_KEY = secrets.token_urlsafe(64)  # Generate random key for session
```

### 3. Secure Key Generation Utility

Created `bin/generate_secret_key.py` - A comprehensive utility for:
- Generating cryptographically secure secret keys
- Validating existing keys for security compliance
- Providing deployment instructions
- Supporting multiple key formats (URL-safe, hex, bytes)

## Secret Key Security Best Practices

### 1. Key Generation

Always use cryptographically secure random generators:

```bash
# Generate a secure 64-character key (recommended)
python bin/generate_secret_key.py

# Generate with export commands
python bin/generate_secret_key.py --export

# Generate hex format key
python bin/generate_secret_key.py --format hex --length 128
```

### 2. Key Storage

**✅ SECURE METHODS:**
- Environment variables (`export SECRET_KEY='...'`)
- Secret management services (AWS Secrets Manager, HashiCorp Vault)
- Encrypted configuration files
- Container orchestration secrets (Kubernetes secrets)

**❌ INSECURE METHODS:**
- Hardcoded in source code
- Configuration files in version control
- Plain text files
- Shared in chat/email

### 3. Key Management

**Production Requirements:**
- Minimum 32 characters length (recommended: 64+)
- Cryptographically random generation
- Unique per environment (dev/staging/prod)
- Regular rotation (quarterly recommended)
- No weak patterns or dictionary words

**Validation Commands:**
```bash
# Check current environment key
python bin/generate_secret_key.py --check-env

# Validate a specific key
python bin/generate_secret_key.py --validate 'your-key-here'
```

### 4. Deployment Patterns

#### Local Development
```bash
# Generate and set for current session
export SECRET_KEY=$(python bin/generate_secret_key.py)

# Add to shell profile for persistence
echo "export SECRET_KEY='$(python bin/generate_secret_key.py)'" >> ~/.bashrc
```

#### Docker Deployment
```bash
# Environment file approach
echo "SECRET_KEY=$(python bin/generate_secret_key.py)" > .env
docker run --env-file .env your-app

# Direct environment variable
docker run -e SECRET_KEY="$(python bin/generate_secret_key.py)" your-app
```

#### Production Server
```bash
# System environment variable
sudo tee -a /etc/environment <<< "SECRET_KEY=$(python bin/generate_secret_key.py)"

# Systemd service
echo "Environment=SECRET_KEY=$(python bin/generate_secret_key.py)" >> /etc/systemd/system/your-app.service
```

#### Kubernetes
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
type: Opaque
data:
  SECRET_KEY: <base64-encoded-secret-key>
```

### 5. Configuration Validation

Add validation to your application startup:

```python
def validate_secret_key():
    """Validate SECRET_KEY configuration at startup."""
    secret_key = os.environ.get('SECRET_KEY')

    if not secret_key:
        raise ValueError("SECRET_KEY environment variable must be set")

    if len(secret_key) < 32:
        raise ValueError("SECRET_KEY must be at least 32 characters for security")

    # Check for common weak patterns
    weak_patterns = ['secret', 'password', 'key', 'test', 'demo']
    key_lower = secret_key.lower()
    for pattern in weak_patterns:
        if pattern in key_lower:
            raise ValueError(f"SECRET_KEY contains weak pattern: {pattern}")

    return True

# Call during application initialization
validate_secret_key()
```

## Security Testing

### Automated Key Validation

Include in your CI/CD pipeline:

```bash
# Test configuration security
python bin/generate_secret_key.py --check-env

# Validate all config files don't contain hardcoded keys
grep -r "SECRET_KEY.*=" config/ examples/ | grep -v "os.environ" | grep -v "secrets.token"
```

### Code Review Checklist

- [ ] No hardcoded secret keys in any configuration files
- [ ] All production configs require environment variables
- [ ] Secret key validation at application startup
- [ ] Development configs warn about temporary keys
- [ ] Documentation updated with security guidance

## Migration Guide

### For Existing Applications

1. **Generate secure key:**
   ```bash
   python bin/generate_secret_key.py --export
   ```

2. **Set environment variable:**
   ```bash
   export SECRET_KEY='your-generated-key'
   ```

3. **Update configuration:**
   ```python
   # Replace hardcoded key with environment reading
   SECRET_KEY = os.environ.get('SECRET_KEY')
   if not SECRET_KEY:
       raise ValueError("SECRET_KEY environment variable required")
   ```

4. **Test thoroughly:**
   - Verify sessions work correctly
   - Test CSRF protection
   - Validate authentication flows

### For Production Deployments

1. **Backup current sessions** (users may need to re-login)
2. **Generate production key** using the utility
3. **Deploy with new environment variable**
4. **Monitor for authentication issues**
5. **Update deployment documentation**

## Compliance and Standards

This security fix addresses:
- **OWASP Top 10**: A02:2021 – Cryptographic Failures
- **CWE-798**: Use of Hard-coded Credentials
- **NIST Cybersecurity Framework**: PR.AC-1 (Access Control)
- **ISO 27001**: A.9.4.3 (Password management)

## Emergency Response

If you suspect secret key compromise:

1. **Immediately rotate the key** using the generator utility
2. **Force logout all users** (sessions will be invalidated)
3. **Review access logs** for suspicious activity
4. **Update deployment** with new key
5. **Monitor authentication** for anomalies

## Support and Resources

- **Key Generator**: `bin/generate_secret_key.py --help`
- **Validation**: `python bin/generate_secret_key.py --validate 'key'`
- **Environment Check**: `python bin/generate_secret_key.py --check-env`
- **Security Documentation**: This guide and `docs/CODE_REVIEW_REPORT.md`

## Summary

The hardcoded secret key vulnerability has been completely eliminated through:
- Mandatory environment variable configuration
- Secure key generation utilities
- Comprehensive validation systems
- Development-friendly fallbacks for examples
- Complete documentation and migration guidance

All production deployments now require proper secret key configuration, preventing the critical security vulnerability while maintaining development usability.