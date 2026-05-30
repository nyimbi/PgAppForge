"""
Workspace Manager

Comprehensive workspace management system for PgAppForge collaborative features.
Handles shared workspaces, resource management, access control, and workspace-level
collaboration features with multi-tenancy support.
"""

import uuid
import json
from typing import Dict, List, Any, Optional, Set, Union, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
import logging
from collections import defaultdict
from pathlib import Path
from contextlib import contextmanager

from flask import Flask, g, current_app
from pgappforge import AppBuilder
from pgappforge.security import BaseSecurityManager
from pgappforge.models.sqla import Model
from pgappforge.models.mixins import AuditMixin
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import relationship, Session
from sqlalchemy.ext.declarative import declarative_base

from .team_manager import TeamManager, TeamPermission, Team
from .collaboration_engine import CollaborationEngine
from pgappforge.security.sqla.models import User
from ..utils.slug_generator import generate_workspace_slug, create_uniqueness_checker

logger = logging.getLogger(__name__)


class WorkspaceType(Enum):
    """Workspace types"""

    PERSONAL = "personal"
    TEAM = "team"
    PROJECT = "project"
    DEPARTMENT = "department"
    ORGANIZATION = "organization"
    PUBLIC = "public"


class ResourceType(Enum):
    """Resource types in workspaces"""

    DOCUMENT = "document"
    FORM = "form"
    REPORT = "report"
    DASHBOARD = "dashboard"
    VIEW = "view"
    MODEL = "model"
    CHART = "chart"
    FOLDER = "folder"
    FILE = "file"
    LINK = "link"


class AccessLevel(Enum):
    """Access levels for workspace resources"""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    OWNER = "owner"


class ShareScope(Enum):
    """Sharing scope options"""

    PRIVATE = "private"
    TEAM = "team"
    ORGANIZATION = "organization"
    PUBLIC = "public"
    CUSTOM = "custom"


@dataclass
class WorkspaceConfig:
    """Workspace configuration"""

    max_resources: int = 1000
    max_collaborators: int = 100
    enable_version_control: bool = True
    enable_real_time_sync: bool = True
    enable_comments: bool = True
    enable_notifications: bool = True
    auto_save_interval: int = 30  # seconds
    retention_days: int = 90
    allow_external_sharing: bool = False
    require_approval_for_access: bool = False


@dataclass
class ResourceMetadata:
    """Resource metadata structure"""

    title: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    category: str = ""
    version: str = "1.0"
    size_bytes: int = 0
    mime_type: str = ""
    encoding: str = "utf-8"
    custom_fields: Dict[str, Any] = field(default_factory=dict)


# Database models
Base = declarative_base()


class Workspace(Model, AuditMixin):
    """Workspace model with PgAppForge integration"""

    __tablename__ = "fab_workspaces"

    id = Column(Integer, primary_key=True)
    uuid = Column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )

    # Basic information
    name = Column(String(200), nullable=False)
    description = Column(Text)
    slug = Column(String(100), nullable=False)
    workspace_type = Column(String(50), nullable=False)

    # Access control
    is_public = Column(Boolean, default=False)
    share_scope = Column(String(50), default=ShareScope.PRIVATE.value)
    require_approval = Column(Boolean, default=False)

    # Configuration
    config = Column(JSON)

    # Team relationship
    team_id = Column(Integer, ForeignKey("fab_teams.id"))

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    team = relationship("Team", foreign_keys=[team_id])
    resources = relationship(
        "WorkspaceResource", back_populates="workspace", cascade="all, delete-orphan"
    )
    members = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )
    activity_log = relationship(
        "WorkspaceActivity", back_populates="workspace", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("ix_workspace_team", "team_id"),
        Index("ix_workspace_type", "workspace_type"),
        Index("ix_workspace_public", "is_public"),
        Index("ix_workspace_slug", "slug", unique=True),
    )

    def __repr__(self):
        return f"<Workspace {self.name}>"


