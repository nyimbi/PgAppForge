"""
pgappforge/plugins/erp/analytics/cdp/__init__.py

CDPPlugin — Customer Data Platform: unified profiles, identity graph, segmentation.

Domain: analytics
Depends on: foundation

Events emitted
--------------
  analytics.cdp.profile_computed      — UnifiedProfile recomputed
  analytics.cdp.segment_computed      — segment membership refreshed
  analytics.cdp.identity_resolved     — source ID linked to canonical party
  analytics.cdp.segment_activated     — segment pushed to delivery channel
  analytics.cdp.event_stream_ingested — clickstream batch ingested

Events consumed
---------------
  party.created          — create initial UnifiedProfile stub
  ar.invoice.paid        — update lifetime_value_cents on profile
  crm.opportunity.won    — update LTV and next_best_action
  analytics.prediction.created — update propensity_scores on profile

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.analytics.cdp",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CDPPlugin(BasePlugin):
	"""Customer Data Platform ERP plugin.

	Provides unified party profiles (360° view), identity graph (deterministic
	and probabilistic matching), audience segmentation (STATIC/DYNAMIC/AI),
	and high-volume behavioural event stream ingestion.

	Pre-configures 5 Rules Engine rulesets for identity quality, segment
	health, and profile freshness controls.

	Class-level attributes:
	    name       = "analytics.cdp"
	    domain     = "analytics"
	    depends_on = ["foundation"]
	"""

	name = "analytics.cdp"
	domain = "analytics"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics.cdp",
			version="1.0.0",
			description=(
				"Customer Data Platform — unified party profiles, identity graph resolution "
				"(DETERMINISTIC/PROBABILISTIC), audience segmentation (STATIC/DYNAMIC/AI), "
				"and high-throughput behavioural event stream."
			),
			author="PgAppForge Contributors",
			tags=["erp", "analytics", "cdp", "identity", "segmentation", "profiles"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_analytics_cdp_profile_list",
				"can_analytics_cdp_profile_compute",
				"can_analytics_cdp_segment_list",
				"can_analytics_cdp_segment_write",
				"can_analytics_cdp_segment_compute",
				"can_analytics_cdp_segment_activate",
				"can_analytics_cdp_identity_resolve",
				"can_analytics_cdp_identity_write",
				"can_analytics_cdp_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"analytics.cdp.profile_computed",
			"analytics.cdp.segment_computed",
			"analytics.cdp.identity_resolved",
			"analytics.cdp.segment_activated",
			"analytics.cdp.event_stream_ingested",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"party.created",
			"ar.invoice.paid",
			"crm.opportunity.won",
			"analytics.prediction.created",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CDP_MENU_CATEGORY": "Analytics",
			"CDP_PROFILE_STALE_DAYS": 7,
			"CDP_IDENTITY_MIN_CONFIDENCE": 0.80,
			"CDP_EVENT_STREAM_BATCH_SIZE": 1000,
		}
		self.config = {**defaults, **self.config}
		log.info("CDPPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		self._subscribe_to_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.analytics.cdp.views import (
			CDPReportView,
			IdentityView,
			SegmentView,
			UnifiedProfileView,
		)
		cat = self.config.get("CDP_MENU_CATEGORY", "Analytics")
		self.add_view(UnifiedProfileView, "Unified Profiles", icon="fa-user-circle", category=cat)
		self.add_view(SegmentView, "Segments", icon="fa-users", category=cat)
		self.add_view(IdentityView, "Identity Graph", icon="fa-link", category=cat)
		self.add_view(CDPReportView, "CDP Reports", icon="fa-pie-chart", category=cat)
		log.info("CDPPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.analytics.cdp.models import (
			EventStream,
			IdentityEdge,
			Segment,
			SegmentMembership,
			UnifiedProfile,
		)
		return [UnifiedProfile, IdentityEdge, Segment, SegmentMembership, EventStream]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for CDP data quality and governance."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("CDPPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "analytics.cdp.block_low_confidence_probabilistic",
				"description": "Block probabilistic identity edges with confidence < 0.80",
				"model_name": "IdentityEdge",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_low_confidence",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "match_method", "op": "eq", "value": "PROBABILISTIC"},
							{"field": "confidence_score", "op": "lt", "value": 0.80},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Probabilistic identity edges require confidence_score >= 0.80",
							}
						],
					}
				],
			},
			{
				"name": "analytics.cdp.warn_stale_profile",
				"description": "Flag UnifiedProfile not computed in 7+ days",
				"model_name": "UnifiedProfile",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_stale",
						"trigger_event": "on_read",
						"conditions_json": [
							{"field": "_days_since_computed", "op": "gte", "value": 7},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "UnifiedProfile is stale — last computed 7+ days ago",
							}
						],
					}
				],
			},
			{
				"name": "analytics.cdp.require_definition_for_dynamic_segment",
				"description": "Block creating DYNAMIC segment without definition.sql",
				"model_name": "Segment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_sql",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "segment_type", "op": "eq", "value": "DYNAMIC"},
							{"field": "definition.sql", "op": "is_null", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "DYNAMIC segments must have definition.sql populated",
							}
						],
					}
				],
			},
			{
				"name": "analytics.cdp.require_model_for_ai_segment",
				"description": "Block creating AI segment without definition.model_name",
				"model_name": "Segment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_model_name",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "segment_type", "op": "eq", "value": "AI"},
							{"field": "definition.model_name", "op": "is_null", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "AI segments must have definition.model_name populated",
							}
						],
					}
				],
			},
			{
				"name": "analytics.cdp.high_churn_next_best_action",
				"description": "Set next_best_action to retention offer when churn_probability > 0.70",
				"model_name": "UnifiedProfile",
				"stop_on_match": False,
				"rules": [
					{
						"name": "retention_offer_on_high_churn",
						"trigger_event": "on_update",
						"conditions_json": [
							{"field": "churn_probability", "op": "gte", "value": 0.70},
							{"field": "next_best_action", "op": "is_null", "value": True},
						],
						"actions_json": [
							{
								"type": "set_field",
								"field": "next_best_action",
								"value": "RETENTION_OFFER",
							}
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
		log.info("CDPPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("party.created", self._on_party_created)
			subscribe("ar.invoice.paid", self._on_invoice_paid)
			subscribe("crm.opportunity.won", self._on_opportunity_won)
			subscribe("analytics.prediction.created", self._on_prediction_created)
			log.debug("CDPPlugin: subscribed to foundation, AR, CRM, and predictive events")
		except Exception as exc:
			log.warning("CDPPlugin._subscribe_to_events failed: %s", exc)

	def _on_party_created(self, event: Any) -> None:
		log.debug("CDPPlugin._on_party_created: party=%s", getattr(event, "party_id", "?"))

	def _on_invoice_paid(self, event: Any) -> None:
		log.debug(
			"CDPPlugin._on_invoice_paid: invoice=%s amount=%s customer=%s",
			getattr(event, "invoice_id", "?"),
			getattr(event, "total_cents", "?"),
			getattr(event, "customer_id", "?"),
		)

	def _on_opportunity_won(self, event: Any) -> None:
		log.debug("CDPPlugin._on_opportunity_won: opp=%s", getattr(event, "opportunity_id", "?"))

	def _on_prediction_created(self, event: Any) -> None:
		log.debug(
			"CDPPlugin._on_prediction_created: model=%s entity=%s/%s",
			getattr(event, "model_id", "?"),
			getattr(event, "entity_type", "?"),
			getattr(event, "entity_id", "?"),
		)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> CDPPlugin:
	return CDPPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.analytics.cdp.models import (  # noqa: E402
	EventStream,
	IdentityEdge,
	Segment,
	SegmentMembership,
	UnifiedProfile,
)
from pgappforge.plugins.erp.analytics.cdp.events import (  # noqa: E402
	EventStreamIngestedEvent,
	IdentityResolvedEvent,
	ProfileComputedEvent,
	SegmentActivatedEvent,
	SegmentComputedEvent,
)
from pgappforge.plugins.erp.analytics.cdp.services import (  # noqa: E402
	CDPError,
	CDPService,
	IdentityNotFoundError,
	PartyNotFoundError,
	SegmentationError,
	SegmentNotFoundError,
)

__all__ = [
	"CDPPlugin",
	"create_plugin",
	# models
	"UnifiedProfile",
	"IdentityEdge",
	"Segment",
	"SegmentMembership",
	"EventStream",
	# events
	"ProfileComputedEvent",
	"SegmentComputedEvent",
	"IdentityResolvedEvent",
	"SegmentActivatedEvent",
	"EventStreamIngestedEvent",
	# services
	"CDPService",
	"CDPError",
	"SegmentNotFoundError",
	"SegmentationError",
	"IdentityNotFoundError",
	"PartyNotFoundError",
]
