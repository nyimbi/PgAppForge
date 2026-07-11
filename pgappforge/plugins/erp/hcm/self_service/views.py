from __future__ import annotations
from flask_babel import lazy_gettext as _

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.self_service.models import (
	Announcement,
	LeaveBalance,
	LeaveRequest,
)

__all__ = [
	"LeaveRequestView",
	"LeaveBalanceView",
	"AnnouncementView",
	"SelfServiceDashboardView",
]


class LeaveRequestView(ModelView):
	datamodel = SQLAInterface(LeaveRequest)
	list_columns = ["employee_id", "leave_type", "start_date", "end_date", "days_requested", "status"]
	label_columns = {"employee_id": _("Employee"), "leave_type": _("Leave Type"), "start_date": _("Start Date"), "end_date": _("End Date"), "days_requested": _("Days Requested"), "status": _("Status")}
	show_columns = ["employee_id", "leave_type", "start_date", "end_date", "days_requested", "status"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "leave_type", "status"]

	@expose('/submit-approval/<string:doc_id>', methods=['POST'])
	@has_access
	def submit_approval(self, doc_id):
		from pgappforge.plugins.erp.platform.approvals.views import submit_document_approval
		return submit_document_approval(
			document_type="leave_request",
			document_id=doc_id,
			document_model=LeaveRequest,
			session=self.datamodel.session,
			amount_getter=lambda doc: 0,
			requester_getter=lambda doc: str(getattr(doc, "employee_id", "")),
		)

	@expose('/approve/<string:request_id>', methods=['POST'])
	@has_access
	def approve(self, request_id):
		from pgappforge.plugins.erp.platform.approvals.views import approve_document_approval
		return approve_document_approval(request_id, self.datamodel.session)

	@expose('/reject/<string:request_id>', methods=['POST'])
	@has_access
	def reject(self, request_id):
		from pgappforge.plugins.erp.platform.approvals.views import reject_document_approval
		return reject_document_approval(request_id, self.datamodel.session)


class LeaveBalanceView(ModelView):
	datamodel = SQLAInterface(LeaveBalance)
	list_columns = ["employee_id", "leave_type", "year", "entitled_days", "used_days", "balance_days"]
	label_columns = {"employee_id": _("Employee"), "leave_type": _("Leave Type"), "year": _("Year"), "entitled_days": _("Entitled Days"), "used_days": _("Used Days"), "balance_days": _("Balance Days")}
	show_columns = ["employee_id", "leave_type", "year", "entitled_days", "used_days", "balance_days"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "leave_type"]


class AnnouncementView(ModelView):
	datamodel = SQLAInterface(Announcement)
	list_columns = ["title", "priority", "is_pinned", "published_at", "expires_at"]
	label_columns = {"title": _("Title"), "priority": _("Priority"), "is_pinned": _("Is Pinned"), "published_at": _("Published At"), "expires_at": _("Expires At")}
	show_columns = ["title", "priority", "is_pinned", "published_at", "expires_at"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["title", "priority"]


class SelfServiceDashboardView(BaseERPView):
	route_base = "/hcm/ess"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.self_service.models import (
				Announcement,
				LeaveRequest,
			)
			sess = self._session()
			pending_leaves = self._count(LeaveRequest, session=sess, status="PENDING")
			announcements = self._count(Announcement, session=sess)
		except Exception:
			pending_leaves = announcements = 0
		kpi_html = self.kpi_cards([
			{"label": "Pending Leaves", "value": pending_leaves, "icon": "fa-calendar-times", "color": "#f59e0b"},
			{"label": "Announcements", "value": announcements, "icon": "fa-bullhorn", "color": "#1a56db"},
		])
		return render_template(
			"appbuilder/hcm_ess/employee_portal.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
