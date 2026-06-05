"""
pgappforge ERP QC plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-quality

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_quality import QCPlugin
    plugin = QCPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.operations.quality import QCPlugin as _Plugin
from pgappforge.plugins.erp.operations.quality.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.quality.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.quality.events import *  # noqa: F401, F403

# Canonical re-export
QCPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["QCPlugin", "__version__"]
