"""
pgappforge/plugins/erp/hcm/org/models.py

SQLAlchemy models for the HCM Org Management plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - lazy='select' throughout (SA 2.x removed lazy='dynamic')
  - JSONB for semi-structured fields (address, metadata)
  - Proper composite indexes for tenant + status hot paths

Table prefix: hcm_org_
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
# HcmLegalEntity
# ---------------------------------------------------------------------------

class HcmLegalEntity(AuditMixin, Model):
	"""Employer legal entity that runs payroll.

	One tenant can operate multiple legal entities in different countries.
	payroll_currency and fiscal_year_start_month drive payrun scheduling.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_legal_entity"
	__table_args__ = (
		Index("ix_hcm_le_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "entity_code", name="uq_hcm_le_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_code = Column(String(20), nullable=False, comment="Short alphanumeric code; unique per tenant")
	entity_name = Column(String(255), nullable=False, comment="Full registered legal name")
	tax_id = Column(String(50), nullable=True, comment="Employer tax registration number (EIN, ABN, etc.)")
	payroll_currency = Column(String(3), nullable=False, default="USD", comment="ISO 4217 default payroll currency")
	country_code = Column(String(2), nullable=False, comment="ISO 3166-1 alpha-2 country of incorporation")
	fiscal_year_start_month = Column(Integer, nullable=False, default=1, comment="Month 1-12 when fiscal year begins")
	address = Column(JSONB, nullable=False, default=dict, comment="{line1,line2,city,state,postal_code,country}")
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

	# Relationships
	org_units: list[OrgUnit] = relationship("OrgUnit", back_populates="legal_entity", lazy="select")
	positions: list[Position] = relationship("Position", back_populates="legal_entity", lazy="select")
	leave_policies: list[Any] = relationship(
		"LeavePolicy",
		primaryjoin="HcmLegalEntity.id == foreign(LeavePolicy.entity_id)",
		lazy="select",
		viewonly=True,
	)

	def __repr__(self) -> str:
		return f"<HcmLegalEntity {self.entity_code!r} {self.entity_name!r}>"


# ---------------------------------------------------------------------------
# OrgUnit
# ---------------------------------------------------------------------------

class OrgUnit(AuditMixin, Model):
	"""Org chart node.

	Self-referencing parent_id builds the hierarchy.
	manager_id is a soft FK to hcm_org_position.id managed by the application.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_unit"
	__table_args__ = (
		Index("ix_hcm_ou_tenant", "tenant_id"),
		Index("ix_hcm_ou_entity", "entity_id"),
		Index("ix_hcm_ou_parent", "parent_id"),
		UniqueConstraint("tenant_id", "org_code", name="uq_hcm_ou_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_legal_entity.id"), nullable=False, index=True)
	org_code = Column(String(20), nullable=False, comment="Unique short code per tenant")
	org_name = Column(String(255), nullable=False)
	org_type = Column(
		String(30),
		nullable=False,
		comment="DIVISION | DEPARTMENT | TEAM | UNIT",
	)
	parent_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_unit.id"), nullable=True, index=True)
	cost_center_code = Column(String(20), nullable=True, comment="GL cost centre code")
	# manager_id: soft FK to hcm_org_position.id — no DB constraint (avoids circular FK)
	manager_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to hcm_org_position.id (soft)")
	headcount_budget = Column(Integer, nullable=True, comment="Approved headcount for this unit")
	# [HIGH] Org unit status lifecycle
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="PROPOSED | ACTIVE | FROZEN | ABOLISHED",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	legal_entity: HcmLegalEntity = relationship("HcmLegalEntity", back_populates="org_units", lazy="select")
	parent: OrgUnit | None = relationship("OrgUnit", remote_side="OrgUnit.id", lazy="select", foreign_keys="[OrgUnit.parent_id]")
	children: list[OrgUnit] = relationship("OrgUnit", back_populates="parent", lazy="select", foreign_keys="[OrgUnit.parent_id]", overlaps="parent")
	positions: list[Position] = relationship("Position", back_populates="org_unit", lazy="select")
	history: list[OrgUnitHistory] = relationship("OrgUnitHistory", back_populates="org_unit", lazy="select")

	def __repr__(self) -> str:
		return f"<OrgUnit {self.org_code!r} type={self.org_type!r}>"


# ---------------------------------------------------------------------------
# OrgUnitHistory  [CRITICAL — effective-dated org unit changes]
# ---------------------------------------------------------------------------

class OrgUnitHistory(Model):
	"""Immutable audit trail for destructive OrgUnit mutations.

	Written BEFORE the mutation occurs so the record captures old_value_json
	and new_value_json.  Never update or delete rows — this is an append-only
	ledger used by org_unit_as_of() for point-in-time reconstruction.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_unit_history"
	__table_args__ = (
		Index("ix_hcm_ouh_org_unit", "org_unit_id"),
		Index("ix_hcm_ouh_effective_date", "effective_date"),
		Index("ix_hcm_ouh_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	org_unit_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_unit.id"), nullable=False, index=True)
	# RENAME | REPARENT | TYPE_CHANGE | STATUS_CHANGE | MANAGER_CHANGE
	change_type = Column(String(30), nullable=False)
	effective_date = Column(Date, nullable=False, comment="Date the change became effective")
	old_value_json = Column(JSONB, nullable=False, default=dict, comment="Snapshot of affected fields before change")
	new_value_json = Column(JSONB, nullable=False, default=dict, comment="Snapshot of affected fields after change")
	changed_by = Column(String(255), nullable=True, comment="User or system that triggered the change")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	org_unit: OrgUnit = relationship("OrgUnit", back_populates="history", lazy="select")

	def __repr__(self) -> str:
		return f"<OrgUnitHistory unit={self.org_unit_id!r} type={self.change_type!r} eff={self.effective_date}>"


# ---------------------------------------------------------------------------
# JobCatalog
# ---------------------------------------------------------------------------

class JobCatalog(AuditMixin, Model):
	"""Centralised job architecture library.

	pay_grade links to CompensationGrade for approved salary bands.
	flsa_status drives overtime eligibility in US-jurisdiction payrolls.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_job_catalog"
	__table_args__ = (
		Index("ix_hcm_jc_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "job_code", name="uq_hcm_jc_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	job_code = Column(String(30), nullable=False, comment="Unique job architecture code per tenant")
	job_title = Column(String(200), nullable=False, comment="Official job title for contracts and org charts")
	job_family = Column(String(100), nullable=True, comment="Broad functional grouping e.g. Engineering, Finance")
	job_function = Column(String(100), nullable=True, comment="Sub-grouping within job family")
	grade_level = Column(String(20), nullable=True, comment="Career level identifier e.g. L3, IC4, Manager")
	flsa_status = Column(
		String(20),
		nullable=True,
		comment="EXEMPT | NON_EXEMPT — US FLSA overtime classification",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	positions: list[Position] = relationship("Position", back_populates="job_catalog", lazy="select")

	def __repr__(self) -> str:
		return f"<JobCatalog {self.job_code!r} {self.job_title!r}>"


# ---------------------------------------------------------------------------
# CompensationGrade
# ---------------------------------------------------------------------------

class CompensationGrade(AuditMixin, Model):
	"""Salary band / pay grade definition.

	IMMUTABLE LEDGER: INSERT a new row with updated effective_from rather than
	updating existing rows. The active grade is the row with the highest
	effective_from <= today.

	All amounts are integer cents — NEVER float.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_compensation_grade"
	__table_args__ = (
		Index("ix_hcm_cg_tenant", "tenant_id"),
		Index("ix_hcm_cg_grade_code", "grade_code"),
		Index("ix_hcm_cg_effective_from", "effective_from"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	grade_code = Column(String(20), nullable=False, comment="Pay grade code e.g. G5, IC3, M2")
	grade_label = Column(String(100), nullable=False, comment="Human-readable label e.g. Senior Engineer")
	min_cents = Column(BigInteger, nullable=False, comment="Minimum annual salary in cents")
	mid_cents = Column(BigInteger, nullable=False, comment="Midpoint / target salary in cents")
	max_cents = Column(BigInteger, nullable=False, comment="Maximum annual salary in cents")
	currency_code = Column(String(3), nullable=False, default="KES", comment="ISO 4217 currency; default KES for East Africa")
	effective_from = Column(Date, nullable=False, comment="Date this band became effective")
	# [HIGH] Gazette reference for Kenya public service
	gazette_reference = Column(String(100), nullable=True, comment="Kenya Gazette notice ref e.g. Vol. CXXIII No. 45")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	exchange_rates: list[CompensationGradeExchange] = relationship(
		"CompensationGradeExchange", back_populates="grade", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<CompensationGrade {self.grade_code!r} min={self.min_cents}¢ max={self.max_cents}¢ {self.currency_code}>"


# ---------------------------------------------------------------------------
# CompensationGradeExchange  [HIGH — multi-currency EAC support]
# ---------------------------------------------------------------------------

class CompensationGradeExchange(Model):
	"""Spot-rate snapshot for converting a CompensationGrade to another currency.

	Used by grade_in_currency() service method to support EAC multi-currency
	operations (KES/UGX/TZS/RWF/ETB).  Append-only; the most-recent row per
	(grade_id, target_currency) is authoritative.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_compensation_grade_exchange"
	__table_args__ = (
		Index("ix_hcm_cgx_grade", "grade_id"),
		Index("ix_hcm_cgx_tenant", "tenant_id"),
		Index("ix_hcm_cgx_target_currency", "target_currency"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	grade_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_compensation_grade.id"), nullable=False, index=True)
	target_currency = Column(String(3), nullable=False, comment="ISO 4217 target currency code")
	# Stored as integer micro-units (1 KES = exchange_rate_micro/1_000_000 TARGET)
	# Using BigInteger micro-rate avoids float precision; divide by 1_000_000 to get rate.
	exchange_rate_micro = Column(BigInteger, nullable=False, comment="exchange rate * 1_000_000 (integer micro-rate)")
	rate_date = Column(Date, nullable=False, comment="Date this rate was sourced (CBK/BNR API)")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	grade: CompensationGrade = relationship("CompensationGrade", back_populates="exchange_rates", lazy="select")

	def __repr__(self) -> str:
		return f"<CompensationGradeExchange grade={self.grade_id!r} {self.target_currency} rate_date={self.rate_date}>"


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class Position(AuditMixin, Model):
	"""Budgeted position in the org chart.

	A position is a slot that may be filled by one employee.
	graded_salary_min/max_cents are the approved range for this specific position,
	which may be narrower than the CompensationGrade band.

	is_filled is maintained by the Personnel plugin via EmployeeAssignedEvent.
	grade_code links to CompensationGrade for salary band validation.
	last_vacated_at is set by vacate_position() for open position aging reports.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_position"
	__table_args__ = (
		Index("ix_hcm_pos_tenant", "tenant_id"),
		Index("ix_hcm_pos_entity", "entity_id"),
		Index("ix_hcm_pos_org_unit", "org_unit_id"),
		UniqueConstraint("tenant_id", "position_code", name="uq_hcm_pos_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	position_code = Column(String(30), nullable=False, comment="Unique position code per tenant")
	entity_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_legal_entity.id"), nullable=False, index=True)
	org_unit_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_unit.id"), nullable=False, index=True)
	job_code = Column(UUID(as_uuid=False), ForeignKey("hcm_org_job_catalog.id"), nullable=True, index=True, comment="FK to job catalog entry")
	# [HIGH] grade_code links to CompensationGrade for salary band enforcement
	grade_code = Column(String(20), nullable=True, comment="CompensationGrade.grade_code for salary band enforcement")
	position_title = Column(String(200), nullable=False)
	employment_type = Column(
		String(20),
		nullable=False,
		default="FULL_TIME",
		comment="FULL_TIME | PART_TIME | CONTRACT | CASUAL",
	)
	is_filled = Column(Boolean, nullable=False, default=False, comment="True when an active employee occupies this position")
	graded_salary_min_cents = Column(BigInteger, nullable=True, comment="Position-specific salary floor in cents")
	graded_salary_max_cents = Column(BigInteger, nullable=True, comment="Position-specific salary ceiling in cents")
	is_active = Column(Boolean, nullable=False, default=True)
	# For open position aging analytics
	last_vacated_at = Column(DateTime(timezone=True), nullable=True, comment="Timestamp of last vacate_position() call")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	legal_entity: HcmLegalEntity = relationship("HcmLegalEntity", back_populates="positions", lazy="select")
	org_unit: OrgUnit = relationship("OrgUnit", back_populates="positions", lazy="select")
	job_catalog: JobCatalog | None = relationship("JobCatalog", back_populates="positions", lazy="select")
	reporting_lines_from: list[ReportingLine] = relationship(
		"ReportingLine",
		foreign_keys="[ReportingLine.from_position_id]",
		back_populates="from_position",
		lazy="select",
	)
	reporting_lines_to: list[ReportingLine] = relationship(
		"ReportingLine",
		foreign_keys="[ReportingLine.to_position_id]",
		back_populates="to_position",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Position {self.position_code!r} filled={self.is_filled}>"


# ---------------------------------------------------------------------------
# ReportingLine  [CRITICAL — matrix / dotted-line reporting]
# ---------------------------------------------------------------------------

class ReportingLine(Model):
	"""Association between two positions: from_position reports to to_position.

	line_type:
	  SOLID  — primary hierarchical reporting (exactly one active solid line per position)
	  DOTTED — matrix/functional reporting (many allowed)

	The database enforces the single-solid-line constraint via a partial unique
	index created in migrations:
	  CREATE UNIQUE INDEX uq_hcm_rl_solid
	    ON hcm_org_reporting_line (tenant_id, from_position_id)
	    WHERE line_type = 'SOLID' AND effective_to IS NULL;
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_reporting_line"
	__table_args__ = (
		Index("ix_hcm_rl_tenant", "tenant_id"),
		Index("ix_hcm_rl_from", "from_position_id"),
		Index("ix_hcm_rl_to", "to_position_id"),
		Index("ix_hcm_rl_effective", "effective_from", "effective_to"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	from_position_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_position.id"), nullable=False, index=True)
	to_position_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_position.id"), nullable=False, index=True)
	line_type = Column(String(10), nullable=False, default="SOLID", comment="SOLID | DOTTED")
	effective_from = Column(Date, nullable=False, comment="Date this reporting line became active")
	effective_to = Column(Date, nullable=True, comment="Date this reporting line ended; NULL = still active")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	from_position: Position = relationship(
		"Position",
		foreign_keys=[from_position_id],
		back_populates="reporting_lines_from",
		lazy="select",
	)
	to_position: Position = relationship(
		"Position",
		foreign_keys=[to_position_id],
		back_populates="reporting_lines_to",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ReportingLine {self.from_position_id!r} -({self.line_type})-> {self.to_position_id!r}>"


# ---------------------------------------------------------------------------
# OrgRestructureRequest  [HIGH — org restructuring workflow]
# ---------------------------------------------------------------------------

class OrgRestructureRequest(AuditMixin, Model):
	"""Workflow record for a proposed structural change to an OrgUnit.

	Lifecycle: DRAFT → APPROVED / REJECTED
	           APPROVED → APPLIED (by execute_restructure when effective_date <= today)

	change_payload_json captures the full before/after snapshot enabling rollback
	and audit reconstruction without the OrgUnitHistory join.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_restructure_request"
	__table_args__ = (
		Index("ix_hcm_rr_tenant", "tenant_id"),
		Index("ix_hcm_rr_org_unit", "org_unit_id"),
		Index("ix_hcm_rr_status", "status"),
		Index("ix_hcm_rr_effective_date", "effective_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	org_unit_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_unit.id"), nullable=False, index=True)
	# MERGE | SPLIT | RENAME | REPARENT | ABOLISH
	restructure_type = Column(String(20), nullable=False)
	requested_by = Column(String(255), nullable=False, comment="User who raised the request")
	effective_date = Column(Date, nullable=False, comment="Intended date for the change to take effect")
	description = Column(Text, nullable=True)
	change_payload_json = Column(JSONB, nullable=False, default=dict, comment="Before/after snapshot {before: {...}, after: {...}}")
	# DRAFT | APPROVED | REJECTED | APPLIED
	status = Column(String(20), nullable=False, default="DRAFT")
	approved_by = Column(String(255), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	rejected_reason = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	org_unit: OrgUnit = relationship("OrgUnit", lazy="select")

	def __repr__(self) -> str:
		return f"<OrgRestructureRequest {self.restructure_type!r} unit={self.org_unit_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# PositionRequisition  [CRITICAL — vacancy tracking with workflow]
# ---------------------------------------------------------------------------

class PositionRequisition(AuditMixin, Model):
	"""Open-position requisition with approval workflow.

	Lifecycle: OPEN → APPROVED → FILLED | CANCELLED

	opened_at / filled_at enable vacancy age analytics.
	target_fill_date is set by the requester; SLA breach tracking can be
	built on top via the Rules Engine.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_position_requisition"
	__table_args__ = (
		Index("ix_hcm_pr_tenant", "tenant_id"),
		Index("ix_hcm_pr_position", "position_id"),
		Index("ix_hcm_pr_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	position_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_position.id"), nullable=False, index=True)
	requester_id = Column(String(255), nullable=False, comment="User ID of HR/manager who raised the requisition")
	target_fill_date = Column(Date, nullable=True, comment="Target date by which position should be filled")
	# OPEN | APPROVED | FILLED | CANCELLED
	status = Column(String(20), nullable=False, default="OPEN")
	approver_id = Column(String(255), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	opened_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
	filled_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	position: Position = relationship("Position", lazy="select")

	def __repr__(self) -> str:
		return f"<PositionRequisition pos={self.position_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# HeadcountBudget  [CRITICAL — FTE headcount budget vs actual]
# ---------------------------------------------------------------------------

class HeadcountBudget(AuditMixin, Model):
	"""Period-based FTE headcount budget for an OrgUnit.

	Finance sets budgeted_fte and budgeted_amount_cents per fiscal year/period.
	Actuals are derived at query time via get_headcount_actual() service method.
	headcount_variance() exposes the delta.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_headcount_budget"
	__table_args__ = (
		Index("ix_hcm_hb_tenant", "tenant_id"),
		Index("ix_hcm_hb_org_unit", "org_unit_id"),
		UniqueConstraint("tenant_id", "org_unit_id", "fiscal_year", "period", name="uq_hcm_hb_unit_period"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	org_unit_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_unit.id"), nullable=False, index=True)
	fiscal_year = Column(Integer, nullable=False, comment="e.g. 2026")
	# Period 1-12 for monthly; 0 = annual budget
	period = Column(Integer, nullable=False, default=0, comment="1-12 for monthly; 0 = full-year budget")
	budgeted_fte = Column(Integer, nullable=False, comment="Approved FTE count for this period")
	budgeted_amount_cents = Column(BigInteger, nullable=False, default=0, comment="Approved payroll budget in cents")
	currency_code = Column(String(3), nullable=False, default="KES")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	org_unit: OrgUnit = relationship("OrgUnit", lazy="select")

	def __repr__(self) -> str:
		return f"<HeadcountBudget unit={self.org_unit_id!r} fy={self.fiscal_year} period={self.period} fte={self.budgeted_fte}>"


# ---------------------------------------------------------------------------
# JobGrade  [task spec — simple grade catalogue, unique per tenant]
# ---------------------------------------------------------------------------

class JobGrade(AuditMixin, Model):
	"""Simple pay-grade catalogue entry.

	Unlike CompensationGrade (which is an effective-dated, immutable ledger),
	JobGrade is a mutable master-data record keyed by grade_code per tenant.
	It stores the current approved band and is updated in-place when the band
	changes.  Use CompensationGrade for point-in-time history and gazette refs.

	All amounts are integer cents — NEVER float.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_job_grade"
	__table_args__ = (
		Index("ix_hcm_jg_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "grade_code", name="uq_hcm_jg_tenant_grade"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	grade_code = Column(String(20), nullable=False, comment="Pay grade code, unique per tenant e.g. G5, IC3")
	grade_name = Column(String(100), nullable=False, comment="Human-readable label e.g. Senior Engineer")
	min_salary_cents = Column(BigInteger, nullable=False, comment="Minimum annual salary in cents")
	mid_salary_cents = Column(BigInteger, nullable=False, comment="Midpoint salary in cents")
	max_salary_cents = Column(BigInteger, nullable=False, comment="Maximum annual salary in cents")
	currency_code = Column(String(3), nullable=False, default="KES", comment="ISO 4217 currency code")

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
		return f"<JobGrade {self.grade_code!r} min={self.min_salary_cents}¢ max={self.max_salary_cents}¢ {self.currency_code}>"


# ---------------------------------------------------------------------------
# OrgRole  [HIGH — role-based org modelling]
# ---------------------------------------------------------------------------

class OrgRole(AuditMixin, Model):
	"""Abstract role in a RACI matrix attached to an OrgUnit.

	Roles propagate downward through the hierarchy when inherited=True.
	Positions reference roles via PositionRole association.
	Essential for Kenya devolved government: "Budget Officer" role defined at
	national level and inherited by all county Treasury org units.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_role"
	__table_args__ = (
		Index("ix_hcm_or_tenant", "tenant_id"),
		Index("ix_hcm_or_org_unit", "org_unit_id"),
		UniqueConstraint("tenant_id", "role_code", name="uq_hcm_or_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	role_code = Column(String(30), nullable=False, comment="Unique role identifier per tenant")
	role_name = Column(String(200), nullable=False)
	org_unit_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_unit.id"), nullable=True, comment="Owning org unit; NULL = global role")
	# JSONB: {responsible: [...], accountable: [...], consulted: [...], informed: [...]}
	responsibilities_json = Column(JSONB, nullable=False, default=dict, comment="RACI responsibilities for this role")
	inherited = Column(Boolean, nullable=False, default=False, comment="If True, child org units inherit this role")
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	org_unit: OrgUnit | None = relationship("OrgUnit", lazy="select")
	position_roles: list[PositionRole] = relationship("PositionRole", back_populates="role", lazy="select")

	def __repr__(self) -> str:
		return f"<OrgRole {self.role_code!r} {self.role_name!r} inherited={self.inherited}>"


# ---------------------------------------------------------------------------
# PositionRole  [HIGH — role-based org modelling, M2M association]
# ---------------------------------------------------------------------------

class PositionRole(Model):
	"""Many-to-many association between Position and OrgRole."""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_position_role"
	__table_args__ = (
		UniqueConstraint("position_id", "role_id", name="uq_hcm_pr_pos_role"),
		Index("ix_hcm_pr2_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	position_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_position.id"), nullable=False, index=True)
	role_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_role.id"), nullable=False, index=True)
	assigned_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

	# Relationships
	role: OrgRole = relationship("OrgRole", back_populates="position_roles", lazy="select")
	position: Position = relationship("Position", lazy="select")

	def __repr__(self) -> str:
		return f"<PositionRole pos={self.position_id!r} role={self.role_id!r}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"HcmLegalEntity",
	"OrgUnit",
	"OrgUnitHistory",
	"JobCatalog",
	"JobGrade",
	"CompensationGrade",
	"CompensationGradeExchange",
	"Position",
	"ReportingLine",
	"OrgRestructureRequest",
	"PositionRequisition",
	"HeadcountBudget",
	"OrgRole",
	"PositionRole",
]
