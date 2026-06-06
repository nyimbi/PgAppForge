"""
pgappforge/plugins/erp/crm/events/events.py

Domain events emitted by the Events Management plugin.

All monetary amounts are integer cents. Never floats.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class EventPublishedEvent(DomainEvent):
	"""Emitted when an event transitions DRAFT → PUBLISHED."""
	event_type: str = "crm.events.published"
	event_id: str = ""
	title: str = ""
	tenant_id: str = ""


@dataclass
class TicketPurchasedEvent(DomainEvent):
	"""Emitted when a ticket is confirmed for an attendee."""
	event_type: str = "crm.events.ticket.purchased"
	ticket_id: str = ""
	event_id: str = ""
	attendee_id: str = ""
	amount_cents: int = 0


@dataclass
class AttendeeCheckedInEvent(DomainEvent):
	"""Emitted when an attendee successfully checks in at the event."""
	event_type: str = "crm.events.attendee.checked_in"
	attendance_id: str = ""
	event_id: str = ""
	attendee_id: str = ""
	checked_in_at: str = ""  # ISO-8601 string; datetime serialised for JSON safety


@dataclass
class EventCompletedEvent(DomainEvent):
	"""Emitted when an event is marked COMPLETED with final tallies."""
	event_type: str = "crm.events.completed"
	event_id: str = ""
	attendee_count: int = 0
	revenue_cents: int = 0


@dataclass
class SponsorAddedEvent(DomainEvent):
	"""Emitted when a sponsor is attached to an event."""
	event_type: str = "crm.events.sponsor.added"
	event_id: str = ""
	sponsor_id: str = ""
	tier: str = ""
	amount_cents: int = 0


__all__ = [
	"EventPublishedEvent",
	"TicketPurchasedEvent",
	"AttendeeCheckedInEvent",
	"EventCompletedEvent",
	"SponsorAddedEvent",
]
