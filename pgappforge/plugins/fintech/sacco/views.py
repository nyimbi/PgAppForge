"""
pgappforge/plugins/fintech/sacco/views.py

FAB views for the SACCO / MFI / Chama plugin.

Views:
  MemberView           — Member list/detail with share capital and status
  SACCOView            — SACCO institution management
  SACCOLoanProductView — Loan product catalogue per SACCO
  DividendView         — Dividend declarations and payment tracking
  ChamaView            — Chama savings group management
  ChamaMemberView      — Per-Chama membership and contribution tracking
  SACCODashboardView   — KPI dashboard: savings, loan book, NPL, capital adequacy
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
	chart_widget,
	select2_widget,
	select2_ajax_widget,
	json_widget,
	progress_widget,
	star_widget,
)
from pgappforge.plugins.fintech.sacco.models import (
	SACCO,
	Member,
	SACCOLoanProduct,
	Dividend,
	Chama,
	ChamaMember,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SACCOView
# ---------------------------------------------------------------------------

class SACCOView(ModelView):
	"""SACCO institution management."""

	datamodel = SQLAInterface(SACCO)

	list_title = "SACCOs"
	show_title = "SACCO Detail"
	add_title = "Register SACCO"
	edit_title = "Edit SACCO"

	list_columns = [
		"name",
		"registration_number",
		"sacco_type",
		"regulator",
		"membership_count",
		"total_shares_cents",
		"total_loans_outstanding_cents",
		"delinquency_rate_pct",
	]

	label_columns = {
		"name": "SACCO Name",
		"registration_number": "Reg. Number",
		"sacco_type": "Type",
		"regulator": "Regulator",
		"license_number": "Licence #",
		"license_expiry_date": "Licence Expiry",
		"common_bond": "Common Bond",
		"membership_count": "Members",
		"total_shares_cents": "Total Shares",
		"total_deposits_cents": "Total Deposits",
		"total_loans_outstanding_cents": "Loan Book",
		"reserve_fund_cents": "Reserve Fund",
		"institutional_capital_pct": "Capital Adequacy %",
		"delinquency_rate_pct": "Delinquency Rate %",
		"address": "Address",
		"created_at": "Created",
		"updated_at": "Last Updated",
	}

	show_fieldsets = [
		("Institution", {
			"fields": [
				"name",
				"registration_number",
				"sacco_type",
				"regulator",
				"license_number",
				"license_expiry_date",
				"common_bond",
			],
		}),
		("Financial Aggregates", {
			"fields": [
				"membership_count",
				"total_shares_cents",
				"total_deposits_cents",
				"total_loans_outstanding_cents",
				"reserve_fund_cents",
			],
		}),
		("Regulatory Ratios", {
			"fields": [
				"institutional_capital_pct",
				"delinquency_rate_pct",
			],
		}),
		("Contact", {
			"fields": ["address"],
		}),
	]

	add_fieldsets = [
		("Institution", {
			"fields": [
				"name",
				"registration_number",
				"sacco_type",
				"regulator",
				"license_number",
				"license_expiry_date",
				"common_bond",
				"address",
			],
		}),
	]

	edit_fieldsets = [
		("Institution", {
			"fields": [
				"name",
				"sacco_type",
				"regulator",
				"license_number",
				"license_expiry_date",
				"common_bond",
			],
		}),
		("Regulatory Ratios", {
			"fields": [
				"institutional_capital_pct",
				"delinquency_rate_pct",
				"reserve_fund_cents",
			],
		}),
		("Contact", {
			"fields": ["address"],
		}),
	]

	formatters_columns = {
		"total_shares_cents": currency_widget("KES"),
		"total_deposits_cents": currency_widget("KES"),
		"total_loans_outstanding_cents": currency_widget("KES"),
		"reserve_fund_cents": currency_widget("KES"),
		"license_expiry_date": date_widget(),
		"created_at": datetime_widget(),
		"updated_at": datetime_widget(),
		"sacco_type": select2_widget(
			choices=[
				("DEPOSIT_TAKING", "Deposit Taking"),
				("NON_DEPOSIT_TAKING", "Non-Deposit Taking"),
				("FOSA", "FOSA (Front Office Service Activity)"),
			]
		),
		"regulator": select2_widget(
			choices=[
				("SASRA", "SASRA — Kenya"),
				("UCSCU", "UCSCU — Uganda"),
				("CRDB", "CRDB — Tanzania"),
				("ACCOSCA", "ACCOSCA — Pan-African"),
			]
		),
		"address": json_widget(mode="tree"),
	}

	search_columns = ["name", "registration_number", "sacco_type", "regulator"]
	base_order = ("name", "asc")


# ---------------------------------------------------------------------------
# MemberView
# ---------------------------------------------------------------------------

class MemberView(ModelView):
	"""SACCO member list / detail with share capital and contribution tracking."""

	datamodel = SQLAInterface(Member)

	list_title = "Members"
	show_title = "Member Detail"
	add_title = "Register Member"
	edit_title = "Edit Member"

	list_columns = [
		"member_number",
		"sacco_id",
		"membership_status",
		"shares_held",
		"total_shares_value_cents",
		"monthly_contribution_cents",
		"membership_date",
	]

	label_columns = {
		"member_number": "Member #",
		"sacco_id": "SACCO",
		"party_id": "Party",
		"membership_date": "Joined",
		"membership_status": "Status",
		"share_account_id": "Share Account",
		"deposit_account_id": "Deposit Account",
		"shares_held": "Shares Held",
		"share_value_cents": "Share Par Value",
		"total_shares_value_cents": "Shares Value",
		"monthly_contribution_cents": "Monthly Contribution",
		"guarantees_given": "Guarantees Given",
		"guarantees_active_cents": "Active Guarantee Exposure",
		"dividend_account": "Dividend Account",
		"exit_date": "Exit Date",
		"exit_reason": "Exit Reason",
		"withdrawal_balance_cents": "Withdrawal Balance",
		"created_at": "Registered",
	}

	show_fieldsets = [
		("Membership", {
			"fields": [
				"member_number",
				"sacco_id",
				"party_id",
				"membership_date",
				"membership_status",
			],
		}),
		("Accounts", {
			"fields": [
				"share_account_id",
				"deposit_account_id",
				"dividend_account",
			],
		}),
		("Share Capital", {
			"fields": [
				"shares_held",
				"share_value_cents",
				"total_shares_value_cents",
				"monthly_contribution_cents",
			],
		}),
		("Guarantor Exposure", {
			"fields": [
				"guarantees_given",
				"guarantees_active_cents",
			],
		}),
		("Exit", {
			"fields": [
				"exit_date",
				"exit_reason",
				"withdrawal_balance_cents",
			],
		}),
	]

	add_fieldsets = [
		("Membership", {
			"fields": [
				"sacco_id",
				"party_id",
				"membership_date",
				"monthly_contribution_cents",
				"share_account_id",
				"deposit_account_id",
				"dividend_account",
			],
		}),
	]

	edit_fieldsets = [
		("Membership", {
			"fields": [
				"membership_status",
				"monthly_contribution_cents",
				"dividend_account",
			],
		}),
		("Exit", {
			"fields": ["exit_date", "exit_reason"],
		}),
	]

	formatters_columns = {
		"total_shares_value_cents": currency_widget("KES"),
		"monthly_contribution_cents": currency_widget("KES"),
		"share_value_cents": currency_widget("KES"),
		"guarantees_active_cents": currency_widget("KES"),
		"withdrawal_balance_cents": currency_widget("KES"),
		"membership_date": date_widget(),
		"exit_date": date_widget(),
		"created_at": datetime_widget(),
		"membership_status": select2_widget(
			choices=[
				("ACTIVE", "Active"),
				("SUSPENDED", "Suspended"),
				("WITHDRAWN", "Withdrawn"),
				("DECEASED", "Deceased"),
			]
		),
		"guarantees_given": json_widget(mode="view", readonly=True),
		# shares_held rendered as star rating out of 10 (visual indicator, not exact)
		"shares_held": star_widget(max_rating=10, readonly=True),
		"sacco_id": select2_ajax_widget(min_chars=2),
		"party_id": select2_ajax_widget(min_chars=2),
	}

	search_columns = ["member_number", "membership_status"]
	base_order = ("membership_date", "desc")

	# Custom action: Calculate exit value
	@expose("/exit_value/<string:pk>", methods=["GET"])
	def exit_value_action(self, pk: str):
		"""Calculate and display the exit value for a member."""
		from flask import jsonify
		try:
			from pgappforge.plugins.fintech.sacco.services import SACCOService
			member = self.datamodel.get(pk)
			if member is None:
				return jsonify({"error": "Member not found"}), 404
			svc = SACCOService()
			result = svc.calculate_member_exit_value(self.datamodel.session, pk)
			self.datamodel.session.commit()
			return jsonify(result)
		except Exception as exc:
			log.exception("exit_value_action failed for member %s", pk)
			return jsonify({"error": str(exc)}), 500

	# Custom action: Post contribution
	@expose("/contribute/<string:pk>", methods=["POST"])
	def contribute_action(self, pk: str):
		"""Post a monthly contribution for a member."""
		try:
			from pgappforge.plugins.fintech.sacco.services import SACCOService
			member = self.datamodel.get(pk)
			if member is None:
				flash("Member not found", "danger")
				return redirect(url_for(".list"))
			amount_cents = int(request.form.get("amount_cents", member.monthly_contribution_cents))
			svc = SACCOService()
			result = svc.process_monthly_contribution(self.datamodel.session, pk, amount_cents)
			self.datamodel.session.commit()
			flash(
				f"Contribution of {amount_cents} cents posted for {member.member_number}",
				"success",
			)
		except Exception as exc:
			log.exception("contribute_action failed for member %s", pk)
			flash(str(exc), "danger")
		return redirect(url_for(".list"))


# ---------------------------------------------------------------------------
# SACCOLoanProductView
# ---------------------------------------------------------------------------

class SACCOLoanProductView(ModelView):
	"""SACCO loan product catalogue."""

	datamodel = SQLAInterface(SACCOLoanProduct)

	list_title = "SACCO Loan Products"
	show_title = "Loan Product Detail"
	add_title = "New Loan Product"
	edit_title = "Edit Loan Product"

	list_columns = [
		"product_name",
		"sacco_id",
		"loan_type",
		"max_multiple_of_savings",
		"interest_rate_pa",
		"max_tenor_months",
		"requires_guarantors",
		"is_active",
	]

	label_columns = {
		"product_name": "Product Name",
		"sacco_id": "SACCO",
		"loan_type": "Loan Type",
		"max_multiple_of_savings": "Max Savings Multiple",
		"max_amount_cents": "Absolute Cap",
		"interest_rate_pa": "Interest Rate p.a.",
		"max_tenor_months": "Max Tenor (months)",
		"processing_fee_pct": "Processing Fee %",
		"requires_guarantors": "Requires Guarantors",
		"min_guarantors": "Min. Guarantors",
		"guarantor_coverage_pct": "Guarantor Coverage %",
		"is_active": "Active",
	}

	show_fieldsets = [
		("Product", {
			"fields": [
				"product_name",
				"sacco_id",
				"loan_type",
				"is_active",
			],
		}),
		("Limits", {
			"fields": [
				"max_multiple_of_savings",
				"max_amount_cents",
				"max_tenor_months",
			],
		}),
		("Pricing", {
			"fields": [
				"interest_rate_pa",
				"processing_fee_pct",
			],
		}),
		("Guarantors", {
			"fields": [
				"requires_guarantors",
				"min_guarantors",
				"guarantor_coverage_pct",
			],
		}),
	]

	formatters_columns = {
		"max_amount_cents": currency_widget("KES"),
		"loan_type": select2_widget(
			choices=[
				("DEVELOPMENT", "Development"),
				("EMERGENCY", "Emergency"),
				("SCHOOL_FEES", "School Fees"),
				("ASSET", "Asset"),
				("AGRI", "Agricultural"),
				("MICRO", "Micro-enterprise"),
				("SALARY_ADVANCE", "Salary Advance"),
			]
		),
		# guarantor_coverage_pct rendered as a range slider 0–200%
		"guarantor_coverage_pct": progress_widget(max_value=200),
	}

	search_columns = ["product_name", "loan_type"]
	base_order = ("product_name", "asc")


# ---------------------------------------------------------------------------
# DividendView
# ---------------------------------------------------------------------------

class DividendView(ModelView):
	"""Dividend declaration and payment tracking (immutable records)."""

	datamodel = SQLAInterface(Dividend)

	list_title = "Dividends"
	show_title = "Dividend Detail"
	add_title = "Declare Dividend"

	list_columns = [
		"sacco_id",
		"financial_year",
		"dividend_rate_pct",
		"interest_rebate_pct",
		"total_dividend_pool_cents",
		"approved_date",
		"status",
	]

	label_columns = {
		"sacco_id": "SACCO",
		"financial_year": "Financial Year",
		"dividend_rate_pct": "Dividend Rate %",
		"interest_rebate_pct": "Interest Rebate %",
		"total_dividend_pool_cents": "Total Pool",
		"approved_date": "AGM Approved",
		"payment_date": "Payment Date",
		"status": "Status",
	}

	show_fieldsets = [
		("Declaration", {
			"fields": [
				"sacco_id",
				"financial_year",
				"dividend_rate_pct",
				"interest_rebate_pct",
				"total_dividend_pool_cents",
				"approved_date",
			],
		}),
		("Payment", {
			"fields": [
				"payment_date",
				"status",
			],
		}),
	]

	add_fieldsets = [
		("Declaration", {
			"fields": [
				"sacco_id",
				"financial_year",
				"dividend_rate_pct",
				"interest_rebate_pct",
				"total_dividend_pool_cents",
				"approved_date",
			],
		}),
	]

	formatters_columns = {
		"total_dividend_pool_cents": currency_widget("KES"),
		"approved_date": date_widget(),
		"payment_date": date_widget(),
		"status": select2_widget(
			choices=[
				("DECLARED", "Declared"),
				("PAID", "Paid"),
				("CANCELLED", "Cancelled"),
			]
		),
		# Rate sliders 0–50%
		"dividend_rate_pct": progress_widget(max_value=50),
		"interest_rebate_pct": progress_widget(max_value=50),
	}

	# Immutable — no in-place editing
	can_edit = False
	can_delete = False

	search_columns = ["financial_year", "status"]
	base_order = ("financial_year", "desc")

	# Custom action: Pay dividends
	@expose("/pay/<string:pk>", methods=["POST"])
	def pay_action(self, pk: str):
		"""Trigger dividend payment for all eligible members."""
		try:
			from pgappforge.plugins.fintech.sacco.services import SACCOService
			svc = SACCOService()
			result = svc.pay_dividends(self.datamodel.session, pk)
			self.datamodel.session.commit()
			flash(
				f"Dividends paid: {result['members_credited']} members credited, "
				f"total={result['total_paid_cents']} cents",
				"success",
			)
		except Exception as exc:
			log.exception("pay_action failed for dividend %s", pk)
			flash(str(exc), "danger")
		return redirect(url_for(".list"))


# ---------------------------------------------------------------------------
# ChamaView
# ---------------------------------------------------------------------------

class ChamaView(ModelView):
	"""Chama savings group management."""

	datamodel = SQLAInterface(Chama)

	list_title = "Chamas"
	show_title = "Chama Detail"
	add_title = "Form Chama"
	edit_title = "Edit Chama"

	list_columns = [
		"chama_name",
		"chama_type",
		"meeting_frequency",
		"contribution_amount_cents",
		"current_pool_cents",
		"status",
	]

	label_columns = {
		"chama_name": "Chama Name",
		"chama_type": "Type",
		"formation_date": "Formation Date",
		"meeting_frequency": "Frequency",
		"contribution_amount_cents": "Contribution Amount",
		"current_pool_cents": "Current Pool",
		"group_account_id": "Group Account",
		"chairperson_id": "Chairperson",
		"treasurer_id": "Treasurer",
		"secretary_id": "Secretary",
		"rules": "Rules",
		"status": "Status",
	}

	show_fieldsets = [
		("Chama", {
			"fields": [
				"chama_name",
				"chama_type",
				"formation_date",
				"meeting_frequency",
				"status",
			],
		}),
		("Finances", {
			"fields": [
				"contribution_amount_cents",
				"current_pool_cents",
				"group_account_id",
			],
		}),
		("Office Bearers", {
			"fields": [
				"chairperson_id",
				"treasurer_id",
				"secretary_id",
			],
		}),
		("Rules", {
			"fields": ["rules"],
		}),
	]

	add_fieldsets = [
		("Chama", {
			"fields": [
				"chama_name",
				"chama_type",
				"formation_date",
				"meeting_frequency",
				"contribution_amount_cents",
			],
		}),
		("Office Bearers", {
			"fields": [
				"chairperson_id",
				"treasurer_id",
				"secretary_id",
			],
		}),
		("Rules", {
			"fields": ["rules"],
		}),
	]

	edit_fieldsets = [
		("Chama", {
			"fields": [
				"chama_name",
				"meeting_frequency",
				"status",
			],
		}),
		("Finances", {
			"fields": ["contribution_amount_cents", "group_account_id"],
		}),
		("Office Bearers", {
			"fields": [
				"chairperson_id",
				"treasurer_id",
				"secretary_id",
			],
		}),
		("Rules", {
			"fields": ["rules"],
		}),
	]

	formatters_columns = {
		"contribution_amount_cents": currency_widget("KES"),
		"current_pool_cents": currency_widget("KES"),
		"formation_date": date_widget(),
		"chama_type": select2_widget(
			choices=[
				("MERRY_GO_ROUND", "Merry-Go-Round"),
				("TABLE_BANKING", "Table Banking"),
				("INVESTMENT_CLUB", "Investment Club"),
				("WELFARE_GROUP", "Welfare Group"),
			]
		),
		"meeting_frequency": select2_widget(
			choices=[
				("WEEKLY", "Weekly"),
				("BIWEEKLY", "Bi-weekly"),
				("MONTHLY", "Monthly"),
				("QUARTERLY", "Quarterly"),
			]
		),
		"status": select2_widget(
			choices=[
				("ACTIVE", "Active"),
				("DORMANT", "Dormant"),
				("DISSOLVED", "Dissolved"),
			]
		),
		"rules": json_widget(mode="tree"),
		"chairperson_id": select2_ajax_widget(min_chars=2),
		"treasurer_id": select2_ajax_widget(min_chars=2),
		"secretary_id": select2_ajax_widget(min_chars=2),
	}

	search_columns = ["chama_name", "chama_type", "status"]
	base_order = ("chama_name", "asc")

	# Custom action: process merry-go-round
	@expose("/merry_go_round/<string:pk>", methods=["POST"])
	def merry_go_round_action(self, pk: str):
		"""Disburse merry-go-round pool to the current recipient."""
		try:
			from pgappforge.plugins.fintech.sacco.services import ChamaService
			recipient_id = request.form.get("recipient_member_id", "")
			if not recipient_id:
				flash("Recipient member ID is required", "danger")
				return redirect(url_for(".list"))
			svc = ChamaService()
			result = svc.process_merry_go_round(self.datamodel.session, pk, recipient_id)
			self.datamodel.session.commit()
			flash(
				f"Merry-go-round: {result['amount_disbursed_cents']} cents paid to member "
				f"{recipient_id}. Next recipient: {result['next_recipient_member_id']}",
				"success",
			)
		except Exception as exc:
			log.exception("merry_go_round_action failed for chama %s", pk)
			flash(str(exc), "danger")
		return redirect(url_for(".list"))

	# Custom action: get chama statement (JSON)
	@expose("/statement/<string:pk>", methods=["GET"])
	def statement_action(self, pk: str):
		"""Return Chama contribution/payout statement as JSON."""
		from flask import jsonify, request as req
		try:
			from pgappforge.plugins.fintech.sacco.services import ChamaService
			period = int(req.args.get("months", 3))
			svc = ChamaService()
			result = svc.get_chama_statement(self.datamodel.session, pk, period_months=period)
			return jsonify(result)
		except Exception as exc:
			log.exception("statement_action failed for chama %s", pk)
			return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# ChamaMemberView
# ---------------------------------------------------------------------------

class ChamaMemberView(ModelView):
	"""Per-Chama membership and contribution tracking."""

	datamodel = SQLAInterface(ChamaMember)

	list_title = "Chama Members"
	show_title = "Chama Member Detail"

	list_columns = [
		"chama_id",
		"member_id",
		"total_contributed_cents",
		"total_received_cents",
		"is_current_recipient",
		"contribution_streak",
		"status",
	]

	label_columns = {
		"chama_id": "Chama",
		"member_id": "Member",
		"join_date": "Joined",
		"total_contributed_cents": "Total Contributed",
		"total_received_cents": "Total Received",
		"is_current_recipient": "Current Recipient",
		"contribution_streak": "Streak (cycles)",
		"status": "Status",
	}

	show_fieldsets = [
		("Membership", {
			"fields": [
				"chama_id",
				"member_id",
				"join_date",
				"status",
			],
		}),
		("Contributions & Payouts", {
			"fields": [
				"total_contributed_cents",
				"total_received_cents",
				"is_current_recipient",
				"contribution_streak",
			],
		}),
	]

	# Readonly — mutations via service actions only
	can_add = False
	can_edit = False
	can_delete = False

	formatters_columns = {
		"total_contributed_cents": currency_widget("KES"),
		"total_received_cents": currency_widget("KES"),
		"join_date": date_widget(),
		"status": select2_widget(
			choices=[
				("ACTIVE", "Active"),
				("SUSPENDED", "Suspended"),
				("EXITED", "Exited"),
			]
		),
		# contribution_streak rendered as star rating out of 12 (12 months)
		"contribution_streak": star_widget(max_rating=12, readonly=True),
	}

	search_columns = ["status"]
	base_order = ("join_date", "asc")


# ---------------------------------------------------------------------------
# SACCODashboardView
# ---------------------------------------------------------------------------

class SACCODashboardView(BaseView):
	"""SACCO financial KPI dashboard.

	Displays:
	  - Savings growth (deposits + shares) — area chart
	  - Loan book trend — bar chart
	  - NPL / delinquency rate gauge
	  - Capital adequacy % vs SASRA minimum (8%)
	  - Membership growth
	"""

	route_base = "/sacco/dashboard"
	default_view = "index"

	@expose("/")
	@expose("/<string:sacco_id>")
	def index(self, sacco_id: str | None = None):
		"""Render SACCO KPI dashboard."""
		from flask import request as req
		kpis: dict = {}
		error: str | None = None
		sacco_list: list = []

		sacco_id = sacco_id or req.args.get("sacco_id", "")

		try:
			from flask_appbuilder.security.sqla.models import db
			import sqlalchemy as sa
			from pgappforge.plugins.fintech.sacco.models import SACCO as SACCOModel
			from pgappforge.plugins.fintech.sacco.services import SACCOService

			sacco_list = db.session.execute(
				sa.select(SACCOModel).order_by(SACCOModel.name)
			).scalars().all()

			if sacco_id:
				svc = SACCOService()
				kpis = svc.get_sacco_financials(db.session, sacco_id)

		except Exception as exc:
			log.exception("SACCO dashboard failed")
			error = str(exc)

		savings_chart = chart_widget("area")
		loan_chart = chart_widget("bar")
		npl_gauge = chart_widget("doughnut")
		membership_chart = chart_widget("line")

		return self.render_template(
			"sacco/dashboard.html",
			kpis=kpis,
			sacco_list=sacco_list,
			selected_sacco_id=sacco_id,
			savings_chart=savings_chart,
			loan_chart=loan_chart,
			npl_gauge=npl_gauge,
			membership_chart=membership_chart,
			error=error,
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SACCOView",
	"MemberView",
	"SACCOLoanProductView",
	"DividendView",
	"ChamaView",
	"ChamaMemberView",
	"SACCODashboardView",
]
