__author__ = "Daniel Vaz Gaspar"
__version__ = "5.2.1.dev3"

from .actions import action  # noqa: F401
from .api import ModelRestApi  # noqa: F401
from .base import AppBuilder  # noqa: F401
from .baseviews import BaseView, expose  # noqa: F401
from .charts.views import DirectByChartView, GroupByChartView  # noqa: F401
from .models.group import aggregate_avg, aggregate_count, aggregate_sum  # noqa: F401
from .models.sqla import Base, Model, SQLA  # noqa: F401
from .security.decorators import has_access, permission_name  # noqa: F401

# Import original views first
from .views import (  # noqa: F401
    CompactCRUDMixin,
    MasterDetailView,
    ModelView,
    MultipleView,
    PublicFormView,
    RestCRUDView,
    SimpleFormView,
)  # noqa: F401

# Import enhanced components
try:
    from .enhanced_index_view import IndexView  # Enhanced beautiful dashboard
    
    # Also make enhanced wizard views available
    from .views.dashboard import DashboardIndexView, DashboardAPIView
    from .views.wizard import WizardFormView, WizardModelView
    from .views.wizard_builder import (
        WizardBuilderView,
        WizardTemplateGalleryView,
        WizardPreviewView,
        WizardManagementView
    )
    from .views.wizard_migration import (
        WizardMigrationView,
        WizardExportView,
        WizardImportView,
        WizardBackupView
    )
    
    # Export enhanced views for easy access
    __all__ = [
        # Core PgForge
        'AppBuilder', 'BaseView', 'ModelView', 'expose', 'action',
        'has_access', 'permission_name', 'ModelRestApi',
        'CompactCRUDMixin', 'MasterDetailView', 'MultipleView',
        'PublicFormView', 'RestCRUDView', 'SimpleFormView',
        
        # Enhanced Views
        'IndexView',  # Beautiful dashboard
        'DashboardIndexView', 'DashboardAPIView',
        'WizardFormView', 'WizardModelView',
        'WizardBuilderView', 'WizardTemplateGalleryView', 
        'WizardPreviewView', 'WizardManagementView',
        'WizardMigrationView', 'WizardExportView',
        'WizardImportView', 'WizardBackupView',
    ]
    
except ImportError:
    # Fallback to original IndexView if enhanced views not available
    from .views import IndexView  # noqa: F401
    
    __all__ = [
        'AppBuilder', 'BaseView', 'ModelView', 'IndexView', 'expose', 'action',
        'has_access', 'permission_name', 'ModelRestApi',
        'CompactCRUDMixin', 'MasterDetailView', 'MultipleView',
        'PublicFormView', 'RestCRUDView', 'SimpleFormView',
    ]
