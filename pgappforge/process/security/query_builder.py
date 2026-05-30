"""
Centralized Security Query Builder for Approval Workflow System.

Provides unified secure database query patterns and input validation
to prevent SQL injection and ensure consistent security practices.
"""

import logging
import re
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from enum import Enum

from sqlalchemy import bindparam, func, and_, or_
from sqlalchemy.orm import Query
from sqlalchemy.exc import SQLAlchemyError

from pgappforge import db

log = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """Security validation levels for different operations."""
    BASIC = "basic"
    STANDARD = "standard"
    HIGH = "high"
    CRITICAL = "critical"


class SecureQueryBuilder:
    """
    Centralized secure query builder for approval workflow system.

    Provides parameterized query patterns and input validation to prevent
    SQL injection attacks and ensure consistent security practices.
    """

    # Whitelist of allowed operators for dynamic queries
    ALLOWED_OPERATORS = ['==', '!=', '>', '<', '>=', '<=', 'in', 'not_in', 'like', 'ilike']

    # Whitelist of allowed field expressions for approval context
    ALLOWED_APPROVAL_FIELDS = [
        'tenant_id', 'user_id', 'approver_id', 'status', 'priority',
        'chain_id', 'request_id', 'created_at', 'updated_at', 'expires_at',
        'requested_at', 'responded_at', 'is_active', 'required'
    ]

    # Maximum allowed limit for queries to prevent resource exhaustion
    MAX_QUERY_LIMIT = 1000

    def __init__(self, security_level: SecurityLevel = SecurityLevel.STANDARD):
        self.security_level = security_level
        self._validation_enabled = True

    def create_secure_filter(self, model_class, filters: Dict[str, Any]) -> Query:
        """
        Create a secure parameterized query filter.

        Args:
            model_class: SQLAlchemy model class
            filters: Dictionary of field->value filters

        Returns:
            Query object with parameterized filters

        Raises:
            ValueError: If validation fails or unsafe patterns detected
        """
        if not filters:
            return db.session.query(model_class)

        # Validate all filter fields are allowed
        self._validate_filter_fields(filters)

        # Start with base query
        query = db.session.query(model_class)

        # Build parameterized filters
        filter_conditions = []
        params = {}

        for field_name, value in filters.items():
            # Validate field name
            if not self._is_valid_field_name(field_name):
                raise ValueError(f"Invalid field name: {field_name}")

            # Get model attribute
            if not hasattr(model_class, field_name):
                raise ValueError(f"Model {model_class.__name__} has no field: {field_name}")

            attr = getattr(model_class, field_name)
            param_name = f"param_{field_name}"

            # Handle different value types
            if isinstance(value, (list, tuple)):
                # Handle IN queries
                filter_conditions.append(attr.in_(bindparam(param_name)))
                params[param_name] = list(value)
            elif value is None:
                # Handle NULL queries
                filter_conditions.append(attr.is_(None))
            else:
                # Handle equality queries
                filter_conditions.append(attr == bindparam(param_name))
                params[param_name] = value

        # Apply all filters
        if filter_conditions:
            query = query.filter(and_(*filter_conditions)).params(**params)

        return query

    def create_secure_comparison(self, model_class, field: str, operator: str, value: Any) -> Query:
        """
        Create secure comparison query with operator validation.

        Args:
            model_class: SQLAlchemy model class
            field: Field name to compare
            operator: Comparison operator (must be whitelisted)
            value: Value to compare against

        Returns:
            Query object with parameterized comparison
        """
        # Validate operator
        if operator not in self.ALLOWED_OPERATORS:
            log.warning(f"Blocked unsafe operator: {operator}")
            raise ValueError(f"Operator not allowed: {operator}")

        # Validate field name
        if not self._is_valid_field_name(field):
            raise ValueError(f"Invalid field name: {field}")

        # Get model attribute
        if not hasattr(model_class, field):
            raise ValueError(f"Model {model_class.__name__} has no field: {field}")

        attr = getattr(model_class, field)
        param_name = f"param_{field}"

        # Build query based on operator
        query = db.session.query(model_class)

        if operator == '==':
            condition = attr == bindparam(param_name)
        elif operator == '!=':
            condition = attr != bindparam(param_name)
        elif operator == '>':
            condition = attr > bindparam(param_name)
        elif operator == '<':
            condition = attr < bindparam(param_name)
        elif operator == '>=':
            condition = attr >= bindparam(param_name)
        elif operator == '<=':
            condition = attr <= bindparam(param_name)
        elif operator == 'in':
            condition = attr.in_(bindparam(param_name))
        elif operator == 'not_in':
            condition = ~attr.in_(bindparam(param_name))
        elif operator == 'like':
            condition = attr.like(bindparam(param_name))
        elif operator == 'ilike':
            condition = attr.ilike(bindparam(param_name))
        else:
            raise ValueError(f"Operator not implemented: {operator}")

        return query.filter(condition).params(**{param_name: value})

    def create_tenant_scoped_query(self, model_class, tenant_id: str, additional_filters: Dict[str, Any] = None) -> Query:
        """
        Create tenant-scoped secure query for multi-tenant environments.

        Args:
            model_class: SQLAlchemy model class
            tenant_id: Tenant ID to scope query to
            additional_filters: Additional filters to apply

        Returns:
            Query object scoped to tenant with additional filters
        """
        # Validate tenant ID
        self._validate_tenant_id(tenant_id)

        # Start with tenant filter
        filters = {'tenant_id': tenant_id}

        # Add additional filters if provided
        if additional_filters:
            filters.update(additional_filters)

        return self.create_secure_filter(model_class, filters)

    def validate_input_data(self, input_data: Dict[str, Any], allowed_fields: List[str]) -> Dict[str, Any]:
        """
        Validate and sanitize input data.

        Args:
            input_data: Input data to validate
            allowed_fields: List of allowed field names

        Returns:
            Sanitized input data

        Raises:
            ValueError: If validation fails
        """
        if not isinstance(input_data, dict):
            raise ValueError("Input data must be a dictionary")

        sanitized = {}

        for field, value in input_data.items():
            # Check if field is allowed
            if field not in allowed_fields:
                log.warning(f"Blocked unauthorized field: {field}")
                continue

            # Validate field name format
            if not self._is_valid_field_name(field):
                log.warning(f"Blocked invalid field name format: {field}")
                continue

            # Sanitize value based on type
            sanitized_value = self._sanitize_value(value)
            if sanitized_value is not None:
                sanitized[field] = sanitized_value

        return sanitized

    def apply_query_limits(self, query: Query, limit: Optional[int] = None, offset: Optional[int] = None) -> Query:
        """
        Apply secure limits and offset to query.

        Args:
            query: Query to apply limits to
            limit: Maximum number of results (capped at MAX_QUERY_LIMIT)
            offset: Number of results to skip

        Returns:
            Query with limits applied
        """
        if limit is not None:
            # Cap limit to prevent resource exhaustion
            safe_limit = min(limit, self.MAX_QUERY_LIMIT)
            if safe_limit != limit:
                log.warning(f"Query limit capped from {limit} to {safe_limit}")
            query = query.limit(safe_limit)

        if offset is not None:
            # Validate offset is non-negative
            if offset < 0:
                raise ValueError("Offset must be non-negative")
            query = query.offset(offset)

        return query

    def _validate_filter_fields(self, filters: Dict[str, Any]) -> None:
        """Validate that all filter fields are allowed."""
        for field_name in filters.keys():
            if field_name not in self.ALLOWED_APPROVAL_FIELDS:
                if self.security_level in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]:
                    raise ValueError(f"Field not in whitelist: {field_name}")
                else:
                    log.warning(f"Field not in whitelist but allowed: {field_name}")

    def _is_valid_field_name(self, field_name: str) -> bool:
        """Validate field name format to prevent injection attacks."""
        if not isinstance(field_name, str):
            return False

        # Must be alphanumeric with underscores, no SQL keywords
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', field_name):
            return False

        # Block SQL keywords
        sql_keywords = {
            'select', 'insert', 'update', 'delete', 'drop', 'create', 'alter',
            'union', 'where', 'having', 'group', 'order', 'limit', 'offset',
            'from', 'join', 'inner', 'outer', 'left', 'right', 'cross',
            'exec', 'execute', 'declare', 'begin', 'end', 'if', 'else'
        }

        if field_name.lower() in sql_keywords:
            return False

        return True

    def _validate_tenant_id(self, tenant_id: str) -> None:
        """Validate tenant ID format."""
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Invalid tenant ID")

        # Tenant ID should be UUID format or alphanumeric
        if not re.match(r'^[a-zA-Z0-9_-]+$', tenant_id):
            raise ValueError(f"Invalid tenant ID format: {tenant_id}")

    def _sanitize_value(self, value: Any) -> Any:
        """Sanitize input values to prevent injection attacks."""
        if value is None:
            return None

        if isinstance(value, str):
            # Remove potential SQL injection patterns
            sanitized = value.strip()

            # Block common SQL injection patterns
            dangerous_patterns = [
                r'(\s|^)(union|select|insert|update|delete|drop|create|alter|exec|execute)(\s|$)',
                r'(\s|^)(or|and)(\s+\d+\s*=\s*\d+|\s+true|\s+false)(\s|$)',
                r'(--|/\*|\*/|;)',
                r'(\s|^)(script|javascript|vbscript)(\s|:)'
            ]

            for pattern in dangerous_patterns:
                if re.search(pattern, sanitized, re.IGNORECASE):
                    log.warning(f"Blocked potentially dangerous value: {value[:100]}")
                    return None

            return sanitized

        elif isinstance(value, (int, float, bool, datetime)):
            return value

        elif isinstance(value, (list, tuple)):
            # Recursively sanitize list items
            sanitized_list = []
            for item in value:
                sanitized_item = self._sanitize_value(item)
                if sanitized_item is not None:
                    sanitized_list.append(sanitized_item)
            return sanitized_list

        elif isinstance(value, dict):
            # Recursively sanitize dictionary values
            sanitized_dict = {}
            for k, v in value.items():
                if self._is_valid_field_name(k):
                    sanitized_v = self._sanitize_value(v)
                    if sanitized_v is not None:
                        sanitized_dict[k] = sanitized_v
            return sanitized_dict

        else:
            # For other types, log and reject
            log.warning(f"Unsupported value type: {type(value)}")
            return None


