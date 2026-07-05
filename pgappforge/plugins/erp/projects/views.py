"""
pgappforge/plugins/erp/projects/views.py

Flask-AppBuilder views for the Projects / PSA plugin.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Any

from flask import make_response, request

try:
	from pgappforge import expose
	from pgappforge.models.sqla.interface import SQLAInterface
	from pgappforge.plugins.erp.base_view import BaseERPModelView, BaseERPView
except ImportError:  # pragma: no cover - fallback for standalone FAB installs
	from flask_appbuilder import BaseView as BaseERPView
	from flask_appbuilder import ModelView as BaseERPModelView
	from flask_appbuilder import expose
	from flask_appbuilder.models.sqla.interface import SQLAInterface

from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.projects.models import (
	ChangeOrder,
	Program,
	Project,
	ProjectInvoice,
	ProjectMilestone,
	ProjectResource,
	ProjectRisk,
	ProjectTimesheet,
	WBSElement,
)
from pgappforge.plugins.erp.projects.services import ProjectService


def _fmt_cents(value: Any) -> str:
	try:
		cents = int(value or 0)
	except (TypeError, ValueError):
		cents = 0
	sign = "-" if cents < 0 else ""
	return f"{sign}{abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def _fmt(value: Any) -> str:
	if value is None:
		return ""
	return escape(str(value))


def _table(headers: list[str], rows: list[dict[str, Any]], columns: list[str]) -> str:
	if not rows:
		colspan = max(len(headers), 1)
		return (
			"<table class='table table-bordered table-condensed table-hover'>"
			f"<thead><tr>{''.join(f'<th>{escape(h)}</th>' for h in headers)}</tr></thead>"
			f"<tbody><tr><td colspan='{colspan}' class='text-muted'>No records found.</td></tr></tbody>"
			"</table>"
		)
	body = "".join(
		"<tr>"
		+ "".join(f"<td>{_fmt(row.get(col))}</td>" for col in columns)
		+ "</tr>"
		for row in rows
	)
	head = "".join(f"<th>{escape(header)}</th>" for header in headers)
	return (
		"<table class='table table-bordered table-condensed table-hover'>"
		f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
	)


def _page(title: str, kpi_html: Any, table_html: str) -> Any:
	return make_response(
		"<!DOCTYPE html><html><head><meta charset='utf-8'>"
		f"<title>{escape(title)}</title>"
		"<link rel='stylesheet' href='/static/appbuilder/css/bootstrap.min.css'>"
		"</head><body style='padding:24px'>"
		f"<h3>{escape(title)}</h3>{kpi_html}{table_html}"
		"</body></html>",
		200,
	)


PROGRAM_COLUMNS = [
	"code",
	"name",
	"owner_id",
	"status",
	"budget_cents",
	"currency_code",
	"description",
	"created_at",
	"updated_at",
]
PROGRAM_LABELS = {
	"code": "Program Code",
	"name": "Program Name",
	"owner_id": "Owner",
	"status": "Status",
	"budget_cents": "Budget (cents)",
	"currency_code": "Currency",
	"description": "Description",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

PROJECT_COLUMNS = [
	"program_id",
	"code",
	"name",
	"project_type",
	"customer_id",
	"owner_id",
	"start_date",
	"end_date",
	"status",
	"original_budget_cents",
	"revised_budget_cents",
	"forecast_at_completion_cents",
	"billed_to_date_cents",
	"recognised_revenue_cents",
	"percent_complete",
	"risk_level",
	"currency_code",
	"description",
	"metadata_",
	"created_at",
	"updated_at",
]
PROJECT_LABELS = {
	"program_id": "Program",
	"code": "Project Code",
	"name": "Project Name",
	"project_type": "Project Type",
	"customer_id": "Customer",
	"owner_id": "Project Manager",
	"start_date": "Start Date",
	"end_date": "End Date",
	"status": "Status",
	"original_budget_cents": "Original Budget (cents)",
	"revised_budget_cents": "Revised Budget (cents)",
	"forecast_at_completion_cents": "Forecast at Completion (cents)",
	"billed_to_date_cents": "Billed to Date (cents)",
	"recognised_revenue_cents": "Recognised Revenue (cents)",
	"percent_complete": "Percent Complete",
	"risk_level": "Risk Level",
	"currency_code": "Currency",
	"description": "Description",
	"metadata_": "Metadata",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

WBS_COLUMNS = [
	"project_id",
	"parent_id",
	"code",
	"name",
	"element_type",
	"planned_start",
	"planned_end",
	"actual_start",
	"actual_end",
	"planned_hours",
	"actual_hours",
	"planned_cost_cents",
	"actual_cost_cents",
	"status",
	"predecessor_ids",
	"notes",
	"created_at",
	"updated_at",
]
WBS_LABELS = {
	"project_id": "Project",
	"parent_id": "Parent WBS Element",
	"code": "WBS Code",
	"name": "WBS Name",
	"element_type": "Element Type",
	"planned_start": "Planned Start",
	"planned_end": "Planned End",
	"actual_start": "Actual Start",
	"actual_end": "Actual End",
	"planned_hours": "Planned Hours",
	"actual_hours": "Actual Hours",
	"planned_cost_cents": "Planned Cost (cents)",
	"actual_cost_cents": "Actual Cost (cents)",
	"status": "Status",
	"predecessor_ids": "Predecessors",
	"notes": "Notes",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

RESOURCE_COLUMNS = [
	"project_id",
	"employee_id",
	"role",
	"allocated_hours",
	"actual_hours",
	"bill_rate_cents_per_hour",
	"cost_rate_cents_per_hour",
	"start_date",
	"end_date",
	"is_active",
	"created_at",
	"updated_at",
]
RESOURCE_LABELS = {
	"project_id": "Project",
	"employee_id": "Employee",
	"role": "Role",
	"allocated_hours": "Allocated Hours",
	"actual_hours": "Actual Hours",
	"bill_rate_cents_per_hour": "Bill Rate / Hour (cents)",
	"cost_rate_cents_per_hour": "Cost Rate / Hour (cents)",
	"start_date": "Start Date",
	"end_date": "End Date",
	"is_active": "Active",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

TIMESHEET_COLUMNS = [
	"project_id",
	"wbs_element_id",
	"employee_id",
	"work_date",
	"hours",
	"description",
	"status",
	"cost_cents",
	"bill_amount_cents",
	"approved_by",
	"approved_at",
	"invoice_id",
	"created_at",
	"updated_at",
]
TIMESHEET_LABELS = {
	"project_id": "Project",
	"wbs_element_id": "WBS Element",
	"employee_id": "Employee",
	"work_date": "Work Date",
	"hours": "Hours",
	"description": "Description",
	"status": "Status",
	"cost_cents": "Cost (cents)",
	"bill_amount_cents": "Bill Amount (cents)",
	"approved_by": "Approved By",
	"approved_at": "Approved At",
	"invoice_id": "Invoice",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

MILESTONE_COLUMNS = [
	"project_id",
	"name",
	"due_date",
	"achieved_date",
	"amount_cents",
	"status",
	"invoice_id",
	"notes",
	"created_at",
	"updated_at",
]
MILESTONE_LABELS = {
	"project_id": "Project",
	"name": "Milestone",
	"due_date": "Due Date",
	"achieved_date": "Achieved Date",
	"amount_cents": "Amount (cents)",
	"status": "Status",
	"invoice_id": "Invoice",
	"notes": "Notes",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

RISK_COLUMNS = [
	"project_id",
	"title",
	"description",
	"probability",
	"impact",
	"risk_score",
	"mitigation",
	"risk_owner_id",
	"status",
	"review_date",
	"created_at",
	"updated_at",
]
RISK_LABELS = {
	"project_id": "Project",
	"title": "Risk Title",
	"description": "Description",
	"probability": "Probability",
	"impact": "Impact",
	"risk_score": "Risk Score",
	"mitigation": "Mitigation",
	"risk_owner_id": "Risk Owner",
	"status": "Status",
	"review_date": "Review Date",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

CHANGE_ORDER_COLUMNS = [
	"project_id",
	"co_number",
	"description",
	"budget_delta_cents",
	"schedule_delta_days",
	"status",
	"submitted_by",
	"submitted_at",
	"approved_by",
	"approved_at",
	"rejection_reason",
	"created_at",
	"updated_at",
]
CHANGE_ORDER_LABELS = {
	"project_id": "Project",
	"co_number": "Change Order Number",
	"description": "Description",
	"budget_delta_cents": "Budget Delta (cents)",
	"schedule_delta_days": "Schedule Delta (days)",
	"status": "Status",
	"submitted_by": "Submitted By",
	"submitted_at": "Submitted At",
	"approved_by": "Approved By",
	"approved_at": "Approved At",
	"rejection_reason": "Rejection Reason",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

INVOICE_COLUMNS = [
	"project_id",
	"invoice_number",
	"invoice_type",
	"invoice_date",
	"due_date",
	"amount_cents",
	"tax_cents",
	"total_cents",
	"status",
	"paid_at",
	"gl_journal_id",
	"notes",
	"created_at",
	"updated_at",
]
INVOICE_LABELS = {
	"project_id": "Project",
	"invoice_number": "Invoice Number",
	"invoice_type": "Invoice Type",
	"invoice_date": "Invoice Date",
	"due_date": "Due Date",
	"amount_cents": "Amount (cents)",
	"tax_cents": "Tax (cents)",
	"total_cents": "Total (cents)",
	"status": "Status",
	"paid_at": "Paid At",
	"gl_journal_id": "GL Journal",
	"notes": "Notes",
	"created_at": "Created At",
	"updated_at": "Updated At",
}


class ProgramView(BaseERPModelView):
	"""CRUD view for project programmes."""

	datamodel = SQLAInterface(Program)
	route_base = "/projects/programs"
	list_columns = ["code", "name", "owner_id", "status", "budget_cents", "currency_code"]
	show_columns = PROGRAM_COLUMNS
	label_columns = PROGRAM_LABELS
	add_columns = ["code", "name", "owner_id", "status", "budget_cents", "currency_code", "description"]
	edit_columns = add_columns
	search_columns = ["code", "name", "status", "description"]
	page_size = 25


class ProjectView(BaseERPModelView):
	"""CRUD view for projects."""

	datamodel = SQLAInterface(Project)
	route_base = "/projects/projects"
	list_columns = ["code", "name", "project_type", "customer_id", "owner_id", "status", "percent_complete", "risk_level"]
	show_columns = PROJECT_COLUMNS
	label_columns = PROJECT_LABELS
	add_columns = [
		"program_id",
		"code",
		"name",
		"project_type",
		"customer_id",
		"owner_id",
		"start_date",
		"end_date",
		"status",
		"original_budget_cents",
		"revised_budget_cents",
		"risk_level",
		"currency_code",
		"description",
		"metadata_",
	]
	edit_columns = [
		"program_id",
		"name",
		"project_type",
		"customer_id",
		"owner_id",
		"start_date",
		"end_date",
		"status",
		"revised_budget_cents",
		"forecast_at_completion_cents",
		"billed_to_date_cents",
		"recognised_revenue_cents",
		"percent_complete",
		"risk_level",
		"currency_code",
		"description",
		"metadata_",
	]
	search_columns = ["code", "name", "project_type", "status", "risk_level", "description"]
	page_size = 25


class WBSElementView(BaseERPModelView):
	"""CRUD view for work breakdown structure elements."""

	datamodel = SQLAInterface(WBSElement)
	route_base = "/projects/wbs"
	list_columns = ["project_id", "code", "name", "element_type", "planned_end", "status", "planned_hours", "actual_hours"]
	show_columns = WBS_COLUMNS
	label_columns = WBS_LABELS
	add_columns = [
		"project_id",
		"parent_id",
		"code",
		"name",
		"element_type",
		"planned_start",
		"planned_end",
		"planned_hours",
		"planned_cost_cents",
		"status",
		"predecessor_ids",
		"notes",
	]
	edit_columns = [
		"parent_id",
		"code",
		"name",
		"element_type",
		"planned_start",
		"planned_end",
		"actual_start",
		"actual_end",
		"planned_hours",
		"actual_hours",
		"planned_cost_cents",
		"actual_cost_cents",
		"status",
		"predecessor_ids",
		"notes",
	]
	search_columns = ["code", "name", "element_type", "status", "notes"]
	page_size = 25


class ProjectResourceView(BaseERPModelView):
	"""CRUD view for project resource allocations."""

	datamodel = SQLAInterface(ProjectResource)
	route_base = "/projects/resources"
	list_columns = ["project_id", "employee_id", "role", "allocated_hours", "actual_hours", "start_date", "end_date", "is_active"]
	show_columns = RESOURCE_COLUMNS
	label_columns = RESOURCE_LABELS
	add_columns = [
		"project_id",
		"employee_id",
		"role",
		"allocated_hours",
		"bill_rate_cents_per_hour",
		"cost_rate_cents_per_hour",
		"start_date",
		"end_date",
		"is_active",
	]
	edit_columns = [
		"role",
		"allocated_hours",
		"actual_hours",
		"bill_rate_cents_per_hour",
		"cost_rate_cents_per_hour",
		"start_date",
		"end_date",
		"is_active",
	]
	search_columns = ["role", "is_active"]
	page_size = 25


class ProjectTimesheetView(BaseERPModelView):
	"""CRUD view for project timesheets."""

	datamodel = SQLAInterface(ProjectTimesheet)
	route_base = "/projects/timesheets"
	list_columns = ["project_id", "employee_id", "work_date", "hours", "status", "bill_amount_cents", "invoice_id"]
	show_columns = TIMESHEET_COLUMNS
	label_columns = TIMESHEET_LABELS
	add_columns = ["project_id", "wbs_element_id", "employee_id", "work_date", "hours", "description", "status"]
	edit_columns = [
		"wbs_element_id",
		"work_date",
		"hours",
		"description",
		"status",
		"cost_cents",
		"bill_amount_cents",
		"approved_by",
		"approved_at",
		"invoice_id",
	]
	search_columns = ["description", "status"]
	page_size = 25


class ProjectMilestoneView(BaseERPModelView):
	"""CRUD view for project milestones."""

	datamodel = SQLAInterface(ProjectMilestone)
	route_base = "/projects/milestones"
	list_columns = ["project_id", "name", "due_date", "achieved_date", "amount_cents", "status"]
	show_columns = MILESTONE_COLUMNS
	label_columns = MILESTONE_LABELS
	add_columns = ["project_id", "name", "due_date", "amount_cents", "status", "notes"]
	edit_columns = ["name", "due_date", "achieved_date", "amount_cents", "status", "invoice_id", "notes"]
	search_columns = ["name", "status", "notes"]
	page_size = 25


class ProjectRiskView(BaseERPModelView):
	"""CRUD view for project risk register entries."""

	datamodel = SQLAInterface(ProjectRisk)
	route_base = "/projects/risks"
	list_columns = ["project_id", "title", "probability", "impact", "risk_score", "status", "review_date"]
	show_columns = RISK_COLUMNS
	label_columns = RISK_LABELS
	add_columns = [
		"project_id",
		"title",
		"description",
		"probability",
		"impact",
		"risk_score",
		"mitigation",
		"risk_owner_id",
		"status",
		"review_date",
	]
	edit_columns = add_columns
	search_columns = ["title", "description", "mitigation", "status"]
	page_size = 25


class ChangeOrderView(BaseERPModelView):
	"""CRUD view for project change orders."""

	datamodel = SQLAInterface(ChangeOrder)
	route_base = "/projects/change-orders"
	list_columns = ["project_id", "co_number", "budget_delta_cents", "schedule_delta_days", "status", "submitted_at", "approved_at"]
	show_columns = CHANGE_ORDER_COLUMNS
	label_columns = CHANGE_ORDER_LABELS
	add_columns = ["project_id", "co_number", "description", "budget_delta_cents", "schedule_delta_days", "status", "submitted_by", "submitted_at"]
	edit_columns = [
		"description",
		"budget_delta_cents",
		"schedule_delta_days",
		"status",
		"submitted_by",
		"submitted_at",
		"approved_by",
		"approved_at",
		"rejection_reason",
	]
	search_columns = ["co_number", "description", "status", "rejection_reason"]
	page_size = 25


class ProjectInvoiceView(BaseERPModelView):
	"""CRUD view for project invoices."""

	datamodel = SQLAInterface(ProjectInvoice)
	route_base = "/projects/invoices"
	list_columns = ["project_id", "invoice_number", "invoice_type", "invoice_date", "due_date", "total_cents", "status"]
	show_columns = INVOICE_COLUMNS
	label_columns = INVOICE_LABELS
	add_columns = [
		"project_id",
		"invoice_number",
		"invoice_type",
		"invoice_date",
		"due_date",
		"amount_cents",
		"tax_cents",
		"total_cents",
		"status",
		"notes",
	]
	edit_columns = [
		"invoice_type",
		"invoice_date",
		"due_date",
		"amount_cents",
		"tax_cents",
		"total_cents",
		"status",
		"paid_at",
		"gl_journal_id",
		"notes",
	]
	search_columns = ["invoice_number", "invoice_type", "status", "notes"]
	page_size = 25


class ProjectPortfolioReportView(BaseERPView):
	"""Project portfolio KPI report."""

	route_base = "/projects/reports/portfolio"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id") or self._tenant_id()
		status = request.args.get("status") or None
		rows = ProjectService.get_project_portfolio(session, status=status, tenant_id=tenant_id)
		total_budget = sum(int(row.get("revised_budget_cents") or 0) for row in rows)
		total_eac = sum(int(row.get("forecast_at_completion_cents") or 0) for row in rows)
		total_billed = sum(int(row.get("billed_to_date_cents") or 0) for row in rows)
		high_risk = sum(1 for row in rows if row.get("risk_level") in {"HIGH", "CRITICAL"})
		kpi_html = self.kpi_cards([
			{"label": "Projects", "value": len(rows), "format": "integer", "color": "#1a56db", "icon": "fa-briefcase"},
			{"label": "Revised Budget", "value": total_budget // 100, "format": "currency", "color": "#057a55", "icon": "fa-money"},
			{"label": "EAC", "value": total_eac // 100, "format": "currency", "color": "#7e3af2", "icon": "fa-line-chart"},
			{"label": "High Risk", "value": high_risk, "format": "integer", "color": "#c81e1e", "icon": "fa-exclamation-triangle"},
		])
		table_rows = [
			{
				"code": row.get("code"),
				"name": row.get("name"),
				"status": row.get("status"),
				"percent_complete": row.get("percent_complete"),
				"risk_level": row.get("risk_level"),
				"budget": _fmt_cents(row.get("revised_budget_cents")),
				"eac": _fmt_cents(row.get("forecast_at_completion_cents")),
				"vac": _fmt_cents(row.get("variance_at_completion_cents")),
				"billed": _fmt_cents(row.get("billed_to_date_cents")),
			}
			for row in rows
		]
		table_html = _table(
			["Code", "Name", "Status", "Complete", "Risk", "Budget", "EAC", "VAC", "Billed"],
			table_rows,
			["code", "name", "status", "percent_complete", "risk_level", "budget", "eac", "vac", "billed"],
		)
		return _page("Project Portfolio", kpi_html, table_html)


class EVMReportView(BaseERPView):
	"""Earned value management KPI report."""

	route_base = "/projects/reports/evm"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id") or self._tenant_id()
		project_id = request.args.get("project_id", "")
		as_of = date.fromisoformat(request.args.get("as_of_date") or date.today().isoformat())
		if not project_id:
			kpi_html = self.kpi_cards([
				{"label": "Project Required", "value": 0, "format": "integer", "color": "#c81e1e", "icon": "fa-exclamation-triangle"},
			])
			table_html = "<p class='text-muted'>Provide ?project_id= to calculate EVM for a project.</p>"
			return _page("EVM Dashboard", kpi_html, table_html)
		result = ProjectService.calculate_evm(session, project_id, as_of, tenant_id)
		kpi_html = self.kpi_cards([
			{"label": "CPI", "value": result["CPI"], "format": "number", "color": "#057a55", "icon": "fa-tachometer"},
			{"label": "SPI", "value": result["SPI"], "format": "number", "color": "#1a56db", "icon": "fa-clock-o"},
			{"label": "EAC", "value": int(result["EAC"]) // 100, "format": "currency", "color": "#7e3af2", "icon": "fa-line-chart"},
			{"label": "Health", "value": result["health"], "format": "integer", "color": "#c81e1e" if result["health"] == "RED" else "#057a55", "icon": "fa-heartbeat"},
		])
		table_rows = [{
			"project_id": result["project_id"],
			"as_of_date": result["as_of_date"],
			"bac": _fmt_cents(result["BAC"]),
			"pv": _fmt_cents(result["PV"]),
			"ev": _fmt_cents(result["EV"]),
			"ac": _fmt_cents(result["AC"]),
			"cv": _fmt_cents(result["CV"]),
			"sv": _fmt_cents(result["SV"]),
			"vac": _fmt_cents(result["VAC"]),
		}]
		table_html = _table(
			["Project", "As Of", "BAC", "PV", "EV", "AC", "CV", "SV", "VAC"],
			table_rows,
			["project_id", "as_of_date", "bac", "pv", "ev", "ac", "cv", "sv", "vac"],
		)
		return _page("EVM Dashboard", kpi_html, table_html)


class ResourceUtilizationReportView(BaseERPView):
	"""Resource utilization KPI report."""

	route_base = "/projects/reports/utilization"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id") or self._tenant_id()
		to_date = date.fromisoformat(request.args.get("to_date") or date.today().isoformat())
		from_date = date.fromisoformat(request.args.get("from_date") or (to_date - timedelta(days=30)).isoformat())
		rows = ProjectService.get_resource_utilization(session, from_date, to_date, tenant_id)
		total_hours = sum(float(row.get("total_hours") or 0) for row in rows)
		total_bill = sum(int(row.get("total_bill_cents") or 0) for row in rows)
		avg_utilization = sum(float(row.get("utilization_pct") or 0) for row in rows) / len(rows) if rows else 0
		kpi_html = self.kpi_cards([
			{"label": "Resources", "value": len(rows), "format": "integer", "color": "#1a56db", "icon": "fa-users"},
			{"label": "Total Hours", "value": round(total_hours, 2), "format": "number", "color": "#057a55", "icon": "fa-clock-o"},
			{"label": "Avg Utilization", "value": round(avg_utilization, 2), "format": "percent", "color": "#7e3af2", "icon": "fa-tachometer"},
			{"label": "Billable Value", "value": total_bill // 100, "format": "currency", "color": "#d97706", "icon": "fa-money"},
		])
		table_rows = [
			{
				"employee_id": row.get("employee_id"),
				"total_hours": row.get("total_hours"),
				"utilization_pct": row.get("utilization_pct"),
				"project_count": row.get("project_count"),
				"total_cost": _fmt_cents(row.get("total_cost_cents")),
				"total_bill": _fmt_cents(row.get("total_bill_cents")),
			}
			for row in rows
		]
		table_html = _table(
			["Employee", "Hours", "Utilization", "Projects", "Cost", "Billable"],
			table_rows,
			["employee_id", "total_hours", "utilization_pct", "project_count", "total_cost", "total_bill"],
		)
		return _page("Resource Utilization", kpi_html, table_html)


__all__ = [
	"ProgramView",
	"ProjectView",
	"WBSElementView",
	"ProjectResourceView",
	"ProjectTimesheetView",
	"ProjectMilestoneView",
	"ProjectRiskView",
	"ChangeOrderView",
	"ProjectInvoiceView",
	"ProjectPortfolioReportView",
	"EVMReportView",
	"ResourceUtilizationReportView",
]
