"""
pgappforge/plugins/erp/platform/events/__init__.py

Platform Events plugin — durable event subscription registry + EventBus service.

Events emitted:
  event.subscription.created
  event.subscription.deactivated
  event.delivery.failed
  event.delivery.dead_lettered
  event.replayed

Events consumed:
  (any — the bus is a cross-cutting concern, not domain-specific)

Usage
-----
Add to PGAPPFORGE_PLUGINS::

    "pgappforge.plugins.erp.platform.events"

Or instantiate directly::

    from pgappforge.plugins.erp.platform.events import PlatformEventsPlugin
    plugin = PlatformEventsPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PlatformEventsPlugin(BasePlugin):
	"""Platform Events plugin.

	Extends the in-process foundation event bus with a durable subscription
	registry (EventSubscription) and delivery audit log (EventDeliveryLog).
	"""

	name = "platform.events"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="platform.events",
			version="1.0.0",
			description=(
				"Platform event bus — durable subscription registry, "
				"delivery logging, and event replay for ERP plugins."
			),
			author="PgAppForge Contributors",
			tags=["platform", "events", "eventbus", "pubsub"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_platform_events_subscriptions_read",
				"can_platform_events_subscriptions_write",
				"can_platform_events_delivery_read",
				"can_platform_events_replay",
				"can_platform_events_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"event.subscription.created",
			"event.subscription.deactivated",
			"event.delivery.failed",
			"event.delivery.dead_lettered",
			"event.replayed",
		]

	def subscribe_to(self) -> list[str]:
		# Cross-cutting — subscribes to everything via the bus, not listed here
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PLATFORM_EVENTS_MENU_CATEGORY": "Platform",
			"PLATFORM_EVENTS_DEFAULT_RETRY": 3,
			"PLATFORM_EVENTS_DEFAULT_DEAD_LETTER": 5,
		}
		self.config = {**defaults, **self.config}
		log.info("PlatformEventsPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.events.views import (
			EventSubscriptionView,
			EventDeliveryLogView,
			EventBusView,
			EventReportView,
		)
		cat = self.config.get("PLATFORM_EVENTS_MENU_CATEGORY", "Platform")
		self.add_view(
			EventSubscriptionView, "Event Subscriptions",
			icon="fa-rss", category=cat,
		)
		self.add_view(
			EventBusView, "Event Bus",
			icon="fa-exchange", category=cat,
		)
		self.add_view(
			EventReportView, "Event Reports",
			icon="fa-bar-chart", category=cat,
		)
		self.add_view_no_menu(EventDeliveryLogView)
		log.info("PlatformEventsPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.events.models import (
			EventSubscription,
			EventDeliveryLog,
		)
		return [EventSubscription, EventDeliveryLog]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 3 rulesets for event bus operations."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("PlatformEventsPlugin.setup_rules: rules plugin not available")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "event_subscription.no_self_loop",
				"description": "A plugin cannot subscribe to its own events",
				"model_name": "EventSubscription",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_self_subscription",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "subscriber_plugin", "op": "eq",
							 "value": "{{event_type_prefix}}"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Plugin cannot subscribe to its own events"}
						],
					}
				],
			},
			{
				"name": "event_subscription.retry_limits",
				"description": "Retry count must not exceed dead_letter_after",
				"model_name": "EventSubscription",
				"stop_on_match": True,
				"rules": [
					{
						"name": "retry_not_exceed_dead_letter",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "retry_count", "op": "gt",
							 "value": "{{dead_letter_after}}"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "retry_count cannot exceed dead_letter_after"}
						],
					}
				],
			},
			{
				"name": "event_delivery.immutable",
				"description": "EventDeliveryLog rows must never be updated",
				"model_name": "EventDeliveryLog",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_delivery_log_update",
						"trigger_event": "on_before_update",
						"conditions_json": [{"field": "id", "op": "exists", "value": True}],
						"actions_json": [
							{"type": "raise_error",
							 "message": "EventDeliveryLog rows are immutable; never update"}
						],
					}
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("PlatformEventsPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> PlatformEventsPlugin:
	return PlatformEventsPlugin(appbuilder, config=config or {})


# Re-exports
from pgappforge.plugins.erp.platform.events.models import EventSubscription, EventDeliveryLog  # noqa: E402
from pgappforge.plugins.erp.platform.events.events import (  # noqa: E402
	EventBus,
	get_event_bus,
	EventSubscriptionCreatedEvent,
	EventSubscriptionDeactivatedEvent,
	EventDeliveryFailedEvent,
	EventDeliveryDeadLetteredEvent,
	EventReplayedEvent,
)
from pgappforge.plugins.erp.platform.events.services import EventBusService  # noqa: E402

__all__ = [
	"PlatformEventsPlugin",
	"create_plugin",
	"EventSubscription",
	"EventDeliveryLog",
	"EventBus",
	"get_event_bus",
	"EventBusService",
	"EventSubscriptionCreatedEvent",
	"EventSubscriptionDeactivatedEvent",
	"EventDeliveryFailedEvent",
	"EventDeliveryDeadLetteredEvent",
	"EventReplayedEvent",
]
