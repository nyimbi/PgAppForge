"""
pgappforge/plugins/erp/operations/warehouse/models.py

SQLAlchemy models for the Warehouse Management plugin.

Models:
  PickList        — order picking batch header
  PickListLine    — per-product pick instruction
  PutawayTask     — directs received stock to storage location
  StockCount      — physical inventory count run header
  StockCountLine  — expected vs. counted quantity per SKU per location

Design invariants:
  - UUID v4 PKs, tenant_id NOT NULL, AuditMixin
  - TIMESTAMPTZ DEFAULT NOW() for all timestamps
  - Integer cents for all financial amounts (variance_value_cents)
  - lazy='select' (SA 2.x)
  - NEVER UPDATE StockCount rows once APPROVED — post COUNT_ADJUSTMENT
    movements via InventoryService instead

Table prefix: wms_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	CheckConstraint,
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# PickList
# ---------------------------------------------------------------------------

class PickList(AuditMixin, Model):
	"""Picking batch header.

	Groups all pick instructions for a single outbound order into one task
	assignable to a warehouse operative.

	Status machine:
	  PENDING → ASSIGNED → IN_PROGRESS → COMPLETED | CANCELLED

	order_type distinguishes the source demand:
	  SALES_ORDER   — customer order pick
	  TRANSFER      — inter-warehouse transfer
	  PRODUCTION    — raw material issue to production
	"""

	__allow_unmapped__ = True
	__tablename__ = "wms_picklist"
	__table_args__ = (
		Index("ix_wms_pl_warehouse", "warehouse_id"),
		Index("ix_wms_pl_tenant", "tenant_id"),
		Index("ix_wms_pl_order", "order_id"),
		Index("ix_wms_pl_assigned_to", "assigned_to"),
		Index("ix_wms_pl_tenant_status", "tenant_id", "status"),
		Index("ix_wms_pl_due_by", "due_by"),
		CheckConstraint(
			"order_type IN ('SALES_ORDER','TRANSFER','PRODUCTION')",
			name="ck_wms_pl_order_type",
		),
		CheckConstraint(
			"status IN ('PENDING','ASSIGNED','IN_PROGRESS','COMPLETED','CANCELLED')",
			name="ck_wms_pl_status",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	warehouse_id = Column(
		UUID(as_uuid=False),
		ForeignKey("inv_warehouse.id"),
		nullable=False,
		index=True,
	)
	order_type = Column(String(20), nullable=False, comment="SALES_ORDER | TRANSFER | PRODUCTION")
	order_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to SO, transfer, or production order")
	status = Column(String(20), nullable=False, default="PENDING")
	assigned_to = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ab_user — picker")
	priority = Column(Integer, nullable=False, default=5, comment="Lower = higher priority")
	due_by = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	lines: list[PickListLine] = relationship(
		"PickListLine", back_populates="picklist", cascade="all, delete-orphan", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<PickList order={self.order_id!r} type={self.order_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# PickListLine
# ---------------------------------------------------------------------------

class PickListLine(AuditMixin, Model):
	"""Individual pick instruction within a PickList.

	quantity_requested: how much the order needs
	quantity_picked:    how much the operative has actually picked so far

	status:
	  PENDING    — not yet started
	  PARTIAL    — partially picked
	  COMPLETED  — fully picked (quantity_picked >= quantity_requested)
	  SKIPPED    — could not pick (location empty / product unavailable)
	"""

	__allow_unmapped__ = True
	__tablename__ = "wms_picklist_line"
	__table_args__ = (
		Index("ix_wms_pll_picklist", "picklist_id"),
		Index("ix_wms_pll_product", "product_id"),
		Index("ix_wms_pll_location", "location_id"),
		Index("ix_wms_pll_tenant", "tenant_id"),
		CheckConstraint(
			"status IN ('PENDING','PARTIAL','COMPLETED','SKIPPED')",
			name="ck_wms_pll_status",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	picklist_id = Column(UUID(as_uuid=False), ForeignKey("wms_picklist.id", ondelete="CASCADE"), nullable=False, index=True)
	product_id = Column(UUID(as_uuid=False), ForeignKey("inv_product.id"), nullable=False, index=True)
	location_id = Column(UUID(as_uuid=False), ForeignKey("inv_warehouse_location.id"), nullable=True, index=True, comment="Directed pick face location")
	quantity_requested = Column(Numeric(15, 4), nullable=False)
	quantity_picked = Column(Numeric(15, 4), nullable=False, default=0)
	lot_number = Column(String(100), nullable=True)
	serial_number = Column(String(200), nullable=True)
	status = Column(String(20), nullable=False, default="PENDING")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	picklist: PickList = relationship("PickList", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<PickListLine pl={self.picklist_id!r} product={self.product_id!r} "
			f"req={self.quantity_requested} picked={self.quantity_picked}>"
		)


# ---------------------------------------------------------------------------
# PutawayTask
# ---------------------------------------------------------------------------

class PutawayTask(AuditMixin, Model):
	"""Directs received stock from GRN to its storage location.

	suggested_location_id: system-recommended location (from putaway rules)
	actual_location_id:    where the operative actually put the stock

	Completing a PutawayTask triggers a TRANSFER StockMovement from the
	RECEIVE location to actual_location_id.

	Status machine: PENDING → IN_PROGRESS → COMPLETED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "wms_putaway_task"
	__table_args__ = (
		Index("ix_wms_pt_warehouse", "warehouse_id"),
		Index("ix_wms_pt_grn", "grn_id"),
		Index("ix_wms_pt_product", "product_id"),
		Index("ix_wms_pt_tenant", "tenant_id"),
		Index("ix_wms_pt_tenant_status", "tenant_id", "status"),
		CheckConstraint(
			"status IN ('PENDING','IN_PROGRESS','COMPLETED','CANCELLED')",
			name="ck_wms_pta_status",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	warehouse_id = Column(UUID(as_uuid=False), ForeignKey("inv_warehouse.id"), nullable=False, index=True)
	grn_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK to ap_goods_receipt.id or inv_grn — soft FK to avoid cross-plugin constraint",
	)
	product_id = Column(UUID(as_uuid=False), ForeignKey("inv_product.id"), nullable=False, index=True)
	quantity = Column(Numeric(15, 4), nullable=False)
	lot_number = Column(String(100), nullable=True)
	expiry_date = Column(Date, nullable=True)

	suggested_location_id = Column(
		UUID(as_uuid=False),
		ForeignKey("inv_warehouse_location.id"),
		nullable=True,
		comment="System-suggested putaway location",
	)
	actual_location_id = Column(
		UUID(as_uuid=False),
		ForeignKey("inv_warehouse_location.id"),
		nullable=True,
		comment="Location where stock was actually placed",
	)

	status = Column(String(20), nullable=False, default="PENDING")
	completed_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	completed_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<PutawayTask grn={self.grn_id!r} product={self.product_id!r} qty={self.quantity} status={self.status!r}>"


# ---------------------------------------------------------------------------
# StockCount
# ---------------------------------------------------------------------------

class StockCount(AuditMixin, Model):
	"""Physical inventory count run header.

	count_type:
	  FULL  — all SKUs in warehouse
	  CYCLE — rolling subset (e.g. A-class items this week)
	  SPOT  — specific products or locations (ad-hoc)

	Status machine: DRAFT → IN_PROGRESS → COMPLETED → APPROVED
	  APPROVED triggers COUNT_ADJUSTMENT StockMovements for all lines
	  with non-zero variance.

	IMMUTABLE AFTER APPROVED: post correction counts as a new SPOT count.
	total_variance_value_cents: sum of |variance_value_cents| across lines.
	"""

	__allow_unmapped__ = True
	__tablename__ = "wms_stock_count"
	__table_args__ = (
		Index("ix_wms_sc_warehouse", "warehouse_id"),
		Index("ix_wms_sc_tenant", "tenant_id"),
		Index("ix_wms_sc_count_date", "count_date"),
		Index("ix_wms_sc_tenant_status", "tenant_id", "status"),
		CheckConstraint("count_type IN ('FULL','CYCLE','SPOT')", name="ck_wms_sc_type"),
		CheckConstraint(
			"status IN ('DRAFT','IN_PROGRESS','COMPLETED','APPROVED')",
			name="ck_wms_sc_status",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	warehouse_id = Column(UUID(as_uuid=False), ForeignKey("inv_warehouse.id"), nullable=False, index=True)
	count_date = Column(Date, nullable=False)
	count_type = Column(String(20), nullable=False, default="FULL")
	status = Column(String(20), nullable=False, default="DRAFT")

	# Integer cents for total financial impact
	total_variance_value_cents = Column(
		Integer,
		nullable=True,
		comment="Sum of variance_value_cents across all lines; computed at approval",
	)

	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — approver who posts adjustments")
	approved_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	lines: list[StockCountLine] = relationship(
		"StockCountLine", back_populates="stock_count", cascade="all, delete-orphan", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<StockCount wh={self.warehouse_id!r} date={self.count_date} type={self.count_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# StockCountLine
# ---------------------------------------------------------------------------

class StockCountLine(AuditMixin, Model):
	"""Expected vs. counted quantity per SKU per location within a count run.

	variance = counted_quantity - expected_quantity
	variance_value_cents = variance × average_cost_cents (per unit)
	  Negative → stock loss; positive → stock gain.

	NULL counted_quantity means the line has not yet been counted.
	"""

	__allow_unmapped__ = True
	__tablename__ = "wms_stock_count_line"
	__table_args__ = (
		Index("ix_wms_scl_count", "stock_count_id"),
		Index("ix_wms_scl_product", "product_id"),
		Index("ix_wms_scl_location", "location_id"),
		Index("ix_wms_scl_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	stock_count_id = Column(UUID(as_uuid=False), ForeignKey("wms_stock_count.id", ondelete="CASCADE"), nullable=False, index=True)
	product_id = Column(UUID(as_uuid=False), ForeignKey("inv_product.id"), nullable=False, index=True)
	location_id = Column(
		UUID(as_uuid=False),
		ForeignKey("inv_warehouse_location.id"),
		nullable=True,
		comment="NULL for warehouse-level counts",
	)
	lot_number = Column(String(100), nullable=True)
	expiry_date = Column(Date, nullable=True)

	expected_quantity = Column(Numeric(15, 4), nullable=False, default=0, comment="System QOH at count freeze")
	counted_quantity = Column(Numeric(15, 4), nullable=True, comment="NULL until operative records count")
	variance = Column(Numeric(15, 4), nullable=False, default=0, comment="counted - expected; negative = loss")

	# Valuation — integer cents
	variance_value_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="variance × average_cost_cents; financial impact of this line",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	stock_count: StockCount = relationship("StockCount", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<StockCountLine count={self.stock_count_id!r} product={self.product_id!r} "
			f"expected={self.expected_quantity} counted={self.counted_quantity} var={self.variance}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"PickList",
	"PickListLine",
	"PutawayTask",
	"StockCount",
	"StockCountLine",
]
