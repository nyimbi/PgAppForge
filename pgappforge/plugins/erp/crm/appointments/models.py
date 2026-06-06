"""
pgappforge/plugins/erp/crm/appointments/models.py

SQLAlchemy models for the Appointments/Booking plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: Integer CENTS — never float/Decimal
  - PostgreSQL ONLY — JSONB, UUID, DateTime(timezone=True)
  - lazy='select' throughout (SA 2.x)

Table prefix: apt_
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
	String,
	Text,
	Time,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Status enumerations
# ---------------------------------------------------------------------------

APPOINTMENT_STATUS = ("PENDING", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")


# ---------------------------------------------------------------------------
# AppointmentService
# ---------------------------------------------------------------------------

class AppointmentService(AuditMixin, Model):
	"""A bookable service offered by the organisation.

	duration_minutes is the actual service time; buffer_minutes is dead-time
	after the appointment before the staff member is available again.
	price_cents stored as integer cents with currency_code.
	eligible_staff_ids: empty list = all staff are eligible.
	max_advance_days / min_advance_hours gate how far out (and how soon)
	customers can book.
	"""

	__allow_unmapped__ = True
	__tablename__ = "apt_service"
	__table_args__ = (
		Index("ix_apt_service_tenant_active", "tenant_id", "is_active"),
		Index("ix_apt_service_tenant_category", "tenant_id", "category"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(300), nullable=False)
	description = Column(Text, nullable=True)
	duration_minutes = Column(Integer, nullable=False, default=60, server_default="60")
	buffer_minutes = Column(Integer, nullable=False, default=0, server_default="0",
		comment="Dead-time buffer after the appointment before staff is free again")
	price_cents = Column(Integer, nullable=False, default=0, server_default="0")
	currency_code = Column(String(3), nullable=False, default="KES")
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")
	category = Column(String(100), nullable=True)
	max_advance_days = Column(Integer, nullable=False, default=90, server_default="90",
		comment="How many days in advance a booking can be made")
	min_advance_hours = Column(Integer, nullable=False, default=24, server_default="24",
		comment="Minimum hours notice before appointment start")
	eligible_staff_ids = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="List of staff_id strings; empty = all staff eligible",
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

	appointments: list[Appointment] = relationship(
		"Appointment",
		back_populates="service",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<AppointmentService {self.name!r} duration={self.duration_minutes}min>"


# ---------------------------------------------------------------------------
# StaffAvailability
# ---------------------------------------------------------------------------

class StaffAvailability(AuditMixin, Model):
	"""Recurring weekly availability window for a staff member.

	day_of_week: 0=Monday … 6=Sunday (ISO convention).
	effective_from / effective_to allow scheduling future availability changes.
	entity_id optionally scopes availability to a location or branch.
	"""

	__allow_unmapped__ = True
	__tablename__ = "apt_availability"
	__table_args__ = (
		Index("ix_apt_availability_staff_day", "staff_id", "day_of_week"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	staff_id = Column(String(50), nullable=False, index=True)
	day_of_week = Column(Integer, nullable=False,
		comment="0=Monday, 6=Sunday")
	start_time = Column(Time, nullable=False)
	end_time = Column(Time, nullable=False)
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")
	effective_from = Column(Date, nullable=True)
	effective_to = Column(Date, nullable=True)
	entity_id = Column(String(50), nullable=True,
		comment="Optional location/branch scoping")

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
		days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
		day_name = days[self.day_of_week] if self.day_of_week is not None else "?"
		return (
			f"<StaffAvailability staff={self.staff_id!r} "
			f"{day_name} {self.start_time}–{self.end_time}>"
		)


# ---------------------------------------------------------------------------
# StaffBlockedSlot
# ---------------------------------------------------------------------------

class StaffBlockedSlot(AuditMixin, Model):
	"""An explicit blocked period during which a staff member is unavailable.

	Used for holidays, training, sickness, or any ad-hoc unavailability.
	Overlaps between blocked_from/blocked_to are checked during slot calculation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "apt_blocked_slot"
	__table_args__ = (
		Index("ix_apt_blocked_slot_staff_from", "staff_id", "blocked_from"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	staff_id = Column(String(50), nullable=False, index=True)
	blocked_from = Column(DateTime(timezone=True), nullable=False)
	blocked_to = Column(DateTime(timezone=True), nullable=False)
	reason = Column(Text, nullable=True)

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
			f"<StaffBlockedSlot staff={self.staff_id!r} "
			f"{self.blocked_from}–{self.blocked_to}>"
		)


# ---------------------------------------------------------------------------
# Appointment
# ---------------------------------------------------------------------------

class Appointment(AuditMixin, Model):
	"""A confirmed time-slot booking between a customer and a staff member.

	service_id SET NULL on delete — appointment history is preserved even
	if a service is retired.
	booking_ref is a short human-readable reference unique per tenant.
	amount_cents / currency_code reflect the price charged at booking time
	(may differ from the service list price after discounts).
	"""

	__allow_unmapped__ = True
	__tablename__ = "apt_appointment"
	__table_args__ = (
		Index("ix_apt_appointment_staff_start", "staff_id", "start_at"),
		Index("ix_apt_appointment_customer_start", "customer_id", "start_at"),
		Index("ix_apt_appointment_tenant_status_start", "tenant_id", "status", "start_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	service_id = Column(
		UUID(as_uuid=False),
		ForeignKey("apt_service.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	staff_id = Column(String(50), nullable=False, index=True)
	customer_id = Column(String(50), nullable=True, index=True)
	customer_email = Column(String(320), nullable=True)
	customer_name = Column(String(200), nullable=True)
	customer_phone = Column(String(30), nullable=True)
	start_at = Column(DateTime(timezone=True), nullable=False)
	end_at = Column(DateTime(timezone=True), nullable=False)
	status = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
	amount_cents = Column(Integer, nullable=False, default=0, server_default="0")
	currency_code = Column(String(3), nullable=False, default="KES")
	notes = Column(Text, nullable=True)
	cancellation_reason = Column(Text, nullable=True)
	cancelled_by = Column(String(50), nullable=True)
	reminder_sent = Column(Boolean, nullable=False, default=False, server_default="false")
	booking_ref = Column(String(50), nullable=True, index=True,
		comment="Short human-readable reference; unique per tenant")
	metadata_ = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
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

	service: Any = relationship("AppointmentService", back_populates="appointments", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Appointment {self.booking_ref!r} staff={self.staff_id!r} "
			f"start={self.start_at} status={self.status!r}>"
		)


__all__ = [
	"AppointmentService",
	"StaffAvailability",
	"StaffBlockedSlot",
	"Appointment",
	# enumerations
	"APPOINTMENT_STATUS",
]
