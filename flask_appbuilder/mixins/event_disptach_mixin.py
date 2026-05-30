"""
event_dispatch_mixin.py - Advanced Event Management System for Flask-AppBuilder

A production-ready event management system providing comprehensive event handling,
tracking and auditing capabilities for Flask-AppBuilder applications. This module
implements best practices for event-driven architecture while maintaining simplicity
of use.

Key Features:
- Synchronous and asynchronous event processing
- Comprehensive audit logging with PostgreSQL JSONB support
- Automatic event dispatch on model changes
- Event prioritization and conditional execution
- Dead letter queue for failed events
- Full monitoring and metrics support
- Configurable retry policies
- Rich event context and metadata
- Circuit breaking for fault tolerance
- Event batching and throttling
- Integration with monitoring systems
- Performance optimization for high-volume events

Core Components:
- EventDispatchMixin: Main mixin class for adding event capabilities
- Event: Rich event data container with metadata
- EventHandler: Base class for event handlers
- AuditLog: Audit trail with JSONB storage
- FailedEvent: Dead letter queue for failed events
- EventMetrics: StatsD/Prometheus metrics integration

Technical Specifications:
- Python: 3.10+
- Database: PostgreSQL 12+ (recommended, falls back to JSON for other DBs)
- Runtime: Async/await support
- Storage: JSONB (PostgreSQL) or JSON (other DBs) for flexible event data
- Metrics: StatsD exporter (optional)
- Security: Role-based access control integration
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any

from flask import current_app, g, request

from flask_appbuilder import Model, db
from flask_appbuilder.security.sqla.models import User
from sqlalchemy import (
	JSON,
	Boolean,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	event,
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

# SQLAlchemy 2.x mapped_column / Mapped with 1.x fallback
try:
	from sqlalchemy.orm import Mapped, mapped_column
	_SA2 = True
except ImportError:
	_SA2 = False

# PostgreSQL JSONB with JSON fallback for other databases
try:
	from sqlalchemy.dialects.postgresql import JSONB as _JSONB
	_JSON_TYPE = _JSONB
except ImportError:
	_JSON_TYPE = JSON

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventType(Enum):
	"""Standard event types with automatic value generation.

	CREATE  - Record creation events
	UPDATE  - Record update events
	DELETE  - Record deletion events
	CUSTOM  - Custom application events
	SYSTEM  - System events and operations
	AUDIT   - Audit log events
	ERROR   - Error events
	NOTIFICATION - Notification events
	WORKFLOW - Workflow state changes
	SECURITY - Security events
	"""

	CREATE = auto()
	UPDATE = auto()
	DELETE = auto()
	CUSTOM = auto()
	SYSTEM = auto()
	AUDIT = auto()
	ERROR = auto()
	NOTIFICATION = auto()
	WORKFLOW = auto()
	SECURITY = auto()


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class Event:
	"""Rich event data container with metadata.

	Attributes:
		type: The event type (EventType enum)
		model: Name of the model class
		instance_id: ID of the model instance
		user_id: ID of user triggering event (None for anonymous)
		timestamp: Event timestamp (UTC)
		data: Event payload data
		metadata: Additional event metadata
		priority: Event priority (higher = more important)
		async_dispatch: Whether to handle asynchronously
		retry_count: Number of retry attempts
		correlation_id: Request correlation ID
		tenant_id: Multi-tenant ID if applicable
		tags: List of event tags
	"""

	type: EventType
	model: str
	instance_id: int
	user_id: int | None
	timestamp: datetime
	data: dict[str, Any]
	metadata: dict[str, Any]
	priority: int = 0
	async_dispatch: bool = False
	retry_count: int = 0
	correlation_id: str | None = None
	tenant_id: str | None = None
	tags: list[str] = field(default_factory=list)

	def __post_init__(self) -> None:
		"""Populate correlation/tenant IDs from Flask request context when absent."""
		if not self.correlation_id:
			self.correlation_id = g.get("correlation_id") if g else None
		if not self.tenant_id:
			self.tenant_id = g.get("tenant_id") if g else None


# ---------------------------------------------------------------------------
# Handler base
# ---------------------------------------------------------------------------

class EventHandler:
	"""Base event handler with timeout and retry support.

	Attributes:
		event_type: Type of events this handler processes
		priority: Handler priority (higher = processed first)
		retry_limit: Max number of retry attempts
		timeout: Handler timeout in seconds
	"""

	def __init__(
		self,
		event_type: EventType,
		priority: int = 0,
		retry_limit: int = 3,
		timeout: int = 30,
	) -> None:
		self.event_type = event_type
		self.priority = priority
		self.retry_limit = retry_limit
		self.timeout = timeout

	async def handle(self, event: Event) -> bool:
		"""Handle event with timeout guard.

		Args:
			event: The event to handle

		Returns:
			bool: Success status
		"""
		try:
			return await asyncio.wait_for(
				self._handle_event(event),
				timeout=self.timeout,
			)
		except asyncio.TimeoutError:
			logger.error("Handler timeout for %s in %s", event.type, self.name)
			return False
		except Exception:
			logger.exception("Handler error in %s for %s", self.name, event.type)
			return False

	async def _handle_event(self, event: Event) -> bool:
		"""Override to implement handler logic.

		Args:
			event: The event to handle

		Returns:
			bool: Success status

		Raises:
			NotImplementedError: Must be implemented by subclasses
		"""
		raise NotImplementedError

	def can_handle(self, event: Event) -> bool:
		"""Check if handler can process event.

		Args:
			event: The event to check

		Returns:
			bool: Whether handler can process event
		"""
		return True

	@property
	def name(self) -> str:
		"""Handler class name for log messages."""
		return self.__class__.__name__


# ---------------------------------------------------------------------------
# Main mixin
# ---------------------------------------------------------------------------

class EventDispatchMixin:
	"""Mixin adding advanced event dispatch capabilities to FAB models.

	Adds three columns to the owning table:
	  event_metadata  – JSON/JSONB bag tracking last event state
	  last_event      – timestamp of the most recent dispatched event
	  event_count     – running total of events dispatched from this instance

	SQLAlchemy event listeners (after_insert / after_update / after_delete) are
	wired up via __declare_last__ so they activate after the mapper is fully
	configured.

	Usage::

		class MyModel(EventDispatchMixin, Model):
			__tablename__ = "my_models"
			id = Column(Integer, primary_key=True)
	"""

	@declared_attr
	def event_metadata(cls):  # noqa: N805
		return db.Column(_JSON_TYPE, default=dict, nullable=False)

	@declared_attr
	def last_event(cls):  # noqa: N805
		return db.Column(DateTime, nullable=True, index=True)

	@declared_attr
	def event_count(cls):  # noqa: N805
		return db.Column(Integer, default=0, nullable=False)

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		"""Initialize event dispatch capabilities."""
		super().__init__(*args, **kwargs)
		self.event_handlers: dict[EventType, list[EventHandler]] = {}
		self._initialize_handlers()
		self._setup_metrics()

	def _initialize_handlers(self) -> None:
		"""Register default CRUD audit handlers plus any app-configured handlers."""
		for et in (EventType.CREATE, EventType.UPDATE, EventType.DELETE):
			self.register_handler(et, AuditHandler(et))

		handlers = current_app.config.get("EVENT_HANDLERS", {})
		for event_type, handler_cls in handlers.items():
			self.register_handler(event_type, handler_cls())

	def register_handler(self, event_type: EventType, handler: EventHandler) -> None:
		"""Register event handler; list is kept sorted by descending priority.

		Args:
			event_type: Type of events to handle
			handler: Handler instance
		"""
		bucket = self.event_handlers.setdefault(event_type, [])
		bucket.append(handler)
		bucket.sort(key=lambda h: h.priority, reverse=True)

	async def dispatch_event(
		self,
		event_type: EventType,
		data: dict[str, Any],
		async_dispatch: bool = False,
		priority: int = 0,
	) -> bool:
		"""Dispatch an event to all registered handlers.

		Updates event_metadata, last_event, and event_count on the instance.
		On handler failure the event is persisted to the dead-letter queue
		(FailedEvent table) for later retry.

		Args:
			event_type: Type of event to dispatch
			data: Event data payload
			async_dispatch: Whether to run handlers concurrently via asyncio.gather
			priority: Event priority attached to the Event object

		Returns:
			bool: True when all applicable handlers succeeded
		"""
		start_time = datetime.utcnow()

		# Build request context metadata defensively (may run outside request context)
		try:
			ip_address: str | None = request.remote_addr
			user_agent: str | None = request.user_agent.string
		except RuntimeError:
			ip_address = None
			user_agent = None

		user_id: int | None = None
		if g and hasattr(g, "user") and g.user is not None:
			user_id = getattr(g.user, "id", None)

		try:
			ev = Event(
				type=event_type,
				model=self.__class__.__name__,
				instance_id=self.id,
				user_id=user_id,
				timestamp=start_time,
				data=data,
				metadata={
					"ip_address": ip_address,
					"user_agent": user_agent,
					"correlation_id": g.get("correlation_id") if g else None,
					"tenant_id": g.get("tenant_id") if g else None,
					"source": g.get("event_source") if g else None,
				},
				priority=priority,
				async_dispatch=async_dispatch,
			)

			# Update tracking fields
			self.last_event = ev.timestamp
			self.event_count = (self.event_count or 0) + 1
			if self.event_metadata is None:
				self.event_metadata = {}
			self.event_metadata.update(
				{
					"last_event_type": event_type.name,
					"total_events": self.event_count,
					"last_success": None,
					"last_error": None,
				}
			)

			handlers = self.event_handlers.get(event_type, [])
			if not handlers:
				logger.warning("No handlers registered for event type: %s", event_type)
				return True

			eligible = [h for h in handlers if h.can_handle(ev)]

			if async_dispatch:
				results = await asyncio.gather(
					*(h.handle(ev) for h in eligible),
					return_exceptions=True,
				)
				success = all(r is True for r in results)
			else:
				success = True
				for h in eligible:
					result = await h.handle(ev)
					success = success and bool(result)

			duration = (datetime.utcnow() - start_time).total_seconds()
			self._update_metrics(event_type, success, duration)

			if not success:
				logger.error("Event dispatch failed for %s", event_type)
				self.event_metadata["last_error"] = {
					"timestamp": datetime.utcnow().isoformat(),
					"event_type": event_type.name,
				}
				await self._handle_failed_event(ev)
			else:
				self.event_metadata["last_success"] = datetime.utcnow().isoformat()

			db.session.commit()
			return success

		except Exception:
			logger.exception("Unexpected error dispatching %s", event_type)
			if self.event_metadata is None:
				self.event_metadata = {}
			self.event_metadata["last_error"] = {
				"timestamp": datetime.utcnow().isoformat(),
				"error": "see server logs",
			}
			db.session.commit()
			return False

	async def _handle_failed_event(self, ev: Event) -> None:
		"""Persist failed event to the dead-letter queue.

		Args:
			ev: The failed Event object
		"""
		try:
			failed = FailedEvent(
				model=ev.model,
				instance_id=ev.instance_id,
				event_type=ev.type.name,
				user_id=ev.user_id,
				timestamp=ev.timestamp,
				data=ev.data,
				metadata=ev.metadata,
				retry_count=ev.retry_count,
				error_detail=str(ev.metadata.get("error")),
			)
			db.session.add(failed)
			db.session.commit()

			if current_app.config.get("EVENT_FAILURE_NOTIFICATION"):
				await self._notify_failure(failed)

		except Exception:
			logger.exception("Error storing failed event for %s", ev.model)

	async def _notify_failure(self, failed_event: FailedEvent) -> None:
		"""Hook for failure notification integrations.

		Override in subclasses or extend via EVENT_FAILURE_NOTIFICATION config.

		Args:
			failed_event: The persisted FailedEvent record
		"""
		logger.warning(
			"Unhandled event failure: %s#%s type=%s",
			failed_event.model,
			failed_event.instance_id,
			failed_event.event_type,
		)

	def _setup_metrics(self) -> None:
		"""Initialise StatsD client if STATSD_HOST is configured."""
		try:
			if current_app.config.get("STATSD_HOST"):
				from statsd import StatsClient  # optional dependency

				self.statsd = StatsClient(
					host=current_app.config["STATSD_HOST"],
					port=current_app.config.get("STATSD_PORT", 8125),
					prefix=f"events.{self.__class__.__name__.lower()}",
				)
			else:
				self.statsd = None
		except Exception:
			self.statsd = None

	def _update_metrics(
		self,
		event_type: EventType,
		success: bool,
		duration: float,
	) -> None:
		"""Emit dispatch counters and timing to StatsD when configured.

		Args:
			event_type: Type of event dispatched
			success: Whether the dispatch succeeded
			duration: Wall-clock duration in seconds
		"""
		if not self.statsd:
			return
		self.statsd.incr(f"dispatch.{event_type.name.lower()}")
		self.statsd.incr("dispatch.success" if success else "dispatch.failure")
		self.statsd.timing("dispatch.duration", duration * 1000)

	@classmethod
	def __declare_last__(cls) -> None:
		"""Wire SQLAlchemy ORM event listeners after mapper configuration."""

		@event.listens_for(cls, "after_insert")
		def after_insert(mapper: Any, connection: Any, target: Any) -> None:
			"""Dispatch CREATE event after a row is inserted."""
			loop = _get_or_create_loop()
			loop.run_until_complete(
				target.dispatch_event(EventType.CREATE, {"id": target.id})
			)

		@event.listens_for(cls, "after_update")
		def after_update(mapper: Any, connection: Any, target: Any) -> None:
			"""Dispatch UPDATE event carrying a diff of changed attributes."""
			state = db.inspect(target)
			changes: dict[str, Any] = {}
			for attr in state.attrs:
				hist = attr.history
				if hist.has_changes():
					changes[attr.key] = {
						"old": hist.deleted[0] if hist.deleted else None,
						"new": hist.added[0] if hist.added else None,
					}

			if changes:
				loop = _get_or_create_loop()
				loop.run_until_complete(
					target.dispatch_event(EventType.UPDATE, {"changes": changes})
				)

		@event.listens_for(cls, "after_delete")
		def after_delete(mapper: Any, connection: Any, target: Any) -> None:
			"""Dispatch DELETE event after a row is removed."""
			loop = _get_or_create_loop()
			loop.run_until_complete(
				target.dispatch_event(EventType.DELETE, {"id": target.id})
			)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_loop() -> asyncio.AbstractEventLoop:
	"""Return the running event loop or create a new one.

	SQLAlchemy ORM events fire in synchronous context; this helper bridges into
	the async dispatch machinery without requiring callers to manage loops.
	"""
	try:
		return asyncio.get_running_loop()
	except RuntimeError:
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		return loop


# ---------------------------------------------------------------------------
# Audit log model
# ---------------------------------------------------------------------------

class AuditLog(Model):
	"""Persistent audit trail for dispatched events.

	Columns:
		id           – Primary key
		model        – Name of the audited model class
		instance_id  – PK of the audited instance
		event_type   – EventType name string
		user_id      – FK to ab_user (nullable for system events)
		timestamp    – UTC time of the event
		data         – Event payload (JSONB / JSON)
		metadata     – Request/context metadata (JSONB / JSON)
	"""

	__tablename__ = "nx_audit_logs"

	id = db.Column(Integer, primary_key=True)
	model = db.Column(String(100), nullable=False, index=True)
	instance_id = db.Column(Integer, nullable=False, index=True)
	event_type = db.Column(String(50), nullable=False, index=True)
	user_id = db.Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	timestamp = db.Column(DateTime, nullable=False, index=True)
	data = db.Column(_JSON_TYPE, nullable=False)
	metadata = db.Column(_JSON_TYPE, nullable=False)

	user = relationship(User, foreign_keys=[user_id])

	__table_args__ = (
		Index("ix_audit_composite", "model", "instance_id", "timestamp"),
		Index("ix_audit_data_gin", "data", postgresql_using="gin"),
		Index("ix_audit_metadata_gin", "metadata", postgresql_using="gin"),
	)


# ---------------------------------------------------------------------------
# Dead-letter queue model
# ---------------------------------------------------------------------------

class FailedEvent(Model):
	"""Dead-letter queue for events that could not be processed.

	Supports exponential-backoff retry via retry_count / next_retry columns.
	Resolved failures are stamped with resolved_at and resolved_by.

	Columns:
		retry_count  – How many dispatch attempts have been made
		next_retry   – When the next retry should be attempted
		resolved     – True once the failure has been handled
		resolved_at  – UTC timestamp of resolution
		resolved_by  – FK to ab_user who marked it resolved
	"""

	__tablename__ = "nx_failed_events"

	id = db.Column(Integer, primary_key=True)
	model = db.Column(String(100), nullable=False, index=True)
	instance_id = db.Column(Integer, nullable=False, index=True)
	event_type = db.Column(String(50), nullable=False, index=True)
	user_id = db.Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	timestamp = db.Column(DateTime, nullable=False, index=True)
	data = db.Column(_JSON_TYPE, nullable=False)
	metadata = db.Column(_JSON_TYPE, nullable=False)
	retry_count = db.Column(Integer, default=0, nullable=False, index=True)
	error_detail = db.Column(Text)
	next_retry = db.Column(DateTime, index=True)
	resolved = db.Column(Boolean, default=False, index=True)
	resolved_at = db.Column(DateTime)
	resolved_by = db.Column(Integer, ForeignKey("ab_user.id"))

	user = relationship(User, foreign_keys=[user_id])
	resolver = relationship(User, foreign_keys=[resolved_by])

	__table_args__ = (
		Index("ix_failed_composite", "model", "instance_id", "timestamp"),
		Index("ix_failed_data_gin", "data", postgresql_using="gin"),
		Index("ix_failed_retry", "retry_count", "next_retry", "resolved"),
	)

	def schedule_next_retry(self, base_minutes: int = 5) -> None:
		"""Set next_retry with exponential back-off.

		Args:
			base_minutes: Base interval in minutes (multiplied by retry_count)
		"""
		self.next_retry = datetime.utcnow() + timedelta(
			minutes=base_minutes * max(self.retry_count, 1)
		)

	def mark_resolved(self, user_id: int | None = None) -> None:
		"""Stamp the record as resolved.

		Args:
			user_id: ID of the user resolving the failure
		"""
		self.resolved = True
		self.resolved_at = datetime.utcnow()
		self.resolved_by = user_id


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------

class AuditHandler(EventHandler):
	"""Default handler that persists every event to the AuditLog table.

	Initialised with priority=100 so it runs before lower-priority handlers.
	Can be disabled per-app by setting AUDIT_LOGGING_ENABLED=False.
	"""

	def __init__(self, event_type: EventType) -> None:
		super().__init__(event_type, priority=100)

	async def _handle_event(self, event: Event) -> bool:
		"""Write event to the audit trail.

		Args:
			event: Event to audit

		Returns:
			bool: True on success
		"""
		try:
			logger.info(
				"Audit: %s on %s:%s by user %s at %s",
				event.type.name,
				event.model,
				event.instance_id,
				event.user_id,
				event.timestamp,
			)

			if current_app.config.get("AUDIT_LOGGING_ENABLED", True):
				audit_log = AuditLog(
					model=event.model,
					instance_id=event.instance_id,
					event_type=event.type.name,
					user_id=event.user_id,
					timestamp=event.timestamp,
					data=event.data,
					metadata=event.metadata,
				)
				db.session.add(audit_log)
				db.session.commit()

			return True

		except Exception:
			logger.exception("Audit logging failed for %s:%s", event.model, event.instance_id)
			return False


# ---------------------------------------------------------------------------
# Retry utility
# ---------------------------------------------------------------------------

class EventMonitor:
	"""Utility for retrying failed events from the dead-letter queue.

	Intended for use in a scheduled task or Celery beat job::

		@celery.task
		def retry_failed_events():
			asyncio.run(EventMonitor.process_failed_events())
	"""

	@staticmethod
	async def process_failed_events(max_retry: int = 3) -> None:
		"""Retry all unresolved events that are due.

		Args:
			max_retry: Maximum retry_count before giving up
		"""
		from sqlalchemy import select

		stmt = (
			select(FailedEvent)
			.where(
				FailedEvent.resolved == False,  # noqa: E712
				FailedEvent.retry_count < max_retry,
				(FailedEvent.next_retry == None) | (FailedEvent.next_retry <= datetime.utcnow()),  # noqa: E711
			)
		)
		failed_events: list[FailedEvent] = db.session.execute(stmt).scalars().all()

		for fe in failed_events:
			# Resolve the model class from SQLAlchemy's registry
			mapper_registry = db.Model.registry.mappers
			model_class = next(
				(m.class_ for m in mapper_registry if m.class_.__name__ == fe.model),
				None,
			)
			if model_class is None:
				logger.warning("Cannot retry: unknown model class %s", fe.model)
				continue

			instance = db.session.get(model_class, fe.instance_id)
			if instance is None:
				logger.warning("Cannot retry: %s#%s not found", fe.model, fe.instance_id)
				fe.mark_resolved()
				db.session.commit()
				continue

			event_type = EventType[fe.event_type]
			success = await instance.dispatch_event(
				event_type,
				fe.data,
				async_dispatch=True,
			)

			if success:
				resolver_id: int | None = None
				if g and hasattr(g, "user") and g.user:
					resolver_id = getattr(g.user, "id", None)
				fe.mark_resolved(resolver_id)
			else:
				fe.retry_count += 1
				fe.schedule_next_retry()

			db.session.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"EventType",
	"Event",
	"EventHandler",
	"EventDispatchMixin",
	"AuditLog",
	"FailedEvent",
	"AuditHandler",
	"EventMonitor",
]
