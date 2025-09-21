"""
Exception classes for the Flask-AppBuilder plugin system.

This module defines all exception types used in the enhanced plugin architecture
to provide clear error handling and debugging capabilities.
"""


class PluginError(Exception):
    """Base exception for all plugin-related errors."""

    def __init__(self, message: str, plugin_name: str = None, details: dict = None):
        """
        Initialize plugin error.

        Args:
            message: Error message
            plugin_name: Name of plugin that caused the error
            details: Additional error details
        """
        super().__init__(message)
        self.plugin_name = plugin_name
        self.details = details or {}

    def __str__(self):
        if self.plugin_name:
            return f"Plugin '{self.plugin_name}': {super().__str__()}"
        return super().__str__()


class PluginLoadError(PluginError):
    """Exception raised when a plugin fails to load."""

    def __init__(self, message: str, plugin_name: str = None, cause: Exception = None):
        """
        Initialize plugin load error.

        Args:
            message: Error message
            plugin_name: Name of plugin that failed to load
            cause: Original exception that caused the load failure
        """
        details = {'cause': str(cause)} if cause else {}
        super().__init__(message, plugin_name, details)
        self.cause = cause


class PluginValidationError(PluginError):
    """Exception raised when plugin validation fails."""

    def __init__(self, message: str, plugin_name: str = None, validation_errors: list = None):
        """
        Initialize plugin validation error.

        Args:
            message: Error message
            plugin_name: Name of plugin that failed validation
            validation_errors: List of specific validation errors
        """
        details = {'validation_errors': validation_errors or []}
        super().__init__(message, plugin_name, details)
        self.validation_errors = validation_errors or []


class PluginDependencyError(PluginError):
    """Exception raised when plugin dependencies cannot be resolved."""

    def __init__(self, message: str, plugin_name: str = None, missing_dependencies: list = None):
        """
        Initialize plugin dependency error.

        Args:
            message: Error message
            plugin_name: Name of plugin with dependency issues
            missing_dependencies: List of missing dependency names
        """
        details = {'missing_dependencies': missing_dependencies or []}
        super().__init__(message, plugin_name, details)
        self.missing_dependencies = missing_dependencies or []


class PluginSecurityError(PluginError):
    """Exception raised when plugin security validation fails."""

    def __init__(self, message: str, plugin_name: str = None, security_issues: list = None):
        """
        Initialize plugin security error.

        Args:
            message: Error message
            plugin_name: Name of plugin with security issues
            security_issues: List of specific security issues found
        """
        details = {'security_issues': security_issues or []}
        super().__init__(message, plugin_name, details)
        self.security_issues = security_issues or []


class PluginConfigurationError(PluginError):
    """Exception raised when plugin configuration is invalid."""

    def __init__(self, message: str, plugin_name: str = None, config_errors: dict = None):
        """
        Initialize plugin configuration error.

        Args:
            message: Error message
            plugin_name: Name of plugin with configuration issues
            config_errors: Dictionary of configuration field errors
        """
        details = {'config_errors': config_errors or {}}
        super().__init__(message, plugin_name, details)
        self.config_errors = config_errors or {}


class PluginLifecycleError(PluginError):
    """Exception raised during plugin lifecycle operations."""

    def __init__(self, message: str, plugin_name: str = None, lifecycle_stage: str = None):
        """
        Initialize plugin lifecycle error.

        Args:
            message: Error message
            plugin_name: Name of plugin with lifecycle issues
            lifecycle_stage: Stage where the error occurred (initialize, activate, deactivate, etc.)
        """
        details = {'lifecycle_stage': lifecycle_stage}
        super().__init__(message, plugin_name, details)
        self.lifecycle_stage = lifecycle_stage


class PluginResourceError(PluginError):
    """Exception raised when plugin resource management fails."""

    def __init__(self, message: str, plugin_name: str = None, resource_type: str = None):
        """
        Initialize plugin resource error.

        Args:
            message: Error message
            plugin_name: Name of plugin with resource issues
            resource_type: Type of resource that caused the error
        """
        details = {'resource_type': resource_type}
        super().__init__(message, plugin_name, details)
        self.resource_type = resource_type