"""
pgappforge/plugins/erp/finance/fpa/models.py

SQLAlchemy models for the FP&A plugin.

Design invariants:
  - All PKs:         UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps:  DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - All models:      tenant_id UUID NOT NULL
  - All amounts:     Integer cents (BigInteger) — NEVER float or Numeric for money
  - Table prefix:    fpa_
  - AuditMixin:      applied to all mutable entities
  - JSONB:           used for extensible/formula attributes
  - Indexes:         composite indexes matching common query patterns
  - lazy=:           'select' everywhere (SA 2.x removed 'dynamic')
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
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
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# BudgetCycle  — top-level container for a planning round
# ---------------------------------------------------------------------------

class BudgetCycle(AuditMixin, Model):
	"""A named budget planning cycle (e.g. "FY2026 Annual Budget").

	Status transitions:
	    DRAFT → INPUT_OPEN → UNDER_REVIEW → APPROVED → LOCKED

	Only one APPROVED/LOCKED cycle should exist per fiscal_year per tenant
	for a given cycle_type, but this is enforced at the service layer.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fpa_budget_cycle"
	__table_args__ = (
		Index("ix_fpa_cycle_tenant_year", "tenant_id", "fiscal_year"),
		Index("ix_fpa_cycle_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	fiscal_year = Column(Integer, nullable=False)
	cycle_type = Column(
		String(20),
		nullable=False,
		default="ANNUAL",
		comment="ANNUAL|QUARTERLY|ROLLING_12M",
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|INPUT_OPEN|UNDER_REVIEW|APPROVED|LOCKED",
	)
	input_deadline = Column(Date, nullable=True)
	approval_deadline = Column(Date, nullable=True)
	approved_by = Column(UUID(as_uuid=False), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)

	versions: list[BudgetVersion] = relationship(
		"BudgetVersion",
		back_populates="cycle",
		lazy="select",
		cascade="all, delete-orphan",
	)
	forecast_snapshots: list[ForecastSnapshot] = relationship(
		"ForecastSnapshot",
		back_populates="cycle",
		lazy="select",
		cascade="all, delete-orphan",
	)
	kpi_targets: list[KPITarget] = relationship(
		"KPITarget",
		back_populates="cycle",
		lazy="select",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return f"<BudgetCycle {self.name!r} fy={self.fiscal_year} status={self.status}>"


# ---------------------------------------------------------------------------
# BudgetVersion  — a named snapshot within a cycle
# ---------------------------------------------------------------------------

class BudgetVersion(AuditMixin, Model):
	"""A version of a budget within a cycle.

	ORIGINAL is the first submitted version; REVISED_n are incremental
	re-forecasts; FORECAST is a rolling forecast overlay; WORKING is a
	transient scratchpad.

	Only one version per (cycle_id, version_type) should be is_active=True;
	enforced at service layer.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fpa_budget_version"
	__table_args__ = (
		Index("ix_fpa_version_cycle", "cycle_id", "is_active"),
		Index("ix_fpa_version_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	cycle_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fpa_budget_cycle.id", ondelete="CASCADE"),
		nullable=False,
	)
	version_name = Column(String(50), nullable=False)
	version_type = Column(
		String(20),
		nullable=False,
		default="ORIGINAL",
		comment="ORIGINAL|REVISED_1|REVISED_2|FORECAST|WORKING",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	locked_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	cycle: BudgetCycle = relationship(
		"BudgetCycle",
		back_populates="versions",
		lazy="select",
	)
	lines: list[BudgetLine] = relationship(
		"BudgetLine",
		back_populates="version",
		lazy="select",
		cascade="all, delete-orphan",
	)
	scenario_models: list[ScenarioModel] = relationship(
		"ScenarioModel",
		primaryjoin="ScenarioModel.base_version_id == BudgetVersion.id",
		foreign_keys="[ScenarioModel.base_version_id]",
		back_populates="base_version",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<BudgetVersion {self.version_name!r} type={self.version_type} "
			f"locked={self.locked_at is not None}>"
		)


# ---------------------------------------------------------------------------
# BudgetLine  — per-account, per-period budget amount
# ---------------------------------------------------------------------------

class BudgetLine(AuditMixin, Model):
	"""One budget line: account × cost-centre × period-month × amount.

	amount_cents is always integer cents (BigInteger).  driver_params stores
	the computed inputs (e.g. headcount, rate) that produced the amount when
	driver_type != MANUAL; the formula is re-applied if inputs change.

	status workflow: DRAFT → SUBMITTED → APPROVED
	"""

	__allow_unmapped__ = True
	__tablename__ = "fpa_budget_line"
	__table_args__ = (
		Index(
			"ix_fpa_line_version_account_period",
			"version_id", "gl_account_code", "period_month",
		),
		Index(
			"ix_fpa_budgetline_version_month_account",
			"version_id", "period_month", "gl_account_code",
		),
		Index("ix_fpa_line_cost_center", "version_id", "cost_center_code"),
		Index("ix_fpa_line_tenant", "tenant_id"),
		UniqueConstraint(
			"version_id", "gl_account_code", "cost_center_code", "entity_id", "period_month",
			name="uq_fpa_line_version_acct_cc_entity_month",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	version_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fpa_budget_version.id", ondelete="CASCADE"),
		nullable=False,
	)
	gl_account_code = Column(String(20), nullable=False)
	cost_center_code = Column(String(20), nullable=True)
	entity_id = Column(UUID(as_uuid=False), nullable=True)
	period_month = Column(
		Date,
		nullable=False,
		comment="Always first day of the month; e.g. 2026-01-01",
	)
	amount_cents = Column(BigInteger, nullable=False, default=0)
	driver_type = Column(
		String(20),
		nullable=False,
		default="MANUAL",
		comment="MANUAL|HEADCOUNT|REVENUE_PCT|PRIOR_YEAR|FORMULA",
	)
	driver_params = Column(JSONB, nullable=True)
	dimensions = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment=(
			"Tenant-defined dimension values for this budget line. "
			"Mirrors GLJournalLine.dimensions — enables dimension-aware variance analysis. "
			"e.g. {\"project\": \"PRJ001\", \"grant\": \"GRT001\", \"fund\": \"RECURRENT\"}"
		),
	)
	narrative = Column(Text, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|SUBMITTED|APPROVED",
	)

	version: BudgetVersion = relationship(
		"BudgetVersion",
		back_populates="lines",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<BudgetLine acct={self.gl_account_code!r} "
			f"cc={self.cost_center_code!r} month={self.period_month} "
			f"amt={self.amount_cents}>"
		)


# ---------------------------------------------------------------------------
# BudgetDriver  — reusable driver definitions
# ---------------------------------------------------------------------------

class BudgetDriver(AuditMixin, Model):
	"""A named driver used to compute budget line amounts programmatically.

	driver_code is unique per tenant (UniqueConstraint below).
	formula_expression is a safe Python expression evaluated with a restricted
	namespace: {base_value, params} where params is the BudgetLine.driver_params
	dict.  Example: "base_value * params['headcount'] * params['rate']"
	"""

	__allow_unmapped__ = True
	__tablename__ = "fpa_budget_driver"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "driver_code",
			name="uq_fpa_driver_tenant_code",
		),
		Index("ix_fpa_driver_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	driver_code = Column(String(30), nullable=False)
	name = Column(String(100), nullable=False)
	driver_type = Column(
		String(20),
		nullable=False,
		comment="HEADCOUNT|VOLUME|RATE|PERCENTAGE|FORMULA",
	)
	unit = Column(String(20), nullable=True)
	base_value = Column(Numeric(12, 4), nullable=False, default=0)
	formula_expression = Column(Text, nullable=True)
	is_global = Column(
		Boolean,
		nullable=False,
		default=True,
		comment="True = usable across all cycles for this tenant",
	)

	def __repr__(self) -> str:
		return f"<BudgetDriver {self.driver_code!r} type={self.driver_type}>"


# ---------------------------------------------------------------------------
# ScenarioModel  — what-if scenario over a base version
# ---------------------------------------------------------------------------

class ScenarioModel(AuditMixin, Model):
	"""A what-if scenario applied to a base BudgetVersion.

	adjustment_rules is a dict keyed by gl_account_code prefix or '*':
	    {"revenue": {"pct": 10}, "headcount": {"pct": -5}, "*": {"pct": 0}}

	Keys are matched as prefix of gl_account_code (longest match wins).
	Generates a new WORKING BudgetVersion with adjusted lines.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fpa_scenario_model"
	__table_args__ = (
		Index("ix_fpa_scenario_tenant", "tenant_id"),
		Index("ix_fpa_scenario_base_version", "base_version_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	base_version_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fpa_budget_version.id", ondelete="RESTRICT"),
		nullable=False,
	)
	description = Column(Text, nullable=True)
	scenario_type = Column(
		String(20),
		nullable=False,
		default="BASE",
		comment="OPTIMISTIC|BASE|PESSIMISTIC|STRESS|CUSTOM",
	)
	adjustment_rules = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='e.g. {"4": {"pct": 10}, "6": {"pct": -5}}',
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|GENERATED|APPROVED",
	)
	# FK to the generated version (set after generate_scenario())
	generated_version_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fpa_budget_version.id", ondelete="SET NULL"),
		nullable=True,
	)

	base_version: BudgetVersion = relationship(
		"BudgetVersion",
		foreign_keys=[base_version_id],
		back_populates="scenario_models",
		lazy="select",
	)
	generated_version: BudgetVersion | None = relationship(
		"BudgetVersion",
		foreign_keys=[generated_version_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ScenarioModel {self.name!r} type={self.scenario_type} status={self.status}>"


# ---------------------------------------------------------------------------
# ForecastSnapshot  — point-in-time actuals vs budget vs forecast
# ---------------------------------------------------------------------------

class ForecastSnapshot(Model):
	"""Immutable point-in-time snapshot of actuals vs budget vs forecast.

	Written by FPAService.take_forecast_snapshot().  Never updated — each
	invocation inserts new rows (snapshot_date differentiates them).

	All amounts are integer cents (BigInteger).
	"""

	__allow_unmapped__ = True
	__tablename__ = "fpa_forecast_snapshot"
	__table_args__ = (
		Index(
			"ix_fpa_snapshot_cycle_date",
			"cycle_id", "snapshot_date", "period_month",
		),
		Index("ix_fpa_snapshot_account", "tenant_id", "gl_account_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	cycle_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fpa_budget_cycle.id", ondelete="CASCADE"),
		nullable=False,
	)
	snapshot_date = Column(Date, nullable=False)
	period_month = Column(Date, nullable=False)
	gl_account_code = Column(String(20), nullable=False)
	cost_center_code = Column(String(20), nullable=True)
	actual_cents = Column(BigInteger, nullable=False, default=0)
	budget_cents = Column(BigInteger, nullable=False, default=0)
	forecast_cents = Column(BigInteger, nullable=False, default=0)
	variance_cents = Column(BigInteger, nullable=False, default=0)
	variance_pct = Column(Numeric(8, 4), nullable=False, default=0)

	cycle: BudgetCycle = relationship(
		"BudgetCycle",
		back_populates="forecast_snapshots",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ForecastSnapshot cycle={self.cycle_id!r} "
			f"snap={self.snapshot_date} period={self.period_month} "
			f"acct={self.gl_account_code!r}>"
		)


# ---------------------------------------------------------------------------
# KPITarget  — per-period KPI tracking
# ---------------------------------------------------------------------------

class KPITarget(AuditMixin, Model):
	"""KPI target and actuals for a specific period within a budget cycle.

	direction determines the ON_TRACK threshold direction.
	status is auto-computed by FPAService.update_kpi():
	    ON_TRACK  — within 5% of target
	    AT_RISK   — 5–15% variance from target
	    OFF_TRACK — >15% variance
	"""

	__allow_unmapped__ = True
	__tablename__ = "fpa_kpi_target"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "kpi_code", "cycle_id", "period_month",
			name="uq_fpa_kpi_tenant_code_cycle_month",
		),
		Index("ix_fpa_kpi_tenant_cycle", "tenant_id", "cycle_id"),
		Index("ix_fpa_kpi_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	kpi_code = Column(String(30), nullable=False)
	kpi_name = Column(String(100), nullable=False)
	cycle_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fpa_budget_cycle.id", ondelete="CASCADE"),
		nullable=False,
	)
	period_month = Column(Date, nullable=False)
	target_value = Column(Numeric(16, 4), nullable=False)
	actual_value = Column(Numeric(16, 4), nullable=True)
	unit = Column(String(20), nullable=True)
	direction = Column(
		String(25),
		nullable=False,
		default="HIGHER_IS_BETTER",
		comment="HIGHER_IS_BETTER|LOWER_IS_BETTER",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ON_TRACK",
		comment="ON_TRACK|AT_RISK|OFF_TRACK",
	)

	cycle: BudgetCycle = relationship(
		"BudgetCycle",
		back_populates="kpi_targets",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<KPITarget {self.kpi_code!r} period={self.period_month} "
			f"target={self.target_value} status={self.status}>"
		)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
	"BudgetCycle",
	"BudgetVersion",
	"BudgetLine",
	"BudgetDriver",
	"ScenarioModel",
	"ForecastSnapshot",
	"KPITarget",
]
