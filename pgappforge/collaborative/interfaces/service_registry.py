"""
Service registry for dependency injection container.

Provides centralized service registration, dependency resolution, and lifecycle management
for all collaborative services.
"""

from typing import Dict, Type, Any, List, Optional, Set, get_origin
from abc import ABC
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime

from .base_interfaces import ServiceLifecycle, ServiceMetadata, BaseCollaborativeService

# Protocol detection utilities for different Python versions
if sys.version_info >= (3, 8):
    from typing import Protocol
    try:
        from typing import get_args, get_origin
    except ImportError:
        from typing_extensions import get_args, get_origin
    
    def is_protocol_type(type_hint: Type) -> bool:
        """Check if a type is a Protocol type."""
        # Check for Protocol marker attribute
        if hasattr(type_hint, '_is_protocol'):
            return getattr(type_hint, '_is_protocol', False)
        
        # Check for Protocol base class
        if hasattr(type_hint, '__bases__'):
            for base in type_hint.__bases__:
                if hasattr(base, '__name__') and base.__name__ == 'Protocol':
                    return True
        
        # Check using get_origin for generic protocols
        origin = get_origin(type_hint)
        if origin is not None and hasattr(origin, '_is_protocol'):
            return getattr(origin, '_is_protocol', False)
            
        return False
else:
    # Python < 3.8 fallback
    def is_protocol_type(type_hint: Type) -> bool:
        """Fallback Protocol detection for older Python versions."""
        return hasattr(type_hint, '_is_protocol') and getattr(type_hint, '_is_protocol', False)


logger = logging.getLogger(__name__)


