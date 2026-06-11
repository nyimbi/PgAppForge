"""
pgappforge/plugins/erp/platform/nlp/models.py

SQLAlchemy 2.x models for persisting NLP analysis results.
Supports audit, tenant isolation, and cache look-up by input hash.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


class NLPAnalysisResult(AuditMixin, Model):
	"""Persisted NLP analysis result for audit trail and response caching.

	Cache key: (tenant_id, analysis_type, input_text_hash).
	"""

	__tablename__ = "plat_nlp_result"
	__table_args__ = (
		Index("ix_plat_nlp_ref", "reference_type", "reference_id"),
		Index("ix_plat_nlp_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# What kind of NLP was performed
	# CLASSIFY / SENTIMENT / ENTITIES / SUMMARIZE / EXTRACT / DETECT_LANG
	analysis_type = Column(String(30), nullable=False)

	# Optional back-reference to the originating business record
	reference_type = Column(String(50), nullable=True)   # e.g. "APInvoice"
	reference_id = Column(String(100), nullable=True)    # PK of that record

	# SHA-256 hex digest of the input text — used for cache lookups
	input_text_hash = Column(String(64), nullable=False)

	# JSON payload returned by the service method
	result = Column(JSONB, nullable=False, default=dict)

	model_used = Column(String(50), nullable=True)
	latency_ms = Column(Integer, nullable=True)

	# "llm" | "fallback" | "cache"
	source = Column(String(10), nullable=False, default="llm")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)


__all__ = ["NLPAnalysisResult"]
