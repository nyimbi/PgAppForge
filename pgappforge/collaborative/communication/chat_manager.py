"""
Real-time chat system for collaborative workspaces.

Provides threaded conversations, direct messaging, and workspace channels
with real-time delivery and message history.
"""

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from pgappforge.models.sqla import Model
from pgappforge.models.mixins import AuditMixin

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Types of chat messages."""

    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    SYSTEM = "system"
    THREAD_REPLY = "thread_reply"


class ChatChannel(Model, AuditMixin):
    """Chat channel model for workspace communications with PgAppForge integration."""

    __tablename__ = "fab_chat_channels"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    is_private = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    messages = relationship(
        "ChatMessage", back_populates="channel", cascade="all, delete-orphan"
    )
    members = relationship(
        "ChatChannelMember", back_populates="channel", cascade="all, delete-orphan"
    )


class ChatChannelMember(Model, AuditMixin):
    """Membership table for chat channels with PgAppForge integration."""

    __tablename__ = "fab_chat_channel_members"

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("fab_chat_channels.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_admin = Column(Boolean, default=False)
    last_read_message_id = Column(
        Integer, ForeignKey("fab_chat_messages.id"), nullable=True
    )

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    channel = relationship("ChatChannel", back_populates="members")


class ChatMessage(Model, AuditMixin):
    """Chat message model with PgAppForge integration."""

    __tablename__ = "fab_chat_messages"

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("fab_chat_channels.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    message_type = Column(String(20), default=MessageType.TEXT.value)
    content = Column(Text, nullable=False)
    thread_parent_id = Column(
        Integer, ForeignKey("fab_chat_messages.id"), nullable=True
    )
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    edited_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False)

    # Metadata for different message types
    file_url = Column(String(500), nullable=True)  # For file/image messages
    file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)

    # created_by_id and audit fields are provided by AuditMixin

    # Relationships
    channel = relationship("ChatChannel", back_populates="messages")
    thread_replies = relationship("ChatMessage", remote_side=[id])


class ChatManager:
    """Manages chat functionality for collaborative workspaces."""

    def __init__(self, websocket_manager=None, session_factory=None):
        self.websocket_manager = websocket_manager
        self.session_factory = session_factory
        self.active_channels: Dict[int, Set[int]] = {}  # channel_id -> set of user_ids
        self.user_typing: Dict[
            int, Dict[int, float]
        ] = {}  # channel_id -> {user_id: timestamp}

    async def create_channel(
        self,
        workspace_id: int,
        name: str,
        description: str,
        created_by_id: int,
        is_private: bool = False,
    ) -> ChatChannel:
        """Create a new chat channel."""
        try:
            session = self.session_factory()

            channel = ChatChannel(
                workspace_id=workspace_id,
                name=name,
                description=description,
                created_by_id=created_by_id,
                is_private=is_private,
            )

            session.add(channel)
            session.flush()  # Get the ID

            # Add creator as admin member
            member = ChatChannelMember(
                channel_id=channel.id, user_id=created_by_id, is_admin=True
            )
            session.add(member)
            session.commit()

            logger.info(f"Created chat channel '{name}' in workspace {workspace_id}")

            # Notify workspace members
            await self._notify_channel_created(channel)

            return channel

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create chat channel: {e}")
            raise
        finally:
            session.close()

    async def join_channel(self, channel_id: int, user_id: int) -> bool:
        """Add user to a chat channel."""
        try:
            session = self.session_factory()

            # Check if already a member
            existing = (
                session.query(ChatChannelMember)
                .filter_by(channel_id=channel_id, user_id=user_id)
                .first()
            )

            if existing:
                return True

            # Check channel permissions
            channel = session.query(ChatChannel).get(channel_id)
            if not channel or not channel.is_active:
                return False

            member = ChatChannelMember(channel_id=channel_id, user_id=user_id)
            session.add(member)
            session.commit()

            # Add to active users if online
            if channel_id not in self.active_channels:
                self.active_channels[channel_id] = set()

            # Notify channel members
            await self._notify_user_joined(channel_id, user_id)

            logger.info(f"User {user_id} joined channel {channel_id}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to join channel: {e}")
            return False
        finally:
            session.close()

    async def send_message(
        self,
        channel_id: int,
        sender_id: int,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        thread_parent_id: Optional[int] = None,
        file_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[ChatMessage]:
        """Send a message to a chat channel."""
        try:
            session = self.session_factory()

            # Verify user can send to channel
            member = (
                session.query(ChatChannelMember)
                .filter_by(channel_id=channel_id, user_id=sender_id)
                .first()
            )

            if not member:
                logger.warning(f"User {sender_id} not a member of channel {channel_id}")
                return None

            message = ChatMessage(
                channel_id=channel_id,
                sender_id=sender_id,
                message_type=message_type.value,
                content=content,
                thread_parent_id=thread_parent_id,
            )

            # Add file metadata if present
            if file_metadata:
                message.file_url = file_metadata.get("url")
                message.file_name = file_metadata.get("name")
                message.file_size = file_metadata.get("size")

            session.add(message)
            session.commit()

            # Real-time delivery to channel members
            await self._deliver_message(message)

            logger.info(f"Message sent to channel {channel_id} by user {sender_id}")
            return message

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to send message: {e}")
            return None
        finally:
            session.close()

    async def get_channel_messages(
        self,
        channel_id: int,
        user_id: int,
        limit: int = 50,
        before_message_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get messages from a channel with pagination."""
        try:
            session = self.session_factory()

            # Verify user access
            member = (
                session.query(ChatChannelMember)
                .filter_by(channel_id=channel_id, user_id=user_id)
                .first()
            )

            if not member:
                return []

            query = session.query(ChatMessage).filter_by(
                channel_id=channel_id, is_deleted=False
            )

            if before_message_id:
                query = query.filter(ChatMessage.id < before_message_id)

            messages = query.order_by(ChatMessage.sent_at.desc()).limit(limit).all()

            # Convert to dict format
            result = []
            for msg in reversed(messages):  # Reverse to get chronological order
                result.append(
                    {
                        "id": msg.id,
                        "sender_id": msg.sender_id,
                        "content": msg.content,
                        "message_type": msg.message_type,
                        "sent_at": msg.sent_at.isoformat(),
                        "edited_at": msg.edited_at.isoformat()
                        if msg.edited_at
                        else None,
                        "thread_parent_id": msg.thread_parent_id,
                        "file_url": msg.file_url,
                        "file_name": msg.file_name,
                        "file_size": msg.file_size,
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Failed to get channel messages: {e}")
            return []
        finally:
            session.close()

    async def mark_channel_read(
        self, channel_id: int, user_id: int, last_message_id: int
    ) -> bool:
        """Mark channel as read up to a specific message."""
        try:
            session = self.session_factory()

            member = (
                session.query(ChatChannelMember)
                .filter_by(channel_id=channel_id, user_id=user_id)
                .first()
            )

            if member:
                member.last_read_message_id = last_message_id
                session.commit()
                return True

            return False

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to mark channel read: {e}")
            return False
        finally:
            session.close()

    async def set_typing_indicator(
        self, channel_id: int, user_id: int, is_typing: bool
    ) -> None:
        """Set typing indicator for user in channel."""
        try:
            if channel_id not in self.user_typing:
                self.user_typing[channel_id] = {}

            if is_typing:
                self.user_typing[channel_id][user_id] = datetime.now(
                    timezone.utc
                ).timestamp()
            else:
                self.user_typing[channel_id].pop(user_id, None)

            # Broadcast typing state to channel members
            await self._broadcast_typing_state(channel_id, user_id, is_typing)

        except Exception as e:
            logger.error(f"Failed to set typing indicator: {e}")

    async def get_user_channels(
        self, user_id: int, workspace_id: int
    ) -> List[Dict[str, Any]]:
        """Get all channels for a user in a workspace."""
        try:
            session = self.session_factory()

            channels = (
                session.query(ChatChannel)
                .join(ChatChannelMember)
                .filter(
                    ChatChannel.workspace_id == workspace_id,
                    ChatChannelMember.user_id == user_id,
                    ChatChannel.is_active == True,
                )
                .all()
            )

            result = []
            for channel in channels:
                # Get unread count
                member = next(
                    (m for m in channel.members if m.user_id == user_id), None
                )
                last_read_id = member.last_read_message_id if member else 0

                unread_count = (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.channel_id == channel.id,
                        ChatMessage.id > (last_read_id or 0),
                        ChatMessage.is_deleted == False,
                    )
                    .count()
                )

                result.append(
                    {
                        "id": channel.id,
                        "name": channel.name,
                        "description": channel.description,
                        "is_private": channel.is_private,
                        "created_at": channel.created_at.isoformat(),
                        "unread_count": unread_count,
                        "member_count": len(channel.members),
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Failed to get user channels: {e}")
            return []
        finally:
            session.close()

    async def _deliver_message(self, message: ChatMessage) -> None:
        """Deliver message to all channel members via WebSocket."""
        if not self.websocket_manager:
            return

        try:
            session = self.session_factory()

            # Get channel members
            members = (
                session.query(ChatChannelMember)
                .filter_by(channel_id=message.channel_id)
                .all()
            )

            message_data = {
                "type": "chat_message",
                "channel_id": message.channel_id,
                "message": {
                    "id": message.id,
                    "sender_id": message.sender_id,
                    "content": message.content,
                    "message_type": message.message_type,
                    "sent_at": message.sent_at.isoformat(),
                    "thread_parent_id": message.thread_parent_id,
                    "file_url": message.file_url,
                    "file_name": message.file_name,
                    "file_size": message.file_size,
                },
            }

            # Send to all members
            for member in members:
                await self.websocket_manager.send_to_user(member.user_id, message_data)

        except Exception as e:
            logger.error(f"Failed to deliver message: {e}")
        finally:
            session.close()

    async def _notify_channel_created(self, channel: ChatChannel) -> None:
        """Notify workspace members about new channel."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "channel_created",
            "workspace_id": channel.workspace_id,
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "is_private": channel.is_private,
                "created_by_id": channel.created_by_id,
            },
        }

        await self.websocket_manager.broadcast_to_workspace(
            channel.workspace_id, notification
        )

    async def _notify_user_joined(self, channel_id: int, user_id: int) -> None:
        """Notify channel members about new user."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "user_joined_channel",
            "channel_id": channel_id,
            "user_id": user_id,
        }

        await self.websocket_manager.broadcast_to_channel(channel_id, notification)

    async def _broadcast_typing_state(
        self, channel_id: int, user_id: int, is_typing: bool
    ) -> None:
        """Broadcast typing indicator to channel members."""
        if not self.websocket_manager:
            return

        notification = {
            "type": "typing_indicator",
            "channel_id": channel_id,
            "user_id": user_id,
            "is_typing": is_typing,
        }

        await self.websocket_manager.broadcast_to_channel(
            channel_id, notification, exclude_user=user_id
        )

    async def cleanup_typing_indicators(self) -> None:
        """Clean up stale typing indicators."""
        current_time = datetime.now(timezone.utc).timestamp()
        timeout = 5.0  # 5 seconds timeout

        for channel_id in list(self.user_typing.keys()):
            for user_id in list(self.user_typing[channel_id].keys()):
                if current_time - self.user_typing[channel_id][user_id] > timeout:
                    del self.user_typing[channel_id][user_id]
                    await self._broadcast_typing_state(channel_id, user_id, False)

            # Clean up empty channels
            if not self.user_typing[channel_id]:
                del self.user_typing[channel_id]
