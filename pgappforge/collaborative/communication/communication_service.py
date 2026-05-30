"""
Unified communication service for collaborative workspaces.

Orchestrates chat, comments, and notifications to provide a cohesive
communication experience across all collaborative features.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import sessionmaker

from .chat_manager import ChatManager, MessageType
from .comment_manager import (
    CommentManager,
    CommentableType,
    CommentStatus,
    Comment,
    CommentThread,
)
from .notification_manager import (
    NotificationManager,
    NotificationType,
    NotificationPriority,
    DeliveryChannel,
)

logger = logging.getLogger(__name__)


class CommunicationService:
    """
    Unified service that orchestrates all communication features.

    Provides a single interface for chat, comments, and notifications
    with intelligent cross-system integration and event handling.
    """

    def __init__(
        self,
        websocket_manager=None,
        session_factory=None,
        email_service=None,
        push_service=None,
    ):
        self.websocket_manager = websocket_manager
        self.session_factory = session_factory

        # Initialize component managers
        self.chat_manager = ChatManager(websocket_manager, session_factory)
        self.comment_manager = CommentManager(websocket_manager, session_factory)
        self.notification_manager = NotificationManager(
            websocket_manager, session_factory, email_service, push_service
        )

        # Background task handles
        self.background_tasks: List[asyncio.Task] = []

    async def start_services(self) -> None:
        """Start all background services and processors."""
        logger.info("Starting communication services")

        # Start notification delivery processor
        delivery_task = asyncio.create_task(
            self.notification_manager.process_delivery_queue()
        )
        self.background_tasks.append(delivery_task)

        # Start digest scheduler
        digest_task = asyncio.create_task(
            self.notification_manager.start_digest_scheduler()
        )
        self.background_tasks.append(digest_task)

        # Start typing indicator cleanup
        typing_cleanup_task = asyncio.create_task(self._typing_cleanup_loop())
        self.background_tasks.append(typing_cleanup_task)

        logger.info("Communication services started successfully")

    async def stop_services(self) -> None:
        """Stop all background services."""
        logger.info("Stopping communication services")

        # Cancel all background tasks
        for task in self.background_tasks:
            task.cancel()

        # Wait for tasks to complete
        await asyncio.gather(*self.background_tasks, return_exceptions=True)

        # Stop digest scheduler
        self.notification_manager.stop_digest_scheduler()

        logger.info("Communication services stopped")

    # Chat Operations with Notification Integration
    async def send_chat_message(
        self,
        channel_id: int,
        sender_id: int,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        mention_user_ids: Optional[List[int]] = None,
        **kwargs,
    ) -> Optional[Any]:
        """Send a chat message with automatic mention notifications."""
        # Send the message
        message = await self.chat_manager.send_message(
            channel_id, sender_id, content, message_type, **kwargs
        )

        if not message:
            return None

        # Handle mentions
        if mention_user_ids:
            await self._handle_chat_mentions(message, mention_user_ids)

        return message

    async def create_chat_channel(
        self,
        workspace_id: int,
        name: str,
        description: str,
        created_by_id: int,
        notify_workspace: bool = True,
        **kwargs,
    ) -> Optional[Any]:
        """Create a chat channel with workspace notification."""
        channel = await self.chat_manager.create_channel(
            workspace_id, name, description, created_by_id, **kwargs
        )

        if channel and notify_workspace:
            # Notify workspace members about new channel
            await self._notify_channel_creation(channel)

        return channel

    # Comment Operations with Notification Integration
    async def create_comment_thread(
        self,
        workspace_id: int,
        commentable_type: CommentableType,
        commentable_id: str,
        created_by_id: int,
        initial_comment: str,
        notify_stakeholders: bool = True,
        **kwargs,
    ) -> Optional[Any]:
        """Create a comment thread with stakeholder notifications."""
        thread = await self.comment_manager.create_thread(
            workspace_id,
            commentable_type,
            commentable_id,
            created_by_id,
            initial_comment,
            **kwargs,
        )

        if thread and notify_stakeholders:
            await self._notify_comment_thread_creation(thread)

        return thread

    async def add_comment_reply(
        self,
        thread_id: int,
        author_id: int,
        content: str,
        notify_thread_participants: bool = True,
        mention_user_ids: Optional[List[int]] = None,
        **kwargs,
    ) -> Optional[Any]:
        """Add a comment reply with participant notifications."""
        comment = await self.comment_manager.add_comment(
            thread_id, author_id, content, **kwargs
        )

        if not comment:
            return None

        if notify_thread_participants:
            await self._notify_comment_reply(comment)

        # Handle mentions in comment
        if mention_user_ids:
            await self._handle_comment_mentions(comment, mention_user_ids)

        return comment

    async def resolve_comment_thread(
        self, thread_id: int, resolved_by_id: int, notify_participants: bool = True
    ) -> bool:
        """Resolve a comment thread with participant notifications."""
        success = await self.comment_manager.resolve_thread(thread_id, resolved_by_id)

        if success and notify_participants:
            await self._notify_thread_resolution(thread_id, resolved_by_id)

        return success

    # Unified Notification Operations
    async def send_workspace_announcement(
        self,
        workspace_id: int,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        sender_id: Optional[int] = None,
    ) -> List[int]:
        """Send an announcement to all workspace members."""
        try:
            session = self.session_factory()

            # Get all workspace members using proper database query
            # Import the workspace models (would need to be imported at module level)
            from ..core.workspace_manager import WorkspaceResource, WorkspaceMember

            workspace_members = (
                session.query(WorkspaceMember)
                .filter_by(workspace_id=workspace_id, is_active=True)
                .all()
            )

            user_ids = [member.user_id for member in workspace_members]

            if sender_id and sender_id in user_ids:
                user_ids.remove(sender_id)  # Don't notify sender

            # Create bulk notifications
            notification_ids = (
                await self.notification_manager.create_bulk_notifications(
                    user_ids=user_ids,
                    notification_type=NotificationType.WORKSPACE_UPDATE,
                    title=title,
                    message=message,
                    workspace_id=workspace_id,
                    priority=priority,
                    metadata={"sender_id": sender_id} if sender_id else None,
                )
            )

            logger.info(f"Sent workspace announcement to {len(user_ids)} members")
            return notification_ids

        except Exception as e:
            logger.error(f"Failed to send workspace announcement: {e}")
            return []
        finally:
            session.close()

    async def send_direct_notification(
        self,
        user_id: int,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.SYSTEM_ALERT,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        **kwargs,
    ) -> Optional[Any]:
        """Send a direct notification to a specific user."""
        return await self.notification_manager.create_notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            **kwargs,
        )

    # Communication Analytics and Insights
    async def get_communication_summary(
        self, workspace_id: int, user_id: int, days: int = 7
    ) -> Dict[str, Any]:
        """Get communication activity summary for a user/workspace."""
        try:
            session = self.session_factory()

            since_date = datetime.now(timezone.utc) - timedelta(days=days)

            # Get chat activity
            chat_channels = await self.chat_manager.get_user_channels(
                user_id, workspace_id
            )
            total_unread_messages = sum(ch["unread_count"] for ch in chat_channels)

            # Get comment activity
            comment_mentions = await self.comment_manager.get_user_mentions(
                user_id, workspace_id, limit=100
            )
            recent_mentions = [
                m
                for m in comment_mentions
                if datetime.fromisoformat(m["created_at"]) > since_date
            ]

            # Get notification counts
            notification_counts = (
                await self.notification_manager.get_notification_counts(
                    user_id, workspace_id
                )
            )

            return {
                "period_days": days,
                "chat": {
                    "channels": len(chat_channels),
                    "unread_messages": total_unread_messages,
                },
                "comments": {
                    "recent_mentions": len(recent_mentions),
                    "total_mentions": len(comment_mentions),
                },
                "notifications": notification_counts,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get communication summary: {e}")
            return {}
        finally:
            session.close()

    # Private helper methods for cross-system integration
    async def _handle_chat_mentions(
        self, message: Any, mention_user_ids: List[int]
    ) -> None:
        """Handle user mentions in chat messages."""
        for user_id in mention_user_ids:
            await self.notification_manager.create_notification(
                user_id=user_id,
                notification_type=NotificationType.COMMENT_MENTION,
                title="You were mentioned in chat",
                message=f"You were mentioned in channel discussion",
                workspace_id=message.channel.workspace_id,
                related_entity_type="chat_message",
                related_entity_id=str(message.id),
                metadata={
                    "channel_id": message.channel_id,
                    "sender_id": message.sender_id,
                    "message_preview": message.content[:100],
                },
            )

    async def _handle_comment_mentions(
        self, comment: Any, mention_user_ids: List[int]
    ) -> None:
        """Handle user mentions in comments."""
        for user_id in mention_user_ids:
            await self.notification_manager.create_notification(
                user_id=user_id,
                notification_type=NotificationType.COMMENT_MENTION,
                title="You were mentioned in a comment",
                message=f"You were mentioned in a comment thread",
                workspace_id=comment.thread.workspace_id,
                related_entity_type="comment",
                related_entity_id=str(comment.id),
                metadata={
                    "thread_id": comment.thread_id,
                    "author_id": comment.author_id,
                    "comment_preview": comment.content[:100],
                },
            )

    async def _notify_channel_creation(self, channel: Any) -> None:
        """Notify workspace members about new chat channel."""
        try:
            if not hasattr(channel, "workspace_id") or not channel.workspace_id:
                logger.warning("Channel missing workspace_id for notification")
                return

            session = self.session_factory()

            # Get workspace members
            from ..core.workspace_manager import WorkspaceResource, WorkspaceMember

            workspace_members = (
                session.query(WorkspaceMember)
                .filter_by(workspace_id=channel.workspace_id, is_active=True)
                .all()
            )

            # Exclude the channel creator from notifications
            user_ids = [
                member.user_id
                for member in workspace_members
                if member.user_id != channel.created_by_id
            ]

            if not user_ids:
                logger.debug(f"No users to notify for channel creation: {channel.name}")
                return

            # Create bulk notifications for new channel
            notification_ids = await self.notification_manager.create_bulk_notifications(
                user_ids=user_ids,
                notification_type=NotificationType.WORKSPACE_UPDATE,
                title=f"New chat channel: {channel.name}",
                message=f"A new chat channel '{channel.name}' has been created in your workspace",
                workspace_id=channel.workspace_id,
                priority=NotificationPriority.LOW,
                related_entity_type="chat_channel",
                related_entity_id=str(channel.id),
                metadata={
                    "channel_id": channel.id,
                    "channel_name": channel.name,
                    "created_by_id": channel.created_by_id,
                    "description": getattr(channel, "description", ""),
                },
            )

            logger.info(
                f"Notified {len(user_ids)} users about new chat channel: {channel.name}"
            )
            return notification_ids

        except Exception as e:
            logger.error(f"Failed to notify channel creation: {e}")
            return []
        finally:
            session.close()

    async def _notify_comment_thread_creation(self, thread: Any) -> None:
        """Notify relevant users about new comment thread."""
        try:
            if not hasattr(thread, "workspace_id") or not thread.workspace_id:
                logger.warning("Thread missing workspace_id for notification")
                return

            session = self.session_factory()

            # Get stakeholders based on commentable type
            stakeholder_ids = set()

            # Strategy 1: Notify workspace collaborators with access to the commentable resource
            from ..core.workspace_manager import WorkspaceResource, WorkspaceMember

            # Get workspace members who could be interested
            workspace_members = (
                session.query(WorkspaceMember)
                .filter_by(workspace_id=thread.workspace_id, is_active=True)
                .all()
            )

            # Filter based on commentable type and access permissions
            for member in workspace_members:
                # Don't notify the thread creator
                if member.user_id == thread.created_by_id:
                    continue

                # Check if user has access to the commentable resource
                has_access = await self._check_commentable_access(
                    member.user_id,
                    thread.commentable_type,
                    thread.commentable_id,
                    thread.workspace_id,
                )

                if has_access:
                    stakeholder_ids.add(member.user_id)

            if not stakeholder_ids:
                logger.debug(
                    f"No stakeholders to notify for comment thread on {thread.commentable_type}:{thread.commentable_id}"
                )
                return

            # Get the first comment content for preview
            from .comment_manager import Comment

            first_comment = (
                session.query(Comment)
                .filter_by(thread_id=thread.id, is_deleted=False)
                .order_by(Comment.created_on.asc())
                .first()
            )

            comment_preview = ""
            if first_comment:
                comment_preview = (
                    first_comment.content[:100] + "..."
                    if len(first_comment.content) > 100
                    else first_comment.content
                )

            # Create notifications
            notification_ids = (
                await self.notification_manager.create_bulk_notifications(
                    user_ids=list(stakeholder_ids),
                    notification_type=NotificationType.COMMENT_THREAD,
                    title=f"New comment thread on {thread.commentable_type}",
                    message=f"A new comment thread was started: {comment_preview}",
                    workspace_id=thread.workspace_id,
                    priority=NotificationPriority.NORMAL,
                    related_entity_type="comment_thread",
                    related_entity_id=str(thread.id),
                    metadata={
                        "thread_id": thread.id,
                        "commentable_type": thread.commentable_type,
                        "commentable_id": thread.commentable_id,
                        "created_by_id": thread.created_by_id,
                        "comment_preview": comment_preview,
                    },
                )
            )

            logger.info(
                f"Notified {len(stakeholder_ids)} stakeholders about new comment thread on {thread.commentable_type}"
            )
            return notification_ids

        except Exception as e:
            logger.error(f"Failed to notify comment thread creation: {e}")
            return []
        finally:
            session.close()

    async def _check_commentable_access(
        self,
        user_id: int,
        commentable_type: str,
        commentable_id: str,
        workspace_id: str,
    ) -> bool:
        """Check if user has access to comment on the specified resource."""
        try:
            # Basic access check - for now, allow all workspace members
            # In a real implementation, this would check specific permissions based on:
            # - Resource type (document, form, dashboard, etc.)
            # - User role in workspace
            # - Resource-specific permissions
            # - Privacy settings

            # For MVP: allow all active workspace members
            session = self.session_factory()
            from ..core.workspace_manager import WorkspaceMember

            member = (
                session.query(WorkspaceMember)
                .filter_by(workspace_id=workspace_id, user_id=user_id, is_active=True)
                .first()
            )

            return member is not None

        except Exception as e:
            logger.error(f"Error checking commentable access for user {user_id}: {e}")
            # Fail secure - deny access on error
            return False
        finally:
            session.close()

    async def _notify_comment_reply(self, comment: Any) -> None:
        """Notify thread participants about new comment reply."""
        try:
            session = self.session_factory()

            # Get thread participants (authors of previous comments)
            thread_comments = (
                session.query(Comment)
                .filter_by(thread_id=comment.thread_id, is_deleted=False)
                .all()
            )

            participant_ids = set()
            for thread_comment in thread_comments:
                if thread_comment.author_id != comment.author_id:  # Don't notify author
                    participant_ids.add(thread_comment.author_id)

            # Send notifications
            for user_id in participant_ids:
                await self.notification_manager.create_notification(
                    user_id=user_id,
                    notification_type=NotificationType.COMMENT_REPLY,
                    title="New reply in comment thread",
                    message=f"Someone replied to a comment thread you participated in",
                    workspace_id=comment.thread.workspace_id,
                    related_entity_type="comment",
                    related_entity_id=str(comment.id),
                    metadata={
                        "thread_id": comment.thread_id,
                        "author_id": comment.author_id,
                    },
                )

        except Exception as e:
            logger.error(f"Failed to notify comment reply: {e}")
        finally:
            session.close()

    async def _notify_thread_resolution(
        self, thread_id: int, resolved_by_id: int
    ) -> None:
        """Notify thread participants about resolution."""
        try:
            session = self.session_factory()

            thread = session.query(CommentThread).get(thread_id)
            if not thread:
                return

            # Get thread participants
            thread_comments = (
                session.query(Comment)
                .filter_by(thread_id=thread_id, is_deleted=False)
                .all()
            )

            participant_ids = set()
            for comment in thread_comments:
                if comment.author_id != resolved_by_id:  # Don't notify resolver
                    participant_ids.add(comment.author_id)

            # Send notifications
            for user_id in participant_ids:
                await self.notification_manager.create_notification(
                    user_id=user_id,
                    notification_type=NotificationType.THREAD_RESOLVED,
                    title="Comment thread resolved",
                    message=f"A comment thread you participated in has been resolved",
                    workspace_id=thread.workspace_id,
                    related_entity_type="comment_thread",
                    related_entity_id=str(thread_id),
                    metadata={
                        "resolved_by_id": resolved_by_id,
                        "commentable_type": thread.commentable_type,
                        "commentable_id": thread.commentable_id,
                    },
                )

        except Exception as e:
            logger.error(f"Failed to notify thread resolution: {e}")
        finally:
            session.close()

    async def _typing_cleanup_loop(self) -> None:
        """Background loop to clean up stale typing indicators."""
        while True:
            try:
                await self.chat_manager.cleanup_typing_indicators()
                await asyncio.sleep(10)  # Clean up every 10 seconds
            except Exception as e:
                logger.error(f"Error in typing cleanup loop: {e}")
                await asyncio.sleep(30)  # Retry in 30 seconds on error
