"""
pgappforge ERP Sales plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-sales

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_sales import SalesPlugin
    plugin = SalesPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.crm.sales import SalesPlugin as _Plugin
from pgappforge.plugins.erp.crm.sales.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.sales.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.sales.events import *  # noqa: F401, F403

# Canonical re-export
SalesPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["SalesPlugin", "__version__"]
