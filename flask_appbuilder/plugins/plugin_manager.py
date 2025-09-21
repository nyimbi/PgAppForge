"""
Plugin manager for orchestrating plugin lifecycle and dependencies.

This module implements the core plugin management functionality that addresses
scope explosion by providing proper modularization and isolation.
"""

import logging
from typing import Dict, List, Optional, Set, Any, Type, Tuple
from collections import defaultdict, deque
import threading
from contextlib import contextmanager

from .base_plugin import BasePlugin, PluginMetadata, PluginStatus, PluginPriority
from .exceptions import PluginError, PluginDependencyError, PluginLoadError
from ..exceptions import FABSecurityError, FABConfigurationError, ErrorContext

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Registry for managing plugin metadata and instances.

    Provides centralized plugin discovery, registration, and status tracking.
    """

    def __init__(self):
        """Initialize the plugin registry."""
        self._plugins: Dict[str, BasePlugin] = {}
        self._metadata: Dict[str, PluginMetadata] = {}
        self._plugin_classes: Dict[str, Type[BasePlugin]] = {}
        self._lock = threading.RLock()

    def register_plugin_class(self, plugin_class: Type[BasePlugin]) -> None:
        """
        Register a plugin class for later instantiation.

        Args:
            plugin_class: Plugin class to register
        """
        with self._lock:
            # Get metadata from the class
            temp_instance = plugin_class(None)  # Temporary instance for metadata
            metadata = temp_instance.metadata

            self._plugin_classes[metadata.name] = plugin_class
            self._metadata[metadata.name] = metadata

            logger.info(f"Registered plugin class: {metadata.name} v{metadata.version}")

    def register_plugin_instance(self, plugin: BasePlugin) -> None:
        """
        Register an active plugin instance.

        Args:
            plugin: Plugin instance to register
        """
        with self._lock:
            name = plugin.metadata.name
            self._plugins[name] = plugin
            self._metadata[name] = plugin.metadata

            logger.info(f"Registered plugin instance: {name}")

    def unregister_plugin(self, name: str) -> None:
        """
        Unregister a plugin.

        Args:
            name: Plugin name to unregister
        """
        with self._lock:
            self._plugins.pop(name, None)
            self._metadata.pop(name, None)
            self._plugin_classes.pop(name, None)

            logger.info(f"Unregistered plugin: {name}")

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get plugin instance by name."""
        return self._plugins.get(name)

    def get_metadata(self, name: str) -> Optional[PluginMetadata]:
        """Get plugin metadata by name."""
        return self._metadata.get(name)

    def get_plugin_class(self, name: str) -> Optional[Type[BasePlugin]]:
        """Get plugin class by name."""
        return self._plugin_classes.get(name)

    def list_plugins(self) -> List[str]:
        """List all registered plugin names."""
        return list(self._metadata.keys())

    def list_active_plugins(self) -> List[str]:
        """List names of active plugin instances."""
        return list(self._plugins.keys())

    def get_status_summary(self) -> Dict[str, Any]:
        """Get summary of plugin registry status."""
        with self._lock:
            status_counts = defaultdict(int)
            for plugin in self._plugins.values():
                status_counts[plugin.status.value] += 1

            return {
                'total_registered': len(self._metadata),
                'active_instances': len(self._plugins),
                'status_counts': dict(status_counts),
                'plugin_list': [
                    {
                        'name': name,
                        'version': metadata.version,
                        'status': self._plugins.get(name, {}).status.value if name in self._plugins else 'unloaded',
                        'priority': metadata.priority.value
                    }
                    for name, metadata in self._metadata.items()
                ]
            }


