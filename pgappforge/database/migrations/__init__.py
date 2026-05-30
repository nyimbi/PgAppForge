"""
Database Migrations for PgAppForge AI Features

This package contains database migrations for AI-powered collaborative features
including RAG (Retrieval-Augmented Generation), chatbot functionality, and
knowledge base management.

Available Migrations:
- ai_models_001: VectorEmbedding table for RAG system
- ai_models_002: Chatbot conversation and message tables  
- ai_models_003: IndexedContent table for knowledge base

Usage:
    from pgappforge.database.migrations import apply_ai_migrations
    apply_ai_migrations.apply_all_ai_migrations()

Or run directly:
    python apply_ai_migrations.py apply
    python apply_ai_migrations.py status
    python apply_ai_migrations.py rollback migration_ids
"""

__version__ = "1.0.0"
__author__ = "PgAppForge AI Team"

# Make migration modules available at package level
from . import ai_models_001_create_vector_embedding_table
from . import ai_models_002_create_chatbot_tables
from . import ai_models_003_create_indexed_content_table
from . import apply_ai_migrations

__all__ = [
    "ai_models_001_create_vector_embedding_table",
    "ai_models_002_create_chatbot_tables", 
    "ai_models_003_create_indexed_content_table",
    "apply_ai_migrations"
]