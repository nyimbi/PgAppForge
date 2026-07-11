from __future__ import annotations
from flask_babel import lazy_gettext as _

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.recruiting.models import (
	InterviewSchedule,
	JobApplication,
	JobRequisition,
	OfferLetter,
)

__all__ = [
	"JobRequisitionView",
	"JobApplicationView",
	"InterviewScheduleView",
	"OfferLetterView",
	"RecruitingDashboardView",
]


class JobRequisitionView(ModelView):
	datamodel = SQLAInterface(JobRequisition)
	list_columns = ["title", "department_id", "headcount", "employment_type", "status", "posted_at"]
	label_columns = {"title": _("Title"), "department_id": _("Department"), "headcount": _("Headcount"), "employment_type": _("Employment Type"), "status": _("Status"), "posted_at": _("Posted At")}
	show_columns = ["title", "department_id", "headcount", "employment_type", "status", "posted_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "applications"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "applications"]
	search_columns = ["title", "status", "entity_id"]


class JobApplicationView(ModelView):
	datamodel = SQLAInterface(JobApplication)
	list_columns = ["candidate_name", "candidate_email", "source", "status", "applied_at"]
	label_columns = {"candidate_name": _("Candidate Name"), "candidate_email": _("Candidate Email"), "source": _("Source"), "status": _("Status"), "applied_at": _("Applied At")}
	show_columns = ["candidate_name", "candidate_email", "source", "status", "applied_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "interviews", "offer"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "interviews", "offer"]
	search_columns = ["candidate_name", "candidate_email", "status"]


class InterviewScheduleView(ModelView):
	datamodel = SQLAInterface(InterviewSchedule)
	list_columns = ["application", "interviewer_id", "scheduled_at", "format", "rating", "recommendation"]
	label_columns = {"application": _("Application"), "interviewer_id": _("Interviewer"), "scheduled_at": _("Scheduled At"), "format": _("Format"), "rating": _("Rating"), "recommendation": _("Recommendation")}
	show_columns = ["application", "interviewer_id", "scheduled_at", "format", "rating", "recommendation"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["interviewer_id", "format"]


class OfferLetterView(ModelView):
	datamodel = SQLAInterface(OfferLetter)
	list_columns = ["application", "start_date", "status", "currency_code"]
	label_columns = {"application": _("Application"), "offered_salary_cents": _("Offered Salary (KES)"), "start_date": _("Start Date"), "status": _("Status"), "currency_code": _("Currency Code")}
	show_columns = ["application", "offered_salary_cents", "start_date", "status", "currency_code"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["status"]


class RecruitingDashboardView(BaseERPView):
	route_base = "/hcm/recruiting"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.recruiting.models import (
				JobApplication,
				JobRequisition,
				OfferLetter,
			)
			sess = self._session()
			open_reqs = self._count(JobRequisition, session=sess, status="OPEN")
			screening_apps = self._count(JobApplication, session=sess, status="SCREENING")
			pending_offers = self._count(OfferLetter, session=sess, status="SENT")
			total_apps = self._count(JobApplication, session=sess)
		except Exception:
			open_reqs = screening_apps = pending_offers = total_apps = 0
		kpi_html = self.kpi_cards([
			{"label": "Open Requisitions", "value": open_reqs, "icon": "fa-briefcase", "color": "#1a56db"},
			{"label": "Applications", "value": total_apps, "icon": "fa-file-alt", "color": "#0e9f6e"},
			{"label": "In Screening", "value": screening_apps, "icon": "fa-comments", "color": "#f59e0b"},
			{"label": "Pending Offers", "value": pending_offers, "icon": "fa-handshake", "color": "#7e3af2"},
		])
		return render_template(
			"appbuilder/hcm_rec_full/recruiting_full.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
