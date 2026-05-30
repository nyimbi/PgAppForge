"""
PgAppForge Views Package

Enhanced view functionality including wizard form views.
This module provides both original PgAppForge views and wizard views.
"""

# Import original views from the parent directory's views.py
import importlib.util
import os.path
import sys

# Load views from the parent directory's views.py
parent_dir = os.path.dirname(os.path.dirname(__file__))
views_file = os.path.join(parent_dir, 'views.py')

if os.path.exists(views_file):
    spec = importlib.util.spec_from_file_location("fab_views", views_file)
    fab_views = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fab_views)
    
    # Import the required classes
    IndexView = fab_views.IndexView
    UtilView = fab_views.UtilView
    ModelView = fab_views.ModelView
    MasterDetailView = fab_views.MasterDetailView
    MultipleView = fab_views.MultipleView
    CompactCRUDMixin = fab_views.CompactCRUDMixin
    BaseFormView = fab_views.BaseFormView
    SimpleFormView = fab_views.SimpleFormView
    PublicFormView = fab_views.PublicFormView
    BaseView = fab_views.BaseView
    RestCRUDView = fab_views.RestCRUDView
else:
    # Fallback - import from baseviews
    from pgappforge.baseviews import BaseView
    # Create dummy classes for missing views
    class IndexView(BaseView):
        route_base = ""
        default_view = "index"
        
    class UtilView(BaseView):
        pass
        
    # Set others to BaseView as fallback
    ModelView = BaseView
    MasterDetailView = BaseView  
    MultipleView = BaseView
    CompactCRUDMixin = object
    BaseFormView = BaseView
    SimpleFormView = BaseView
    PublicFormView = BaseView
    RestCRUDView = BaseView

# Import essential decorators and functions that other modules need
from pgappforge.baseviews import expose, expose_api
from pgappforge.security.decorators import has_access

# Import enhanced views only if dependencies are available
try:
    from .wizard import WizardFormView, WizardModelView, WizardFormWidget, WizardFormMixin
    wizard_imports_available = True
except ImportError:
    wizard_imports_available = False

try:
    from .wizard_builder import (
        WizardBuilderView,
        WizardTemplateGalleryView,
        WizardPreviewView,
        WizardManagementView,
        WizardBuilderAPIView
    )
    builder_imports_available = True
except ImportError:
    builder_imports_available = False

try:
    from .wizard_migration import (
        WizardMigrationView,
        WizardExportView,
        WizardImportView,
        WizardBackupView,
        WizardMigrationAPIView
    )
    migration_imports_available = True
except ImportError:
    migration_imports_available = False

try:
    from .dashboard import (
        DashboardIndexView,
        DashboardAPIView
    )
    dashboard_imports_available = True
except ImportError:
    dashboard_imports_available = False

# Define exports based on what's available
__all__ = [
    # Core PgAppForge views
    'IndexView',
    'UtilView', 
    'ModelView',
    'MasterDetailView',
    'MultipleView',
    'CompactCRUDMixin',
    'BaseFormView',
    'SimpleFormView',
    'PublicFormView',
    'BaseView',
    'RestCRUDView',
    
    # Essential decorators and functions
    'expose',
    'expose_api', 
    'has_access',
]

# Add enhanced views if available
if wizard_imports_available:
    __all__.extend([
        'WizardFormView',
        'WizardModelView',
        'WizardFormWidget', 
        'WizardFormMixin',
    ])

if builder_imports_available:
    __all__.extend([
        'WizardBuilderView',
        'WizardTemplateGalleryView',
        'WizardPreviewView',
        'WizardManagementView',
        'WizardBuilderAPIView',
    ])

if migration_imports_available:
    __all__.extend([
        'WizardMigrationView',
        'WizardExportView',
        'WizardImportView',
        'WizardBackupView',
        'WizardMigrationAPIView',
    ])

if dashboard_imports_available:
    __all__.extend([
        'DashboardIndexView',
        'DashboardAPIView',
    ])
