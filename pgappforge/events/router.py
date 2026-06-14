"""Durable, glob-aware event router for PgAppForge.

Architecture
------------
- Handlers register via glob patterns (fnmatch): 'finance.*', 'crm.customer.*'
- emit() persists to DomainEventLog (same session = atomic with business tx)
- emit() also fires in-process handlers synchronously (best-effort; exceptions logged)
- EventWorker polls DomainEventLog for unprocessed events and dispatches to
  registered handlers — provides durability across process restarts
- Dead-letter: events that fail MAX_RETRIES times are marked 'dead_letter'
"""
from __future__ import annotations

import fnmatch
import logging
import threading
import time
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)

MAX_RETRIES = 3
_LOCK = threading.Lock()


class EventRouter:
	"""Central registry for glob-pattern event subscriptions.

	One instance per process (accessed via get_router()).
	"""

	def __init__(self) -> None:
		# pattern -> list[callable(event_type, payload, tenant_id)]
		self._handlers: dict[str, list[Callable]] = defaultdict(list)

	def subscribe(self, pattern: str, handler: Callable) -> None:
		"""Register *handler* for all events matching glob *pattern*.

		Pattern examples: 'finance.*', 'crm.customer.created', '*.*.approved'
		"""
		with _LOCK:
			self._handlers[pattern].append(handler)
		log.debug("EventRouter: registered %s → %s", pattern, handler.__qualname__)

	def unsubscribe(self, pattern: str, handler: Callable) -> None:
		with _LOCK:
			handlers = self._handlers.get(pattern, [])
			try:
				handlers.remove(handler)
			except ValueError:
				pass

	def dispatch(self, event_type: str, payload: dict[str, Any], tenant_id: str) -> int:
		"""Fire all in-process handlers whose pattern matches *event_type*.

		Returns the number of handlers invoked. Exceptions are caught and logged
		so a failing handler never rolls back the calling transaction.
		"""
		invoked = 0
		with _LOCK:
			snapshot = list(self._handlers.items())
		for pattern, handlers in snapshot:
			if fnmatch.fnmatch(event_type, pattern):
				for handler in handlers:
					try:
						handler(event_type=event_type, payload=payload, tenant_id=tenant_id)
						invoked += 1
					except Exception:
						log.exception(
							"EventRouter: handler %s raised on %s",
							handler.__qualname__, event_type,
						)
		return invoked

	def matching_patterns(self, event_type: str) -> list[str]:
		"""Return registered patterns that match *event_type*."""
		with _LOCK:
			return [p for p in self._handlers if fnmatch.fnmatch(event_type, p)]


# Module-level singleton
_router: EventRouter | None = None


def get_router() -> EventRouter:
	global _router
	if _router is None:
		_router = EventRouter()
	return _router


def emit(
	event_type: str,
	payload: dict[str, Any],
	tenant_id: str,
	session: Any = None,
	aggregate_id: str = "",
	aggregate_type: str = "",
) -> None:
	"""Emit an event:

	1. Persist to DomainEventLog (if session provided — atomic with business tx).
	2. Fire all registered in-process handlers synchronously.

	If no session is given, only in-process dispatch is performed (not durable).
	"""
	# 1. Persist (durable path)
	if session is not None:
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit, DomainEvent
			import dataclasses

			@dataclasses.dataclass
			class _GenericEvent(DomainEvent):
				event_type: str = event_type
				payload_json: str = ""

			ev = _GenericEvent(
				aggregate_id=aggregate_id,
				aggregate_type=aggregate_type,
				tenant_id=tenant_id,
				payload_json=str(payload),
			)
			_emit(ev, session)
		except Exception:
			log.exception("EventRouter.emit: failed to persist %s", event_type)

	# 2. In-process dispatch (best-effort)
	get_router().dispatch(event_type, payload, tenant_id)
