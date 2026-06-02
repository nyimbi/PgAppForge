"""
pgappforge/plugins/erp/finance/tax/models.py

Tax Management models.

Design rules:
  - All PKs: UUID v4 via gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All monetary amounts: INTEGER cents — never float
  - All models: tenant_id UUID NOT NULL + AuditMixin
  - Financial records: IMMUTABLE — INSERT correction entries only, NEVER UPDATE
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured metadata
  - Table name convention: erp_tx_<entity>

Tax types covered:
  VAT       — Value Added Tax (EU, UK, Africa)
  GST       — Goods and Services Tax (AU, NZ, India, Canada)
  SALES_TAX — US-style sales tax (no input credit mechanism)
  WHT       — Withholding Tax (deducted at source from payments)

Rates are NUMERIC(7,4) — e.g. 7.5000 = 7.5%. Never float.
All tax amounts are integer cents.
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
# TaxJurisdiction
# ---------------------------------------------------------------------------

class TaxJurisdiction(AuditMixin, Model):
	"""Tax jurisdiction — the geographic/legal authority that levies tax.

	Examples:
	  Nigeria Federal — VAT   (FIRS)
	  Lagos State     — WHT   (LIRS)
	  Germany         — VAT   (Bundeszentralamt für Steuern)
	  California      — SALES_TAX

	tax_type discriminates the regime — affects input/output credit mechanism.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tx_jurisdiction"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_erp_tx_jurisdiction_code"),
		Index("ix_erp_tx_jurisdiction_tenant", "tenant_id"),
		Index("ix_erp_tx_jurisdiction_country", "country_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(20), nullable=False, comment="e.g. NG-FIRS, DE-VAT, US-CA")
	name = Column(String(200), nullable=False)
	country_code = Column(
		String(2),
		ForeignKey("erp_country.iso_alpha2"),
		nullable=False,
		comment="ISO 3166-1 alpha-2",
	)
	region_code = Column(
		String(20),
		nullable=True,
		comment="State/province code where applicable",
	)
	tax_type = Column(
		String(15),
		nullable=False,
		comment="VAT | GST | SALES_TAX | WHT",
	)
	tax_authority_name = Column(
		String(200),
		nullable=False,
		comment="Name of the revenue authority e.g. FIRS, HMRC, IRS",
	)
	filing_frequency = Column(
		String(20),
		nullable=True,
		default="MONTHLY",
		comment="MONTHLY | QUARTERLY | ANNUALLY",
	)
	tax_authority_reference = Column(
		String(100),
		nullable=True,
		comment="Registered tax ID / VAT number with this authority",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	metadata_: dict[str, Any] = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
	)

	# Relationships
	tax_codes: list[TaxCode] = relationship(
		"TaxCode",
		back_populates="jurisdiction",
		lazy="select",
	)
	tax_returns: list[TaxReturn] = relationship(
		"TaxReturn",
		back_populates="jurisdiction",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<TaxJurisdiction {self.code!r} {self.tax_type!r} "
			f"authority={self.tax_authority_name!r}>"
		)


# ---------------------------------------------------------------------------
# TaxCode
# ---------------------------------------------------------------------------

class TaxCode(AuditMixin, Model):
	"""Tax rate code within a jurisdiction.

	A jurisdiction may have multiple rates at different points in time
	(effective_from/effective_to) and for different supply types
	(standard, zero-rated, exempt, reduced).

	rate is NUMERIC(7,4): 7.5000 = 7.5%, 0.0000 = zero-rated.

	For WHT codes, rate represents the withholding percentage deducted.
	For VAT/GST codes, is_input_tax=True means the tax is recoverable
	(credit against output tax liability).

	effective_to NULL = currently applicable.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tx_code"
	__table_args__ = (
		UniqueConstraint("jurisdiction_id", "code", "effective_from",
		                 name="uq_erp_tx_code_jurisdiction_code_from"),
		Index("ix_erp_tx_code_jurisdiction", "jurisdiction_id"),
		Index("ix_erp_tx_code_tenant", "tenant_id"),
		Index("ix_erp_tx_code_effective", "effective_from", "effective_to"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	jurisdiction_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tx_jurisdiction.id", ondelete="RESTRICT"),
		nullable=False,
	)
	code = Column(String(20), nullable=False, comment="e.g. STD, ZR, EX, RR, WHT15")
	description = Column(String(200), nullable=False)
	rate = Column(
		Numeric(7, 4),
		nullable=False,
		comment="Tax rate as percentage e.g. 7.5000 = 7.5%",
	)
	effective_from = Column(
		Date,
		nullable=False,
		comment="Date from which this rate applies",
	)
	effective_to = Column(
		Date,
		nullable=True,
		comment="NULL = currently applicable rate",
	)
	is_input_tax = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True = tax paid on purchases (claimable as input credit)",
	)
	is_output_tax = Column(
		Boolean,
		nullable=False,
		default=True,
		comment="True = tax charged on sales (output liability)",
	)
	is_zero_rated = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True = rate is 0% but supply is taxable (credit allowed)",
	)
	is_exempt = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True = supply is exempt (no tax, no input credit)",
	)
	is_reverse_charge = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True = recipient accounts for output and input tax (B2B cross-border)",
	)
	gl_account = Column(
		String(50),
		nullable=False,
		comment="GL account for this tax code (input or output depending on context)",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	metadata_: dict[str, Any] = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
	)

	# Relationships
	jurisdiction: TaxJurisdiction = relationship(
		"TaxJurisdiction",
		back_populates="tax_codes",
		lazy="select",
	)
	transactions: list[TaxTransaction] = relationship(
		"TaxTransaction",
		back_populates="tax_code",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<TaxCode {self.code!r} rate={self.rate!r} "
			f"from={self.effective_from!r} to={self.effective_to!r}>"
		)


# ---------------------------------------------------------------------------
# TaxReturn  (IMMUTABLE header — corrections via new rows)
# ---------------------------------------------------------------------------

class TaxReturn(AuditMixin, Model):
	"""Tax return (VAT return, GST return, etc.) for a filing period.

	IMMUTABLE after FILED status. To amend, create a new TaxReturn with
	amended figures and reference the original via amended_return_id.

	net_tax_cents = output_tax_cents - input_tax_cents
	Positive net = payment due to authority.
	Negative net = refund due to taxpayer.

	status lifecycle:
	  DRAFT → FILED → PAID (for net payable returns)
	  DRAFT → FILED → REFUND_CLAIMED (for net refund returns)
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tx_return"
	__table_args__ = (
		Index("ix_erp_tx_return_jurisdiction", "jurisdiction_id"),
		Index("ix_erp_tx_return_period", "period_start", "period_end"),
		Index("ix_erp_tx_return_tenant", "tenant_id"),
		Index("ix_erp_tx_return_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	jurisdiction_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tx_jurisdiction.id", ondelete="RESTRICT"),
		nullable=False,
	)
	period_start = Column(Date, nullable=False, comment="First day of the filing period")
	period_end = Column(Date, nullable=False, comment="Last day of the filing period")
	filing_date = Column(
		Date,
		nullable=True,
		comment="Date return was submitted to authority",
	)
	due_date = Column(Date, nullable=True, comment="Statutory filing deadline")
	output_tax_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total output VAT/GST charged on sales",
	)
	input_tax_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total input VAT/GST recoverable on purchases",
	)
	net_tax_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="output_tax - input_tax. Positive = payable; negative = refundable",
	)
	taxable_supplies_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total value of taxable supplies in the period",
	)
	exempt_supplies_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total value of exempt supplies in the period",
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | FILED | PAID | REFUND_CLAIMED",
	)
	reference_number = Column(
		String(100),
		nullable=True,
		comment="Authority-issued confirmation / submission reference",
	)
	payment_reference = Column(String(100), nullable=True)
	payment_date = Column(Date, nullable=True)
	amended_return_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tx_return.id", ondelete="SET NULL"),
		nullable=True,
		comment="FK to original return this amends",
	)
	notes = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
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

	# Relationships
	jurisdiction: TaxJurisdiction = relationship(
		"TaxJurisdiction",
		back_populates="tax_returns",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<TaxReturn jurisdiction={self.jurisdiction_id!r} "
			f"period={self.period_start!r}→{self.period_end!r} "
			f"net={self.net_tax_cents} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# TaxTransaction  (IMMUTABLE — append-only, never update)
# ---------------------------------------------------------------------------

class TaxTransaction(RulesMixin, Model):
	"""Individual tax line generated from a source document.

	CRITICAL: NEVER UPDATE. If a tax line was posted in error, insert a
	reversal (negative tax_amount_cents) referencing the same source document,
	then post the corrected line.

	source_document_type + source_document_id form a logical FK to any ERP
	document (sales invoice, purchase invoice, payment, etc.).

	is_recoverable:
	  True  = input tax that may be reclaimed as input credit (VAT/GST)
	  False = irrecoverable (non-business use, blocked input, exempt supply)
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tx_transaction"
	__table_args__ = (
		Index("ix_erp_tx_txn_source", "source_document_type", "source_document_id"),
		Index("ix_erp_tx_txn_code", "tax_code_id"),
		Index("ix_erp_tx_txn_posting_date", "posting_date"),
		Index("ix_erp_tx_txn_tenant", "tenant_id"),
		Index(
			"ix_erp_tx_txn_tenant_date",
			"tenant_id", "posting_date",
			postgresql_using="brin",
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
	tax_code_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tx_code.id", ondelete="RESTRICT"),
		nullable=False,
	)
	source_document_type = Column(
		String(100),
		nullable=False,
		comment="Model class of the originating document e.g. 'SalesInvoice'",
	)
	source_document_id = Column(
		String(64),
		nullable=False,
		comment="UUID of the originating document",
	)
	taxable_amount_cents = Column(
		Integer,
		nullable=False,
		comment="Net amount on which tax is calculated (before tax)",
	)
	tax_amount_cents = Column(
		Integer,
		nullable=False,
		comment="Tax amount = taxable_amount * rate / 100. Negative = reversal.",
	)
	is_recoverable = Column(
		Boolean,
		nullable=False,
		default=True,
		comment="True = input tax eligible for reclaim",
	)
	posting_date = Column(Date, nullable=False, comment="Tax point date")
	tax_period = Column(
		String(10),
		nullable=True,
		comment="Filing period this belongs to e.g. '2026-01'",
	)
	currency_code = Column(String(3), nullable=False, default="NGN")
	exchange_rate = Column(
		Numeric(20, 8),
		nullable=True,
		comment="Rate used to convert to reporting currency if multicurrency",
	)
	reporting_tax_amount_cents = Column(
		Integer,
		nullable=True,
		comment="Tax amount in reporting currency (after FX conversion)",
	)
	is_reversal = Column(Boolean, nullable=False, default=False)
	reversal_of_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tx_transaction.id", ondelete="SET NULL"),
		nullable=True,
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	tax_code: TaxCode = relationship(
		"TaxCode",
		back_populates="transactions",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<TaxTransaction code={self.tax_code_id!r} "
			f"src={self.source_document_type!r}/{self.source_document_id!r} "
			f"tax={self.tax_amount_cents} date={self.posting_date!r}>"
		)


__all__ = [
	"TaxJurisdiction",
	"TaxCode",
	"TaxReturn",
	"TaxTransaction",
]
