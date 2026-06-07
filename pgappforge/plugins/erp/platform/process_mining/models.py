"""
pgappforge/plugins/erp/platform/process_mining/models.py

SQLAlchemy model for the Process Mining plugin.

Table prefix: pm_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Column,
	DateTime,
	Index,
	String,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


class ProcessMiningDefinition(AuditMixin, Model):
	"""Persists a process mining analysis definition and its last-run metrics."""

	__tablename__ = "pm_definition"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	name = Column(String(200), nullable=False)

	# List of event_type strings to include in this process analysis
	event_types = Column(JSONB, nullable=False, default=list)

	last_run = Column(DateTime(timezone=True), nullable=True)

	# Stores latest computed metrics: avg_cycle_time, case_count, etc.
	metrics = Column(JSONB, nullable=True, default=dict)

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_pm_definition_name_tenant"),
	)

	def __repr__(self) -> str:
		return f"<ProcessMiningDefinition {self.name!r}>"
