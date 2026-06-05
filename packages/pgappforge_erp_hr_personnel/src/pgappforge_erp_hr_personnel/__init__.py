"""
pgappforge ERP Personnel plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-hr-personnel

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_hr_personnel import PersonnelPlugin
    plugin = PersonnelPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.hcm.personnel import PersonnelPlugin as _Plugin
from pgappforge.plugins.erp.hcm.personnel.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.personnel.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.personnel.events import *  # noqa: F401, F403

# Canonical re-export
PersonnelPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["PersonnelPlugin", "__version__"]
