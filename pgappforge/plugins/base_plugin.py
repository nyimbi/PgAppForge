"""
Base plugin class and metadata structures for PgForge plugins.

This module provides the foundation for creating secure, modular plugins
that address the scope explosion issue identified in the code review.
"""

import abc
import logging
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class PluginStatus(Enum):
	"""Plugin lifecycle status enumeration."""
	UNLOADED = "unloaded"
	LOADING = "loading"
	LOADED = "loaded"
	INITIALIZING = "initializing"
	ACTIVE = "active"
	DEACTIVATING = "deactivating"
	FAILED = "failed"
	DISABLED = "disabled"


class PluginPriority(Enum):
	"""Plugin loading priority levels."""
	CRITICAL = 1      # Core functionality (security, authentication)
	HIGH = 2          # Important features (database, API)
	NORMAL = 3        # Standard features (UI components)
	LOW = 4           # Optional features (themes, widgets)


@dataclass
class PluginDependency:
	"""Plugin dependency specification."""
	name: str
	version: Optional[str] = None
	optional: bool = False
	minimum_version: Optional[str] = None
	maximum_version: Optional[str] = None

	def is_satisfied_by(self, version: str) -> bool:
		"""Check if dependency is satisfied by given version."""
		if not self.version and not self.minimum_version and not self.maximum_version:
			return True

		# Simple version comparison (can be enhanced with proper semver)
		if self.version and version != self.version:
			return False

		if self.minimum_version and version < self.minimum_version:
			return False

		if self.maximum_version and version > self.maximum_version:
			return False

		return True


@dataclass
class PluginMetadata:
	"""Plugin metadata for registration and validation."""
	name: str
	version: str
	description: str
	author: str

	# Optional metadata
	author_email: Optional[str] = None
	url: Optional[str] = None
	license: Optional[str] = None
	tags: List[str] = field(default_factory=list)

	# Technical metadata
	api_version: str = "1.0.0"
	priority: PluginPriority = PluginPriority.NORMAL
	dependencies: List[PluginDependency] = field(default_factory=list)

	# Security metadata
	permissions: List[str] = field(default_factory=list)
	safe_mode_compatible: bool = True
	trusted_source: bool = False

	# Documentation
	documentation_url: Optional[str] = None
	example_config: Optional[Dict[str, Any]] = None


