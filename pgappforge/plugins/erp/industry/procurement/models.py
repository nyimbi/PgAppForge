"""
pgappforge/plugins/erp/industry/procurement/models.py

SQLAlchemy models for the Public Procurement plugin (OCDS-compliant).

Design invariants:
  - ALL PKs: UUID v4 via gen_random_uuid()
  - ALL monetary amounts: Integer cents (NEVER float)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - ContractPayment records are IMMUTABLE (insert-only ledger)
  - ALL timestamps: DateTime(timezone=True) — TIMESTAMPTZ
  - lazy='select' throughout
  - Table prefix: proc_

OCDS alignment:
  TenderNotice  → ocds Release (tender stage)
  Bid           → ocds Tender/tenderers + Award evaluation
  ProcurementContract      → ocds ProcurementContract
  ContractMilestone → ocds ProcurementContract/milestones
  ContractPayment   → ocds Implementation/transactions
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ProcuringEntity
# ---------------------------------------------------------------------------

class ProcuringEntity(AuditMixin, Model):
	"""Government / SOE / international body that initiates procurements.

	Links to foundation.Party for shared contact/address data.
	entity_type drives which procurement rules and thresholds apply.
	annual_procurement_budget_cents is used for spend analytics.
	"""

	__allow_unmapped__ = True
	__tablename__ = "proc_procuring_entity"
	__table_args__ = (
		Index("ix_proc_entity_tenant", "tenant_id"),
		Index("ix_proc_entity_party", "party_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	party_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation.Party (soft)")

	# OCDS: buyer identifier
	entity_type = Column(
		String(30),
		nullable=False,
		default="NATIONAL",
		comment="NATIONAL|LOCAL|SOE|INTERNATIONAL",
	)
	buyer_profile_url = Column(Text, nullable=True, comment="Public procurement portal profile URL")
	annual_procurement_budget_cents = Column(
		Integer, nullable=False, default=0,
		comment="Annual procurement budget in integer cents",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	tenders: list[TenderNotice] = relationship("TenderNotice", back_populates="procuring_entity", lazy="select")

	def __repr__(self) -> str:
		return f"<ProcuringEntity {self.id!r} type={self.entity_type!r}>"


# ---------------------------------------------------------------------------
# TenderNotice
# ---------------------------------------------------------------------------

class TenderNotice(AuditMixin, Model):
	"""Core OCDS tender record — from planning through close of bidding.

	One row per OCID (globally unique contracting process identifier).
	lots and items follow OCDS array schemas stored as JSONB.
	documents JSONB: [{id, title, url, format, language, datePublished}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "proc_tender_notice"
	__table_args__ = (
		Index("ix_proc_tender_tenant", "tenant_id"),
		Index("ix_proc_tender_entity", "procuring_entity_id"),
		Index("ix_proc_tender_status", "status"),
		Index("ix_proc_tender_method", "procurement_method"),
		Index("ix_proc_tender_category", "main_procurement_category"),
		UniqueConstraint("ocid", name="uq_proc_tender_ocid"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# OCDS required fields
	ocid = Column(String(100), nullable=False, unique=True, comment="OCDS globally unique contracting process ID")
	title = Column(String(1024), nullable=False)
	description = Column(Text, nullable=True)
	procuring_entity_id = Column(UUID(as_uuid=False), ForeignKey("proc_procuring_entity.id"), nullable=False, index=True)

	# Procurement classification
	procurement_method = Column(
		String(30),
		nullable=False,
		default="OPEN",
		comment="OPEN|LIMITED|DIRECT|COMPETITIVE_DIALOGUE",
	)
	main_procurement_category = Column(
		String(20),
		nullable=False,
		default="GOODS",
		comment="GOODS|WORKS|SERVICES",
	)

	# Value
	tender_value_estimate_cents = Column(Integer, nullable=True, comment="Estimated contract value in cents")
	currency_code = Column(String(3), nullable=False, default="USD")

	# Timeline
	publication_date = Column(DateTime(timezone=True), nullable=True)
	deadline_date = Column(DateTime(timezone=True), nullable=True, comment="Bid submission deadline")

	# Criteria
	eligibility_criteria = Column(Text, nullable=True)
	selection_criteria = Column(Text, nullable=True)

	# OCDS JSONB arrays
	lots = Column(JSONB, nullable=False, default=list, comment="[{id, title, value, status}]")
	items = Column(JSONB, nullable=False, default=list, comment="[{id, description, quantity, unit, classification}]")
	documents = Column(JSONB, nullable=False, default=list, comment="[{id, title, url, format, language, datePublished}]")

	status = Column(
		String(20),
		nullable=False,
		default="PLANNING",
		comment="PLANNING|ACTIVE|CANCELLED|COMPLETE|UNSUCCESSFUL",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	procuring_entity: ProcuringEntity = relationship("ProcuringEntity", back_populates="tenders", lazy="select")
	bids: list[Bid] = relationship("Bid", back_populates="tender", lazy="select")
	contracts: list[ProcurementContract] = relationship("ProcurementContract", back_populates="tender", lazy="select")

	def __repr__(self) -> str:
		return f"<TenderNotice ocid={self.ocid!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Bid
# ---------------------------------------------------------------------------

class Bid(AuditMixin, Model):
	"""Supplier bid submitted against a TenderNotice.

	technical_score, financial_score, overall_score are populated during
	the evaluation phase by ProcurementService.evaluate_bids().
	lot_bids JSONB: [{lot_id, price_cents, documents}]
	documents JSONB: bid qualification documents array.
	"""

	__allow_unmapped__ = True
	__tablename__ = "proc_bid"
	__table_args__ = (
		Index("ix_proc_bid_tender", "tender_id"),
		Index("ix_proc_bid_bidder", "bidder_id"),
		Index("ix_proc_bid_tenant", "tenant_id"),
		Index("ix_proc_bid_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	tender_id = Column(UUID(as_uuid=False), ForeignKey("proc_tender_notice.id"), nullable=False, index=True)
	bidder_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to foundation.Party (soft)")

	submission_date = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
	bid_price_cents = Column(Integer, nullable=False, comment="Total bid price in integer cents")
	currency_code = Column(String(3), nullable=False, default="USD")

	# Evaluation scores — set during evaluation phase
	technical_score = Column(Numeric(5, 2), nullable=True, comment="Technical evaluation score 0–100")
	financial_score = Column(Numeric(5, 2), nullable=True, comment="Financial evaluation score 0–100")
	overall_score = Column(Numeric(5, 2), nullable=True, comment="Weighted overall score 0–100")

	lot_bids = Column(JSONB, nullable=False, default=list, comment="[{lot_id, price_cents, documents}]")
	documents = Column(JSONB, nullable=False, default=list, comment="Bid qualification documents")

	status = Column(
		String(20),
		nullable=False,
		default="SUBMITTED",
		comment="SUBMITTED|EVALUATED|SHORTLISTED|AWARDED|REJECTED",
	)
	disqualification_reason = Column(Text, nullable=True, comment="Set when status=REJECTED")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	tender: TenderNotice = relationship("TenderNotice", back_populates="bids", lazy="select")

	def __repr__(self) -> str:
		return f"<Bid tender={self.tender_id!r} bidder={self.bidder_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ProcurementContract
# ---------------------------------------------------------------------------

class ProcurementContract(AuditMixin, Model):
	"""Legally binding contract signed after award.

	Maps to OCDS ProcurementContract block.
	amendments JSONB: [{id, date, description, rationale, value_change_cents}]
	performance_bond_pct: retention percentage held until completion.
	"""

	__allow_unmapped__ = True
	__tablename__ = "proc_contract"
	__table_args__ = (
		Index("ix_proc_contract_tender", "tender_id"),
		Index("ix_proc_contract_supplier", "supplier_id"),
		Index("ix_proc_contract_tenant", "tenant_id"),
		Index("ix_proc_contract_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	tender_id = Column(UUID(as_uuid=False), ForeignKey("proc_tender_notice.id"), nullable=False, index=True)

	# OCDS award_id — string reference from the award decision
	award_id = Column(String(100), nullable=False, comment="OCDS award identifier string")
	supplier_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to foundation.Party (soft)")

	title = Column(String(1024), nullable=False)
	description = Column(Text, nullable=True)

	contract_value_cents = Column(Integer, nullable=False, comment="Contracted value in integer cents")
	currency_code = Column(String(3), nullable=False, default="USD")

	signed_date = Column(Date, nullable=True, comment="Date contract was formally executed")
	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING|ACTIVE|TERMINATED|COMPLETED",
	)
	performance_bond_pct = Column(Numeric(5, 2), nullable=False, default=0, comment="Retention bond %")
	amendments = Column(JSONB, nullable=False, default=list, comment="[{id, date, description, rationale, value_change_cents}]")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	tender: TenderNotice = relationship("TenderNotice", back_populates="contracts", lazy="select")
	milestones: list[ContractMilestone] = relationship("ContractMilestone", back_populates="contract", lazy="select")
	payments: list[ContractPayment] = relationship("ContractPayment", back_populates="contract", lazy="select")

	def __repr__(self) -> str:
		return f"<ProcurementContract {self.award_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ContractMilestone
# ---------------------------------------------------------------------------

class ContractMilestone(AuditMixin, Model):
	"""Key delivery/payment/performance checkpoint within a contract.

	payment_pct: percentage of contract value due at this milestone.
	achieved_date NULL means milestone not yet met.
	"""

	__allow_unmapped__ = True
	__tablename__ = "proc_contract_milestone"
	__table_args__ = (
		Index("ix_proc_milestone_contract", "contract_id"),
		Index("ix_proc_milestone_tenant", "tenant_id"),
		Index("ix_proc_milestone_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(UUID(as_uuid=False), ForeignKey("proc_contract.id"), nullable=False, index=True)

	title = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	milestone_type = Column(
		String(20),
		nullable=False,
		default="DELIVERY",
		comment="DELIVERY|PAYMENT|PERFORMANCE|REVIEW",
	)

	due_date = Column(Date, nullable=False)
	achieved_date = Column(Date, nullable=True, comment="NULL = not yet met")
	payment_pct = Column(Numeric(5, 2), nullable=False, default=0, comment="% of contract value triggered at this milestone")

	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING|MET|MISSED|EXTENDED",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	contract: ProcurementContract = relationship("ProcurementContract", back_populates="milestones", lazy="select")

	def __repr__(self) -> str:
		return f"<ContractMilestone {self.title!r} status={self.status!r} due={self.due_date!r}>"


# ---------------------------------------------------------------------------
# ContractPayment — IMMUTABLE
# ---------------------------------------------------------------------------

class ContractPayment(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable payment record against a contract.

	Insert-only ledger — never update or delete.
	milestone_id is optional (some payments are not milestone-triggered).
	"""

	__allow_unmapped__ = True
	__tablename__ = "proc_contract_payment"
	__table_args__ = (
		Index("ix_proc_payment_contract", "contract_id"),
		Index("ix_proc_payment_milestone", "milestone_id"),
		Index("ix_proc_payment_tenant", "tenant_id"),
		Index("ix_proc_payment_date", "payment_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(UUID(as_uuid=False), ForeignKey("proc_contract.id"), nullable=False, index=True)
	milestone_id = Column(UUID(as_uuid=False), ForeignKey("proc_contract_milestone.id"), nullable=True, index=True)

	payment_date = Column(Date, nullable=False)
	amount_cents = Column(Integer, nullable=False, comment="Payment amount in integer cents")
	invoice_reference = Column(String(100), nullable=False)
	description = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	# No updated_at — immutable record

	contract: ProcurementContract = relationship("ProcurementContract", back_populates="payments", lazy="select")

	def __repr__(self) -> str:
		return f"<ContractPayment contract={self.contract_id!r} amount={self.amount_cents}¢ date={self.payment_date!r}>"


# Register immutability hook once models are defined
ContractPayment._register_immutability()


__all__ = [
	"ProcuringEntity",
	"TenderNotice",
	"Bid",
	"ProcurementContract",
	"ContractMilestone",
	"ContractPayment",
]
