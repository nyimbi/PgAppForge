"""
pgappforge/plugins/erp/crm/appointments/events.py

Domain events for the Appointments/Booking plugin.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class AppointmentBookedEvent(DomainEvent):
	"""Emitted when a new appointment is created (status PENDING)."""
	event_type: str = "crm.appointments.booked"
	appointment_id: str = ""
	service_id: str = ""
	customer_id: str = ""
	staff_id: str = ""
	start_at: str = ""  # ISO datetime
	tenant_id: str = ""


@dataclass
class AppointmentConfirmedEvent(DomainEvent):
	"""Emitted when an appointment is confirmed (PENDING → CONFIRMED)."""
	event_type: str = "crm.appointments.confirmed"
	appointment_id: str = ""
	customer_id: str = ""


@dataclass
class AppointmentCancelledEvent(DomainEvent):
	"""Emitted when an appointment is cancelled."""
	event_type: str = "crm.appointments.cancelled"
	appointment_id: str = ""
	cancelled_by: str = ""
	reason: str = ""


@dataclass
class AppointmentCompletedEvent(DomainEvent):
	"""Emitted when an appointment is marked COMPLETED."""
	event_type: str = "crm.appointments.completed"
	appointment_id: str = ""
	duration_minutes: int = 0


@dataclass
class ReminderSentEvent(DomainEvent):
	"""Emitted when a reminder notification is dispatched for an appointment."""
	event_type: str = "crm.appointments.reminder.sent"
	appointment_id: str = ""
	customer_id: str = ""
	send_at: str = ""  # ISO datetime


__all__ = [
	"AppointmentBookedEvent",
	"AppointmentConfirmedEvent",
	"AppointmentCancelledEvent",
	"AppointmentCompletedEvent",
	"ReminderSentEvent",
]
