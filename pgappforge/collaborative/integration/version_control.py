"""
Version Control Integration

Git-inspired version control system for collaborative editing in PgAppForge.
Provides branching, merging, conflict resolution, and distributed collaboration
features for workspace content.
"""

import uuid
import json
import difflib
from typing import Dict, List, Any, Optional, Set, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging
from collections import defaultdict, deque
import hashlib
import re

from flask import Flask, g, current_app
from pgappforge import AppBuilder
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
)
from sqlalchemy.orm import relationship, Session
from sqlalchemy.ext.declarative import declarative_base

from ..core.workspace_manager import WorkspaceManager, WorkspaceResource
from ..core.collaboration_engine import (
    CollaborationEngine,
    CollaborativeEvent,
    CollaborativeEventType,
)

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Types of changes in version control"""

    INSERT = "insert"
    DELETE = "delete"
    MODIFY = "modify"
    MOVE = "move"
    COPY = "copy"


class MergeStrategy(Enum):
    """Merge strategies for conflict resolution"""

    AUTO = "auto"  # Automatic merge where possible
    MANUAL = "manual"  # Require manual resolution
    OURS = "ours"  # Always prefer our changes
    THEIRS = "theirs"  # Always prefer their changes
    UNION = "union"  # Combine both changes


class BranchStatus(Enum):
    """Branch status"""

    ACTIVE = "active"
    MERGED = "merged"
    ABANDONED = "abandoned"
    PROTECTED = "protected"


class ConflictType(Enum):
    """Types of merge conflicts"""

    CONTENT = "content"
    STRUCTURE = "structure"
    METADATA = "metadata"
    PERMISSION = "permission"


@dataclass
class Change:
    """Represents a single change in content"""

    change_type: ChangeType
    line_number: int
    content: str
    old_content: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    author_id: int = 0


@dataclass
class Conflict:
    """Represents a merge conflict"""

    conflict_type: ConflictType
    line_number: int
    ours: str
    theirs: str
    base: str = ""
    resolved: bool = False
    resolution: str = ""
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None


@dataclass
class DiffHunk:
    """A hunk of differences between two versions"""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: List[str]
    context: List[str] = field(default_factory=list)


# Database models
Base = declarative_base()


class Repository(Model, AuditMixin):
    """Repository model for version control with PgAppForge integration"""

    __tablename__ = "fab_vc_repositories"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=False)

    # Repository information
    name = Column(String(200), nullable=False)
    description = Column(Text)
    default_branch = Column(String(100), default="main")

    # Settings
    allow_force_push = Column(Boolean, default=False)
    require_review = Column(Boolean, default=False)
    auto_merge = Column(Boolean, default=True)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    workspace = relationship("Workspace", foreign_keys=[workspace_id])
    branches = relationship(
        "Branch", back_populates="repository", cascade="all, delete-orphan"
    )
    commits = relationship(
        "Commit", back_populates="repository", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_repo_workspace", "workspace_id"),)


class Branch(Model, AuditMixin):
    """Branch model with PgAppForge integration"""

    __tablename__ = "fab_vc_branches"

    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("fab_vc_repositories.id"), nullable=False)

    # Branch information
    name = Column(String(100), nullable=False)
    description = Column(Text)
    status = Column(String(20), default=BranchStatus.ACTIVE.value)

    # References
    head_commit_id = Column(Integer, ForeignKey("fab_vc_commits.id"))
    parent_branch_id = Column(Integer, ForeignKey("fab_vc_branches.id"))

    # Protection and settings
    is_protected = Column(Boolean, default=False)
    require_pull_request = Column(Boolean, default=False)

    # Additional timestamps
    last_commit_at = Column(DateTime, default=datetime.now)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    repository = relationship("Repository", back_populates="branches")
    head_commit = relationship(
        "Commit", foreign_keys=[head_commit_id], post_update=True
    )
    parent_branch = relationship("Branch", remote_side=[id])
    commits = relationship(
        "Commit", back_populates="branch", foreign_keys="Commit.branch_id"
    )

    __table_args__ = (Index("ix_branch_repo", "repository_id", "name", unique=True),)


class Commit(Model, AuditMixin):
    """Commit model with PgAppForge integration"""

    __tablename__ = "fab_vc_commits"

    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("fab_vc_repositories.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("fab_vc_branches.id"), nullable=False)

    # Commit information
    hash = Column(String(64), unique=True, nullable=False)
    message = Column(Text, nullable=False)
    description = Column(Text)

    # References
    parent_commit_id = Column(Integer, ForeignKey("fab_vc_commits.id"))
    merge_commit_id = Column(Integer, ForeignKey("fab_vc_commits.id"))

    # Author and timing
    author_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    authored_at = Column(DateTime, default=datetime.now)
    committed_at = Column(DateTime, default=datetime.now)

    # Metadata
    tags = Column(JSON)
    statistics = Column(JSON)  # lines added, deleted, etc.

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    repository = relationship("Repository", back_populates="commits")
    branch = relationship("Branch", back_populates="commits", foreign_keys=[branch_id])
    author = relationship("User", foreign_keys=[author_id])
    parent_commit = relationship(
        "Commit", remote_side=[id], foreign_keys=[parent_commit_id]
    )
    merge_commit = relationship(
        "Commit", remote_side=[id], foreign_keys=[merge_commit_id]
    )
    changes = relationship(
        "CommitChange", back_populates="commit", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_commit_repo", "repository_id"),
        Index("ix_commit_branch", "branch_id"),
        Index("ix_commit_hash", "hash"),
    )


class CommitChange(Model, AuditMixin):
    """Individual changes in a commit with PgAppForge integration"""

    __tablename__ = "fab_vc_commit_changes"

    id = Column(Integer, primary_key=True)
    commit_id = Column(Integer, ForeignKey("fab_vc_commits.id"), nullable=False)
    resource_id = Column(Integer, ForeignKey("fab_workspace_resources.id"), nullable=False)

    # Change information
    change_type = Column(String(20), nullable=False)
    old_path = Column(String(500))
    new_path = Column(String(500))

    # Content changes
    old_content = Column(Text)
    new_content = Column(Text)
    diff = Column(Text)  # Unified diff format

    # Statistics
    lines_added = Column(Integer, default=0)
    lines_deleted = Column(Integer, default=0)
    lines_modified = Column(Integer, default=0)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    commit = relationship("Commit", back_populates="changes")
    resource = relationship("WorkspaceResource", foreign_keys=[resource_id])


class MergeRequest(Model, AuditMixin):
    """Merge request model with PgAppForge integration"""

    __tablename__ = "fab_vc_merge_requests"

    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("fab_vc_repositories.id"), nullable=False)

    # Branch information
    source_branch_id = Column(Integer, ForeignKey("fab_vc_branches.id"), nullable=False)
    target_branch_id = Column(Integer, ForeignKey("fab_vc_branches.id"), nullable=False)

    # Request information
    title = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(String(20), default="open")

    # Review settings
    require_approval = Column(Boolean, default=True)
    auto_merge = Column(Boolean, default=False)

    # Merge information
    merge_strategy = Column(String(20))
    merged_at = Column(DateTime)
    merged_commit_id = Column(Integer, ForeignKey("fab_vc_commits.id"))

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    repository = relationship("Repository", foreign_keys=[repository_id])
    source_branch = relationship("Branch", foreign_keys=[source_branch_id])
    target_branch = relationship("Branch", foreign_keys=[target_branch_id])
    merged_commit = relationship("Commit", foreign_keys=[merged_commit_id])

    __table_args__ = (
        Index("ix_merge_request_repo", "repository_id"),
        Index("ix_merge_request_source", "source_branch_id"),
        Index("ix_merge_request_target", "target_branch_id"),
    )


class MergeConflict(Model, AuditMixin):
    """Merge conflict model with PgAppForge integration"""

    __tablename__ = "fab_vc_merge_conflicts"

    id = Column(Integer, primary_key=True)
    merge_request_id = Column(Integer, ForeignKey("fab_vc_merge_requests.id"), nullable=False)
    resource_id = Column(Integer, ForeignKey("fab_workspace_resources.id"), nullable=False)

    # Conflict information
    conflict_type = Column(String(50), nullable=False)
    path = Column(String(500), nullable=False)
    line_number = Column(Integer)

    # Content
    base_content = Column(Text)
    source_content = Column(Text)
    target_content = Column(Text)
    resolved_content = Column(Text)

    # Status
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    resolved_by_id = Column(Integer, ForeignKey("ab_user.id"))

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    merge_request = relationship("MergeRequest", foreign_keys=[merge_request_id])
    resource = relationship("WorkspaceResource", foreign_keys=[resource_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])

    __table_args__ = (
        Index("ix_conflict_merge_request", "merge_request_id"),
        Index("ix_conflict_resource", "resource_id"),
    )







class VersionControlIntegration:
    """
    Git-inspired version control system for collaborative editing.

    Features:
    - Branch-based development workflow
    - Commit history with detailed change tracking
    - Merge requests with conflict resolution
    - Automatic and manual merge strategies
    - Integration with collaborative editing
    - Distributed collaboration support
    """

    def __init__(
        self,
        app_builder: AppBuilder,
        workspace_manager: WorkspaceManager,
        collaboration_engine: CollaborationEngine,
    ):
        self.app_builder = app_builder
        self.app = app_builder.app
        self.db = app_builder.get_session
        self.workspace_manager = workspace_manager
        self.collaboration_engine = collaboration_engine

        # Setup integration
        self._setup_collaboration_integration()

    def _setup_collaboration_integration(self) -> None:
        """Setup integration with collaboration engine"""
        # Register for collaborative events
        self.collaboration_engine.register_event_handler(
            CollaborativeEventType.DATA_CHANGE, self._handle_collaborative_change
        )

    def create_repository(
        self,
        workspace_id: int,
        name: str,
        created_by_id: int,
        description: str = "",
        default_branch: str = "main",
    ) -> Optional[Repository]:
        """
        Create a new repository for version control.

        Args:
            workspace_id: Workspace ID
            name: Repository name
            created_by_id: User creating repository
            description: Repository description
            default_branch: Default branch name

        Returns:
            Created repository or None if failed
        """
        try:
            # Check workspace access
            if not self.workspace_manager.has_workspace_access(
                created_by_id, workspace_id, self.workspace_manager.AccessLevel.ADMIN
            ):
                return None

            repository = Repository(
                workspace_id=workspace_id,
                name=name,
                description=description,
                default_branch=default_branch,
                created_by_id=created_by_id,
            )

            session = self.db()
            session.add(repository)
            session.commit()

            # Create default branch
            self.create_branch(
                repository.id,
                default_branch,
                created_by_id,
                description="Default branch",
            )

            logger.info(f"Created repository '{name}' in workspace {workspace_id}")
            return repository

        except Exception as e:
            logger.error(f"Error creating repository: {e}")
            if "session" in locals():
                session.rollback()
            return None

    def create_branch(
        self,
        repository_id: int,
        name: str,
        created_by_id: int,
        description: str = "",
        parent_branch_id: Optional[int] = None,
    ) -> Optional[Branch]:
        """
        Create a new branch.

        Args:
            repository_id: Repository ID
            name: Branch name
            created_by_id: User creating branch
            description: Branch description
            parent_branch_id: Parent branch (for forking)

        Returns:
            Created branch or None if failed
        """
        try:
            session = self.db()
            repository = (
                session.query(Repository).filter(Repository.id == repository_id).first()
            )

            if not repository:
                return None

            # Check permissions
            if not self.workspace_manager.has_workspace_access(
                created_by_id,
                repository.workspace_id,
                self.workspace_manager.AccessLevel.WRITE,
            ):
                return None

            branch = Branch(
                repository_id=repository_id,
                name=name,
                description=description,
                parent_branch_id=parent_branch_id,
                created_by_id=created_by_id,
            )

            session.add(branch)
            session.commit()

            logger.info(f"Created branch '{name}' in repository {repository_id}")
            return branch

        except Exception as e:
            logger.error(f"Error creating branch: {e}")
            if "session" in locals():
                session.rollback()
            return None

    def commit_changes(
        self,
        repository_id: int,
        branch_name: str,
        author_id: int,
        message: str,
        changes: List[Dict[str, Any]],
        description: str = "",
    ) -> Optional[Commit]:
        """
        Commit changes to a branch.

        Args:
            repository_id: Repository ID
            branch_name: Branch name
            author_id: Author user ID
            message: Commit message
            changes: List of changes to commit
            description: Detailed description

        Returns:
            Created commit or None if failed
        """
        try:
            session = self.db()

            # Get branch
            branch = (
                session.query(Branch)
                .filter(
                    Branch.repository_id == repository_id, Branch.name == branch_name
                )
                .first()
            )

            if not branch:
                return None

            # Check permissions
            repository = (
                session.query(Repository).filter(Repository.id == repository_id).first()
            )
            if not self.workspace_manager.has_workspace_access(
                author_id,
                repository.workspace_id,
                self.workspace_manager.AccessLevel.WRITE,
            ):
                return None

            # Generate commit hash
            commit_hash = self._generate_commit_hash(message, changes, author_id)

            # Calculate statistics
            stats = self._calculate_commit_statistics(changes)

            commit = Commit(
                repository_id=repository_id,
                branch_id=branch.id,
                hash=commit_hash,
                message=message,
                description=description,
                parent_commit_id=branch.head_commit_id,
                author_id=author_id,
                statistics=stats,
            )

            session.add(commit)
            session.flush()  # Get commit ID

            # Create commit changes
            for change_data in changes:
                change = CommitChange(
                    commit_id=commit.id,
                    resource_id=change_data["resource_id"],
                    change_type=change_data["change_type"],
                    old_path=change_data.get("old_path"),
                    new_path=change_data.get("new_path"),
                    old_content=change_data.get("old_content", ""),
                    new_content=change_data.get("new_content", ""),
                    diff=change_data.get("diff", ""),
                    lines_added=change_data.get("lines_added", 0),
                    lines_deleted=change_data.get("lines_deleted", 0),
                    lines_modified=change_data.get("lines_modified", 0),
                )
                session.add(change)

            # Update branch head
            branch.head_commit_id = commit.id
            branch.last_commit_at = datetime.now()

            session.commit()

            # Emit collaborative event
            self._emit_commit_event(commit, author_id)

            logger.info(
                f"Committed changes to {branch_name} in repository {repository_id}"
            )
            return commit

        except Exception as e:
            logger.error(f"Error committing changes: {e}")
            if "session" in locals():
                session.rollback()
            return None

    def create_merge_request(
        self,
        repository_id: int,
        title: str,
        source_branch_name: str,
        target_branch_name: str,
        created_by_id: int,
        description: str = "",
        merge_strategy: MergeStrategy = MergeStrategy.AUTO,
    ) -> Optional[MergeRequest]:
        """
        Create a merge request.

        Args:
            repository_id: Repository ID
            title: Merge request title
            source_branch_name: Source branch name
            target_branch_name: Target branch name
            created_by_id: User creating merge request
            description: Description
            merge_strategy: Merge strategy

        Returns:
            Created merge request or None if failed
        """
        try:
            session = self.db()

            # Get branches
            source_branch = (
                session.query(Branch)
                .filter(
                    Branch.repository_id == repository_id,
                    Branch.name == source_branch_name,
                )
                .first()
            )

            target_branch = (
                session.query(Branch)
                .filter(
                    Branch.repository_id == repository_id,
                    Branch.name == target_branch_name,
                )
                .first()
            )

            if not source_branch or not target_branch:
                return None

            # Check permissions
            repository = (
                session.query(Repository).filter(Repository.id == repository_id).first()
            )
            if not self.workspace_manager.has_workspace_access(
                created_by_id,
                repository.workspace_id,
                self.workspace_manager.AccessLevel.WRITE,
            ):
                return None

            merge_request = MergeRequest(
                repository_id=repository_id,
                title=title,
                description=description,
                source_branch_id=source_branch.id,
                target_branch_id=target_branch.id,
                merge_strategy=merge_strategy.value,
                created_by_id=created_by_id,
                require_review=repository.require_review,
            )

            session.add(merge_request)
            session.commit()

            # Detect conflicts
            conflicts = self._detect_conflicts(source_branch, target_branch)

            # Create conflict records
            for conflict in conflicts:
                conflict_record = MergeConflict(
                    merge_request_id=merge_request.id,
                    resource_id=conflict.get("resource_id"),
                    conflict_type=conflict.get("conflict_type"),
                    line_number=conflict.get("line_number"),
                    ours=conflict.get("ours", ""),
                    theirs=conflict.get("theirs", ""),
                    base=conflict.get("base", ""),
                )
                session.add(conflict_record)

            session.commit()

            logger.info(
                f"Created merge request '{title}' in repository {repository_id}"
            )
            return merge_request

        except Exception as e:
            logger.error(f"Error creating merge request: {e}")
            if "session" in locals():
                session.rollback()
            return None

    def merge_request(
        self, merge_request_id: int, merged_by_id: int, force_merge: bool = False
    ) -> bool:
        """
        Merge a merge request.

        Args:
            merge_request_id: Merge request ID
            merged_by_id: User performing merge
            force_merge: Force merge even with conflicts

        Returns:
            True if successful, False otherwise
        """
        try:
            session = self.db()
            merge_request = (
                session.query(MergeRequest)
                .filter(MergeRequest.id == merge_request_id)
                .first()
            )

            if not merge_request or merge_request.status != "open":
                return False

            # Check permissions
            repository = (
                session.query(Repository)
                .filter(Repository.id == merge_request.repository_id)
                .first()
            )

            if not self.workspace_manager.has_workspace_access(
                merged_by_id,
                repository.workspace_id,
                self.workspace_manager.AccessLevel.WRITE,
            ):
                return False

            # Check for unresolved conflicts
            unresolved_conflicts = (
                session.query(MergeConflict)
                .filter(
                    MergeConflict.merge_request_id == merge_request_id,
                    MergeConflict.is_resolved == False,
                )
                .count()
            )

            if unresolved_conflicts > 0 and not force_merge:
                logger.warning(
                    f"Merge request {merge_request_id} has unresolved conflicts"
                )
                return False

            # Perform merge
            merge_commit = self._perform_merge(merge_request, merged_by_id)

            if merge_commit:
                # Update merge request
                merge_request.status = "merged"
                merge_request.merged_at = datetime.now()
                merge_request.merged_by_id = merged_by_id
                merge_request.merge_commit_id = merge_commit.id

                session.commit()

                # Emit collaborative event
                self._emit_merge_event(merge_request, merged_by_id)

                logger.info(f"Merged request {merge_request_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error merging request: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def resolve_conflict(
        self, conflict_id: int, resolution: str, resolved_by_id: int
    ) -> bool:
        """
        Resolve a merge conflict.

        Args:
            conflict_id: Conflict ID
            resolution: Resolution content
            resolved_by_id: User resolving conflict

        Returns:
            True if successful, False otherwise
        """
        try:
            session = self.db()
            conflict = (
                session.query(MergeConflict)
                .filter(MergeConflict.id == conflict_id)
                .first()
            )

            if not conflict:
                return False

            # Check permissions
            merge_request = conflict.merge_request
            repository = (
                session.query(Repository)
                .filter(Repository.id == merge_request.repository_id)
                .first()
            )

            if not self.workspace_manager.has_workspace_access(
                resolved_by_id,
                repository.workspace_id,
                self.workspace_manager.AccessLevel.WRITE,
            ):
                return False

            # Update conflict
            conflict.is_resolved = True
            conflict.resolution = resolution
            conflict.resolved_by_id = resolved_by_id
            conflict.resolved_at = datetime.now()

            session.commit()

            logger.info(f"Resolved conflict {conflict_id}")
            return True

        except Exception as e:
            logger.error(f"Error resolving conflict: {e}")
            if "session" in locals():
                session.rollback()
            return False

    def get_commit_history(
        self, repository_id: int, branch_name: str, limit: int = 50
    ) -> List[Commit]:
        """Get commit history for a branch"""
        try:
            session = self.db()

            branch = (
                session.query(Branch)
                .filter(
                    Branch.repository_id == repository_id, Branch.name == branch_name
                )
                .first()
            )

            if not branch:
                return []

            return (
                session.query(Commit)
                .filter(Commit.branch_id == branch.id)
                .order_by(Commit.committed_at.desc())
                .limit(limit)
                .all()
            )

        except Exception as e:
            logger.error(f"Error getting commit history: {e}")
            return []

    def get_file_history(
        self, resource_id: int, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get version history for a specific file"""
        try:
            session = self.db()

            changes = (
                session.query(CommitChange, Commit)
                .join(Commit, CommitChange.commit_id == Commit.id)
                .filter(CommitChange.resource_id == resource_id)
                .order_by(Commit.committed_at.desc())
                .limit(limit)
                .all()
            )

            history = []
            for change, commit in changes:
                history.append(
                    {
                        "commit": commit,
                        "change": change,
                        "message": commit.message,
                        "author_id": commit.author_id,
                        "committed_at": commit.committed_at,
                        "change_type": change.change_type,
                        "lines_added": change.lines_added,
                        "lines_deleted": change.lines_deleted,
                    }
                )

            return history

        except Exception as e:
            logger.error(f"Error getting file history: {e}")
            return []

    def create_diff(self, old_content: str, new_content: str) -> str:
        """Create unified diff between two content versions"""
        try:
            old_lines = old_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)

            diff = difflib.unified_diff(
                old_lines, new_lines, fromfile="old", tofile="new", lineterm=""
            )

            return "".join(diff)

        except Exception as e:
            logger.error(f"Error creating diff: {e}")
            return ""

    def apply_patch(self, original_content: str, patch: str) -> str:
        """Apply a patch to content"""
        try:
            # This is a simplified patch application
            # In a production system, you'd want a more robust patch parser
            lines = original_content.splitlines()
            patch_lines = patch.splitlines()

            result_lines = []
            current_line = 0

            for patch_line in patch_lines:
                if patch_line.startswith("@@"):
                    # Parse hunk header
                    match = re.search(
                        r"@@\s*-(\d+),(\d+)\s*\+(\d+),(\d+)\s*@@", patch_line
                    )
                    if match:
                        old_start, old_lines, new_start, new_lines = map(
                            int, match.groups()
                        )
                        current_line = old_start - 1
                elif patch_line.startswith(" "):
                    # Context line
                    if current_line < len(lines):
                        result_lines.append(lines[current_line])
                        current_line += 1
                elif patch_line.startswith("+"):
                    # Added line
                    result_lines.append(patch_line[1:])
                elif patch_line.startswith("-"):
                    # Deleted line
                    current_line += 1

            # Add remaining lines
            while current_line < len(lines):
                result_lines.append(lines[current_line])
                current_line += 1

            return "\n".join(result_lines)

        except Exception as e:
            logger.error(f"Error applying patch: {e}")
            return original_content

    def _generate_commit_hash(
        self, message: str, changes: List[Dict[str, Any]], author_id: int
    ) -> str:
        """Generate a unique hash for a commit"""
        content = f"{message}{author_id}{datetime.now().isoformat()}"
        for change in changes:
            content += str(change.get("resource_id", ""))
            content += change.get("new_content", "")

        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _calculate_commit_statistics(
        self, changes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate commit statistics"""
        stats = {
            "files_changed": len(changes),
            "lines_added": sum(change.get("lines_added", 0) for change in changes),
            "lines_deleted": sum(change.get("lines_deleted", 0) for change in changes),
            "lines_modified": sum(
                change.get("lines_modified", 0) for change in changes
            ),
        }

        return stats

    def _detect_conflicts(
        self, source_branch: Branch, target_branch: Branch
    ) -> List[Dict[str, Any]]:
        """Detect merge conflicts between branches"""
        conflicts = []

        try:
            session = self.db()

            # Get latest commits from both branches
            source_commit = source_branch.head_commit
            target_commit = target_branch.head_commit

            if not source_commit or not target_commit:
                return conflicts

            # Find common base commit
            base_commit = self._find_common_base(source_commit, target_commit)

            # Get changes from base to each branch
            source_changes = self._get_changes_since_commit(
                source_branch.id, base_commit.id if base_commit else None
            )
            target_changes = self._get_changes_since_commit(
                target_branch.id, base_commit.id if base_commit else None
            )

            # Find conflicting changes (same file modified in both branches)
            source_files = {change.resource_id: change for change in source_changes}
            target_files = {change.resource_id: change for change in target_changes}

            for resource_id in source_files.keys() & target_files.keys():
                source_change = source_files[resource_id]
                target_change = target_files[resource_id]

                # Check if content conflicts
                if source_change.new_content != target_change.new_content:
                    conflicts.append(
                        {
                            "resource_id": resource_id,
                            "conflict_type": ConflictType.CONTENT.value,
                            "line_number": 0,  # Would need more detailed analysis
                            "ours": target_change.new_content,
                            "theirs": source_change.new_content,
                            "base": source_change.old_content,
                        }
                    )

        except Exception as e:
            logger.error(f"Error detecting conflicts: {e}")

        return conflicts

    def _find_common_base(self, commit1: Commit, commit2: Commit) -> Optional[Commit]:
        """Find common base commit between two commits"""
        try:
            # Simple implementation - in practice, you'd use a more sophisticated algorithm
            # like the merge-base algorithm from Git

            commit1_ancestors = set()
            current = commit1

            # Get all ancestors of commit1
            while current:
                commit1_ancestors.add(current.id)
                current = current.parent_commit

            # Find first common ancestor in commit2's history
            current = commit2
            while current:
                if current.id in commit1_ancestors:
                    return current
                current = current.parent_commit

            return None

        except Exception as e:
            logger.error(f"Error finding common base: {e}")
            return None

    def _get_changes_since_commit(
        self, branch_id: int, since_commit_id: Optional[int]
    ) -> List[CommitChange]:
        """Get all changes in a branch since a specific commit"""
        try:
            session = self.db()

            query = (
                session.query(CommitChange)
                .join(Commit, CommitChange.commit_id == Commit.id)
                .filter(Commit.branch_id == branch_id)
            )

            if since_commit_id:
                # Get commits after the base commit
                base_commit = (
                    session.query(Commit).filter(Commit.id == since_commit_id).first()
                )
                if base_commit:
                    query = query.filter(Commit.committed_at > base_commit.committed_at)

            return query.all()

        except Exception as e:
            logger.error(f"Error getting changes since commit: {e}")
            return []

    def _perform_merge(
        self, merge_request: MergeRequest, merged_by_id: int
    ) -> Optional[Commit]:
        """Perform the actual merge operation"""
        try:
            session = self.db()

            source_branch = merge_request.source_branch
            target_branch = merge_request.target_branch

            # Create merge commit
            commit_hash = self._generate_commit_hash(
                f"Merge {source_branch.name} into {target_branch.name}",
                [],
                merged_by_id,
            )

            merge_commit = Commit(
                repository_id=merge_request.repository_id,
                branch_id=target_branch.id,
                hash=commit_hash,
                message=f"Merge {source_branch.name} into {target_branch.name}",
                description=f"Merged via merge request #{merge_request.id}",
                parent_commit_id=target_branch.head_commit_id,
                merge_commit_id=source_branch.head_commit_id,
                author_id=merged_by_id,
            )

            session.add(merge_commit)
            session.flush()

            # Apply changes from source branch
            source_changes = self._get_changes_since_commit(
                source_branch.id, target_branch.head_commit_id
            )

            # Create commit changes for the merge
            for change in source_changes:
                merge_change = CommitChange(
                    commit_id=merge_commit.id,
                    resource_id=change.resource_id,
                    change_type=change.change_type,
                    old_path=change.old_path,
                    new_path=change.new_path,
                    old_content=change.old_content,
                    new_content=change.new_content,
                    diff=change.diff,
                    lines_added=change.lines_added,
                    lines_deleted=change.lines_deleted,
                    lines_modified=change.lines_modified,
                )
                session.add(merge_change)

            # Update target branch head
            target_branch.head_commit_id = merge_commit.id
            target_branch.last_commit_at = datetime.now()

            session.commit()

            return merge_commit

        except Exception as e:
            logger.error(f"Error performing merge: {e}")
            if "session" in locals():
                session.rollback()
            return None

    async def _handle_collaborative_change(self, event: CollaborativeEvent) -> None:
        """Handle collaborative editing changes for version control"""
        try:
            # Auto-commit changes for real-time collaboration
            if event.event_type == CollaborativeEventType.DATA_CHANGE:
                resource_id = event.data.get("object_id")
                if resource_id:
                    # This would integrate with the workspace manager
                    # to get the current content and create a commit
                    pass

        except Exception as e:
            logger.error(f"Error handling collaborative change: {e}")

    def _emit_commit_event(self, commit: Commit, author_id: int) -> None:
        """Emit collaborative event for commit"""
        try:
            import asyncio

            event = CollaborativeEvent(
                event_type=CollaborativeEventType.DATA_CHANGE,
                user_id=author_id,
                workspace_id=str(commit.repository.workspace_id),
                data={
                    "action": "commit",
                    "commit_id": commit.id,
                    "commit_hash": commit.hash,
                    "message": commit.message,
                    "branch_id": commit.branch_id,
                },
            )

            asyncio.create_task(self.collaboration_engine.emit_event(event))

        except Exception as e:
            logger.error(f"Error emitting commit event: {e}")

    def _emit_merge_event(self, merge_request: MergeRequest, merged_by_id: int) -> None:
        """Emit collaborative event for merge"""
        try:
            import asyncio

            event = CollaborativeEvent(
                event_type=CollaborativeEventType.DATA_CHANGE,
                user_id=merged_by_id,
                workspace_id=str(merge_request.repository.workspace_id),
                data={
                    "action": "merge",
                    "merge_request_id": merge_request.id,
                    "source_branch": merge_request.source_branch.name,
                    "target_branch": merge_request.target_branch.name,
                },
            )

            asyncio.create_task(self.collaboration_engine.emit_event(event))

        except Exception as e:
            logger.error(f"Error emitting merge event: {e}")

    def get_repository_stats(self, repository_id: int) -> Dict[str, Any]:
        """Get repository statistics"""
        try:
            session = self.db()
            repository = (
                session.query(Repository).filter(Repository.id == repository_id).first()
            )

            if not repository:
                return {}

            # Count branches, commits, merge requests
            branch_count = (
                session.query(Branch)
                .filter(
                    Branch.repository_id == repository_id,
                    Branch.status == BranchStatus.ACTIVE.value,
                )
                .count()
            )

            commit_count = (
                session.query(Commit)
                .filter(Commit.repository_id == repository_id)
                .count()
            )

            open_mr_count = (
                session.query(MergeRequest)
                .filter(
                    MergeRequest.repository_id == repository_id,
                    MergeRequest.status == "open",
                )
                .count()
            )

            return {
                "name": repository.name,
                "default_branch": repository.default_branch,
                "branch_count": branch_count,
                "commit_count": commit_count,
                "open_merge_requests": open_mr_count,
                "created_at": repository.created_at.isoformat(),
                "workspace_id": repository.workspace_id,
            }

        except Exception as e:
            logger.error(f"Error getting repository stats: {e}")
            return {}
