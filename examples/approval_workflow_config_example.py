"""
PgAppForge Approval Workflow Configuration Example

This configuration demonstrates how to set up the approval workflow system
for PgAppForge applications. The approval workflow system provides
secure, auditable multi-step approval processes for transactions and other
business processes.

Features demonstrated:
- Multi-step approval workflows with role-based authorization
- MFA requirements for high-value approvals  
- Database-level locking for financial transactions
- Comprehensive audit logging and security monitoring
- PgAppForge integration with proper permission management

To use this configuration:
1. Copy this file to your application's config directory
2. Modify the workflows to match your business requirements
3. Ensure you have the required roles configured in your PgAppForge application
4. Start your application - the approval workflow views will be automatically registered
"""

import os
from datetime import timedelta

# PgAppForge Basic Configuration
SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-in-production'
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Security Configuration
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = None

# Register the Approval Workflow Addon Manager
ADDON_MANAGERS = [
    'pgappforge.process.approval.addon_manager.ApprovalWorkflowAddonManager',
]

# ===========================
# Approval Workflow Configuration
# ===========================

PGAF_APPROVAL_WORKFLOWS = {
    # Default workflow for standard approval processes
    'default': {
        'steps': [
            {
                'name': 'manager_review', 
                'required_role': 'Manager', 
                'required_approvals': 1,
                'timeout_hours': 72  # 3 days
            },
            {
                'name': 'admin_approval', 
                'required_role': 'Admin', 
                'required_approvals': 1,
                'timeout_hours': 48  # 2 days
            }
        ],
        'initial_state': 'pending_approval',
        'approved_state': 'approved',
        'rejected_state': 'rejected',
        'timeout_state': 'timeout_expired'
    },
    
    # Financial workflow for monetary transactions with enhanced security
    'financial': {
        'steps': [
            {
                'name': 'financial_review', 
                'required_role': 'Financial_Manager', 
                'required_approvals': 2,  # Requires 2 financial managers
                'timeout_hours': 24
            },
            {
                'name': 'executive_approval', 
                'required_role': 'Executive', 
                'required_approvals': 1,
                'timeout_hours': 48,
                'requires_mfa': True  # MFA required for executive approval
            }
        ],
        'initial_state': 'pending_financial_review',
        'approved_state': 'financially_approved', 
        'rejected_state': 'financially_rejected',
        'timeout_state': 'financial_timeout',
        'requires_database_locking': True  # Critical for financial transactions
    },
    
    # High-value workflow for transactions above threshold
    'high_value': {
        'steps': [
            {
                'name': 'senior_manager_review',
                'required_role': 'Senior_Manager',
                'required_approvals': 1,
                'timeout_hours': 12
            },
            {
                'name': 'director_approval',
                'required_role': 'Director', 
                'required_approvals': 1,
                'timeout_hours': 24,
                'requires_mfa': True
            },
            {
                'name': 'cfo_approval',
                'required_role': 'CFO',
                'required_approvals': 1, 
                'timeout_hours': 72,
                'requires_mfa': True
            }
        ],
        'initial_state': 'pending_high_value_review',
        'approved_state': 'high_value_approved',
        'rejected_state': 'high_value_rejected', 
        'timeout_state': 'high_value_timeout',
        'requires_database_locking': True
    }
}

# ===========================
# PgAppForge Security Configuration
# ===========================

# Authentication Type
AUTH_TYPE = 1  # Database authentication (AUTH_DB)

# Role-based Access Control
AUTH_ROLE_ADMIN = 'Admin'
AUTH_ROLE_PUBLIC = 'Public'

# User registration settings
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Public"

# ===========================
# Optional: Wallet System Integration
# ===========================

# If you're using the wallet system with approval workflows:
# WALLET_CONFIG = {
#     'default_currency': 'USD',
#     'enable_multi_currency': False,
#     'approval_threshold': 1000.00,  # Transactions above this require approval
#     'high_value_threshold': 10000.00,  # High-value workflow threshold
#     'enable_audit_logging': True,
#     'transaction_retention_days': 2555  # 7 years
# }

# ===========================
# Application Factory Function
# ===========================

def create_app():
    """
    Create and configure the PgAppForge application with approval workflows.
    
    The ApprovalWorkflowAddonManager will be automatically loaded via ADDON_MANAGERS
    and will register:
    - Approval workflow views and API endpoints
    - Required permissions and roles
    - Menu items for approval management
    - Database models for approval tracking
    """
    from flask import Flask
    from pgappforge import AppBuilder, SQLA

    app = Flask(__name__)
    app.config.from_object(__name__)
    
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)
    
    # The approval workflow system is automatically initialized
    # You can access it via: appbuilder.get_addon_manager('ApprovalWorkflowAddonManager')
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)