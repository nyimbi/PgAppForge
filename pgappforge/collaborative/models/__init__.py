"""
Collaborative Features Database Models

All database models for collaborative features should be imported here
to ensure proper registration with PgForge's SQLAlchemy metadata.
"""

# Import all model classes to ensure they're registered with SQLAlchemy
from ..core.team_manager import (
    Team,
    TeamInvitation,
    TeamWorkspace,
)

from ..core.workspace_manager import (
    Workspace,
    WorkspaceResource,
    WorkspaceMember,
    ResourceVersion,
    ResourcePermission,
    WorkspaceActivity,
)

from ..communication.notification_manager import (
    Notification,
    NotificationPreference,
    NotificationDelivery,
    NotificationDigest,
)

from ..communication.comment_manager import (
    CommentThread,
    Comment,
    CommentReaction,
)

from ..communication.chat_manager import (
    ChatChannel,
    ChatChannelMember,
    ChatMessage,
)

from ..integration.version_control import (
    Repository,
    Branch,
    Commit,
    CommitChange,
    MergeRequest,
    MergeConflict,
)

from ..ai.models import VectorEmbedding
from ..ai.chatbot_service import ChatbotConversation, ChatbotMessage
from ..ai.knowledge_base import IndexedContent

# Export all models for PgForge registration
__all__ = [
    # Team models
    "Team",
    "TeamInvitation", 
    "TeamWorkspace",
    
    # Workspace models
    "Workspace",
    "WorkspaceResource",
    "WorkspaceMember",
    "ResourceVersion",
    "ResourcePermission",
    "WorkspaceActivity",
    
    # Communication models
    "Notification",
    "NotificationPreference",
    "NotificationDelivery",
    "NotificationDigest",
    "CommentThread",
    "Comment",
    "CommentReaction",
    "ChatChannel",
    "ChatChannelMember",
    "ChatMessage",
    
    # Version control models
    "Repository",
    "Branch",
    "Commit",
    "CommitChange",
    "MergeRequest",
    "MergeConflict",

    # AI models
    "VectorEmbedding",
    "ChatbotConversation",
    "ChatbotMessage",
    "IndexedContent",
]