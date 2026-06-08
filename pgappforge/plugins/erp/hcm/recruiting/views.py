from __future__ import annotations

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
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "applications"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "applications"]
	search_columns = ["title", "status", "entity_id"]


class JobApplicationView(ModelView):
	datamodel = SQLAInterface(JobApplication)
	list_columns = ["candidate_name", "candidate_email", "source", "status", "applied_at"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "interviews", "offer"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at", "interviews", "offer"]
	search_columns = ["candidate_name", "candidate_email", "status"]


class InterviewScheduleView(ModelView):
	datamodel = SQLAInterface(InterviewSchedule)
	list_columns = ["application", "interviewer_id", "scheduled_at", "format", "rating", "recommendation"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["interviewer_id", "format"]


class OfferLetterView(ModelView):
	datamodel = SQLAInterface(OfferLetter)
	list_columns = ["application", "offered_salary_cents", "start_date", "status", "currency_code"]
	add_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "created_at", "updated_at"]
	search_columns = ["status"]


class RecruitingDashboardView(BaseERPView):
	route_base = "/hcm/recruiting"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Open Requisitions", "value": 0, "icon": "fa-briefcase", "color": "#1a56db"},
			{"label": "Applications", "value": 0, "icon": "fa-file-alt", "color": "#0e9f6e"},
			{"label": "Interviews This Week", "value": 0, "icon": "fa-comments", "color": "#f59e0b"},
			{"label": "Pending Offers", "value": 0, "icon": "fa-handshake", "color": "#7e3af2"},
		])
		return render_template(
			"appbuilder/hcm_rec_full/recruiting_full.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
