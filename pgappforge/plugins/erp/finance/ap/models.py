"""
pgappforge/plugins/erp/finance/ap/models.py

SQLAlchemy models for the Accounts Payable plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - Financial records (APInvoice, APPayment, APPaymentRun): NEVER UPDATE
    outstanding amounts directly — use correction entries / payment application
  - lazy='select' throughout (SA 2.x removed lazy='dynamic')
  - JSONB for semi-structured fields (bank_details, metadata)
  - Proper composite indexes for tenant + status hot paths

Table prefix: ap_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# APSupplier
# ---------------------------------------------------------------------------

class APSupplier(AuditMixin, Model):
	"""Supplier master record.

	Links to foundation.Party via party_id for shared master data (name,
	address, contacts).  AP-specific payment and tax fields live here.

	Bank IBAN/BIC drives ISO 20022 payment file generation.
	Dynamic discounting: if eligible, early_payment_discount_pct applies when
	payment is made within early_payment_days of the invoice date.

	IMMUTABLE LEDGER NOTE: do not delete rows; set approved_supplier=False
	and status='blocked' to block a supplier.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_supplier"
	__table_args__ = (
		Index("ix_ap_supplier_tenant", "tenant_id"),
		Index("ix_ap_supplier_party", "party_id"),
		Index("ix_ap_supplier_account", "account_number"),
		Index("ix_ap_supplier_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "account_number", name="uq_ap_supplier_tenant_account"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Link to foundation Party (not a DB FK to avoid cross-schema coupling)
	party_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to erp_party.id (soft — no DB constraint for cross-plugin safety)",
	)

	# Identity
	account_number = Column(String(20), nullable=False, comment="Internal supplier code; unique per tenant")
	name = Column(String(255), nullable=False, comment="Trading name; denormalized from Party for query convenience")
	supplier_type = Column(
		String(20),
		nullable=True,
		comment="GOODS | SERVICES | SUBCONTRACTOR | INTERCOMPANY | OTHER",
	)
	status = Column(String(20), nullable=False, default="active", comment="active | inactive | blocked | under_review")

	# Payment terms
	payment_terms_days = Column(Integer, nullable=False, default=30, comment="Net payment days e.g. 30 = Net 30")
	payment_method = Column(
		String(20),
		nullable=True,
		comment="WIRE | ACH | SEPA | CHECK | BACS",
	)
	currency_code = Column(String(3), nullable=False, default="USD", comment="ISO 4217 default invoice currency")

	# Banking
	bank_account_iban = Column(String(34), nullable=True, comment="ISO 13616 IBAN for electronic payment")
	bank_bic = Column(String(11), nullable=True, comment="ISO 9362 BIC/SWIFT code")
	bank_account_name = Column(String(255), nullable=True, comment="Account holder name as registered with bank")
	bank_details = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Additional bank fields: sort_code, routing_number, branch_code etc.",
	)

	# Tax & compliance
	tax_id = Column(String(50), nullable=True, comment="National tax/EIN identifier")
	vat_number = Column(String(50), nullable=True, comment="VAT registration number")
	w9_on_file = Column(Boolean, nullable=False, default=False, comment="US: W-9 received and filed")
	reporting_1099 = Column(Boolean, nullable=False, default=False, comment="US: subject to 1099-MISC reporting")
	gl_payable_account = Column(String(20), nullable=True, comment="Default AP control account in GL chart of accounts")

	# Vendor approval
	approved_supplier = Column(Boolean, nullable=False, default=True, comment="Passed vendor onboarding; eligible for POs")
	credit_rating = Column(String(10), nullable=True, comment="Internal credit rating e.g. A, B+, BB")

	# Dynamic discounting / early payment
	dynamic_discounting_eligible = Column(Boolean, nullable=False, default=False)
	early_payment_discount_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=0,
		comment="Discount percentage if paid within early_payment_days",
	)
	early_payment_days = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Days from invoice date within which discount applies",
	)

	# Contact (denormalized for AP clerks; canonical data stays in Party)
	contact_email = Column(String(255), nullable=True)
	contact_phone = Column(String(50), nullable=True)
	address = Column(JSONB, nullable=False, default=dict, comment="{line1,line2,city,state,postal_code,country}")

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
	purchase_orders: list[APPurchaseOrder] = relationship(
		"APPurchaseOrder", back_populates="supplier", lazy="select",
	)
	invoices: list[APInvoice] = relationship(
		"APInvoice", back_populates="supplier", lazy="select",
	)
	payments: list[APPayment] = relationship(
		"APPayment", back_populates="supplier", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<APSupplier {self.account_number!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# APPurchaseOrder
# ---------------------------------------------------------------------------

class APPurchaseOrder(AuditMixin, Model):
	"""Purchase order header.

	Tracks three-way match running totals (received_cents, invoiced_cents,
	paid_cents) as denormalized integers updated by service methods — avoids
	JOIN-heavy aggregation on hot list queries.

	Status machine:
	  DRAFT → PENDING_APPROVAL → APPROVED → SENT → PARTIAL →
	  RECEIVED → CLOSED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_purchase_order"
	__table_args__ = (
		Index("ix_ap_po_tenant", "tenant_id"),
		Index("ix_ap_po_supplier", "supplier_id"),
		Index("ix_ap_po_tenant_status", "tenant_id", "status"),
		Index("ix_ap_po_order_date", "order_date"),
		UniqueConstraint("tenant_id", "po_number", name="uq_ap_po_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	po_number = Column(String(50), nullable=False, comment="Purchase order number; unique per tenant")
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("ap_supplier.id"), nullable=False, index=True)
	requisitioner_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — raised by")
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — approved by")
	approval_date = Column(DateTime(timezone=True), nullable=True)

	order_date = Column(Date, nullable=False)
	delivery_date = Column(Date, nullable=True, comment="Expected delivery date")
	currency_code = Column(String(3), nullable=False, default="USD")

	# Committed amounts — integer cents
	subtotal_cents = Column(Integer, nullable=False, default=0)
	tax_cents = Column(Integer, nullable=False, default=0)
	total_cents = Column(Integer, nullable=False, default=0)

	# Running match totals — updated by service layer (integer cents)
	received_cents = Column(Integer, nullable=False, default=0, comment="Sum of GRN accepted values")
	invoiced_cents = Column(Integer, nullable=False, default=0, comment="Sum of matched invoice totals")
	paid_cents = Column(Integer, nullable=False, default=0, comment="Sum of payments applied")

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|PENDING_APPROVAL|APPROVED|SENT|PARTIAL|RECEIVED|CLOSED|CANCELLED",
	)

	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	supplier: APSupplier = relationship("APSupplier", back_populates="purchase_orders", lazy="select")
	lines: list[APPOLine] = relationship("APPOLine", back_populates="purchase_order", cascade="all, delete-orphan", lazy="select")
	goods_receipts: list[APGoodsReceipt] = relationship("APGoodsReceipt", back_populates="purchase_order", lazy="select")
	invoices: list[APInvoice] = relationship("APInvoice", back_populates="purchase_order", lazy="select")

	def __repr__(self) -> str:
		return f"<APPurchaseOrder {self.po_number!r} status={self.status!r} total={self.total_cents}¢>"


# ---------------------------------------------------------------------------
# APPOLine
# ---------------------------------------------------------------------------

class APPOLine(AuditMixin, Model):
	"""Purchase order line item.

	quantity_received and quantity_invoiced are updated by GRN posting and
	invoice matching respectively.  Both are NUMERIC(15,4) to support non-integer
	UOMs (e.g. 1.5 kg, 0.75 hr).

	unit_cost_cents and line_amount_cents are integer cents — the service layer
	multiplies Decimal quantity × Decimal unit cost then rounds half-up to int.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_po_line"
	__table_args__ = (
		Index("ix_ap_po_line_po", "po_id"),
		Index("ix_ap_po_line_tenant", "tenant_id"),
		UniqueConstraint("po_id", "line_number", name="uq_ap_po_line_po_seq"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	po_id = Column(UUID(as_uuid=False), ForeignKey("ap_purchase_order.id", ondelete="CASCADE"), nullable=False, index=True)
	line_number = Column(Integer, nullable=False)
	description = Column(Text, nullable=False)
	quantity = Column(Numeric(15, 4), nullable=False)
	uom = Column(String(20), nullable=True, comment="Unit of measure: EA, KG, HR, L, M2…")
	unit_cost_cents = Column(Integer, nullable=False, comment="Agreed unit cost in cents")
	line_amount_cents = Column(Integer, nullable=False, comment="quantity × unit_cost_cents (rounded)")

	quantity_received = Column(Numeric(15, 4), nullable=False, default=0, comment="Updated by GRN posting")
	quantity_invoiced = Column(Numeric(15, 4), nullable=False, default=0, comment="Updated by invoice matching")

	gl_expense_account = Column(String(20), nullable=True, comment="GL expense account code")
	cost_center = Column(String(20), nullable=True)
	project_code = Column(String(50), nullable=True)
	product_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to item/product master (app-managed)")
	product_sku = Column(String(100), nullable=True)
	status = Column(String(20), nullable=False, default="OPEN", comment="OPEN|PARTIAL|RECEIVED|CLOSED|CANCELLED")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	purchase_order: APPurchaseOrder = relationship("APPurchaseOrder", back_populates="lines", lazy="select")
	grn_lines: list[APGRNLine] = relationship("APGRNLine", back_populates="po_line", lazy="select")
	invoice_lines: list[APInvoiceLine] = relationship("APInvoiceLine", back_populates="po_line", lazy="select")

	def __repr__(self) -> str:
		return f"<APPOLine po={self.po_id!r} line={self.line_number} amt={self.line_amount_cents}¢>"


# ---------------------------------------------------------------------------
# APGoodsReceipt  (GRN header)
# ---------------------------------------------------------------------------

class APGoodsReceipt(AuditMixin, Model):
	"""Goods receipt note (GRN) header.

	DRAFT → CONFIRMED → QUALITY_HOLD (optional) → POSTED

	Posting a CONFIRMED GRN updates APPOLine.quantity_received and
	APPurchaseOrder.received_cents via APService.post_grn().
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_goods_receipt"
	__table_args__ = (
		Index("ix_ap_grn_tenant", "tenant_id"),
		Index("ix_ap_grn_po", "po_id"),
		Index("ix_ap_grn_supplier", "supplier_id"),
		UniqueConstraint("tenant_id", "grn_number", name="uq_ap_grn_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	grn_number = Column(String(50), nullable=False, comment="Goods receipt note number; unique per tenant")
	po_id = Column(UUID(as_uuid=False), ForeignKey("ap_purchase_order.id"), nullable=True, index=True, comment="NULL = non-PO receipt")
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("ap_supplier.id"), nullable=False, index=True)
	received_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	received_date = Column(Date, nullable=False)
	warehouse_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to warehouse/location master (app-managed)")
	status = Column(String(20), nullable=False, default="DRAFT", comment="DRAFT|CONFIRMED|QUALITY_HOLD|POSTED")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	purchase_order: APPurchaseOrder | None = relationship("APPurchaseOrder", back_populates="goods_receipts", lazy="select")
	supplier: APSupplier = relationship("APSupplier", lazy="select")
	lines: list[APGRNLine] = relationship("APGRNLine", back_populates="goods_receipt", cascade="all, delete-orphan", lazy="select")
	invoices: list[APInvoice] = relationship("APInvoice", back_populates="goods_receipt", lazy="select")

	def __repr__(self) -> str:
		return f"<APGoodsReceipt {self.grn_number!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# APGRNLine
# ---------------------------------------------------------------------------

class APGRNLine(AuditMixin, Model):
	"""Goods receipt line.

	quantity_accepted + quantity_rejected == quantity_received.
	Rejected quantities trigger a supplier debit note workflow upstream.
	unit_cost_cents is locked at GRN time for inventory valuation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_grn_line"
	__table_args__ = (
		Index("ix_ap_grn_line_grn", "grn_id"),
		Index("ix_ap_grn_line_po_line", "po_line_id"),
		Index("ix_ap_grn_line_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	grn_id = Column(UUID(as_uuid=False), ForeignKey("ap_goods_receipt.id", ondelete="CASCADE"), nullable=False, index=True)
	po_line_id = Column(UUID(as_uuid=False), ForeignKey("ap_po_line.id"), nullable=True, index=True, comment="NULL = non-PO receipt line")
	description = Column(Text, nullable=True, comment="Defaults from PO line if linked")
	quantity_received = Column(Numeric(15, 4), nullable=False)
	quantity_accepted = Column(Numeric(15, 4), nullable=True, comment="Accepted into stock")
	quantity_rejected = Column(Numeric(15, 4), nullable=False, default=0)
	rejection_reason = Column(Text, nullable=True, comment="Required when quantity_rejected > 0")
	unit_cost_cents = Column(Integer, nullable=True, comment="Locked unit cost at receipt for inventory valuation")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	goods_receipt: APGoodsReceipt = relationship("APGoodsReceipt", back_populates="lines", lazy="select")
	po_line: APPOLine | None = relationship("APPOLine", back_populates="grn_lines", lazy="select")
	invoice_lines: list[APInvoiceLine] = relationship("APInvoiceLine", back_populates="grn_line", lazy="select")

	def __repr__(self) -> str:
		return f"<APGRNLine grn={self.grn_id!r} accepted={self.quantity_accepted} rejected={self.quantity_rejected}>"


# ---------------------------------------------------------------------------
# APPaymentRun  (defined before APInvoice to avoid forward-ref issues)
# ---------------------------------------------------------------------------

class APPaymentRun(AuditMixin, Model):
	"""Payment batch header.

	Aggregates multiple supplier payments into a single bank file (ISO 20022
	pain.001.001.03 for SEPA credit transfers; NACHA for ACH).

	iso20022_xml stores the generated XML payload — TEXT column to avoid
	binary encoding issues; callers write to file/object-store and blank this
	after transmission.

	IMMUTABLE: once status=TRANSMITTED, do not mutate.  To cancel, set
	status=FAILED and issue recall payments.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_payment_run"
	__table_args__ = (
		Index("ix_ap_pmtrun_tenant", "tenant_id"),
		Index("ix_ap_pmtrun_tenant_status", "tenant_id", "status"),
		Index("ix_ap_pmtrun_run_date", "run_date"),
		UniqueConstraint("tenant_id", "run_number", name="uq_ap_pmtrun_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	run_number = Column(String(50), nullable=False, comment="Payment run reference; unique per tenant")
	run_date = Column(Date, nullable=False, comment="Date the run was initiated")
	value_date = Column(Date, nullable=False, comment="Requested bank settlement date")
	bank_account = Column(String(50), nullable=True, comment="Company bank account IBAN")
	bic = Column(String(11), nullable=True, comment="Company bank BIC")
	currency_code = Column(String(3), nullable=False, default="USD")

	# Aggregate counters — integer
	total_payments = Column(Integer, nullable=False, default=0, comment="Number of individual payments")
	total_amount_cents = Column(Integer, nullable=False, default=0, comment="Sum of all ap_payment.amount_cents")

	payment_file_ref = Column(String(200), nullable=True, comment="Bank file name or object-store key")
	iso20022_xml = Column(Text, nullable=True, comment="Generated ISO 20022 XML; blank after transmission")
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|APPROVED|TRANSMITTED|CONFIRMED|FAILED",
	)
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — treasury approver")
	approved_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	payments: list[APPayment] = relationship("APPayment", back_populates="payment_run", lazy="select")
	invoices: list[APInvoice] = relationship("APInvoice", back_populates="payment_run", lazy="select")

	def __repr__(self) -> str:
		return f"<APPaymentRun {self.run_number!r} status={self.status!r} total={self.total_amount_cents}¢>"


# ---------------------------------------------------------------------------
# APInvoice
# ---------------------------------------------------------------------------

class APInvoice(AuditMixin, Model):
	"""Supplier invoice header.

	match_status drives the 2-way / 3-way matching workflow.
	approval_status drives the multi-level approval chain.

	IMMUTABLE LEDGER: paid_cents is incremented by payment application; it is
	never decremented.  To reverse a payment, create an APPayment with negative
	amount_cents and post a correction GL entry.

	exchange_rate: rate at invoice date, stored as Numeric(15,6) — convert
	to Decimal before arithmetic, never use Python float.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_invoice"
	__table_args__ = (
		Index("ix_ap_inv_tenant", "tenant_id"),
		Index("ix_ap_inv_supplier", "supplier_id"),
		Index("ix_ap_inv_po", "po_id"),
		Index("ix_ap_inv_grn", "grn_id"),
		Index("ix_ap_inv_payment_run", "payment_run_id"),
		Index("ix_ap_inv_tenant_status", "tenant_id", "status"),
		Index("ix_ap_inv_due_date", "due_date"),
		UniqueConstraint("tenant_id", "supplier_id", "invoice_number_supplier", name="uq_ap_inv_supplier_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Supplier's own invoice number (unique per supplier per tenant)
	invoice_number_supplier = Column(String(100), nullable=False, comment="Supplier's invoice number")
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("ap_supplier.id"), nullable=False, index=True)
	po_id = Column(UUID(as_uuid=False), ForeignKey("ap_purchase_order.id"), nullable=True, index=True)
	grn_id = Column(UUID(as_uuid=False), ForeignKey("ap_goods_receipt.id"), nullable=True, index=True)
	payment_run_id = Column(UUID(as_uuid=False), ForeignKey("ap_payment_run.id"), nullable=True, index=True)

	invoice_date = Column(Date, nullable=False, comment="Tax point / invoice date")
	due_date = Column(Date, nullable=False, comment="Derived from supplier payment terms")
	currency_code = Column(String(3), nullable=False, default="USD")
	exchange_rate = Column(Numeric(15, 6), nullable=False, default=1, comment="Rate at invoice date; convert to Decimal before use")

	# Amounts — integer cents (NEVER float)
	subtotal_cents = Column(Integer, nullable=False, default=0)
	discount_cents = Column(Integer, nullable=False, default=0, comment="Header-level early-payment discount")
	tax_cents = Column(Integer, nullable=False, default=0)
	total_cents = Column(Integer, nullable=False, default=0, comment="subtotal - discount + tax")
	paid_cents = Column(Integer, nullable=False, default=0, comment="Cumulative payments applied; immutable-ledger, never decrement directly")
	early_payment_discount_taken_cents = Column(Integer, nullable=False, default=0)

	# GL coding
	gl_payable_account = Column(String(20), nullable=True, comment="AP control account; defaults from supplier")

	# Match / approval state
	match_status = Column(
		String(20),
		nullable=False,
		default="UNMATCHED",
		comment="UNMATCHED|2WAY|3WAY|EXCEPTION",
	)
	approval_status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING|APPROVED|REJECTED",
	)
	status = Column(
		String(20),
		nullable=False,
		default="RECEIVED",
		comment="RECEIVED|MATCHING|APPROVED|PAYMENT_SCHEDULED|PAID|DISPUTED|CANCELLED",
	)

	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	supplier: APSupplier = relationship("APSupplier", back_populates="invoices", lazy="select")
	purchase_order: APPurchaseOrder | None = relationship("APPurchaseOrder", back_populates="invoices", lazy="select")
	goods_receipt: APGoodsReceipt | None = relationship("APGoodsReceipt", back_populates="invoices", lazy="select")
	payment_run: APPaymentRun | None = relationship("APPaymentRun", back_populates="invoices", lazy="select")
	lines: list[APInvoiceLine] = relationship("APInvoiceLine", back_populates="invoice", cascade="all, delete-orphan", lazy="select")
	approval_workflows: list[APApprovalWorkflow] = relationship("APApprovalWorkflow", back_populates="invoice", cascade="all, delete-orphan", lazy="select")
	payments: list[APPayment] = relationship("APPayment", back_populates="invoice", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<APInvoice {self.invoice_number_supplier!r} "
			f"total={self.total_cents}¢ match={self.match_status!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# APInvoiceLine
# ---------------------------------------------------------------------------

class APInvoiceLine(AuditMixin, Model):
	"""Supplier invoice line with optional PO/GRN linkage for 3-way matching."""

	__allow_unmapped__ = True
	__tablename__ = "ap_invoice_line"
	__table_args__ = (
		Index("ix_ap_invline_invoice", "invoice_id"),
		Index("ix_ap_invline_po_line", "po_line_id"),
		Index("ix_ap_invline_grn_line", "grn_line_id"),
		Index("ix_ap_invline_gl_account", "gl_expense_account"),
		UniqueConstraint("invoice_id", "line_number", name="uq_ap_invline_invoice_seq"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	invoice_id = Column(UUID(as_uuid=False), ForeignKey("ap_invoice.id", ondelete="CASCADE"), nullable=False, index=True)
	line_number = Column(Integer, nullable=False)
	po_line_id = Column(UUID(as_uuid=False), ForeignKey("ap_po_line.id"), nullable=True, index=True)
	grn_line_id = Column(UUID(as_uuid=False), ForeignKey("ap_grn_line.id"), nullable=True, index=True)

	description = Column(Text, nullable=False)
	quantity = Column(Numeric(15, 4), nullable=True)
	uom = Column(String(20), nullable=True)
	unit_cost_cents = Column(Integer, nullable=True, comment="Unit cost in cents at time of invoice")
	line_amount_cents = Column(Integer, nullable=False, comment="quantity × unit_cost_cents")

	tax_category = Column(String(20), nullable=True, comment="S=standard,Z=zero,E=exempt,RC=reverse-charge")
	tax_rate = Column(Numeric(5, 2), nullable=False, default=0)
	tax_cents = Column(Integer, nullable=False, default=0)

	gl_expense_account = Column(String(20), nullable=True, index=True)
	cost_center = Column(String(20), nullable=True)
	project_code = Column(String(50), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	invoice: APInvoice = relationship("APInvoice", back_populates="lines", lazy="select")
	po_line: APPOLine | None = relationship("APPOLine", back_populates="invoice_lines", lazy="select")
	grn_line: APGRNLine | None = relationship("APGRNLine", back_populates="invoice_lines", lazy="select")

	def __repr__(self) -> str:
		return f"<APInvoiceLine inv={self.invoice_id!r} line={self.line_number} amt={self.line_amount_cents}¢>"


# ---------------------------------------------------------------------------
# APApprovalWorkflow
# ---------------------------------------------------------------------------

class APApprovalWorkflow(AuditMixin, Model):
	"""Multi-level invoice approval record.

	One row per approver per invoice.  approval_level determines sequence.
	amount_threshold_cents: max invoice total this approver can authorise (NULL = unlimited).

	Status machine: PENDING → APPROVED | REJECTED
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_approval_workflow"
	__table_args__ = (
		Index("ix_ap_appwf_invoice", "invoice_id"),
		Index("ix_ap_appwf_approver", "approver_id"),
		Index("ix_ap_appwf_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	invoice_id = Column(UUID(as_uuid=False), ForeignKey("ap_invoice.id", ondelete="CASCADE"), nullable=False, index=True)
	approver_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to ab_user")
	approval_level = Column(Integer, nullable=False, default=1, comment="1=line manager,2=dept head,3=CFO")
	amount_threshold_cents = Column(Integer, nullable=True, comment="NULL = unlimited authority")
	status = Column(String(20), nullable=False, default="PENDING", comment="PENDING|APPROVED|REJECTED")
	actioned_at = Column(DateTime(timezone=True), nullable=True)
	comments = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	invoice: APInvoice = relationship("APInvoice", back_populates="approval_workflows", lazy="select")

	def __repr__(self) -> str:
		return f"<APApprovalWorkflow inv={self.invoice_id!r} level={self.approval_level} status={self.status!r}>"


# ---------------------------------------------------------------------------
# APPayment
# ---------------------------------------------------------------------------

class APPayment(AuditMixin, Model):
	"""Individual supplier payment within a payment run (or ad-hoc).

	IMMUTABLE after status=CONFIRMED.  To reverse, post a negative-amount
	correction payment and a compensating GL entry.

	uetr: SWIFT gpi Unique End-to-end Transaction Reference (UUID format)
	for cross-border tracking — assigned by the initiating bank.

	exchange_rate: rate at payment date for functional-currency reporting.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ap_payment"
	__table_args__ = (
		Index("ix_ap_pmt_payment_run", "payment_run_id"),
		Index("ix_ap_pmt_supplier", "supplier_id"),
		Index("ix_ap_pmt_invoice", "invoice_id"),
		Index("ix_ap_pmt_tenant", "tenant_id"),
		Index("ix_ap_pmt_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	payment_run_id = Column(UUID(as_uuid=False), ForeignKey("ap_payment_run.id"), nullable=True, index=True)
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("ap_supplier.id"), nullable=False, index=True)
	invoice_id = Column(UUID(as_uuid=False), ForeignKey("ap_invoice.id"), nullable=True, index=True, comment="Primary invoice being settled; NULL for bulk run payments")

	payment_date = Column(Date, nullable=False)
	amount_cents = Column(Integer, nullable=False, comment="Payment amount in cents; negative = reversal")
	currency_code = Column(String(3), nullable=False, default="USD")
	exchange_rate = Column(Numeric(15, 6), nullable=False, default=1)

	bank_reference = Column(String(200), nullable=True, comment="Bank transaction reference")
	uetr = Column(String(36), nullable=True, comment="SWIFT gpi UETR (UUID format)")
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING|SENT|CONFIRMED|FAILED",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	payment_run: APPaymentRun | None = relationship("APPaymentRun", back_populates="payments", lazy="select")
	supplier: APSupplier = relationship("APSupplier", back_populates="payments", lazy="select")
	invoice: APInvoice | None = relationship("APInvoice", back_populates="payments", lazy="select")

	def __repr__(self) -> str:
		return f"<APPayment {self.id!r} supplier={self.supplier_id!r} amt={self.amount_cents}¢ status={self.status!r}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"APSupplier",
	"APPurchaseOrder",
	"APPOLine",
	"APGoodsReceipt",
	"APGRNLine",
	"APInvoice",
	"APInvoiceLine",
	"APApprovalWorkflow",
	"APPaymentRun",
	"APPayment",
]
