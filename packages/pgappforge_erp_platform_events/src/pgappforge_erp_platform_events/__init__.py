"""
pgappforge ERP PlatformEvents plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-platform-events

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_platform_events import PlatformEventsPlugin
    plugin = PlatformEventsPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.platform.events import PlatformEventsPlugin as _Plugin
from pgappforge.plugins.erp.platform.events.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.platform.events.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.platform.events.events import *  # noqa: F401, F403

# Canonical re-export
PlatformEventsPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["PlatformEventsPlugin", "__version__"]
