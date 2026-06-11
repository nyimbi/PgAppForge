"""
pgappforge/plugins/fintech/wealth_management/views.py

Wealth Management views: WealthClient, Portfolio, WealthOrder, Dashboard.

Widget conventions (follow core_banking pattern):
  - Monetary columns:  CurrencyWidget
  - Date fields:       DatePickerWidget
  - JSON allocations:  JSONWidget
  - KPI gauges:        ProgressWidget / AdvancedChartsWidget
  - Dropdowns:         Select2Widget

Security model:
  - WealthClientView:  can_list, can_show  (read; RM edits via dedicated form)
  - PortfolioView:     can_list, can_show
  - WealthOrderView:   can_list, can_show  (orders created via service)
  - WealthDashboard:   can_list (summary KPIs)
"""
from __future__ import annotations

import logging
from typing import Any

from flask import flash, redirect, request, url_for
from flask_appbuilder import BaseView, ModelView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	currency_widget,
	date_widget,
	json_widget,
	progress_widget,
	select2_widget,
)

from pgappforge.plugins.fintech.wealth_management.models import (
	PerformanceReport,
	Portfolio,
	PortfolioHolding,
	WealthClient,
	WealthOrder,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WealthClientView
# ---------------------------------------------------------------------------

class WealthClientView(ModelView):
	"""Read-only list/show view for wealth client records."""

	datamodel = SQLAInterface(WealthClient)

	list_title = "Wealth Clients"
	show_title = "Wealth Client"

	list_columns = [
		"full_name",
		"risk_profile",
		"suitability_score",
		"total_aum_cents",
		"investment_experience",
		"investment_horizon_years",
		"onboarded_at",
	]
	show_columns = list_columns + [
		"customer_id",
		"annual_income_cents",
		"liquid_assets_cents",
		"relationship_manager_id",
		"updated_at",
	]

	label_columns = {
		"full_name": "Client Name",
		"risk_profile": "Risk Profile",
		"suitability_score": "Suitability Score",
		"total_aum_cents": "Total AUM",
		"investment_experience": "Investment Experience",
		"investment_horizon_years": "Horizon (yrs)",
		"annual_income_cents": "Annual Income",
		"liquid_assets_cents": "Liquid Assets",
		"onboarded_at": "Onboarded",
		"updated_at": "Last Updated",
	}

	formatters_columns = {
		"total_aum_cents": currency_widget(),
		"annual_income_cents": currency_widget(),
		"liquid_assets_cents": currency_widget(),
		"onboarded_at": date_widget(),
		"updated_at": date_widget(),
	}

	search_columns = ["full_name", "risk_profile", "investment_experience"]
	base_order = ("onboarded_at", "desc")
	base_permissions = ["can_list", "can_show"]

	page_size = 25


# ---------------------------------------------------------------------------
# PortfolioView
# ---------------------------------------------------------------------------

class PortfolioView(ModelView):
	"""List/show view for investment portfolios."""

	datamodel = SQLAInterface(Portfolio)

	list_title = "Portfolios"
	show_title = "Portfolio"

	list_columns = [
		"name",
		"mandate_type",
		"base_currency",
		"benchmark",
		"status",
		"management_fee_pct",
		"created_at",
	]
	show_columns = list_columns + [
		"client_id",
		"target_allocation",
		"updated_at",
	]

	label_columns = {
		"name": "Portfolio Name",
		"mandate_type": "Mandate Type",
		"base_currency": "Currency",
		"benchmark": "Benchmark",
		"status": "Status",
		"management_fee_pct": "Mgmt Fee %",
		"target_allocation": "Target Allocation",
		"created_at": "Created",
		"updated_at": "Last Updated",
	}

	formatters_columns = {
		"target_allocation": json_widget(),
		"created_at": date_widget(),
		"updated_at": date_widget(),
	}

	search_columns = ["name", "mandate_type", "status", "base_currency"]
	base_order = ("created_at", "desc")
	base_permissions = ["can_list", "can_show"]

	page_size = 25


# ---------------------------------------------------------------------------
# WealthOrderView
# ---------------------------------------------------------------------------

class WealthOrderView(ModelView):
	"""Read-only list/show view for wealth orders."""

	datamodel = SQLAInterface(WealthOrder)

	list_title = "Wealth Orders"
	show_title = "Order Detail"

	list_columns = [
		"asset_code",
		"asset_name",
		"order_side",
		"order_type",
		"quantity",
		"amount_cents",
		"status",
		"executed_quantity",
		"executed_amount_cents",
		"created_at",
	]
	show_columns = list_columns + [
		"portfolio_id",
		"limit_price_cents",
		"broker_reference",
		"updated_at",
	]

	label_columns = {
		"asset_code": "Asset",
		"asset_name": "Asset Name",
		"order_side": "Side",
		"order_type": "Type",
		"quantity": "Quantity",
		"amount_cents": "Amount",
		"status": "Status",
		"executed_quantity": "Executed Qty",
		"executed_amount_cents": "Executed Amount",
		"limit_price_cents": "Limit Price",
		"broker_reference": "Broker Ref",
		"created_at": "Created",
		"updated_at": "Last Updated",
	}

	formatters_columns = {
		"amount_cents": currency_widget(),
		"executed_amount_cents": currency_widget(),
		"limit_price_cents": currency_widget(),
		"created_at": date_widget(),
		"updated_at": date_widget(),
	}

	search_columns = ["asset_code", "order_side", "order_type", "status", "broker_reference"]
	base_order = ("created_at", "desc")
	base_permissions = ["can_list", "can_show"]

	page_size = 50


# ---------------------------------------------------------------------------
# WealthDashboardView
# ---------------------------------------------------------------------------

class WealthDashboardView(BaseView):
	"""Wealth management summary dashboard — AUM, top portfolios, recent orders."""

	route_base = "/wealth"
	default_view = "dashboard"

	@expose("/dashboard/")
	@has_access
	def dashboard(self) -> Any:
		"""Render the wealth management KPI dashboard."""
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			session = ab.get_session if ab else None
			kpis = self._get_kpis(session) if session else {}
		except Exception as exc:
			log.warning("WealthDashboardView.dashboard: KPI fetch failed: %s", exc)
			kpis = {}

		return self.render_template(
			"wealth_dashboard.html",
			kpis=kpis,
			title="Wealth Management Dashboard",
		)

	def _get_kpis(self, session: Any) -> dict[str, Any]:
		"""Aggregate KPIs across all wealth clients for the current tenant."""
		try:
			from sqlalchemy import func, select as _select
			total_clients = session.execute(
				_select(func.count()).select_from(WealthClient)
			).scalar() or 0

			total_aum = session.execute(
				_select(func.coalesce(func.sum(WealthClient.total_aum_cents), 0))
			).scalar() or 0

			active_portfolios = session.execute(
				_select(func.count()).select_from(Portfolio).where(Portfolio.status == "ACTIVE")
			).scalar() or 0

			pending_orders = session.execute(
				_select(func.count()).select_from(WealthOrder).where(
					WealthOrder.status.in_(["PENDING", "SUBMITTED", "PARTIALLY_FILLED"])
				)
			).scalar() or 0

			return {
				"total_clients": total_clients,
				"total_aum_cents": total_aum,
				"active_portfolios": active_portfolios,
				"pending_orders": pending_orders,
			}
		except Exception as exc:
			log.debug("_get_kpis failed: %s", exc)
			return {}


__all__ = [
	"WealthClientView",
	"PortfolioView",
	"WealthOrderView",
	"WealthDashboardView",
]