class BasePlugin(abc.ABC):
	"""
	Enhanced base class for PgForge plugins.

	This replaces the basic BaseManager with a more robust plugin architecture
	that provides proper lifecycle management, resource isolation, and security.
	"""

	def __init__(self, appbuilder, config: Optional[Dict[str, Any]] = None):
		"""
		Initialize the plugin with AppBuilder instance and configuration.

		Args:
			appbuilder: PgForge instance
			config: Plugin-specific configuration
		"""
		self.appbuilder = appbuilder
		self.config = config or {}
		self.status = PluginStatus.UNLOADED
		self.error_message: Optional[str] = None
		self.load_time: Optional[datetime] = None

		# Resource tracking for cleanup
		self._registered_views: List[Any] = []
		self._registered_blueprints: List[str] = []
		self._registered_menu_items: List[str] = []
		self._background_tasks: List[Any] = []
		self._event_listeners: List[Callable] = []

		# Validate plugin configuration
		self._validate_config()

	@property
	@abc.abstractmethod
	def metadata(self) -> PluginMetadata:
		"""Return plugin metadata."""
		pass

	@abc.abstractmethod
	def initialize(self) -> None:
		"""
		Initialize the plugin.

		This method should contain the main plugin initialization logic,
		including registering views, setting up resources, etc.
		"""
		pass

	def configure(self, config: Dict[str, Any]) -> None:
		"""
		Update plugin configuration.

		Args:
			config: New configuration to merge with existing
		"""
		self.config.update(config)
		self._validate_config()

	def activate(self) -> bool:
		"""
		Activate the plugin through its complete lifecycle.

		Returns:
			True if activation successful, False otherwise
		"""
		try:
			self.status = PluginStatus.LOADING
			self.load_time = datetime.now()

			# Pre-initialization hooks
			self.pre_initialize()

			# Main initialization
			self.status = PluginStatus.INITIALIZING
			self.initialize()

			# Post-initialization hooks
			self.post_initialize()

			# Register with PgForge
			self.register_views()

			# Final activation
			self.status = PluginStatus.ACTIVE
			logger.info(f"Plugin {self.metadata.name} activated successfully")
			return True

		except Exception as e:
			self.status = PluginStatus.FAILED
			self.error_message = str(e)
			logger.error(f"Failed to activate plugin {self.metadata.name}: {e}")
			self.cleanup()
			return False

	def deactivate(self) -> bool:
		"""
		Deactivate the plugin and clean up resources.

		Returns:
			True if deactivation successful, False otherwise
		"""
		try:
			self.status = PluginStatus.DEACTIVATING

			# Plugin-specific cleanup
			self.cleanup()

			# Framework cleanup
			self._cleanup_framework_resources()

			self.status = PluginStatus.UNLOADED
			logger.info(f"Plugin {self.metadata.name} deactivated successfully")
			return True

		except Exception as e:
			logger.error(f"Error deactivating plugin {self.metadata.name}: {e}")
			return False

	def pre_initialize(self) -> None:
		"""Hook called before initialize(). Override for custom logic."""
		pass

	def post_initialize(self) -> None:
		"""Hook called after initialize(). Override for custom logic."""
		pass

	def register_views(self) -> None:
		"""
		Register views with PgForge.

		Override this method to register plugin views. Use the helper methods
		to ensure proper tracking for cleanup.
		"""
		pass

	def cleanup(self) -> None:
		"""
		Plugin-specific cleanup logic.

		Override this method to clean up plugin-specific resources.
		"""
		pass

	def get_status(self) -> Dict[str, Any]:
		"""
		Get plugin status information.

		Returns:
			Dictionary with plugin status details
		"""
		return {
			'name': self.metadata.name,
			'version': self.metadata.version,
			'status': self.status.value,
			'error_message': self.error_message,
			'load_time': self.load_time.isoformat() if self.load_time else None,
			'config': self.config,
			'resources': {
				'views': len(self._registered_views),
				'blueprints': len(self._registered_blueprints),
				'menu_items': len(self._registered_menu_items),
				'background_tasks': len(self._background_tasks)
			}
		}

	# Helper methods for resource tracking

	def add_view(self, view_class, name: str, **kwargs) -> None:
		"""
		Add a view with tracking for cleanup.

		Args:
			view_class: View class to register
			name: View name
			**kwargs: Additional arguments for add_view
		"""
		self.appbuilder.add_view(view_class, name, **kwargs)
		self._registered_views.append((view_class, name))

	def add_view_no_menu(self, view_class, **kwargs) -> None:
		"""Add a view without menu entry, with tracking."""
		self.appbuilder.add_view_no_menu(view_class, **kwargs)
		self._registered_views.append((view_class, None))

	def register_blueprint(self, blueprint, **options) -> None:
		"""Register a blueprint with tracking."""
		self.appbuilder.get_app.register_blueprint(blueprint, **options)
		self._registered_blueprints.append(blueprint.name)

	def add_menu_item(self, name: str, href: str, category: str = None) -> None:
		"""Add a menu item with tracking."""
		# Implementation depends on PgForge's menu system
		# This is a placeholder for the actual implementation
		self._registered_menu_items.append(name)

	def schedule_background_task(self, task: Callable, interval: int = None) -> None:
		"""Schedule a background task with tracking."""
		# Implementation depends on background task system
		# This is a placeholder for the actual implementation
		self._background_tasks.append(task)

	def add_event_listener(self, event: str, callback: Callable) -> None:
		"""Add an event listener with tracking."""
		# Implementation depends on event system
		# This is a placeholder for the actual implementation
		self._event_listeners.append(callback)

	def _validate_config(self) -> None:
		"""Validate plugin configuration."""
		# Override in subclasses for custom validation
		pass

	def _cleanup_framework_resources(self) -> None:
		"""Clean up PgForge resources."""
		# Remove registered views
		for view_info in self._registered_views:
			try:
				# Implementation depends on PgForge's cleanup methods
				# This is a placeholder for the actual implementation
				pass
			except Exception as e:
				logger.warning(f"Error removing view {view_info}: {e}")

		# Remove blueprints
		for blueprint_name in self._registered_blueprints:
			try:
				# Flask blueprints can't be easily removed, but we can track them
				pass
			except Exception as e:
				logger.warning(f"Error removing blueprint {blueprint_name}: {e}")

		# Clear tracking lists
		self._registered_views.clear()
		self._registered_blueprints.clear()
		self._registered_menu_items.clear()
		self._background_tasks.clear()
		self._event_listeners.clear()


