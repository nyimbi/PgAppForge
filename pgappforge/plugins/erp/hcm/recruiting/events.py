"""
pgappforge/plugins/erp/hcm/recruiting/events.py

Domain events for the HCM Recruiting / ATS plugin.

Events emitted:
  hcm.recruiting.requisition.posted    — job requisition published and open
  hcm.recruiting.application.received  — candidate application received
  hcm.recruiting.interview.scheduled   — interview slot booked
  hcm.recruiting.offer.extended        — offer letter sent to candidate
  hcm.recruiting.offer.accepted        — candidate accepted the offer
  hcm.recruiting.requisition.filled    — requisition fully filled

Events consumed:
  hcm.employee.hired                   — (handled externally; triggers onboarding)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class RequisitionPostedEvent(DomainEvent):
	"""Emitted when a job requisition is opened and published."""
	event_type: str = "hcm.recruiting.requisition.posted"
	req_id: str = ""
	title: str = ""
	entity_id: str = ""
	tenant_id: str = ""


@dataclass
class ApplicationReceivedEvent(DomainEvent):
	"""Emitted when a candidate application is submitted."""
	event_type: str = "hcm.recruiting.application.received"
	app_id: str = ""
	req_id: str = ""
	candidate_name: str = ""
	source: str = ""


@dataclass
class InterviewScheduledEvent(DomainEvent):
	"""Emitted when an interview slot is booked for an application."""
	event_type: str = "hcm.recruiting.interview.scheduled"
	schedule_id: str = ""
	app_id: str = ""
	interviewer_id: str = ""
	scheduled_at: str = ""


@dataclass
class OfferExtendedEvent(DomainEvent):
	"""Emitted when an offer letter is sent to a candidate."""
	event_type: str = "hcm.recruiting.offer.extended"
	offer_id: str = ""
	app_id: str = ""
	salary_cents: int = 0


@dataclass
class OfferAcceptedEvent(DomainEvent):
	"""Emitted when a candidate accepts an offer and is hired."""
	event_type: str = "hcm.recruiting.offer.accepted"
	offer_id: str = ""
	app_id: str = ""
	employee_id: str = ""


@dataclass
class RequisitionFilledEvent(DomainEvent):
	"""Emitted when a requisition's full headcount has been hired."""
	event_type: str = "hcm.recruiting.requisition.filled"
	req_id: str = ""
	days_to_fill: int = 0
	hires_count: int = 0


__all__ = [
	"RequisitionPostedEvent",
	"ApplicationReceivedEvent",
	"InterviewScheduledEvent",
	"OfferExtendedEvent",
	"OfferAcceptedEvent",
	"RequisitionFilledEvent",
]
