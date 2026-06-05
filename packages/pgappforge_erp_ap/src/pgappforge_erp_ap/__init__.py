"""
pgappforge ERP AP plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-ap

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_ap import APPlugin
    plugin = APPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.finance.ap import APPlugin as _Plugin
from pgappforge.plugins.erp.finance.ap.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.ap.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.ap.events import *  # noqa: F401, F403

# Canonical re-export
APPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["APPlugin", "__version__"]
