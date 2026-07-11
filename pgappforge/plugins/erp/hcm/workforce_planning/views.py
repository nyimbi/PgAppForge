from __future__ import annotations
from flask_babel import lazy_gettext as _

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
	label_columns = {"name": _("Name"), "entity_id": _("Legal Entity"), "plan_year": _("Plan Year"), "status": _("Status"), "total_planned_fte": _("Total Planned Fte"), "total_budget_cents": _("Total Budget (KES)")}
	show_columns = ["name", "plan_year", "status", "total_planned_fte", "total_budget_cents", "approved_by", "approved_at", "gl_cost_center", "metadata_"]
	add_exclude_columns = ["id", "created_on", "changed_on", "positions", "scenarios"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "positions", "scenarios"]
	search_columns = ["name", "entity_id", "status"]


class PlannedPositionView(ModelView):
	datamodel = SQLAInterface(PlannedPosition)
	list_columns = ["position_code", "position_title", "department", "planned_fte", "headcount_change_type", "approval_status"]
	label_columns = {"position_code": _("Position Code"), "position_title": _("Position Title"), "department": _("Department"), "planned_fte": _("Planned Fte"), "headcount_change_type": _("Headcount Change Type"), "approval_status": _("Approval Status")}
	show_columns = ["position_code", "position_title", "department", "planned_fte", "headcount_change_type", "approval_status", "grade_level", "annual_base_cost_cents", "total_annual_cost_cents", "planned_start_date", "notes", "plan"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["position_code", "position_title", "headcount_change_type"]


class WorkforcePlanningDashboardView(BaseERPView):
	route_base = "/hcm/workforce-planning"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.workforce_planning.models import (
				PlannedPosition,
				WorkforcePlan,
			)
			sess = self._session()
			active_plans = self._count(WorkforcePlan, session=sess, status="APPROVED")
			submitted_plans = self._count(WorkforcePlan, session=sess, status="SUBMITTED")
			pending_positions = self._count(PlannedPosition, session=sess, approval_status="PENDING")
		except Exception:
			active_plans = submitted_plans = pending_positions = 0
		kpi_html = self.kpi_cards([
			{"label": "Approved Plans", "value": active_plans, "icon": "fa-project-diagram", "color": "#1a56db"},
			{"label": "Submitted Plans", "value": submitted_plans, "icon": "fa-users", "color": "#0e9f6e"},
			{"label": "Positions Pending Approval", "value": pending_positions, "icon": "fa-coins", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_workforce/workforce_planning.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
