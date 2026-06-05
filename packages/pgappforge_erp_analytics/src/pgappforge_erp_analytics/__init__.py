"""
pgappforge ERP Operational plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-analytics

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_analytics import OperationalPlugin
    plugin = OperationalPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.analytics.operational import OperationalPlugin as _Plugin
from pgappforge.plugins.erp.analytics.operational.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.analytics.operational.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.analytics.operational.events import *  # noqa: F401, F403

# Canonical re-export
OperationalPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["OperationalPlugin", "__version__"]
