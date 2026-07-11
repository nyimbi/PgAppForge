"""
pgappforge/plugins/erp/operations/scm/models.py

SQLAlchemy models for the Supply Chain Management (SCM) plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields (supplier events, forecast metadata)
  - Proper composite indexes for tenant + status hot paths

Table prefix: scm_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
# Supplier
# ---------------------------------------------------------------------------

class Supplier(AuditMixin, Model):
	"""SCM supplier master — performance and sourcing profile.

	supplier_type: MANUFACTURER | DISTRIBUTOR | SERVICE | AGENT
	status: ACTIVE | QUALIFIED | SUSPENDED | BLACKLISTED
	rating: composite 0-10 score; service layer recomputes from historical KPIs.
	on_time_delivery_pct: rolling 12-month on-time delivery percentage.
	quality_score: rolling 12-month acceptance rate.
	lead_time_days: default replenishment lead time for MRP.
	credit_limit_cents: maximum outstanding payables allowed; 0 = unlimited.
	min_order_qty: minimum order quantity for any PO line.
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_supplier"
	__table_args__ = (
		Index("ix_scm_supplier_tenant", "tenant_id"),
		Index("ix_scm_supplier_party", "party_id"),
		Index("ix_scm_supplier_tenant_preferred", "tenant_id", "preferred"),
		Index("ix_scm_supplier_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "supplier_code", name="uq_scm_supplier_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Link to foundation Party (soft FK — no DB constraint for cross-plugin safety)
	party_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to erp_party.id (soft — no DB constraint)",
	)
	supplier_code = Column(String(20), nullable=False, comment="Unique supplier code per tenant (max 20 chars)")
	name = Column(String(255), nullable=False, comment="Trading name; denormalized from Party for query convenience")

	# Classification
	supplier_type = Column(
		String(20),
		nullable=False,
		default="DISTRIBUTOR",
		comment="MANUFACTURER | DISTRIBUTOR | SERVICE | AGENT",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | QUALIFIED | SUSPENDED | BLACKLISTED",
	)
	country_code = Column(String(2), nullable=True, comment="ISO 3166-1 alpha-2")

	# Performance KPIs
	rating = Column(
		Numeric(3, 1),
		nullable=True,
		comment="Composite supplier rating 0.0-10.0; NULL = not yet rated",
	)
	on_time_delivery_pct = Column(
		Numeric(5, 2),
		nullable=True,
		comment="Rolling 12-month on-time delivery percentage 0.00-100.00",
	)
	quality_score = Column(
		Numeric(5, 2),
		nullable=True,
		comment="Rolling 12-month acceptance rate 0.00-100.00",
	)

	# Sourcing parameters
	lead_time_days = Column(Integer, nullable=False, default=14, comment="Default replenishment lead time in days")
	min_order_qty = Column(
		Numeric(12, 3),
		nullable=False,
		default=1,
		comment="Minimum order quantity for any PO line",
	)
	minimum_order_value_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Minimum order value in cents; PO below this triggers warning",
	)
	credit_limit_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Max outstanding payables in cents; 0 = unlimited",
	)
	preferred = Column(Boolean, nullable=False, default=False, comment="Preferred/approved source flag")
	is_active = Column(Boolean, nullable=False, default=True)

	# Payment & banking
	payment_terms_days = Column(Integer, nullable=False, default=30)
	currency_code = Column(String(3), nullable=False, default="USD")

	notes = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	products: list[SupplierProduct] = relationship(
		"SupplierProduct", back_populates="supplier", cascade="all, delete-orphan", lazy="select",
	)
	shipments: list[ShipmentTracking] = relationship(
		"ShipmentTracking", back_populates="supplier", lazy="select",
	)
	purchase_orders: list[PurchaseOrder] = relationship(
		"PurchaseOrder", back_populates="supplier", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Supplier {self.supplier_code!r} {self.name!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# SupplierProduct
# ---------------------------------------------------------------------------

class SupplierProduct(AuditMixin, Model):
	"""Supplier-specific product catalogue entry.

	Associates a supplier with a purchasable product, carrying supplier-specific
	lead time, MOQ, price, and validity period.

	price_cents: integer cents in currency_code — always cents, never float.
	valid_from / valid_to: price/lead-time validity window.
	  NULL valid_to = currently open.
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_supplier_product"
	__table_args__ = (
		Index("ix_scm_sp_supplier", "supplier_id"),
		Index("ix_scm_sp_product", "product_id"),
		Index("ix_scm_sp_tenant", "tenant_id"),
		Index("ix_scm_sp_validity", "product_id", "valid_from", "valid_to"),
		UniqueConstraint("supplier_id", "product_id", "valid_from", name="uq_scm_sp_supplier_product_from"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("scm_supplier.id", ondelete="CASCADE"), nullable=False, index=True)
	product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product/item master (app-managed)")

	# Supplier-specific identity
	supplier_sku = Column(String(100), nullable=True, comment="Supplier's own part number / SKU")
	description = Column(Text, nullable=True, comment="Supplier's description of the product")

	# Sourcing terms
	lead_time_days = Column(Integer, nullable=False, default=14, comment="Supplier-specific lead time for this product")
	minimum_quantity = Column(Numeric(15, 4), nullable=False, default=1, comment="Minimum order quantity (MOQ)")
	uom = Column(String(20), nullable=False, default="EA")

	# Pricing — integer cents
	price_cents = Column(Integer, nullable=False, default=0, comment="Unit price in cents; NEVER float")
	currency_code = Column(String(3), nullable=False, default="USD")

	# Validity window
	valid_from = Column(Date, nullable=False, comment="Price/terms effective from this date")
	valid_to = Column(Date, nullable=True, comment="NULL = currently open / no expiry")

	is_preferred = Column(Boolean, nullable=False, default=False, comment="Preferred source for this product")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	supplier: Supplier = relationship("Supplier", back_populates="products", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<SupplierProduct supplier={self.supplier_id!r} product={self.product_id!r} "
			f"price={self.price_cents}¢ valid={self.valid_from!r}→{self.valid_to!r}>"
		)


# ---------------------------------------------------------------------------
# PurchaseRequisition
# ---------------------------------------------------------------------------

class PurchaseRequisition(AuditMixin, Model):
	"""Internal purchase requisition — precedes a Purchase Order.

	items JSONB: list of {product_code, qty, estimated_unit_cost_cents, justification}
	status machine: DRAFT → SUBMITTED → APPROVED → PARTIALLY_ORDERED → ORDERED → CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_purchase_requisition"
	__table_args__ = (
		Index("ix_scm_pr_tenant_status", "tenant_id", "status"),
		Index("ix_scm_pr_requester", "requester_id"),
		Index("ix_scm_pr_department", "department_id"),
		Index("ix_scm_pr_required_by", "required_by"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	requester_id = Column(UUID(as_uuid=False), nullable=False, comment="FK to user / employee (app-managed)")
	department_id = Column(UUID(as_uuid=False), nullable=False, comment="FK to department (app-managed)")

	req_date = Column(Date, nullable=False, comment="Date requisition was raised")
	required_by = Column(Date, nullable=False, comment="Date goods/services are needed by")

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | APPROVED | PARTIALLY_ORDERED | ORDERED | CANCELLED",
	)

	# Line items as JSONB: [{product_code, qty, estimated_unit_cost_cents, justification}]
	items: list[dict[str, Any]] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment='[{product_code, qty, estimated_unit_cost_cents, justification}]',
	)

	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="User who approved this requisition")
	approved_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	purchase_orders: list[PurchaseOrder] = relationship(
		"PurchaseOrder", back_populates="requisition", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<PurchaseRequisition id={self.id!r} status={self.status!r} required_by={self.required_by!r}>"


# ---------------------------------------------------------------------------
# PurchaseOrder
# ---------------------------------------------------------------------------

class PurchaseOrder(AuditMixin, Model):
	"""Purchase Order header.

	status machine:
	  DRAFT → SENT → ACKNOWLEDGED → PARTIAL → RECEIVED → INVOICED → CLOSED | CANCELLED

	GL on confirmation (SENT): DR inventory_in_transit "1150" CR AP "2000"
	GL on goods receipt:       DR inventory "1140"           CR inventory_in_transit "1150"
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_purchase_order"
	__table_args__ = (
		Index("ix_scm_po_tenant_status", "tenant_id", "status"),
		Index("ix_scm_po_supplier", "supplier_id"),
		Index("ix_scm_po_requisition", "requisition_id"),
		Index("ix_scm_po_expected_delivery", "expected_delivery_date"),
		UniqueConstraint("tenant_id", "po_number", name="uq_scm_po_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	po_number = Column(String(20), nullable=False, comment="Human-readable PO number, unique per tenant")
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("scm_supplier.id"), nullable=False, index=True)
	requisition_id = Column(
		UUID(as_uuid=False),
		ForeignKey("scm_purchase_requisition.id"),
		nullable=True,
		index=True,
		comment="Source requisition, nullable for direct POs",
	)

	order_date = Column(Date, nullable=False, comment="Date PO was raised")
	expected_delivery_date = Column(Date, nullable=False, comment="Expected delivery date")

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SENT | ACKNOWLEDGED | PARTIAL | RECEIVED | INVOICED | CLOSED | CANCELLED",
	)

	total_amount_cents = Column(BigInteger, nullable=False, default=0, comment="Sum of all line totals in cents")
	currency_code = Column(String(3), nullable=False, default="USD")
	payment_terms_days = Column(Integer, nullable=False, default=30)
	shipping_terms = Column(String(20), nullable=True, comment="e.g. FOB, CIF, DDP, EXW")
	incoterm = Column(String(5), nullable=True, comment="Incoterms 2020 code e.g. FOB, CIF")

	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	supplier: Supplier = relationship("Supplier", back_populates="purchase_orders", lazy="select")
	requisition: PurchaseRequisition | None = relationship("PurchaseRequisition", back_populates="purchase_orders", lazy="select")
	lines: list[POLine] = relationship("POLine", back_populates="purchase_order", cascade="all, delete-orphan", lazy="select")
	goods_receipts: list[GoodsReceipt] = relationship("GoodsReceipt", back_populates="purchase_order", lazy="select")
	invoices: list[SupplierInvoice] = relationship("SupplierInvoice", back_populates="purchase_order", lazy="select")

	def __repr__(self) -> str:
		return f"<PurchaseOrder {self.po_number!r} supplier={self.supplier_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# POLine
# ---------------------------------------------------------------------------

class POLine(AuditMixin, Model):
	"""Purchase Order line — one product/service per line.

	Tracks ordered, received, and invoiced quantities independently to
	support partial receipts and partial invoicing.

	status: OPEN | PARTIAL | RECEIVED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_po_line"
	__table_args__ = (
		Index("ix_scm_pol_po", "po_id"),
		Index("ix_scm_pol_product", "product_code"),
		UniqueConstraint("po_id", "line_number", name="uq_scm_pol_po_line"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	po_id = Column(UUID(as_uuid=False), ForeignKey("scm_purchase_order.id", ondelete="CASCADE"), nullable=False, index=True)

	line_number = Column(Integer, nullable=False, comment="1-based line sequence within the PO")
	product_code = Column(String(30), nullable=False, comment="Internal product / SKU code")
	description = Column(Text, nullable=True)

	ordered_qty = Column(Numeric(12, 3), nullable=False, comment="Quantity originally ordered")
	received_qty = Column(Numeric(12, 3), nullable=False, default=0, comment="Cumulative quantity received via GRN")
	invoiced_qty = Column(Numeric(12, 3), nullable=False, default=0, comment="Cumulative quantity invoiced by supplier")

	unit_of_measure = Column(String(10), nullable=False, default="EA")
	unit_price_cents = Column(BigInteger, nullable=False, comment="Unit price in cents")
	line_total_cents = Column(BigInteger, nullable=False, comment="ordered_qty * unit_price_cents (stored for reporting)")

	status = Column(
		String(15),
		nullable=False,
		default="OPEN",
		comment="OPEN | PARTIAL | RECEIVED | CANCELLED",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	purchase_order: PurchaseOrder = relationship("PurchaseOrder", back_populates="lines", lazy="select")
	grn_lines: list[GoodsReceiptLine] = relationship("GoodsReceiptLine", back_populates="po_line", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<POLine po={self.po_id!r} line={self.line_number} "
			f"product={self.product_code!r} ordered={self.ordered_qty} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# GoodsReceipt
# ---------------------------------------------------------------------------

class GoodsReceipt(AuditMixin, Model):
	"""Goods Receipt Note (GRN) header — records physical arrival of goods.

	GL on post: DR inventory "1140" CR inventory_in_transit "1150"
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_goods_receipt"
	__table_args__ = (
		Index("ix_scm_grn_tenant", "tenant_id"),
		Index("ix_scm_grn_tenant_status", "tenant_id", "status"),
		Index("ix_scm_grn_po", "po_id"),
		Index("ix_scm_grn_received_date", "received_date"),
		UniqueConstraint("tenant_id", "grn_number", name="uq_scm_grn_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	po_id = Column(UUID(as_uuid=False), ForeignKey("scm_purchase_order.id"), nullable=False, index=True)
	grn_number = Column(String(20), nullable=False, comment="Human-readable GRN number, unique per tenant")
	received_date = Column(Date, nullable=False, comment="Date goods were physically received")
	received_by = Column(UUID(as_uuid=False), nullable=False, comment="FK to user / employee (app-managed)")
	status = Column(
		String(15),
		nullable=False,
		default="POSTED",
		comment="DRAFT | CONFIRMED | POSTED | CANCELLED",
	)
	warehouse_id = Column(UUID(as_uuid=False), nullable=True, comment="Destination warehouse (app-managed)")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	purchase_order: PurchaseOrder = relationship("PurchaseOrder", back_populates="goods_receipts", lazy="select")
	lines: list[GoodsReceiptLine] = relationship("GoodsReceiptLine", back_populates="goods_receipt", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return f"<GoodsReceipt {self.grn_number!r} po={self.po_id!r} date={self.received_date!r}>"


# ---------------------------------------------------------------------------
# GoodsReceiptLine
# ---------------------------------------------------------------------------

class GoodsReceiptLine(AuditMixin, Model):
	"""Single line of a Goods Receipt — maps back to a POLine.

	accepted_qty + rejected_qty = received_qty (enforced in service layer).
	lot_number / expiry_date: traceability for perishables or batch-controlled items.
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_goods_receipt_line"
	__table_args__ = (
		Index("ix_scm_grnl_grn", "grn_id"),
		Index("ix_scm_grnl_po_line", "po_line_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	grn_id = Column(UUID(as_uuid=False), ForeignKey("scm_goods_receipt.id", ondelete="CASCADE"), nullable=False, index=True)
	po_line_id = Column(UUID(as_uuid=False), ForeignKey("scm_po_line.id"), nullable=False, index=True)

	received_qty = Column(Numeric(12, 3), nullable=False, comment="Total qty physically received")
	accepted_qty = Column(Numeric(12, 3), nullable=False, comment="Qty accepted into stock")
	rejected_qty = Column(Numeric(12, 3), nullable=False, default=0, comment="Qty rejected (QC failure)")

	rejection_reason = Column(Text, nullable=True)
	lot_number = Column(String(30), nullable=True, comment="Batch / lot number for traceability")
	expiry_date = Column(Date, nullable=True, comment="Expiry date for perishable / batch items")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	goods_receipt: GoodsReceipt = relationship("GoodsReceipt", back_populates="lines", lazy="select")
	po_line: POLine = relationship("POLine", back_populates="grn_lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<GoodsReceiptLine grn={self.grn_id!r} pol={self.po_line_id!r} "
			f"accepted={self.accepted_qty} rejected={self.rejected_qty}>"
		)


# ---------------------------------------------------------------------------
# SupplierInvoice
# ---------------------------------------------------------------------------

class SupplierInvoice(AuditMixin, Model):
	"""Supplier Invoice — subject to 3-way match against PO and GRN.

	3-way match: PO qty ≈ GRN qty ≈ invoice qty (within tolerance).
	status: RECEIVED → MATCHED → APPROVED → PAID | DISPUTED
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_supplier_invoice"
	__table_args__ = (
		Index("ix_scm_sinv_tenant_status", "tenant_id", "status"),
		Index("ix_scm_sinv_po", "po_id"),
		Index("ix_scm_sinv_grn", "grn_id"),
		Index("ix_scm_sinv_due_date", "due_date"),
		UniqueConstraint("tenant_id", "supplier_id", "invoice_number", name="uq_scm_sinv_tenant_supplier_invoice"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	po_id = Column(UUID(as_uuid=False), ForeignKey("scm_purchase_order.id"), nullable=False, index=True)
	grn_id = Column(
		UUID(as_uuid=False),
		ForeignKey("scm_goods_receipt.id"),
		nullable=True,
		index=True,
		comment="Source goods receipt for 3-way match",
	)
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("scm_supplier.id"), nullable=False, index=True)

	invoice_number = Column(String(50), nullable=False, comment="Supplier's own invoice reference")
	invoice_date = Column(Date, nullable=False)
	due_date = Column(Date, nullable=False)

	currency_code = Column(String(3), nullable=False, default="USD")
	subtotal_cents = Column(BigInteger, nullable=False, default=0)
	tax_cents = Column(BigInteger, nullable=False, default=0)
	total_cents = Column(BigInteger, nullable=False, default=0)

	status = Column(
		String(15),
		nullable=False,
		default="RECEIVED",
		comment="RECEIVED | MATCHED | APPROVED | PAID | DISPUTED",
	)

	match_notes = Column(Text, nullable=True, comment="Notes from 3-way match; populated when DISPUTED")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	purchase_order: PurchaseOrder = relationship("PurchaseOrder", back_populates="invoices", lazy="select")
	goods_receipt: GoodsReceipt | None = relationship("GoodsReceipt", lazy="select")
	supplier: Supplier = relationship("Supplier", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<SupplierInvoice {self.invoice_number!r} po={self.po_id!r} "
			f"total={self.total_cents}¢ status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# DemandForecast
# ---------------------------------------------------------------------------

class DemandForecast(AuditMixin, Model):
	"""Statistical demand forecast for a product/period.

	period_month: first day of the forecast month (DATE).
	forecast_method: e.g. MOVING_AVG, EXP_SMOOTH, ML.
	confidence_pct: forecast confidence interval width (0-100); NULL = not computed.
	actual_qty: populated at end of period for accuracy tracking (MAPE).
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_demand_forecast"
	__table_args__ = (
		Index("ix_scm_df_tenant_product", "tenant_id", "product_code"),
		Index("ix_scm_df_period", "period_month"),
		UniqueConstraint("tenant_id", "product_code", "period_month", name="uq_scm_df_tenant_product_period"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	product_code = Column(String(30), nullable=False, comment="Internal product / SKU code")
	period_month = Column(Date, nullable=False, comment="First day of forecast month")

	forecast_qty = Column(Numeric(12, 3), nullable=False, comment="Predicted demand quantity for this period")
	actual_qty = Column(Numeric(12, 3), nullable=True, comment="Actual demand realised; populated at period end")

	forecast_method = Column(String(20), nullable=False, default="MOVING_AVG", comment="MOVING_AVG | EXP_SMOOTH | ML")
	confidence_pct = Column(Numeric(5, 2), nullable=True, comment="Confidence interval width 0-100; NULL = not computed")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<DemandForecast product={self.product_code!r} period={self.period_month!r} "
			f"forecast={self.forecast_qty} actual={self.actual_qty}>"
		)


# ---------------------------------------------------------------------------
# ShipmentTracking
# ---------------------------------------------------------------------------

class ShipmentTracking(AuditMixin, Model):
	"""In-transit shipment tracking record.

	Tracks a shipment from origin to destination warehouse with carrier
	and milestone events.

	events: JSONB array of milestone objects:
	  [{"ts": "ISO8601", "status": "DEPARTED_ORIGIN", "location": "Lagos Port", "note": "..."}, ...]

	Status machine:
	  IN_TRANSIT → DELIVERED | EXCEPTION | RETURNED

	IMMUTABLE NOTE: once status=DELIVERED, do not mutate shipment header.
	Append exception events to the events JSONB array instead.
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_shipment_tracking"
	__table_args__ = (
		Index("ix_scm_ship_tenant", "tenant_id"),
		Index("ix_scm_ship_supplier", "supplier_id"),
		Index("ix_scm_ship_status", "tenant_id", "status"),
		Index("ix_scm_ship_tracking", "carrier", "tracking_number"),
		Index("ix_scm_ship_eta", "estimated_arrival"),
		UniqueConstraint("tenant_id", "tracking_number", "carrier", name="uq_scm_ship_tenant_tracking"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Source document links (soft FKs)
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("scm_supplier.id"), nullable=True, index=True)
	purchase_order_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to scm_purchase_order.id (soft)")
	shipment_reference = Column(String(100), nullable=True, comment="Internal shipment reference / ASN number")

	# Carrier info
	carrier = Column(String(100), nullable=False, comment="Carrier name e.g. DHL, FedEx, Maersk")
	tracking_number = Column(String(200), nullable=False, comment="Carrier tracking / bill of lading number")
	carrier_service = Column(String(100), nullable=True, comment="Service level e.g. EXPRESS, OCEAN_FCL")

	# Route
	origin_warehouse_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to warehouse (app-managed)")
	destination_warehouse_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to warehouse (app-managed)")
	origin_address = Column(JSONB, nullable=False, default=dict, comment="{city, country_code, port}")
	destination_address = Column(JSONB, nullable=False, default=dict, comment="{city, country_code, port}")

	# Timeline
	shipped_at = Column(DateTime(timezone=True), nullable=True, comment="Actual dispatch timestamp")
	estimated_arrival = Column(Date, nullable=True, comment="Carrier ETA")
	actual_arrival = Column(Date, nullable=True, comment="Date physically received at destination warehouse")

	# Status
	status = Column(
		String(15),
		nullable=False,
		default="IN_TRANSIT",
		comment="IN_TRANSIT | DELIVERED | EXCEPTION | RETURNED",
	)

	# Milestone event log — JSONB append-only array
	events: list[dict[str, Any]] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment='[{"ts":ISO8601, "status":"...", "location":"...", "note":"..."}]',
	)

	# Value & customs
	declared_value_cents = Column(Integer, nullable=True, comment="Customs declared value in cents")
	currency_code = Column(String(3), nullable=True)
	incoterms = Column(String(10), nullable=True, comment="e.g. FOB, CIF, DDP, EXW")

	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	supplier: Supplier | None = relationship("Supplier", back_populates="shipments", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ShipmentTracking {self.carrier!r}/{self.tracking_number!r} "
			f"status={self.status!r} eta={self.estimated_arrival!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Supplier",
	"SupplierProduct",
	"PurchaseRequisition",
	"PurchaseOrder",
	"POLine",
	"GoodsReceipt",
	"GoodsReceiptLine",
	"SupplierInvoice",
	"DemandForecast",
	"ShipmentTracking",
]
