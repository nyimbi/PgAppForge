from __future__ import annotations
from flask_babel import lazy_gettext as _

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
	label_columns = {"position_code": _("Position Code"), "title": _("Title"), "department_id": _("Department"), "grade_level": _("Grade Level"), "employment_type": _("Employment Type"), "status": _("Status"), "headcount_budget": _("Headcount Budget")}
	show_columns = ["position_code", "title", "department_id", "grade_level", "employment_type", "status", "headcount_budget"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["position_code", "title", "status", "entity_id"]


class HeadcountRequestView(ModelView):
	datamodel = SQLAInterface(HeadcountRequest)
	list_columns = ["entity_id", "request_year", "total_fte_requested", "total_fte_approved", "status", "submitted_by"]
	label_columns = {"entity_id": _("Legal Entity"), "request_year": _("Request Year"), "total_fte_requested": _("Total Fte Requested"), "total_fte_approved": _("Total Fte Approved"), "status": _("Status"), "submitted_by": _("Submitted By")}
	show_columns = ["request_year", "total_fte_requested", "total_fte_approved", "status", "submitted_by"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["entity_id", "status"]


class PositionManagementDashboardView(BaseERPView):
	route_base = "/hcm/positions"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.position_management.models import (
				HeadcountRequest,
				Position,
			)
			sess = self._session()
			total_positions = self._count(Position, session=sess)
			vacant_positions = self._count(Position, session=sess, status="VACANT")
			filled_positions = self._count(Position, session=sess, status="FILLED")
		except Exception:
			total_positions = vacant_positions = filled_positions = 0
		kpi_html = self.kpi_cards([
			{"label": "Total Positions", "value": total_positions, "icon": "fa-sitemap", "color": "#1a56db"},
			{"label": "Vacant", "value": vacant_positions, "icon": "fa-user-slash", "color": "#e02424"},
			{"label": "Filled", "value": filled_positions, "icon": "fa-user-check", "color": "#0e9f6e"},
		])
		return render_template(
			"appbuilder/hcm_positions/position_org_chart.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
