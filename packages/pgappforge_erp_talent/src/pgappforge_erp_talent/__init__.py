"""
pgappforge ERP Talent plugin.

Standalone PyPI package — install with:
    pip install pgappforge-erp-talent

Auto-discovered by pgappforge via entry points when installed.

Quick start::

    from pgappforge_erp_talent import TalentPlugin
    plugin = TalentPlugin(appbuilder)
    plugin.activate()
"""
from pgappforge.plugins.erp.hcm.talent import TalentPlugin as _Plugin
from pgappforge.plugins.erp.hcm.talent.models import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.talent.services import *  # noqa: F401, F403
from pgappforge.plugins.erp.hcm.talent.events import *  # noqa: F401, F403

# Canonical re-export
TalentPlugin = _Plugin

__version__ = "0.1.0"
__all__ = ["TalentPlugin", "__version__"]
