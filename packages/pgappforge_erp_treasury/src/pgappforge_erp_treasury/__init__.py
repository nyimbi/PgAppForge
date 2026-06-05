"""
pgappforge ERP Treasury plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-treasury

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_treasury import TreasuryPlugin
    plugin = TreasuryPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.finance.treasury import TreasuryPlugin as _Plugin
from pgappforge.plugins.erp.finance.treasury.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.treasury.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.treasury.events import *  # noqa: F401, F403

# Canonical re-export
TreasuryPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["TreasuryPlugin", "__version__"]
