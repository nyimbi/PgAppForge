from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.position_management.models import (
	HeadcountRequest,
	Position,
)

__all__ = [
	"PositionView",
	"HeadcountRequestView",
	"PositionManagementDashboardView",
]


class PositionView(ModelView):
	datamodel = SQLAInterface(Position)
	list_columns = ["position_code", "title", "department_id", "grade_level", "employment_type", "status", "headcount_budget"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["position_code", "title", "status", "entity_id"]


class HeadcountRequestView(ModelView):
	datamodel = SQLAInterface(HeadcountRequest)
	list_columns = ["entity_id", "request_year", "total_fte_requested", "total_fte_approved", "status", "submitted_by"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["entity_id", "status"]


class PositionManagementDashboardView(BaseERPView):
	route_base = "/hcm/positions"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Total Positions", "value": 0, "icon": "fa-sitemap", "color": "#1a56db"},
			{"label": "Vacant", "value": 0, "icon": "fa-user-slash", "color": "#e02424"},
			{"label": "Filled", "value": 0, "icon": "fa-user-check", "color": "#0e9f6e"},
		])
		return render_template(
			"appbuilder/hcm_positions/position_org_chart.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
