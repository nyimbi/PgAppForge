"""
PgForge Configuration Package

Runtime application config (database-backed key/value store) and wizard
form configuration (pure-Python dataclasses).

Runtime config usage::

    from pgappforge.config import AppConfig, AppConfigManager, AppConfigView

    mgr = AppConfigManager(db.session)
    mgr.set("APP_TITLE", "Acme Portal", category="appearance")
    title = mgr.get("APP_TITLE", default="Untitled")
"""

from .models import AppConfig, AppConfigManager, BUILT_IN_DEFAULTS
from .views import AppConfigView
from .wizard import (
	WizardConfig,
	WizardUIConfig,
	WizardBehaviorConfig,
	WizardPersistenceConfig,
	WizardSecurityConfig,
	WizardIntegrationConfig,
	WizardAccessibilityConfig,
	WizardPerformanceConfig,
	WizardAdvancedConfig,
	WizardTheme,
	WizardAnimation,
	WizardLayout,
	WizardValidationMode,
	WIZARD_CONFIG_PRESETS,
	get_wizard_config,
	create_custom_config,
)

__all__ = [
	# Runtime app config
	"AppConfig",
	"AppConfigManager",
	"AppConfigView",
	"BUILT_IN_DEFAULTS",
	# Wizard config (pure-Python, no DB)
	"WizardConfig",
	"WizardUIConfig",
	"WizardBehaviorConfig",
	"WizardPersistenceConfig",
	"WizardSecurityConfig",
	"WizardIntegrationConfig",
	"WizardAccessibilityConfig",
	"WizardPerformanceConfig",
	"WizardAdvancedConfig",
	"WizardTheme",
	"WizardAnimation",
	"WizardLayout",
	"WizardValidationMode",
	"WIZARD_CONFIG_PRESETS",
	"get_wizard_config",
	"create_custom_config",
]
