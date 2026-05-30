# Process Security System

## Overview

The Process Security System provides comprehensive security measures for the Intelligent Business Process Engine. It implements multiple layers of protection including input validation, authorization checks, tenant isolation, rate limiting, audit logging, and security event monitoring.

## Security Layers

### 1. Input Validation

**ProcessValidator** provides comprehensive validation for:

- **Process Definitions**: Structure validation, dangerous pattern detection, size limits
- **Process Instances**: Context data validation, size constraints
- **Expressions**: Security pattern scanning, length limits
- **HTML Content**: XSS prevention through sanitization

```python
from pgappforge.process.security import ProcessValidator

# Validate process definition
validated_data = ProcessValidator.validate_process_definition({
    'name': 'my_process',
    'description': 'A secure process',
    'definition': {'nodes': {...}, 'edges': [...]}
})
```

### 2. Authorization

**ProcessAuthorization** manages permission-based access control:

- Permission mapping for process operations
- Resource-specific access checks
- User authentication verification
- Role-based authorization

```python
from pgappforge.process.security import ProcessAuthorization

# Check user permissions
if ProcessAuthorization.check_permission('deploy', definition_id):
    # User can deploy the process
    pass

# Decorator for automatic permission checks
@ProcessAuthorization.require_permission('create')
def create_process():
    pass
```

### 3. Tenant Isolation

**TenantIsolationValidator** ensures data isolation between tenants:

- Resource ownership validation
- Cross-tenant access prevention
- Automatic tenant context filtering

```python
from pgappforge.process.security import TenantIsolationValidator

# Validate tenant access
if TenantIsolationValidator.validate_tenant_access(ProcessDefinition, process_id):
    # User can access this process within their tenant
    pass

# Decorator for automatic tenant validation
@TenantIsolationValidator.require_tenant_access(ProcessDefinition)
def access_process(id):
    pass
```

### 4. Rate Limiting

**RateLimiter** prevents abuse and ensures fair resource usage:

- Per-user, per-endpoint rate limiting
- Configurable limits and time windows
- Memory-efficient sliding window algorithm
- Automatic cleanup of expired entries

```python
from pgappforge.process.security import RateLimiter

# Create custom rate limiter
limiter = RateLimiter()
if limiter.is_allowed('user:123:endpoint', limit=100, window=60):
    # Request allowed
    pass

# Pre-configured limiters
from pgappforge.process.security import process_deploy_limiter

@process_deploy_limiter
def deploy_process():
    pass
```

### 5. Audit Logging

**ProcessAuditLogger** maintains comprehensive audit trails:

- Operation logging with context
- User and tenant tracking
- Success/failure recording
- Persistent storage for compliance

```python
from pgappforge.process.security import ProcessAuditLogger

# Log operation
ProcessAuditLogger.log_operation(
    operation='process_deploy',
    resource_type='process_definition',
    resource_id=123,
    details={'version': '1.0'},
    success=True
)

# Decorator for automatic audit logging
@ProcessAuditLogger.audit('process_create', 'process_definition')
def create_process():
    pass
```

### 6. Security Event Monitoring

**ProcessSecurityEvent** model tracks security-relevant events:

- Authentication failures
- Authorization violations
- Rate limit exceedances
- Tenant isolation breaches
- Suspicious activities

## Integration with Views and APIs

### Securing View Methods

```python
from pgappforge.process.security import secure_view_method

class ProcessDefinitionView(ModelView):
    
    @action('deploy', 'Deploy Process', 'Deploy this process definition', 'fa-rocket')
    @secure_view_method('deploy', 'process_definition')
    def deploy_process(self, items):
        # Method is automatically secured
        pass
```

### Securing API Endpoints

```python
from pgappforge.process.security import secure_api_endpoint

class ProcessApi(ModelRestApi):
    
    @expose('/deploy/<int:definition_id>', methods=['POST'])
    @has_access_api
    @secure_api_endpoint('deploy', 'process_definition', require_data=False)
    def deploy_definition(self, definition_id):
        # Endpoint is automatically secured
        pass
```

### Combined Security Decorator

```python
from pgappforge.process.security import secure_process_operation

@secure_process_operation(
    operation='deploy',
    resource_type='process_definition',
    permission='deploy',
    model_class=ProcessDefinition,
    rate_limiter=process_deploy_limiter
)
def deploy_process_comprehensive(definition_id):
    # All security measures applied automatically
    pass
```

## Security Configuration

### Rate Limit Configuration

```python
# Default rate limits
PROCESS_RATE_LIMITS = {
    'read': (100, 60),      # 100 reads per minute
    'write': (20, 60),      # 20 writes per minute
    'deploy': (5, 300),     # 5 deployments per 5 minutes
    'execute': (10, 60),    # 10 executions per minute
}
```

### Security Headers

Automatic security headers are applied to all responses:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- Content Security Policy
- Referrer Policy

### Validation Limits

```python
# Configuration constants
MAX_NAME_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 2000
MAX_PROPERTIES_SIZE = 50000  # 50KB
MAX_EXPRESSION_LENGTH = 1000
```

## Error Handling

The security system provides specific exception types:

