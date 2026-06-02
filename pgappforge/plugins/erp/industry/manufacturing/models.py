"""
pgappforge/plugins/erp/industry/manufacturing/models.py

SQLAlchemy models for the Manufacturing plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - lazy='select' throughout (SA 2.x removed lazy='dynamic')
  - JSONB for semi-structured fields
  - OEE percentages stored as NUMERIC(5,4): 0.0000–1.0000

Table prefix: mfg_
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
# ManufacturingOrder
# ---------------------------------------------------------------------------

class ManufacturingOrder(AuditMixin, Model):
	"""Production/work order — authorises manufacture of a quantity of a product.

	Status machine:
	  DRAFT → RELEASED → IN_PROGRESS → COMPLETED | CANCELLED | SCRAPPED

	actual_qty_produced and actual_cost_cents are updated progressively
	as production progresses; they are never decremented directly.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mfg_manufacturing_order"
	__table_args__ = (
		Index("ix_mfg_mo_tenant", "tenant_id"),
		Index("ix_mfg_mo_tenant_status", "tenant_id", "status"),
		Index("ix_mfg_mo_product", "product_id"),
		Index("ix_mfg_mo_scheduled_start", "scheduled_start"),
		UniqueConstraint("tenant_id", "order_number", name="uq_mfg_mo_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	order_number = Column(String(50), nullable=False, comment="Unique MO number per tenant")
	product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product master")
	product_sku = Column(String(100), nullable=True, comment="Denormalized for quick display")
	bom_id = Column(UUID(as_uuid=False), nullable=True, comment="Bill of materials revision used")
	routing_id = Column(UUID(as_uuid=False), nullable=True, comment="Production routing used")
	work_center_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="Primary work center")

	planned_qty = Column(Numeric(15, 4), nullable=False, comment="Planned production quantity")
	actual_qty_produced = Column(Numeric(15, 4), nullable=False, default=0, comment="Cumulative good output")
	actual_qty_scrapped = Column(Numeric(15, 4), nullable=False, default=0)
	uom = Column(String(20), nullable=False, default="EA")

	# Costs — integer cents
	planned_material_cost_cents = Column(Integer, nullable=False, default=0)
	planned_labour_cost_cents = Column(Integer, nullable=False, default=0)
	planned_overhead_cost_cents = Column(Integer, nullable=False, default=0)
	actual_cost_cents = Column(Integer, nullable=False, default=0, comment="Running actual cost; immutable-ledger add-only")

	scheduled_start = Column(DateTime(timezone=True), nullable=True)
	scheduled_end = Column(DateTime(timezone=True), nullable=True)
	actual_start = Column(DateTime(timezone=True), nullable=True)
	actual_end = Column(DateTime(timezone=True), nullable=True)

	priority = Column(Integer, nullable=False, default=50, comment="1=urgent … 100=low")
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|RELEASED|IN_PROGRESS|COMPLETED|CANCELLED|SCRAPPED",
	)
	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	schedule_entries: list[ProductionSchedule] = relationship(
		"ProductionSchedule", back_populates="manufacturing_order", lazy="select",
	)
	oee_snapshots: list[OEESnapshot] = relationship(
		"OEESnapshot", back_populates="manufacturing_order", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ManufacturingOrder {self.order_number!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ProductionSchedule
# ---------------------------------------------------------------------------

class ProductionSchedule(AuditMixin, Model):
	"""Scheduled slot for a manufacturing order on a work centre.

	Represents a finite-capacity scheduling entry.  Multiple slots per MO
	are valid (multi-operation routing).

	conflict_flag is set by the scheduler when two orders overlap on the
	same work_center_id in overlapping time windows.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mfg_production_schedule"
	__table_args__ = (
		Index("ix_mfg_sched_mo", "manufacturing_order_id"),
		Index("ix_mfg_sched_work_center", "work_center_id"),
		Index("ix_mfg_sched_tenant", "tenant_id"),
		Index("ix_mfg_sched_slot", "work_center_id", "slot_start", "slot_end"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	manufacturing_order_id = Column(UUID(as_uuid=False), ForeignKey("mfg_manufacturing_order.id"), nullable=False, index=True)
	work_center_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	operation_name = Column(String(100), nullable=True, comment="Operation step name e.g. CUT, WELD, PAINT")
	operation_sequence = Column(Integer, nullable=False, default=10)

	slot_start = Column(DateTime(timezone=True), nullable=False)
	slot_end = Column(DateTime(timezone=True), nullable=False)
	setup_minutes = Column(Integer, nullable=False, default=0)
	run_minutes = Column(Integer, nullable=False, default=0)

	status = Column(String(20), nullable=False, default="PLANNED", comment="PLANNED|CONFIRMED|IN_PROGRESS|COMPLETED|CANCELLED")
	conflict_flag = Column(Boolean, nullable=False, default=False, comment="Set when capacity overlap detected")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	manufacturing_order: ManufacturingOrder = relationship("ManufacturingOrder", back_populates="schedule_entries", lazy="select")

	def __repr__(self) -> str:
		return f"<ProductionSchedule mo={self.manufacturing_order_id!r} op={self.operation_name!r} start={self.slot_start}>"


# ---------------------------------------------------------------------------
# MaintenanceWork
# ---------------------------------------------------------------------------

class MaintenanceWork(AuditMixin, Model):
	"""Maintenance work order for plant assets.

	Covers corrective (breakdown), preventive, and predictive maintenance.
	labour_cost_cents and parts_cost_cents are integer cents updated as
	technicians log time and parts consumption.

	IMMUTABLE COST LEDGER: actual_total_cost_cents is computed from
	labour + parts + overhead; never directly overwritten.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mfg_maintenance_work"
	__table_args__ = (
		Index("ix_mfg_maint_tenant", "tenant_id"),
		Index("ix_mfg_maint_asset", "asset_id"),
		Index("ix_mfg_maint_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "work_order_number", name="uq_mfg_maint_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	work_order_number = Column(String(50), nullable=False)
	asset_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to asset registry")
	asset_tag = Column(String(100), nullable=True, comment="Denormalized asset tag for display")
	assigned_technician_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")

	maintenance_type = Column(String(20), nullable=False, comment="CORRECTIVE|PREVENTIVE|PREDICTIVE|STATUTORY")
	priority = Column(String(10), nullable=False, default="MEDIUM", comment="LOW|MEDIUM|HIGH|CRITICAL")
	description = Column(Text, nullable=False)
	root_cause = Column(Text, nullable=True)

	requested_date = Column(Date, nullable=False)
	scheduled_date = Column(Date, nullable=True)
	completed_date = Column(Date, nullable=True)
	downtime_minutes = Column(Integer, nullable=False, default=0, comment="Asset downtime caused by this work order")

	# Costs — integer cents
	estimated_cost_cents = Column(Integer, nullable=False, default=0)
	labour_cost_cents = Column(Integer, nullable=False, default=0)
	parts_cost_cents = Column(Integer, nullable=False, default=0)
	overhead_cost_cents = Column(Integer, nullable=False, default=0)
	actual_total_cost_cents = Column(Integer, nullable=False, default=0, comment="labour + parts + overhead; add-only")

	status = Column(String(20), nullable=False, default="OPEN", comment="OPEN|ASSIGNED|IN_PROGRESS|ON_HOLD|COMPLETED|CANCELLED")
	parts_used = Column(JSONB, nullable=False, default=list, comment="[{part_id, qty, unit_cost_cents}]")
	attachments = Column(JSONB, nullable=False, default=list, comment="[{url, mime, label}]")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	sensor_readings: list[AssetSensor] = relationship("AssetSensor", back_populates="maintenance_work", lazy="select")

	def __repr__(self) -> str:
		return f"<MaintenanceWork {self.work_order_number!r} type={self.maintenance_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# AssetSensor
# ---------------------------------------------------------------------------

class AssetSensor(AuditMixin, Model):
	"""IoT/SCADA sensor reading for a plant asset.

	One row per sensor reading event.  High-frequency data should be
	partitioned by read_at (range partition on month) in production.

	anomaly_flag is set by the predictive maintenance service when the
	reading deviates beyond threshold (stored in thresholds JSONB).
	"""

	__allow_unmapped__ = True
	__tablename__ = "mfg_asset_sensor"
	__table_args__ = (
		Index("ix_mfg_sensor_asset", "asset_id"),
		Index("ix_mfg_sensor_tenant", "tenant_id"),
		Index("ix_mfg_sensor_read_at", "read_at"),
		Index("ix_mfg_sensor_asset_type_read", "asset_id", "sensor_type", "read_at"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	asset_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to asset registry")
	maintenance_work_id = Column(UUID(as_uuid=False), ForeignKey("mfg_maintenance_work.id"), nullable=True, index=True, comment="Linked WO if reading triggered maintenance")

	sensor_type = Column(String(50), nullable=False, comment="TEMPERATURE|VIBRATION|PRESSURE|CURRENT|SPEED|FLOW")
	sensor_tag = Column(String(100), nullable=True, comment="Physical sensor tag/instrument number")
	read_at = Column(DateTime(timezone=True), nullable=False, index=True)
	value = Column(Numeric(20, 6), nullable=False, comment="Raw sensor reading")
	unit = Column(String(20), nullable=False, comment="°C, RPM, bar, A, m³/h…")
	quality = Column(String(10), nullable=False, default="GOOD", comment="GOOD|UNCERTAIN|BAD")
	anomaly_flag = Column(Boolean, nullable=False, default=False)
	anomaly_details = Column(JSONB, nullable=True, comment="{score, threshold, model_version}")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	maintenance_work: MaintenanceWork | None = relationship("MaintenanceWork", back_populates="sensor_readings", lazy="select")

	def __repr__(self) -> str:
		return f"<AssetSensor asset={self.asset_id!r} type={self.sensor_type!r} val={self.value} at={self.read_at}>"


# ---------------------------------------------------------------------------
# OEESnapshot
# ---------------------------------------------------------------------------

class OEESnapshot(AuditMixin, Model):
	"""Overall Equipment Effectiveness snapshot per shift / per work centre.

	OEE = availability × performance × quality (all in [0, 1]).
	Stored as NUMERIC(5,4): 0.0000 → 1.0000 (four decimal places).

	Snapshots are IMMUTABLE once recorded — corrections are new rows.
	downtime_minutes, speed_loss_minutes, reject_qty are raw inputs used
	to recalculate OEE components if required.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mfg_oee_snapshot"
	__table_args__ = (
		Index("ix_mfg_oee_tenant", "tenant_id"),
		Index("ix_mfg_oee_work_center", "work_center_id"),
		Index("ix_mfg_oee_mo", "manufacturing_order_id"),
		Index("ix_mfg_oee_shift_date", "shift_date"),
		Index("ix_mfg_oee_tenant_wc_shift", "tenant_id", "work_center_id", "shift_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	work_center_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	manufacturing_order_id = Column(UUID(as_uuid=False), ForeignKey("mfg_manufacturing_order.id"), nullable=True, index=True)
	shift_date = Column(Date, nullable=False)
	shift_name = Column(String(20), nullable=False, comment="MORNING|AFTERNOON|NIGHT or custom")

	# Raw inputs
	planned_production_minutes = Column(Integer, nullable=False, comment="Total scheduled time in minutes")
	downtime_minutes = Column(Integer, nullable=False, default=0, comment="Unplanned + planned stops")
	ideal_cycle_time_seconds = Column(Numeric(10, 3), nullable=True, comment="Ideal cycle time per unit")
	total_units_run = Column(Numeric(15, 4), nullable=False, default=0)
	good_units = Column(Numeric(15, 4), nullable=False, default=0)
	reject_qty = Column(Numeric(15, 4), nullable=False, default=0)

	# OEE components — NUMERIC(5,4): 0.0000–1.0000
	availability_pct = Column(Numeric(5, 4), nullable=False, comment="(planned_min - downtime_min) / planned_min")
	performance_pct = Column(Numeric(5, 4), nullable=False, comment="(total_units × ideal_cycle) / run_time")
	quality_pct = Column(Numeric(5, 4), nullable=False, comment="good_units / total_units_run")
	oee_pct = Column(Numeric(5, 4), nullable=False, comment="availability × performance × quality")

	notes = Column(Text, nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	manufacturing_order: ManufacturingOrder | None = relationship("ManufacturingOrder", back_populates="oee_snapshots", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<OEESnapshot wc={self.work_center_id!r} shift={self.shift_date}/{self.shift_name!r} "
			f"OEE={float(self.oee_pct):.1%}>"
		)


__all__ = [
	"ManufacturingOrder",
	"ProductionSchedule",
	"MaintenanceWork",
	"AssetSensor",
	"OEESnapshot",
]
