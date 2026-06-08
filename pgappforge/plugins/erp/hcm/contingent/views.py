from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.contingent.models import (
	ContingentTimesheet,
	ContingentWorker,
	StatementOfWork,
)

__all__ = [
	"ContingentWorkerView",
	"StatementOfWorkView",
	"ContingentTimesheetView",
	"ContingentDashboardView",
]


class ContingentWorkerView(ModelView):
	datamodel = SQLAInterface(ContingentWorker)
	list_columns = ["first_name", "last_name", "worker_type", "rate_cents", "rate_unit", "status", "start_date"]
	add_exclude_columns = ["id", "created_on", "changed_on", "sows", "timesheets"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "sows", "timesheets"]
	search_columns = ["first_name", "last_name", "worker_type", "status"]


class StatementOfWorkView(ModelView):
	datamodel = SQLAInterface(StatementOfWork)
	list_columns = ["title", "worker", "budget_cents", "start_date", "end_date", "status"]
	add_exclude_columns = ["id", "created_on", "changed_on", "timesheets"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "timesheets"]
	search_columns = ["title", "status"]


class ContingentTimesheetView(ModelView):
	datamodel = SQLAInterface(ContingentTimesheet)
	list_columns = ["worker", "period", "hours", "amount_cents", "status", "approved_by"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["period", "status"]


class ContingentDashboardView(BaseERPView):
	route_base = "/hcm/contingent"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Workers", "value": 0, "icon": "fa-user-tie", "color": "#1a56db"},
			{"label": "Open SOWs", "value": 0, "icon": "fa-file-contract", "color": "#0e9f6e"},
			{"label": "Pending Timesheets", "value": 0, "icon": "fa-clock", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_contingent/contingent_workforce.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
