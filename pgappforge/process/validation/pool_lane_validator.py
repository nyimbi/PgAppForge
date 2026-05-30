"""
Pool/Lane and Subprocess Validation Module.

Provides comprehensive validation logic for BPMN pools, lanes, and subprocess
configurations including organizational workflow structure validation.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from flask import current_app
from pgappforge import db
from pgappforge.models.tenant_context import get_current_tenant_id

from ..models.process_models import (
    ProcessDefinition, ProcessPool, ProcessLane, 
    SubprocessDefinition, SubprocessExecution
)
from ..security.integration import pool_lane_security_manager
from ..security.validation import ProcessValidator, ValidationError

log = logging.getLogger(__name__)


class PoolLaneValidator:
    """
    Validator for Pool/Lane configurations and organizational structures.
    
    Provides validation for BPMN pools and lanes including role assignments,
    organizational hierarchy, and workflow structure compliance.
    """
    
    def __init__(self):
        self.max_pool_depth = 5  # Maximum nested pool depth
        self.max_lanes_per_pool = 20  # Maximum lanes per pool
        self.reserved_pool_names = ['System', 'Admin', 'Default']
        self.required_pool_types = ['participant', 'blackbox', 'collapsed']
    
    def validate_pool_configuration(self, pool_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate pool configuration data.
        
        Args:
            pool_data: Pool configuration dictionary
            
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        try:
            # Basic field validation
            name = pool_data.get('name', '').strip()
            if not name:
                errors.append("Pool name is required")
            elif len(name) < 2:
                errors.append("Pool name must be at least 2 characters long")
            elif len(name) > 100:
                errors.append("Pool name cannot exceed 100 characters")
            elif name in self.reserved_pool_names:
                errors.append(f"Pool name '{name}' is reserved")
            
            # Pool type validation
            pool_type = pool_data.get('pool_type', '').lower()
            if pool_type not in self.required_pool_types:
                errors.append(f"Pool type must be one of: {', '.join(self.required_pool_types)}")
            
            # Organization validation
            organization = pool_data.get('organization', '').strip()
            if organization and len(organization) > 200:
                errors.append("Organization name cannot exceed 200 characters")
            
            # Configuration validation
            config = pool_data.get('configuration', {})
            if config:
                config_errors = self._validate_pool_config_object(config)
                errors.extend(config_errors)
            
            # Check for duplicate pool names in tenant
            if name and not self._is_pool_name_unique(name, pool_data.get('id')):
                errors.append(f"Pool name '{name}' already exists in this tenant")
            
            # Validate organizational hierarchy if specified
            parent_pool_id = pool_data.get('parent_pool_id')
            if parent_pool_id:
                hierarchy_errors = self._validate_pool_hierarchy(parent_pool_id, pool_data.get('id'))
                errors.extend(hierarchy_errors)
            
            return len(errors) == 0, errors
            
        except Exception as e:
            log.error(f"Pool validation error: {str(e)}")
            errors.append(f"Validation error: {str(e)}")
            return False, errors
    
    def validate_lane_configuration(self, lane_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate lane configuration data.
        
        Args:
            lane_data: Lane configuration dictionary
            
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        try:
            # Basic field validation
            name = lane_data.get('name', '').strip()
            if not name:
                errors.append("Lane name is required")
            elif len(name) < 2:
                errors.append("Lane name must be at least 2 characters long")
            elif len(name) > 100:
                errors.append("Lane name cannot exceed 100 characters")
            
            # Pool reference validation
            pool_id = lane_data.get('pool_id')
            if not pool_id:
                errors.append("Pool ID is required for lane")
            else:
                pool = db.session.query(ProcessPool).filter_by(
                    id=pool_id,
                    tenant_id=get_current_tenant_id()
                ).first()
                if not pool:
                    errors.append("Referenced pool not found or access denied")
                else:
                    # Check lane count limit
                    existing_lanes = len(pool.lanes or [])
                    if existing_lanes >= self.max_lanes_per_pool:
                        errors.append(f"Pool cannot have more than {self.max_lanes_per_pool} lanes")
            
            # Role assignment validation
            assigned_role = lane_data.get('assigned_role', '').strip()
            if assigned_role:
                role_errors = self._validate_role_assignment(assigned_role, pool_id)
                errors.extend(role_errors)
            
            # Workload balancing validation
            workload_balancing = lane_data.get('workload_balancing', 'round_robin')
            valid_balancing_types = ['round_robin', 'priority', 'capacity', 'random']
            if workload_balancing not in valid_balancing_types:
                errors.append(f"Workload balancing must be one of: {', '.join(valid_balancing_types)}")
            
            # Configuration validation
            config = lane_data.get('configuration', {})
            if config:
                config_errors = self._validate_lane_config_object(config)
                errors.extend(config_errors)
            
            # Check for duplicate lane names within pool
            if name and pool_id and not self._is_lane_name_unique_in_pool(name, pool_id, lane_data.get('id')):
                errors.append(f"Lane name '{name}' already exists in this pool")
            
            return len(errors) == 0, errors
            
        except Exception as e:
            log.error(f"Lane validation error: {str(e)}")
            errors.append(f"Validation error: {str(e)}")
            return False, errors
    
    def validate_pool_lane_workflow_structure(self, process_definition: ProcessDefinition) -> Tuple[bool, List[str]]:
        """
        Validate that pools and lanes are properly structured in a workflow.
        
        Args:
            process_definition: Process definition to validate
            
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        try:
            if not process_definition.process_graph:
                return True, []  # No pool/lane structure to validate
            
            nodes = process_definition.process_graph.get('nodes', [])
            edges = process_definition.process_graph.get('edges', [])
            
            # Find pool and lane nodes
            pool_nodes = [n for n in nodes if n.get('type') == 'pool']
            lane_nodes = [n for n in nodes if n.get('type') == 'lane']
            
            if not pool_nodes and not lane_nodes:
                return True, []  # No pool/lane structure
            
            # Validate pool structure
            for pool_node in pool_nodes:
                pool_errors = self._validate_pool_node_structure(pool_node, nodes, edges)
                errors.extend(pool_errors)
            
            # Validate lane structure
            for lane_node in lane_nodes:
                lane_errors = self._validate_lane_node_structure(lane_node, pool_nodes, nodes)
                errors.extend(lane_errors)
            
            # Validate organizational consistency
            org_errors = self._validate_organizational_consistency(pool_nodes, lane_nodes)
            errors.extend(org_errors)
            
            return len(errors) == 0, errors
            
        except Exception as e:
            log.error(f"Pool/Lane workflow structure validation error: {str(e)}")
            errors.append(f"Structure validation error: {str(e)}")
            return False, errors
    
    def _validate_pool_config_object(self, config: Dict[str, Any]) -> List[str]:
        """Validate pool configuration object."""
        errors = []
        
        # Validate allowed configuration keys
        allowed_keys = [
            'default_role', 'auto_assign_tasks', 'priority', 'capacity',
            'working_hours', 'timezone', 'escalation_rules'
        ]
        
        for key in config:
            if key not in allowed_keys:
                errors.append(f"Unknown configuration key: {key}")
        
        # Validate specific configuration values
        if 'priority' in config:
            priority = config['priority']
            if not isinstance(priority, int) or priority < 1 or priority > 10:
                errors.append("Priority must be an integer between 1 and 10")
        
        if 'capacity' in config:
            capacity = config['capacity']
            if not isinstance(capacity, int) or capacity < 1:
                errors.append("Capacity must be a positive integer")
        
        if 'working_hours' in config:
            working_hours = config['working_hours']
            if not isinstance(working_hours, dict):
                errors.append("Working hours must be an object")
            else:
                hours_errors = self._validate_working_hours(working_hours)
                errors.extend(hours_errors)
        
        return errors
    
    def _validate_lane_config_object(self, config: Dict[str, Any]) -> List[str]:
        """Validate lane configuration object."""
        errors = []
        
        # Validate allowed configuration keys
        allowed_keys = [
            'max_concurrent_tasks', 'auto_assignment', 'priority_rules',
            'escalation_timeout', 'notification_rules', 'performance_metrics'
        ]
        
        for key in config:
            if key not in allowed_keys:
                errors.append(f"Unknown lane configuration key: {key}")
        
        # Validate specific values
        if 'max_concurrent_tasks' in config:
            max_tasks = config['max_concurrent_tasks']
            if not isinstance(max_tasks, int) or max_tasks < 1 or max_tasks > 100:
                errors.append("Max concurrent tasks must be between 1 and 100")
        
        if 'escalation_timeout' in config:
            timeout = config['escalation_timeout']
            if not isinstance(timeout, int) or timeout < 60:  # Minimum 1 minute
                errors.append("Escalation timeout must be at least 60 seconds")
        
        return errors
    
    def _validate_role_assignment(self, role_name: str, pool_id: Optional[int]) -> List[str]:
        """Validate role assignment for a lane."""
        errors = []
        
        try:
            # Check if role exists in PgAppForge
            available_roles = pool_lane_security_manager.get_available_roles(get_current_tenant_id())
            role_names = [role['name'] for role in available_roles]
            
            if role_name not in role_names:
                errors.append(f"Role '{role_name}' does not exist or is not available")
            
            # Check role compatibility with pool if pool exists
            if pool_id:
                pool = db.session.query(ProcessPool).get(pool_id)
                if pool and pool.pool_type == 'system':
                    system_roles = ['Admin', 'ProcessAdmin', 'SystemUser']
                    if role_name not in system_roles:
                        errors.append(f"Role '{role_name}' cannot be assigned to system pool")
            
        except Exception as e:
            log.error(f"Role validation error: {str(e)}")
            errors.append("Failed to validate role assignment")
        
        return errors
    
    def _validate_working_hours(self, working_hours: Dict[str, Any]) -> List[str]:
        """Validate working hours configuration."""
        errors = []
        
        required_keys = ['start_time', 'end_time', 'days_of_week']
        for key in required_keys:
            if key not in working_hours:
                errors.append(f"Working hours missing required key: {key}")
        
        # Validate time format
        if 'start_time' in working_hours:
            if not self._is_valid_time_format(working_hours['start_time']):
                errors.append("Start time must be in HH:MM format")
        
        if 'end_time' in working_hours:
            if not self._is_valid_time_format(working_hours['end_time']):
                errors.append("End time must be in HH:MM format")
        
        # Validate days of week
        if 'days_of_week' in working_hours:
            days = working_hours['days_of_week']
            if not isinstance(days, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
                errors.append("Days of week must be a list of integers 0-6 (Monday=0)")
        
        return errors
    
    def _is_valid_time_format(self, time_str: str) -> bool:
        """Check if string is valid HH:MM time format."""
        try:
            datetime.strptime(time_str, '%H:%M')
            return True
        except ValueError:
            return False
    
    def _is_pool_name_unique(self, name: str, excluding_id: Optional[int] = None) -> bool:
        """Check if pool name is unique within tenant."""
        try:
            query = db.session.query(ProcessPool).filter_by(
                name=name,
                tenant_id=get_current_tenant_id()
            )
            
            if excluding_id:
                query = query.filter(ProcessPool.id != excluding_id)
            
            return query.first() is None
            
        except Exception as e:
            log.error(f"Pool name uniqueness check error: {str(e)}")
            return False
    
    def _is_lane_name_unique_in_pool(self, name: str, pool_id: int, excluding_id: Optional[int] = None) -> bool:
        """Check if lane name is unique within pool."""
        try:
            query = db.session.query(ProcessLane).filter_by(
                name=name,
                pool_id=pool_id,
                tenant_id=get_current_tenant_id()
            )
            
            if excluding_id:
                query = query.filter(ProcessLane.id != excluding_id)
            
            return query.first() is None
            
        except Exception as e:
            log.error(f"Lane name uniqueness check error: {str(e)}")
            return False
    
    def _validate_pool_hierarchy(self, parent_pool_id: int, pool_id: Optional[int] = None) -> List[str]:
        """Validate pool organizational hierarchy."""
        errors = []
        
        try:
            # Check parent pool exists
            parent_pool = db.session.query(ProcessPool).filter_by(
                id=parent_pool_id,
                tenant_id=get_current_tenant_id()
            ).first()
            
            if not parent_pool:
                errors.append("Parent pool not found")
                return errors
            
            # Check for circular hierarchy
            if pool_id and self._has_circular_hierarchy(parent_pool_id, pool_id):
                errors.append("Circular pool hierarchy detected")
            
            # Check hierarchy depth
            depth = self._get_pool_hierarchy_depth(parent_pool_id)
            if depth >= self.max_pool_depth:
                errors.append(f"Pool hierarchy depth cannot exceed {self.max_pool_depth}")
            
        except Exception as e:
            log.error(f"Pool hierarchy validation error: {str(e)}")
            errors.append("Failed to validate pool hierarchy")
        
        return errors
    
    def _has_circular_hierarchy(self, parent_id: int, pool_id: int) -> bool:
        """Check for circular references in pool hierarchy."""
        visited = set()
        current_id = parent_id
        
        while current_id and current_id not in visited:
            visited.add(current_id)
            
            if current_id == pool_id:
                return True
            
            # Get parent of current pool
            pool = db.session.query(ProcessPool).get(current_id)
            current_id = getattr(pool, 'parent_pool_id', None) if pool else None
        
        return False
    
    def _get_pool_hierarchy_depth(self, pool_id: int) -> int:
        """Get depth of pool hierarchy."""
        depth = 0
        current_id = pool_id
        
        while current_id and depth < self.max_pool_depth + 1:
            pool = db.session.query(ProcessPool).get(current_id)
            if not pool:
                break
            
            current_id = getattr(pool, 'parent_pool_id', None)
            depth += 1
        
        return depth
    
    def _validate_pool_node_structure(self, pool_node: Dict[str, Any], 
                                    all_nodes: List[Dict[str, Any]], 
                                    edges: List[Dict[str, Any]]) -> List[str]:
        """Validate pool node structure in workflow."""
        errors = []
        
        pool_id = pool_node.get('id')
        if not pool_id:
            errors.append("Pool node missing ID")
            return errors
        
        # Check if pool has lanes
        pool_lanes = [n for n in all_nodes if n.get('type') == 'lane' and n.get('pool_id') == pool_id]
        
        if not pool_lanes:
            errors.append(f"Pool '{pool_node.get('label', pool_id)}' has no lanes")
        
        # Validate pool contains tasks
        pool_tasks = self._get_tasks_in_pool(pool_id, all_nodes, edges)
        if not pool_tasks and pool_lanes:
            errors.append(f"Pool '{pool_node.get('label', pool_id)}' contains no tasks")
        
        return errors
    
    def _validate_lane_node_structure(self, lane_node: Dict[str, Any], 
                                    pool_nodes: List[Dict[str, Any]], 
                                    all_nodes: List[Dict[str, Any]]) -> List[str]:
        """Validate lane node structure in workflow."""
        errors = []
        
        lane_id = lane_node.get('id')
        pool_id = lane_node.get('pool_id')
        
        if not lane_id:
            errors.append("Lane node missing ID")
        
        if not pool_id:
            errors.append(f"Lane '{lane_node.get('label', lane_id)}' not assigned to a pool")
        else:
            # Check if referenced pool exists in workflow
            pool_exists = any(p.get('id') == pool_id for p in pool_nodes)
            if not pool_exists:
                errors.append(f"Lane '{lane_node.get('label', lane_id)}' references non-existent pool")
        
        return errors
    
    def _validate_organizational_consistency(self, pool_nodes: List[Dict[str, Any]], 
                                           lane_nodes: List[Dict[str, Any]]) -> List[str]:
        """Validate organizational consistency across pools and lanes."""
        errors = []
        
        # Check for role conflicts between lanes
        role_assignments = {}
        for lane in lane_nodes:
            role = lane.get('properties', {}).get('assigned_role')
            if role:
                if role in role_assignments:
                    errors.append(f"Role '{role}' assigned to multiple lanes")
                else:
                    role_assignments[role] = lane.get('id')
        
        # Validate pool organization alignment
        organizations = set()
        for pool in pool_nodes:
            org = pool.get('properties', {}).get('organization')
            if org:
                organizations.add(org)
        
        if len(organizations) > 3:  # Allow max 3 different organizations
            errors.append("Too many different organizations in single process (max 3)")
        
        return errors
    
    def _get_tasks_in_pool(self, pool_id: str, all_nodes: List[Dict[str, Any]], 
                          edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get all tasks within a pool."""
        # Find lanes in pool
        pool_lanes = [n for n in all_nodes if n.get('type') == 'lane' and n.get('pool_id') == pool_id]
        lane_ids = {lane.get('id') for lane in pool_lanes}
        
        # Find tasks in lanes
        tasks_in_pool = []
        for node in all_nodes:
            if node.get('type') in ['task', 'service', 'approval']:
                assigned_lane = node.get('properties', {}).get('assigned_lane')
                if assigned_lane in lane_ids:
                    tasks_in_pool.append(node)
        
        return tasks_in_pool


class SubprocessValidator:
    """
    Validator for subprocess definitions and execution configurations.
    
    Provides validation for all subprocess types including embedded processes,
    call activities, and event-driven subprocesses.
    """
    
    def __init__(self):
        self.max_subprocess_depth = 3  # Maximum nested subprocess depth
        self.valid_subprocess_types = ['embedded', 'call_activity', 'event']
        self.valid_event_types = ['message', 'signal', 'timer', 'conditional']
    
    def validate_subprocess_definition(self, subprocess_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate subprocess definition data.
        
        Args:
            subprocess_data: Subprocess definition dictionary
            
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        try:
            # Basic field validation
            name = subprocess_data.get('name', '').strip()
            if not name:
                errors.append("Subprocess name is required")
            elif len(name) < 2:
                errors.append("Subprocess name must be at least 2 characters long")
            elif len(name) > 100:
                errors.append("Subprocess name cannot exceed 100 characters")
            
            # Subprocess type validation
            subprocess_type = subprocess_data.get('subprocess_type', '').lower()
            if subprocess_type not in self.valid_subprocess_types:
                errors.append(f"Subprocess type must be one of: {', '.join(self.valid_subprocess_types)}")
            
            # Parent process validation
            process_definition_id = subprocess_data.get('process_definition_id')
            if not process_definition_id:
                errors.append("Parent process definition ID is required")
            else:
                parent_errors = self._validate_parent_process(process_definition_id)
                errors.extend(parent_errors)
            
            # Definition validation
            definition = subprocess_data.get('definition', {})
            if definition:
                def_errors = self._validate_subprocess_definition_structure(definition, subprocess_type)
                errors.extend(def_errors)
            
            # Parameters validation
            parameters = subprocess_data.get('parameters', {})
            if parameters:
                param_errors = self._validate_subprocess_parameters(parameters)
                errors.extend(param_errors)
            
            # Type-specific validation
            if subprocess_type == 'event':
                event_errors = self._validate_event_subprocess_config(subprocess_data)
                errors.extend(event_errors)
            elif subprocess_type == 'call_activity':
                call_errors = self._validate_call_activity_config(subprocess_data)
                errors.extend(call_errors)
            
            return len(errors) == 0, errors
            
        except Exception as e:
            log.error(f"Subprocess validation error: {str(e)}")
            errors.append(f"Validation error: {str(e)}")
            return False, errors
    
    def validate_subprocess_execution_request(self, execution_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate subprocess execution request.
        
        Args:
            execution_data: Execution request data
            
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        try:
            # Subprocess definition validation
            subprocess_definition_id = execution_data.get('subprocess_definition_id')
            if not subprocess_definition_id:
                errors.append("Subprocess definition ID is required")
            else:
                subprocess_def = db.session.query(SubprocessDefinition).filter_by(
                    id=subprocess_definition_id,
                    tenant_id=get_current_tenant_id()
                ).first()
                
                if not subprocess_def:
                    errors.append("Subprocess definition not found")
                elif not subprocess_def.is_active:
                    errors.append("Subprocess definition is not active")
                else:
                    # Validate input data against parameters
                    input_data = execution_data.get('input_data', {})
                    param_errors = self._validate_input_against_parameters(
                        input_data, subprocess_def.parameters or {}
                    )
                    errors.extend(param_errors)
            
            # Parent instance validation if provided
            parent_instance_id = execution_data.get('parent_instance_id')
            if parent_instance_id:
                parent_errors = self._validate_parent_instance(parent_instance_id)
                errors.extend(parent_errors)
            
            return len(errors) == 0, errors
            
        except Exception as e:
            log.error(f"Subprocess execution validation error: {str(e)}")
            errors.append(f"Execution validation error: {str(e)}")
            return False, errors
    
    def _validate_parent_process(self, process_definition_id: int) -> List[str]:
        """Validate parent process definition."""
        errors = []
        
        try:
            parent_def = db.session.query(ProcessDefinition).filter_by(
                id=process_definition_id,
                tenant_id=get_current_tenant_id()
            ).first()
            
            if not parent_def:
                errors.append("Parent process definition not found")
            elif not parent_def.is_active:
                errors.append("Parent process definition is not active")
            
        except Exception as e:
            log.error(f"Parent process validation error: {str(e)}")
            errors.append("Failed to validate parent process")
        
        return errors
    
    def _validate_subprocess_definition_structure(self, definition: Dict[str, Any], 
                                                 subprocess_type: str) -> List[str]:
        """Validate subprocess definition structure."""
        errors = []
        
        # Basic structure validation
        if not isinstance(definition, dict):
            errors.append("Subprocess definition must be a dictionary")
            return errors
        
        nodes = definition.get('nodes', [])
        edges = definition.get('edges', [])
        
        if not isinstance(nodes, list):
            errors.append("Definition nodes must be a list")
        
        if not isinstance(edges, list):
            errors.append("Definition edges must be a list")
        
        if not nodes:
            errors.append("Subprocess definition must contain at least one node")
            return errors
        
        # Validate nodes
        start_nodes = []
        end_nodes = []
        
        for node in nodes:
            if not isinstance(node, dict):
                errors.append("Each node must be a dictionary")
                continue
            
            node_type = node.get('type')
            if not node_type:
                errors.append("Each node must have a type")
                continue
            
            if node_type == 'start':
                start_nodes.append(node)
            elif node_type == 'end':
                end_nodes.append(node)
        
        # Validate start/end nodes
        if not start_nodes:
            errors.append("Subprocess must have at least one start node")
        if len(start_nodes) > 1:
            errors.append("Subprocess can have only one start node")
        
        if not end_nodes:
            errors.append("Subprocess must have at least one end node")
        
        return errors
    
    def _validate_subprocess_parameters(self, parameters: Dict[str, Any]) -> List[str]:
        """Validate subprocess parameters."""
        errors = []
        
        if not isinstance(parameters, dict):
            errors.append("Parameters must be a dictionary")
            return errors
        
        for param_name, param_config in parameters.items():
            if not isinstance(param_config, dict):
                errors.append(f"Parameter '{param_name}' configuration must be a dictionary")
                continue
            
            # Validate parameter configuration
            param_type = param_config.get('type')
            if not param_type:
                errors.append(f"Parameter '{param_name}' missing type")
            elif param_type not in ['string', 'number', 'boolean', 'object', 'array']:
                errors.append(f"Parameter '{param_name}' has invalid type: {param_type}")
            
            # Validate required flag
            required = param_config.get('required', False)
            if not isinstance(required, bool):
                errors.append(f"Parameter '{param_name}' required flag must be boolean")
        
        return errors
    
    def _validate_event_subprocess_config(self, subprocess_data: Dict[str, Any]) -> List[str]:
        """Validate event subprocess specific configuration."""
        errors = []
        
        parameters = subprocess_data.get('parameters', {})
        
        # Event subprocesses require event configuration
        event_config = parameters.get('event_configuration', {})
        if not event_config:
            errors.append("Event subprocess requires event_configuration parameter")
            return errors
        
        event_type = event_config.get('event_type')
        if not event_type:
            errors.append("Event configuration missing event_type")
        elif event_type not in self.valid_event_types:
            errors.append(f"Event type must be one of: {', '.join(self.valid_event_types)}")
        
        event_name = event_config.get('event_name')
        if not event_name:
            errors.append("Event configuration missing event_name")
        elif not isinstance(event_name, str) or len(event_name.strip()) < 1:
            errors.append("Event name must be a non-empty string")
        
        # Validate timeout if specified
        timeout_seconds = event_config.get('timeout_seconds')
        if timeout_seconds is not None:
            if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
                errors.append("Event timeout must be a positive integer")
        
        return errors
    
    def _validate_call_activity_config(self, subprocess_data: Dict[str, Any]) -> List[str]:
        """Validate call activity specific configuration."""
        errors = []
        
        parameters = subprocess_data.get('parameters', {})
        
        # Call activities may specify wait behavior
        wait_for_completion = parameters.get('wait_for_completion', True)
        if not isinstance(wait_for_completion, bool):
            errors.append("wait_for_completion parameter must be boolean")
        
        # Validate called process reference if specified
        called_process_id = parameters.get('called_process_definition_id')
        if called_process_id:
            try:
                called_def = db.session.query(ProcessDefinition).filter_by(
                    id=called_process_id,
                    tenant_id=get_current_tenant_id()
                ).first()
                
                if not called_def:
                    errors.append("Referenced called process definition not found")
                elif not called_def.is_active:
                    errors.append("Referenced called process definition is not active")
            except Exception as e:
                log.error(f"Called process validation error: {str(e)}")
                errors.append("Failed to validate called process reference")
        
        return errors
    
    def _validate_input_against_parameters(self, input_data: Dict[str, Any], 
                                         parameters: Dict[str, Any]) -> List[str]:
        """Validate input data against defined parameters."""
        errors = []
        
        # Check required parameters
        for param_name, param_config in parameters.items():
            if param_config.get('required', False):
                if param_name not in input_data:
                    errors.append(f"Required parameter '{param_name}' is missing")
                elif input_data[param_name] is None:
                    errors.append(f"Required parameter '{param_name}' cannot be null")
        
        # Validate provided input data types
        for input_name, input_value in input_data.items():
            if input_name in parameters:
                expected_type = parameters[input_name].get('type')
                if expected_type and not self._is_correct_type(input_value, expected_type):
                    errors.append(f"Parameter '{input_name}' has incorrect type, expected {expected_type}")
        
        return errors
    
    def _is_correct_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type."""
        if value is None:
            return True  # Allow null values unless marked as required
        
        type_checkers = {
            'string': lambda v: isinstance(v, str),
            'number': lambda v: isinstance(v, (int, float)),
            'boolean': lambda v: isinstance(v, bool),
            'object': lambda v: isinstance(v, dict),
            'array': lambda v: isinstance(v, list)
        }
        
        checker = type_checkers.get(expected_type)
        return checker(value) if checker else True
    
    def _validate_parent_instance(self, parent_instance_id: int) -> List[str]:
        """Validate parent process instance."""
        errors = []
        
        try:
            from ..models.process_models import ProcessInstance
            
            parent_instance = db.session.query(ProcessInstance).filter_by(
                id=parent_instance_id,
                tenant_id=get_current_tenant_id()
            ).first()
            
            if not parent_instance:
                errors.append("Parent process instance not found")
            elif parent_instance.status not in ['running', 'suspended']:
                errors.append("Parent process instance is not in a valid state for subprocess execution")
        
        except Exception as e:
            log.error(f"Parent instance validation error: {str(e)}")
            errors.append("Failed to validate parent instance")
        
        return errors


# Global validator instances
pool_lane_validator = PoolLaneValidator()
subprocess_validator = SubprocessValidator()


def validate_bpmn_organizational_structure(process_definition: ProcessDefinition) -> Tuple[bool, List[str]]:
    """
    Comprehensive validation of BPMN organizational structure.
    
    Args:
        process_definition: Process definition to validate
        
    Returns:
        Tuple of (is_valid, error_messages)
    """
    all_errors = []
    
    try:
        # Validate pool/lane structure
        structure_valid, structure_errors = pool_lane_validator.validate_pool_lane_workflow_structure(process_definition)
        all_errors.extend(structure_errors)
        
        # Validate subprocess references in process
        subprocess_errors = _validate_subprocess_references_in_process(process_definition)
        all_errors.extend(subprocess_errors)
        
        # Cross-validation between pools/lanes and subprocesses
        cross_errors = _validate_pool_subprocess_integration(process_definition)
        all_errors.extend(cross_errors)
        
        return len(all_errors) == 0, all_errors
        
    except Exception as e:
        log.error(f"BPMN organizational structure validation error: {str(e)}")
        all_errors.append(f"Structure validation failed: {str(e)}")
        return False, all_errors


def _validate_subprocess_references_in_process(process_definition: ProcessDefinition) -> List[str]:
    """Validate subprocess references within process definition."""
    errors = []
    
    try:
        if not process_definition.process_graph:
            return errors
        
        nodes = process_definition.process_graph.get('nodes', [])
        subprocess_nodes = [n for n in nodes if n.get('type') == 'subprocess']
        
        for subprocess_node in subprocess_nodes:
            properties = subprocess_node.get('properties', {})
            subprocess_def_id = properties.get('subprocess_definition_id')
            
            if subprocess_def_id:
                subprocess_def = db.session.query(SubprocessDefinition).filter_by(
                    id=subprocess_def_id,
                    tenant_id=get_current_tenant_id()
                ).first()
                
                if not subprocess_def:
                    errors.append(f"Subprocess node '{subprocess_node.get('label', 'unnamed')}' references non-existent subprocess definition")
                elif not subprocess_def.is_active:
                    errors.append(f"Subprocess node '{subprocess_node.get('label', 'unnamed')}' references inactive subprocess definition")
        
    except Exception as e:
        log.error(f"Subprocess reference validation error: {str(e)}")
        errors.append("Failed to validate subprocess references")
    
    return errors


def _validate_pool_subprocess_integration(process_definition: ProcessDefinition) -> List[str]:
    """Validate integration between pools/lanes and subprocesses."""
    errors = []
    
    try:
        if not process_definition.process_graph:
            return errors
        
        nodes = process_definition.process_graph.get('nodes', [])
        subprocess_nodes = [n for n in nodes if n.get('type') == 'subprocess']
        lane_nodes = [n for n in nodes if n.get('type') == 'lane']
        
        # Check if subprocesses are properly assigned to lanes
        for subprocess_node in subprocess_nodes:
            properties = subprocess_node.get('properties', {})
            assigned_lane = properties.get('assigned_lane')
            
            if assigned_lane:
                lane_exists = any(lane.get('id') == assigned_lane for lane in lane_nodes)
                if not lane_exists:
                    errors.append(f"Subprocess '{subprocess_node.get('label', 'unnamed')}' assigned to non-existent lane")
        
    except Exception as e:
        log.error(f"Pool-subprocess integration validation error: {str(e)}")
        errors.append("Failed to validate pool-subprocess integration")
    
    return errors