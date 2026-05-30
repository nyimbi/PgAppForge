"""
PgAppForge Manager for Export System.

Provides proper integration with PgAppForge's manager lifecycle and
view registration system following FAB patterns.
"""

import logging
from pgappforge.basemanager import BaseManager
from .export_views import ExportView, DataExportView
from .export_manager import ExportManager as CoreExportManager

log = logging.getLogger(__name__)


class ExportManager(BaseManager):
    """
    PgAppForge manager for the export system.
    
    Handles proper lifecycle management, view registration, and integration
    with PgAppForge's data export capabilities.
    """
    
    def __init__(self, appbuilder):
        """Initialize export manager with AppBuilder instance."""
        super().__init__(appbuilder)
        
        # Initialize core export component
        self.core_export_manager = None
    
    def init_app(self, app):
        """Initialize the export system with Flask app."""
        super().init_app(app)
        
        # Initialize core export manager
        self.core_export_manager = CoreExportManager(app)
        
        # Store reference for view access
        app.extensions['export_manager'] = self
        app.extensions['core_export_manager'] = self.core_export_manager
        
        log.info("Export Manager initialized successfully")
    
    def register_views(self):
        """Register export views with PgAppForge."""
        try:
            # Register main export configuration view
            self.appbuilder.add_view(
                ExportView,
                "Data Export",
                icon="fa-download",
                category="Data",
                category_icon="fa-database",
                category_label="Data Management"
            )
            
            # Register data export view (no menu - used by other views)
            self.appbuilder.add_view_no_menu(DataExportView)
            
            log.info("Export views registered successfully")
            
        except Exception as e:
            log.error(f"Error registering export views: {e}")
            raise
    
    def create_permissions(self):
        """Create permissions for export views."""
        try:
            # Define export-specific permissions
            permissions = [
                # Export configuration permissions
                ('can_list', 'ExportView'),
                ('can_show', 'ExportView'),
                ('can_configure', 'ExportView'),
                ('can_download', 'ExportView'),
                
                # API permissions
                ('can_api_formats', 'ExportView'),
                ('can_api_preview', 'ExportView'),
                
                # Data export permissions
                ('can_export_model', 'DataExportView'),
                ('can_export_query', 'DataExportView'),
            ]
            
            # Create permissions using AppBuilder's permission system
            for permission_name, view_name in permissions:
                self.appbuilder.sm.add_permission_view_menu(
                    permission_name, 
                    view_name
                )
            
            log.info("Export permissions created successfully")
            
        except Exception as e:
            log.error(f"Error creating export permissions: {e}")
            # Don't raise - permissions can be created manually if needed
    
    def create_roles(self):
        """Create default roles for export system."""
        try:
            # Define export roles
            export_admin_perms = [
                ('can_list', 'ExportView'),
                ('can_show', 'ExportView'),
                ('can_configure', 'ExportView'),
                ('can_download', 'ExportView'),
                ('can_api_formats', 'ExportView'),
                ('can_api_preview', 'ExportView'),
                ('can_export_model', 'DataExportView'),
                ('can_export_query', 'DataExportView'),
            ]
            
            export_user_perms = [
                ('can_list', 'ExportView'),
                ('can_show', 'ExportView'),
                ('can_configure', 'ExportView'),
                ('can_download', 'ExportView'),
                ('can_api_preview', 'ExportView'),
                ('can_export_model', 'DataExportView'),
            ]
            
            # Create Export Admin role
            export_admin_role = self.appbuilder.sm.add_role('Export Admin')
            if export_admin_role:
                for perm_name, view_name in export_admin_perms:
                    pv = self.appbuilder.sm.find_permission_view_menu(perm_name, view_name)
                    if pv:
                        self.appbuilder.sm.add_permission_role(export_admin_role, pv)
            
            # Create Export User role
            export_user_role = self.appbuilder.sm.add_role('Export User')
            if export_user_role:
                for perm_name, view_name in export_user_perms:
                    pv = self.appbuilder.sm.find_permission_view_menu(perm_name, view_name)
                    if pv:
                        self.appbuilder.sm.add_permission_role(export_user_role, pv)
            
            log.info("Export roles created successfully")
            
        except Exception as e:
            log.error(f"Error creating export roles: {e}")
            # Don't raise - roles can be created manually if needed
    
    def pre_process(self):
        """Pre-processing before view registration."""
        super().pre_process()
        
        # Initialize app if not already done
        if not self.core_export_manager:
            self.init_app(self.appbuilder.get_app)
    
    def post_process(self):
        """Post-processing after view registration."""
        super().post_process()
        
        # Create permissions and roles
        self.create_permissions()
        self.create_roles()
        
        log.info("Export Manager post-processing completed")
    
    def add_model_export_capability(self, modelview_class):
        """
        Add export capabilities to an existing ModelView.
        
        Args:
            modelview_class: ModelView class to enhance with export functionality
        """
        try:
            # Add export button to ModelView actions
            if hasattr(modelview_class, 'base_actions'):
                modelview_class.base_actions = getattr(modelview_class, 'base_actions', [])
                
                # Add export action
                export_action = {
                    'name': 'export_data',
                    'text': 'Export Data',
                    'confirmation': None,
                    'icon': 'fa-download',
                    'multiple': True,
                    'single': False
                }
                
                if export_action not in modelview_class.base_actions:
                    modelview_class.base_actions.append(export_action)
            
            log.info(f"Added export capability to {modelview_class.__name__}")
            
        except Exception as e:
            log.warning(f"Could not add export capability to {modelview_class.__name__}: {e}")
    
    def get_available_formats(self):
        """Get list of available export formats."""
        if self.core_export_manager:
            return self.core_export_manager.get_supported_formats()
        return ['csv']  # Fallback to basic CSV
    
    def export_modelview_data(self, modelview, format_type='csv', **options):
        """
        Export data from a ModelView.
        
        Args:
            modelview: ModelView instance
            format_type: Export format (csv, xlsx, pdf)
            **options: Additional export options
            
        Returns:
            Export result
        """
        try:
            if not self.core_export_manager:
                raise RuntimeError("Core export manager not initialized")
            
            # Get data from ModelView's datamodel
            query = modelview.datamodel.get_query()
            data = []
            
            # Convert query results to dictionaries
            for item in query.all():
                item_dict = {}
                for column in modelview.datamodel.obj.__table__.columns:
                    value = getattr(item, column.name, None)
                    item_dict[column.name] = value
                data.append(item_dict)
            
            # Export using core manager
            from .export_manager import ExportFormat
            export_format = ExportFormat(format_type)
            
            return self.core_export_manager.export_data(
                data=data,
                format_type=export_format,
                metadata={
                    'model_name': modelview.datamodel.obj.__name__,
                    'exported_by': 'ModelView Export',
                    'total_records': len(data)
                },
                options=options
            )
            
        except Exception as e:
            log.error(f"Error exporting ModelView data: {e}")
            raise