"""
pgappforge ERP AI plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-ai

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_ai import AIPlugin
    plugin = AIPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.analytics.ai import AIPlugin as _Plugin
from pgappforge.plugins.erp.analytics.ai.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.analytics.ai.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.analytics.ai.events import *  # noqa: F401, F403

# Canonical re-export
AIPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["AIPlugin", "__version__"]
