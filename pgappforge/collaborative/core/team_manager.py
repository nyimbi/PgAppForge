"""
Team Manager

Advanced team management system for PgAppForge collaborative features.
Extends PgAppForge's security with team-based permissions, hierarchies,
and collaborative access control.
"""

import uuid
from typing import Dict, List, Any, Optional, Set, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging
from collections import defaultdict
from contextlib import contextmanager

from flask import Flask, current_app
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
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, Session, joinedload, selectinload
from sqlalchemy import func, and_, or_, case

# Import shared slug generation utility
from ..utils.slug_generator import (
    generate_team_slug,
    generate_workspace_slug,
    create_uniqueness_checker,
    SlugGenerationStrategy,
)

logger = logging.getLogger(__name__)


class TeamRole(Enum):
    """Team role types"""

    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"
    VIEWER = "viewer"
    GUEST = "guest"


class TeamPermission(Enum):
    """Team-specific permissions"""

    # Team management
    MANAGE_TEAM = "manage_team"
    INVITE_MEMBERS = "invite_members"
    REMOVE_MEMBERS = "remove_members"
    MANAGE_ROLES = "manage_roles"

    # Resource management
    CREATE_WORKSPACE = "create_workspace"
    DELETE_WORKSPACE = "delete_workspace"
    MANAGE_WORKSPACE = "manage_workspace"
    ACCESS_WORKSPACE = "access_workspace"

    # Content permissions
    CREATE_CONTENT = "create_content"
    EDIT_CONTENT = "edit_content"
    DELETE_CONTENT = "delete_content"
    VIEW_CONTENT = "view_content"

    # Collaboration permissions
    REAL_TIME_EDIT = "real_time_edit"
    COMMENT = "comment"
    SHARE_RESOURCES = "share_resources"
    EXPORT_DATA = "export_data"

    # Administrative
    VIEW_AUDIT_LOG = "view_audit_log"
    MANAGE_SETTINGS = "manage_settings"


class InvitationStatus(Enum):
    """Team invitation status"""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class TeamConfig:
    """Team configuration settings"""

    max_members: int = 100
    allow_public_join: bool = False
    require_approval: bool = True
    invitation_expires_days: int = 7
    enable_hierarchies: bool = True
    enable_custom_roles: bool = False
    default_member_role: TeamRole = TeamRole.MEMBER
    allowed_domains: List[str] = field(default_factory=list)


@dataclass
class TeamStats:
    """Team statistics"""

    total_members: int = 0
    active_members: int = 0
    pending_invitations: int = 0
    workspaces_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)


# Association table for team members - will be created with Model.metadata
team_members = Table(
    "fab_team_members",
    Model.metadata,
    Column("team_id", Integer, ForeignKey("fab_teams.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("ab_user.id"), primary_key=True),
    Column("role", String(50), nullable=False),
    Column("joined_at", DateTime, default=datetime.now),
    Column("is_active", Boolean, default=True),
)

# Association table for team permissions
team_role_permissions = Table(
    "fab_team_role_permissions",
    Model.metadata,
    Column("team_id", Integer, ForeignKey("fab_teams.id"), primary_key=True),
    Column("role", String(50), primary_key=True),
    Column("permission", String(100), primary_key=True),
)


class Team(Model, AuditMixin):
    """Team model with PgAppForge integration"""

    __tablename__ = "fab_teams"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    slug = Column(String(100), unique=True, nullable=False)

    # Team settings
    is_public = Column(Boolean, default=False)
    require_approval = Column(Boolean, default=True)
    max_members = Column(Integer, default=100)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    invitations = relationship(
        "TeamInvitation", back_populates="team", cascade="all, delete-orphan"
    )
    workspaces = relationship(
        "TeamWorkspace", back_populates="team", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Team {self.name}>"

    def __str__(self):
        return self.name


class TeamInvitation(Model, AuditMixin):
    """Team invitation model with PgAppForge integration"""

    __tablename__ = "fab_team_invitations"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("fab_teams.id"), nullable=False)

    # Invitation details
    email = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    token = Column(String(255), unique=True, nullable=False)
    message = Column(Text)

    # Status and timing
    status = Column(String(20), default=InvitationStatus.PENDING.value)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime)

    # User references
    invited_user_id = Column(Integer, ForeignKey("ab_user.id"))

    # Relationships
    team = relationship("Team", back_populates="invitations")

    __table_args__ = (
        UniqueConstraint("team_id", "email", name="unique_team_email_invitation"),
    )

    def __repr__(self):
        return f"<TeamInvitation {self.email} for {self.team.name}>"

    def __str__(self):
        return f"{self.email} invited to {self.team.name}"


class TeamWorkspace(Model, AuditMixin):
    """Team workspace model with PgAppForge integration"""

    __tablename__ = "fab_team_workspaces"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("fab_teams.id"), nullable=False)

    # Workspace details
    name = Column(String(100), nullable=False)
    description = Column(Text)
    slug = Column(String(100), nullable=False)

    # Settings
    is_public = Column(Boolean, default=False)
    allow_external_sharing = Column(Boolean, default=False)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    team = relationship("Team", back_populates="workspaces")

    def __repr__(self):
        return f"<TeamWorkspace {self.name}>"

    def __str__(self):
        return self.name

    __table_args__ = (
        UniqueConstraint("team_id", "slug", name="unique_team_workspace_slug"),
    )


