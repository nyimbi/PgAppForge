"""
pgappforge/plugins/erp/industry/financial_services/__init__.py

FinancialServicesPlugin — Financial Services Cloud ERP plugin.

Provides:
  - FinancialClient  (KYC, AML score, risk profile, relationship manager)
  - PortfolioAccount (SAVINGS / CHECKING / INVESTMENT / PENSION / INSURANCE)
  - FinancialProduct (LOAN / DEPOSIT / INSURANCE / INVESTMENT / CARD)
  - ClientHolding    (immutable holding snapshots; NEVER UPDATE)
  - SanctionsScreeningResult (OFAC / EU / UN / UK / LOCAL; NEVER UPDATE)

Business rules enforced:
  - All amounts: integer cents — never float
  - Sanctions screening rows are immutable (new row per screen)
  - ClientHolding rows are immutable (new snapshot per revaluation)
  - PortfolioAccount balances mutated only via post_account_transaction()
  - KYC must be APPROVED before accounts can be opened
  - CONFIRMED_MATCH sanctions blocks KYC approval

Events emitted:
  finserv.client.onboarded
  finserv.client.kyc_status_changed
  finserv.client.risk_profile_changed
  finserv.account.opened
  finserv.account.status_changed
  finserv.account.balance_updated
  finserv.holding.revalued
  finserv.sanctions.screening_completed
  finserv.sanctions.match_cleared

Events consumed:
  party.created  (to seed FinancialClient party_id reference)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.financial_services",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class FinancialServicesPlugin(BasePlugin):
	"""Financial Services Cloud ERP plugin.

	Class-level routing metadata:
	    name       = "financial_services"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "financial_services"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="financial_services",
			version="1.0.0",
			description=(
				"Financial Services Cloud — regulated client onboarding (KYC/AML), "
				"portfolio accounts, product catalogue, investment holdings, and "
				"multi-list sanctions screening."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "financial-services", "kyc", "aml", "sanctions"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_finserv_client_read",
				"can_finserv_client_write",
				"can_finserv_client_kyc_approve",
				"can_finserv_account_read",
				"can_finserv_account_write",
				"can_finserv_account_transact",
				"can_finserv_product_read",
				"can_finserv_product_write",
				"can_finserv_holding_read",
				"can_finserv_sanctions_screen",
				"can_finserv_sanctions_clear",
				"can_finserv_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"finserv.client.onboarded",
			"finserv.client.kyc_status_changed",
			"finserv.client.risk_profile_changed",
			"finserv.account.opened",
			"finserv.account.status_changed",
			"finserv.account.balance_updated",
			"finserv.holding.revalued",
			"finserv.sanctions.screening_completed",
			"finserv.sanctions.match_cleared",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"party.created",   # Optionally auto-create FinancialClient shell on party creation
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"FINSERV_MENU_CATEGORY": "Financial Services",
			"FINSERV_DEFAULT_CURRENCY": "USD",
			"FINSERV_SEED_RULES_ON_INIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("FinancialServicesPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("FINSERV_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register FinServ views under the configured menu category."""
		from pgappforge.plugins.erp.industry.financial_services.views import (
			FinancialClientView,
			FinancialProductView,
			FinServReportView,
			PortfolioAccountView,
			SanctionsScreeningView,
		)

		cat = self.config.get("FINSERV_MENU_CATEGORY", "Financial Services")

		self.add_view(
			FinancialClientView,
			"Clients",
			icon="fa-users",
			category=cat,
		)
		self.add_view(
			PortfolioAccountView,
			"Accounts",
			icon="fa-bank",
			category=cat,
		)
		self.add_view(
			FinancialProductView,
			"Products",
			icon="fa-briefcase",
			category=cat,
		)
		self.add_view(
			SanctionsScreeningView,
			"Sanctions Screening",
			icon="fa-shield",
			category=cat,
		)
		self.add_view(
			FinServReportView,
			"FinServ Reports",
			icon="fa-file-text-o",
			category=cat,
		)

		log.info("FinancialServicesPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.financial_services.models import (
			ClientHolding,
			FinancialClient,
			FinancialProduct,
			PortfolioAccount,
			SanctionsScreeningResult,
		)
		return [
			FinancialClient,
			PortfolioAccount,
			FinancialProduct,
			ClientHolding,
			SanctionsScreeningResult,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 rulesets for FinServ domain rules.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("FinancialServicesPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "finserv.client.kyc_required_for_accounts",
				"description": "Block account opening for non-APPROVED KYC clients",
				"model_name": "PortfolioAccount",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_account_without_kyc",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "client.kyc_status", "op": "neq", "value": "APPROVED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot open account: client KYC status is not APPROVED",
							}
						],
					},
				],
			},
			{
				"name": "finserv.account.no_debit_frozen",
				"description": "Block any debit on a FROZEN account",
				"model_name": "PortfolioAccount",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_debit_frozen_account",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "FROZEN"},
							{"field": "_delta_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Debit rejected: account is FROZEN",
							}
						],
					},
				],
			},
			{
				"name": "finserv.client.sanctions_block_kyc",
				"description": "Block KYC approval if confirmed sanctions match exists",
				"model_name": "FinancialClient",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_kyc_on_sanctions_hit",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_kyc_status", "op": "eq", "value": "APPROVED"},
							{"field": "party.sanctions_confirmed", "op": "eq", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"KYC approval blocked: party has a CONFIRMED_MATCH "
									"sanctions record. Resolve via compliance review first."
								),
							}
						],
					},
				],
			},
			{
				"name": "finserv.holding.positive_quantity",
				"description": "Client holding quantity must be non-negative",
				"model_name": "ClientHolding",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_negative_quantity",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "quantity", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "ClientHolding quantity must be >= 0",
							}
						],
					},
				],
			},
			{
				"name": "finserv.product.amount_range",
				"description": "Product min_amount must be <= max_amount (when max > 0)",
				"model_name": "FinancialProduct",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_inverted_amount_range",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "max_amount_cents", "op": "gt", "value": 0},
							{
								"field": "min_amount_cents",
								"op": "gt",
								"value": "{{max_amount_cents}}",
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"FinancialProduct: min_amount_cents must be <= max_amount_cents"
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
		log.info(
			"FinancialServicesPlugin.setup_rules: %d rulesets configured", len(RULESETS)
		)

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
			log.warning(
				"FinancialServicesPlugin._try_setup_rules failed (non-fatal): %s", exc
			)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> FinancialServicesPlugin:
	return FinancialServicesPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.financial_services.models import (  # noqa: E402
	ClientHolding,
	FinancialClient,
	FinancialProduct,
	PortfolioAccount,
	SanctionsScreeningResult,
)
from pgappforge.plugins.erp.industry.financial_services.events import (  # noqa: E402
	AccountBalanceUpdatedEvent,
	AccountOpenedEvent,
	AccountStatusChangedEvent,
	ClientKYCStatusChangedEvent,
	ClientOnboardedEvent,
	ClientRiskProfileChangedEvent,
	HoldingRevaluedEvent,
	SanctionsMatchClearedEvent,
	SanctionsScreeningCompletedEvent,
	emit_event,
)
from pgappforge.plugins.erp.industry.financial_services.services import (  # noqa: E402
	AccountClosedError,
	AccountFrozenError,
	AccountNotFoundError,
	ClientNotFoundError,
	DuplicateClientNumberError,
	FinancialServicesService,
	FinServError,
	InsufficientBalanceError,
	KYCNotApprovedError,
	SanctionsHoldError,
)

__all__ = [
	# plugin
	"FinancialServicesPlugin",
	"create_plugin",
	# models
	"FinancialClient",
	"PortfolioAccount",
	"FinancialProduct",
	"ClientHolding",
	"SanctionsScreeningResult",
	# events
	"emit_event",
	"ClientOnboardedEvent",
	"ClientKYCStatusChangedEvent",
	"ClientRiskProfileChangedEvent",
	"AccountOpenedEvent",
	"AccountStatusChangedEvent",
	"AccountBalanceUpdatedEvent",
	"HoldingRevaluedEvent",
	"SanctionsScreeningCompletedEvent",
	"SanctionsMatchClearedEvent",
	# services
	"FinancialServicesService",
	"FinServError",
	"ClientNotFoundError",
	"AccountNotFoundError",
	"AccountFrozenError",
	"AccountClosedError",
	"InsufficientBalanceError",
	"KYCNotApprovedError",
	"SanctionsHoldError",
	"DuplicateClientNumberError",
]
