"""
Approval Workflow System for PgForge

This module provides comprehensive approval workflow functionality with:
- Real ApprovalWorkflowManager implementation
- Database-level locking for race condition prevention  
- PgForge security integration with proper permission controls
- Comprehensive audit logging and security monitoring
- Web interface and REST API for approval operations

SECURITY FEATURES:
- Self-approval prevention with comprehensive audit trails
- Role-based authorization integrated with PgForge security
- Input sanitization and validation to prevent injection attacks
- Database-level concurrency controls using SELECT FOR UPDATE
- Multi-factor authentication support for high-value approvals
- Rate limiting and suspicious activity monitoring

INTEGRATION:
- Proper PgForge addon manager pattern
- Integration with existing security, permission, and audit systems
- Template-based web interface with responsive design
- RESTful API with comprehensive error handling
"""

from .workflow_manager import ApprovalWorkflowManager
from .workflow_views import ApprovalWorkflowView, ApprovalWorkflowApiView
from .addon_manager import ApprovalWorkflowAddonManager
from .security_validator import ApprovalSecurityValidator
from .audit_logger import ApprovalAuditLogger
from .workflow_engine import ApprovalWorkflowEngine

__all__ = [
    'ApprovalWorkflowManager',
    'ApprovalWorkflowView', 
    'ApprovalWorkflowApiView',
    'ApprovalWorkflowAddonManager',
    'ApprovalSecurityValidator',
    'ApprovalAuditLogger',
    'ApprovalWorkflowEngine'
]

# Version information
__version__ = '1.0.0'
__author__ = 'PgForge Extensions'
__description__ = 'Secure approval workflow system with PgForge integration'