"""
pgappforge/plugins/erp/crm/subscriptions/__init__.py

SubscriptionsPlugin — Subscription Lifecycle Management for SaaS/recurring billing.

Domain:    crm
Depends:   foundation

Events emitted
--------------
  crm.subscriptions.created
  crm.subscriptions.activated
  crm.subscriptions.renewed
  crm.subscriptions.upgraded
  crm.subscriptions.downgraded
  crm.subscriptions.cancelled
  crm.subscriptions.past_due
  crm.subscriptions.invoice.generated

Events consumed
---------------
  crm.invoice.paid  — marks a SubscriptionInvoice as PAID when received
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SubscriptionsPlugin(BasePlugin):
	"""Subscription Lifecycle Management plugin.

	Covers the full subscription lifecycle: plan management, trial activation,
	billing period renewal, plan upgrades/downgrades with proration, cancellation
	(immediate and scheduled), metered usage recording, and MRR analytics.
	"""

	name = "subscriptions"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="subscriptions",
			version="1.0.0",
			description=(
				"Subscription Lifecycle Management — plans, trials, renewals, "
				"upgrades/downgrades, metered billing, and MRR analytics."
			),
			author="PgAppForge Contributors",
			tags=["crm", "subscriptions", "billing", "mrr", "saas"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_sub_plan_read",
				"can_sub_plan_write",
				"can_sub_plan_delete",
				"can_sub_subscription_list",
				"can_sub_subscription_create",
				"can_sub_subscription_write",
				"can_sub_subscription_cancel",
				"can_sub_subscription_change_plan",
				"can_sub_invoice_read",
				"can_sub_invoice_write",
				"can_sub_invoice_void",
				"can_sub_usage_record",
				"can_sub_renewals_process",
				"can_sub_mrr_report",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.subscriptions.created",
			"crm.subscriptions.activated",
			"crm.subscriptions.renewed",
			"crm.subscriptions.upgraded",
			"crm.subscriptions.downgraded",
			"crm.subscriptions.cancelled",
			"crm.subscriptions.past_due",
			"crm.subscriptions.invoice.generated",
		]

	def subscribe_to(self) -> list[str]:
		return ["crm.invoice.paid"]

	def activate(self) -> None:
		"""Alias for initialize() — satisfies plugin protocol variants."""
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SUBSCRIPTIONS_MENU_CATEGORY": "Subscriptions",
			"SUBSCRIPTIONS_DEFAULT_CURRENCY": "KES",
		}
		self.config = {**defaults, **self.config}
		log.info("SubscriptionsPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.subscriptions.models import (
			SubscriptionPlan,
			Subscription,
			SubscriptionInvoice,
			SubscriptionUsage,
		)
		return [SubscriptionPlan, Subscription, SubscriptionInvoice, SubscriptionUsage]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.crm.subscriptions.views import (
			SubscriptionPlanView,
			SubscriptionView,
			SubscriptionInvoiceView,
			MRRDashboardView,
		)
		cat = self.config.get("SUBSCRIPTIONS_MENU_CATEGORY", "Subscriptions")
		self.add_view(MRRDashboardView, "MRR Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(SubscriptionPlanView, "Plans", icon="fa-list", category=cat)
		self.add_view(SubscriptionView, "Subscriptions", icon="fa-repeat", category=cat)
		self.add_view(SubscriptionInvoiceView, "Invoices", icon="fa-file-text-o", category=cat)
		log.info("SubscriptionsPlugin: views registered under %r", cat)

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for subscription business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("SubscriptionsPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Invoice amount must be positive (credits use a separate credit note flow)
			{
				"name": "subscriptions.invoice.positive_amount",
				"description": "SubscriptionInvoice amount_cents must be non-negative; use credit notes for refunds",
				"model_name": "SubscriptionInvoice",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_negative_invoice",
						"trigger_event": "on_before_insert",
						"conditions_json": [
							{"field": "amount_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "SubscriptionInvoice amount_cents must be >= 0; use a credit note for refunds",
							}
						],
					},
				],
			},
			# 2. Immediate cancellation requires a non-empty cancel_reason
			{
				"name": "subscriptions.cancel.at_period_end_only",
				"description": "Immediate cancellation (status=CANCELLED) requires a non-empty cancel_reason",
				"model_name": "Subscription",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_reason_for_immediate_cancel",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "CANCELLED"},
							{"field": "cancel_reason", "op": "eq", "value": ""},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Immediate cancellation requires a non-empty cancel_reason",
							}
						],
					},
				],
			},
			# 3. Plan base_price_cents must be positive
			{
				"name": "subscriptions.plan.price_positive",
				"description": "SubscriptionPlan base_price_cents must be > 0",
				"model_name": "SubscriptionPlan",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_zero_price_plan",
						"trigger_event": "on_before_insert",
						"conditions_json": [
							{"field": "base_price_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "SubscriptionPlan base_price_cents must be > 0",
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
		log.info("SubscriptionsPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> SubscriptionsPlugin:
	"""Factory function — preferred entry-point for plugin loader."""
	return SubscriptionsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.subscriptions.models import (  # noqa: E402
	SubscriptionPlan,
	Subscription,
	SubscriptionInvoice,
	SubscriptionUsage,
)
from pgappforge.plugins.erp.crm.subscriptions.events import (  # noqa: E402
	SubscriptionCreatedEvent,
	SubscriptionActivatedEvent,
	SubscriptionRenewedEvent,
	SubscriptionUpgradedEvent,
	SubscriptionDowngradedEvent,
	SubscriptionCancelledEvent,
	SubscriptionPastDueEvent,
	InvoiceGeneratedEvent,
)
from pgappforge.plugins.erp.crm.subscriptions.services import (  # noqa: E402
	SubscriptionService,
	SubscriptionServiceError,
	SubscriptionNotFoundError,
	SubscriptionStateError,
)

__all__ = [
	# Plugin
	"SubscriptionsPlugin",
	"create_plugin",
	# Models
	"SubscriptionPlan",
	"Subscription",
	"SubscriptionInvoice",
	"SubscriptionUsage",
	# Events
	"SubscriptionCreatedEvent",
	"SubscriptionActivatedEvent",
	"SubscriptionRenewedEvent",
	"SubscriptionUpgradedEvent",
	"SubscriptionDowngradedEvent",
	"SubscriptionCancelledEvent",
	"SubscriptionPastDueEvent",
	"InvoiceGeneratedEvent",
	# Services / Exceptions
	"SubscriptionService",
	"SubscriptionServiceError",
	"SubscriptionNotFoundError",
	"SubscriptionStateError",
]
