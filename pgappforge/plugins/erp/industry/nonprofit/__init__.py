"""
pgappforge/plugins/erp/industry/nonprofit/__init__.py

NonprofitPlugin — Nonprofit Cloud ERP plugin.

Provides:
  - Donor            (lifetime giving, segmentation, relationship management)
  - Donation         (immutable after acknowledgement, tax receipts)
  - NPOProgram          (theory of change, budget, beneficiaries)
  - ImpactMeasurement (quantified outcomes, evidence links)

Business rules enforced:
  - Donations are IMMUTABLE once acknowledged_at is set
  - lifetime_giving_cents is add-only; never decremented directly
  - Tax receipts are generated via ReportForge and URL stored on Donation
  - LYBUNT = Last Year But Unfortunately Not This Year (key retention KPI)

Events emitted:
  npo.donation.received
  npo.grant.awarded
  npo.program.milestone.reached
  npo.donor.major_gift_prospect
  npo.impact.measured

Events consumed:
  finance.ar.invoice.paid  (donation payment cleared via AR)
  crm.campaign.responded   (donor responded to a campaign)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.sales",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.industry.nonprofit",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class NonprofitPlugin(BasePlugin):
	"""Nonprofit Cloud ERP plugin.

	Class-level routing metadata:
	    name       = "nonprofit"
	    domain     = "industry"
	    depends_on = ["foundation", "crm.sales", "finance.gl"]
	"""

	name = "nonprofit"
	domain = "industry"
	depends_on: list[str] = ["foundation", "crm.sales", "finance.gl"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="nonprofit",
			version="1.0.0",
			description=(
				"Nonprofit Cloud — donor relationship management, donation processing, "
				"tax receipt generation, grant pipeline tracking, program impact measurement, "
				"LYBUNT/SYBUNT retention analytics, and major gift prospect scoring."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "nonprofit", "fundraising", "donations", "impact"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_npo_donor_read",
				"can_npo_donor_write",
				"can_npo_donor_segment",
				"can_npo_donation_read",
				"can_npo_donation_write",
				"can_npo_donation_acknowledge",
				"can_npo_receipt_generate",
				"can_npo_program_read",
				"can_npo_program_write",
				"can_npo_impact_read",
				"can_npo_impact_write",
				"can_npo_grant_read",
				"can_npo_grant_write",
				"can_npo_pledge_write",
				"can_npo_reports",
				"can_npo_prospect_score",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"npo.donation.received",
			"npo.grant.awarded",
			"npo.program.milestone.reached",
			"npo.donor.major_gift_prospect",
			"npo.impact.measured",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"finance.ar.invoice.paid",   # Donation payment cleared via AR
			"crm.campaign.responded",    # Donor responded to a solicitation campaign
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"NONPROFIT_MENU_CATEGORY": "Nonprofit Cloud",
			"NONPROFIT_SEED_RULES_ON_INIT": True,
			"NONPROFIT_MAJOR_GIFT_THRESHOLD_CENTS": 10_000_00,  # $10,000
			"NONPROFIT_MID_GIFT_THRESHOLD_CENTS": 1_000_00,     # $1,000
			"NONPROFIT_LYBUNT_GRACE_DAYS": 30,
		}
		self.config = {**defaults, **self.config}
		log.info("NonprofitPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("NONPROFIT_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Nonprofit views under the configured menu category."""
		from pgappforge.plugins.erp.industry.nonprofit.views import (
			DonationView,
			DonorProspectDashboardView,
			DonorView,
			GrantView,
			ImpactMeasurementView,
			ProgramView,
		)

		cat = self.config.get("NONPROFIT_MENU_CATEGORY", "Nonprofit Cloud")

		self.add_view(
			DonorView,
			"Donors",
			icon="fa-heart",
			category=cat,
		)
		self.add_view(
			DonationView,
			"Donations",
			icon="fa-money",
			category=cat,
		)
		self.add_view(
			ProgramView,
			"Programs",
			icon="fa-sitemap",
			category=cat,
		)
		self.add_view(
			ImpactMeasurementView,
			"Impact Measurements",
			icon="fa-bar-chart",
			category=cat,
		)
		self.add_view(
			GrantView,
			"Grants",
			icon="fa-file-text",
			category=cat,
		)
		self.add_view(
			DonorProspectDashboardView,
			"Prospect Dashboard",
			icon="fa-star",
			category=cat,
		)

		log.info("NonprofitPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.nonprofit.models import (
			Donation,
			Donor,
			ImpactMeasurement,
			NPOProgram,
		)
		return [Donor, Donation, NPOProgram, ImpactMeasurement]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure rulesets for Nonprofit domain rules.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("NonprofitPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "nonprofit.donation.immutable_after_acknowledge",
				"description": "Block mutation of acknowledged donations",
				"model_name": "Donation",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_update_acknowledged",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_acknowledged_at", "op": "is_not_null", "value": None},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Donation is acknowledged and immutable. "
									"To reverse, create a negative-amount correction donation."
								),
							}
						],
					},
				],
			},
			{
				"name": "nonprofit.donation.no_negative_without_reversal_flag",
				"description": "Warn when a negative donation is created without explicit reversal flag",
				"model_name": "Donation",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_negative_donation",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "amount_cents", "op": "lt", "value": 0},
							{"field": "payment_reference", "op": "is_null", "value": None},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "WARNING",
								"message": (
									"Donation {{id}}: negative amount_cents without payment_reference "
									"— ensure this is a documented reversal."
								),
							}
						],
					},
				],
			},
			{
				"name": "nonprofit.donor.lifetime_giving_add_only",
				"description": "Block direct decrement of lifetime_giving_cents",
				"model_name": "Donor",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_lifetime_decrement",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "_new_lifetime_giving_cents",
								"op": "lt",
								"value": "{{_old_lifetime_giving_cents}}",
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"lifetime_giving_cents is add-only. "
									"Do not decrement directly — create a reversal Donation instead."
								),
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
		log.info("NonprofitPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _try_setup_rules(self) -> None:
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			self.setup_rules(session)
			session.commit()
		except RuntimeError:
			pass
		except Exception as exc:
			log.warning("NonprofitPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> NonprofitPlugin:
	return NonprofitPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.nonprofit.models import (  # noqa: E402
	Donation,
	Donor,
	ImpactMeasurement,
	NPOProgram,
)
from pgappforge.plugins.erp.industry.nonprofit.events import (  # noqa: E402
	DonationAcknowledgedEvent,
	DonationReceivedEvent,
	DonorGivingLevelUpgradedEvent,
	ImpactMeasurementRecordedEvent,
)
from pgappforge.plugins.erp.industry.nonprofit.services import (  # noqa: E402
	NonprofitService,
	NonprofitServiceError,
	DonorNotFoundError,
	DonationNotFoundError,
	ProgramNotFoundError,
	DonationAlreadyAcknowledgedError,
)

__all__ = [
	# plugin
	"NonprofitPlugin",
	"create_plugin",
	# models
	"Donor",
	"Donation",
	"NPOProgram",
	"ImpactMeasurement",
	# events
	"DonationReceivedEvent",
	"DonationAcknowledgedEvent",
	"DonorGivingLevelUpgradedEvent",
	"ImpactMeasurementRecordedEvent",
	# services
	"NonprofitService",
	"NonprofitServiceError",
	"DonorNotFoundError",
	"DonationNotFoundError",
	"ProgramNotFoundError",
	"DonationAlreadyAcknowledgedError",
]
