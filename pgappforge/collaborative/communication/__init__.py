"""
Communication package for collaborative workspaces.

Provides real-time chat, contextual comments, and comprehensive
notification systems for collaborative PgForge applications.
"""

from .chat_manager import (
    ChatManager,
    ChatChannel,
    ChatChannelMember,
    ChatMessage,
    MessageType,
)

from .comment_manager import (
    CommentManager,
    CommentThread,
    Comment,
    CommentReaction,
    CommentableType,
    CommentStatus,
)

from .notification_manager import (
    NotificationManager,
    Notification,
    NotificationPreference,
    NotificationDelivery,
    NotificationDigest,
    NotificationType,
    NotificationPriority,
    DeliveryChannel,
)

__all__ = [
    # Chat system
    "ChatManager",
    "ChatChannel",
    "ChatChannelMember",
    "ChatMessage",
    "MessageType",
    # Comment system
    "CommentManager",
    "CommentThread",
    "Comment",
    "CommentReaction",
    "CommentableType",
    "CommentStatus",
    # Notification system
    "NotificationManager",
    "Notification",
    "NotificationPreference",
    "NotificationDelivery",
    "NotificationDigest",
    "NotificationType",
    "NotificationPriority",
    "DeliveryChannel",
]
