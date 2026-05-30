"""
Simplified ApprovalWorkflowManager

Refactored to follow Single Responsibility Principle by coordinating
focused service classes instead of handling all concerns directly.

This replaces the original 680+ line god class with a clean coordinator
that delegates to specialized services.
"""

import logging
from typing import Dict, List, Optional
from flask import flash
from pgappforge.basemanager import BaseManager
from flask_babel import lazy_gettext as _

from .security_validator import ApprovalSecurityValidator
from .audit_logger import ApprovalAuditLogger
from .workflow_engine import ApprovalWorkflowEngine
from .cache_manager import get_cache_manager, CacheKeyPrefix, cache_result

log = logging.getLogger(__name__)


class ApprovalWorkflowManager(BaseManager):
    """
    Simplified PgAppForge addon manager for approval workflows.
    
    Acts as a lightweight coordinator that delegates to focused service classes:
    - ApprovalSecurityValidator: handles all security validation
    - ApprovalAuditLogger: handles audit logging and integrity  
    - ApprovalWorkflowEngine: handles workflow processing and data management
    
    This design follows Single Responsibility Principle and makes the system
    much easier to test, maintain, and extend.
    """
    
    def __init__(self, appbuilder):
        super(ApprovalWorkflowManager, self).__init__(appbuilder)
        
        # Initialize focused service classes
        self.security_validator = ApprovalSecurityValidator(appbuilder)
        self.audit_logger = ApprovalAuditLogger(appbuilder)
        self.workflow_engine = ApprovalWorkflowEngine(appbuilder)
        
        # Initialize cache manager
        self.cache_manager = get_cache_manager()
        
        # Configuration storage
        self.workflow_configs = {}
    
    def pre_process(self):
        """Pre-process hook called by PgAppForge during app initialization."""
        log.info("ApprovalWorkflowManager pre-process: Loading workflow configurations")
        self._load_workflow_configs()
    
    def post_process(self):
        """Post-process hook called by PgAppForge after app initialization."""
        config_count = len(self.workflow_configs)
        log.info(f"ApprovalWorkflowManager post-process: {config_count} workflows configured")
    
    @cache_result(CacheKeyPrefix.WORKFLOW_CONFIG, ttl=3600)  # Cache for 1 hour
    def _load_workflow_configs(self):
        """Load workflow configurations from Flask config with caching."""
        # Check cache first
        cached_configs = self.cache_manager.get(CacheKeyPrefix.WORKFLOW_CONFIG, "global_configs")
        if cached_configs is not None:
            self.workflow_configs = cached_configs
            log.info(f"ApprovalWorkflowManager loaded {len(self.workflow_configs)} workflow configurations from cache")
            return
            
        # Load from Flask config
        config = self.appbuilder.get_app.config
        self.workflow_configs = config.get('PGAF_APPROVAL_WORKFLOWS', {
            # Default secure workflow configuration
            'default': {
                'steps': [
                    {
                        'name': 'manager_review', 
                        'required_role': 'Manager', 
                        'required_approvals': 1,
                        'timeout_hours': 72
                    },
                    {
                        'name': 'admin_approval', 
                        'required_role': 'Admin', 
                        'required_approvals': 1,
                        'timeout_hours': 48
                    }
                ],
                'initial_state': 'pending_approval',
                'approved_state': 'approved',
                'rejected_state': 'rejected',
                'timeout_state': 'timeout_expired'
            }
        })
        
        # Cache the loaded configurations
        self.cache_manager.set(CacheKeyPrefix.WORKFLOW_CONFIG, "global_configs", value=self.workflow_configs, ttl=3600)
        
        log.info(f"ApprovalWorkflowManager loaded {len(self.workflow_configs)} workflow configurations from config")
    
    def register_model_workflow(self, model_class, workflow_name='default'):
        """Register a model with a specific workflow."""
        return self.workflow_engine.register_model_workflow(
            model_class, workflow_name, self.workflow_configs
        )
    
    def approve_instance(self, instance, step: int = 0, comments: str = None) -> bool:
        """
        SECURE APPROVAL IMPLEMENTATION with comprehensive security controls.
        
        Coordinates security validation, workflow processing, and audit logging
        through focused service classes.
        
        Args:
            instance: Model instance to approve
            step: Approval step (0-based index)
            comments: Optional approval comments (will be sanitized)
            
        Returns:
            bool: True if approval successful and committed to database
        """
        # Get current user from PgAppForge security manager
        current_user = self.appbuilder.sm.current_user
        
        # 1. AUTHENTICATION VALIDATION (Security Service)
        if not self.security_validator.validate_authentication(current_user):
            self.audit_logger.log_security_violation(
                'approval_attempt_unauthenticated',
                None, instance, {'step': step}
            )
            flash(_("Authentication required for approval operations"), "error")
            return False
        
        # 2. RATE LIMITING CHECK (Security Service)
        if not self.security_validator.check_approval_rate_limit(current_user.id):
            self.audit_logger.log_security_violation(
                'rate_limit_exceeded', 
                current_user, instance, {'step': step}
            )
            flash(_("Too many approval attempts. Please wait before trying again."), "error")
            return False
        
        # 3. WORKFLOW CONFIGURATION VALIDATION
        workflow_name = getattr(instance.__class__, '_approval_workflow', 'default')
        workflow_config = self.workflow_configs.get(workflow_name)
        if not workflow_config:
            self.audit_logger.log_security_violation(
                'invalid_workflow_access',
                current_user, instance, {'workflow_name': workflow_name}
            )
            log.error(f"No workflow configuration found: {workflow_name}")
            return False
        
        # 4. APPROVAL STEP VALIDATION (Security Service)
        if not self.security_validator.validate_approval_step(step, workflow_config):
            self.audit_logger.log_security_violation(
                'invalid_step_access',
                current_user, instance, {'step': step, 'max_steps': len(workflow_config['steps'])}
            )
            return False
        
        step_config = workflow_config['steps'][step]
        
        # 5. SELF-APPROVAL PREVENTION (Security Service)
        if self.security_validator.validate_self_approval(instance, current_user):
            self.audit_logger.log_security_violation(
                'self_approval_blocked',
                current_user, instance, {'step': step}
            )
            flash(_("Users cannot approve their own submissions for security reasons"), "error")
            return False
        
        # 6. ROLE-BASED AUTHORIZATION (Security Service)
        if not self.security_validator.validate_user_role(current_user, step_config['required_role']):
            self.audit_logger.log_security_violation(
                'insufficient_privileges',
                current_user, instance, {
                    'required_role': step_config['required_role'],
                    'user_roles': [role.name for role in current_user.roles] if current_user.roles else []
                }
            )
            flash(_("Insufficient privileges for this approval step"), "error")
            return False
        
        # 7. MFA VALIDATION (Security Service)
        if step_config.get('requires_mfa', False):
            if not self.security_validator.validate_mfa_requirement(current_user, instance):
                self.audit_logger.log_security_violation(
                    'mfa_required_not_satisfied',
                    current_user, instance, {'step': step}
                )
                flash(_("Multi-factor authentication required for this approval"), "error")
                return False
        
        # 8. INPUT SANITIZATION (Security Service)
        sanitized_comments = self.security_validator.sanitize_approval_comments(comments) if comments else None
        if comments and not sanitized_comments:
            self.audit_logger.log_security_violation(
                'malicious_comment_blocked',
                current_user, instance, {'step': step, 'original_length': len(comments)}
            )
            flash(_("Comments contain invalid content and were rejected"), "error")
            return False
        
        # 9. WORKFLOW STATE VALIDATION (Security Service)
        if not self.security_validator.validate_workflow_state(instance, workflow_config, step):
            self.audit_logger.log_security_violation(
                'invalid_workflow_state',
                current_user, instance, {'step': step, 'current_state': getattr(instance, 'current_state', 'unknown')}
            )
            flash(_("Invalid workflow state for this approval step"), "error")
            return False
        
        # 10. DUPLICATE APPROVAL CHECK (Security Service)
        approval_history = self.workflow_engine.get_approval_history(instance)
        if self.security_validator.check_duplicate_approval(approval_history, current_user.id, step):
            self.audit_logger.log_security_violation(
                'duplicate_approval_blocked',
                current_user, instance, {'step': step}
            )
            flash(_("You have already approved this step"), "warning")
            return False
        
        # 11. WORKFLOW PROCESSING (Workflow Engine)
        try:
            use_locking = workflow_config.get('requires_database_locking', False)
            success, approval_data = self.workflow_engine.process_approval_transaction(
                instance, current_user, step, step_config, sanitized_comments, workflow_config, use_locking
            )
            
            if success:
                # 12. AUDIT LOGGING (Audit Service)
                # Create secure approval record with integrity hash
                secure_approval_data = self.audit_logger.create_secure_approval_record(
                    current_user, step, step_config, sanitized_comments
                )
                
                # Log successful approval
                self.audit_logger.log_approval_granted(
                    current_user, instance, step_config, workflow_name, sanitized_comments
                )
                
                flash(_("Approval recorded successfully for step: %(step_name)s", step_name=step_config['name']), "success")
                return True
            else:
                flash(_("Approval failed due to system error"), "error")
                return False
                
        except Exception as e:
            self.audit_logger.log_transaction_failed(current_user, getattr(instance, 'id', 'unknown'), step, e)
            log.error(f"Secure approval transaction failed: {e}")
            flash(_("Approval failed due to system error"), "error")
            return False
    
    def create_approval_workflow(self, instance, workflow_name: str = 'default') -> bool:
        """
        Initialize approval workflow for an instance.
        
        Delegates to workflow engine for processing.
        """
        workflow_config = self.workflow_configs.get(workflow_name)
        if not workflow_config:
            log.error(f"Unknown workflow: {workflow_name}")
            return False
        
        return self.workflow_engine.create_approval_workflow(instance, workflow_name, workflow_config)
    
    def get_approval_history(self, instance) -> List[Dict]:
        """Get approval history for an instance."""
        return self.workflow_engine.get_approval_history(instance)

    
    @cache_result(CacheKeyPrefix.USER_ROLES, ttl=900, key_args=['user_id'])
    def get_user_roles_cached(self, user_id: int) -> List[str]:
        """
        Get user roles with caching to improve performance.
        
        Args:
            user_id: User ID to get roles for
            
        Returns:
            list: List of role names for the user
        """
        # Check cache first
        cached_roles = self.cache_manager.get(CacheKeyPrefix.USER_ROLES, user_id)
        if cached_roles is not None:
            return cached_roles
        
        try:
            # Query user roles from database
            from pgappforge.security.sqla.models import User
            db_session = self.appbuilder.get_session()
            user = db_session.query(User).get(user_id)
            
            if user and user.roles:
                role_names = [role.name for role in user.roles]
            else:
                role_names = []
            
            # Cache the roles
            self.cache_manager.set(CacheKeyPrefix.USER_ROLES, user_id, value=role_names, ttl=900)
            
            return role_names
            
        except Exception as e:
            log.error(f"Error getting user roles for user {user_id}: {e}")
            return []
    
    @cache_result(CacheKeyPrefix.USER_PERMISSIONS, ttl=600, key_args=['user_id', 'resource'])
    def check_user_permission_cached(self, user_id: int, resource: str, permission: str) -> bool:
        """
        Check user permission with caching.
        
        Args:
            user_id: User ID to check
            resource: Resource name
            permission: Permission name
            
        Returns:
            bool: True if user has permission
        """
        cache_key = f"{user_id}:{resource}:{permission}"
        cached_result = self.cache_manager.get(CacheKeyPrefix.USER_PERMISSIONS, cache_key)
        
        if cached_result is not None:
            return cached_result
        
        try:
            # Check permission using PgAppForge security manager
            user = self.appbuilder.sm.get_user_by_id(user_id)
            if not user:
                result = False
            else:
                result = self.appbuilder.sm.has_access(permission, resource, user)
            
            # Cache the result
            self.cache_manager.set(CacheKeyPrefix.USER_PERMISSIONS, cache_key, value=result, ttl=600)
            
            return result
            
        except Exception as e:
            log.error(f"Error checking permission for user {user_id}: {e}")
            return False
    
    def invalidate_user_cache(self, user_id: int):
        """
        Invalidate all cached data for a specific user.
        
        This should be called when user roles or permissions change.
        """
        self.cache_manager.delete(CacheKeyPrefix.USER_ROLES, user_id)
        # Clear all user permissions (requires prefix clearing)
        self.cache_manager.clear_prefix(CacheKeyPrefix.USER_PERMISSIONS)
        log.info(f"Invalidated cache for user {user_id}")
    
    def get_cache_statistics(self) -> Dict:
        """Get comprehensive cache statistics for monitoring."""
        return self.cache_manager.get_statistics()
