"""
pgappforge/plugins/erp/platform/events/views.py

Flask views for the Platform Events plugin.

Endpoints:
  EventSubscriptionView    GET /platform/events/subscriptions/
                           POST /platform/events/subscriptions/
                           POST /platform/events/subscriptions/<id>/deactivate
  EventDeliveryLogView     GET /platform/events/delivery-log/
  EventBusView             POST /platform/events/replay
                           GET  /platform/events/stats

Reports:
  GET /platform/events/reports/delivery-summary  — delivery rate by subscription
  GET /platform/events/reports/dead-letters      — all DEAD_LETTER entries
  GET /platform/events/reports/event-volume      — event type frequency heatmap
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.platform.events.services import EventBusService
	return EventBusService()


# ---------------------------------------------------------------------------
# EventSubscriptionView
# ---------------------------------------------------------------------------

class EventSubscriptionView(BaseView):
	"""Manage durable event subscriptions.

	GET  /platform/events/subscriptions/                — list active subscriptions
	POST /platform/events/subscriptions/                — create subscription
	POST /platform/events/subscriptions/<id>/deactivate — deactivate
	"""

	route_base = "/platform/events/subscriptions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		event_type = request.args.get("event_type")
		active_only = request.args.get("active_only", "true").lower() != "false"
		rows = _svc().list_subscriptions(
			session, event_type=event_type, active_only=active_only
		)
		return jsonify(rows)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("subscriber_plugin", "event_type", "handler_function")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			result = _svc().create_subscription(
				session=session,
				subscriber_plugin=data["subscriber_plugin"],
				event_type=data["event_type"],
				handler_function=data["handler_function"],
				retry_count=data.get("retry_count", 3),
				dead_letter_after=data.get("dead_letter_after", 5),
				description=data.get("description"),
				filter_conditions=data.get("filter_conditions"),
				tenant_id=data.get("tenant_id"),
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:subscription_id>/deactivate", methods=["POST"])
	@has_access
	def deactivate(self, subscription_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			result = _svc().deactivate_subscription(
				session=session,
				subscription_id=subscription_id,
				reason=data.get("reason", ""),
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# EventDeliveryLogView
# ---------------------------------------------------------------------------

class EventDeliveryLogView(BaseView):
	"""Read-only delivery log browser.

	GET /platform/events/delivery-log/                     — paginated log
	GET /platform/events/delivery-log/?status=DEAD_LETTER  — filter by status
	"""

	route_base = "/platform/events/delivery-log"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.platform.events.models import EventDeliveryLog
		session = _get_session()
		status_filter = request.args.get("status")
		sub_filter = request.args.get("subscription_id")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = sa.select(EventDeliveryLog).order_by(
			EventDeliveryLog.delivered_at.desc()
		).limit(limit)
		if status_filter:
			q = q.where(EventDeliveryLog.status == status_filter)
		if sub_filter:
			q = q.where(EventDeliveryLog.subscription_id == sub_filter)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"event_id": r.event_id,
				"subscription_id": r.subscription_id,
				"delivery_attempt": r.delivery_attempt,
				"delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
				"status": r.status,
				"error_message": r.error_message,
				"response_code": r.response_code,
			}
			for r in rows
		])


# ---------------------------------------------------------------------------
# EventBusView
# ---------------------------------------------------------------------------

class EventBusView(BaseView):
	"""EventBus management — replay and stats.

	POST /platform/events/replay  — replay events in a time window
	GET  /platform/events/stats   — delivery statistics
	"""

	route_base = "/platform/events"
	default_view = "stats"

	@expose("/stats")
	@has_access
	def stats(self):
		session = _get_session()
		subscription_id = request.args.get("subscription_id")
		since_str = request.args.get("since")
		since = datetime.fromisoformat(since_str) if since_str else None
		result = _svc().get_delivery_stats(
			session, subscription_id=subscription_id, since=since
		)
		return jsonify(result)

	@expose("/replay", methods=["POST"])
	@has_access
	def replay(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("from_timestamp") or not data.get("to_timestamp"):
			return jsonify({"error": "from_timestamp and to_timestamp required"}), 400
		try:
			from_ts = datetime.fromisoformat(data["from_timestamp"])
			to_ts = datetime.fromisoformat(data["to_timestamp"])
		except ValueError as exc:
			return jsonify({"error": f"Invalid timestamp: {exc}"}), 400

		result = _svc().replay_events(
			session=session,
			from_timestamp=from_ts,
			to_timestamp=to_ts,
			event_types=data.get("event_types"),
			tenant_id=data.get("tenant_id"),
		)
		session.commit()
		return jsonify(result)


# ---------------------------------------------------------------------------
# EventReportView  — 3 canned reports
# ---------------------------------------------------------------------------

class EventReportView(BaseView):
	"""Platform event reports.

	GET /platform/events/reports/delivery-summary  — per-subscription delivery rate
	GET /platform/events/reports/dead-letters      — all DEAD_LETTER entries
	GET /platform/events/reports/event-volume      — event type frequency
	"""

	route_base = "/platform/events/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"reports": [
				{"name": "Delivery Summary",
				 "endpoint": "/platform/events/reports/delivery-summary"},
				{"name": "Dead Letters",
				 "endpoint": "/platform/events/reports/dead-letters"},
				{"name": "Event Volume",
				 "endpoint": "/platform/events/reports/event-volume"},
			]
		})

	@expose("/delivery-summary")
	@has_access
	def delivery_summary(self):
		from pgappforge.plugins.erp.platform.events.models import (
			EventDeliveryLog, EventSubscription,
		)
		session = _get_session()
		from sqlalchemy import func as F
		rows = session.execute(
			sa.select(
				EventSubscription.subscriber_plugin,
				EventSubscription.event_type,
				EventDeliveryLog.status,
				F.count().label("count"),
			)
			.join(
				EventDeliveryLog,
				EventDeliveryLog.subscription_id == EventSubscription.id,
			)
			.group_by(
				EventSubscription.subscriber_plugin,
				EventSubscription.event_type,
				EventDeliveryLog.status,
			)
			.order_by(EventSubscription.subscriber_plugin)
		).all()
		return jsonify([
			{
				"subscriber_plugin": r.subscriber_plugin,
				"event_type": r.event_type,
				"status": r.status,
				"count": r.count,
			}
			for r in rows
		])

	@expose("/dead-letters")
	@has_access
	def dead_letters(self):
		from pgappforge.plugins.erp.platform.events.models import EventDeliveryLog
		session = _get_session()
		rows = session.execute(
			sa.select(EventDeliveryLog)
			.where(EventDeliveryLog.status == "DEAD_LETTER")
			.order_by(EventDeliveryLog.delivered_at.desc())
			.limit(200)
		).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"event_id": r.event_id,
				"subscription_id": r.subscription_id,
				"delivery_attempt": r.delivery_attempt,
				"delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
				"error_message": r.error_message,
			}
			for r in rows
		])

	@expose("/event-volume")
	@has_access
	def event_volume(self):
		"""Event type frequency from DomainEventLog."""
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		from sqlalchemy import func as F
		session = _get_session()
		since_str = request.args.get("since")
		since = datetime.fromisoformat(since_str) if since_str else None

		q = (
			sa.select(
				DomainEventLog.event_type,
				F.count().label("count"),
				F.max(DomainEventLog.published_at).label("last_seen"),
			)
			.group_by(DomainEventLog.event_type)
			.order_by(sa.desc("count"))
			.limit(100)
		)
		if since:
			q = q.where(DomainEventLog.published_at >= since)

		rows = session.execute(q).all()
		return jsonify([
			{
				"event_type": r.event_type,
				"count": r.count,
				"last_seen": r.last_seen.isoformat() if r.last_seen else None,
			}
			for r in rows
		])


__all__ = [
	"EventSubscriptionView",
	"EventDeliveryLogView",
	"EventBusView",
	"EventReportView",
]
