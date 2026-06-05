"""
pgappforge ERP AR plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-ar

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_ar import ARPlugin
    plugin = ARPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.finance.ar import ARPlugin as _Plugin
from pgappforge.plugins.erp.finance.ar.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.ar.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.ar.events import *  # noqa: F401, F403

# Canonical re-export
ARPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["ARPlugin", "__version__"]
