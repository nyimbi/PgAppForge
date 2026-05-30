"""
Process Security Integration.

Integrates comprehensive security measures with existing process
views and APIs, providing a unified security layer.
"""

import logging
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Dict, Any, Optional, List, Union

from flask import request, jsonify, current_app
from flask_login import current_user
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .validation import (
    ProcessValidator, ProcessAuthorization, TenantIsolationValidator,
    ProcessAuditLogger, RateLimiter, secure_process_operation,
    ProcessSecurityError, ValidationError, AuthorizationError,
    TenantIsolationError, RateLimitExceededError,
    process_read_limiter, process_write_limiter, process_deploy_limiter, process_execute_limiter
)
from ..models.process_models import ProcessDefinition, ProcessInstance, ProcessStep, ProcessPool, ProcessLane
from ..models.audit_models import ProcessSecurityEvent
from flask_appbuilder import db

log = logging.getLogger(__name__)


class ProcessSecurityManager:
    """
    Central security manager for process operations.
    
    Coordinates all security aspects including validation, authorization,
    audit logging, and security event handling.
    """
    
    def __init__(self):
        self.validator = ProcessValidator()
        self.rate_limiter = RateLimiter()
        self.security_events_cache = {}  # In production, use Redis
    
    def validate_and_secure_operation(self, operation: str, data: Optional[Dict[str, Any]] = None,
                                    resource_id: Optional[int] = None, 
                                    resource_type: str = 'process') -> Dict[str, Any]:
        """
        Comprehensive security validation for process operations.
        
        Args:
            operation: The operation being performed
            data: Request data to validate
            resource_id: ID of resource being accessed
            resource_type: Type of resource
            
        Returns:
            Validated and sanitized data
            
        Raises:
            ProcessSecurityError: For any security violation
        """
        try:
            # 1. Rate limiting check
            self._check_rate_limits(operation)
            
            # 2. Authentication check
            if not current_user or not current_user.is_authenticated:
                self._record_security_event(
                    ProcessSecurityEvent.TYPE_AUTH_FAILURE,
                    f"Unauthenticated access attempt to {operation}",
                    ProcessSecurityEvent.SEVERITY_WARNING
                )
                raise AuthorizationError("Authentication required")
            
            # 3. Authorization check
            if not ProcessAuthorization.check_permission(operation, resource_id):
                self._record_security_event(
                    ProcessSecurityEvent.TYPE_AUTH_FAILURE,
                    f"Unauthorized access attempt to {operation} by user {current_user.username}",
                    ProcessSecurityEvent.SEVERITY_WARNING,
                    resource_type=resource_type,
                    resource_id=resource_id
                )
                raise AuthorizationError(f"Insufficient permissions for {operation}")
            
            # 4. Tenant isolation validation
            if resource_id:
                model_class = self._get_model_class(resource_type)
                if model_class and not TenantIsolationValidator.validate_tenant_access(model_class, resource_id):
                    self._record_security_event(
                        ProcessSecurityEvent.TYPE_TENANT_VIOLATION,
                        f"Tenant isolation violation: {operation} on {resource_type}:{resource_id}",
                        ProcessSecurityEvent.SEVERITY_ERROR,
                        resource_type=resource_type,
                        resource_id=resource_id
                    )
                    raise TenantIsolationError("Access denied: resource not found in current tenant")
            
            # 5. Data validation and sanitization
            validated_data = None
            if data:
                validated_data = self._validate_operation_data(operation, data)
            
            # 6. Log successful security validation
            ProcessAuditLogger.log_operation(
                operation=f"security_validation_{operation}",
                resource_type=resource_type,
                resource_id=resource_id,
                details={'validation_passed': True},
                success=True
            )
            
            return validated_data or {}
            
        except ProcessSecurityError:
            # Re-raise security errors as-is
            raise
        except Exception as e:
            # Log unexpected errors as security events
            self._record_security_event(
                ProcessSecurityEvent.TYPE_SUSPICIOUS_ACTIVITY,
                f"Unexpected error during security validation: {str(e)}",
                ProcessSecurityEvent.SEVERITY_ERROR,
                resource_type=resource_type,
                resource_id=resource_id
            )
            raise ProcessSecurityError(f"Security validation failed: {str(e)}")
    
    def _check_rate_limits(self, operation: str):
        """Check rate limits for operation."""
        user_id = getattr(current_user, 'id', 'anonymous') if current_user else 'anonymous'
        endpoint = request.endpoint or operation
        key = f"rate_limit:{user_id}:{endpoint}"
        
        # Determine appropriate limits based on operation
        if operation in ['read', 'list', 'get']:
            limit, window = 100, 60  # 100 requests per minute
        elif operation in ['deploy']:
            limit, window = 5, 300   # 5 requests per 5 minutes
        elif operation in ['execute', 'start', 'terminate']:
            limit, window = 10, 60   # 10 requests per minute
        else:
            limit, window = 20, 60   # 20 requests per minute for other operations
        
        if not self.rate_limiter.is_allowed(key, limit, window):
            self._record_security_event(
                ProcessSecurityEvent.TYPE_RATE_LIMIT,
                f"Rate limit exceeded for {operation} by user {getattr(current_user, 'username', 'anonymous')}",
                ProcessSecurityEvent.SEVERITY_WARNING,
                details={'limit': limit, 'window': window}
            )
            raise RateLimitExceededError(f"Rate limit exceeded: {limit} requests per {window} seconds")
    
    def _get_model_class(self, resource_type: str):
        """Get model class for resource type."""
        model_mapping = {
            'process_definition': ProcessDefinition,
            'process': ProcessDefinition,
            'process_instance': ProcessInstance,
            'instance': ProcessInstance,
            'process_step': ProcessStep,
            'step': ProcessStep
        }
        return model_mapping.get(resource_type)
    
    def _validate_operation_data(self, operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data for specific operations."""
        try:
            if operation in ['create', 'update'] and 'definition' in data:
                # Process definition validation
                return ProcessValidator.validate_process_definition(data)
            elif operation == 'start' or 'context_data' in data:
                # Process instance validation
                return ProcessValidator.validate_process_instance_data(data)
            else:
                # Generic validation - sanitize any HTML content
                for key, value in data.items():
                    if isinstance(value, str) and any(tag in value.lower() for tag in ['<', '>', '&']):
                        data[key] = ProcessValidator.sanitize_html(value)
                return data
                
        except ValidationError:
            self._record_security_event(
                ProcessSecurityEvent.TYPE_VALIDATION_ERROR,
                f"Validation failed for {operation}",
                ProcessSecurityEvent.SEVERITY_WARNING,
                details={'validation_errors': str(data)}
            )
            raise
    
    def _record_security_event(self, event_type: str, message: str, severity: str,
                             resource_type: Optional[str] = None, resource_id: Optional[int] = None,
                             details: Optional[Dict[str, Any]] = None):
        """Record a security event."""
        try:
            event = ProcessSecurityEvent(
                event_type=event_type,
                severity=severity,
                resource_type=resource_type,
                resource_id=resource_id,
                user_id=getattr(current_user, 'id', None) if current_user else None,
                username=getattr(current_user, 'username', 'anonymous') if current_user else 'anonymous',
                tenant_id=getattr(current_user, 'tenant_id', None) if hasattr(current_user, 'tenant_id') else None,
                ip_address=request.remote_addr if request else None,
                user_agent=request.headers.get('User-Agent') if request else None,
                endpoint=request.endpoint if request else None,
                message=message
            )
            
            if details:
                event.details_dict = details
            
            db.session.add(event)
            db.session.commit()
            
            # Log critical events immediately
            if severity in [ProcessSecurityEvent.SEVERITY_ERROR, ProcessSecurityEvent.SEVERITY_CRITICAL]:
                log.error(f"SECURITY EVENT [{severity.upper()}]: {message}")
            
        except Exception as e:
            log.error(f"Failed to record security event: {e}")


class PoolLaneSecurityManager:
    """
    Security manager for Pool/Lane operations with role-based access control.
    
    Integrates with Flask-AppBuilder's security manager to provide
    role-based lane assignment and pool access validation.
    """
    
    def __init__(self):
        self.role_cache = {}  # Cache for role lookups
        self.lane_role_cache = {}  # Cache for lane-role mappings
        self.cache_timeout = 300  # 5 minutes
    
    def get_available_roles(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get available roles from Flask-AppBuilder security manager."""
        from flask_appbuilder.security import current_user
        from flask import current_app
        
        try:
            # Get the Flask-AppBuilder security manager
            fab = current_app.extensions.get('appbuilder')
            if not fab or not fab.sm:
                log.warning("Flask-AppBuilder security manager not available")
                return []
            
            security_manager = fab.sm
            
            # Get all roles
            roles = security_manager.get_all_roles()
            
            # Filter roles based on tenant if multi-tenant
            available_roles = []
            for role in roles:
                role_data = {
                    'id': role.id,
                    'name': role.name,
                    'description': getattr(role, 'description', ''),
                    'permissions': [p.permission.name for p in role.permissions] if hasattr(role, 'permissions') else []
                }
                
                # Add tenant filtering if applicable
                if tenant_id and hasattr(role, 'tenant_id'):
                    if role.tenant_id == tenant_id or role.tenant_id is None:
                        available_roles.append(role_data)
                else:
                    available_roles.append(role_data)
            
            # Cache the results
            cache_key = f"roles_{tenant_id or 'global'}"
            self.role_cache[cache_key] = {
                'data': available_roles,
                'timestamp': time.time()
            }
            
            return available_roles
            
        except Exception as e:
            log.error(f"Failed to get available roles: {str(e)}")
            return []
    
    def validate_lane_role_assignment(self, lane_id: int, role_name: str, user_id: Optional[int] = None) -> bool:
        """
        Validate that a role can be assigned to a lane.
        
        Args:
            lane_id: ID of the lane
            role_name: Name of the role to assign
            user_id: Optional user ID for additional validation
            
        Returns:
            True if assignment is valid, False otherwise
        """
        try:
            # Get lane from database
            lane = db.session.query(ProcessLane).filter_by(
                id=lane_id,
                tenant_id=getattr(current_user, 'tenant_id', None) if hasattr(current_user, 'tenant_id') else None
            ).first()
            
            if not lane:
                log.warning(f"Lane {lane_id} not found for role assignment validation")
                return False
            
            # Get role from Flask-AppBuilder
            from flask import current_app
            fab = current_app.extensions.get('appbuilder')
            if not fab or not fab.sm:
                log.warning("Flask-AppBuilder security manager not available for role validation")
                return False
            
            role = fab.sm.find_role(role_name)
            if not role:
                log.warning(f"Role {role_name} not found in security manager")
                return False
            
            # Check if current user has permission to assign this role
            if user_id and hasattr(current_user, 'id') and current_user.id != user_id:
                if not fab.sm.has_access('can_edit', 'ProcessLane', user=current_user):
                    log.warning(f"User {current_user.username} lacks permission to assign roles to lanes")
                    return False
            
            # Validate role compatibility with lane type
            if lane.lane_type == 'system' and not self._is_system_role(role):
                log.warning(f"Role {role_name} is not compatible with system lane")
                return False
            
            return True
            
        except Exception as e:
            log.error(f"Error validating lane role assignment: {str(e)}")
            return False
    
    def assign_role_to_lane(self, lane_id: int, role_name: str) -> bool:
        """
        Assign a role to a lane with security validation.
        
        Args:
            lane_id: ID of the lane
            role_name: Name of the role to assign
            
        Returns:
            True if assignment successful, False otherwise
        """
        try:
            # Validate the assignment
            if not self.validate_lane_role_assignment(lane_id, role_name):
                return False
            
            # Get and update the lane
            lane = db.session.query(ProcessLane).filter_by(
                id=lane_id,
                tenant_id=getattr(current_user, 'tenant_id', None) if hasattr(current_user, 'tenant_id') else None
            ).first()
            
            if not lane:
                return False
            
            # Update lane with role assignment
            old_role = lane.assigned_role
            lane.assigned_role = role_name
            lane.updated_at = datetime.now(tz=timezone.utc)
            lane.updated_by = getattr(current_user, 'id', None) if current_user else None
            
            db.session.commit()
            
            # Log the role assignment
            ProcessAuditLogger.log_operation(
                operation='assign_lane_role',
                resource_type='process_lane',
                resource_id=lane_id,
                details={
                    'old_role': old_role,
                    'new_role': role_name,
                    'lane_name': lane.name
                },
                success=True
            )
            
            # Clear cache
            self._clear_lane_role_cache(lane_id)
            
            return True
            
        except Exception as e:
            log.error(f"Failed to assign role {role_name} to lane {lane_id}: {str(e)}")
            db.session.rollback()
            return False
    
    def check_lane_access(self, lane_id: int, user_id: Optional[int] = None) -> bool:
        """
        Check if a user has access to a specific lane.
        
        Args:
            lane_id: ID of the lane
            user_id: User ID to check (defaults to current user)
            
        Returns:
            True if user has access, False otherwise
        """
        try:
            user = current_user if user_id is None else self._get_user_by_id(user_id)
            if not user:
                return False
            
            # Get lane with role assignment
            lane = db.session.query(ProcessLane).filter_by(
                id=lane_id,
                tenant_id=getattr(user, 'tenant_id', None) if hasattr(user, 'tenant_id') else None
            ).first()
            
            if not lane:
                return False
            
            # If no role assigned to lane, check general process permissions
            if not lane.assigned_role:
                from flask import current_app
                fab = current_app.extensions.get('appbuilder')
                if fab and fab.sm:
                    return fab.sm.has_access('can_read', 'ProcessInstance', user=user)
                return False
            
            # Check if user has the assigned role
            user_roles = [role.name for role in user.roles] if hasattr(user, 'roles') else []
            
            # Allow access if user has the assigned role or admin privileges
            has_lane_role = lane.assigned_role in user_roles
            has_admin_role = any(role in ['Admin', 'ProcessAdmin'] for role in user_roles)
            
            return has_lane_role or has_admin_role
            
        except Exception as e:
            log.error(f"Error checking lane access for lane {lane_id}: {str(e)}")
            return False
    
    def get_user_accessible_lanes(self, pool_id: Optional[int] = None, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all lanes accessible to a user.
        
        Args:
            pool_id: Optional pool ID to filter lanes
            user_id: User ID to check (defaults to current user)
            
        Returns:
            List of accessible lane data
        """
        try:
            user = current_user if user_id is None else self._get_user_by_id(user_id)
            if not user:
                return []
            
            # Build query
            query = db.session.query(ProcessLane)
            
            # Filter by tenant
            if hasattr(user, 'tenant_id') and user.tenant_id:
                query = query.filter_by(tenant_id=user.tenant_id)
            
            # Filter by pool if specified
            if pool_id:
                query = query.filter_by(pool_id=pool_id)
            
            lanes = query.all()
            accessible_lanes = []
            
            for lane in lanes:
                if self.check_lane_access(lane.id, user_id):
                    accessible_lanes.append({
                        'id': lane.id,
                        'name': lane.name,
                        'pool_id': lane.pool_id,
                        'assigned_role': lane.assigned_role,
                        'workload_balancing': lane.workload_balancing,
                        'lane_type': getattr(lane, 'lane_type', 'user')
                    })
            
            return accessible_lanes
            
        except Exception as e:
            log.error(f"Error getting accessible lanes: {str(e)}")
            return []
    
    def validate_pool_access(self, pool_id: int, operation: str = 'read', user_id: Optional[int] = None) -> bool:
        """
        Validate user access to a process pool.
        
        Args:
            pool_id: ID of the pool
            operation: Operation being performed (read, write, execute)
            user_id: User ID to check (defaults to current user)
            
        Returns:
            True if access allowed, False otherwise
        """
        try:
            user = current_user if user_id is None else self._get_user_by_id(user_id)
            if not user:
                return False
            
            # Get pool
            pool = db.session.query(ProcessPool).filter_by(
                id=pool_id,
                tenant_id=getattr(user, 'tenant_id', None) if hasattr(user, 'tenant_id') else None
            ).first()
            
            if not pool:
                return False
            
            # Check if user has access to at least one lane in the pool
            pool_lanes = db.session.query(ProcessLane).filter_by(pool_id=pool_id).all()
            
            if not pool_lanes:
                # No lanes, check general pool permissions
                from flask import current_app
                fab = current_app.extensions.get('appbuilder')
                if fab and fab.sm:
                    permission_map = {
                        'read': 'can_show',
                        'write': 'can_edit',
                        'execute': 'can_edit'
                    }
                    return fab.sm.has_access(permission_map.get(operation, 'can_show'), 'ProcessPool', user=user)
                return False
            
            # Check access to at least one lane
            for lane in pool_lanes:
                if self.check_lane_access(lane.id, user_id):
                    return True
            
            return False
            
        except Exception as e:
            log.error(f"Error validating pool access: {str(e)}")
            return False
    
    def _is_system_role(self, role) -> bool:
        """Check if a role is a system role."""
        system_roles = ['Admin', 'ProcessAdmin', 'SystemUser']
        return role.name in system_roles if role else False
    
    def _get_user_by_id(self, user_id: int):
        """Get user by ID from Flask-AppBuilder."""
        try:
            from flask import current_app
            fab = current_app.extensions.get('appbuilder')
            if fab and fab.sm:
                return fab.sm.get_user_by_id(user_id)
            return None
        except Exception as e:
            log.error(f"Failed to get user by ID {user_id}: {str(e)}")
            return None
    
    def _clear_lane_role_cache(self, lane_id: int):
        """Clear cache entries for a specific lane."""
        keys_to_remove = [key for key in self.lane_role_cache.keys() if str(lane_id) in key]
        for key in keys_to_remove:
            del self.lane_role_cache[key]


# Global security manager instances
security_manager = ProcessSecurityManager()
pool_lane_security_manager = PoolLaneSecurityManager()


def secure_api_endpoint(operation: str, resource_type: str = 'process', 
                       require_data: bool = False):
    """
    Decorator for securing API endpoints.
    
    Args:
        operation: The operation being performed
        resource_type: Type of resource being accessed
        require_data: Whether to validate request data
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # Extract resource ID from kwargs or URL
                resource_id = kwargs.get('id') or kwargs.get('pk') or request.view_args.get('id')
                
                # Get request data if required
                request_data = None
                if require_data:
                    if request.is_json:
                        request_data = request.get_json() or {}
                    else:
                        request_data = request.form.to_dict()
                
                # Perform security validation
                validated_data = security_manager.validate_and_secure_operation(
                    operation=operation,
                    data=request_data,
                    resource_id=resource_id,
                    resource_type=resource_type
                )
                
                # Add validated data to kwargs
                if validated_data:
                    kwargs['validated_data'] = validated_data
                
                # Execute the original function
                result = f(*args, **kwargs)
                
                # Log successful operation
                ProcessAuditLogger.log_operation(
                    operation=operation,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    success=True
                )
                
                return result
                
            except ProcessSecurityError as e:
                # Return appropriate HTTP error response
                status_code = 403  # Forbidden by default
                if isinstance(e, ValidationError):
                    status_code = 400  # Bad Request
                elif isinstance(e, AuthorizationError):
                    status_code = 403  # Forbidden
                elif isinstance(e, TenantIsolationError):
                    status_code = 404  # Not Found (hide existence)
                elif isinstance(e, RateLimitExceededError):
                    status_code = 429  # Too Many Requests
                
                # Log failed operation
                ProcessAuditLogger.log_operation(
                    operation=operation,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details={'error': str(e), 'error_type': type(e).__name__},
                    success=False
                )
                
                return jsonify({
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'operation': operation
                }), status_code
                
            except Exception as e:
                # Handle unexpected errors
                log.error(f"Unexpected error in secured endpoint {f.__name__}: {e}")
                
                # Record as security event
                security_manager._record_security_event(
                    ProcessSecurityEvent.TYPE_SUSPICIOUS_ACTIVITY,
                    f"Unexpected error in {operation}: {str(e)}",
                    ProcessSecurityEvent.SEVERITY_ERROR,
                    resource_type=resource_type,
                    resource_id=resource_id
                )
                
                return jsonify({
                    'error': 'Internal server error',
                    'operation': operation
                }), 500
        
        return decorated_function
    return decorator


def secure_view_method(operation: str, resource_type: str = 'process'):
    """
    Decorator for securing Flask-AppBuilder view methods.
    
    Args:
        operation: The operation being performed
        resource_type: Type of resource being accessed
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(self, *args, **kwargs):
            try:
                # Extract resource ID
                resource_id = kwargs.get('id') or getattr(self, 'pk', None)
                
                # Perform security validation
                security_manager.validate_and_secure_operation(
                    operation=operation,
                    resource_id=resource_id,
                    resource_type=resource_type
                )
                
                # Execute the original method
                result = f(self, *args, **kwargs)
                
                # Log successful operation
                ProcessAuditLogger.log_operation(
                    operation=operation,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    success=True
                )
                
                return result
                
            except ProcessSecurityError as e:
                # Flash error message for web interface
                from flask import flash
                flash(str(e), 'error')
                
                # Log failed operation
                ProcessAuditLogger.log_operation(
                    operation=operation,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details={'error': str(e), 'error_type': type(e).__name__},
                    success=False
                )
                
                # Redirect to safe location
                from flask import redirect, url_for
                return redirect(url_for('ProcessDefinitionView.list'))
                
        return decorated_function
    return decorator


class SecurityHeaders:
    """Security headers for process-related responses."""
    
    SECURITY_HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
        'Referrer-Policy': 'strict-origin-when-cross-origin'
    }
    
    @classmethod
    def add_security_headers(cls, response):
        """Add security headers to response."""
        for header, value in cls.SECURITY_HEADERS.items():
            response.headers[header] = value
        return response
    
    @classmethod
    def secure_response(cls):
        """Decorator to add security headers to responses."""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                response = f(*args, **kwargs)
                return cls.add_security_headers(response)
            return decorated_function
        return decorator


def init_process_security(app):
    """Initialize process security system with Flask app."""
    
    # Register error handlers
    @app.errorhandler(ProcessSecurityError)
    def handle_security_error(e):
        """Handle process security errors."""
        if request.is_json:
            return jsonify({
                'error': str(e),
                'error_type': type(e).__name__
            }), 403
        else:
            from flask import flash, redirect, url_for
            flash(str(e), 'error')
            return redirect(url_for('index'))
    
    @app.errorhandler(ValidationError)
    def handle_validation_error(e):
        """Handle validation errors."""
        if request.is_json:
            return jsonify({
                'error': str(e),
                'error_type': 'ValidationError'
            }), 400
        else:
            from flask import flash, redirect
            flash(str(e), 'error')
            return redirect(request.referrer or url_for('index'))
    
    @app.errorhandler(RateLimitExceededError)
    def handle_rate_limit_error(e):
        """Handle rate limit errors."""
        return jsonify({
            'error': str(e),
            'error_type': 'RateLimitExceededError'
        }), 429
    
    # Add security headers to all responses
    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses."""
        return SecurityHeaders.add_security_headers(response)
    
    log.info("Process security system initialized")


# Export commonly used decorators and classes
__all__ = [
    'ProcessSecurityManager',
    'PoolLaneSecurityManager',
    'secure_api_endpoint',
    'secure_view_method',
    'secure_process_operation',
    'SecurityHeaders',
    'init_process_security',
    'security_manager',
    'pool_lane_security_manager'
]