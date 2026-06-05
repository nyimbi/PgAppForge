"""
pgappforge/plugins/erp/industry/insurance/__init__.py

InsurancePlugin — policies, claims, underwriting, reinsurance.

Depends on: foundation

Events emitted
--------------
  insurance.policy.issued   — new policy issued (DRAFT → ACTIVE)
  insurance.policy.lapsed   — policy lapsed due to non-payment
  insurance.claim.filed     — new claim filed
  insurance.claim.approved  — claim approved for payment
  insurance.claim.paid      — claim payment disbursed

Events consumed
---------------
  (none — standalone industry plugin)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.insurance",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class InsurancePlugin(BasePlugin):
	"""Insurance industry plugin (ACORD-aligned).

	Registers product catalog, policy, premium, claim, and reinsurance views.
	Provides InsuranceService with underwriting, premium calculation, and full
	claim lifecycle methods.

	Class-level attributes:
	    name       = "insurance"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "insurance"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="insurance",
			version="1.0.0",
			description=(
				"Insurance industry plugin — products, policies, premiums, claims, "
				"underwriting, and reinsurance. ACORD standard aligned."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "insurance", "acord", "claims", "underwriting"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ins_product_list",
				"can_ins_product_write",
				"can_ins_policy_list",
				"can_ins_policy_write",
				"can_ins_policy_underwrite",
				"can_ins_claim_list",
				"can_ins_claim_write",
				"can_ins_claim_assess",
				"can_ins_claim_approve",
				"can_ins_claim_pay",
				"can_ins_underwriting_dashboard",
				"can_ins_claims_analytics",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"insurance.policy.issued",
			"insurance.policy.lapsed",
			"insurance.claim.filed",
			"insurance.claim.approved",
			"insurance.claim.paid",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"INS_MENU_CATEGORY": "Insurance",
			"INS_DEFAULT_CURRENCY": "USD",
			"INS_PREMIUM_GRACE_DAYS": 15,
			"INS_QUOTE_VALIDITY_DAYS": 30,
			"INS_AUTO_LAPSE_ENABLED": True,
		}
		self.config = {**defaults, **self.config}
		log.info("InsurancePlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		pass

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.insurance.views import (
			PolicyView,
			ClaimView,
			UnderwritingDashboardView,
			ClaimsAnalyticsDashboardView,
		)

		cat = self.config.get("INS_MENU_CATEGORY", "Insurance")

		self.add_view(PolicyView, "Policies", icon="fa-file-text-o", category=cat)
		self.add_view(ClaimView, "Claims", icon="fa-exclamation-triangle", category=cat)
		self.add_view(UnderwritingDashboardView, "Underwriting", icon="fa-shield", category=cat)
		self.add_view(ClaimsAnalyticsDashboardView, "Claims Analytics", icon="fa-bar-chart", category=cat)

		log.info("InsurancePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.insurance.models import (
			InsuranceProduct,
			PolicyHolder,
			Policy,
			Premium,
			Claim,
			Reinsurance,
		)
		return [
			InsuranceProduct,
			PolicyHolder,
			Policy,
			Premium,
			Claim,
			Reinsurance,
		]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for insurance business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("InsurancePlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Coverage amount bounds check
			{
				"name": "ins.policy.coverage_within_product_bounds",
				"description": "coverage_amount_cents must be within product min/max",
				"model_name": "Policy",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_coverage_below_minimum",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_coverage_below_min", "op": "eq", "value": True},
						],
						"actions_json": [
							{"type": "raise_error", "message": "coverage_amount_cents is below product minimum"}
						],
					},
				],
			},
			# 2. Claim cannot exceed policy coverage
			{
				"name": "ins.claim.cannot_exceed_coverage",
				"description": "claimed_amount_cents must not exceed policy coverage_amount_cents",
				"model_name": "Claim",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_claim_exceeds_coverage",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_claimed_exceeds_coverage", "op": "eq", "value": True},
						],
						"actions_json": [
							{"type": "raise_error", "message": "claimed_amount_cents exceeds policy coverage_amount_cents"}
						],
					},
				],
			},
			# 3. LAPSED policy cannot receive new claims
			{
				"name": "ins.claim.no_claim_on_lapsed_policy",
				"description": "Claims cannot be filed against LAPSED or CANCELLED policies",
				"model_name": "Claim",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_claim_on_inactive_policy",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "_policy_status", "op": "in", "value": ["LAPSED", "CANCELLED", "EXPIRED"]},
						],
						"actions_json": [
							{"type": "raise_error", "message": "Cannot file a claim against a LAPSED, CANCELLED, or EXPIRED policy"}
						],
					},
				],
			},
			# 4. Approved amount cannot exceed assessed amount
			{
				"name": "ins.claim.approved_lte_assessed",
				"description": "approved_amount_cents must be <= assessed_amount_cents",
				"model_name": "Claim",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_approve_exceeds_assessed",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "APPROVED"},
							{"field": "_approved_gt_assessed", "op": "eq", "value": True},
						],
						"actions_json": [
							{"type": "raise_error", "message": "approved_amount_cents cannot exceed assessed_amount_cents"}
						],
					},
				],
			},
			# 5. Premium overdue auto-escalation warning
			{
				"name": "ins.premium.overdue_warning",
				"description": "Warn when a DUE premium passes grace period without payment",
				"model_name": "Premium",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_overdue_premium",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "OVERDUE"},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Premium is now OVERDUE — policy may lapse if not paid within grace period",
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
		log.info("InsurancePlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> InsurancePlugin:
	"""Construct and return an InsurancePlugin bound to *appbuilder*."""
	return InsurancePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.insurance.models import (  # noqa: E402
	InsuranceProduct,
	PolicyHolder,
	Policy,
	Premium,
	Claim,
	Reinsurance,
)
from pgappforge.plugins.erp.industry.insurance.events import (  # noqa: E402
	PolicyIssuedEvent,
	PolicyLapsedEvent,
	ClaimFiledEvent,
	ClaimApprovedEvent,
	ClaimPaidEvent,
)
from pgappforge.plugins.erp.industry.insurance.services import (  # noqa: E402
	InsuranceService,
	InsuranceServiceError,
	ProductNotFoundError,
	PolicyNotFoundError,
	ClaimNotFoundError,
	InsuranceValidationError,
)

__all__ = [
	# plugin
	"InsurancePlugin",
	"create_plugin",
	# models
	"InsuranceProduct",
	"PolicyHolder",
	"Policy",
	"Premium",
	"Claim",
	"Reinsurance",
	# events
	"PolicyIssuedEvent",
	"PolicyLapsedEvent",
	"ClaimFiledEvent",
	"ClaimApprovedEvent",
	"ClaimPaidEvent",
	# services
	"InsuranceService",
	"InsuranceServiceError",
	"ProductNotFoundError",
	"PolicyNotFoundError",
	"ClaimNotFoundError",
	"InsuranceValidationError",
]