class LegacyManagerAdapter(BasePlugin):
	"""
	Adapter to make existing BaseManager classes compatible with new plugin system.

	This allows gradual migration from the old ADDON_MANAGERS system to the new
	plugin architecture without breaking existing addons.
	"""

	def __init__(self, appbuilder, legacy_manager_class, config: Optional[Dict[str, Any]] = None):
		"""
		Initialize adapter with legacy manager class.

		Args:
			appbuilder: PgForge instance
			legacy_manager_class: Legacy BaseManager class
			config: Plugin configuration
		"""
		super().__init__(appbuilder, config)
		self.legacy_manager_class = legacy_manager_class
		self.legacy_instance = None

	@property
	def metadata(self) -> PluginMetadata:
		"""Generate metadata from legacy manager."""
		class_name = self.legacy_manager_class.__name__
		return PluginMetadata(
			name=class_name,
			version="1.0.0",  # Default version for legacy managers
			description=f"Legacy manager adapter for {class_name}",
			author="Unknown",
			tags=["legacy", "adapter"],
			priority=PluginPriority.NORMAL
		)

	def initialize(self) -> None:
		"""Initialize legacy manager through adapter."""
		try:
			# Create legacy manager instance
			self.legacy_instance = self.legacy_manager_class(self.appbuilder)

			# Call legacy lifecycle methods
			if hasattr(self.legacy_instance, 'pre_process'):
				self.legacy_instance.pre_process()

			if hasattr(self.legacy_instance, 'register_views'):
				self.legacy_instance.register_views()

			if hasattr(self.legacy_instance, 'post_process'):
				self.legacy_instance.post_process()

		except Exception as e:
			logger.error(f"Error initializing legacy manager {self.legacy_manager_class.__name__}: {e}")
			raise

	def cleanup(self) -> None:
		"""Clean up legacy manager resources."""
		if self.legacy_instance:
			# Try to call cleanup method if it exists
			if hasattr(self.legacy_instance, 'cleanup'):
				try:
					self.legacy_instance.cleanup()
				except Exception as e:
					logger.warning(f"Error during legacy manager cleanup: {e}")

			self.legacy_instance = None

# ─── Application hook overrides ──────────────────────────────────────────────
# Plugins override these instead of directly connecting to HookRegistry signals.
# The PluginManager calls these automatically when the corresponding hook fires.

	def on_app_ready(self, app) -> None:
		"""Called once after the Flask app is fully configured."""

	def on_user_login(self, user) -> None:
		"""Called after a user successfully authenticates."""

	def on_user_logout(self, user) -> None:
		"""Called when a user logs out."""

	def on_record_save(self, model_class, record, is_new: bool) -> None:
		"""Called after any Model record is created or updated.

		Args:
		    model_class: The SQLAlchemy model class.
		    record: The saved model instance.
		    is_new: True for creates, False for updates.
		"""

	def on_record_delete(self, model_class, record) -> None:
		"""Called before a record is deleted."""

	def on_permission_denied(self, user, permission: str, view_menu: str) -> None:
		"""Called when access is denied. Useful for audit logging."""

	def register_models(self) -> list:
		"""Return a list of SQLAlchemy Model classes this plugin adds.

		These are included in Alembic autogenerate migrations.

		Returns:
		    List of Model subclasses, e.g. [AnalyticsDashboard, AnalyticsWidget]
		"""
		return []

	def get_config_schema(self) -> dict:
		"""Return a JSON Schema dict describing this plugin's config keys.

		Used by the admin UI to render a plugin settings form.
		"""
		return {}
