from __future__ import annotations

import sqlalchemy as sa
from flask import current_app, request

from pgappforge import expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView, BaseERPModelView
from pgappforge.plugins.erp.finance.fpa.models import (
	BudgetCycle,
	ForecastSnapshot,
	KPITarget,
	ScenarioModel,
)


def _get_session():
	ab = current_app.extensions.get("appbuilder")
	if ab and hasattr(ab, "get_session"):
		return ab.get_session
	db = current_app.extensions.get("sqlalchemy")
	if db:
		return db.session
	raise RuntimeError("Cannot obtain database session outside app context")


def _tenant_filter(model, tenant_id: str | None) -> list:
	if not tenant_id:
		return []
	return [model.tenant_id == tenant_id]


def _status_badge(status: str) -> str:
	return {
		"DRAFT": "default",
		"INPUT_OPEN": "primary",
		"UNDER_REVIEW": "warning",
		"APPROVED": "success",
		"LOCKED": "default",
	}.get(status, "default")


class FPADashboardView(BaseERPView):
	route_base = "/fpa"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id") or None

		active_statuses = ["INPUT_OPEN", "UNDER_REVIEW", "APPROVED"]
		open_statuses = ["DRAFT", "INPUT_OPEN", "UNDER_REVIEW"]

		active_cycles = session.execute(
			sa.select(sa.func.count(BudgetCycle.id)).where(
				BudgetCycle.status.in_(active_statuses),
				*_tenant_filter(BudgetCycle, tenant_id),
			)
		).scalar_one() or 0
		open_cycles_count = session.execute(
			sa.select(sa.func.count(BudgetCycle.id)).where(
				BudgetCycle.status.in_(open_statuses),
				*_tenant_filter(BudgetCycle, tenant_id),
			)
		).scalar_one() or 0
		scenario_count = session.execute(
			sa.select(sa.func.count(ScenarioModel.id)).where(
				*_tenant_filter(ScenarioModel, tenant_id),
			)
		).scalar_one() or 0
		off_track_kpis = session.execute(
			sa.select(sa.func.count(KPITarget.id)).where(
				KPITarget.status == "OFF_TRACK",
				*_tenant_filter(KPITarget, tenant_id),
			)
		).scalar_one() or 0

		open_cycles = session.execute(
			sa.select(BudgetCycle).where(
				BudgetCycle.status.in_(open_statuses),
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
					{"label": "Plan", "data": [int(row[1] or 0) // 100 for row in chart_rows]},
					{"label": "Actual", "data": [int(row[2] or 0) // 100 for row in chart_rows]},
				],
			},
		}

		kpi_tiles = [
			{"label": "Active Budget Cycles", "value": active_cycles},
			{"label": "Open Planning Cycles", "value": open_cycles_count},
			{"label": "Scenario Models", "value": scenario_count},
			{"label": "Off-track KPIs", "value": off_track_kpis},
		]
		kpi_html = self.kpi_cards([
			{
				"label": "Active Budget Cycles",
				"value": active_cycles,
				"format": "integer",
				"color": "#1a56db",
				"icon": "fa-calendar-check-o",
			},
			{
				"label": "Open Planning Cycles",
				"value": open_cycles_count,
				"format": "integer",
				"color": "#0e9f6e",
				"icon": "fa-folder-open",
			},
			{
				"label": "Scenario Models",
				"value": scenario_count,
				"format": "integer",
				"color": "#7e3af2",
				"icon": "fa-random",
			},
			{
				"label": "Off-track KPIs",
				"value": off_track_kpis,
				"format": "integer",
				"color": "#c81e1e",
				"icon": "fa-bullseye",
			},
		])
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
			kpi_html=kpi_html,
			chart_config=chart_config,
			open_budget_cycles=cycle_rows,
			variance_rows=[],
			rolling_forecast={},
		)


class BudgetCycleView(BaseERPModelView):
	datamodel = SQLAInterface(BudgetCycle)

	list_title = "Budget Cycles"
	show_title = "Budget Cycle"
	add_title = "Create Budget Cycle"
	edit_title = "Edit Budget Cycle"

	list_columns = [
		"name",
		"fiscal_year",
		"cycle_type",
		"status",
		"input_deadline",
		"approval_deadline",
	]
	show_columns = [
		"id",
		"name",
		"fiscal_year",
		"cycle_type",
		"status",
		"input_deadline",
		"approval_deadline",
		"approved_by",
		"approved_at",
	]
	add_columns = [
		"tenant_id",
		"name",
		"fiscal_year",
		"cycle_type",
		"status",
		"input_deadline",
		"approval_deadline",
	]
	edit_columns = [
		"name",
		"fiscal_year",
		"cycle_type",
		"status",
		"input_deadline",
		"approval_deadline",
		"approved_by",
		"approved_at",
	]
	search_columns = ["name", "fiscal_year", "cycle_type", "status"]
	label_columns = {
		"id": "ID",
		"name": "Name",
		"fiscal_year": "Fiscal Year",
		"cycle_type": "Cycle Type",
		"status": "Status",
		"input_deadline": "Input Deadline",
		"approval_deadline": "Approval Deadline",
		"approved_by": "Approved By",
		"approved_at": "Approved At",
		"tenant_id": "Tenant",
	}


class ScenarioView(BaseERPModelView):
	datamodel = SQLAInterface(ScenarioModel)

	list_title = "Scenarios"
	show_title = "Scenario"
	add_title = "Create Scenario"
	edit_title = "Edit Scenario"

	list_columns = [
		"name",
		"scenario_type",
		"status",
		"base_version_id",
		"generated_version_id",
	]
	show_columns = [
		"id",
		"name",
		"base_version_id",
		"description",
		"scenario_type",
		"adjustment_rules",
		"status",
		"generated_version_id",
	]
	add_columns = [
		"tenant_id",
		"base_version_id",
		"name",
		"description",
		"scenario_type",
		"adjustment_rules",
		"status",
	]
	edit_columns = [
		"base_version_id",
		"name",
		"description",
		"scenario_type",
		"adjustment_rules",
		"status",
		"generated_version_id",
	]
	search_columns = ["name", "scenario_type", "status", "base_version_id", "generated_version_id"]
	label_columns = {
		"id": "ID",
		"name": "Name",
		"base_version_id": "Base Version",
		"description": "Description",
		"scenario_type": "Scenario Type",
		"adjustment_rules": "Adjustment Rules",
		"status": "Status",
		"generated_version_id": "Generated Version",
		"tenant_id": "Tenant",
	}


ScenarioModelView = ScenarioView

__all__ = [
	"FPADashboardView",
	"BudgetCycleView",
	"ScenarioView",
	"ScenarioModelView",
]
