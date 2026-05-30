"""
Secure Expression Evaluator for Approval Workflows

This module provides secure evaluation of dynamic expressions used in approval
workflows, preventing SQL injection and other code injection attacks.

SECURITY FEATURES:
- Whitelisted expression patterns only
- No dynamic code execution
- Parameterized database queries
- Input validation and sanitization
- Comprehensive audit logging
"""

import re
import logging
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta, timezone

from .cache_manager import get_cache_manager, CacheKeyPrefix, cache_result

from sqlalchemy import bindparam
from flask import current_app
from pgappforge import db

from ..models.process_models import ProcessInstance
from ...security.sqla.models import User
from .crypto_config import SecureCryptoConfig
from .audit_logger import ApprovalAuditLogger

log = logging.getLogger(__name__)


class ExpressionType(Enum):
    """Types of supported expressions."""
    USER_ATTRIBUTE = "user_attribute"
    INSTANCE_DATA = "instance_data"
    ORGANIZATIONAL = "organizational"
    THRESHOLD = "threshold"


@dataclass
class ExpressionContext:
    """Context for expression evaluation."""
    instance_id: int
    initiator_id: int
    tenant_id: int
    priority: str
    request_data: Dict[str, Any]


class SecurityViolation(Exception):
    """Raised when expression evaluation detects security violation."""
    pass