class WorkspaceResource(Model, AuditMixin):
    """Workspace resource model with PgAppForge integration"""

    __tablename__ = "fab_workspace_resources"

    id = Column(Integer, primary_key=True)
    uuid = Column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )

    # Basic information
    name = Column(String(200), nullable=False)
    resource_type = Column(String(50), nullable=False)
    path = Column(String(500))  # Virtual path within workspace

    # Content
    content = Column(Text)  # For text-based resources
    content_hash = Column(String(64))  # For integrity checking
    meta_data = Column(JSON)  # Resource metadata

    # Relationships
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("fab_workspace_resources.id"))  # For folders

    # Access and versioning
    is_public = Column(Boolean, default=False)
    is_locked = Column(Boolean, default=False)
    locked_by_id = Column(Integer, ForeignKey("ab_user.id"))
    version = Column(Integer, default=1)

    # Timestamps - last_accessed handled separately from AuditMixin
    last_accessed = Column(DateTime, default=datetime.now)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    workspace = relationship("Workspace", back_populates="resources")
    locked_by = relationship("User", foreign_keys=[locked_by_id])
    parent = relationship("WorkspaceResource", remote_side=[id])
    children = relationship("WorkspaceResource", cascade="all, delete-orphan")
    versions = relationship(
        "ResourceVersion", back_populates="resource", cascade="all, delete-orphan"
    )
    permissions = relationship(
        "ResourcePermission", back_populates="resource", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("ix_resource_workspace", "workspace_id"),
        Index("ix_resource_type", "resource_type"),
        Index("ix_resource_parent", "parent_id"),
        Index("ix_resource_path", "workspace_id", "path"),
    )


class WorkspaceMember(Model, AuditMixin):
    """Workspace member model with PgAppForge integration"""

    __tablename__ = "fab_workspace_members"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)

    # Access control
    access_level = Column(String(20), nullable=False)
    invited_by_id = Column(Integer, ForeignKey("ab_user.id"))

    # Status
    is_active = Column(Boolean, default=True)
    joined_at = Column(DateTime, default=datetime.now)
    last_activity = Column(DateTime, default=datetime.now)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    invited_by = relationship("User", foreign_keys=[invited_by_id])

    # Constraints
    __table_args__ = (
        Index("ix_workspace_member", "workspace_id", "user_id", unique=True),
    )


class ResourceVersion(Model, AuditMixin):
    """Resource version history with PgAppForge integration"""

    __tablename__ = "fab_resource_versions"

    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("fab_workspace_resources.id"), nullable=False)

    # Version information
    version_number = Column(Integer, nullable=False)
    content = Column(Text)
    content_hash = Column(String(64))
    meta_data = Column(JSON)

    # Change tracking
    changed_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    change_summary = Column(String(500))

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    resource = relationship("WorkspaceResource", back_populates="versions")
    changed_by = relationship("User", foreign_keys=[changed_by_id])

    # Indexes
    __table_args__ = (
        Index("ix_version_resource", "resource_id"),
        Index("ix_version_number", "resource_id", "version_number", unique=True),
    )


class ResourcePermission(Model, AuditMixin):
    """Resource-level permissions with PgAppForge integration"""

    __tablename__ = "fab_resource_permissions"

    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("fab_workspace_resources.id"), nullable=False)

    # Subject (user or team)
    user_id = Column(Integer, ForeignKey("ab_user.id"))
    team_id = Column(Integer, ForeignKey("fab_teams.id"))

    # Permission details
    permission_type = Column(String(50), nullable=False)
    granted_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime)

    # Grant tracking
    granted_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    resource = relationship("WorkspaceResource", back_populates="permissions")
    user = relationship("User", foreign_keys=[user_id])
    team = relationship("Team", foreign_keys=[team_id])
    granted_by = relationship("User", foreign_keys=[granted_by_id])

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND team_id IS NULL) OR "
            "(user_id IS NULL AND team_id IS NOT NULL)",
            name="check_permission_subject"
        ),
        Index("ix_resource_permission_user", "resource_id", "user_id"),
        Index("ix_resource_permission_team", "resource_id", "team_id"),
    )


