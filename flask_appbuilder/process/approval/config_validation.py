"""
Configuration Validation System

Provides JSON Schema validation for approval workflow configurations,
connection pool settings, and security parameters with comprehensive
error reporting and examples.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Union, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum

try:
    import jsonschema
    from jsonschema import validate, ValidationError, Draft7Validator
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    ValidationError = Exception

log = logging.getLogger(__name__)


class ConfigurationType(Enum):
    """Types of configurations that can be validated."""
    WORKFLOW = "workflow"
    CONNECTION_POOL = "connection_pool"
    SECURITY = "security"
    APPROVAL_CHAIN = "approval_chain"
    NOTIFICATION = "notification"
    ESCALATION = "escalation"


@dataclass
class ValidationResult:
    """Result of configuration validation."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    config_type: Optional[str] = None
    validated_config: Optional[Dict] = None
    validation_timestamp: datetime = field(default_factory=datetime.utcnow)


class ConfigurationValidator:
    """
    Comprehensive configuration validator using JSON Schema.
    
    Provides validation for all approval system configurations with
    detailed error reporting and automatic schema discovery.
    """
    
    def __init__(self):
        """Initialize validator with all schema definitions."""
        self.schemas = self._load_schemas()
        self._validator_cache = {}
    
    def _load_schemas(self) -> Dict[str, Dict]:
        """Load all JSON schema definitions."""
        return {
            ConfigurationType.WORKFLOW.value: self._get_workflow_schema(),
            ConfigurationType.CONNECTION_POOL.value: self._get_connection_pool_schema(),
            ConfigurationType.SECURITY.value: self._get_security_schema(),
            ConfigurationType.APPROVAL_CHAIN.value: self._get_approval_chain_schema(),
            ConfigurationType.NOTIFICATION.value: self._get_notification_schema(),
            ConfigurationType.ESCALATION.value: self._get_escalation_schema()
        }
    
    def _get_workflow_schema(self) -> Dict:
        """Get JSON schema for workflow configuration."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "Approval Workflow Configuration",
            "description": "Configuration schema for approval workflows",
            "required": ["name", "steps", "initial_state", "approved_state"],
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Workflow name identifier"
                },
                "description": {
                    "type": "string",
                    "maxLength": 500,
                    "description": "Optional workflow description"
                },
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "description": "Workflow steps definition",
                    "items": {
                        "type": "object",
                        "required": ["name", "required_approvals"],
                        "properties": {
                            "name": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 100
                            },
                            "description": {
                                "type": "string",
                                "maxLength": 200
                            },
                            "required_approvals": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 50
                            },
                            "approvers": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["user", "role", "dynamic"]
                                        },
                                        "user_id": {"type": "integer"},
                                        "role": {"type": "string"},
                                        "expression": {"type": "string"},
                                        "required": {"type": "boolean"},
                                        "order": {"type": "integer", "minimum": 0}
                                    }
                                }
                            },
                            "timeout_hours": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": 720
                            },
                            "escalation": {
                                "type": "object",
                                "properties": {
                                    "enabled": {"type": "boolean"},
                                    "timeout_action": {
                                        "type": "string",
                                        "enum": ["escalate", "reject", "approve"]
                                    },
                                    "escalation_target": {"type": "string"}
                                }
                            }
                        }
                    }
                },
                "initial_state": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Initial workflow state"
                },
                "approved_state": {
                    "type": "string", 
                    "minLength": 1,
                    "description": "Final approved state"
                },
                "rejected_state": {
                    "type": "string",
                    "description": "Final rejected state"
                },
                "workflow_type": {
                    "type": "string",
                    "enum": ["sequential", "parallel", "conditional"],
                    "default": "sequential"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "critical"],
                    "default": "normal"
                },
                "metadata": {
                    "type": "object",
                    "description": "Additional workflow metadata"
                }
            },
            "additionalProperties": false
        }
    
    def _get_connection_pool_schema(self) -> Dict:
        """Get JSON schema for connection pool configuration."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "Database Connection Pool Configuration",
            "description": "Configuration schema for database connection pooling",
            "properties": {
                "pool_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "Base connection pool size"
                },
                "max_overflow": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 200,
                    "default": 30,
                    "description": "Maximum overflow connections"
                },
                "pool_timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 300,
                    "default": 30,
                    "description": "Connection acquisition timeout (seconds)"
                },
                "pool_recycle": {
                    "type": "integer",
                    "minimum": 300,
                    "maximum": 86400,
                    "default": 3600,
                    "description": "Connection recycle time (seconds)"
                },
                "pool_pre_ping": {
                    "type": "boolean",
                    "default": True,
                    "description": "Enable connection health checks"
                },
                "echo_pool": {
                    "type": "boolean",
                    "default": False,
                    "description": "Enable connection pool logging"
                },
                "connect_timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 120,
                    "default": 10,
                    "description": "Database connection timeout (seconds)"
                },
                "health_check_interval": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 3600,
                    "default": 300,
                    "description": "Health check interval (seconds)"
                }
            },
            "additionalProperties": false
        }
    
    def _get_security_schema(self) -> Dict:
        """Get JSON schema for security configuration."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "Security Configuration",
            "description": "Configuration schema for security settings",
            "required": ["authentication_required", "csrf_protection"],
            "properties": {
                "authentication_required": {
                    "type": "boolean",
                    "description": "Require authentication for all operations"
                },
                "csrf_protection": {
                    "type": "boolean",
                    "description": "Enable CSRF protection"
                },
                "session_timeout": {
                    "type": "integer",
                    "minimum": 300,
                    "maximum": 86400,
                    "default": 3600,
                    "description": "Session timeout (seconds)"
                },
                "max_login_attempts": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Maximum login attempts before lockout"
                },
                "lockout_duration": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 3600,
                    "default": 300,
                    "description": "Account lockout duration (seconds)"
                },
                "password_policy": {
                    "type": "object",
                    "properties": {
                        "min_length": {
                            "type": "integer",
                            "minimum": 6,
                            "maximum": 50,
                            "default": 8
                        },
                        "require_uppercase": {"type": "boolean", "default": True},
                        "require_lowercase": {"type": "boolean", "default": True},
                        "require_numbers": {"type": "boolean", "default": True},
                        "require_symbols": {"type": "boolean", "default": False},
                        "max_age_days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 365,
                            "default": 90
                        }
                    }
                },
                "encryption": {
                    "type": "object",
                    "properties": {
                        "algorithm": {
                            "type": "string",
                            "enum": ["AES256", "ChaCha20"],
                            "default": "AES256"
                        },
                        "key_rotation_days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 365,
                            "default": 90
                        }
                    }
                },
                "audit_logging": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean", "default": True},
                        "log_level": {
                            "type": "string",
                            "enum": ["DEBUG", "INFO", "WARNING", "ERROR"],
                            "default": "INFO"
                        },
                        "retention_days": {
                            "type": "integer",
                            "minimum": 30,
                            "maximum": 2555,
                            "default": 365
                        }
                    }
                }
            },
            "additionalProperties": false
        }
    
    def _get_approval_chain_schema(self) -> Dict:
        """Get JSON schema for approval chain configuration."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "Approval Chain Configuration",
            "description": "Configuration schema for approval chains",
            "required": ["type", "approvers"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["sequential", "parallel", "conditional", "unanimous", "majority", "first_response"],
                    "description": "Approval chain type"
                },
                "approvers": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "description": "List of approvers in the chain",
                    "items": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["user", "role", "dynamic"]
                            },
                            "user_id": {"type": "integer"},
                            "role": {"type": "string"},
                            "expression": {"type": "string"},
                            "order": {"type": "integer", "minimum": 0},
                            "required": {"type": "boolean", "default": True},
                            "delegate_allowed": {"type": "boolean", "default": False},
                            "selection_mode": {
                                "type": "string",
                                "enum": ["first", "all", "random"]
                            }
                        }
                    }
                },
                "approval_threshold": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Required number of approvals for parallel chains"
                },
                "timeout_action": {
                    "type": "string",
                    "enum": ["escalate", "reject", "approve"],
                    "default": "escalate"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "critical"],
                    "default": "normal"
                },
                "due_date_hours": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 8760
                },
                "metadata": {
                    "type": "object",
                    "description": "Additional chain metadata"
                }
            },
            "additionalProperties": false
        }
    
    def _get_notification_schema(self) -> Dict:
        """Get JSON schema for notification configuration."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "Notification Configuration",
            "description": "Configuration schema for notifications",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Enable notifications"
                },
                "channels": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["email", "sms", "webhook", "slack", "teams"]
                            },
                            "enabled": {"type": "boolean", "default": True},
                            "config": {
                                "type": "object",
                                "description": "Channel-specific configuration"
                            }
                        }
                    }
                },
                "templates": {
                    "type": "object",
                    "properties": {
                        "approval_request": {"type": "string"},
                        "approval_approved": {"type": "string"},
                        "approval_rejected": {"type": "string"},
                        "approval_escalated": {"type": "string"},
                        "approval_timeout": {"type": "string"}
                    }
                },
                "frequency_limits": {
                    "type": "object",
                    "properties": {
                        "max_per_hour": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100
                        },
                        "max_per_day": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10000,
                            "default": 1000
                        }
                    }
                }
            },
            "additionalProperties": false
        }
    
    def _get_escalation_schema(self) -> Dict:
        """Get JSON schema for escalation configuration."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "Escalation Configuration",
            "description": "Configuration schema for approval escalations",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Enable escalation"
                },
                "triggers": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["timeout", "rejection", "no_response", "manual"]
                    },
                    "default": ["timeout"]
                },
                "timeout_hours": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 168,
                    "default": 24,
                    "description": "Hours before escalation"
                },
                "max_escalation_levels": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 3
                },
                "escalation_targets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["level", "target_type"],
                        "properties": {
                            "level": {"type": "integer", "minimum": 1},
                            "target_type": {
                                "type": "string",
                                "enum": ["user", "role", "manager", "admin"]
                            },
                            "target_id": {"type": "integer"},
                            "target_role": {"type": "string"}
                        }
                    }
                },
                "escalation_delay_minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1440,
                    "default": 60
                }
            },
            "additionalProperties": false
        }
    
    def validate_configuration(self, config: Dict[str, Any], 
                             config_type: Union[str, ConfigurationType]) -> ValidationResult:
        """
        Validate configuration against appropriate schema.
        
        Args:
            config: Configuration dictionary to validate
            config_type: Type of configuration (from ConfigurationType enum)
            
        Returns:
            ValidationResult with validation details
        """
        if not JSONSCHEMA_AVAILABLE:
            return ValidationResult(
                is_valid=False,
                errors=["jsonschema library not available for validation"],
                config_type=str(config_type)
            )
        
        # Convert enum to string if needed
        if isinstance(config_type, ConfigurationType):
            config_type = config_type.value
        
        # Check if schema exists
        if config_type not in self.schemas:
            return ValidationResult(
                is_valid=False,
                errors=[f"Unknown configuration type: {config_type}"],
                config_type=config_type
            )
        
        schema = self.schemas[config_type]
        result = ValidationResult(config_type=config_type)
        
        try:
            # Get or create validator
            if config_type not in self._validator_cache:
                self._validator_cache[config_type] = Draft7Validator(schema)
            
            validator = self._validator_cache[config_type]
            
            # Validate configuration
            errors = list(validator.iter_errors(config))
            
            if not errors:
                result.is_valid = True
                result.validated_config = config.copy()
                
                # Add warnings for optional best practices
                warnings = self._generate_warnings(config, config_type)
                result.warnings = warnings
                
            else:
                result.is_valid = False
                result.errors = [
                    f"Path '{'.'.join(str(p) for p in error.absolute_path)}': {error.message}"
                    for error in errors
                ]
                
        except Exception as e:
            result.is_valid = False
            result.errors = [f"Validation error: {str(e)}"]
            log.error(f"Configuration validation failed: {e}")
        
        return result
    
    def _generate_warnings(self, config: Dict[str, Any], config_type: str) -> List[str]:
        """Generate warnings for configuration best practices."""
        warnings = []
        
        if config_type == ConfigurationType.WORKFLOW.value:
            # Check for workflow best practices
            steps = config.get('steps', [])
            
            if len(steps) > 10:
                warnings.append("Consider reducing workflow complexity (>10 steps)")
            
            for i, step in enumerate(steps):
                if step.get('required_approvals', 1) > 5:
                    warnings.append(f"Step {i}: High approval requirement ({step['required_approvals']}) may cause delays")
                
                if not step.get('timeout_hours'):
                    warnings.append(f"Step {i}: Consider setting timeout for better workflow control")
        
        elif config_type == ConfigurationType.CONNECTION_POOL.value:
            pool_size = config.get('pool_size', 20)
            max_overflow = config.get('max_overflow', 30)
            
            if pool_size < 5:
                warnings.append("Small pool size may cause connection contention")
            
            if max_overflow > pool_size * 3:
                warnings.append("High overflow ratio may indicate undersized base pool")
            
            if not config.get('pool_pre_ping', True):
                warnings.append("Consider enabling pool_pre_ping for better reliability")
        
        elif config_type == ConfigurationType.SECURITY.value:
            if not config.get('audit_logging', {}).get('enabled', True):
                warnings.append("Audit logging disabled - security compliance risk")
            
            password_policy = config.get('password_policy', {})
            if password_policy.get('min_length', 8) < 8:
                warnings.append("Password minimum length below recommended 8 characters")
        
        return warnings
    
    def get_schema(self, config_type: Union[str, ConfigurationType]) -> Dict[str, Any]:
        """Get JSON schema for specified configuration type."""
        if isinstance(config_type, ConfigurationType):
            config_type = config_type.value
        
        return self.schemas.get(config_type, {})
    
    def get_example_configuration(self, config_type: Union[str, ConfigurationType]) -> Dict[str, Any]:
        """Get example configuration for specified type."""
        if isinstance(config_type, ConfigurationType):
            config_type = config_type.value
        
        examples = {
            ConfigurationType.WORKFLOW.value: {
                "name": "Financial Approval Workflow",
                "description": "Multi-step approval for financial transactions",
                "steps": [
                    {
                        "name": "Initial Review",
                        "description": "First level financial review",
                        "required_approvals": 1,
                        "approvers": [
                            {
                                "type": "role",
                                "role": "Finance_Reviewer",
                                "required": True,
                                "order": 0
                            }
                        ],
                        "timeout_hours": 24,
                        "escalation": {
                            "enabled": True,
                            "timeout_action": "escalate"
                        }
                    },
                    {
                        "name": "Manager Approval",
                        "description": "Department manager approval",
                        "required_approvals": 1,
                        "approvers": [
                            {
                                "type": "dynamic",
                                "expression": "input_data.manager_id",
                                "required": True,
                                "order": 0
                            }
                        ],
                        "timeout_hours": 48
                    }
                ],
                "initial_state": "pending_review",
                "approved_state": "approved",
                "rejected_state": "rejected",
                "workflow_type": "sequential",
                "priority": "normal"
            },
            
            ConfigurationType.CONNECTION_POOL.value: {
                "pool_size": 25,
                "max_overflow": 50,
                "pool_timeout": 30,
                "pool_recycle": 3600,
                "pool_pre_ping": True,
                "echo_pool": False,
                "connect_timeout": 15,
                "health_check_interval": 300
            },
            
            ConfigurationType.SECURITY.value: {
                "authentication_required": True,
                "csrf_protection": True,
                "session_timeout": 3600,
                "max_login_attempts": 5,
                "lockout_duration": 300,
                "password_policy": {
                    "min_length": 8,
                    "require_uppercase": True,
                    "require_lowercase": True,
                    "require_numbers": True,
                    "require_symbols": False,
                    "max_age_days": 90
                },
                "encryption": {
                    "algorithm": "AES256",
                    "key_rotation_days": 90
                },
                "audit_logging": {
                    "enabled": True,
                    "log_level": "INFO",
                    "retention_days": 365
                }
            },
            
            ConfigurationType.APPROVAL_CHAIN.value: {
                "type": "sequential",
                "approvers": [
                    {
                        "type": "role",
                        "role": "Finance_Approver",
                        "order": 0,
                        "required": True,
                        "delegate_allowed": False
                    },
                    {
                        "type": "user",
                        "user_id": 123,
                        "order": 1,
                        "required": True,
                        "delegate_allowed": True
                    }
                ],
                "timeout_action": "escalate",
                "priority": "normal",
                "due_date_hours": 72
            },
            
            ConfigurationType.NOTIFICATION.value: {
                "enabled": True,
                "channels": [
                    {
                        "type": "email",
                        "enabled": True,
                        "config": {
                            "smtp_server": "smtp.company.com",
                            "port": 587,
                            "use_tls": True
                        }
                    },
                    {
                        "type": "slack",
                        "enabled": True,
                        "config": {
                            "webhook_url": "https://hooks.slack.com/...",
                            "channel": "#approvals"
                        }
                    }
                ],
                "templates": {
                    "approval_request": "New approval request: {{title}}",
                    "approval_approved": "Approval granted for: {{title}}",
                    "approval_rejected": "Approval rejected for: {{title}}"
                },
                "frequency_limits": {
                    "max_per_hour": 100,
                    "max_per_day": 1000
                }
            },
            
            ConfigurationType.ESCALATION.value: {
                "enabled": True,
                "triggers": ["timeout", "no_response"],
                "timeout_hours": 24,
                "max_escalation_levels": 3,
                "escalation_targets": [
                    {
                        "level": 1,
                        "target_type": "manager",
                        "target_id": 456
                    },
                    {
                        "level": 2,
                        "target_type": "role",
                        "target_role": "Senior_Manager"
                    },
                    {
                        "level": 3,
                        "target_type": "admin"
                    }
                ],
                "escalation_delay_minutes": 60
            }
        }
        
        return examples.get(config_type, {})
    
    def validate_all_examples(self) -> Dict[str, ValidationResult]:
        """Validate all example configurations to ensure they're correct."""
        results = {}
        
        for config_type in ConfigurationType:
            example = self.get_example_configuration(config_type)
            if example:
                result = self.validate_configuration(example, config_type)
                results[config_type.value] = result
        
        return results


