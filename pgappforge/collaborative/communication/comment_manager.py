"""
Contextual comment system for collaborative content.

Provides threaded comments on documents, code, and workspace content
with real-time updates and rich formatting support.
"""

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Float,
)
from sqlalchemy.orm import relationship
from pgappforge.models.sqla import Model
from pgappforge.models.mixins import AuditMixin
from ..core.workspace_manager import AccessLevel
import json

logger = logging.getLogger(__name__)


class CommentableType(Enum):
    """Types of content that can be commented on."""

    DOCUMENT = "document"
    CODE_FILE = "code_file"
    IMAGE = "image"
    FORM = "form"
    DASHBOARD = "dashboard"
    DATASET = "dataset"


class CommentStatus(Enum):
    """Status of comments for workflow integration."""

    OPEN = "open"
    RESOLVED = "resolved"
    ACKNOWLEDGED = "acknowledged"


class CommentThread(Model, AuditMixin):
    """Main comment thread on a piece of content with PgAppForge integration."""

    __tablename__ = "fab_comment_threads"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=False)
    commentable_type = Column(String(50), nullable=False)
    commentable_id = Column(
        String(255), nullable=False
    )  # ID of the item being commented on
    title = Column(String(255), nullable=True)  # Optional thread title

    # Position information for precise commenting
    line_number = Column(Integer, nullable=True)  # For code files
    character_position = Column(Integer, nullable=True)  # For documents
    x_coordinate = Column(Float, nullable=True)  # For images/visual content
    y_coordinate = Column(Float, nullable=True)
    selection_text = Column(Text, nullable=True)  # Selected text being commented on

    status = Column(String(20), default=CommentStatus.OPEN.value)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)

    # Metadata for context
    context_data = Column(Text, nullable=True)  # JSON string for additional context

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    comments = relationship(
        "Comment", back_populates="thread", cascade="all, delete-orphan"
    )


class Comment(Model, AuditMixin):
    """Individual comment within a thread with PgAppForge integration."""

    __tablename__ = "fab_comments"

    id = Column(Integer, primary_key=True)
    thread_id = Column(Integer, ForeignKey("fab_comment_threads.id"), nullable=False)
    parent_comment_id = Column(Integer, ForeignKey("fab_comments.id"), nullable=True)

    content = Column(Text, nullable=False)
    content_format = Column(String(20), default="markdown")  # markdown, html, plain
    is_deleted = Column(Boolean, default=False)

    # Reactions and interactions
    reactions = Column(Text, nullable=True)  # JSON string for emoji reactions

    # created_by_id and audit fields are provided by AuditMixin
    # changed_by_id from AuditMixin tracks the last updater

    # Relationships
    thread = relationship("CommentThread", back_populates="comments")
    replies = relationship("Comment", remote_side=[id])


