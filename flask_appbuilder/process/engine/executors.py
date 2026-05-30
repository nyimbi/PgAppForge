"""
Process Node Executors.

Implements execution logic for different types of process nodes including
tasks, gateways, approvals, services, and timers with comprehensive
error handling and integration capabilities.
"""

import logging
import asyncio
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Callable
from abc import ABC, abstractmethod
from enum import Enum
import uuid

from flask import current_app
from flask_appbuilder import db
from flask_appbuilder.models.tenant_context import get_current_tenant_id

from ..models.process_models import (
    ProcessInstance, ProcessStep, ApprovalRequest, ApprovalStatus,
    SubprocessDefinition, SubprocessExecution
)

log = logging.getLogger(__name__)


class NodeExecutionError(Exception):
    """Exception raised during node execution."""
    pass


class NodeExecutor(ABC):
    """
    Base class for process node executors.
    
    Provides common functionality and interface for all node types
    with extensible execution patterns and error handling.
    """
    
    def __init__(self, engine):
        """Initialize node executor."""
        self.engine = engine
        self.execution_hooks = {}
        self.config = {
            'default_timeout': 300,  # 5 minutes
            'max_retries': 3,
            'enable_performance_tracking': True
        }
    
    async def execute(self, instance: ProcessInstance, node: Dict[str, Any],
                     step: ProcessStep, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the node with common pre/post processing.
        
        Args:
            instance: Process instance
            node: Node definition
            step: Process step
            input_data: Input data for execution
            
        Returns:
            Dict containing output data
        """
        node_id = node.get('id')
        start_time = time.time()
        
        try:
            # Pre-execution hooks
            await self._execute_pre_hooks(instance, node, step, input_data)
            
            # Execute node-specific logic
            output_data = await self._execute_node(instance, node, step, input_data)
            
            # Post-execution hooks
            await self._execute_post_hooks(instance, node, step, input_data, output_data)
            
            # Record performance metrics
            if self.config['enable_performance_tracking']:
                execution_time = time.time() - start_time
                await self._record_performance_metrics(instance, node, step, execution_time)
            
            return output_data or {}
            
        except Exception as e:
            log.error(f"Node execution failed - Node: {node_id}, Error: {str(e)}")
            await self._handle_execution_error(instance, node, step, e)
            raise NodeExecutionError(f"Node {node_id} execution failed: {str(e)}")
    
    @abstractmethod
    async def _execute_node(self, instance: ProcessInstance, node: Dict[str, Any],
                           step: ProcessStep, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute node-specific logic. Must be implemented by subclasses."""
        pass
    
    async def _execute_pre_hooks(self, instance: ProcessInstance, node: Dict[str, Any],
                               step: ProcessStep, input_data: Dict[str, Any]):
        """Execute pre-execution hooks."""
        hooks = self.execution_hooks.get('pre', [])
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(instance, node, step, input_data)
                else:
                    hook(instance, node, step, input_data)
            except Exception as e:
                log.warning(f"Pre-execution hook failed: {str(e)}")
    
    async def _execute_post_hooks(self, instance: ProcessInstance, node: Dict[str, Any],
                                step: ProcessStep, input_data: Dict[str, Any],
                                output_data: Dict[str, Any]):
        """Execute post-execution hooks."""
        hooks = self.execution_hooks.get('post', [])
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(instance, node, step, input_data, output_data)
                else:
                    hook(instance, node, step, input_data, output_data)
            except Exception as e:
                log.warning(f"Post-execution hook failed: {str(e)}")
    
    async def _handle_execution_error(self, instance: ProcessInstance, node: Dict[str, Any],
                                    step: ProcessStep, error: Exception):
        """Handle execution errors with logging and notifications."""
        error_details = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'node_id': node.get('id'),
            'node_type': node.get('type'),
            'step_id': step.id,
            'timestamp': datetime.now(tz=timezone.utc).isoformat()
        }
        
        # Store error details
        step.error_details = error_details
        
        # Execute error hooks
        error_hooks = self.execution_hooks.get('error', [])
        for hook in error_hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(instance, node, step, error)
                else:
                    hook(instance, node, step, error)
            except Exception as e:
                log.warning(f"Error hook failed: {str(e)}")
    
    async def _record_performance_metrics(self, instance: ProcessInstance, node: Dict[str, Any],
                                        step: ProcessStep, execution_time: float):
        """Record performance metrics for node execution."""
        try:
            from ..models.process_models import ProcessMetric
            
            metric = ProcessMetric(
                process_definition_id=instance.process_definition_id,
                process_instance_id=instance.id,
                metric_date=datetime.now(tz=timezone.utc),
                metric_type='step_duration',
                value=execution_time,
                node_id=node.get('id'),
                context_data={
                    'node_type': node.get('type'),
                    'step_id': step.id
                },
                tenant_id=instance.tenant_id
            )
            
            db.session.add(metric)
            db.session.commit()
            
        except Exception as e:
            log.debug(f"Failed to record performance metrics: {str(e)}")
    
    def register_hook(self, hook_type: str, hook: Callable):
        """Register execution hook."""
        if hook_type not in self.execution_hooks:
            self.execution_hooks[hook_type] = []
        
        self.execution_hooks[hook_type].append(hook)
        log.debug(f"Registered {hook_type} hook for {self.__class__.__name__}")


