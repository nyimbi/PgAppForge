"""
Multi-Tenant SaaS Manager.

PgAppForge addon manager for multi-tenant SaaS functionality.
Handles tenant management, context middleware, and view registration.
"""

import logging
from typing import Dict, List, Any

from flask import Flask
from pgappforge.base import BaseManager
from pgappforge.const import AUTH_LDAP, AUTH_DB, AUTH_OID, AUTH_OAUTH, AUTH_REMOTE_USER

from ..models.tenant_context import TenantMiddleware, init_tenant_middleware

log = logging.getLogger(__name__)


class TenantManager(BaseManager):
    """
    Manager for multi-tenant SaaS functionality.
    
    Provides tenant isolation, context management, and administrative
    interfaces for managing tenants, subscriptions, and billing.
    """
    
    def __init__(self, appbuilder):
        """Initialize tenant manager"""
        super().__init__(appbuilder)
        
        self.tenant_middleware = None
        self._tenant_views_registered = False
    
    def register_views(self):
        """Register tenant management views"""
        try:
            # Import views only when needed to avoid circular imports
            from .views import (
                TenantModelView, TenantUserModelView, TenantConfigModelView,
                TenantOnboardingView, TenantAdminView, TenantSelectorView
            )
            
            # Admin views for platform administrators
            self.appbuilder.add_view(
                TenantModelView,
                "Tenants",
                icon="fa-building",
                category="Tenant Management",
                category_icon="fa-users-cog"
            )
            
            self.appbuilder.add_view(
                TenantUserModelView,
                "Tenant Users", 
                icon="fa-user-friends",
                category="Tenant Management"
            )
            
            self.appbuilder.add_view(
                TenantConfigModelView,
                "Tenant Configs",
                icon="fa-cogs", 
                category="Tenant Management"
            )
            
            # Tenant-specific views
            self.appbuilder.add_view_no_menu(TenantOnboardingView)
            self.appbuilder.add_view_no_menu(TenantAdminView)
            self.appbuilder.add_view_no_menu(TenantSelectorView)
            
            self._tenant_views_registered = True
            log.info("Tenant management views registered successfully")
            
        except Exception as e:
            log.error(f"Failed to register tenant views: {e}")
            raise
    
    def create_permissions(self):
        """Create tenant-specific permissions and roles"""
        try:
            # Create permissions for tenant management
            permissions = [
                ('can_list', 'TenantModelView'),
                ('can_show', 'TenantModelView'),
                ('can_add', 'TenantModelView'),
                ('can_edit', 'TenantModelView'),
                ('can_delete', 'TenantModelView'),
                
                ('can_list', 'TenantUserModelView'),
                ('can_show', 'TenantUserModelView'),
                ('can_add', 'TenantUserModelView'),
                ('can_edit', 'TenantUserModelView'),
                ('can_delete', 'TenantUserModelView'),
                
                ('can_list', 'TenantConfigModelView'),
                ('can_show', 'TenantConfigModelView'),
                ('can_add', 'TenantConfigModelView'),
                ('can_edit', 'TenantConfigModelView'),
                ('can_delete', 'TenantConfigModelView'),
                
                # Tenant admin permissions
                ('can_admin_dashboard', 'TenantAdminView'),
                ('can_manage_users', 'TenantAdminView'),
                ('can_manage_billing', 'TenantAdminView'),
                ('can_manage_settings', 'TenantAdminView'),
                
                # Onboarding permissions
                ('can_signup', 'TenantOnboardingView'),
                ('can_verify', 'TenantOnboardingView'),
            ]
            
            # Create permissions
            for permission, view in permissions:
                self.appbuilder.sm.add_permission_view_menu(permission, view)
            
            # Create roles
            self._create_tenant_roles()
            
            log.info("Tenant permissions and roles created successfully")
            
        except Exception as e:
            log.error(f"Failed to create tenant permissions: {e}")
            raise
    
    def _create_tenant_roles(self):
        """Create tenant-specific roles"""
        # Platform Administrator - can manage all tenants
        platform_admin_perms = [
            ('can_list', 'TenantModelView'),
            ('can_show', 'TenantModelView'),
            ('can_add', 'TenantModelView'),
            ('can_edit', 'TenantModelView'),
            ('can_delete', 'TenantModelView'),
            ('can_list', 'TenantUserModelView'),
            ('can_show', 'TenantUserModelView'),
            ('can_add', 'TenantUserModelView'),
            ('can_edit', 'TenantUserModelView'),
            ('can_delete', 'TenantUserModelView'),
            ('can_list', 'TenantConfigModelView'),
            ('can_show', 'TenantConfigModelView'),
            ('can_add', 'TenantConfigModelView'),
            ('can_edit', 'TenantConfigModelView'),
            ('can_delete', 'TenantConfigModelView'),
        ]
        
        platform_admin_role = self.appbuilder.sm.add_role('Platform Admin')
        for perm, view in platform_admin_perms:
            perm_obj = self.appbuilder.sm.find_permission_view_menu(perm, view)
            if perm_obj:
                self.appbuilder.sm.add_permission_role(platform_admin_role, perm_obj)
        
        # Tenant Administrator - can manage their own tenant
        tenant_admin_perms = [
            ('can_admin_dashboard', 'TenantAdminView'),
            ('can_manage_users', 'TenantAdminView'),
            ('can_manage_billing', 'TenantAdminView'),
            ('can_manage_settings', 'TenantAdminView'),
        ]
        
        tenant_admin_role = self.appbuilder.sm.add_role('Tenant Admin')
        for perm, view in tenant_admin_perms:
            perm_obj = self.appbuilder.sm.find_permission_view_menu(perm, view)
            if perm_obj:
                self.appbuilder.sm.add_permission_role(tenant_admin_role, perm_obj)
        
        # Tenant User - basic tenant access
        tenant_user_role = self.appbuilder.sm.add_role('Tenant User')
        # Basic permissions would be added here based on tenant features
        
        log.info("Tenant roles created: Platform Admin, Tenant Admin, Tenant User")
    
    def init_app(self, app: Flask):
        """Initialize tenant functionality with Flask app"""
        try:
            # Initialize tenant middleware
            self.tenant_middleware = init_tenant_middleware(app)
            
            # Initialize configuration encryption system
            self._setup_config_encryption(app)
            
            # Set up tenant configuration
            self._setup_tenant_config(app)
            
            # Register database models
            self._register_models()
            
            log.info("Tenant manager initialized successfully")
            
        except Exception as e:
            log.error(f"Failed to initialize tenant manager: {e}")
            raise
    
    def _setup_config_encryption(self, app: Flask):
        """Initialize configuration encryption system"""
        try:
            from ..security.config_encryption import ConfigEncryption
            
            # Initialize encryption system
            config_encryption = ConfigEncryption(app)
            
            log.info("Configuration encryption system initialized")
            
            # Register CLI commands for config management
            self._register_config_cli(app)
            
        except Exception as e:
            log.error(f"Failed to initialize configuration encryption: {e}")
            # Don't raise - encryption is important but not critical for basic operation
            log.warning("Continuing without configuration encryption - sensitive data will not be encrypted")
    
    def _register_config_cli(self, app: Flask):
        """Register configuration management CLI commands"""
        try:
            from ..cli.config_migration import init_config_commands
            init_config_commands(app)
            log.debug("Configuration CLI commands registered")
        except Exception as e:
            log.error(f"Failed to register config CLI commands: {e}")
    
    def _setup_tenant_config(self, app: Flask):
        """Setup tenant-specific configuration"""
        # Set default tenant configuration
        app.config.setdefault('TENANT_SUBDOMAIN_ENABLED', True)
        app.config.setdefault('TENANT_CUSTOM_DOMAIN_ENABLED', True)
        app.config.setdefault('TENANT_ONBOARDING_ENABLED', True)
        app.config.setdefault('TENANT_DEV_DEFAULT_SLUG', None)
        
        # Default plans configuration
        app.config.setdefault('TENANT_DEFAULT_PLAN', 'free')
        app.config.setdefault('TENANT_AVAILABLE_PLANS', ['free', 'starter', 'professional', 'enterprise'])
        
        # Billing configuration
        app.config.setdefault('TENANT_BILLING_ENABLED', False)
        app.config.setdefault('STRIPE_PUBLISHABLE_KEY', None)
        app.config.setdefault('STRIPE_SECRET_KEY', None)
        
        log.debug("Tenant configuration setup complete")
    
    def _register_models(self):
        """Register tenant models with the session"""
        try:
            from ..models.tenant_models import (
                Tenant, TenantUser, TenantConfig, 
                TenantSubscription, TenantUsage
            )
            from ..models.tenant_examples import (
                CustomerMT, OrderMT, ProductMT, OrderItemMT,
                ProjectMT, TaskMT
            )
            
            # Models are automatically registered via SQLAlchemy declarative base
            log.debug("Tenant models registered with database session")
            
        except ImportError as e:
            log.warning(f"Some tenant models not available: {e}")
        except Exception as e:
            log.error(f"Failed to register tenant models: {e}")
    
    def pre_process(self):
        """Pre-process hook called by AppBuilder"""
        try:
            # Create database tables if they don't exist
            self._create_tables()
            
            # Set up default tenant if in development mode
            self._setup_development_tenant()
            
        except Exception as e:
            log.error(f"Tenant manager pre-process failed: {e}")
    
    def post_process(self):
        """Post-process hook called by AppBuilder"""
        try:
            # Final setup after all other managers are initialized
            log.info("Tenant manager post-process complete")
            
        except Exception as e:
            log.error(f"Tenant manager post-process failed: {e}")
    
    def _create_tables(self):
        """Create tenant database tables"""
        try:
            from pgappforge import db
            
            # Create all tables (this is safe - won't recreate existing tables)
            db.create_all()
            
            log.debug("Tenant database tables created/verified")
            
        except Exception as e:
            log.error(f"Failed to create tenant tables: {e}")
    
    def _setup_development_tenant(self):
        """Set up default tenant for development"""
        try:
            if not self.appbuilder.get_app.debug:
                return
            
            from ..models.tenant_models import Tenant
            from pgappforge import db
            
            # Check if development tenant exists
            dev_tenant = Tenant.query.filter_by(slug='dev').first()
            if not dev_tenant:
                dev_tenant = Tenant(
                    slug='dev',
                    name='Development Tenant',
                    description='Default tenant for development',
                    primary_contact_email='dev@localhost',
                    plan_id='enterprise',
                    status='active'
                )
                
                db.session.add(dev_tenant)
                db.session.commit()
                
                log.info("Created development tenant: dev")
            
        except Exception as e:
            log.error(f"Failed to setup development tenant: {e}")
    
    def get_tenant_stats(self) -> Dict[str, Any]:
        """Get platform-wide tenant statistics"""
        try:
            from ..models.tenant_models import Tenant, TenantUser, TenantSubscription
            from sqlalchemy import func
            from pgappforge import db
            
            # Basic tenant counts
            total_tenants = Tenant.query.count()
            active_tenants = Tenant.query.filter_by(status='active').count()
            
            # User counts
            total_tenant_users = TenantUser.query.filter_by(is_active=True).count()
            
            # Subscription stats
            subscription_stats = db.session.query(
                TenantSubscription.plan_id,
                func.count(TenantSubscription.id).label('count')
            ).filter_by(status='active').group_by(TenantSubscription.plan_id).all()
            
            plan_distribution = {plan: count for plan, count in subscription_stats}
            
            return {
                'total_tenants': total_tenants,
                'active_tenants': active_tenants,
                'total_users': total_tenant_users,
                'plan_distribution': plan_distribution,
                'average_users_per_tenant': round(total_tenant_users / max(active_tenants, 1), 2)
            }
            
        except Exception as e:
            log.error(f"Failed to get tenant stats: {e}")
            return {}
    
    def validate_tenant_isolation(self, model_class) -> List[str]:
        """Validate that a model properly implements tenant isolation"""
        issues = []
        
        # Check if model has tenant_id
        if not hasattr(model_class, 'tenant_id'):
            issues.append(f"{model_class.__name__} does not have tenant_id column")
        
        # Check if model uses TenantAwareMixin
        from ..models.tenant_models import TenantAwareMixin
        if not issubclass(model_class, TenantAwareMixin):
            issues.append(f"{model_class.__name__} does not inherit from TenantAwareMixin")
        
        # Check for proper indexes
        table = getattr(model_class, '__table__', None)
        if table is not None:
            tenant_indexed = any(
                'tenant_id' in [col.name for col in idx.columns] 
                for idx in table.indexes
            )
            if not tenant_indexed:
                issues.append(f"{model_class.__name__} should have indexes including tenant_id")
        
        return issues