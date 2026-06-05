"""
pgappforge ERP Payroll plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-payroll

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_payroll import PayrollPlugin
    plugin = PayrollPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.hcm.payroll import PayrollPlugin as _Plugin
from pgappforge.plugins.erp.hcm.payroll.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.payroll.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.payroll.events import *  # noqa: F401, F403

# Canonical re-export
PayrollPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["PayrollPlugin", "__version__"]
