"""
pgappforge/plugins/erp/crm/events/services.py

EventsService — business logic for event publishing, ticket sales,
attendee check-in, and sponsorship management.

Conventions:
  - session is always a SQLAlchemy Session passed by the caller
  - All monetary values are integer cents
  - emit_event() is called after the state mutation and session.flush()
    so the event log row is part of the same transaction
  - BPMActionRegistry.register decorators expose key operations to workflow steps
  - ticket_ref format: EVT-<YYYYMMDD>-<6-char-upper-hex-fragment-of-uuid>
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

from .events import (
	AttendeeCheckedInEvent,
	EventCompletedEvent,
	EventPublishedEvent,
	SponsorAddedEvent,
	TicketPurchasedEvent,
)
from .models import (
	Event,
	EventAttendance,
	EventSponsor,
	EventTicket,
	EventTicketType,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class EventsServiceError(Exception):
	"""Base exception for all events service errors."""


class EventsNotFoundError(EventsServiceError):
	"""Raised when a requested entity cannot be located."""


class EventsStateError(EventsServiceError):
	"""Raised when an operation is invalid for the entity's current state."""


# ---------------------------------------------------------------------------
# ticket_ref generator
# ---------------------------------------------------------------------------

def _generate_ticket_ref() -> str:
	"""Generate a short human-readable ticket reference.

	Format: EVT-YYYYMMDD-XXXXXX  (X = 6 upper-hex chars from UUID4 fragment)
	Example: EVT-20260606-A3F9C1
	"""
	today = datetime.now(timezone.utc).strftime("%Y%m%d")
	fragment = uuid.uuid4().hex[:6].upper()
	return f"EVT-{today}-{fragment}"


# ---------------------------------------------------------------------------
# EventsService
# ---------------------------------------------------------------------------

