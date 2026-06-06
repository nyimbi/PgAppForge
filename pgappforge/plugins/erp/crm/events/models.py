"""
pgappforge/plugins/erp/crm/events/models.py

SQLAlchemy models for the Events Management plugin.

Design rules enforced:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY — never Numeric/float for money
  - AuditMixin on all mutable entities
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured data (tags, perks, metadata_)
  - PostgreSQL only — JSONB, UUID, DateTime(timezone=True)

Table name convention: evt_<entity>
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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations (VARCHAR — no SA Enum, stays PG-only)
# ---------------------------------------------------------------------------

EVENT_TYPE = ("CONFERENCE", "WEBINAR", "WORKSHOP", "SEMINAR", "TRADE_SHOW", "SOCIAL", "OTHER")
EVENT_STATUS = ("DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED")
TICKET_STATUS = ("PENDING", "CONFIRMED", "CANCELLED", "REFUNDED")
SPONSOR_TIER = ("PLATINUM", "GOLD", "SILVER", "BRONZE", "COMMUNITY")


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

class Event(AuditMixin, Model):
	"""Top-level event entity.

	tags JSONB: list of free-text tag strings for search/filtering.
	is_virtual + virtual_link: mutually exclusive with physical venue but both
	  fields may coexist for hybrid events.
	max_capacity=None means unlimited registration.
	"""

	__tablename__ = "evt_event"
	__table_args__ = (
		Index("ix_evt_event_tenant_status", "tenant_id", "status"),
		Index("ix_evt_event_tenant_start", "tenant_id", "start_datetime"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	title = Column(String(300), nullable=False)
	description = Column(Text, nullable=True)
	event_type = Column(String(30), nullable=False, default="OTHER")
	status = Column(String(20), nullable=False, default="DRAFT")

	start_datetime = Column(DateTime(timezone=True), nullable=False)
	end_datetime = Column(DateTime(timezone=True), nullable=False)

	venue = Column(String(500), nullable=True)
	venue_address = Column(Text, nullable=True)
	is_virtual = Column(Boolean, nullable=False, default=False)
	virtual_link = Column(Text, nullable=True)

	max_capacity = Column(Integer, nullable=True)
	registration_deadline = Column(DateTime(timezone=True), nullable=True)

	entity_id = Column(String(50), nullable=True)
	created_by = Column(String(50), nullable=True)
	cover_image_url = Column(Text, nullable=True)
	tags = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))

	# Relationships
	ticket_types = relationship("EventTicketType", back_populates="event", lazy="select", cascade="all, delete-orphan")
	tickets = relationship("EventTicket", back_populates="event", lazy="select", cascade="all, delete-orphan")
	attendances = relationship("EventAttendance", back_populates="event", lazy="select", cascade="all, delete-orphan")
	sponsors = relationship("EventSponsor", back_populates="event", lazy="select", cascade="all, delete-orphan")

	def __repr__(self) -> str:
		return f"<Event id={self.id} title={self.title!r} status={self.status}>"


# ---------------------------------------------------------------------------
# EventTicketType
# ---------------------------------------------------------------------------

class EventTicketType(AuditMixin, Model):
	"""Defines a ticket tier for an event (e.g. GENERAL, VIP, EARLY_BIRD).

	quantity=None means unlimited availability.
	sold_count is incremented transactionally on each purchase.
	perks JSONB: list of perk strings, e.g. ["Lunch included", "Speaker access"]
	"""

	__tablename__ = "evt_ticket_type"
	__table_args__ = (
		Index("ix_evt_ticket_type_event", "event_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	event_id = Column(
		UUID(as_uuid=False),
		ForeignKey("evt_event.id", ondelete="CASCADE"),
		nullable=False,
	)
	name = Column(String(200), nullable=False)
	price_cents = Column(BigInteger, nullable=False, default=0)
	quantity = Column(Integer, nullable=True)
	sold_count = Column(Integer, nullable=False, default=0)
	sale_starts_at = Column(DateTime(timezone=True), nullable=True)
	sale_ends_at = Column(DateTime(timezone=True), nullable=True)
	perks = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))

	# Relationships
	event = relationship("Event", back_populates="ticket_types", lazy="select")
	tickets = relationship("EventTicket", back_populates="ticket_type", lazy="select")

	def __repr__(self) -> str:
		return f"<EventTicketType event={self.event_id} name={self.name!r} price_cents={self.price_cents}>"


# ---------------------------------------------------------------------------
# EventTicket
# ---------------------------------------------------------------------------

class EventTicket(AuditMixin, Model):
	"""Individual ticket purchased by an attendee.

	ticket_ref is a short human-readable reference unique per tenant,
	  generated at purchase time (e.g. EVT-2026-00042).
	qr_code_data: serialised QR payload (base64 PNG or a signed URL).
	metadata_ JSONB: channel-specific data (payment reference, coupon used, etc.)
	"""

	__tablename__ = "evt_ticket"
	__table_args__ = (
		UniqueConstraint("tenant_id", "ticket_ref", name="uq_evt_ticket_tenant_ref"),
		Index("ix_evt_ticket_event_status", "event_id", "status"),
		Index("ix_evt_ticket_attendee_event", "attendee_id", "event_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	event_id = Column(
		UUID(as_uuid=False),
		ForeignKey("evt_event.id", ondelete="CASCADE"),
		nullable=False,
	)
	ticket_type_id = Column(
		UUID(as_uuid=False),
		ForeignKey("evt_ticket_type.id", ondelete="CASCADE"),
		nullable=False,
	)
	attendee_id = Column(String(50), nullable=False)
	attendee_email = Column(String(320), nullable=False)
	attendee_name = Column(String(200), nullable=False)
	ticket_ref = Column(String(50), nullable=False)
	amount_paid_cents = Column(BigInteger, nullable=False)
	currency_code = Column(String(3), nullable=False, default="KES")
	status = Column(String(20), nullable=False, default="CONFIRMED")
	purchased_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	qr_code_data = Column(Text, nullable=True)
	metadata_ = Column("metadata_", JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))

	# Relationships
	event = relationship("Event", back_populates="tickets", lazy="select")
	ticket_type = relationship("EventTicketType", back_populates="tickets", lazy="select")
	attendance = relationship("EventAttendance", back_populates="ticket", uselist=False, lazy="select")

	def __repr__(self) -> str:
		return f"<EventTicket ref={self.ticket_ref} attendee={self.attendee_id} status={self.status}>"


# ---------------------------------------------------------------------------
# EventAttendance
# ---------------------------------------------------------------------------

class EventAttendance(AuditMixin, Model):
	"""Check-in record for a ticket holder at the event venue.

	One row per ticket (UniqueConstraint on ticket_id).
	checked_in_at=None means the attendee has not yet checked in.
	checked_out_at is optional — only set for events that track departures.
	"""

	__tablename__ = "evt_attendance"
	__table_args__ = (
		UniqueConstraint("ticket_id", name="uq_evt_attendance_ticket"),
		Index("ix_evt_attendance_event_checkin", "event_id", "checked_in_at"),
		Index("ix_evt_attendance_attendee", "attendee_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	event_id = Column(
		UUID(as_uuid=False),
		ForeignKey("evt_event.id", ondelete="CASCADE"),
		nullable=False,
	)
	ticket_id = Column(
		UUID(as_uuid=False),
		ForeignKey("evt_ticket.id", ondelete="CASCADE"),
		nullable=False,
	)
	attendee_id = Column(String(50), nullable=False)
	checked_in_at = Column(DateTime(timezone=True), nullable=True)
	checked_in_by = Column(String(50), nullable=True)
	checked_out_at = Column(DateTime(timezone=True), nullable=True)

	# Relationships
	event = relationship("Event", back_populates="attendances", lazy="select")
	ticket = relationship("EventTicket", back_populates="attendance", lazy="select")

	def __repr__(self) -> str:
		return f"<EventAttendance event={self.event_id} attendee={self.attendee_id} checked_in={self.checked_in_at}>"


# ---------------------------------------------------------------------------
# EventSponsor
# ---------------------------------------------------------------------------

class EventSponsor(AuditMixin, Model):
	"""Sponsor attached to an event with tier classification and financials."""

	__tablename__ = "evt_sponsor"
	__table_args__ = (
		Index("ix_evt_sponsor_event_tier", "event_id", "sponsor_tier"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	event_id = Column(
		UUID(as_uuid=False),
		ForeignKey("evt_event.id", ondelete="CASCADE"),
		nullable=False,
	)
	sponsor_name = Column(String(300), nullable=False)
	sponsor_tier = Column(String(30), nullable=False, default="COMMUNITY")
	amount_cents = Column(BigInteger, nullable=False)
	logo_url = Column(Text, nullable=True)
	website_url = Column(Text, nullable=True)
	notes = Column(Text, nullable=True)

	# Relationships
	event = relationship("Event", back_populates="sponsors", lazy="select")

	def __repr__(self) -> str:
		return f"<EventSponsor event={self.event_id} name={self.sponsor_name!r} tier={self.sponsor_tier}>"


__all__ = [
	"Event",
	"EventTicketType",
	"EventTicket",
	"EventAttendance",
	"EventSponsor",
	"EVENT_TYPE",
	"EVENT_STATUS",
	"TICKET_STATUS",
	"SPONSOR_TIER",
]
