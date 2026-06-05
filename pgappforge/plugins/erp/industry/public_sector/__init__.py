"""
pgappforge/plugins/erp/industry/public_sector/__init__.py

PublicSectorPlugin — Public Sector ERP plugin.

Provides:
  - Constituent       (citizen/business/NGO registration, benefits enrollment)
  - GovernmentCase    (benefit eligibility, decision workflow, grant start/end)
  - PublicFundingGrant (external funding from central/federal/donor bodies)
  - ServiceRequest    (multi-channel citizen service requests)
  - CaseloadDashboard (SLA compliance, processing time analytics)
  - EligibilityCalculator (program-specific eligibility scoring)

Business rules enforced:
  - Benefit grant blocked until case status == APPROVED
  - Grant disbursement blocked when disbursed_cents + amount > total_amount_cents
  - SLA warning when case processing time exceeds 30 days

Events emitted:
  ps.constituent.registered
  ps.case.opened
  ps.case.decision.made
  ps.benefit.granted
  ps.benefit.terminated
  ps.grant.disbursed
  ps.service.request.fulfilled

Events consumed:
  grc.privacy.dsr.received  (GDPR/POPIA data subject request — anonymise constituent)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.grc.privacy",
        "pgappforge.plugins.erp.grc.controls",
        "pgappforge.plugins.erp.industry.public_sector",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PublicSectorPlugin(BasePlugin):
	"""Public Sector ERP plugin.

	Class-level routing metadata:
	    name       = "public_sector"
	    domain     = "industry"
	    depends_on = ["foundation", "finance.gl", "grc.privacy", "grc.controls"]
	"""

	name = "public_sector"
	domain = "industry"
	depends_on: list[str] = ["foundation", "finance.gl", "grc.privacy", "grc.controls"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="public_sector",
			version="1.0.0",
			description=(
				"Public Sector Cloud — constituent management, benefit case processing, "
				"eligibility determination, public funding grants, multi-channel service "
				"requests, caseload analytics, and GDPR/POPIA compliance."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "public_sector", "government", "benefits", "grants", "citizen"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ps_constituent_read",
				"can_ps_constituent_write",
				"can_ps_constituent_anonymize",
				"can_ps_case_read",
				"can_ps_case_write",
				"can_ps_case_decision",
				"can_ps_case_disburse",
				"can_ps_grant_read",
				"can_ps_grant_write",
				"can_ps_grant_disburse",
				"can_ps_grant_report",
				"can_ps_service_request_read",
				"can_ps_service_request_write",
				"can_ps_service_request_assign",
				"can_ps_service_request_resolve",
				"can_ps_service_request_escalate",
				"can_ps_eligibility_calculate",
				"can_ps_caseload_dashboard",
				"can_ps_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"ps.constituent.registered",
			"ps.case.opened",
			"ps.case.decision.made",
			"ps.benefit.granted",
			"ps.benefit.terminated",
			"ps.grant.disbursed",
			"ps.service.request.fulfilled",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"grc.privacy.dsr.received",  # GDPR/POPIA DSR — anonymise constituent PII
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"PUBLIC_SECTOR_MENU_CATEGORY": "Public Sector",
			"PUBLIC_SECTOR_SEED_RULES_ON_INIT": True,
			"PUBLIC_SECTOR_SLA_DAYS": 30,
			"PUBLIC_SECTOR_ELIGIBILITY_SCORE_THRESHOLD": "0.6",
		}
		self.config = {**defaults, **self.config}
		log.info("PublicSectorPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed pre-built rules after tables exist."""
		if self.config.get("PUBLIC_SECTOR_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Public Sector views under the configured menu category."""
		from pgappforge.plugins.erp.industry.public_sector.views import (
			CaseloadDashboardView,
			ConstituentView,
			EligibilityCalculatorView,
			GovernmentCaseView,
			PublicFundingGrantView,
			ServiceRequestView,
		)

		cat = self.config.get("PUBLIC_SECTOR_MENU_CATEGORY", "Public Sector")

		self.add_view(
			ConstituentView,
			"Constituents",
			icon="fa-users",
			category=cat,
		)
		self.add_view(
			GovernmentCaseView,
			"Government Cases",
			icon="fa-folder-open",
			category=cat,
		)
		self.add_view(
			PublicFundingGrantView,
			"Funding Grants",
			icon="fa-money",
			category=cat,
		)
		self.add_view(
			ServiceRequestView,
			"Service Requests",
			icon="fa-ticket",
			category=cat,
		)
		self.add_view(
			CaseloadDashboardView,
			"Caseload Dashboard",
			icon="fa-dashboard",
			category=cat,
		)
		self.add_view(
			EligibilityCalculatorView,
			"Eligibility Calculator",
			icon="fa-calculator",
			category=cat,
		)

		log.info("PublicSectorPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.public_sector.models import (
			Constituent,
			GovernmentCase,
			PublicFundingGrant,
		)
		from pgappforge.plugins.erp.industry.public_sector.service_request_model import (
			ServiceRequest,
		)
		return [Constituent, GovernmentCase, PublicFundingGrant, ServiceRequest]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure rulesets for Public Sector domain rules.

		Pre-built rules:
		  1. Block benefit grant if case status != APPROVED
		  2. Block grant disbursement if disbursed_cents + amount > total_amount_cents
		  3. Warn when case processing time exceeds SLA (30 days)

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("PublicSectorPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "public_sector.case.benefit_grant_requires_approval",
				"description": "Block benefit grant if case status is not APPROVED",
				"model_name": "GovernmentCase",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_benefit_grant_unapproved_case",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_action", "op": "eq", "value": "grant_benefit"},
							{"field": "status", "op": "ne", "value": "APPROVED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot grant benefit: case {{case_number}} is in status "
									"{{status}}. Case must be APPROVED before benefits can be granted."
								),
							}
						],
					},
				],
			},
			{
				"name": "public_sector.grant.disburse_within_total",
				"description": "Block disbursement when disbursed_cents + amount would exceed total_amount_cents",
				"model_name": "PublicFundingGrant",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_over_disbursement",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_action", "op": "eq", "value": "disburse"},
							{
								"field": "_disbursement_would_exceed_total",
								"op": "eq",
								"value": True,
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Disbursement of {{_tranche_amount_cents}} cents would exceed "
									"the total grant amount of {{amount_cents}} cents for grant "
									"{{grant_number}}. Already disbursed: {{disbursed_cents}} cents."
								),
							}
						],
					},
				],
			},
			{
				"name": "public_sector.case.sla_breach_warning",
				"description": "Warn when a case has been open for more than 30 days without decision",
				"model_name": "GovernmentCase",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_sla_breach",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "status",
								"op": "in",
								"value": ["OPEN", "UNDER_REVIEW"],
							},
							{
								"field": "_processing_days",
								"op": "gt",
								"value": 30,
							},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "WARNING",
								"message": (
									"SLA BREACH: Case {{case_number}} (program={{program_type}}) "
									"has been open for {{_processing_days}} days — exceeds 30-day SLA. "
									"Case worker: {{case_worker_id}}."
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
		log.info("PublicSectorPlugin.setup_rules: %d rulesets configured", len(RULESETS))

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
			log.warning("PublicSectorPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PublicSectorPlugin:
	return PublicSectorPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.public_sector.models import (  # noqa: E402
	Constituent,
	GovernmentCase,
	PublicFundingGrant,
)
from pgappforge.plugins.erp.industry.public_sector.events import (  # noqa: E402
	ConstituentRegisteredEvent,
	GovernmentCaseApprovedEvent,
	GovernmentCaseSuspendedEvent,
	GrantDisbursementEvent,
)
from pgappforge.plugins.erp.industry.public_sector.services import (  # noqa: E402
	PublicSectorService,
	PublicSectorServiceError,
	ConstituentNotFoundError,
	CaseNotFoundError,
	GrantNotFoundError,
	ServiceRequestNotFoundError,
	CaseNotApprovedError,
	GrantOverDisbursementError,
)

__all__ = [
	# plugin
	"PublicSectorPlugin",
	"create_plugin",
	# models
	"Constituent",
	"GovernmentCase",
	"PublicFundingGrant",
	# events
	"ConstituentRegisteredEvent",
	"GovernmentCaseApprovedEvent",
	"GovernmentCaseSuspendedEvent",
	"GrantDisbursementEvent",
	# services
	"PublicSectorService",
	"PublicSectorServiceError",
	"ConstituentNotFoundError",
	"CaseNotFoundError",
	"GrantNotFoundError",
	"ServiceRequestNotFoundError",
	"CaseNotApprovedError",
	"GrantOverDisbursementError",
]
