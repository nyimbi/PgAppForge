from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.workforce_planning.models import (
	PlannedPosition,
	WorkforcePlan,
)

__all__ = [
	"WorkforcePlanView",
	"PlannedPositionView",
	"WorkforcePlanningDashboardView",
]


class WorkforcePlanView(ModelView):
	datamodel = SQLAInterface(WorkforcePlan)
	list_columns = ["name", "entity_id", "plan_year", "status", "total_planned_fte", "total_budget_cents"]
	add_exclude_columns = ["id", "created_on", "changed_on", "positions", "scenarios"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "positions", "scenarios"]
	search_columns = ["name", "entity_id", "status"]


class PlannedPositionView(ModelView):
	datamodel = SQLAInterface(PlannedPosition)
	list_columns = ["position_code", "position_title", "department", "planned_fte", "headcount_change_type", "approval_status"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["position_code", "position_title", "headcount_change_type"]


class WorkforcePlanningDashboardView(BaseERPView):
	route_base = "/hcm/workforce-planning"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Plans", "value": 0, "icon": "fa-project-diagram", "color": "#1a56db"},
			{"label": "Planned FTE", "value": 0, "icon": "fa-users", "color": "#0e9f6e"},
			{"label": "Budget (KES)", "value": 0, "format": "currency", "icon": "fa-coins", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_workforce/workforce_planning.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
