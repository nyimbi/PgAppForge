"""
pgappforge/plugins/erp/operations/inventory/models.py

SQLAlchemy models for the Inventory plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - StockMovement: IMMUTABLE event-sourced log — never UPDATE rows
  - lazy='select' throughout (SA 2.x removed lazy='dynamic')
  - JSONB for semi-structured fields (dimensions, address, metadata)
  - Proper composite indexes for tenant + status hot paths
  - weight_grams INTEGER (spec requirement), dimensions_cm JSONB

Table prefix: inv_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	CheckConstraint,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	SmallInteger,
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
# ProductCategory
# ---------------------------------------------------------------------------

class ProductCategory(AuditMixin, Model):
	"""Hierarchical product taxonomy via self-referencing parent_id.

	gl_account links each category to a balance-sheet or P&L account for
	inventory valuation journal entries.
	"""

	__allow_unmapped__ = True
	__tablename__ = "inv_product_category"
	__table_args__ = (
		Index("ix_inv_pcat_tenant", "tenant_id"),
		Index("ix_inv_pcat_parent", "parent_id"),
		UniqueConstraint("tenant_id", "code", name="uq_inv_pcat_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(30), nullable=False, comment="Unique short code per tenant")
	name = Column(String(200), nullable=False, comment="Full display name")
	parent_id = Column(
		UUID(as_uuid=False),
		ForeignKey("inv_product_category.id"),
		nullable=True,
		index=True,
		comment="Parent category; NULL for root categories",
	)
	gl_account = Column(String(20), nullable=True, comment="Inventory asset GL account for valuation journal entries")
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	parent: ProductCategory | None = relationship("ProductCategory", remote_side="ProductCategory.id", lazy="select")
	children: list[ProductCategory] = relationship("ProductCategory", lazy="select", overlaps="parent")
	products: list[Product] = relationship("Product", back_populates="category", lazy="select")

	def __repr__(self) -> str:
		return f"<ProductCategory {self.code!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

class Product(AuditMixin, Model):
	"""Master product / SKU record.

	Monetary fields (base_price_cents, cost_price_cents, standard_cost_cents)
	are integer cents — NEVER float.

	is_serial_tracked drives serial_number validation on StockMovement.
	is_lot_tracked drives lot_number validation.
	is_batch_managed groups lots by manufacturing batch.

	valuation_method determines how COGS is computed on issue:
	  FIFO | LIFO | WEIGHTED_AVG | STANDARD_COST
	"""

	__allow_unmapped__ = True
	__tablename__ = "inv_product"
	__table_args__ = (
		Index("ix_inv_product_tenant", "tenant_id"),
		Index("ix_inv_product_category", "category_id"),
		Index("ix_inv_product_tenant_active", "tenant_id", "is_active"),
		UniqueConstraint("tenant_id", "sku", name="uq_inv_product_tenant_sku"),
		UniqueConstraint("tenant_id", "barcode", name="uq_inv_product_tenant_barcode"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Identity
	sku = Column(String(100), nullable=False, comment="Stock-keeping unit; unique per tenant")
	barcode = Column(String(50), nullable=True, comment="GS1 barcode (EAN/UPC)")
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	category_id = Column(UUID(as_uuid=False), ForeignKey("inv_product_category.id"), nullable=True, index=True)
	brand = Column(String(100), nullable=True)
	uom = Column(String(20), nullable=False, default="EACH", comment="Base unit of measure: EACH, KG, L, M, BOX, etc.")

	# Physical attributes
	weight_grams = Column(Integer, nullable=True, comment="Weight in grams (integer)")
	dimensions_cm = Column(JSONB, nullable=False, default=dict, comment="{length, width, height} in cm")

	# Pricing — integer cents, NEVER float
	base_price_cents = Column(Integer, nullable=False, default=0, comment="Published list price in cents")
	cost_price_cents = Column(Integer, nullable=False, default=0, comment="Last known purchase cost in cents")
	currency_code = Column(String(3), nullable=False, default="USD")

	# Replenishment
	reorder_point = Column(Numeric(15, 4), nullable=False, default=0, comment="Quantity that triggers replenishment order")
	reorder_quantity = Column(Numeric(15, 4), nullable=False, default=0, comment="Default order quantity at reorder")
	max_stock_level = Column(Numeric(15, 4), nullable=False, default=0, server_default="0", comment="Maximum desired stock level; 0 means no cap configured")
	qty_issued_ytd = Column(Numeric(15, 4), nullable=False, default=0, server_default="0", comment="Quantity issued in the current year for ABC analysis")
	lead_time_days = Column(Integer, nullable=False, default=0, comment="Supplier lead time in calendar days")

	# Tracking flags
	is_lot_tracked = Column(Boolean, nullable=False, default=False, comment="Every movement must supply lot_number")
	is_serial_tracked = Column(Boolean, nullable=False, default=False, comment="Every movement must supply serial_number")
	is_batch_managed = Column(Boolean, nullable=False, default=False, comment="Lots grouped by manufacturing batch")
	is_hazardous = Column(Boolean, nullable=False, default=False)
	shelf_life_days = Column(Integer, nullable=True, comment="Shelf life; drives expiry_date validation")

	# Valuation
	valuation_method = Column(
		String(20),
		nullable=False,
		default="WEIGHTED_AVG",
		comment="FIFO | LIFO | WEIGHTED_AVG | STANDARD_COST",
	)
	standard_cost_cents = Column(Integer, nullable=True, comment="Standard cost in cents; used when valuation_method=STANDARD_COST")

	# GL accounts
	gl_inventory_account = Column(String(20), nullable=True, comment="Inventory asset account code")
	gl_cogs_account = Column(String(20), nullable=True, comment="Cost of goods sold account code")

	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	category: ProductCategory | None = relationship("ProductCategory", back_populates="products", lazy="select")
	stock_levels: list[StockLevel] = relationship("StockLevel", back_populates="product", lazy="select")
	stock_movements: list[StockMovement] = relationship("StockMovement", back_populates="product", lazy="select")

	def __repr__(self) -> str:
		return f"<Product {self.sku!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# Warehouse
# ---------------------------------------------------------------------------

class Warehouse(AuditMixin, Model):
	"""Physical or virtual storage facility.

	VIRTUAL type used for in-transit and consignment tracking without a
	physical address.  3PL warehouses are managed by third parties.
	"""

	__allow_unmapped__ = True
	__tablename__ = "inv_warehouse"
	__table_args__ = (
		Index("ix_inv_wh_tenant", "tenant_id"),
		Index("ix_inv_wh_manager", "manager_id"),
		UniqueConstraint("tenant_id", "code", name="uq_inv_wh_tenant_code"),
		CheckConstraint(
			"warehouse_type IN ('OWNED','3PL','CONSIGNMENT','VIRTUAL')",
			name="ck_inv_wh_type",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(20), nullable=False, comment="Unique warehouse code per tenant")
	name = Column(String(200), nullable=False)
	warehouse_type = Column(String(20), nullable=False, default="OWNED", comment="OWNED | 3PL | CONSIGNMENT | VIRTUAL")
	address = Column(JSONB, nullable=False, default=dict, comment="{line1, city, state, postal_code, country}")
	timezone = Column(String(60), nullable=True, default="UTC")
	manager_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ab_user — warehouse manager")
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	locations: list[WarehouseLocation] = relationship("WarehouseLocation", back_populates="warehouse", lazy="select")
	stock_levels: list[StockLevel] = relationship("StockLevel", back_populates="warehouse", lazy="select")
	stock_movements: list[StockMovement] = relationship("StockMovement", back_populates="warehouse", lazy="select")

	def __repr__(self) -> str:
		return f"<Warehouse {self.code!r} type={self.warehouse_type!r}>"


# ---------------------------------------------------------------------------
# WarehouseLocation
# ---------------------------------------------------------------------------

class WarehouseLocation(AuditMixin, Model):
	"""Sub-location within a warehouse (aisle/rack/bin).

	location_type drives putaway and pick rules:
	  BULK   — bulk storage, full pallet
	  PICK   — forward pick face
	  RECEIVE — inbound staging
	  SHIP   — outbound staging / dispatch bay
	  QC     — quality inspection hold
	  QUARANTINE — blocked / rejected stock
	  STAGING — cross-dock staging
	"""

	__allow_unmapped__ = True
	__tablename__ = "inv_warehouse_location"
	__table_args__ = (
		Index("ix_inv_loc_warehouse", "warehouse_id"),
		Index("ix_inv_loc_tenant", "tenant_id"),
		Index("ix_inv_loc_type", "location_type"),
		CheckConstraint(
			"location_type IN ('BULK','PICK','RECEIVE','SHIP','QC','QUARANTINE','STAGING')",
			name="ck_inv_loc_type",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	warehouse_id = Column(UUID(as_uuid=False), ForeignKey("inv_warehouse.id"), nullable=False, index=True)
	aisle = Column(String(20), nullable=True)
	rack = Column(String(20), nullable=True)
	bin = Column(String(20), nullable=True)
	zone = Column(String(30), nullable=True, comment="AMBIENT | COLD | HAZMAT | OVERSIZE")
	location_type = Column(String(20), nullable=False, default="BULK")
	capacity_units = Column(Numeric(10, 2), nullable=True, comment="Max capacity in capacity_uom units")
	capacity_uom = Column(String(20), nullable=True, comment="PALLET | CBM | KG")
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	warehouse: Warehouse = relationship("Warehouse", back_populates="locations", lazy="select")
	stock_levels: list[StockLevel] = relationship("StockLevel", back_populates="location", lazy="select", foreign_keys="StockLevel.location_id")

	def __repr__(self) -> str:
		return f"<WarehouseLocation {self.warehouse_id!r} {self.aisle}/{self.rack}/{self.bin} type={self.location_type!r}>"


# ---------------------------------------------------------------------------
# StockLevel
# ---------------------------------------------------------------------------

class StockLevel(AuditMixin, Model):
	"""Aggregated quantity-on-hand per product / warehouse / location.

	quantity_available = quantity_on_hand - quantity_reserved
	average_cost_cents implements weighted average costing — updated on every
	RECEIPT movement by the service layer.

	lot_number and serial_number provide lot/serial-level granularity when
	the product is tracked at that level.
	"""

	__allow_unmapped__ = True
	__tablename__ = "inv_stock_level"
	__table_args__ = (
		Index("ix_inv_sl_product", "product_id"),
		Index("ix_inv_sl_warehouse", "warehouse_id"),
		Index("ix_inv_sl_location", "location_id"),
		Index("ix_inv_sl_tenant", "tenant_id"),
		Index("ix_inv_sl_tenant_product_wh", "tenant_id", "product_id", "warehouse_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	product_id = Column(UUID(as_uuid=False), ForeignKey("inv_product.id"), nullable=False, index=True)
	warehouse_id = Column(UUID(as_uuid=False), ForeignKey("inv_warehouse.id"), nullable=False, index=True)
	location_id = Column(
		UUID(as_uuid=False),
		ForeignKey("inv_warehouse_location.id"),
		nullable=True,
		index=True,
		comment="NULL for warehouse-level aggregation",
	)

	# Lot / serial level tracking
	lot_number = Column(String(100), nullable=True)
	serial_number = Column(String(200), nullable=True)
	expiry_date = Column(Date, nullable=True)

	# Quantities — NUMERIC(15,4) for fractional UOMs
	quantity_on_hand = Column(Numeric(15, 4), nullable=False, default=0)
	quantity_reserved = Column(Numeric(15, 4), nullable=False, default=0, comment="Allocated to unfulfilled orders")
	quantity_available = Column(Numeric(15, 4), nullable=False, default=0, comment="on_hand - reserved")
	quantity_in_transit = Column(Numeric(15, 4), nullable=False, default=0, comment="Shipped from supplier, not yet received")

	# Valuation — integer cents
	average_cost_cents = Column(Integer, nullable=False, default=0, comment="Weighted average unit cost in cents")
	last_movement_at = Column(DateTime(timezone=True), nullable=True)
	last_movement_date = Column(Date, nullable=False, default=lambda: datetime.now(timezone.utc).date(), server_default=sa.text("CURRENT_DATE"), comment="Date of most recent stock movement")
	receipt_date = Column(Date, nullable=False, default=lambda: datetime.now(timezone.utc).date(), server_default=sa.text("CURRENT_DATE"), comment="Original receipt date for lot aging")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	product: Product = relationship("Product", back_populates="stock_levels", lazy="select")
	warehouse: Warehouse = relationship("Warehouse", back_populates="stock_levels", lazy="select")
	location: WarehouseLocation | None = relationship(
		"WarehouseLocation",
		back_populates="stock_levels",
		lazy="select",
		foreign_keys=[location_id],
	)

	def __repr__(self) -> str:
		return (
			f"<StockLevel product={self.product_id!r} wh={self.warehouse_id!r} "
			f"on_hand={self.quantity_on_hand} avail={self.quantity_available}>"
		)


# ---------------------------------------------------------------------------
# StockMovement — IMMUTABLE event-sourced ledger
# ---------------------------------------------------------------------------

class StockMovement(AuditMixin, Model):
	"""Immutable audit log of every inventory transaction.

	direction = 1  → inbound (RECEIPT, RETURN): increases stock
	direction = -1 → outbound (ISSUE, WRITE_OFF): decreases stock

	NEVER UPDATE rows.  To correct an error, insert a compensating movement.

	reference_type / reference_id link to the source document:
	  PO       → purchase order (receiving)
	  SO       → sales order (picking / shipping)
	  TRANSFER → internal transfer
	  MANUAL   → manual adjustment by warehouse operator

	unit_cost_cents and total_cost_cents are frozen at movement time for
	full cost layer reconstruction from this table alone.
	"""

	__allow_unmapped__ = True
	__tablename__ = "inv_stock_movement"
	__table_args__ = (
		Index("ix_inv_sm_product", "product_id"),
		Index("ix_inv_sm_warehouse", "warehouse_id"),
		Index("ix_inv_sm_tenant", "tenant_id"),
		Index("ix_inv_sm_ref", "reference_id"),
		Index("ix_inv_sm_moved_at", "moved_at"),
		Index("ix_inv_sm_tenant_product_type", "tenant_id", "product_id", "movement_type"),
		CheckConstraint(
			"movement_type IN ('RECEIPT','ISSUE','TRANSFER','ADJUSTMENT','RETURN','WRITE_OFF','COUNT_ADJUSTMENT')",
			name="ck_inv_sm_type",
		),
		CheckConstraint("direction IN (1,-1)", name="ck_inv_sm_direction"),
		CheckConstraint(
			"reference_type IN ('PO','SO','TRANSFER','MANUAL') OR reference_type IS NULL",
			name="ck_inv_sm_ref_type",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	product_id = Column(UUID(as_uuid=False), ForeignKey("inv_product.id"), nullable=False, index=True)
	warehouse_id = Column(UUID(as_uuid=False), ForeignKey("inv_warehouse.id"), nullable=False, index=True)
	from_location_id = Column(
		UUID(as_uuid=False),
		ForeignKey("inv_warehouse_location.id"),
		nullable=True,
		comment="Source location; NULL for inbound RECEIPT",
	)
	to_location_id = Column(
		UUID(as_uuid=False),
		ForeignKey("inv_warehouse_location.id"),
		nullable=True,
		comment="Destination location; NULL for outbound ISSUE/WRITE_OFF",
	)

	movement_type = Column(String(30), nullable=False)
	quantity = Column(Numeric(15, 4), nullable=False, comment="Absolute quantity (always positive)")
	direction = Column(SmallInteger, nullable=False, comment="1=inbound, -1=outbound")

	# Valuation — integer cents
	unit_cost_cents = Column(Integer, nullable=True, comment="Unit cost frozen at movement time")
	total_cost_cents = Column(Integer, nullable=True, comment="quantity × unit_cost_cents; sign follows direction")

	# Lot / serial
	lot_number = Column(String(100), nullable=True)
	serial_number = Column(String(200), nullable=True)
	expiry_date = Column(Date, nullable=True)

	# Source document linkage
	reference_type = Column(String(50), nullable=True)
	reference_id = Column(UUID(as_uuid=False), nullable=True, index=True)

	notes = Column(Text, nullable=True)
	moved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — operator")
	moved_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		comment="Physical movement timestamp (may differ from created_at)",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	product: Product = relationship("Product", back_populates="stock_movements", lazy="select")
	warehouse: Warehouse = relationship("Warehouse", back_populates="stock_movements", lazy="select")

	def __repr__(self) -> str:
		sign = "+" if self.direction == 1 else "-"
		return (
			f"<StockMovement {self.movement_type!r} {sign}{self.quantity} "
			f"product={self.product_id!r} wh={self.warehouse_id!r}>"
		)


# ---------------------------------------------------------------------------
# CostLayer — FIFO/LIFO/Weighted Average inventory cost layers
# ---------------------------------------------------------------------------

class CostLayer(AuditMixin, Model):
	"""Inventory cost layer for FIFO/LIFO/Weighted Average valuation.

	Each stock receipt creates one CostLayer.  Issues consume layers based on
	the product's valuation_method: FIFO (oldest first), LIFO (newest first),
	WEIGHTED_AVG (existing logic in StockLevel.average_cost_cents).

	remaining_qty is decremented to zero (is_exhausted=True) as stock is
	consumed.  Do NOT update rows for other purposes — treat as append-only
	except for remaining_qty / is_exhausted.
	"""

	__allow_unmapped__ = True
	__tablename__ = "inv_cost_layer"
	__table_args__ = (
		Index("ix_inv_cost_layer_product_wh", "product_id", "warehouse_id"),
		Index("ix_inv_cost_layer_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	product_id = Column(UUID(as_uuid=False), nullable=False)
	warehouse_id = Column(UUID(as_uuid=False), nullable=False)
	received_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		comment="Timestamp of the originating receipt; used for FIFO/LIFO ordering",
	)
	received_qty = Column(Numeric(15, 4), nullable=False, comment="Original quantity received into this layer")
	unit_cost_cents = Column(BigInteger, nullable=False, comment="Unit cost at receipt time, in cents")
	remaining_qty = Column(Numeric(15, 4), nullable=False, comment="Quantity not yet consumed; decremented on issue")
	is_exhausted = Column(Boolean, nullable=False, default=False, comment="True when remaining_qty reaches zero")
	source_grn_id = Column(UUID(as_uuid=False), nullable=True, comment="Originating GRN UUID (soft FK)")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<CostLayer product={self.product_id!r} wh={self.warehouse_id!r} "
			f"unit_cost={self.unit_cost_cents}¢ remaining={self.remaining_qty}>"
		)


# ---------------------------------------------------------------------------
# TransferOrder — inter-location inventory transfer
# ---------------------------------------------------------------------------

class TransferOrder(AuditMixin, Model):
	"""Inter-location inventory transfer with in-transit status.

	Lifecycle: DRAFT → SHIPPED (stock deducted from source) → RECEIVED
	           (stock added to destination) | CANCELLED

	lines JSONB schema:
	  [{"product_id": str, "qty": str, "unit_cost_cents": int,
	    "lot_number": str | null}, ...]
	"""

	__allow_unmapped__ = True
	__tablename__ = "inv_transfer_order"
	__table_args__ = (
		Index("ix_inv_to_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	transfer_ref = Column(String(50), nullable=False, comment="Human-readable reference e.g. TO-20260607120000")
	from_location_id = Column(UUID(as_uuid=False), nullable=False, comment="Source warehouse/location UUID (soft FK)")
	to_location_id = Column(UUID(as_uuid=False), nullable=False, comment="Destination warehouse/location UUID (soft FK)")
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SHIPPED | RECEIVED | CANCELLED",
	)
	lines = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{product_id, qty, unit_cost_cents, lot_number?}]",
	)
	shipped_at = Column(DateTime(timezone=True), nullable=True)
	received_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<TransferOrder {self.transfer_ref!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ProductCategory",
	"Product",
	"Warehouse",
	"WarehouseLocation",
	"StockLevel",
	"StockMovement",
	"CostLayer",
	"TransferOrder",
]
