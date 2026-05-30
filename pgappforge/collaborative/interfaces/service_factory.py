"""
Service factory for creating and configuring collaborative services.

Provides convenient factory methods for setting up service registries with
common configurations and service implementations.
"""

from typing import Type, Any, Dict, List, Optional, Callable
import logging
from functools import wraps

from .service_registry import ServiceRegistry
from .base_interfaces import (
    ICollaborationService,
    ITeamService,
    IWorkspaceService,
    ICommunicationService,
    IWebSocketService,
)


logger = logging.getLogger(__name__)


class ServiceFactory:
    """
    Factory for creating and configuring service registries.

    Provides convenient methods for setting up service registries with
    standard configurations and automatic service discovery.
    """

    @staticmethod
    def create_registry(app_builder: Any = None) -> ServiceRegistry:
        """
        Create a new service registry instance.

        Args:
            app_builder: PgForge instance

        Returns:
            Configured service registry
        """
        return ServiceRegistry(app_builder=app_builder)

    @staticmethod
    def create_default_registry(
        app_builder: Any = None, auto_discover: bool = True
    ) -> ServiceRegistry:
        """
        Create a service registry with default collaborative services.

        Args:
            app_builder: PgForge instance
            auto_discover: Whether to auto-discover service implementations

        Returns:
            Configured service registry with default services
        """
        registry = ServiceFactory.create_registry(app_builder)

        if auto_discover:
            ServiceFactory._register_default_services(registry)

        return registry

    @staticmethod
    def _register_default_services(registry: ServiceRegistry) -> None:
        """Register default service implementations."""
        try:
            # Import default implementations dynamically to avoid circular imports
            from ..core.collaboration_engine import CollaborationEngine
            from ..core.team_manager import TeamManager
            from ..core.workspace_manager import WorkspaceManager
            from ..communication.notification_manager import NotificationManager
            from ..realtime.websocket_manager import WebSocketManager

            # Register services in dependency order
            registry.register_service(
                service_type=IWebSocketService,
                implementation=WebSocketManager,
                initialization_order=10,
            )

            registry.register_service(
                service_type=ICommunicationService,
                implementation=NotificationManager,
                dependencies=[IWebSocketService],
                initialization_order=20,
            )

            registry.register_service(
                service_type=ITeamService,
                implementation=TeamManager,
                initialization_order=30,
            )

            registry.register_service(
                service_type=IWorkspaceService,
                implementation=WorkspaceManager,
                dependencies=[ITeamService],
                initialization_order=40,
            )

            registry.register_service(
                service_type=ICollaborationService,
                implementation=CollaborationEngine,
                dependencies=[
                    IWorkspaceService,
                    ICommunicationService,
                    IWebSocketService,
                ],
                initialization_order=50,
            )

            logger.info("Registered default collaborative services")

        except ImportError as e:
            logger.warning(f"Could not auto-register some services: {e}")

    @staticmethod
    def register_service_with_config(
        registry: ServiceRegistry,
        service_type: Type,
        implementation: Type,
        config: Dict[str, Any] = None,
    ) -> None:
        """
        Register a service with configuration options.

        Args:
            registry: Service registry to register with
            service_type: Interface/protocol type
            implementation: Concrete implementation class
            config: Configuration options for the service
        """
        config = config or {}

        singleton = config.get("singleton", True)
        dependencies = config.get("dependencies", [])
        initialization_order = config.get("initialization_order", 0)

        registry.register_service(
            service_type=service_type,
            implementation=implementation,
            singleton=singleton,
            dependencies=dependencies,
            initialization_order=initialization_order,
        )

    @staticmethod
    def create_test_registry(
        app_builder: Any = None, mock_services: Dict[Type, Any] = None
    ) -> ServiceRegistry:
        """
        Create a service registry configured for testing.

        Args:
            app_builder: PgForge instance
            mock_services: Dictionary of service types to mock instances

        Returns:
            Service registry configured for testing
        """
        registry = ServiceFactory.create_registry(app_builder)

        if mock_services:
            for service_type, mock_instance in mock_services.items():
                # Create a mock implementation class that returns the mock instance
                class MockImplementation:
                    def __init__(self, *args, **kwargs):
                        pass

                    def __getattr__(self, name):
                        return getattr(mock_instance, name)

                    def initialize(self):
                        if hasattr(mock_instance, "initialize"):
                            mock_instance.initialize()

                    def cleanup(self):
                        if hasattr(mock_instance, "cleanup"):
                            mock_instance.cleanup()

                registry.register_service(
                    service_type=service_type,
                    implementation=MockImplementation,
                    singleton=True,
                )

        return registry

    @staticmethod
    def validate_service_configuration(registry: ServiceRegistry) -> bool:
        """
        Validate that a service registry is properly configured.

        Args:
            registry: Service registry to validate

        Returns:
            True if configuration is valid, False otherwise
        """
        issues = registry.validate_registry()

        has_issues = any(len(issue_list) > 0 for issue_list in issues.values())

        if has_issues:
            logger.error("Service registry validation failed:")
            for category, issue_list in issues.items():
                if issue_list:
                    logger.error(f"  {category}:")
                    for issue in issue_list:
                        logger.error(f"    - {issue}")

        return not has_issues


