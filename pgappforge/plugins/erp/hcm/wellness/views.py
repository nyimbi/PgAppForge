from __future__ import annotations
from flask_babel import lazy_gettext as _

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.wellness.models import (
	WellnessCheckIn,
	WellnessEnrollment,
	WellnessProgram,
)

__all__ = [
	"WellnessProgramView",
	"WellnessEnrollmentView",
	"WellnessCheckInView",
	"WellnessDashboardView",
]


class WellnessProgramView(ModelView):
	datamodel = SQLAInterface(WellnessProgram)
	list_columns = ["name", "program_type", "status", "provider", "start_date", "is_voluntary"]
	label_columns = {"name": _("Name"), "program_type": _("Program Type"), "status": _("Status"), "provider": _("Provider"), "start_date": _("Start Date"), "is_voluntary": _("Is Voluntary")}
	show_columns = ["name", "program_type", "status", "provider", "start_date", "is_voluntary", "description", "end_date", "target_roles", "max_participants"]
	add_exclude_columns = ["id", "created_on", "changed_on", "enrollments"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "enrollments"]
	search_columns = ["name", "program_type", "status"]


class WellnessEnrollmentView(ModelView):
	datamodel = SQLAInterface(WellnessEnrollment)
	list_columns = ["employee_id", "program", "status", "enrolled_at", "completed_at"]
	label_columns = {"employee_id": _("Employee"), "program": _("Program"), "status": _("Status"), "enrolled_at": _("Enrolled At"), "completed_at": _("Completed At")}
	show_columns = ["employee_id", "program", "status", "enrolled_at", "completed_at"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "status"]


class WellnessCheckInView(ModelView):
	datamodel = SQLAInterface(WellnessCheckIn)
	list_columns = ["employee_id", "check_in_date", "wellbeing_score", "stress_level", "anonymous"]
	label_columns = {"employee_id": _("Employee"), "check_in_date": _("Check In Date"), "wellbeing_score": _("Wellbeing Score"), "stress_level": _("Stress Level"), "anonymous": _("Anonymous")}
	show_columns = ["employee_id", "check_in_date", "wellbeing_score", "stress_level", "anonymous", "energy_level", "flags", "notes"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id"]


class WellnessDashboardView(BaseERPView):
	route_base = "/hcm/wellness"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.wellness.models import (
				WellnessCheckIn,
				WellnessEnrollment,
				WellnessProgram,
			)
			sess = self._session()
			active_programs = self._count(WellnessProgram, session=sess, status="ACTIVE")
			active_enrollments = self._count(WellnessEnrollment, session=sess, status="ACTIVE")
			total_checkins = self._count(WellnessCheckIn, session=sess)
		except Exception:
			active_programs = active_enrollments = total_checkins = 0
		kpi_html = self.kpi_cards([
			{"label": "Active Programs", "value": active_programs, "icon": "fa-heartbeat", "color": "#1a56db"},
			{"label": "Active Enrollments", "value": active_enrollments, "icon": "fa-users", "color": "#0e9f6e"},
			{"label": "Check-Ins", "value": total_checkins, "icon": "fa-clipboard-check", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_wellness/wellness_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
