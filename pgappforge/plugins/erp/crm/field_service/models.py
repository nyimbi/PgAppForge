"""
pgappforge/plugins/erp/crm/field_service/models.py

SQLAlchemy models for the Field Service plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - PostGIS GEOMETRY types via Geoalchemy2 when available; falls back to JSONB
  - JSONB for skills, availability, parts_used, address, proposed_slots
  - lazy='select' throughout (SA 2.x)

Table prefix: fs_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
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


# ---------------------------------------------------------------------------
# ServiceTerritory
# ---------------------------------------------------------------------------

class ServiceTerritory(AuditMixin, Model):
	"""Geographic service territory managed by a field service team."""

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

	def __repr__(self) -> str:
		return f"<ServiceResource employee={self.employee_id!r} territory={self.territory_id!r}>"


# ---------------------------------------------------------------------------
# WorkOrder
# ---------------------------------------------------------------------------

class WorkOrder(RulesMixin, AuditMixin, Model):
	"""Field service work order — tracks scheduling and execution of on-site work."""

	__allow_unmapped__ = True
	__tablename__ = "fs_work_order"
	__table_args__ = (
		UniqueConstraint("tenant_id", "work_order_number", name="uq_fs_wo_tenant_number"),
		Index("ix_fs_wo_tenant", "tenant_id"),
		Index("ix_fs_wo_account", "account_id"),
		Index("ix_fs_wo_status", "status"),
		Index("ix_fs_wo_assigned", "assigned_to"),
		Index("ix_fs_wo_scheduled_start", "scheduled_start"),
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

	# Work details
	work_type = Column(
		String(20),
		nullable=False,
		comment="INSTALL|REPAIR|MAINTENANCE|INSPECTION",
	)
	scheduled_start = Column(DateTime(timezone=True), nullable=True, index=True)
	scheduled_end = Column(DateTime(timezone=True), nullable=True)
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
		comment='Array of {sku, qty, unit_cost_cents} dicts',
	)
	labor_minutes = Column(Integer, nullable=True, comment="Actual labor time in minutes")
	completion_notes = Column(Text, nullable=True)

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
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ServiceTerritory",
	"ServiceResource",
	"WorkOrder",
	"ServiceAppointment",
]
