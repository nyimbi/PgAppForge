"""
pgappforge/plugins/erp/hcm/equity_compensation/models.py

SQLAlchemy models for the HCM Equity Compensation plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: BigInteger cents (NEVER Numeric/float for money)
  - ALL models: tenant_id NOT NULL + AuditMixin
  - Decimal arithmetic in services; models store integer cents only
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields
  - Composite indexes for hot query paths

Table prefix: eq_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# EquityPlan
# ---------------------------------------------------------------------------

class EquityPlan(AuditMixin, Model):
	"""Equity plan master — defines terms for a class of grants.

	plan_type: STOCK_OPTION | RSU | ESPP | SAR
	vesting_schedule_type: CLIFF | GRADED | IMMEDIATE
	exercise_price_cents: 0 for RSUs; grant-date strike for options.
	expiry_years: options expire this many years after grant date.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eq_plan"
	__table_args__ = (
		Index("ix_eq_plan_tenant_type_active", "tenant_id", "plan_type", "is_active"),
		Index("ix_eq_plan_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="Legal entity scope; NULL = global plan")

	name = Column(String(200), nullable=False, comment="Human-readable plan name")
	plan_type = Column(
		String(30),
		nullable=False,
		comment="STOCK_OPTION | RSU | ESPP | SAR",
	)
	total_shares_authorized = Column(Integer, nullable=False, comment="Maximum shares the plan may issue")
	total_shares_issued = Column(Integer, nullable=False, default=0, comment="Running total of shares granted")

	vesting_schedule_type = Column(
		String(20),
		nullable=False,
		default="GRADED",
		comment="CLIFF | GRADED | IMMEDIATE",
	)
	vesting_period_months = Column(
		Integer,
		nullable=False,
		default=48,
		comment="Total vesting period in months (e.g. 48 = 4 years)",
	)
	cliff_months = Column(
		Integer,
		nullable=False,
		default=12,
		comment="Months before first vesting event (e.g. 12 = 1-year cliff)",
	)

	exercise_price_cents = Column(
		BigInteger,
		nullable=True,
		comment="Per-share exercise price in cents; 0 for RSUs",
	)
	plan_currency = Column(String(3), nullable=False, default="USD")
	expiry_years = Column(
		Integer,
		nullable=False,
		default=10,
		comment="Options expire this many years after grant date",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

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

	# Relationships
	grants: list[EquityGrant] = relationship(
		"EquityGrant", back_populates="plan", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<EquityPlan {self.name!r} type={self.plan_type!r} active={self.is_active}>"


# ---------------------------------------------------------------------------
# EquityGrant
# ---------------------------------------------------------------------------

class EquityGrant(AuditMixin, Model):
	"""Individual equity grant to an employee.

	Status machine:
	  ACTIVE → EXERCISED (when all vested+unvested shares exercised)
	  ACTIVE → FORFEITED (employee leaves before fully vested)
	  ACTIVE → EXPIRED   (options not exercised before expiry_date)

	unvested_shares tracks the remaining unvested balance; decremented by
	VestingEvent processing.  vested_shares is incremented in parallel.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eq_grant"
	__table_args__ = (
		Index("ix_eq_grant_tenant_employee_status", "tenant_id", "employee_id", "status"),
		Index("ix_eq_grant_plan_employee", "plan_id", "employee_id"),
		Index("ix_eq_grant_tenant", "tenant_id"),
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
		comment="Soft FK to HCM employee master",
	)
	plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eq_plan.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	grant_date = Column(Date, nullable=False)
	shares_granted = Column(Integer, nullable=False)
	vested_shares = Column(Integer, nullable=False, default=0)
	unvested_shares = Column(Integer, nullable=False, comment="Decremented as vesting events are processed")

	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | EXERCISED | FORFEITED | EXPIRED",
	)
	grant_fmv_cents = Column(
		BigInteger,
		nullable=True,
		comment="Fair market value per share on grant date (cents) — for tax purposes",
	)
	expiry_date = Column(
		Date,
		nullable=True,
		comment="Auto-computed: grant_date + plan.expiry_years; options void after this",
	)
	approved_by = Column(String(50), nullable=True, comment="User/manager who approved the grant")
	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

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

	# Relationships
	plan: EquityPlan = relationship("EquityPlan", back_populates="grants", lazy="select")
	vesting_events: list[VestingEvent] = relationship(
		"VestingEvent", back_populates="grant", cascade="all, delete-orphan", lazy="select"
	)
	exercises: list[EquityExercise] = relationship(
		"EquityExercise", back_populates="grant", cascade="all, delete-orphan", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<EquityGrant employee={self.employee_id!r} "
			f"shares={self.shares_granted} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# VestingEvent
# ---------------------------------------------------------------------------

class VestingEvent(AuditMixin, Model):
	"""Scheduled vesting milestone for a grant.

	Generated by EquityService.create_grant() based on the plan's vesting
	schedule type.  Processed by process_vesting() up to as_of_date.

	is_cliff: True for the cliff vesting event (first big tranche).
	is_processed: False until process_vesting() runs and marks it done.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eq_vesting_event"
	__table_args__ = (
		Index("ix_eq_vesting_grant_date_processed", "grant_id", "vest_date", "is_processed"),
		Index("ix_eq_vesting_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	grant_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eq_grant.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	vest_date = Column(Date, nullable=False)
	shares_vested = Column(Integer, nullable=False)
	is_cliff = Column(Boolean, nullable=False, default=False)
	is_processed = Column(Boolean, nullable=False, default=False, index=True)
	processed_at = Column(DateTime(timezone=True), nullable=True)

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

	# Relationships
	grant: EquityGrant = relationship("EquityGrant", back_populates="vesting_events", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<VestingEvent grant={self.grant_id!r} date={self.vest_date} "
			f"shares={self.shares_vested} processed={self.is_processed}>"
		)


# ---------------------------------------------------------------------------
# EquityExercise
# ---------------------------------------------------------------------------

class EquityExercise(AuditMixin, Model):
	"""Record of an option exercise transaction.

	gain_cents = (fmv_cents - exercise_price_cents) × shares_exercised
	withholding_tax_cents = 30% of gain (configurable via plan.metadata_)
	net_proceeds_cents = gain_cents - withholding_tax_cents

	employee_id is denormalised here for query efficiency (avoid join to grant).
	All monetary fields are BigInteger cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eq_exercise"
	__table_args__ = (
		Index("ix_eq_exercise_grant", "grant_id"),
		Index("ix_eq_exercise_employee", "employee_id"),
		Index("ix_eq_exercise_tenant", "tenant_id"),
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
		comment="Denormalised from grant for query efficiency",
	)
	grant_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eq_grant.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	exercise_date = Column(Date, nullable=False)
	shares_exercised = Column(Integer, nullable=False)

	# Per-share prices — BigInteger cents
	exercise_price_cents = Column(
		BigInteger,
		nullable=False,
		comment="Per-share exercise price in cents (from plan or override)",
	)
	fmv_cents = Column(
		BigInteger,
		nullable=False,
		comment="Fair market value per share on exercise date (cents)",
	)

	# Computed amounts — BigInteger cents
	gain_cents = Column(
		BigInteger,
		nullable=False,
		comment="(fmv - exercise_price) × shares_exercised",
	)
	withholding_tax_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Tax withheld at source (default 30% of gain)",
	)
	net_proceeds_cents = Column(
		BigInteger,
		nullable=False,
		comment="gain_cents - withholding_tax_cents",
	)

	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

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

	# Relationships
	grant: EquityGrant = relationship("EquityGrant", back_populates="exercises", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<EquityExercise employee={self.employee_id!r} "
			f"shares={self.shares_exercised} gain={self.gain_cents}¢>"
		)


__all__ = [
	"EquityPlan",
	"EquityGrant",
	"VestingEvent",
	"EquityExercise",
]
