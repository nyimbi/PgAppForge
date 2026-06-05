"""
pgappforge/plugins/fintech/trade_finance/models.py

Trade Finance models: Letters of Credit, LC Presentations, Bank Guarantees,
Documentary Collections, Supply Chain Finance.

Design rules enforced:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL + created_at/updated_at
  - ALL monetary amounts: INTEGER cents/kobo/fils — never Decimal/float in storage
  - LCPresentation: ImmutableRecordMixin — financial presentation records never updated
  - JSONB for documents_required, documents_presented, discrepancies, documents_held

Table name convention: tf_<entity>
"""
from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
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
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# LetterOfCredit
# ---------------------------------------------------------------------------

class LetterOfCredit(AuditMixin, Model):
	"""Documentary Letter of Credit — the primary instrument for international trade settlement.

	Supports: SIGHT / USANCE / TRANSFERABLE / BACK_TO_BACK / STANDBY / RED_CLAUSE / GREEN_CLAUSE

	Key East Africa use cases:
	  - SGR (Standard Gauge Railway) goods imports through Mombasa port
	  - Agricultural export financing (tea, coffee, flowers to EU/ME)
	  - Oil import financing for landlocked Uganda/Rwanda via Kenya pipeline

	amount_cents: total LC face value in minor currency units (never float)
	margin_cents: cash collateral held against the LC (reduces bank's risk exposure)
	amount_utilized_cents: running total of presentations settled (≤ amount_cents + tolerance)
	swift_mt700: generated SWIFT MT700 message text (stored for reference/replay)

	Status flow:
	  DRAFT → ISSUED → AMENDED → PRESENTED → DISCREPANT | ACCEPTED → PAID | EXPIRED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_letter_of_credit"
	__table_args__ = (
		UniqueConstraint("lc_number", "tenant_id", name="uq_tf_lc_number_tenant"),
		Index("ix_tf_lc_applicant", "applicant_id"),
		Index("ix_tf_lc_status", "status"),
		Index("ix_tf_lc_tenant_expiry", "tenant_id", "expiry_date"),
		Index("ix_tf_lc_issue_date", "issue_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		String(64),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	# LC identification
	lc_number = Column(
		String(30),
		nullable=False,
		comment="Bank-assigned LC reference number e.g. LC/2026/001234",
	)
	lc_type = Column(
		String(30),
		nullable=False,
		comment="SIGHT | USANCE | TRANSFERABLE | BACK_TO_BACK | STANDBY | RED_CLAUSE | GREEN_CLAUSE",
	)

	# Parties
	applicant_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Importer / buyer who requests the LC",
	)
	beneficiary_name = Column(
		String(200),
		nullable=False,
		comment="Exporter / seller name (may be foreign party, no FK)",
	)
	beneficiary_bank_bic = Column(
		String(11),
		nullable=True,
		comment="BIC/SWIFT of beneficiary's advising bank",
	)
	issuing_bank_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="The bank issuing (guaranteeing) this LC",
	)
	confirming_bank_bic = Column(
		String(11),
		nullable=True,
		comment="BIC of confirming bank (adds its guarantee to issuing bank's)",
	)
	advising_bank_bic = Column(
		String(11),
		nullable=True,
		comment="BIC of advising bank in beneficiary's country",
	)

	# Financial terms
	currency_code = Column(
		String(3),
		nullable=False,
		comment="ISO 4217 currency code e.g. USD, EUR, KES",
	)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="LC face value in minor currency units (integer cents — never float)",
	)
	tolerance_pct = Column(
		Numeric(4, 1),
		nullable=False,
		default=10,
		server_default="10",
		comment="Permitted amount tolerance ±% (UCP 600 Art 30: default 10%)",
	)
	margin_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Cash margin/collateral held on applicant account",
	)
	amount_utilized_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Running total of settled presentations against this LC",
	)

	# Dates
	issue_date = Column(Date, nullable=False, comment="Date LC was issued by issuing bank")
	expiry_date = Column(Date, nullable=False, comment="Last date documents can be presented")
	expiry_place = Column(
		String(200),
		nullable=False,
		comment="Place of expiry per UCP 600 (e.g. 'Nairobi, Kenya' or beneficiary's country)",
	)
	latest_shipment_date = Column(
		Date,
		nullable=True,
		comment="Latest date goods must be shipped (bill of lading date)",
	)

	# Shipment conditions
	partial_shipments = Column(
		String(20),
		nullable=False,
		default="NOT_ALLOWED",
		server_default="'NOT_ALLOWED'",
		comment="ALLOWED | NOT_ALLOWED | CONDITIONAL",
	)
	transhipment = Column(
		String(20),
		nullable=False,
		default="NOT_ALLOWED",
		server_default="'NOT_ALLOWED'",
		comment="ALLOWED | NOT_ALLOWED | CONDITIONAL",
	)
	port_of_loading = Column(
		String(100),
		nullable=True,
		comment="Port/airport/place of dispatch e.g. 'Shanghai, China'",
	)
	port_of_discharge = Column(
		String(100),
		nullable=True,
		comment="Port/airport/place of destination e.g. 'Mombasa, Kenya'",
	)

	# Goods and documents
	description_of_goods = Column(
		Text,
		nullable=False,
		comment="Precise description per LC (per UCP 600 Art 18 — matches invoice)",
	)
	documents_required = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Required documents and copy counts: {commercial_invoice: 3, bill_of_lading: 1, ...}",
	)
	special_conditions = Column(
		Text,
		nullable=True,
		comment="Additional LC terms and conditions (free text)",
	)

	# Linked account (for margin hold)
	applicant_margin_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id", ondelete="SET NULL"),
		nullable=True,
		comment="Core banking account from which margin is held",
	)

	# State
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		server_default="'DRAFT'",
		comment="DRAFT | ISSUED | AMENDED | PRESENTED | DISCREPANT | ACCEPTED | PAID | EXPIRED | CANCELLED",
	)

	# SWIFT message text
	swift_mt700 = Column(
		Text,
		nullable=True,
		comment="Generated SWIFT MT700 (LC Issuance) message text",
	)

	# GL journal linkage (CRITICAL gap 1)
	gl_journal_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="FK to tf_gl_journal for the issuance posting (non-FK to avoid circular mapper load)",
	)

	# AML screening (HIGH gap — AML hook)
	screening_ref = Column(String(100), nullable=True,
		comment="External AML/sanctions screening reference ID")
	screening_status = Column(String(20), nullable=True, default="PENDING",
		comment="CLEAR | HIT | PENDING | BYPASSED")
	screening_bypassed_by = Column(String(100), nullable=True,
		comment="User who bypassed a screening HIT (must hold BYPASS_AML_SCREENING permission)")

	# Activity tracking (HIGH gap — standing instructions / dormancy)
	last_activity_date = Column(Date, nullable=True,
		comment="Date of last service mutation — updated on every state change")

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
	applicant = relationship(
		"Party",
		foreign_keys=[applicant_id],
		lazy="select",
	)
	issuing_bank = relationship(
		"Party",
		foreign_keys=[issuing_bank_id],
		lazy="select",
	)
	presentations: list[LCPresentation] = relationship(
		"LCPresentation",
		back_populates="lc",
		cascade="all, delete-orphan",
		lazy="select",
	)
	# margin_account: cross-plugin relationship to cb_account — resolved at runtime
	# via TradeFinanceService._place_margin_hold(); no ORM relationship here to
	# avoid mapper resolution failures when core_banking models aren't loaded.

	def __repr__(self) -> str:
		return (
			f"<LetterOfCredit {self.lc_number!r} type={self.lc_type!r} "
			f"status={self.status!r} amount={self.amount_cents} {self.currency_code}>"
		)


# ---------------------------------------------------------------------------
# LCPresentation  — IMMUTABLE (financial record, no UPDATE allowed)
# ---------------------------------------------------------------------------

class LCPresentation(ImmutableRecordMixin, AuditMixin, Model):
	"""Documents presented under a Letter of Credit by the beneficiary's bank.

	IMMUTABLE: Once a presentation record is created, it must never be updated.
	Discrepancy waivers, payment confirmations, and status changes are recorded
	via new LCPresentationAmendment entries (compensation pattern).

	Examination follows UCP 600 Art 14-17 (5-banking-day examination period).

	Status flow:
	  UNDER_EXAMINATION → COMPLIANT | DISCREPANT → ACCEPTED | REJECTED | WAIVED → (payment)
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_lc_presentation"
	__table_args__ = (
		UniqueConstraint("presentation_number", "tenant_id", name="uq_tf_lcp_number_tenant"),
		Index("ix_tf_lcp_lc_id", "lc_id"),
		Index("ix_tf_lcp_status", "status"),
		Index("ix_tf_lcp_tenant_date", "tenant_id", "presentation_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		String(64),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	lc_id = Column(
		UUID(as_uuid=False),
		ForeignKey("tf_letter_of_credit.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	presentation_number = Column(
		String(30),
		nullable=False,
		comment="Unique presentation reference e.g. PRES/2026/000789",
	)
	presented_by_bank_bic = Column(
		String(11),
		nullable=True,
		comment="BIC of presenting bank (beneficiary's bank)",
	)
	presentation_date = Column(
		Date,
		nullable=False,
		comment="Date documents were physically/electronically presented",
	)
	amount_presented_cents = Column(
		Integer,
		nullable=False,
		comment="Value of documents presented (must be within LC tolerance)",
	)
	documents_presented = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Documents received: {bill_of_lading: {copies: 1, reference: 'BL001', ...}}",
	)
	discrepancies = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="List of discrepancy descriptions per UCP 600 Art 16",
	)
	status = Column(
		String(20),
		nullable=False,
		default="UNDER_EXAMINATION",
		server_default="'UNDER_EXAMINATION'",
		comment="UNDER_EXAMINATION | COMPLIANT | DISCREPANT | ACCEPTED | REJECTED | WAIVED",
	)
	examination_completed_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when examination was finalised (within 5 banking days per UCP 600)",
	)
	payment_due_date = Column(
		Date,
		nullable=True,
		comment="For usance LCs: maturity date when payment falls due",
	)
	payment_made_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when settlement was executed",
	)

	# GL journal linkage (CRITICAL gap 1)
	gl_journal_id = Column(UUID(as_uuid=False), nullable=True,
		comment="FK to tf_gl_journal for the settlement posting")

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
	lc: LetterOfCredit = relationship(
		"LetterOfCredit",
		back_populates="presentations",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LCPresentation {self.presentation_number!r} "
			f"lc={self.lc_id!r} status={self.status!r} "
			f"amount={self.amount_presented_cents}>"
		)