class ApprovalSecurityValidator:
    """
    Specialized security validator for approval workflow operations.

    Extends SecureQueryBuilder with approval-specific validation logic.
    """

    def __init__(self):
        self.query_builder = SecureQueryBuilder(SecurityLevel.HIGH)

    def validate_approval_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate approval request data.

        Args:
            request_data: Approval request data to validate

        Returns:
            Validated and sanitized request data
        """
        allowed_fields = [
            'approver_id', 'chain_id', 'status', 'priority', 'approval_data',
            'response_data', 'notes', 'required', 'delegate_allowed',
            'expires_at'
        ]

        return self.query_builder.validate_input_data(request_data, allowed_fields)

    def validate_chain_configuration(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate approval chain configuration data.

        Args:
            config_data: Chain configuration to validate

        Returns:
            Validated and sanitized configuration
        """
        allowed_fields = [
            'chain_type', 'priority', 'approvers', 'configuration',
            'due_date', 'escalation_rules', 'parallel_approval',
            'required_approvals'
        ]

        return self.query_builder.validate_input_data(config_data, allowed_fields)

    def create_user_scoped_approval_query(self, model_class, tenant_id: str, user_id: str, additional_filters: Dict[str, Any] = None):
        """
        Create user and tenant scoped approval query.

        Args:
            model_class: SQLAlchemy model class
            tenant_id: Tenant ID to scope to
            user_id: User ID to scope to
            additional_filters: Additional filters

        Returns:
            Secure query scoped to tenant and user
        """
        filters = {'tenant_id': tenant_id, 'approver_id': user_id}

        if additional_filters:
            validated_filters = self.query_builder.validate_input_data(
                additional_filters,
                self.query_builder.ALLOWED_APPROVAL_FIELDS
            )
            filters.update(validated_filters)

        return self.query_builder.create_secure_filter(model_class, filters)


# Singleton instance for easy access
approval_security_validator = ApprovalSecurityValidator()