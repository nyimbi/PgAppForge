"""
PgAppForge addon manager for collaborative features.

Integrates the collaborative service registry with PgAppForge's addon system,
providing proper lifecycle management and configuration integration.
"""

import logging
import re
from typing import Dict, Any, Optional, List, Type, Set
from flask import Flask

from ..basemanager import BaseManager
from .interfaces.service_registry import ServiceRegistry
from .interfaces.service_factory import ServiceFactory, ServiceLifecycleManager
from .interfaces.base_interfaces import (
    ICollaborationService,
    ITeamService,
    IWorkspaceService,
    ICommunicationService,
    IWebSocketService,
)


logger = logging.getLogger(__name__)


class CollaborativeAddonManager(BaseManager):
    """
    PgAppForge addon manager for collaborative features.

    Manages the lifecycle of collaborative services within the PgAppForge
    framework, providing proper integration with the app factory pattern and
    configuration management.
    """

    def __init__(self, appbuilder):
        """
        Initialize the collaborative addon manager.

        Args:
            appbuilder: PgAppForge instance
        """
        super().__init__(appbuilder)
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

        # Service management
        self.service_registry: Optional[ServiceRegistry] = None
        self.lifecycle_manager: Optional[ServiceLifecycleManager] = None

        # Configuration
        self.config: Dict[str, Any] = {}
        self.enabled = True

        # View classes to register
        self._view_classes: List[Type] = []

        # Security: Whitelist for allowed import paths
        self._allowed_import_prefixes: Set[str] = {
            'pgappforge.collaborative.',
            'pgappforge.security.',
            'pgappforge.views.',
            'pgappforge.api.',
            # Add your trusted package prefixes here
        }

        # Security: Pattern for validating import paths
        self._import_path_pattern = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_.]*$')

    def pre_process(self) -> None:
        """
        Pre-processing tasks before manager initialization.

        Loads configuration, validates settings, and prepares the service registry.
        """
        try:
            self.logger.info("Starting collaborative addon pre-processing")

            # Load configuration from Flask app config
            self._load_configuration()
            
            # Import models to register them with SQLAlchemy metadata
            self._register_models()

            # Check if collaborative features are enabled
            if not self.config.get("COLLABORATIVE_ENABLED", True):
                self.enabled = False
                self.logger.info("Collaborative features disabled via configuration")
                return

            # Validate configuration
            self._validate_configuration()

            # Create service registry with default services
            self.service_registry = ServiceFactory.create_default_registry(
                app_builder=self.appbuilder,
                auto_discover=self.config.get("COLLABORATIVE_AUTO_DISCOVER", True),
            )

            # Validate service registry configuration
            if not ServiceFactory.validate_service_configuration(self.service_registry):
                raise ValueError("Service registry validation failed")

            # Create lifecycle manager
            self.lifecycle_manager = ServiceLifecycleManager(self.service_registry)

            # Load custom service implementations if configured
            self._register_custom_services()

            self.logger.info(
                "Collaborative addon pre-processing completed successfully"
            )

        except Exception as e:
            self.logger.error(f"Failed during collaborative addon pre-processing: {e}")
            self.enabled = False
            raise

    def register_views(self) -> None:
        """
        Register views and endpoints for collaborative features.

        This method registers all collaborative views, API endpoints, and
        menu items with the PgAppForge instance.
        """
        if not self.enabled:
            self.logger.info("Collaborative addon disabled, skipping view registration")
            return

        try:
            self.logger.info("Registering collaborative views")

            # Register collaborative API endpoints
            self._register_api_views()

            # Register administrative views
            self._register_admin_views()

            # Register WebSocket endpoints
            self._register_websocket_views()

            # Add menu items
            self._add_menu_items()

            self.logger.info("Collaborative views registered successfully")

        except Exception as e:
            self.logger.error(f"Failed to register collaborative views: {e}")
            raise

    def post_process(self) -> None:
        """
        Post-processing tasks after manager initialization.

        Initializes services, sets up lifecycle management, and performs
        final configuration steps.
        """
        if not self.enabled:
            self.logger.info("Collaborative addon disabled, skipping post-processing")
            return

        try:
            self.logger.info("Starting collaborative addon post-processing")

            # Initialize the service registry with Flask app context
            if self.lifecycle_manager and self.appbuilder.app:
                self.lifecycle_manager.initialize_with_app(self.appbuilder.app)

                # Configure teardown handlers for proper cleanup
                self.lifecycle_manager.configure_teardown_handlers(self.appbuilder.app)

            # Register health check endpoints
            self._register_health_endpoints()

            # Configure background tasks if enabled
            self._configure_background_tasks()

            # Store service registry reference in appbuilder for easy access
            self.appbuilder.collaborative_services = self.service_registry

            self.logger.info(
                "Collaborative addon post-processing completed successfully"
            )

        except Exception as e:
            self.logger.error(f"Failed during collaborative addon post-processing: {e}")
            raise

    def _load_configuration(self) -> None:
        """Load configuration from Flask app config."""
        app_config = self.appbuilder.get_app.config

        # Default configuration
        default_config = {
            "COLLABORATIVE_ENABLED": True,
            "COLLABORATIVE_AUTO_DISCOVER": True,
            "COLLABORATIVE_WEBSOCKET_ENABLED": True,
            "COLLABORATIVE_BACKGROUND_TASKS": True,
            "COLLABORATIVE_HEALTH_CHECKS": True,
            "COLLABORATIVE_API_PREFIX": "/api/v1/collaborative",
            "COLLABORATIVE_WEBSOCKET_PATH": "/ws/collaborative",
            "COLLABORATIVE_MENU_CATEGORY": "Collaboration",
            "COLLABORATIVE_MENU_ICON": "fa-users",
            "COLLABORATIVE_CUSTOM_SERVICES": {},
        }

        # Load configuration with defaults
        for key, default_value in default_config.items():
            self.config[key] = app_config.get(key, default_value)

        self.logger.debug(f"Loaded collaborative configuration: {self.config}")

    def _register_models(self) -> None:
        """Register collaborative models with PgAppForge's SQLAlchemy metadata."""
        try:
            # Import models module to trigger model registration with SQLAlchemy
            from . import models
            self.logger.info("Collaborative models registered with SQLAlchemy metadata")
        except ImportError as e:
            self.logger.warning(f"Could not import collaborative models: {e}")
            # Models are optional - collaborative features can work with external models

    def _validate_configuration(self) -> None:
        """Validate the loaded configuration."""
        required_flask_config = ["SECRET_KEY", "SQLALCHEMY_DATABASE_URI"]

        app_config = self.appbuilder.get_app.config
        missing_config = []

        for key in required_flask_config:
            if not app_config.get(key):
                missing_config.append(key)

        if missing_config:
            raise ValueError(f"Missing required Flask configuration: {missing_config}")

        # Validate specific collaborative settings
        if self.config["COLLABORATIVE_WEBSOCKET_ENABLED"]:
            if not self.config.get("COLLABORATIVE_WEBSOCKET_PATH"):
                raise ValueError(
                    "COLLABORATIVE_WEBSOCKET_PATH required when WebSocket is enabled"
                )

    def _register_custom_services(self) -> None:
        """Register custom service implementations from configuration with security validation."""
        custom_services = self.config.get("COLLABORATIVE_CUSTOM_SERVICES", {})

        for service_name, implementation_path in custom_services.items():
            try:
                # Security: Validate the import path
                if not self._is_safe_import_path(implementation_path):
                    self.logger.error(
                        f"Security violation: Blocked unsafe import path for service {service_name}: {implementation_path}"
                    )
                    continue

                # Security: Log all import attempts for monitoring
                self.logger.info(
                    f"Attempting to import custom service implementation: {service_name} -> {implementation_path}"
                )

                # Import the custom implementation using secure method
                implementation_class = self._secure_dynamic_import(implementation_path)

                if implementation_class:
                    # Security: Validate that the imported class implements expected interface
                    service_type = self._get_service_type(service_name)
                    if not service_type:
                        self.logger.warning(f"Unknown service type: {service_name}")
                        continue

                    if not self._validate_service_interface(implementation_class, service_type):
                        self.logger.error(
                            f"Security violation: Service {service_name} class {implementation_path} does not implement required interface"
                        )
                        continue

                    # Register the validated service
                    if self.service_registry:
                        self.service_registry.register_service(
                            service_type=service_type,
                            implementation=implementation_class,
                            singleton=True,
                        )
                        self.logger.info(
                            f"Successfully registered custom service: {service_name} -> {implementation_path}"
                        )

            except Exception as e:
                self.logger.error(
                    f"Failed to register custom service {service_name}: {e}"
                )
                # Security: Log potential security violations
                if "Security violation" in str(e) or "blocked" in str(e).lower():
                    self.logger.critical(
                        f"SECURITY ALERT: Potential code injection attempt via service {service_name}: {implementation_path}"
                    )

    def _register_api_views(self) -> None:
        """Register collaborative API views."""
        api_prefix = self.config["COLLABORATIVE_API_PREFIX"]
        registered_apis = []

        # Try to import and register each API individually
        api_classes = [
            ("collaboration_api", "CollaborationApi"),
            ("team_api", "TeamApi"),
            ("workspace_api", "WorkspaceApi"),
            ("communication_api", "CommunicationApi"),
        ]

        for module_name, class_name in api_classes:
            try:
                module = __import__(f".api.{module_name}", fromlist=[class_name], level=1)
                api_class = getattr(module, class_name)
                self.appbuilder.add_api(api_class)
                registered_apis.append(class_name)
                self.logger.info(f"Registered {class_name} API")
            except (ImportError, AttributeError) as e:
                self.logger.debug(f"Could not import {class_name}: {e}")

        if registered_apis:
            self.logger.info(
                f"Registered {len(registered_apis)} collaborative API views with prefix: {api_prefix}"
            )
        else:
            self.logger.info("No collaborative API views found to register")

    def _is_safe_import_path(self, import_path: str) -> bool:
        """Security: Validate that an import path is safe to import.

        Args:
            import_path: Python import path to validate

        Returns:
            True if the path is safe to import, False otherwise
        """
        if not import_path or not isinstance(import_path, str):
            return False

        # Check path format - only allow valid Python identifiers and dots
        if not self._import_path_pattern.match(import_path):
            self.logger.warning(f"Invalid import path format: {import_path}")
            return False

        # Prevent path traversal attempts
        if '..' in import_path or import_path.startswith('/') or '\\' in import_path:
            self.logger.warning(f"Path traversal attempt detected: {import_path}")
            return False

        # Check against whitelist of allowed prefixes
        if not any(import_path.startswith(prefix) for prefix in self._allowed_import_prefixes):
            self.logger.warning(f"Import path not in whitelist: {import_path}")
            return False

        # Block dangerous modules
        dangerous_modules = {
            'os', 'sys', 'subprocess', 'eval', 'exec', 'compile',
            '__builtins__', '__import__', 'importlib', 'pickle',
            'marshal', 'shelve', 'dill', 'ctypes'
        }

        path_parts = import_path.split('.')
        if any(part in dangerous_modules for part in path_parts):
            self.logger.warning(f"Dangerous module detected in path: {import_path}")
            return False

        return True

    def _secure_dynamic_import(self, import_path: str) -> Optional[Type]:
        """Security: Safely import a class with additional validation.

        Args:
            import_path: Validated Python import path

        Returns:
            Imported class or None if import failed
        """
        try:
            # Split module and class name
            if '.' in import_path:
                module_path, class_name = import_path.rsplit('.', 1)
            else:
                self.logger.error(f"Invalid import path format: {import_path}")
                return None

            # Import module
            module = __import__(module_path, fromlist=[class_name])

            # Get class from module
            if not hasattr(module, class_name):
                self.logger.error(f"Class {class_name} not found in module {module_path}")
                return None

            implementation_class = getattr(module, class_name)

            # Basic type validation
            if not isinstance(implementation_class, type):
                self.logger.error(f"Import result is not a class: {import_path}")
                return None

            return implementation_class

        except ImportError as e:
            self.logger.error(f"Failed to import {import_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error importing {import_path}: {e}")
            return None

    def _get_service_type(self, service_name: str) -> Optional[Type]:
        """Get the service interface type for a service name.

        Args:
            service_name: Name of the service

        Returns:
            Service interface class or None if unknown
        """
        service_type_map = {
            "collaboration": ICollaborationService,
            "team": ITeamService,
            "workspace": IWorkspaceService,
            "communication": ICommunicationService,
            "websocket": IWebSocketService,
        }
        return service_type_map.get(service_name.lower())

    def _validate_service_interface(self, implementation_class: Type, expected_interface: Type) -> bool:
        """Security: Validate that a class implements the expected service interface.

        Args:
            implementation_class: Class to validate
            expected_interface: Expected interface/base class

        Returns:
            True if class implements interface, False otherwise
        """
        try:
            # Check if class is a subclass of the expected interface
            if not issubclass(implementation_class, expected_interface):
                self.logger.error(
                    f"Class {implementation_class.__name__} does not inherit from {expected_interface.__name__}"
                )
                return False

            # Additional validation could be added here:
            # - Check for required methods
            # - Validate method signatures
            # - Check for security decorators

            return True

        except Exception as e:
            self.logger.error(f"Error validating service interface: {e}")
            return False

    def _register_admin_views(self) -> None:
        """Register administrative views for collaborative features."""
        menu_category = self.config["COLLABORATIVE_MENU_CATEGORY"]
        menu_icon = self.config["COLLABORATIVE_MENU_ICON"]
        registered_views = []

        # Try to import and register each view individually
        view_configs = [
            ("team_view", "TeamModelView", "Teams", "fa-users"),
            ("workspace_view", "WorkspaceModelView", "Workspaces", "fa-folder"),
            ("collaboration_view", "CollaborationView", "Collaboration Dashboard", "fa-dashboard"),
        ]

        for module_name, class_name, title, icon in view_configs:
            try:
                module = __import__(f".views.{module_name}", fromlist=[class_name], level=1)
                view_class = getattr(module, class_name)
                
                if class_name == "TeamModelView":
                    self.appbuilder.add_view(
                        view_class,
                        title,
                        icon=icon,
                        category=menu_category,
                        category_icon=menu_icon,
                    )
                else:
                    self.appbuilder.add_view(
                        view_class,
                        title,
                        icon=icon,
                        category=menu_category,
                    )
                
                registered_views.append(class_name)
                self.logger.info(f"Registered {class_name} admin view")
            except (ImportError, AttributeError) as e:
                self.logger.debug(f"Could not import {class_name}: {e}")

        if registered_views:
            self.logger.info(f"Registered {len(registered_views)} collaborative administrative views")
        else:
            self.logger.info("No collaborative administrative views found to register")

    def _register_websocket_views(self) -> None:
        """Register WebSocket views if enabled."""
        if not self.config["COLLABORATIVE_WEBSOCKET_ENABLED"]:
            return

        try:
            # Import WebSocket views dynamically
            from .views.websocket_view import WebSocketView

            # Register WebSocket endpoint
            self.appbuilder.add_view_no_menu(WebSocketView)

            self.logger.info("Registered collaborative WebSocket views")

        except ImportError as e:
            self.logger.warning(f"Could not import WebSocket views: {e}")

    def _add_menu_items(self) -> None:
        """Add menu items for collaborative features."""
        menu_category = self.config["COLLABORATIVE_MENU_CATEGORY"]

        # Add separator before collaborative menu
        self.appbuilder.add_separator(menu_category)

        # Add documentation link
        self.appbuilder.add_link(
            "Collaboration Guide",
            href="/collaborative/docs",
            icon="fa-book",
            category=menu_category,
        )

    def _register_health_endpoints(self) -> None:
        """Register health check endpoints if enabled."""
        if not self.config["COLLABORATIVE_HEALTH_CHECKS"]:
            return

        try:
            from .views.health_view import CollaborativeHealthView

            self.appbuilder.add_view_no_menu(CollaborativeHealthView)

            self.logger.info("Registered collaborative health check endpoints")

        except ImportError as e:
            self.logger.warning(f"Could not import health check views: {e}")

    def _configure_background_tasks(self) -> None:
        """Configure background tasks if enabled."""
        if not self.config["COLLABORATIVE_BACKGROUND_TASKS"]:
            return

        try:
            # Configure background task scheduler
            from .tasks.scheduler import CollaborativeTaskScheduler

            scheduler = CollaborativeTaskScheduler(
                service_registry=self.service_registry, app=self.appbuilder.app
            )
            scheduler.initialize()

            # Store scheduler reference
            self.appbuilder.collaborative_scheduler = scheduler

            self.logger.info("Configured collaborative background tasks")

        except ImportError as e:
            self.logger.warning(f"Could not configure background tasks: {e}")

    def get_service(self, service_type: Type) -> Any:
        """
        Get a collaborative service instance.

        Args:
            service_type: Type of service to retrieve

        Returns:
            Service instance

        Raises:
            ValueError: If service registry not initialized or service not found
        """
        if not self.service_registry:
            raise ValueError("Service registry not initialized")

        return self.service_registry.get_service(service_type)

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get health status of collaborative services.

        Returns:
            Dictionary containing health status information
        """
        if not self.lifecycle_manager:
            return {
                "status": "disabled",
                "message": "Collaborative addon not initialized",
            }

        return self.lifecycle_manager.get_health_status()

    def shutdown(self) -> None:
        """Shutdown the collaborative addon and cleanup resources."""
        if self.lifecycle_manager:
            try:
                if hasattr(self.appbuilder, "collaborative_scheduler"):
                    self.appbuilder.collaborative_scheduler.shutdown()

                self.lifecycle_manager.registry.shutdown_all_services()
                self.logger.info("Collaborative addon shutdown completed")

            except Exception as e:
                self.logger.error(f"Error during collaborative addon shutdown: {e}")


# Factory function for easy registration
def create_collaborative_addon_manager(appbuilder) -> CollaborativeAddonManager:
    """
    Factory function to create a collaborative addon manager.

    Args:
        appbuilder: PgAppForge instance

    Returns:
        Configured CollaborativeAddonManager instance
    """
    return CollaborativeAddonManager(appbuilder)
