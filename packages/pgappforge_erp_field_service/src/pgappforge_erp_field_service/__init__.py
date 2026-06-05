"""
pgappforge ERP FieldService plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-field-service

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_field_service import FieldServicePlugin
    plugin = FieldServicePlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.crm.field_service import FieldServicePlugin as _Plugin
from pgappforge.plugins.erp.crm.field_service.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.field_service.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.field_service.events import *  # noqa: F401, F403

# Canonical re-export
FieldServicePlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["FieldServicePlugin", "__version__"]
