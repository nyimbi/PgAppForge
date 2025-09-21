"""
Plugin loader system for dynamic discovery and loading of Flask-AppBuilder plugins.

This module provides secure plugin loading capabilities with validation,
dependency resolution, and proper error handling.
"""

import importlib
import importlib.util
import logging
import os
import sys
from typing import List, Dict, Any, Optional, Type, Set
from pathlib import Path
import pkgutil

from .base_plugin import BasePlugin, PluginMetadata, LegacyManagerAdapter
from .plugin_validator import PluginValidator
from .exceptions import PluginLoadError, PluginValidationError, PluginSecurityError

logger = logging.getLogger(__name__)


class PluginLoader:
    """
    Basic plugin loader for Flask-AppBuilder plugins.

    Provides plugin discovery, loading, and basic validation capabilities.
    """

    def __init__(self, validator: Optional[PluginValidator] = None):
        """
        Initialize the plugin loader.

        Args:
            validator: Plugin validator instance
        """
        self.validator = validator or PluginValidator()
        self._loaded_modules: Dict[str, Any] = {}
        self._plugin_paths: List[Path] = []

    def add_plugin_path(self, path: Path) -> None:
        """
        Add a directory to search for plugins.

        Args:
            path: Directory path to search for plugins
        """
        if path.is_dir():
            self._plugin_paths.append(path)
            logger.info(f"Added plugin path: {path}")
        else:
            logger.warning(f"Plugin path does not exist: {path}")

    def discover_plugins(self, package_name: str = None) -> List[str]:
        """
        Discover available plugins in configured paths.

        Args:
            package_name: Optional package name to search within

        Returns:
            List of discovered plugin module names
        """
        discovered = []

        # Search in configured paths
        for plugin_path in self._plugin_paths:
            discovered.extend(self._discover_in_path(plugin_path))

        # Search in Python packages if specified
        if package_name:
            discovered.extend(self._discover_in_package(package_name))

        return list(set(discovered))  # Remove duplicates

    def load_plugin_from_file(self, file_path: Path) -> Type[BasePlugin]:
        """
        Load a plugin from a specific file.

        Args:
            file_path: Path to plugin file

        Returns:
            Plugin class

        Raises:
            PluginLoadError: If loading fails
        """
        try:
            # Validate file first
            validation_result = self.validator.validate_plugin_file(file_path)

            if not validation_result['valid']:
                raise PluginValidationError(
                    f"Plugin validation failed: {file_path}",
                    validation_result.get('metadata', {}).get('name', 'unknown'),
                    validation_result.get('validation_errors', [])
                )

            # Load the module
            module_name = file_path.stem
            spec = importlib.util.spec_from_file_location(module_name, file_path)

            if not spec or not spec.loader:
                raise PluginLoadError(f"Cannot create module spec for: {file_path}")

            module = importlib.util.module_from_spec(spec)
            self._loaded_modules[module_name] = module

            # Execute module to load classes
            spec.loader.exec_module(module)

            # Find plugin class
            plugin_class = self._find_plugin_class(module)
            if not plugin_class:
                raise PluginLoadError(f"No plugin class found in: {file_path}")

            logger.info(f"Successfully loaded plugin from: {file_path}")
            return plugin_class

        except Exception as e:
            if isinstance(e, (PluginLoadError, PluginValidationError)):
                raise
            raise PluginLoadError(f"Error loading plugin from {file_path}: {e}")

    def load_plugin_from_module(self, module_name: str) -> Type[BasePlugin]:
        """
        Load a plugin from a module name.

        Args:
            module_name: Name of module to load

        Returns:
            Plugin class

        Raises:
            PluginLoadError: If loading fails
        """
        try:
            # Import module
            module = importlib.import_module(module_name)
            self._loaded_modules[module_name] = module

            # Find plugin class
            plugin_class = self._find_plugin_class(module)
            if not plugin_class:
                raise PluginLoadError(f"No plugin class found in module: {module_name}")

            # Validate the class
            try:
                validation_result = self.validator.validate_plugin_class(plugin_class)
                if not validation_result['valid']:
                    raise PluginValidationError(
                        f"Plugin validation failed: {module_name}",
                        validation_result.get('metadata', {}).get('name', module_name),
                        validation_result.get('validation_errors', [])
                    )
            except Exception as e:
                logger.warning(f"Plugin validation failed for {module_name}: {e}")
                # Continue loading but log the warning

            logger.info(f"Successfully loaded plugin from module: {module_name}")
            return plugin_class

        except ImportError as e:
            raise PluginLoadError(f"Cannot import module {module_name}: {e}")
        except Exception as e:
            if isinstance(e, (PluginLoadError, PluginValidationError)):
                raise
            raise PluginLoadError(f"Error loading plugin from module {module_name}: {e}")

    def load_legacy_manager(self, manager_class: Type) -> Type[BasePlugin]:
        """
        Load a legacy BaseManager as a plugin using the adapter.

        Args:
            manager_class: Legacy manager class

        Returns:
            Plugin adapter class
        """
        try:
            # Create adapter class
            class LegacyPluginAdapter(LegacyManagerAdapter):
                def __init__(self, appbuilder, config=None):
                    super().__init__(appbuilder, manager_class, config)

            adapter_name = f"Legacy{manager_class.__name__}Adapter"
            LegacyPluginAdapter.__name__ = adapter_name
            LegacyPluginAdapter.__qualname__ = adapter_name

            logger.info(f"Created legacy adapter for: {manager_class.__name__}")
            return LegacyPluginAdapter

        except Exception as e:
            raise PluginLoadError(f"Error creating legacy adapter for {manager_class.__name__}: {e}")

    def _discover_in_path(self, path: Path) -> List[str]:
        """Discover plugins in a directory path."""
        plugins = []

        try:
            for py_file in path.glob("**/*.py"):
                if py_file.name.startswith("__"):
                    continue

                # Create module name from file path
                relative_path = py_file.relative_to(path)
                module_name = str(relative_path.with_suffix('')).replace(os.sep, '.')
                plugins.append(module_name)

        except Exception as e:
            logger.error(f"Error discovering plugins in {path}: {e}")

        return plugins

    def _discover_in_package(self, package_name: str) -> List[str]:
        """Discover plugins in a Python package."""
        plugins = []

        try:
            package = importlib.import_module(package_name)
            if hasattr(package, '__path__'):
                for _, name, _ in pkgutil.iter_modules(package.__path__, package_name + '.'):
                    plugins.append(name)
        except ImportError as e:
            logger.error(f"Cannot import package {package_name}: {e}")
        except Exception as e:
            logger.error(f"Error discovering plugins in package {package_name}: {e}")

        return plugins

    def _find_plugin_class(self, module) -> Optional[Type[BasePlugin]]:
        """Find plugin class in a loaded module."""
        for name in dir(module):
            obj = getattr(module, name)

            if (isinstance(obj, type) and
                issubclass(obj, BasePlugin) and
                obj != BasePlugin and
                obj != LegacyManagerAdapter):
                return obj

        return None


