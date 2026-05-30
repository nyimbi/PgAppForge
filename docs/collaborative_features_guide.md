# PgAppForge Collaborative Features Guide

## Overview

PgAppForge's collaborative features provide a comprehensive framework for building real-time, multi-user applications with robust validation, error handling, audit logging, and transaction management.

## Architecture

The collaborative features are built around four core utility modules:

### 1. Validation Utilities (`pgappforge.collaborative.utils.validation`)

Provides comprehensive data validation with consistent error reporting:

- **FieldValidator**: Basic field validation (required, type, length, range)
- **UserValidator**: User object and ID validation
- **TokenValidator**: Token format and JWT validation
- **DataValidator**: JSON serialization and data structure validation
- **MessageValidator**: Message object validation combining multiple patterns

### 2. Error Handling (`pgappforge.collaborative.utils.error_handling`)

Structured exception hierarchy with context and user-friendly messages:

- **CollaborativeError**: Base exception with categorization and severity
- **Specialized Errors**: ValidationError, AuthenticationError, AuthorizationError, etc.
- **ErrorHandlingMixin**: Mixin for consistent error handling across services

### 3. Audit Logging (`pgappforge.collaborative.utils.audit_logging`)

Centralized audit logging with structured events:

- **AuditLogger**: Configurable audit event logging
- **AuditEvent**: Structured audit event data
- **CollaborativeAuditMixin**: Mixin for adding audit capabilities

### 4. Transaction Management (`pgappforge.collaborative.utils.transaction_manager`)

Framework-wide transaction handling with deadlock detection:

- **TransactionManager**: Context-based transaction management
- **Decorators**: @transaction_required, @retry_on_deadlock
- **TransactionMixin**: Mixin for adding transaction capabilities

## Quick Start

### Basic Setup

```python
from flask import Flask
from pgappforge import AppBuilder
from pgappforge.collaborative.addon_manager import CollaborativeAddonManager

# Create Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'your-database-uri'

# Create AppBuilder
appbuilder = AppBuilder(app, db.session)

# Add collaborative features addon
app.config['ADDON_MANAGERS'] = [
    'pgappforge.collaborative.addon_manager.CollaborativeAddonManager'
]
```

### Using Validation Utilities

```python
from pgappforge.collaborative.utils.validation import (
    FieldValidator, UserValidator, MessageValidator
)

# Field validation
result = FieldValidator.validate_required_field(user_input, 'username')
if not result.is_valid:
    return {"error": result.error_message}

# User validation
result = UserValidator.validate_user_object(current_user)
if not result.is_valid:
    raise ValidationError(result.error_message)

# Message validation
result = MessageValidator.validate_message_with_data(message, max_data_size=1024*100)
if not result.is_valid:
    return {"error": result.error_message, "code": result.error_code}
```

### Using Error Handling

```python
from pgappforge.collaborative.utils.error_handling import (
    ErrorHandlingMixin, ValidationError, create_error_response
)

class MyService(ErrorHandlingMixin):
    def process_data(self, data):
        # Set error context for better debugging
        self.set_error_context(
            user_id=current_user.id,
            operation="process_data"
        )
        
        try:
            # Validate and process data
            if not data:
                raise ValidationError("Data is required")
                
            # Use safe_execute for operations that might fail
            result = self.safe_execute(
                self._risky_operation,
                data,
                operation="risky_operation"
            )
            
            return {"success": True, "result": result}
            
        except CollaborativeError as e:
            # Create standardized error response
            return create_error_response(e)
```

### Using Audit Logging

```python
from pgappforge.collaborative.utils.audit_logging import (
    CollaborativeAuditMixin, AuditEventType
)

class TeamService(CollaborativeAuditMixin):
    def create_team(self, name, created_by_user_id):
        # Set audit context
        self.audit_logger.set_context(
            user_id=created_by_user_id,
            session_id=request.session.get('session_id'),
            ip_address=request.remote_addr
        )
        
        try:
            # Create team
            team = Team(name=name, created_by=created_by_user_id)
            db.session.add(team)
            db.session.commit()
            
            # Log successful creation
            self.audit_event(
                AuditEventType.TEAM_CREATED,
                resource_type="team",
                resource_id=str(team.id),
                details={"team_name": name}
            )
            
            return team
            
        except Exception as e:
            # Log failure
            self.audit_security_event(
                AuditEventType.SERVICE_ERROR,
                outcome="failure",
                details={"error": str(e)}
            )
            raise
```

### Using Transaction Management

