"""
pgappforge/plugins/erp/analytics/operational/models.py

SQLAlchemy models for the Operational Analytics plugin.

Tables
------
analytics_kpi_definition   — KPI catalogue with formula, unit, frequency, owner
analytics_kpi_snapshot     — Point-in-time KPI actuals vs target
analytics_query            — Saved SQL queries with parameters and runtime stats
analytics_report           — Scheduled/ad-hoc report definitions with layout JSONB

Design rules
  - All PKs: UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All mutable entities: tenant_id UUID NOT NULL + AuditMixin
  - Numeric amounts: never float (Numeric columns only)
  - JSONB for semi-structured: parameters, layout, recipients
  - PostgreSQL ARRAY (TEXT[]) for tags
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
	Date,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# KPIDefinition
# ---------------------------------------------------------------------------

class KPIDefinition(AuditMixin, Model):
	"""Catalogue entry for a single KPI.

	formula TEXT stores a human-readable expression (e.g. "revenue / headcount")
	or a reference key used by the KPI calculation engine.

	target_direction controls alerting:
	  HIGHER — higher actual is better (revenue, NPS, conversion rate)
	  LOWER  — lower actual is better (churn rate, defect rate, cost)
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_kpi_definition"
	__table_args__ = (
		UniqueConstraint("tenant_id", "kpi_code", name="uq_analytics_kpi_def_tenant_code"),
		Index("ix_analytics_kpi_def_tenant", "tenant_id"),
		Index("ix_analytics_kpi_def_domain", "domain"),
		Index("ix_analytics_kpi_def_owner", "owner_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	kpi_code = Column(
		String(100),
		nullable=False,
		comment="Unique code within tenant e.g. REVENUE_MRR, CHURN_RATE",
	)
	kpi_name = Column(String(500), nullable=False)
	domain = Column(
		String(100),
		nullable=False,
		comment="Business domain e.g. finance, sales, hcm, operations",
	)
	formula = Column(
		Text,
		nullable=True,
		comment="Human-readable formula or calculation engine key",
	)
	unit = Column(
		String(50),
		nullable=True,
		comment="e.g. USD, %, count, days",
	)
	frequency = Column(
		String(20),
		nullable=False,
		default="MONTHLY",
		comment="DAILY | WEEKLY | MONTHLY | QUARTERLY",
	)
	target_value = Column(
		Numeric(20, 4),
		nullable=True,
		comment="Default target; overridden per-snapshot when needed",
	)
	target_direction = Column(
		String(10),
		nullable=False,
		default="HIGHER",
		comment="HIGHER = more is better | LOWER = less is better",
	)
	owner_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
		comment="Accountable owner (ab_user FK)",
	)
	tags: list[str] = Column(
		ARRAY(String),
		nullable=False,
		default=list,
		comment="Free-form classification tags",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	snapshots: list[KPISnapshot] = sa.orm.relationship(
		"KPISnapshot",
		back_populates="kpi",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<KPIDefinition {self.kpi_code!r} domain={self.domain!r}>"


# ---------------------------------------------------------------------------
# KPISnapshot
# ---------------------------------------------------------------------------

class KPISnapshot(Model):
	"""Point-in-time snapshot of a KPI's actual vs target value.

	Immutable ledger: do NOT update existing rows. To correct a snapshot,
	insert a new row for the same (kpi_id, snapshot_date) with revised values.
	The service layer selects the most-recent row per (kpi_id, snapshot_date).

	variance_pct = (actual - target) / target * 100, negative = below target.
	status computed on insert: ON_TRACK | AT_RISK | OFF_TRACK.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_kpi_snapshot"
	__table_args__ = (
		Index("ix_analytics_kpi_snap_kpi_date", "kpi_id", "snapshot_date"),
		Index("ix_analytics_kpi_snap_status", "status"),
		Index("ix_analytics_kpi_snap_date", "snapshot_date", postgresql_using="brin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	kpi_id = Column(
		UUID(as_uuid=False),
		ForeignKey("analytics_kpi_definition.id", ondelete="CASCADE"),
		nullable=False,
	)
	snapshot_date = Column(Date, nullable=False)
	actual_value = Column(Numeric(20, 4), nullable=False)
	target_value = Column(Numeric(20, 4), nullable=True)
	prior_period_value = Column(Numeric(20, 4), nullable=True)
	variance_pct = Column(
		Numeric(7, 2),
		nullable=True,
		comment="(actual - target) / target * 100; NULL when target is NULL",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ON_TRACK",
		comment="ON_TRACK | AT_RISK | OFF_TRACK",
	)
	recorded_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	kpi: KPIDefinition = sa.orm.relationship(
		"KPIDefinition",
		back_populates="snapshots",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<KPISnapshot kpi={self.kpi_id!r} date={self.snapshot_date!r} "
			f"actual={self.actual_value!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# AnalyticsQuery
# ---------------------------------------------------------------------------

class AnalyticsQuery(AuditMixin, Model):
	"""Saved SQL query with parameterisation support.

	query_sql may contain named parameter placeholders e.g. :tenant_id, :from_date.
	parameters JSONB describes expected parameters: {"from_date": {"type": "date"}}.
	is_public=True means any authenticated user can run it (row-level filtering
	still applies via tenant_id injection).
	average_runtime_ms is a rolling average updated by the service layer after
	each execution.
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_query"
	__table_args__ = (
		Index("ix_analytics_query_tenant", "tenant_id"),
		Index("ix_analytics_query_created_by", "created_by"),
		Index("ix_analytics_query_public", "is_public"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(500), nullable=False)
	description = Column(Text, nullable=True)
	query_sql = Column(Text, nullable=False, comment="Parameterised SQL; use :param placeholders")
	parameters: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='{"param_name": {"type": "date|string|integer", "required": true}}',
	)
	created_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	last_run_at = Column(DateTime(timezone=True), nullable=True)
	average_runtime_ms = Column(Integer, nullable=True)
	is_public = Column(Boolean, nullable=False, default=False)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return f"<AnalyticsQuery {self.id!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# AnalyticsReport
# ---------------------------------------------------------------------------

class AnalyticsReport(AuditMixin, Model):
	"""Report definition — layout, scheduling, recipients.

	layout JSONB describes the report canvas (widgets, KPIs, charts, tables).
	recipients JSONB is a list of delivery targets:
	  [{"type": "email", "address": "cfo@acme.com"}, {"type": "slack", "channel": "#finance"}]
	schedule_cron is a standard cron expression (empty string when not scheduled).
	"""

	__allow_unmapped__ = True
	__tablename__ = "analytics_report"
	__table_args__ = (
		Index("ix_analytics_report_tenant", "tenant_id"),
		Index("ix_analytics_report_category", "category"),
		Index("ix_analytics_report_scheduled", "is_scheduled"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(500), nullable=False)
	category = Column(String(100), nullable=False, comment="e.g. Finance, Sales, Operations, HR")
	layout: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Report canvas descriptor: widgets, queries, chart types",
	)
	is_scheduled = Column(Boolean, nullable=False, default=False)
	schedule_cron = Column(
		String(100),
		nullable=True,
		comment="Standard cron e.g. '0 8 * * 1' = Mondays 08:00",
	)
	last_generated_at = Column(DateTime(timezone=True), nullable=True)
	recipients: list[dict] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment='[{"type":"email","address":"x@y.com"}]',
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return f"<AnalyticsReport {self.id!r} {self.name!r} cat={self.category!r}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"KPIDefinition",
	"KPISnapshot",
	"AnalyticsQuery",
	"AnalyticsReport",
]
