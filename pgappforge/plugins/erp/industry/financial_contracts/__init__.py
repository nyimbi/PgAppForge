"""
pgappforge/plugins/erp/industry/financial_contracts/__init__.py

FinancialContractsPlugin — ACTUS-based algorithmic financial contract plugin.

Provides:
  - FinancialContract master records (PAM/ANN/CLM/BND/LAX/NAM ACTUS types)
  - CashFlowSchedule — immutable, ACTUS-generated event sequences
  - RiskFactor — market risk factor reference data (rates, FX, spreads)
  - ContractValuation — immutable NPV/duration/convexity snapshots

Business services:
  - generate_cash_flows()         — ACTUS PAM/ANN/LAX schedule generation
  - calculate_npv()               — flat-rate discounted NPV in integer cents
  - mark_to_market()              — value against market data + persist snapshot
  - stress_test()                 — multi-scenario NPV analysis
  - calculate_maturity_profile()  — portfolio cash flows bucketed by tenor
  - generate_schedule_report()    — full contract schedule with settlement summary

Events emitted:
  - financial_contracts.cash_flows.generated
  - financial_contracts.contract.valued
  - financial_contracts.cash_flow.settled
  - financial_contracts.cash_flow.missed
  - financial_contracts.contract.defaulted
  - financial_contracts.stress_test.completed

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.financial_contracts",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class FinancialContractsPlugin(BasePlugin):
	"""ACTUS-based financial contracts plugin.

	Class-level routing metadata:
	    name       = "financial_contracts"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "financial_contracts"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="financial_contracts",
			version="1.0.0",
			description=(
				"ACTUS algorithmic financial contracts — PAM, ANN, CLM, BND, LAX, NAM "
				"contract types with deterministic cash flow generation, NPV calculation, "
				"mark-to-market valuation, stress testing, and maturity profile analytics."
			),
			author="PgAppForge Contributors",
			tags=[
				"erp", "industry", "finance", "actus", "contracts",
				"bonds", "loans", "derivatives", "risk",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_fc_contract_read",
				"can_fc_contract_write",
				"can_fc_contract_generate_flows",
				"can_fc_cashflow_read",
				"can_fc_cashflow_settle",
				"can_fc_riskfactor_read",
				"can_fc_riskfactor_write",
				"can_fc_valuation_read",
				"can_fc_valuation_write",
				"can_fc_stress_test",
				"can_fc_reports",
				"can_fc_portfolio",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events emitted by this plugin."""
		return [
			"financial_contracts.cash_flows.generated",
			"financial_contracts.contract.valued",
			"financial_contracts.cash_flow.settled",
			"financial_contracts.cash_flow.missed",
			"financial_contracts.contract.defaulted",
			"financial_contracts.stress_test.completed",
		]

	def subscribe_to(self) -> list[str]:
		"""Events consumed by this plugin (v1: none)."""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"FC_MENU_CATEGORY": "Financial Contracts",
			"FC_DEFAULT_DISCOUNT_RATE": "0.05",
			"FC_DEFAULT_DAY_COUNT": "A365",
			"FC_SETTLEMENT_LAG": "P2D",
		}
		self.config = {**defaults, **self.config}
		log.info(
			"FinancialContractsPlugin initialised (config keys: %s)",
			list(self.config),
		)

	def register_views(self) -> None:
		"""Register financial contract views under the configured menu category."""
		from pgappforge.plugins.erp.industry.financial_contracts.views import (
			ContractView,
			CashFlowView,
			ValuationView,
			RiskFactorView,
			PortfolioView,
		)

		cat = self.config.get("FC_MENU_CATEGORY", "Financial Contracts")

		self.add_view(
			ContractView, "Contracts",
			icon="fa-file-contract", category=cat,
		)
		self.add_view(
			CashFlowView, "Cash Flows",
			icon="fa-exchange", category=cat,
		)
		self.add_view(
			ValuationView, "Valuations",
			icon="fa-line-chart", category=cat,
		)
		self.add_view(
			RiskFactorView, "Risk Factors",
			icon="fa-thermometer-half", category=cat,
		)
		self.add_view(
			PortfolioView, "Portfolio",
			icon="fa-pie-chart", category=cat,
		)

		log.info(
			"FinancialContractsPlugin: views registered under category %r", cat,
		)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract,
			CashFlowSchedule,
			RiskFactor,
			ContractValuation,
		)
		return [
			FinancialContract,
			CashFlowSchedule,
			RiskFactor,
			ContractValuation,
		]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> FinancialContractsPlugin:
	"""Construct and return a FinancialContractsPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return FinancialContractsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.financial_contracts.models import (  # noqa: E402
	FinancialContract,
	CashFlowSchedule,
	RiskFactor,
	ContractValuation,
)
from pgappforge.plugins.erp.industry.financial_contracts.events import (  # noqa: E402
	CashFlowsGeneratedEvent,
	ContractValuedEvent,
	CashFlowSettledEvent,
	CashFlowMissedEvent,
	ContractDefaultedEvent,
	StressTestCompletedEvent,
	emit_event,
)
from pgappforge.plugins.erp.industry.financial_contracts.services import (  # noqa: E402
	FinancialContractsService,
	FinancialContractsError,
	ContractNotFoundError,
	InvalidContractTypeError,
	CashFlowGenerationError,
)

__all__ = [
	# plugin
	"FinancialContractsPlugin",
	"create_plugin",
	# models
	"FinancialContract",
	"CashFlowSchedule",
	"RiskFactor",
	"ContractValuation",
	# events
	"CashFlowsGeneratedEvent",
	"ContractValuedEvent",
	"CashFlowSettledEvent",
	"CashFlowMissedEvent",
	"ContractDefaultedEvent",
	"StressTestCompletedEvent",
	"emit_event",
	# services
	"FinancialContractsService",
	"FinancialContractsError",
	"ContractNotFoundError",
	"InvalidContractTypeError",
	"CashFlowGenerationError",
]
