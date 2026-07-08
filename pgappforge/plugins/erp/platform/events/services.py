"""
pgappforge/plugins/erp/platform/events/services.py

EventBusService — stateless service for managing event subscriptions
and replaying events.

All methods accept an explicit SQLAlchemy Session; callers own transaction
boundaries.  No Flask context assumed — safe for CLI and background jobs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EventBusServiceError(Exception):
	"""Base error for EventBus domain violations."""


class SubscriptionNotFoundError(EventBusServiceError):
	"""No EventSubscription with the given id."""


class DuplicateSubscriptionError(EventBusServiceError):
	"""Plugin already subscribed to this event_type."""


# ---------------------------------------------------------------------------
# EventBusService
# ---------------------------------------------------------------------------

class EventBusService:
	"""Stateless service for EventBus subscription management.

	Manages the durable EventSubscription registry and provides
	replay capability over DomainEventLog.
	"""

	# ------------------------------------------------------------------
	# create_subscription
	# ------------------------------------------------------------------

	def create_subscription(
		self,
		session: Any,
		subscriber_plugin: str,
		event_type: str,
		handler_function: str,
		retry_count: int = 3,
		dead_letter_after: int = 5,
		description: str | None = None,
		filter_conditions: dict | None = None,
		tenant_id: str | None = None,
	) -> dict:
		"""Register a new subscription in the durable store.

		Raises DuplicateSubscriptionError if (subscriber_plugin, event_type)
		already exists and is_active=True.

		Returns: dict with subscription_id.
		"""
		from pgappforge.plugins.erp.platform.events.models import EventSubscription
		from pgappforge.plugins.erp.platform.events.events import (
			EventSubscriptionCreatedEvent,
			get_event_bus,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event
		retry_count = self._positive_policy_int(retry_count, "retry_count")
		dead_letter_after = self._positive_policy_int(
			dead_letter_after,
			"dead_letter_after",
		)
		if retry_count > dead_letter_after:
			raise EventBusServiceError(
				"retry_count cannot exceed dead_letter_after"
			)

		# Check for existing active subscription
		existing = session.execute(
			select(EventSubscription).where(
				EventSubscription.subscriber_plugin == subscriber_plugin,
				EventSubscription.event_type == event_type,
				EventSubscription.is_active.is_(True),
			)
		).scalar_one_or_none()

		if existing is not None:
			raise DuplicateSubscriptionError(
				f"Plugin {subscriber_plugin!r} already subscribed to {event_type!r}"
			)

		sub = EventSubscription(
			tenant_id=tenant_id,
			subscriber_plugin=subscriber_plugin,
			event_type=event_type,
			handler_function=handler_function,
			retry_count=retry_count,
			dead_letter_after=dead_letter_after,
			description=description,
			filter_conditions=filter_conditions or {},
			is_active=True,
		)
		session.add(sub)
		session.flush()

		emit_event(
			EventSubscriptionCreatedEvent(
				aggregate_id=sub.id,
				aggregate_type="EventSubscription",
				tenant_id=tenant_id or "",
				subscriber_plugin=subscriber_plugin,
				event_type_subscribed=event_type,
				handler_function=handler_function,
			),
			session,
		)

		# Also register in-process
		bus = get_event_bus()
		handler = bus._resolve_handler(handler_function)
		if handler:
			bus.register_handler(event_type, handler)

		log.info(
			"EventBusService: created subscription %r → %r for %r",
			subscriber_plugin, event_type, handler_function,
		)
		return {"subscription_id": sub.id, "status": "created"}

	# ------------------------------------------------------------------
	# deactivate_subscription
	# ------------------------------------------------------------------

	def deactivate_subscription(
		self,
		session: Any,
		subscription_id: str,
		reason: str = "",
	) -> dict:
		"""Deactivate a subscription (soft delete).

		Delivery will cease; the subscription row is retained for audit.
		"""
		from pgappforge.plugins.erp.platform.events.models import EventSubscription
		from pgappforge.plugins.erp.platform.events.events import (
			EventSubscriptionDeactivatedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		sub = session.get(EventSubscription, subscription_id)
		if sub is None:
			raise SubscriptionNotFoundError(
				f"EventSubscription {subscription_id!r} not found"
			)

		sub.is_active = False
		emit_event(
			EventSubscriptionDeactivatedEvent(
				aggregate_id=subscription_id,
				aggregate_type="EventSubscription",
				tenant_id=str(sub.tenant_id) if sub.tenant_id else "",
				subscription_id=subscription_id,
				subscriber_plugin=sub.subscriber_plugin,
				reason=reason,
			),
			session,
		)
		log.info("EventBusService: deactivated subscription %r", subscription_id)
		return {"subscription_id": subscription_id, "status": "deactivated"}

	# ------------------------------------------------------------------
	# replay_events
	# ------------------------------------------------------------------

	def replay_events(
		self,
		session: Any,
		from_timestamp: datetime,
		to_timestamp: datetime,
		event_types: list[str] | None = None,
		tenant_id: str | None = None,
	) -> dict:
		"""Replay DomainEventLog rows through the in-process EventBus.

		Does NOT re-insert DomainEventLog rows — only re-fires handlers.

		Returns: {"rows_processed": int, "replayed": int, "errors": int}
		"""
		from pgappforge.plugins.erp.platform.events.events import get_event_bus
		from pgappforge.plugins.erp.platform.events.events import EventReplayedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		bus = get_event_bus()
		result = bus.replay_events(
			from_timestamp=from_timestamp,
			to_timestamp=to_timestamp,
			session=session,
			event_types=event_types,
		)

		emit_event(
			EventReplayedEvent(
				aggregate_id="EventBus",
				aggregate_type="EventBus",
				tenant_id=tenant_id or "",
				from_timestamp=from_timestamp.isoformat(),
				to_timestamp=to_timestamp.isoformat(),
				event_types_filter=event_types or [],
				events_replayed=result["replayed"],
			),
			session,
		)
		return result

	# ------------------------------------------------------------------
	# get_delivery_stats
	# ------------------------------------------------------------------

	def get_delivery_stats(
		self,
		session: Any,
		subscription_id: str | None = None,
		since: datetime | None = None,
	) -> dict:
		"""Return delivery statistics from EventDeliveryLog.

		Returns counts by status: DELIVERED, FAILED, DEAD_LETTER.
		"""
		from pgappforge.plugins.erp.platform.events.models import EventDeliveryLog

		q = select(
			EventDeliveryLog.status,
			func.count().label("count"),
		).group_by(EventDeliveryLog.status)

		if subscription_id:
			q = q.where(EventDeliveryLog.subscription_id == subscription_id)
		if since:
			q = q.where(EventDeliveryLog.delivered_at >= since)

		rows = session.execute(q).all()
		stats = {r.status: r.count for r in rows}
		total = sum(stats.values())
		return {
			"total": total,
			"delivered": stats.get("DELIVERED", 0),
			"failed": stats.get("FAILED", 0),
			"dead_letter": stats.get("DEAD_LETTER", 0),
		}

	# ------------------------------------------------------------------
	# list_subscriptions
	# ------------------------------------------------------------------

	def list_subscriptions(
		self,
		session: Any,
		event_type: str | None = None,
		active_only: bool = True,
	) -> list[dict]:
		"""List registered subscriptions with optional filters."""
		from pgappforge.plugins.erp.platform.events.models import EventSubscription

		q = select(EventSubscription).order_by(
			EventSubscription.subscriber_plugin,
			EventSubscription.event_type,
		)
		if active_only:
			q = q.where(EventSubscription.is_active.is_(True))
		if event_type:
			q = q.where(EventSubscription.event_type == event_type)

		rows = session.execute(q).scalars().all()
		return [
			{
				"id": r.id,
				"subscriber_plugin": r.subscriber_plugin,
				"event_type": r.event_type,
				"handler_function": r.handler_function,
				"is_active": r.is_active,
				"retry_count": r.retry_count,
				"dead_letter_after": r.dead_letter_after,
				"description": r.description,
			}
			for r in rows
		]


	@staticmethod
	def _positive_policy_int(value: Any, field_name: str) -> int:
		try:
			parsed = int(value)
		except (TypeError, ValueError) as exc:
			raise EventBusServiceError(f"{field_name} must be a positive integer") from exc
		if parsed < 1:
			raise EventBusServiceError(f"{field_name} must be a positive integer")
		return parsed


__all__ = [
	"EventBusService",
	"EventBusServiceError",
	"SubscriptionNotFoundError",
	"DuplicateSubscriptionError",
]
