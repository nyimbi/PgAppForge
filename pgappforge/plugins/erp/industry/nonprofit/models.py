"""
pgappforge/plugins/erp/industry/nonprofit/models.py

SQLAlchemy models for the Nonprofit plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid()
  - ALL monetary amounts: Integer cents (NEVER float)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - Donation records are IMMUTABLE once acknowledged
  - lazy='select' throughout
  - outcomes_tracked JSONB for flexible impact measurement

Table prefix: npo_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Donor
# ---------------------------------------------------------------------------

class Donor(AuditMixin, Model):
	"""Donor master record — individual or institutional.

	Links to foundation.Party for shared contact data.
	lifetime_giving_cents is a running total; it is updated (add-only)
	by the donation service and must never be decremented directly.

	giving_level is re-computed periodically by the donor segmentation
	service based on lifetime_giving_cents and recency.
	"""

	__allow_unmapped__ = True
	__tablename__ = "npo_donor"
	__table_args__ = (
		Index("ix_npo_donor_tenant", "tenant_id"),
		Index("ix_npo_donor_party", "party_id"),
		Index("ix_npo_donor_giving_level", "giving_level"),
		Index("ix_npo_donor_tenant_level", "tenant_id", "giving_level"),
		UniqueConstraint("tenant_id", "donor_number", name="uq_npo_donor_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	party_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation Party (soft)")
	donor_number = Column(String(50), nullable=False, comment="Unique donor reference per tenant")

	giving_level = Column(
		String(10),
		nullable=False,
		default="SMALL",
		comment="MAJOR|MID|SMALL — re-computed by segmentation service",
	)

	# Giving history — integer cents; add-only
	lifetime_giving_cents = Column(Integer, nullable=False, default=0, comment="Cumulative giving total; add-only")
	first_gift_date = Column(Date, nullable=True)
	last_gift_date = Column(Date, nullable=True)
	largest_gift_cents = Column(Integer, nullable=False, default=0)
	gift_count = Column(Integer, nullable=False, default=0, comment="Total number of donations; add-only")

	preferred_cause = Column(String(100), nullable=True, comment="Preferred program/fund designation")
	preferred_payment_method = Column(String(30), nullable=True, comment="CARD|BANK|CHECK|CRYPTO|PLEDGE")
	is_anonymous = Column(Boolean, nullable=False, default=False)
	do_not_contact = Column(Boolean, nullable=False, default=False)
	communication_preferences = Column(JSONB, nullable=False, default=dict, comment="{email: bool, sms: bool, post: bool}")

	assigned_relationship_manager_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	notes = Column(Text, nullable=True)
	status = Column(String(20), nullable=False, default="ACTIVE", comment="ACTIVE|LAPSED|DECEASED|INACTIVE")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	donations: list[Donation] = relationship("Donation", back_populates="donor", lazy="select")

	def __repr__(self) -> str:
		return f"<Donor {self.donor_number!r} level={self.giving_level!r} lifetime={self.lifetime_giving_cents}¢>"


# ---------------------------------------------------------------------------
# Donation
# ---------------------------------------------------------------------------

class Donation(AuditMixin, Model):
	"""Individual donation transaction.

	IMMUTABLE once acknowledged_at is set — to reverse, create a
	negative-amount correction donation row.
	tax_receipt_url is populated by the receipt generation service after
	acknowledgement.
	"""

	__allow_unmapped__ = True
	__tablename__ = "npo_donation"
	__table_args__ = (
		Index("ix_npo_donation_tenant", "tenant_id"),
		Index("ix_npo_donation_donor", "donor_id"),
		Index("ix_npo_donation_campaign", "campaign_id"),
		Index("ix_npo_donation_tenant_status", "tenant_id", "status"),
		Index("ix_npo_donation_donated_at", "donated_at"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	donor_id = Column(UUID(as_uuid=False), ForeignKey("npo_donor.id"), nullable=False, index=True)
	campaign_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to campaign (app-managed)")
	campaign_name = Column(String(255), nullable=True, comment="Denormalized")

	donated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

	# Amount — integer cents; NEVER float
	amount_cents = Column(Integer, nullable=False, comment="Donation amount; negative = reversal/refund")
	currency_code = Column(String(3), nullable=False, default="USD")
	exchange_rate = Column(Numeric(15, 6), nullable=False, default=1)
	functional_amount_cents = Column(Integer, nullable=False, default=0, comment="amount_cents × exchange_rate, rounded")

	payment_method = Column(String(30), nullable=True, comment="CARD|BANK|CHECK|CRYPTO|PLEDGE|PAYROLL_GIVING")
	payment_reference = Column(String(200), nullable=True)
	is_recurring = Column(Boolean, nullable=False, default=False)
	recurring_frequency = Column(String(20), nullable=True, comment="WEEKLY|MONTHLY|QUARTERLY|ANNUAL")
	designation = Column(String(100), nullable=True, comment="Fund or program this donation is restricted to")
	is_restricted = Column(Boolean, nullable=False, default=False)

	# Acknowledgement
	acknowledged_at = Column(DateTime(timezone=True), nullable=True, comment="Set when receipt is issued; makes record immutable")
	tax_receipt_url = Column(String(500), nullable=True)
	tax_receipt_number = Column(String(100), nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING|CLEARED|ACKNOWLEDGED|REVERSED|FAILED",
	)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	donor: Donor = relationship("Donor", back_populates="donations", lazy="select")

	def __repr__(self) -> str:
		return f"<Donation donor={self.donor_id!r} amount={self.amount_cents}¢ status={self.status!r}>"


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------

class Program(AuditMixin, Model):
	"""Nonprofit program — a structured initiative delivering social impact.

	theory_of_change describes the causal chain from inputs → activities →
	outputs → outcomes → impact.

	outcomes_tracked JSONB: [{metric_name, unit, target, baseline}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "npo_program"
	__table_args__ = (
		Index("ix_npo_prog_tenant", "tenant_id"),
		Index("ix_npo_prog_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "program_code", name="uq_npo_prog_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	program_code = Column(String(50), nullable=False)
	program_name = Column(String(255), nullable=False)
	theory_of_change = Column(Text, nullable=True)
	description = Column(Text, nullable=True)

	program_manager_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")

	# Budget — integer cents
	budget_cents = Column(Integer, nullable=False, default=0)
	spent_cents = Column(Integer, nullable=False, default=0, comment="Running expenditure; add-only")
	currency_code = Column(String(3), nullable=False, default="USD")

	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)
	geographic_focus = Column(JSONB, nullable=False, default=list, comment="[{country, region, district}]")
	target_beneficiaries = Column(Integer, nullable=True)
	actual_beneficiaries = Column(Integer, nullable=False, default=0)

	outcomes_tracked = Column(JSONB, nullable=False, default=list, comment="[{metric_name, unit, target, baseline}]")
	status = Column(String(20), nullable=False, default="ACTIVE", comment="ACTIVE|PLANNED|COMPLETED|SUSPENDED|CANCELLED")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	measurements: list[ImpactMeasurement] = relationship("ImpactMeasurement", back_populates="program", lazy="select")

	def __repr__(self) -> str:
		return f"<Program {self.program_code!r} {self.program_name!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ImpactMeasurement
# ---------------------------------------------------------------------------

class ImpactMeasurement(AuditMixin, Model):
	"""Quantified impact measurement for a program metric.

	One row per metric per measurement date.  Immutable once recorded.
	variance = actual_value - target_value (computed by service).
	"""

	__allow_unmapped__ = True
	__tablename__ = "npo_impact_measurement"
	__table_args__ = (
		Index("ix_npo_impact_program", "program_id"),
		Index("ix_npo_impact_tenant", "tenant_id"),
		Index("ix_npo_impact_measurement_date", "measurement_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	program_id = Column(UUID(as_uuid=False), ForeignKey("npo_program.id"), nullable=False, index=True)
	metric_name = Column(String(100), nullable=False)
	metric_unit = Column(String(50), nullable=True, comment="beneficiaries, meals, kg, km, etc.")

	target_value = Column(Numeric(20, 4), nullable=False)
	actual_value = Column(Numeric(20, 4), nullable=False)
	measurement_date = Column(Date, nullable=False)

	evidence_url = Column(String(500), nullable=True, comment="Link to supporting evidence / survey data")
	methodology = Column(Text, nullable=True, comment="How the measurement was conducted")
	verified_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	program: Program = relationship("Program", back_populates="measurements", lazy="select")

	def __repr__(self) -> str:
		return f"<ImpactMeasurement prog={self.program_id!r} metric={self.metric_name!r} actual={self.actual_value}>"


__all__ = [
	"Donor",
	"Donation",
	"Program",
	"ImpactMeasurement",
]