class EventsService:
	"""Stateless service — callers supply a SQLAlchemy session per operation."""

	# ------------------------------------------------------------------
	# Event lifecycle
	# ------------------------------------------------------------------

	def publish_event(self, event_id: str, session: Any) -> Event:
		"""Transition event DRAFT → PUBLISHED and emit EventPublishedEvent.

		Raises:
		  EventsNotFoundError: event not found.
		  EventsStateError: event is not in DRAFT status.
		"""
		event = session.execute(
			sa.select(Event).where(Event.id == event_id)
		).scalar_one_or_none()
		if event is None:
			raise EventsNotFoundError(f"Event {event_id!r} not found")
		if event.status != "DRAFT":
			raise EventsStateError(
				f"Event {event_id!r} cannot be published from status {event.status!r}"
			)

		event.status = "PUBLISHED"
		session.flush()

		emit_event(
			EventPublishedEvent(
				aggregate_id=event.id,
				aggregate_type="Event",
				tenant_id=event.tenant_id,
				event_id=event.id,
				title=event.title,
			),
			session,
		)
		log.info("publish_event: event=%s %r published", event_id, event.title)
		return event

	def complete_event(self, event_id: str, session: Any) -> Event:
		"""Transition event PUBLISHED → COMPLETED with final attendance/revenue tallies.

		Emits EventCompletedEvent with attendee_count and revenue_cents.

		Raises:
		  EventsNotFoundError: event not found.
		  EventsStateError: event is not in PUBLISHED status.
		"""
		event = session.execute(
			sa.select(Event).where(Event.id == event_id)
		).scalar_one_or_none()
		if event is None:
			raise EventsNotFoundError(f"Event {event_id!r} not found")
		if event.status != "PUBLISHED":
			raise EventsStateError(
				f"Event {event_id!r} cannot be completed from status {event.status!r}"
			)

		# Count checked-in attendees
		attendee_count: int = session.execute(
			sa.select(func.count(EventAttendance.id))
			.where(
				EventAttendance.event_id == event_id,
				EventAttendance.checked_in_at.isnot(None),
			)
		).scalar() or 0

		# Sum confirmed ticket revenue
		revenue_cents: int = session.execute(
			sa.select(func.coalesce(func.sum(EventTicket.amount_paid_cents), 0))
			.where(
				EventTicket.event_id == event_id,
				EventTicket.status == "CONFIRMED",
			)
		).scalar() or 0

		event.status = "COMPLETED"
		session.flush()

		emit_event(
			EventCompletedEvent(
				aggregate_id=event.id,
				aggregate_type="Event",
				tenant_id=event.tenant_id,
				event_id=event.id,
				attendee_count=attendee_count,
				revenue_cents=int(revenue_cents),
			),
			session,
		)
		log.info(
			"complete_event: event=%s completed — attendees=%d revenue_cents=%d",
			event_id, attendee_count, revenue_cents,
		)
		return event

	# ------------------------------------------------------------------
	# Ticket sales
	# ------------------------------------------------------------------

	def purchase_ticket(
		self,
		event_id: str,
		ticket_type_id: str,
		attendee_id: str,
		attendee_email: str,
		attendee_name: str,
		session: Any,
		*,
		tenant_id: str,
		currency_code: str = "KES",
		metadata: dict | None = None,
	) -> EventTicket:
		"""Purchase a ticket for an attendee.

		Steps:
		1. Load event and ticket type; validate statuses.
		2. Check capacity (max_capacity on event and quantity on ticket type).
		3. Verify sale window (sale_starts_at / sale_ends_at).
		4. Generate ticket_ref, create EventTicket and EventAttendance stub.
		5. Increment ticket_type.sold_count.
		6. Emit TicketPurchasedEvent.

		Raises:
		  EventsNotFoundError: event or ticket type not found.
		  EventsStateError: event not PUBLISHED, capacity exhausted, or outside sale window.
		"""
		event = session.execute(
			sa.select(Event).where(Event.id == event_id)
		).scalar_one_or_none()
		if event is None:
			raise EventsNotFoundError(f"Event {event_id!r} not found")
		if event.status != "PUBLISHED":
			raise EventsStateError(
				f"Event {event_id!r} is {event.status!r} — ticket sales require PUBLISHED status"
			)

		ticket_type = session.execute(
			sa.select(EventTicketType).where(
				EventTicketType.id == ticket_type_id,
				EventTicketType.event_id == event_id,
			)
		).scalar_one_or_none()
		if ticket_type is None:
			raise EventsNotFoundError(
				f"EventTicketType {ticket_type_id!r} not found for event {event_id!r}"
			)

		now = datetime.now(timezone.utc)

		# Sale window check
		if ticket_type.sale_starts_at and now < ticket_type.sale_starts_at:
			raise EventsStateError(
				f"Ticket type {ticket_type_id!r} sale has not started yet "
				f"(starts {ticket_type.sale_starts_at.isoformat()})"
			)
		if ticket_type.sale_ends_at and now > ticket_type.sale_ends_at:
			raise EventsStateError(
				f"Ticket type {ticket_type_id!r} sale has ended "
				f"(ended {ticket_type.sale_ends_at.isoformat()})"
			)

		# Capacity check — ticket type
		if ticket_type.quantity is not None and ticket_type.sold_count >= ticket_type.quantity:
			raise EventsStateError(
				f"Ticket type {ticket_type_id!r} is sold out "
				f"({ticket_type.sold_count}/{ticket_type.quantity})"
			)

		# Capacity check — event-level max_capacity
		if event.max_capacity is not None:
			total_sold: int = session.execute(
				sa.select(func.count(EventTicket.id))
				.where(
					EventTicket.event_id == event_id,
					EventTicket.status.in_(["PENDING", "CONFIRMED"]),
				)
			).scalar() or 0
			if total_sold >= event.max_capacity:
				raise EventsStateError(
					f"Event {event_id!r} is at full capacity ({event.max_capacity})"
				)

		# Generate unique ticket_ref (retry up to 5 times on collision)
		ticket_ref: str = ""
		for _ in range(5):
			candidate = _generate_ticket_ref()
			clash = session.execute(
				sa.select(EventTicket.id).where(
					EventTicket.tenant_id == tenant_id,
					EventTicket.ticket_ref == candidate,
				)
			).scalar_one_or_none()
			if clash is None:
				ticket_ref = candidate
				break
		if not ticket_ref:
			ticket_ref = f"EVT-{uuid.uuid4().hex[:12].upper()}"

		ticket = EventTicket(
			tenant_id=tenant_id,
			event_id=event_id,
			ticket_type_id=ticket_type_id,
			attendee_id=attendee_id,
			attendee_email=attendee_email,
			attendee_name=attendee_name,
			ticket_ref=ticket_ref,
			amount_paid_cents=ticket_type.price_cents,
			currency_code=currency_code,
			status="CONFIRMED",
			purchased_at=now,
			metadata_=metadata or {},
		)
		session.add(ticket)
		session.flush()

		# Create attendance stub (checked_in_at remains null until check-in)
		attendance = EventAttendance(
			tenant_id=tenant_id,
			event_id=event_id,
			ticket_id=ticket.id,
			attendee_id=attendee_id,
		)
		session.add(attendance)

		# Increment sold_count
		ticket_type.sold_count = (ticket_type.sold_count or 0) + 1
		session.flush()

		emit_event(
			TicketPurchasedEvent(
				aggregate_id=ticket.id,
				aggregate_type="EventTicket",
				tenant_id=tenant_id,
				ticket_id=ticket.id,
				event_id=event_id,
				attendee_id=attendee_id,
				amount_cents=int(ticket_type.price_cents),
			),
			session,
		)
		log.info(
			"purchase_ticket: ticket=%s ref=%s event=%s attendee=%s amount_cents=%d",
			ticket.id, ticket_ref, event_id, attendee_id, ticket_type.price_cents,
		)
		return ticket

	# ------------------------------------------------------------------
	# Check-in
	# ------------------------------------------------------------------

	def check_in_attendee(
		self,
		ticket_id_or_ref: str,
		checked_in_by: str,
		session: Any,
	) -> EventAttendance:
		"""Check in an attendee by ticket ID or ticket_ref.

		Sets EventAttendance.checked_in_at to now and records checked_in_by.
		Emits AttendeeCheckedInEvent.

		Raises:
		  EventsNotFoundError: ticket or attendance not found.
		  EventsStateError: ticket not CONFIRMED, or already checked in.
		"""
		# Try to resolve by ID first, then by ticket_ref
		ticket = session.execute(
			sa.select(EventTicket).where(EventTicket.id == ticket_id_or_ref)
		).scalar_one_or_none()
		if ticket is None:
			ticket = session.execute(
				sa.select(EventTicket).where(EventTicket.ticket_ref == ticket_id_or_ref)
			).scalar_one_or_none()
		if ticket is None:
			raise EventsNotFoundError(f"EventTicket {ticket_id_or_ref!r} not found")
		if ticket.status != "CONFIRMED":
			raise EventsStateError(
				f"Ticket {ticket.ticket_ref!r} has status {ticket.status!r} — cannot check in"
			)

		attendance = session.execute(
			sa.select(EventAttendance).where(EventAttendance.ticket_id == ticket.id)
		).scalar_one_or_none()
		if attendance is None:
			raise EventsNotFoundError(
				f"EventAttendance for ticket {ticket.id!r} not found"
			)
		if attendance.checked_in_at is not None:
			raise EventsStateError(
				f"Attendee {ticket.attendee_id!r} already checked in at "
				f"{attendance.checked_in_at.isoformat()}"
			)

		now = datetime.now(timezone.utc)
		attendance.checked_in_at = now
		attendance.checked_in_by = checked_in_by
		session.flush()

		emit_event(
			AttendeeCheckedInEvent(
				aggregate_id=attendance.id,
				aggregate_type="EventAttendance",
				tenant_id=str(ticket.tenant_id),
				attendance_id=attendance.id,
				event_id=str(ticket.event_id),
				attendee_id=ticket.attendee_id,
				checked_in_at=now.isoformat(),
			),
			session,
		)
		log.info(
			"check_in_attendee: attendee=%s event=%s checked_in_at=%s by=%s",
			ticket.attendee_id, ticket.event_id, now.isoformat(), checked_in_by,
		)
		return attendance

	# ------------------------------------------------------------------
	# Sponsorship
	# ------------------------------------------------------------------

	def add_sponsor(
		self,
		event_id: str,
		sponsor_name: str,
		tier: str,
		amount_cents: int,
		session: Any,
		*,
		logo_url: str | None = None,
		website_url: str | None = None,
		notes: str | None = None,
	) -> EventSponsor:
		"""Attach a sponsor to an event and emit SponsorAddedEvent.

		Raises:
		  EventsNotFoundError: event not found.
		"""
		event = session.execute(
			sa.select(Event).where(Event.id == event_id)
		).scalar_one_or_none()
		if event is None:
			raise EventsNotFoundError(f"Event {event_id!r} not found")

		sponsor = EventSponsor(
			tenant_id=event.tenant_id,
			event_id=event_id,
			sponsor_name=sponsor_name,
			sponsor_tier=tier,
			amount_cents=amount_cents,
			logo_url=logo_url,
			website_url=website_url,
			notes=notes,
		)
		session.add(sponsor)
		session.flush()

		emit_event(
			SponsorAddedEvent(
				aggregate_id=sponsor.id,
				aggregate_type="EventSponsor",
				tenant_id=str(event.tenant_id),
				event_id=event_id,
				sponsor_id=sponsor.id,
				tier=tier,
				amount_cents=amount_cents,
			),
			session,
		)
		log.info(
			"add_sponsor: sponsor=%s event=%s tier=%s amount_cents=%d",
			sponsor_name, event_id, tier, amount_cents,
		)
		return sponsor

	# ------------------------------------------------------------------
	# Dashboard analytics
	# ------------------------------------------------------------------

	def get_event_dashboard(self, event_id: str, session: Any) -> dict[str, Any]:
		"""Return a comprehensive dashboard snapshot for an event.

		Returns:
		  dict with keys: ticket_types, attendance_rate_pct, revenue_cents,
		  sponsor_total_cents, checked_in_count, total_sold
		"""
		event = session.execute(
			sa.select(Event).where(Event.id == event_id)
		).scalar_one_or_none()
		if event is None:
			raise EventsNotFoundError(f"Event {event_id!r} not found")

		# Ticket type breakdown
		tt_rows = session.execute(
			sa.select(EventTicketType).where(EventTicketType.event_id == event_id)
		).scalars().all()

		ticket_types: list[dict] = []
		total_sold = 0
		for tt in tt_rows:
			remaining = (tt.quantity - tt.sold_count) if tt.quantity is not None else None
			ticket_types.append({
				"ticket_type_id": tt.id,
				"name": tt.name,
				"price_cents": tt.price_cents,
				"sold": tt.sold_count,
				"remaining": remaining,
			})
			total_sold += tt.sold_count

		# Checked-in count
		checked_in_count: int = session.execute(
			sa.select(func.count(EventAttendance.id))
			.where(
				EventAttendance.event_id == event_id,
				EventAttendance.checked_in_at.isnot(None),
			)
		).scalar() or 0

		attendance_rate_pct = round(checked_in_count / total_sold * 100, 2) if total_sold else 0.0

		# Revenue
		revenue_cents: int = session.execute(
			sa.select(func.coalesce(func.sum(EventTicket.amount_paid_cents), 0))
			.where(
				EventTicket.event_id == event_id,
				EventTicket.status == "CONFIRMED",
			)
		).scalar() or 0

		# Sponsor totals
		sponsor_total_cents: int = session.execute(
			sa.select(func.coalesce(func.sum(EventSponsor.amount_cents), 0))
			.where(EventSponsor.event_id == event_id)
		).scalar() or 0

		return {
			"event_id": event_id,
			"title": event.title,
			"status": event.status,
			"ticket_types": ticket_types,
			"total_sold": total_sold,
			"checked_in_count": checked_in_count,
			"attendance_rate_pct": attendance_rate_pct,
			"revenue_cents": int(revenue_cents),
			"sponsor_total_cents": int(sponsor_total_cents),
		}


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"crm.events.purchase_ticket",
	"Purchase event ticket from workflow",
)
def _bpm_purchase_ticket(
	record_ctx: dict,
	session: Any,
	event_id: str = "",
	ticket_type_id: str = "",
	attendee_id: str = "",
	attendee_email: str = "",
	attendee_name: str = "",
	tenant_id: str = "",
	currency_code: str = "KES",
	**kw: Any,
) -> dict:
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = EventsService()
		ticket = svc.purchase_ticket(
			event_id=event_id,
			ticket_type_id=ticket_type_id,
			attendee_id=attendee_id,
			attendee_email=attendee_email,
			attendee_name=attendee_name,
			session=session,
			tenant_id=_tenant_id,
			currency_code=currency_code,
		)
		return {
			"status": "ok",
			"ticket_id": ticket.id,
			"ticket_ref": ticket.ticket_ref,
			"amount_paid_cents": ticket.amount_paid_cents,
		}
	except EventsServiceError as exc:
		log.warning("bpm crm.events.purchase_ticket failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"EventsService",
	"EventsServiceError",
	"EventsNotFoundError",
	"EventsStateError",
]
