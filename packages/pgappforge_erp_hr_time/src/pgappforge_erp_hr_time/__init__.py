"""
pgappforge ERP Time plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-hr-time

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_hr_time import TimePlugin
    plugin = TimePlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.hcm.time import TimePlugin as _Plugin
from pgappforge.plugins.erp.hcm.time.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.time.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.time.events import *  # noqa: F401, F403

# Canonical re-export
TimePlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["TimePlugin", "__version__"]
