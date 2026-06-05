"""
pgappforge ERP Commerce plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-commerce

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_commerce import CommercePlugin
    plugin = CommercePlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.crm.commerce import CommercePlugin as _Plugin
from pgappforge.plugins.erp.crm.commerce.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.commerce.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.crm.commerce.events import *  # noqa: F401, F403

# Canonical re-export
CommercePlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["CommercePlugin", "__version__"]
