"""
pgappforge ERP Warehouse plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-warehouse

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_warehouse import WarehousePlugin
    plugin = WarehousePlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.operations.warehouse import WarehousePlugin as _Plugin
from pgappforge.plugins.erp.operations.warehouse.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.warehouse.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.warehouse.events import *  # noqa: F401, F403

# Canonical re-export
WarehousePlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["WarehousePlugin", "__version__"]
