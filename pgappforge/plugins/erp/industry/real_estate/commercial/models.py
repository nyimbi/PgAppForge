"""
pgappforge/plugins/erp/industry/real_estate/commercial/models.py

SQLAlchemy models for the Commercial Real Estate sub-plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY — never float
  - JSONB for rent_schedule, options, categories, tenant_allocations, rent_steps, etc.

Table name convention: re_com_<entity>
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
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
# Enumerations
# ---------------------------------------------------------------------------

UNIT_TYPE = ("OFFICE", "RETAIL", "INDUSTRIAL", "STORAGE", "MEDICAL")
UNIT_STATUS = ("VACANT", "OCCUPIED", "UNDER_NEGOTIATION", "OFFLINE")
COMMERCIAL_LEASE_TYPE = ("NNN", "MODIFIED_GROSS", "FULL_SERVICE", "GROSS")
COMMERCIAL_LEASE_STATUS = ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
LOI_STATUS = ("DRAFT", "SUBMITTED", "NEGOTIATING", "ACCEPTED", "REJECTED", "EXPIRED")
CAM_RECON_STATUS = ("DRAFT", "FINAL")


# ---------------------------------------------------------------------------
# SpaceUnit
# ---------------------------------------------------------------------------

class SpaceUnit(AuditMixin, Model):
	"""A leasable commercial space unit within a property.

	suite_code is unique per property (enforced by application logic).
	asking_rent_cents: annual per-sqft rent * sqft / 12 = monthly in cents.
	unit_type: OFFICE / RETAIL / INDUSTRIAL / STORAGE / MEDICAL
	status:    VACANT / OCCUPIED / UNDER_NEGOTIATION / OFFLINE
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_com_space"
	__table_args__ = (
		Index("ix_re_com_space_tenant", "tenant_id"),
		Index("ix_re_com_space_property", "property_id"),
		Index("ix_re_com_space_status", "status"),
		Index("ix_re_com_space_unit_type", "unit_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	suite_code = Column(String(30), nullable=False, comment="Unique suite identifier within the property")
	floor = Column(Integer, nullable=True, comment="Floor number; NULL for single-storey")
	sqft = Column(Integer, nullable=True, comment="Rentable square footage")
	unit_type = Column(
		String(20),
		nullable=False,
		default="OFFICE",
		server_default="OFFICE",
		comment="OFFICE/RETAIL/INDUSTRIAL/STORAGE/MEDICAL",
	)
	status = Column(
		String(20),
		nullable=False,
		default="VACANT",
		server_default="VACANT",
		comment="VACANT/OCCUPIED/UNDER_NEGOTIATION/OFFLINE",
	)
	asking_rent_cents = Column(
		Integer,
		nullable=True,
		comment="Monthly asking rent in cents (annual_ppsf * sqft / 12)",
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

	leases: list[CommercialLease] = relationship(
		"CommercialLease",
		back_populates="space",
		lazy="select",
	)
	lois: list[LOI] = relationship(
		"LOI",
		back_populates="space",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<SpaceUnit suite={self.suite_code!r} type={self.unit_type!r} "
			f"status={self.status!r} sqft={self.sqft}>"
		)


# ---------------------------------------------------------------------------
# CommercialLease
# ---------------------------------------------------------------------------

class CommercialLease(AuditMixin, Model):
	"""Commercial lease agreement for a SpaceUnit.

	lease_type:             NNN / MODIFIED_GROSS / FULL_SERVICE / GROSS
	base_rent_cents:        Monthly base rent in cents.
	cam_estimate_cents:     Monthly estimated CAM pass-through in cents.
	insurance_estimate_cents: Monthly estimated insurance pass-through in cents.
	tax_estimate_cents:     Monthly estimated tax pass-through in cents.
	rent_schedule JSONB:    [{period: "YYYY-MM", amount_cents}] for stepped rents.
	options JSONB:          [{type: RENEWAL/EXPANSION/TERMINATION, notice_days, terms}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_com_lease"
	__table_args__ = (
		Index("ix_re_com_lease_tenant", "tenant_id"),
		Index("ix_re_com_lease_space", "space_id"),
		Index("ix_re_com_lease_tenant_party", "tenant_party_id"),
		Index("ix_re_com_lease_status", "status"),
		Index("ix_re_com_lease_dates", "lease_start", "lease_end"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	space_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_com_space.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Parties (soft FKs to foundation.Party)
	tenant_party_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK foundation.Party — commercial lessee (soft reference)",
	)
	landlord_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="FK foundation.Party — lessor (soft reference)",
	)

	# Lease economics — all integer cents
	lease_type = Column(
		String(20),
		nullable=False,
		default="NNN",
		server_default="NNN",
		comment="NNN/MODIFIED_GROSS/FULL_SERVICE/GROSS",
	)
	base_rent_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Monthly base rent in cents",
	)
	cam_estimate_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Monthly CAM pass-through estimate in cents",
	)
	insurance_estimate_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Monthly insurance pass-through estimate in cents",
	)
	tax_estimate_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Monthly tax pass-through estimate in cents",
	)

	# Term
	lease_start = Column(Date, nullable=False)
	lease_end = Column(Date, nullable=False)

	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT/ACTIVE/EXPIRED/TERMINATED",
	)

	# JSONB fields
	rent_schedule = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{period: 'YYYY-MM', amount_cents}] for stepped/abated rents",
	)
	options = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{type: RENEWAL/EXPANSION/TERMINATION, notice_days, terms}]",
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

	space: SpaceUnit = relationship("SpaceUnit", back_populates="leases", lazy="select")
	abstract: LeaseAbstract = relationship(
		"LeaseAbstract",
		back_populates="lease",
		uselist=False,
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CommercialLease space={self.space_id!r} type={self.lease_type!r} "
			f"base={self.base_rent_cents}¢/mo status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# CAMBudget
# ---------------------------------------------------------------------------

class CAMBudget(Model):
	"""Annual Common Area Maintenance budget for a property.

	categories JSONB: {maintenance: cents, insurance: cents, taxes: cents, management: cents}
	UniqueConstraint on (tenant_id, property_id, year).
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_com_cam_budget"
	__table_args__ = (
		UniqueConstraint("tenant_id", "property_id", "year", name="uq_re_com_cam_budget"),
		Index("ix_re_com_cam_budget_property", "property_id"),
		Index("ix_re_com_cam_budget_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	year = Column(Integer, nullable=False, comment="Calendar year of the budget")
	total_budget_cents = Column(
		Integer,
		nullable=False,
		comment="Total annual CAM budget in cents",
	)
	categories = Column(
		JSONB,
		nullable=True,
		default=dict,
		server_default="{}",
		comment="{maintenance: cents, insurance: cents, taxes: cents, management: cents}",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<CAMBudget property={self.property_id!r} year={self.year} "
			f"total={self.total_budget_cents}¢>"
		)


# ---------------------------------------------------------------------------
# CAMActual
# ---------------------------------------------------------------------------

class CAMActual(Model):
	"""Actual annual Common Area Maintenance spend for a property.

	categories JSONB: same keys as CAMBudget.
	UniqueConstraint on (tenant_id, property_id, year).
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_com_cam_actual"
	__table_args__ = (
		UniqueConstraint("tenant_id", "property_id", "year", name="uq_re_com_cam_actual"),
		Index("ix_re_com_cam_actual_property", "property_id"),
		Index("ix_re_com_cam_actual_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	year = Column(Integer, nullable=False, comment="Calendar year of the actuals")
	total_actual_cents = Column(
		Integer,
		nullable=False,
		comment="Total actual CAM spend in cents",
	)
	categories = Column(
		JSONB,
		nullable=True,
		default=dict,
		server_default="{}",
		comment="{maintenance: cents, insurance: cents, taxes: cents, management: cents}",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<CAMActual property={self.property_id!r} year={self.year} "
			f"total={self.total_actual_cents}¢>"
		)


# ---------------------------------------------------------------------------
# CAMReconciliation
# ---------------------------------------------------------------------------

class CAMReconciliation(Model):
	"""Year-end CAM reconciliation — budgeted vs actual, per-tenant true-ups.

	variance_cents: actual - budgeted; positive = over-budget (tenants owe more).
	tenant_allocations JSONB:
	    [{lease_id, proration_pct, estimated_cents, actual_cents, trueup_cents}]
	status: DRAFT / FINAL
	UniqueConstraint on (tenant_id, property_id, year).
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_com_cam_reconciliation"
	__table_args__ = (
		UniqueConstraint("tenant_id", "property_id", "year", name="uq_re_com_cam_recon"),
		Index("ix_re_com_cam_recon_property", "property_id"),
		Index("ix_re_com_cam_recon_tenant", "tenant_id"),
		Index("ix_re_com_cam_recon_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	year = Column(Integer, nullable=False)
	total_budgeted_cents = Column(Integer, nullable=True, comment="Total budgeted CAM in cents")
	total_actual_cents = Column(Integer, nullable=True, comment="Total actual CAM in cents")
	variance_cents = Column(
		Integer,
		nullable=True,
		comment="actual - budgeted; positive = over-budget",
	)
	tenant_allocations = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{lease_id, proration_pct, estimated_cents, actual_cents, trueup_cents}]",
	)
	reconciled_at = Column(DateTime(timezone=True), nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT/FINAL",
	)

	def __repr__(self) -> str:
		return (
			f"<CAMReconciliation property={self.property_id!r} year={self.year} "
			f"variance={self.variance_cents}¢ status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# LeaseAbstract
# ---------------------------------------------------------------------------

class LeaseAbstract(Model):
	"""Extracted key economic terms from a CommercialLease.

	One-to-one with CommercialLease (lease_id UNIQUE).
	rent_steps JSONB:       [{effective_date, amount_cents}]
	renewal_options JSONB:  [{term_months, notice_days, rent_type: MARKET/FIXED, fixed_amount_cents}]
	termination_option JSONB nullable: {effective_date, penalty_cents}
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_com_lease_abstract"
	__table_args__ = (
		Index("ix_re_com_lease_abstract_lease", "lease_id"),
		Index("ix_re_com_lease_abstract_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	lease_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_com_lease.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
		index=True,
	)

	commencement_date = Column(Date, nullable=True)
	expiry_date = Column(Date, nullable=True)
	rent_commencement_date = Column(Date, nullable=True)
	free_rent_months = Column(Integer, nullable=False, default=0, server_default="0")
	tenant_improvement_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Tenant improvement allowance in cents",
	)

	rent_steps = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{effective_date, amount_cents}]",
	)
	renewal_options = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{term_months, notice_days, rent_type: MARKET/FIXED, fixed_amount_cents}]",
	)
	termination_option = Column(
		JSONB,
		nullable=True,
		comment="{effective_date, penalty_cents}",
	)

	exclusivity_clause = Column(Text, nullable=True)
	permitted_use = Column(Text, nullable=True)
	special_provisions = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	lease: CommercialLease = relationship(
		"CommercialLease",
		back_populates="abstract",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LeaseAbstract lease={self.lease_id!r} "
			f"commencement={self.commencement_date} expiry={self.expiry_date}>"
		)


# ---------------------------------------------------------------------------
# LOI (Letter of Intent)
# ---------------------------------------------------------------------------

class LOI(AuditMixin, Model):
	"""Letter of Intent — pre-lease negotiation record.

	status lifecycle: DRAFT → SUBMITTED → NEGOTIATING → ACCEPTED/REJECTED/EXPIRED
	ti_requested_cents:  Tenant improvement allowance requested in cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_com_loi"
	__table_args__ = (
		Index("ix_re_com_loi_tenant", "tenant_id"),
		Index("ix_re_com_loi_property", "property_id"),
		Index("ix_re_com_loi_space", "space_id"),
		Index("ix_re_com_loi_prospect", "prospect_party_id"),
		Index("ix_re_com_loi_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	space_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_com_space.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

	prospect_party_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK foundation.Party — prospective tenant (soft reference)",
	)
	proposed_term_months = Column(Integer, nullable=True)
	proposed_rent_cents = Column(Integer, nullable=True, comment="Proposed monthly rent in cents")
	proposed_start_date = Column(Date, nullable=True)
	ti_requested_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Tenant improvement allowance requested in cents",
	)
	free_rent_months = Column(Integer, nullable=False, default=0, server_default="0")

	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT/SUBMITTED/NEGOTIATING/ACCEPTED/REJECTED/EXPIRED",
	)
	notes = Column(Text, nullable=True)
	expires_at = Column(DateTime(timezone=True), nullable=True)

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

	space: SpaceUnit = relationship("SpaceUnit", back_populates="lois", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<LOI property={self.property_id!r} prospect={self.prospect_party_id!r} "
			f"rent={self.proposed_rent_cents}¢/mo status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SpaceUnit",
	"CommercialLease",
	"CAMBudget",
	"CAMActual",
	"CAMReconciliation",
	"LeaseAbstract",
	"LOI",
]
