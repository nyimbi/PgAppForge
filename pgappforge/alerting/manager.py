"""
PgAppForge Manager for Alerting System.

Provides proper integration with PgAppForge's manager lifecycle and
view registration system following FAB patterns.
"""

import logging
from pgappforge.basemanager import BaseManager
from .alert_views import AlertConfigView, AlertHistoryView
from .alert_manager import AlertManager
from .threshold_monitor import ThresholdMonitor
from .notification_service import NotificationService

log = logging.getLogger(__name__)


class AlertingManager(BaseManager):
    """
    PgAppForge manager for the alerting system.
    
    Handles proper lifecycle management, view registration, and integration
    with PgAppForge's permission and menu systems.
    """
    
    def __init__(self, appbuilder):
        """Initialize alerting manager with AppBuilder instance."""
        super().__init__(appbuilder)
        
        # Initialize core alerting components
        self.alert_manager = None
        self.threshold_monitor = None
        self.notification_service = None
    
    def init_app(self, app):
        """Initialize the alerting system with Flask app."""
        super().init_app(app)
        
        # Initialize core components
        self.alert_manager = AlertManager(app)
        self.notification_service = NotificationService(app)
        self.threshold_monitor = ThresholdMonitor(
            self.alert_manager,
            # TODO: Load config from app.config
        )
        
        # Store references for view access
        app.extensions['alerting_manager'] = self
        app.extensions['alert_manager'] = self.alert_manager
        app.extensions['notification_service'] = self.notification_service
        app.extensions['threshold_monitor'] = self.threshold_monitor
        
        log.info("Alerting Manager initialized successfully")
    
    def register_views(self):
        """Register alerting views with PgAppForge."""
        try:
            # Register main alert configuration view
            self.appbuilder.add_view(
                AlertConfigView,
                "Alert Dashboard",
                icon="fa-bell",
                category="Monitoring",
                category_icon="fa-chart-line",
                category_label="Monitoring"
            )
            
            # Register alert rules management
            self.appbuilder.add_view_no_menu(
                AlertConfigView(),
                "Alert Rules"
            )
            
            # Register alert history view  
            self.appbuilder.add_view(
                AlertHistoryView,
                "Alert History",
                icon="fa-history",
                category="Monitoring"
            )
            
            log.info("Alerting views registered successfully")
            
        except Exception as e:
            log.error(f"Error registering alerting views: {e}")
            raise
    
    def create_permissions(self):
        """Create permissions for alerting views."""
        try:
            # Define alerting-specific permissions
            permissions = [
                # Alert configuration permissions
                ('can_list', 'AlertConfigView'),
                ('can_show', 'AlertConfigView'), 
                ('can_add', 'AlertConfigView'),
                ('can_edit', 'AlertConfigView'),
                ('can_delete', 'AlertConfigView'),
                
                # Alert monitoring permissions
                ('can_start_monitoring', 'AlertConfigView'),
                ('can_stop_monitoring', 'AlertConfigView'),
                ('can_force_evaluation', 'AlertConfigView'),
                
                # Alert history permissions
                ('can_list', 'AlertHistoryView'),
                ('can_show', 'AlertHistoryView'),
                ('can_export', 'AlertHistoryView'),
                
                # API permissions
                ('can_api_alerts', 'AlertConfigView'),
                ('can_api_acknowledge_alert', 'AlertConfigView'),
                ('can_api_metrics', 'AlertConfigView'),
            ]
            
            # Create permissions using AppBuilder's permission system
            for permission_name, view_name in permissions:
                self.appbuilder.sm.add_permission_view_menu(
                    permission_name, 
                    view_name
                )
            
            log.info("Alerting permissions created successfully")
            
        except Exception as e:
            log.error(f"Error creating alerting permissions: {e}")
            # Don't raise - permissions can be created manually if needed
    
    def create_roles(self):
        """Create default roles for alerting system."""
        try:
            # Define alerting roles
            alert_admin_perms = [
                ('can_list', 'AlertConfigView'),
                ('can_show', 'AlertConfigView'),
                ('can_add', 'AlertConfigView'), 
                ('can_edit', 'AlertConfigView'),
                ('can_delete', 'AlertConfigView'),
                ('can_start_monitoring', 'AlertConfigView'),
                ('can_stop_monitoring', 'AlertConfigView'),
                ('can_force_evaluation', 'AlertConfigView'),
                ('can_list', 'AlertHistoryView'),
                ('can_show', 'AlertHistoryView'),
                ('can_export', 'AlertHistoryView'),
                ('can_api_alerts', 'AlertConfigView'),
                ('can_api_acknowledge_alert', 'AlertConfigView'),
                ('can_api_metrics', 'AlertConfigView'),
            ]
            
            alert_user_perms = [
                ('can_list', 'AlertConfigView'),
                ('can_show', 'AlertConfigView'),
                ('can_api_acknowledge_alert', 'AlertConfigView'),
                ('can_list', 'AlertHistoryView'),
                ('can_show', 'AlertHistoryView'),
            ]
            
            # Create Alert Admin role
            alert_admin_role = self.appbuilder.sm.add_role('Alert Admin')
            if alert_admin_role:
                for perm_name, view_name in alert_admin_perms:
                    pv = self.appbuilder.sm.find_permission_view_menu(perm_name, view_name)
                    if pv:
                        self.appbuilder.sm.add_permission_role(alert_admin_role, pv)
            
            # Create Alert User role
            alert_user_role = self.appbuilder.sm.add_role('Alert User')
            if alert_user_role:
                for perm_name, view_name in alert_user_perms:
                    pv = self.appbuilder.sm.find_permission_view_menu(perm_name, view_name)
                    if pv:
                        self.appbuilder.sm.add_permission_role(alert_user_role, pv)
            
            log.info("Alerting roles created successfully")
            
        except Exception as e:
            log.error(f"Error creating alerting roles: {e}")
            # Don't raise - roles can be created manually if needed
    
    def pre_process(self):
        """Pre-processing before view registration."""
        super().pre_process()
        
        # Initialize app if not already done
        if not self.alert_manager:
            self.init_app(self.appbuilder.get_app)
    
    def post_process(self):
        """Post-processing after view registration."""
        super().post_process()
        
        # Create permissions and roles
        self.create_permissions()
        self.create_roles()
        
        # Register default metric providers
        self._register_default_metrics()
        
        log.info("Alerting Manager post-processing completed")
    
    def _register_default_metrics(self):
        """Register default system metrics with alert manager."""
        try:
            # Register basic system metrics that work with any PgAppForge app
            
            # User metrics
            def get_total_users():
                try:
                    return self.appbuilder.sm.get_all_users().count()
                except:
                    return 0
            
            def get_active_sessions():
                try:
                    # This would need to be implemented based on session storage
                    return 0  # Placeholder
                except:
                    return 0
            
            # Application metrics  
            def get_total_views():
                try:
                    return len(self.appbuilder.baseviews)
                except:
                    return 0
            
            # Register metrics
            self.alert_manager.register_metric_provider('total_users', get_total_users)
            self.alert_manager.register_metric_provider('active_sessions', get_active_sessions)
            self.alert_manager.register_metric_provider('total_views', get_total_views)
            
            log.info("Default metrics registered with alert manager")
            
        except Exception as e:
            log.warning(f"Error registering default metrics: {e}")
            # Non-critical - metrics can be registered manually