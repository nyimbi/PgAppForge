"""
pgappforge ERP Predictive plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-predictive

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_predictive import PredictivePlugin
    plugin = PredictivePlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.analytics.predictive import PredictivePlugin as _Plugin
from pgappforge.plugins.erp.analytics.predictive.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.analytics.predictive.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.analytics.predictive.events import *  # noqa: F401, F403

# Canonical re-export
PredictivePlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["PredictivePlugin", "__version__"]
