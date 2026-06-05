"""
pgappforge ERP GL plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-gl

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_gl import GLPlugin
    plugin = GLPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.finance.gl import GLPlugin as _Plugin
from pgappforge.plugins.erp.finance.gl.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.gl.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.finance.gl.events import *  # noqa: F401, F403

# Canonical re-export
GLPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["GLPlugin", "__version__"]
