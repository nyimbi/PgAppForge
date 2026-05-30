"""
Base service interfaces for collaborative features.

Defines protocols and abstract base classes that all collaborative services
must implement, enabling dependency injection and service replacement.
"""

from abc import ABC, abstractmethod
from typing import Protocol, Any, Dict, List, Optional, Set, Union, Tuple
from datetime import datetime
from enum import Enum

# Import types from collaborative modules
from ..core.team_manager import TeamRole, TeamConfig
from ..core.workspace_manager import WorkspaceType, AccessLevel
from ..communication.notification_manager import NotificationType, NotificationPriority


class ICollaborationService(Protocol):
    """
    Interface for collaboration engine services.

    Provides real-time collaboration capabilities including session management,
    event handling, and collaborative editing features.
    """

    async def create_session(self, workspace_id: str, user: Any) -> str:
        """Create a new collaboration session."""
        ...

    async def join_session(self, session_id: str, user: Any) -> bool:
        """Join an existing collaboration session."""
        ...

    async def leave_session(self, session_id: str, user_id: int) -> bool:
        """Leave a collaboration session."""
        ...

    async def emit_event(self, event: Any) -> None:
        """Emit a collaborative event to session participants."""
        ...

    async def acquire_lock(
        self, session_id: str, user_id: int, resource_id: str
    ) -> bool:
        """Acquire a lock on a resource for exclusive editing."""
        ...

    async def release_lock(
        self, session_id: str, user_id: int, resource_id: str
    ) -> bool:
        """Release a lock on a resource."""
        ...

    def get_session_users(self, session_id: str) -> List[Any]:
        """Get all users in a collaboration session."""
        ...


