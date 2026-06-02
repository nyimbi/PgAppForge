"""
pgappforge/plugins/erp/crm/cpq/__init__.py

CPQPlugin — Configure-Price-Quote ERP plugin.

Depends on: foundation, sales (for Opportunity/SalesAccount FK references)

Events emitted
--------------
  crm.quote.created             — new quote created (DRAFT)
  crm.quote.sent                — quote sent to customer
  crm.quote.accepted            — customer accepted quote
  crm.quote.rejected            — customer rejected quote
  crm.quote.expired             — quote passed valid_until date
  crm.quote.approval_requested  — submitted for internal approval
  crm.quote.approved            — approver approved
  crm.quote.approval_rejected   — approver rejected

Events consumed
---------------
  crm.opportunity.won  — no-op stub (sales drives this; CPQ reacts to quote.accepted)
  ar.invoice.paid      — no-op stub (close the feedback loop on revenue)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.sales",
        "pgappforge.plugins.erp.crm.cpq",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CPQPlugin(BasePlugin):
	"""Configure-Price-Quote ERP plugin.

	Registers CPQ CRUD views, report views, and the quote lifecycle service.
	Pre-configures 5 Rules Engine rulesets for quote, pricing, and approval controls.

	Class-level attributes for dependency resolution:
	    name       = "cpq"
	    domain     = "crm"
	    depends_on = ["foundation", "sales"]
	"""

	name = "cpq"
	domain = "crm"
	depends_on: list[str] = ["foundation", "sales"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="cpq",
			version="1.0.0",
			description=(
				"Configure-Price-Quote — full CPQ lifecycle: product catalogs, pricing rules, "
				"configurable products, bundles, quotes, quote lines, and approval workflows."
			),
			author="PgAppForge Contributors",
			tags=["erp", "crm", "cpq", "quoting", "pricing", "approval"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_cpq_catalog_list",
				"can_cpq_catalog_write",
				"can_cpq_pricing_rule_list",
				"can_cpq_pricing_rule_write",
				"can_cpq_bundle_list",
				"can_cpq_bundle_write",
				"can_cpq_quote_list",
				"can_cpq_quote_write",
				"can_cpq_quote_send",
				"can_cpq_quote_accept",
				"can_cpq_quote_approve",
				"can_cpq_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"crm.quote.created",
			"crm.quote.sent",
			"crm.quote.accepted",
			"crm.quote.rejected",
			"crm.quote.expired",
			"crm.quote.approval_requested",
			"crm.quote.approved",
			"crm.quote.approval_rejected",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes from upstream plugins."""
		return [
			"crm.opportunity.won",   # could auto-close related quotes
			"ar.invoice.paid",       # close revenue feedback loop
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CPQ_MENU_CATEGORY": "Sales / CPQ",
			"CPQ_DEFAULT_CURRENCY": "USD",
			"CPQ_QUOTE_VALIDITY_DAYS": 30,
			"CPQ_APPROVAL_DISCOUNT_THRESHOLD_PCT": 20,
			"CPQ_AUTO_EXPIRE_QUOTES": True,
		}
		self.config = {**defaults, **self.config}
		log.info("CPQPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Wire event subscriptions after init."""
		self._subscribe_to_events()

	def register_views(self) -> None:
		"""Register all CPQ views under the configured menu category."""
		from pgappforge.plugins.erp.crm.cpq.views import (
			ProductCatalogView,
			PricingRuleView,
			ProductBundleView,
			QuoteView,
			CPQReportView,
		)

		cat = self.config.get("CPQ_MENU_CATEGORY", "Sales / CPQ")

		self.add_view(ProductCatalogView, "Price Catalogs", icon="fa-book", category=cat)
		self.add_view(PricingRuleView, "Pricing Rules", icon="fa-tags", category=cat)
		self.add_view(ProductBundleView, "Product Bundles", icon="fa-cubes", category=cat)
		self.add_view(QuoteView, "Quotes", icon="fa-file-text-o", category=cat)
		self.add_view(CPQReportView, "CPQ Reports", icon="fa-chart-pie", category=cat)

		log.info("CPQPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate."""
		from pgappforge.plugins.erp.crm.cpq.models import (
			ProductCatalog,
			PricingRule,
			ConfigurableProduct,
			ProductBundle,
			BundleLine,
			Quote,
			QuoteLine,
		)
		return [
			ProductCatalog,
			PricingRule,
			ConfigurableProduct,
			ProductBundle,
			BundleLine,
			Quote,
			QuoteLine,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for CPQ business controls.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("CPQPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Approval required for high-discount quotes
			{
				"name": "cpq.quote.approval_required_high_discount",
				"description": "Quotes with >20% discount require approval before sending",
				"model_name": "Quote",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_approval_for_high_discount",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "SENT"},
							{"field": "_discount_pct", "op": "gt", "value": 20},
							{"field": "approval_status", "op": "neq", "value": "APPROVED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Quotes with >20% discount require approval before sending",
							}
						],
					},
				],
			},
			# 2. Quote immutability after SENT
			{
				"name": "cpq.quote.immutable_after_sent",
				"description": "Quote amounts cannot change once SENT",
				"model_name": "Quote",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_amount_change_after_sent",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "not_in", "value": ["DRAFT"]},
							{"field": "_new_total_cents", "op": "neq", "value": "{{_old_total_cents}}"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Quote amounts are immutable after SENT; create a new revision",
							}
						],
					},
				],
			},
			# 3. Negative price guard
			{
				"name": "cpq.quote_line.no_negative_price",
				"description": "Quote line net_price_cents must be non-negative",
				"model_name": "QuoteLine",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_negative_net_price",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "net_price_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "net_price_cents cannot be negative",
							}
						],
					},
				],
			},
			# 4. Catalog date overlap warning
			{
				"name": "cpq.catalog.date_overlap_check",
				"description": "Warn when a new catalog overlaps with an existing active catalog",
				"model_name": "ProductCatalog",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_catalog_date_overlap",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "is_active", "op": "eq", "value": True},
							{"field": "_overlapping_catalog_count", "op": "gt", "value": 0},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "New catalog date range overlaps with an existing active catalog",
							}
						],
					},
				],
			},
			# 5. Expired quote cannot be accepted
			{
				"name": "cpq.quote.no_accept_expired",
				"description": "EXPIRED quotes cannot transition to ACCEPTED",
				"model_name": "Quote",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_accept_expired",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "EXPIRED"},
							{"field": "_new_status", "op": "eq", "value": "ACCEPTED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot accept an EXPIRED quote; create a new quote",
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
		log.info("CPQPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Event subscriptions
	# ------------------------------------------------------------------

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("crm.opportunity.won", self._on_opportunity_won)
			log.debug("CPQPlugin: subscribed to crm.opportunity.won")
		except Exception as exc:
			log.warning("CPQPlugin._subscribe_to_events failed: %s", exc)

	def _on_opportunity_won(self, event: Any) -> None:
		"""When an opportunity is won, auto-accept any SENT quotes linked to it."""
		log.debug(
			"CPQPlugin._on_opportunity_won: opp=%s — quote auto-accept not implemented "
			"(requires session context; use CPQService.accept_quote in a task)",
			getattr(event, "opportunity_id", "?"),
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> CPQPlugin:
	"""Construct and return a CPQPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return CPQPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.cpq.models import (  # noqa: E402
	BundleLine,
	ConfigurableProduct,
	PricingRule,
	ProductBundle,
	ProductCatalog,
	Quote,
	QuoteLine,
)
from pgappforge.plugins.erp.crm.cpq.events import (  # noqa: E402
	QuoteAcceptedEvent,
	QuoteApprovalRejectedEvent,
	QuoteApprovalRequestedEvent,
	QuoteApprovedEvent,
	QuoteCreatedEvent,
	QuoteExpiredEvent,
	QuoteRejectedEvent,
	QuoteSentEvent,
)
from pgappforge.plugins.erp.crm.cpq.services import (  # noqa: E402
	ApprovalRequiredError,
	CPQService,
	CPQServiceError,
	CPQValidationError,
	CatalogNotFoundError,
	ProductNotFoundError,
	QuoteNotFoundError,
)

__all__ = [
	# plugin
	"CPQPlugin",
	"create_plugin",
	# models
	"ProductCatalog",
	"PricingRule",
	"ConfigurableProduct",
	"ProductBundle",
	"BundleLine",
	"Quote",
	"QuoteLine",
	# events
	"QuoteCreatedEvent",
	"QuoteSentEvent",
	"QuoteAcceptedEvent",
	"QuoteRejectedEvent",
	"QuoteExpiredEvent",
	"QuoteApprovalRequestedEvent",
	"QuoteApprovedEvent",
	"QuoteApprovalRejectedEvent",
	# services
	"CPQService",
	"CPQServiceError",
	"QuoteNotFoundError",
	"ProductNotFoundError",
	"CatalogNotFoundError",
	"CPQValidationError",
	"ApprovalRequiredError",
]
