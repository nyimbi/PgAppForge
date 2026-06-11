"""
pgappforge/plugins/erp/platform/rag/models.py

SQLAlchemy models for the RAG (Retrieval-Augmented Generation) plugin.

Table prefix: plat_rag_
PostgreSQL ONLY — JSONB embeddings, content dedup via SHA-256, pgvector-ready.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Source type constants — what kind of ERP record was indexed
# ---------------------------------------------------------------------------
SOURCE_ERP_GL_ENTRY	= "ERP_GL_ENTRY"
SOURCE_POLICY		= "POLICY"
SOURCE_MANUAL		= "MANUAL"
SOURCE_FAQ		= "FAQ"
SOURCE_CONTRACT		= "CONTRACT"
SOURCE_TICKET		= "TICKET"
SOURCE_GL_ACCOUNT	= "GL_ACCOUNT"


class RAGDocument(AuditMixin, Model):
	"""A document ingested into the RAG knowledge base.

	One document maps 1-to-many RAGChunks.  Deduplication is enforced via
	the (tenant_id, content_hash) unique constraint so the same text is never
	embedded twice.

	source_type values: ERP_GL_ENTRY | POLICY | MANUAL | FAQ | CONTRACT |
	                    TICKET | GL_ACCOUNT (and any custom string).
	"""

	__tablename__ = "plat_rag_document"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False)

	# --- provenance ----------------------------------------------------------
	source_type = Column(String(50), nullable=False)
	source_id   = Column(String(100), nullable=True)   # FK to source record

	# --- content -------------------------------------------------------------
	title        = Column(String(500), nullable=True)
	content      = Column(Text, nullable=False)
	content_hash = Column(String(64), nullable=False)  # SHA-256 hex digest

	# --- metadata ------------------------------------------------------------
	language = Column(String(10), nullable=False, default="en")
	# {author, department, tags, version, ...}
	doc_metadata = Column(JSONB, nullable=False, default=dict, comment="Document metadata: author, tags, version, department")

	# --- indexing state ------------------------------------------------------
	is_active   = Column(Boolean, nullable=False, default=True)
	chunk_count = Column(Integer, nullable=False, default=0)
	indexed_at  = Column(DateTime(timezone=True), nullable=True)

	# --- timestamps (AuditMixin adds created_on / changed_on) ---------------
	created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
	updated_at = Column(
		DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
	)

	# --- relationships -------------------------------------------------------
	chunks = relationship(
		"RAGChunk",
		back_populates="document",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	# --- constraints / indexes -----------------------------------------------
	__table_args__ = (
		Index("ix_plat_rag_document_tenant",	"tenant_id"),
		Index("ix_plat_rag_document_source_type",	"source_type"),
		UniqueConstraint(
			"tenant_id", "content_hash",
			name="uq_plat_rag_document_tenant_hash",
		),
	)

	def __repr__(self) -> str:
		return f"<RAGDocument id={self.id!r} source_type={self.source_type!r} title={self.title!r}>"


class RAGChunk(Model):
	"""A single text chunk belonging to a RAGDocument, with its embedding.

	Embeddings are stored as a JSONB list of floats (1 536 dimensions for
	text-embedding-ada-002).  This keeps the schema portable and lets us
	migrate to a native pgvector VECTOR column later without changing
	application code.
	"""

	__tablename__ = "plat_rag_chunk"

	id          = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id   = Column(String(36), nullable=False)
	document_id = Column(
		String(36),
		ForeignKey("plat_rag_document.id", ondelete="CASCADE"),
		nullable=False,
	)

	chunk_index    = Column(Integer, nullable=False)
	content        = Column(Text, nullable=False)
	content_length = Column(Integer, nullable=False)

	# Embedding stored as JSONB list of floats.
	# text-embedding-ada-002 → 1 536 dimensions.
	# pgvector VECTOR type can be added as an ALTER TABLE later.
	embedding       = Column(JSONB, nullable=True)
	embedding_model = Column(String(50), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

	# --- relationships -------------------------------------------------------
	document = relationship("RAGDocument", back_populates="chunks")

	# --- indexes -------------------------------------------------------------
	__table_args__ = (
		Index("ix_plat_rag_chunk_tenant_doc", "tenant_id", "document_id"),
	)

	def __repr__(self) -> str:
		return (
			f"<RAGChunk id={self.id!r} document_id={self.document_id!r}"
			f" chunk_index={self.chunk_index}>"
		)


__all__ = [
	"RAGDocument",
	"RAGChunk",
	"SOURCE_ERP_GL_ENTRY",
	"SOURCE_POLICY",
	"SOURCE_MANUAL",
	"SOURCE_FAQ",
	"SOURCE_CONTRACT",
	"SOURCE_TICKET",
	"SOURCE_GL_ACCOUNT",
]
