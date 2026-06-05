"""
pgappforge ERP FinancialServices plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-finserv

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_finserv import FinancialServicesPlugin
    plugin = FinancialServicesPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.industry.financial_services import FinancialServicesPlugin as _Plugin
from pgappforge.plugins.erp.industry.financial_services.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.industry.financial_services.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.industry.financial_services.events import *  # noqa: F401, F403

# Canonical re-export
FinancialServicesPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["FinancialServicesPlugin", "__version__"]