class SecureExpressionEvaluator:
    """
    Secure expression evaluator for approval workflow dynamic routing.

    SECURITY IMPROVEMENTS:
    - CVE-2024-004: Prevents SQL injection through expression manipulation
    - CVE-2024-005: Blocks code injection attacks
    - CVE-2024-006: Implements secure pattern matching
    """

    # Whitelisted expression patterns with strict validation
    ALLOWED_EXPRESSIONS = {
        # User data patterns
        'input_data.manager_id': {
            'type': ExpressionType.INSTANCE_DATA,
            'description': 'Manager ID from input data',
            'validator': lambda x: isinstance(x, (int, str)) and str(x).isdigit(),
            'evaluator': '_evaluate_input_data_field'
        },
        'input_data.department_id': {
            'type': ExpressionType.INSTANCE_DATA,
            'description': 'Department ID from input data',
            'validator': lambda x: isinstance(x, (int, str)) and str(x).isdigit(),
            'evaluator': '_evaluate_input_data_field'
        },
        'input_data.cost_center': {
            'type': ExpressionType.INSTANCE_DATA,
            'description': 'Cost center from input data',
            'validator': lambda x: isinstance(x, str) and len(x) <= 20,
            'evaluator': '_evaluate_input_data_field'
        },

        # Organizational hierarchy patterns
        'initiator_manager': {
            'type': ExpressionType.ORGANIZATIONAL,
            'description': 'Direct manager of request initiator',
            'validator': lambda x: True,  # Handled by database query
            'evaluator': '_evaluate_initiator_manager'
        },
        'department_head': {
            'type': ExpressionType.ORGANIZATIONAL,
            'description': 'Head of initiator department',
            'validator': lambda x: True,
            'evaluator': '_evaluate_department_head'
        },
        'cost_center_manager': {
            'type': ExpressionType.ORGANIZATIONAL,
            'description': 'Manager of cost center',
            'validator': lambda x: True,
            'evaluator': '_evaluate_cost_center_manager'
        },

        # Threshold-based patterns
        'amount_threshold_manager': {
            'type': ExpressionType.THRESHOLD,
            'description': 'Manager based on amount threshold',
            'validator': lambda x: True,
            'evaluator': '_evaluate_amount_threshold_manager'
        }
    }

    def __init__(self, audit_logger: Optional[ApprovalAuditLogger] = None, config: Optional[Dict] = None):
        self.audit_logger = audit_logger or ApprovalAuditLogger()
        self._expression_cache = {}  # Cache for validated expressions
        
        # PERFORMANCE OPTIMIZATION: Add caching for frequently accessed data
        self._department_head_cache = {}  # Cache for department head lookups
        self._cost_center_manager_cache = {}  # Cache for cost center manager lookups
        self._manager_role_cache = {}  # Cache for role-based manager lookups
        self._cache_ttl = 300  # 5 minutes TTL for cached data
        self._last_cache_clear = datetime.now(tz=timezone.utc)
        
        # SECURITY IMPROVEMENT: Configurable business logic instead of hardcoded values
        self.config = config or {}
        
        # Configurable amount thresholds - can be overridden via config
        self.amount_thresholds = self.config.get('amount_thresholds', [
            {'threshold': 10000, 'manager_role': 'vp_finance', 'description': 'VP Finance approval for high-value items'},
            {'threshold': 5000, 'manager_role': 'finance_manager', 'description': 'Finance Manager approval for medium-value items'},
            {'threshold': 1000, 'manager_role': 'department_manager', 'description': 'Department Manager approval for standard items'},
            {'threshold': 0, 'manager_role': 'team_lead', 'description': 'Team Lead approval for small items'}
        ])
        
        # Validate threshold configuration
        self._validate_threshold_config()
        
        # Clear expired cache entries periodically
        self._clear_expired_cache()
        
        # Configurable role mappings
        self.role_mappings = self.config.get('role_mappings', {
            'vp_finance': {'department': 'finance', 'level': 'executive'},
            'finance_manager': {'department': 'finance', 'level': 'manager'},
            'department_manager': {'department': None, 'level': 'manager'},
            'team_lead': {'department': None, 'level': 'lead'}
        })

    def evaluate_expression(self, expression: str, context: ExpressionContext) -> Optional[int]:
        """
        Securely evaluate a dynamic approver expression.

        Args:
            expression: Expression to evaluate (must be whitelisted)
            context: Evaluation context with required data

        Returns:
            int: User ID of resolved approver, or None if evaluation fails

        Raises:
            SecurityViolation: If expression is not allowed or contains suspicious patterns
        """
        try:
            # Step 1: Validate expression format
            self._validate_expression_format(expression)

            # Step 2: Check against whitelist
            if expression not in self.ALLOWED_EXPRESSIONS:
                self._log_security_violation(
                    "unauthorized_expression",
                    expression,
                    context,
                    {"reason": "Expression not in whitelist"}
                )
                raise SecurityViolation(f"Expression '{expression}' not allowed")

            # Step 3: Get expression configuration
            expr_config = self.ALLOWED_EXPRESSIONS[expression]

            # Step 4: Evaluate using appropriate handler
            evaluator_method = getattr(self, expr_config['evaluator'])
            result = evaluator_method(expression, context)

            # Step 5: Validate result
            if result is not None and not isinstance(result, int):
                self._log_security_violation(
                    "invalid_expression_result",
                    expression,
                    context,
                    {"result_type": type(result).__name__}
                )
                return None

            # Step 6: Log successful evaluation
            self.audit_logger.log_security_event('expression_evaluated', {
                'expression': expression,
                'context_instance_id': context.instance_id,
                'context_initiator_id': context.initiator_id,
                'result_user_id': result,
                'expression_type': expr_config['type'].value
            })

            return result

        except SecurityViolation:
            raise
        except Exception as e:
            self._log_security_violation(
                "expression_evaluation_error",
                expression,
                context,
                {"error": str(e), "error_type": type(e).__name__}
            )
            log.error(f"Expression evaluation failed: {expression} - {e}")
            return None

    def _validate_expression_format(self, expression: str) -> None:
        """
        Validate expression format for basic security.

        Args:
            expression: Expression to validate

        Raises:
            SecurityViolation: If expression format is invalid
        """
        # Check length
        if len(expression) > 100:
            raise SecurityViolation("Expression too long")

        # Check for dangerous patterns
        dangerous_patterns = [
            r';',  # SQL statement separator
            r'--',  # SQL comment
            r'/\*',  # SQL block comment start
            r'\*/',  # SQL block comment end
            r'union\s+select',  # SQL union injection
            r'drop\s+table',  # SQL drop statement
            r'delete\s+from',  # SQL delete statement
            r'insert\s+into',  # SQL insert statement
            r'update\s+.*\s+set',  # SQL update statement
            r'exec\s*\(',  # Function execution
            r'eval\s*\(',  # Code evaluation
            r'__import__',  # Python import
            r'subprocess',  # System command execution
            r'os\.',  # OS module access
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, expression, re.IGNORECASE):
                raise SecurityViolation(f"Dangerous pattern detected: {pattern}")

        # Must match allowed character pattern
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_\.]*$', expression):
            raise SecurityViolation("Invalid characters in expression")

    def _evaluate_input_data_field(self, expression: str, context: ExpressionContext) -> Optional[int]:
        """
        Evaluate input_data field expressions securely.

        Args:
            expression: Expression like 'input_data.manager_id'
            context: Evaluation context

        Returns:
            int: User ID from input data
        """
        # Extract field name securely
        field_match = re.match(r'^input_data\.([a-zA-Z_][a-zA-Z0-9_]*)$', expression)
        if not field_match:
            return None

        field_name = field_match.group(1)
        
        # CRITICAL SECURITY FIX: Whitelist allowed field names to prevent SQL injection
        ALLOWED_FIELDS = {
            'manager_id': {'type': 'integer'},
            'department_id': {'type': 'integer'},
            'cost_center': {'type': 'string'},
            'amount': {'type': 'float'},
            'priority': {'type': 'string'},
            'workflow_type': {'type': 'string'}
        }
        
        if field_name not in ALLOWED_FIELDS:
            self._log_security_violation(
                "field_not_in_whitelist",
                expression,
                context,
                {
                    "field_name": field_name,
                    "allowed_fields": list(ALLOWED_FIELDS.keys()),
                    "reason": "Field name not in security whitelist"
                }
            )
            raise SecurityViolation(f"Field '{field_name}' not in whitelist")

        # Get instance data with parameterized query
        instance = db.session.query(ProcessInstance).filter(
            ProcessInstance.id == bindparam('instance_id'),
            ProcessInstance.tenant_id == bindparam('tenant_id')
        ).params(
            instance_id=context.instance_id,
            tenant_id=context.tenant_id
        ).first()

        if not instance or not instance.input_data:
            return None

        # Safely extract field value
        field_value = instance.input_data.get(field_name)
        if field_value is None:
            return None

        # Validate field value
        expr_config = self.ALLOWED_EXPRESSIONS[expression]
        if not expr_config['validator'](field_value):
            self._log_security_violation(
                "invalid_field_value",
                expression,
                context,
                {"field_name": field_name, "field_value": str(field_value)}
            )
            return None

        try:
            return int(field_value)
        except (ValueError, TypeError):
            return None

    def _evaluate_initiator_manager(self, expression: str, context: ExpressionContext) -> Optional[int]:
        """
        Evaluate initiator manager expression securely.

        Args:
            expression: 'initiator_manager'
            context: Evaluation context

        Returns:
            int: Manager user ID
        """
        # Get initiator with parameterized query
        initiator = db.session.query(User).filter(
            User.id == bindparam('initiator_id'),
            User.active == True
        ).params(initiator_id=context.initiator_id).first()

        if not initiator:
            return None

        # Check if user has manager relationship
        if hasattr(initiator, 'manager_id') and initiator.manager_id:
            # Verify manager is active
            manager = db.session.query(User).filter(
                User.id == bindparam('manager_id'),
                User.active == True
            ).params(manager_id=initiator.manager_id).first()

            if manager:
                return manager.id

        return None

    def _evaluate_department_head(self, expression: str, context: ExpressionContext) -> Optional[int]:
        """
        Evaluate department head expression securely with caching optimization.

        Args:
            expression: 'department_head'
            context: Evaluation context

        Returns:
            int: Department head user ID
        """
        # Get initiator with department info using secure query
        try:
            from sqlalchemy import and_
            from pgappforge.security.sqla.models import User
            
            initiator = db.session.query(User).filter(
                and_(
                    User.id == bindparam('initiator_id'),
                    User.active == True
                )
            ).params(initiator_id=context.initiator_id).first()

            if not initiator:
                return None

            # Get department from user - support multiple department field patterns
            department_id = None
            for dept_field in ['department_id', 'dept_id', 'department']:
                if hasattr(initiator, dept_field):
                    dept_value = getattr(initiator, dept_field)
                    if dept_value:
                        department_id = dept_value.id if hasattr(dept_value, 'id') else dept_value
                        break

            if not department_id:
                return None

            # PERFORMANCE OPTIMIZATION: Use cached batch query instead of individual query
            dept_heads_map = self._get_cached_or_query_department_heads([department_id])
            return dept_heads_map.get(department_id)

        except Exception as e:
            log.error(f"Error evaluating department head: {e}")
            return None

    def _evaluate_cost_center_manager(self, expression: str, context: ExpressionContext) -> Optional[int]:
        """
        Evaluate cost center manager expression securely with caching optimization.

        Args:
            expression: 'cost_center_manager'
            context: Evaluation context

        Returns:
            int: Cost center manager user ID
        """
        # Get cost center from instance data using secure query
        try:
            from sqlalchemy import and_
            
            instance = db.session.query(ProcessInstance).filter(
                and_(
                    ProcessInstance.id == bindparam('instance_id'),
                    ProcessInstance.tenant_id == bindparam('tenant_id')
                )
            ).params(
                instance_id=context.instance_id,
                tenant_id=context.tenant_id
            ).first()

            if not instance or not instance.input_data:
                return None

            cost_center = instance.input_data.get('cost_center')
            if not cost_center:
                return None

            # PERFORMANCE OPTIMIZATION: Use cached batch query instead of individual query
            cc_managers_map = self._get_cached_or_query_cost_center_managers([cost_center])
            return cc_managers_map.get(cost_center)

        except Exception as e:
            log.error(f"Error evaluating cost center manager: {e}")
            return None

    def _evaluate_amount_threshold_manager(self, expression: str, context: ExpressionContext) -> Optional[int]:
        """
        Evaluate amount threshold-based manager expression securely.

        Args:
            expression: 'amount_threshold_manager'
            context: Evaluation context

        Returns:
            int: Manager user ID based on amount threshold
        """
        # Get amount from instance data
        instance = db.session.query(ProcessInstance).filter(
            ProcessInstance.id == bindparam('instance_id'),
            ProcessInstance.tenant_id == bindparam('tenant_id')
        ).params(
            instance_id=context.instance_id,
            tenant_id=context.tenant_id
        ).first()

        if not instance or not instance.input_data:
            return None

        amount = instance.input_data.get('amount')
        if amount is None:
            return None

        try:
            amount_value = float(amount)
        except (ValueError, TypeError):
            return None

        # Use configurable amount thresholds instead of hardcoded values
        # Sort thresholds by amount descending to check highest thresholds first
        sorted_thresholds = sorted(self.amount_thresholds, key=lambda x: x['threshold'], reverse=True)

        for threshold_config in sorted_thresholds:
            threshold_amount = threshold_config['threshold']
            manager_role = threshold_config['manager_role']
            
            if amount_value >= threshold_amount:
                # Log threshold evaluation for audit
                self.audit_logger.log_security_event('threshold_evaluation', {
                    'expression': expression,
                    'amount': amount_value,
                    'threshold': threshold_amount,
                    'manager_role': manager_role,
                    'context_instance_id': context.instance_id,
                    'description': threshold_config.get('description', 'No description')
                })
                
                # Get manager by role using enhanced role resolution
                return self._get_manager_by_role(manager_role, context)

        return None

    def _get_manager_by_role(self, role: str, context: ExpressionContext) -> Optional[int]:
        """
        Get manager by role securely with caching optimization.

        Args:
            role: Manager role
            context: Evaluation context

        Returns:
            int: Manager user ID
        """
        # SECURITY IMPROVEMENT: Enhanced role-based manager resolution
        if role not in self.role_mappings:
            self.audit_logger.log_security_event('unknown_manager_role', {
                'role': role,
                'context_instance_id': context.instance_id,
                'available_roles': list(self.role_mappings.keys())
            })
            return None
        
        # PERFORMANCE OPTIMIZATION: Check cache first
        self._clear_expired_cache()
        cache_key = f"{role}_{context.tenant_id}"
        
        if cache_key in self._manager_role_cache:
            return self._manager_role_cache[cache_key]
        
        role_config = self.role_mappings[role]
        
        try:
            from pgappforge import db
            from ...security.sqla.models import User, Role
            
            # Query for user with the specific role
            # This is a basic implementation - customize based on your User/Role model
            query = db.session.query(User).join(User.roles).filter(
                Role.name == role,
                User.active == True
            )
            
            # If role is department-specific, filter by department
            if role_config.get('department'):
                query = query.filter(User.department == role_config['department'])
            
            # Get the first active user with this role
            manager = query.first()
            
            if manager:
                # PERFORMANCE OPTIMIZATION: Cache the result
                self._manager_role_cache[cache_key] = manager.id
                
                self.audit_logger.log_security_event('manager_resolved', {
                    'role': role,
                    'manager_id': manager.id,
                    'manager_username': manager.username,
                    'context_instance_id': context.instance_id
                })
                return manager.id
            else:
                # PERFORMANCE OPTIMIZATION: Cache negative result
                self._manager_role_cache[cache_key] = None
                
                self.audit_logger.log_security_event('manager_not_found', {
                    'role': role,
                    'role_config': role_config,
                    'context_instance_id': context.instance_id
                })
                return None
                
        except Exception as e:
            # Don't cache errors to allow retries
            self.audit_logger.log_security_event('manager_resolution_error', {
                'role': role,
                'error': str(e),
                'error_type': type(e).__name__,
                'context_instance_id': context.instance_id
            })
            return None

    def _validate_threshold_config(self) -> None:
        """Validate the threshold configuration for security and consistency."""
        if not self.amount_thresholds:
            raise ValueError("Amount thresholds configuration cannot be empty")
        
        for i, threshold in enumerate(self.amount_thresholds):
            if not isinstance(threshold, dict):
                raise ValueError(f"Threshold {i} must be a dictionary")
            
            required_fields = ['threshold', 'manager_role']
            for field in required_fields:
                if field not in threshold:
                    raise ValueError(f"Threshold {i} missing required field: {field}")
            
            if not isinstance(threshold['threshold'], (int, float)):
                raise ValueError(f"Threshold {i} 'threshold' must be numeric")
            
            if threshold['threshold'] < 0:
                raise ValueError(f"Threshold {i} 'threshold' cannot be negative")
            
            if not isinstance(threshold['manager_role'], str):
                raise ValueError(f"Threshold {i} 'manager_role' must be a string")
        
        # Check for duplicate thresholds
        threshold_values = [t['threshold'] for t in self.amount_thresholds]
        if len(threshold_values) != len(set(threshold_values)):
            raise ValueError("Duplicate threshold values detected")

    def _clear_expired_cache(self):
        """Clear expired cache entries to prevent memory leaks."""
        now = datetime.now(tz=timezone.utc)
        if (now - self._last_cache_clear).total_seconds() > self._cache_ttl:
            self._department_head_cache.clear()
            self._cost_center_manager_cache.clear()
            self._manager_role_cache.clear()
            self._last_cache_clear = now

    @cache_result(CacheKeyPrefix.DEPARTMENT_HEAD, ttl=300, key_args=['department_ids'])
    def _get_cached_or_query_department_heads(self, department_ids: List[int]) -> Dict[int, int]:
        """
        Get department heads for multiple departments with centralized caching to prevent N+1 queries.
        
        Args:
            department_ids: List of department IDs
            
        Returns:
            dict: Mapping of department_id -> user_id for department heads
        """
        cache_manager = get_cache_manager()
        result = {}
        uncached_dept_ids = []
        
        # Check cache first for each department
        for dept_id in department_ids:
            cached_head = cache_manager.get(CacheKeyPrefix.DEPARTMENT_HEAD, dept_id)
            if cached_head is not None:
                if cached_head != "NOT_FOUND":  # Handle negative caching
                    result[dept_id] = cached_head
            else:
                uncached_dept_ids.append(dept_id)
        
        # Batch query for uncached departments
        if uncached_dept_ids:
            try:
                from sqlalchemy import and_, or_
                from pgappforge.security.sqla.models import User, Role
                
                # Single batch query for all department heads
                dept_heads = db.session.query(
                    User.id,
                    # Support multiple department field patterns
                    User.department_id.label('dept_id') if hasattr(User, 'department_id') else 
                    User.dept_id.label('dept_id') if hasattr(User, 'dept_id') else
                    User.id.label('dept_id')  # Fallback
                ).join(User.roles).filter(
                    and_(
                        Role.name.in_(['DepartmentHead', 'Department Head', 'Manager']),
                        User.active == True
                    )
                ).filter(
                    # Support multiple department association patterns
                    or_(
                        User.department_id.in_(uncached_dept_ids) if hasattr(User, 'department_id') else False,
                        User.dept_id.in_(uncached_dept_ids) if hasattr(User, 'dept_id') else False
                    )
                ).all()
                
                # Process results and cache them individually
                found_dept_ids = set()
                for user_id, dept_id in dept_heads:
                    if dept_id in uncached_dept_ids:
                        result[dept_id] = user_id
                        cache_manager.set(CacheKeyPrefix.DEPARTMENT_HEAD, dept_id, value=user_id, ttl=300)
                        found_dept_ids.add(dept_id)
                
                # Cache negative results to avoid repeated queries
                for dept_id in uncached_dept_ids:
                    if dept_id not in found_dept_ids:
                        cache_manager.set(CacheKeyPrefix.DEPARTMENT_HEAD, dept_id, value="NOT_FOUND", ttl=300)
                        
            except Exception as e:
                log.error(f"Error in batch department head query: {e}")
        
        return result

    @cache_result(CacheKeyPrefix.COST_CENTER_MGR, ttl=300, key_args=['cost_centers'])
    def _get_cached_or_query_cost_center_managers(self, cost_centers: List[str]) -> Dict[str, int]:
        """
        Get cost center managers for multiple cost centers with centralized caching to prevent N+1 queries.
        
        Args:
            cost_centers: List of cost center codes
            
        Returns:
            dict: Mapping of cost_center -> user_id for managers
        """
        cache_manager = get_cache_manager()
        result = {}
        uncached_cost_centers = []
        
        # Check cache first for each cost center
        for cc in cost_centers:
            cached_manager = cache_manager.get(CacheKeyPrefix.COST_CENTER_MGR, cc)
            if cached_manager is not None:
                if cached_manager != "NOT_FOUND":  # Handle negative caching
                    result[cc] = cached_manager
            else:
                uncached_cost_centers.append(cc)
        
        # Batch query for uncached cost centers
        if uncached_cost_centers:
            try:
                from sqlalchemy import and_, or_
                from pgappforge.security.sqla.models import User, Role
                
                # Single batch query for all cost center managers
                cc_managers = db.session.query(
                    User.id,
                    # Support multiple cost center field patterns
                    User.cost_center.label('cc_code') if hasattr(User, 'cost_center') else
                    User.cost_center_id.label('cc_code') if hasattr(User, 'cost_center_id') else
                    getattr(User, 'cost_center_code', User.id).label('cc_code')
                ).join(User.roles).filter(
                    and_(
                        Role.name.in_(['CostCenterManager', 'Cost Center Manager', 'Finance Manager']),
                        User.active == True
                    )
                ).filter(
                    # Support multiple cost center field patterns
                    or_(
                        User.cost_center.in_(uncached_cost_centers) if hasattr(User, 'cost_center') else False,
                        User.cost_center_id.in_(uncached_cost_centers) if hasattr(User, 'cost_center_id') else False,
                        getattr(User, 'cost_center_code', User.id).in_(uncached_cost_centers) if hasattr(User, 'cost_center_code') else False
                    )
                ).all()
                
                # Process results and cache them individually
                found_cc_ids = set()
                for user_id, cc_code in cc_managers:
                    if cc_code in uncached_cost_centers:
                        result[cc_code] = user_id
                        cache_manager.set(CacheKeyPrefix.COST_CENTER_MGR, cc_code, value=user_id, ttl=300)
                        found_cc_ids.add(cc_code)
                
                # Cache negative results to avoid repeated queries
                for cc in uncached_cost_centers:
                    if cc not in found_cc_ids:
                        cache_manager.set(CacheKeyPrefix.COST_CENTER_MGR, cc, value="NOT_FOUND", ttl=300)
                        
            except Exception as e:
                log.error(f"Error in batch cost center manager query: {e}")
        
        return result

    def _log_security_violation(self, violation_type: str, expression: str,
                              context: ExpressionContext, details: Dict[str, Any]) -> None:
        """
        Log security violation with comprehensive context.

        Args:
            violation_type: Type of violation
            expression: Expression that caused violation
            context: Evaluation context
            details: Additional violation details
        """
        self.audit_logger.log_security_event('expression_security_violation', {
            'violation_type': violation_type,
            'expression': expression,
            'context_instance_id': context.instance_id,
            'context_initiator_id': context.initiator_id,
            'context_tenant_id': context.tenant_id,
            'details': details
        })

    def validate_all_expressions(self) -> Dict[str, Any]:
        """
        Validate all whitelisted expressions for security.

        Returns:
            dict: Validation results
        """
        results = {
            'total_expressions': len(self.ALLOWED_EXPRESSIONS),
            'valid_expressions': [],
            'security_warnings': []
        }

        for expression, config in self.ALLOWED_EXPRESSIONS.items():
            try:
                self._validate_expression_format(expression)
                results['valid_expressions'].append(expression)
            except SecurityViolation as e:
                results['security_warnings'].append({
                    'expression': expression,
                    'warning': str(e)
                })

        return results


# Factory function for backward compatibility
def create_secure_evaluator() -> SecureExpressionEvaluator:
    """Create secure expression evaluator instance."""
    return SecureExpressionEvaluator()


# Global evaluator instance (singleton pattern)
_global_evaluator = None


def get_secure_evaluator() -> SecureExpressionEvaluator:
    """Get global secure expression evaluator instance."""
    global _global_evaluator
    if _global_evaluator is None:
        _global_evaluator = create_secure_evaluator()
    return _global_evaluator