class WorkspaceActivity(Model, AuditMixin):
    """Workspace activity log with PgAppForge integration"""

    __tablename__ = "fab_workspace_activity"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=False)

    # Activity details
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    action = Column(String(100), nullable=False)
    resource_id = Column(Integer, ForeignKey("fab_workspace_resources.id"))

    # Data
    details = Column(JSON)
    ip_address = Column(String(45))
    user_agent = Column(String(500))

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    workspace = relationship("Workspace", back_populates="activity_log")
    user = relationship("User", foreign_keys=[user_id])
    resource = relationship("WorkspaceResource", foreign_keys=[resource_id])

    # Indexes
    __table_args__ = (
        Index("ix_activity_workspace", "workspace_id"),
        Index("ix_activity_user", "user_id"),
        Index("ix_activity_created", "created_on"),
    )


class WorkspaceManager:
    """
    Comprehensive workspace management system.

    Features:
    - Multi-tenant workspace isolation
    - Resource management with versioning
    - Fine-grained access control
    - Real-time collaboration integration
    - Activity tracking and audit logs
    - Flexible sharing and permissions
    """

    def __init__(
        self,
        app_builder: AppBuilder,
        team_manager: TeamManager,
        collaboration_engine: CollaborationEngine,
    ):
        self.app_builder = app_builder
        self.app = app_builder.app
        self.db = app_builder.get_session
        self.security_manager = app_builder.sm
        self.team_manager = team_manager
        self.collaboration_engine = collaboration_engine

        # Configuration
        self.default_config = WorkspaceConfig()

        # Setup integration
        self._setup_collaboration_integration()

    def _setup_collaboration_integration(self) -> None:
        """Setup integration with collaboration engine"""
        # Register workspace events with collaboration engine
        pass

    @contextmanager
    def _database_transaction(self, retry_count=3, isolation_level="READ COMMITTED"):
        """Context manager for database transactions with concurrent access handling"""
        session = self.db()
        attempt = 0
        savepoint = None

        while attempt < retry_count:
            try:
                # Set transaction isolation level
                from sqlalchemy import text

                session.execute(
                    text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}")
                )

                # Create savepoint for complex operations
                if attempt > 0:
                    savepoint = session.begin_nested()

                yield session

                # Commit the transaction
                if savepoint:
                    savepoint.commit()
                session.commit()
                return  # Success

            except Exception as e:
                # Handle rollback
                if savepoint:
                    try:
                        savepoint.rollback()
                    except Exception:
                        pass

                session.rollback()

                # Check if retryable error
                if self._is_retryable_db_error(e) and attempt < retry_count - 1:
                    attempt += 1
                    retry_delay = min(0.1 * (2**attempt), 2.0)
                    logger.warning(
                        f"Workspace DB error (attempt {attempt}/{retry_count}), retrying in {retry_delay}s: {e}"
                    )

                    # Close failed session and create new one
                    session.close()
                    session = self.db()

                    import time

                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(
                        f"Workspace transaction failed after {attempt + 1} attempts: {e}"
                    )
                    # Cleanup any partial workspace resources before raising
                    self._cleanup_failed_workspace_operation(e)
                    raise

        raise RuntimeError(f"Workspace transaction failed after {retry_count} attempts")

    def _is_retryable_db_error(self, error: Exception) -> bool:
        """Determine if database error is retryable (same logic as team_manager)"""
        from sqlalchemy.exc import (
            OperationalError,
            DisconnectionError,
            TimeoutError,
            IntegrityError,
        )

        error_str = str(error).lower()

        if isinstance(error, (OperationalError, DisconnectionError, TimeoutError)):
            return True

        retryable_messages = [
            "deadlock detected",
            "lock wait timeout",
            "connection lost",
            "server has gone away",
            "connection reset",
            "database is locked",
            "could not serialize access",
        ]

        return any(message in error_str for message in retryable_messages)

    def _cleanup_failed_workspace_operation(self, error: Exception) -> None:
        """Clean up resources after failed workspace operation"""
        try:
            # Log the failure for monitoring
            logger.error(f"Workspace operation failed, performing cleanup: {error}")

            # Here you would clean up any workspace-specific resources
            # that might have been created before the failure
            # Examples: temporary files, cache entries, external service registrations

        except Exception as cleanup_error:
            logger.error(f"Error during workspace cleanup: {cleanup_error}")

    def create_workspace(
        self,
        name: str,
        owner_id: int,
        workspace_type: WorkspaceType = WorkspaceType.PERSONAL,
        description: str = "",
        team_id: Optional[int] = None,
        config: Optional[WorkspaceConfig] = None,
    ) -> Optional[Workspace]:
        """
        Create a new workspace.

        Args:
            name: Workspace name
            owner_id: Owner user ID
            workspace_type: Type of workspace
            description: Workspace description
            team_id: Associated team ID (if any)
            config: Workspace configuration

        Returns:
            Created workspace or None if failed
        """
        try:
            config = config or self.default_config

            # Generate unique slug using shared utility
            uniqueness_checker = create_uniqueness_checker(
                self.session_factory, Workspace, slug_field="slug"
            )
            slug = generate_workspace_slug(name, uniqueness_checker)

            with self._database_transaction() as session:
                workspace = Workspace(
                    name=name,
                    description=description,
                    slug=slug,
                    workspace_type=workspace_type.value,
                    owner_id=owner_id,
                    team_id=team_id,
                    config=asdict(config),
                )

                session.add(workspace)
                session.flush()  # Get the ID before committing

                # Add owner as admin member (within same transaction)
                self._add_workspace_member_in_session(
                    session, workspace.id, owner_id, AccessLevel.OWNER
                )

                # Create default folder structure (within same transaction)
                self._create_default_structure_in_session(
                    session, workspace.id, owner_id
                )

                # Log activity (within same transaction)
                self._log_activity_in_session(
                    session,
                    workspace.id,
                    owner_id,
                    "workspace_created",
                    details={"workspace_type": workspace_type.value},
                )

                # Transaction is automatically committed by context manager

            logger.info(
                f"Created workspace '{name}' (ID: {workspace.id}) by user {owner_id}"
            )
            return workspace

        except Exception as e:
            logger.error(f"Error creating workspace: {e}")
            return None

    def get_workspace(self, workspace_id: int) -> Optional[Workspace]:
        """Get workspace by ID"""
        try:
            session = self.db()
            return session.query(Workspace).filter(Workspace.id == workspace_id).first()
        except Exception as e:
            logger.error(f"Error getting workspace {workspace_id}: {e}")
            return None

    def get_workspace_by_uuid(self, workspace_uuid: str) -> Optional[Workspace]:
        """Get workspace by UUID"""
        try:
            session = self.db()
            return (
                session.query(Workspace)
                .filter(Workspace.uuid == workspace_uuid)
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting workspace by UUID {workspace_uuid}: {e}")
            return None

    def get_user_workspaces(
        self, user_id: int, workspace_type: Optional[WorkspaceType] = None
    ) -> List[Dict[str, Any]]:
        """Get all workspaces accessible to a user"""
        try:
            session = self.db()

            # Query workspaces where user is a member
            query = (
                session.query(Workspace, WorkspaceMember.access_level)
                .join(WorkspaceMember, Workspace.id == WorkspaceMember.workspace_id)
                .filter(
                    WorkspaceMember.user_id == user_id,
                    WorkspaceMember.is_active == True,
                )
            )

            if workspace_type:
                query = query.filter(Workspace.workspace_type == workspace_type.value)

            workspaces = []
            for workspace, access_level in query.all():
                workspaces.append(
                    {
                        "workspace": workspace,
                        "access_level": AccessLevel(access_level),
                        "member_count": self.get_workspace_member_count(workspace.id),
                        "resource_count": self.get_workspace_resource_count(
                            workspace.id
                        ),
                    }
                )

            return workspaces

        except Exception as e:
            logger.error(f"Error getting user workspaces for {user_id}: {e}")
            return []

    def add_workspace_member(
        self,
        workspace_id: int,
        user_id: int,
        access_level: AccessLevel,
        invited_by_id: Optional[int] = None,
    ) -> bool:
        """
        Add a member to a workspace.

        Args:
            workspace_id: Workspace ID
            user_id: User to add
            access_level: Access level to grant
            invited_by_id: User who invited (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            session = self.db()

            # Check if user is already a member
            existing = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                    WorkspaceMember.is_active == True,
                )
                .first()
            )

            if existing:
                # Update access level if different
                if existing.access_level != access_level.value:
                    existing.access_level = access_level.value
                    existing.last_activity = datetime.now()
                    session.commit()
                return True

            # Check workspace capacity
            workspace = self.get_workspace(workspace_id)
            if not workspace:
                return False

            config = (
                WorkspaceConfig(**workspace.config)
                if workspace.config
                else self.default_config
            )
            member_count = self.get_workspace_member_count(workspace_id)

            if member_count >= config.max_collaborators:
                logger.warning(
                    f"Workspace {workspace_id} at capacity ({config.max_collaborators} members)"
                )
                return False

            # Add member
            member = WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user_id,
                access_level=access_level.value,
                invited_by_id=invited_by_id,
            )

            session.add(member)
            session.commit()

            # Log activity
            self._log_activity(
                workspace_id,
                invited_by_id or user_id,
                "member_added",
                details={"user_id": user_id, "access_level": access_level.value},
            )

            logger.info(
                f"Added user {user_id} to workspace {workspace_id} with access {access_level.value}"
            )
            return True

        except Exception as e:
            logger.error(f"Error adding workspace member: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def remove_workspace_member(
        self, workspace_id: int, user_id: int, removed_by_id: int
    ) -> bool:
        """Remove a member from a workspace"""
        try:
            # Check permissions
            if not self.has_workspace_access(
                removed_by_id, workspace_id, AccessLevel.ADMIN
            ):
                return False

            session = self.db()

            # Don't allow removing the owner
            workspace = self.get_workspace(workspace_id)
            if workspace and workspace.owner_id == user_id:
                logger.warning(f"Cannot remove owner from workspace {workspace_id}")
                return False

            # Deactivate membership
            member = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
                .first()
            )

            if member:
                member.is_active = False
                session.commit()

                # Log activity
                self._log_activity(
                    workspace_id,
                    removed_by_id,
                    "member_removed",
                    details={"user_id": user_id},
                )

                logger.info(f"Removed user {user_id} from workspace {workspace_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error removing workspace member: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def create_resource(
        self,
        workspace_id: int,
        name: str,
        resource_type: ResourceType,
        created_by_id: int,
        content: str = "",
        metadata: Optional[ResourceMetadata] = None,
        parent_id: Optional[int] = None,
        path: Optional[str] = None,
    ) -> Optional[WorkspaceResource]:
        """
        Create a resource in a workspace.

        Args:
            workspace_id: Workspace ID
            name: Resource name
            resource_type: Type of resource
            created_by_id: User creating the resource
            content: Resource content
            metadata: Resource metadata
            parent_id: Parent resource ID (for folders)
            path: Virtual path in workspace

        Returns:
            Created resource or None if failed
        """
        try:
            # Check permissions
            if not self.has_workspace_access(
                created_by_id, workspace_id, AccessLevel.WRITE
            ):
                return None

            # Check workspace capacity
            workspace = self.get_workspace(workspace_id)
            if not workspace:
                return None

            config = (
                WorkspaceConfig(**workspace.config)
                if workspace.config
                else self.default_config
            )
            resource_count = self.get_workspace_resource_count(workspace_id)

            if resource_count >= config.max_resources:
                logger.warning(
                    f"Workspace {workspace_id} at resource capacity ({config.max_resources})"
                )
                return None

            # Generate path if not provided
            if not path:
                path = self._generate_resource_path(workspace_id, name, parent_id)

            # Calculate content hash
            content_hash = self._calculate_content_hash(content)

            resource = WorkspaceResource(
                workspace_id=workspace_id,
                name=name,
                resource_type=resource_type.value,
                path=path,
                content=content,
                content_hash=content_hash,
                metadata=asdict(metadata) if metadata else {},
                parent_id=parent_id,
                created_by_id=created_by_id,
            )

            session = self.db()
            session.add(resource)
            session.commit()

            # Create initial version
            self._create_resource_version(
                resource.id, content, content_hash, created_by_id, "Initial version"
            )

            # Log activity
            self._log_activity(
                workspace_id,
                created_by_id,
                "resource_created",
                resource_id=resource.id,
                details={"name": name, "type": resource_type.value},
            )

            logger.info(f"Created resource '{name}' in workspace {workspace_id}")
            return resource

        except Exception as e:
            logger.error(f"Error creating resource: {e}")
            if "session" in locals():
                session.rollback()
            return None

    def update_resource(
        self,
        resource_id: int,
        updated_by_id: int,
        content: Optional[str] = None,
        metadata: Optional[ResourceMetadata] = None,
        change_summary: str = "",
    ) -> bool:
        """
        Update a workspace resource.

        Args:
            resource_id: Resource ID
            updated_by_id: User making the update
            content: New content (optional)
            metadata: Updated metadata (optional)
            change_summary: Summary of changes

        Returns:
            True if successful, False otherwise
        """
        try:
            session = self.db()
            resource = (
                session.query(WorkspaceResource)
                .filter(WorkspaceResource.id == resource_id)
                .first()
            )

            if not resource:
                return False

            # Check permissions
            if not self.has_resource_access(
                updated_by_id, resource_id, AccessLevel.WRITE
            ):
                return False

            # Check if resource is locked
            if resource.is_locked and resource.locked_by_id != updated_by_id:
                logger.warning(
                    f"Resource {resource_id} is locked by user {resource.locked_by_id}"
                )
                return False

            updated = False

            # Update content if provided
            if content is not None and content != resource.content:
                old_content = resource.content
                old_hash = resource.content_hash

                resource.content = content
                resource.content_hash = self._calculate_content_hash(content)
                resource.version += 1
                resource.updated_at = datetime.now()

                # Create version record
                self._create_resource_version(
                    resource_id, old_content, old_hash, updated_by_id, change_summary
                )

                updated = True

            # Update metadata if provided
            if metadata is not None:
                resource.metadata = asdict(metadata)
                resource.updated_at = datetime.now()
                updated = True

            if updated:
                session.commit()

                # Log activity
                self._log_activity(
                    resource.workspace_id,
                    updated_by_id,
                    "resource_updated",
                    resource_id=resource_id,
                    details={"change_summary": change_summary},
                )

                logger.info(f"Updated resource {resource_id} by user {updated_by_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error updating resource: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def delete_resource(self, resource_id: int, deleted_by_id: int) -> bool:
        """Delete a workspace resource"""
        try:
            session = self.db()
            resource = (
                session.query(WorkspaceResource)
                .filter(WorkspaceResource.id == resource_id)
                .first()
            )

            if not resource:
                return False

            # Check permissions
            if not self.has_resource_access(
                deleted_by_id, resource_id, AccessLevel.ADMIN
            ):
                return False

            # Check if resource is locked
            if resource.is_locked and resource.locked_by_id != deleted_by_id:
                return False

            workspace_id = resource.workspace_id
            resource_name = resource.name

            # Delete resource (cascades to versions and permissions)
            session.delete(resource)
            session.commit()

            # Log activity
            self._log_activity(
                workspace_id,
                deleted_by_id,
                "resource_deleted",
                details={"name": resource_name},
            )

            logger.info(f"Deleted resource {resource_id} by user {deleted_by_id}")
            return True

        except Exception as e:
            logger.error(f"Error deleting resource: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def lock_resource(self, resource_id: int, user_id: int) -> bool:
        """Lock a resource for exclusive editing"""
        try:
            session = self.db()
            resource = (
                session.query(WorkspaceResource)
                .filter(WorkspaceResource.id == resource_id)
                .first()
            )

            if not resource:
                return False

            # Check permissions
            if not self.has_resource_access(user_id, resource_id, AccessLevel.WRITE):
                return False

            # Check if already locked
            if resource.is_locked and resource.locked_by_id != user_id:
                return False

            # Lock resource
            resource.is_locked = True
            resource.locked_by_id = user_id
            session.commit()

            # Log activity
            self._log_activity(
                resource.workspace_id,
                user_id,
                "resource_locked",
                resource_id=resource_id,
            )

            logger.debug(f"Locked resource {resource_id} by user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error locking resource: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def unlock_resource(self, resource_id: int, user_id: int) -> bool:
        """Unlock a resource"""
        try:
            session = self.db()
            resource = (
                session.query(WorkspaceResource)
                .filter(WorkspaceResource.id == resource_id)
                .first()
            )

            if not resource:
                return False

            # Check if user can unlock (owner or admin)
            if resource.locked_by_id != user_id:
                if not self.has_resource_access(
                    user_id, resource_id, AccessLevel.ADMIN
                ):
                    return False

            # Unlock resource
            resource.is_locked = False
            resource.locked_by_id = None
            session.commit()

            # Log activity
            self._log_activity(
                resource.workspace_id,
                user_id,
                "resource_unlocked",
                resource_id=resource_id,
            )

            logger.debug(f"Unlocked resource {resource_id} by user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error unlocking resource: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def has_workspace_access(
        self, user_id: int, workspace_id: int, required_level: AccessLevel
    ) -> bool:
        """Check if user has required access level to workspace"""
        try:
            session = self.db()

            # Check workspace membership
            member = (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                    WorkspaceMember.is_active == True,
                )
                .first()
            )

            if not member:
                # Check if workspace is public
                workspace = self.get_workspace(workspace_id)
                if (
                    workspace
                    and workspace.is_public
                    and required_level == AccessLevel.READ
                ):
                    return True
                return False

            # Check access level hierarchy
            user_level = AccessLevel(member.access_level)
            return self._access_level_sufficient(user_level, required_level)

        except Exception as e:
            logger.error(f"Error checking workspace access: {e}")
            return False

    def has_resource_access(
        self, user_id: int, resource_id: int, required_level: AccessLevel
    ) -> bool:
        """Check if user has required access level to resource"""
        try:
            session = self.db()
            resource = (
                session.query(WorkspaceResource)
                .filter(WorkspaceResource.id == resource_id)
                .first()
            )

            if not resource:
                return False

            # Check workspace access first
            workspace_access = self.has_workspace_access(
                user_id, resource.workspace_id, required_level
            )

            # Check resource-specific permissions
            resource_permission = (
                session.query(ResourcePermission)
                .filter(
                    ResourcePermission.resource_id == resource_id,
                    ResourcePermission.user_id == user_id,
                )
                .first()
            )

            if resource_permission:
                resource_level = AccessLevel(resource_permission.access_level)
                if self._access_level_sufficient(resource_level, required_level):
                    return True

            return workspace_access

        except Exception as e:
            logger.error(f"Error checking resource access: {e}")
            return False

    def get_workspace_resources(
        self,
        workspace_id: int,
        user_id: int,
        parent_id: Optional[int] = None,
        resource_type: Optional[ResourceType] = None,
    ) -> List[WorkspaceResource]:
        """Get resources in a workspace"""
        try:
            # Check access
            if not self.has_workspace_access(user_id, workspace_id, AccessLevel.READ):
                return []

            session = self.db()
            query = session.query(WorkspaceResource).filter(
                WorkspaceResource.workspace_id == workspace_id,
                WorkspaceResource.parent_id == parent_id,
            )

            if resource_type:
                query = query.filter(
                    WorkspaceResource.resource_type == resource_type.value
                )

            return query.order_by(WorkspaceResource.name).all()

        except Exception as e:
            logger.error(f"Error getting workspace resources: {e}")
            return []

    def get_workspace_member_count(self, workspace_id: int) -> int:
        """Get active member count for workspace"""
        try:
            session = self.db()
            return (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.is_active == True,
                )
                .count()
            )
        except Exception as e:
            logger.error(f"Error getting workspace member count: {e}")
            return 0

    def get_workspace_resource_count(self, workspace_id: int) -> int:
        """Get resource count for workspace"""
        try:
            session = self.db()
            return (
                session.query(WorkspaceResource)
                .filter(WorkspaceResource.workspace_id == workspace_id)
                .count()
            )
        except Exception as e:
            logger.error(f"Error getting workspace resource count: {e}")
            return 0

    def get_workspace_activity(
        self, workspace_id: int, user_id: int, limit: int = 50
    ) -> List[WorkspaceActivity]:
        """Get recent workspace activity"""
        try:
            # Check access
            if not self.has_workspace_access(user_id, workspace_id, AccessLevel.READ):
                return []

            session = self.db()
            return (
                session.query(WorkspaceActivity)
                .filter(WorkspaceActivity.workspace_id == workspace_id)
                .order_by(WorkspaceActivity.created_on.desc())
                .limit(limit)
                .all()
            )

        except Exception as e:
            logger.error(f"Error getting workspace activity: {e}")
            return []

    def _access_level_sufficient(
        self, user_level: AccessLevel, required_level: AccessLevel
    ) -> bool:
        """Check if user access level meets requirement"""
        level_hierarchy = {
            AccessLevel.NONE: 0,
            AccessLevel.READ: 1,
            AccessLevel.WRITE: 2,
            AccessLevel.ADMIN: 3,
            AccessLevel.OWNER: 4,
        }

        return level_hierarchy.get(user_level, 0) >= level_hierarchy.get(
            required_level, 0
        )

    # Slug generation now handled by shared utility in utils/slug_generator.py
    # Removed duplicate _generate_workspace_slug method

    def _generate_resource_path(
        self, workspace_id: int, name: str, parent_id: Optional[int]
    ) -> str:
        """Generate resource path within workspace"""
        if not parent_id:
            return f"/{name}"

        # Get parent path
        session = self.db()
        parent = (
            session.query(WorkspaceResource)
            .filter(
                WorkspaceResource.id == parent_id,
                WorkspaceResource.workspace_id == workspace_id,
            )
            .first()
        )

        if parent:
            return f"{parent.path}/{name}"

        return f"/{name}"

    def _calculate_content_hash(self, content: str) -> str:
        """Calculate SHA-256 hash of content"""
        import hashlib

        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _create_resource_version(
        self,
        resource_id: int,
        content: str,
        content_hash: str,
        changed_by_id: int,
        change_summary: str,
    ) -> None:
        """Create a resource version record"""
        try:
            session = self.db()

            # Get current version number
            latest_version = (
                session.query(ResourceVersion)
                .filter(ResourceVersion.resource_id == resource_id)
                .order_by(ResourceVersion.version_number.desc())
                .first()
            )

            version_number = (
                (latest_version.version_number + 1) if latest_version else 1
            )

            version = ResourceVersion(
                resource_id=resource_id,
                version_number=version_number,
                content=content,
                content_hash=content_hash,
                changed_by_id=changed_by_id,
                change_summary=change_summary,
            )

            session.add(version)
            session.commit()

        except Exception as e:
            logger.error(f"Error creating resource version: {e}")

    def _create_default_structure(self, workspace_id: int, user_id: int) -> None:
        """Create default folder structure for new workspace"""
        try:
            # Create default folders
            default_folders = [
                ("Documents", "Store documents and files"),
                ("Reports", "Generated reports and dashboards"),
                ("Shared", "Shared resources and templates"),
            ]

            for folder_name, folder_desc in default_folders:
                metadata = ResourceMetadata(
                    title=folder_name, description=folder_desc, category="system"
                )

                self.create_resource(
                    workspace_id=workspace_id,
                    name=folder_name,
                    resource_type=ResourceType.FOLDER,
                    created_by_id=user_id,
                    metadata=metadata,
                )

        except Exception as e:
            logger.error(f"Error creating default structure: {e}")

    def _log_activity(
        self,
        workspace_id: int,
        user_id: int,
        action: str,
        resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log workspace activity"""
        try:
            from flask import request

            activity = WorkspaceActivity(
                workspace_id=workspace_id,
                user_id=user_id,
                action=action,
                resource_id=resource_id,
                details=details or {},
                ip_address=request.remote_addr if request else None,
                user_agent=str(request.user_agent) if request else None,
            )

            session = self.db()
            session.add(activity)
            session.commit()

        except Exception as e:
            logger.error(f"Error logging activity: {e}")

    def get_workspace_stats(self, workspace_id: int) -> Dict[str, Any]:
        """Get workspace statistics"""
        try:
            workspace = self.get_workspace(workspace_id)
            if not workspace:
                return {}

            return {
                "name": workspace.name,
                "type": workspace.workspace_type,
                "created_at": workspace.created_on.isoformat(),
                "member_count": self.get_workspace_member_count(workspace_id),
                "resource_count": self.get_workspace_resource_count(workspace_id),
                "last_accessed": workspace.last_accessed.isoformat()
                if workspace.last_accessed
                else None,
                "is_public": workspace.is_public,
                "owner_id": workspace.owner_id,
            }

        except Exception as e:
            logger.error(f"Error getting workspace stats: {e}")
            return {}
