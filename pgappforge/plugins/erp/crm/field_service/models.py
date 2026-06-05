"""
pgappforge/plugins/erp/crm/field_service/models.py

SQLAlchemy models for the Field Service plugin — world-class FSM beyond
Salesforce Field Service, ServiceMax, IFS FSM, and FieldAware.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - All monetary amounts: INTEGER CENTS stored in BigInteger — never float/Decimal
  - PostGIS GEOMETRY types via Geoalchemy2 when available; falls back to JSONB
  - JSONB for skills, availability, parts_used, address, proposed_slots, templates
  - lazy='select' throughout (SA 2.x)

Table prefix: fs_
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
from pgappforge.plugins.rules.mixin import RulesMixin

# Geoalchemy2 is optional — gracefully degrade to JSONB geometry storage
try:
	from geoalchemy2 import Geometry as _Geometry  # type: ignore[import]
	_HAVE_GEO = True
except ImportError:
	_Geometry = None  # type: ignore[assignment,misc]
	_HAVE_GEO = False


def _uuid4() -> str:
	return str(uuid.uuid4())


def _geo_column(geom_type: str, srid: int = 4326) -> Column:
	"""Return a Geometry column or a JSONB fallback when Geoalchemy2 is absent."""
	if _HAVE_GEO:
		return Column(_Geometry(geom_type, srid=srid), nullable=True)
	return Column(JSONB, nullable=True, comment=f"GeoJSON {geom_type} (Geoalchemy2 not installed)")


# ---------------------------------------------------------------------------
# Work order status / type enumerations
# ---------------------------------------------------------------------------

WORK_TYPE = ("INSTALL", "REPAIR", "MAINTENANCE", "INSPECTION")
WORK_ORDER_STATUS = ("DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
APPOINTMENT_STATUS = ("PENDING", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")
CONTRACT_TYPE = ("SILVER", "GOLD", "PLATINUM", "CUSTOM")
CONTRACT_STATUS = ("ACTIVE", "EXPIRED", "CANCELLED", "DRAFT")
MAINTENANCE_PLAN_TYPE = ("CALENDAR", "METER", "CONDITION")
PART_SOURCE = ("VAN_STOCK", "WAREHOUSE", "DIRECT_PURCHASE")
DISPATCH_EVENT_TYPE = ("ASSIGNED", "EN_ROUTE", "ON_SITE", "PAUSED", "COMPLETED")


# ---------------------------------------------------------------------------
# ServiceTerritory
# ---------------------------------------------------------------------------

class ServiceTerritory(AuditMixin, Model):
	"""Geographic service territory managed by a field service team.

	Boundaries stored as PostGIS POLYGON(4326) when Geoalchemy2 is installed,
	or JSONB GeoJSON when it is not.  Territory managers are referenced by
	employee_id so no hard FK dependency on HR models is required.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_service_territory"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_fs_territory_tenant_name"),
		Index("ix_fs_territory_tenant", "tenant_id"),
		Index("ix_fs_territory_manager", "manager_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	manager_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK Employee.id — territory manager",
	)
	# GEOMETRY(POLYGON,4326) — Geoalchemy2 or JSONB fallback
	boundary: Any = _geo_column("POLYGON")

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

	resources: list[ServiceResource] = relationship(
		"ServiceResource",
		back_populates="territory",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ServiceTerritory {self.name!r}>"


# ---------------------------------------------------------------------------
# ServiceResource
# ---------------------------------------------------------------------------

class ServiceResource(AuditMixin, Model):
	"""A field technician / engineer assignable to work orders.

	skills: JSONB dict e.g. {"electrical": 3, "plumbing": 2}
	availability: JSONB weekly schedule e.g. {"mon": ["08:00","17:00"], ...}

	Detailed per-skill records with certification tracking live in
	TechnicianSkill (one row per skill/technician pair).
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_service_resource"
	__table_args__ = (
		UniqueConstraint("tenant_id", "employee_id", name="uq_fs_resource_tenant_employee"),
		Index("ix_fs_resource_tenant", "tenant_id"),
		Index("ix_fs_resource_territory", "territory_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK Employee.id",
	)
	territory_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_service_territory.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	skills: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment='Skill name → proficiency level, e.g. {"hvac": 3}',
	)
	availability: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment='Weekly schedule e.g. {"mon": ["08:00","17:00"]}',
	)
	capacity_per_day = Column(
		Integer,
		nullable=False,
		default=1,
		server_default="1",
		comment="Max work orders per day",
	)
	# Hourly rate in cents for labor cost calculations
	hourly_rate_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="Technician billable rate in cents per hour",
	)
	# Last known location for proximity-based dispatch
	last_known_lat = Column(Numeric(9, 6), nullable=True, comment="Last GPS latitude")
	last_known_lng = Column(Numeric(9, 6), nullable=True, comment="Last GPS longitude")
	last_location_at = Column(DateTime(timezone=True), nullable=True)

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

	territory: ServiceTerritory = relationship("ServiceTerritory", back_populates="resources", lazy="select")
	work_orders: list[WorkOrder] = relationship(
		"WorkOrder",
		back_populates="assigned_resource",
		lazy="select",
	)
	technician_skills: list[TechnicianSkill] = relationship(
		"TechnicianSkill",
		back_populates="resource",
		cascade="all, delete-orphan",
		lazy="select",
	)
	dispatch_logs: list[DispatchLog] = relationship(
		"DispatchLog",
		back_populates="resource",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ServiceResource employee={self.employee_id!r} territory={self.territory_id!r}>"


# ---------------------------------------------------------------------------
# ServiceLevel
# ---------------------------------------------------------------------------

class ServiceLevel(AuditMixin, Model):
	"""SLA tier definition — named response/resolution/on-site time targets
	with automatic escalation thresholds and penalty rates.

	Example tiers: Bronze (8h response), Silver (4h), Gold (2h), Platinum (1h).
	Penalty rates are applied when the resolution clock is breached.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_service_level"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_fs_service_level_tenant_name"),
		Index("ix_fs_service_level_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(80), nullable=False, comment="e.g. Gold, Platinum, 4-Hour Response")
	response_hours = Column(
		Numeric(8, 2),
		nullable=False,
		comment="Target hours from work order creation to first technician response",
	)
	resolution_hours = Column(
		Numeric(8, 2),
		nullable=False,
		comment="Target hours from creation to work order completion",
	)
	on_site_hours = Column(
		Numeric(8, 2),
		nullable=True,
		comment="Target hours from creation to technician arriving on site",
	)
	penalty_cents_per_hour = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="Penalty in cents per hour beyond resolution_hours",
	)
	escalation_at_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=80,
		server_default="80",
		comment="Escalate when this percentage of resolution SLA has elapsed (0-100)",
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

	contracts: list[ServiceContract] = relationship(
		"ServiceContract",
		back_populates="service_level",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ServiceLevel {self.name!r} resp={self.response_hours}h>"


# ---------------------------------------------------------------------------
# ServiceContract
# ---------------------------------------------------------------------------

class ServiceContract(AuditMixin, Model):
	"""Customer service contract — entitlements, SLA commitments, and covered
	assets per customer.

	Silver/Gold/Platinum/Custom tiers link to a ServiceLevel for actual SLA
	thresholds.  covered_assets is a JSONB array of asset-id strings so no
	hard FK dependency on a separate asset registry is required.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_service_contract"
	__table_args__ = (
		Index("ix_fs_contract_tenant", "tenant_id"),
		Index("ix_fs_contract_customer", "customer_id"),
		Index("ix_fs_contract_status", "status"),
		Index("ix_fs_contract_end_date", "end_date"),
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
		nullable=False,
		index=True,
		comment="FK SalesAccount.id or Party.id",
	)
	service_level_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_service_level.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	contract_type = Column(
		String(20),
		nullable=False,
		default="SILVER",
		server_default="SILVER",
		comment="SILVER|GOLD|PLATINUM|CUSTOM",
	)
	# SLA overrides — if set these take precedence over the linked ServiceLevel
	sla_response_hours = Column(
		Numeric(8, 2),
		nullable=True,
		comment="Override response SLA hours (falls back to service_level if NULL)",
	)
	sla_resolution_hours = Column(
		Numeric(8, 2),
		nullable=True,
		comment="Override resolution SLA hours (falls back to service_level if NULL)",
	)
	max_visits_per_year = Column(
		Integer,
		nullable=True,
		comment="Maximum on-site visits included; NULL = unlimited",
	)
	visits_used_this_year = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Counter of visits consumed in the current contract year",
	)
	covered_assets: Any = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="Array of asset-id strings covered by this contract",
	)
	covered_service_types: Any = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default='["REPAIR","MAINTENANCE","INSPECTION","INSTALL"]',
		comment="Work-type strings this contract covers",
	)
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT|ACTIVE|EXPIRED|CANCELLED",
	)
	auto_renew = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
		comment="Automatically renew on end_date",
	)
	# Contract financial value
	value_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="Total contract value in cents",
	)
	currency_code = Column(String(3), nullable=False, default="USD", server_default="'USD'")
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

	service_level: ServiceLevel | None = relationship(
		"ServiceLevel",
		back_populates="contracts",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ServiceContract customer={self.customer_id!r} type={self.contract_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# WorkOrder
# ---------------------------------------------------------------------------

class WorkOrder(RulesMixin, AuditMixin, Model):
	"""Field service work order — tracks scheduling and execution of on-site work.

	Links optionally to a ServiceContract for SLA tracking and entitlement
	verification.  The failure_code field enables failure-mode analytics for
	repeat-visit reduction (Salesforce FSL parity).
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_work_order"
	__table_args__ = (
		UniqueConstraint("tenant_id", "work_order_number", name="uq_fs_wo_tenant_number"),
		Index("ix_fs_wo_tenant", "tenant_id"),
		Index("ix_fs_wo_account", "account_id"),
		Index("ix_fs_wo_status", "status"),
		Index("ix_fs_wo_assigned", "assigned_to"),
		Index("ix_fs_wo_scheduled_start", "scheduled_start"),
		Index("ix_fs_wo_contract", "contract_id"),
		Index("ix_fs_wo_maintenance_plan", "maintenance_plan_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"status", "assigned_to", "scheduled_start", "scheduled_end",
		"labor_minutes", "parts_used",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	work_order_number = Column(String(30), nullable=False)

	# Links
	case_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_case.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Optional link to originating Service Case",
	)
	account_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK SalesAccount.id")
	contact_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK SalesContact.id")
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_service_contract.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Active ServiceContract governing SLA for this work order",
	)
	maintenance_plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_maintenance_plan.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Set when WO was auto-generated by a FSMaintenancePlan",
	)

	# Work details
	work_type = Column(
		String(20),
		nullable=False,
		comment="INSTALL|REPAIR|MAINTENANCE|INSPECTION",
	)
	failure_code = Column(
		String(40),
		nullable=True,
		comment="Standard failure/fault code for analytics (e.g. LEAK, MOTOR_BURNOUT)",
	)
	priority = Column(
		Integer,
		nullable=False,
		default=3,
		server_default="3",
		comment="1=Critical 2=High 3=Normal 4=Low",
	)
	scheduled_start = Column(DateTime(timezone=True), nullable=True, index=True)
	scheduled_end = Column(DateTime(timezone=True), nullable=True)
	actual_start = Column(DateTime(timezone=True), nullable=True)
	actual_end = Column(DateTime(timezone=True), nullable=True)
	assigned_to = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_service_resource.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT|SCHEDULED|IN_PROGRESS|COMPLETED|CANCELLED",
	)

	# Location — GEOMETRY(Point,4326) or JSONB fallback
	location: Any = _geo_column("POINT")
	address: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment='Structured address snapshot e.g. {"street": "...", "city": "..."}',
	)

	# Execution details
	parts_used: Any = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment='Array of {sku, qty, unit_cost_cents} dicts (legacy; use FSWorkOrderPart rows)',
	)
	labor_minutes = Column(Integer, nullable=True, comment="Actual labor time in minutes")
	completion_notes = Column(Text, nullable=True)

	# SLA breach tracking (denormalised for fast dashboard queries)
	response_breached = Column(Boolean, nullable=False, default=False, server_default="false")
	resolution_breached = Column(Boolean, nullable=False, default=False, server_default="false")

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

	assigned_resource: ServiceResource = relationship(
		"ServiceResource",
		back_populates="work_orders",
		lazy="select",
	)
	appointments: list[ServiceAppointment] = relationship(
		"ServiceAppointment",
		back_populates="work_order",
		cascade="all, delete-orphan",
		lazy="select",
	)
	parts: list[FSWorkOrderPart] = relationship(
		"FSWorkOrderPart",
		back_populates="work_order",
		cascade="all, delete-orphan",
		lazy="select",
	)
	dispatch_logs: list[DispatchLog] = relationship(
		"DispatchLog",
		back_populates="work_order",
		cascade="all, delete-orphan",
		lazy="select",
	)
	feedback: list[CustomerFeedback] = relationship(
		"CustomerFeedback",
		back_populates="work_order",
		cascade="all, delete-orphan",
		lazy="select",
	)
	contract: ServiceContract | None = relationship(
		"ServiceContract",
		foreign_keys=[contract_id],
		lazy="select",
	)
	maintenance_plan: FSMaintenancePlan | None = relationship(
		"FSMaintenancePlan",
		foreign_keys=[maintenance_plan_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<WorkOrder {self.work_order_number!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ServiceAppointment
# ---------------------------------------------------------------------------

class ServiceAppointment(AuditMixin, Model):
	"""Customer-facing appointment booking for a work order.

	confirmed_slot is a TSTZRANGE (stored as JSONB {start, end} when
	psycopg2-binary range types not available).
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_service_appointment"
	__table_args__ = (
		Index("ix_fs_appt_work_order", "work_order_id"),
		Index("ix_fs_appt_tenant", "tenant_id"),
		Index("ix_fs_appt_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	work_order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_work_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	contact_id = Column(UUID(as_uuid=False), nullable=True, index=True)

	# Proposed and confirmed slots
	proposed_slots: Any = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment='Array of {start, end} ISO datetime pairs offered to customer',
	)
	# confirmed_slot: TSTZRANGE stored as JSONB {start, end}
	confirmed_slot: Any = Column(
		JSONB,
		nullable=True,
		comment='Confirmed time slot: {"start": "<iso>", "end": "<iso>"}',
	)

	confirmation_sent_at = Column(DateTime(timezone=True), nullable=True)
	reminder_sent_at = Column(DateTime(timezone=True), nullable=True)
	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		server_default="PENDING",
		comment="PENDING|CONFIRMED|COMPLETED|CANCELLED|NO_SHOW",
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

	work_order: WorkOrder = relationship("WorkOrder", back_populates="appointments", lazy="select")

	def __repr__(self) -> str:
		return f"<ServiceAppointment wo={self.work_order_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# FSWorkOrderPart
# ---------------------------------------------------------------------------

class FSWorkOrderPart(AuditMixin, Model):
	"""Individual part/material line on a work order.

	Replaces the legacy parts_used JSONB array with a proper normalised row
	that supports van-stock, warehouse, and direct-purchase sourcing.  All
	monetary columns are integer cents (BigInteger).
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_work_order_part"
	__table_args__ = (
		Index("ix_fs_wo_part_work_order", "work_order_id"),
		Index("ix_fs_wo_part_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	work_order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_work_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	part_code = Column(String(60), nullable=False, comment="SKU or internal part code")
	part_name = Column(String(200), nullable=False)
	quantity = Column(Numeric(12, 4), nullable=False, default=1)
	unit_cost_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="Per-unit cost in cents",
	)
	total_cost_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="quantity × unit_cost_cents, stored for fast aggregation",
	)
	source = Column(
		String(20),
		nullable=False,
		default="VAN_STOCK",
		server_default="'VAN_STOCK'",
		comment="VAN_STOCK|WAREHOUSE|DIRECT_PURCHASE",
	)
	issued_at = Column(DateTime(timezone=True), nullable=True)

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

	work_order: WorkOrder = relationship("WorkOrder", back_populates="parts", lazy="select")

	def __repr__(self) -> str:
		return f"<FSWorkOrderPart {self.part_code!r} qty={self.quantity} wo={self.work_order_id!r}>"


# ---------------------------------------------------------------------------
# FSMaintenancePlan
# ---------------------------------------------------------------------------

class FSMaintenancePlan(AuditMixin, Model):
	"""Preventive maintenance plan that auto-generates work orders on a schedule.

	Supports three trigger modes:
	  CALENDAR  — fire every interval_days calendar days
	  METER     — fire every interval_units meter/cycle increments (requires
	              external meter reading updates to next_due_at)
	  CONDITION — fire when monitored condition exceeds threshold (handled
	              externally by updating next_due_at)

	work_order_template is a JSONB dict of default WorkOrder field values
	(work_type, priority, address, failure_code, contact_id, etc.) used when
	auto-generating work orders.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_maintenance_plan"
	__table_args__ = (
		Index("ix_fs_mp_tenant", "tenant_id"),
		Index("ix_fs_mp_asset", "asset_id"),
		Index("ix_fs_mp_next_due", "next_due_at"),
		Index("ix_fs_mp_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	asset_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="Optional FK to asset registry; NULL means plan applies to an asset type",
	)
	asset_type = Column(
		String(100),
		nullable=True,
		comment="Asset class/type when asset_id is not specified",
	)
	name = Column(String(200), nullable=False)
	plan_type = Column(
		String(20),
		nullable=False,
		default="CALENDAR",
		server_default="'CALENDAR'",
		comment="CALENDAR|METER|CONDITION",
	)
	interval_days = Column(
		Integer,
		nullable=True,
		comment="Days between triggers for CALENDAR plans",
	)
	interval_units = Column(
		Integer,
		nullable=True,
		comment="Meter/cycle units between triggers for METER plans",
	)
	last_triggered_at = Column(DateTime(timezone=True), nullable=True)
	next_due_at = Column(DateTime(timezone=True), nullable=True, index=True)
	work_order_template: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Default WorkOrder fields: work_type, priority, address, contact_id, etc.",
	)
	is_active = Column(
		Boolean,
		nullable=False,
		default=True,
		server_default="true",
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
		return f"<FSMaintenancePlan {self.name!r} type={self.plan_type!r} next_due={self.next_due_at}>"


# ---------------------------------------------------------------------------
# TechnicianSkill
# ---------------------------------------------------------------------------

class TechnicianSkill(AuditMixin, Model):
	"""Normalised per-skill record for a ServiceResource with certification tracking.

	Complements the JSONB skills summary on ServiceResource with expiry dates,
	certification evidence, and structured proficiency levels (1-5 scale).
	Used by the smart dispatch algorithm (find_best_technician) for accurate
	skill-match scoring.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_technician_skill"
	__table_args__ = (
		UniqueConstraint("resource_id", "skill_code", name="uq_fs_tech_skill_resource_code"),
		Index("ix_fs_tech_skill_resource", "resource_id"),
		Index("ix_fs_tech_skill_tenant", "tenant_id"),
		Index("ix_fs_tech_skill_code", "skill_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	resource_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_service_resource.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	skill_code = Column(String(30), nullable=False, comment="Standardised skill identifier e.g. HVAC_REPAIR")
	proficiency = Column(
		Integer,
		nullable=False,
		default=1,
		server_default="1",
		comment="1=Novice 2=Beginner 3=Competent 4=Proficient 5=Expert",
	)
	certified_at = Column(Date, nullable=True)
	expires_at = Column(Date, nullable=True, comment="NULL means certification does not expire")

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

	resource: ServiceResource = relationship("ServiceResource", back_populates="technician_skills", lazy="select")

	def __repr__(self) -> str:
		return f"<TechnicianSkill resource={self.resource_id!r} skill={self.skill_code!r} prof={self.proficiency}>"


# ---------------------------------------------------------------------------
# DispatchLog
# ---------------------------------------------------------------------------

class DispatchLog(AuditMixin, Model):
	"""Immutable timeline of dispatch events for a work order / technician.

	Every state transition (ASSIGNED, EN_ROUTE, ON_SITE, PAUSED, COMPLETED)
	is recorded here with GPS coordinates when available.  This feeds the
	real-time map view and SLA breach detection.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_dispatch_log"
	__table_args__ = (
		Index("ix_fs_dispatch_work_order", "work_order_id"),
		Index("ix_fs_dispatch_resource", "resource_id"),
		Index("ix_fs_dispatch_tenant", "tenant_id"),
		Index("ix_fs_dispatch_event_at", "event_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	work_order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_work_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	resource_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_service_resource.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	event_type = Column(
		String(20),
		nullable=False,
		comment="ASSIGNED|EN_ROUTE|ON_SITE|PAUSED|COMPLETED",
	)
	event_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		index=True,
	)
	location_lat = Column(Numeric(9, 6), nullable=True)
	location_lng = Column(Numeric(9, 6), nullable=True)
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

	work_order: WorkOrder = relationship("WorkOrder", back_populates="dispatch_logs", lazy="select")
	resource: ServiceResource | None = relationship("ServiceResource", back_populates="dispatch_logs", lazy="select")

	def __repr__(self) -> str:
		return f"<DispatchLog wo={self.work_order_id!r} event={self.event_type!r} at={self.event_at}>"


# ---------------------------------------------------------------------------
# CustomerFeedback
# ---------------------------------------------------------------------------

class CustomerFeedback(AuditMixin, Model):
	"""Post-service customer satisfaction record (CSAT + NPS).

	Collected after work order completion.  NPS score (0-10 promoter scale)
	is separate from the 1-5 service rating so both metrics can be tracked
	independently.  Drives the get_service_dashboard CSAT and NPS KPIs.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fs_customer_feedback"
	__table_args__ = (
		UniqueConstraint("work_order_id", name="uq_fs_feedback_work_order"),
		Index("ix_fs_feedback_tenant", "tenant_id"),
		Index("ix_fs_feedback_work_order", "work_order_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	work_order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fs_work_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
		unique=True,
	)
	rating = Column(
		Integer,
		nullable=False,
		comment="1-5 CSAT rating",
	)
	comments = Column(Text, nullable=True)
	submitted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	nps_score = Column(
		Integer,
		nullable=True,
		comment="Net Promoter Score 0-10; NULL when not collected",
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

	work_order: WorkOrder = relationship("WorkOrder", back_populates="feedback", lazy="select")

	def __repr__(self) -> str:
		return f"<CustomerFeedback wo={self.work_order_id!r} rating={self.rating} nps={self.nps_score}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ServiceTerritory",
	"ServiceResource",
	"ServiceLevel",
	"ServiceContract",
	"WorkOrder",
	"ServiceAppointment",
	"FSWorkOrderPart",
	"FSMaintenancePlan",
	"TechnicianSkill",
	"DispatchLog",
	"CustomerFeedback",
	# Constants
	"WORK_TYPE",
	"WORK_ORDER_STATUS",
	"APPOINTMENT_STATUS",
	"CONTRACT_TYPE",
	"CONTRACT_STATUS",
	"MAINTENANCE_PLAN_TYPE",
	"PART_SOURCE",
	"DISPATCH_EVENT_TYPE",
]
