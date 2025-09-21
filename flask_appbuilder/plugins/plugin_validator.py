"""
Plugin validation and security checking for Flask-AppBuilder plugins.

This module provides comprehensive validation to ensure plugins are secure
and compatible, addressing security concerns from the code review.
"""

import ast
import importlib.util
import inspect
import logging
import re
from typing import List, Dict, Any, Set, Optional, Type
from pathlib import Path

from .base_plugin import BasePlugin, PluginMetadata
from .exceptions import PluginValidationError, PluginSecurityError

logger = logging.getLogger(__name__)


class PluginSecurityCheck:
    """Security validation for plugin code and behavior."""

    # Dangerous imports and functions that should be restricted
    DANGEROUS_IMPORTS = {
        'os', 'subprocess', 'sys', 'importlib', 'pickle', 'marshal',
        'eval', 'exec', 'compile', '__import__', 'globals', 'locals'
    }

    DANGEROUS_FUNCTIONS = {
        'eval', 'exec', 'compile', 'open', 'file', '__import__',
        'getattr', 'setattr', 'delattr', 'globals', 'locals', 'vars'
    }

    RESTRICTED_ATTRIBUTES = {
        '__class__', '__bases__', '__mro__', '__subclasses__',
        '__dict__', '__module__', '__file__', '__code__'
    }

    def __init__(self, strict_mode: bool = False):
        """
        Initialize security checker.

        Args:
            strict_mode: Enable strict security validation
        """
        self.strict_mode = strict_mode
        self.security_issues: List[str] = []

    def validate_plugin_code(self, plugin_class: Type[BasePlugin]) -> List[str]:
        """
        Validate plugin code for security issues.

        Args:
            plugin_class: Plugin class to validate

        Returns:
            List of security issues found
        """
        self.security_issues = []

        try:
            # Get source code
            source = inspect.getsource(plugin_class)

            # Parse AST for analysis
            tree = ast.parse(source)

            # Check for dangerous patterns
            self._check_dangerous_imports(tree)
            self._check_dangerous_functions(tree)
            self._check_attribute_access(tree)
            self._check_string_eval(tree)

            # Check method signatures
            self._check_method_signatures(plugin_class)

        except Exception as e:
            self.security_issues.append(f"Error analyzing plugin code: {e}")

        return self.security_issues

    def _check_dangerous_imports(self, tree: ast.AST) -> None:
        """Check for dangerous import statements."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.DANGEROUS_IMPORTS:
                        if self.strict_mode:
                            self.security_issues.append(f"Dangerous import: {alias.name}")
                        else:
                            logger.warning(f"Potentially dangerous import: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module in self.DANGEROUS_IMPORTS:
                    if self.strict_mode:
                        self.security_issues.append(f"Dangerous import from: {node.module}")
                    else:
                        logger.warning(f"Potentially dangerous import from: {node.module}")

    def _check_dangerous_functions(self, tree: ast.AST) -> None:
        """Check for dangerous function calls."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None

                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name in self.DANGEROUS_FUNCTIONS:
                    self.security_issues.append(f"Dangerous function call: {func_name}")

    def _check_attribute_access(self, tree: ast.AST) -> None:
        """Check for dangerous attribute access."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in self.RESTRICTED_ATTRIBUTES:
                    if self.strict_mode:
                        self.security_issues.append(f"Restricted attribute access: {node.attr}")
                    else:
                        logger.warning(f"Potentially dangerous attribute access: {node.attr}")

    def _check_string_eval(self, tree: ast.AST) -> None:
        """Check for dynamic code execution through strings."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for eval/exec with string literals
                if (isinstance(node.func, ast.Name) and
                    node.func.id in ['eval', 'exec'] and
                    node.args):
                    self.security_issues.append("Dynamic code execution detected")

    def _check_method_signatures(self, plugin_class: Type[BasePlugin]) -> None:
        """Check plugin method signatures for compliance."""
        required_methods = ['metadata', 'initialize']

        for method_name in required_methods:
            if not hasattr(plugin_class, method_name):
                self.security_issues.append(f"Missing required method: {method_name}")
                continue

            method = getattr(plugin_class, method_name)
            if not callable(method):
                self.security_issues.append(f"Required attribute {method_name} is not callable")