```python
from pgappforge.collaborative.utils.transaction_manager import (
    TransactionMixin, TransactionScope, transaction_required
)

class WorkspaceService(TransactionMixin):
    @transaction_required(scope=TransactionScope.READ_WRITE, retry_on_deadlock=True)
    def update_workspace_permissions(self, workspace_id, permissions):
        """Update workspace permissions with automatic transaction management."""
        
        # This method automatically runs in a transaction with deadlock retry
        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            raise ValidationError("Workspace not found")
            
        # Update permissions
        for user_id, permission in permissions.items():
            permission_obj = WorkspacePermission.query.filter_by(
                workspace_id=workspace_id,
                user_id=user_id
            ).first()
            
            if permission_obj:
                permission_obj.permission = permission
            else:
                permission_obj = WorkspacePermission(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    permission=permission
                )
                db.session.add(permission_obj)
        
        return {"updated": len(permissions)}
    
    def create_workspace_with_savepoint(self, workspace_data):
        """Create workspace using manual transaction management with savepoints."""
        
        with self.with_transaction(TransactionScope.READ_WRITE) as session:
            # Create main workspace
            workspace = Workspace(**workspace_data)
            session.add(workspace)
            session.flush()  # Get workspace.id
            
            # Use savepoint for permission setup
            with self.with_savepoint("permission_setup") as sp_session:
                try:
                    # Set up initial permissions
                    admin_permission = WorkspacePermission(
                        workspace_id=workspace.id,
                        user_id=workspace_data['owner_id'],
                        permission='admin'
                    )
                    sp_session.add(admin_permission)
                    
                except Exception:
                    # Savepoint will automatically rollback
                    # Workspace creation continues without permissions
                    pass
            
            return workspace
```

## Advanced Usage

### Service Integration Pattern

```python
from pgappforge.collaborative.interfaces.base_interfaces import BaseCollaborativeService
from pgappforge.collaborative.utils import *

class ComprehensiveService(
    BaseCollaborativeService,
    CollaborativeAuditMixin, 
    ErrorHandlingMixin,
    TransactionMixin
):
    """Example service using all collaborative utilities."""
    
    def initialize(self):
        self.audit_service_event("started")
        
    def process_user_request(self, user, request_data):
        # Set context for error handling and audit logging
        self.set_error_context(
            user_id=user.id,
            operation="process_user_request"
        )
        
        self.audit_logger.set_context(
            user_id=user.id,
            session_id=request_data.get('session_id')
        )
        
        try:
            # Validate input using validation utilities
            user_result = UserValidator.validate_user_object(user)
            if not user_result.is_valid:
                raise ValidationError(user_result.error_message)
                
            data_result = DataValidator.validate_json_serializable(request_data)
            if not data_result.is_valid:
                raise ValidationError(data_result.error_message)
            
            # Process with transaction management
            with self.with_transaction(TransactionScope.READ_WRITE):
                result = self._perform_business_logic(user, request_data)
                
                # Log successful processing
                self.audit_event(
                    AuditEventType.USER_ACTION,
                    details={"action": "request_processed"}
                )
                
                return result
                
        except Exception as e:
            # Unified error handling
            collaborative_error = self.handle_error(e)
            
            # Log error for audit
            self.audit_security_event(
                AuditEventType.SERVICE_ERROR,
                outcome="failure"
            )
            
            # Return standardized error response
            return create_error_response(collaborative_error)
```

### Custom Validation Patterns

```python
from pgappforge.collaborative.utils.validation import ValidationResult

def validate_team_membership(user_id, team_id):
    """Custom validation function following the ValidationResult pattern."""
    
    # Check if user exists
    user_result = UserValidator.validate_user_id(user_id)
    if not user_result.is_valid:
        return user_result
        
    # Check team membership (example business logic)
    membership = TeamMembership.query.filter_by(
        user_id=user_id,
        team_id=team_id
    ).first()
    
    if not membership:
        return ValidationResult.failure(
            "User is not a member of this team",
            "NOT_TEAM_MEMBER"
        )
        
    if membership.status != 'active':
        return ValidationResult.failure(
            "User membership is not active",
            "INACTIVE_MEMBERSHIP"
        )
        
    return ValidationResult.success()

# Usage in service
result = validate_team_membership(user.id, team.id)
if not result.is_valid:
    raise ValidationError(result.error_message, error_code=result.error_code)
```

## Configuration Options

### Collaborative Features Configuration

```python
# Flask app configuration
app.config.update({
    # Enable/disable collaborative features
    'COLLABORATIVE_ENABLED': True,
    
    # Auto-discover service implementations
    'COLLABORATIVE_AUTO_DISCOVER': True,
    
    # WebSocket configuration
    'COLLABORATIVE_WEBSOCKET_ENABLED': True,
    'COLLABORATIVE_WEBSOCKET_PATH': '/ws/collaborative',
    
    # Background tasks
    'COLLABORATIVE_BACKGROUND_TASKS': True,
    
    # Health checks
    'COLLABORATIVE_HEALTH_CHECKS': True,
    
    # API configuration
    'COLLABORATIVE_API_PREFIX': '/api/v1/collaborative',
    
    # Menu configuration
    'COLLABORATIVE_MENU_CATEGORY': 'Collaboration',
    'COLLABORATIVE_MENU_ICON': 'fa-users',
    
    # Custom service implementations
    'COLLABORATIVE_CUSTOM_SERVICES': {
        'collaboration': 'myapp.services.CustomCollaborationService',
        'team': 'myapp.services.CustomTeamService'
    }
})
```

