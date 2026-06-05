"""
pgappforge ERP GRCPrivacy plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-privacy

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_privacy import GRCPrivacyPlugin
    plugin = GRCPrivacyPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.grc.privacy import GRCPrivacyPlugin as _Plugin
from pgappforge.plugins.erp.grc.privacy.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.grc.privacy.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.grc.privacy.events import *  # noqa: F401, F403

# Canonical re-export
GRCPrivacyPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["GRCPrivacyPlugin", "__version__"]
