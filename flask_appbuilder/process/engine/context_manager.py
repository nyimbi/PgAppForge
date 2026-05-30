"""
Process Context Manager.

Manages process execution context, variable resolution, data flow
between nodes, and secure context isolation for multi-tenant processes.
"""

import logging
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union
import threading
from copy import deepcopy

from flask_appbuilder import db
from flask_appbuilder.models.tenant_context import get_current_tenant_id

from ..models.process_models import ProcessInstance, ProcessStep

log = logging.getLogger(__name__)


class ContextManagerError(Exception):
    """Base exception for context manager errors."""
    pass


class VariableNotFoundError(ContextManagerError):
    """Exception raised when a required variable is not found."""
    pass


class ContextIsolationError(ContextManagerError):
    """Exception raised when context isolation is violated."""
    pass


class ProcessContextManager:
    """
    Manages process execution context and data flow.
    
    Provides secure variable storage, context isolation, and data flow
    management for multi-tenant business processes.
    """
    
    def __init__(self, redis_client=None):
        """Initialize context manager."""
        self.redis = redis_client
        self._lock = threading.RLock()
        self._context_cache: Dict[int, Dict[str, Any]] = {}
        self._variable_validators = {}
        self._context_hooks = {}
        
        # Configuration
        self.config = {
            'max_context_size_mb': 10,  # Max context size in MB
            'variable_ttl_seconds': 3600,  # Variable TTL in Redis
            'enable_context_encryption': True,
            'audit_variable_access': True
        }
        
        log.debug("Process Context Manager initialized")
    
    async def initialize_context(self, instance: ProcessInstance,
                                initial_variables: Dict[str, Any] = None):
        """Initialize process execution context."""
        try:
            context_id = instance.id
            tenant_id = instance.tenant_id
            
            # Initialize base context
            base_context = {
                'process_instance_id': instance.id,
                'process_definition_id': instance.process_definition_id,
                'tenant_id': tenant_id,
                'initiated_by': instance.initiated_by,
                'started_at': instance.started_at.isoformat() if instance.started_at else None,
                'priority': instance.priority,
                'input_data': instance.input_data or {},
                'variables': initial_variables or {},
                'system_variables': self._get_system_variables(instance)
            }
            
            # Store context
            await self._store_context(context_id, base_context)
            
            # Update instance context reference
            instance.context = {'context_id': context_id}
            db.session.commit()
            
            log.debug(f"Initialized context for process instance {instance.id}")
            
        except Exception as e:
            log.error(f"Failed to initialize context for instance {instance.id}: {str(e)}")
            raise ContextManagerError(f"Context initialization failed: {str(e)}")
    
    async def get_variable(self, instance_id: int, variable_name: str,
                          default: Any = None, required: bool = False) -> Any:
        """Get variable value from process context."""
        try:
            context = await self._get_context(instance_id)
            
            # Check in variables first
            if variable_name in context.get('variables', {}):
                value = context['variables'][variable_name]
                
                if self.config['audit_variable_access']:
                    await self._audit_variable_access(instance_id, variable_name, 'read', value)
                
                return value
            
            # Check in input_data
            if variable_name in context.get('input_data', {}):
                return context['input_data'][variable_name]
            
            # Check in system variables
            if variable_name in context.get('system_variables', {}):
                return context['system_variables'][variable_name]
            
            # Variable not found
            if required:
                raise VariableNotFoundError(f"Required variable '{variable_name}' not found")
            
            return default
            
        except Exception as e:
            log.error(f"Error getting variable '{variable_name}' for instance {instance_id}: {str(e)}")
            if required:
                raise
            return default
    
    async def set_variable(self, instance_id: int, variable_name: str, 
                          value: Any, step_id: int = None) -> bool:
        """Set variable value in process context."""
        try:
            # Validate variable name
            if not self._is_valid_variable_name(variable_name):
                raise ContextManagerError(f"Invalid variable name: {variable_name}")
            
            # Validate variable value
            if not await self._validate_variable_value(variable_name, value):
                raise ContextManagerError(f"Invalid value for variable: {variable_name}")
            
            # Get current context
            context = await self._get_context(instance_id)
            
            # Ensure tenant isolation
            if not await self._validate_tenant_access(instance_id):
                raise ContextIsolationError("Tenant access validation failed")
            
            # Set variable
            if 'variables' not in context:
                context['variables'] = {}
            
            old_value = context['variables'].get(variable_name)
            context['variables'][variable_name] = value
            
            # Add metadata
            context['variables'][f'__{variable_name}__meta'] = {
                'updated_at': datetime.now(tz=timezone.utc).isoformat(),
                'updated_by_step': step_id,
                'previous_value': old_value,
                'type': type(value).__name__
            }
            
            # Store updated context
            await self._store_context(instance_id, context)
            
            # Audit variable change
            if self.config['audit_variable_access']:
                await self._audit_variable_access(instance_id, variable_name, 'write', value, step_id)
            
            # Execute variable change hooks
            await self._execute_variable_hooks(instance_id, variable_name, old_value, value)
            
            log.debug(f"Set variable '{variable_name}' for instance {instance_id}")
            return True
            
        except Exception as e:
            log.error(f"Error setting variable '{variable_name}' for instance {instance_id}: {str(e)}")
            raise ContextManagerError(f"Failed to set variable: {str(e)}")
    
    async def get_all_variables(self, instance_id: int) -> Dict[str, Any]:
        """Get all variables from process context."""
        try:
            context = await self._get_context(instance_id)
            
            all_variables = {}
            
            # Include input data
            all_variables.update(context.get('input_data', {}))
            
            # Include process variables
            variables = context.get('variables', {})
            for key, value in variables.items():
                if not key.startswith('__') or not key.endswith('__meta'):
                    all_variables[key] = value
            
            # Include system variables (read-only)
            system_vars = context.get('system_variables', {})
            all_variables.update({f'system.{k}': v for k, v in system_vars.items()})
            
            return all_variables
            
        except Exception as e:
            log.error(f"Error getting all variables for instance {instance_id}: {str(e)}")
            return {}
    
    async def update_step_output(self, instance_id: int, step_id: int,
                                output_data: Dict[str, Any]) -> bool:
        """Update context with step output data."""
        try:
            if not output_data:
                return True
            
            context = await self._get_context(instance_id)
            
            # Store step outputs for reference
            if 'step_outputs' not in context:
                context['step_outputs'] = {}
            
            context['step_outputs'][str(step_id)] = {
                'data': output_data,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
            
            # Merge output data into process variables
            for key, value in output_data.items():
                await self.set_variable(instance_id, key, value, step_id)
            
            await self._store_context(instance_id, context)
            
            log.debug(f"Updated context with output from step {step_id}")
            return True
            
        except Exception as e:
            log.error(f"Error updating step output for instance {instance_id}: {str(e)}")
            return False
    
    async def resolve_expression(self, instance_id: int, expression: str) -> Any:
        """Resolve variable expressions in context."""
        try:
            if not isinstance(expression, str):
                return expression
            
            # Simple variable resolution: ${variable_name}
            import re
            
            def replace_variable(match):
                var_name = match.group(1)
                try:
                    # Use asyncio to get variable value
                    loop = asyncio.get_event_loop()
                    value = loop.run_until_complete(
                        self.get_variable(instance_id, var_name, required=True)
                    )
                    return str(value)
                except:
                    return match.group(0)  # Return original if resolution fails
            
            # Replace ${variable} patterns
            resolved = re.sub(r'\$\{([^}]+)\}', replace_variable, expression)
            
            # Try to convert to appropriate type
            if resolved.isdigit():
                return int(resolved)
            elif resolved.replace('.', '', 1).isdigit():
                return float(resolved)
            elif resolved.lower() in ['true', 'false']:
                return resolved.lower() == 'true'
            
            return resolved
            
        except Exception as e:
            log.warning(f"Error resolving expression '{expression}': {str(e)}")
            return expression
    
    async def create_context_snapshot(self, instance_id: int) -> Dict[str, Any]:
        """Create a snapshot of current context state."""
        try:
            context = await self._get_context(instance_id)
            
            snapshot = {
                'snapshot_id': f"snapshot_{instance_id}_{int(datetime.now(tz=timezone.utc).timestamp())}",
                'instance_id': instance_id,
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'context': deepcopy(context)
            }
            
            # Store snapshot if Redis is available
            if self.redis:
                snapshot_key = f"process_context_snapshot:{instance_id}:{snapshot['snapshot_id']}"
                self.redis.setex(
                    snapshot_key, 
                    86400,  # 24 hours
                    json.dumps(snapshot, default=str)
                )
            
            return snapshot
            
        except Exception as e:
            log.error(f"Error creating context snapshot for instance {instance_id}: {str(e)}")
            raise ContextManagerError(f"Failed to create context snapshot: {str(e)}")
    
    async def restore_context_snapshot(self, instance_id: int, snapshot_id: str) -> bool:
        """Restore context from a snapshot."""
        try:
            if not self.redis:
                raise ContextManagerError("Redis not available for snapshot restore")
            
            snapshot_key = f"process_context_snapshot:{instance_id}:{snapshot_id}"
            snapshot_data = self.redis.get(snapshot_key)
            
            if not snapshot_data:
                raise ContextManagerError(f"Snapshot {snapshot_id} not found")
            
            snapshot = json.loads(snapshot_data)
            context = snapshot['context']
            
            # Validate snapshot belongs to correct instance
            if context.get('process_instance_id') != instance_id:
                raise ContextManagerError("Snapshot instance ID mismatch")
            
            # Restore context
            await self._store_context(instance_id, context)
            
            log.info(f"Restored context from snapshot {snapshot_id} for instance {instance_id}")
            return True
            
        except Exception as e:
            log.error(f"Error restoring context snapshot: {str(e)}")
            raise ContextManagerError(f"Failed to restore context snapshot: {str(e)}")
    
    async def finalize_context(self, instance: ProcessInstance):
        """Finalize context when process completes."""
        try:
            context = await self._get_context(instance.id)
            
            # Update instance output data
            instance.output_data = context.get('variables', {})
            instance.variables = context.get('variables', {})
            
            # Store final context snapshot
            await self.create_context_snapshot(instance.id)
            
            # Clean up temporary data if process completed successfully
            if instance.status == 'completed':
                await self._cleanup_temporary_context(instance.id)
            
            db.session.commit()
            
            log.debug(f"Finalized context for process instance {instance.id}")
            
        except Exception as e:
            log.error(f"Error finalizing context for instance {instance.id}: {str(e)}")
    
    async def _get_context(self, instance_id: int) -> Dict[str, Any]:
        """Get process context with caching."""
        with self._lock:
            # Check cache first
            if instance_id in self._context_cache:
                return deepcopy(self._context_cache[instance_id])
        
        # Load from Redis if available
        if self.redis:
            try:
                context_key = f"process_context:{instance_id}"
                context_data = self.redis.get(context_key)
                if context_data:
                    context = json.loads(context_data)
                    
                    # Update cache
                    with self._lock:
                        self._context_cache[instance_id] = deepcopy(context)
                    
                    return context
            except Exception as e:
                log.debug(f"Error loading context from Redis: {str(e)}")
        
        # Load from database as fallback
        try:
            instance = db.session.query(ProcessInstance).get(instance_id)
            if not instance:
                raise ContextManagerError(f"Process instance {instance_id} not found")
            
            context = instance.context or {}
            
            # Ensure basic structure
            if 'variables' not in context:
                context['variables'] = instance.variables or {}
            
            # Update cache
            with self._lock:
                self._context_cache[instance_id] = deepcopy(context)
            
            return context
            
        except Exception as e:
            log.error(f"Error loading context from database: {str(e)}")
            raise ContextManagerError(f"Failed to load context: {str(e)}")
    
    async def _store_context(self, instance_id: int, context: Dict[str, Any]):
        """Store process context with validation."""
        # Validate context size
        context_size = len(json.dumps(context, default=str))
        max_size = self.config['max_context_size_mb'] * 1024 * 1024
        
        if context_size > max_size:
            raise ContextManagerError(f"Context too large: {context_size} bytes")
        
        # Store in Redis if available
        if self.redis:
            try:
                context_key = f"process_context:{instance_id}"
                self.redis.setex(
                    context_key,
                    self.config['variable_ttl_seconds'],
                    json.dumps(context, default=str)
                )
            except Exception as e:
                log.warning(f"Failed to store context in Redis: {str(e)}")
        
        # Update cache
        with self._lock:
            self._context_cache[instance_id] = deepcopy(context)
        
        # Store in database as backup
        try:
            instance = db.session.query(ProcessInstance).get(instance_id)
            if instance:
                instance.context = context
                instance.variables = context.get('variables', {})
                db.session.commit()
        except Exception as e:
            log.warning(f"Failed to store context in database: {str(e)}")
    
    def _get_system_variables(self, instance: ProcessInstance) -> Dict[str, Any]:
        """Get system-provided variables."""
        return {
            'current_time': datetime.now(tz=timezone.utc).isoformat(),
            'instance_id': instance.id,
            'definition_id': instance.process_definition_id,
            'tenant_id': instance.tenant_id,
            'initiated_by': instance.initiated_by,
            'priority': instance.priority,
            'started_at': instance.started_at.isoformat() if instance.started_at else None
        }
    
    def _is_valid_variable_name(self, name: str) -> bool:
        """Validate variable name format."""
        import re
        # Allow alphanumeric, underscore, dot notation
        return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9_.]*$', name)) and not name.startswith('system.')
    
    async def _validate_variable_value(self, name: str, value: Any) -> bool:
        """Validate variable value."""
        # Check for validator
        if name in self._variable_validators:
            validator = self._variable_validators[name]
            try:
                if asyncio.iscoroutinefunction(validator):
                    return await validator(value)
                else:
                    return validator(value)
            except Exception as e:
                log.warning(f"Variable validation failed for '{name}': {str(e)}")
                return False
        
        # Basic type validation
        allowed_types = (str, int, float, bool, list, dict, type(None))
        return isinstance(value, allowed_types)
    
    async def _validate_tenant_access(self, instance_id: int) -> bool:
        """Validate tenant isolation for context access."""
        try:
            current_tenant_id = get_current_tenant_id()
            if not current_tenant_id:
                return True  # No tenant context (system operation)
            
            instance = db.session.query(ProcessInstance).get(instance_id)
            return instance and instance.tenant_id == current_tenant_id
            
        except Exception as e:
            log.warning(f"Tenant access validation failed: {str(e)}")
            return False
    
    async def _audit_variable_access(self, instance_id: int, variable_name: str,
                                   operation: str, value: Any, step_id: int = None):
        """Audit variable access for security and compliance."""
        try:
            audit_data = {
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'instance_id': instance_id,
                'step_id': step_id,
                'variable_name': variable_name,
                'operation': operation,
                'value_type': type(value).__name__,
                'tenant_id': get_current_tenant_id()
            }
            
            # Store audit record (implementation depends on audit system)
            if self.redis:
                audit_key = f"variable_audit:{instance_id}:{variable_name}"
                self.redis.lpush(audit_key, json.dumps(audit_data, default=str))
                self.redis.ltrim(audit_key, 0, 999)  # Keep last 1000 records
                self.redis.expire(audit_key, 2592000)  # 30 days
                
        except Exception as e:
            log.debug(f"Variable audit logging failed: {str(e)}")
    
    async def _execute_variable_hooks(self, instance_id: int, variable_name: str,
                                    old_value: Any, new_value: Any):
        """Execute registered hooks for variable changes."""
        hooks = self._context_hooks.get(variable_name, [])
        
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(instance_id, variable_name, old_value, new_value)
                else:
                    hook(instance_id, variable_name, old_value, new_value)
            except Exception as e:
                log.warning(f"Context hook execution failed: {str(e)}")
    
    async def _cleanup_temporary_context(self, instance_id: int):
        """Clean up temporary context data."""
        try:
            # Remove from cache
            with self._lock:
                self._context_cache.pop(instance_id, None)
            
            # Clean up Redis data
            if self.redis:
                context_key = f"process_context:{instance_id}"
                self.redis.delete(context_key)
                
        except Exception as e:
            log.debug(f"Context cleanup failed: {str(e)}")
    
    # Public API for hooks and validators
    
    def register_variable_validator(self, variable_name: str, validator: Callable):
        """Register variable value validator."""
        self._variable_validators[variable_name] = validator
        log.debug(f"Registered validator for variable: {variable_name}")
    
    def register_variable_hook(self, variable_name: str, hook: Callable):
        """Register hook for variable changes."""
        if variable_name not in self._context_hooks:
            self._context_hooks[variable_name] = []
        
        self._context_hooks[variable_name].append(hook)
        log.debug(f"Registered hook for variable: {variable_name}")
    
    def get_context_stats(self) -> Dict[str, Any]:
        """Get context manager statistics."""
        with self._lock:
            return {
                'cached_contexts': len(self._context_cache),
                'registered_validators': len(self._variable_validators),
                'registered_hooks': sum(len(hooks) for hooks in self._context_hooks.values()),
                'redis_available': self.redis is not None,
                'config': self.config.copy()
            }