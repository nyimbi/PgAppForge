"""
pgappforge ERP Foundation plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-foundation

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_foundation import FoundationPlugin
    plugin = FoundationPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.foundation import FoundationPlugin as _Plugin
from pgappforge.plugins.erp.foundation.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.foundation.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.foundation.events import *  # noqa: F401, F403

# Canonical re-export
FoundationPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["FoundationPlugin", "__version__"]
