"""
Main Process Execution Engine.

Orchestrates business process execution with state management,
error handling, and integration with Flask-AppBuilder ecosystem.
"""

import logging
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple, Callable
from contextlib import asynccontextmanager
import uuid
import threading
import time

from sqlalchemy.exc import SQLAlchemyError
from flask import current_app, g

from flask_appbuilder import db
from flask_appbuilder.models.tenant_context import get_current_tenant_id

from ..models.process_models import (
    ProcessDefinition, ProcessInstance, ProcessStep, ProcessLog,
    ProcessInstanceStatus, ProcessStepStatus
)
from .state_machine import ProcessStateMachine
from .context_manager import ProcessContextManager
from .executors import (
    NodeExecutor, TaskExecutor, GatewayExecutor,
    ApprovalExecutor, ServiceExecutor, TimerExecutor
)

log = logging.getLogger(__name__)


class ProcessEngineError(Exception):
    """Base exception for process engine errors."""
    
    def __init__(self, message: str, process_instance_id: int = None, 
                 node_id: str = None, error_code: str = None):
        super().__init__(message)
        self.process_instance_id = process_instance_id
        self.node_id = node_id
        self.error_code = error_code


class ProcessExecutionError(ProcessEngineError):
    """Exception raised during process step execution."""
    pass


class ProcessValidationError(ProcessEngineError):
    """Exception raised for invalid process definitions."""
    pass