def create_configuration_template(config_type: Union[str, ConfigurationType]) -> str:
    """
    Create a configuration template with comments and examples.
    
    Args:
        config_type: Type of configuration to generate template for
        
    Returns:
        JSON string with commented template
    """
    validator = ConfigurationValidator()
    example = validator.get_example_configuration(config_type)
    schema = validator.get_schema(config_type)
    
    if isinstance(config_type, ConfigurationType):
        config_type = config_type.value
    
    template = {
        "_schema_info": {
            "title": schema.get("title", f"{config_type.title()} Configuration"),
            "description": schema.get("description", ""),
            "validation_required": True,
            "last_updated": datetime.now(tz=timezone.utc).isoformat()
        },
        "_example": example,
        "_validation_notes": [
            "This configuration will be validated against JSON schema",
            "Required fields must be provided",
            "See example section for reference values",
            "Consult documentation for advanced options"
        ]
    }
    
    return json.dumps(template, indent=2, default=str)


# Global validator instance
_global_validator: Optional[ConfigurationValidator] = None


def get_validator() -> ConfigurationValidator:
    """Get or create global configuration validator."""
    global _global_validator
    if _global_validator is None:
        _global_validator = ConfigurationValidator()
    return _global_validator


def validate_config(config: Dict[str, Any], 
                   config_type: Union[str, ConfigurationType]) -> ValidationResult:
    """Convenience function for configuration validation."""
    validator = get_validator()
    return validator.validate_configuration(config, config_type)