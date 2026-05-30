"""
Process Security and Validation.

Comprehensive security validation for business process operations including
input validation, authorization checks, tenant isolation, and audit logging.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Dict, Any, List, Optional, Set, Union
from uuid import uuid4

import bleach
from flask import request, current_app, g
from flask_login import current_user
from sqlalchemy import and_, or_
from werkzeug.exceptions import BadRequest, Forbidden, TooManyRequests

from ...security import current_user
from ..models.process_models import ProcessDefinition, ProcessInstance, ProcessStep
from ..models.audit_models import ProcessAuditLog
from pgappforge.models.tenant_context import get_current_tenant_id

log = logging.getLogger(__name__)


class ProcessSecurityError(Exception):
    """Base exception for process security violations."""
    
    def __init__(self, message: str, error_code: str = None, context: Dict[str, Any] = None):
        super().__init__(message)
        self.error_code = error_code or 'PROCESS_SECURITY_ERROR'
        self.context = context or {}
        self.timestamp = datetime.now(tz=timezone.utc)
        self.request_id = getattr(g, 'request_id', str(uuid4()))
        self.user_id = getattr(current_user, 'id', None) if current_user and not current_user.is_anonymous else None
        self.tenant_id = get_current_tenant_id()
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging."""
        return {
            'error_code': self.error_code,
            'message': str(self),
            'context': self.context,
            'timestamp': self.timestamp.isoformat(),
            'request_id': self.request_id,
            'user_id': self.user_id,
            'tenant_id': self.tenant_id
        }


class ValidationError(ProcessSecurityError):
    """Input validation error."""
    
    def __init__(self, message: str, field: str = None, value: Any = None, rule: str = None):
        super().__init__(message, 'VALIDATION_ERROR')
        self.field = field
        self.value = value
        self.rule = rule
        self.context.update({
            'field': field,
            'value': str(value) if value is not None else None,
            'validation_rule': rule
        })


class AuthorizationError(ProcessSecurityError):
    """Authorization error."""
    
    def __init__(self, message: str, required_permission: str = None, resource: str = None):
        super().__init__(message, 'AUTHORIZATION_ERROR')
        self.required_permission = required_permission
        self.resource = resource
        self.context.update({
            'required_permission': required_permission,
            'resource': resource
        })


class TenantIsolationError(ProcessSecurityError):
    """Tenant isolation violation."""
    
    def __init__(self, message: str, accessed_tenant: str = None, user_tenant: str = None):
        super().__init__(message, 'TENANT_ISOLATION_ERROR')
        self.accessed_tenant = accessed_tenant
        self.user_tenant = user_tenant
        self.context.update({
            'accessed_tenant': accessed_tenant,
            'user_tenant': user_tenant
        })


class RateLimitExceededError(ProcessSecurityError):
    """Rate limit exceeded."""
    
    def __init__(self, message: str, limit: int = None, window: int = None, retry_after: int = None):
        super().__init__(message, 'RATE_LIMIT_EXCEEDED')
        self.limit = limit
        self.window = window
        self.retry_after = retry_after
        self.context.update({
            'rate_limit': limit,
            'time_window': window,
            'retry_after_seconds': retry_after
        })