class ProcessEngine:
    """
    Main process execution engine.
    
    Provides comprehensive business process automation with state management,
    async task coordination, error handling, and performance monitoring.
    """
    
    def __init__(self, redis_client=None, celery_app=None):
        """Initialize the process engine."""
        self.redis = redis_client
        self.celery = celery_app
        self.state_machine = ProcessStateMachine()
        self.context_manager = ProcessContextManager(redis_client)
        
        # Executor registry
        self.executors: Dict[str, NodeExecutor] = {}
        self._register_default_executors()
        
        # Engine configuration
        self.config = {
            'max_concurrent_instances': 100,
            'default_step_timeout': 300,  # 5 minutes
            'max_retry_attempts': 3,
            'error_escalation_threshold': 5,
            'performance_monitoring': True
        }
        
        # Runtime state
        self._running_instances: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._engine_stats = {
            'instances_started': 0,
            'instances_completed': 0,
            'instances_failed': 0,
            'total_execution_time': 0,
            'avg_execution_time': 0
        }
        
        log.info("Process Engine initialized successfully")
    
    def _register_default_executors(self):
        """Register default node executors."""
        self.executors = {
            'task': TaskExecutor(self),
            'service': ServiceExecutor(self),
            'gateway': GatewayExecutor(self),
            'approval': ApprovalExecutor(self),
            'timer': TimerExecutor(self),
            'start': NodeExecutor(self),
            'end': NodeExecutor(self)
        }
    
    def register_executor(self, node_type: str, executor: NodeExecutor):
        """Register a custom node executor."""
        if not isinstance(executor, NodeExecutor):
            raise ValueError("Executor must be an instance of NodeExecutor")
        
        self.executors[node_type] = executor
        log.info(f"Registered custom executor for node type: {node_type}")
    
    async def start_process(self, definition_id: int, input_data: Dict[str, Any] = None,
                           initiated_by: int = None, instance_name: str = None,
                           priority: int = 5) -> ProcessInstance:
        """
        Start a new process instance.
        
        Args:
            definition_id: Process definition ID
            input_data: Initial process data
            initiated_by: User ID who initiated the process
            instance_name: Optional custom name for the instance
            priority: Process priority (1-10)
        
        Returns:
            ProcessInstance: The created and started process instance
        """
        try:
            # Get process definition
            definition = db.session.query(ProcessDefinition).get(definition_id)
            if not definition:
                raise ProcessValidationError(f"Process definition {definition_id} not found")
            
            if definition.status != 'active':
                raise ProcessValidationError(f"Process definition {definition_id} is not active")
            
            # Validate process definition
            await self._validate_process_definition(definition)
            
            # Create process instance
            instance = ProcessInstance(
                process_definition_id=definition_id,
                name=instance_name or f"Process {definition.name} - {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                status=ProcessInstanceStatus.RUNNING.value,
                input_data=input_data or {},
                context={'initiated_by': initiated_by},
                initiated_by=initiated_by,
                priority=priority,
                tenant_id=get_current_tenant_id()
            )
            
            db.session.add(instance)
            db.session.commit()
            
            # Log process start
            await self._log_process_event(
                instance.id, 'INFO', 'process_started',
                f"Process instance {instance.id} started",
                user_id=initiated_by
            )
            
            # Initialize process context
            await self.context_manager.initialize_context(instance)
            
            # Start execution from first node
            await self._execute_process_start(instance)
            
            # Update engine stats
            with self._lock:
                self._engine_stats['instances_started'] += 1
            
            log.info(f"Started process instance {instance.id} from definition {definition_id}")
            return instance
            
        except Exception as e:
            log.error(f"Failed to start process {definition_id}: {str(e)}")
            if 'instance' in locals():
                await self._mark_instance_failed(instance, str(e))
            raise ProcessExecutionError(f"Failed to start process: {str(e)}")
    
    async def _execute_process_start(self, instance: ProcessInstance):
        """Execute the process from start nodes."""
        try:
            definition = instance.definition
            start_nodes = definition.get_start_nodes()
            
            if not start_nodes:
                raise ProcessValidationError("Process definition has no start nodes")
            
            # Execute all start nodes (support for multiple start events)
            for start_node in start_nodes:
                await self._execute_node(instance, start_node)
                
        except Exception as e:
            log.error(f"Failed to execute process start for instance {instance.id}: {str(e)}")
            await self._mark_instance_failed(instance, str(e))
            raise
    
    async def _execute_node(self, instance: ProcessInstance, node: Dict[str, Any],
                           input_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute a specific node in the process.
        
        Args:
            instance: Process instance
            node: Node definition from process graph
            input_data: Input data for the node
        
        Returns:
            Dict containing output data from node execution
        """
        node_id = node.get('id')
        node_type = node.get('type')
        
        try:
            # Create or get process step
            step = await self._create_process_step(instance, node, input_data)
            
            # Log step start
            await self._log_process_event(
                instance.id, 'INFO', 'step_started',
                f"Started executing node {node_id} ({node_type})",
                step_id=step.id,
                node_id=node_id
            )
            
            # Get executor for node type
            executor = self.executors.get(node_type)
            if not executor:
                raise ProcessExecutionError(f"No executor found for node type: {node_type}")
            
            # Mark step as running
            step.mark_started()
            db.session.commit()
            
            # Execute node
            start_time = time.time()
            output_data = await executor.execute(instance, node, step, input_data or {})
            execution_time = time.time() - start_time
            
            # Mark step as completed
            step.mark_completed(output_data)
            step.execution_time = execution_time
            db.session.commit()
            
            # Log step completion
            await self._log_process_event(
                instance.id, 'INFO', 'step_completed',
                f"Completed executing node {node_id} in {execution_time:.2f}s",
                step_id=step.id,
                node_id=node_id,
                execution_time=execution_time
            )
            
            # Continue to next nodes if not a blocking step
            if not self._is_blocking_step(step):
                await self._continue_process_execution(instance, node, output_data)
            
            return output_data
            
        except Exception as e:
            log.error(f"Node execution failed - Instance: {instance.id}, Node: {node_id}, Error: {str(e)}")
            
            # Mark step as failed if it exists
            if 'step' in locals():
                step.mark_failed(str(e))
                db.session.commit()
            
            # Log error
            await self._log_process_event(
                instance.id, 'ERROR', 'step_failed',
                f"Node {node_id} execution failed: {str(e)}",
                step_id=getattr(locals().get('step'), 'id', None),
                node_id=node_id,
                error_details={'error': str(e), 'node_type': node_type}
            )
            
            # Handle error according to error handling strategy
            await self._handle_step_error(instance, node, step if 'step' in locals() else None, e)
            
            raise ProcessExecutionError(f"Node execution failed: {str(e)}", 
                                      instance.id, node_id, 'EXECUTION_ERROR')
    
    async def _create_process_step(self, instance: ProcessInstance, node: Dict[str, Any],
                                  input_data: Dict[str, Any] = None) -> ProcessStep:
        """Create a process step for node execution."""
        step = ProcessStep(
            process_instance_id=instance.id,
            node_id=node.get('id'),
            node_type=node.get('type'),
            step_name=node.get('name', node.get('id')),
            input_data=input_data or {},
            configuration=node.get('properties', {}),
            status=ProcessStepStatus.PENDING.value,
            tenant_id=instance.tenant_id
        )
        
        # Set execution order
        step.execution_order = len(instance.steps) + 1
        
        # Set due date if specified
        if 'due_in_minutes' in node.get('properties', {}):
            due_minutes = node['properties']['due_in_minutes']
            step.due_at = datetime.now(tz=timezone.utc) + timedelta(minutes=due_minutes)
        
        db.session.add(step)
        db.session.flush()  # Get ID without committing
        
        return step
    
    async def _continue_process_execution(self, instance: ProcessInstance, 
                                        current_node: Dict[str, Any],
                                        output_data: Dict[str, Any]):
        """Continue process execution to next nodes."""
        try:
            # Get outgoing edges from current node
            outgoing_edges = instance.definition.get_outgoing_edges(current_node.get('id'))
            
            if not outgoing_edges:
                # No outgoing edges - check if this is an end node
                if current_node.get('type') == 'end':
                    await self._complete_process_instance(instance)
                return
            
            # Execute each outgoing path
            for edge in outgoing_edges:
                target_node_id = edge.get('target')
                target_node = instance.definition.get_node_by_id(target_node_id)
                
                if not target_node:
                    log.warning(f"Target node {target_node_id} not found in process definition")
                    continue
                
                # Check edge conditions if any
                if await self._evaluate_edge_condition(edge, output_data):
                    # Execute target node (async to allow parallel paths)
                    if self.celery:
                        # Use Celery for async execution if available
                        from ..tasks import execute_node_async
                        execute_node_async.delay(instance.id, target_node_id, output_data)
                    else:
                        # Execute directly (in production, should use proper async handling)
                        await self._execute_node(instance, target_node, output_data)
                        
        except Exception as e:
            log.error(f"Error continuing process execution for instance {instance.id}: {str(e)}")
            await self._handle_process_error(instance, e)
    
    async def _evaluate_edge_condition(self, edge: Dict[str, Any], 
                                     context_data: Dict[str, Any]) -> bool:
        """Evaluate edge condition to determine if flow should continue."""
        condition = edge.get('condition')
        if not condition:
            return True  # No condition means always follow this edge
        
        try:
            # Simple condition evaluation (can be extended for complex expressions)
            if isinstance(condition, dict):
                field = condition.get('field')
                operator = condition.get('operator', '==')
                value = condition.get('value')
                
                if field not in context_data:
                    return False
                
                actual_value = context_data[field]
                
                if operator == '==':
                    return actual_value == value
                elif operator == '!=':
                    return actual_value != value
                elif operator == '>':
                    return actual_value > value
                elif operator == '>=':
                    return actual_value >= value
                elif operator == '<':
                    return actual_value < value
                elif operator == '<=':
                    return actual_value <= value
                elif operator == 'in':
                    return actual_value in value
                elif operator == 'not_in':
                    return actual_value not in value
            
            return True
            
        except Exception as e:
            log.warning(f"Error evaluating edge condition: {str(e)}")
            return False
    
    async def _complete_process_instance(self, instance: ProcessInstance):
        """Mark process instance as completed."""
        try:
            instance.status = ProcessInstanceStatus.COMPLETED.value
            instance.completed_at = datetime.now(tz=timezone.utc)
            instance.update_activity()
            
            # Update context with final state
            await self.context_manager.finalize_context(instance)
            
            db.session.commit()
            
            # Log completion
            await self._log_process_event(
                instance.id, 'INFO', 'process_completed',
                f"Process instance {instance.id} completed successfully",
                execution_time=instance.duration
            )
            
            # Update engine stats
            with self._lock:
                self._engine_stats['instances_completed'] += 1
                self._engine_stats['total_execution_time'] += (instance.duration or 0)
                completed = self._engine_stats['instances_completed']
                self._engine_stats['avg_execution_time'] = self._engine_stats['total_execution_time'] / completed
            
            log.info(f"Process instance {instance.id} completed successfully")
            
        except Exception as e:
            log.error(f"Error completing process instance {instance.id}: {str(e)}")
            await self._mark_instance_failed(instance, str(e))
    
    async def _mark_instance_failed(self, instance: ProcessInstance, error_message: str):
        """Mark process instance as failed."""
        try:
            instance.status = ProcessInstanceStatus.FAILED.value
            instance.last_error = error_message
            instance.error_count += 1
            instance.update_activity()
            
            if not instance.completed_at:
                instance.completed_at = datetime.now(tz=timezone.utc)
            
            db.session.commit()
            
            # Log failure
            await self._log_process_event(
                instance.id, 'ERROR', 'process_failed',
                f"Process instance {instance.id} failed: {error_message}",
                error_details={'error': error_message}
            )
            
            # Update engine stats
            with self._lock:
                self._engine_stats['instances_failed'] += 1
            
            log.error(f"Process instance {instance.id} marked as failed: {error_message}")
            
        except Exception as e:
            log.error(f"Error marking instance {instance.id} as failed: {str(e)}")
    
    def _is_blocking_step(self, step: ProcessStep) -> bool:
        """Check if step blocks process continuation (e.g., waiting for approval)."""
        blocking_types = ['approval', 'timer', 'manual_task']
        return step.node_type in blocking_types and step.status in [
            ProcessStepStatus.PENDING.value,
            ProcessStepStatus.WAITING.value
        ]
    
    async def _handle_step_error(self, instance: ProcessInstance, node: Dict[str, Any],
                                step: Optional[ProcessStep], error: Exception):
        """Handle step execution errors with retry and escalation logic."""
        try:
            error_handling = node.get('properties', {}).get('error_handling', {})
            
            # Check if step should be retried
            if step and step.retry_count < self.config['max_retry_attempts']:
                retry_delay = error_handling.get('retry_delay', 30)  # seconds
                
                if self.celery:
                    # Schedule retry using Celery
                    from ..tasks import retry_step_async
                    retry_step_async.apply_async(
                        args=[step.id],
                        countdown=retry_delay
                    )
                else:
                    # In-memory retry (not recommended for production)
                    await asyncio.sleep(retry_delay)
                    await self._retry_step(step)
                
                return
            
            # Handle based on error handling strategy
            strategy = error_handling.get('strategy', 'fail_process')
            
            if strategy == 'skip_step':
                # Skip this step and continue
                if step:
                    step.status = ProcessStepStatus.SKIPPED.value
                    step.error_message = str(error)
                    db.session.commit()
                
                await self._continue_process_execution(instance, node, {})
                
            elif strategy == 'alternative_path':
                # Take alternative path if defined
                alt_path = error_handling.get('alternative_path')
                if alt_path:
                    alt_node = instance.definition.get_node_by_id(alt_path)
                    if alt_node:
                        await self._execute_node(instance, alt_node)
                        return
                
                # Fall back to failing process if no alternative
                await self._mark_instance_failed(instance, str(error))
                
            else:  # strategy == 'fail_process'
                await self._mark_instance_failed(instance, str(error))
                
        except Exception as e:
            log.error(f"Error in step error handler: {str(e)}")
            await self._mark_instance_failed(instance, str(error))
    
    async def _handle_process_error(self, instance: ProcessInstance, error: Exception):
        """Handle process-level errors."""
        try:
            await self._mark_instance_failed(instance, str(error))
        except Exception as e:
            log.error(f"Error in process error handler: {str(e)}")
    
    async def _retry_step(self, step: ProcessStep):
        """Retry a failed step."""
        try:
            step.retry_count += 1
            step.status = ProcessStepStatus.PENDING.value
            step.error_message = None
            step.error_details = {}
            
            db.session.commit()
            
            # Get instance and node
            instance = step.instance
            node = instance.definition.get_node_by_id(step.node_id)
            
            if node:
                await self._execute_node(instance, node, step.input_data)
            
        except Exception as e:
            log.error(f"Error retrying step {step.id}: {str(e)}")
            step.mark_failed(str(e))
            db.session.commit()
    
    async def _validate_process_definition(self, definition: ProcessDefinition):
        """Validate process definition before execution."""
        if not definition.is_valid_graph:
            raise ProcessValidationError(f"Invalid process graph in definition {definition.id}")
        
        # Additional validation can be added here
        nodes = definition.process_graph.get('nodes', [])
        for node in nodes:
            node_type = node.get('type')
            if node_type not in self.executors:
                raise ProcessValidationError(f"Unsupported node type: {node_type}")
    
    async def _log_process_event(self, instance_id: int, level: str, event_type: str,
                                message: str, step_id: int = None, node_id: str = None,
                                user_id: int = None, execution_time: float = None,
                                error_details: Dict[str, Any] = None):
        """Log process execution event."""
        try:
            log_entry = ProcessLog(
                process_instance_id=instance_id,
                process_step_id=step_id,
                timestamp=datetime.now(tz=timezone.utc),
                level=level,
                event_type=event_type,
                message=message,
                user_id=user_id,
                node_id=node_id,
                execution_time=execution_time,
                details=error_details or {},
                tenant_id=get_current_tenant_id()
            )
            
            db.session.add(log_entry)
            db.session.commit()
            
        except Exception as e:
            # Don't fail process execution due to logging errors
            log.error(f"Failed to log process event: {str(e)}")
    
    # Public API methods
    
    async def resume_process(self, instance_id: int, node_id: str = None, 
                            resume_data: Dict[str, Any] = None) -> bool:
        """Resume a suspended process instance."""
        try:
            instance = db.session.query(ProcessInstance).get(instance_id)
            if not instance:
                raise ProcessValidationError(f"Process instance {instance_id} not found")
            
            if instance.status != ProcessInstanceStatus.SUSPENDED.value:
                raise ProcessValidationError(f"Process instance {instance_id} is not suspended")
            
            # Resume from specified node or current step
            if node_id:
                node = instance.definition.get_node_by_id(node_id)
                if not node:
                    raise ProcessValidationError(f"Node {node_id} not found in process definition")
            else:
                node = instance.definition.get_node_by_id(instance.current_step)
                if not node:
                    raise ProcessValidationError("Cannot determine resume point")
            
            # Update instance status
            instance.status = ProcessInstanceStatus.RUNNING.value
            instance.suspended_at = None
            instance.update_activity()
            db.session.commit()
            
            # Log resume
            await self._log_process_event(
                instance.id, 'INFO', 'process_resumed',
                f"Process instance {instance_id} resumed at node {node_id or instance.current_step}"
            )
            
            # Continue execution
            await self._execute_node(instance, node, resume_data or {})
            
            return True
            
        except Exception as e:
            log.error(f"Failed to resume process instance {instance_id}: {str(e)}")
            return False
    
    async def suspend_process(self, instance_id: int, reason: str = None) -> bool:
        """Suspend a running process instance."""
        try:
            instance = db.session.query(ProcessInstance).get(instance_id)
            if not instance:
                raise ProcessValidationError(f"Process instance {instance_id} not found")
            
            if instance.status != ProcessInstanceStatus.RUNNING.value:
                raise ProcessValidationError(f"Process instance {instance_id} is not running")
            
            # Update instance status
            instance.status = ProcessInstanceStatus.SUSPENDED.value
            instance.suspended_at = datetime.now(tz=timezone.utc)
            instance.update_activity()
            db.session.commit()
            
            # Log suspension
            await self._log_process_event(
                instance.id, 'INFO', 'process_suspended',
                f"Process instance {instance_id} suspended: {reason or 'Manual suspension'}"
            )
            
            return True
            
        except Exception as e:
            log.error(f"Failed to suspend process instance {instance_id}: {str(e)}")
            return False
    
    async def cancel_process(self, instance_id: int, reason: str = None) -> bool:
        """Cancel a process instance."""
        try:
            instance = db.session.query(ProcessInstance).get(instance_id)
            if not instance:
                raise ProcessValidationError(f"Process instance {instance_id} not found")
            
            if instance.status in [ProcessInstanceStatus.COMPLETED.value, ProcessInstanceStatus.FAILED.value]:
                raise ProcessValidationError(f"Process instance {instance_id} is already finished")
            
            # Update instance status
            instance.status = ProcessInstanceStatus.CANCELLED.value
            instance.completed_at = datetime.now(tz=timezone.utc)
            instance.update_activity()
            db.session.commit()
            
            # Log cancellation
            await self._log_process_event(
                instance.id, 'INFO', 'process_cancelled',
                f"Process instance {instance_id} cancelled: {reason or 'Manual cancellation'}"
            )
            
            return True
            
        except Exception as e:
            log.error(f"Failed to cancel process instance {instance_id}: {str(e)}")
            return False
    
    def get_engine_stats(self) -> Dict[str, Any]:
        """Get engine performance statistics."""
        with self._lock:
            return self._engine_stats.copy()
    
    def get_running_instances_count(self) -> int:
        """Get count of currently running instances."""
        try:
            return db.session.query(ProcessInstance).filter_by(
                status=ProcessInstanceStatus.RUNNING.value
            ).count()
        except Exception as e:
            log.error(f"Error getting running instances count: {str(e)}")
            return 0
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform engine health check."""
        try:
            health_status = {
                'status': 'healthy',
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'engine_stats': self.get_engine_stats(),
                'running_instances': self.get_running_instances_count(),
                'executors_registered': len(self.executors),
                'redis_available': self.redis is not None,
                'celery_available': self.celery is not None
            }
            
            # Check database connectivity
            try:
                db.session.execute('SELECT 1').fetchone()
                health_status['database'] = 'connected'
            except Exception as e:
                health_status['database'] = f'error: {str(e)}'
                health_status['status'] = 'degraded'
            
            # Check Redis connectivity
            if self.redis:
                try:
                    self.redis.ping()
                    health_status['redis'] = 'connected'
                except Exception as e:
                    health_status['redis'] = f'error: {str(e)}'
                    health_status['status'] = 'degraded'
            
            return health_status
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }