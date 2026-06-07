"""
pgappforge/plugins/erp/hcm/workforce_planning/models.py

SQLAlchemy 2.x models for the Workforce Planning plugin.

Table prefix: wfp_

Models:
  WorkforcePlan     (wfp_plan)      — annual headcount plan per entity
  PlannedPosition   (wfp_position)  — individual position lines within a plan
  WorkforceScenario (wfp_scenario)  — what-if scenarios (BASE/OPTIMISTIC/etc.)

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
	Integer,
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
	"WorkforcePlan",
	"PlannedPosition",
	"WorkforceScenario",
]


# ---------------------------------------------------------------------------
# WorkforcePlan
# ---------------------------------------------------------------------------

class WorkforcePlan(AuditMixin, Model):
	"""Annual headcount and budget plan for an organisational entity.

	gl_cost_center links to the finance profit centre for GL integration.
	metadata_ holds free-form plan context (notes, links, HR system refs).
	"""
	__tablename__ = "wfp_plan"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "entity_id", "plan_year",
			name="uq_wfp_plan_tenant_entity_year",
		),
		Index("ix_wfp_plan_tenant_entity_status", "tenant_id", "entity_id", "status"),
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
	entity_id = Column(VARCHAR(50), nullable=False)
	plan_year = Column(Integer, nullable=False)

	status = Column(
		VARCHAR(20),
		nullable=False,
		default="DRAFT",
		server_default=sa.text("'DRAFT'"),
		comment="DRAFT/SUBMITTED/APPROVED/CLOSED",
	)

	# Running totals updated by add_position()
	total_planned_fte = Column(
		Numeric(10, 2),
		nullable=False,
		default=0,
		server_default=sa.text("0"),
	)
	total_budget_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default=sa.text("0"),
	)

	approved_by = Column(VARCHAR(50), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)

	# Link to finance GL cost centre (profit centre code)
	gl_cost_center = Column(VARCHAR(50), nullable=True)

	metadata_ = Column(
		"metadata_",
		JSONB,
		nullable=False,
		default=dict,
		server_default=sa.text("'{}'::jsonb"),
	)

	positions = relationship("PlannedPosition", back_populates="plan", lazy="select")
	scenarios = relationship("WorkforceScenario", back_populates="plan", lazy="select")


# ---------------------------------------------------------------------------
# PlannedPosition
# ---------------------------------------------------------------------------

class PlannedPosition(AuditMixin, Model):
	"""A single planned headcount line within a WorkforcePlan.

	annual_base_cost_cents = cost for 1.0 FTE per year.
	total_annual_cost_cents = planned_fte × annual_base_cost_cents (computed by service).

	headcount_change_type values:
	  NEW       — net new role
	  BACKFILL  — replacing a departed employee
	  EXISTING  — continuing existing headcount
	  REDUCTION — planned headcount reduction (negative contribution)
	"""
	__tablename__ = "wfp_position"
	__table_args__ = (
		Index("ix_wfp_position_plan_change_type", "plan_id", "headcount_change_type"),
		Index("ix_wfp_position_tenant_approval", "tenant_id", "approval_status"),
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

	plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("wfp_plan.id", ondelete="CASCADE"),
		nullable=False,
	)
	position_code = Column(VARCHAR(100), nullable=False)
	position_title = Column(VARCHAR(200), nullable=False)
	department = Column(VARCHAR(200), nullable=True)
	grade_level = Column(VARCHAR(50), nullable=True)

	planned_fte = Column(
		Numeric(6, 2),
		nullable=False,
		default=1.0,
		server_default=sa.text("1.0"),
	)
	# Cost for 1.0 FTE/year
	annual_base_cost_cents = Column(BigInteger, nullable=False)
	# planned_fte × annual_base_cost_cents — maintained by service
	total_annual_cost_cents = Column(BigInteger, nullable=False)

	planned_start_date = Column(Date, nullable=True)

	headcount_change_type = Column(
		VARCHAR(20),
		nullable=False,
		default="EXISTING",
		server_default=sa.text("'EXISTING'"),
		comment="NEW/BACKFILL/EXISTING/REDUCTION",
	)
	approval_status = Column(
		VARCHAR(20),
		nullable=False,
		default="PENDING",
		server_default=sa.text("'PENDING'"),
		comment="PENDING/APPROVED/REJECTED",
	)
	notes = Column(Text, nullable=True)

	plan = relationship("WorkforcePlan", back_populates="positions", lazy="select")


# ---------------------------------------------------------------------------
# WorkforceScenario
# ---------------------------------------------------------------------------

class WorkforceScenario(AuditMixin, Model):
	"""What-if scenario derived from a WorkforcePlan.

	scenario_data JSONB stores an adjusted snapshot of the plan's positions,
	e.g. each position with adjusted_fte and adjusted_cost_cents fields.

	fte_adjustment_pct / cost_adjustment_pct are the global multipliers applied
	when creating the scenario (e.g. +10.0 = +10%, -15.0 = -15%).
	"""
	__tablename__ = "wfp_scenario"
	__table_args__ = (
		Index("ix_wfp_scenario_plan_type", "plan_id", "scenario_type"),
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

	plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("wfp_plan.id", ondelete="CASCADE"),
		nullable=False,
	)
	scenario_type = Column(
		VARCHAR(30),
		nullable=False,
		comment="BASE/OPTIMISTIC/PESSIMISTIC/GROWTH_10PCT/GROWTH_25PCT/CUSTOM",
	)
	name = Column(VARCHAR(200), nullable=False)

	fte_adjustment_pct = Column(
		Numeric(6, 2),
		nullable=False,
		default=0,
		server_default=sa.text("0"),
		comment="Global FTE % adjustment, e.g. +10 = grow headcount 10%",
	)
	cost_adjustment_pct = Column(
		Numeric(6, 2),
		nullable=False,
		default=0,
		server_default=sa.text("0"),
		comment="Global cost % adjustment applied on top of FTE adjustment",
	)

	# Adjusted positions snapshot
	scenario_data = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default=sa.text("'{}'::jsonb"),
	)

	plan = relationship("WorkforcePlan", back_populates="scenarios", lazy="select")