class CommentReaction(Model, AuditMixin):
    """User reactions to comments with PgAppForge integration."""

    __tablename__ = "fab_comment_reactions"

    id = Column(Integer, primary_key=True)
    comment_id = Column(Integer, ForeignKey("fab_comments.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    reaction_type = Column(
        String(50), nullable=False
    )  # 'like', 'thumbs_up', 'heart', etc.

    # created_by_id and audit fields are provided by AuditMixin


class CommentManager:
    """Manages contextual comments for collaborative content."""

    def __init__(self, websocket_manager=None, session_factory=None, workspace_manager=None):
        self.websocket_manager = websocket_manager
        self.session_factory = session_factory
        self.workspace_manager = workspace_manager
        self.active_threads: Dict[
            int, Set[int]
        ] = {}  # thread_id -> set of user_ids viewing  # thread_id -> set of user_ids viewing

    async def create_thread(
        self,
        workspace_id: int,
        commentable_type: CommentableType,
        commentable_id: str,
        created_by_id: int,
        initial_comment: str,
        title: Optional[str] = None,
        position_data: Optional[Dict[str, Any]] = None,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[CommentThread]:
        """Create a new comment thread with initial comment."""
        try:
            session = self.session_factory()

            thread = CommentThread(
                workspace_id=workspace_id,
                commentable_type=commentable_type.value,
                commentable_id=commentable_id,
                title=title,
                created_by_id=created_by_id,
            )

            # Set position data if provided
            if position_data:
                thread.line_number = position_data.get("line_number")
                thread.character_position = position_data.get("character_position")
                thread.x_coordinate = position_data.get("x_coordinate")
                thread.y_coordinate = position_data.get("y_coordinate")
                thread.selection_text = position_data.get("selection_text")

            # Set context data
            if context_data:
                thread.context_data = json.dumps(context_data)

            session.add(thread)
            session.flush()  # Get thread ID

            # Create initial comment
            comment = Comment(
                thread_id=thread.id, 
                created_by_id=created_by_id, 
                content=initial_comment
            )
            session.add(comment)
            session.commit()

            logger.info(
                f"Created comment thread {thread.id} on {commentable_type.value}:{commentable_id}"
            )

            # Notify relevant users
            await self._notify_thread_created(thread, comment)

            return thread

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create comment thread: {e}")
            return None
        finally:
            session.close()

    async def add_comment(
        self,
        thread_id: int,
        author_id: int,
        content: str,
        parent_comment_id: Optional[int] = None,
        content_format: str = "markdown",
    ) -> Optional[Comment]:
        """Add a comment to an existing thread."""
        try:
            session = self.session_factory()

            # Verify thread exists and user has access
            thread = session.query(CommentThread).get(thread_id)
            if not thread:
                logger.warning(f"Comment thread {thread_id} not found")
                return None

            comment = Comment(
                thread_id=thread_id,
                parent_comment_id=parent_comment_id,
                created_by_id=author_id,
                content=content,
                content_format=content_format,
            )

            session.add(comment)
            session.commit()

            logger.info(f"Added comment to thread {thread_id} by user {author_id}")

            # Real-time notification
            await self._notify_comment_added(thread, comment)

            return comment

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to add comment: {e}")
            return None
        finally:
            session.close()

    async def update_comment(
        self, comment_id: int, user_id: int, new_content: str
    ) -> bool:
        """Update an existing comment (only by author)."""
        try:
            session = self.session_factory()

            comment = session.query(Comment).get(comment_id)
            if not comment or comment.author_id != user_id:
                return False

            comment.content = new_content
            comment.updated_at = datetime.now(timezone.utc)
            session.commit()

            # Notify about edit
            await self._notify_comment_updated(comment)

            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update comment: {e}")
            return False
        finally:
            session.close()

    async def delete_comment(self, comment_id: int, user_id: int) -> bool:
        """Soft delete a comment (only by author or workspace admin)."""
        try:
            session = self.session_factory()

            comment = session.query(Comment).get(comment_id)
            if not comment:
                return False

            # Check permissions (author or workspace admin)
            if comment.created_by_id != user_id:
                # Check if user is workspace admin
                if self.workspace_manager:
                    # Get the workspace_id from the comment thread
                    thread = session.query(CommentThread).get(comment.thread_id)
                    if not thread:
                        return False
                    
                    # Check if user has admin access to the workspace
                    if not self.workspace_manager.has_workspace_access(
                        user_id, thread.workspace_id, AccessLevel.ADMIN
                    ):
                        logger.warning(
                            f"User {user_id} attempted to delete comment {comment_id} "
                            f"without admin access to workspace {thread.workspace_id}"
                        )
                        return False
                else:
                    # No workspace manager available, only allow author to delete
                    logger.warning(
                        f"No workspace manager available for admin check, "
                        f"denying delete request for comment {comment_id} by user {user_id}"
                    )
                    return False

            comment.is_deleted = True
            comment.updated_at = datetime.now(timezone.utc)
            session.commit()

            # Notify about deletion
            await self._notify_comment_deleted(comment)

            logger.info(
                f"Comment {comment_id} deleted by user {user_id} "
                f"(author: {comment.created_by_id})"
            )
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete comment: {e}")
            return False
        finally:
            session.close()

    async def resolve_thread(self, thread_id: int, resolved_by_id: int) -> bool:
        """Mark a comment thread as resolved."""
        try:
            session = self.session_factory()

            thread = session.query(CommentThread).get(thread_id)
            if not thread:
                return False

            thread.status = CommentStatus.RESOLVED.value
            thread.resolved_at = datetime.now(timezone.utc)
            thread.resolved_by_id = resolved_by_id
            session.commit()

            # Notify about resolution
            await self._notify_thread_resolved(thread)

            logger.info(f"Thread {thread_id} resolved by user {resolved_by_id}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to resolve thread: {e}")
            return False
        finally:
            session.close()

    async def reopen_thread(self, thread_id: int, reopened_by_id: int) -> bool:
        """Reopen a resolved comment thread."""
        try:
            session = self.session_factory()

            thread = session.query(CommentThread).get(thread_id)
            if not thread:
                return False

            thread.status = CommentStatus.OPEN.value
            thread.resolved_at = None
            thread.resolved_by_id = None
            session.commit()

            # Notify about reopening
            await self._notify_thread_reopened(thread, reopened_by_id)

            logger.info(f"Thread {thread_id} reopened by user {reopened_by_id}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to reopen thread: {e}")
            return False
        finally:
            session.close()

    async def add_reaction(
        self, comment_id: int, user_id: int, reaction_type: str
    ) -> bool:
        """Add a reaction to a comment."""
        try:
            session = self.session_factory()

            # Check if reaction already exists
            existing = (
                session.query(CommentReaction)
                .filter_by(
                    comment_id=comment_id, user_id=user_id, reaction_type=reaction_type
                )
                .first()
            )

            if existing:
                return True

            reaction = CommentReaction(
                comment_id=comment_id, user_id=user_id, reaction_type=reaction_type
            )
            session.add(reaction)
            session.commit()

            # Update comment reactions cache
            await self._update_comment_reactions(comment_id)

            # Notify about reaction
            await self._notify_reaction_added(comment_id, user_id, reaction_type)

            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to add reaction: {e}")
            return False
        finally:
            session.close()

    async def remove_reaction(
        self, comment_id: int, user_id: int, reaction_type: str
    ) -> bool:
        """Remove a reaction from a comment."""
        try:
            session = self.session_factory()

            reaction = (
                session.query(CommentReaction)
                .filter_by(
                    comment_id=comment_id, user_id=user_id, reaction_type=reaction_type
                )
                .first()
            )

            if reaction:
                session.delete(reaction)
                session.commit()

                # Update comment reactions cache
                await self._update_comment_reactions(comment_id)

                # Notify about reaction removal
                await self._notify_reaction_removed(comment_id, user_id, reaction_type)

            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to remove reaction: {e}")
            return False
        finally:
            session.close()

    async def get_threads_for_content(
        self,
        workspace_id: int,
        commentable_type: CommentableType,
        commentable_id: str,
        include_resolved: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get all comment threads for a piece of content."""
        try:
            session = self.session_factory()

            query = session.query(CommentThread).filter_by(
                workspace_id=workspace_id,
                commentable_type=commentable_type.value,
                commentable_id=commentable_id,
            )

            if not include_resolved:
                query = query.filter(
                    CommentThread.status != CommentStatus.RESOLVED.value
                )

            threads = query.order_by(CommentThread.created_at.desc()).all()

            result = []
            for thread in threads:
                # Get comments for thread
                comments = (
                    session.query(Comment)
                    .filter_by(thread_id=thread.id, is_deleted=False)
                    .order_by(Comment.created_at.asc())
                    .all()
                )

                comment_data = []
                for comment in comments:
                    # Get reactions
                    reactions = (
                        session.query(CommentReaction)
                        .filter_by(comment_id=comment.id)
                        .all()
                    )

                    reaction_summary = {}
                    for reaction in reactions:
                        if reaction.reaction_type not in reaction_summary:
                            reaction_summary[reaction.reaction_type] = []
                        reaction_summary[reaction.reaction_type].append(
                            reaction.user_id
                        )

                    comment_data.append(
                        {
                            "id": comment.id,
                            "author_id": comment.author_id,
                            "content": comment.content,
                            "content_format": comment.content_format,
                            "created_at": comment.created_at.isoformat(),
                            "updated_at": comment.updated_at.isoformat()
                            if comment.updated_at
                            else None,
                            "parent_comment_id": comment.parent_comment_id,
                            "reactions": reaction_summary,
                        }
                    )

                # Parse context data
                context_data = None
                if thread.context_data:
                    try:
                        context_data = json.loads(thread.context_data)
                    except json.JSONDecodeError:
                        pass

                result.append(
                    {
                        "id": thread.id,
                        "title": thread.title,
                        "status": thread.status,
                        "created_by_id": thread.created_by_id,
                        "created_at": thread.created_at.isoformat(),
                        "resolved_at": thread.resolved_at.isoformat()
                        if thread.resolved_at
                        else None,
                        "resolved_by_id": thread.resolved_by_id,
                        "position": {
                            "line_number": thread.line_number,
                            "character_position": thread.character_position,
                            "x_coordinate": thread.x_coordinate,
                            "y_coordinate": thread.y_coordinate,
                            "selection_text": thread.selection_text,
                        },
                        "context_data": context_data,
                        "comments": comment_data,
                        "comment_count": len(comment_data),
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Failed to get threads for content: {e}")
            return []
        finally:
            session.close()

    async def get_user_mentions(
        self, user_id: int, workspace_id: int, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get comments where user is mentioned."""
        try:
            session = self.session_factory()

            # Find comments mentioning the user (simple @ mention search)
            comments = (
                session.query(Comment)
                .join(CommentThread)
                .filter(
                    CommentThread.workspace_id == workspace_id,
                    Comment.content.contains(
                        f"@{user_id}"
                    ),  # Simplified mention detection
                    Comment.is_deleted == False,
                )
                .order_by(Comment.created_at.desc())
                .limit(limit)
                .all()
            )

            result = []
            for comment in comments:
                result.append(
                    {
                        "comment_id": comment.id,
                        "thread_id": comment.thread_id,
                        "author_id": comment.author_id,
                        "content": comment.content,
                        "created_at": comment.created_at.isoformat(),
                        "commentable_type": comment.thread.commentable_type,
                        "commentable_id": comment.thread.commentable_id,
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Failed to get user mentions: {e}")
            return []
        finally:
            session.close()

    async def _notify_thread_created(
        self, thread: CommentThread, comment: Comment
    ) -> None:
        """Notify users about new comment thread."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "comment_thread_created",
            "workspace_id": thread.workspace_id,
            "thread_id": thread.id,
            "commentable_type": thread.commentable_type,
            "commentable_id": thread.commentable_id,
            "author_id": comment.author_id,
            "content_preview": comment.content[:100] + "..."
            if len(comment.content) > 100
            else comment.content,
        }

        await self.websocket_manager.broadcast_to_workspace(
            thread.workspace_id, notification
        )

    async def _notify_comment_added(
        self, thread: CommentThread, comment: Comment
    ) -> None:
        """Notify users about new comment in thread."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "comment_added",
            "thread_id": thread.id,
            "comment_id": comment.id,
            "author_id": comment.author_id,
            "content": comment.content,
            "created_at": comment.created_at.isoformat(),
        }

        await self.websocket_manager.broadcast_to_workspace(
            thread.workspace_id, notification
        )

    async def _notify_comment_updated(self, comment: Comment) -> None:
        """Notify users about comment update."""
        if not self.websocket_manager:
            return

        session = self.session_factory()
        try:
            thread = session.query(CommentThread).get(comment.thread_id)
            if not thread:
                return

            notification = {
                "type": "comment_updated",
                "thread_id": thread.id,
                "comment_id": comment.id,
                "content": comment.content,
                "updated_at": comment.updated_at.isoformat(),
            }

            await self.websocket_manager.broadcast_to_workspace(
                thread.workspace_id, notification
            )
        finally:
            session.close()

    async def _notify_comment_deleted(self, comment: Comment) -> None:
        """Notify users about comment deletion."""
        if not self.websocket_manager:
            return

        session = self.session_factory()
        try:
            thread = session.query(CommentThread).get(comment.thread_id)
            if not thread:
                return

            notification = {
                "type": "comment_deleted",
                "thread_id": thread.id,
                "comment_id": comment.id,
            }

            await self.websocket_manager.broadcast_to_workspace(
                thread.workspace_id, notification
            )
        finally:
            session.close()

    async def _notify_thread_resolved(self, thread: CommentThread) -> None:
        """Notify users about thread resolution."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "thread_resolved",
            "thread_id": thread.id,
            "resolved_by_id": thread.resolved_by_id,
            "resolved_at": thread.resolved_at.isoformat(),
        }

        await self.websocket_manager.broadcast_to_workspace(
            thread.workspace_id, notification
        )

    async def _notify_thread_reopened(
        self, thread: CommentThread, reopened_by_id: int
    ) -> None:
        """Notify users about thread reopening."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "thread_reopened",
            "thread_id": thread.id,
            "reopened_by_id": reopened_by_id,
        }

        await self.websocket_manager.broadcast_to_workspace(
            thread.workspace_id, notification
        )

    async def _notify_reaction_added(
        self, comment_id: int, user_id: int, reaction_type: str
    ) -> None:
        """Notify users about reaction addition."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "reaction_added",
            "comment_id": comment_id,
            "user_id": user_id,
            "reaction_type": reaction_type,
        }

        # Get thread workspace for broadcasting
        session = self.session_factory()
        try:
            comment = session.query(Comment).get(comment_id)
            if comment and comment.thread:
                await self.websocket_manager.broadcast_to_workspace(
                    comment.thread.workspace_id, notification
                )
        finally:
            session.close()

    async def _notify_reaction_removed(
        self, comment_id: int, user_id: int, reaction_type: str
    ) -> None:
        """Notify users about reaction removal."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "reaction_removed",
            "comment_id": comment_id,
            "user_id": user_id,
            "reaction_type": reaction_type,
        }

        # Get thread workspace for broadcasting
        session = self.session_factory()
        try:
            comment = session.query(Comment).get(comment_id)
            if comment and comment.thread:
                await self.websocket_manager.broadcast_to_workspace(
                    comment.thread.workspace_id, notification
                )
        finally:
            session.close()

    async def _update_comment_reactions(self, comment_id: int) -> None:
        """Update cached reaction summary for a comment."""
        try:
            session = self.session_factory()

            reactions = (
                session.query(CommentReaction).filter_by(comment_id=comment_id).all()
            )

            reaction_summary = {}
            for reaction in reactions:
                if reaction.reaction_type not in reaction_summary:
                    reaction_summary[reaction.reaction_type] = 0
                reaction_summary[reaction.reaction_type] += 1

            # Update comment reactions field
            comment = session.query(Comment).get(comment_id)
            if comment:
                comment.reactions = json.dumps(reaction_summary)
                session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update comment reactions: {e}")
        finally:
            session.close()
