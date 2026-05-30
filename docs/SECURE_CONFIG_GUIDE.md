# Secure Configuration Management

This guide explains how to securely manage sensitive tenant configuration data in PgAppForge's multi-tenant system.

## Overview

The secure configuration system provides automatic encryption for sensitive tenant configuration values such as:
- API keys and secrets
- OAuth client credentials
- Webhook secrets
- Database connection strings
- Third-party integration tokens
- SSL certificates and private keys

## Key Features

- **Automatic encryption/decryption**: Transparent handling of sensitive data
- **Industry-standard cryptography**: Uses Fernet (AES 128 in CBC mode) with PBKDF2 key derivation
- **Migration support**: CLI tools for encrypting existing configurations
- **Audit capabilities**: Tools for reviewing and verifying encryption status
- **Backward compatibility**: Works with existing non-sensitive configurations

## Setup

### 1. Environment Configuration

Set the master encryption key in your environment:

```bash
# Production - use a strong, randomly generated key
export FAB_CONFIG_MASTER_KEY="your-secure-master-key-here"

# Optional: custom salt (defaults to built-in salt)
export FAB_CONFIG_SALT="your-custom-salt"
```

**Important**: The master key should be:
- At least 32 characters long
- Randomly generated
- Stored securely (use a secrets manager in production)
- Backed up safely for disaster recovery

### 2. Generate a Secure Master Key

```python
from cryptography.fernet import Fernet

# Generate a secure key
master_key = Fernet.generate_key().decode()
print(f"Master key: {master_key}")
```

## Usage

### Storing Sensitive Configuration

```python
from pgappforge.models.tenant_models import TenantConfig

# Store an API key securely
TenantConfig.set_tenant_config(
    tenant_id=1,
    config_key='stripe_secret_key',
    value='sk_test_123456789...',
    is_sensitive=True,  # This will encrypt the value
    description='Stripe secret key for payments',
    category='billing'
)

# Store non-sensitive configuration
TenantConfig.set_tenant_config(
    tenant_id=1,
    config_key='app_theme',
    value='dark',
    is_sensitive=False,  # Plain text storage
    category='branding'
)
```

### Retrieving Configuration

```python
# Get decrypted sensitive value
api_key = TenantConfig.get_tenant_config(1, 'stripe_secret_key')
# Returns the decrypted value automatically

# Get non-sensitive value
theme = TenantConfig.get_tenant_config(1, 'app_theme', default='light')
```

### Using Configuration Objects

```python
from pgappforge.models.tenant_models import TenantConfig

# Get configuration object
config = TenantConfig.query.filter_by(
    tenant_id=1, 
    config_key='stripe_secret_key'
).first()

# Get decrypted value
api_key = config.get_value()  # Automatically decrypts

# Get display-safe value (for UI)
display_value = config.display_value  # Returns "***HIDDEN***" for sensitive configs
```

## CLI Management

The system includes comprehensive CLI tools for managing encrypted configurations:

### Check Encryption Status

```bash
flask fab config encryption-status
```

### Encrypt Existing Sensitive Configurations

```bash
flask fab config encrypt-sensitive
```

### Verify All Encryption is Working

```bash
flask fab config verify-encryption
```

### Audit Configuration Security

```bash
# Audit all tenants
flask fab config audit-config-security

# Audit specific tenant
flask fab config audit-config-security --tenant-id 1
```

### Mark Configuration as Sensitive

```bash
# Mark a configuration key as sensitive
flask fab config mark-sensitive --config-key webhook_secret

# Mark for specific tenant and encrypt immediately
flask fab config mark-sensitive --config-key api_token --tenant-id 1 --encrypt-now
```

## Migration from Plain Text

If you have existing sensitive configurations stored in plain text:

1. **Mark configurations as sensitive**:
   ```bash
   flask fab config mark-sensitive --config-key api_key
   flask fab config mark-sensitive --config-key webhook_secret
   ```

2. **Encrypt all sensitive configurations**:
   ```bash
   flask fab config encrypt-sensitive
   ```

3. **Verify encryption status**:
   ```bash
   flask fab config verify-encryption
   ```

## Security Best Practices

### 1. Key Management

- **Use environment variables** for the master key in production
- **Rotate keys regularly** (quarterly or annually)
- **Store keys in a secrets manager** (AWS Secrets Manager, HashiCorp Vault)
- **Never commit keys to version control**

### 2. Access Control

```python
# Check if user can access sensitive configs
from pgappforge import db
from pgappforge.models.tenant_models import TenantConfig
from pgappforge.security import current_user

def can_access_sensitive_config(tenant_id: int) -> bool:
    # Implement your access control logic
    return current_user.has_role('Tenant Admin') or current_user.has_role('Platform Admin')

# Use in views
if can_access_sensitive_config(tenant_id):
    config_value = TenantConfig.get_tenant_config(tenant_id, 'api_key')
else:
    # Return masked value or deny access
    config_value = "***ACCESS DENIED***"
```

### 3. Audit Logging

```python
import logging

# Log sensitive configuration access
log = logging.getLogger('security.config')

def get_sensitive_config(tenant_id: int, config_key: str):
    value = TenantConfig.get_tenant_config(tenant_id, config_key)
    
    # Log access
    log.info(f"Sensitive config accessed: {config_key} for tenant {tenant_id} by user {current_user.id}")
    
    return value
```

