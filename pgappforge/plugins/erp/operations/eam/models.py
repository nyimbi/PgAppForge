"""
pgappforge/plugins/erp/operations/eam/models.py

SQLAlchemy 2.x models for the Enterprise Asset Management (EAM/CMMS) plugin.

Design invariants:
  - ALL PKs: UUID(as_uuid=False) — gen_random_uuid() server default + Python default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - Monetary amounts: BigInteger cents (never Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - MeterReading: IMMUTABLE event log — never UPDATE rows
  - JSONB for semi-structured fields (steps, parts_list, required_skills)
  - Composite indexes for tenant + status hot paths
  - Table prefix: eam_

NOTE: finance/assets plugin handles depreciation.
      This plugin handles maintenance lifecycle only.
      ManagedAsset.finance_asset_id is an advisory FK — no hard constraint
      across plugin boundaries.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
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
# AssetLocation
# ---------------------------------------------------------------------------

class AssetLocation(AuditMixin, Model):
	"""Physical or logical location where assets reside.

	Supports unlimited hierarchy via self-referencing parent_location_id.
	GPS coordinates enable map-based asset tracking.
	level is denormalised (depth from root) for fast subtree queries.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_asset_location"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_eam_loc_tenant_code"),
		Index("ix_eam_loc_tenant", "tenant_id"),
		Index("ix_eam_loc_parent", "parent_location_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	code = Column(String(20), nullable=False, comment="Short location code, unique per tenant")
	name = Column(String(200), nullable=False)
	parent_location_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_asset_location.id"),
		nullable=True,
		index=True,
	)
	level = Column(Integer, nullable=False, default=0, comment="Depth from root; 0 = root")
	address = Column(Text, nullable=True)
	gps_lat = Column(Numeric(9, 6), nullable=True)
	gps_lng = Column(Numeric(9, 6), nullable=True)

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

	parent: AssetLocation | None = relationship(
		"AssetLocation", remote_side="AssetLocation.id", lazy="select"
	)
	children: list[AssetLocation] = relationship(
		"AssetLocation", lazy="select", overlaps="parent"
	)
	assets: list[ManagedAsset] = relationship(
		"ManagedAsset", back_populates="location", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<AssetLocation {self.code!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# ManagedAsset
# ---------------------------------------------------------------------------

class ManagedAsset(AuditMixin, Model):
	"""Physical asset subject to maintenance management.

	asset_type  : equipment class for routing and reporting
	criticality : drives work order priority and planning lead times
	status      : lifecycle state — transitions governed by EAMService
	finance_asset_id : advisory reference to the finance/assets depreciation
	             record; no hard FK constraint across plugin boundaries.

	Monetary field replacement_cost_cents uses BigInteger to handle
	large infrastructure assets (bridges, plant etc.).
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_managed_asset"
	__table_args__ = (
		UniqueConstraint("tenant_id", "asset_code", name="uq_eam_asset_tenant_code"),
		Index("ix_eam_asset_tenant", "tenant_id"),
		Index("ix_eam_asset_status", "tenant_id", "status"),
		Index("ix_eam_asset_location", "asset_location_id"),
		CheckConstraint(
			"asset_type IN ('EQUIPMENT','VEHICLE','BUILDING','INFRASTRUCTURE','IT')",
			name="ck_eam_asset_type",
		),
		CheckConstraint(
			"status IN ('ACTIVE','IN_MAINTENANCE','OUT_OF_SERVICE','DECOMMISSIONED')",
			name="ck_eam_asset_status",
		),
		CheckConstraint(
			"criticality IN ('CRITICAL','HIGH','MEDIUM','LOW')",
			name="ck_eam_asset_criticality",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	asset_code = Column(String(20), nullable=False, comment="Short code, unique per tenant")
	name = Column(String(200), nullable=False)
	asset_location_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_asset_location.id"),
		nullable=False,
		index=True,
	)
	parent_asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_managed_asset.id"),
		nullable=True,
		index=True,
		comment="Parent asset for sub-component tracking",
	)
	asset_type = Column(String(20), nullable=False)
	manufacturer = Column(String(100), nullable=True)
	model_number = Column(String(100), nullable=True)
	serial_number = Column(String(100), nullable=True, unique=True)
	install_date = Column(Date, nullable=False)
	warranty_expiry = Column(Date, nullable=True)
	expected_life_years = Column(Integer, nullable=True)
	replacement_cost_cents = Column(BigInteger, nullable=False, default=0)
	status = Column(String(20), nullable=False, default="ACTIVE")
	criticality = Column(String(10), nullable=False, default="MEDIUM")
	# Advisory cross-plugin reference — no FK constraint
	finance_asset_id = Column(UUID(as_uuid=False), nullable=True)

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

	location: AssetLocation = relationship(
		"AssetLocation", back_populates="assets", lazy="select"
	)
	parent_asset: ManagedAsset | None = relationship(
		"ManagedAsset", remote_side="ManagedAsset.id", lazy="select"
	)
	children_assets: list[ManagedAsset] = relationship(
		"ManagedAsset", lazy="select", overlaps="parent_asset"
	)
	meter_readings: list[MeterReading] = relationship(
		"MeterReading", back_populates="asset", lazy="select"
	)
	maintenance_plans: list[MaintenancePlan] = relationship(
		"MaintenancePlan", back_populates="asset", lazy="select"
	)
	work_orders: list[MaintenanceWorkOrder] = relationship(
		"MaintenanceWorkOrder", back_populates="asset", lazy="select"
	)
	failure_reports: list[FailureReport] = relationship(
		"FailureReport", back_populates="asset", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<ManagedAsset {self.asset_code!r} {self.name!r} [{self.status}]>"


# ---------------------------------------------------------------------------
# MeterReading  (immutable event log)
# ---------------------------------------------------------------------------

class MeterReading(Model):
	"""Immutable meter / odometer reading for an asset.

	Rows are NEVER updated — corrections are new readings.
	meter_type determines which MaintenancePlan triggers to evaluate.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_meter_reading"
	__table_args__ = (
		Index("ix_eam_meter_asset_date", "asset_id", "reading_date"),
		Index("ix_eam_meter_tenant", "tenant_id"),
		Index("ix_eam_meter_tenant_asset_date", "tenant_id", "asset_id", "reading_date"),
		CheckConstraint(
			"meter_type IN ('HOURS','KM','CYCLES','UNITS')",
			name="ck_eam_meter_type",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_managed_asset.id"),
		nullable=False,
		index=True,
	)
	meter_type = Column(String(10), nullable=False)
	reading_value = Column(Numeric(12, 2), nullable=False)
	reading_date = Column(Date, nullable=False)
	recorded_by = Column(UUID(as_uuid=False), nullable=False, comment="Employee UUID")
	notes = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	asset: ManagedAsset = relationship(
		"ManagedAsset", back_populates="meter_readings", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<MeterReading asset={self.asset_id} {self.meter_type}={self.reading_value} @ {self.reading_date}>"


# ---------------------------------------------------------------------------
# JobPlan
# ---------------------------------------------------------------------------

class JobPlan(AuditMixin, Model):
	"""Reusable maintenance task template.

	steps       : ordered list of {step_no: int, description: str, estimated_mins: int}
	required_skills : list of craft strings e.g. ["ELECTRICIAN", "MECHANIC"]
	parts_list  : list of {part_code: str, quantity: float}
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_job_plan"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_eam_job_plan_tenant_code"),
		Index("ix_eam_job_plan_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	code = Column(String(20), nullable=False)
	name = Column(String(200), nullable=False)
	estimated_hours = Column(Numeric(6, 2), nullable=False, default=0)
	steps = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="'[]'::jsonb",
		comment="[{step_no, description, estimated_mins}]",
	)
	required_skills = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="'[]'::jsonb",
		comment="List of craft strings",
	)
	safety_precautions = Column(Text, nullable=True)
	parts_list = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="'[]'::jsonb",
		comment="[{part_code, quantity}]",
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

	maintenance_plans: list[MaintenancePlan] = relationship(
		"MaintenancePlan", back_populates="job_plan", lazy="select"
	)
	work_orders: list[MaintenanceWorkOrder] = relationship(
		"MaintenanceWorkOrder", back_populates="job_plan", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<JobPlan {self.code!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# MaintenancePlan
# ---------------------------------------------------------------------------

class MaintenancePlan(AuditMixin, Model):
	"""Scheduled or condition-based maintenance plan for an asset.

	plan_type determines the trigger mechanism:
	  CALENDAR  — trigger_interval_days drives periodic WO generation
	  METER     — trigger_meter_value + trigger_meter_type drives generation
	  CONDITION — externally triggered (condition monitoring systems)

	lead_days : generate the WO this many days before next_due_at so
	            parts and labour can be arranged in advance.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_maintenance_plan"
	__table_args__ = (
		Index("ix_eam_mplan_tenant_active", "tenant_id", "is_active"),
		Index("ix_eam_mplan_asset", "asset_id"),
		Index("ix_eam_mplan_next_due", "next_due_at"),
		CheckConstraint(
			"plan_type IN ('CALENDAR','METER','CONDITION')",
			name="ck_eam_mplan_type",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_managed_asset.id"),
		nullable=False,
		index=True,
	)
	plan_name = Column(String(200), nullable=False)
	plan_type = Column(String(10), nullable=False, default="CALENDAR")
	trigger_interval_days = Column(Integer, nullable=True, comment="CALENDAR plans only")
	trigger_meter_value = Column(Numeric(12, 2), nullable=True, comment="METER plans: reading delta before trigger")
	trigger_meter_type = Column(
		String(10),
		nullable=True,
		comment="METER plans: HOURS/KM/CYCLES/UNITS",
	)
	lead_days = Column(Integer, nullable=False, default=7)
	job_plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_job_plan.id"),
		nullable=True,
		index=True,
	)
	last_generated_at = Column(DateTime(timezone=True), nullable=True)
	next_due_at = Column(DateTime(timezone=True), nullable=True, index=True)
	is_active = Column(Boolean, nullable=False, default=True)

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

	asset: ManagedAsset = relationship(
		"ManagedAsset", back_populates="maintenance_plans", lazy="select"
	)
	job_plan: JobPlan | None = relationship(
		"JobPlan", back_populates="maintenance_plans", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<MaintenancePlan {self.plan_name!r} [{self.plan_type}] asset={self.asset_id}>"


# ---------------------------------------------------------------------------
# MaintenanceWorkOrder
# ---------------------------------------------------------------------------

class MaintenanceWorkOrder(AuditMixin, Model):
	"""Central work order record driving the maintenance execution lifecycle.

	work_type  : PREVENTIVE | CORRECTIVE | EMERGENCY | INSPECTION | STATUTORY
	priority   : 1=Emergency, 2=Urgent, 3=Routine, 4=Low
	status     : PLANNED → APPROVED → ASSIGNED → IN_PROGRESS
	             → PENDING_PARTS | ON_HOLD → COMPLETED → CLOSED | CANCELLED

	failure_code / cause_code / remedy_code : follow the failure code
	taxonomy (e.g. ISO 14224 or custom per tenant).

	safety_permit_required : when True, EAMService.issue_safety_permit()
	must be called before the WO can transition to IN_PROGRESS.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_work_order"
	__table_args__ = (
		UniqueConstraint("tenant_id", "wo_number", name="uq_eam_wo_tenant_number"),
		Index("ix_eam_wo_tenant_status", "tenant_id", "status"),
		Index("ix_eam_wo_asset", "asset_id"),
		Index("ix_eam_wo_planned_start", "planned_start"),
		Index("ix_eam_wo_assigned", "assigned_to"),
		CheckConstraint(
			"work_type IN ('PREVENTIVE','CORRECTIVE','EMERGENCY','INSPECTION','STATUTORY')",
			name="ck_eam_wo_work_type",
		),
		CheckConstraint(
			"status IN ('PLANNED','APPROVED','ASSIGNED','IN_PROGRESS','PENDING_PARTS',"
			"'ON_HOLD','COMPLETED','CLOSED','CANCELLED')",
			name="ck_eam_wo_status",
		),
		CheckConstraint("priority BETWEEN 1 AND 4", name="ck_eam_wo_priority"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	wo_number = Column(String(20), nullable=False, comment="Unique WO reference per tenant")
	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_managed_asset.id"),
		nullable=False,
		index=True,
	)
	work_type = Column(String(15), nullable=False, default="CORRECTIVE")
	priority = Column(Integer, nullable=False, default=3)
	status = Column(String(15), nullable=False, default="PLANNED")
	job_plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_job_plan.id"),
		nullable=True,
		index=True,
	)
	description = Column(Text, nullable=False)
	failure_code = Column(String(20), nullable=True)
	cause_code = Column(String(20), nullable=True)
	remedy_code = Column(String(20), nullable=True)
	assigned_to = Column(UUID(as_uuid=False), nullable=True, comment="Employee UUID")
	planned_start = Column(DateTime(timezone=True), nullable=False)
	planned_end = Column(DateTime(timezone=True), nullable=False)
	actual_start = Column(DateTime(timezone=True), nullable=True)
	actual_end = Column(DateTime(timezone=True), nullable=True)
	estimated_cost_cents = Column(BigInteger, nullable=False, default=0)
	actual_cost_cents = Column(BigInteger, nullable=False, default=0)
	downtime_hours = Column(Numeric(8, 2), nullable=True)
	safety_permit_required = Column(Boolean, nullable=False, default=False)

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

	asset: ManagedAsset = relationship(
		"ManagedAsset", back_populates="work_orders", lazy="select"
	)
	job_plan: JobPlan | None = relationship(
		"JobPlan", back_populates="work_orders", lazy="select"
	)
	labor_lines: list[WorkOrderLabor] = relationship(
		"WorkOrderLabor", back_populates="work_order", lazy="select",
		cascade="all, delete-orphan",
	)
	part_lines: list[WorkOrderPart] = relationship(
		"WorkOrderPart", back_populates="work_order", lazy="select",
		cascade="all, delete-orphan",
	)
	safety_permits: list[SafetyPermit] = relationship(
		"SafetyPermit", back_populates="work_order", lazy="select",
		cascade="all, delete-orphan",
	)
	failure_reports: list[FailureReport] = relationship(
		"FailureReport", back_populates="work_order", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<MaintenanceWorkOrder {self.wo_number!r} [{self.status}] asset={self.asset_id}>"


# ---------------------------------------------------------------------------
# WorkOrderLabor
# ---------------------------------------------------------------------------

class WorkOrderLabor(Model):
	"""Labour line on a work order.

	total_cost_cents is a computed property — not stored — to avoid
	the dual-write problem between rate/hours and total.
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_wo_labor"
	__table_args__ = (
		Index("ix_eam_labor_wo", "wo_id"),
		Index("ix_eam_labor_employee", "employee_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	wo_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_work_order.id"),
		nullable=False,
		index=True,
	)
	employee_id = Column(UUID(as_uuid=False), nullable=False)
	craft = Column(String(30), nullable=False, comment="e.g. ELECTRICIAN, MECHANIC")
	planned_hours = Column(Numeric(6, 2), nullable=False, default=0)
	actual_hours = Column(Numeric(6, 2), nullable=False, default=0)
	rate_cents_per_hour = Column(Integer, nullable=False, default=0)

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

	work_order: MaintenanceWorkOrder = relationship(
		"MaintenanceWorkOrder", back_populates="labor_lines", lazy="select"
	)

	@property
	def total_cost_cents(self) -> int:
		"""Computed: actual_hours * rate_cents_per_hour, rounded to int."""
		from decimal import Decimal, ROUND_HALF_UP
		hours = Decimal(str(self.actual_hours or 0))
		rate = Decimal(str(self.rate_cents_per_hour or 0))
		return int((hours * rate).to_integral_value(ROUND_HALF_UP))

	def __repr__(self) -> str:
		return f"<WorkOrderLabor wo={self.wo_id} employee={self.employee_id} craft={self.craft!r}>"


# ---------------------------------------------------------------------------
# WorkOrderPart
# ---------------------------------------------------------------------------

class WorkOrderPart(Model):
	"""Parts / materials consumed on a work order."""

	__allow_unmapped__ = True
	__tablename__ = "eam_wo_part"
	__table_args__ = (
		Index("ix_eam_part_wo", "wo_id"),
		CheckConstraint(
			"sourced_from IN ('STOCK','PURCHASE','WARRANTY')",
			name="ck_eam_part_sourced_from",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	wo_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_work_order.id"),
		nullable=False,
		index=True,
	)
	part_code = Column(String(30), nullable=False)
	part_name = Column(String(100), nullable=False)
	quantity = Column(Numeric(8, 2), nullable=False)
	unit_cost_cents = Column(Integer, nullable=False, default=0)
	total_cost_cents = Column(BigInteger, nullable=False, default=0)
	sourced_from = Column(String(10), nullable=False, default="STOCK")

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

	work_order: MaintenanceWorkOrder = relationship(
		"MaintenanceWorkOrder", back_populates="part_lines", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<WorkOrderPart wo={self.wo_id} {self.part_code!r} qty={self.quantity}>"


# ---------------------------------------------------------------------------
# SafetyPermit
# ---------------------------------------------------------------------------

class SafetyPermit(AuditMixin, Model):
	"""Work permit required before high-risk work orders can proceed.

	permit_type : HOT_WORK | CONFINED_SPACE | ELECTRICAL | HEIGHT | CHEMICAL | GENERAL
	status      : ISSUED → ACTIVE → SUSPENDED | CLOSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_safety_permit"
	__table_args__ = (
		Index("ix_eam_permit_wo", "wo_id"),
		Index("ix_eam_permit_status", "status"),
		CheckConstraint(
			"permit_type IN ('HOT_WORK','CONFINED_SPACE','ELECTRICAL','HEIGHT','CHEMICAL','GENERAL')",
			name="ck_eam_permit_type",
		),
		CheckConstraint(
			"status IN ('ISSUED','ACTIVE','SUSPENDED','CLOSED')",
			name="ck_eam_permit_status",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	wo_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_work_order.id"),
		nullable=False,
		index=True,
	)
	permit_type = Column(String(20), nullable=False)
	issued_by = Column(UUID(as_uuid=False), nullable=False, comment="Employee UUID")
	issued_at = Column(DateTime(timezone=True), nullable=False)
	expires_at = Column(DateTime(timezone=True), nullable=False)
	conditions = Column(Text, nullable=True)
	status = Column(String(10), nullable=False, default="ISSUED")

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

	work_order: MaintenanceWorkOrder = relationship(
		"MaintenanceWorkOrder", back_populates="safety_permits", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<SafetyPermit {self.permit_type!r} wo={self.wo_id} [{self.status}]>"


# ---------------------------------------------------------------------------
# FailureReport
# ---------------------------------------------------------------------------

class FailureReport(AuditMixin, Model):
	"""Records of asset failures — feeds MTBF / reliability analytics.

	wo_id is nullable because failures can be reported before a WO is raised
	(e.g. operator log entry that eventually spawns a corrective WO).
	"""

	__allow_unmapped__ = True
	__tablename__ = "eam_failure_report"
	__table_args__ = (
		Index("ix_eam_failure_asset", "asset_id"),
		Index("ix_eam_failure_reported_at", "reported_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_managed_asset.id"),
		nullable=False,
		index=True,
	)
	wo_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eam_work_order.id"),
		nullable=True,
		index=True,
	)
	reported_by = Column(UUID(as_uuid=False), nullable=False, comment="Employee UUID")
	reported_at = Column(DateTime(timezone=True), nullable=False)
	failure_description = Column(Text, nullable=False)
	failure_code = Column(String(20), nullable=False)
	cause_code = Column(String(20), nullable=False)

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

	asset: ManagedAsset = relationship(
		"ManagedAsset", back_populates="failure_reports", lazy="select"
	)
	work_order: MaintenanceWorkOrder | None = relationship(
		"MaintenanceWorkOrder", back_populates="failure_reports", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<FailureReport asset={self.asset_id} code={self.failure_code!r} @ {self.reported_at}>"


__all__ = [
	"AssetLocation",
	"ManagedAsset",
	"MeterReading",
	"JobPlan",
	"MaintenancePlan",
	"MaintenanceWorkOrder",
	"WorkOrderLabor",
	"WorkOrderPart",
	"SafetyPermit",
	"FailureReport",
]