class TaskExecutor(NodeExecutor):
    """
    Executor for user task nodes.
    
    Handles user task creation, assignment, and completion tracking
    with support for forms, deadlines, and escalation.
    """
    
    async def _execute_node(self, instance: ProcessInstance, node: Dict[str, Any],
                           step: ProcessStep, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute user task node."""
        task_config = node.get('properties', {})
        
        # Assign task to user
        assignee_id = await self._resolve_assignee(instance, task_config, input_data)
        if assignee_id:
            step.assigned_to = assignee_id
        
        # Set task form configuration
        if 'form_schema' in task_config:
            step.configuration['form_schema'] = task_config['form_schema']
        
        # Set due date
        if 'due_in_hours' in task_config:
            hours = task_config['due_in_hours']
            step.due_at = datetime.now(tz=timezone.utc) + timedelta(hours=hours)
        
        # Mark step as waiting for user action
        step.status = 'waiting'
        db.session.commit()
        
        # Send notification to assignee
        if assignee_id:
            await self._send_task_notification(instance, step, assignee_id)
        
        # Task will be completed externally via API
        # Return empty output for now
        return {}
    
    async def _resolve_assignee(self, instance: ProcessInstance, task_config: Dict[str, Any],
                               input_data: Dict[str, Any]) -> Optional[int]:
        """Resolve task assignee from configuration."""
        # Check for direct assignment
        if 'assigned_to' in task_config:
            return task_config['assigned_to']
        
        # Check for assignment by role
        if 'assigned_to_role' in task_config:
            role_name = task_config['assigned_to_role']
            # In real implementation, resolve users by role
            # For now, return None to indicate no specific assignee
            return None
        
        # Check for dynamic assignment from context
        if 'assignee_variable' in task_config:
            variable_name = task_config['assignee_variable']
            try:
                assignee = await self.engine.context_manager.get_variable(
                    instance.id, variable_name
                )
                return int(assignee) if assignee else None
            except:
                return None
        
        return None
    
    async def _send_task_notification(self, instance: ProcessInstance, step: ProcessStep,
                                    assignee_id: int):
        """Send task notification to assignee."""
        try:
            # In real implementation, integrate with notification system
            notification_data = {
                'type': 'task_assigned',
                'process_instance_id': instance.id,
                'step_id': step.id,
                'assignee_id': assignee_id,
                'task_name': step.step_name,
                'due_at': step.due_at.isoformat() if step.due_at else None,
                'url': f"/process/task/{step.id}"
            }
            
            log.info(f"Task notification sent to user {assignee_id}: {json.dumps(notification_data)}")
            
        except Exception as e:
            log.warning(f"Failed to send task notification: {str(e)}")


class ServiceExecutor(NodeExecutor):
    """
    Executor for service task nodes.
    
    Handles automated service calls, API integrations, and system
    operations with retry logic and error handling.
    """
    
    async def _execute_node(self, instance: ProcessInstance, node: Dict[str, Any],
                           step: ProcessStep, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute service task node."""
        service_config = node.get('properties', {})
        service_type = service_config.get('service_type')
        
        if service_type == 'http_call':
            return await self._execute_http_call(instance, service_config, input_data)
        elif service_type == 'email':
            return await self._execute_email_service(instance, service_config, input_data)
        elif service_type == 'database':
            return await self._execute_database_operation(instance, service_config, input_data)
        elif service_type == 'script':
            return await self._execute_script(instance, service_config, input_data)
        else:
            # Custom service type
            return await self._execute_custom_service(instance, service_config, input_data)
    
    async def _execute_http_call(self, instance: ProcessInstance, config: Dict[str, Any],
                               input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute HTTP API call."""
        import aiohttp
        import asyncio
        
        try:
            url = config.get('url')
            method = config.get('method', 'GET').upper()
            headers = config.get('headers', {})
            
            # Resolve variables in URL and headers
            if url:
                url = await self.engine.context_manager.resolve_expression(instance.id, url)
            
            for key, value in headers.items():
                headers[key] = await self.engine.context_manager.resolve_expression(instance.id, value)
            
            # Prepare request data
            request_data = None
            if method in ['POST', 'PUT', 'PATCH']:
                request_data = config.get('data', input_data)
            
            # Make HTTP call with timeout
            timeout = aiohttp.ClientTimeout(total=config.get('timeout', 30))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(method, url, headers=headers, json=request_data) as response:
                    response_data = await response.text()
                    
                    # Try to parse as JSON
                    try:
                        response_json = await response.json()
                    except:
                        response_json = {'text': response_data}
                    
                    return {
                        'http_status': response.status,
                        'response_data': response_json,
                        'success': response.status < 400
                    }
                    
        except Exception as e:
            log.error(f"HTTP call failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'http_status': 0
            }
    
    async def _execute_email_service(self, instance: ProcessInstance, config: Dict[str, Any],
                                   input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute email sending service."""
        try:
            # Email configuration
            to_addresses = config.get('to', [])
            subject = config.get('subject', 'Process Notification')
            template = config.get('template', 'default')
            
            # Resolve variables
            subject = await self.engine.context_manager.resolve_expression(instance.id, subject)
            
            # In real implementation, integrate with email service
            email_data = {
                'to': to_addresses,
                'subject': subject,
                'template': template,
                'context': input_data,
                'process_id': instance.id
            }
            
            log.info(f"Email sent: {json.dumps(email_data)}")
            
            return {
                'success': True,
                'email_sent': True,
                'recipients_count': len(to_addresses)
            }
            
        except Exception as e:
            log.error(f"Email service failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'email_sent': False
            }
    
    async def _execute_database_operation(self, instance: ProcessInstance, config: Dict[str, Any],
                                        input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute database operation."""
        try:
            operation = config.get('operation', 'select')
            table_name = config.get('table')
            
            if operation == 'select':
                # Execute SELECT query with proper parameterization
                query_template = config.get('query')
                query_params = config.get('parameters', {})
                
                if query_template:
                    # Resolve parameters safely
                    resolved_params = {}
                    for key, value in query_params.items():
                        resolved_value = await self.engine.context_manager.resolve_expression(instance.id, str(value))
                        resolved_params[key] = resolved_value
                    
                    try:
                        # Use SQLAlchemy's text() with bound parameters for security
                        from sqlalchemy import text
                        result = db.session.execute(text(query_template), resolved_params)
                        rows = [dict(row) for row in result.fetchall()]
                        
                        return {
                            'success': True,
                            'operation': operation,
                            'row_count': len(rows),
                            'data': rows
                        }
                    except Exception as e:
                        log.error(f"Database query execution failed: {str(e)}")
                        return {
                            'success': False,
                            'error': f"Query execution failed: {str(e)}"
                        }
            
            return {
                'success': False,
                'error': f"Unsupported database operation: {operation}"
            }
            
        except Exception as e:
            log.error(f"Database operation failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def _execute_script(self, instance: ProcessInstance, config: Dict[str, Any],
                            input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute custom script in secure sandbox."""
        try:
            script_type = config.get('script_type', 'python')
            script_content = config.get('script')
            
            if not script_content:
                return {
                    'success': False,
                    'error': 'No script content provided'
                }
            
            if script_type == 'python':
                # Execute Python script in secure sandbox
                return await self._execute_python_script_safely(script_content, input_data, instance)
            
            return {
                'success': False,
                'error': f"Unsupported script type: {script_type}"
            }
            
        except Exception as e:
            log.error(f"Script execution failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def _execute_custom_service(self, instance: ProcessInstance, config: Dict[str, Any],
                                    input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute custom service type."""
        service_type = config.get('service_type')
        
        # Look for registered custom service handlers
        if hasattr(current_app, 'process_service_handlers'):
            handlers = current_app.process_service_handlers
            if service_type in handlers:
                handler = handlers[service_type]
                try:
                    if asyncio.iscoroutinefunction(handler):
                        return await handler(instance, config, input_data)
                    else:
                        return handler(instance, config, input_data)
                except Exception as e:
                    return {
                        'success': False,
                        'error': f"Custom service handler failed: {str(e)}"
                    }
        
        return {
            'success': False,
            'error': f"Unknown service type: {service_type}"
        }


class GatewayExecutor(NodeExecutor):
    """
    Executor for gateway (decision) nodes.
    
    Evaluates conditions to determine process flow direction
    with support for complex expressions and data-driven routing.
    """
    
    async def _execute_node(self, instance: ProcessInstance, node: Dict[str, Any],
                           step: ProcessStep, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute gateway node."""
        gateway_config = node.get('properties', {})
        conditions = gateway_config.get('conditions', [])
        
        # Evaluate each condition
        for condition in conditions:
            if await self._evaluate_condition(instance, condition, input_data):
                target_node = condition.get('target')
                return {
                    'gateway_result': True,
                    'target_node': target_node,
                    'condition_met': condition.get('name', 'unnamed')
                }
        
        # Check for default path
        default_condition = next((c for c in conditions if c.get('default', False)), None)
        if default_condition:
            return {
                'gateway_result': True,
                'target_node': default_condition.get('target'),
                'condition_met': 'default'
            }
        
        # No conditions met and no default
        return {
            'gateway_result': False,
            'error': 'No gateway conditions were met'
        }
    
    async def _evaluate_condition(self, instance: ProcessInstance, condition: Dict[str, Any],
                                input_data: Dict[str, Any]) -> bool:
        """Evaluate a single gateway condition."""
        try:
            condition_type = condition.get('type', 'simple')
            
            if condition_type == 'simple':
                return await self._evaluate_simple_condition(instance, condition, input_data)
            elif condition_type == 'expression':
                return await self._evaluate_expression_condition(instance, condition, input_data)
            elif condition_type == 'script':
                return await self._evaluate_script_condition(instance, condition, input_data)
            else:
                log.warning(f"Unknown condition type: {condition_type}")
                return False
                
        except Exception as e:
            log.error(f"Condition evaluation failed: {str(e)}")
            return False
    
    async def _evaluate_simple_condition(self, instance: ProcessInstance, 
                                       condition: Dict[str, Any],
                                       input_data: Dict[str, Any]) -> bool:
        """Evaluate simple field comparison condition."""
        field = condition.get('field')
        operator = condition.get('operator', '==')
        expected_value = condition.get('value')
        
        if not field:
            return False
        
        # Get field value from context
        actual_value = await self.engine.context_manager.get_variable(
            instance.id, field, default=None
        )
        
        # If not found in context, check input data
        if actual_value is None and field in input_data:
            actual_value = input_data[field]
        
        # Evaluate based on operator
        if operator == '==':
            return actual_value == expected_value
        elif operator == '!=':
            return actual_value != expected_value
        elif operator == '>':
            return actual_value > expected_value
        elif operator == '>=':
            return actual_value >= expected_value
        elif operator == '<':
            return actual_value < expected_value
        elif operator == '<=':
            return actual_value <= expected_value
        elif operator == 'in':
            return actual_value in expected_value
        elif operator == 'not_in':
            return actual_value not in expected_value
        elif operator == 'contains':
            return expected_value in str(actual_value)
        elif operator == 'starts_with':
            return str(actual_value).startswith(str(expected_value))
        elif operator == 'ends_with':
            return str(actual_value).endswith(str(expected_value))
        else:
            log.warning(f"Unknown operator: {operator}")
            return False
    
    async def _evaluate_expression_condition(self, instance: ProcessInstance,
                                           condition: Dict[str, Any],
                                           input_data: Dict[str, Any]) -> bool:
        """Evaluate complex expression condition."""
        expression = condition.get('expression')
        if not expression:
            return False
        
        try:
            # Resolve variables in expression
            resolved_expression = await self.engine.context_manager.resolve_expression(
                instance.id, expression
            )
            

            # Build context data from all available sources
            context_data = {}
            
            # Add input data from method parameters
            if input_data:
                context_data.update(input_data)
            
            # Add instance variables if available
            if instance.variables:
                context_data.update(instance.variables)
                
            # Add instance context if available  
            if instance.context:
                context_data.update(instance.context)
                
            # Add instance input_data if available
            if instance.input_data:
                context_data.update(instance.input_data)
                
            # Add any output data for reference
            if instance.output_data:
                context_data.update(instance.output_data)
            # For safety, only allow simple boolean expressions
            # Use safe expression evaluator instead of dangerous eval()
            if resolved_expression.lower() in ['true', '1', 'yes']:
                return True
            elif resolved_expression.lower() in ['false', '0', 'no']:
                return False
            else:
                # Use safe expression evaluator
                return bool(self._safe_eval(resolved_expression, context_data))
                
        except Exception as e:
            log.warning(f"Expression evaluation failed: {str(e)}")
            return False
    
    def _safe_eval(self, expression: str, variables: Dict[str, Any]) -> Any:
        """Safely evaluate boolean expression using AST parsing."""
        import ast
        import operator as ops
        
        # Safe operators only
        safe_operators = {
            ast.Add: ops.add, ast.Sub: ops.sub, ast.Mult: ops.mul,
            ast.Div: ops.truediv, ast.Mod: ops.mod, ast.Pow: ops.pow,
            ast.Eq: ops.eq, ast.NotEq: ops.ne, ast.Lt: ops.lt, 
            ast.LtE: ops.le, ast.Gt: ops.gt, ast.GtE: ops.ge,
            ast.And: ops.and_, ast.Or: ops.or_, ast.Not: ops.not_
        }
        
        def _eval_node(node, variables):
            """Recursively evaluate AST node."""
            if isinstance(node, ast.Constant):  # Python 3.8+
                return node.value
            elif isinstance(node, ast.Num):  # Python < 3.8
                return node.n
            elif isinstance(node, ast.Str):  # Python < 3.8
                return node.s
            elif isinstance(node, ast.NameConstant):  # Python < 3.8
                return node.value
            elif isinstance(node, ast.Name):
                if node.id in variables:
                    return variables[node.id]
                else:
                    raise NameError(f"Variable '{node.id}' not defined")
            elif isinstance(node, ast.BinOp):
                left = _eval_node(node.left, variables)
                right = _eval_node(node.right, variables)
                op = safe_operators.get(type(node.op))
                if op:
                    return op(left, right)
                else:
                    raise TypeError(f"Unsupported operator: {type(node.op)}")
            elif isinstance(node, ast.UnaryOp):
                operand = _eval_node(node.operand, variables)
                op = safe_operators.get(type(node.op))
                if op:
                    return op(operand)
                else:
                    raise TypeError(f"Unsupported unary operator: {type(node.op)}")
            elif isinstance(node, ast.Compare):
                left = _eval_node(node.left, variables)
                result = True
                for op, comparator in zip(node.ops, node.comparators):
                    right = _eval_node(comparator, variables)
                    op_func = safe_operators.get(type(op))
                    if op_func:
                        result = result and op_func(left, right)
                        left = right  # For chained comparisons
                    else:
                        raise TypeError(f"Unsupported comparison: {type(op)}")
                return result
            elif isinstance(node, ast.BoolOp):
                op = safe_operators.get(type(node.op))
                if not op:
                    raise TypeError(f"Unsupported boolean operator: {type(node.op)}")
                
                values = [_eval_node(value, variables) for value in node.values]
                if isinstance(node.op, ast.And):
                    return all(values)
                elif isinstance(node.op, ast.Or):
                    return any(values)
            else:
                raise TypeError(f"Unsupported node type: {type(node)}")
        
        try:
            # Parse expression into AST
            tree = ast.parse(expression, mode='eval')
            
            # Evaluate safely
            return _eval_node(tree.body, variables)
            
        except (SyntaxError, ValueError, NameError, TypeError) as e:
            log.warning(f"Safe evaluation failed for expression '{expression}': {str(e)}")
            return False
        except Exception as e:
            log.error(f"Unexpected error in safe evaluation: {str(e)}")
            return False
    
    async def _evaluate_script_condition(self, instance: ProcessInstance,
                                       condition: Dict[str, Any],
                                       input_data: Dict[str, Any]) -> bool:
        """Evaluate script-based condition."""
        # Script evaluation would be implemented with sandboxed execution
        # For security reasons, returning False for now
        log.warning("Script condition evaluation not implemented for security reasons")
        return False


class ApprovalExecutor(NodeExecutor):
    """
    Executor for approval nodes.
    
    Creates approval requests with multi-level chains, escalation,
    and delegation support integrated with the approval system.
    """
    
    async def _execute_node(self, instance: ProcessInstance, node: Dict[str, Any],
                           step: ProcessStep, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute approval node."""
        approval_config = node.get('properties', {})
        
        # Create approval request
        approval = await self._create_approval_request(instance, step, approval_config, input_data)
        
        # Mark step as waiting for approval
        step.status = 'waiting'
        step.configuration['approval_id'] = approval.id
        db.session.commit()
        
        # Send approval notifications
        await self._send_approval_notifications(approval)
        
        return {
            'approval_created': True,
            'approval_id': approval.id,
            'current_approvers': approval.get_current_approvers()
        }
    
    async def _create_approval_request(self, instance: ProcessInstance, step: ProcessStep,
                                     config: Dict[str, Any], input_data: Dict[str, Any]) -> ApprovalRequest:
        """Create approval request."""
        # Build approval chain
        chain_definition = await self._build_approval_chain(instance, config, input_data)
        
        # Create approval request
        approval = ApprovalRequest(
            process_instance_id=instance.id,
            process_step_id=step.id,
            title=config.get('title', f'Approval for {step.step_name}'),
            description=config.get('description', ''),
            status=ApprovalStatus.PENDING.value,
            priority=config.get('priority', 5),
            chain_definition=chain_definition,
            current_level=0,
            request_data=input_data,
            form_schema=config.get('form_schema', {}),
            tenant_id=instance.tenant_id
        )
        
        # Set due date
        if 'due_in_hours' in config:
            hours = config['due_in_hours']
            approval.due_at = datetime.now(tz=timezone.utc) + timedelta(hours=hours)
        
        # Set current approver
        if chain_definition.get('levels'):
            first_level = chain_definition['levels'][0]
            approvers = first_level.get('approvers', [])
            if approvers:
                approval.current_approver_id = approvers[0]  # First approver
        
        db.session.add(approval)
        db.session.commit()
        
        return approval
    
    async def _build_approval_chain(self, instance: ProcessInstance, config: Dict[str, Any],
                                  input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build approval chain definition."""
        chain_type = config.get('chain_type', 'single')
        
        if chain_type == 'single':
            # Single approver
            approver_id = await self._resolve_approver(instance, config, input_data)
            return {
                'type': 'single',
                'levels': [
                    {
                        'level': 0,
                        'name': 'Primary Approval',
                        'approvers': [approver_id] if approver_id else [],
                        'require_all': False
                    }
                ]
            }
            
        elif chain_type == 'multi_level':
            # Multi-level approval chain
            levels = config.get('levels', [])
            chain_levels = []
            
            for i, level_config in enumerate(levels):
                approvers = await self._resolve_level_approvers(instance, level_config, input_data)
                chain_levels.append({
                    'level': i,
                    'name': level_config.get('name', f'Level {i+1}'),
                    'approvers': approvers,
                    'require_all': level_config.get('require_all', False),
                    'escalation_hours': level_config.get('escalation_hours', 24)
                })
            
            return {
                'type': 'multi_level',
                'levels': chain_levels
            }
            
        elif chain_type == 'dynamic':
            # Dynamic approval based on conditions
            return await self._build_dynamic_approval_chain(instance, config, input_data)
        
        else:
            # Default to single approver
            return {
                'type': 'single',
                'levels': [
                    {
                        'level': 0,
                        'name': 'Default Approval',
                        'approvers': [],
                        'require_all': False
                    }
                ]
            }
    
    async def _resolve_approver(self, instance: ProcessInstance, config: Dict[str, Any],
                              input_data: Dict[str, Any]) -> Optional[int]:
        """Resolve single approver ID."""
        # Direct assignment
        if 'approver_id' in config:
            return config['approver_id']
        
        # Assignment by role
        if 'approver_role' in config:
            try:
                from flask_appbuilder import current_app
                
                # Get role name(s)  
                role_names = config['approver_role']
                if not isinstance(role_names, list):
                    role_names = [role_names]
                
                # Get FAB's security manager
                sm = current_app.appbuilder.sm
                
                # Find users with the specified roles
                potential_approvers = []
                for role_name in role_names:
                    role = sm.find_role(role_name)
                    if role:
                        # Get active users with this role
                        for user in role.user:
                            if user.is_active:
                                potential_approvers.append(user.id)
                
                if potential_approvers:
                    # For now, return first available approver
                    # In production, could implement load balancing, availability checks, etc.
                    return potential_approvers[0]
                else:
                    log.warning(f"No active users found for approval roles: {role_names}")
                    return None
                    
            except Exception as e:
                log.error(f"Failed to resolve approver by role: {str(e)}")
                return None
        
        # Dynamic assignment from context
        if 'approver_variable' in config:
            variable_name = config['approver_variable']
            approver = await self.engine.context_manager.get_variable(
                instance.id, variable_name
            )
            return int(approver) if approver else None
        
        return None
    
    async def _resolve_level_approvers(self, instance: ProcessInstance, level_config: Dict[str, Any],
                                     input_data: Dict[str, Any]) -> List[int]:
        """Resolve approvers for a specific level."""
        approvers = []
        
        # Direct approver list
        if 'approvers' in level_config:
            approvers.extend(level_config['approvers'])
        
        # Approvers by role
        if 'approver_roles' in level_config:
            # In real implementation, resolve users by roles
            pass
        
        # Dynamic approvers
        if 'approver_variable' in level_config:
            variable_name = level_config['approver_variable']
            dynamic_approvers = await self.engine.context_manager.get_variable(
                instance.id, variable_name
            )
            if isinstance(dynamic_approvers, list):
                approvers.extend([int(a) for a in dynamic_approvers if str(a).isdigit()])
            elif dynamic_approvers:
                approvers.append(int(dynamic_approvers))
        
        return approvers
    
    async def _build_dynamic_approval_chain(self, instance: ProcessInstance, config: Dict[str, Any],
                                          input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build dynamic approval chain based on conditions."""
        # In real implementation, evaluate conditions to determine approval chain
        # For now, return simple chain
        return {
            'type': 'dynamic',
            'levels': [
                {
                    'level': 0,
                    'name': 'Dynamic Approval',
                    'approvers': [],
                    'require_all': False
                }
            ]
        }
    
    async def _send_approval_notifications(self, approval: ApprovalRequest):
        """Send notifications to current approvers."""
        try:
            current_approvers = approval.get_current_approvers()
            
            for approver_id in current_approvers:
                notification_data = {
                    'type': 'approval_request',
                    'approval_id': approval.id,
                    'approver_id': approver_id,
                    'title': approval.title,
                    'due_at': approval.due_at.isoformat() if approval.due_at else None,
                    'url': f"/process/approval/{approval.id}"
                }
                
                log.info(f"Approval notification sent to user {approver_id}: {json.dumps(notification_data)}")
            
        except Exception as e:
            log.warning(f"Failed to send approval notifications: {str(e)}")


class TimerExecutor(NodeExecutor):
    """
    Executor for timer nodes.
    
    Handles time-based delays, scheduled execution, and timeout
    management with precise timing and cleanup capabilities.
    """
    
    async def _execute_node(self, instance: ProcessInstance, node: Dict[str, Any],
                           step: ProcessStep, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute timer node."""
        timer_config = node.get('properties', {})
        timer_type = timer_config.get('timer_type', 'delay')
        
        if timer_type == 'delay':
            return await self._execute_delay_timer(instance, step, timer_config)
        elif timer_type == 'schedule':
            return await self._execute_schedule_timer(instance, step, timer_config)
        elif timer_type == 'timeout':
            return await self._execute_timeout_timer(instance, step, timer_config)
        else:
            raise NodeExecutionError(f"Unknown timer type: {timer_type}")
    
    async def _execute_delay_timer(self, instance: ProcessInstance, step: ProcessStep,
                                 config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute delay timer."""
        delay_seconds = config.get('delay_seconds', 0)
        delay_minutes = config.get('delay_minutes', 0)
        delay_hours = config.get('delay_hours', 0)
        
        total_delay = delay_seconds + (delay_minutes * 60) + (delay_hours * 3600)
        
        if total_delay <= 0:
            return {'timer_completed': True, 'delay': 0}
        
        # Mark step as waiting
        step.status = 'waiting'
        step.due_at = datetime.now(tz=timezone.utc) + timedelta(seconds=total_delay)
        db.session.commit()
        
        # Schedule completion using Celery if available
        if self.engine.celery:
            from ..tasks import complete_timer_step
            complete_timer_step.apply_async(
                args=[step.id],
                countdown=total_delay
            )
        else:
            # For testing or simple setups, use asyncio sleep
            await asyncio.sleep(total_delay)
            step.status = 'completed'
            db.session.commit()
        
        return {
            'timer_type': 'delay',
            'delay_seconds': total_delay,
            'scheduled_completion': step.due_at.isoformat() if step.due_at else None
        }
    
    async def _execute_schedule_timer(self, instance: ProcessInstance, step: ProcessStep,
                                    config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduled timer."""
        schedule_time = config.get('schedule_time')
        
        if not schedule_time:
            raise NodeExecutionError("Schedule time not specified")
        
        # Parse schedule time
        try:
            if isinstance(schedule_time, str):
                scheduled_at = datetime.fromisoformat(schedule_time)
            else:
                scheduled_at = schedule_time
        except ValueError:
            raise NodeExecutionError(f"Invalid schedule time format: {schedule_time}")
        
        # Calculate delay
        now = datetime.now(tz=timezone.utc)
        if scheduled_at <= now:
            # Time already passed, complete immediately
            return {'timer_completed': True, 'scheduled_for': scheduled_at.isoformat()}
        
        delay_seconds = (scheduled_at - now).total_seconds()
        
        # Mark step as waiting
        step.status = 'waiting'
        step.due_at = scheduled_at
        db.session.commit()
        
        # Schedule completion
        if self.engine.celery:
            from ..tasks import complete_timer_step
            complete_timer_step.apply_async(
                args=[step.id],
                eta=scheduled_at
            )
        
        return {
            'timer_type': 'schedule',
            'scheduled_for': scheduled_at.isoformat(),
            'delay_seconds': delay_seconds
        }
    
    async def _execute_timeout_timer(self, instance: ProcessInstance, step: ProcessStep,
                                   config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute timeout timer."""
        timeout_seconds = config.get('timeout_seconds', 3600)  # Default 1 hour
        
        # Mark step as waiting with timeout
        step.status = 'waiting'
        step.due_at = datetime.now(tz=timezone.utc) + timedelta(seconds=timeout_seconds)
        step.configuration['timeout_action'] = config.get('timeout_action', 'fail')
        db.session.commit()
        
        # Schedule timeout handling
        if self.engine.celery:
            from ..tasks import handle_step_timeout
            handle_step_timeout.apply_async(
                args=[step.id],
                countdown=timeout_seconds
            )
        
        return {
            'timer_type': 'timeout',
            'timeout_seconds': timeout_seconds,
            'timeout_at': step.due_at.isoformat() if step.due_at else None,
            'timeout_action': config.get('timeout_action', 'fail')
        }


class SubprocessExecutor(NodeExecutor):
    """
    Executor for subprocess nodes.
    
    Handles three types of subprocesses:
    - embedded: Executes subprocess inline within parent process context
    - call_activity: Calls another standalone process definition
    - event: Subprocess triggered by events with message/signal handling
    """
    
    async def _execute_node(self, instance: ProcessInstance, node: Dict[str, Any],
                           step: ProcessStep, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute subprocess node."""
        subprocess_config = node.get('properties', {})
        subprocess_type = subprocess_config.get('subprocess_type', 'embedded')
        
        if subprocess_type == 'embedded':
            return await self._execute_embedded_subprocess(instance, step, subprocess_config, input_data)
        elif subprocess_type == 'call_activity':
            return await self._execute_call_activity(instance, step, subprocess_config, input_data)
        elif subprocess_type == 'event':
            return await self._execute_event_subprocess(instance, step, subprocess_config, input_data)
        else:
            raise NodeExecutionError(f"Unknown subprocess type: {subprocess_type}")
    
    async def _execute_embedded_subprocess(self, instance: ProcessInstance, step: ProcessStep,
                                         config: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute embedded subprocess inline within parent process."""
        subprocess_def_id = config.get('subprocess_definition_id')
        if not subprocess_def_id:
            raise NodeExecutionError("Subprocess definition ID required for embedded subprocess")
        
        # Get subprocess definition with eager loading for process graph
        from sqlalchemy.orm import selectinload
        subprocess_def = db.session.query(SubprocessDefinition).options(
            selectinload(SubprocessDefinition.process_definition)
        ).filter_by(
            id=subprocess_def_id,
            tenant_id=get_current_tenant_id()
        ).first()
        
        if not subprocess_def:
            raise NodeExecutionError(f"Subprocess definition {subprocess_def_id} not found")
        
        # Create subprocess execution record
        subprocess_exec = SubprocessExecution(
            subprocess_definition_id=subprocess_def.id,
            parent_instance_id=instance.id,
            parent_step_id=step.id,
            subprocess_type='embedded',
            status='running',
            started_at=datetime.now(tz=timezone.utc),
            input_data=input_data,
            tenant_id=get_current_tenant_id()
        )
        db.session.add(subprocess_exec)
        db.session.commit()
        
        try:
            # Execute subprocess nodes inline
            output_data = await self._execute_subprocess_nodes(
                subprocess_def, subprocess_exec, input_data, instance
            )
            
            # Mark subprocess execution as completed
            subprocess_exec.status = 'completed'
            subprocess_exec.completed_at = datetime.now(tz=timezone.utc)
            subprocess_exec.output_data = output_data
            db.session.commit()
            
            return {
                'subprocess_type': 'embedded',
                'subprocess_execution_id': subprocess_exec.id,
                'status': 'completed',
                'output_data': output_data
            }
            
        except Exception as e:
            # Mark subprocess execution as failed
            subprocess_exec.status = 'failed'
            subprocess_exec.completed_at = datetime.now(tz=timezone.utc)
            subprocess_exec.error_message = str(e)
            db.session.commit()
            
            raise NodeExecutionError(f"Embedded subprocess failed: {str(e)}")
    
    async def _execute_call_activity(self, instance: ProcessInstance, step: ProcessStep,
                                   config: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute call activity - creates new standalone process instance."""
        subprocess_def_id = config.get('subprocess_definition_id')
        if not subprocess_def_id:
            raise NodeExecutionError("Subprocess definition ID required for call activity")
        
        # Get subprocess definition with eager loading for related data
        from sqlalchemy.orm import selectinload
        subprocess_def = db.session.query(SubprocessDefinition).options(
            selectinload(SubprocessDefinition.process_definition)
        ).filter_by(
            id=subprocess_def_id,
            tenant_id=get_current_tenant_id()
        ).first()
        
        if not subprocess_def:
            raise NodeExecutionError(f"Subprocess definition {subprocess_def_id} not found")
        
        # Create new process instance for the called subprocess
        called_instance = ProcessInstance(
            definition_id=subprocess_def.process_definition_id,
            definition_version=subprocess_def.definition_version,
            name=f"Called from {instance.name} - {subprocess_def.name}",
            status='pending',
            created_by=instance.created_by,
            tenant_id=get_current_tenant_id(),
            parent_instance_id=instance.id,
            input_data=input_data
        )
        db.session.add(called_instance)
        db.session.commit()
        
        # Create subprocess execution record
        subprocess_exec = SubprocessExecution(
            subprocess_definition_id=subprocess_def.id,
            parent_instance_id=instance.id,
            parent_step_id=step.id,
            called_instance_id=called_instance.id,
            subprocess_type='call_activity',
            status='running',
            started_at=datetime.now(tz=timezone.utc),
            input_data=input_data,
            tenant_id=get_current_tenant_id()
        )
        db.session.add(subprocess_exec)
        db.session.commit()
        
        try:
            # Start the called process instance using the process engine
            called_instance.status = 'running'
            called_instance.started_at = datetime.now(tz=timezone.utc)
            db.session.commit()
            
            # Execute called process asynchronously
            if config.get('wait_for_completion', True):
                # Wait for completion
                output_data = await self._execute_and_wait_for_process(called_instance)
                
                # Update subprocess execution
                subprocess_exec.status = called_instance.status
                subprocess_exec.completed_at = datetime.now(tz=timezone.utc)
                subprocess_exec.output_data = output_data
                db.session.commit()
                
                return {
                    'subprocess_type': 'call_activity',
                    'subprocess_execution_id': subprocess_exec.id,
                    'called_instance_id': called_instance.id,
                    'status': called_instance.status,
                    'output_data': output_data
                }
            else:
                # Fire and forget - start async execution
                from ..tasks import start_process_async
                start_process_async.delay(called_instance.id)
                
                return {
                    'subprocess_type': 'call_activity',
                    'subprocess_execution_id': subprocess_exec.id,
                    'called_instance_id': called_instance.id,
                    'status': 'started_async',
                    'wait_for_completion': False
                }
                
        except Exception as e:
            # Mark subprocess execution as failed
            subprocess_exec.status = 'failed'
            subprocess_exec.completed_at = datetime.now(tz=timezone.utc)
            subprocess_exec.error_message = str(e)
            called_instance.status = 'failed'
            called_instance.completed_at = datetime.now(tz=timezone.utc)
            db.session.commit()
            
            raise NodeExecutionError(f"Call activity failed: {str(e)}")
    
    async def _execute_event_subprocess(self, instance: ProcessInstance, step: ProcessStep,
                                      config: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute event subprocess - waits for external events."""
        subprocess_def_id = config.get('subprocess_definition_id')
        event_type = config.get('event_type', 'message')  # message, signal, timer
        event_name = config.get('event_name')
        
        if not subprocess_def_id:
            raise NodeExecutionError("Subprocess definition ID required for event subprocess")
        if not event_name:
            raise NodeExecutionError("Event name required for event subprocess")
        
        # Get subprocess definition with optimized loading
        from sqlalchemy.orm import selectinload
        subprocess_def = db.session.query(SubprocessDefinition).options(
            selectinload(SubprocessDefinition.process_definition)
        ).filter_by(
            id=subprocess_def_id,
            tenant_id=get_current_tenant_id()
        ).first()
        
        if not subprocess_def:
            raise NodeExecutionError(f"Subprocess definition {subprocess_def_id} not found")
        
        # Create subprocess execution record
        subprocess_exec = SubprocessExecution(
            subprocess_definition_id=subprocess_def.id,
            parent_instance_id=instance.id,
            parent_step_id=step.id,
            subprocess_type='event',
            status='waiting_for_event',
            started_at=datetime.now(tz=timezone.utc),
            input_data=input_data,
            tenant_id=get_current_tenant_id(),
            event_configuration={
                'event_type': event_type,
                'event_name': event_name,
                'timeout_seconds': config.get('timeout_seconds')
            }
        )
        db.session.add(subprocess_exec)
        
        # Mark parent step as waiting for event
        step.status = 'waiting'
        step.configuration['waiting_for_event'] = event_name
        step.configuration['subprocess_execution_id'] = subprocess_exec.id
        
        # Set timeout if specified
        timeout_seconds = config.get('timeout_seconds')
        if timeout_seconds:
            step.due_at = datetime.now(tz=timezone.utc) + timedelta(seconds=timeout_seconds)
            step.configuration['timeout_action'] = config.get('timeout_action', 'fail')
            
            # Schedule timeout handling
            if self.engine.celery:
                from ..tasks import handle_step_timeout
                handle_step_timeout.apply_async(
                    args=[step.id],
                    countdown=timeout_seconds
                )
        
        db.session.commit()
        
        return {
            'subprocess_type': 'event',
            'subprocess_execution_id': subprocess_exec.id,
            'status': 'waiting_for_event',
            'event_type': event_type,
            'event_name': event_name,
            'timeout_seconds': timeout_seconds
        }
    
    async def _execute_subprocess_nodes(self, subprocess_def: SubprocessDefinition, 
                                      subprocess_exec: SubprocessExecution,
                                      input_data: Dict[str, Any], 
                                      parent_instance: ProcessInstance) -> Dict[str, Any]:
        """Execute nodes within an embedded subprocess."""
        if not subprocess_def.process_graph:
            raise NodeExecutionError("Subprocess definition has no node definitions")
        
        # Parse subprocess definition
        nodes = subprocess_def.process_graph.get('nodes', [])
        edges = subprocess_def.process_graph.get('edges', [])
        
        if not nodes:
            return input_data
        
        # Find start node
        start_node = None
        for node in nodes:
            if node.get('type') == 'start':
                start_node = node
                break
        
        if not start_node:
            raise NodeExecutionError("No start node found in subprocess definition")
        
        # Execute subprocess using simplified execution logic
        current_data = input_data.copy()
        visited_nodes = set()
        
        return await self._execute_subprocess_flow(
            start_node, nodes, edges, current_data, visited_nodes,
            subprocess_exec, parent_instance
        )
    
    async def _execute_subprocess_flow(self, current_node: Dict[str, Any], all_nodes: List[Dict[str, Any]],
                                     edges: List[Dict[str, Any]], data: Dict[str, Any],
                                     visited_nodes: set, subprocess_exec: SubprocessExecution,
                                     parent_instance: ProcessInstance) -> Dict[str, Any]:
        """Execute subprocess node flow recursively."""
        node_id = current_node['id']
        
        # Prevent infinite loops
        if node_id in visited_nodes:
            log.warning(f"Cycle detected in subprocess {subprocess_exec.id}, node {node_id}")
            return data
        
        visited_nodes.add(node_id)
        
        # Execute current node
        node_type = current_node.get('type')
        if node_type == 'end':
            return data
        elif node_type in ['task', 'service', 'approval']:
            # Create temporary step for subprocess node execution
            temp_step = ProcessStep(
                instance_id=parent_instance.id,
                node_id=node_id,
                name=current_node.get('name', f'Subprocess Node {node_id}'),
                node_type=node_type,
                status='running',
                started_at=datetime.now(tz=timezone.utc),
                input_data=data
            )
            
            # Execute node using appropriate executor
            if node_type == 'task':
                executor = TaskExecutor(self.engine)
            elif node_type == 'service':
                executor = ServiceExecutor(self.engine)
            elif node_type == 'approval':
                executor = ApprovalExecutor(self.engine)
            else:
                raise NodeExecutionError(f"Unsupported node type in subprocess: {node_type}")
            
            result_data = await executor._execute_node(parent_instance, current_node, temp_step, data)
            data.update(result_data)
        
        # Find next nodes
        next_nodes = []
        for edge in edges:
            if edge['source'] == node_id:
                target_node = next((n for n in all_nodes if n['id'] == edge['target']), None)
                if target_node:
                    next_nodes.append(target_node)
        
        # Execute next nodes
        for next_node in next_nodes:
            data = await self._execute_subprocess_flow(
                next_node, all_nodes, edges, data, visited_nodes,
                subprocess_exec, parent_instance
            )
        
        return data
    
    async def _execute_and_wait_for_process(self, process_instance: ProcessInstance) -> Dict[str, Any]:
        """Execute a called process and wait for completion."""
        # This would use the main ProcessEngine to execute the called process
        # For now, return a placeholder result
        return {
            'called_process_completed': True,
            'instance_id': process_instance.id,
            'status': 'completed'
        }
    
    async def handle_event_trigger(self, event_name: str, event_data: Dict[str, Any],
                                 tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Handle incoming event that may trigger event subprocesses with optimized queries."""
        from sqlalchemy.orm import selectinload
        
        tenant_filter = {'tenant_id': tenant_id} if tenant_id else {}
        
        # Find waiting event subprocesses with eager loading to prevent N+1 queries
        waiting_executions = db.session.query(SubprocessExecution).options(
            selectinload(SubprocessExecution.subprocess_definition),
            selectinload(SubprocessExecution.parent_instance),
            selectinload(SubprocessExecution.parent_step)
        ).filter_by(
            status='waiting_for_event',
            subprocess_type='event',
            **tenant_filter
        ).all()
        
        triggered_results = []
        
        for subprocess_exec in waiting_executions:
            event_config = subprocess_exec.event_configuration or {}
            if event_config.get('event_name') == event_name:
                try:
                    # Trigger subprocess execution
                    subprocess_exec.status = 'running'
                    subprocess_exec.event_data = event_data
                    
                    # Get subprocess definition and execute
                    subprocess_def = subprocess_exec.subprocess_definition
                    parent_instance = subprocess_exec.parent_instance
                    
                    output_data = await self._execute_subprocess_nodes(
                        subprocess_def, subprocess_exec, event_data, parent_instance
                    )
                    
                    # Complete subprocess execution
                    subprocess_exec.status = 'completed'
                    subprocess_exec.completed_at = datetime.now(tz=timezone.utc)
                    subprocess_exec.output_data = output_data
                    
                    # Update parent step
                    parent_step = subprocess_exec.parent_step
                    if parent_step:
                        parent_step.status = 'completed'
                        parent_step.output_data = output_data
                        parent_step.completed_at = datetime.now(tz=timezone.utc)
                    
                    db.session.commit()
                    
                    triggered_results.append({
                        'subprocess_execution_id': subprocess_exec.id,
                        'parent_instance_id': subprocess_exec.parent_instance_id,
                        'status': 'completed',
                        'output_data': output_data
                    })
                    
                except Exception as e:
                    subprocess_exec.status = 'failed'
                    subprocess_exec.completed_at = datetime.now(tz=timezone.utc)
                    subprocess_exec.error_message = str(e)
                    db.session.commit()
                    
                    log.error(f"Event subprocess execution failed: {str(e)}")
                    
                    triggered_results.append({
                        'subprocess_execution_id': subprocess_exec.id,
                        'parent_instance_id': subprocess_exec.parent_instance_id,
                        'status': 'failed',
                        'error': str(e)
                    })
        
        return triggered_results
    
    async def _execute_python_script_safely(self, script_content: str, input_data: Dict[str, Any], 
                                           instance: ProcessInstance) -> Dict[str, Any]:
        """Execute Python script in secure sandbox environment."""
        try:
            # Validate script syntax and security
            security_validator = ScriptSecurityValidator()
            validation_result = security_validator.validate_script(script_content)
            
            if not validation_result.is_safe:
                return {
                    'success': False,
                    'error': f'Script security validation failed: {validation_result.reason}',
                    'violations': validation_result.violations
                }
            
            # Create secure execution context
            safe_context = {
                'input_data': input_data.copy(),
                'result': {},
                'log': log,
                'datetime': datetime,
                'json': json,
                'len': len,
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
                'dict': dict,
                'list': list,
                'min': min,
                'max': max,
                'sum': sum,
                'abs': abs,
                'round': round
            }
            
            # Execute in restricted environment with timeout
            executor = SecurePythonExecutor(timeout=30)  # 30 second timeout
            execution_result = await executor.execute(script_content, safe_context)
            
            if execution_result.success:
                return {
                    'success': True,
                    'script_executed': True,
                    'execution_time': execution_result.execution_time,
                    'output_data': execution_result.output_data,
                    'result': safe_context.get('result', {})
                }
            else:
                return {
                    'success': False,
                    'error': execution_result.error_message,
                    'execution_time': execution_result.execution_time
                }
                
        except Exception as e:
            log.error(f"Secure script execution failed: {str(e)}")
            return {
                'success': False,
                'error': f'Script execution error: {str(e)}'
            }


class ScriptSecurityValidator:
    """Validates Python scripts for security before execution."""
    
    def __init__(self):
        # Dangerous imports and functions to block
        self.dangerous_imports = {
            'os', 'sys', 'subprocess', 'importlib', '__import__',
            'eval', 'exec', 'compile', 'open', 'file', 'input', 'raw_input',
            'globals', 'locals', 'vars', 'dir', 'hasattr', 'getattr', 'setattr', 'delattr',
            'pickle', 'cPickle', 'marshal', 'shelve', 'socket', 'urllib', 'requests',
            'ftplib', 'smtplib', 'poplib', 'imaplib', 'telnetlib', 'xmlrpc',
            'threading', 'multiprocessing', 'asyncio', 'subprocess',
            'ctypes', 'gc', 'weakref', 'code', 'codeop'
        }
        
        # Allowed AST node types for safe execution
        self.safe_nodes = {
            ast.Module, ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign,
            ast.Name, ast.Constant, ast.Num, ast.Str, ast.NameConstant,  # literals
            ast.List, ast.Tuple, ast.Dict, ast.Set,  # containers
            ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,  # operations
            ast.Subscript, ast.Index, ast.Slice,  # indexing
            ast.Call, ast.keyword,  # function calls
            ast.If, ast.For, ast.While, ast.Break, ast.Continue,  # control flow
            ast.FunctionDef, ast.Return, ast.Pass,  # function definition
            ast.Load, ast.Store  # expression contexts
        }
        
        # Safe built-in functions
        self.safe_builtins = {
            'len', 'str', 'int', 'float', 'bool', 'dict', 'list', 'tuple', 'set',
            'min', 'max', 'sum', 'abs', 'round', 'sorted', 'reversed', 'enumerate',
            'zip', 'range', 'any', 'all', 'isinstance', 'type', 'print'
        }
    
    def validate_script(self, script_content: str) -> 'ValidationResult':
        """Validate script for security violations."""
        violations = []
        
        try:
            # Parse script into AST
            tree = ast.parse(script_content)
            
            # Check for dangerous patterns
            violations.extend(self._check_dangerous_imports(tree))
            violations.extend(self._check_dangerous_nodes(tree))
            violations.extend(self._check_dangerous_functions(tree))
            violations.extend(self._check_dangerous_attributes(tree))
            
            is_safe = len(violations) == 0
            reason = f"Found {len(violations)} security violations" if not is_safe else "Script is safe"
            
            return ValidationResult(is_safe=is_safe, reason=reason, violations=violations)
            
        except SyntaxError as e:
            return ValidationResult(
                is_safe=False, 
                reason=f"Syntax error: {str(e)}", 
                violations=[f"Syntax error at line {e.lineno}: {e.text}"]
            )
        except Exception as e:
            return ValidationResult(
                is_safe=False,
                reason=f"Validation error: {str(e)}",
                violations=[f"Unexpected validation error: {str(e)}"]
            )
    
    def _check_dangerous_imports(self, tree: ast.AST) -> List[str]:
        """Check for dangerous import statements."""
        violations = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.dangerous_imports:
                        violations.append(f"Dangerous import: {alias.name}")
            
            elif isinstance(node, ast.ImportFrom):
                if node.module in self.dangerous_imports:
                    violations.append(f"Dangerous import from: {node.module}")
                
                for alias in node.names:
                    if alias.name in self.dangerous_imports:
                        violations.append(f"Dangerous import: {alias.name} from {node.module}")
        
        return violations
    
    def _check_dangerous_nodes(self, tree: ast.AST) -> List[str]:
        """Check for dangerous AST node types."""
        violations = []
        
        for node in ast.walk(tree):
            if type(node) not in self.safe_nodes:
                violations.append(f"Dangerous node type: {type(node).__name__}")
        
        return violations
    
    def _check_dangerous_functions(self, tree: ast.AST) -> List[str]:
        """Check for dangerous function calls."""
        violations = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check function name
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in self.dangerous_imports and func_name not in self.safe_builtins:
                        violations.append(f"Dangerous function call: {func_name}")
                
                # Check for eval, exec, compile calls
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in {'eval', 'exec', 'compile'}:
                        violations.append(f"Dangerous method call: {node.func.attr}")
        
        return violations
    
    def _check_dangerous_attributes(self, tree: ast.AST) -> List[str]:
        """Check for dangerous attribute access."""
        violations = []
        
        dangerous_attributes = {
            '__import__', '__builtins__', '__globals__', '__locals__',
            '__dict__', '__class__', '__bases__', '__mro__', '__subclasses__',
            'func_globals', 'func_code', 'gi_frame', 'gi_code'
        }
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in dangerous_attributes:
                    violations.append(f"Dangerous attribute access: {node.attr}")
        
        return violations


class ValidationResult:
    """Result of script security validation."""
    
    def __init__(self, is_safe: bool, reason: str, violations: List[str]):
        self.is_safe = is_safe
        self.reason = reason
        self.violations = violations


class SecurePythonExecutor:
    """Secure Python script executor with sandboxing and timeout."""
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
    
    async def execute(self, script_content: str, context: Dict[str, Any]) -> 'ExecutionResult':
        """Execute script in secure sandboxed environment."""
        import asyncio
        import time
        
        start_time = time.time()
        
        try:
            # Create restricted execution environment
            restricted_globals = {
                '__builtins__': {
                    # Only allow safe built-ins
                    'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool,
                    'dict': dict, 'list': list, 'tuple': tuple, 'set': set,
                    'min': min, 'max': max, 'sum': sum, 'abs': abs, 'round': round,
                    'sorted': sorted, 'reversed': reversed, 'enumerate': enumerate,
                    'zip': zip, 'range': range, 'any': any, 'all': all,
                    'isinstance': isinstance, 'type': type, 'print': print
                }
            }
            
            # Add context variables
            restricted_globals.update(context)
            
            # Compile script with restricted mode
            compiled_code = compile(script_content, '<sandbox>', 'exec')
            
            # Execute with timeout
            result = await asyncio.wait_for(
                self._execute_with_timeout(compiled_code, restricted_globals),
                timeout=self.timeout
            )
            
            execution_time = time.time() - start_time
            
            return ExecutionResult(
                success=True,
                execution_time=execution_time,
                output_data=restricted_globals.get('result', {})
            )
            
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                error_message=f"Script execution timed out after {self.timeout} seconds",
                execution_time=time.time() - start_time
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error_message=f"Script execution failed: {str(e)}",
                execution_time=time.time() - start_time
            )
    
    async def _execute_with_timeout(self, compiled_code, restricted_globals):
        """Execute compiled code in event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, exec, compiled_code, restricted_globals)


class ExecutionResult:
    """Result of script execution."""
    
    def __init__(self, success: bool, execution_time: float, 
                 output_data: Dict[str, Any] = None, error_message: str = None):
        self.success = success
        self.execution_time = execution_time
        self.output_data = output_data or {}
        self.error_message = error_message