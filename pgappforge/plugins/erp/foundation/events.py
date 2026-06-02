"""
pgappforge/plugins/erp/foundation/events.py

DomainEvent base dataclass and emit_event() helper used by all ERP plugins.

Every ERP domain event:
 - Gets a unique event_id (UUID4 string) on construction.
 - Carries aggregate identity + tenant scoping.
 - Is persisted to DomainEventLog inside the *same* SQLAlchemy session as the
   business mutation (atomic by default).
 - Optionally broadcasts via the Realtime plugin when it is loaded.

Downstream plugins subscribe by filtering DomainEventLog.event_type or by
listening to the in-process _EVENT_BUS dict (best-effort, in-process only).

Usage
-----
    from pgappforge.plugins.erp.foundation.events import (
        DomainEvent, emit_event, subscribe, PartyCreatedEvent,
    )

    @dataclass
    class InvoicePaidEvent(DomainEvent):
        event_type: str = "invoice.paid"
        invoice_id: str = ""
        amount_cents: int = 0
        currency: str = "NGN"

    # Inside a service method:
    emit_event(InvoicePaidEvent(
        aggregate_id=invoice.id,
        aggregate_type="Invoice",
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        amount_cents=invoice.total_cents,
        currency=invoice.currency,
    ), session)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process event bus (best-effort; complements durable DomainEventLog)
# ---------------------------------------------------------------------------

# event_type -> list[callable(DomainEvent)]
_EVENT_BUS: dict[str, list[Callable]] = {}


def subscribe(event_type: str, handler: Callable) -> None:
	"""Register an in-process handler for *event_type*.

	Handlers are called synchronously inside emit_event, after the log row is
	added to the session.  Exceptions are caught and logged — they do NOT roll
	back the business transaction.
	"""
	_EVENT_BUS.setdefault(event_type, []).append(handler)


def unsubscribe(event_type: str, handler: Callable) -> None:
	"""Remove a previously registered handler (useful in tests)."""
	handlers = _EVENT_BUS.get(event_type, [])
	try:
		handlers.remove(handler)
	except ValueError:
		pass


# ---------------------------------------------------------------------------
# Base event dataclass
# ---------------------------------------------------------------------------

@dataclass
class DomainEvent:
	"""Base class for all ERP domain events.

	Subclasses should:
	  1. Set ``event_type`` as a class-level default, e.g.
	         event_type: str = "party.created"
	  2. Add domain-specific payload fields after the base fields.
	  3. Never store floats for monetary amounts — use integer cents.

	The ``payload`` dict is auto-populated from all non-base fields in
	emit_event so downstream consumers always have a flat JSON representation.
	"""

	event_id: str = field(default_factory=lambda: str(uuid4()))
	event_type: str = ""
	aggregate_id: str = ""
	aggregate_type: str = ""
	tenant_id: str = ""
	occurred_at: datetime = field(
		default_factory=lambda: datetime.now(timezone.utc)
	)
	correlation_id: str = ""
	causation_id: str = ""
	payload: dict = field(default_factory=dict)

	# Names of the base DomainEvent fields — excluded from auto-payload build
	_BASE_FIELDS: frozenset = field(
		default=frozenset({
			"event_id", "event_type", "aggregate_id", "aggregate_type",
			"tenant_id", "occurred_at", "correlation_id", "causation_id",
			"payload", "_BASE_FIELDS",
		}),
		init=False,
		repr=False,
		compare=False,
	)

	def build_payload(self) -> dict[str, Any]:
		"""Return a JSON-serialisable dict of domain-specific fields."""
		base = self._BASE_FIELDS
		result: dict[str, Any] = {}
		for f in fields(self):
			if f.name in base:
				continue
			val = getattr(self, f.name)
			# datetime → ISO string for JSON safety
			if isinstance(val, datetime):
				val = val.isoformat()
			result[f.name] = val
		return result


# ---------------------------------------------------------------------------
# Canonical foundation events
# ---------------------------------------------------------------------------

@dataclass
class PartyCreatedEvent(DomainEvent):
	event_type: str = "party.created"
	party_id: str = ""
	party_type: str = ""
	name: str = ""


@dataclass
class PartyUpdatedEvent(DomainEvent):
	event_type: str = "party.updated"
	party_id: str = ""
	changed_fields: list = field(default_factory=list)


@dataclass
class PartyMergedEvent(DomainEvent):
	event_type: str = "party.merged"
	primary_id: str = ""
	duplicate_id: str = ""


@dataclass
class ExchangeRateUpdatedEvent(DomainEvent):
	event_type: str = "exchange_rate.updated"
	from_currency: str = ""
	to_currency: str = ""
	# rate stored as string to avoid float; callers convert from Decimal
	rate: str = ""
	rate_date: str = ""
	source: str = ""


# ---------------------------------------------------------------------------
# emit_event
# ---------------------------------------------------------------------------

def emit_event(event: DomainEvent, session: Any) -> None:
	"""Persist *event* to DomainEventLog and dispatch in-process handlers.

	The DomainEventLog INSERT is added to *session* but NOT committed here —
	it commits atomically with the caller's business transaction.  This means
	that if the business transaction rolls back, the event log row also rolls
	back (exactly-once semantics for durable storage).

	In-process handlers (registered via subscribe()) are called after the
	session.add() so they can inspect the session state.  Their exceptions are
	swallowed to protect the business transaction.

	Realtime broadcast is attempted when the Realtime plugin is active; its
	failure is also swallowed.
	"""
	# Auto-build payload from domain-specific fields if caller left it empty
	if not event.payload:
		event.payload = event.build_payload()

	# Persist to durable event log
	try:
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		log_row = DomainEventLog(
			event_id=event.event_id,
			event_type=event.event_type,
			aggregate_type=event.aggregate_type,
			aggregate_id=event.aggregate_id,
			tenant_id=event.tenant_id or None,
			payload=event.payload,
			correlation_id=event.correlation_id or None,
			causation_id=event.causation_id or None,
			published_at=event.occurred_at,
		)
		session.add(log_row)
	except Exception as exc:
		log.error("emit_event: failed to persist DomainEventLog for %s: %s", event.event_type, exc)

	# In-process dispatch (best-effort)
	for handler in _EVENT_BUS.get(event.event_type, []):
		try:
			handler(event)
		except Exception as exc:
			log.warning(
				"emit_event: in-process handler %r for %s raised: %s",
				getattr(handler, "__name__", "?"),
				event.event_type,
				exc,
			)

	# Realtime broadcast (best-effort; requires realtime plugin loaded)
	try:
		from flask import current_app
		rt = current_app.extensions.get("pgaf_realtime")
		if rt is not None:
			rt.broadcast(
				channel=f"erp.{event.event_type}",
				data={
					"event_id": event.event_id,
					"event_type": event.event_type,
					"aggregate_id": event.aggregate_id,
					"tenant_id": event.tenant_id,
					"occurred_at": event.occurred_at.isoformat(),
					**event.payload,
				},
			)
	except Exception as exc:
		log.debug("emit_event: realtime broadcast failed (non-fatal): %s", exc)


__all__ = [
	"DomainEvent",
	"PartyCreatedEvent",
	"PartyUpdatedEvent",
	"PartyMergedEvent",
	"ExchangeRateUpdatedEvent",
	"emit_event",
	"subscribe",
	"unsubscribe",
]
