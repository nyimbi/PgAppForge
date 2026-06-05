"""
pgappforge ERP Health plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-health

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_health import HealthPlugin
    plugin = HealthPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.industry.health import HealthPlugin as _Plugin
from pgappforge.plugins.erp.industry.health.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.industry.health.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.industry.health.events import *  # noqa: F401, F403

# Canonical re-export
HealthPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["HealthPlugin", "__version__"]
