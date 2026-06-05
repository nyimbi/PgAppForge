"""
pgappforge/plugins/erp/industry/real_estate/__init__.py

RealEstatePlugin — MLS property listings, transactions, valuations, agents.

Depends on: foundation

Events emitted
--------------
  realestate.property.listed    — new property listed
  realestate.property.sold      — property sold
  realestate.transaction.closed — transaction reached CLOSED
  realestate.lease.signed       — lease agreement activated

Events consumed
---------------
  (none — standalone industry plugin)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.real_estate",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class RealEstatePlugin(BasePlugin):
	"""Real Estate industry plugin.

	Registers MLS property, transaction, agent, valuation, and lease views.
	Provides RealEstateService with AVM, CMA, market-stats, and transaction
	lifecycle methods.

	Class-level attributes:
	    name       = "real_estate"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "real_estate"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="real_estate",
			version="1.0.0",
			description=(
				"Real Estate industry plugin — MLS listings, transactions, valuations, "
				"agents, leases, and inspections. RESO Data Dictionary 2.0 aligned."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "real-estate", "mls", "reso", "property"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_re_property_list",
				"can_re_property_write",
				"can_re_property_avm",
				"can_re_transaction_list",
				"can_re_transaction_write",
				"can_re_transaction_close",
				"can_re_agent_list",
				"can_re_valuation_list",
				"can_re_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"realestate.property.listed",
			"realestate.property.sold",
			"realestate.transaction.closed",
			"realestate.lease.signed",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"RE_MENU_CATEGORY": "Real Estate",
			"RE_DEFAULT_CURRENCY": "USD",
			"RE_AVM_RADIUS_KM": 1.0,
			"RE_CMA_LOOKBACK_DAYS": 180,
		}
		self.config = {**defaults, **self.config}
		log.info("RealEstatePlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		pass

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.real_estate.views import (
			PropertyView,
			TransactionView,
			AgentView,
			ValuationView,
			MarketDashboard,
		)

		cat = self.config.get("RE_MENU_CATEGORY", "Real Estate")

		self.add_view(PropertyView, "Properties", icon="fa-home", category=cat)
		self.add_view(TransactionView, "Transactions", icon="fa-handshake-o", category=cat)
		self.add_view(AgentView, "Agents", icon="fa-id-badge", category=cat)
		self.add_view(ValuationView, "Valuations", icon="fa-calculator", category=cat)
		self.add_view(MarketDashboard, "Market Dashboard", icon="fa-bar-chart", category=cat)

		log.info("RealEstatePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.real_estate.models import (
			Property,
			PropertyValuation,
			RealEstateAgent,
			Transaction,
			LeaseAgreement,
			PropertyInspection,
		)
		return [
			Property,
			PropertyValuation,
			RealEstateAgent,
			Transaction,
			LeaseAgreement,
			PropertyInspection,
		]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for real estate business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("RealEstatePlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Property price must be positive
			{
				"name": "re.property.positive_price",
				"description": "list_price_cents must be > 0 on any active listing",
				"model_name": "Property",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_zero_or_negative_price",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "list_price_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error", "message": "list_price_cents must be > 0"}
						],
					},
				],
			},
			# 2. Transaction close requires CONTRACT status
			{
				"name": "re.transaction.close_requires_contract",
				"description": "Only CONTRACT transactions can transition to CLOSED",
				"model_name": "Transaction",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_close_without_contract",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "CLOSED"},
							{"field": "status", "op": "neq", "value": "CONTRACT"},
						],
						"actions_json": [
							{"type": "raise_error", "message": "Transaction must be in CONTRACT status before closing"}
						],
					},
				],
			},
			# 3. Sold price must be recorded on CLOSED transaction
			{
				"name": "re.transaction.sold_price_required",
				"description": "sale_price_cents must be > 0 when closing a transaction",
				"model_name": "Transaction",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_close_without_price",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "CLOSED"},
							{"field": "sale_price_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error", "message": "sale_price_cents must be > 0 to close a transaction"}
						],
					},
				],
			},
			# 4. Lease end must be after lease start
			{
				"name": "re.lease.end_after_start",
				"description": "lease_end must be after lease_start for FIXED leases",
				"model_name": "LeaseAgreement",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_lease_dates",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "lease_type", "op": "eq", "value": "FIXED"},
							{"field": "_lease_end_before_start", "op": "eq", "value": True},
						],
						"actions_json": [
							{"type": "raise_error", "message": "lease_end must be after lease_start"}
						],
					},
				],
			},
			# 5. AVM confidence threshold warning
			{
				"name": "re.valuation.low_confidence_warning",
				"description": "Warn when AVM confidence_score < 0.3 (fewer than 3 comps)",
				"model_name": "PropertyValuation",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_low_avm_confidence",
						"trigger_event": "on_after_create",
						"conditions_json": [
							{"field": "valuation_type", "op": "eq", "value": "AVM"},
							{"field": "confidence_score", "op": "lt", "value": 0.3},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "AVM confidence_score < 0.3 — fewer than 3 comparable sales found; consider manual appraisal",
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
		log.info("RealEstatePlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RealEstatePlugin:
	"""Construct and return a RealEstatePlugin bound to *appbuilder*."""
	return RealEstatePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.real_estate.models import (  # noqa: E402
	Property,
	PropertyValuation,
	RealEstateAgent,
	Transaction,
	LeaseAgreement,
	PropertyInspection,
)
from pgappforge.plugins.erp.industry.real_estate.events import (  # noqa: E402
	PropertyListedEvent,
	PropertySoldEvent,
	TransactionClosedEvent,
	LeaseSignedEvent,
)
from pgappforge.plugins.erp.industry.real_estate.services import (  # noqa: E402
	RealEstateService,
	RealEstateServiceError,
	PropertyNotFoundError,
	TransactionNotFoundError,
	RealEstateValidationError,
)

__all__ = [
	# plugin
	"RealEstatePlugin",
	"create_plugin",
	# models
	"Property",
	"PropertyValuation",
	"RealEstateAgent",
	"Transaction",
	"LeaseAgreement",
	"PropertyInspection",
	# events
	"PropertyListedEvent",
	"PropertySoldEvent",
	"TransactionClosedEvent",
	"LeaseSignedEvent",
	# services
	"RealEstateService",
	"RealEstateServiceError",
	"PropertyNotFoundError",
	"TransactionNotFoundError",
	"RealEstateValidationError",
]