class PluginValidator:
    """Comprehensive plugin validation system."""

    def __init__(self, security_strict: bool = False):
        """
        Initialize plugin validator.

        Args:
            security_strict: Enable strict security validation
        """
        self.security_checker = PluginSecurityCheck(security_strict)
        self.validation_errors: List[str] = []

    def validate_plugin_class(self, plugin_class: Type[BasePlugin]) -> Dict[str, Any]:
        """
        Perform comprehensive validation of a plugin class.

        Args:
            plugin_class: Plugin class to validate

        Returns:
            Validation result dictionary

        Raises:
            PluginValidationError: If validation fails
        """
        self.validation_errors = []

        try:
            # Basic class validation
            self._validate_class_structure(plugin_class)

            # Metadata validation
            temp_instance = plugin_class(None)
            metadata = temp_instance.metadata
            self._validate_metadata(metadata)

            # Security validation
            security_issues = self.security_checker.validate_plugin_code(plugin_class)

            # Method validation
            self._validate_methods(plugin_class)

            # Dependency validation
            self._validate_dependencies(metadata)

            # Compile validation results
            is_valid = len(self.validation_errors) == 0 and len(security_issues) == 0

            result = {
                'valid': is_valid,
                'validation_errors': self.validation_errors,
                'security_issues': security_issues,
                'metadata': {
                    'name': metadata.name,
                    'version': metadata.version,
                    'author': metadata.author,
                    'description': metadata.description
                },
                'plugin_info': {
                    'class_name': plugin_class.__name__,
                    'module': plugin_class.__module__,
                    'methods': [name for name, _ in inspect.getmembers(plugin_class, inspect.ismethod)]
                }
            }

            if not is_valid:
                raise PluginValidationError(
                    f"Plugin validation failed: {len(self.validation_errors + security_issues)} issues found",
                    metadata.name,
                    self.validation_errors + security_issues
                )

            return result

        except Exception as e:
            if isinstance(e, PluginValidationError):
                raise
            raise PluginValidationError(f"Validation error: {e}", getattr(plugin_class, '__name__', 'unknown'))

    def _validate_class_structure(self, plugin_class: Type[BasePlugin]) -> None:
        """Validate basic plugin class structure."""
        # Check inheritance
        if not issubclass(plugin_class, BasePlugin):
            self.validation_errors.append("Plugin class must inherit from BasePlugin")

        # Check if class is properly defined
        if not inspect.isclass(plugin_class):
            self.validation_errors.append("Plugin must be a class")

        # Check for abstract methods implementation
        abstract_methods = getattr(plugin_class, '__abstractmethods__', set())
        if abstract_methods:
            self.validation_errors.append(f"Abstract methods not implemented: {abstract_methods}")

    def _validate_metadata(self, metadata: PluginMetadata) -> None:
        """Validate plugin metadata."""
        # Required fields
        required_fields = ['name', 'version', 'description', 'author']
        for field in required_fields:
            value = getattr(metadata, field, None)
            if not value or not value.strip():
                self.validation_errors.append(f"Required metadata field missing or empty: {field}")

        # Name validation
        if metadata.name:
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', metadata.name):
                self.validation_errors.append("Plugin name must start with letter and contain only alphanumeric, underscore, or dash")

        # Version validation (simple semver check)
        if metadata.version:
            if not re.match(r'^\d+\.\d+\.\d+', metadata.version):
                self.validation_errors.append("Version must follow semantic versioning (major.minor.patch)")

    def _validate_methods(self, plugin_class: Type[BasePlugin]) -> None:
        """Validate plugin methods."""
        # Check required methods exist and are callable
        required_methods = {
            'metadata': 'property',
            'initialize': 'method'
        }

        for method_name, method_type in required_methods.items():
            if not hasattr(plugin_class, method_name):
                self.validation_errors.append(f"Missing required {method_type}: {method_name}")
                continue

            attr = getattr(plugin_class, method_name)

            if method_type == 'method' and not callable(attr):
                self.validation_errors.append(f"Required {method_type} {method_name} is not callable")
            elif method_type == 'property' and not isinstance(attr, property):
                self.validation_errors.append(f"Required {method_type} {method_name} is not a property")

    def _validate_dependencies(self, metadata: PluginMetadata) -> None:
        """Validate plugin dependencies."""
        for dep in metadata.dependencies:
            # Check dependency name format
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', dep.name):
                self.validation_errors.append(f"Invalid dependency name format: {dep.name}")

            # Check version format if specified
            if dep.version and not re.match(r'^\d+\.\d+\.\d+', dep.version):
                self.validation_errors.append(f"Invalid dependency version format: {dep.version}")

    def validate_plugin_file(self, file_path: Path) -> Dict[str, Any]:
        """
        Validate a plugin file before loading.

        Args:
            file_path: Path to plugin file

        Returns:
            Validation result dictionary
        """
        try:
            # Basic file checks
            if not file_path.exists():
                raise PluginValidationError(f"Plugin file does not exist: {file_path}")

            if not file_path.suffix == '.py':
                raise PluginValidationError(f"Plugin file must be a Python file: {file_path}")

            # Check file size (prevent huge files)
            max_size = 1024 * 1024  # 1MB limit
            if file_path.stat().st_size > max_size:
                raise PluginValidationError(f"Plugin file too large (>1MB): {file_path}")

            # Load and validate module
            spec = importlib.util.spec_from_file_location("plugin_module", file_path)
            if not spec or not spec.loader:
                raise PluginValidationError(f"Cannot load plugin module: {file_path}")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find plugin classes in module
            plugin_classes = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BasePlugin) and obj != BasePlugin:
                    plugin_classes.append(obj)

            if not plugin_classes:
                raise PluginValidationError(f"No plugin classes found in: {file_path}")

            if len(plugin_classes) > 1:
                raise PluginValidationError(f"Multiple plugin classes found in: {file_path}")

            # Validate the plugin class
            plugin_class = plugin_classes[0]
            return self.validate_plugin_class(plugin_class)

        except Exception as e:
            if isinstance(e, PluginValidationError):
                raise
            raise PluginValidationError(f"Error validating plugin file {file_path}: {e}")

    def validate_plugin_package(self, package_path: Path) -> Dict[str, List[Dict[str, Any]]]:
        """
        Validate an entire plugin package directory.

        Args:
            package_path: Path to plugin package directory

        Returns:
            Dictionary with validation results for all plugins in package
        """
        results = {'valid': [], 'invalid': []}

        if not package_path.is_dir():
            raise PluginValidationError(f"Plugin package path is not a directory: {package_path}")

        # Find all Python files in package
        python_files = list(package_path.glob("**/*.py"))

        for py_file in python_files:
            try:
                result = self.validate_plugin_file(py_file)
                result['file_path'] = str(py_file)
                results['valid'].append(result)
            except PluginValidationError as e:
                results['invalid'].append({
                    'file_path': str(py_file),
                    'error': str(e),
                    'details': e.details
                })

        return results