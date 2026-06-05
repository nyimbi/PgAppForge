"""
pgappforge ERP Marketing plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-marketing

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_marketing import MarketingPlugin
    plugin = MarketingPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.crm.marketing import MarketingPlugin as _Plugin
from pgappforge.plugins.erp.crm.marketing.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.marketing.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.marketing.events import *  # noqa: F401, F403

# Canonical re-export
MarketingPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["MarketingPlugin", "__version__"]
