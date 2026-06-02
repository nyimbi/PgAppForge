"""
pgappforge/plugins/erp/crm/commerce/__init__.py

CommercePlugin — Commerce ERP plugin.

Depends on: foundation, ar (for subscription invoice generation)

Events emitted
--------------
  commerce.subscription.activated
  commerce.subscription.renewed
  commerce.subscription.cancelled
  commerce.subscription.past_due

Events consumed
---------------
  ar.invoice.paid           — mark subscription renewal successful
  marketing.lead.responded  — convert responding leads to trial subscriptions
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CommercePlugin(BasePlugin):
	"""Commerce plugin — shipping, tax, subscription plans, and subscriptions."""

	name = "commerce"
	domain = "crm"
	depends_on: list[str] = ["foundation", "ar"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="commerce",
			version="1.0.0",
			description=(
				"Commerce — subscription lifecycle, shipping method configuration, "
				"jurisdiction tax rules, and subscription revenue reporting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "crm", "commerce", "subscription", "billing", "shipping", "tax"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_com_shipping_write",
				"can_com_tax_write",
				"can_com_plan_write",
				"can_com_subscription_list",
				"can_com_subscription_write",
				"can_com_subscription_cancel",
				"can_com_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"commerce.subscription.activated",
			"commerce.subscription.renewed",
			"commerce.subscription.cancelled",
			"commerce.subscription.past_due",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"ar.invoice.paid",            # confirm renewal payment
			"marketing.lead.responded",   # trial conversion hook
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"COM_MENU_CATEGORY": "Commerce",
			"COM_DEFAULT_CURRENCY": "USD",
			"COM_TRIAL_GRACE_DAYS": 3,
		}
		self.config = {**defaults, **self.config}
		log.info("CommercePlugin initialised")

	def post_initialize(self) -> None:
		self._subscribe_to_upstream_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.crm.commerce.views import (
			CommerceReportView,
			ShippingMethodView,
			SubscriptionPlanView,
			SubscriptionView,
			TaxRuleView,
		)
		cat = self.config.get("COM_MENU_CATEGORY", "Commerce")
		self.add_view(ShippingMethodView, "Shipping Methods", icon="fa-truck", category=cat)
		self.add_view(TaxRuleView, "Tax Rules", icon="fa-percent", category=cat)
		self.add_view(SubscriptionPlanView, "Plans", icon="fa-tags", category=cat)
		self.add_view(SubscriptionView, "Subscriptions", icon="fa-refresh", category=cat)
		self.add_view(CommerceReportView, "Commerce Reports", icon="fa-chart-bar", category=cat)
		log.info("CommercePlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.commerce.models import (
			ShippingMethod,
			Subscription,
			SubscriptionPlan,
			TaxRule,
		)
		return [ShippingMethod, TaxRule, SubscriptionPlan, Subscription]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 Rules Engine rulesets for Commerce business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("CommercePlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Block modifying amount_cents on active subscriptions
			{
				"name": "com.subscription.amount_immutable",
				"description": "Subscription amount is immutable once ACTIVE — cancel and recreate",
				"model_name": "Subscription",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_amount_change_active",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "ACTIVE"},
							{"field": "_new_amount_cents", "op": "neq", "value": "{{_old_amount_cents}}"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Subscription amount cannot be changed while ACTIVE. Cancel and create a new subscription.",
							}
						],
					},
				],
			},
			# 2. Block renewing cancelled subscriptions
			{
				"name": "com.subscription.no_renew_cancelled",
				"description": "Cancelled subscriptions cannot be renewed",
				"model_name": "Subscription",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_renew_cancelled",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "CANCELLED"},
							{"field": "_new_next_billing_date", "op": "is_not_null", "value": None},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot renew a CANCELLED subscription",
							}
						],
					},
				],
			},
			# 3. Tax rate range validation
			{
				"name": "com.tax_rule.rate_range",
				"description": "Tax rate must be between 0 and 1 (0% to 100%)",
				"model_name": "TaxRule",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_tax_rate",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "tax_rate", "op": "gt", "value": 1},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "tax_rate must be a decimal between 0 and 1 (e.g. 0.20 for 20%)",
							}
						],
					},
				],
			},
			# 4. Shipping cost non-negative
			{
				"name": "com.shipping.cost_non_negative",
				"description": "Shipping cost_cents must be >= 0",
				"model_name": "ShippingMethod",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_shipping_cost",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "cost_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Shipping cost_cents must be >= 0",
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
		log.info("CommercePlugin.setup_rules: %d rulesets configured", len(RULESETS))

	def _subscribe_to_upstream_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("ar.invoice.paid", self._on_invoice_paid)
			log.debug("CommercePlugin: subscribed to ar.invoice.paid")
		except Exception as exc:
			log.warning("CommercePlugin._subscribe_to_upstream_events failed: %s", exc)

	def _on_invoice_paid(self, event: Any) -> None:
		log.debug(
			"CommercePlugin._on_invoice_paid: invoice=%s amount=%s (renewal confirmation hook)",
			event.aggregate_id,
			getattr(event, "amount_cents", "?"),
		)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> CommercePlugin:
	return CommercePlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.crm.commerce.models import (  # noqa: E402
	ShippingMethod,
	Subscription,
	SubscriptionPlan,
	TaxRule,
)
from pgappforge.plugins.erp.crm.commerce.events import (  # noqa: E402
	SubscriptionActivatedEvent,
	SubscriptionCancelledEvent,
	SubscriptionPastDueEvent,
	SubscriptionRenewedEvent,
)
from pgappforge.plugins.erp.crm.commerce.services import (  # noqa: E402
	CommerceService,
	CommerceError,
	SubscriptionNotFoundError,
	CommerceValidationError,
)

__all__ = [
	"CommercePlugin",
	"create_plugin",
	"ShippingMethod",
	"TaxRule",
	"SubscriptionPlan",
	"Subscription",
	"SubscriptionActivatedEvent",
	"SubscriptionRenewedEvent",
	"SubscriptionCancelledEvent",
	"SubscriptionPastDueEvent",
	"CommerceService",
	"CommerceError",
	"SubscriptionNotFoundError",
	"CommerceValidationError",
]
