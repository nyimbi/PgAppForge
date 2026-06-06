"""
pgappforge/plugins/erp/hcm/analytics/models.py

SQLAlchemy models for the HR Analytics plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields (data, factors, parameters, result_data)
  - Composite indexes for tenant + type hot paths
  - PostgreSQL-only: JSONB, UUID, gen_random_uuid()

Table prefix: hr_anl_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# HrAnalyticsSnapshot
# ---------------------------------------------------------------------------

class HrAnalyticsSnapshot(AuditMixin, Model):
	"""Point-in-time analytics snapshot for a tenant / entity.

	snapshot_type:
	  HEADCOUNT     — total + breakdowns (dept, type, gender)
	  TURNOVER      — termination rate for a period
	  DIVERSITY     — gender + age distribution
	  COST_PER_HIRE — recruitment cost efficiency
	  TIME_TO_FILL  — average days from open to accepted offer
	  ENGAGEMENT    — engagement score aggregates

	period: coarse period key e.g. "2025-Q1", "2025-01", "2025"
	entity_id: department or cost-centre UUID; NULL = whole tenant.
	data: JSONB blob of the full computed result (schema varies by type).
	"""

	__allow_unmapped__ = True
	__tablename__ = "hr_anl_snapshot"
	__table_args__ = (
		Index("ix_hr_anl_snap_tenant_type_period", "tenant_id", "snapshot_type", "period"),
		Index("ix_hr_anl_snap_tenant_entity", "tenant_id", "entity_id"),
		Index("ix_hr_anl_snap_computed_at", "computed_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	snapshot_type = Column(
		String(50),
		nullable=False,
		comment="HEADCOUNT | TURNOVER | DIVERSITY | COST_PER_HIRE | TIME_TO_FILL | ENGAGEMENT",
	)
	period = Column(
		String(20),
		nullable=False,
		comment="Coarse period key e.g. '2025-Q1', '2025-01', '2025'",
	)
	entity_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Department/cost-centre UUID; NULL = whole tenant",
	)
	data = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Full computed result; schema varies by snapshot_type",
	)
	computed_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	period_start = Column(Date, nullable=True, comment="Inclusive start date of the period")
	period_end = Column(Date, nullable=True, comment="Inclusive end date of the period")

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
		return (
			f"<HrAnalyticsSnapshot type={self.snapshot_type!r} "
			f"period={self.period!r} tenant={self.tenant_id!r}>"
		)


# ---------------------------------------------------------------------------
# HrFlightRiskScore
# ---------------------------------------------------------------------------

class HrFlightRiskScore(AuditMixin, Model):
	"""Flight risk score for a single employee at a point in time.

	score: 0–100, higher = higher flight risk.
	risk_level: LOW (0–30) | MEDIUM (31–60) | HIGH (61–80) | CRITICAL (81–100).
	factors: JSONB list of {factor: str, weight: int, value: any} dicts.
	is_current: True on the latest row; all prior rows are False.

	Service pattern: on each recompute, set all prior rows is_current=False,
	insert new row with is_current=True.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hr_anl_flight_risk"
	__table_args__ = (
		Index("ix_hr_anl_fr_employee_current", "employee_id", "is_current"),
		Index("ix_hr_anl_fr_tenant_level_current", "tenant_id", "risk_level", "is_current"),
		Index("ix_hr_anl_fr_computed_at", "computed_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	employee_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK to HCM employee / personnel master",
	)
	score = Column(
		Integer,
		nullable=False,
		comment="0–100, higher = higher flight risk",
	)
	risk_level = Column(
		String(20),
		nullable=False,
		comment="LOW | MEDIUM | HIGH | CRITICAL",
	)
	factors = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{factor: str, weight: int, value: any}, ...] — contributing risk factors",
	)
	computed_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	is_current = Column(
		Boolean,
		nullable=False,
		default=True,
		comment="True = most recent score for this employee",
	)
	notes = Column(Text, nullable=True)

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
		return (
			f"<HrFlightRiskScore employee={self.employee_id!r} "
			f"score={self.score} level={self.risk_level!r} current={self.is_current}>"
		)


# ---------------------------------------------------------------------------
# HrAnalyticsReport
# ---------------------------------------------------------------------------

class HrAnalyticsReport(AuditMixin, Model):
	"""Persisted analytics report — richer than a snapshot; includes parameters
	and the full result payload for audit and download.

	report_type: free-form string matching the requesting consumer,
	  e.g. "TURNOVER_DETAIL", "DIVERSITY_SUMMARY", "FLIGHT_RISK_ROSTER".
	entity_id: department/cost-centre UUID; NULL = whole tenant.
	generated_by: ab_user UUID who requested the report (NULL = system/scheduled).
	parameters: JSONB dict of inputs used to produce this report.
	result_data: JSONB dict of the full report output.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hr_anl_report"
	__table_args__ = (
		Index("ix_hr_anl_rpt_tenant_type_generated", "tenant_id", "report_type", "generated_at"),
		Index("ix_hr_anl_rpt_entity", "entity_id"),
		Index("ix_hr_anl_rpt_generated_by", "generated_by"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	report_type = Column(
		String(50),
		nullable=False,
		comment="Report type slug e.g. TURNOVER_DETAIL, DIVERSITY_SUMMARY",
	)
	title = Column(String(300), nullable=False)
	period = Column(
		String(20),
		nullable=False,
		comment="Period key e.g. '2025-Q1'",
	)
	entity_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Department/cost-centre UUID; NULL = whole tenant",
	)
	generated_by = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Soft FK to ab_user who requested; NULL = system/scheduled",
	)
	generated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	parameters = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Input parameters used to produce this report",
	)
	result_data = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Full report output payload",
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
		return (
			f"<HrAnalyticsReport type={self.report_type!r} "
			f"period={self.period!r} tenant={self.tenant_id!r}>"
		)


__all__ = [
	"HrAnalyticsSnapshot",
	"HrFlightRiskScore",
	"HrAnalyticsReport",
]
