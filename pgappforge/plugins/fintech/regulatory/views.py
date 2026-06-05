"""
pgappforge/plugins/fintech/regulatory/views.py

Regulatory Compliance views.

Views
-----
  AMLRuleView          — manage AML detection rules
  AMLAlertView         — investigate and action AML alerts
                         (Investigate / Escalate / File SAR action buttons)
  SARView              — read-only SAR register with document viewer
  CapitalAdequacyView  — capital ratio trends with gauge charts
  IFRS9View            — ECL provision runs with stage migration charts
  PEPListView          — PEP register management
  ComplianceDashboard  — /regulatory/dashboard/ — KPI gauges and alert counts

Widget conventions
------------------
  Monetary columns  : CurrencyWidget (KES)
  Date fields       : DatePickerWidget
  DateTime fields   : DateTimePickerWidget
  Risk score        : StarRatingWidget (max=10, maps 1-100 to 0-10 stars)
  Status columns    : Select2Widget with status choices
  Notes / text      : RichTextEditorWidget
  JSON detail       : JSONEditorWidget (readonly on SARView)
  Ratio trends      : AdvancedChartsWidget (line)
  Gauge displays    : AdvancedChartsWidget (gauge)
  Stage migration   : AdvancedChartsWidget (stacked bar)
  Documents         : FileUploadWidget (for SAR attachment)
"""
from __future__ import annotations

import logging
from typing import Any

