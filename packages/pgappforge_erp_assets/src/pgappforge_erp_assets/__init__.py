"""
pgappforge ERP Assets plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-assets

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_assets import AssetsPlugin
    plugin = AssetsPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.finance.assets import AssetsPlugin as _Plugin
from pgappforge.plugins.erp.finance.assets.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.assets.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.assets.events import *  # noqa: F401, F403

# Canonical re-export
AssetsPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["AssetsPlugin", "__version__"]
