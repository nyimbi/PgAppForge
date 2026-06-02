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
# LegalEntity
# ---------------------------------------------------------------------------

class LegalEntity(AuditMixin, Model):
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
		primaryjoin="LegalEntity.id == foreign(LeavePolicy.entity_id)",
		lazy="select",
		viewonly=True,
	)

	def __repr__(self) -> str:
		return f"<LegalEntity {self.entity_code!r} {self.entity_name!r}>"


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
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	legal_entity: LegalEntity = relationship("LegalEntity", back_populates="org_units", lazy="select")
	parent: OrgUnit | None = relationship("OrgUnit", remote_side="OrgUnit.id", lazy="select", foreign_keys="[OrgUnit.parent_id]")
	children: list[OrgUnit] = relationship("OrgUnit", back_populates="parent", lazy="select", foreign_keys="[OrgUnit.parent_id]", overlaps="parent")
	positions: list[Position] = relationship("Position", back_populates="org_unit", lazy="select")

	def __repr__(self) -> str:
		return f"<OrgUnit {self.org_code!r} type={self.org_type!r}>"


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
	min_cents = Column(Integer, nullable=False, comment="Minimum annual salary in cents")
	mid_cents = Column(Integer, nullable=False, comment="Midpoint / target salary in cents")
	max_cents = Column(Integer, nullable=False, comment="Maximum annual salary in cents")
	currency_code = Column(String(3), nullable=False, default="USD")
	effective_from = Column(Date, nullable=False, comment="Date this band became effective")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<CompensationGrade {self.grade_code!r} min={self.min_cents}¢ max={self.max_cents}¢>"


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class Position(AuditMixin, Model):
	"""Budgeted position in the org chart.

	A position is a slot that may be filled by one employee.
	graded_salary_min/max_cents are the approved range for this specific position,
	which may be narrower than the CompensationGrade band.

	is_filled is maintained by the Personnel plugin via EmployeeAssignedEvent.
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
	position_title = Column(String(200), nullable=False)
	employment_type = Column(
		String(20),
		nullable=False,
		default="FULL_TIME",
		comment="FULL_TIME | PART_TIME | CONTRACT | CASUAL",
	)
	is_filled = Column(Boolean, nullable=False, default=False, comment="True when an active employee occupies this position")
	graded_salary_min_cents = Column(Integer, nullable=True, comment="Position-specific salary floor in cents")
	graded_salary_max_cents = Column(Integer, nullable=True, comment="Position-specific salary ceiling in cents")
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	legal_entity: LegalEntity = relationship("LegalEntity", back_populates="positions", lazy="select")
	org_unit: OrgUnit = relationship("OrgUnit", back_populates="positions", lazy="select")
	job_catalog: JobCatalog | None = relationship("JobCatalog", back_populates="positions", lazy="select")

	def __repr__(self) -> str:
		return f"<Position {self.position_code!r} filled={self.is_filled}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LegalEntity",
	"OrgUnit",
	"JobCatalog",
	"CompensationGrade",
	"Position",
]
