"""
pgappforge ERP PlatformIdentity plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-identity

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_identity import PlatformIdentityPlugin
    plugin = PlatformIdentityPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.platform.identity import PlatformIdentityPlugin as _Plugin
from pgappforge.plugins.erp.platform.identity.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.platform.identity.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.platform.identity.events import *  # noqa: F401, F403

# Canonical re-export
PlatformIdentityPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["PlatformIdentityPlugin", "__version__"]
