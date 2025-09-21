"""
Enhanced Plugin Architecture for Flask-AppBuilder

This module implements an enhanced plugin architecture to address scope explosion
by providing proper modularization, isolation, and lifecycle management for features.

Key Improvements:
- Plugin lifecycle management with proper error handling
- Plugin dependency resolution and ordering
- Resource isolation and cleanup
- Security validation for plugin loading
- Plugin metadata and documentation
- Hot-reload capabilities for development
- Plugin marketplace integration

Usage:
    from flask_appbuilder.plugins import PluginManager, BasePlugin

    class MyPlugin(BasePlugin):
        def initialize(self):
            # Plugin initialization logic
            pass

    # Register plugin
    plugin_manager.register_plugin('my_plugin', MyPlugin)
"""

from .base_plugin import BasePlugin, PluginMetadata, PluginDependency
from .plugin_manager import PluginManager, PluginRegistry
from .plugin_loader import PluginLoader, SecurePluginLoader
from .plugin_validator import PluginValidator, PluginSecurityCheck
from .exceptions import (
    PluginError,
    PluginLoadError,
    PluginValidationError,
    PluginDependencyError,
    PluginSecurityError
)

__all__ = [
    # Core plugin classes
    'BasePlugin',
    'PluginManager',
    'PluginRegistry',
    'PluginLoader',
    'SecurePluginLoader',
    'PluginValidator',

    # Metadata and dependencies
    'PluginMetadata',
    'PluginDependency',
    'PluginSecurityCheck',

    # Exceptions
    'PluginError',
    'PluginLoadError',
    'PluginValidationError',
    'PluginDependencyError',
    'PluginSecurityError',
]

# Plugin architecture version for compatibility checking
PLUGIN_API_VERSION = "1.0.0"