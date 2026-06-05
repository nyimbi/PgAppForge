"""
pgappforge ERP PP plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-production

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_production import PPPlugin
    plugin = PPPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.operations.production import PPPlugin as _Plugin
from pgappforge.plugins.erp.operations.production.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.production.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.production.events import *  # noqa: F401, F403

# Canonical re-export
PPPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["PPPlugin", "__version__"]
