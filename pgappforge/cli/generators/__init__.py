"""
PgForge Code Generation Commands

This module provides comprehensive code generation capabilities for PgForge,
including database introspection, model generation, view generation, and complete
application scaffolding.

Commands:
    flask fab gen model    - Generate SQLAlchemy models from database
    flask fab gen view     - Generate beautiful views with modern widgets  
    flask fab gen app      - Generate complete PgForge application
    flask fab gen api      - Generate REST API from database
    flask fab gen all      - Generate everything with all features enabled

Usage:
    flask fab gen --help                    Show all generation commands
    flask fab gen model --help              Show model generation options
    flask fab gen app --database-url ...   Generate complete app from database
"""

from .cli_commands import gen
from .database_inspector import EnhancedDatabaseInspector
from .model_generator import EnhancedModelGenerator
from .view_generator import BeautifulViewGenerator
from .app_generator import FullAppGenerator
from .mobile_generator import MobileGenerator, MobileGenerationConfig
from .desktop_generator import DesktopGenerator, DesktopConfig
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
    "gen",
    "EnhancedDatabaseInspector",
    "EnhancedModelGenerator",
    "BeautifulViewGenerator",
    "FullAppGenerator",
    "MobileGenerator",
    "MobileGenerationConfig",
    "DesktopGenerator",
    "DesktopConfig",
    "MobileGenerationConfig",
    # Pure-Python code templates (3.14-aware)
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