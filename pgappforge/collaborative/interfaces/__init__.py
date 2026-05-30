"""
Service interfaces for collaborative features.

Provides abstract base classes and protocols for all collaborative services,
enabling dependency injection, testing, and service replacement.
"""

from .base_interfaces import (
    ICollaborationService,
    ITeamService,
    IWorkspaceService,
    ICommunicationService,
    IWebSocketService,
)

from .service_registry import ServiceRegistry
from .service_factory import ServiceFactory

__all__ = [
    "ICollaborationService",
    "ITeamService",
    "IWorkspaceService",
    "ICommunicationService",
    "IWebSocketService",
    "ServiceRegistry",
    "ServiceFactory",
]