class PluginManager:
    """
    Enhanced plugin manager for Flask-AppBuilder.

    Provides comprehensive plugin lifecycle management, dependency resolution,
    and resource isolation to address scope explosion issues.
    """

    def __init__(self, appbuilder):
        """
        Initialize the plugin manager.

        Args:
            appbuilder: Flask-AppBuilder instance
        """
        self.appbuilder = appbuilder
        self.registry = PluginRegistry()
        self._dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self._reverse_dependencies: Dict[str, Set[str]] = defaultdict(set)
        self._load_order: List[str] = []
        self._lock = threading.RLock()

    def register_plugin_class(self, plugin_class: Type[BasePlugin]) -> None:
        """
        Register a plugin class.

        Args:
            plugin_class: Plugin class to register
        """
        self.registry.register_plugin_class(plugin_class)
        self._update_dependency_graph()

    def load_plugin(self, name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Load and activate a plugin.

        Args:
            name: Plugin name to load
            config: Plugin configuration

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            # Check if already loaded
            if self.registry.get_plugin(name):
                logger.warning(f"Plugin {name} is already loaded")
                return True

            # Get plugin class
            plugin_class = self.registry.get_plugin_class(name)
            if not plugin_class:
                logger.error(f"Plugin class not found: {name}")
                return False

            try:
                # Create and configure plugin instance
                plugin = plugin_class(self.appbuilder, config)

                # Validate dependencies
                if not self._validate_dependencies(plugin):
                    return False

                # Activate plugin
                if plugin.activate():
                    self.registry.register_plugin_instance(plugin)
                    logger.info(f"Successfully loaded plugin: {name}")
                    return True
                else:
                    logger.error(f"Failed to activate plugin: {name}")
                    return False

            except Exception as e:
                # Use standardized error handling with context
                context = ErrorContext(
                    operation="plugin_loading",
                    additional_data={"plugin_name": name}
                )

                # Log as security event if it's a security-related plugin error
                if any(term in str(e).lower() for term in ['security', 'permission', 'access']):
                    logger.error(f"Security-related plugin loading error for {name}: {e}")
                    # Note: Not raising here to maintain existing behavior, just enhanced logging
                else:
                    logger.error(f"Error loading plugin {name}: {e}")

                return False

    def unload_plugin(self, name: str) -> bool:
        """
        Unload and deactivate a plugin.

        Args:
            name: Plugin name to unload

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            plugin = self.registry.get_plugin(name)
            if not plugin:
                logger.warning(f"Plugin {name} is not loaded")
                return True

            try:
                # Check for reverse dependencies
                dependents = self._reverse_dependencies.get(name, set())
                active_dependents = [
                    dep for dep in dependents
                    if self.registry.get_plugin(dep)
                ]

                if active_dependents:
                    logger.error(f"Cannot unload {name}: required by {active_dependents}")
                    return False

                # Deactivate plugin
                if plugin.deactivate():
                    self.registry.unregister_plugin(name)
                    logger.info(f"Successfully unloaded plugin: {name}")
                    return True
                else:
                    logger.error(f"Failed to deactivate plugin: {name}")
                    return False

            except Exception as e:
                logger.error(f"Error unloading plugin {name}: {e}")
                return False

    def load_plugins_batch(self, plugin_configs: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
        """
        Load multiple plugins in dependency order.

        Args:
            plugin_configs: Dictionary mapping plugin names to their configurations

        Returns:
            Dictionary mapping plugin names to load success status
        """
        results = {}

        # Calculate load order based on dependencies
        load_order = self._calculate_load_order(list(plugin_configs.keys()))

        for plugin_name in load_order:
            if plugin_name in plugin_configs:
                config = plugin_configs[plugin_name]
                results[plugin_name] = self.load_plugin(plugin_name, config)
            else:
                # Plugin needed as dependency but not in requested list
                results[plugin_name] = self.load_plugin(plugin_name)

        return results

    def reload_plugin(self, name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Reload a plugin (unload then load).

        Args:
            name: Plugin name to reload
            config: New plugin configuration

        Returns:
            True if successful, False otherwise
        """
        # Store current config if none provided
        current_plugin = self.registry.get_plugin(name)
        if not config and current_plugin:
            config = current_plugin.config

        # Unload then load
        if self.unload_plugin(name):
            return self.load_plugin(name, config)
        return False

    def get_plugin_status(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed status of a plugin.

        Args:
            name: Plugin name

        Returns:
            Plugin status dictionary or None if not found
        """
        plugin = self.registry.get_plugin(name)
        if plugin:
            return plugin.get_status()

        # Check if plugin is registered but not loaded
        metadata = self.registry.get_metadata(name)
        if metadata:
            return {
                'name': name,
                'version': metadata.version,
                'status': PluginStatus.UNLOADED.value,
                'error_message': None,
                'load_time': None,
                'config': {},
                'resources': {
                    'views': 0,
                    'blueprints': 0,
                    'menu_items': 0,
                    'background_tasks': 0
                }
            }

        return None

    def list_plugins(self) -> List[Dict[str, Any]]:
        """
        List all plugins with their status.

        Returns:
            List of plugin status dictionaries
        """
        plugins = []
        for name in self.registry.list_plugins():
            status = self.get_plugin_status(name)
            if status:
                plugins.append(status)
        return plugins

    def get_dependency_info(self, name: str) -> Dict[str, Any]:
        """
        Get dependency information for a plugin.

        Args:
            name: Plugin name

        Returns:
            Dependency information dictionary
        """
        metadata = self.registry.get_metadata(name)
        if not metadata:
            return {}

        return {
            'name': name,
            'dependencies': [
                {
                    'name': dep.name,
                    'version': dep.version,
                    'optional': dep.optional,
                    'satisfied': self._is_dependency_satisfied(dep)
                }
                for dep in metadata.dependencies
            ],
            'dependents': list(self._reverse_dependencies.get(name, [])),
            'load_order_index': self._load_order.index(name) if name in self._load_order else -1
        }

    @contextmanager
    def plugin_isolation(self, name: str):
        """
        Context manager for plugin resource isolation.

        Args:
            name: Plugin name for isolation context
        """
        plugin = self.registry.get_plugin(name)
        if not plugin:
            raise PluginError(f"Plugin {name} not found")

        # Setup isolation
        original_status = plugin.status
        try:
            yield plugin
        except Exception as e:
            # Handle plugin errors
            plugin.status = PluginStatus.FAILED
            plugin.error_message = str(e)
            logger.error(f"Error in plugin {name}: {e}")
            raise
        finally:
            # Cleanup if needed
            if plugin.status == PluginStatus.FAILED:
                try:
                    plugin.cleanup()
                except Exception as cleanup_error:
                    logger.error(f"Error during plugin cleanup {name}: {cleanup_error}")

    def _update_dependency_graph(self) -> None:
        """Update dependency graph from registered plugins."""
        self._dependency_graph.clear()
        self._reverse_dependencies.clear()

        for name in self.registry.list_plugins():
            metadata = self.registry.get_metadata(name)
            if metadata:
                for dep in metadata.dependencies:
                    if not dep.optional:  # Only consider required dependencies
                        self._dependency_graph[name].add(dep.name)
                        self._reverse_dependencies[dep.name].add(name)

        # Update load order
        self._load_order = self._calculate_load_order(self.registry.list_plugins())

    def _validate_dependencies(self, plugin: BasePlugin) -> bool:
        """
        Validate that plugin dependencies are satisfied.

        Args:
            plugin: Plugin to validate

        Returns:
            True if dependencies are satisfied, False otherwise
        """
        for dep in plugin.metadata.dependencies:
            if not self._is_dependency_satisfied(dep):
                if not dep.optional:
                    logger.error(f"Required dependency not satisfied: {dep.name}")
                    return False
                else:
                    logger.warning(f"Optional dependency not satisfied: {dep.name}")

        return True

    def _is_dependency_satisfied(self, dependency) -> bool:
        """Check if a dependency is satisfied."""
        dep_plugin = self.registry.get_plugin(dependency.name)
        if not dep_plugin:
            return False

        dep_metadata = dep_plugin.metadata
        return dependency.is_satisfied_by(dep_metadata.version)

    def _calculate_load_order(self, plugin_names: List[str]) -> List[str]:
        """
        Calculate plugin load order based on dependencies using topological sort.

        Args:
            plugin_names: List of plugin names to order

        Returns:
            Ordered list of plugin names
        """
        # Build graph for topological sort
        in_degree = defaultdict(int)
        graph = defaultdict(list)

        # Initialize all plugins with 0 in-degree
        for name in plugin_names:
            in_degree[name] = 0

        # Build dependency edges
        for name in plugin_names:
            metadata = self.registry.get_metadata(name)
            if metadata:
                for dep in metadata.dependencies:
                    if not dep.optional and dep.name in plugin_names:
                        graph[dep.name].append(name)
                        in_degree[name] += 1

        # Topological sort with priority consideration
        queue = deque()
        result = []

        # Sort by priority first (critical plugins first)
        priority_order = sorted(
            plugin_names,
            key=lambda name: (
                in_degree[name],  # Dependencies first
                self.registry.get_metadata(name).priority.value if self.registry.get_metadata(name) else 999
            )
        )

        # Add nodes with no dependencies
        for name in priority_order:
            if in_degree[name] == 0:
                queue.append(name)

        while queue:
            current = queue.popleft()
            result.append(current)

            # Process dependent plugins
            for dependent in graph[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # Check for circular dependencies
        if len(result) != len(plugin_names):
            remaining = set(plugin_names) - set(result)
            raise PluginDependencyError(f"Circular dependency detected among: {remaining}")

        return result