"""
AI-powered features for PgForge collaborative platform.

This module provides AI chatbot capabilities and Retrieval-Augmented Generation
for intelligent assistance within workspaces and teams.
"""

from .chatbot_service import ChatbotService
from .rag_engine import RAGEngine
from .ai_models import AIModelAdapter
from .knowledge_base import KnowledgeBaseManager

__all__ = [
    "ChatbotService", 
    "RAGEngine", 
    "AIModelAdapter", 
    "KnowledgeBaseManager"
]