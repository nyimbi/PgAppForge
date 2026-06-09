"""
pgappforge/plugins/erp/industry/real_estate/portfolio/__init__.py

PortfolioPlugin — Real Estate Portfolio Analytics sub-plugin.

Extends the real_estate plugin with:
  - PropertyPortfolio / PortfolioProperty: portfolio composition
  - PropertyDebt / DebtPayment: debt tracking and amortisation
  - CapExRecord: capital expenditure tracking
  - InvestorHolding / DistributionRecord: investor equity and distributions
  - PortfolioAnalyticsService: NOI, cap rate, DSCR, IRR, portfolio summary

Depends on: foundation, real_estate

Events emitted
--------------
  re_portfolio.property.acquired     — property added to a portfolio
  re_portfolio.capex.recorded        — capital expenditure recorded
  re_portfolio.distribution.paid     — distribution paid to investors
  re_portfolio.investor.exited       — investor holding exited

Events consumed
---------------
  (none — analytics are computed on demand)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.real_estate",
        "pgappforge.plugins.erp.industry.real_estate.portfolio",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PortfolioPlugin(BasePlugin):
	"""Real Estate Portfolio Analytics sub-plugin.

	Registers portfolio, debt, capex, investor, and distribution views.
	Provides PortfolioAnalyticsService with NOI, cap rate, DSCR, IRR,
	distribution calculation, and investor statement methods.
	"""

	name = "real_estate_portfolio"
	domain = "industry"
	depends_on: list[str] = ["foundation", "real_estate"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="real_estate_portfolio",
			version="1.0.0",
			description=(
				"Real Estate Portfolio Analytics — portfolio composition, debt tracking, "
				"CapEx recording, investor equity, pro-rata distributions, NOI, cap rate, "
				"DSCR, and IRR analytics."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "real-estate", "portfolio", "analytics", "debt", "capex", "investor"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_re_portfolio_list",
				"can_re_portfolio_write",
				"can_re_portfolio_analytics",
				"can_re_debt_list",
				"can_re_debt_write",
				"can_re_capex_list",
				"can_re_capex_write",
				"can_re_investor_list",
				"can_re_distribution_list",
				"can_re_distribution_pay",
				"can_re_portfolio_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"re_portfolio.property.acquired",
			"re_portfolio.capex.recorded",
			"re_portfolio.distribution.paid",
			"re_portfolio.investor.exited",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"RE_PORTFOLIO_MENU_CATEGORY": "Real Estate",
			"RE_PORTFOLIO_IRR_MIN_MONTHS": 12,
			"RE_PORTFOLIO_DIST_TOLERANCE_PCT": "0.01",
		}
		self.config = {**defaults, **self.config}
		log.info("PortfolioPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		pass

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.real_estate.portfolio.views import (
			PropertyPortfolioView,
			PropertyDebtView,
			CapExRecordView,
			InvestorHoldingView,
			DistributionRecordView,
			PortfolioDashboardView,
		)

		cat = self.config.get("RE_PORTFOLIO_MENU_CATEGORY", "Real Estate")

		self.add_view(PropertyPortfolioView, "Portfolios",       icon="fa-briefcase",       category=cat)
		self.add_view(PropertyDebtView,      "Debt Instruments", icon="fa-bank",             category=cat)
		self.add_view(CapExRecordView,       "CapEx Records",    icon="fa-wrench",           category=cat)
		self.add_view(InvestorHoldingView,   "Investor Holdings",icon="fa-users",            category=cat)
		self.add_view(DistributionRecordView,"Distributions",    icon="fa-money",            category=cat)
		self.add_view(PortfolioDashboardView,"Portfolio Dashboard", icon="fa-tachometer",   category=cat)

		log.info("PortfolioPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.real_estate.portfolio.models import (
			PropertyPortfolio,
			PortfolioProperty,
			PropertyDebt,
			DebtPayment,
			CapExRecord,
			InvestorHolding,
			DistributionRecord,
		)
		return [
			PropertyPortfolio,
			PortfolioProperty,
			PropertyDebt,
			DebtPayment,
			CapExRecord,
			InvestorHolding,
			DistributionRecord,
		]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PortfolioPlugin:
	"""Construct and return a PortfolioPlugin bound to *appbuilder*."""
	return PortfolioPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.real_estate.portfolio.models import (  # noqa: E402
	PropertyPortfolio,
	PortfolioProperty,
	PropertyDebt,
	DebtPayment,
	CapExRecord,
	InvestorHolding,
	DistributionRecord,
)
from pgappforge.plugins.erp.industry.real_estate.portfolio.events import (  # noqa: E402
	DistributionPaidEvent,
	CapExRecordedEvent,
	PropertyAcquiredEvent,
	InvestorExitedEvent,
)
from pgappforge.plugins.erp.industry.real_estate.portfolio.services import (  # noqa: E402
	PortfolioAnalyticsService,
	_xirr,
)

__all__ = [
	# plugin
	"PortfolioPlugin",
	"create_plugin",
	# models
	"PropertyPortfolio",
	"PortfolioProperty",
	"PropertyDebt",
	"DebtPayment",
	"CapExRecord",
	"InvestorHolding",
	"DistributionRecord",
	# events
	"DistributionPaidEvent",
	"CapExRecordedEvent",
	"PropertyAcquiredEvent",
	"InvestorExitedEvent",
	# services
	"PortfolioAnalyticsService",
	"_xirr",
]
