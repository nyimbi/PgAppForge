from __future__ import annotations
from flask_babel import lazy_gettext as _

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
	label_columns = {"name": _("Name"), "journey_type": _("Journey Type"), "is_default": _("Is Default"), "is_active": _("Is Active")}
	show_columns = ["name", "journey_type", "is_default", "is_active", "description", "tasks", "metadata_", "created_at", "updated_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "journeys"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "journeys"]
	search_columns = ["name", "journey_type"]


class JourneyView(ModelView):
	datamodel = SQLAInterface(Journey)
	list_columns = ["employee_id", "journey_type", "status", "trigger_date", "completed_at"]
	label_columns = {"employee_id": _("Employee"), "journey_type": _("Journey Type"), "status": _("Status"), "trigger_date": _("Trigger Date"), "completed_at": _("Completed At")}
	show_columns = ["employee_id", "journey_type", "status", "trigger_date", "completed_at", "metadata_", "created_at", "updated_at", "template"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "tasks"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "tasks"]
	search_columns = ["employee_id", "journey_type", "status"]


class JourneyTaskView(ModelView):
	datamodel = SQLAInterface(JourneyTask)
	list_columns = ["task_code", "title", "category", "status", "due_date", "owner_role", "is_mandatory"]
	label_columns = {"task_code": _("Task Code"), "title": _("Title"), "category": _("Category"), "status": _("Status"), "due_date": _("Due Date"), "owner_role": _("Owner Role"), "is_mandatory": _("Is Mandatory")}
	show_columns = ["task_code", "title", "category", "status", "due_date", "owner_role", "is_mandatory", "depends_on", "completed_at", "notes", "metadata_", "created_at", "updated_at", "journey"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["task_code", "title", "status"]


class JourneysDashboardView(BaseERPView):
	route_base = "/hcm/journeys"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.journeys.models import (
				Journey,
				JourneyTask,
			)
			sess = self._session()
			active_journeys = self._count(Journey, session=sess, status="ACTIVE")
			pending_tasks = self._count(JourneyTask, session=sess, status="PENDING")
			in_progress_tasks = self._count(JourneyTask, session=sess, status="IN_PROGRESS")
		except Exception:
			active_journeys = pending_tasks = in_progress_tasks = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Journeys", "value": active_journeys, "icon": "fa-route", "color": "#1a56db"},
			{"label": "Pending Tasks", "value": pending_tasks, "icon": "fa-exclamation-triangle", "color": "#e02424"},
			{"label": "Tasks In Progress", "value": in_progress_tasks, "icon": "fa-check-circle", "color": "#0e9f6e"},
		])
		return render_template(
			"appbuilder/hcm_journeys/journey_tracker.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
