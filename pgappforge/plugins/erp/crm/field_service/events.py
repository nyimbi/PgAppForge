"""
pgappforge/plugins/erp/crm/field_service/events.py

Domain events for the Field Service plugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class WorkOrderCreatedEvent(DomainEvent):
	"""Emitted when a new work order is created."""
	event_type: str = "field_service.work_order.created"
	work_order_id: str = ""
	work_order_number: str = ""
	work_type: str = ""
	account_id: str = ""
	case_id: str = ""


@dataclass
class WorkOrderScheduledEvent(DomainEvent):
	"""Emitted when a work order is scheduled to a resource."""
	event_type: str = "field_service.work_order.scheduled"
	work_order_id: str = ""
	work_order_number: str = ""
	assigned_to: str = ""
	scheduled_start: str = ""  # ISO datetime
	scheduled_end: str = ""    # ISO datetime


@dataclass
class WorkOrderCompletedEvent(DomainEvent):
	"""Emitted when a technician marks a work order COMPLETED."""
	event_type: str = "field_service.work_order.completed"
	work_order_id: str = ""
	work_order_number: str = ""
	assigned_to: str = ""
	labor_minutes: int = 0
	parts_used: list = field(default_factory=list)


@dataclass
class AppointmentConfirmedEvent(DomainEvent):
	"""Emitted when a customer confirms a service appointment slot."""
	event_type: str = "field_service.appointment.confirmed"
	appointment_id: str = ""
	work_order_id: str = ""
	contact_id: str = ""
	confirmed_start: str = ""  # ISO datetime
	confirmed_end: str = ""    # ISO datetime


@dataclass
class AppointmentCancelledEvent(DomainEvent):
	"""Emitted when a service appointment is cancelled."""
	event_type: str = "field_service.appointment.cancelled"
	appointment_id: str = ""
	work_order_id: str = ""
	contact_id: str = ""


__all__ = [
	"WorkOrderCreatedEvent",
	"WorkOrderScheduledEvent",
	"WorkOrderCompletedEvent",
	"AppointmentConfirmedEvent",
	"AppointmentCancelledEvent",
]
