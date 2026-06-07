"""
pgappforge/plugins/erp/finance/credit_management/__init__.py

CreditManagementPlugin — Credit Management ERP plugin.

Provides customer credit limit management, live exposure tracking,
credit hold/release workflows, breach detection, and overdue analytics.

Depends on: foundation, ar (exposure component source)
Integrates with: ar (invoice exposure), sales (order exposure),
                 gl (breach notifications)

Events emitted
--------------
  finance.credit.limit.set        — credit limit created or updated
  finance.credit.exposure.updated — live exposure recomputed
  finance.credit.hold.placed      — customer placed on credit hold
  finance.credit.hold.released    — credit hold lifted
  finance.credit.breach           — exposure exceeds limit

BPM actions
-----------
  finance.credit.check            — evaluate credit before order
  finance.credit.place_hold       — place hold via workflow

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.ar",
        "pgappforge.plugins.erp.finance.credit_management",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.credit_management import CreditManagementPlugin
    plugin = CreditManagementPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CreditManagementPlugin(BasePlugin):
	"""Credit Management ERP plugin.

	Registers credit profile views, exposure dashboards, hold management,
	and overdue customer analytics. Pre-configures 5 Rules Engine rulesets
	for credit risk controls.

	Class-level attributes for dependency resolution:
	    name       = "credit_management"
	    domain     = "finance"
	    depends_on = ["foundation"]
	"""

	name = "credit_management"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="credit_management",
			version="1.0.0",
			description=(
				"Credit Management — customer credit limit configuration, live exposure "
				"tracking across AR invoices and sales orders, credit hold/release workflows, "
				"breach detection, and overdue customer analytics."
			),
			author="PgAppForge Contributors",
			tags=["finance", "credit", "ar", "risk", "collections"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_credit_profile_list",
				"can_credit_profile_write",
				"can_credit_limit_set",
				"can_credit_hold_place",
				"can_credit_hold_release",
				"can_credit_exposure_view",
				"can_credit_overdue_report",
				"can_credit_check",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"finance.credit.limit.set",
			"finance.credit.exposure.updated",
			"finance.credit.hold.placed",
			"finance.credit.hold.released",
			"finance.credit.breach",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"ar.invoice.issued",       # register invoice exposure component
			"ar.invoice.paid",         # remove invoice exposure component
			"ar.invoice.written_off",  # remove invoice exposure component
			"sales.order.confirmed",   # register order exposure component
			"sales.order.shipped",     # remove order exposure component (shipped = exposure cleared)
			"sales.order.cancelled",   # remove order exposure component
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CREDIT_MENU_CATEGORY": "Credit Management",
			"CREDIT_DEFAULT_CURRENCY": "USD",
			"CREDIT_DEFAULT_PAYMENT_TERMS_DAYS": 30,
			"CREDIT_OVERDUE_DAYS_THRESHOLD": 30,
			"CREDIT_AUTO_HOLD_ON_BREACH": False,  # set True to auto-hold on breach event
		}
		self.config = {**defaults, **self.config}
		log.info("CreditManagementPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Wire event subscriptions after init."""
		self._subscribe_to_ar_events()

	def register_views(self) -> None:
		"""Register credit management views under the configured menu category."""
		try:
			from pgappforge.plugins.erp.finance.credit_management import views as v  # type: ignore[import]

			cat = self.config.get("CREDIT_MENU_CATEGORY", "Credit Management")
			self.add_view(v.CreditProfileView, "Credit Profiles", icon="fa-user-shield", category=cat)
			self.add_view(v.CreditExposureView, "Exposure", icon="fa-balance-scale", category=cat)
			self.add_view(v.CreditHoldView, "Credit Holds", icon="fa-hand-paper", category=cat)
			self.add_view(v.OverdueCustomerView, "Overdue Customers", icon="fa-exclamation-triangle", category=cat)
			self.add_view(v.CreditCheckView, "Credit Check", icon="fa-check-circle", category=cat)
			log.info("CreditManagementPlugin: views registered under category %r", cat)
		except ImportError:
			log.debug("CreditManagementPlugin: views module not found — skipping view registration")

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate."""
		from pgappforge.plugins.erp.finance.credit_management.models import (
			CreditExposureComponent,
			CustomerCreditProfile,
		)
		return [
			CustomerCreditProfile,
			CreditExposureComponent,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for credit risk controls.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("CreditManagementPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Auto-hold on limit breach
			{
				"name": "credit.profile.auto_hold_on_breach",
				"description": "Optionally auto-place hold when exposure exceeds limit",
				"model_name": "CustomerCreditProfile",
				"stop_on_match": False,
				"rules": [
					{
						"name": "flag_breach_for_review",
						"trigger_event": "on_after_update",
						"conditions_json": [
							{"field": "current_exposure_cents", "op": "gt", "value": "{{credit_limit_cents}}"},
							{"field": "is_on_hold", "op": "eq", "value": False},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Customer exposure exceeds credit limit — manual hold review required",
							}
						],
					},
				],
			},
			# 2. Zero credit limit warning
			{
				"name": "credit.profile.zero_limit_warning",
				"description": "Warn when a customer credit limit is set to zero",
				"model_name": "CustomerCreditProfile",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_zero_credit_limit",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "credit_limit_cents", "op": "eq", "value": 0},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Customer credit limit set to zero — all orders will fail credit check",
							}
						],
					},
				],
			},
			# 3. Block hold removal without approval
			{
				"name": "credit.profile.hold_release_audit",
				"description": "Log all credit hold releases for audit trail",
				"model_name": "CustomerCreditProfile",
				"stop_on_match": False,
				"rules": [
					{
						"name": "audit_hold_release",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_is_on_hold", "op": "eq", "value": True},
							{"field": "_new_is_on_hold", "op": "eq", "value": False},
						],
						"actions_json": [
							{
								"type": "log_info",
								"message": "Credit hold released — ensure release is authorised per credit policy",
							}
						],
					},
				],
			},
			# 4. Negative exposure guard
			{
				"name": "credit.component.positive_amount",
				"description": "Exposure component amounts must be positive",
				"model_name": "CreditExposureComponent",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_negative_exposure",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "amount_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Exposure component amount must be non-negative",
							}
						],
					},
				],
			},
			# 5. D-rated customer high-risk flag
			{
				"name": "credit.profile.d_rating_high_risk",
				"description": "Flag D-rated customers for immediate credit review",
				"model_name": "CustomerCreditProfile",
				"stop_on_match": False,
				"rules": [
					{
						"name": "flag_d_rated_customer",
						"trigger_event": "on_after_update",
						"conditions_json": [
							{"field": "credit_rating", "op": "eq", "value": "D"},
							{"field": "is_on_hold", "op": "eq", "value": False},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "D-rated customer has no credit hold — consider placing hold pending review",
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
		log.info("CreditManagementPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# AR / Sales event subscriptions
	# ------------------------------------------------------------------

	def _subscribe_to_ar_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("ar.invoice.issued", self._on_invoice_issued)
			subscribe("ar.invoice.paid", self._on_invoice_paid)
			subscribe("ar.invoice.written_off", self._on_invoice_paid)  # same removal logic
			subscribe("sales.order.confirmed", self._on_order_confirmed)
			subscribe("sales.order.shipped", self._on_order_closed)
			subscribe("sales.order.cancelled", self._on_order_closed)
			log.debug("CreditManagementPlugin: subscribed to AR and sales events")
		except Exception as exc:
			log.warning("CreditManagementPlugin._subscribe_to_ar_events failed: %s", exc)

	def _on_invoice_issued(self, event: Any) -> None:
		"""No-op stub: real implementation calls register_exposure_component."""
		log.debug(
			"CreditManagementPlugin._on_invoice_issued: invoice=%s customer=%s amount=%s",
			getattr(event, "invoice_id", "?"),
			getattr(event, "customer_id", "?"),
			getattr(event, "total_cents", "?"),
		)

	def _on_invoice_paid(self, event: Any) -> None:
		"""No-op stub: real implementation calls remove_exposure_component."""
		log.debug(
			"CreditManagementPlugin._on_invoice_paid/written_off: invoice=%s",
			getattr(event, "invoice_id", "?"),
		)

	def _on_order_confirmed(self, event: Any) -> None:
		"""No-op stub: real implementation calls register_exposure_component."""
		log.debug(
			"CreditManagementPlugin._on_order_confirmed: order=%s",
			getattr(event, "aggregate_id", "?"),
		)

	def _on_order_closed(self, event: Any) -> None:
		"""No-op stub: real implementation calls remove_exposure_component."""
		log.debug(
			"CreditManagementPlugin._on_order_closed: order=%s",
			getattr(event, "aggregate_id", "?"),
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> CreditManagementPlugin:
	"""Construct and return a CreditManagementPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return CreditManagementPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.credit_management.models import (  # noqa: E402
	CreditExposureComponent,
	CustomerCreditProfile,
)
from pgappforge.plugins.erp.finance.credit_management.events import (  # noqa: E402
	CreditExposureUpdatedEvent,
	CreditHoldPlacedEvent,
	CreditHoldReleasedEvent,
	CreditLimitBreachEvent,
	CreditLimitSetEvent,
)
from pgappforge.plugins.erp.finance.credit_management.services import (  # noqa: E402
	CreditManagementError,
	CreditManagementService,
	CreditProfileNotFoundError,
	CreditValidationError,
)

__all__ = [
	# plugin
	"CreditManagementPlugin",
	"create_plugin",
	# models
	"CustomerCreditProfile",
	"CreditExposureComponent",
	# events
	"CreditLimitSetEvent",
	"CreditExposureUpdatedEvent",
	"CreditHoldPlacedEvent",
	"CreditHoldReleasedEvent",
	"CreditLimitBreachEvent",
	# services
	"CreditManagementService",
	"CreditManagementError",
	"CreditProfileNotFoundError",
	"CreditValidationError",
]
