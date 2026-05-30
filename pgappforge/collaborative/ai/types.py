"""
Shared types and interfaces for AI modules.

This module contains shared data types, enums, and interfaces used across
AI modules to prevent circular import dependencies.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Protocol, runtime_checkable
from enum import Enum
from datetime import datetime


class DocumentType(Enum):
    """Types of documents that can be processed"""

    # Collaboration-specific types
    CHAT_MESSAGE = "chat_message"
    COMMENT = "comment"
    WORKSPACE_RESOURCE = "workspace_resource"
    TEAM_DOCUMENT = "team_document"
    MEETING_NOTES = "meeting_notes"
    PROJECT_SPEC = "project_spec"
    CODE_REVIEW = "code_review"
    ISSUE_TRACKER = "issue_tracker"

    # General document types for broader RAG usage
    TEXT = "text"
    CODE = "code"
    HTML = "html"
    MARKDOWN = "markdown"
    PDF = "pdf"
    JSON = "json"
    XML = "xml"
    CSV = "csv"


class ChunkingStrategy(Enum):
    """Strategies for chunking documents"""

    SENTENCE_BOUNDARY = "sentence_boundary"
    PARAGRAPH_BOUNDARY = "paragraph_boundary"
    FIXED_SIZE = "fixed_size"
    CODE_BLOCKS = "code_blocks"
    SEMANTIC_SECTIONS = "semantic_sections"


@dataclass
class DocumentChunk:
    """Represents a chunk of a document for processing and storage"""

    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    document_id: str = ""
    document_type: DocumentType = DocumentType.TEXT

    # Optional fields
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    parent_chunk_id: Optional[str] = None

    # Generated fields
    content_hash: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def get_content_hash(self) -> str:
        """Generate content hash for deduplication."""
        if self.content_hash is None:
            import hashlib
            self.content_hash = hashlib.sha256(self.content.encode()).hexdigest()
        return self.content_hash


@dataclass
class RetrievalResult:
    """Result from vector similarity search"""

    chunk: DocumentChunk
    similarity_score: float
    rank: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EmbeddingModelProtocol(Protocol):
    """Protocol for embedding models to prevent circular imports"""

    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text"""
        ...

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        ...


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Protocol for vector stores to prevent circular imports"""

    async def add_documents(self, chunks: List[DocumentChunk], **kwargs) -> List[str]:
        """Add documents to the vector store"""
        ...

    async def similarity_search(self, query: str, k: int = 5, **kwargs) -> List[RetrievalResult]:
        """Perform similarity search"""
        ...

    async def delete_documents(self, document_ids: List[str]) -> int:
        """Delete documents by IDs"""
        ...