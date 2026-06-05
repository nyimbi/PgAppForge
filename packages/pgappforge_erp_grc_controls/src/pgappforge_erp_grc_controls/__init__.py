"""
pgappforge ERP GRCControls plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-grc-controls

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_grc_controls import GRCControlsPlugin
    plugin = GRCControlsPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.grc.controls import GRCControlsPlugin as _Plugin
from pgappforge.plugins.erp.grc.controls.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.grc.controls.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.grc.controls.events import *  # noqa: F401, F403

# Canonical re-export
GRCControlsPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["GRCControlsPlugin", "__version__"]
