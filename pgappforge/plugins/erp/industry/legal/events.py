"""
pgappforge/plugins/erp/industry/legal/events.py

Domain events for the Legal Services plugin.

Event payloads carry only identifiers and status codes — never full
document content or client confidential data — to limit privilege
exposure in the event log.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Matter lifecycle
# ---------------------------------------------------------------------------

@dataclass
class MatterOpenedEvent(DomainEvent):
	"""New legal matter opened."""
	event_type: str = "legal.matter.opened"
	matter_id: str = ""
	matter_number: str = ""
	matter_type: str = ""
	client_id: str = ""
	lead_counsel_id: str = ""


@dataclass
class MatterStatusChangedEvent(DomainEvent):
	"""Matter status transitioned (e.g. INTAKE → ACTIVE, ACTIVE → SETTLED)."""
	event_type: str = "legal.matter.status_changed"
	matter_id: str = ""
	matter_number: str = ""
	old_status: str = ""
	new_status: str = ""


@dataclass
class MatterClosedEvent(DomainEvent):
	"""Matter closed or settled."""
	event_type: str = "legal.matter.closed"
	matter_id: str = ""
	matter_number: str = ""
	final_status: str = ""


# ---------------------------------------------------------------------------
# Document lifecycle
# ---------------------------------------------------------------------------

@dataclass
class DocumentCreatedEvent(DomainEvent):
	"""Legal document created (any type)."""
	event_type: str = "legal.document.created"
	document_id: str = ""
	matter_id: str = ""
	document_type: str = ""
	title: str = ""


@dataclass
class DocumentExecutedEvent(DomainEvent):
	"""Document executed/signed by all parties."""
	event_type: str = "legal.document.executed"
	document_id: str = ""
	matter_id: str = ""
	document_type: str = ""
	executed_at: str = ""


# ---------------------------------------------------------------------------
# Time & billing
# ---------------------------------------------------------------------------

@dataclass
class TimeEntryRecordedEvent(DomainEvent):
	"""Time entry recorded against a matter."""
	event_type: str = "legal.time_entry.recorded"
	time_entry_id: str = ""
	matter_id: str = ""
	timekeeper_id: str = ""
	amount_cents: int = 0
	is_billable: bool = True


@dataclass
class InvoiceGeneratedEvent(DomainEvent):
	"""Invoice generated for a matter billing period."""
	event_type: str = "legal.invoice.generated"
	invoice_id: str = ""
	matter_id: str = ""
	invoice_number: str = ""
	total_cents: int = 0


@dataclass
class InvoicePaidEvent(DomainEvent):
	"""Invoice marked as paid."""
	event_type: str = "legal.invoice.paid"
	invoice_id: str = ""
	matter_id: str = ""
	invoice_number: str = ""
	total_cents: int = 0


# ---------------------------------------------------------------------------
# Deadline
# ---------------------------------------------------------------------------

@dataclass
class DeadlineTrackedEvent(DomainEvent):
	"""New deadline added to a matter."""
	event_type: str = "legal.deadline.tracked"
	deadline_id: str = ""
	matter_id: str = ""
	deadline_type: str = ""
	deadline_date: str = ""
	is_hard_deadline: bool = True


@dataclass
class DeadlineMissedEvent(DomainEvent):
	"""Hard deadline missed — requires urgent attention."""
	event_type: str = "legal.deadline.missed"
	deadline_id: str = ""
	matter_id: str = ""
	deadline_type: str = ""
	deadline_date: str = ""
	responsible_id: str = ""


__all__ = [
	"emit_event",
	# matter
	"MatterOpenedEvent",
	"MatterStatusChangedEvent",
	"MatterClosedEvent",
	# document
	"DocumentCreatedEvent",
	"DocumentExecutedEvent",
	# time & billing
	"TimeEntryRecordedEvent",
	"InvoiceGeneratedEvent",
	"InvoicePaidEvent",
	# deadline
	"DeadlineTrackedEvent",
	"DeadlineMissedEvent",
]
