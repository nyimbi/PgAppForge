"""
pgappforge/plugins/erp/operations/mrp/models.py

SQLAlchemy models for the MRP (Materials Requirements Planning) plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - PostgreSQL only — JSONB, UUID, gen_random_uuid()
  - Quantities: Numeric(15,4) — fractional UOMs supported

Table prefix: mrp_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

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
# MRPRun
# ---------------------------------------------------------------------------

class MRPRun(AuditMixin, Model):
	"""Single MRP planning run for a tenant.

	Captures the planning period, horizon, status, and aggregate counts of
	planned orders and purchase requisitions generated.  One run per
	period/tenant; historical runs are retained for audit and comparison.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mrp_run"
	__table_args__ = (
		Index("ix_mrp_run_tenant_status", "tenant_id", "status"),
		Index("ix_mrp_run_tenant_period", "tenant_id", "period"),
		CheckConstraint(
			"status IN ('IN_PROGRESS','COMPLETED','FAILED')",
			name="ck_mrp_run_status",
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

	# Planning parameters
	period = Column(
		String(20),
		nullable=False,
		comment="Planning period label — e.g. '2025-06' or 'W24-2025'",
	)
	horizon_days = Column(
		Integer,
		nullable=False,
		default=90,
		comment="Number of days forward from run date to plan",
	)

	# Lifecycle
	status = Column(
		String(20),
		nullable=False,
		default="IN_PROGRESS",
		comment="IN_PROGRESS | COMPLETED | FAILED",
	)
	started_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	completed_at = Column(DateTime(timezone=True), nullable=True)

	# Aggregate results
	planned_orders_count = Column(Integer, nullable=False, default=0)
	purchase_reqs_count = Column(Integer, nullable=False, default=0)

	# Optional entity scope (e.g. plant/business unit)
	entity_id = Column(String(50), nullable=True, index=True)

	# Timestamps from AuditMixin
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
	planned_orders: list[MRPPlannedOrder] = relationship(
		"MRPPlannedOrder",
		back_populates="run",
		lazy="select",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return f"<MRPRun period={self.period!r} status={self.status!r} tenant={self.tenant_id!r}>"


# ---------------------------------------------------------------------------
# MRPProductConfig
# ---------------------------------------------------------------------------

class MRPProductConfig(AuditMixin, Model):
	"""MRP planning parameters for a single product within a tenant.

	Drives the net requirements calculation:
	  - safety_stock_qty: buffer stock below which stock is considered insufficient
	  - reorder_point_qty: triggers replenishment (used by check_safety_stock)
	  - lot_size_qty: minimum order / production quantity — planned_qty is always
	    a multiple of this
	  - lead_time_days: supplier or production lead time
	  - procurement_type: EXTERNAL (purchase), INTERNAL (produce), PHANTOM (virtual
	    assembly — pass-through in BOM explosion)
	  - bom_id: soft FK to production BOM — used for BOM explosion
	"""

	__allow_unmapped__ = True
	__tablename__ = "mrp_config"
	__table_args__ = (
		Index("ix_mrp_config_tenant_product", "tenant_id", "product_id"),
		Index("ix_mrp_config_tenant_proc_type", "tenant_id", "procurement_type"),
		UniqueConstraint("tenant_id", "product_id", name="uq_mrp_config_tenant_product"),
		CheckConstraint(
			"procurement_type IN ('EXTERNAL','INTERNAL','PHANTOM')",
			name="ck_mrp_config_proc_type",
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

	# Product reference (soft FK — cross-module)
	product_id = Column(
		String(50),
		nullable=False,
		comment="Soft FK to inv_product.id or product catalogue ID",
	)

	# MRP planning parameters
	safety_stock_qty = Column(
		Numeric(15, 4),
		nullable=False,
		default=0,
		comment="Buffer stock qty — net req = demand - on_hand - safety_stock",
	)
	reorder_point_qty = Column(
		Numeric(15, 4),
		nullable=False,
		default=0,
		comment="Stock level that triggers safety stock breach alert",
	)
	lot_size_qty = Column(
		Numeric(15, 4),
		nullable=False,
		default=1,
		comment="Minimum order/production qty — planned_qty is always a multiple",
	)
	lead_time_days = Column(
		Integer,
		nullable=False,
		default=7,
		comment="Calendar days from order to receipt/completion",
	)
	procurement_type = Column(
		String(20),
		nullable=False,
		default="EXTERNAL",
		comment="EXTERNAL=purchase, INTERNAL=produce, PHANTOM=pass-through BOM",
	)

	# Optional sourcing links (soft FKs)
	preferred_supplier_id = Column(
		String(50),
		nullable=True,
		comment="Soft FK to scm_supplier.id",
	)
	bom_id = Column(
		String(50),
		nullable=True,
		comment="Soft FK to production BOM — enables BOM explosion for INTERNAL",
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

	def __repr__(self) -> str:
		return (
			f"<MRPProductConfig product={self.product_id!r} "
			f"type={self.procurement_type!r} lead={self.lead_time_days}d>"
		)


# ---------------------------------------------------------------------------
# MRPPlannedOrder
# ---------------------------------------------------------------------------

class MRPPlannedOrder(AuditMixin, Model):
	"""A planned order generated by an MRP run.

	planned_qty >= required_qty, rounded up to the nearest lot_size_qty.
	planned_start_date = required_date - lead_time_days (workback schedule).

	order_type:
	  PURCHASE   — triggers a purchase requisition (→ PO)
	  PRODUCTION — triggers a production order recommendation

	Lifecycle:
	  PLANNED  → RELEASED (converted to actual PO or production order)
	           → CANCELLED (demand disappeared or superseded by later run)

	converted_to_id links to the actual PO ID or production order ID after
	release — enables full traceability from plan to execution.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mrp_planned_order"
	__table_args__ = (
		Index("ix_mrp_po_run_type", "run_id", "order_type"),
		Index("ix_mrp_po_product_date", "product_id", "required_date"),
		Index("ix_mrp_po_status", "status"),
		Index("ix_mrp_po_tenant", "tenant_id"),
		CheckConstraint(
			"order_type IN ('PURCHASE','PRODUCTION')",
			name="ck_mrp_po_order_type",
		),
		CheckConstraint(
			"status IN ('PLANNED','RELEASED','CANCELLED')",
			name="ck_mrp_po_status",
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

	run_id = Column(
		UUID(as_uuid=False),
		ForeignKey("mrp_run.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	# Product reference (soft FK — cross-module)
	product_id = Column(
		String(50),
		nullable=False,
		comment="Soft FK to inv_product.id or product catalogue ID",
	)

	# Quantities
	required_qty = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Net requirement quantity before lot-size rounding",
	)
	planned_qty = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Planned quantity — required_qty rounded up to lot_size_qty multiples",
	)

	# Dates
	required_date = Column(
		Date,
		nullable=False,
		comment="Date by which the quantity must be available",
	)
	planned_start_date = Column(
		Date,
		nullable=False,
		comment="Start date = required_date minus lead_time_days",
	)

	# Classification
	order_type = Column(
		String(20),
		nullable=False,
		comment="PURCHASE | PRODUCTION",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PLANNED",
		comment="PLANNED | RELEASED | CANCELLED",
	)

	# Traceability after conversion
	converted_to_id = Column(
		String(50),
		nullable=True,
		comment="Actual PO or production order ID after release",
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
	run: MRPRun = relationship("MRPRun", back_populates="planned_orders", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<MRPPlannedOrder product={self.product_id!r} "
			f"type={self.order_type!r} qty={self.planned_qty} "
			f"date={self.required_date} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"MRPRun",
	"MRPProductConfig",
	"MRPPlannedOrder",
]