class ServiceConfigurationBuilder:
    """
    Builder pattern for creating complex service configurations.

    Provides a fluent interface for configuring service registries
    with custom implementations and dependencies.
    """

    def __init__(self, app_builder: Any = None):
        """
        Initialize the configuration builder.

        Args:
            app_builder: PgForge instance
        """
        self.app_builder = app_builder
        self._configurations: List[Dict[str, Any]] = []

    def register(
        self, service_type: Type, implementation: Type
    ) -> "ServiceConfigurationBuilder":
        """
        Register a service type with implementation.

        Args:
            service_type: Interface/protocol type
            implementation: Concrete implementation class

        Returns:
            Self for method chaining
        """
        self._configurations.append(
            {
                "service_type": service_type,
                "implementation": implementation,
                "singleton": True,
                "dependencies": [],
                "initialization_order": 0,
            }
        )
        return self

    def as_singleton(self, singleton: bool = True) -> "ServiceConfigurationBuilder":
        """
        Configure the last registered service as singleton or not.

        Args:
            singleton: Whether service should be singleton

        Returns:
            Self for method chaining
        """
        if self._configurations:
            self._configurations[-1]["singleton"] = singleton
        return self

    def with_dependencies(self, *dependencies: Type) -> "ServiceConfigurationBuilder":
        """
        Add dependencies to the last registered service.

        Args:
            dependencies: Service types this service depends on

        Returns:
            Self for method chaining
        """
        if self._configurations:
            self._configurations[-1]["dependencies"] = list(dependencies)
        return self

    def with_initialization_order(self, order: int) -> "ServiceConfigurationBuilder":
        """
        Set initialization order for the last registered service.

        Args:
            order: Initialization order (lower numbers first)

        Returns:
            Self for method chaining
        """
        if self._configurations:
            self._configurations[-1]["initialization_order"] = order
        return self

    def build(self) -> ServiceRegistry:
        """
        Build the service registry with configured services.

        Returns:
            Configured service registry
        """
        registry = ServiceFactory.create_registry(self.app_builder)

        for config in self._configurations:
            registry.register_service(
                service_type=config["service_type"],
                implementation=config["implementation"],
                singleton=config["singleton"],
                dependencies=config["dependencies"],
                initialization_order=config["initialization_order"],
            )

        return registry


def service_decorator(
    service_type: Type,
    dependencies: List[Type] = None,
    singleton: bool = True,
    initialization_order: int = 0,
):
    """
    Decorator for automatically registering service implementations.

    Args:
        service_type: Interface/protocol type this class implements
        dependencies: List of service types this service depends on
        singleton: Whether service should be singleton
        initialization_order: Initialization order

    Returns:
        Decorator function
    """

    def decorator(implementation_class: Type) -> Type:
        # Store service metadata on the class for later registration
        implementation_class._service_metadata = {
            "service_type": service_type,
            "dependencies": dependencies or [],
            "singleton": singleton,
            "initialization_order": initialization_order,
        }
        return implementation_class

    return decorator


def auto_register_services(
    registry: ServiceRegistry, implementations: List[Type]
) -> None:
    """
    Automatically register services that have service metadata.

    Args:
        registry: Service registry to register services with
        implementations: List of implementation classes to check
    """
    for impl_class in implementations:
        if hasattr(impl_class, "_service_metadata"):
            metadata = impl_class._service_metadata
            registry.register_service(
                service_type=metadata["service_type"],
                implementation=impl_class,
                singleton=metadata["singleton"],
                dependencies=metadata["dependencies"],
                initialization_order=metadata["initialization_order"],
            )
            logger.info(
                f"Auto-registered service: {metadata['service_type'].__name__} -> {impl_class.__name__}"
            )


class ServiceLifecycleManager:
    """
    Manager for handling service lifecycle events across the application.

    Provides hooks for service initialization, configuration, and cleanup
    with integration into PgForge lifecycle.
    """

    def __init__(self, registry: ServiceRegistry):
        """
        Initialize the lifecycle manager.

        Args:
            registry: Service registry to manage
        """
        self.registry = registry
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    def initialize_with_app(self, app: Any) -> None:
        """
        Initialize services with Flask app context.

        Args:
            app: Flask application instance
        """
        with app.app_context():
            try:
                self.registry.initialize_all_services()
                self.logger.info("Service lifecycle manager initialized with Flask app")
            except Exception as e:
                self.logger.error(f"Failed to initialize services with app: {e}")
                raise

    def configure_teardown_handlers(self, app: Any) -> None:
        """
        Configure Flask teardown handlers for service cleanup.

        Args:
            app: Flask application instance
        """

        @app.teardown_appcontext
        def cleanup_services(error):
            if error:
                self.logger.error(f"Application error during teardown: {error}")
            # Note: Don't shutdown registry on every request teardown
            # Only on application shutdown

        # Register cleanup on application shutdown
        import atexit

        atexit.register(self._cleanup_on_shutdown)

    def _cleanup_on_shutdown(self) -> None:
        """Cleanup services on application shutdown."""
        try:
            self.registry.shutdown_all_services()
            self.logger.info("Services cleaned up on application shutdown")
        except Exception as e:
            self.logger.error(f"Error during service cleanup: {e}")

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get health status of all services.

        Returns:
            Dictionary containing service health information
        """
        status = self.registry.get_service_status()

        # Add health-specific information
        status["health"] = {
            "healthy_services": 0,
            "unhealthy_services": 0,
            "total_services": len(status["services"]),
        }

        for service_name, service_info in status["services"].items():
            if service_info["lifecycle_state"] in ["initialized", "running"]:
                status["health"]["healthy_services"] += 1
            else:
                status["health"]["unhealthy_services"] += 1

        status["health"]["overall_health"] = (
            "healthy" if status["health"]["unhealthy_services"] == 0 else "degraded"
        )

        return status
