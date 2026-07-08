"""
pgappforge/plugins/erp/platform/events/events.py

Platform Events plugin — domain events + in-process EventBus with
durable subscription registry and delivery logging.

Events emitted by this plugin:
  event.subscription.created
  event.subscription.deactivated
  event.delivery.failed
  event.delivery.dead_lettered
  event.replayed

EventBus service:
  register_handler(event_type, handler)  — in-process registration
  publish(event, session)                — emit + deliver to subscribers
  replay_events(from_ts, to_ts, types)   — reprocess DomainEventLog rows
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event, subscribe

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Platform event dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EventSubscriptionCreatedEvent(DomainEvent):
	event_type: str = "event.subscription.created"
	subscriber_plugin: str = ""
	event_type_subscribed: str = ""
	handler_function: str = ""


@dataclass
class EventSubscriptionDeactivatedEvent(DomainEvent):
	event_type: str = "event.subscription.deactivated"
	subscription_id: str = ""
	subscriber_plugin: str = ""
	reason: str = ""


@dataclass
class EventDeliveryFailedEvent(DomainEvent):
	event_type: str = "event.delivery.failed"
	source_event_id: str = ""
	subscription_id: str = ""
	attempt: int = 0
	error_message: str = ""


@dataclass
class EventDeliveryDeadLetteredEvent(DomainEvent):
	event_type: str = "event.delivery.dead_lettered"
	source_event_id: str = ""
	subscription_id: str = ""
	total_attempts: int = 0


@dataclass
class EventReplayedEvent(DomainEvent):
	event_type: str = "event.replayed"
	from_timestamp: str = ""
	to_timestamp: str = ""
	event_types_filter: list = field(default_factory=list)
	events_replayed: int = 0


# ---------------------------------------------------------------------------
# EventBus service
# ---------------------------------------------------------------------------

class EventBus:
	"""In-process + durable event bus for ERP plugins.

	In-process handlers are called synchronously inside publish().
	Delivery results are logged to EventDeliveryLog (append-only).

	Usage::

	    bus = EventBus()
	    bus.register_handler("invoice.paid", handle_invoice_paid)
	    bus.publish(InvoicePaidEvent(...), session)
	"""

	def __init__(self) -> None:
		# event_type → list[callable]
		self._handlers: dict[str, list[Callable]] = {}

	def register_handler(self, event_type: str, handler: Callable) -> None:
		"""Register an in-process handler for *event_type*.

		Also delegates to foundation.subscribe so emit_event() calls it too.
		"""
		self._handlers.setdefault(event_type, []).append(handler)
		subscribe(event_type, handler)
		log.debug("EventBus: registered handler %r for %r", handler, event_type)

	def publish(self, event: DomainEvent, session: Any) -> None:
		"""Emit *event* durably and deliver to all registered in-process handlers.

		Steps:
		1. emit_event() — writes DomainEventLog row + calls foundation bus.
		2. Deliver to handlers registered directly on this EventBus instance.
		3. Log each delivery attempt to EventDeliveryLog.
		"""
		emit_event(event, session)
		self._deliver(event, session)

	def _deliver(self, event: DomainEvent, session: Any) -> None:
		"""Deliver to durable subscriptions; write one log row per attempt."""
		from pgappforge.plugins.erp.platform.events.models import EventDeliveryLog
		from pgappforge.plugins.erp.platform.events.models import EventSubscription
		import sqlalchemy as sa

		# Load active subscriptions from DB for this event type
		try:
			subs = session.execute(
				sa.select(EventSubscription).where(
					EventSubscription.event_type == event.event_type,
					EventSubscription.is_active.is_(True),
				)
			).scalars().all()
		except Exception as exc:
			log.warning("EventBus._deliver: cannot load subscriptions: %s", exc)
			subs = []

		for sub in subs:
			handler = self._resolve_handler(sub.handler_function)
			max_attempts = self._max_delivery_attempts(sub)
			if handler is None:
				error_msg = f"Cannot resolve handler {sub.handler_function!r}"
				self._record_delivery_attempt(
					EventDeliveryLog,
					event,
					sub,
					attempt=1,
					status="DEAD_LETTER",
					error_message=error_msg,
					session=session,
				)
				self._emit_delivery_failure_event(
					event,
					sub,
					attempt=1,
					error_message=error_msg,
					session=session,
					dead_letter=True,
				)
				continue

			for attempt in range(1, max_attempts + 1):
				try:
					handler(event)
				except Exception as exc:
					error_msg = str(exc)[:2000]
					is_terminal = attempt >= max_attempts
					status = "DEAD_LETTER" if is_terminal else "FAILED"
					self._record_delivery_attempt(
						EventDeliveryLog,
						event,
						sub,
						attempt=attempt,
						status=status,
						error_message=error_msg,
						session=session,
					)
					self._emit_delivery_failure_event(
						event,
						sub,
						attempt=attempt,
						error_message=error_msg,
						session=session,
						dead_letter=is_terminal,
					)
					log.warning(
						"EventBus: handler %r for %r failed on attempt %s/%s: %s",
						sub.handler_function,
						event.event_type,
						attempt,
						max_attempts,
						exc,
					)
					if is_terminal:
						break
					continue

				self._record_delivery_attempt(
					EventDeliveryLog,
					event,
					sub,
					attempt=attempt,
					status="DELIVERED",
					error_message=None,
					session=session,
				)
				break

	@staticmethod
	def _max_delivery_attempts(sub: Any) -> int:
		"""Return the bounded retry count for a subscription row."""
		retry_count = EventBus._positive_int(getattr(sub, "retry_count", None), 1)
		dead_letter_after = EventBus._positive_int(
			getattr(sub, "dead_letter_after", None),
			retry_count,
		)
		return max(1, min(retry_count, dead_letter_after))

	@staticmethod
	def _positive_int(value: Any, default: int) -> int:
		try:
			parsed = int(value)
		except (TypeError, ValueError):
			return default
		return parsed if parsed > 0 else default

	@staticmethod
	def _record_delivery_attempt(
		log_model: Any,
		event: DomainEvent,
		sub: Any,
		attempt: int,
		status: str,
		error_message: str | None,
		session: Any,
	) -> None:
		try:
			log_row = log_model(
				event_id=event.event_id,
				subscription_id=sub.id,
				delivery_attempt=attempt,
				delivered_at=datetime.now(timezone.utc),
				status=status,
				error_message=error_message,
			)
			session.add(log_row)
		except Exception as exc:
			log.error("EventBus: failed to write EventDeliveryLog: %s", exc)

	@staticmethod
	def _emit_delivery_failure_event(
		event: DomainEvent,
		sub: Any,
		attempt: int,
		error_message: str,
		session: Any,
		dead_letter: bool,
	) -> None:
		"""Emit best-effort delivery failure/dead-letter domain events."""
		try:
			emit_event(
				EventDeliveryFailedEvent(
					aggregate_id=event.event_id,
					aggregate_type="DomainEvent",
					tenant_id=event.tenant_id,
					source_event_id=event.event_id,
					subscription_id=str(sub.id),
					attempt=attempt,
					error_message=error_message,
				),
				session,
			)
			if dead_letter:
				emit_event(
					EventDeliveryDeadLetteredEvent(
						aggregate_id=event.event_id,
						aggregate_type="DomainEvent",
						tenant_id=event.tenant_id,
						source_event_id=event.event_id,
						subscription_id=str(sub.id),
						total_attempts=attempt,
					),
					session,
				)
		except Exception as exc:
			log.warning("EventBus: failed to emit delivery outcome event: %s", exc)

	def replay_events(
		self,
		from_timestamp: datetime,
		to_timestamp: datetime,
		session: Any,
		event_types: list[str] | None = None,
	) -> dict:
		"""Reprocess DomainEventLog rows within a time window.

		Loads rows from erp_domain_event_log in time order and re-delivers
		them to in-process handlers.  Does NOT re-insert new DomainEventLog
		rows — only re-runs the handler delivery path.

		Returns: {"replayed": count, "errors": count}
		"""
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		import sqlalchemy as sa

		q = sa.select(DomainEventLog).where(
			DomainEventLog.published_at >= from_timestamp,
			DomainEventLog.published_at <= to_timestamp,
		).order_by(DomainEventLog.published_at)

		if event_types:
			q = q.where(DomainEventLog.event_type.in_(event_types))

		rows = session.execute(q).scalars().all()
		replayed = 0
		errors = 0

		for row in rows:
			handlers = self._handlers.get(row.event_type, [])
			# Reconstruct a minimal DomainEvent for handler compatibility
			synthetic = DomainEvent(
				event_id=row.event_id,
				event_type=row.event_type,
				aggregate_id=row.aggregate_id or "",
				aggregate_type=row.aggregate_type or "",
				tenant_id=str(row.tenant_id) if row.tenant_id else "",
				occurred_at=row.published_at,
				correlation_id=row.correlation_id or "",
				causation_id=row.causation_id or "",
				payload=row.payload or {},
			)
			for handler in handlers:
				try:
					handler(synthetic)
					replayed += 1
				except Exception as exc:
					errors += 1
					log.warning(
						"EventBus.replay: handler %r for %r raised: %s",
						getattr(handler, "__name__", "?"),
						row.event_type,
						exc,
					)

		log.info(
			"EventBus.replay_events: %d rows processed, %d handler calls, %d errors",
			len(rows), replayed, errors,
		)
		return {"replayed": replayed, "errors": errors, "rows_processed": len(rows)}

	@staticmethod
	def _resolve_handler(dotted_path: str) -> Callable | None:
		"""Import and return the callable at *dotted_path*, or None on failure."""
		if not dotted_path:
			return None
		parts = dotted_path.rsplit(".", 1)
		if len(parts) != 2:
			log.warning("EventBus: invalid handler path %r", dotted_path)
			return None
		module_path, attr = parts
		try:
			import importlib
			mod = importlib.import_module(module_path)
			return getattr(mod, attr)
		except Exception as exc:
			log.warning("EventBus: cannot resolve handler %r: %s", dotted_path, exc)
			return None


# Module-level singleton — plugins call get_event_bus() to obtain it
_BUS: EventBus | None = None


def get_event_bus() -> EventBus:
	"""Return the module-level EventBus singleton (created on first call)."""
	global _BUS
	if _BUS is None:
		_BUS = EventBus()
	return _BUS


__all__ = [
	"EventBus",
	"get_event_bus",
	"EventSubscriptionCreatedEvent",
	"EventSubscriptionDeactivatedEvent",
	"EventDeliveryFailedEvent",
	"EventDeliveryDeadLetteredEvent",
	"EventReplayedEvent",
]