from flask import flash, redirect, url_for, request, jsonify
from flask_appbuilder import ModelView, BaseView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	currency_widget,
	date_widget,
	datetime_widget,
	file_widget,
	json_widget,
	rich_text_widget,
	select2_widget,
	select2_ajax_widget,
	star_widget,
)
from pgappforge.plugins.fintech.regulatory.models import (
	AMLAlert,
	AMLRule,
	CapitalAdequacyReport,
	IFRS9ProvisionRun,
	PEPList,
	SuspiciousActivityReport,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Common label maps
# ---------------------------------------------------------------------------

_REG_MONEY_LABELS: dict[str, str] = {
	"total_amount_cents": "Total Amount",
	"core_capital_cents": "Core Capital (CET1)",
	"additional_tier1_cents": "Additional Tier 1",
	"tier1_capital_cents": "Tier 1 Capital",
	"tier2_capital_cents": "Tier 2 Capital",
	"total_capital_cents": "Total Capital",
	"credit_rwa_cents": "Credit RWA",
	"market_rwa_cents": "Market RWA",
	"operational_rwa_cents": "Operational RWA",
	"total_rwa_cents": "Total RWA",
	"stage1_loans_cents": "Stage 1 Loans",
	"stage1_ecl_cents": "Stage 1 ECL",
	"stage2_loans_cents": "Stage 2 Loans",
	"stage2_ecl_cents": "Stage 2 ECL",
	"stage3_loans_cents": "Stage 3 Loans",
	"stage3_ecl_cents": "Stage 3 ECL",
	"total_loans_outstanding_cents": "Total Loans Outstanding",
	"total_ecl_cents": "Total ECL",
	"provision_movement_cents": "Provision Movement",
}

_STATUS_LABELS: dict[str, str] = {
	"status": "Status",
	"alert_number": "Alert #",
	"sar_number": "SAR #",
	"rule_code": "Rule Code",
	"rule_type": "Rule Type",
	"risk_score": "Risk Score",
}

_RATIO_LABELS: dict[str, str] = {
	"cet1_ratio_pct": "CET1 Ratio %",
	"tier1_ratio_pct": "Tier 1 Ratio %",
	"total_capital_ratio_pct": "Total Capital Ratio %",
	"leverage_ratio_pct": "Leverage Ratio %",
	"liquidity_coverage_ratio_pct": "LCR %",
	"nsfr_pct": "NSFR %",
	"total_provision_pct": "Provision %",
	"coverage_ratio_pct": "Coverage Ratio %",
}


# ---------------------------------------------------------------------------
# AMLRuleView
# ---------------------------------------------------------------------------

class AMLRuleView(ModelView):
	"""Manage AML detection rules."""

	datamodel = SQLAInterface(AMLRule)
	route_base = "/regulatory/aml-rules"

	list_title = "AML Rules"
	show_title = "AML Rule Detail"
	add_title = "Add AML Rule"
	edit_title = "Edit AML Rule"

	list_columns = [
		"rule_code", "rule_name", "rule_type", "risk_score", "is_active", "regulatory_reference",
	]
	show_columns = [
		"rule_code", "rule_name", "rule_type", "description",
		"parameters", "risk_score", "is_active", "regulatory_reference",
		"created_at", "updated_at",
	]
	add_columns = [
		"rule_code", "rule_name", "rule_type", "description",
		"parameters", "risk_score", "is_active", "regulatory_reference",
		"tenant_id",
	]
	edit_columns = [
		"rule_name", "rule_type", "description",
		"parameters", "risk_score", "is_active", "regulatory_reference",
	]
	search_columns = ["rule_code", "rule_name", "rule_type", "is_active"]
	order_columns = ["rule_code", "risk_score", "rule_type"]

	label_columns = {
		**_STATUS_LABELS,
		"rule_name": "Rule Name",
		"description": "Description",
		"parameters": "Parameters (JSONB)",
		"is_active": "Active",
		"regulatory_reference": "Regulatory Reference",
	}

	formatters_columns = {
		"risk_score": lambda score: f"{score}/100" if score else "-",
		"is_active": lambda v: "Yes" if v else "No",
	}

	validators_columns: dict = {}

	# Widget overrides
	add_form_extra_fields: dict[str, Any] = {}
	edit_form_extra_fields: dict[str, Any] = {}

	# Custom widget hints (consumed by FAB template layer)
	column_widgets = {
		"risk_score": star_widget(max_rating=10),
		"parameters": json_widget(mode="code", height=250),
	}


# ---------------------------------------------------------------------------
# AMLAlertView
# ---------------------------------------------------------------------------

class AMLAlertView(ModelView):
	"""Manage and investigate AML alerts.

	Action buttons: Investigate, Escalate, File SAR (routed to service).
	"""

	datamodel = SQLAInterface(AMLAlert)
	route_base = "/regulatory/aml-alerts"

	list_title = "AML Alerts"
	show_title = "AML Alert Detail"
	edit_title = "Update Alert"

	# No add — alerts are generated by the rule engine only
	can_add = False

	list_columns = [
		"alert_number", "status", "risk_score", "customer_id",
		"due_by", "assigned_to", "created_at",
	]
	show_columns = [
		"alert_number", "rule_id", "customer_id", "account_id",
		"risk_score", "status", "triggering_transaction_ids", "alert_detail",
		"assigned_to", "due_by", "investigated_by", "investigation_notes",
		"closed_at", "created_at",
	]
	edit_columns = [
		"status", "assigned_to", "investigation_notes",
	]
	search_columns = ["alert_number", "status", "customer_id"]
	order_columns = ["created_at", "risk_score", "due_by", "status"]

	label_columns = {
		**_STATUS_LABELS,
		**_REG_MONEY_LABELS,
		"customer_id": "Customer",
		"account_id": "Account",
		"rule_id": "AML Rule",
		"triggering_transaction_ids": "Triggering Transactions",
		"alert_detail": "Alert Detail",
		"assigned_to": "Assigned To",
		"due_by": "Due By",
		"investigated_by": "Investigated By",
		"investigation_notes": "Investigation Notes",
		"closed_at": "Closed At",
	}

	column_widgets = {
		"risk_score": star_widget(max_rating=10),
		"due_by": datetime_widget(),
		"status": select2_widget(choices=[
			"OPEN", "UNDER_REVIEW", "ESCALATED",
			"CLOSED_FALSE_POSITIVE", "CLOSED_SAR_FILED", "CLOSED_NO_ACTION",
		]),
		"investigation_notes": rich_text_widget(height=200),
		"alert_detail": json_widget(readonly=True),
		"triggering_transaction_ids": json_widget(readonly=True),
	}

	@expose("/investigate/<alert_id>", methods=["POST"])
	@has_access
	def investigate(self, alert_id: str):
		"""Mark alert UNDER_REVIEW and assign to current user."""
		from flask_login import current_user
		from flask_appbuilder import current_app
		from pgappforge.plugins.fintech.regulatory.services import (
			RegulatoryComplianceService,
			AMLAlertNotFoundError,
			InvalidAlertStatusError,
		)
		notes = request.form.get("notes", "")
		try:
			ab = current_app.extensions["appbuilder"]
			svc = RegulatoryComplianceService(ab.get_session)
			svc.investigate_alert(alert_id, str(current_user.id), notes)
			ab.get_session.commit()
			flash("Alert marked UNDER_REVIEW.", "success")
		except (AMLAlertNotFoundError, InvalidAlertStatusError) as exc:
			flash(str(exc), "danger")
		except Exception as exc:
			log.error("investigate action error: %s", exc)
			flash("Error updating alert.", "danger")
		return redirect(url_for("AMLAlertView.show", pk=alert_id))

	@expose("/escalate/<alert_id>", methods=["POST"])
	@has_access
	def escalate(self, alert_id: str):
		"""Escalate alert to ESCALATED status."""
		from flask_login import current_user
		from flask_appbuilder import current_app
		from pgappforge.plugins.fintech.regulatory.services import (
			RegulatoryComplianceService,
			AMLAlertNotFoundError,
			InvalidAlertStatusError,
		)
		try:
			ab = current_app.extensions["appbuilder"]
			svc = RegulatoryComplianceService(ab.get_session)
			svc.escalate_alert(alert_id, str(current_user.id))
			ab.get_session.commit()
			flash("Alert escalated.", "warning")
		except (AMLAlertNotFoundError, InvalidAlertStatusError) as exc:
			flash(str(exc), "danger")
		except Exception as exc:
			log.error("escalate action error: %s", exc)
			flash("Error escalating alert.", "danger")
		return redirect(url_for("AMLAlertView.show", pk=alert_id))

	@expose("/file-sar/<alert_id>", methods=["POST"])
	@has_access
	def file_sar(self, alert_id: str):
		"""File a SAR for this alert with FRC Kenya."""
		from flask_login import current_user
		from flask_appbuilder import current_app
		from pgappforge.plugins.fintech.regulatory.services import (
			RegulatoryComplianceService,
			AMLAlertNotFoundError,
			SARAlreadyFiledError,
		)
		description = request.form.get("description", "")
		if not description:
			flash("SAR description is required.", "danger")
			return redirect(url_for("AMLAlertView.show", pk=alert_id))
		try:
			ab = current_app.extensions["appbuilder"]
			svc = RegulatoryComplianceService(ab.get_session)
			sar = svc.file_sar(alert_id, description, filed_by=str(current_user.id))
			ab.get_session.commit()
			flash(f"SAR {sar.sar_number} filed with FRC Kenya.", "success")
		except SARAlreadyFiledError as exc:
			flash(str(exc), "warning")
		except (AMLAlertNotFoundError, Exception) as exc:
			log.error("file_sar action error: %s", exc)
			flash("Error filing SAR.", "danger")
		return redirect(url_for("AMLAlertView.show", pk=alert_id))


# ---------------------------------------------------------------------------
# SARView — read-only after filing
# ---------------------------------------------------------------------------

class SARView(ModelView):
	"""Suspicious Activity Report register. Read-only after filing."""

	datamodel = SQLAInterface(SuspiciousActivityReport)
	route_base = "/regulatory/sars"

	list_title = "Suspicious Activity Reports"
	show_title = "SAR Detail"

	can_add = False
	can_edit = False
	can_delete = False

	list_columns = [
		"sar_number", "subject_id", "status", "total_amount_cents",
		"currency_code", "filed_at", "regulator", "regulator_reference",
	]
	show_columns = [
		"sar_number", "alert_id", "subject_id", "account_ids",
		"activity_period_start", "activity_period_end",
		"suspicious_activity_description",
		"total_amount_cents", "currency_code",
		"filed_by", "filed_at", "regulator", "regulator_reference", "status",
		"created_at",
	]
	search_columns = ["sar_number", "status", "regulator"]
	order_columns = ["filed_at", "sar_number", "status"]

	label_columns = {
		**_REG_MONEY_LABELS,
		"sar_number": "SAR Number",
		"subject_id": "Subject (Customer)",
		"alert_id": "Source Alert",
		"account_ids": "Accounts Involved",
		"activity_period_start": "Activity From",
		"activity_period_end": "Activity To",
		"suspicious_activity_description": "Suspicious Activity Description",
		"currency_code": "Currency",
		"filed_by": "Filed By",
		"filed_at": "Filed At",
		"regulator": "Regulator",
		"regulator_reference": "Regulator Reference",
	}

	column_widgets = {
		"total_amount_cents": currency_widget("KES"),
		"activity_period_start": date_widget(),
		"activity_period_end": date_widget(),
		"filed_at": datetime_widget(),
		"account_ids": json_widget(readonly=True),
		"suspicious_activity_description": rich_text_widget(height=300),
	}


# ---------------------------------------------------------------------------
# CapitalAdequacyView
# ---------------------------------------------------------------------------

class CapitalAdequacyView(ModelView):
	"""Capital adequacy report history with ratio trend charts."""

	datamodel = SQLAInterface(CapitalAdequacyReport)
	route_base = "/regulatory/capital-adequacy"

	list_title = "Capital Adequacy Reports"
	show_title = "Capital Adequacy Report"

	can_add = False
	can_edit = False
	can_delete = False

	list_columns = [
		"report_date", "reporting_period",
		"cet1_ratio_pct", "tier1_ratio_pct", "total_capital_ratio_pct",
		"leverage_ratio_pct", "liquidity_coverage_ratio_pct", "nsfr_pct",
		"meets_minimum", "submitted_to_cbk",
	]
	show_columns = [
		"report_date", "reporting_period",
		"core_capital_cents", "additional_tier1_cents", "tier1_capital_cents",
		"tier2_capital_cents", "total_capital_cents",
		"credit_rwa_cents", "market_rwa_cents", "operational_rwa_cents", "total_rwa_cents",
		"cet1_ratio_pct", "tier1_ratio_pct", "total_capital_ratio_pct",
		"leverage_ratio_pct", "liquidity_coverage_ratio_pct", "nsfr_pct",
		"meets_minimum", "submitted_to_cbk", "submitted_at",
	]
	search_columns = ["report_date", "reporting_period", "meets_minimum"]
	order_columns = ["report_date"]

	label_columns = {**_REG_MONEY_LABELS, **_RATIO_LABELS, **_STATUS_LABELS,
		"report_date": "As-of Date",
		"reporting_period": "Period",
		"meets_minimum": "Meets CBK Minimum",
		"submitted_to_cbk": "Submitted to CBK",
		"submitted_at": "Submitted At",
	}

	column_widgets = {
		"core_capital_cents": currency_widget("KES"),
		"additional_tier1_cents": currency_widget("KES"),
		"tier1_capital_cents": currency_widget("KES"),
		"tier2_capital_cents": currency_widget("KES"),
		"total_capital_cents": currency_widget("KES"),
		"credit_rwa_cents": currency_widget("KES"),
		"market_rwa_cents": currency_widget("KES"),
		"operational_rwa_cents": currency_widget("KES"),
		"total_rwa_cents": currency_widget("KES"),
		"report_date": date_widget(),
		# Ratio trend charts on show view
		"cet1_ratio_pct": chart_widget("gauge"),
		"tier1_ratio_pct": chart_widget("gauge"),
		"total_capital_ratio_pct": chart_widget("gauge"),
		"leverage_ratio_pct": chart_widget("gauge"),
		"liquidity_coverage_ratio_pct": chart_widget("gauge"),
		"nsfr_pct": chart_widget("gauge"),
	}


# ---------------------------------------------------------------------------
# IFRS9View
# ---------------------------------------------------------------------------

class IFRS9View(ModelView):
	"""IFRS 9 ECL provision run history with stage migration charts."""

	datamodel = SQLAInterface(IFRS9ProvisionRun)
	route_base = "/regulatory/ifrs9"

	list_title = "IFRS 9 Provision Runs"
	show_title = "IFRS 9 Provision Run Detail"

	can_add = False
	can_edit = False
	can_delete = False

	list_columns = [
		"run_date", "run_type",
		"total_loans_outstanding_cents", "total_ecl_cents",
		"total_provision_pct", "coverage_ratio_pct",
		"provision_movement_cents",
	]
	show_columns = [
		"run_date", "run_type",
		"stage1_loans_cents", "stage1_ecl_cents",
		"stage2_loans_cents", "stage2_ecl_cents",
		"stage3_loans_cents", "stage3_ecl_cents",
		"total_loans_outstanding_cents", "total_ecl_cents",
		"total_provision_pct", "coverage_ratio_pct",
		"provision_movement_cents", "approved_by",
		"created_at",
	]
	search_columns = ["run_date", "run_type"]
	order_columns = ["run_date"]

	label_columns = {
		**_REG_MONEY_LABELS,
		"run_date": "Run Date",
		"run_type": "Run Type",
		"total_provision_pct": "Total Provision %",
		"coverage_ratio_pct": "NPL Coverage %",
		"provision_movement_cents": "Provision Movement",
		"approved_by": "Approved By",
	}

	column_widgets = {
		"stage1_loans_cents": currency_widget("KES"),
		"stage1_ecl_cents": currency_widget("KES"),
		"stage2_loans_cents": currency_widget("KES"),
		"stage2_ecl_cents": currency_widget("KES"),
		"stage3_loans_cents": currency_widget("KES"),
		"stage3_ecl_cents": currency_widget("KES"),
		"total_loans_outstanding_cents": currency_widget("KES"),
		"total_ecl_cents": currency_widget("KES"),
		"provision_movement_cents": currency_widget("KES"),
		"run_date": date_widget(),
		# Stage migration stacked bar on show view
		"stage1_loans_cents_chart": chart_widget("bar"),
	}


# ---------------------------------------------------------------------------
# PEPListView
# ---------------------------------------------------------------------------

class PEPListView(ModelView):
	"""PEP register management."""

	datamodel = SQLAInterface(PEPList)
	route_base = "/regulatory/pep-list"

	list_title = "PEP Register"
	show_title = "PEP Entry"
	add_title = "Add PEP Entry"
	edit_title = "Update PEP Entry"

	list_columns = [
		"party_id", "pep_type", "position_held", "country_code",
		"source", "review_date", "status",
	]
	show_columns = [
		"party_id", "pep_type", "position_held", "country_code",
		"source", "added_at", "review_date", "status",
		"created_at", "updated_at",
	]
	add_columns = [
		"party_id", "pep_type", "position_held", "country_code",
		"source", "added_at", "review_date", "status", "tenant_id",
	]
	edit_columns = [
		"pep_type", "position_held", "source", "review_date", "status",
	]
	search_columns = ["party_id", "pep_type", "country_code", "status"]
	order_columns = ["review_date", "pep_type", "status"]

	label_columns = {
		"party_id": "Customer / Party",
		"pep_type": "PEP Type",
		"position_held": "Position Held",
		"country_code": "Country",
		"source": "Source",
		"added_at": "Added At",
		"review_date": "Next EDD Review",
		"status": "Status",
	}

	column_widgets = {
		"review_date": date_widget(),
		"added_at": datetime_widget(),
		"status": select2_widget(choices=["ACTIVE", "INACTIVE"]),
		"pep_type": select2_widget(choices=[
			"DOMESTIC_PEP", "FOREIGN_PEP",
			"INTERNATIONAL_ORGANIZATION_PEP",
			"CLOSE_ASSOCIATE", "FAMILY_MEMBER",
		]),
		"source": select2_widget(choices=["WORLD_CHECK", "REFINITIV", "MANUAL", "GOVERNMENT"]),
		"party_id": select2_ajax_widget(),
	}


# ---------------------------------------------------------------------------
# ComplianceDashboard — aggregated KPI view
# ---------------------------------------------------------------------------

class ComplianceDashboard(BaseView):
	"""Regulatory compliance dashboard at /regulatory/dashboard/.

	Displays:
	  - Capital ratio gauges (CET1, Tier1, Total CAR, Leverage, LCR, NSFR)
	  - AML alert queue breakdown by status
	  - IFRS 9 ECL summary and stage distribution
	  - PEP register counts and overdue EDD reviews
	  - Upcoming report deadlines

	All chart widgets use AdvancedChartsWidget for consistency.
	"""

	route_base = "/regulatory/dashboard"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""Render compliance dashboard with live KPI aggregates."""
		from flask_appbuilder import current_app
		from pgappforge.plugins.fintech.regulatory.services import RegulatoryComplianceService

		dashboard_data: dict = {}
		try:
			ab = current_app.extensions["appbuilder"]
			svc = RegulatoryComplianceService(ab.get_session)
			dashboard_data = svc.generate_compliance_dashboard()
		except Exception as exc:
			log.error("ComplianceDashboard.index error: %s", exc)
			flash("Could not load compliance dashboard data.", "danger")

		# Widget config map passed to template
		widgets = {
			"cet1_gauge": chart_widget("gauge"),
			"tier1_gauge": chart_widget("gauge"),
			"total_car_gauge": chart_widget("gauge"),
			"lcr_gauge": chart_widget("gauge"),
			"nsfr_gauge": chart_widget("gauge"),
			"alert_status_bar": chart_widget("bar"),
			"ecl_stage_bar": chart_widget("bar"),
			"provision_trend_line": chart_widget("line"),
		}

		return self.render_template(
			"regulatory/dashboard.html",
			dashboard=dashboard_data,
			widgets=widgets,
			title="Regulatory Compliance Dashboard",
		)

	@expose("/api/kpis")
	@has_access
	def api_kpis(self):
		"""JSON API endpoint for dashboard KPIs (used by chart widgets)."""
		from flask_appbuilder import current_app
		from pgappforge.plugins.fintech.regulatory.services import RegulatoryComplianceService

		try:
			ab = current_app.extensions["appbuilder"]
			svc = RegulatoryComplianceService(ab.get_session)
			return jsonify(svc.generate_compliance_dashboard())
		except Exception as exc:
			log.error("ComplianceDashboard.api_kpis error: %s", exc)
			return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"AMLRuleView",
	"AMLAlertView",
	"SARView",
	"CapitalAdequacyView",
	"IFRS9View",
	"PEPListView",
	"ComplianceDashboard",
]
