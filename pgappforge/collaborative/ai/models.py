"""
AI Models for PgAppForge Collaborative Features

Database models for AI components including vector embeddings,
chatbot conversations, and knowledge base content.
"""

import json
from typing import Dict, Any, List
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Index
from pgappforge import Model
from pgappforge.models.mixins import AuditMixin


class VectorEmbedding(Model, AuditMixin):
    """Vector embeddings storage with PgAppForge integration."""

    __tablename__ = "fab_vector_embeddings"

    id = Column(Integer, primary_key=True)

    # Document identification
    document_id = Column(String(255), nullable=False, index=True)
    document_type = Column(String(50), nullable=False)
    chunk_index = Column(Integer, default=0)
    content_hash = Column(String(64), nullable=False, index=True)

    # Content and metadata
    content = Column(Text, nullable=False)
    # Changed from 'metadata' to 'meta_data' to avoid SQLAlchemy reserved name
    meta_data = Column(Text)  # JSON string

    # Embeddings (stored as JSON for flexibility)
    embedding_vector = Column(Text, nullable=False)  # JSON array
    embedding_model = Column(String(100), nullable=False)

    # Workspace/access control
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"))
    team_id = Column(Integer, ForeignKey("fab_teams.id"))
    user_id = Column(Integer, ForeignKey("ab_user.id"))

    # Performance optimization
    content_length = Column(Integer)
    language = Column(String(10), default="en")

    # Timestamps handled by AuditMixin (created_at, updated_at)

    # Indexes for efficient querying
    __table_args__ = (
        Index("ix_embedding_workspace", "workspace_id"),
        Index("ix_embedding_team", "team_id"),
        Index("ix_embedding_type", "document_type"),
        Index("ix_embedding_content_hash", "content_hash"),
        Index("ix_embedding_composite", "workspace_id", "document_type"),
    )

    def get_embedding_vector(self) -> List[float]:
        """Parse embedding vector from JSON."""
        try:
            return json.loads(self.embedding_vector)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_embedding_vector(self, vector: List[float]):
        """Store embedding vector as JSON."""
        self.embedding_vector = json.dumps(vector)

    def get_metadata(self) -> Dict[str, Any]:
        """Parse metadata from JSON."""
        try:
            return json.loads(self.meta_data) if self.meta_data else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_metadata(self, metadata: Dict[str, Any]):
        """Store metadata as JSON."""
        self.meta_data = json.dumps(metadata) if metadata else None