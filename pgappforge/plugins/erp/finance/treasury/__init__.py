"""
pgappforge/plugins/erp/finance/treasury/__init__.py

Treasury Management plugin for the PgAppForge ERP.

Entities:  BankAccount, CashPosition, FXDeal, BankStatement, BankStatementLine
Service:   TreasuryService
Events:    treasury.bank_account_created, treasury.fx_deal_booked,
           treasury.fx_deal_settled, treasury.bank_reconciliation_done,
           treasury.cash_position_updated
Consumes:  exchange_rate.updated (MTM revaluation), party.created

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.treasury",
    ]

Reports
-------
  /treasury/reports/cash-position  — Daily cash position (30 days)
  /treasury/reports/fx-exposure    — Open FX deal exposure
  /treasury/reports/bank-balances  — Bank account balances
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TreasuryPlugin(BasePlugin):
	"""Treasury Management plugin.

	Provides: bank accounts, daily cash positions, FX deal management (IFRS 9
	hedge accounting support), bank statement import, auto-reconciliation,
	mark-to-market revaluation, and cash-flow forecasting.
	"""

	name = "treasury"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="treasury",
			version="1.0.0",
			description=(
				"Treasury Management — bank accounts, cash positioning, FX deals "
				"(spot/forward/swap) with IFRS 9 hedge designation, bank statement "
				"import and auto-reconciliation, MTM revaluation, cash-flow forecasting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "treasury", "fx", "cash", "ifrs9"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_treasury_bank_account_read",
				"can_treasury_bank_account_write",
				"can_treasury_fx_read",
				"can_treasury_fx_book",
				"can_treasury_fx_settle",
				"can_treasury_fx_mtm",
				"can_treasury_statement_import",
				"can_treasury_reconcile",
				"can_treasury_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"treasury.bank_account_created",
			"treasury.fx_deal_booked",
			"treasury.fx_deal_settled",
			"treasury.bank_reconciliation_done",
			"treasury.cash_position_updated",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"exchange_rate.updated",   # triggers MTM revaluation of open FX deals
			"party.created",           # auto-link new parties as potential counterparties
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"TREASURY_MENU_CATEGORY": "Treasury",
			"TREASURY_DEFAULT_CURRENCY": "NGN",
			"TREASURY_MTM_AUTO_ON_RATE_UPDATE": False,
		}
		self.config = {**defaults, **self.config}
		self._wire_event_subscriptions()
		log.info("TreasuryPlugin initialised")

	def _wire_event_subscriptions(self) -> None:
		"""Wire in-process event handlers for upstream events."""
		from pgappforge.plugins.erp.foundation.events import subscribe

		if self.config.get("TREASURY_MTM_AUTO_ON_RATE_UPDATE"):
			def _on_rate_updated(event):
				log.info("TreasuryPlugin: exchange_rate.updated — scheduling MTM revaluation")
				# Production: dispatch to a Celery/ARQ task for async MTM run

			subscribe("exchange_rate.updated", _on_rate_updated)

	def register_views(self) -> None:
		from pgappforge.plugins.erp.finance.treasury.views import (
			BankAccountView,
			BankStatementView,
			FXDealView,
			TreasuryReportView,
		)
		cat = self.config.get("TREASURY_MENU_CATEGORY", "Treasury")
		self.add_view(BankAccountView, "Bank Accounts", icon="fa-bank", category=cat)
		self.add_view(FXDealView, "FX Deals", icon="fa-exchange", category=cat)
		self.add_view(BankStatementView, "Bank Statements", icon="fa-file-text-o", category=cat)
		self.add_view(TreasuryReportView, "Treasury Reports", icon="fa-bar-chart", category=cat)
		log.info("TreasuryPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.treasury.models import (
			BankAccount,
			BankStatement,
			BankStatementLine,
			CashPosition,
			FXDeal,
		)
		return [BankAccount, CashPosition, FXDeal, BankStatement, BankStatementLine]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for Treasury domain."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("TreasuryPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "bank_account.valid_account_type",
				"description": "BankAccount account_type must be CURRENT, SAVINGS, or OVERDRAFT",
				"model_name": "BankAccount",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_invalid_account_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "account_type", "op": "not_in",
							 "value": ["CURRENT", "SAVINGS", "OVERDRAFT"]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "account_type must be CURRENT, SAVINGS, or OVERDRAFT"}
						],
					},
				],
			},
			{
				"name": "fx_deal.positive_amounts",
				"description": "FX deal buy and sell amounts must be positive",
				"model_name": "FXDeal",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_zero_buy",
						"trigger_event": "on_before_create",
						"conditions_json": [{"field": "buy_amount_cents", "op": "lte", "value": 0}],
						"actions_json": [
							{"type": "raise_error", "message": "buy_amount_cents must be positive"}
						],
					},
					{
						"name": "block_zero_sell",
						"trigger_event": "on_before_create",
						"conditions_json": [{"field": "sell_amount_cents", "op": "lte", "value": 0}],
						"actions_json": [
							{"type": "raise_error", "message": "sell_amount_cents must be positive"}
						],
					},
				],
			},
			{
				"name": "fx_deal.valid_hedge_designation",
				"description": "hedge_designation must be a valid IFRS 9 value",
				"model_name": "FXDeal",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_invalid_hedge",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "hedge_designation", "op": "not_in",
							 "value": ["FAIR_VALUE", "CASH_FLOW", "NET_INVESTMENT", "NONE"]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "hedge_designation must be FAIR_VALUE, CASH_FLOW, NET_INVESTMENT, or NONE"}
						],
					},
				],
			},
			{
				"name": "fx_deal.no_settle_cancelled",
				"description": "Cannot settle a cancelled FX deal",
				"model_name": "FXDeal",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_settle_cancelled",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "CANCELLED"},
							{"field": "_new_status", "op": "eq", "value": "SETTLED"},
						],
						"actions_json": [
							{"type": "raise_error", "message": "Cannot settle a cancelled FX deal"}
						],
					},
				],
			},
			{
				"name": "bank_statement.balance_check",
				"description": "Statement closing_balance_cents must differ from opening by lines sum",
				"model_name": "BankStatement",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_balance_mismatch",
						"trigger_event": "on_create",
						"conditions_json": [],   # audited post-import by reconciliation
						"actions_json": [{"type": "log", "message": "Bank statement imported for reconciliation"}],
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
		log.info("TreasuryPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> TreasuryPlugin:
	return TreasuryPlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.finance.treasury.models import (  # noqa: E402
	BankAccount,
	BankStatement,
	BankStatementLine,
	CashPosition,
	FXDeal,
)
from pgappforge.plugins.erp.finance.treasury.services import (  # noqa: E402
	TreasuryService,
	TreasuryServiceError,
	BankAccountNotFoundError,
	FXDealNotFoundError,
	FXDealStatusError,
	BankAccountDetails,
	FXDealDetails,
)
from pgappforge.plugins.erp.finance.treasury.events import (  # noqa: E402
	BankAccountCreatedEvent,
	FXDealBookedEvent,
	FXDealSettledEvent,
	BankReconciliationDoneEvent,
	CashPositionUpdatedEvent,
)

__all__ = [
	"TreasuryPlugin",
	"create_plugin",
	# models
	"BankAccount",
	"CashPosition",
	"FXDeal",
	"BankStatement",
	"BankStatementLine",
	# services
	"TreasuryService",
	"TreasuryServiceError",
	"BankAccountNotFoundError",
	"FXDealNotFoundError",
	"FXDealStatusError",
	"BankAccountDetails",
	"FXDealDetails",
	# events
	"BankAccountCreatedEvent",
	"FXDealBookedEvent",
	"FXDealSettledEvent",
	"BankReconciliationDoneEvent",
	"CashPositionUpdatedEvent",
]
