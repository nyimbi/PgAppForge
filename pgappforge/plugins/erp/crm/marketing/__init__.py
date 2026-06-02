"""
pgappforge/plugins/erp/crm/marketing/__init__.py

MarketingPlugin — Marketing ERP plugin.

Depends on: foundation (Party)

Events emitted
--------------
  marketing.campaign.activated
  marketing.campaign.completed
  marketing.lead.responded
  marketing.member.unsubscribed
  marketing.journey.step_executed

Events consumed
---------------
  party.created   — seed new leads into active campaigns
  ar.invoice.paid — attribute revenue to source campaign
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class MarketingPlugin(BasePlugin):
	"""Marketing plugin — campaigns, email templates, journeys, lists."""

	name = "marketing"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="marketing",
			version="1.0.0",
			description=(
				"Marketing — campaign lifecycle, email templates, marketing lists, "
				"journey automation, and campaign attribution."
			),
			author="PgAppForge Contributors",
			tags=["erp", "crm", "marketing", "campaign", "email", "automation"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_mkt_campaign_list",
				"can_mkt_campaign_write",
				"can_mkt_campaign_activate",
				"can_mkt_template_write",
				"can_mkt_list_write",
				"can_mkt_member_write",
				"can_mkt_journey_write",
				"can_mkt_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"marketing.campaign.activated",
			"marketing.campaign.completed",
			"marketing.lead.responded",
			"marketing.member.unsubscribed",
			"marketing.journey.step_executed",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"party.created",   # seed new leads
			"ar.invoice.paid", # revenue attribution
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"MKT_MENU_CATEGORY": "Marketing",
			"MKT_DEFAULT_SENDER_NAME": "Marketing Team",
			"MKT_UNSUBSCRIBE_HONOR_DAYS": 30,
		}
		self.config = {**defaults, **self.config}
		log.info("MarketingPlugin initialised")

	def post_initialize(self) -> None:
		self._subscribe_to_upstream_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.crm.marketing.views import (
			CampaignView,
			EmailTemplateView,
			MarketingListView,
			MarketingReportView,
		)
		cat = self.config.get("MKT_MENU_CATEGORY", "Marketing")
		self.add_view(CampaignView, "Campaigns", icon="fa-bullhorn", category=cat)
		self.add_view(EmailTemplateView, "Email Templates", icon="fa-envelope", category=cat)
		self.add_view(MarketingListView, "Lists", icon="fa-list", category=cat)
		self.add_view(MarketingReportView, "Marketing Reports", icon="fa-chart-bar", category=cat)
		log.info("MarketingPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.marketing.models import (
			Campaign,
			CampaignMember,
			EmailTemplate,
			JourneyStep,
			MarketingList,
		)
		return [Campaign, EmailTemplate, CampaignMember, MarketingList, JourneyStep]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 3 Rules Engine rulesets for Marketing business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("MarketingPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Block adding members to COMPLETED campaigns
			{
				"name": "mkt.campaign.no_members_after_complete",
				"description": "Prevent adding members to COMPLETED or ARCHIVED campaigns",
				"model_name": "CampaignMember",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_add_member_closed_campaign",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "campaign.status", "op": "in", "value": ["COMPLETED", "ARCHIVED"]},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot add members to a COMPLETED or ARCHIVED campaign",
							}
						],
					},
				],
			},
			# 2. Budget overspend alert
			{
				"name": "mkt.campaign.budget_overspend",
				"description": "Flag campaigns where actual_cost exceeds budget",
				"model_name": "Campaign",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_budget_overspend",
						"trigger_event": "on_update",
						"conditions_json": [
							{"field": "budget_cents", "op": "is_not_null", "value": None},
							{"field": "actual_cost_cents", "op": "gt", "value": "{{budget_cents}}"},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Campaign actual cost has exceeded approved budget",
							}
						],
					},
				],
			},
			# 3. Unsubscribe honour — block re-adding unsubscribed party within window
			{
				"name": "mkt.member.unsubscribe_honour",
				"description": "Warn when adding a party that previously unsubscribed from this campaign",
				"model_name": "CampaignMember",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_resubscribe",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_existing_member_status", "op": "eq", "value": "UNSUBSCRIBED"},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Party previously unsubscribed from this campaign — verify consent before re-adding",
							}
						],
					},
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
		log.info("MarketingPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	def _subscribe_to_upstream_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("party.created", self._on_party_created)
			log.debug("MarketingPlugin: subscribed to party.created")
		except Exception as exc:
			log.warning("MarketingPlugin._subscribe_to_upstream_events failed: %s", exc)

	def _on_party_created(self, event: Any) -> None:
		log.debug("MarketingPlugin._on_party_created: party=%s (no auto-enroll)", event.aggregate_id)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> MarketingPlugin:
	return MarketingPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.crm.marketing.models import (  # noqa: E402
	Campaign,
	CampaignMember,
	EmailTemplate,
	JourneyStep,
	MarketingList,
)
from pgappforge.plugins.erp.crm.marketing.events import (  # noqa: E402
	CampaignActivatedEvent,
	CampaignCompletedEvent,
	LeadRespondedEvent,
	MemberUnsubscribedEvent,
	JourneyStepExecutedEvent,
)
from pgappforge.plugins.erp.crm.marketing.services import (  # noqa: E402
	MarketingService,
	MarketingError,
	CampaignNotFoundError,
	MarketingValidationError,
)

__all__ = [
	"MarketingPlugin",
	"create_plugin",
	"Campaign",
	"CampaignMember",
	"EmailTemplate",
	"JourneyStep",
	"MarketingList",
	"CampaignActivatedEvent",
	"CampaignCompletedEvent",
	"LeadRespondedEvent",
	"MemberUnsubscribedEvent",
	"JourneyStepExecutedEvent",
	"MarketingService",
	"MarketingError",
	"CampaignNotFoundError",
	"MarketingValidationError",
]
