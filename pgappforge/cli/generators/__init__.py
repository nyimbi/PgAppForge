"""
PgForge Code Generation Commands

Comprehensive code generation for PgForge: database introspection, model/view/API
generation, and complete application scaffolding across Flask, React Native, and
Electron targets.

Commands:
    flask fab gen model    - Generate SQLAlchemy models from database
    flask fab gen view     - Generate beautiful views with modern widgets
    flask fab gen app      - Generate complete PgForge application
    flask fab gen api      - Generate REST API from database
    flask fab gen mobile   - Generate React Native / Expo mobile app
    flask fab gen desktop  - Generate PyWebView/PySide6 desktop wrapper
    flask fab gen all      - Generate everything with all features enabled

Programmatic use::

    from pgappforge.cli.generators import FullAppGenerator, AppGenerationConfig
    from pgappforge.cli.generators import _naming as naming

    cfg = AppGenerationConfig(database_url="postgresql://...", app_name="MyApp")
    gen = FullAppGenerator(cfg)
    gen.write()

    # Naming helpers
    naming.pascal("user_account")  # -> "UserAccount"
    naming.camel("user_account")   # -> "userAccount"
    naming.kebab("user_account")   # -> "user-account"
    naming.snake("UserAccount")    # -> "user_account"
    naming.label("user_account")   # -> "User Account"
"""

from .cli_commands import gen
from .database_inspector import EnhancedDatabaseInspector
from .model_generator import EnhancedModelGenerator, ModelGenerationConfig
from .view_generator import BeautifulViewGenerator, ViewGenerationConfig
from .app_generator import FullAppGenerator, AppGenerationConfig
from .mobile_generator import MobileGenerator, MobileGenerationConfig
from .desktop_generator import DesktopGenerator, DesktopConfig
from ._base import BaseGenerator
from . import _naming
from .code_templates import (
    ColumnSpec,
    RelationshipSpec,
    ViewColumnSet,
    render_model,
    render_model_view,
    render_api,
    render_all,
    MODEL_TEMPLATE,
    VIEW_TEMPLATE,
    API_TEMPLATE,
)

__version__ = "1.0.0"
__author__ = "PgForge Team"

__all__ = [
    # CLI entry-point
    "gen",
    # Database
    "EnhancedDatabaseInspector",
    # Models
    "EnhancedModelGenerator",
    "ModelGenerationConfig",
    # Views
    "BeautifulViewGenerator",
    "ViewGenerationConfig",
    # Full app
    "FullAppGenerator",
    "AppGenerationConfig",
    # Mobile
    "MobileGenerator",
    "MobileGenerationConfig",
    # Desktop
    "DesktopGenerator",
    "DesktopConfig",
    # Base class & naming utilities
    "BaseGenerator",
    "_naming",
    # Pure-Python code templates
    "ColumnSpec",
    "RelationshipSpec",
    "ViewColumnSet",
    "render_model",
    "render_model_view",
    "render_api",
    "render_all",
    "MODEL_TEMPLATE",
    "VIEW_TEMPLATE",
    "API_TEMPLATE",
]