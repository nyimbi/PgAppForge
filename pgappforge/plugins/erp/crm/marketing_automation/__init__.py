"""
pgappforge/plugins/erp/crm/marketing_automation/__init__.py

MarketingAutomationPlugin — campaign lifecycle, drip sequences, lead scoring,
A/B testing, and revenue attribution for the CRM domain.

Events emitted
--------------
  crm.marketing.campaign.activated   — campaign transitions DRAFT → ACTIVE
  crm.marketing.email.sent           — email dispatched in a sequence step
  crm.marketing.lead.scored          — lead grade boundary crossed
  crm.marketing.ab_test.winner       — A/B test winner determined
  crm.marketing.revenue.attributed   — opportunity revenue attributed to campaign

Events consumed
---------------
  crm.opportunity.won                — trigger revenue attribution + lead conversion
  crm.lead.converted                 — mark LeadScore.converted = True

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.sales",
        "pgappforge.plugins.erp.crm.marketing_automation",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class MarketingAutomationPlugin(BasePlugin):
	"""Marketing Automation ERP plugin.

	Provides campaign management, multi-step drip sequences, A/B variant
	assignment, lead scoring with grade computation, and multi-touch revenue
	attribution.  Integrates with the Rules Engine for segment targeting and
	the BPM workflow engine for enrollment and scoring triggers.

	Class-level attributes for dependency resolution:
	    name       = "marketing_automation"
	    domain     = "crm"
	    depends_on = ["foundation"]
	"""

	name = "marketing_automation"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="marketing_automation",
			version="1.0.0",
			description=(
				"Marketing Automation — full campaign lifecycle: drip sequences, "
				"A/B testing, lead scoring, and multi-touch revenue attribution."
			),
			author="PgAppForge Contributors",
			tags=["crm", "marketing", "automation", "email", "lead-scoring"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_mkt_campaign_list",
				"can_mkt_campaign_write",
				"can_mkt_campaign_activate",
				"can_mkt_sequence_write",
				"can_mkt_contact_list",
				"can_mkt_contact_write",
				"can_mkt_lead_score_list",
				"can_mkt_lead_score_write",
				"can_mkt_attribution_list",
				"can_mkt_analytics",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.marketing.campaign.activated",
			"crm.marketing.email.sent",
			"crm.marketing.lead.scored",
			"crm.marketing.ab_test.winner",
			"crm.marketing.revenue.attributed",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"crm.opportunity.won",   # auto-attribute revenue to last-touch campaign
			"crm.lead.converted",    # mark LeadScore.converted = True
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"MARKETING_MENU_CATEGORY": "Marketing",
			"MARKETING_DEFAULT_ATTRIBUTION_MODEL": "LAST_TOUCH",
			"MARKETING_LEAD_GRADE_THRESHOLDS": {
				"A+": 90, "A": 70, "B": 50, "C": 30, "D": 0,
			},
		}
		self.config = {**defaults, **self.config}
		log.info("MarketingAutomationPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		self._subscribe_to_events()

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.crm.marketing_automation.views import (
				MarketingCampaignView,
				MarketingSequenceView,
				CampaignContactView,
				LeadScoreView,
				CampaignAttributionView,
			)
			cat = self.config.get("MARKETING_MENU_CATEGORY", "Marketing")
			self.add_view(MarketingCampaignView, "Campaigns", icon="fa-bullhorn", category=cat)
			self.add_view(MarketingSequenceView, "Sequences", icon="fa-list-ol", category=cat)
			self.add_view(CampaignContactView, "Enrolled Contacts", icon="fa-users", category=cat)
			self.add_view(LeadScoreView, "Lead Scores", icon="fa-star", category=cat)
			self.add_view(CampaignAttributionView, "Attribution", icon="fa-line-chart", category=cat)
			log.info("MarketingAutomationPlugin: views registered under category %r", cat)
		except ImportError as exc:
			log.debug("MarketingAutomationPlugin.register_views: views not available — %s", exc)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.marketing_automation.models import (
			CampaignAttribution,
			CampaignContact,
			LeadScore,
			MarketingCampaign,
			MarketingSequence,
		)
		return [
			MarketingCampaign,
			MarketingSequence,
			CampaignContact,
			LeadScore,
			CampaignAttribution,
		]

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("crm.opportunity.won", self._on_opportunity_won)
			subscribe("crm.lead.converted", self._on_lead_converted)
			log.debug(
				"MarketingAutomationPlugin: subscribed to crm.opportunity.won and crm.lead.converted"
			)
		except Exception as exc:
			log.warning("MarketingAutomationPlugin._subscribe_to_events failed: %s", exc)

	def _on_opportunity_won(self, event: Any) -> None:
		"""Auto-attribute revenue to the last-touch campaign for this contact."""
		log.debug(
			"MarketingAutomationPlugin._on_opportunity_won: opportunity=%s contact=%s amount=%s",
			getattr(event, "opportunity_id", "?"),
			getattr(event, "contact_id", "?"),
			getattr(event, "amount_cents", "?"),
		)
		# Real implementation: look up last CampaignContact for contact_id
		# ordered by enrolled_at DESC, call attribute_revenue with a fresh session.

	def _on_lead_converted(self, event: Any) -> None:
		"""Mark LeadScore.converted = True when a lead is converted."""
		log.debug(
			"MarketingAutomationPlugin._on_lead_converted: lead=%s contact=%s",
			getattr(event, "lead_id", "?"),
			getattr(event, "contact_id", "?"),
		)
		# Real implementation: upsert LeadScore.converted = True.


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> MarketingAutomationPlugin:
	"""Construct and return a MarketingAutomationPlugin bound to *appbuilder*."""
	return MarketingAutomationPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.marketing_automation.models import (  # noqa: E402
	CampaignAttribution,
	CampaignContact,
	LeadScore,
	MarketingCampaign,
	MarketingSequence,
)
from pgappforge.plugins.erp.crm.marketing_automation.events import (  # noqa: E402
	ABTestVariantWonEvent,
	CampaignActivatedEvent,
	CampaignEmailSentEvent,
	LeadScoredEvent,
	RevenueAttributedEvent,
)
from pgappforge.plugins.erp.crm.marketing_automation.services import (  # noqa: E402
	MarketingAutomationService,
	MarketingNotFoundError,
	MarketingServiceError,
	MarketingStateError,
)

__all__ = [
	# plugin
	"MarketingAutomationPlugin",
	"create_plugin",
	# models
	"MarketingCampaign",
	"MarketingSequence",
	"CampaignContact",
	"LeadScore",
	"CampaignAttribution",
	# events
	"CampaignActivatedEvent",
	"CampaignEmailSentEvent",
	"LeadScoredEvent",
	"ABTestVariantWonEvent",
	"RevenueAttributedEvent",
	# services
	"MarketingAutomationService",
	"MarketingServiceError",
	"MarketingNotFoundError",
	"MarketingStateError",
]
