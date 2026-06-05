"""
pgappforge ERP GRCSustainability plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-sustainability

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_sustainability import GRCSustainabilityPlugin
    plugin = GRCSustainabilityPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.grc.sustainability import GRCSustainabilityPlugin as _Plugin
from pgappforge.plugins.erp.grc.sustainability.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.grc.sustainability.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.grc.sustainability.events import *  # noqa: F401, F403

# Canonical re-export
GRCSustainabilityPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["GRCSustainabilityPlugin", "__version__"]
