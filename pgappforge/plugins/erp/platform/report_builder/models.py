"""
pgappforge/plugins/erp/platform/report_builder/models.py

SQLAlchemy model for the No-Code Report Builder plugin.

Table prefix: pgaf_report
PostgreSQL ONLY — JSONB for ReportBro report definition.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	Index,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _uuid7str() -> str:
	try:
		from uuid6 import uuid7
		return str(uuid7())
	except ImportError:
		import uuid
		return str(uuid.uuid4())


class SavedReport(AuditMixin, Model):
	"""Persisted ReportBro report definition with metadata.

	report_definition holds the full ReportBro JSON (elements, styles, etc.)
	exported from the browser-side designer and round-tripped unchanged to
	reportbro-lib for server-side PDF rendering.
	"""

	__tablename__ = "pgaf_report"

	id = Column(String(36), primary_key=True, default=_uuid7str)
	tenant_id = Column(String(36), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)

	# Full ReportBro designer JSON — stored verbatim, never mutated server-side
	report_definition = Column(JSONB, nullable=False, default=dict)

	# standard | financial | statistical
	report_type = Column(String(20), nullable=False, default="standard")

	# Access control
	is_public = Column(Boolean, nullable=False, default=False)   # visible to all users in tenant
	is_template = Column(Boolean, nullable=False, default=False)  # usable as template for new reports

	# Data sourcing — exactly one of these should be set (or neither for static/sample data)
	data_source_query = Column(Text, nullable=True)        # Raw SQL SELECT
	data_source_model = Column(String(100), nullable=True) # SQLAlchemy model class name

	created_by = Column(String(36), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now,
		onupdate=_now,
		server_default=sa.text("NOW()"),
	)

	__table_args__ = (
		Index("ix_pgaf_report_tenant", "tenant_id"),
		Index("ix_pgaf_report_type", "report_type"),
	)

	def __repr__(self) -> str:
		return f"<SavedReport {self.name!r} tenant={self.tenant_id!r}>"


__all__ = ["SavedReport"]