### Audit Logging Configuration

```python
app.config.update({
    # Enable/disable audit logging
    'AUDIT_LOGGING_ENABLED': True,
    
    # Logging level for audit events
    'AUDIT_LOG_LEVEL': 'INFO',
    
    # Include sensitive data in audit logs
    'AUDIT_INCLUDE_SENSITIVE_DATA': False,
    
    # Maximum size for audit event details
    'AUDIT_MAX_DETAILS_SIZE': 10240  # 10KB
})
```

### Transaction Management Configuration

```python
app.config.update({
    # Maximum retry attempts for deadlock resolution
    'TRANSACTION_MAX_RETRY_ATTEMPTS': 3,
    
    # Base delay between retries (seconds)
    'TRANSACTION_BASE_RETRY_DELAY': 0.1,
    
    # Maximum delay between retries (seconds)
    'TRANSACTION_MAX_RETRY_DELAY': 5.0,
    
    # Enable deadlock retry by default
    'TRANSACTION_DEADLOCK_RETRY_ENABLED': True,
    
    # Enable savepoint functionality
    'TRANSACTION_SAVEPOINT_ENABLED': True,
    
    # Enable transaction metrics collection
    'TRANSACTION_METRICS_ENABLED': True
})
```

## Best Practices

### 1. Validation Strategy

- **Always validate at boundaries**: API endpoints, service entry points
- **Use ValidationResult pattern**: Consistent error reporting across the application
- **Validate early**: Check inputs before expensive operations
- **Provide specific error messages**: Help users understand what went wrong

### 2. Error Handling Strategy

- **Use structured exceptions**: Leverage the CollaborativeError hierarchy
- **Set error context**: Provide debugging information for operations
- **Log errors appropriately**: Use audit logging for security-relevant errors
- **Return user-friendly messages**: Use create_error_response for API responses

### 3. Audit Logging Strategy

- **Log security events**: Authentication, authorization, permission changes
- **Log business events**: Important state changes, user actions
- **Use structured data**: Include relevant context in audit event details
- **Respect privacy**: Configure sensitive data inclusion appropriately

### 4. Transaction Management Strategy

- **Use appropriate scope**: READ_ONLY for queries, READ_WRITE for modifications
- **Enable deadlock retry**: For operations that might conflict with other users
- **Use savepoints**: For complex operations with partial rollback needs
- **Monitor metrics**: Track transaction performance and deadlock frequency

## Testing

### Unit Testing Utilities

```python
import unittest
from pgappforge.collaborative.utils.validation import ValidationResult
from pgappforge.collaborative.utils.error_handling import ValidationError

class TestMyService(unittest.TestCase):
    def test_validation(self):
        # Test successful validation
        result = FieldValidator.validate_required_field("value", "field")
        self.assertTrue(result.is_valid)
        
        # Test failed validation
        result = FieldValidator.validate_required_field(None, "field")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "FIELD_REQUIRED")
    
    def test_error_handling(self):
        error = ValidationError("Test error")
        response = create_error_response(error)
        
        self.assertTrue(response['error'])
        self.assertEqual(response['error_code'], 'VALIDATION')
```

## Migration Guide

If you're upgrading from previous collaborative feature implementations:

1. **Replace direct validation**: Use ValidationResult pattern instead of boolean returns
2. **Update error handling**: Migrate to CollaborativeError hierarchy
3. **Add audit logging**: Use CollaborativeAuditMixin for existing services
4. **Wrap transactions**: Use transaction decorators or context managers
5. **Update configuration**: Add new collaborative feature configuration options

## Performance Considerations

- **Validation overhead**: Minimal - utilities are designed for efficiency
- **Audit logging**: Asynchronous by default to minimize performance impact
- **Transaction management**: Optimized retry logic with exponential backoff
- **Error handling**: Lightweight exception creation and serialization

## Security Features

- **Input validation**: Comprehensive validation prevents injection attacks
- **Audit trails**: Complete audit logging for compliance and security monitoring
- **Error sanitization**: Sensitive data filtering in error responses
- **Transaction isolation**: Proper isolation levels prevent data corruption

This guide provides a comprehensive overview of PgAppForge's collaborative features. For specific implementation details, refer to the API documentation and example applications.