## API Integration

### Views Integration

```python
from pgappforge.models.tenant_models import TenantConfig
from pgappforge.models.tenant_context import require_active_tenant

class TenantConfigView(ModelView):
    datamodel = SQLAInterface(TenantConfig)
    
    @require_active_tenant()
    def list(self):
        # Filter configurations by current tenant
        tenant_id = get_current_tenant_id()
        self.base_filters = [['tenant_id', FilterEqual, tenant_id]]
        return super().list()
    
    def pre_update(self, item):
        # Ensure sensitive values are properly encrypted
        if item.is_sensitive and hasattr(request.form, 'config_value'):
            item.set_value(request.form.config_value)
```

### REST API Integration

```python
from pgappforge.api import ModelRestApi
from pgappforge.models.tenant_models import TenantConfig

class TenantConfigApi(ModelRestApi):
    resource_name = 'tenantconfig'
    datamodel = SQLAInterface(TenantConfig)
    
    def pre_get_list(self):
        # Automatically filter by tenant
        tenant_id = get_current_tenant_id()
        if tenant_id:
            self.base_filters = [['tenant_id', FilterEqual, tenant_id]]
    
    def post_get_list(self, result):
        # Mask sensitive values in API responses
        for item in result.get('result', []):
            if item.get('is_sensitive'):
                item['config_value'] = "***HIDDEN***"
        return result
```

## Error Handling

```python
from pgappforge.security.config_encryption import ConfigEncryptionError

try:
    config_value = TenantConfig.get_tenant_config(1, 'api_key')
except ConfigEncryptionError as e:
    # Handle encryption/decryption errors
    log.error(f"Config encryption error: {e}")
    # Fallback or alert administrators
    send_alert("Configuration encryption failed", str(e))
    raise
```

## Monitoring and Alerts

### Health Checks

```python
def check_encryption_health():
    """Health check for configuration encryption system"""
    try:
        from pgappforge.security.config_encryption import get_config_encryption
        
        encryption = get_config_encryption()
        
        # Test encryption/decryption
        test_value = "test-encryption-check"
        encrypted = encryption.encrypt_value(test_value)
        decrypted = encryption.decrypt_value(encrypted)
        
        if decrypted != test_value:
            return False, "Encryption test failed"
        
        return True, "Encryption system healthy"
        
    except Exception as e:
        return False, f"Encryption error: {e}"
```

### Monitoring Script

```bash
#!/bin/bash
# monitoring_script.sh

# Check encryption status
if ! flask fab config encryption-status > /dev/null 2>&1; then
    echo "ALERT: Configuration encryption system failed"
    exit 1
fi

# Verify all sensitive configs are encrypted
if ! flask fab config verify-encryption > /dev/null 2>&1; then
    echo "ALERT: Some sensitive configurations are not encrypted"
    exit 1
fi

echo "Configuration encryption monitoring: OK"
```

## Troubleshooting

### Common Issues

1. **"FAB_CONFIG_MASTER_KEY not found"**
   - Set the `FAB_CONFIG_MASTER_KEY` environment variable
   - Check that your deployment scripts include the key

2. **"Invalid encryption token"**
   - The master key may have changed
   - Data may be corrupted
   - Check logs for more details

3. **"Encryption failed"**
   - Check that the encryption system is properly initialized
   - Verify the master key is valid
   - Check for sufficient permissions

### Debug Mode

```python
# Enable debug logging
import logging
logging.getLogger('pgappforge.security.config_encryption').setLevel(logging.DEBUG)
```

### Recovery

If you lose the master key, encrypted data cannot be recovered. Have a recovery plan:

1. **Backup strategy**: Regularly backup your master key securely
2. **Key rotation**: Plan for key rotation procedures
3. **Recovery process**: Document steps to handle key loss scenarios

## Performance Considerations

- **Caching**: The system uses caching to avoid repeated encryption/decryption
- **Lazy loading**: Decryption only occurs when values are accessed
- **Connection pooling**: Use database connection pooling for better performance
- **Indexing**: Ensure proper database indexes on tenant_id and config_key

## Compliance

This encryption system helps meet compliance requirements for:

- **GDPR**: Data protection for EU tenant data
- **SOC 2**: Security controls for sensitive data
- **HIPAA**: Healthcare data encryption requirements
- **PCI DSS**: Payment card data security standards

## Advanced Features

### Custom Encryption Backend

```python
from pgappforge.security.config_encryption import ConfigEncryption

class CustomEncryption(ConfigEncryption):
    def encrypt_value(self, value):
        # Implement custom encryption logic
        pass
    
    def decrypt_value(self, encrypted_value):
        # Implement custom decryption logic
        pass
```

### Bulk Operations

```python
def encrypt_tenant_configs(tenant_id: int, config_keys: List[str]):
    """Bulk encrypt multiple configurations"""
    for key in config_keys:
        config = TenantConfig.query.filter_by(
            tenant_id=tenant_id, 
            config_key=key
        ).first()
        
        if config and not config.is_sensitive:
            config.is_sensitive = True
            config.set_value(config.config_value)  # Re-encrypt
    
    db.session.commit()
```

This secure configuration system provides enterprise-grade security for sensitive tenant data while maintaining ease of use and backward compatibility.