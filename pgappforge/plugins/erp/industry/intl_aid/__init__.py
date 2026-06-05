"""
pgappforge/plugins/erp/industry/intl_aid/__init__.py

IntlAidPlugin — International Aid ERP plugin (IATI 2.03-compliant).

Provides:
  - AidOrganization    (IATI publishing organisation: donor, implementer, NGO)
  - AidProject         (IATI activity with budget/commitment/disbursement aggregates)
  - ProjectTransaction (IMMUTABLE financial transaction ledger: COMMITMENT/DISBURSEMENT/EXPENDITURE/REPAYMENT)
  - ResultIndicator    (IATI result framework: OUTPUT/OUTCOME/IMPACT indicators)
  - BeneficiaryCount   (M&E periodic beneficiary disaggregation)

Business rules enforced:
  - ProjectTransactions are IMMUTABLE — no update or delete permitted
  - total_committed_cents and total_disbursed_cents are add-only
  - usd_value_cents computed at recording time from exchange_rate
  - AidOrganization.total_disbursements_cents updated on every DISBURSEMENT
  - AidOrganization.active_projects incremented on project creation

IATI alignment:
  - generate_iati_xml() produces spec-compliant IATI Activity Standard 2.03 XML
  - org_type maps to IATI OrganisationType codelist codes
  - transaction_type maps to IATI TransactionType codelist codes
  - status maps to IATI ActivityStatus codelist codes

Events emitted:
  aid.project.created
  aid.transaction.disbursement
  aid.transaction.commitment
  aid.results.updated
  aid.project.status.changed
  aid.beneficiaries.counted

Events consumed:
  finance.fx.rate.updated   (exchange rate update — may trigger usd recalculation)
  grc.privacy.dsr.received  (anonymise beneficiary data on DSR)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.grc.privacy",
        "pgappforge.plugins.erp.industry.intl_aid",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class IntlAidPlugin(BasePlugin):
	"""International Aid ERP plugin (IATI 2.03-compliant).

	Class-level routing metadata:
	    name       = "intl_aid"
	    domain     = "industry"
	    depends_on = ["foundation", "finance.gl", "grc.privacy"]
	"""

	name = "intl_aid"
	domain = "industry"
	depends_on: list[str] = ["foundation", "finance.gl", "grc.privacy"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="intl_aid",
			version="1.0.0",
			description=(
				"International Aid Cloud — IATI 2.03-compliant project management, "
				"multi-currency financial transaction ledger (COMMITMENT/DISBURSEMENT/"
				"EXPENDITURE/REPAYMENT), result framework indicator tracking, "
				"beneficiary disaggregation, aid effectiveness analytics, "
				"geographic portfolio heatmap, and IATI Activity Standard XML export."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "intl_aid", "iati", "ngo", "development", "humanitarian"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_aid_org_read",
				"can_aid_org_write",
				"can_aid_project_read",
				"can_aid_project_write",
				"can_aid_project_create",
				"can_aid_transaction_read",
				"can_aid_transaction_record",
				"can_aid_disbursement_record",
				"can_aid_results_read",
				"can_aid_results_write",
				"can_aid_results_update",
				"can_aid_beneficiaries_read",
				"can_aid_beneficiaries_record",
				"can_aid_iati_export",
				"can_aid_effectiveness_view",
				"can_aid_dashboard_view",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"aid.project.created",
			"aid.transaction.disbursement",
			"aid.transaction.commitment",
			"aid.results.updated",
			"aid.project.status.changed",
			"aid.beneficiaries.counted",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"finance.fx.rate.updated",   # Exchange rate update — may trigger USD recalculation
			"grc.privacy.dsr.received",  # Anonymise beneficiary data on data subject request
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"INTL_AID_MENU_CATEGORY": "International Aid",
			"INTL_AID_SEED_RULES_ON_INIT": True,
			"INTL_AID_DEFAULT_CURRENCY": "USD",
			"INTL_AID_IATI_REGISTRY_URL": "https://iatiregistry.org/",
			"INTL_AID_HIGH_DISBURSEMENT_THRESHOLD_CENTS": 1_000_000_00,  # $1M
		}
		self.config = {**defaults, **self.config}
		log.info("IntlAidPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("INTL_AID_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register International Aid views under the configured menu category."""
		from pgappforge.plugins.erp.industry.intl_aid.views import (
			AidDashboard,
			AidOrganizationView,
			BeneficiaryCountView,
			ProjectView,
			ResultsView,
			TransactionView,
		)

		cat = self.config.get("INTL_AID_MENU_CATEGORY", "International Aid")

		self.add_view(AidOrganizationView, "Organisations", icon="fa-globe", category=cat)
		self.add_view(ProjectView, "Projects", icon="fa-map-marker", category=cat)
		self.add_view(TransactionView, "Transactions", icon="fa-exchange", category=cat)
		self.add_view(ResultsView, "Results & Indicators", icon="fa-bar-chart", category=cat)
		self.add_view(BeneficiaryCountView, "Beneficiaries", icon="fa-users", category=cat)
		self.add_view(AidDashboard, "Portfolio Dashboard", icon="fa-dashboard", category=cat)

		log.info("IntlAidPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.intl_aid.models import (
			AidOrganization,
			AidProject,
			BeneficiaryCount,
			ProjectTransaction,
			ResultIndicator,
		)
		return [AidOrganization, AidProject, ProjectTransaction, ResultIndicator, BeneficiaryCount]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure rulesets for International Aid domain rules.

		Pre-built rules:
		  1. Block ProjectTransaction update (immutability guard)
		  2. Block total_disbursed_cents decrement (add-only invariant)
		  3. Warn on high single disbursement (> $1M USD equivalent)
		  4. Block project creation with total_budget_cents = 0

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("IntlAidPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "intl_aid.transaction.immutable",
				"description": "Block any update to ProjectTransaction (immutable ledger)",
				"model_name": "ProjectTransaction",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_transaction_update",
						"trigger_event": "on_before_update",
						"conditions_json": [],  # always fires on update
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"ProjectTransaction {{id}} is an immutable IATI financial record. "
									"Create a REPAYMENT transaction to reverse a disbursement."
								),
							}
						],
					},
				],
			},
			{
				"name": "intl_aid.project.disbursed_add_only",
				"description": "Block direct decrement of total_disbursed_cents",
				"model_name": "AidProject",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_disbursed_decrement",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "_new_total_disbursed_cents",
								"op": "lt",
								"value": "{{_old_total_disbursed_cents}}",
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"total_disbursed_cents is add-only on AidProject {{iati_identifier}}. "
									"Record a REPAYMENT ProjectTransaction to reduce effective disbursement."
								),
							}
						],
					},
				],
			},
			{
				"name": "intl_aid.transaction.large_disbursement_warning",
				"description": "Warn on single disbursement exceeding $1M USD",
				"model_name": "ProjectTransaction",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_large_disbursement",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "transaction_type", "op": "eq", "value": "DISBURSEMENT"},
							{"field": "usd_value_cents", "op": "gt", "value": 1_000_000_00},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "WARNING",
								"message": (
									"LARGE DISBURSEMENT: ProjectTransaction for project {{project_id}} "
									"has usd_value_cents={{usd_value_cents}} (>$1M). "
									"Ensure dual-authorisation is confirmed."
								),
							}
						],
					},
				],
			},
			{
				"name": "intl_aid.project.non_zero_budget",
				"description": "Block project creation with zero total_budget_cents",
				"model_name": "AidProject",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_zero_budget_project",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "total_budget_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"AidProject {{iati_identifier}} cannot be created with "
									"total_budget_cents=0. Provide a positive budget."
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
		log.info("IntlAidPlugin.setup_rules: %d rulesets configured", len(RULESETS))

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
			log.warning("IntlAidPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> IntlAidPlugin:
	return IntlAidPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.intl_aid.models import (  # noqa: E402
	AidOrganization,
	AidProject,
	BeneficiaryCount,
	ProjectTransaction,
	ResultIndicator,
)
from pgappforge.plugins.erp.industry.intl_aid.events import (  # noqa: E402
	AidProjectCreatedEvent,
	BeneficiariesCountedEvent,
	CommitmentRecordedEvent,
	DisbursementRecordedEvent,
	ProjectStatusChangedEvent,
	ResultsUpdatedEvent,
)
from pgappforge.plugins.erp.industry.intl_aid.services import (  # noqa: E402
	IndicatorNotFoundError,
	IntlAidService,
	IntlAidServiceError,
	InvalidTransactionError,
	OrganizationNotFoundError,
	ProjectNotFoundError,
)

__all__ = [
	# plugin
	"IntlAidPlugin",
	"create_plugin",
	# models
	"AidOrganization",
	"AidProject",
	"ProjectTransaction",
	"ResultIndicator",
	"BeneficiaryCount",
	# events
	"AidProjectCreatedEvent",
	"DisbursementRecordedEvent",
	"CommitmentRecordedEvent",
	"ResultsUpdatedEvent",
	"ProjectStatusChangedEvent",
	"BeneficiariesCountedEvent",
	# services
	"IntlAidService",
	"IntlAidServiceError",
	"ProjectNotFoundError",
	"OrganizationNotFoundError",
	"IndicatorNotFoundError",
	"InvalidTransactionError",
]
