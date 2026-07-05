from __future__ import annotations

from datetime import date
from typing import Any

import sqlalchemy as sa
from flask import current_app, request

from pgappforge import BaseView, ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.finance.fpa.models import (
	BudgetCycle,
	BudgetDriver,
	BudgetLine,
	BudgetVersion,
	ForecastSnapshot,
	KPITarget,
	ScenarioModel,
)
from pgappforge.plugins.erp.finance.fpa.services import FPAService


def _get_session():
	ab = current_app.extensions.get("appbuilder")
	if ab and hasattr(ab, "get_session"):
		return ab.get_session
	db = current_app.extensions.get("sqlalchemy")
	if db:
		return db.session
	raise RuntimeError("Cannot obtain database session outside app context")


def _tenant_filter(model: Any, tenant_id: str | None) -> list[Any]:
	if not tenant_id:
		return []
	return [model.tenant_id == tenant_id]


def _status_badge(status: str) -> str:
	return {
		"DRAFT": "secondary",
		"INPUT_OPEN": "primary",
		"UNDER_REVIEW": "warning",
		"APPROVED": "success",
		"LOCKED": "dark",
	}.get(status, "secondary")


class FPADashboardView(BaseView):
	route_base = "/fpa"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id") or None
		service = FPAService()

		active_statuses = ["INPUT_OPEN", "UNDER_REVIEW", "APPROVED"]
		open_version_types = ["FORECAST", "WORKING"]

		active_budgets = session.execute(
			sa.select(sa.func.count(BudgetCycle.id)).where(
				BudgetCycle.status.in_(active_statuses),
				*_tenant_filter(BudgetCycle, tenant_id),
			)
		).scalar_one() or 0
		open_forecasts = session.execute(
			sa.select(sa.func.count(BudgetVersion.id)).where(
				BudgetVersion.version_type.in_(open_version_types),
				BudgetVersion.is_active.is_(True),
				BudgetVersion.locked_at.is_(None),
				*_tenant_filter(BudgetVersion, tenant_id),
			)
		).scalar_one() or 0

		open_cycles = session.execute(
			sa.select(BudgetCycle).where(
				BudgetCycle.status.in_(["DRAFT", "INPUT_OPEN", "UNDER_REVIEW"]),
				*_tenant_filter(BudgetCycle, tenant_id),
			).order_by(BudgetCycle.fiscal_year.desc(), BudgetCycle.name)
		).scalars().all()

		latest_snapshot_date = session.execute(
			sa.select(sa.func.max(ForecastSnapshot.snapshot_date)).where(
				*_tenant_filter(ForecastSnapshot, tenant_id),
			)
		).scalar_one_or_none()
		snapshot_filters = _tenant_filter(ForecastSnapshot, tenant_id)
		if latest_snapshot_date is not None:
			snapshot_filters.append(ForecastSnapshot.snapshot_date == latest_snapshot_date)

		totals = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(ForecastSnapshot.budget_cents), 0),
				sa.func.coalesce(sa.func.sum(ForecastSnapshot.actual_cents), 0),
			).where(*snapshot_filters)
		).one()
		plan_cents = int(totals[0] or 0)
		actual_cents = int(totals[1] or 0)
		variance_pct = round(((actual_cents - plan_cents) / plan_cents * 100), 2) if plan_cents else 0

		chart_rows = session.execute(
			sa.select(
				sa.func.coalesce(ForecastSnapshot.cost_center_code, "Unassigned"),
				sa.func.coalesce(sa.func.sum(ForecastSnapshot.budget_cents), 0),
				sa.func.coalesce(sa.func.sum(ForecastSnapshot.actual_cents), 0),
			).where(*snapshot_filters).group_by(ForecastSnapshot.cost_center_code)
		).all()
		chart_config = {
			"type": "bar",
			"data": {
				"labels": [row[0] for row in chart_rows],
				"datasets": [
					{"label": "Plan", "data": [int(row[1] or 0) / 100 for row in chart_rows]},
					{"label": "Actual", "data": [int(row[2] or 0) / 100 for row in chart_rows]},
				],
			},
		}

		selected_cycle = open_cycles[0] if open_cycles else None
		variance_rows = []
		rolling_forecast = {}
		if selected_cycle is not None and tenant_id:
			latest_period = session.execute(
				sa.select(sa.func.max(ForecastSnapshot.period_month)).where(
					ForecastSnapshot.cycle_id == selected_cycle.id,
					ForecastSnapshot.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if latest_period is not None:
				variance_rows = service.get_variance_analysis(
					session,
					selected_cycle.id,
					latest_period,
					tenant_id=tenant_id,
				)
			rolling_forecast = service.compute_rolling_forecast(
				session,
				selected_cycle.id,
				date.today(),
				tenant_id=tenant_id,
			)

		kpi_tiles = [
			{"label": "Active Budgets", "value": active_budgets},
			{"label": "Open Forecasts", "value": open_forecasts},
			{"label": "Plan vs Actual Variance", "value": f"{variance_pct:,.2f}%"},
		]
		cycle_rows = [
			{
				"name": cycle.name,
				"fiscal_year": cycle.fiscal_year,
				"cycle_type": cycle.cycle_type,
				"status": cycle.status,
				"badge_class": _status_badge(cycle.status),
				"input_deadline": cycle.input_deadline,
				"approval_deadline": cycle.approval_deadline,
			}
			for cycle in open_cycles
		]

		return self.render_template(
			"erp/finance/fpa/dashboard.html",
			kpi_tiles=kpi_tiles,
			chart_config=chart_config,
			open_budget_cycles=cycle_rows,
			variance_rows=variance_rows,
			rolling_forecast=rolling_forecast,
		)


class BudgetCycleView(ModelView):
	datamodel = SQLAInterface(BudgetCycle)

	list_columns = ["name", "fiscal_year", "cycle_type", "status", "input_deadline", "approval_deadline"]
	show_columns = ["id", "name", "fiscal_year", "cycle_type", "status", "input_deadline", "approval_deadline", "approved_at"]
	label_columns = {
		"name": "Name",
		"fiscal_year": "Fiscal Year",
		"cycle_type": "Cycle Type",
		"status": "Status",
		"input_deadline": "Input Deadline",
		"approval_deadline": "Approval Deadline",
		"approved_at": "Approved At",
	}
	add_columns = ["tenant_id", "name", "fiscal_year", "cycle_type", "status", "input_deadline", "approval_deadline"]
	edit_columns = add_columns


class BudgetVersionView(ModelView):
	datamodel = SQLAInterface(BudgetVersion)

	list_columns = ["version_name", "version_type", "is_active", "locked_at", "notes"]
	show_columns = ["id", "version_name", "version_type", "is_active", "locked_at", "notes"]
	label_columns = {
		"version_name": "Version Name",
		"version_type": "Version Type",
		"is_active": "Active",
		"locked_at": "Locked At",
		"notes": "Notes",
	}
	add_columns = ["tenant_id", "cycle_id", "version_name", "version_type", "is_active", "notes"]
	edit_columns = add_columns


class BudgetLineView(ModelView):
	datamodel = SQLAInterface(BudgetLine)

	list_columns = ["gl_account_code", "cost_center_code", "period_month", "amount_cents", "driver_type", "status"]
	show_columns = ["id", "gl_account_code", "cost_center_code", "period_month", "amount_cents", "driver_type", "driver_params", "dimensions", "status"]
	label_columns = {
		"gl_account_code": "GL Account",
		"cost_center_code": "Cost Center",
		"period_month": "Period Month",
		"amount_cents": "Amount (cents)",
		"driver_type": "Driver Type",
		"driver_params": "Driver Parameters",
		"dimensions": "Dimensions",
		"status": "Status",
	}
	add_columns = ["tenant_id", "version_id", "gl_account_code", "cost_center_code", "entity_id", "period_month", "amount_cents", "driver_type", "driver_params", "dimensions", "status"]
	edit_columns = add_columns


class BudgetDriverView(ModelView):
	datamodel = SQLAInterface(BudgetDriver)

	list_columns = ["driver_code", "name", "driver_type", "unit", "base_value", "is_global"]
	show_columns = ["id", "driver_code", "name", "driver_type", "unit", "base_value", "formula_expression", "is_global"]
	label_columns = {
		"driver_code": "Driver Code",
		"name": "Name",
		"driver_type": "Driver Type",
		"unit": "Unit",
		"base_value": "Base Value",
		"formula_expression": "Formula",
		"is_global": "Global",
	}
	add_columns = ["tenant_id", "driver_code", "name", "driver_type", "unit", "base_value", "formula_expression", "is_global"]
	edit_columns = add_columns


class ScenarioView(ModelView):
	datamodel = SQLAInterface(ScenarioModel)

	list_columns = ["name", "scenario_type", "status", "description"]
	show_columns = ["id", "name", "description", "scenario_type", "adjustment_rules", "status"]
	label_columns = {
		"name": "Name",
		"description": "Description",
		"scenario_type": "Scenario Type",
		"adjustment_rules": "Adjustment Rules",
		"status": "Status",
	}
	add_columns = ["tenant_id", "base_version_id", "name", "description", "scenario_type", "adjustment_rules", "status"]
	edit_columns = add_columns


class ForecastSnapshotView(ModelView):
	datamodel = SQLAInterface(ForecastSnapshot)

	list_columns = ["snapshot_date", "period_month", "gl_account_code", "cost_center_code", "actual_cents", "budget_cents", "forecast_cents", "variance_pct"]
	show_columns = ["id", "snapshot_date", "period_month", "gl_account_code", "cost_center_code", "actual_cents", "budget_cents", "forecast_cents", "variance_cents", "variance_pct"]
	label_columns = {
		"snapshot_date": "Snapshot Date",
		"period_month": "Period Month",
		"gl_account_code": "GL Account",
		"cost_center_code": "Cost Center",
		"actual_cents": "Actual (cents)",
		"budget_cents": "Budget (cents)",
		"forecast_cents": "Forecast (cents)",
		"variance_cents": "Variance (cents)",
		"variance_pct": "Variance %",
	}
	add_columns = ["tenant_id", "cycle_id", "snapshot_date", "period_month", "gl_account_code", "cost_center_code", "actual_cents", "budget_cents", "forecast_cents", "variance_cents", "variance_pct"]
	edit_columns = add_columns


class KPITargetView(ModelView):
	datamodel = SQLAInterface(KPITarget)

	list_columns = ["kpi_code", "kpi_name", "period_month", "target_value", "actual_value", "unit", "status"]
	show_columns = ["id", "kpi_code", "kpi_name", "period_month", "target_value", "actual_value", "unit", "direction", "status"]
	label_columns = {
		"kpi_code": "KPI Code",
		"kpi_name": "KPI Name",
		"period_month": "Period Month",
		"target_value": "Target Value",
		"actual_value": "Actual Value",
		"unit": "Unit",
		"direction": "Direction",
		"status": "Status",
	}
	add_columns = ["tenant_id", "kpi_code", "kpi_name", "cycle_id", "period_month", "target_value", "actual_value", "unit", "direction", "status"]
	edit_columns = add_columns


class FPAReportView(FPADashboardView):
	route_base = "/fpa/reports"


ScenarioModelView = ScenarioView

__all__ = [
	"FPADashboardView",
	"BudgetCycleView",
	"BudgetVersionView",
	"BudgetLineView",
	"BudgetDriverView",
	"ScenarioView",
	"ScenarioModelView",
	"ForecastSnapshotView",
	"KPITargetView",
	"FPAReportView",
]
