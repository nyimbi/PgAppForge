"""
pgappforge ERP SCM plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-scm

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_scm import SCMPlugin
    plugin = SCMPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.operations.scm import SCMPlugin as _Plugin
from pgappforge.plugins.erp.operations.scm.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.scm.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.operations.scm.events import *  # noqa: F401, F403

# Canonical re-export
SCMPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["SCMPlugin", "__version__"]
