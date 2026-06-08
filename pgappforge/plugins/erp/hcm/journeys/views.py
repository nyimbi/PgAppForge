from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.journeys.models import (
	Journey,
	JourneyTask,
	JourneyTemplate,
)

__all__ = [
	"JourneyTemplateView",
	"JourneyView",
	"JourneyTaskView",
	"JourneysDashboardView",
]


class JourneyTemplateView(ModelView):
	datamodel = SQLAInterface(JourneyTemplate)
	list_columns = ["name", "journey_type", "is_default", "is_active"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "journeys"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "journeys"]
	search_columns = ["name", "journey_type"]


class JourneyView(ModelView):
	datamodel = SQLAInterface(Journey)
	list_columns = ["employee_id", "journey_type", "status", "trigger_date", "completed_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "tasks"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "tasks"]
	search_columns = ["employee_id", "journey_type", "status"]


class JourneyTaskView(ModelView):
	datamodel = SQLAInterface(JourneyTask)
	list_columns = ["task_code", "title", "category", "status", "due_date", "owner_role", "is_mandatory"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["task_code", "title", "status"]


class JourneysDashboardView(BaseERPView):
	route_base = "/hcm/journeys"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Active Journeys", "value": 0, "icon": "fa-route", "color": "#1a56db"},
			{"label": "Overdue Tasks", "value": 0, "icon": "fa-exclamation-triangle", "color": "#e02424"},
			{"label": "Completed This Month", "value": 0, "icon": "fa-check-circle", "color": "#0e9f6e"},
		])
		return render_template(
			"appbuilder/hcm_journeys/journey_tracker.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
