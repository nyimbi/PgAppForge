"""
pgappforge/plugins/erp/hcm/variable_pay/models.py

SQLAlchemy 2.x models for the Variable Pay plugin.

Table prefix: vp_

Models:
  IncentivePlan       (vp_plan)        — plan definition with tiers + accelerator
  EmployeeQuota       (vp_quota)       — per-employee per-period quota assignment
  CommissionCalculation (vp_calculation) — tier-by-tier commission breakdown
  CommissionPayout    (vp_payout)      — approval + payment lifecycle

All monetary values: BigInteger cents.
All PKs: UUID string, default=_uuid4, server_default=gen_random_uuid().
All models: tenant_id (UUID, non-null) + AuditMixin.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Numeric,
	Text,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


__all__ = [
	"IncentivePlan",
	"EmployeeQuota",
	"CommissionCalculation",
	"CommissionPayout",
]


# ---------------------------------------------------------------------------
# IncentivePlan
# ---------------------------------------------------------------------------

class IncentivePlan(AuditMixin, Model):
	"""Incentive/commission plan definition.

	tiers JSONB stores an ordered list of attainment brackets, e.g.:
	  [
	    {"min_pct": 0,   "max_pct": 80,  "rate_pct": 5,  "description": "Below threshold"},
	    {"min_pct": 80,  "max_pct": 100, "rate_pct": 8,  "description": "On-target"},
	    {"min_pct": 100, "max_pct": 999, "rate_pct": 12, "description": "Overachievement"},
	  ]
	"""
	__tablename__ = "vp_plan"
	__table_args__ = (
		Index("ix_vp_plan_tenant_type_active", "tenant_id", "plan_type", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(VARCHAR(200), nullable=False)
	description = Column(Text, nullable=True)
	plan_type = Column(
		VARCHAR(30),
		nullable=False,
		comment="SALES_COMMISSION/BONUS/PROFIT_SHARE/RETENTION/SPOT_AWARD",
	)
	currency_code = Column(VARCHAR(3), nullable=False, default="USD")
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)

	# Tier structure — ordered list of attainment brackets
	tiers = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default=sa.text("'[]'::jsonb"),
		comment="[{min_pct, max_pct, rate_pct, description}]",
	)

	# Accelerator — kicks in when attainment_pct >= accelerator_threshold_pct
	accelerator_threshold_pct = Column(
		Numeric(6, 2),
		nullable=True,
		comment="Attainment % above which accelerator multiplier applies",
	)
	accelerator_multiplier = Column(
		Numeric(6, 2),
		nullable=False,
		default=1.0,
		server_default=sa.text("1.0"),
	)

	entity_id = Column(VARCHAR(50), nullable=True)

	quotas = relationship("EmployeeQuota", back_populates="plan", lazy="select")


# ---------------------------------------------------------------------------
# EmployeeQuota
# ---------------------------------------------------------------------------

class EmployeeQuota(AuditMixin, Model):
	"""Per-employee quota assignment for a plan period.

	period examples: "2025-Q1", "2025-01", "2025-H1"
	attainment_pct is a persisted computed column updated on every
	record_attainment() call (attained_cents / quota_cents * 100).
	"""
	__tablename__ = "vp_quota"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "employee_id", "plan_id", "period",
			name="uq_vp_quota_tenant_emp_plan_period",
		),
		Index("ix_vp_quota_employee_period_status", "employee_id", "period", "status"),
		Index("ix_vp_quota_plan_period", "plan_id", "period"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("vp_plan.id", ondelete="CASCADE"),
		nullable=False,
	)
	period = Column(VARCHAR(20), nullable=False)
	quota_cents = Column(BigInteger, nullable=False)
	attained_cents = Column(BigInteger, nullable=False, default=0, server_default=sa.text("0"))
	# Stored attainment pct — updated by service on each record_attainment() call
	attainment_pct = Column(
		Numeric(8, 4),
		nullable=False,
		default=0.0,
		server_default=sa.text("0.0"),
	)
	status = Column(
		VARCHAR(20),
		nullable=False,
		default="ACTIVE",
		server_default=sa.text("'ACTIVE'"),
		comment="ACTIVE/CLOSED/CANCELLED",
	)

	plan = relationship("IncentivePlan", back_populates="quotas", lazy="select")
	calculations = relationship("CommissionCalculation", back_populates="quota", lazy="select")


# ---------------------------------------------------------------------------
# CommissionCalculation
# ---------------------------------------------------------------------------

class CommissionCalculation(AuditMixin, Model):
	"""Tier-by-tier commission computation result for one quota.

	calculation_breakdown JSONB example:
	  {
	    "tiers": [
	      {"tier_min_pct": 0,   "tier_max_pct": 80,  "rate_pct": 5,
	       "quota_portion_cents": 400000, "commission_cents": 20000},
	      {"tier_min_pct": 80,  "tier_max_pct": 100, "rate_pct": 8,
	       "quota_portion_cents": 100000, "commission_cents": 8000},
	    ],
	    "accelerator": {"applied": true, "multiplier": 1.5,
	                    "bonus_cents": 12000}
	  }
	"""
	__tablename__ = "vp_calculation"
	__table_args__ = (
		Index("ix_vp_calculation_employee_period", "employee_id", "period"),
		Index("ix_vp_calculation_quota", "quota_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	quota_id = Column(
		UUID(as_uuid=False),
		ForeignKey("vp_quota.id", ondelete="CASCADE"),
		nullable=False,
	)
	employee_id = Column(VARCHAR(50), nullable=False)
	period = Column(VARCHAR(20), nullable=False)

	base_commission_cents = Column(BigInteger, nullable=False)
	accelerator_bonus_cents = Column(BigInteger, nullable=False, default=0, server_default=sa.text("0"))
	total_commission_cents = Column(BigInteger, nullable=False)

	calculation_breakdown = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default=sa.text("'{}'::jsonb"),
	)
	calculated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(__import__("datetime").timezone.utc),
		server_default=sa.text("now()"),
	)

	quota = relationship("EmployeeQuota", back_populates="calculations", lazy="select")
	payout = relationship("CommissionPayout", back_populates="calculation", uselist=False, lazy="select")


# ---------------------------------------------------------------------------
# CommissionPayout
# ---------------------------------------------------------------------------

class CommissionPayout(AuditMixin, Model):
	"""Approval and payment lifecycle for a calculated commission."""

	__tablename__ = "vp_payout"
	__table_args__ = (
		Index("ix_vp_payout_employee_status", "employee_id", "status"),
		Index("ix_vp_payout_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	calculation_id = Column(
		UUID(as_uuid=False),
		ForeignKey("vp_calculation.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
	)
	employee_id = Column(VARCHAR(50), nullable=False)
	period = Column(VARCHAR(20), nullable=False)
	amount_cents = Column(BigInteger, nullable=False)

	status = Column(
		VARCHAR(20),
		nullable=False,
		default="PENDING",
		server_default=sa.text("'PENDING'"),
		comment="PENDING/APPROVED/PAID/CANCELLED",
	)

	approved_by = Column(VARCHAR(50), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	payrun_id = Column(VARCHAR(50), nullable=True)
	paid_at = Column(DateTime(timezone=True), nullable=True)

	calculation = relationship("CommissionCalculation", back_populates="payout", lazy="select")
