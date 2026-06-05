"""
pgappforge/plugins/erp/operations/production/models.py

SQLAlchemy models for the Production Planning (PP) plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields
  - Proper composite indexes for tenant + status hot paths

Table prefix: pp_
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
# BillOfMaterials
# ---------------------------------------------------------------------------

class BillOfMaterials(AuditMixin, Model):
	"""Bill of Materials header.

	Versioned BOM for a product.  Only one ACTIVE version may exist per
	product at any point in time (enforced at service layer).  Temporal
	validity tracked via effective_from / effective_to.

	is_phantom: phantom BOMs collapse their components into the parent BOM
	during MRP explosion — the phantom itself is never stocked or produced.

	Status machine: DRAFT → ACTIVE → OBSOLETE
	"""

	__allow_unmapped__ = True
	__tablename__ = "pp_bom"
	__table_args__ = (
		Index("ix_pp_bom_tenant", "tenant_id"),
		Index("ix_pp_bom_product", "product_id"),
		Index("ix_pp_bom_tenant_status", "tenant_id", "status"),
		Index("ix_pp_bom_effective", "product_id", "effective_from", "effective_to"),
		UniqueConstraint("tenant_id", "product_id", "version", name="uq_pp_bom_product_version"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	product_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK to product/item master (app-managed)",
	)
	version = Column(
		String(20),
		nullable=False,
		default="1",
		comment="Version string e.g. 1, 2, 1.1",
	)
	effective_from = Column(Date, nullable=False, comment="First date this BOM is valid")
	effective_to = Column(Date, nullable=True, comment="Last date; NULL = open-ended")
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | ACTIVE | OBSOLETE",
	)
	is_phantom = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="Phantom BOM: collapse components into parent during MRP explosion",
	)
	description = Column(Text, nullable=True)
	uom = Column(String(20), nullable=False, default="EA", comment="Unit of measure for the produced item")
	yield_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=100,
		comment="Expected yield percentage (100=no loss)",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	lines: list[BOMLine] = relationship(
		"BOMLine",
		back_populates="bom",
		cascade="all, delete-orphan",
		lazy="select",
		order_by="BOMLine.position",
	)
	production_orders: list[ProductionOrder] = relationship(
		"ProductionOrder",
		back_populates="bom",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<BOM product={self.product_id!r} v={self.version!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# BOMLine
# ---------------------------------------------------------------------------

class BOMLine(AuditMixin, Model):
	"""Bill of Materials component line.

	scrap_factor: fraction of component lost during production.
	  required_quantity = quantity * (1 + scrap_factor)
	  e.g. scrap_factor=0.05 means 5% scrapped, so order 5% extra.

	is_critical: flags components where shortage blocks production.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pp_bom_line"
	__table_args__ = (
		Index("ix_pp_bom_line_bom", "bom_id"),
		Index("ix_pp_bom_line_component", "component_product_id"),
		Index("ix_pp_bom_line_tenant", "tenant_id"),
		UniqueConstraint("bom_id", "position", name="uq_pp_bom_line_position"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	bom_id = Column(UUID(as_uuid=False), ForeignKey("pp_bom.id", ondelete="CASCADE"), nullable=False, index=True)
	component_product_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK to product/item master (app-managed)",
	)
	quantity = Column(Numeric(15, 4), nullable=False, comment="Base quantity per parent BOM unit")
	uom = Column(String(20), nullable=False, default="EA", comment="Unit of measure for this component")
	position = Column(Integer, nullable=False, comment="Sort order in BOM explosion")
	scrap_factor = Column(
		Numeric(5, 4),
		nullable=False,
		default=0,
		comment="Fraction scrapped: 0.05 = 5% loss. Gross qty = qty * (1 + scrap_factor)",
	)
	is_critical = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="Shortage of critical components blocks production order release",
	)
	operation_number = Column(
		Integer,
		nullable=True,
		comment="Links to WorkOrderOperation.operation_number (NULL = any operation)",
	)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	bom: BillOfMaterials = relationship("BillOfMaterials", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return f"<BOMLine bom={self.bom_id!r} pos={self.position} comp={self.component_product_id!r} qty={self.quantity}>"


# ---------------------------------------------------------------------------
# WorkCenter
# ---------------------------------------------------------------------------

class WorkCenter(AuditMixin, Model):
	"""Manufacturing work center / machine / production resource.

	capacity_units_per_hour: production throughput in output UOM per hour.
	overhead_rate_per_hour_cents: integer cents — manufacturing overhead
	  absorbed by each work center hour (for standard costing).
	gl_cost_center: links to GL cost centre for overhead posting.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pp_work_center"
	__table_args__ = (
		Index("ix_pp_wc_tenant", "tenant_id"),
		Index("ix_pp_wc_tenant_active", "tenant_id", "is_active"),
		UniqueConstraint("tenant_id", "code", name="uq_pp_wc_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(50), nullable=False, comment="Short code e.g. WC-001, PRESS-A")
	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)
	capacity_units_per_hour = Column(
		Numeric(8, 2),
		nullable=False,
		default=1,
		comment="Output throughput in product UOM per hour",
	)
	overhead_rate_per_hour_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Manufacturing overhead absorption rate: integer cents per hour",
	)
	gl_cost_center = Column(
		String(20),
		nullable=True,
		comment="GL cost centre code for overhead posting",
	)
	calendar_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="FK to shift/capacity calendar (app-managed)",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	production_orders: list[ProductionOrder] = relationship(
		"ProductionOrder", back_populates="work_center", lazy="select",
	)
	operations: list[WorkOrderOperation] = relationship(
		"WorkOrderOperation", back_populates="work_center", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<WorkCenter {self.code!r} {self.name!r} active={self.is_active}>"


# ---------------------------------------------------------------------------
# ProductionOrder
# ---------------------------------------------------------------------------

class ProductionOrder(AuditMixin, Model):
	"""Production order (manufacturing order / work order header).

	Links a BOM to a work center for a specific quantity of output product.

	Costing:
	  planned_cost_cents: derived from BOM component costs + work center rates
	  actual_cost_cents: updated by component issue transactions and labor recording
	  Both are integer cents — never float.

	Status machine:
	  PLANNED → RELEASED → IN_PROGRESS → COMPLETED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "pp_production_order"
	__table_args__ = (
		Index("ix_pp_po_tenant", "tenant_id"),
		Index("ix_pp_po_product", "product_id"),
		Index("ix_pp_po_tenant_status", "tenant_id", "status"),
		Index("ix_pp_po_start_date", "start_date"),
		Index("ix_pp_po_work_center", "work_center_id"),
		UniqueConstraint("tenant_id", "order_number", name="uq_pp_po_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	order_number = Column(String(50), nullable=False, comment="Production order number; unique per tenant")
	product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product/item master (app-managed)")
	bom_id = Column(UUID(as_uuid=False), ForeignKey("pp_bom.id"), nullable=True, index=True, comment="BOM revision used; NULL = latest active")
	work_center_id = Column(UUID(as_uuid=False), ForeignKey("pp_work_center.id"), nullable=True, index=True)

	planned_quantity = Column(Numeric(15, 4), nullable=False, comment="Planned production quantity")
	produced_quantity = Column(Numeric(15, 4), nullable=False, default=0, comment="Actual confirmed output quantity")
	uom = Column(String(20), nullable=False, default="EA")

	start_date = Column(Date, nullable=False, comment="Planned start date")
	end_date = Column(Date, nullable=False, comment="Planned completion date")
	actual_start_date = Column(Date, nullable=True)
	actual_end_date = Column(Date, nullable=True)

	status = Column(
		String(15),
		nullable=False,
		default="PLANNED",
		comment="PLANNED | RELEASED | IN_PROGRESS | COMPLETED | CANCELLED",
	)

	# Costing — integer cents
	planned_cost_cents = Column(Integer, nullable=True, comment="Expected cost from BOM explosion + routing")
	actual_cost_cents = Column(Integer, nullable=False, default=0, comment="Running actual cost from issues and labor")

	warehouse_id = Column(UUID(as_uuid=False), nullable=True, comment="Output storage warehouse (app-managed)")
	notes = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	bom: BillOfMaterials | None = relationship("BillOfMaterials", back_populates="production_orders", lazy="select")
	work_center: WorkCenter | None = relationship("WorkCenter", back_populates="production_orders", lazy="select")
	lines: list[ProductionOrderLine] = relationship(
		"ProductionOrderLine", back_populates="production_order", cascade="all, delete-orphan", lazy="select",
	)
	operations: list[WorkOrderOperation] = relationship(
		"WorkOrderOperation", back_populates="production_order", cascade="all, delete-orphan", lazy="select",
		order_by="WorkOrderOperation.operation_number",
	)

	def __repr__(self) -> str:
		return (
			f"<ProductionOrder {self.order_number!r} product={self.product_id!r} "
			f"qty={self.planned_quantity} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ProductionOrderLine
# ---------------------------------------------------------------------------

class ProductionOrderLine(AuditMixin, Model):
	"""Component material requirement line on a production order.

	Derived from BOM explosion at order creation.
	issued_quantity updated as stock is physically issued to the shop floor.

	Status machine: PENDING → ISSUED → COMPLETE
	"""

	__allow_unmapped__ = True
	__tablename__ = "pp_production_order_line"
	__table_args__ = (
		Index("ix_pp_pol_order", "production_order_id"),
		Index("ix_pp_pol_component", "component_product_id"),
		Index("ix_pp_pol_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	production_order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pp_production_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	component_product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product/item master")
	bom_line_id = Column(UUID(as_uuid=False), ForeignKey("pp_bom_line.id"), nullable=True, comment="Source BOM line (NULL for manually added lines)")
	required_quantity = Column(Numeric(15, 4), nullable=False, comment="Gross requirement including scrap allowance")
	issued_quantity = Column(Numeric(15, 4), nullable=False, default=0, comment="Quantity physically issued to shop floor")
	uom = Column(String(20), nullable=False, default="EA")
	unit_cost_cents = Column(Integer, nullable=True, comment="Standard cost at order creation; integer cents")
	status = Column(
		String(10),
		nullable=False,
		default="PENDING",
		comment="PENDING | ISSUED | COMPLETE",
	)
	warehouse_id = Column(UUID(as_uuid=False), nullable=True, comment="Source warehouse for issue (app-managed)")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	production_order: ProductionOrder = relationship("ProductionOrder", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ProductionOrderLine order={self.production_order_id!r} "
			f"comp={self.component_product_id!r} req={self.required_quantity} issued={self.issued_quantity}>"
		)


# ---------------------------------------------------------------------------
# WorkOrderOperation
# ---------------------------------------------------------------------------

class WorkOrderOperation(AuditMixin, Model):
	"""Routing operation step on a production order.

	Represents a single manufacturing step: setup + run at a work center.
	setup_time_minutes + run_time_minutes = total planned capacity.
	actual_time_minutes: recorded on completion.

	Status machine: PENDING → IN_PROGRESS → COMPLETED | SKIPPED
	"""

	__allow_unmapped__ = True
	__tablename__ = "pp_work_order_operation"
	__table_args__ = (
		Index("ix_pp_woo_order", "production_order_id"),
		Index("ix_pp_woo_work_center", "work_center_id"),
		Index("ix_pp_woo_tenant", "tenant_id"),
		Index("ix_pp_woo_tenant_status", "tenant_id", "status"),
		UniqueConstraint("production_order_id", "operation_number", name="uq_pp_woo_order_seq"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	production_order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pp_production_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	operation_number = Column(Integer, nullable=False, comment="Sequence number within the production order routing")
	work_center_id = Column(UUID(as_uuid=False), ForeignKey("pp_work_center.id"), nullable=False, index=True)
	description = Column(Text, nullable=True)

	# Planned times
	setup_time_minutes = Column(Integer, nullable=False, default=0, comment="Setup/changeover time in minutes")
	run_time_minutes = Column(Integer, nullable=False, default=0, comment="Run time per production order in minutes")

	# Actual
	actual_time_minutes = Column(Integer, nullable=True, comment="Actual elapsed time recorded at completion")
	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		comment="PENDING | IN_PROGRESS | COMPLETED | SKIPPED",
	)
	completed_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user who confirmed completion")
	completed_at = Column(DateTime(timezone=True), nullable=True)

	# Labor cost captured on completion
	labor_cost_cents = Column(Integer, nullable=True, comment="Actual labor cost for this operation; integer cents")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	production_order: ProductionOrder = relationship("ProductionOrder", back_populates="operations", lazy="select")
	work_center: WorkCenter = relationship("WorkCenter", back_populates="operations", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<WorkOrderOperation order={self.production_order_id!r} op={self.operation_number} "
			f"wc={self.work_center_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# PPDemandForecast
# ---------------------------------------------------------------------------

class PPDemandForecast(AuditMixin, Model):
	"""Demand forecast record for a product at a warehouse on a date.

	forecast_method:
	  STATISTICAL — time-series model (e.g. Holt-Winters, ARIMA)
	  ML           — machine-learning model prediction
	  MANUAL       — planner-entered forecast

	confidence_interval: JSONB — { "lower": 95, "upper": 115 } in same UOM.
	created_by_model: model name / version string for audit (e.g. "holt_winters_v2").

	Multiple forecasts per (product, warehouse, date) allowed — service layer
	picks the most recent active revision.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pp_demand_forecast"
	__table_args__ = (
		Index("ix_pp_df_tenant", "tenant_id"),
		Index("ix_pp_df_product_date", "product_id", "forecast_date"),
		Index("ix_pp_df_warehouse_date", "warehouse_id", "forecast_date"),
		Index("ix_pp_df_tenant_method", "tenant_id", "forecast_method"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product/item master (app-managed)")
	warehouse_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to warehouse (app-managed); NULL = all warehouses")
	forecast_date = Column(Date, nullable=False, comment="The date this forecast quantity applies to")
	forecast_quantity = Column(Numeric(15, 4), nullable=False, comment="Forecasted demand quantity")
	uom = Column(String(20), nullable=False, default="EA")
	forecast_method = Column(
		String(15),
		nullable=False,
		default="MANUAL",
		comment="STATISTICAL | ML | MANUAL",
	)
	confidence_interval: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='{"lower": <qty>, "upper": <qty>} in same UOM as forecast_quantity',
	)
	created_by_model = Column(
		String(100),
		nullable=True,
		comment="Model name/version that generated this forecast (NULL for MANUAL)",
	)
	is_active = Column(Boolean, nullable=False, default=True, comment="False = superseded by newer revision")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<PPDemandForecast product={self.product_id!r} date={self.forecast_date!r} "
			f"qty={self.forecast_quantity} method={self.forecast_method!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"BillOfMaterials",
	"BOMLine",
	"WorkCenter",
	"ProductionOrder",
	"ProductionOrderLine",
	"WorkOrderOperation",
	"PPDemandForecast",
]
