"""
Shared audit logging utilities for collaborative features.

Provides centralized audit logging functionality to ensure consistent
logging patterns across all collaborative modules.
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict
from enum import Enum
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class AuditEventType(Enum):
    """Types of audit events."""

    # User actions
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_PERMISSION_CHANGE = "user_permission_change"

    # Team events
    TEAM_CREATED = "team_created"
    TEAM_UPDATED = "team_updated"
    TEAM_DELETED = "team_deleted"
    TEAM_MEMBER_ADDED = "team_member_added"
    TEAM_MEMBER_REMOVED = "team_member_removed"
    TEAM_MEMBER_ROLE_CHANGED = "team_member_role_changed"

    # Workspace events
    WORKSPACE_CREATED = "workspace_created"
    WORKSPACE_UPDATED = "workspace_updated"
    WORKSPACE_DELETED = "workspace_deleted"
    WORKSPACE_ACCESS_GRANTED = "workspace_access_granted"
    WORKSPACE_ACCESS_REVOKED = "workspace_access_revoked"

    # Collaboration events
    COLLABORATION_SESSION_STARTED = "collaboration_session_started"
    COLLABORATION_SESSION_ENDED = "collaboration_session_ended"
    COLLABORATION_SESSION_JOINED = "collaboration_session_joined"
    COLLABORATION_SESSION_LEFT = "collaboration_session_left"

    # Communication events
    MESSAGE_SENT = "message_sent"
    MESSAGE_DELETED = "message_deleted"
    NOTIFICATION_SENT = "notification_sent"
    NOTIFICATION_FAILED = "notification_failed"

    # Security events
    AUTHENTICATION_FAILED = "authentication_failed"
    AUTHORIZATION_FAILED = "authorization_failed"
    TOKEN_EXPIRED = "token_expired"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"

    # System events
    SERVICE_STARTED = "service_started"
    SERVICE_STOPPED = "service_stopped"
    SERVICE_ERROR = "service_error"
    CONFIGURATION_CHANGED = "configuration_changed"


@dataclass
class AuditEvent:
    """Audit event data structure."""

    event_type: AuditEventType
    timestamp: datetime
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    outcome: str = "success"  # success, failure, error
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert audit event to dictionary for logging."""
        result = asdict(self)
        result["event_type"] = self.event_type.value
        result["timestamp"] = self.timestamp.isoformat()
        return result

    def to_json(self) -> str:
        """Convert audit event to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class AuditLogger:
    """
    Centralized audit logging manager.

    Provides consistent audit logging functionality across all collaborative
    modules with configurable output formats and storage backends.
    """

    def __init__(
        self, app_builder: Any = None, logger_name: str = "collaborative.audit"
    ):
        """
        Initialize the audit logger.

        Args:
            app_builder: PgForge instance for configuration
            logger_name: Name for the audit logger
        """
        self.app_builder = app_builder
        self.audit_logger = logging.getLogger(logger_name)

        # Configuration
        self.enabled = True
        self.log_level = logging.INFO
        self.include_sensitive_data = False
        self.max_details_size = 1024 * 10  # 10KB

        # Load configuration from app if available
        if app_builder and app_builder.app:
            self._load_configuration()

        # Context tracking
        self._current_user_id: Optional[int] = None
        self._current_session_id: Optional[str] = None
        self._current_ip_address: Optional[str] = None
        self._current_user_agent: Optional[str] = None

    def _load_configuration(self) -> None:
        """Load audit logging configuration from Flask app."""
        config = self.app_builder.app.config

        self.enabled = config.get("AUDIT_LOGGING_ENABLED", True)
        self.log_level = getattr(logging, config.get("AUDIT_LOG_LEVEL", "INFO"))
        self.include_sensitive_data = config.get("AUDIT_INCLUDE_SENSITIVE_DATA", False)
        self.max_details_size = config.get("AUDIT_MAX_DETAILS_SIZE", 1024 * 10)

        # Configure audit logger level
        self.audit_logger.setLevel(self.log_level)

    def set_context(
        self,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """
        Set context information for subsequent audit events.

        Args:
            user_id: Current user ID
            session_id: Current session ID
            ip_address: Client IP address
            user_agent: Client user agent string
        """
        self._current_user_id = user_id
        self._current_session_id = session_id
        self._current_ip_address = ip_address
        self._current_user_agent = user_agent

    @contextmanager
    def audit_context(
        self,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """
        Context manager for setting audit context temporarily.

        Args:
            user_id: Current user ID
            session_id: Current session ID
            ip_address: Client IP address
            user_agent: Client user agent string
        """
        # Save current context
        old_user_id = self._current_user_id
        old_session_id = self._current_session_id
        old_ip_address = self._current_ip_address
        old_user_agent = self._current_user_agent

        try:
            # Set new context
            self.set_context(user_id, session_id, ip_address, user_agent)
            yield self
        finally:
            # Restore old context
            self.set_context(
                old_user_id, old_session_id, old_ip_address, old_user_agent
            )

    def log_event(
        self,
        event_type: AuditEventType,
        user_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        outcome: str = "success",
        message: Optional[str] = None,
        **kwargs,
    ) -> None:
        """
        Log an audit event.

        Args:
            event_type: Type of event being logged
            user_id: User ID (uses context if not provided)
            resource_type: Type of resource involved
            resource_id: ID of resource involved
            details: Additional event details
            outcome: Event outcome (success, failure, error)
            message: Human-readable message
            **kwargs: Additional fields for the audit event
        """
        if not self.enabled:
            return

        try:
            # Use context values if not explicitly provided
            user_id = user_id or self._current_user_id
            session_id = kwargs.get("session_id") or self._current_session_id
            ip_address = kwargs.get("ip_address") or self._current_ip_address
            user_agent = kwargs.get("user_agent") or self._current_user_agent

            # Clean and validate details
            if details:
                details = self._sanitize_details(details)

            # Create audit event
            event = AuditEvent(
                event_type=event_type,
                timestamp=datetime.now(),
                user_id=user_id,
                session_id=session_id,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                ip_address=ip_address,
                user_agent=user_agent,
                outcome=outcome,
                message=message,
            )

            # Log the event
            self._write_audit_event(event)

        except Exception as e:
            # Don't let audit logging failures break the application
            logger.error(f"Failed to log audit event: {e}")

    def _sanitize_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize details dictionary for logging.

        Args:
            details: Details dictionary to sanitize

        Returns:
            Sanitized details dictionary
        """
        if not details:
            return {}

        # Remove sensitive fields if not allowed
        if not self.include_sensitive_data:
            sensitive_keys = {
                "password",
                "token",
                "secret",
                "key",
                "credential",
                "auth",
                "authorization",
                "jwt",
                "session_key",
            }
            details = {
                k: v
                for k, v in details.items()
                if not any(sensitive in k.lower() for sensitive in sensitive_keys)
            }

        # Check size limit
        try:
            details_json = json.dumps(details, default=str)
            if len(details_json) > self.max_details_size:
                # Truncate details if too large
                details = {"_truncated": True, "_original_size": len(details_json)}
                logger.warning(
                    f"Audit event details truncated due to size: {len(details_json)} bytes"
                )

        except (TypeError, ValueError):
            # If details can't be serialized, replace with summary
            details = {
                "_error": "Details not serializable",
                "_type": str(type(details)),
            }

        return details

    def _write_audit_event(self, event: AuditEvent) -> None:
        """
        Write audit event to configured output.

        Args:
            event: Audit event to write
        """
        # Format log message
        log_message = f"AUDIT: {event.event_type.value}"
        if event.user_id:
            log_message += f" | User: {event.user_id}"
        if event.resource_type and event.resource_id:
            log_message += f" | Resource: {event.resource_type}:{event.resource_id}"
        if event.outcome != "success":
            log_message += f" | Outcome: {event.outcome}"
        if event.message:
            log_message += f" | {event.message}"

        # Log with structured data as extra
        extra_data = {
            "audit_event": event.to_dict(),
            "event_type": event.event_type.value,
            "outcome": event.outcome,
        }

        # Choose log level based on outcome
        if event.outcome == "error":
            log_level = logging.ERROR
        elif event.outcome == "failure":
            log_level = logging.WARNING
        else:
            log_level = self.log_level

        self.audit_logger.log(log_level, log_message, extra=extra_data)

    # Convenience methods for common audit events
    def log_user_action(
        self,
        action: str,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        """Log a user action event."""
        event_type = (
            AuditEventType.USER_LOGIN
            if action == "login"
            else AuditEventType.USER_LOGOUT
        )
        self.log_event(event_type, user_id=user_id, details=details, **kwargs)

    def log_team_event(
        self,
        action: str,
        team_id: str,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        """Log a team-related event."""
        event_map = {
            "created": AuditEventType.TEAM_CREATED,
            "updated": AuditEventType.TEAM_UPDATED,
            "deleted": AuditEventType.TEAM_DELETED,
            "member_added": AuditEventType.TEAM_MEMBER_ADDED,
            "member_removed": AuditEventType.TEAM_MEMBER_REMOVED,
            "member_role_changed": AuditEventType.TEAM_MEMBER_ROLE_CHANGED,
        }
        event_type = event_map.get(action, AuditEventType.TEAM_UPDATED)
        self.log_event(
            event_type,
            user_id=user_id,
            resource_type="team",
            resource_id=team_id,
            details=details,
            **kwargs,
        )

    def log_workspace_event(
        self,
        action: str,
        workspace_id: str,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        """Log a workspace-related event."""
        event_map = {
            "created": AuditEventType.WORKSPACE_CREATED,
            "updated": AuditEventType.WORKSPACE_UPDATED,
            "deleted": AuditEventType.WORKSPACE_DELETED,
            "access_granted": AuditEventType.WORKSPACE_ACCESS_GRANTED,
            "access_revoked": AuditEventType.WORKSPACE_ACCESS_REVOKED,
        }
        event_type = event_map.get(action, AuditEventType.WORKSPACE_UPDATED)
        self.log_event(
            event_type,
            user_id=user_id,
            resource_type="workspace",
            resource_id=workspace_id,
            details=details,
            **kwargs,
        )

    def log_security_event(
        self,
        event_type: AuditEventType,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        outcome: str = "failure",
        **kwargs,
    ) -> None:
        """Log a security-related event."""
        self.log_event(
            event_type, user_id=user_id, details=details, outcome=outcome, **kwargs
        )


class CollaborativeAuditMixin:
    """
    Mixin class for adding audit logging capabilities to collaborative services.

    Provides consistent audit logging methods that can be mixed into any
    collaborative service class.
    """

    def __init__(self, *args, **kwargs):
        """Initialize audit mixin."""
        super().__init__(*args, **kwargs)
        self._audit_logger: Optional[AuditLogger] = None

    @property
    def audit_logger(self) -> AuditLogger:
        """Get or create audit logger instance."""
        if self._audit_logger is None:
            app_builder = getattr(self, "app_builder", None)
            self._audit_logger = AuditLogger(app_builder)
        return self._audit_logger

    def audit_event(self, event_type: AuditEventType, **kwargs) -> None:
        """
        Log an audit event for this service.

        Args:
            event_type: Type of event to log
            **kwargs: Additional audit event parameters
        """
        self.audit_logger.log_event(event_type, **kwargs)

    def audit_user_action(
        self, action: str, user_id: Optional[int] = None, **kwargs
    ) -> None:
        """Log a user action audit event."""
        self.audit_logger.log_user_action(action, user_id=user_id, **kwargs)

    def audit_security_event(
        self,
        event_type: AuditEventType,
        user_id: Optional[int] = None,
        outcome: str = "failure",
        **kwargs,
    ) -> None:
        """Log a security audit event."""
        self.audit_logger.log_security_event(
            event_type, user_id=user_id, outcome=outcome, **kwargs
        )

    def audit_service_event(
        self, action: str, outcome: str = "success", **kwargs
    ) -> None:
        """Log a service-related audit event."""
        service_name = self.__class__.__name__
        event_map = {
            "started": AuditEventType.SERVICE_STARTED,
            "stopped": AuditEventType.SERVICE_STOPPED,
            "error": AuditEventType.SERVICE_ERROR,
        }
        event_type = event_map.get(action, AuditEventType.SERVICE_ERROR)
        self.audit_logger.log_event(
            event_type,
            resource_type="service",
            resource_id=service_name,
            outcome=outcome,
            **kwargs,
        )
