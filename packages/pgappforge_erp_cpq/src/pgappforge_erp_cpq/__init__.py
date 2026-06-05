"""
pgappforge ERP CPQ plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-cpq

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_cpq import CPQPlugin
    plugin = CPQPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.crm.cpq import CPQPlugin as _Plugin
from pgappforge.plugins.erp.crm.cpq.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.cpq.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.cpq.events import *  # noqa: F401, F403

# Canonical re-export
CPQPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["CPQPlugin", "__version__"]
