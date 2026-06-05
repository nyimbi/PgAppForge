"""
pgappforge ERP Tax plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-tax

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_tax import TaxPlugin
    plugin = TaxPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.finance.tax import TaxPlugin as _Plugin
from pgappforge.plugins.erp.finance.tax.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.tax.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.tax.events import *  # noqa: F401, F403

# Canonical re-export
TaxPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["TaxPlugin", "__version__"]
