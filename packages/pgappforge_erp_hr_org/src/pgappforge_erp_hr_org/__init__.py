"""
pgappforge ERP Org plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-hr-org

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_hr_org import OrgPlugin
    plugin = OrgPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.hcm.org import OrgPlugin as _Plugin
from pgappforge.plugins.erp.hcm.org.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.org.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.org.events import *  # noqa: F401, F403

# Canonical re-export
OrgPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["OrgPlugin", "__version__"]
