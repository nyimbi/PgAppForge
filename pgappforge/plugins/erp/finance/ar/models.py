"""
pgappforge/plugins/erp/finance/ar/models.py

SQLAlchemy models for the Accounts Receivable plugin.

Design rules enforced:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY — never Numeric/float
  - AuditMixin on all mutable entities
  - RulesMixin on ARCustomer, ARInvoice, ARPayment for rules engine integration
  - Financial records immutable: ARAllocation never updated, corrections via
    new rows or ARCreditNote
  - JSONB for semi-structured data (billing_address, invoice_ids)
  - lazy='select' throughout (SA 2.x: lazy='dynamic' removed)

Table name convention: ar_<entity>
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
# Enumerations (stored as VARCHAR with CHECK — no SQLAlchemy Enum to stay PG-only)
# ---------------------------------------------------------------------------

INVOICE_STATUS = ("DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "DISPUTED", "WRITTEN_OFF", "CANCELLED")
PAYMENT_METHOD = ("CHECK", "WIRE", "ACH", "CARD", "CASH", "DIRECT_DEBIT", "OTHER")
PAYMENT_STATUS = ("UNALLOCATED", "PARTIAL", "ALLOCATED", "RETURNED")
DUNNING_RUN_STATUS = ("PENDING", "RUNNING", "COMPLETED", "FAILED")
DUNNING_METHOD = ("EMAIL", "LETTER", "CALL", "LEGAL")
STATEMENT_FREQ = ("MONTHLY", "WEEKLY", "NONE")
CREDIT_NOTE_STATUS = ("OPEN", "PARTIAL", "APPLIED", "CANCELLED")


# ---------------------------------------------------------------------------
# ARCustomer
# ---------------------------------------------------------------------------

class ARCustomer(RulesMixin, AuditMixin, Model):
	"""AR customer profile — credit, dunning state, billing preferences.

	Links to erp_party via party_id for name/address/contact data.
	All financial amounts are integer cents.

	RulesMixin fires rules engine on create/update/delete via SA mapper events.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ar_customer"
	__table_args__ = (
		UniqueConstraint("tenant_id", "account_number", name="uq_ar_customer_tenant_account"),
		Index("ix_ar_customer_tenant", "tenant_id"),
		Index("ix_ar_customer_party", "party_id"),
		Index("ix_ar_customer_status", "status"),
		Index("ix_ar_customer_dunning", "dunning_level"),
		{"extend_existing": True},
	)

	# Rules Engine configuration
	_rules_mutable_fields: frozenset[str] = frozenset({
		"credit_limit_cents", "credit_used_cents", "credit_hold",
		"dunning_level", "dunning_blocked", "status", "payment_terms_days",
		"risk_score", "statement_frequency",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Link to Foundation Party for name/address/contact",
	)

	# Identity
	account_number = Column(
		String(20),
		nullable=False,
		comment="Human-readable customer account code; unique per tenant",
	)
	customer_type = Column(
		String(20),
		nullable=False,
		default="CUSTOMER",
		server_default="CUSTOMER",
		comment="CUSTOMER | PROSPECT | INTERNAL",
	)

	# Credit profile — integer cents
	credit_limit_cents = Column(
		Integer,
		nullable=True,
		comment="Maximum approved credit in cents; NULL = unlimited",
	)
	credit_used_cents = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Current outstanding balance in cents against credit_limit",
	)
	credit_hold = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
		comment="When true, new orders and invoices are blocked",
	)

	# Terms & dunning
	payment_terms_days = Column(
		Integer,
		nullable=False,
		default=30,
		server_default="30",
		comment="Net payment term in days (e.g. 30 = Net 30)",
	)
	dunning_level = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="0=none, 1=reminder, 2=warning, 3=final, 4=collections",
	)
	dunning_blocked = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
		comment="When true, customer is excluded from dunning runs",
	)

	# GL integration
	gl_reconciliation_account = Column(
		String(20),
		nullable=True,
		comment="GL AR control account for this customer segment",
	)

	# Statement preferences
	statement_frequency = Column(
		String(10),
		nullable=False,
		default="MONTHLY",
		server_default="MONTHLY",
		comment="MONTHLY | WEEKLY | NONE",
	)
	last_statement_date = Column(Date, nullable=True)

	# Risk scoring
	risk_score = Column(
		Numeric(5, 2),
		nullable=True,
		comment="0.00–100.00 risk score; computed by scoring engine",
	)

	# Lifecycle
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE | INACTIVE | SUSPENDED",
	)

	# Billing address snapshot (denormalised for invoice printing)
	billing_address: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
	)
	contact_email = Column(String(255), nullable=True)
	contact_phone = Column(String(50), nullable=True)

	# Timestamps (AuditMixin provides created_by/updated_by)
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
	invoices: list[ARInvoice] = relationship(
		"ARInvoice",
		back_populates="customer",
		cascade="all, delete-orphan",
		lazy="select",
	)
	payments: list[ARPayment] = relationship(
		"ARPayment",
		back_populates="customer",
		cascade="all, delete-orphan",
		lazy="select",
	)
	aging_snapshots: list[ARAging] = relationship(
		"ARAging",
		back_populates="customer",
		cascade="all, delete-orphan",
		lazy="select",
	)
	dunning_events: list[ARDunningEvent] = relationship(
		"ARDunningEvent",
		back_populates="customer",
		lazy="select",
	)
	credit_notes: list[ARCreditNote] = relationship(
		"ARCreditNote",
		back_populates="customer",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ARCustomer {self.account_number!r} id={self.id!r}>"


# ---------------------------------------------------------------------------
# ARInvoice
# ---------------------------------------------------------------------------

class ARInvoice(RulesMixin, AuditMixin, Model):
	"""AR invoice header.

	Immutable ledger rule: once ISSUED, amounts are never updated.
	Corrections are handled via ARCreditNote (credit note).

	balance_due_cents = total_cents - paid_cents - write_off_cents
	(maintained by ARService, not a generated column, for portability)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ar_invoice"
	__table_args__ = (
		UniqueConstraint("tenant_id", "invoice_number", name="uq_ar_invoice_tenant_number"),
		Index("ix_ar_invoice_tenant", "tenant_id"),
		Index("ix_ar_invoice_customer", "customer_id"),
		Index("ix_ar_invoice_status", "status"),
		Index("ix_ar_invoice_due_date", "due_date"),
		Index("ix_ar_invoice_billing_ref", "billing_reference_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"status", "paid_cents", "balance_due_cents", "write_off_cents",
		"dispute_reason", "dunning_level",
	})
	__rules_context_fields__: list[str] = [
		"customer.credit_hold",
		"customer.dunning_level",
		"customer.status",
	]

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	invoice_number = Column(String(50), nullable=False)
	customer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_customer.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Dates
	invoice_date = Column(Date, nullable=False, comment="Issue date; determines tax point")
	due_date = Column(Date, nullable=False, comment="Payment due date; drives aging and dunning")
	billing_period_start = Column(Date, nullable=True)
	billing_period_end = Column(Date, nullable=True)

	# Currency
	currency_code = Column(String(3), nullable=False, default="USD", comment="ISO 4217")
	exchange_rate = Column(
		Numeric(15, 6),
		nullable=False,
		default=1,
		server_default="1",
		comment="Rate to functional currency at invoice date",
	)

	# Amounts — integer cents
	subtotal_cents = Column(Integer, nullable=False, default=0, comment="Sum of line amounts before discount/tax")
	discount_cents = Column(Integer, nullable=False, default=0, server_default="0")
	tax_cents = Column(Integer, nullable=False, default=0, server_default="0")
	total_cents = Column(Integer, nullable=False, default=0, comment="subtotal - discount + tax")
	paid_cents = Column(Integer, nullable=False, default=0, server_default="0")
	balance_due_cents = Column(Integer, nullable=False, default=0, comment="total - paid - write_off")
	write_off_cents = Column(Integer, nullable=False, default=0, server_default="0")

	# Status
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT|ISSUED|PARTIAL|PAID|OVERDUE|DISPUTED|WRITTEN_OFF|CANCELLED",
	)

	# GL coding
	gl_revenue_account = Column(String(20), nullable=True, comment="Revenue GL account")
	gl_ar_account = Column(String(20), nullable=True, comment="AR control account")

	# Cross-references
	po_reference = Column(String(100), nullable=True, comment="Customer PO number")
	contract_reference = Column(String(100), nullable=True)
	billing_reference_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_invoice.id", ondelete="SET NULL"),
		nullable=True,
		comment="For credit/debit notes: FK to original invoice",
	)

	# Dunning state
	dunning_level = Column(Integer, nullable=False, default=0, server_default="0")
	last_dunning_date = Column(Date, nullable=True)

	# Dispute / write-off
	dispute_reason = Column(Text, nullable=True)
	write_off_date = Column(Date, nullable=True)
	write_off_reason = Column(Text, nullable=True)
	paid_date = Column(Date, nullable=True)

	# Delivery address (JSON snapshot at invoice time)
	delivery_address: dict[str, Any] = Column(JSONB, nullable=False, default=dict, server_default="{}")
	notes = Column(Text, nullable=True)

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
	customer: ARCustomer = relationship("ARCustomer", back_populates="invoices", lazy="select")
	lines: list[ARInvoiceLine] = relationship(
		"ARInvoiceLine",
		back_populates="invoice",
		cascade="all, delete-orphan",
		lazy="select",
	)
	allocations: list[ARAllocation] = relationship(
		"ARAllocation",
		back_populates="invoice",
		lazy="select",
	)
	billing_reference: ARInvoice = relationship(
		"ARInvoice",
		remote_side="ARInvoice.id",
		foreign_keys=[billing_reference_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ARInvoice {self.invoice_number!r} status={self.status!r} total={self.total_cents}¢>"


# ---------------------------------------------------------------------------
# ARInvoiceLine
# ---------------------------------------------------------------------------

class ARInvoiceLine(AuditMixin, Model):
	"""One line item on an AR invoice.

	line_amount_cents = round(quantity * unit_price_cents * (1 - discount_pct/100))
	Computed by ARService at line creation; stored for immutability.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ar_invoice_line"
	__table_args__ = (
		UniqueConstraint("invoice_id", "line_number", name="uq_ar_invoice_line_num"),
		Index("ix_ar_invoice_line_invoice", "invoice_id"),
		Index("ix_ar_invoice_line_tenant", "tenant_id"),
		Index("ix_ar_invoice_line_gl", "gl_revenue_account"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	invoice_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_invoice.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	line_number = Column(Integer, nullable=False, comment="1-based sequence within invoice")
	description = Column(Text, nullable=False)

	# Quantity and pricing
	quantity = Column(Numeric(15, 4), nullable=False, default=1)
	uom = Column(String(20), nullable=True, comment="Unit of measure: EA, HR, KG, etc.")
	unit_price_cents = Column(Integer, nullable=False, default=0)
	discount_pct = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
	line_amount_cents = Column(Integer, nullable=False, default=0, comment="After discount, before tax")

	# Tax
	tax_category = Column(String(20), nullable=True, comment="S=standard, Z=zero, E=exempt, AE=reverse charge")
	tax_rate = Column(Numeric(5, 2), nullable=False, default=0, server_default="0")
	tax_cents = Column(Integer, nullable=False, default=0, server_default="0")

	# GL coding
	gl_revenue_account = Column(String(20), nullable=True)
	cost_center = Column(String(20), nullable=True)
	project_code = Column(String(50), nullable=True)
	department = Column(String(50), nullable=True)
	product_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	product_sku = Column(String(100), nullable=True)
	delivery_date = Column(Date, nullable=True)

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

	invoice: ARInvoice = relationship("ARInvoice", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ARInvoiceLine invoice={self.invoice_id!r} line={self.line_number} "
			f"amount={self.line_amount_cents}¢>"
		)


# ---------------------------------------------------------------------------
# ARPayment
# ---------------------------------------------------------------------------

class ARPayment(RulesMixin, AuditMixin, Model):
	"""Cash receipt record — before allocation.

	status transitions: UNALLOCATED → PARTIAL → ALLOCATED | RETURNED.
	Immutable once ALLOCATED — create a reversal payment for corrections.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ar_payment"
	__table_args__ = (
		UniqueConstraint("tenant_id", "payment_number", name="uq_ar_payment_tenant_number"),
		Index("ix_ar_payment_tenant", "tenant_id"),
		Index("ix_ar_payment_customer", "customer_id"),
		Index("ix_ar_payment_status", "status"),
		Index("ix_ar_payment_date", "payment_date"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({"status"})

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	payment_number = Column(String(50), nullable=False)
	customer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_customer.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	payment_date = Column(Date, nullable=False)
	payment_method = Column(
		String(30),
		nullable=False,
		default="WIRE",
		comment="CHECK|WIRE|ACH|CARD|CASH|DIRECT_DEBIT|OTHER",
	)
	currency_code = Column(String(3), nullable=False, default="USD")
	amount_cents = Column(Integer, nullable=False, comment="Gross payment in cents")
	exchange_rate = Column(Numeric(15, 6), nullable=False, default=1, server_default="1")
	bank_reference = Column(String(100), nullable=True)
	bank_account_iban = Column(String(34), nullable=True)
	bank_bic = Column(String(11), nullable=True)
	remittance_info = Column(Text, nullable=True)
	deposited_date = Column(Date, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="UNALLOCATED",
		server_default="UNALLOCATED",
		comment="UNALLOCATED|PARTIAL|ALLOCATED|RETURNED",
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

	customer: ARCustomer = relationship("ARCustomer", back_populates="payments", lazy="select")
	allocations: list[ARAllocation] = relationship(
		"ARAllocation",
		back_populates="payment",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ARPayment {self.payment_number!r} amount={self.amount_cents}¢ "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ARAllocation  (append-only — NEVER UPDATE)
# ---------------------------------------------------------------------------

class ARAllocation(Model):
	"""Payment-to-invoice allocation junction.

	CRITICAL: Immutable ledger — NEVER UPDATE rows.
	To reverse an allocation, create a new ARAllocation row with negative
	allocated_cents and a compensating ARPayment (reversal).

	discount_taken_cents: early-payment discount taken at allocation time.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ar_allocation"
	__table_args__ = (
		Index("ix_ar_allocation_payment", "payment_id"),
		Index("ix_ar_allocation_invoice", "invoice_id"),
		Index("ix_ar_allocation_tenant", "tenant_id"),
		Index("ix_ar_allocation_date", "allocation_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	payment_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_payment.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	invoice_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_invoice.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	allocation_date = Column(Date, nullable=False)
	allocated_cents = Column(Integer, nullable=False, comment="Amount applied; negative for reversals")
	discount_taken_cents = Column(Integer, nullable=False, default=0, server_default="0")
	notes = Column(Text, nullable=True)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	# No updated_at — this table is append-only
	created_by = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)

	payment: ARPayment = relationship("ARPayment", back_populates="allocations", lazy="select")
	invoice: ARInvoice = relationship("ARInvoice", back_populates="allocations", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ARAllocation payment={self.payment_id!r} invoice={self.invoice_id!r} "
			f"amount={self.allocated_cents}¢>"
		)


# ---------------------------------------------------------------------------
# ARCreditNote
# ---------------------------------------------------------------------------

class ARCreditNote(AuditMixin, Model):
	"""Credit note against a customer.

	Can be linked to an original invoice (original_invoice_id) or standalone.
	applied_cents tracks how much has been used against invoices.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ar_credit_note"
	__table_args__ = (
		UniqueConstraint("tenant_id", "credit_note_number", name="uq_ar_credit_note_number"),
		Index("ix_ar_credit_note_tenant", "tenant_id"),
		Index("ix_ar_credit_note_customer", "customer_id"),
		Index("ix_ar_credit_note_original", "original_invoice_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	credit_note_number = Column(String(50), nullable=False)
	customer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_customer.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	original_invoice_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_invoice.id", ondelete="SET NULL"),
		nullable=True,
	)
	issue_date = Column(Date, nullable=False)
	reason = Column(Text, nullable=False)
	currency_code = Column(String(3), nullable=False, default="USD")
	total_cents = Column(Integer, nullable=False, default=0)
	applied_cents = Column(Integer, nullable=False, default=0, server_default="0")
	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		server_default="OPEN",
		comment="OPEN|PARTIAL|APPLIED|CANCELLED",
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

	customer: ARCustomer = relationship("ARCustomer", back_populates="credit_notes", lazy="select")

	def __repr__(self) -> str:
		return f"<ARCreditNote {self.credit_note_number!r} total={self.total_cents}¢ status={self.status!r}>"


# ---------------------------------------------------------------------------
# ARDunningRun
# ---------------------------------------------------------------------------

class ARDunningRun(AuditMixin, Model):
	"""Batch dunning execution record — one per dunning level per date."""

	__allow_unmapped__ = True
	__tablename__ = "ar_dunning_run"
	__table_args__ = (
		Index("ix_ar_dunning_run_tenant", "tenant_id"),
		Index("ix_ar_dunning_run_date_level", "run_date", "dunning_level"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	run_date = Column(Date, nullable=False)
	dunning_level = Column(Integer, nullable=False, comment="1=reminder, 2=warning, 3=final, 4=collections")
	batch_size = Column(Integer, nullable=False, default=0, server_default="0")
	emails_sent = Column(Integer, nullable=False, default=0, server_default="0")
	letters_sent = Column(Integer, nullable=False, default=0, server_default="0")
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		server_default="PENDING",
		comment="PENDING|RUNNING|COMPLETED|FAILED",
	)
	run_by = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)

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

	events: list[ARDunningEvent] = relationship(
		"ARDunningEvent",
		back_populates="dunning_run",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ARDunningRun {self.run_date!r} level={self.dunning_level} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ARDunningEvent
# ---------------------------------------------------------------------------

class ARDunningEvent(AuditMixin, Model):
	"""Per-customer outcome within a dunning run.

	invoice_ids is a JSONB array of invoice UUIDs covered by this communication.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ar_dunning_event"
	__table_args__ = (
		Index("ix_ar_dunning_event_run", "dunning_run_id"),
		Index("ix_ar_dunning_event_customer", "customer_id"),
		Index("ix_ar_dunning_event_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	dunning_run_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_dunning_run.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	customer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_customer.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	invoice_ids: list = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="Array of invoice UUIDs covered",
	)
	amount_overdue_cents = Column(Integer, nullable=False, default=0)
	method = Column(
		String(20),
		nullable=False,
		default="EMAIL",
		comment="EMAIL|LETTER|CALL|LEGAL",
	)
	sent_at = Column(DateTime(timezone=True), nullable=True)
	response = Column(Text, nullable=True)
	promise_to_pay_date = Column(Date, nullable=True)
	outcome = Column(
		String(50),
		nullable=True,
		comment="DELIVERED|BOUNCED|FAILED|PROMISE_RECEIVED|DISPUTE_RAISED",
	)
	contact_email = Column(String(255), nullable=True)

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

	dunning_run: ARDunningRun = relationship("ARDunningRun", back_populates="events", lazy="select")
	customer: ARCustomer = relationship("ARCustomer", back_populates="dunning_events", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ARDunningEvent run={self.dunning_run_id!r} customer={self.customer_id!r} "
			f"method={self.method!r}>"
		)


# ---------------------------------------------------------------------------
# ARAging  (point-in-time snapshot — append-only by convention)
# ---------------------------------------------------------------------------

class ARAging(Model):
	"""Nightly aging bucket snapshot per customer.

	All amounts in integer cents.
	Computed by ARService.run_aging(); drives dashboards and dunning triggers
	without hitting transactional invoice tables.

	Append-only by convention: never update existing rows; insert new snapshots.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ar_aging"
	__table_args__ = (
		Index("ix_ar_aging_customer_date", "customer_id", "snapshot_date"),
		Index("ix_ar_aging_tenant_date", "tenant_id", "snapshot_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	customer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ar_customer.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	snapshot_date = Column(Date, nullable=False, index=True)
	currency_code = Column(String(3), nullable=False, default="USD")

	# Aging buckets — integer cents
	current_cents = Column(Integer, nullable=False, default=0, comment="Not yet due")
	days_1_30 = Column(Integer, nullable=False, default=0, comment="1–30 days overdue")
	days_31_60 = Column(Integer, nullable=False, default=0, comment="31–60 days overdue")
	days_61_90 = Column(Integer, nullable=False, default=0, comment="61–90 days overdue")
	days_91_120 = Column(Integer, nullable=False, default=0, comment="91–120 days overdue")
	over_120 = Column(Integer, nullable=False, default=0, comment=">120 days overdue")
	total_outstanding_cents = Column(Integer, nullable=False, default=0, comment="Sum of all buckets")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	customer: ARCustomer = relationship("ARCustomer", back_populates="aging_snapshots", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ARAging customer={self.customer_id!r} date={self.snapshot_date!r} "
			f"total={self.total_outstanding_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ARCustomer",
	"ARInvoice",
	"ARInvoiceLine",
	"ARPayment",
	"ARAllocation",
	"ARCreditNote",
	"ARDunningRun",
	"ARDunningEvent",
	"ARAging",
]
