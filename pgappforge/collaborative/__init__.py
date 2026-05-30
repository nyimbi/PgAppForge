"""
PgForge Collaborative Features

Real-time collaboration, team management, and shared workspace capabilities
for PgForge applications.
"""

from .core.collaboration_engine import CollaborationEngine
from .core.team_manager import TeamManager
from .core.workspace_manager import WorkspaceManager
from .realtime.websocket_manager import WebSocketManager
from .editing.multi_user_editor import MultiUserEditor
from .communication.communication_service import CommunicationService
from .integration.version_control import VersionControlIntegration

# AI Components
from .ai.chatbot_service import ChatbotService
from .ai.knowledge_base import KnowledgeBaseManager
from .ai.rag_engine import RAGEngine
from .ai.ai_models import ModelManager, AIModelAdapter

__all__ = [
    "CollaborationEngine",
    "TeamManager", 
    "WorkspaceManager",
    "WebSocketManager",
    "MultiUserEditor",
    "CommunicationService",
    "VersionControlIntegration",
    # AI Components
    "ChatbotService",
    "KnowledgeBaseManager",
    "RAGEngine",
    "ModelManager",
    "AIModelAdapter",
]
