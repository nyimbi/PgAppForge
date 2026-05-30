"""
PgForge Configuration Package

Configuration classes and utilities for PgForge components.
"""

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
    create_custom_config
)

__all__ = [
    'WizardConfig',
    'WizardUIConfig',
    'WizardBehaviorConfig', 
    'WizardPersistenceConfig',
    'WizardSecurityConfig',
    'WizardIntegrationConfig',
    'WizardAccessibilityConfig',
    'WizardPerformanceConfig',
    'WizardAdvancedConfig',
    'WizardTheme',
    'WizardAnimation', 
    'WizardLayout',
    'WizardValidationMode',
    'WIZARD_CONFIG_PRESETS',
    'get_wizard_config',
    'create_custom_config'
]