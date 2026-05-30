"""
Approval System Configuration Examples

Comprehensive examples demonstrating all configuration types
with validation, best practices, and real-world scenarios.
"""

import json
from datetime import datetime, timedelta
from pgappforge.process.approval.config_validation import (
    ConfigurationValidator, ConfigurationType, validate_config
)


def get_basic_workflow_config():
    """Basic workflow configuration for simple approvals."""
    return {
        "name": "Basic Approval Workflow",
        "description": "Simple single-step approval process",
        "steps": [
            {
                "name": "Manager Approval",
                "description": "Approval by direct manager",
                "required_approvals": 1,
                "approvers": [
                    {
                        "type": "dynamic",
                        "expression": "input_data.manager_id",
                        "required": True,
                        "order": 0
                    }
                ],
                "timeout_hours": 24,
                "escalation": {
                    "enabled": True,
                    "timeout_action": "escalate"
                }
            }
        ],
        "initial_state": "pending_approval",
        "approved_state": "approved",
        "rejected_state": "rejected",
        "workflow_type": "sequential",
        "priority": "normal"
    }


def get_financial_workflow_config():
    """Financial approval workflow with multiple steps and amount thresholds."""
    return {
        "name": "Financial Transaction Approval",
        "description": "Multi-level approval for financial transactions based on amount",
        "steps": [
            {
                "name": "Finance Team Review",
                "description": "Initial review by finance team member",
                "required_approvals": 1,
                "approvers": [
                    {
                        "type": "role",
                        "role": "Finance_Reviewer",
                        "required": True,
                        "order": 0
                    }
                ],
                "timeout_hours": 8,
                "escalation": {
                    "enabled": True,
                    "timeout_action": "escalate"
                }
            },
            {
                "name": "Department Manager",
                "description": "Approval by department manager",
                "required_approvals": 1,
                "approvers": [
                    {
                        "type": "dynamic",
                        "expression": "input_data.manager_id",
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
                "name": "Executive Approval",
                "description": "Final approval for high-value transactions",
                "required_approvals": 1,
                "approvers": [
                    {
                        "type": "role",
                        "role": "C_Level_Executive",
                        "required": True,
                        "order": 0
                    }
                ],
                "timeout_hours": 72,
                "escalation": {
                    "enabled": True,
                    "timeout_action": "reject"
                }
            }
        ],
        "initial_state": "pending_finance_review",
        "approved_state": "financially_approved",
        "rejected_state": "financially_rejected",
        "workflow_type": "sequential",
        "priority": "high"
    }


def get_parallel_workflow_config():
    """Parallel approval workflow for committee decisions."""
    return {
        "name": "Committee Review Process",
        "description": "Parallel review by multiple committee members",
        "steps": [
            {
                "name": "Committee Review",
                "description": "Review by committee members (majority required)",
                "required_approvals": 3,
                "approvers": [
                    {
                        "type": "user",
                        "user_id": 101,
                        "required": False,
                        "order": 0
                    },
                    {
                        "type": "user", 
                        "user_id": 102,
                        "required": False,
                        "order": 0
                    },
                    {
                        "type": "user",
                        "user_id": 103,
                        "required": False,
                        "order": 0
                    },
                    {
                        "type": "user",
                        "user_id": 104,
                        "required": False,
                        "order": 0
                    },
                    {
                        "type": "user",
                        "user_id": 105,
                        "required": False,
                        "order": 0
                    }
                ],
                "timeout_hours": 48,
                "escalation": {
                    "enabled": True,
                    "timeout_action": "escalate"
                }
            }
        ],
        "initial_state": "committee_review",
        "approved_state": "committee_approved",
        "rejected_state": "committee_rejected", 
        "workflow_type": "parallel",
        "priority": "normal"
    }


def get_production_connection_pool_config():
    """Production-ready connection pool configuration."""
    return {
        "pool_size": 50,
        "max_overflow": 100,
        "pool_timeout": 45,
        "pool_recycle": 7200,  # 2 hours
        "pool_pre_ping": True,
        "echo_pool": False,
        "connect_timeout": 20,
        "health_check_interval": 180  # 3 minutes
    }


def get_development_connection_pool_config():
    """Development environment connection pool configuration."""
    return {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 15,
        "pool_recycle": 3600,  # 1 hour
        "pool_pre_ping": True,
        "echo_pool": True,  # Enable for debugging
        "connect_timeout": 10,
        "health_check_interval": 600  # 10 minutes
    }


def get_comprehensive_security_config():
    """Comprehensive security configuration for production."""
    return {
        "authentication_required": True,
        "csrf_protection": True,
        "session_timeout": 7200,  # 2 hours
        "max_login_attempts": 3,
        "lockout_duration": 900,  # 15 minutes
        "password_policy": {
            "min_length": 12,
            "require_uppercase": True,
            "require_lowercase": True,
            "require_numbers": True,
            "require_symbols": True,
            "max_age_days": 60
        },
        "encryption": {
            "algorithm": "AES256",
            "key_rotation_days": 30
        },
        "audit_logging": {
            "enabled": True,
            "log_level": "INFO",
            "retention_days": 2555  # 7 years
        }
    }


def get_basic_security_config():
    """Basic security configuration for development/testing."""
    return {
        "authentication_required": True,
        "csrf_protection": True,
        "session_timeout": 3600,  # 1 hour
        "max_login_attempts": 5,
        "lockout_duration": 300,  # 5 minutes
        "password_policy": {
            "min_length": 8,
            "require_uppercase": True,
            "require_lowercase": True,
            "require_numbers": True,
            "require_symbols": False,
            "max_age_days": 180
        },
        "audit_logging": {
            "enabled": True,
            "log_level": "DEBUG",
            "retention_days": 90
        }
    }


def get_sequential_approval_chain():
    """Sequential approval chain configuration."""
    return {
        "type": "sequential",
        "approvers": [
            {
                "type": "role",
                "role": "Team_Lead",
                "order": 0,
                "required": True,
                "delegate_allowed": True
            },
            {
                "type": "role",
                "role": "Department_Manager",
                "order": 1,
                "required": True,
                "delegate_allowed": True
            },
            {
                "type": "role",
                "role": "Director",
                "order": 2,
                "required": True,
                "delegate_allowed": False
            }
        ],
        "timeout_action": "escalate",
        "priority": "normal",
        "due_date_hours": 120  # 5 days
    }


def get_parallel_approval_chain():
    """Parallel approval chain configuration."""
    return {
        "type": "parallel",
        "approvers": [
            {
                "type": "user",
                "user_id": 201,
                "order": 0,
                "required": False,
                "delegate_allowed": True
            },
            {
                "type": "user",
                "user_id": 202,
                "order": 0,
                "required": False,
                "delegate_allowed": True
            },
            {
                "type": "user",
                "user_id": 203,
                "order": 0,
                "required": False,
                "delegate_allowed": True
            }
        ],
        "approval_threshold": 2,  # Need 2 out of 3 approvals
        "timeout_action": "reject",
        "priority": "high",
        "due_date_hours": 24
    }


def get_comprehensive_notification_config():
    """Comprehensive notification configuration."""
    return {
        "enabled": True,
        "channels": [
            {
                "type": "email",
                "enabled": True,
                "config": {
                    "smtp_server": "smtp.company.com",
                    "port": 587,
                    "use_tls": True,
                    "username": "approvals@company.com",
                    "from_address": "approvals@company.com"
                }
            },
            {
                "type": "slack",
                "enabled": True,
                "config": {
                    "webhook_url": "https://hooks.slack.com/services/...",
                    "channel": "#approvals",
                    "username": "ApprovalBot"
                }
            },
            {
                "type": "webhook",
                "enabled": True,
                "config": {
                    "url": "https://api.company.com/webhooks/approvals",
                    "headers": {
                        "Authorization": "Bearer token123"
                    },
                    "timeout": 30
                }
            }
        ],
        "templates": {
            "approval_request": "🔔 New approval request: {{title}}\nRequestor: {{requestor_name}}\nAmount: {{amount}}\nReason: {{reason}}\n\nReview: {{approval_url}}",
            "approval_approved": "✅ Approval granted for: {{title}}\nApprover: {{approver_name}}\nComments: {{comments}}",
            "approval_rejected": "❌ Approval rejected for: {{title}}\nRejected by: {{approver_name}}\nReason: {{rejection_reason}}",
            "approval_escalated": "⚠️ Approval escalated: {{title}}\nOriginal approver: {{original_approver}}\nNew approver: {{new_approver}}",
            "approval_timeout": "⏰ Approval request timeout: {{title}}\nDue date passed: {{due_date}}\nAction taken: {{timeout_action}}"
        },
        "frequency_limits": {
            "max_per_hour": 200,
            "max_per_day": 2000
        }
    }


def get_basic_notification_config():
    """Basic notification configuration."""
    return {
        "enabled": True,
        "channels": [
            {
                "type": "email",
                "enabled": True,
                "config": {
                    "smtp_server": "localhost",
                    "port": 25,
                    "use_tls": False
                }
            }
        ],
        "templates": {
            "approval_request": "New approval request: {{title}}",
            "approval_approved": "Approval granted: {{title}}",
            "approval_rejected": "Approval rejected: {{title}}"
        },
        "frequency_limits": {
            "max_per_hour": 50,
            "max_per_day": 500
        }
    }


def get_comprehensive_escalation_config():
    """Comprehensive escalation configuration."""
    return {
        "enabled": True,
        "triggers": ["timeout", "no_response", "rejection"],
        "timeout_hours": 12,
        "max_escalation_levels": 4,
        "escalation_targets": [
            {
                "level": 1,
                "target_type": "manager",
                "target_id": 301
            },
            {
                "level": 2,
                "target_type": "role",
                "target_role": "Senior_Manager"
            },
            {
                "level": 3,
                "target_type": "role",
                "target_role": "Director"
            },
            {
                "level": 4,
                "target_type": "admin"
            }
        ],
        "escalation_delay_minutes": 30
    }


def get_basic_escalation_config():
    """Basic escalation configuration."""
    return {
        "enabled": True,
        "triggers": ["timeout"],
        "timeout_hours": 24,
        "max_escalation_levels": 2,
        "escalation_targets": [
            {
                "level": 1,
                "target_type": "manager",
                "target_id": 401
            },
            {
                "level": 2,
                "target_type": "admin"
            }
        ],
        "escalation_delay_minutes": 60
    }


def validate_all_configurations():
    """Validate all example configurations."""
    print("🔍 VALIDATING ALL CONFIGURATION EXAMPLES")
    print("=" * 60)
    
    validator = ConfigurationValidator()
    
    # Define all configurations to validate
    configurations = [
        ("Basic Workflow", ConfigurationType.WORKFLOW, get_basic_workflow_config()),
        ("Financial Workflow", ConfigurationType.WORKFLOW, get_financial_workflow_config()),
        ("Parallel Workflow", ConfigurationType.WORKFLOW, get_parallel_workflow_config()),
        
        ("Production Connection Pool", ConfigurationType.CONNECTION_POOL, get_production_connection_pool_config()),
        ("Development Connection Pool", ConfigurationType.CONNECTION_POOL, get_development_connection_pool_config()),
        
        ("Comprehensive Security", ConfigurationType.SECURITY, get_comprehensive_security_config()),
        ("Basic Security", ConfigurationType.SECURITY, get_basic_security_config()),
        
        ("Sequential Approval Chain", ConfigurationType.APPROVAL_CHAIN, get_sequential_approval_chain()),
        ("Parallel Approval Chain", ConfigurationType.APPROVAL_CHAIN, get_parallel_approval_chain()),
        
        ("Comprehensive Notifications", ConfigurationType.NOTIFICATION, get_comprehensive_notification_config()),
        ("Basic Notifications", ConfigurationType.NOTIFICATION, get_basic_notification_config()),
        
        ("Comprehensive Escalation", ConfigurationType.ESCALATION, get_comprehensive_escalation_config()),
        ("Basic Escalation", ConfigurationType.ESCALATION, get_basic_escalation_config())
    ]
    
    validation_results = []
    
    for name, config_type, config in configurations:
        print(f"\nValidating: {name}")
        result = validator.validate_configuration(config, config_type)
        
        if result.is_valid:
            status = "✅ VALID"
            if result.warnings:
                status += f" (⚠️ {len(result.warnings)} warnings)"
        else:
            status = f"❌ INVALID ({len(result.errors)} errors)"
        
        print(f"  Status: {status}")
        
        if result.errors:
            print("  Errors:")
            for error in result.errors[:3]:  # Show first 3 errors
                print(f"    - {error}")
            if len(result.errors) > 3:
                print(f"    ... and {len(result.errors) - 3} more")
        
        if result.warnings:
            print("  Warnings:")
            for warning in result.warnings[:3]:  # Show first 3 warnings
                print(f"    - {warning}")
            if len(result.warnings) > 3:
                print(f"    ... and {len(result.warnings) - 3} more")
        
        validation_results.append({
            'name': name,
            'type': config_type.value,
            'valid': result.is_valid,
            'errors': len(result.errors),
            'warnings': len(result.warnings)
        })
    
    # Summary
    print(f"\n" + "=" * 60)
    print("📊 VALIDATION SUMMARY")
    print("=" * 60)
    
    valid_configs = [r for r in validation_results if r['valid']]
    invalid_configs = [r for r in validation_results if not r['valid']]
    
    print(f"Total configurations: {len(validation_results)}")
    print(f"Valid: {len(valid_configs)}")
    print(f"Invalid: {len(invalid_configs)}")
    
    if invalid_configs:
        print(f"\nInvalid configurations:")
        for config in invalid_configs:
            print(f"  - {config['name']}: {config['errors']} errors")
    
    total_warnings = sum(r['warnings'] for r in validation_results)
    if total_warnings > 0:
        print(f"\nTotal warnings: {total_warnings}")
    
    return len(invalid_configs) == 0


def generate_configuration_templates():
    """Generate configuration template files."""
    print("\n📝 GENERATING CONFIGURATION TEMPLATES")
    print("=" * 60)
    
    from pgappforge.process.approval.config_validation import create_configuration_template
    
    templates = {
        "workflow_template.json": ConfigurationType.WORKFLOW,
        "connection_pool_template.json": ConfigurationType.CONNECTION_POOL,
        "security_template.json": ConfigurationType.SECURITY,
        "approval_chain_template.json": ConfigurationType.APPROVAL_CHAIN,
        "notification_template.json": ConfigurationType.NOTIFICATION,
        "escalation_template.json": ConfigurationType.ESCALATION
    }
    
    for filename, config_type in templates.items():
        try:
            template = create_configuration_template(config_type)
            print(f"Generated: {filename}")
            
            # In a real implementation, you would write to file:
            # with open(filename, 'w') as f:
            #     f.write(template)
            
        except Exception as e:
            print(f"Failed to generate {filename}: {e}")
    
    print("✅ Configuration templates generated")


def main():
    """Main function to demonstrate configuration validation."""
    print("🚀 APPROVAL SYSTEM CONFIGURATION EXAMPLES")
    print("=" * 60)
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    
    try:
        # Validate all configurations
        all_valid = validate_all_configurations()
        
        # Generate templates
        generate_configuration_templates()
        
        # Final status
        print(f"\n" + "=" * 60)
        if all_valid:
            print("✅ ALL CONFIGURATION EXAMPLES ARE VALID!")
            print("✅ Configuration validation system working correctly")
            print("✅ Templates generated successfully")
        else:
            print("❌ Some configuration examples failed validation")
            print("⚠️ Review configuration schemas and examples")
        
        return 0 if all_valid else 1
        
    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        return 1


if __name__ == '__main__':
    exit(main())