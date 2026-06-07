"""
pgappforge/plugins/erp/finance/lease_accounting/models.py

IFRS 16 / ASC 842 Lease Accounting models.

Design rules:
  - All PKs: UUID v4 via gen_random_uuid()
  - All monetary amounts: INTEGER cents — never float
  - All rates/percentages: NUMERIC(20,8) — never float
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id UUID NOT NULL on every table
  - Table prefix: erp_la_

Key entities:
  Lease              — lease contract header (IFRS 16 / ASC 842)
  LeasePaymentSchedule — amortisation schedule lines (one row per period)
  RouAsset           — right-of-use asset balance tracker
  LeaseModification  — modification / remeasurement log (immutable audit trail)
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
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.rules.mixin import RulesMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Lease  (contract header)
# ---------------------------------------------------------------------------

class Lease(RulesMixin, AuditMixin, Model):
	"""Lease contract master record (IFRS 16 / ASC 842).

	standard:
	  IFRS16  — International Financial Reporting Standards
	  ASC842  — US GAAP (ASC 842)

	classification:
	  FINANCE    — finance lease (IFRS 16) / finance lease (ASC 842)
	  OPERATING  — short-term or low-value exemption / operating lease (ASC 842)

	status:
	  ACTIVE | TERMINATED | EXPIRED | DRAFT
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_la_lease"
	__table_args__ = (
		UniqueConstraint("tenant_id", "lease_reference", name="uq_erp_la_lease_ref"),
		Index("ix_erp_la_lease_tenant", "tenant_id"),
		Index("ix_erp_la_lease_status", "status"),
		Index("ix_erp_la_lease_commencement", "commencement_date"),
		{"extend_existing": True},
	)

	_rules_mutable_fields = frozenset({"status", "rou_asset_cents", "lease_liability_cents"})

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	lease_reference = Column(String(50), nullable=False)
	description = Column(String(500), nullable=True)
	lessor_name = Column(String(200), nullable=False)
	lessor_party_id = Column(UUID(as_uuid=False), nullable=True,
							 comment="FK to erp_party.id if lessor is a system party")
	asset_class = Column(String(100), nullable=False,
						 comment="E.g. PROPERTY, VEHICLE, EQUIPMENT, IT_ASSET")
	asset_description = Column(String(500), nullable=True)
	commencement_date = Column(Date, nullable=False)
	original_end_date = Column(Date, nullable=False,
							   comment="Original contractual end date")
	revised_end_date = Column(Date, nullable=True,
							  comment="Post-modification end date; NULL = not modified")
	lease_term_months = Column(Integer, nullable=False,
							   comment="Total reasonably certain lease term in months")
	currency_code = Column(String(3), ForeignKey("erp_currency.code"), nullable=False)
	payment_frequency = Column(String(20), nullable=False, default="MONTHLY",
							   comment="MONTHLY | QUARTERLY | ANNUAL")
	payment_amount_cents = Column(Integer, nullable=False,
								  comment="Fixed periodic lease payment in cents")
	variable_lease_payments = Column(Boolean, nullable=False, default=False,
									 comment="True if payments include variable components")
	discount_rate = Column(Numeric(20, 8), nullable=False,
						   comment="Incremental borrowing rate or implicit rate (annual, e.g. 0.085)")
	initial_direct_costs_cents = Column(Integer, nullable=False, default=0,
										comment="Upfront costs added to ROU asset")
	lease_incentives_cents = Column(Integer, nullable=False, default=0,
									comment="Lease incentives received (reduce ROU asset)")
	residual_value_guarantee_cents = Column(Integer, nullable=False, default=0,
											comment="Lessee residual value guarantee in cents")

	# Computed balances (maintained by service layer)
	rou_asset_cents = Column(Integer, nullable=False, default=0,
							 comment="Current net book value of ROU asset")
	lease_liability_cents = Column(Integer, nullable=False, default=0,
								   comment="Current present value of remaining lease payments")
	accumulated_depreciation_cents = Column(Integer, nullable=False, default=0)
	interest_accrued_cents = Column(Integer, nullable=False, default=0)

	standard = Column(String(10), nullable=False, default="IFRS16",
					  comment="IFRS16 | ASC842")
	classification = Column(String(20), nullable=False, default="FINANCE",
							comment="FINANCE | OPERATING")
	status = Column(String(20), nullable=False, default="DRAFT",
					comment="DRAFT | ACTIVE | TERMINATED | EXPIRED")
	gl_rou_account = Column(String(50), nullable=True,
							comment="GL code for ROU asset")
	gl_liability_account = Column(String(50), nullable=True,
								  comment="GL code for lease liability")
	gl_interest_account = Column(String(50), nullable=True)
	gl_depreciation_account = Column(String(50), nullable=True)
	notes = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						onupdate=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	payment_schedule: list[LeasePaymentSchedule] = relationship(
		"LeasePaymentSchedule", back_populates="lease",
		cascade="all, delete-orphan", lazy="select",
		order_by="LeasePaymentSchedule.period_number",
	)
	rou_asset: RouAsset | None = relationship(
		"RouAsset", back_populates="lease",
		uselist=False, lazy="select",
	)
	modifications: list[LeaseModification] = relationship(
		"LeaseModification", back_populates="lease",
		lazy="select", order_by="LeaseModification.modification_date",
	)

	def __repr__(self) -> str:
		return (
			f"<Lease {self.lease_reference!r} {self.lessor_name!r} "
			f"term={self.lease_term_months}m status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# LeasePaymentSchedule  (amortisation table — append-only per modification)
# ---------------------------------------------------------------------------

class LeasePaymentSchedule(Model):
	"""Single period in the lease amortisation schedule.

	Generated by LeaseService._build_amortisation_schedule() on commencement
	and after each modification. Old schedule lines are soft-deleted
	(is_superseded=True) rather than physically deleted.

	All amounts in integer cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_la_payment_schedule"
	__table_args__ = (
		Index("ix_erp_la_ps_lease", "lease_id"),
		Index("ix_erp_la_ps_period", "lease_id", "period_number"),
		Index("ix_erp_la_ps_due_date", "due_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	lease_id = Column(UUID(as_uuid=False),
					  ForeignKey("erp_la_lease.id", ondelete="CASCADE"),
					  nullable=False)
	period_number = Column(Integer, nullable=False, comment="1-based period index")
	due_date = Column(Date, nullable=False)
	opening_liability_cents = Column(Integer, nullable=False)
	interest_expense_cents = Column(Integer, nullable=False)
	payment_cents = Column(Integer, nullable=False)
	principal_reduction_cents = Column(Integer, nullable=False)
	closing_liability_cents = Column(Integer, nullable=False)
	is_superseded = Column(Boolean, nullable=False, default=False,
						   comment="True when this row is replaced by a post-modification schedule")
	is_paid = Column(Boolean, nullable=False, default=False)
	paid_at = Column(DateTime(timezone=True), nullable=True)
	gl_journal_id = Column(UUID(as_uuid=False), nullable=True,
						   comment="GL journal entry ID posted for this period")

	# Relationships
	lease: Lease = relationship("Lease", back_populates="payment_schedule", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<LeasePaymentSchedule lease={self.lease_id!r} "
			f"period={self.period_number} due={self.due_date!r} "
			f"interest={self.interest_expense_cents} principal={self.principal_reduction_cents}>"
		)


# ---------------------------------------------------------------------------
# RouAsset  (right-of-use asset balance)
# ---------------------------------------------------------------------------

class RouAsset(AuditMixin, Model):
	"""Right-of-use asset balance for a lease.

	One row per lease (one-to-one). Balances are updated by the service layer
	on each depreciation posting. Historical movements are captured in
	LeasePaymentSchedule and LeaseModification.

	depreciation_method:
	  STRAIGHT_LINE     — equal charge each period (most common)
	  UNITS_OF_PRODUCTION — usage-based (rare for leases)
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_la_rou_asset"
	__table_args__ = (
		UniqueConstraint("lease_id", name="uq_erp_la_rou_asset_lease"),
		Index("ix_erp_la_rou_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	lease_id = Column(UUID(as_uuid=False),
					  ForeignKey("erp_la_lease.id", ondelete="CASCADE"),
					  nullable=False)
	initial_cost_cents = Column(Integer, nullable=False,
								comment="Initial ROU asset: PV of payments + IDC - incentives + RVG")
	accumulated_depreciation_cents = Column(Integer, nullable=False, default=0)
	net_book_value_cents = Column(Integer, nullable=False,
								  comment="initial_cost - accumulated_depreciation")
	depreciation_method = Column(String(30), nullable=False, default="STRAIGHT_LINE")
	useful_life_months = Column(Integer, nullable=False,
								comment="Depreciation period = min(lease_term, useful_life)")
	monthly_depreciation_cents = Column(Integer, nullable=False,
									   comment="Straight-line monthly charge")
	gl_asset_account = Column(String(50), nullable=True)
	gl_depreciation_account = Column(String(50), nullable=True)
	gl_accum_dep_account = Column(String(50), nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						onupdate=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	lease: Lease = relationship("Lease", back_populates="rou_asset", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<RouAsset lease={self.lease_id!r} "
			f"cost={self.initial_cost_cents} nbv={self.net_book_value_cents}>"
		)


# ---------------------------------------------------------------------------
# LeaseModification  (immutable audit trail of remeasurements)
# ---------------------------------------------------------------------------

class LeaseModification(AuditMixin, Model):
	"""Immutable record of each lease modification / remeasurement.

	On modification, the old payment schedule is superseded and a new
	schedule is built from the modification date. This record captures
	the before/after liability balances for audit and disclosure.

	modification_type:
	  EXTENSION         — lease term extended
	  REDUCTION         — scope or term reduced (partial derecognition)
	  RATE_CHANGE       — discount rate revised (variable rate lease)
	  REASSESSMENT      — reassessment of extension/termination options
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_la_modification"
	__table_args__ = (
		Index("ix_erp_la_mod_lease", "lease_id"),
		Index("ix_erp_la_mod_date", "modification_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	lease_id = Column(UUID(as_uuid=False),
					  ForeignKey("erp_la_lease.id", ondelete="RESTRICT"),
					  nullable=False)
	modification_date = Column(Date, nullable=False)
	modification_type = Column(String(20), nullable=False,
							   comment="EXTENSION | REDUCTION | RATE_CHANGE | REASSESSMENT")
	previous_liability_cents = Column(Integer, nullable=False)
	revised_liability_cents = Column(Integer, nullable=False)
	previous_rou_cents = Column(Integer, nullable=False)
	revised_rou_cents = Column(Integer, nullable=False)
	previous_term_months = Column(Integer, nullable=False)
	revised_term_months = Column(Integer, nullable=False)
	previous_rate = Column(Numeric(20, 8), nullable=False)
	revised_rate = Column(Numeric(20, 8), nullable=False)
	gain_loss_cents = Column(Integer, nullable=False, default=0,
							 comment="P&L gain/loss on partial derecognition (REDUCTION type)")
	narration = Column(Text, nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	lease: Lease = relationship("Lease", back_populates="modifications", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<LeaseModification lease={self.lease_id!r} "
			f"type={self.modification_type!r} date={self.modification_date!r}>"
		)


__all__ = [
	"Lease",
	"LeasePaymentSchedule",
	"RouAsset",
	"LeaseModification",
]