class ITeamService(Protocol):
    """
    Interface for team management services.

    Provides team creation, membership management, and permission handling.
    """

    def create_team(
        self,
        name: str,
        description: str,
        created_by_user_id: int,
        config: Optional[TeamConfig] = None,
    ) -> Optional[Any]:
        """Create a new team."""
        ...

    def get_team_by_id(self, team_id: int) -> Optional[Any]:
        """Get team by ID."""
        ...

    def get_team_by_slug(self, slug: str) -> Optional[Any]:
        """Get team by slug."""
        ...

    def add_team_member(
        self, team_id: int, user_id: int, role: TeamRole, invited_by_user_id: int
    ) -> bool:
        """Add a member to a team."""
        ...

    def remove_team_member(
        self, team_id: int, user_id: int, removed_by_user_id: int
    ) -> bool:
        """Remove a member from a team."""
        ...

    def has_team_permission(self, user_id: int, team_id: int, permission: str) -> bool:
        """Check if user has a specific team permission."""
        ...

    def get_user_teams(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all teams for a user."""
        ...


class IWorkspaceService(Protocol):
    """
    Interface for workspace management services.

    Provides workspace creation, resource management, and access control.
    """

    def create_workspace(
        self,
        name: str,
        description: str,
        workspace_type: WorkspaceType,
        owner_id: int,
        team_id: Optional[int] = None,
        **kwargs,
    ) -> Optional[Any]:
        """Create a new workspace."""
        ...

    def get_workspace_by_id(self, workspace_id: int) -> Optional[Any]:
        """Get workspace by ID."""
        ...

    def has_workspace_access(
        self, user_id: int, workspace_id: int, access_level: AccessLevel
    ) -> bool:
        """Check if user has access to workspace at specified level."""
        ...

    def add_workspace_collaborator(
        self,
        workspace_id: int,
        user_id: int,
        access_level: AccessLevel,
        added_by_user_id: int,
    ) -> bool:
        """Add a collaborator to a workspace."""
        ...

    def remove_workspace_collaborator(
        self, workspace_id: int, user_id: int, removed_by_user_id: int
    ) -> bool:
        """Remove a collaborator from a workspace."""
        ...

    def get_user_workspaces(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all workspaces for a user."""
        ...


class ICommunicationService(Protocol):
    """
    Interface for communication services.

    Provides unified communication capabilities including chat, comments, and notifications.
    """

    async def send_chat_message(
        self, channel_id: int, sender_id: int, content: str, **kwargs
    ) -> Optional[Any]:
        """Send a chat message."""
        ...

    async def create_chat_channel(
        self,
        workspace_id: int,
        name: str,
        description: str,
        created_by_id: int,
        **kwargs,
    ) -> Optional[Any]:
        """Create a chat channel."""
        ...

    async def create_comment_thread(
        self,
        workspace_id: int,
        commentable_type: str,
        commentable_id: str,
        created_by_id: int,
        initial_comment: str,
        **kwargs,
    ) -> Optional[Any]:
        """Create a comment thread."""
        ...

    async def add_comment_reply(
        self, thread_id: int, author_id: int, content: str, **kwargs
    ) -> Optional[Any]:
        """Add a reply to a comment thread."""
        ...

    async def send_notification(
        self,
        user_id: int,
        notification_type: NotificationType,
        title: str,
        message: str,
        **kwargs,
    ) -> Optional[Any]:
        """Send a notification to a user."""
        ...

    async def get_communication_summary(
        self, workspace_id: int, user_id: int, days: int = 7
    ) -> Dict[str, Any]:
        """Get communication activity summary."""
        ...


class IWebSocketService(Protocol):
    """
    Interface for WebSocket management services.

    Provides real-time WebSocket communication and message routing.
    """

    async def handle_connection(
        self, websocket: Any, auth_data: Dict[str, Any]
    ) -> Optional[str]:
        """Handle a new WebSocket connection."""
        ...

    async def handle_message(self, connection_id: str, message: Dict[str, Any]) -> bool:
        """Handle a WebSocket message."""
        ...

    async def send_to_user(self, user_id: int, message: Dict[str, Any]) -> bool:
        """Send a message to a specific user."""
        ...

    async def broadcast_to_session(
        self, session_id: str, message: Dict[str, Any], exclude_sender: bool = False
    ) -> int:
        """Broadcast a message to all users in a session."""
        ...

    async def disconnect_user(self, user_id: int, reason: str = None) -> bool:
        """Disconnect all connections for a user."""
        ...

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        ...


class BaseCollaborativeService(ABC):
    """
    Abstract base class for all collaborative services.

    Provides common functionality and ensures consistent patterns across all services.
    """

    def __init__(self, app_builder: Any, service_registry: "ServiceRegistry" = None):
        """
        Initialize the service.

        Args:
            app_builder: PgForge instance
            service_registry: Service registry for dependency injection
        """
        self.app_builder = app_builder
        self.app = app_builder.app if app_builder else None
        self.service_registry = service_registry

        # Initialize logging
        import logging

        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the service. Called after all dependencies are injected."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Cleanup service resources. Called during shutdown."""
        pass

    def get_dependency(self, service_type: type) -> Any:
        """Get a dependency from the service registry."""
        if self.service_registry:
            return self.service_registry.get_service(service_type)
        raise ValueError(
            f"Service registry not available to resolve dependency: {service_type}"
        )

    def log_service_event(self, event: str, level: str = "info", **kwargs) -> None:
        """Log a service event with consistent formatting."""
        log_data = {"service": self.__class__.__name__, "event": event, **kwargs}
        getattr(self.logger, level)(f"Service event: {log_data}")


class ServiceLifecycle(Enum):
    """Service lifecycle states."""

    CREATED = "created"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class ServiceMetadata:
    """Metadata for service registration and management."""

    def __init__(
        self,
        service_type: type,
        implementation: type,
        singleton: bool = True,
        dependencies: List[type] = None,
        initialization_order: int = 0,
    ):
        """
        Initialize service metadata.

        Args:
            service_type: Interface/protocol type
            implementation: Concrete implementation class
            singleton: Whether to create single instance (default: True)
            dependencies: List of service types this service depends on
            initialization_order: Order of initialization (lower numbers first)
        """
        self.service_type = service_type
        self.implementation = implementation
        self.singleton = singleton
        self.dependencies = dependencies or []
        self.initialization_order = initialization_order
        self.lifecycle_state = ServiceLifecycle.CREATED
        self.instance = None
        self.created_at = datetime.now()
        self.last_accessed = None
