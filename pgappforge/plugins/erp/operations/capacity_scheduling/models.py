"""
pgappforge/plugins/erp/operations/capacity_scheduling/models.py

SQLAlchemy models for the Finite Capacity Scheduling plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - ALL monetary amounts: BigInteger cents (NEVER Numeric/float for money)
  - ALL models: tenant_id VARCHAR(50) NOT NULL
  - Soft FKs only across plugin boundaries (VARCHAR)
  - PostgreSQL: JSONB, TIMESTAMPTZ, Numeric for quantities

Table prefix: csc_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	CheckConstraint,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# WorkCenter
# ---------------------------------------------------------------------------

class WorkCenter(AuditMixin, Model):
	"""A production work center with finite daily capacity.

	capacity_hours_per_day × efficiency_pct = net available hours per working day.
	calendar is a JSONB list of active weekday integers (0=Mon … 6=Sun).
	setup_time_hours is deducted from available hours before loading.

	entity_id is optional multi-entity scoping.
	"""

	__allow_unmapped__ = True
	__tablename__ = "csc_work_center"
	__table_args__ = (
		Index("ix_csc_wc_tenant_entity", "tenant_id", "entity_id"),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	code = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Unique work center code per tenant",
	)
	name = Column(String(200), nullable=False)

	capacity_hours_per_day = Column(
		Numeric(8, 4),
		nullable=False,
		default=sa.text("8.0"),
		comment="Nominal capacity hours per working day",
	)
	efficiency_pct = Column(
		Numeric(6, 4),
		nullable=False,
		default=sa.text("1.0"),
		comment="Efficiency factor 0–1; net_hours = capacity × efficiency",
	)
	calendar = Column(
		JSONB,
		nullable=False,
		default=lambda: [0, 1, 2, 3, 4],
		server_default=sa.text("'[0,1,2,3,4]'::jsonb"),
		comment="Active weekday indices: 0=Mon, 1=Tue, …, 6=Sun",
	)
	setup_time_hours = Column(
		Numeric(6, 4),
		nullable=False,
		default=sa.text("0"),
		comment="Fixed setup time deducted from available capacity each day",
	)

	entity_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Multi-entity scoping; soft FK to entity registry",
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
	capacity_loads: list[CapacityLoad] = relationship(
		"CapacityLoad",
		back_populates="work_center",
		cascade="all, delete-orphan",
		lazy="select",
	)
	schedules: list[ProductionSchedule] = relationship(
		"ProductionSchedule",
		back_populates="work_center",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<WorkCenter id={self.id!r} code={self.code!r} name={self.name!r}>"


# ---------------------------------------------------------------------------
# CapacityLoad
# ---------------------------------------------------------------------------

class CapacityLoad(AuditMixin, Model):
	"""Daily capacity load record for a work center.

	One row per (work_center, date).  loaded_hours grows as orders are scheduled;
	utilization_pct = loaded_hours / available_hours × 100.
	"""

	__allow_unmapped__ = True
	__tablename__ = "csc_capacity_load"
	__table_args__ = (
		UniqueConstraint("work_center_id", "load_date", name="uq_csc_capacity_load_wc_date"),
		Index("ix_csc_capacity_load_wc_date", "work_center_id", "load_date"),
		Index("ix_csc_capacity_load_tenant_date", "tenant_id", "load_date"),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	work_center_id = Column(
		String(50),
		ForeignKey("csc_work_center.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	load_date = Column(Date, nullable=False, comment="The calendar date this load row covers")
	loaded_hours = Column(
		Numeric(8, 4),
		nullable=False,
		default=sa.text("0"),
		comment="Total hours loaded by scheduled production orders",
	)
	available_hours = Column(
		Numeric(8, 4),
		nullable=False,
		comment="Net available hours: capacity × efficiency − setup_time",
	)
	utilization_pct = Column(
		Numeric(8, 4),
		nullable=False,
		default=sa.text("0"),
		comment="loaded_hours / available_hours × 100",
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
	work_center: WorkCenter = relationship(
		"WorkCenter",
		back_populates="capacity_loads",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CapacityLoad wc={self.work_center_id!r} date={self.load_date} "
			f"util={self.utilization_pct}%>"
		)


# ---------------------------------------------------------------------------
# ProductionSchedule
# ---------------------------------------------------------------------------

class ProductionSchedule(AuditMixin, Model):
	"""A scheduled block of production time on a work center.

	production_order_id is a soft FK to any production order system.
	priority: 1 = highest urgency, larger = lower priority.
	"""

	__allow_unmapped__ = True
	__tablename__ = "csc_schedule"
	__table_args__ = (
		Index("ix_csc_schedule_wc_start", "work_center_id", "start_datetime"),
		Index("ix_csc_schedule_order", "production_order_id"),
		Index("ix_csc_schedule_tenant_status", "tenant_id", "status"),
		CheckConstraint(
			"status IN ('PLANNED','CONFIRMED','COMPLETED','CANCELLED')",
			name="ck_csc_schedule_status",
		),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	production_order_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK to production order system",
	)
	work_center_id = Column(
		String(50),
		ForeignKey("csc_work_center.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	start_datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		comment="Scheduled start of production block",
	)
	end_datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		comment="Scheduled end of production block",
	)
	required_hours = Column(
		Numeric(8, 4),
		nullable=False,
		comment="Hours required to complete this production order",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PLANNED",
		comment="PLANNED | CONFIRMED | COMPLETED | CANCELLED",
	)
	priority = Column(
		Integer,
		nullable=False,
		default=5,
		comment="Scheduling priority: 1=highest, 10=lowest",
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
	work_center: WorkCenter = relationship(
		"WorkCenter",
		back_populates="schedules",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ProductionSchedule id={self.id!r} order={self.production_order_id!r} "
			f"wc={self.work_center_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"WorkCenter",
	"CapacityLoad",
	"ProductionSchedule",
]
