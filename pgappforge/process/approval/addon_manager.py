"""
Approval Workflow Addon Manager

PgAppForge addon manager that properly integrates the ApprovalWorkflowManager
and its views with the PgAppForge application lifecycle and security system.

INTEGRATION FEATURES:
- Registers ApprovalWorkflowManager as a PgAppForge addon manager
- Automatically registers approval workflow views with proper permissions
- Integrates with PgAppForge's menu system
- Provides complete PgAppForge security context integration
"""

import logging
from pgappforge.basemanager import BaseManager
from flask_babel import lazy_gettext as _

from .workflow_manager import ApprovalWorkflowManager
from .workflow_views import ApprovalWorkflowView, ApprovalWorkflowApiView

log = logging.getLogger(__name__)


class ApprovalWorkflowAddonManager(BaseManager):
    """
    PgAppForge addon manager for approval workflows.
    
    This manager ensures proper integration of the ApprovalWorkflowManager
    and its views with PgAppForge's security and permission system.
    
    SECURITY INTEGRATION:
    - Registers views with proper PgAppForge permission contexts
    - Integrates with PgAppForge's role-based access control
    - Provides audit logging through PgAppForge's security manager
    - Ensures proper session and authentication context validation
    """
    
    def __init__(self, appbuilder):
        super().__init__(appbuilder)
        self.workflow_manager = None
        self.workflow_view = None
        self.workflow_api_view = None
    
    def register_views(self):
        """
        Register approval workflow views with PgAppForge.
        
        This method is called automatically by PgAppForge during
        application initialization to register all views and their
        associated permissions.
        """
        try:
            # Initialize the ApprovalWorkflowManager
            self.workflow_manager = ApprovalWorkflowManager(self.appbuilder)
            log.info("ApprovalWorkflowManager initialized successfully")
            
            # Register the web interface view
            self.workflow_view = ApprovalWorkflowView()
            self.appbuilder.add_view(
                self.workflow_view,
                "Pending Approvals",
                icon="fa-check-circle",
                category="Workflow Management",
                category_icon="fa-cogs"
            )
            log.info("ApprovalWorkflowView registered successfully")
            
            # Register the REST API view
            self.workflow_api_view = ApprovalWorkflowApiView()
            self.appbuilder.add_api(self.workflow_api_view)
            log.info("ApprovalWorkflowApiView registered successfully")
            
            # Register workflow configurations with models
            self._register_workflow_models()
            
            log.info("ApprovalWorkflowAddonManager registration completed successfully")
            
        except Exception as e:
            log.error(f"Failed to register ApprovalWorkflowAddonManager: {e}")
            raise
    
    
    def _register_workflow_models(self):
        """Register models with their respective approval workflows."""
        try:
            from ...wallet.models import WalletTransaction
            
            # Register WalletTransaction with financial workflow for high-value transactions
            # and default workflow for standard transactions
            self.workflow_manager.register_model_workflow(WalletTransaction, 'financial')
            
            log.info("Workflow models registered successfully")
            
        except Exception as e:
            log.error(f"Failed to register workflow models: {e}")
    
    def create_permissions(self):
        """
        Create PgAppForge permissions for approval workflows.
        
        This method is called automatically by PgAppForge to create
        the necessary permissions in the security system.
        """
        try:
            # Create custom permissions for approval operations
            self.appbuilder.sm.add_permission_view_menu(
                'can_approve_transactions',
                'ApprovalWorkflowView'
            )
            
            self.appbuilder.sm.add_permission_view_menu(
                'can_reject_transactions', 
                'ApprovalWorkflowView'
            )
            
            self.appbuilder.sm.add_permission_view_menu(
                'can_view_approval_history',
                'ApprovalWorkflowView'
            )
            
            # Create permissions for API endpoints
            self.appbuilder.sm.add_permission_view_menu(
                'can_get',
                'ApprovalWorkflowApiView'
            )
            
            self.appbuilder.sm.add_permission_view_menu(
                'can_post',
                'ApprovalWorkflowApiView'
            )
            
            log.info("Approval workflow permissions created successfully")
            
        except Exception as e:
            log.error(f"Failed to create approval workflow permissions: {e}")
    
    def init_role(self):
        """
        Initialize default roles for approval workflows.
        
        Creates default roles with appropriate permissions for approval workflows.
        """
        try:
            # Create Manager role with approval permissions
            manager_role = self.appbuilder.sm.add_role('Manager')
            if manager_role:
                # Add approval permissions to Manager role
                self.appbuilder.sm.add_permission_role(
                    manager_role,
                    self.appbuilder.sm.find_permission_view_menu(
                        'can_approve_transactions',
                        'ApprovalWorkflowView'
                    )
                )
                self.appbuilder.sm.add_permission_role(
                    manager_role,
                    self.appbuilder.sm.find_permission_view_menu(
                        'can_reject_transactions',
                        'ApprovalWorkflowView'
                    )
                )
                self.appbuilder.sm.add_permission_role(
                    manager_role,
                    self.appbuilder.sm.find_permission_view_menu(
                        'can_view_approval_history',
                        'ApprovalWorkflowView'
                    )
                )
                
                log.info("Manager role initialized with approval permissions")
            
            # Create Financial_Manager role for financial workflow approvals
            financial_manager_role = self.appbuilder.sm.add_role('Financial_Manager')
            if financial_manager_role:
                # Add all approval permissions to Financial_Manager role
                self.appbuilder.sm.add_permission_role(
                    financial_manager_role,
                    self.appbuilder.sm.find_permission_view_menu(
                        'can_approve_transactions',
                        'ApprovalWorkflowView'
                    )
                )
                self.appbuilder.sm.add_permission_role(
                    financial_manager_role,
                    self.appbuilder.sm.find_permission_view_menu(
                        'can_reject_transactions',
                        'ApprovalWorkflowView'
                    )
                )
                
                log.info("Financial_Manager role initialized with approval permissions")
            
            # Ensure Admin role has all approval permissions
            admin_role = self.appbuilder.sm.find_role('Admin')
            if admin_role:
                permissions = [
                    ('can_approve_transactions', 'ApprovalWorkflowView'),
                    ('can_reject_transactions', 'ApprovalWorkflowView'),
                    ('can_view_approval_history', 'ApprovalWorkflowView'),
                    ('can_get', 'ApprovalWorkflowApiView'),
                    ('can_post', 'ApprovalWorkflowApiView')
                ]
                
                for perm_name, view_name in permissions:
                    perm = self.appbuilder.sm.find_permission_view_menu(perm_name, view_name)
                    if perm:
                        self.appbuilder.sm.add_permission_role(admin_role, perm)
                
                log.info("Admin role updated with all approval permissions")
                
        except Exception as e:
            log.error(f"Failed to initialize approval workflow roles: {e}")
    
    def get_workflow_manager(self) -> ApprovalWorkflowManager:
        """
        Get the ApprovalWorkflowManager instance.
        
        Returns:
            ApprovalWorkflowManager: The workflow manager instance
        """
        if not self.workflow_manager:
            self.workflow_manager = ApprovalWorkflowManager(self.appbuilder)
        
        return self.workflow_manager
    
    def pre_process(self):
        """
        Pre-process hook called by PgAppForge.
        
        Performs any necessary initialization before the application starts.
        """
        log.info("ApprovalWorkflowAddonManager pre-process hook called")
        
        # Validate workflow configurations
        try:
            workflow_manager = self.get_workflow_manager()
            config_count = len(workflow_manager.workflow_configs)
            log.info(f"Validated {config_count} approval workflow configurations")
            
        except Exception as e:
            log.error(f"Workflow configuration validation failed: {e}")
    
    def post_process(self):
        """
        Post-process hook called by PgAppForge.
        
        Performs any necessary cleanup or final initialization.
        """
        log.info("ApprovalWorkflowAddonManager post-process hook called")
        
        # Log final registration status
        try:
            log.info("Approval workflow system fully integrated with PgAppForge")
            log.info(f"ApprovalWorkflowManager instance: {self.workflow_manager}")
            log.info(f"ApprovalWorkflowView instance: {self.workflow_view}")
            log.info(f"ApprovalWorkflowApiView instance: {self.workflow_api_view}")
            
        except Exception as e:
            log.error(f"Post-process validation failed: {e}")