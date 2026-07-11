from __future__ import annotations
from flask_babel import lazy_gettext as _

from datetime import date

import sqlalchemy as sa
from flask import render_template_string
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.travel_expense.models import (
	CashAdvance as TravelRequest,
	ExpenseReport,
)

__all__ = [
	"TravelRequestView",
	"ExpenseReportView",
	"TravelExpenseDashboardView",
]


class TravelRequestView(ModelView):
	datamodel = SQLAInterface(TravelRequest)
	list_columns = ["employee_id", "request_date", "trip_purpose", "amount_cents", "currency_code", "status", "outstanding_cents"]
	label_columns = {"employee_id": _("Employee"), "request_date": _("Request Date"), "trip_purpose": _("Trip Purpose"), "amount_cents": _("Amount (KES)"), "currency_code": _("Currency Code"), "status": _("Status"), "outstanding_cents": _("Outstanding (KES)")}
	show_columns = ["employee_id", "request_date", "trip_purpose", "amount_cents", "currency_code", "status", "disbursed_at", "disbursement_ref", "outstanding_cents", "created_at", "updated_at", "linked_report"]
	add_exclude_columns = ["id", "tenant_id", "created_on", "changed_on", "created_at", "updated_at", "linked_report"]
	edit_exclude_columns = ["id", "tenant_id", "created_on", "changed_on", "created_at", "updated_at", "linked_report"]
	search_columns = ["employee_id", "trip_purpose", "currency_code", "status"]


class ExpenseReportView(ModelView):
	datamodel = SQLAInterface(ExpenseReport)
	list_columns = ["employee_id", "title", "destination", "trip_start", "trip_end", "total_claimed_cents", "status"]
	label_columns = {"employee_id": _("Employee"), "title": _("Title"), "destination": _("Destination"), "trip_start": _("Trip Start"), "trip_end": _("Trip End"), "total_claimed_cents": _("Total Claimed (KES)"), "status": _("Status")}
	show_columns = ["employee_id", "title", "trip_purpose", "destination", "trip_start", "trip_end", "currency_code", "total_claimed_cents", "total_approved_cents", "advance_received_cents", "reimbursement_due_cents", "status", "submitted_at", "approved_by", "approved_at", "paid_at", "payment_ref", "metadata_", "created_at", "updated_at"]
	add_exclude_columns = ["id", "tenant_id", "created_on", "changed_on", "created_at", "updated_at", "lines", "advances"]
	edit_exclude_columns = ["id", "tenant_id", "created_on", "changed_on", "created_at", "updated_at", "lines", "advances"]
	search_columns = ["employee_id", "title", "destination", "status", "payment_ref"]

	@expose('/submit-approval/<string:doc_id>', methods=['POST'])
	@has_access
	def submit_approval(self, doc_id):
		from pgappforge.plugins.erp.platform.approvals.views import object_amount_cents, submit_document_approval
		return submit_document_approval(
			document_type="expense_report",
			document_id=doc_id,
			document_model=ExpenseReport,
			session=self.datamodel.session,
			amount_getter=lambda doc: object_amount_cents(doc, "total_claimed_cents", "total_approved_cents"),
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


class TravelExpenseDashboardView(BaseERPView):
	route_base = "/hcm/travel-expense"

	@expose("/")
	@has_access
	def index(self):
		try:
			sess = self._session()
			today = date.today()
			month_start = today.replace(day=1)
			pending_approvals = sess.execute(
				sa.select(sa.func.count(ExpenseReport.id)).where(
					ExpenseReport.status.in_(["SUBMITTED", "UNDER_REVIEW"])
				)
			).scalar() or 0
			total_spend_mtd = sess.execute(
				sa.select(sa.func.coalesce(sa.func.sum(ExpenseReport.total_approved_cents), 0)).where(
					ExpenseReport.status.in_(["APPROVED", "PAID"]),
					ExpenseReport.trip_start >= month_start,
					ExpenseReport.trip_start <= today,
				)
			).scalar() or 0
			awaiting_reimbursement = sess.execute(
				sa.select(sa.func.count(ExpenseReport.id)).where(
					ExpenseReport.status == "APPROVED",
					ExpenseReport.reimbursement_due_cents > 0,
				)
			).scalar() or 0
		except Exception:
			pending_approvals = total_spend_mtd = awaiting_reimbursement = 0

		kpi_html = self.kpi_cards([
			{"label": "Pending Approvals", "value": pending_approvals, "format": "integer", "icon": "fa-clock", "color": "#f59e0b"},
			{"label": "Spend MTD", "value": total_spend_mtd / 100, "format": "currency", "icon": "fa-plane", "color": "#1a56db"},
			{"label": "Awaiting Reimbursement", "value": awaiting_reimbursement, "format": "integer", "icon": "fa-money-bill-wave", "color": "#0e9f6e"},
		])
		return render_template_string(
			"<h3>Travel & Expense Dashboard</h3>{{ kpi_html|safe }}",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
