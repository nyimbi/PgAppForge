"""
pgappforge/plugins/fintech/wealth_management/__init__.py

WealthManagementPlugin — portfolios, orders, rebalancing, and performance.

Registers
---------
  - WealthClientView      (Wealth Clients menu)
  - PortfolioView         (Portfolios menu)
  - WealthOrderView       (Orders menu)
  - WealthDashboardView   (/wealth/dashboard/)

Events emitted
--------------
  wealth.client.onboarded, wealth.portfolio.created,
  wealth.order.placed, wealth.order.filled,
  wealth.rebalance.recommended, wealth.performance.report.generated

BPM actions
-----------
  wealth.place_order, wealth.rebalance

Depends on
----------
  foundation, core_banking
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class WealthManagementPlugin(BasePlugin):
	"""Wealth Management fintech plugin.

	Provides client onboarding, portfolio management, order placement,
	rebalancing, performance reporting, and management fee calculation.
	"""

	name = "wealth_management"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="wealth_management",
			version="1.0.0",
			description=(
				"Wealth Management — client suitability profiling, discretionary and advisory "
				"portfolio mandates, order routing, rebalancing engine, and monthly performance "
				"reporting with management fee calculation."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "wealth", "portfolio", "investment", "orders", "rebalancing"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_wlth_client_list",
				"can_wlth_client_write",
				"can_wlth_portfolio_list",
				"can_wlth_portfolio_write",
				"can_wlth_order_list",
				"can_wlth_order_write",
				"can_wlth_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.wealth_management.events import ALL_WLTH_EVENT_TYPES
		return ALL_WLTH_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		# React to core banking account events for AUM reconciliation (non-fatal)
		return ["cb.account.credited", "cb.account.debited"]

	def on_event(self, event_type: str, payload: dict, session: Any = None) -> None:
		"""Handle cross-plugin events.

		cb.account.credited / cb.account.debited — no-op for now; future AUM
		reconciliation hook.
		"""
		pass

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"WLTH_MENU_CATEGORY": "Wealth Management",
			"WLTH_REBALANCE_DRIFT_THRESHOLD_PCT": 5.0,
			"WLTH_DEFAULT_CURRENCY": "KES",
			"WLTH_SCHEDULER_ENABLED": True,
		}
		self.config = {**defaults, **self.config}
		log.info("WealthManagementPlugin initialised (config: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""No seeding required for wealth management."""
		pass

	def register_views(self) -> None:
		from pgappforge.plugins.fintech.wealth_management.views import (
			PortfolioView,
			WealthClientView,
			WealthDashboardView,
			WealthOrderView,
		)

		cat = self.config.get("WLTH_MENU_CATEGORY", "Wealth Management")

		self.add_view(
			WealthClientView,
			"Clients",
			icon="fa-users",
			category=cat,
		)
		self.add_view(
			PortfolioView,
			"Portfolios",
			icon="fa-briefcase",
			category=cat,
		)
		self.add_view(
			WealthOrderView,
			"Orders",
			icon="fa-exchange",
			category=cat,
		)
		self.add_view(
			WealthDashboardView,
			"Dashboard",
			icon="fa-dashboard",
			category=cat,
		)

		log.info("WealthManagementPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.fintech.wealth_management.models import (
			PerformanceReport,
			Portfolio,
			PortfolioHolding,
			WealthClient,
			WealthOrder,
		)
		return [WealthClient, Portfolio, PortfolioHolding, WealthOrder, PerformanceReport]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> WealthManagementPlugin:
	"""Construct and return a WealthManagementPlugin bound to *appbuilder*."""
	return WealthManagementPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.wealth_management.models import (  # noqa: E402
	PerformanceReport,
	Portfolio,
	PortfolioHolding,
	WealthClient,
	WealthOrder,
)
from pgappforge.plugins.fintech.wealth_management.events import (  # noqa: E402
	ALL_WLTH_EVENT_TYPES,
	OrderFilledEvent,
	OrderPlacedEvent,
	PerformanceReportGeneratedEvent,
	PortfolioCreatedEvent,
	RebalanceRecommendedEvent,
	WealthClientOnboardedEvent,
	WLTH_CLIENT_ONBOARDED,
	WLTH_ORDER_FILLED,
	WLTH_ORDER_PLACED,
	WLTH_PERFORMANCE_REPORT_GENERATED,
	WLTH_PORTFOLIO_CREATED,
	WLTH_REBALANCE_RECOMMENDED,
)
from pgappforge.plugins.fintech.wealth_management.services import (  # noqa: E402
	AllocationError,
	ClientNotFoundError,
	MandateViolationError,
	OrderNotFoundError,
	PortfolioNotFoundError,
	WealthManagementError,
	WealthManagementService,
)
from pgappforge.plugins.fintech.wealth_management.views import (  # noqa: E402
	PortfolioView,
	WealthClientView,
	WealthDashboardView,
	WealthOrderView,
)

__all__ = [
	# plugin
	"WealthManagementPlugin",
	"create_plugin",
	# models
	"WealthClient",
	"Portfolio",
	"PortfolioHolding",
	"WealthOrder",
	"PerformanceReport",
	# events — classes
	"WealthClientOnboardedEvent",
	"PortfolioCreatedEvent",
	"OrderPlacedEvent",
	"OrderFilledEvent",
	"RebalanceRecommendedEvent",
	"PerformanceReportGeneratedEvent",
	# events — constants
	"WLTH_CLIENT_ONBOARDED",
	"WLTH_PORTFOLIO_CREATED",
	"WLTH_ORDER_PLACED",
	"WLTH_ORDER_FILLED",
	"WLTH_REBALANCE_RECOMMENDED",
	"WLTH_PERFORMANCE_REPORT_GENERATED",
	"ALL_WLTH_EVENT_TYPES",
	# services
	"WealthManagementService",
	"WealthManagementError",
	"ClientNotFoundError",
	"PortfolioNotFoundError",
	"OrderNotFoundError",
	"AllocationError",
	"MandateViolationError",
	# views
	"WealthClientView",
	"PortfolioView",
	"WealthOrderView",
	"WealthDashboardView",
]
