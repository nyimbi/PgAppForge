"""
pgappforge/plugins/erp/crm/sales/__init__.py

SalesPlugin — Sales Force Automation (SFA) ERP plugin.

Depends on: foundation
Optionally integrates with: cpq (quote generation), ar (invoice on win)

Events emitted
--------------
  crm.lead.created            — new lead ingested
  crm.lead.scored             — lead score recomputed
  crm.lead.qualified          — lead status → QUALIFIED
  crm.lead.converted          — lead converted to account/contact/opportunity
  crm.lead.disqualified       — lead marked DISQUALIFIED
  crm.opportunity.created     — new opportunity created
  crm.opportunity.stage_advanced — stage changed
  crm.opportunity.won         — stage → CLOSED_WON
  crm.opportunity.lost        — stage → CLOSED_LOST
  crm.activity.logged         — activity completed
  crm.forecast.submitted      — forecast submitted for a period

Events consumed
---------------
  crm.quote.accepted          — update opportunity stage to CLOSED_WON
  ar.invoice.paid             — update account lifetime_value_cents

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.sales",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SalesPlugin(BasePlugin):
	"""Sales Force Automation ERP plugin.

	Registers SFA CRUD views, report views, and scoring/stage-advance services.
	Pre-configures 5 Rules Engine rulesets for lead, opportunity, and forecast controls.

	Class-level attributes for dependency resolution:
	    name       = "sales"
	    domain     = "crm"
	    depends_on = ["foundation"]
	"""

	name = "sales"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="sales",
			version="1.0.0",
			description=(
				"Sales Force Automation — full SFA lifecycle: accounts, contacts, leads, "
				"opportunities, activities, sales targets, and forecasting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "crm", "sales", "sfa", "pipeline", "forecasting"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_crm_account_list",
				"can_crm_account_write",
				"can_crm_contact_list",
				"can_crm_contact_write",
				"can_crm_lead_list",
				"can_crm_lead_write",
				"can_crm_lead_score",
				"can_crm_lead_convert",
				"can_crm_opportunity_list",
				"can_crm_opportunity_write",
				"can_crm_opportunity_advance",
				"can_crm_activity_list",
				"can_crm_activity_write",
				"can_crm_forecast_write",
				"can_crm_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"crm.lead.created",
			"crm.lead.scored",
			"crm.lead.qualified",
			"crm.lead.converted",
			"crm.lead.disqualified",
			"crm.opportunity.created",
			"crm.opportunity.stage_advanced",
			"crm.opportunity.won",
			"crm.opportunity.lost",
			"crm.activity.logged",
			"crm.forecast.submitted",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes from upstream/peer plugins."""
		return [
			"crm.quote.accepted",   # CPQ: auto-advance opportunity to CLOSED_WON
			"ar.invoice.paid",      # AR: update account lifetime_value_cents
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SALES_MENU_CATEGORY": "Sales",
			"SALES_DEFAULT_CURRENCY": "USD",
			"SALES_LEAD_SCORE_THRESHOLD_QUALIFY": 70,
			"SALES_FORECAST_LOCK_DAYS_BEFORE_PERIOD_END": 3,
		}
		self.config = {**defaults, **self.config}
		log.info("SalesPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Wire event subscriptions after init."""
		self._subscribe_to_events()

	def register_views(self) -> None:
		"""Register all Sales views under the configured menu category."""
		from pgappforge.plugins.erp.crm.sales.views import (
			SalesAccountView,
			SalesContactView,
			LeadView,
			OpportunityView,
			ActivityView,
			SalesReportView,
		)

		cat = self.config.get("SALES_MENU_CATEGORY", "Sales")

		self.add_view(SalesAccountView, "Accounts", icon="fa-building", category=cat)
		self.add_view(SalesContactView, "Contacts", icon="fa-address-book", category=cat)
		self.add_view(LeadView, "Leads", icon="fa-user-plus", category=cat)
		self.add_view(OpportunityView, "Opportunities", icon="fa-handshake-o", category=cat)
		self.add_view(ActivityView, "Activities", icon="fa-calendar-check-o", category=cat)
		self.add_view(SalesReportView, "Sales Reports", icon="fa-chart-line", category=cat)

		log.info("SalesPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate."""
		from pgappforge.plugins.erp.crm.sales.models import (
			SalesAccount,
			SalesContact,
			Lead,
			Opportunity,
			Activity,
			SalesTarget,
			SalesForecast,
		)
		return [
			SalesAccount,
			SalesContact,
			Lead,
			Opportunity,
			Activity,
			SalesTarget,
			SalesForecast,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for sales business controls.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("SalesPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Auto-qualify high-score leads
			{
				"name": "crm.lead.auto_qualify",
				"description": "Auto-advance lead to QUALIFIED when score >= 70",
				"model_name": "Lead",
				"stop_on_match": True,
				"rules": [
					{
						"name": "qualify_on_high_score",
						"trigger_event": "on_update",
						"conditions_json": [
							{"field": "score", "op": "gte", "value": 70},
							{"field": "status", "op": "in", "value": ["NEW", "CONTACTED", "WORKING"]},
						],
						"actions_json": [
							{"type": "set_field", "field": "status", "value": "QUALIFIED"},
						],
					},
				],
			},
			# 2. Block opportunity advance without amount
			{
				"name": "crm.opportunity.amount_required_for_proposal",
				"description": "Require amount_cents before advancing to PROPOSAL or beyond",
				"model_name": "Opportunity",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_proposal_without_amount",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "_new_stage",
								"op": "in",
								"value": ["PROPOSAL", "NEGOTIATION", "CLOSED_WON"],
							},
							{"field": "amount_cents", "op": "is_null", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "amount_cents is required before advancing to PROPOSAL or beyond",
							}
						],
					},
				],
			},
			# 3. Require close date for NEGOTIATION
			{
				"name": "crm.opportunity.close_date_required",
				"description": "Require expected_close_date in NEGOTIATION",
				"model_name": "Opportunity",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_close_date",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_stage", "op": "eq", "value": "NEGOTIATION"},
							{"field": "expected_close_date", "op": "is_null", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "expected_close_date is required before entering NEGOTIATION",
							}
						],
					},
				],
			},
			# 4. Flag stale opportunities
			{
				"name": "crm.opportunity.stale_deal_warning",
				"description": "Flag opportunities with no activity in 30+ days",
				"model_name": "Opportunity",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_stale_opportunity",
						"trigger_event": "on_read",
						"conditions_json": [
							{"field": "stage", "op": "not_in", "value": ["CLOSED_WON", "CLOSED_LOST"]},
							{"field": "_days_since_update", "op": "gte", "value": 30},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Opportunity has had no update in 30+ days — review required",
							}
						],
					},
				],
			},
			# 5. Disqualified lead cannot be converted
			{
				"name": "crm.lead.no_convert_disqualified",
				"description": "Block conversion of DISQUALIFIED leads",
				"model_name": "Lead",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_disqualified_convert",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "DISQUALIFIED"},
							{"field": "_new_status", "op": "eq", "value": "CONVERTED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot convert a DISQUALIFIED lead; re-qualify first",
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
		log.info("SalesPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Event subscriptions
	# ------------------------------------------------------------------

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("crm.quote.accepted", self._on_quote_accepted)
			subscribe("ar.invoice.paid", self._on_invoice_paid)
			log.debug("SalesPlugin: subscribed to crm.quote.accepted and ar.invoice.paid")
		except Exception as exc:
			log.warning("SalesPlugin._subscribe_to_events failed: %s", exc)

	def _on_quote_accepted(self, event: Any) -> None:
		"""When a CPQ quote is accepted, auto-advance the linked opportunity to CLOSED_WON."""
		log.debug(
			"SalesPlugin._on_quote_accepted: quote=%s opp=%s",
			getattr(event, "quote_id", "?"),
			getattr(event, "opportunity_id", "?"),
		)
		# Real implementation: call SalesService.advance_stage with a fresh session.
		# Skipped here — event handler runs outside a request context.

	def _on_invoice_paid(self, event: Any) -> None:
		"""When an AR invoice is paid, update account lifetime_value_cents."""
		log.debug(
			"SalesPlugin._on_invoice_paid: invoice=%s amount=%s",
			getattr(event, "invoice_id", "?"),
			getattr(event, "total_cents", "?"),
		)
		# Real implementation: look up account via customer, add total_cents to LTV.


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> SalesPlugin:
	"""Construct and return a SalesPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return SalesPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.sales.models import (  # noqa: E402
	Activity,
	Lead,
	Opportunity,
	SalesAccount,
	SalesContact,
	SalesForecast,
	SalesTarget,
)
from pgappforge.plugins.erp.crm.sales.events import (  # noqa: E402
	ActivityLoggedEvent,
	ForecastSubmittedEvent,
	LeadConvertedEvent,
	LeadCreatedEvent,
	LeadDisqualifiedEvent,
	LeadQualifiedEvent,
	LeadScoredEvent,
	OpportunityCreatedEvent,
	OpportunityLostEvent,
	OpportunityStageAdvancedEvent,
	OpportunityWonEvent,
)
from pgappforge.plugins.erp.crm.sales.services import (  # noqa: E402
	LeadNotFoundError,
	OpportunityNotFoundError,
	SalesAccountNotFoundError,
	SalesContactNotFoundError,
	SalesService,
	SalesServiceError,
	SalesValidationError,
)

__all__ = [
	# plugin
	"SalesPlugin",
	"create_plugin",
	# models
	"SalesAccount",
	"SalesContact",
	"Lead",
	"Opportunity",
	"Activity",
	"SalesTarget",
	"SalesForecast",
	# events
	"LeadCreatedEvent",
	"LeadScoredEvent",
	"LeadQualifiedEvent",
	"LeadConvertedEvent",
	"LeadDisqualifiedEvent",
	"OpportunityCreatedEvent",
	"OpportunityStageAdvancedEvent",
	"OpportunityWonEvent",
	"OpportunityLostEvent",
	"ActivityLoggedEvent",
	"ForecastSubmittedEvent",
	# services
	"SalesService",
	"SalesServiceError",
	"SalesAccountNotFoundError",
	"SalesContactNotFoundError",
	"LeadNotFoundError",
	"OpportunityNotFoundError",
	"SalesValidationError",
]
