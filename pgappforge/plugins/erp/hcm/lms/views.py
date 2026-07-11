from __future__ import annotations
from flask_babel import lazy_gettext as _

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
	label_columns = {"code": _("Code"), "title": _("Title"), "course_type": _("Course Type"), "status": _("Status"), "duration_minutes": _("Duration Minutes"), "is_mandatory": _("Is Mandatory")}
	show_columns = ["code", "title", "course_type", "status", "duration_minutes", "is_mandatory", "description", "passing_score", "max_attempts", "mandatory_roles", "due_days", "content_url", "scorm_manifest", "thumbnail_url", "tags", "created_by", "published_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "lessons", "enrollments", "certificates"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "lessons", "enrollments", "certificates"]
	search_columns = ["code", "title", "course_type", "status"]


class LmsEnrollmentView(ModelView):
	datamodel = SQLAInterface(LmsEnrollment)
	list_columns = ["employee_id", "course", "status", "enrolled_at", "due_date", "passed"]
	label_columns = {"employee_id": _("Employee"), "course": _("Course"), "status": _("Status"), "enrolled_at": _("Enrolled At"), "due_date": _("Due Date"), "passed": _("Passed")}
	show_columns = ["employee_id", "course", "status", "enrolled_at", "due_date", "passed", "completed_at", "final_score", "attempt_number", "assigned_by", "certificate"]
	add_exclude_columns = ["id", "created_on", "changed_on", "progress_rows", "certificate"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "progress_rows", "certificate"]
	search_columns = ["employee_id", "status"]


class LmsCertificateView(ModelView):
	datamodel = SQLAInterface(LmsCertificate)
	list_columns = ["employee_id", "course", "certificate_ref", "issued_at", "expires_at"]
	label_columns = {"employee_id": _("Employee"), "course": _("Course"), "certificate_ref": _("Certificate Ref"), "issued_at": _("Issued At"), "expires_at": _("Expires At")}
	show_columns = ["employee_id", "course", "certificate_ref", "issued_at", "expires_at", "credential_url", "enrollment"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "certificate_ref"]


class LmsDashboardView(BaseERPView):
	route_base = "/hcm/lms"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.lms.models import (
				LmsCertificate,
				LmsCourse,
				LmsEnrollment,
			)
			sess = self._session()
			published_courses = self._count(LmsCourse, session=sess, status="PUBLISHED")
			active_enrollments = self._count(LmsEnrollment, session=sess, status="IN_PROGRESS")
			certificates_issued = self._count(LmsCertificate, session=sess)
		except Exception:
			published_courses = active_enrollments = certificates_issued = 0
		kpi_html = self.kpi_cards([
			{"label": "Published Courses", "value": published_courses, "icon": "fa-book", "color": "#1a56db"},
			{"label": "Active Enrollments", "value": active_enrollments, "icon": "fa-user-graduate", "color": "#0e9f6e"},
			{"label": "Certificates Issued", "value": certificates_issued, "icon": "fa-certificate", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_lms/course_catalog.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
