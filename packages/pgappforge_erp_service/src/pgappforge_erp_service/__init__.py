"""
pgappforge ERP Service plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-service

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_service import ServicePlugin
    plugin = ServicePlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.crm.service import ServicePlugin as _Plugin
from pgappforge.plugins.erp.crm.service.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.service.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.service.events import *  # noqa: F401, F403

# Canonical re-export
ServicePlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["ServicePlugin", "__version__"]
