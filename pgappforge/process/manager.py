"""
Process Manager for PgAppForge Integration.

Provides proper lifecycle management, view registration, and security
integration following PgAppForge addon manager patterns.
"""

import logging
from typing import Dict, Any, Optional

from flask import current_app
from pgappforge.basemanager import BaseManager

from .engine.process_engine import ProcessEngine
from .engine.process_service import ProcessService
from .views import (
    ProcessDefinitionView, ProcessInstanceView, ProcessStepView, ApprovalRequestView,
    ProcessApi, ProcessInstanceApi, ProcessMetricsApi
)
from .security.integration import init_process_security
from .models.process_models import ProcessDefinition, ProcessInstance, ProcessStep, ApprovalRequest

log = logging.getLogger(__name__)


class ProcessManager(BaseManager):
    """
    Process Engine Manager for PgAppForge integration.
    
    Provides proper lifecycle management, view registration, and
    security integration following FAB addon manager patterns.
    """
    
    def __init__(self, appbuilder):
        """Initialize the process manager."""
        super().__init__(appbuilder)
        self.engine = None
        self.process_service = None
        self._security_initialized = False
        self._views_registered = False
        self._models_created = False
    
    def pre_process(self):
        """Initialize process engine and security before view registration."""
        try:
            log.info("ProcessManager: Starting pre-processing")
            
            # Initialize Redis and Celery from app config if available
            redis_client = self.appbuilder.app.extensions.get('redis')
            celery_app = self.appbuilder.app.extensions.get('celery')
            
            # Initialize async engine
            self.engine = ProcessEngine(redis_client, celery_app)
            
            # Initialize synchronous service wrapper
            self.process_service = ProcessService(self.engine)
            
            # Initialize security system
            init_process_security(self.appbuilder.app)
            self._security_initialized = True
            
            # Register engine and service as app extensions for global access
            self.appbuilder.app.extensions['process_engine'] = self.engine
            self.appbuilder.app.extensions['process_service'] = self.process_service
            
            log.info("ProcessManager: Pre-processing completed successfully")
            
        except Exception as e:
            log.error(f"ProcessManager pre-processing failed: {e}")
            raise
    
    def register_views(self):
        """Register process-related views and APIs."""
        try:
            log.info("ProcessManager: Registering views")
            
            # Register Process Definition Management
            self.appbuilder.add_view(
                ProcessDefinitionView,
                "Process Definitions",
                icon="fa-sitemap",
                category="Process Management",
                category_icon="fa-cogs",
                category_label="Process Management"
            )
            
            # Register Process Instance Monitoring  
            self.appbuilder.add_view(
                ProcessInstanceView,
                "Process Instances", 
                icon="fa-tasks",
                category="Process Management"
            )
            
            # Register Process Step Details
            self.appbuilder.add_view(
                ProcessStepView,
                "Process Steps",
                icon="fa-step-forward", 
                category="Process Management"
            )
            
            # Register Approval Requests
            self.appbuilder.add_view(
                ApprovalRequestView,
                "Approval Requests",
                icon="fa-check-circle",
                category="Process Management"
            )
            
            # Register REST APIs
            self.appbuilder.add_api(ProcessApi)
            self.appbuilder.add_api(ProcessInstanceApi) 
            self.appbuilder.add_api(ProcessMetricsApi)
            
            self._views_registered = True
            log.info("ProcessManager: Views registered successfully")
            
        except Exception as e:
            log.error(f"ProcessManager view registration failed: {e}")
            raise
    
    def post_process(self):
        """Finalize process engine setup after views are registered."""
        try:
            log.info("ProcessManager: Starting post-processing")
            
            # Create database tables if they don't exist
            self._create_tables()
            
            # Setup periodic tasks if Celery is available
            if self.engine and self.engine.celery:
                self._setup_periodic_tasks()
            
            # Initialize process security permissions
            self._setup_process_permissions()
            
            # Setup configuration from app config
            self._setup_configuration()
            
            log.info("ProcessManager: Post-processing completed successfully")
            
        except Exception as e:
            log.error(f"ProcessManager post-processing failed: {e}")
            raise
    
    def _create_tables(self):
        """Create process-related database tables."""
        try:
            from pgappforge import db
            
            # Import all models to ensure they're registered
            from .models.process_models import (
                ProcessDefinition, ProcessInstance, ProcessStep,
                ProcessTemplate, ApprovalRequest, SmartTrigger, ProcessMetric
            )
            from .models.audit_models import (
                ProcessAuditLog, ProcessSecurityEvent, ProcessComplianceLog
            )
            
            # Create tables
            db.create_all()
            self._models_created = True
            
            log.info("ProcessManager: Database tables created/verified")
            
        except Exception as e:
            log.error(f"Failed to create process tables: {e}")
            raise
    
    def _setup_periodic_tasks(self):
        """Setup Celery periodic tasks for process management."""
        try:
            # Import tasks to ensure they're registered
            from .tasks import (
                cleanup_completed_processes, monitor_stuck_processes, 
                generate_process_metrics
            )
            
            log.info("ProcessManager: Periodic tasks configured")
            
        except Exception as e:
            log.warning(f"Failed to setup periodic tasks: {e}")
            # Don't fail startup if Celery tasks can't be configured
    
    def _setup_process_permissions(self):
        """Setup process-specific permissions in FAB's security system."""
        try:
            sm = self.appbuilder.sm
            
            # Define process-specific permissions
            process_permissions = [
                ('can_deploy_process', 'ProcessDefinition'),
                ('can_execute_process', 'ProcessInstance'),
                ('can_suspend_process', 'ProcessInstance'),
                ('can_resume_process', 'ProcessInstance'),
                ('can_cancel_process', 'ProcessInstance'),
                ('can_approve_process', 'ApprovalRequest'),
                ('can_reject_process', 'ApprovalRequest'),
                ('can_admin_process', 'ProcessAdmin'),
                ('can_monitor_process', 'ProcessMonitor')
            ]
            
            # Add permissions using FAB's permission system
            for permission_name, view_menu_name in process_permissions:
                # Find or create permission
                perm = sm.find_permission(permission_name)
                if not perm:
                    perm = sm.add_permission(permission_name)
                
                # Find or create view menu
                vm = sm.find_view_menu(view_menu_name)
                if not vm:
                    vm = sm.add_view_menu(view_menu_name)
                
                # Link permission to view menu
                if not sm.find_permission_view_menu(permission_name, view_menu_name):
                    sm.add_permission_view_menu(perm, vm)
            
            log.info("ProcessManager: Process permissions configured")
            
        except Exception as e:
            log.error(f"Failed to setup process permissions: {e}")
            raise
    
    def _setup_configuration(self):
        """Setup process configuration from Flask app config."""
        try:
            app_config = self.appbuilder.app.config
            
            # Process engine configuration
            process_config = {
                'redis_url': app_config.get('PROCESS_REDIS_URL', 'redis://localhost:6379/0'),
                'celery_broker': app_config.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
                'max_concurrent_processes': app_config.get('PROCESS_MAX_CONCURRENT', 100),
                'default_timeout': app_config.get('PROCESS_DEFAULT_TIMEOUT', 3600),
                'retention_days': app_config.get('PROCESS_RETENTION_DAYS', 90),
                'stuck_threshold_hours': app_config.get('STUCK_PROCESS_HOURS', 24),
                'enable_ml_features': app_config.get('PROCESS_ENABLE_ML', False),
                'enable_audit_logging': app_config.get('PROCESS_ENABLE_AUDIT', True)
            }
            
            # Apply configuration to engine
            if self.engine:
                self.engine.configure(process_config)
            
            log.info(f"ProcessManager: Configuration applied: {len(process_config)} settings")
            
        except Exception as e:
            log.warning(f"Failed to apply process configuration: {e}")
            # Don't fail startup for configuration issues
    
    def get_engine(self) -> ProcessEngine:
        """Get the process engine instance."""
        if not self.engine:
            raise RuntimeError("Process engine not initialized. Call pre_process() first.")
        return self.engine
    
    def get_service(self) -> ProcessService:
        """Get the process service instance.""" 
        if not self.process_service:
            raise RuntimeError("Process service not initialized. Call pre_process() first.")
        return self.process_service
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the process system."""
        try:
            status = {
                'manager_status': 'healthy',
                'security_initialized': self._security_initialized,
                'views_registered': self._views_registered,
                'models_created': self._models_created,
                'engine_status': 'not_initialized',
                'service_status': 'not_initialized',
                'components': {}
            }
            
            # Check engine status
            if self.engine:
                status['engine_status'] = 'healthy'
                # Add engine-specific health checks
                if hasattr(self.engine, 'get_health_status'):
                    status['components']['engine'] = self.engine.get_health_status()
            
            # Check service status
            if self.process_service:
                status['service_status'] = 'healthy' 
                
            # Check database connectivity
            try:
                from pgappforge import db
                db.session.execute('SELECT 1').fetchone()
                status['components']['database'] = {'status': 'healthy'}
            except Exception as e:
                status['components']['database'] = {'status': 'unhealthy', 'error': str(e)}
                status['manager_status'] = 'degraded'
            
            # Check Redis connectivity if configured
            if self.engine and self.engine.redis_client:
                try:
                    self.engine.redis_client.ping()
                    status['components']['redis'] = {'status': 'healthy'}
                except Exception as e:
                    status['components']['redis'] = {'status': 'unhealthy', 'error': str(e)}
                    status['manager_status'] = 'degraded'
            
            return status
            
        except Exception as e:
            return {
                'manager_status': 'unhealthy',
                'error': str(e)
            }


def get_process_manager() -> ProcessManager:
    """Get the process manager from current PgAppForge app."""
    try:
        from flask import current_app
        return current_app.appbuilder.process_manager
    except AttributeError:
        raise RuntimeError("ProcessManager not found. Make sure it's registered in ADDON_MANAGERS.")


# Configuration for automatic registration
PROCESS_MANAGER_CONFIG = {
    'name': 'ProcessManager', 
    'description': 'Intelligent Business Process Engine for PgAppForge',
    'version': '1.0.0',
    'author': 'PgAppForge Process Engine',
    'dependencies': ['redis', 'celery'],
    'optional_dependencies': ['pandas', 'numpy', 'scikit-learn']
}