class TeamManager:
    """
    Advanced team management system for PgAppForge.

    Features:
    - Team creation and management
    - Role-based team permissions
    - Team invitations and member management
    - Integration with PgAppForge security
    - Team workspace management
    - Audit logging and analytics
    """

    def __init__(self, app_builder: AppBuilder):
        self.app_builder = app_builder
        self.app = app_builder.app
        self.db = app_builder.get_session
        self.security_manager = app_builder.sm

        # Permission mapping
        self.role_permissions = self._setup_role_permissions()

        # Integration hooks
        self._setup_security_integration()

    def _setup_role_permissions(self) -> Dict[TeamRole, Set[TeamPermission]]:
        """Setup default role permissions"""
        return {
            TeamRole.OWNER: {
                TeamPermission.MANAGE_TEAM,
                TeamPermission.INVITE_MEMBERS,
                TeamPermission.REMOVE_MEMBERS,
                TeamPermission.MANAGE_ROLES,
                TeamPermission.CREATE_WORKSPACE,
                TeamPermission.DELETE_WORKSPACE,
                TeamPermission.MANAGE_WORKSPACE,
                TeamPermission.ACCESS_WORKSPACE,
                TeamPermission.CREATE_CONTENT,
                TeamPermission.EDIT_CONTENT,
                TeamPermission.DELETE_CONTENT,
                TeamPermission.VIEW_CONTENT,
                TeamPermission.REAL_TIME_EDIT,
                TeamPermission.COMMENT,
                TeamPermission.SHARE_RESOURCES,
                TeamPermission.EXPORT_DATA,
                TeamPermission.VIEW_AUDIT_LOG,
                TeamPermission.MANAGE_SETTINGS,
            },
            TeamRole.ADMIN: {
                TeamPermission.INVITE_MEMBERS,
                TeamPermission.REMOVE_MEMBERS,
                TeamPermission.MANAGE_ROLES,
                TeamPermission.CREATE_WORKSPACE,
                TeamPermission.MANAGE_WORKSPACE,
                TeamPermission.ACCESS_WORKSPACE,
                TeamPermission.CREATE_CONTENT,
                TeamPermission.EDIT_CONTENT,
                TeamPermission.DELETE_CONTENT,
                TeamPermission.VIEW_CONTENT,
                TeamPermission.REAL_TIME_EDIT,
                TeamPermission.COMMENT,
                TeamPermission.SHARE_RESOURCES,
                TeamPermission.EXPORT_DATA,
                TeamPermission.VIEW_AUDIT_LOG,
            },
            TeamRole.MANAGER: {
                TeamPermission.INVITE_MEMBERS,
                TeamPermission.CREATE_WORKSPACE,
                TeamPermission.MANAGE_WORKSPACE,
                TeamPermission.ACCESS_WORKSPACE,
                TeamPermission.CREATE_CONTENT,
                TeamPermission.EDIT_CONTENT,
                TeamPermission.VIEW_CONTENT,
                TeamPermission.REAL_TIME_EDIT,
                TeamPermission.COMMENT,
                TeamPermission.SHARE_RESOURCES,
                TeamPermission.EXPORT_DATA,
            },
            TeamRole.MEMBER: {
                TeamPermission.ACCESS_WORKSPACE,
                TeamPermission.CREATE_CONTENT,
                TeamPermission.EDIT_CONTENT,
                TeamPermission.VIEW_CONTENT,
                TeamPermission.REAL_TIME_EDIT,
                TeamPermission.COMMENT,
            },
            TeamRole.VIEWER: {
                TeamPermission.ACCESS_WORKSPACE,
                TeamPermission.VIEW_CONTENT,
                TeamPermission.COMMENT,
            },
            TeamRole.GUEST: {TeamPermission.VIEW_CONTENT},
        }

    def _setup_security_integration(self) -> None:
        """Setup integration with PgAppForge security"""
        # This would extend the security manager with team-based permissions
        # For now, we'll add helper methods to check team permissions
        pass

    @contextmanager
    def _database_transaction(self, retry_count=3, timeout=30, isolation_level=None):
        """Context manager for database transactions with concurrent access handling"""
        session = self.db()
        attempt = 0
        savepoint = None

        while attempt < retry_count:
            try:
                # Set transaction isolation level if specified
                if isolation_level:
                    from sqlalchemy import text

                    session.execute(
                        text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}")
                    )

                # Create savepoint for nested transactions
                if attempt > 0:
                    savepoint = session.begin_nested()

                yield session

                # Commit the transaction
                if savepoint:
                    savepoint.commit()
                session.commit()
                return  # Success, exit retry loop

            except Exception as e:
                # Handle different types of database errors
                if savepoint:
                    try:
                        savepoint.rollback()
                    except Exception:
                        pass  # Savepoint may already be invalid

                session.rollback()

                # Check if this is a retryable error
                if self._is_retryable_db_error(e) and attempt < retry_count - 1:
                    attempt += 1
                    retry_delay = min(
                        0.1 * (2**attempt), 2.0
                    )  # Exponential backoff, max 2s
                    logger.warning(
                        f"Database error (attempt {attempt}/{retry_count}), retrying in {retry_delay}s: {e}"
                    )

                    # Close the failed session and create a new one
                    session.close()
                    session = self.db()

                    import time

                    time.sleep(retry_delay)
                    continue
                else:
                    # Non-retryable error or max attempts reached
                    logger.error(
                        f"Database transaction failed after {attempt + 1} attempts: {e}"
                    )
                    raise

        # Should never reach here, but safety fallback
        raise RuntimeError(f"Database transaction failed after {retry_count} attempts")

    def _is_retryable_db_error(self, error: Exception) -> bool:
        """Determine if database error is retryable"""
        from sqlalchemy.exc import (
            OperationalError,
            DisconnectionError,
            TimeoutError,
            IntegrityError,
        )

        # Convert error to string for message checking
        error_str = str(error).lower()

        # Retryable error types
        if isinstance(error, (OperationalError, DisconnectionError, TimeoutError)):
            return True

        # Specific retryable error messages
        retryable_messages = [
            "deadlock detected",
            "lock wait timeout",
            "connection lost",
            "server has gone away",
            "connection reset",
            "database is locked",
            "could not serialize access",
        ]

        for message in retryable_messages:
            if message in error_str:
                return True

        # Specific integrity constraint violations that might be retryable
        if isinstance(error, IntegrityError):
            # Only retry certain integrity errors (like unique constraint when slug generation races)
            if any(msg in error_str for msg in ["duplicate key", "unique constraint"]):
                return True

        return False

    def _add_team_member_in_session(
        self, session, team_id: int, user_id: int, role: TeamRole
    ) -> bool:
        """Add team member within an existing session"""
        try:
            # Use proper SQLAlchemy Core insert for team member
            stmt = team_members.insert().values(
                team_id=team_id,
                user_id=user_id,
                role=role.value,
                joined_at=datetime.now(),
                is_active=True
            )
            session.execute(stmt)
            logger.info(
                f"Added user {user_id} to team {team_id} with role {role.value}"
            )
            return True
        except Exception as e:
            logger.error(f"Error adding team member: {e}")
            return False

    # Slug generation now handled by shared utility in utils/slug_generator.py
    # Removed duplicate _generate_team_slug method

    def create_team(
        self,
        name: str,
        description: str,
        created_by_user_id: int,
        config: Optional[TeamConfig] = None,
    ) -> Optional[Team]:
        """
        Create a new team with proper transaction management.

        Args:
            name: Team name
            description: Team description
            created_by_user_id: User creating the team
            config: Team configuration

        Returns:
            Created team or None if failed
        """
        try:
            config = config or TeamConfig()

            # Generate unique slug using shared utility
            uniqueness_checker = create_uniqueness_checker(
                self.db, Team, slug_field="slug"
            )
            slug = generate_team_slug(
                name, uniqueness_checker, SlugGenerationStrategy.UUID
            )

            with self._database_transaction() as session:
                team = Team(
                    name=name,
                    description=description,
                    slug=slug,
                    is_public=config.allow_public_join,
                    require_approval=config.require_approval,
                    max_members=config.max_members,
                )

                session.add(team)
                session.flush()  # Get the ID before committing

                # Add creator as owner (within same transaction)
                self._add_team_member_in_session(
                    session, team.id, created_by_user_id, TeamRole.OWNER
                )

                # Transaction is automatically committed by context manager

            logger.info(
                f"Created team '{name}' (ID: {team.id}) by user {created_by_user_id}"
            )
            return team

        except Exception as e:
            logger.error(f"Error creating team: {e}")
            return None

    def get_team(self, team_id: int) -> Optional[Team]:
        """Get team by ID with proper session management"""
        try:
            with self._database_transaction() as session:
                return session.query(Team).filter(Team.id == team_id).first()
        except Exception as e:
            logger.error(f"Error getting team {team_id}: {e}")
            return None

    def get_team_by_slug(self, slug: str) -> Optional[Team]:
        """Get team by slug with proper session management"""
        try:
            with self._database_transaction() as session:
                return session.query(Team).filter(Team.slug == slug).first()
        except Exception as e:
            logger.error(f"Error getting team by slug {slug}: {e}")
            return None

    def get_user_teams(self, user_id: int, include_stats: bool = False) -> List[Dict[str, Any]]:
        """Get all teams a user belongs to with optimized queries"""
        try:
            session = self.db()

            # Query team memberships with eager loading
            query = (
                session.query(Team, team_members.c.role, team_members.c.joined_at)
                .join(team_members, Team.id == team_members.c.team_id)
                .filter(
                    team_members.c.user_id == user_id, team_members.c.is_active == True
                )
                .options(selectinload(Team.workspaces), selectinload(Team.invitations))
            )

            teams = []
            team_roles = {}  # Cache roles to avoid repeated permission lookups

            for team, role, joined_at in query.all():
                team_role = TeamRole(role)
                team_roles[team.id] = team_role

                team_data = {
                    "team": team,
                    "role": team_role,
                    "joined_at": joined_at,
                    "permissions": self.role_permissions.get(team_role, set()),  # Use cached permissions
                }

                if include_stats:
                    team_data["stats"] = self._get_team_stats_from_loaded_data(team)

                teams.append(team_data)

            return teams

        except Exception as e:
            logger.error(f"Error getting user teams for {user_id}: {e}")
            return []

    def add_team_member(self, team_id: int, user_id: int, role: TeamRole) -> bool:
        """
        Add a member to a team.

        Args:
            team_id: Team ID
            user_id: User to add
            role: Team role to assign

        Returns:
            True if successful, False otherwise
        """
        try:
            session = self.db()

            # Check if team exists and has capacity
            team = self.get_team(team_id)
            if not team:
                return False

            member_count = self.get_team_member_count(team_id)
            if member_count >= team.max_members:
                logger.warning(
                    f"Team {team_id} at capacity ({team.max_members} members)"
                )
                return False

            # Check if user is already a member
            existing = session.execute(
                team_members.select().where(
                    team_members.c.team_id == team_id,
                    team_members.c.user_id == user_id,
                    team_members.c.is_active == True,
                )
            ).first()

            if existing:
                logger.warning(f"User {user_id} already member of team {team_id}")
                return False

            # Add membership
            session.execute(
                team_members.insert().values(
                    team_id=team_id,
                    user_id=user_id,
                    role=role.value,
                    joined_at=datetime.now(),
                    is_active=True,
                )
            )
            session.commit()

            logger.info(
                f"Added user {user_id} to team {team_id} with role {role.value}"
            )
            return True

        except Exception as e:
            logger.error(f"Error adding team member: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def remove_team_member(
        self, team_id: int, user_id: int, removed_by_user_id: int
    ) -> bool:
        """
        Remove a member from a team.

        Args:
            team_id: Team ID
            user_id: User to remove
            removed_by_user_id: User performing the removal

        Returns:
            True if successful, False otherwise
        """
        try:
            # Check permissions
            if not self.has_team_permission(
                removed_by_user_id, team_id, TeamPermission.REMOVE_MEMBERS
            ):
                logger.warning(
                    f"User {removed_by_user_id} lacks permission to remove members from team {team_id}"
                )
                return False

            # Don't allow removing the last owner
            if self.get_user_team_role(user_id, team_id) == TeamRole.OWNER:
                owner_count = self.get_team_role_count(team_id, TeamRole.OWNER)
                if owner_count <= 1:
                    logger.warning(f"Cannot remove last owner from team {team_id}")
                    return False

            session = self.db()

            # Deactivate membership
            session.execute(
                team_members.update()
                .where(
                    team_members.c.team_id == team_id, team_members.c.user_id == user_id
                )
                .values(is_active=False)
            )
            session.commit()

            logger.info(f"Removed user {user_id} from team {team_id}")
            return True

        except Exception as e:
            logger.error(f"Error removing team member: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def change_member_role(
        self, team_id: int, user_id: int, new_role: TeamRole, changed_by_user_id: int
    ) -> bool:
        """
        Change a team member's role.

        Args:
            team_id: Team ID
            user_id: User whose role to change
            new_role: New role to assign
            changed_by_user_id: User making the change

        Returns:
            True if successful, False otherwise
        """
        try:
            # Check permissions
            if not self.has_team_permission(
                changed_by_user_id, team_id, TeamPermission.MANAGE_ROLES
            ):
                return False

            current_role = self.get_user_team_role(user_id, team_id)
            if not current_role:
                return False

            # Don't allow changing the last owner
            if current_role == TeamRole.OWNER and new_role != TeamRole.OWNER:
                owner_count = self.get_team_role_count(team_id, TeamRole.OWNER)
                if owner_count <= 1:
                    logger.warning(
                        f"Cannot change role of last owner in team {team_id}"
                    )
                    return False

            session = self.db()

            # Update role
            session.execute(
                team_members.update()
                .where(
                    team_members.c.team_id == team_id, team_members.c.user_id == user_id
                )
                .values(role=new_role.value)
            )
            session.commit()

            logger.info(
                f"Changed user {user_id} role in team {team_id} from {current_role.value} to {new_role.value}"
            )
            return True

        except Exception as e:
            logger.error(f"Error changing member role: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def invite_user(
        self,
        team_id: int,
        email: str,
        role: TeamRole,
        invited_by_user_id: int,
        message: Optional[str] = None,
    ) -> Optional[TeamInvitation]:
        """
        Invite a user to join a team.

        Args:
            team_id: Team ID
            email: Email of user to invite
            role: Role to assign
            invited_by_user_id: User sending invitation
            message: Optional invitation message

        Returns:
            Created invitation or None if failed
        """
        try:
            # Check permissions
            if not self.has_team_permission(
                invited_by_user_id, team_id, TeamPermission.INVITE_MEMBERS
            ):
                return None

            # Check if already invited
            session = self.db()
            existing = (
                session.query(TeamInvitation)
                .filter(
                    TeamInvitation.team_id == team_id,
                    TeamInvitation.email == email,
                    TeamInvitation.status == InvitationStatus.PENDING.value,
                )
                .first()
            )

            if existing:
                logger.warning(
                    f"User {email} already has pending invitation to team {team_id}"
                )
                return existing

            # Create invitation
            invitation = TeamInvitation(
                team_id=team_id,
                email=email,
                role=role.value,
                token=str(uuid.uuid4()),
                message=message,
                expires_at=datetime.now() + timedelta(days=7),
                invited_by_id=invited_by_user_id,
            )

            session.add(invitation)
            session.commit()

            # Send invitation email (would integrate with email system)
            self._send_invitation_email(invitation)

            logger.info(f"Invited {email} to team {team_id} with role {role.value}")
            return invitation

        except Exception as e:
            logger.error(f"Error inviting user: {e}")
            if "session" in locals():
                session.rollback()
            return None

    def accept_invitation(self, token: str, user_id: int) -> bool:
        """
        Accept a team invitation.

        Args:
            token: Invitation token
            user_id: User accepting invitation

        Returns:
            True if successful, False otherwise
        """
        try:
            session = self.db()

            # Get invitation
            invitation = (
                session.query(TeamInvitation)
                .filter(
                    TeamInvitation.token == token,
                    TeamInvitation.status == InvitationStatus.PENDING.value,
                )
                .first()
            )

            if not invitation:
                return False

            # Check expiration
            if invitation.expires_at < datetime.now():
                invitation.status = InvitationStatus.EXPIRED.value
                session.commit()
                return False

            # Add user to team
            success = self.add_team_member(
                invitation.team_id, user_id, TeamRole(invitation.role)
            )

            if success:
                # Update invitation
                invitation.status = InvitationStatus.ACCEPTED.value
                invitation.accepted_at = datetime.now()
                invitation.invited_user_id = user_id
                session.commit()

                logger.info(
                    f"User {user_id} accepted invitation to team {invitation.team_id}"
                )
                return True

            return False

        except Exception as e:
            logger.error(f"Error accepting invitation: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def get_user_team_role(self, user_id: int, team_id: int) -> Optional[TeamRole]:
        """Get user's role in a team"""
        try:
            session = self.db()

            result = session.execute(
                team_members.select().where(
                    team_members.c.team_id == team_id,
                    team_members.c.user_id == user_id,
                    team_members.c.is_active == True,
                )
            ).first()

            if result:
                return TeamRole(result.role)

            return None

        except Exception as e:
            logger.error(f"Error getting user team role: {e}")
            return None

    def has_team_permission(
        self, user_id: int, team_id: int, permission: TeamPermission
    ) -> bool:
        """
        Check if user has a specific permission in a team.

        Args:
            user_id: User ID
            team_id: Team ID
            permission: Permission to check

        Returns:
            True if user has permission, False otherwise
        """
        try:
            role = self.get_user_team_role(user_id, team_id)
            if not role:
                return False

            return permission in self.role_permissions.get(role, set())

        except Exception as e:
            logger.error(f"Error checking team permission: {e}")
            return False

    def get_user_team_permissions(
        self, user_id: int, team_id: int
    ) -> Set[TeamPermission]:
        """Get all permissions a user has in a team"""
        role = self.get_user_team_role(user_id, team_id)
        if not role:
            return set()

        return self.role_permissions.get(role, set())

    def get_team_members(
        self, team_id: int, include_inactive: bool = False, include_user_details: bool = True
    ) -> List[Dict[str, Any]]:
        """Get all members of a team with optimized user details loading"""
        try:
            session = self.db()

            if include_user_details:
                # Use JOIN to get user details in single query (assuming FAB user model)
                from pgappforge.security.sqla.models import User

                query = (
                    session.query(
                        team_members.c.user_id,
                        team_members.c.role,
                        team_members.c.joined_at,
                        team_members.c.is_active,
                        User.first_name,
                        User.last_name,
                        User.username,
                        User.email
                    )
                    .join(User, team_members.c.user_id == User.id)
                    .filter(team_members.c.team_id == team_id)
                )
            else:
                query = session.query(team_members).filter(
                    team_members.c.team_id == team_id
                )

            if not include_inactive:
                query = query.filter(team_members.c.is_active == True)

            members = []
            for row in query.all():
                member_data = {
                    "user_id": row.user_id,
                    "role": TeamRole(row.role),
                    "joined_at": row.joined_at,
                    "is_active": row.is_active,
                }

                if include_user_details:
                    member_data.update({
                        "user_details": {
                            "first_name": row.first_name,
                            "last_name": row.last_name,
                            "username": row.username,
                            "email": row.email,
                        }
                    })

                members.append(member_data)

            return members

        except Exception as e:
            logger.error(f"Error getting team members: {e}")
            return []

    def get_team_member_count(self, team_id: int) -> int:
        """Get active member count for a team"""
        try:
            session = self.db()

            count = session.execute(
                team_members.select().where(
                    team_members.c.team_id == team_id, team_members.c.is_active == True
                )
            ).rowcount

            return count

        except Exception as e:
            logger.error(f"Error getting team member count: {e}")
            return 0

    def get_team_role_count(self, team_id: int, role: TeamRole) -> int:
        """Get count of members with specific role"""
        try:
            session = self.db()

            count = session.execute(
                team_members.select().where(
                    team_members.c.team_id == team_id,
                    team_members.c.role == role.value,
                    team_members.c.is_active == True,
                )
            ).rowcount

            return count

        except Exception as e:
            logger.error(f"Error getting team role count: {e}")
            return 0

    def create_workspace(
        self,
        team_id: int,
        name: str,
        description: str,
        created_by_user_id: int,
        is_public: bool = False,
    ) -> Optional[TeamWorkspace]:
        """
        Create a team workspace.

        Args:
            team_id: Team ID
            name: Workspace name
            description: Workspace description
            created_by_user_id: User creating workspace
            is_public: Whether workspace is public

        Returns:
            Created workspace or None if failed
        """
        try:
            # Check permissions
            if not self.has_team_permission(
                created_by_user_id, team_id, TeamPermission.CREATE_WORKSPACE
            ):
                return None

            # Generate unique slug using shared utility
            uniqueness_checker = create_uniqueness_checker(
                self.db,
                TeamWorkspace,
                slug_field="slug",
                additional_filters={"team_id": team_id},
            )
            slug = generate_workspace_slug(name, uniqueness_checker)

            workspace = TeamWorkspace(
                team_id=team_id,
                name=name,
                description=description,
                slug=slug,
                is_public=is_public,
                created_by_id=created_by_user_id,
            )

            session = self.db()
            session.add(workspace)
            session.commit()

            logger.info(f"Created workspace '{name}' for team {team_id}")
            return workspace

        except Exception as e:
            logger.error(f"Error creating workspace: {e}")
            if "session" in locals():
                session.rollback()
            return None

    def get_team_workspaces(
        self, team_id: int, user_id: Optional[int] = None
    ) -> List[TeamWorkspace]:
        """Get workspaces for a team"""
        try:
            session = self.db()

            query = session.query(TeamWorkspace).filter(
                TeamWorkspace.team_id == team_id
            )

            # Filter by access permissions if user specified
            if user_id:
                if not self.has_team_permission(
                    user_id, team_id, TeamPermission.ACCESS_WORKSPACE
                ):
                    return []

            return query.all()

        except Exception as e:
            logger.error(f"Error getting team workspaces: {e}")
            return []

    def get_team_stats(self, team_id: int) -> TeamStats:
        """Get team statistics with optimized single query"""
        try:
            session = self.db()

            # Get all stats in a single query using subqueries
            stats_query = (
                session.query(
                    Team.created_at,
                    Team.updated_at,
                    func.coalesce(
                        session.query(func.count(team_members.c.user_id))
                        .filter(
                            and_(
                                team_members.c.team_id == team_id,
                                team_members.c.is_active == True
                            )
                        )
                        .scalar_subquery(), 0
                    ).label('member_count'),
                    func.coalesce(
                        session.query(func.count(TeamInvitation.id))
                        .filter(
                            and_(
                                TeamInvitation.team_id == team_id,
                                TeamInvitation.status == InvitationStatus.PENDING.value
                            )
                        )
                        .scalar_subquery(), 0
                    ).label('pending_invitations'),
                    func.coalesce(
                        session.query(func.count(TeamWorkspace.id))
                        .filter(TeamWorkspace.team_id == team_id)
                        .scalar_subquery(), 0
                    ).label('workspace_count')
                )
                .filter(Team.id == team_id)
            ).first()

            if not stats_query:
                return TeamStats()

            return TeamStats(
                total_members=stats_query.member_count,
                active_members=stats_query.member_count,
                pending_invitations=stats_query.pending_invitations,
                workspaces_count=stats_query.workspace_count,
                created_at=stats_query.created_at,
                last_activity=stats_query.updated_at,
            )

        except Exception as e:
            logger.error(f"Error getting team stats: {e}")
            return TeamStats()

    # Slug generation now handled by shared utility in utils/slug_generator.py
    # Removed duplicate _generate_team_slug method

    # Slug generation now handled by shared utility in utils/slug_generator.py
    # Removed duplicate _generate_workspace_slug method

    def _send_invitation_email(self, invitation: TeamInvitation) -> None:
        """Send invitation email (placeholder)"""
        # This would integrate with PgAppForge's email system
        logger.info(
            f"Sending invitation email to {invitation.email} for team {invitation.team_id}"
        )

    def _get_team_stats_from_loaded_data(self, team: Team) -> TeamStats:
        """Get team stats from already loaded team data (to avoid N+1 queries)"""
        try:
            # Use loaded relationships when available
            pending_invitations = len([
                inv for inv in team.invitations
                if inv.status == InvitationStatus.PENDING.value
            ]) if team.invitations else 0

            workspace_count = len(team.workspaces) if team.workspaces else 0

            # Still need to query member count as it's not a direct relationship
            member_count = self.get_team_member_count(team.id)

            return TeamStats(
                total_members=member_count,
                active_members=member_count,
                pending_invitations=pending_invitations,
                workspaces_count=workspace_count,
                created_at=team.created_at,
                last_activity=team.updated_at,
            )
        except Exception as e:
            logger.error(f"Error calculating stats from loaded data: {e}")
            return TeamStats()

    def get_teams_with_stats(self, team_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Get multiple teams with their stats in bulk queries"""
        try:
            session = self.db()

            if not team_ids:
                return {}

            # Get teams with eager loading
            teams_query = (
                session.query(Team)
                .filter(Team.id.in_(team_ids))
                .options(selectinload(Team.workspaces), selectinload(Team.invitations))
            ).all()

            # Get member counts for all teams in single query
            member_counts_query = (
                session.query(
                    team_members.c.team_id,
                    func.count(team_members.c.user_id).label('member_count')
                )
                .filter(
                    team_members.c.team_id.in_(team_ids),
                    team_members.c.is_active == True
                )
                .group_by(team_members.c.team_id)
            ).all()

            member_counts = {row.team_id: row.member_count for row in member_counts_query}

            results = {}
            for team in teams_query:
                member_count = member_counts.get(team.id, 0)
                pending_invitations = len([
                    inv for inv in team.invitations
                    if inv.status == InvitationStatus.PENDING.value
                ])
                workspace_count = len(team.workspaces)

                results[team.id] = {
                    'team': team,
                    'stats': TeamStats(
                        total_members=member_count,
                        active_members=member_count,
                        pending_invitations=pending_invitations,
                        workspaces_count=workspace_count,
                        created_at=team.created_at,
                        last_activity=team.updated_at,
                    )
                }

            return results

        except Exception as e:
            logger.error(f"Error getting teams with stats: {e}")
            return {}

    def get_teams_members_bulk(self, team_ids: List[int], include_user_details: bool = True) -> Dict[int, List[Dict[str, Any]]]:
        """Get members for multiple teams in a single bulk query"""
        try:
            session = self.db()

            if not team_ids:
                return {}

            if include_user_details:
                # Use JOIN to get user details in single query
                from pgappforge.security.sqla.models import User

                query = (
                    session.query(
                        team_members.c.team_id,
                        team_members.c.user_id,
                        team_members.c.role,
                        team_members.c.joined_at,
                        team_members.c.is_active,
                        User.first_name,
                        User.last_name,
                        User.username,
                        User.email
                    )
                    .join(User, team_members.c.user_id == User.id)
                    .filter(
                        team_members.c.team_id.in_(team_ids),
                        team_members.c.is_active == True
                    )
                    .order_by(team_members.c.team_id, team_members.c.joined_at)
                )
            else:
                query = (
                    session.query(team_members)
                    .filter(
                        team_members.c.team_id.in_(team_ids),
                        team_members.c.is_active == True
                    )
                    .order_by(team_members.c.team_id, team_members.c.joined_at)
                )

            # Group results by team_id
            results = defaultdict(list)
            for row in query.all():
                member_data = {
                    "user_id": row.user_id,
                    "role": TeamRole(row.role),
                    "joined_at": row.joined_at,
                    "is_active": row.is_active,
                }

                if include_user_details:
                    member_data["user_details"] = {
                        "first_name": row.first_name,
                        "last_name": row.last_name,
                        "username": row.username,
                        "email": row.email,
                    }

                results[row.team_id].append(member_data)

            return dict(results)

        except Exception as e:
            logger.error(f"Error getting teams members bulk: {e}")
            return {}

    def get_team_member_count_bulk(self, team_ids: List[int]) -> Dict[int, int]:
        """Get member counts for multiple teams in single query"""
        try:
            session = self.db()

            if not team_ids:
                return {}

            counts_query = (
                session.query(
                    team_members.c.team_id,
                    func.count(team_members.c.user_id).label('count')
                )
                .filter(
                    team_members.c.team_id.in_(team_ids),
                    team_members.c.is_active == True
                )
                .group_by(team_members.c.team_id)
            ).all()

            return {row.team_id: row.count for row in counts_query}

        except Exception as e:
            logger.error(f"Error getting team member counts bulk: {e}")
            return {}

    def cleanup_expired_invitations(self) -> int:
        """Clean up expired invitations"""
        try:
            session = self.db()

            # Update expired invitations
            expired_count = (
                session.query(TeamInvitation)
                .filter(
                    TeamInvitation.status == InvitationStatus.PENDING.value,
                    TeamInvitation.expires_at < datetime.now(),
                )
                .update({"status": InvitationStatus.EXPIRED.value})
            )

            session.commit()

            if expired_count > 0:
                logger.info(f"Cleaned up {expired_count} expired team invitations")

            return expired_count

        except Exception as e:
            logger.error(f"Error cleaning up expired invitations: {e}")
            return 0
