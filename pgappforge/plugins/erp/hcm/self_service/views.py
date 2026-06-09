from __future__ import annotations

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
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "leave_type", "status"]


class LeaveBalanceView(ModelView):
	datamodel = SQLAInterface(LeaveBalance)
	list_columns = ["employee_id", "leave_type", "year", "entitled_days", "used_days", "balance_days"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id", "leave_type"]


class AnnouncementView(ModelView):
	datamodel = SQLAInterface(Announcement)
	list_columns = ["title", "priority", "is_pinned", "published_at", "expires_at"]
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