# Register immutability guard after class definition
LCPresentation._register_immutability()


# ---------------------------------------------------------------------------
# BankGuarantee
# ---------------------------------------------------------------------------

class BankGuarantee(AuditMixin, Model):
	"""Bank Guarantee — contingent liability instrument.

	East Africa types:
	  BID_BOND: public tender requirements (Kenya Government tenders ≥ KES 5M)
	  PERFORMANCE: construction, SGR works, government contracts
	  ADVANCE_PAYMENT: buyer releases advance, seller guarantees delivery
	  PAYMENT: seller ships on open account, bank guarantees buyer payment
	  RETENTION: contractor's retention money guarantee
	  CUSTOMS: CBK-mandated customs duty guarantee for bonded warehouses

	commission_rate_pa: annual commission rate (e.g. 0.015 = 1.5% p.a.)
	margin_cents: cash held to collateralise the guarantee
	claimed_amount_cents: amount paid out on claims (may be < amount_cents for partial claims)

	Status flow:
	  ISSUED → EXTENDED → CLAIMED | EXPIRED | RETURNED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_bank_guarantee"
	__table_args__ = (
		UniqueConstraint("guarantee_number", "tenant_id", name="uq_tf_bg_number_tenant"),
		Index("ix_tf_bg_applicant", "applicant_id"),
		Index("ix_tf_bg_status", "status"),
		Index("ix_tf_bg_tenant_expiry", "tenant_id", "expiry_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		String(64),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	guarantee_number = Column(
		String(30),
		nullable=False,
		comment="Bank-assigned guarantee reference e.g. BG/2026/002456",
	)
	guarantee_type = Column(
		String(30),
		nullable=False,
		comment="BID_BOND | PERFORMANCE | ADVANCE_PAYMENT | PAYMENT | RETENTION | CUSTOMS",
	)

	# Parties
	applicant_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Principal / obligor requesting the guarantee",
	)
	beneficiary_name = Column(
		String(200),
		nullable=False,
		comment="Guarantee beneficiary (may be government body, foreign buyer, etc.)",
	)
	underlying_contract_reference = Column(
		String(100),
		nullable=True,
		comment="Contract / tender number that this guarantee supports",
	)

	# Financial terms
	currency_code = Column(
		String(3),
		nullable=False,
		default="KES",
		server_default="'KES'",
		comment="ISO 4217 currency code (KES default for local guarantees)",
	)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Guarantee face value in minor currency units",
	)
	commission_rate_pa = Column(
		Numeric(5, 3),
		nullable=False,
		default="0.015",
		server_default="0.015",
		comment="Annual commission rate (e.g. 0.015 = 1.5% p.a.)",
	)
	margin_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Cash margin held as collateral",
	)
	claimed_amount_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Cumulative amount paid on claims (never exceed amount_cents)",
	)

	# Dates
	issue_date = Column(Date, nullable=False)
	expiry_date = Column(Date, nullable=False)
	claim_period_days = Column(
		Integer,
		nullable=False,
		default=30,
		server_default="30",
		comment="Days after expiry within which beneficiary may still lodge a claim",
	)

	# Guarantee text
	guarantee_text = Column(
		Text,
		nullable=False,
		comment="Full legal text of the guarantee instrument",
	)

	# Linked margin account
	margin_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id", ondelete="SET NULL"),
		nullable=True,
		comment="Core banking account from which margin is held",
	)

	# State
	status = Column(
		String(20),
		nullable=False,
		default="ISSUED",
		server_default="'ISSUED'",
		comment="ISSUED | EXTENDED | CLAIMED | EXPIRED | RETURNED | CANCELLED",
	)

	# GL journal linkage (CRITICAL gap 1)
	gl_journal_id = Column(UUID(as_uuid=False), nullable=True,
		comment="FK to tf_gl_journal for the issuance posting")

	# AML screening (HIGH gap — AML hook)
	screening_ref = Column(String(100), nullable=True)
	screening_status = Column(String(20), nullable=True, default="PENDING",
		comment="CLEAR | HIT | PENDING | BYPASSED")
	screening_bypassed_by = Column(String(100), nullable=True)

	# Activity tracking
	last_activity_date = Column(Date, nullable=True)

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
	applicant = relationship(
		"Party",
		foreign_keys=[applicant_id],
		lazy="select",
	)
	# margin_account: cross-plugin FK to cb_account — no ORM relationship here.

	def __repr__(self) -> str:
		return (
			f"<BankGuarantee {self.guarantee_number!r} type={self.guarantee_type!r} "
			f"status={self.status!r} amount={self.amount_cents} {self.currency_code}>"
		)


# ---------------------------------------------------------------------------
# DocumentaryCollection
# ---------------------------------------------------------------------------

class DocumentaryCollection(AuditMixin, Model):
	"""Documentary Collection — lower-cost alternative to LC for trusted trade relationships.

	Types:
	  D/P (Documents against Payment): importer pays before documents released
	  D/A (Documents against Acceptance): importer accepts draft, gets documents,
	      pays at maturity (gives importer a credit period)

	East Africa use: Ugandan/Rwandan importers sourcing from China/India
	where the LC cost is prohibitive but seller needs more security than open account.

	Instructions field stores SWIFT MT400/MT410 format collection instructions
	from the remitting bank (exporter's bank).

	Status flow:
	  RECEIVED → PRESENTED → ACCEPTED (D/A) | PAID (D/P) → PROTESTED | RETURNED
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_documentary_collection"
	__table_args__ = (
		UniqueConstraint("collection_number", "tenant_id", name="uq_tf_dc_number_tenant"),
		Index("ix_tf_dc_exporter", "exporter_id"),
		Index("ix_tf_dc_status", "status"),
		Index("ix_tf_dc_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		String(64),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	collection_number = Column(
		String(30),
		nullable=False,
		comment="Collecting bank's reference number e.g. COL/2026/003789",
	)
	collection_type = Column(
		String(10),
		nullable=False,
		comment="D/P (Documents against Payment) | D/A (Documents against Acceptance)",
	)

	# Parties
	exporter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Exporter / seller (principal) party",
	)
	importer_name = Column(
		String(200),
		nullable=False,
		comment="Importer / drawee name (may be foreign — no FK)",
	)

	# Banks
	remitting_bank_bic = Column(
		String(11),
		nullable=True,
		comment="BIC of remitting bank (exporter's bank that sent the collection)",
	)
	collecting_bank_bic = Column(
		String(11),
		nullable=True,
		comment="BIC of collecting bank (our bank — presents to importer)",
	)

	# Financial terms
	currency_code = Column(
		String(3),
		nullable=False,
		comment="ISO 4217 currency code",
	)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Collection amount in minor currency units",
	)
	draft_tenor = Column(
		String(50),
		nullable=True,
		comment="Payment tenor e.g. 'AT SIGHT' or '90 DAYS AFTER SIGHT'",
	)

	# Documents and instructions
	documents_held = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Documents held by collecting bank: {bill_of_lading: 1, invoice: 3, ...}",
	)
	instructions = Column(
		Text,
		nullable=False,
		comment="SWIFT MT400/MT410 collection instructions from remitting bank",
	)

	# State
	status = Column(
		String(20),
		nullable=False,
		default="RECEIVED",
		server_default="'RECEIVED'",
		comment="RECEIVED | PRESENTED | ACCEPTED | PAID | PROTESTED | RETURNED",
	)

	# GL journal linkage (CRITICAL gap 1)
	gl_journal_id = Column(UUID(as_uuid=False), nullable=True,
		comment="FK to tf_gl_journal for the registration posting")

	# Activity tracking
	last_activity_date = Column(Date, nullable=True)

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
	exporter = relationship(
		"Party",
		foreign_keys=[exporter_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<DocumentaryCollection {self.collection_number!r} "
			f"type={self.collection_type!r} status={self.status!r} "
			f"amount={self.amount_cents} {self.currency_code}>"
		)


# ---------------------------------------------------------------------------
# SupplyChainFinance  — reverse factoring / buyer-led SCF
# ---------------------------------------------------------------------------

class SupplyChainFinanceProgram(AuditMixin, Model):
	"""Supply Chain Finance programme — buyer-anchored reverse factoring.

	The buyer (anchor) negotiates an SCF facility with the bank.
	Approved suppliers can then request early payment on confirmed invoices
	at a discount rate derived from the buyer's credit risk (not the supplier's).

	East Africa use:
	  - Supermarket chains (Naivas, Carrefour) enabling FMCG supplier early pay
	  - Tea factory advance against crop delivery schedules
	  - Oil marketing companies financing upstream supply chain

	discount_rate_pa: annual discount rate applied to early-payment requests
	max_programme_limit_cents: total programme revolving credit limit
	utilised_cents: current outstanding early-payment balance
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_scf_program"
	__table_args__ = (
		UniqueConstraint("program_code", "tenant_id", name="uq_tf_scf_prog_code_tenant"),
		Index("ix_tf_scf_prog_buyer", "buyer_id"),
		Index("ix_tf_scf_prog_status", "status"),
		Index("ix_tf_scf_prog_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	program_code = Column(String(30), nullable=False)
	program_name = Column(String(200), nullable=False)

	# Anchor buyer
	buyer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Anchor buyer whose credit underpins the programme",
	)

	# Financial terms
	currency_code = Column(String(3), nullable=False, default="KES")
	max_programme_limit_cents = Column(
		Integer,
		nullable=False,
		comment="Revolving programme limit in minor currency units",
	)
	utilised_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Current outstanding early-payment balance",
	)
	discount_rate_pa = Column(
		Numeric(5, 3),
		nullable=False,
		comment="Annual discount rate (e.g. 0.085 = 8.5% p.a.) based on buyer's credit risk",
	)

	# Programme tenure
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)

	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		server_default="'ACTIVE'",
		comment="ACTIVE | SUSPENDED | EXPIRED | CANCELLED",
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

	buyer = relationship("Party", foreign_keys=[buyer_id], lazy="select")
	receivables: list[SCFReceivable] = relationship(
		"SCFReceivable",
		back_populates="program",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<SupplyChainFinanceProgram {self.program_code!r} "
			f"status={self.status!r} utilised={self.utilised_cents}>"
		)


class SCFReceivable(ImmutableRecordMixin, AuditMixin, Model):
	"""Individual invoice receivable within a Supply Chain Finance programme.

	IMMUTABLE: Each early-payment request creates a new record.
	Repayments are separate settlement records (correction pattern).

	invoice_amount_cents: face value of the underlying supplier invoice
	early_payment_cents: amount disbursed to supplier (invoice_amount - discount)
	discount_cents: the fee/interest charged for early payment
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_scf_receivable"
	__table_args__ = (
		UniqueConstraint("receivable_number", "tenant_id", name="uq_tf_scf_recv_number_tenant"),
		Index("ix_tf_scf_recv_program", "program_id"),
		Index("ix_tf_scf_recv_supplier", "supplier_id"),
		Index("ix_tf_scf_recv_due_date", "buyer_payment_due_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	program_id = Column(
		UUID(as_uuid=False),
		ForeignKey("tf_scf_program.id", ondelete="RESTRICT"),
		nullable=False,
	)
	supplier_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
	)

	receivable_number = Column(String(30), nullable=False)
	invoice_reference = Column(String(100), nullable=False, comment="Supplier's invoice number")

	# Financials — all integer cents
	currency_code = Column(String(3), nullable=False)
	invoice_amount_cents = Column(Integer, nullable=False)
	early_payment_cents = Column(Integer, nullable=False, comment="Amount disbursed to supplier")
	discount_cents = Column(Integer, nullable=False, comment="Early payment fee (invoice - disbursed)")
	buyer_payment_due_date = Column(
		Date,
		nullable=False,
		comment="Original invoice maturity — when buyer repays the bank",
	)
	early_payment_date = Column(Date, nullable=False, comment="Date supplier received early payment")

	status = Column(
		String(20),
		nullable=False,
		default="FUNDED",
		comment="FUNDED | REPAID | OVERDUE | WRITTEN_OFF",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	# No updated_at — immutable record
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	program: SupplyChainFinanceProgram = relationship(
		"SupplyChainFinanceProgram",
		back_populates="receivables",
		lazy="select",
	)
	supplier = relationship("Party", foreign_keys=[supplier_id], lazy="select")

	def __repr__(self) -> str:
		return (
			f"<SCFReceivable {self.receivable_number!r} "
			f"invoice={self.invoice_reference!r} status={self.status!r} "
			f"early_payment={self.early_payment_cents}>"
		)


SCFReceivable._register_immutability()


# ---------------------------------------------------------------------------
# GLJournal / GLLine — enforced double-entry (CRITICAL gap 1)
# ---------------------------------------------------------------------------

class GLLine(Model):
	"""Single debit or credit line within a GL journal.

	Invariant: sum(debit_cents) == sum(credit_cents) across all lines for a journal.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_gl_line"
	__table_args__ = (
		Index("ix_tf_gl_line_journal", "journal_id"),
		Index("ix_tf_gl_line_account", "account_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	journal_id = Column(
		UUID(as_uuid=False),
		ForeignKey("tf_gl_journal.id", ondelete="CASCADE"),
		nullable=False,
	)
	account_code = Column(String(50), nullable=False)
	debit_cents = Column(Integer, nullable=False, default=0, server_default="0")
	credit_cents = Column(Integer, nullable=False, default=0, server_default="0")
	cost_centre = Column(String(50), nullable=True)
	narrative = Column(String(255), nullable=True)
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


class GLJournal(ImmutableRecordMixin, Model):
	"""Balanced double-entry GL journal header.

	Immutable once posted: reverse via a reversing journal with is_reversal=True.
	Enforced invariant: sum(lines.debit_cents) == sum(lines.credit_cents).
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_gl_journal"
	__table_args__ = (
		Index("ix_tf_gl_journal_instrument", "instrument_id", "instrument_type"),
		Index("ix_tf_gl_journal_tenant_date", "tenant_id", "posted_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	# What business event triggered this journal
	instrument_id = Column(UUID(as_uuid=False), nullable=True, index=True,
		comment="FK to the trade instrument (LC, BG, DC, SCF) that triggered posting")
	instrument_type = Column(String(30), nullable=True,
		comment="LetterOfCredit | BankGuarantee | DocumentaryCollection | SCFReceivable")
	event_type = Column(String(80), nullable=False,
		comment="tf.lc.issued | tf.lc.settled | tf.guarantee.claimed etc.")
	narrative = Column(String(255), nullable=True)

	# Reversal linkage
	is_reversal = Column(Boolean, nullable=False, default=False, server_default="false")
	reversed_journal_id = Column(
		UUID(as_uuid=False),
		ForeignKey("tf_gl_journal.id", ondelete="SET NULL"),
		nullable=True,
		comment="Points to the original journal this entry reverses",
	)
	reversal_flag = Column(String(20), nullable=True,
		comment="REVERSAL | ORIGINAL — set on both sides of a reversal pair")
	reversal_reason = Column(String(255), nullable=True)
	reversed_by = Column(String(100), nullable=True)

	# Totals (denormalised for fast validation)
	total_debit_cents = Column(Integer, nullable=False, default=0, server_default="0")
	total_credit_cents = Column(Integer, nullable=False, default=0, server_default="0")

	posted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
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

	lines: list[GLLine] = relationship(
		"GLLine",
		backref="journal",
		cascade="all, delete-orphan",
		lazy="select",
		foreign_keys=[GLLine.journal_id],
	)


GLJournal._register_immutability()


# ---------------------------------------------------------------------------
# TariffSchedule / TariffTier — configurable fee engine (CRITICAL gap 2)
# ---------------------------------------------------------------------------

class TariffSchedule(Model):
	"""Product-level fee tariff configurable by operations without a code deploy.

	basis:
	  FLAT          — fixed amount in min_cents
	  PCT_NOTIONAL  — rate_bps × notional / 10000
	  PCT_DRAWN     — rate_bps × drawn amount / 10000
	  TIERED        — look up TariffTier rows by amount range
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_tariff_schedule"
	__table_args__ = (
		UniqueConstraint("product_type", "fee_code", "tenant_id", "effective_date",
			name="uq_tf_tariff_product_fee_tenant_date"),
		Index("ix_tf_tariff_product", "product_type", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
		server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(String(64), nullable=False, index=True)

	product_type = Column(String(10), nullable=False,
		comment="LC | BG | DC | SCF")
	fee_code = Column(String(40), nullable=False,
		comment="OPENING_COMMISSION | AMENDMENT_FEE | SWIFT_CHARGES | CONFIRMATION_FEE | etc.")
	basis = Column(String(20), nullable=False, default="PCT_NOTIONAL",
		comment="FLAT | PCT_NOTIONAL | PCT_DRAWN | TIERED")

	rate_bps = Column(Integer, nullable=False, default=0,
		comment="Rate in basis points (1 bps = 0.01%). E.g. 50 bps = 0.5%")
	min_cents = Column(Integer, nullable=False, default=0,
		comment="Minimum fee in minor currency units (floor)")
	max_cents = Column(Integer, nullable=True,
		comment="Maximum fee cap in minor currency units (NULL = no cap)")
	currency = Column(String(3), nullable=False, default="KES")

	effective_date = Column(Date, nullable=False,
		comment="Date from which this schedule is effective (inclusive)")
	expiry_date = Column(Date, nullable=True,
		comment="Last date this schedule is valid (NULL = open-ended)")

	active = Column(Boolean, nullable=False, default=True, server_default="true")

	created_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	tiers: list[TariffTier] = relationship(
		"TariffTier", back_populates="schedule",
		cascade="all, delete-orphan", lazy="select",
	)


class TariffTier(Model):
	"""Tiered rate row under a TariffSchedule with basis=TIERED."""

	__allow_unmapped__ = True
	__tablename__ = "tf_tariff_tier"
	__table_args__ = (
		Index("ix_tf_tariff_tier_schedule", "schedule_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
		server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(String(64), nullable=False, index=True)

	schedule_id = Column(
		UUID(as_uuid=False),
		ForeignKey("tf_tariff_schedule.id", ondelete="CASCADE"),
		nullable=False,
	)
	lower_bound_cents = Column(Integer, nullable=False,
		comment="Lower bound (inclusive) of notional range for this tier")
	upper_bound_cents = Column(Integer, nullable=True,
		comment="Upper bound (exclusive) of notional range (NULL = unbounded)")
	rate_bps = Column(Integer, nullable=False,
		comment="Rate in basis points to apply for this tier")

	created_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	schedule: TariffSchedule = relationship("TariffSchedule", back_populates="tiers")


# ---------------------------------------------------------------------------
# OutboxEvent — transactional outbox for event durability (CRITICAL gap 3)
# ---------------------------------------------------------------------------

class OutboxEvent(Model):
	"""Transactional outbox for at-least-once event delivery.

	Persisted in the same DB transaction as the business mutation.
	OutboxRelay polls PENDING rows, publishes to broker, marks DELIVERED after ACK.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_outbox_event"
	__table_args__ = (
		Index("ix_tf_outbox_status_created", "status", "created_at"),
		Index("ix_tf_outbox_aggregate", "aggregate_type", "aggregate_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
		server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(String(64), nullable=False, index=True)

	aggregate_type = Column(String(60), nullable=False)
	aggregate_id = Column(String(64), nullable=False)
	event_type = Column(String(100), nullable=False)
	payload_json = Column(JSONB, nullable=False, default=dict)

	status = Column(String(20), nullable=False, default="PENDING", server_default="'PENDING'",
		comment="PENDING | DELIVERED | DEAD")
	retry_count = Column(Integer, nullable=False, default=0, server_default="0")
	last_error = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	delivered_at = Column(DateTime(timezone=True), nullable=True)

	def __repr__(self) -> str:
		return (
			f"<OutboxEvent {self.event_type!r} aggregate={self.aggregate_type}/{self.aggregate_id} "
			f"status={self.status!r} retry={self.retry_count}>"
		)


# ---------------------------------------------------------------------------
# TradeLimit / LimitUtilisation — limit management (CRITICAL gap 4)
# ---------------------------------------------------------------------------

class TradeLimit(Model):
	"""Credit/country/bank/product limit for trade finance exposure control.

	utilised_cents is maintained by check_and_reserve_limit() and updated
	atomically on each reservation or release.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_trade_limit"
	__table_args__ = (
		Index("ix_tf_limit_customer", "customer_id", "tenant_id"),
		Index("ix_tf_limit_type", "limit_type", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
		server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(String(64), nullable=False, index=True)

	customer_id = Column(UUID(as_uuid=False), ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False)
	limit_type = Column(String(20), nullable=False,
		comment="CUSTOMER | COUNTRY | BANK | PRODUCT")
	# For COUNTRY limits: ISO2 code stored in reference_code
	# For BANK limits: BIC stored in reference_code
	# For PRODUCT limits: product code stored in reference_code
	reference_code = Column(String(20), nullable=True,
		comment="Scope qualifier: country ISO2, BIC, or product code depending on limit_type")

	currency = Column(String(3), nullable=False, default="USD")
	limit_cents = Column(Integer, nullable=False, comment="Approved credit limit in minor units")
	utilised_cents = Column(Integer, nullable=False, default=0, server_default="0",
		comment="Currently reserved amount — updated atomically")

	expiry_date = Column(Date, nullable=True)
	active = Column(Boolean, nullable=False, default=True, server_default="true")

	created_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	utilisations: list[LimitUtilisation] = relationship(
		"LimitUtilisation", back_populates="limit",
		cascade="all, delete-orphan", lazy="select",
	)

	@property
	def available_cents(self) -> int:
		return max(0, self.limit_cents - self.utilised_cents)

	def __repr__(self) -> str:
		return (
			f"<TradeLimit type={self.limit_type!r} customer={self.customer_id} "
			f"limit={self.limit_cents} utilised={self.utilised_cents}>"
		)


class LimitUtilisation(Model):
	"""Per-instrument limit reservation record.

	One row per instrument that has reserved capacity against a TradeLimit.
	Release sets release_date; the amount is subtracted from TradeLimit.utilised_cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_limit_utilisation"
	__table_args__ = (
		Index("ix_tf_limit_util_limit", "limit_id"),
		Index("ix_tf_limit_util_instrument", "instrument_id", "instrument_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
		server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(String(64), nullable=False, index=True)

	limit_id = Column(UUID(as_uuid=False), ForeignKey("tf_trade_limit.id", ondelete="RESTRICT"),
		nullable=False)
	instrument_id = Column(UUID(as_uuid=False), nullable=False)
	instrument_type = Column(String(30), nullable=False)
	utilised_cents = Column(Integer, nullable=False)
	effective_date = Column(Date, nullable=False)
	release_date = Column(Date, nullable=True,
		comment="Populated when the instrument expires or is cancelled")

	created_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	limit: TradeLimit = relationship("TradeLimit", back_populates="utilisations")


# ---------------------------------------------------------------------------
# TradeAuditEntry — structured audit trail (HIGH gap 5)
# ---------------------------------------------------------------------------

class TradeAuditEntry(Model):
	"""Event-sourced audit log: who changed what field, from/to what value, under which auth.

	Every state transition and field mutation writes one row.
	Never updated — append-only.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_audit_entry"
	__table_args__ = (
		Index("ix_tf_audit_instrument", "instrument_id", "timestamp"),
		Index("ix_tf_audit_tenant_ts", "tenant_id", "timestamp"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
		server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(String(64), nullable=False, index=True)

	instrument_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	instrument_type = Column(String(30), nullable=False)
	event_type = Column(String(80), nullable=False)
	changed_fields = Column(JSONB, nullable=False, default=list,
		comment="List of field names that changed")
	old_values = Column(JSONB, nullable=False, default=dict)
	new_values = Column(JSONB, nullable=False, default=dict)

	performed_by = Column(String(100), nullable=False)
	authorised_by = Column(String(100), nullable=True)
	ip_address = Column(String(45), nullable=True)
	session_id = Column(String(100), nullable=True)

	timestamp = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	created_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<TradeAuditEntry {self.event_type!r} instrument={self.instrument_type}/{self.instrument_id} "
			f"by={self.performed_by!r} at={self.timestamp}>"
		)


# ---------------------------------------------------------------------------
# StandingInstruction — auto-renewal / auto-extend (HIGH gap 6)
# ---------------------------------------------------------------------------

class StandingInstruction(Model):
	"""Standing instruction to auto-renew, auto-extend, or auto-close an instrument.

	A daily batch job calls TradeFinanceService.process_standing_instructions()
	which checks trigger_days_before_expiry and fires the appropriate action.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_standing_instruction"
	__table_args__ = (
		Index("ix_tf_si_instrument", "instrument_id", "instrument_type"),
		Index("ix_tf_si_active", "active", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
		server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(String(64), nullable=False, index=True)

	instrument_id = Column(UUID(as_uuid=False), nullable=False)
	instrument_type = Column(String(30), nullable=False,
		comment="LetterOfCredit | BankGuarantee")
	action = Column(String(20), nullable=False,
		comment="AUTO_RENEW | AUTO_EXTEND | AUTO_CLOSE")
	trigger_days_before_expiry = Column(Integer, nullable=False, default=7,
		comment="Days before expiry_date to trigger the action")
	renewal_period_days = Column(Integer, nullable=False, default=365,
		comment="For AUTO_RENEW / AUTO_EXTEND: how many days to add")
	max_renewals = Column(Integer, nullable=False, default=3)
	renewals_completed = Column(Integer, nullable=False, default=0, server_default="0")
	active = Column(Boolean, nullable=False, default=True, server_default="true")

	created_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<StandingInstruction action={self.action!r} instrument={self.instrument_type}/{self.instrument_id} "
			f"active={self.active} renewals={self.renewals_completed}/{self.max_renewals}>"
		)


# ---------------------------------------------------------------------------
# PresentationDiscrepancy — structured discrepancy lifecycle (HIGH gap)
# ---------------------------------------------------------------------------

class PresentationDiscrepancy(Model):
	"""Per-discrepancy lifecycle record for LC presentations.

	Tracks each discrepancy from raising through waiver/correction/uphold.
	accept_or_reject_presentation requires all OPEN items resolved before acceptance.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tf_presentation_discrepancy"
	__table_args__ = (
		Index("ix_tf_pd_presentation", "presentation_id"),
		Index("ix_tf_pd_status", "status", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
		server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(String(64), nullable=False, index=True)

	presentation_id = Column(
		UUID(as_uuid=False),
		ForeignKey("tf_lc_presentation.id", ondelete="CASCADE"),
		nullable=False,
	)
	discrepancy_code = Column(String(40), nullable=False,
		comment="Short machine-readable code, e.g. AMOUNT_OVER_TOLERANCE, MISSING_BL")
	description = Column(Text, nullable=False)
	status = Column(String(20), nullable=False, default="OPEN", server_default="'OPEN'",
		comment="OPEN | WAIVED | CORRECTED | UPHELD")

	raised_by = Column(String(100), nullable=False)
	raised_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	resolved_by = Column(String(100), nullable=True)
	resolved_at = Column(DateTime(timezone=True), nullable=True)
	waiver_reference = Column(String(100), nullable=True,
		comment="Applicant waiver letter reference number")

	created_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<PresentationDiscrepancy {self.discrepancy_code!r} "
			f"presentation={self.presentation_id} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# BatchResult — value object returned by batch processing methods (HIGH gap)
# ---------------------------------------------------------------------------

@dataclass
class BatchResult:
	"""Return value for process_maturities() and process_standing_instructions()."""
	processed: int = 0
	failed: list[str] = field(default_factory=list)
	total_margin_released_cents: int = 0
	details: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LetterOfCredit",
	"LCPresentation",
	"BankGuarantee",
	"DocumentaryCollection",
	"SupplyChainFinanceProgram",
	"SCFReceivable",
	"GLLine",
	"GLJournal",
	"TariffSchedule",
	"TariffTier",
	"OutboxEvent",
	"TradeLimit",
	"LimitUtilisation",
	"TradeAuditEntry",
	"StandingInstruction",
	"PresentationDiscrepancy",
	"BatchResult",
]
