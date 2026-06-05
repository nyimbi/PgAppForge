"""
pgappforge/plugins/fintech/lending/views.py

FAB views for the Lending plugin.

Views:
  LoanApplicationView     — LOS list/detail + Submit/CreditCheck/Approve/Reject/Disburse
  LoanView                — LMS list/detail + Repayment/Restructure/WriteOff/Statement
  RepaymentScheduleView   — Readonly installment schedule for a loan
  LoanPortfolioDashboard  — PAR / NPA / provision KPIs with charts
  CreditScorecardView     — Application scorecard summary
  CollectionsDashboard    — Overdue bucket view for collections team
"""
from __future__ import annotations

import logging
from flask import flash, redirect, request, url_for
from flask_appbuilder import BaseView, ModelView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	date_widget,
	datetime_widget,
	rich_text_widget,
	chart_widget,
	select2_widget,
	select2_ajax_widget,
	star_widget,
	progress_widget,
	json_widget,
)
from pgappforge.plugins.fintech.lending.models import (
	LoanApplication,
	LoanProduct,
	Collateral,
	Loan,
	RepaymentSchedule,
	LoanRepayment,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LoanApplicationView
# ---------------------------------------------------------------------------

class LoanApplicationView(ModelView):
	"""Loan origination — application list with LOS workflow actions."""

	datamodel = SQLAInterface(LoanApplication)

	list_title = "Loan Applications"
	show_title = "Application Detail"
	edit_title = "Edit Application"
	add_title = "New Application"

	list_columns = [
		"application_number",
		"applicant_id",
		"product_id",
		"requested_amount_cents",
		"status",
		"submitted_at",
		"credit_score",
	]

	label_columns = {
		"application_number": "Application #",
		"applicant_id": "Applicant",
		"product_id": "Product",
		"requested_amount_cents": "Requested Amount",
		"approved_amount_cents": "Approved Amount",
		"status": "Status",
		"submitted_at": "Submitted",
		"credit_checked_at": "Credit Checked",
		"decision_at": "Decision Date",
		"credit_score": "Credit Score",
		"dti_ratio": "DTI Ratio",
		"ltv_ratio": "LTV Ratio",
		"internal_notes": "Internal Notes",
		"conditions": "Conditions",
		"documents_checklist": "Documents",
		"rejection_reason": "Rejection Reason",
	}

	show_fieldsets = [
		("Application", {
			"fields": [
				"application_number",
				"applicant_id",
				"co_applicant_id",
				"product_id",
				"channel",
				"status",
			],
		}),
		("Requested Terms", {
			"fields": [
				"requested_amount_cents",
				"requested_tenor_months",
				"purpose",
			],
		}),
		("Credit Assessment", {
			"fields": [
				"credit_score",
				"dti_ratio",
				"ltv_ratio",
				"credit_checked_at",
			],
		}),
		("Approved Terms", {
			"fields": [
				"approved_amount_cents",
				"approved_tenor_months",
				"approved_rate_pa",
				"conditions",
				"decision_at",
			],
		}),
		("Notes & Documents", {
			"fields": [
				"internal_notes",
				"documents_checklist",
				"rejection_reason",
			],
		}),
	]

	add_fieldsets = [
		("Application", {
			"fields": [
				"applicant_id",
				"product_id",
				"requested_amount_cents",
				"requested_tenor_months",
				"purpose",
				"channel",
			],
		}),
	]

	edit_fieldsets = [
		("Application", {
			"fields": [
				"status",
				"internal_notes",
				"documents_checklist",
				"conditions",
			],
		}),
	]

	# Widgets
	formatters_columns = {
		"requested_amount_cents": currency_widget("KES"),
		"approved_amount_cents": currency_widget("KES"),
		"submitted_at": datetime_widget(),
		"decision_at": datetime_widget(),
		"credit_checked_at": datetime_widget(),
		"internal_notes": rich_text_widget(height=200),
		"documents_checklist": json_widget(mode="tree", readonly=False),
		"conditions": json_widget(mode="view", readonly=True),
		"applicant_id": select2_ajax_widget(min_chars=2),
		# credit_score rendered as star out of 100 (1000 score scale / 10)
		"credit_score": star_widget(max_rating=10, readonly=True),
	}

	search_columns = [
		"application_number",
		"status",
		"channel",
	]

	base_order = ("submitted_at", "desc")

	# Custom action: Submit
	@expose("/submit/<int:pk>", methods=["POST"])
	def submit_action(self, pk: int):
		"""Transition application from DRAFT → SUBMITTED."""
		try:
			from datetime import datetime, timezone
			from flask_appbuilder import current_app
			app_obj = self.datamodel.get(pk)
			if app_obj is None:
				flash("Application not found", "danger")
				return redirect(url_for(".list"))
			app_obj.status = "SUBMITTED"
			app_obj.submitted_at = datetime.now(timezone.utc)
			self.datamodel.session.flush()
			self.datamodel.session.commit()

			from pgappforge.plugins.erp.foundation.commons import emit_event
			try:
				emit_event(
					"ln.application.submitted",
					"LoanApplication",
					str(app_obj.id),
					{
						"application_number": app_obj.application_number,
						"applicant_id": app_obj.applicant_id,
						"requested_amount_cents": app_obj.requested_amount_cents,
						"channel": app_obj.channel,
					},
					self.datamodel.session,
					tenant_id=app_obj.tenant_id,
				)
				self.datamodel.session.commit()
			except Exception:
				pass

			flash(f"Application {app_obj.application_number} submitted", "success")
		except Exception as exc:
			log.exception("submit_action failed")
			flash(str(exc), "danger")
		return redirect(url_for(".list"))

	# Custom action: Credit Check
	@expose("/credit_check/<int:pk>", methods=["POST"])
	def credit_check_action(self, pk: int):
		"""Run automated credit check on a submitted application."""
		try:
			from pgappforge.plugins.fintech.lending.services import LoanOriginationService
			app_obj = self.datamodel.get(pk)
			if app_obj is None:
				flash("Application not found", "danger")
				return redirect(url_for(".list"))
			svc = LoanOriginationService()
			result = svc.run_credit_check(self.datamodel.session, str(app_obj.id))
			self.datamodel.session.commit()
			flash(
				f"Credit check complete. Score={result['score']}, Recommendation={result['recommendation']}",
				"info",
			)
		except Exception as exc:
			log.exception("credit_check_action failed")
			flash(str(exc), "danger")
		return redirect(url_for(".list"))

	# Custom action: Approve
	@expose("/approve/<int:pk>", methods=["POST"])
	def approve_action(self, pk: int):
		"""Approve a loan application with terms from form data."""
		try:
			from decimal import Decimal
			from flask_login import current_user
			from pgappforge.plugins.fintech.lending.services import LoanOriginationService

			app_obj = self.datamodel.get(pk)
			if app_obj is None:
				flash("Application not found", "danger")
				return redirect(url_for(".list"))

			approved_amount = int(request.form.get("approved_amount_cents", app_obj.requested_amount_cents))
			approved_tenor = int(request.form.get("approved_tenor_months", app_obj.requested_tenor_months))
			approved_rate = Decimal(request.form.get("approved_rate_pa", "0.14"))
			approver_id = str(getattr(current_user, "id", "system"))

			svc = LoanOriginationService()
			svc.approve(
				self.datamodel.session,
				str(app_obj.id),
				approver_id,
				approved_amount,
				approved_tenor,
				approved_rate,
			)
			self.datamodel.session.commit()
			flash(f"Application {app_obj.application_number} approved", "success")
		except Exception as exc:
			log.exception("approve_action failed")
			flash(str(exc), "danger")
		return redirect(url_for(".list"))

	# Custom action: Reject
	@expose("/reject/<int:pk>", methods=["POST"])
	def reject_action(self, pk: int):
		"""Reject a loan application."""
		try:
			from flask_login import current_user
			from pgappforge.plugins.fintech.lending.services import LoanOriginationService

			app_obj = self.datamodel.get(pk)
			if app_obj is None:
				flash("Application not found", "danger")
				return redirect(url_for(".list"))

			reason = request.form.get("rejection_reason", "Does not meet credit criteria")
			decision_by = str(getattr(current_user, "id", "system"))

			svc = LoanOriginationService()
			svc.reject(self.datamodel.session, str(app_obj.id), reason, decision_by)
			self.datamodel.session.commit()
			flash(f"Application {app_obj.application_number} rejected", "warning")
		except Exception as exc:
			log.exception("reject_action failed")
			flash(str(exc), "danger")
		return redirect(url_for(".list"))

	# Custom action: Disburse
	@expose("/disburse/<int:pk>", methods=["POST"])
	def disburse_action(self, pk: int):
		"""Disburse an approved loan."""
		try:
			from pgappforge.plugins.fintech.lending.services import LoanOriginationService

			app_obj = self.datamodel.get(pk)
			if app_obj is None:
				flash("Application not found", "danger")
				return redirect(url_for(".list"))

			disbursement_account_id = request.form.get("disbursement_account_id", "")
			if not disbursement_account_id:
				flash("Disbursement account ID is required", "danger")
				return redirect(url_for(".list"))

			svc = LoanOriginationService()
			loan = svc.disburse(self.datamodel.session, str(app_obj.id), disbursement_account_id)
			self.datamodel.session.commit()
			flash(f"Loan {loan.loan_number} disbursed successfully", "success")
		except Exception as exc:
			log.exception("disburse_action failed")
			flash(str(exc), "danger")
		return redirect(url_for(".list"))


# ---------------------------------------------------------------------------
# LoanView
# ---------------------------------------------------------------------------

class LoanView(ModelView):
	"""Loan management — active portfolio view with LMS actions."""

	datamodel = SQLAInterface(Loan)

	list_title = "Loan Portfolio"
	show_title = "Loan Detail"

	list_columns = [
		"loan_number",
		"borrower_id",
		"product_id",
		"outstanding_principal_cents",
		"days_past_due",
		"npa_classification",
		"status",
		"maturity_date",
	]

	label_columns = {
		"loan_number": "Loan #",
		"borrower_id": "Borrower",
		"product_id": "Product",
		"outstanding_principal_cents": "Outstanding",
		"days_past_due": "DPD",
		"npa_classification": "Classification",
		"status": "Status",
		"maturity_date": "Maturity",
		"principal_cents": "Principal",
		"interest_rate_pa": "Rate p.a.",
		"tenor_months": "Tenor",
		"disbursement_date": "Disbursement",
		"arrears_principal_cents": "Arrears (Principal)",
		"arrears_interest_cents": "Arrears (Interest)",
		"penalty_cents": "Penalty",
		"provision_rate_pct": "Provision Rate",
		"provision_amount_cents": "Provision Amount",
		"next_installment_date": "Next Installment",
		"next_installment_amount_cents": "Next Installment Amount",
	}

	show_fieldsets = [
		("Loan Details", {
			"fields": [
				"loan_number",
				"borrower_id",
				"product_id",
				"status",
				"disbursement_date",
				"maturity_date",
			],
		}),
		("Balances", {
			"fields": [
				"principal_cents",
				"outstanding_principal_cents",
				"outstanding_interest_cents",
				"accrued_interest_cents",
				"penalty_cents",
			],
		}),
		("Arrears & Risk", {
			"fields": [
				"days_past_due",
				"arrears_principal_cents",
				"arrears_interest_cents",
				"npa_classification",
				"provision_rate_pct",
				"provision_amount_cents",
			],
		}),
		("Next Payment", {
			"fields": [
				"next_installment_date",
				"next_installment_amount_cents",
				"last_repayment_date",
				"last_repayment_amount_cents",
			],
		}),
	]

	formatters_columns = {
		"principal_cents": currency_widget("KES"),
		"outstanding_principal_cents": currency_widget("KES"),
		"outstanding_interest_cents": currency_widget("KES"),
		"accrued_interest_cents": currency_widget("KES"),
		"arrears_principal_cents": currency_widget("KES"),
		"arrears_interest_cents": currency_widget("KES"),
		"penalty_cents": currency_widget("KES"),
		"provision_amount_cents": currency_widget("KES"),
		"next_installment_amount_cents": currency_widget("KES"),
		"last_repayment_amount_cents": currency_widget("KES"),
		"disbursement_date": date_widget(),
		"maturity_date": date_widget(),
		"next_installment_date": date_widget(),
		"last_repayment_date": date_widget(),
		# DPD as range slider (0-720 days)
		"days_past_due": progress_widget(max_value=720),
		"npa_classification": select2_widget(
			choices=[
				("PERFORMING", "Performing"),
				("WATCH", "Watch"),
				("SUBSTANDARD", "Substandard"),
				("DOUBTFUL", "Doubtful"),
				("LOSS", "Loss"),
			]
		),
	}

	search_columns = ["loan_number", "status", "npa_classification"]
	base_order = ("days_past_due", "desc")

	# Custom action: Apply Repayment
	@expose("/repay/<int:pk>", methods=["POST"])
	def repay_action(self, pk: int):
		"""Apply a repayment to a loan."""
		try:
			from pgappforge.plugins.fintech.lending.services import LoanManagementService

			loan = self.datamodel.get(pk)
			if loan is None:
				flash("Loan not found", "danger")
				return redirect(url_for(".list"))

			amount_cents = int(request.form.get("amount_cents", 0))
			source = request.form.get("source", "BRANCH")
			reference = request.form.get("reference", "")

			if amount_cents <= 0:
				flash("Amount must be positive", "danger")
				return redirect(url_for(".list"))

			svc = LoanManagementService()
			result = svc.apply_repayment(
				self.datamodel.session,
				str(loan.id),
				amount_cents,
				source,
				reference or None,
			)
			self.datamodel.session.commit()
			flash(
				f"Repayment applied. Principal={result['applied_to_principal']}, "
				f"Interest={result['applied_to_interest']}, "
				f"Remaining={result['remaining_balance_cents']} cents",
				"success",
			)
		except Exception as exc:
			log.exception("repay_action failed")
			flash(str(exc), "danger")
		return redirect(url_for(".list"))

	# Custom action: Restructure
	@expose("/restructure/<int:pk>", methods=["POST"])
	def restructure_action(self, pk: int):
		"""Restructure a loan into new terms."""
		try:
			from decimal import Decimal
			from pgappforge.plugins.fintech.lending.services import LoanManagementService

			loan = self.datamodel.get(pk)
			if loan is None:
				flash("Loan not found", "danger")
				return redirect(url_for(".list"))

			new_tenor = int(request.form.get("new_tenor_months", 12))
			new_rate = Decimal(request.form.get("new_rate_pa", "0.14"))
			reason = request.form.get("reason", "Customer restructuring request")

			svc = LoanManagementService()
			new_loan = svc.restructure_loan(
				self.datamodel.session,
				str(loan.id),
				new_tenor,
				new_rate,
				reason,
			)
			self.datamodel.session.commit()
			flash(f"Loan restructured → new loan {new_loan.loan_number}", "success")
		except Exception as exc:
			log.exception("restructure_action failed")
			flash(str(exc), "danger")
		return redirect(url_for(".list"))

	# Custom action: Write-off
	@expose("/write_off/<int:pk>", methods=["POST"])
	def write_off_action(self, pk: int):
		"""Write off a loan."""
		try:
			from pgappforge.plugins.fintech.lending.services import LoanManagementService

			loan = self.datamodel.get(pk)
			if loan is None:
				flash("Loan not found", "danger")
				return redirect(url_for(".list"))

			reason = request.form.get("reason", "Unrecoverable bad debt")
			svc = LoanManagementService()
			svc.write_off(self.datamodel.session, str(loan.id), reason)
			self.datamodel.session.commit()
			flash(f"Loan {loan.loan_number} written off", "warning")
		except Exception as exc:
			log.exception("write_off_action failed")
			flash(str(exc), "danger")
		return redirect(url_for(".list"))

	# Custom action: Generate Statement (stub — returns JSON for now)
	@expose("/statement/<int:pk>", methods=["GET"])
	def statement_action(self, pk: int):
		"""Return a basic loan statement (JSON)."""
		from flask import jsonify
		try:
			loan = self.datamodel.get(pk)
			if loan is None:
				return jsonify({"error": "Loan not found"}), 404
			statement = {
				"loan_number": loan.loan_number,
				"borrower_id": loan.borrower_id,
				"principal_cents": loan.principal_cents,
				"outstanding_principal_cents": loan.outstanding_principal_cents,
				"outstanding_interest_cents": loan.outstanding_interest_cents,
				"penalty_cents": loan.penalty_cents,
				"days_past_due": loan.days_past_due,
				"npa_classification": loan.npa_classification,
				"status": loan.status,
				"disbursement_date": str(loan.disbursement_date),
				"maturity_date": str(loan.maturity_date),
			}
			return jsonify(statement)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# RepaymentScheduleView
# ---------------------------------------------------------------------------

class RepaymentScheduleView(ModelView):
	"""Readonly amortisation schedule for a loan."""

	datamodel = SQLAInterface(RepaymentSchedule)

	list_title = "Repayment Schedule"
	list_columns = [
		"installment_number",
		"due_date",
		"principal_due_cents",
		"interest_due_cents",
		"total_due_cents",
		"paid_total_cents",
		"status",
	]

	label_columns = {
		"installment_number": "Installment #",
		"due_date": "Due Date",
		"principal_due_cents": "Principal Due",
		"interest_due_cents": "Interest Due",
		"insurance_due_cents": "Insurance Due",
		"total_due_cents": "Total Due",
		"paid_total_cents": "Total Paid",
		"paid_date": "Paid Date",
		"status": "Status",
		"opening_principal_cents": "Opening Balance",
		"closing_principal_cents": "Closing Balance",
	}

	formatters_columns = {
		"due_date": date_widget(),
		"paid_date": date_widget(),
		"principal_due_cents": currency_widget("KES"),
		"interest_due_cents": currency_widget("KES"),
		"insurance_due_cents": currency_widget("KES"),
		"total_due_cents": currency_widget("KES"),
		"paid_total_cents": currency_widget("KES"),
		"opening_principal_cents": currency_widget("KES"),
		"closing_principal_cents": currency_widget("KES"),
	}

	base_order = ("installment_number", "asc")

	# Readonly — no add/edit/delete
	can_add = False
	can_edit = False
	can_delete = False


# ---------------------------------------------------------------------------
# LoanPortfolioDashboard
# ---------------------------------------------------------------------------

class LoanPortfolioDashboard(BaseView):
	"""Portfolio KPI dashboard — PAR, NPA, provision coverage, vintage analysis."""

	route_base = "/lending/portfolio"
	default_view = "index"

	@expose("/")
	def index(self):
		"""Render portfolio KPIs."""
		from datetime import date
		from flask_appbuilder import current_app
		from pgappforge.plugins.fintech.lending.services import LoanManagementService

		try:
			from flask_appbuilder.security.sqla.models import db
			session = db.session
		except ImportError:
			return self.render_template("lending/portfolio_dashboard.html", kpis={}, error="DB unavailable")

		svc = LoanManagementService()
		try:
			kpis = svc.get_par_report(session, as_of_date=date.today())
		except Exception as exc:
			log.exception("Portfolio dashboard failed")
			kpis = {"error": str(exc)}

		# Build aging buckets for chart
		aging_chart = chart_widget("bar")
		outstanding_trend_chart = chart_widget("area")

		return self.render_template(
			"lending/portfolio_dashboard.html",
			kpis=kpis,
			aging_chart=aging_chart,
			outstanding_trend_chart=outstanding_trend_chart,
		)


# ---------------------------------------------------------------------------
# CreditScorecardView
# ---------------------------------------------------------------------------

class CreditScorecardView(BaseView):
	"""Application-level credit scorecard — weighted factor breakdown."""

	route_base = "/lending/scorecard"
	default_view = "index"

	@expose("/")
	@expose("/<string:application_id>")
	def index(self, application_id: str | None = None):
		"""Render scorecard for an application or aggregate view."""
		scorecard_data: dict = {}

		if application_id:
			try:
				from flask_appbuilder.security.sqla.models import db
				import sqlalchemy as sa
				from pgappforge.plugins.fintech.lending.models import LoanApplication

				app_obj = db.session.get(LoanApplication, application_id)
				if app_obj:
					# Weighted scoring breakdown (illustrative)
					scorecard_data = {
						"application_number": app_obj.application_number,
						"credit_score": app_obj.credit_score,
						"dti_ratio": str(app_obj.dti_ratio or "N/A"),
						"ltv_ratio": str(app_obj.ltv_ratio or "N/A"),
						"bureau_response": app_obj.credit_bureau_response,
						"factors": [
							{"factor": "Credit Score", "weight": 40, "score": app_obj.credit_score or 0},
							{"factor": "DTI Ratio", "weight": 30, "score": max(0, 100 - int(app_obj.dti_ratio or 0))},
							{"factor": "LTV Ratio", "weight": 20, "score": max(0, 100 - int(app_obj.ltv_ratio or 0))},
							{"factor": "Bureau History", "weight": 10, "score": 80},
						],
					}
			except Exception as exc:
				log.exception("Scorecard view failed")
				scorecard_data = {"error": str(exc)}

		return self.render_template(
			"lending/scorecard.html",
			scorecard=scorecard_data,
			star_widget=star_widget(max_rating=10, readonly=True),
		)


# ---------------------------------------------------------------------------
# CollectionsDashboard
# ---------------------------------------------------------------------------

class CollectionsDashboard(BaseView):
	"""Collections workbench — overdue loans by DPD bucket, recovery metrics."""

	route_base = "/lending/collections"
	default_view = "index"

	@expose("/")
	def index(self):
		"""Render collections dashboard with DPD buckets and collector workload."""
		from collections import defaultdict

		aging_rows: list[dict] = []
		bucket_summary: dict = defaultdict(lambda: {"count": 0, "outstanding_cents": 0, "arrears_cents": 0})
		error: str | None = None

		try:
			from flask_appbuilder.security.sqla.models import db
			from pgappforge.plugins.fintech.lending.services import LoanManagementService

			svc = LoanManagementService()
			aging_rows = svc.get_loan_aging_report(db.session)

			for row in aging_rows:
				bkt = row["dpd_bucket"]
				bucket_summary[bkt]["count"] += 1
				bucket_summary[bkt]["outstanding_cents"] += row["outstanding_principal_cents"]
				bucket_summary[bkt]["arrears_cents"] += row["arrears_cents"]

		except Exception as exc:
			log.exception("Collections dashboard failed")
			error = str(exc)

		aging_chart = chart_widget("bar")

		return self.render_template(
			"lending/collections_dashboard.html",
			aging_rows=aging_rows,
			bucket_summary=dict(bucket_summary),
			aging_chart=aging_chart,
			error=error,
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LoanApplicationView",
	"LoanView",
	"RepaymentScheduleView",
	"LoanPortfolioDashboard",
	"CreditScorecardView",
	"CollectionsDashboard",
]
