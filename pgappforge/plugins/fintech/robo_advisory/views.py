"""
pgappforge/plugins/fintech/robo_advisory/views.py

Robo Advisory views: ModelPortfolio, RoboGoal, RoboDashboard.

Widget conventions (follow core_banking pattern):
  - Monetary columns:  CurrencyWidget
  - Date fields:       DatePickerWidget
  - JSON allocations:  JSONWidget
  - KPI panels:        ProgressWidget / AdvancedChartsWidget
  - Risk level:        Select2Widget

Security model:
  - ModelPortfolioView: can_list, can_show, can_add, can_edit (admin)
  - RoboGoalView:       can_list, can_show (read-only; goals created via service)
  - RoboDashboardView:  can_list (summary KPIs and goal progress)
"""
from __future__ import annotations

import logging
from typing import Any

from flask import request
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

from pgappforge.plugins.fintech.robo_advisory.models import (
	ModelPortfolio,
	RoboDriftReport,
	RoboGoal,
	RoboInvestorProfile,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ModelPortfolioView
# ---------------------------------------------------------------------------

class ModelPortfolioView(ModelView):
	"""Admin view for managing model portfolio templates."""

	datamodel = SQLAInterface(ModelPortfolio)

	list_title = "Model Portfolios"
	show_title = "Model Portfolio"
	add_title = "Add Model Portfolio"
	edit_title = "Edit Model Portfolio"

	list_columns = [
		"name",
		"risk_level",
		"expected_return_pct",
		"expected_volatility_pct",
		"is_active",
	]
	show_columns = list_columns + ["allocation", "description"]
	add_columns = ["name", "risk_level", "allocation", "description",
	               "expected_return_pct", "expected_volatility_pct", "is_active"]
	edit_columns = add_columns

	label_columns = {
		"name": "Portfolio Name",
		"risk_level": "Risk Level",
		"allocation": "Asset Allocation",
		"expected_return_pct": "Expected Return %",
		"expected_volatility_pct": "Expected Volatility %",
		"is_active": "Active",
		"description": "Description",
	}

	formatters_columns = {
		"allocation": json_widget(),
	}

	search_columns = ["name", "risk_level"]
	base_order = ("risk_level", "asc")

	page_size = 20


# ---------------------------------------------------------------------------
# RoboGoalView
# ---------------------------------------------------------------------------

class RoboGoalView(ModelView):
	"""Read-only list/show view for investor goals."""

	datamodel = SQLAInterface(RoboGoal)

	list_title = "Investment Goals"
	show_title = "Goal Detail"

	list_columns = [
		"goal_name",
		"goal_type",
		"target_amount_cents",
		"current_amount_cents",
		"monthly_contribution_cents",
		"status",
		"target_date",
		"created_at",
	]
	show_columns = list_columns + [
		"profile_id",
		"assigned_portfolio_id",
		"updated_at",
	]

	label_columns = {
		"goal_name": "Goal Name",
		"goal_type": "Goal Type",
		"target_amount_cents": "Target Amount",
		"current_amount_cents": "Current Amount",
		"monthly_contribution_cents": "Monthly Contribution",
		"status": "Status",
		"target_date": "Target Date",
		"created_at": "Created",
		"updated_at": "Last Updated",
		"profile_id": "Investor Profile",
		"assigned_portfolio_id": "Model Portfolio",
	}

	formatters_columns = {
		"target_amount_cents": currency_widget(),
		"current_amount_cents": currency_widget(),
		"monthly_contribution_cents": currency_widget(),
		"target_date": date_widget(),
		"created_at": date_widget(),
		"updated_at": date_widget(),
	}

	search_columns = ["goal_name", "goal_type", "status"]
	base_order = ("created_at", "desc")
	base_permissions = ["can_list", "can_show"]

	page_size = 25


# ---------------------------------------------------------------------------
# RoboDashboardView
# ---------------------------------------------------------------------------

class RoboDashboardView(BaseView):
	"""Robo advisory KPI dashboard — total AUM, goal progress, drift alerts."""

	route_base = "/robo"
	default_view = "dashboard"

	@expose("/dashboard/")
	@has_access
	def dashboard(self) -> Any:
		"""Render the robo advisory KPI dashboard."""
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			session = ab.get_session if ab else None
			kpis = self._get_kpis(session) if session else {}
		except Exception as exc:
			log.warning("RoboDashboardView.dashboard: KPI fetch failed: %s", exc)
			kpis = {}

		return self.render_template(
			"robo_dashboard.html",
			kpis=kpis,
			title="Robo Advisory Dashboard",
		)

	def _get_kpis(self, session: Any) -> dict[str, Any]:
		"""Aggregate live KPIs across all robo profiles for the current tenant."""
		try:
			from sqlalchemy import func, select as _select
			total_profiles = session.execute(
				_select(func.count()).select_from(RoboInvestorProfile)
			).scalar() or 0

			active_goals = session.execute(
				_select(func.count()).select_from(RoboGoal).where(
					RoboGoal.status == "ACTIVE"
				)
			).scalar() or 0

			achieved_goals = session.execute(
				_select(func.count()).select_from(RoboGoal).where(
					RoboGoal.status == "ACHIEVED"
				)
			).scalar() or 0

			total_target_cents = session.execute(
				_select(
					func.coalesce(func.sum(RoboGoal.target_amount_cents), 0)
				).where(RoboGoal.status == "ACTIVE")
			).scalar() or 0

			total_current_cents = session.execute(
				_select(
					func.coalesce(func.sum(RoboGoal.current_amount_cents), 0)
				).where(RoboGoal.status == "ACTIVE")
			).scalar() or 0

			drift_alerts = session.execute(
				_select(func.count()).select_from(RoboDriftReport).where(
					RoboDriftReport.rebalance_recommended == True  # noqa: E712
				)
			).scalar() or 0

			model_portfolios = session.execute(
				_select(func.count()).select_from(ModelPortfolio).where(
					ModelPortfolio.is_active == True  # noqa: E712
				)
			).scalar() or 0

			# Overall progress percentage
			progress_pct = (
				round(total_current_cents / max(total_target_cents, 1) * 100, 1)
				if total_target_cents
				else 0.0
			)

			return {
				"total_profiles": total_profiles,
				"active_goals": active_goals,
				"achieved_goals": achieved_goals,
				"total_target_cents": total_target_cents,
				"total_current_cents": total_current_cents,
				"progress_pct": progress_pct,
				"drift_alerts": drift_alerts,
				"model_portfolios": model_portfolios,
			}
		except Exception as exc:
			log.debug("RoboDashboardView._get_kpis failed: %s", exc)
			return {}


__all__ = [
	"ModelPortfolioView",
	"RoboGoalView",
	"RoboDashboardView",
]