class ProcessValidator:
    """Comprehensive process input validation."""
    
    # Allowed characters for identifiers
    IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')
    
    # Maximum lengths
    MAX_NAME_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_PROPERTIES_SIZE = 50000  # 50KB
    MAX_EXPRESSION_LENGTH = 1000
    
    # Allowed HTML tags for rich text fields
    ALLOWED_HTML_TAGS = [
        'p', 'br', 'strong', 'em', 'u', 'ol', 'ul', 'li',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote'
    ]
    
    # Dangerous expression patterns
    DANGEROUS_PATTERNS = [
        r'__import__',
        r'eval\s*\(',
        r'exec\s*\(',
        r'subprocess',
        r'os\.',
        r'sys\.',
        r'open\s*\(',
        r'file\s*\(',
        r'input\s*\(',
        r'raw_input\s*\(',
    ]
    
    @classmethod
    def validate_process_definition(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate process definition data."""
        errors = {}
        
        # Validate name
        name = data.get('name', '').strip()
        if not name:
            errors['name'] = 'Process name is required'
        elif len(name) > cls.MAX_NAME_LENGTH:
            errors['name'] = f'Process name must not exceed {cls.MAX_NAME_LENGTH} characters'
        elif not cls.IDENTIFIER_PATTERN.match(name):
            errors['name'] = 'Process name must start with letter and contain only letters, numbers, hyphens, and underscores'
        
        # Validate description
        description = data.get('description', '')
        if description:
            if len(description) > cls.MAX_DESCRIPTION_LENGTH:
                errors['description'] = f'Description must not exceed {cls.MAX_DESCRIPTION_LENGTH} characters'
            # Sanitize HTML
            data['description'] = bleach.clean(
                description, 
                tags=cls.ALLOWED_HTML_TAGS,
                strip=True
            )
        
        # Validate category
        category = data.get('category', '').strip()
        if category and not cls.IDENTIFIER_PATTERN.match(category):
            errors['category'] = 'Category must contain only letters, numbers, hyphens, and underscores'
        
        # Validate process definition (JSON)
        definition = data.get('definition')
        if not definition:
            errors['definition'] = 'Process definition is required'
        else:
            try:
                if isinstance(definition, str):
                    definition = json.loads(definition)
                    data['definition'] = definition
                
                # Validate definition structure
                def_errors = cls._validate_process_definition_structure(definition)
                if def_errors:
                    errors['definition'] = def_errors
                    
            except json.JSONDecodeError as e:
                errors['definition'] = f'Invalid JSON in process definition: {str(e)}'
        
        # Validate properties
        properties = data.get('properties', {})
        if properties:
            try:
                if isinstance(properties, str):
                    properties = json.loads(properties)
                    data['properties'] = properties
                
                properties_size = len(json.dumps(properties).encode('utf-8'))
                if properties_size > cls.MAX_PROPERTIES_SIZE:
                    errors['properties'] = f'Properties size must not exceed {cls.MAX_PROPERTIES_SIZE} bytes'
                    
            except json.JSONDecodeError as e:
                errors['properties'] = f'Invalid JSON in properties: {str(e)}'
        
        if errors:
            raise ValidationError(f"Validation errors: {errors}")
        
        return data
    
    @classmethod
    def _validate_process_definition_structure(cls, definition: Dict[str, Any]) -> List[str]:
        """Validate the internal structure of process definition."""
        errors = []
        
        # Check required fields
        required_fields = ['nodes', 'edges']
        for field in required_fields:
            if field not in definition:
                errors.append(f"Missing required field: {field}")
        
        if errors:
            return errors
        
        # Validate nodes
        nodes = definition.get('nodes', {})
        if not isinstance(nodes, dict):
            errors.append("Nodes must be a dictionary")
        else:
            for node_id, node in nodes.items():
                node_errors = cls._validate_node(node_id, node)
                errors.extend(node_errors)
        
        # Validate edges
        edges = definition.get('edges', [])
        if not isinstance(edges, list):
            errors.append("Edges must be a list")
        else:
            node_ids = set(nodes.keys()) if isinstance(nodes, dict) else set()
            for i, edge in enumerate(edges):
                edge_errors = cls._validate_edge(i, edge, node_ids)
                errors.extend(edge_errors)
        
        return errors
    
    @classmethod
    def _validate_node(cls, node_id: str, node: Dict[str, Any]) -> List[str]:
        """Validate a single process node."""
        errors = []
        
        # Validate node ID
        if not cls.IDENTIFIER_PATTERN.match(node_id):
            errors.append(f"Invalid node ID '{node_id}': must be valid identifier")
        
        # Check required fields
        required_fields = ['type', 'name']
        for field in required_fields:
            if field not in node:
                errors.append(f"Node '{node_id}' missing required field: {field}")
        
        # Validate node type
        valid_types = ['start', 'end', 'task', 'service', 'gateway', 'approval', 'timer']
        node_type = node.get('type')
        if node_type not in valid_types:
            errors.append(f"Node '{node_id}' has invalid type '{node_type}'. Valid types: {valid_types}")
        
        # Validate expressions in node properties
        if 'properties' in node:
            props = node['properties']
            if isinstance(props, dict):
                for key, value in props.items():
                    if isinstance(value, str) and value.startswith('${'):
                        expr_errors = cls._validate_expression(value)
                        if expr_errors:
                            errors.extend([f"Node '{node_id}' property '{key}': {err}" for err in expr_errors])
        
        return errors
    
    @classmethod
    def _validate_edge(cls, index: int, edge: Dict[str, Any], node_ids: Set[str]) -> List[str]:
        """Validate a single process edge."""
        errors = []
        
        # Check required fields
        required_fields = ['from', 'to']
        for field in required_fields:
            if field not in edge:
                errors.append(f"Edge {index} missing required field: {field}")
        
        # Validate node references
        from_node = edge.get('from')
        to_node = edge.get('to')
        
        if from_node not in node_ids:
            errors.append(f"Edge {index} references unknown 'from' node: {from_node}")
        
        if to_node not in node_ids:
            errors.append(f"Edge {index} references unknown 'to' node: {to_node}")
        
        # Validate condition expression
        condition = edge.get('condition')
        if condition:
            expr_errors = cls._validate_expression(condition)
            if expr_errors:
                errors.extend([f"Edge {index} condition: {err}" for err in expr_errors])
        
        return errors
    
    @classmethod
    def _validate_expression(cls, expression: str) -> List[str]:
        """Validate expression for security issues."""
        errors = []
        
        # Check length
        if len(expression) > cls.MAX_EXPRESSION_LENGTH:
            errors.append(f"Expression too long (max {cls.MAX_EXPRESSION_LENGTH} characters)")
        
        # Check for dangerous patterns
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, expression, re.IGNORECASE):
                errors.append(f"Expression contains dangerous pattern: {pattern}")
        
        return errors
    
    @classmethod
    def validate_process_instance_data(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate process instance creation data."""
        errors = {}
        
        # Validate process_definition_id
        if 'process_definition_id' not in data:
            errors['process_definition_id'] = 'Process definition ID is required'
        
        # Validate context data
        context_data = data.get('context_data', {})
        if context_data:
            try:
                if isinstance(context_data, str):
                    context_data = json.loads(context_data)
                    data['context_data'] = context_data
                
                context_size = len(json.dumps(context_data).encode('utf-8'))
                if context_size > cls.MAX_PROPERTIES_SIZE:
                    errors['context_data'] = f'Context data size must not exceed {cls.MAX_PROPERTIES_SIZE} bytes'
                    
            except json.JSONDecodeError as e:
                errors['context_data'] = f'Invalid JSON in context data: {str(e)}'
        
        if errors:
            raise ValidationError(f"Validation errors: {errors}")
        
        return data
    
    @classmethod
    def sanitize_html(cls, html: str) -> str:
        """Sanitize HTML content."""
        return bleach.clean(html, tags=cls.ALLOWED_HTML_TAGS, strip=True)


class ProcessAuthorization:
    """Process authorization and access control."""
    
    PROCESS_PERMISSIONS = {
        'create': 'can_create_process',
        'read': 'can_read_process', 
        'update': 'can_update_process',
        'delete': 'can_delete_process',
        'deploy': 'can_deploy_process',
        'execute': 'can_execute_process',
        'approve': 'can_approve_process',
        'admin': 'can_admin_process'
    }
    
    @classmethod
    def check_permission(cls, permission: str, resource_id: Optional[int] = None) -> bool:
        """Check if current user has permission."""
        if not current_user or not current_user.is_authenticated:
            return False
        
        permission_name = cls.PROCESS_PERMISSIONS.get(permission)
        if not permission_name:
            log.warning(f"Unknown permission requested: {permission}")
            return False
        
        # Check if user has the permission
        if not current_user.has_permission(permission_name):
            return False
        
        # Additional resource-specific checks
        if resource_id and permission in ['read', 'update', 'delete', 'execute']:
            return cls._check_resource_access(permission, resource_id)
        
        return True
    
    @classmethod
    def _check_resource_access(cls, permission: str, resource_id: int) -> bool:
        """Check access to specific resource."""
        try:
            # Get current tenant
            tenant_id = get_current_tenant_id()
            if not tenant_id:
                return False
            
            # Check if resource belongs to current tenant
            if permission in ['read', 'update', 'delete']:
                # For process definitions
                from ..models.process_models import ProcessDefinition
                definition = ProcessDefinition.query.filter(
                    and_(
                        ProcessDefinition.id == resource_id,
                        ProcessDefinition.tenant_id == tenant_id
                    )
                ).first()
                return definition is not None
            
            elif permission == 'execute':
                # For process instances
                from ..models.process_models import ProcessInstance
                instance = ProcessInstance.query.filter(
                    and_(
                        ProcessInstance.id == resource_id,
                        ProcessInstance.tenant_id == tenant_id
                    )
                ).first()
                return instance is not None
                
        except Exception as e:
            log.error(f"Error checking resource access: {e}")
            return False
        
        return True
    
    @classmethod
    def require_permission(cls, permission: str):
        """Decorator to require specific permission."""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                resource_id = kwargs.get('id') or request.view_args.get('id')
                
                if not cls.check_permission(permission, resource_id):
                    raise AuthorizationError(f"Insufficient permissions for {permission}")
                
                return f(*args, **kwargs)
            return decorated_function
        return decorator


class TenantIsolationValidator:
    """Validate tenant isolation for process operations."""
    
    @classmethod
    def validate_tenant_access(cls, model_class, record_id: int) -> bool:
        """Validate that current user can access record within their tenant."""
        try:
            tenant_id = get_current_tenant_id()
            if not tenant_id:
                return False
            
            record = model_class.query.filter(
                and_(
                    model_class.id == record_id,
                    model_class.tenant_id == tenant_id
                )
            ).first()
            
            return record is not None
            
        except Exception as e:
            log.error(f"Error validating tenant access: {e}")
            return False
    
    @classmethod
    def require_tenant_access(cls, model_class):
        """Decorator to require tenant access validation."""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                record_id = kwargs.get('id') or request.view_args.get('id')
                
                if record_id and not cls.validate_tenant_access(model_class, record_id):
                    raise TenantIsolationError("Access denied: resource not found in current tenant")
                
                return f(*args, **kwargs)
            return decorated_function
        return decorator


class RateLimiter:
    """Rate limiting for process operations."""
    
    def __init__(self):
        self.requests = {}  # In production, use Redis or database
        self.cleanup_interval = 60  # seconds
        self.last_cleanup = time.time()
    
    def is_allowed(self, key: str, limit: int, window: int) -> bool:
        """Check if request is within rate limit."""
        now = time.time()
        
        # Cleanup old entries periodically
        if now - self.last_cleanup > self.cleanup_interval:
            self._cleanup_expired_entries()
            self.last_cleanup = now
        
        # Get or create request history for key
        if key not in self.requests:
            self.requests[key] = []
        
        request_history = self.requests[key]
        
        # Remove expired requests
        cutoff = now - window
        request_history[:] = [req_time for req_time in request_history if req_time > cutoff]
        
        # Check if within limit
        if len(request_history) >= limit:
            return False
        
        # Record this request
        request_history.append(now)
        return True
    
    def _cleanup_expired_entries(self):
        """Remove expired entries to prevent memory leaks."""
        now = time.time()
        expired_keys = []
        
        for key, requests in self.requests.items():
            # Remove requests older than 1 hour
            cutoff = now - 3600
            requests[:] = [req_time for req_time in requests if req_time > cutoff]
            
            # Remove empty entries
            if not requests:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.requests[key]
    
    @classmethod
    def get_shared_limiter(cls):
        """Get or create shared rate limiter instance."""
        if not hasattr(cls, '_shared_limiter'):
            cls._shared_limiter = cls()
        return cls._shared_limiter
    
    @classmethod
    def create_rate_limit_decorator(cls, limit: int, window: int):
        """Create a rate limiting decorator using shared limiter."""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                limiter = cls.get_shared_limiter()  # Use shared instance
                
                # Create key from user and endpoint
                user_id = getattr(current_user, 'id', 'anonymous') if current_user else 'anonymous'
                endpoint = request.endpoint or f.__name__
                key = f"rate_limit:{user_id}:{endpoint}"
                
                if not limiter.is_allowed(key, limit, window):
                    raise RateLimitExceededError(f"Rate limit exceeded: {limit} requests per {window} seconds")
                
                return f(*args, **kwargs)
            return decorated_function
        return decorator


class ProcessAuditLogger:
    """Audit logging for process operations."""
    
    SENSITIVE_OPERATIONS = {
        'process_create', 'process_update', 'process_delete', 'process_deploy',
        'process_start', 'process_terminate', 'approval_grant', 'approval_deny'
    }
    
    @classmethod
    def log_operation(cls, operation: str, resource_type: str, resource_id: Optional[int] = None, 
                     details: Optional[Dict[str, Any]] = None, success: bool = True):
        """Log process operation for audit trail."""
        try:
            # Prepare audit record
            audit_data = {
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'operation': operation,
                'resource_type': resource_type,
                'resource_id': resource_id,
                'user_id': getattr(current_user, 'id', None) if current_user else None,
                'username': getattr(current_user, 'username', 'anonymous') if current_user else 'anonymous',
                'tenant_id': get_current_tenant_id(),
                'ip_address': request.remote_addr if request else None,
                'user_agent': request.headers.get('User-Agent') if request else None,
                'success': success,
                'details': details or {}
            }
            
            # Log sensitive operations at WARNING level
            log_level = logging.WARNING if operation in cls.SENSITIVE_OPERATIONS else logging.INFO
            log.log(log_level, f"AUDIT: {operation} on {resource_type}:{resource_id}", extra=audit_data)
            
            # Store in database for persistent audit trail
            cls._store_audit_record(audit_data)
            
        except Exception as e:
            log.error(f"Failed to log audit operation: {e}")
    
    @classmethod
    def _store_audit_record(cls, audit_data: Dict[str, Any]):
        """Store audit record in database."""
        try:
            from pgappforge import db
            
            audit_log = ProcessAuditLog(
                timestamp=datetime.now(tz=timezone.utc),
                operation=audit_data['operation'],
                resource_type=audit_data['resource_type'],
                resource_id=audit_data['resource_id'],
                user_id=audit_data['user_id'],
                username=audit_data['username'],
                tenant_id=audit_data['tenant_id'],
                ip_address=audit_data['ip_address'],
                user_agent=audit_data['user_agent'],
                success=audit_data['success'],
                details=json.dumps(audit_data['details'])
            )
            
            db.session.add(audit_log)
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()  # Add rollback on failure
            log.error(f"Failed to store audit record: {e}")
            # Don't re-raise - audit failure shouldn't break main operation
    
    @classmethod
    def audit(cls, operation: str, resource_type: str, resource_id: Optional[int] = None):
        """Decorator for audit logging."""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                success = True
                error_details = None
                
                try:
                    result = f(*args, **kwargs)
                    return result
                except Exception as e:
                    success = False
                    error_details = {'error': str(e), 'type': type(e).__name__}
                    raise
                finally:
                    # Extract resource ID from result or kwargs if not provided
                    actual_resource_id = resource_id
                    if actual_resource_id is None:
                        actual_resource_id = kwargs.get('id') or getattr(kwargs.get('result'), 'id', None)
                    
                    cls.log_operation(
                        operation=operation,
                        resource_type=resource_type,
                        resource_id=actual_resource_id,
                        details=error_details,
                        success=success
                    )
            return decorated_function
        return decorator


# Global rate limiters for different operation types
process_read_limiter = RateLimiter.create_rate_limit_decorator(100, 60)    # 100 reads per minute
process_write_limiter = RateLimiter.create_rate_limit_decorator(20, 60)    # 20 writes per minute
process_deploy_limiter = RateLimiter.create_rate_limit_decorator(5, 300)   # 5 deployments per 5 minutes
process_execute_limiter = RateLimiter.create_rate_limit_decorator(10, 60)  # 10 executions per minute


def secure_process_operation(operation: str, resource_type: str = 'process', 
                           permission: Optional[str] = None, 
                           model_class: Optional[type] = None,
                           rate_limiter: Optional[callable] = None):
    """
    Combined security decorator for process operations.
    
    Args:
        operation: Operation name for audit logging
        resource_type: Type of resource for audit logging
        permission: Required permission (defaults to operation)
        model_class: Model class for tenant isolation validation
        rate_limiter: Rate limiter decorator to apply
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Apply rate limiting if specified
            if rate_limiter:
                rate_limiter(lambda: None)()
            
            # Check permissions
            perm = permission or operation
            if not ProcessAuthorization.check_permission(perm, kwargs.get('id')):
                raise AuthorizationError(f"Insufficient permissions for {operation}")
            
            # Validate tenant isolation if model class provided
            if model_class and kwargs.get('id'):
                if not TenantIsolationValidator.validate_tenant_access(model_class, kwargs['id']):
                    raise TenantIsolationError("Access denied: resource not found in current tenant")
            
            # Execute with audit logging
            success = True
            error_details = None
            result = None
            
            try:
                result = f(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_details = {'error': str(e), 'type': type(e).__name__}
                raise
            finally:
                # Log audit trail
                resource_id = kwargs.get('id') or getattr(result, 'id', None)
                ProcessAuditLogger.log_operation(
                    operation=operation,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=error_details,
                    success=success
                )
        
        return decorated_function
    return decorator