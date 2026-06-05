"""
pgappforge ERP CDP plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-cdp

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_cdp import CDPPlugin
    plugin = CDPPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.analytics.cdp import CDPPlugin as _Plugin
from pgappforge.plugins.erp.analytics.cdp.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.analytics.cdp.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.analytics.cdp.events import *  # noqa: F401, F403

# Canonical re-export
CDPPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["CDPPlugin", "__version__"]
