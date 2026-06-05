"""
pgappforge ERP Inventory plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-inventory

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_inventory import InventoryPlugin
    plugin = InventoryPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.operations.inventory import InventoryPlugin as _Plugin
from pgappforge.plugins.erp.operations.inventory.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.inventory.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.inventory.events import *  # noqa: F401, F403

# Canonical re-export
InventoryPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["InventoryPlugin", "__version__"]
