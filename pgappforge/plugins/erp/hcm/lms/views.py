from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.lms.models import (
	LmsCertificate,
	LmsCourse,
	LmsEnrollment,
)

__all__ = [
	"LmsCourseView",
	"LmsEnrollmentView",
	"LmsCertificateView",
	"LmsDashboardView",
]


class LmsCourseView(ModelView):
	datamodel = SQLAInterface(LmsCourse)
	list_columns = ["code", "title", "course_type", "status", "duration_minutes", "is_mandatory"]
	add_exclude_columns = ["id", "created_on", "changed_on", "lessons", "enrollments", "certificates"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "lessons", "enrollments", "certificates"]
	search_columns = ["code", "title", "course_type", "status"]


class LmsEnrollmentView(ModelView):
	datamodel = SQLAInterface(LmsEnrollment)
	list_columns = ["employee_id", "course", "status", "enrolled_at", "due_date", "passed"]
	add_exclude_columns = ["id", "created_on", "changed_on", "progress_rows", "certificate"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "progress_rows", "certificate"]
	search_columns = ["employee_id", "status"]


class LmsCertificateView(ModelView):
	datamodel = SQLAInterface(LmsCertificate)
	list_columns = ["employee_id", "course", "certificate_ref", "issued_at", "expires_at"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "certificate_ref"]


class LmsDashboardView(BaseERPView):
	route_base = "/hcm/lms"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Published Courses", "value": 0, "icon": "fa-book", "color": "#1a56db"},
			{"label": "Active Enrollments", "value": 0, "icon": "fa-user-graduate", "color": "#0e9f6e"},
			{"label": "Certificates Issued", "value": 0, "icon": "fa-certificate", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_lms/course_catalog.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