class SecurePluginLoader(PluginLoader):
    """
    Enhanced plugin loader with additional security checks and sandboxing.

    Provides stricter validation and security measures for production use.
    """

    def __init__(self, strict_security: bool = True, allowed_paths: List[Path] = None):
        """
        Initialize secure plugin loader.

        Args:
            strict_security: Enable strict security validation
            allowed_paths: List of allowed paths for plugin loading
        """
        validator = PluginValidator(security_strict=strict_security)
        super().__init__(validator)

        self.strict_security = strict_security
        self.allowed_paths: Set[Path] = set(allowed_paths or [])
        self._security_violations: List[str] = []

    def add_allowed_path(self, path: Path) -> None:
        """
        Add a path to the allowed paths list.

        Args:
            path: Path to allow for plugin loading
        """
        self.allowed_paths.add(path.resolve())
        self.add_plugin_path(path)

    def load_plugin_from_file(self, file_path: Path) -> Type[BasePlugin]:
        """
        Load plugin with additional security checks.

        Args:
            file_path: Path to plugin file

        Returns:
            Plugin class

        Raises:
            PluginSecurityError: If security validation fails
            PluginLoadError: If loading fails
        """
        # Security check: verify path is allowed
        if self.allowed_paths and not self._is_path_allowed(file_path):
            raise PluginSecurityError(
                f"Plugin path not in allowed paths: {file_path}",
                security_issues=[f"Unauthorized path: {file_path}"]
            )

        # Additional file security checks
        self._validate_file_security(file_path)

        # Use parent class loader with enhanced validation
        return super().load_plugin_from_file(file_path)

    def load_plugin_from_module(self, module_name: str) -> Type[BasePlugin]:
        """
        Load plugin module with security validation.

        Args:
            module_name: Name of module to load

        Returns:
            Plugin class

        Raises:
            PluginSecurityError: If security validation fails
        """
        # Security check: validate module name
        if not self._is_module_name_safe(module_name):
            raise PluginSecurityError(
                f"Unsafe module name: {module_name}",
                security_issues=[f"Dangerous module name pattern: {module_name}"]
            )

        return super().load_plugin_from_module(module_name)

    def get_security_violations(self) -> List[str]:
        """Get list of security violations encountered."""
        return self._security_violations.copy()

    def _is_path_allowed(self, file_path: Path) -> bool:
        """Check if file path is in allowed paths."""
        file_path = file_path.resolve()

        for allowed_path in self.allowed_paths:
            try:
                file_path.relative_to(allowed_path)
                return True
            except ValueError:
                continue

        return False

    def _validate_file_security(self, file_path: Path) -> None:
        """Validate file security properties."""
        # Check file permissions
        if file_path.stat().st_mode & 0o002:  # World writable
            violation = f"World-writable plugin file: {file_path}"
            self._security_violations.append(violation)
            if self.strict_security:
                raise PluginSecurityError(
                    "Plugin file has unsafe permissions",
                    security_issues=[violation]
                )

        # Check file size (prevent huge files)
        max_size = 5 * 1024 * 1024  # 5MB limit
        if file_path.stat().st_size > max_size:
            violation = f"Plugin file too large: {file_path} ({file_path.stat().st_size} bytes)"
            self._security_violations.append(violation)
            raise PluginSecurityError(
                "Plugin file exceeds size limit",
                security_issues=[violation]
            )

    def _is_module_name_safe(self, module_name: str) -> bool:
        """Check if module name is safe to import."""
        # Prevent imports from dangerous locations
        dangerous_prefixes = [
            '__',       # Built-in modules
            'os',       # OS access
            'sys',      # System access
            'subprocess', # Process execution
            'importlib', # Import manipulation
        ]

        for prefix in dangerous_prefixes:
            if module_name.startswith(prefix):
                return False

        # Check for relative imports or path traversal
        if '..' in module_name or '/' in module_name or '\\' in module_name:
            return False

        return True