```python
from pgappforge.process.security import (
    ProcessSecurityError,
    ValidationError,
    AuthorizationError,
    TenantIsolationError,
    RateLimitExceededError
)

try:
    # Perform secured operation
    pass
except ValidationError as e:
    # Handle validation failure (400 Bad Request)
    pass
except AuthorizationError as e:
    # Handle authorization failure (403 Forbidden)
    pass
except TenantIsolationError as e:
    # Handle tenant violation (404 Not Found)
    pass
except RateLimitExceededError as e:
    # Handle rate limit (429 Too Many Requests)
    pass
```

## Audit Trail Models

### ProcessAuditLog

Tracks all process operations:

```python
from pgappforge.process.models.audit_models import ProcessAuditLog

# Query audit logs
logs = ProcessAuditLog.query.filter_by(
    operation='process_deploy',
    user_id=user.id
).order_by(ProcessAuditLog.timestamp.desc()).all()
```

### ProcessSecurityEvent

Tracks security events:

```python
from pgappforge.process.models.audit_models import ProcessSecurityEvent

# Query security events
events = ProcessSecurityEvent.query.filter_by(
    event_type=ProcessSecurityEvent.TYPE_AUTH_FAILURE,
    resolved=False
).all()

# Resolve security event
event.resolve(admin_user.id, "False positive - resolved by admin")
```

### ProcessComplianceLog

Tracks compliance-related activities:

```python
from pgappforge.process.models.audit_models import ProcessComplianceLog

# Create compliance log
compliance_log = ProcessComplianceLog(
    framework=ProcessComplianceLog.FRAMEWORK_GDPR,
    event_type=ProcessComplianceLog.TYPE_DATA_ACCESS,
    description="User accessed personal data",
    user_id=user.id,
    tenant_id=tenant.id,
    data_classification='confidential'
)
```

## Initialization

Initialize the security system in your Flask application:

```python
from pgappforge.process.security import init_process_security

def create_app():
    app = Flask(__name__)
    
    # Initialize process security
    init_process_security(app)
    
    return app
```

## Best Practices

### 1. Always Use Security Decorators

```python
# Good
@secure_api_endpoint('create', 'process_definition', require_data=True)
def create_process(self, validated_data=None):
    pass

# Avoid
def create_process(self):
    # Manual security checks are error-prone
    pass
```

### 2. Validate All User Input

```python
# Good - automatic validation
@secure_api_endpoint('create', 'process_definition', require_data=True)
def create_process(self, validated_data=None):
    # validated_data is already sanitized and validated
    pass

# Manual validation when needed
try:
    validated_data = ProcessValidator.validate_process_definition(raw_data)
except ValidationError as e:
    return error_response(str(e))
```

### 3. Implement Proper Error Handling

```python
try:
    # Perform operation
    result = process_operation()
    return success_response(result)
except ValidationError as e:
    return error_response(str(e), 400)
except AuthorizationError as e:
    return error_response("Access denied", 403)
except TenantIsolationError as e:
    return error_response("Resource not found", 404)
except RateLimitExceededError as e:
    return error_response("Too many requests", 429)
```

### 4. Monitor Security Events

Regularly review security events:

```python
# Monitor failed authentication attempts
auth_failures = ProcessSecurityEvent.query.filter_by(
    event_type=ProcessSecurityEvent.TYPE_AUTH_FAILURE,
    resolved=False
).filter(
    ProcessSecurityEvent.timestamp > datetime.utcnow() - timedelta(hours=24)
).all()

# Alert on suspicious patterns
if len(auth_failures) > 10:
    send_security_alert("High number of authentication failures detected")
```

### 5. Regular Security Audits

```python
# Audit trail queries for compliance
from datetime import datetime, timedelta

# Get all process operations in the last month
recent_operations = ProcessAuditLog.query.filter(
    ProcessAuditLog.timestamp > datetime.utcnow() - timedelta(days=30)
).all()

# Check for failed operations
failed_operations = ProcessAuditLog.query.filter_by(
    success=False
).filter(
    ProcessAuditLog.timestamp > datetime.utcnow() - timedelta(days=7)
).all()
```

## Testing Security

The security system includes comprehensive tests:

```bash
# Run security tests
python -m pytest tests/test_process_security.py -v

# Run with coverage
python -m pytest tests/test_process_security.py --cov=pgappforge.process.security
```

## Troubleshooting

### Common Issues

1. **ValidationError on Process Deployment**
   - Check process definition structure
   - Verify no dangerous patterns in expressions
   - Ensure all required fields are present

2. **AuthorizationError on API Calls**
   - Verify user has required permissions
   - Check if user is authenticated
   - Confirm permission mapping is correct

3. **TenantIsolationError**
   - Ensure resource belongs to current tenant
   - Verify tenant context is properly set
   - Check tenant ID in database records

4. **RateLimitExceededError**
   - Review rate limit configuration
   - Check if limits are appropriate for usage patterns
   - Consider implementing user-specific limits

### Debugging

Enable debug logging for security operations:

```python
import logging

# Set debug level for security module
logging.getLogger('pgappforge.process.security').setLevel(logging.DEBUG)
```

## Security Checklist

- [ ] All view methods use security decorators
- [ ] API endpoints implement proper validation
- [ ] Rate limits are configured appropriately
- [ ] Audit logging is enabled for all operations
- [ ] Security events are monitored and reviewed
- [ ] Error handling preserves security boundaries
- [ ] Input validation prevents injection attacks
- [ ] Tenant isolation is enforced consistently
- [ ] Security headers are applied to all responses
- [ ] Regular security audits are conducted