class ServiceRegistry:
    """
    Dependency injection container for collaborative services.

    Manages service registration, instantiation, dependency resolution,
    and lifecycle management with singleton support.
    """

    def __init__(self, app_builder: Any = None):
        """
        Initialize the service registry.

        Args:
            app_builder: PgForge instance for service initialization
        """
        self.app_builder = app_builder
        self._services: Dict[Type, ServiceMetadata] = {}
        self._instances: Dict[Type, Any] = {}
        self._initialization_order: List[ServiceMetadata] = []
        self._initialized_services: Set[Type] = set()

        # Circular dependency detection
        self._resolving_stack: Set[Type] = set()

        # Registry lifecycle
        self._registry_initialized = False
        self._registry_shutdown = False

        # Logging
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    def register_service(
        self,
        service_type: Type,
        implementation: Type,
        singleton: bool = True,
        dependencies: List[Type] = None,
        initialization_order: int = 0,
    ) -> None:
        """
        Register a service with the registry.

        Args:
            service_type: Interface/protocol type that the service implements
            implementation: Concrete implementation class
            singleton: Whether to create single instance (default: True)
            dependencies: List of service types this service depends on
            initialization_order: Order of initialization (lower numbers first)
        """
        if self._registry_shutdown:
            raise RuntimeError("Cannot register services after registry shutdown")

        metadata = ServiceMetadata(
            service_type=service_type,
            implementation=implementation,
            singleton=singleton,
            dependencies=dependencies or [],
            initialization_order=initialization_order,
        )

        self._services[service_type] = metadata
        self._update_initialization_order()

        self.logger.info(
            f"Registered service: {service_type.__name__} -> {implementation.__name__}"
        )

    def _update_initialization_order(self) -> None:
        """Update the initialization order based on dependencies and priority."""
        self._initialization_order = sorted(
            self._services.values(),
            key=lambda x: (x.initialization_order, x.service_type.__name__),
        )

    def get_service(self, service_type: Type) -> Any:
        """
        Get a service instance, resolving dependencies if needed.

        Args:
            service_type: Type of service to retrieve

        Returns:
            Service instance

        Raises:
            ValueError: If service not registered or circular dependency detected
        """
        if self._registry_shutdown:
            raise RuntimeError("Cannot get services after registry shutdown")

        if service_type not in self._services:
            raise ValueError(f"Service {service_type.__name__} not registered")

        metadata = self._services[service_type]

        # Check for circular dependencies
        if service_type in self._resolving_stack:
            cycle_path = " -> ".join([t.__name__ for t in self._resolving_stack])
            raise ValueError(
                f"Circular dependency detected: {cycle_path} -> {service_type.__name__}"
            )

        # Return existing instance for singletons
        if metadata.singleton and service_type in self._instances:
            metadata.last_accessed = datetime.now()
            return self._instances[service_type]

        # Resolve dependencies first
        self._resolving_stack.add(service_type)
        try:
            resolved_dependencies = self._resolve_dependencies(metadata.dependencies)
            instance = self._create_service_instance(metadata, resolved_dependencies)

            if metadata.singleton:
                self._instances[service_type] = instance

            metadata.last_accessed = datetime.now()
            metadata.lifecycle_state = ServiceLifecycle.RUNNING

            self.logger.debug(f"Created service instance: {service_type.__name__}")
            return instance

        finally:
            self._resolving_stack.remove(service_type)

    def _resolve_dependencies(self, dependencies: List[Type]) -> Dict[Type, Any]:
        """Resolve all dependencies for a service."""
        resolved = {}
        for dep_type in dependencies:
            resolved[dep_type] = self.get_service(dep_type)
        return resolved

    def _create_service_instance(
        self, metadata: ServiceMetadata, dependencies: Dict[Type, Any]
    ) -> Any:
        """Create a new service instance with resolved dependencies."""
        try:
            metadata.lifecycle_state = ServiceLifecycle.INITIALIZING

            # Create instance with app_builder and service_registry
            if issubclass(metadata.implementation, BaseCollaborativeService):
                instance = metadata.implementation(
                    app_builder=self.app_builder, service_registry=self
                )
            else:
                # For non-BaseCollaborativeService implementations
                instance = metadata.implementation()

            # Inject dependencies if the instance has dependency setters
            self._inject_dependencies(instance, dependencies)

            # Initialize the service if it has an initialize method
            if hasattr(instance, "initialize"):
                instance.initialize()

            metadata.lifecycle_state = ServiceLifecycle.INITIALIZED
            self._initialized_services.add(metadata.service_type)

            return instance

        except Exception as e:
            metadata.lifecycle_state = ServiceLifecycle.ERROR
            self.logger.error(
                f"Failed to create service {metadata.service_type.__name__}: {e}"
            )
            raise

    def _inject_dependencies(
        self, instance: Any, dependencies: Dict[Type, Any]
    ) -> None:
        """Inject resolved dependencies into the service instance."""
        for dep_type, dep_instance in dependencies.items():
            # Try common dependency injection patterns
            setter_name = f"set_{dep_type.__name__.lower()}"
            if hasattr(instance, setter_name):
                getattr(instance, setter_name)(dep_instance)
            elif hasattr(instance, "inject_dependency"):
                instance.inject_dependency(dep_type, dep_instance)

    def initialize_all_services(self) -> None:
        """Initialize all registered services in dependency order."""
        if self._registry_initialized:
            self.logger.warning("Registry already initialized")
            return

        self.logger.info("Initializing all services...")

        try:
            for metadata in self._initialization_order:
                if metadata.service_type not in self._initialized_services:
                    self.get_service(metadata.service_type)

            self._registry_initialized = True
            self.logger.info(
                f"Successfully initialized {len(self._initialized_services)} services"
            )

        except Exception as e:
            self.logger.error(f"Failed to initialize services: {e}")
            raise

    def shutdown_all_services(self) -> None:
        """Shutdown all services and cleanup resources."""
        if self._registry_shutdown:
            return

        self.logger.info("Shutting down all services...")

        # Shutdown in reverse initialization order
        for metadata in reversed(self._initialization_order):
            if metadata.service_type in self._instances:
                try:
                    instance = self._instances[metadata.service_type]
                    if hasattr(instance, "cleanup"):
                        instance.cleanup()
                    metadata.lifecycle_state = ServiceLifecycle.STOPPED
                    self.logger.debug(
                        f"Shutdown service: {metadata.service_type.__name__}"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error shutting down {metadata.service_type.__name__}: {e}"
                    )
                    metadata.lifecycle_state = ServiceLifecycle.ERROR

        self._instances.clear()
        self._initialized_services.clear()
        self._registry_shutdown = True

        self.logger.info("Service registry shutdown complete")

    def get_service_status(self) -> Dict[str, Any]:
        """Get status information about all registered services."""
        status = {
            "registry_initialized": self._registry_initialized,
            "registry_shutdown": self._registry_shutdown,
            "total_services": len(self._services),
            "initialized_services": len(self._initialized_services),
            "services": {},
        }

        for service_type, metadata in self._services.items():
            status["services"][service_type.__name__] = {
                "implementation": metadata.implementation.__name__,
                "singleton": metadata.singleton,
                "lifecycle_state": metadata.lifecycle_state.value,
                "dependencies": [dep.__name__ for dep in metadata.dependencies],
                "initialization_order": metadata.initialization_order,
                "created_at": metadata.created_at.isoformat(),
                "last_accessed": metadata.last_accessed.isoformat()
                if metadata.last_accessed
                else None,
                "instance_created": service_type in self._instances,
            }

        return status

    def validate_registry(self) -> Dict[str, List[str]]:
        """
        Validate the service registry for common issues.

        Returns:
            Dictionary of validation issues by category
        """
        issues = {
            "missing_dependencies": [],
            "circular_dependencies": [],
            "invalid_implementations": [],
        }

        # Check for missing dependencies
        for service_type, metadata in self._services.items():
            for dep_type in metadata.dependencies:
                if dep_type not in self._services:
                    issues["missing_dependencies"].append(
                        f"{service_type.__name__} depends on unregistered {dep_type.__name__}"
                    )

        # Check for circular dependencies
        for service_type in self._services:
            try:
                self._check_circular_dependency(service_type, set())
            except ValueError as e:
                if str(e) not in issues["circular_dependencies"]:
                    issues["circular_dependencies"].append(str(e))

        # Check for invalid implementations
        for service_type, metadata in self._services.items():
            # Handle Protocol types differently than regular classes
            if is_protocol_type(service_type):
                # For Protocol types, we validate by checking if required methods exist
                validation_result = self._validate_protocol_implementation(service_type, metadata.implementation)
                if validation_result:
                    issues["invalid_implementations"].extend(validation_result)
            else:
                # For regular classes/interfaces, use standard issubclass check
                try:
                    if not issubclass(metadata.implementation, service_type):
                        issues["invalid_implementations"].append(
                            f"{metadata.implementation.__name__} does not implement {service_type.__name__}"
                        )
                except TypeError:
                    # Handle edge cases where issubclass might fail
                    issues["invalid_implementations"].append(
                        f"Cannot validate implementation {metadata.implementation.__name__} against {service_type.__name__}"
                    )

        return issues

    def _validate_protocol_implementation(self, protocol_type: Type, implementation: Type) -> List[str]:
        """
        Validate that an implementation properly implements a Protocol.
        
        Args:
            protocol_type: Protocol type to validate against
            implementation: Implementation class to check
            
        Returns:
            List of validation errors (empty if valid)
        """
        issues = []
        
        # Get protocol methods and attributes
        protocol_members = set()
        if hasattr(protocol_type, '__annotations__'):
            protocol_members.update(protocol_type.__annotations__.keys())
        
        # Get methods defined in the protocol
        if hasattr(protocol_type, '__dict__'):
            for name, value in protocol_type.__dict__.items():
                if not name.startswith('_') and callable(value):
                    protocol_members.add(name)
        
        # Check if implementation has all required members
        for member_name in protocol_members:
            if not hasattr(implementation, member_name):
                issues.append(
                    f"{implementation.__name__} missing required method/attribute '{member_name}' "
                    f"from protocol {protocol_type.__name__}"
                )
            else:
                # Check if it's callable when it should be
                protocol_member = getattr(protocol_type, member_name, None)
                impl_member = getattr(implementation, member_name, None)
                
                if callable(protocol_member) and not callable(impl_member):
                    issues.append(
                        f"{implementation.__name__}.{member_name} should be callable "
                        f"to match protocol {protocol_type.__name__}"
                    )
        
        return issues

    def _check_circular_dependency(
        self, service_type: Type, visited: Set[Type]
    ) -> None:
        """Recursively check for circular dependencies."""
        if service_type in visited:
            cycle_path = " -> ".join([t.__name__ for t in visited])
            raise ValueError(
                f"Circular dependency detected: {cycle_path} -> {service_type.__name__}"
            )

        if service_type not in self._services:
            return

        visited.add(service_type)
        metadata = self._services[service_type]

        for dep_type in metadata.dependencies:
            self._check_circular_dependency(dep_type, visited.copy())
