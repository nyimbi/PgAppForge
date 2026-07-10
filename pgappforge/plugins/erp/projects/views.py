"""
pgappforge/plugins/erp/projects/views.py

Flask-AppBuilder views for the Projects / PSA plugin.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Any

import sqlalchemy as sa
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


def _table(
	headers: list[str],
	rows: list[dict[str, Any]],
	columns: list[str],
	raw_columns: set[str] | None = None,
) -> str:
	raw_columns = raw_columns or set()
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
		+ "".join(
			f"<td>{'' if row.get(col) is None else str(row.get(col))}</td>"
			if col in raw_columns else f"<td>{_fmt(row.get(col))}</td>"
			for col in columns
		)
		+ "</tr>"
		for row in rows
	)
	head = "".join(f"<th>{escape(header)}</th>" for header in headers)
	return (
		"<table class='table table-bordered table-condensed table-hover'>"
		f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
	)


def _label_badge(text: str, color: str) -> str:
	return f"<span class='label label-{escape(color)}'>{escape(text)}</span>"


def _ratio(numerator: Any, denominator: Any) -> float:
	try:
		num = float(numerator or 0)
		den = float(denominator or 0)
	except (TypeError, ValueError):
		return 0.0
	if den <= 0:
		return 0.0
	return num / den


def _index_badge(value: float) -> str:
	if value >= 1.0:
		return _label_badge(f"{value:.2f}", "success")
	if value < 0.8:
		return _label_badge(f"{value:.2f}", "danger")
	return _label_badge(f"{value:.2f}", "warning")


def _utilization_badge(utilization_pct: float) -> str:
	if utilization_pct > 100:
		return _label_badge("Overallocated", "danger")
	if utilization_pct >= 80:
		return _label_badge("Healthy", "success")
	if utilization_pct < 50:
		return _label_badge("Underused", "warning")
	return _label_badge("Available", "default")


def _quarter_bounds(today: date) -> tuple[date, date]:
	start_month = ((today.month - 1) // 3) * 3 + 1
	quarter_start = date(today.year, start_month, 1)
	if start_month == 10:
		quarter_end = date(today.year, 12, 31)
	else:
		quarter_end = date(today.year, start_month + 3, 1) - timedelta(days=1)
	return quarter_start, quarter_end


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
	"budget_cents": "Budget",
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
	"original_budget_cents": "Original Budget",
	"revised_budget_cents": "Revised Budget",
	"forecast_at_completion_cents": "Forecast at Completion",
	"billed_to_date_cents": "Billed to Date",
	"recognised_revenue_cents": "Recognised Revenue",
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
	"planned_cost_cents": "Planned Cost",
	"actual_cost_cents": "Actual Cost",
	"status": "Status",
	"predecessor_ids": "Predecessors",
	"notes": "Notes",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

# ProjectResource uses employee_id as the resource key; no resource_id field exists.
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
	"bill_rate_cents_per_hour": "Bill Rate / Hour",
	"cost_rate_cents_per_hour": "Cost Rate / Hour",
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
	"cost_cents": "Cost",
	"bill_amount_cents": "Bill Amount",
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
	"amount_cents": "Amount",
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
	"budget_delta_cents": "Budget Delta",
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
	"amount_cents": "Amount",
	"tax_cents": "Tax",
	"total_cents": "Total",
	"status": "Status",
	"paid_at": "Paid At",
	"gl_journal_id": "GL Journal",
	"notes": "Notes",
	"created_at": "Created At",
	"updated_at": "Updated At",
}

PORTFOLIO_REPORT_LABELS = {
	"active_projects": "Active Projects",
	"on_schedule_pct": "On Schedule",
	"on_budget_pct": "On Budget",
	"total_budget_cents": "Total Budget",
	"total_spent_cents": "Total Spent",
	"status": "Status",
}

EVM_REPORT_LABELS = {
	"project_id": "Project",
	"period": "Period",
	"pv_cents": "Planned Value",
	"ev_cents": "Earned Value",
	"ac_cents": "Actual Cost",
	"cpi": "CPI",
	"spi": "SPI",
}

UTILIZATION_REPORT_LABELS = {
	"employee_id": "Resource",
	"allocated_hours": "Allocated Hours",
	"actual_hours": "Actual Hours",
	"utilization_pct": "Utilization",
	"status": "Status",
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
	search_columns = ["code", "name", "status", "created_at", "updated_at", "description"]
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
	search_columns = ["code", "name", "project_type", "status", "start_date", "end_date", "risk_level", "description"]
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
	search_columns = ["code", "name", "element_type", "status", "planned_start", "planned_end", "actual_start", "actual_end", "notes"]
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
	search_columns = ["role", "start_date", "end_date", "is_active"]
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
	search_columns = ["work_date", "description", "status"]
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
	search_columns = ["name", "status", "due_date", "achieved_date", "notes"]
	page_size = 25

	@expose("/overdue/")
	@has_access
	def overdue_milestones(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id") or self._tenant_id()
		today = date.today()
		# ProjectMilestone has no COMPLETED status; exclude all terminal equivalents.
		rows = session.execute(
			sa.select(ProjectMilestone)
			.where(
				ProjectMilestone.tenant_id == tenant_id,
				ProjectMilestone.due_date < today,
				sa.func.lower(ProjectMilestone.status).notin_(["completed", "achieved", "invoiced", "paid"]),
			)
			.order_by(ProjectMilestone.due_date.asc())
		).scalars().all()
		kpi_html = self.kpi_cards([
			{"label": "Overdue Milestones", "value": len(rows), "format": "integer", "color": "#c81e1e", "icon": "fa-flag"},
		])
		table_rows = [
			{
				"project_id": row.project_id,
				"name": row.name,
				"due_date": row.due_date,
				"amount": _fmt_cents(row.amount_cents),
				"status": _label_badge(row.status, "danger"),
				"notes": row.notes,
			}
			for row in rows
		]
		table_html = _table(
			["Project", "Milestone", "Due Date", "Amount", "Status", "Notes"],
			table_rows,
			["project_id", "name", "due_date", "amount", "status", "notes"],
			raw_columns={"status"},
		)
		return _page("Overdue Milestones", kpi_html, table_html)


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
	search_columns = ["title", "description", "mitigation", "status", "review_date"]
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
	search_columns = ["co_number", "description", "status", "submitted_at", "approved_at", "rejection_reason"]
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
	search_columns = ["invoice_number", "invoice_type", "invoice_date", "due_date", "status", "paid_at", "notes"]
	page_size = 25


class ProjectPortfolioReportView(BaseERPView):
	"""Project portfolio KPI report."""

	route_base = "/projects/reports/portfolio"
	default_view = "index"
	show_columns = ["active_projects", "on_schedule_pct", "on_budget_pct", "total_budget_cents", "total_spent_cents", "status"]
	label_columns = PORTFOLIO_REPORT_LABELS
	search_columns = ["status"]

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id") or self._tenant_id()
		status = request.args.get("status") or None
		rows = ProjectService.get_project_portfolio(session, status=status, tenant_id=tenant_id)
		today = date.today()
		all_projects = session.execute(
			sa.select(Project).where(Project.tenant_id == tenant_id)
		).scalars().all()
		status_counts = {key: 0 for key in ["PLANNING", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED"]}
		for project_status, count in session.execute(
			sa.select(Project.status, sa.func.count(Project.id))
			.where(Project.tenant_id == tenant_id)
			.group_by(Project.status)
		).all():
			status_counts[str(project_status or "").upper()] = int(count or 0)

		# Project has no total_spent_cents field; WBS actual_cost_cents is the spend source.
		spent_rows = session.execute(
			sa.select(
				WBSElement.project_id,
				sa.func.coalesce(sa.func.sum(WBSElement.actual_cost_cents), 0).label("spent_cents"),
			)
			.where(WBSElement.tenant_id == tenant_id)
			.group_by(WBSElement.project_id)
		).all()
		spent_by_project = {
			str(row.project_id): int(row.spent_cents or 0)
			for row in spent_rows
		}

		total_budget = sum(int(project.revised_budget_cents or project.original_budget_cents or 0) for project in all_projects)
		total_spent = sum(spent_by_project.get(str(project.id), 0) for project in all_projects)
		total_eac = sum(int(project.forecast_at_completion_cents or project.original_budget_cents or 0) for project in all_projects)
		total_billed = sum(int(project.billed_to_date_cents or 0) for project in all_projects)
		high_risk = sum(1 for project in all_projects if project.risk_level in {"HIGH", "CRITICAL"})
		total_projects = len(all_projects)
		# Project has end_date, not planned_end_date.
		on_time_count = sum(
			1
			for project in all_projects
			if str(project.status or "").upper() == "COMPLETED" or project.end_date >= today
		)
		on_budget_count = sum(
			1
			for project in all_projects
			if spent_by_project.get(str(project.id), 0) <= int(project.revised_budget_cents or project.original_budget_cents or 0)
		)
		active_count = status_counts.get("ACTIVE", 0)
		on_schedule_pct = (on_time_count / total_projects * 100) if total_projects else 0
		on_budget_pct = (on_budget_count / total_projects * 100) if total_projects else 0
		kpi_html = self.kpi_cards([
			{"label": "Active Projects", "value": active_count, "format": "integer", "color": "#1a56db", "icon": "fa-briefcase"},
			{"label": "On Schedule", "value": round(on_schedule_pct, 1), "format": "percent", "color": "#057a55", "icon": "fa-clock-o"},
			{"label": "On Budget", "value": round(on_budget_pct, 1), "format": "percent", "color": "#057a55", "icon": "fa-money"},
			{"label": "Total Budget", "value": total_budget // 100, "format": "currency", "color": "#057a55", "icon": "fa-money"},
			{"label": "Total Spent", "value": total_spent // 100, "format": "currency", "color": "#d97706", "icon": "fa-credit-card"},
			{"label": "EAC", "value": total_eac // 100, "format": "currency", "color": "#7e3af2", "icon": "fa-line-chart"},
			{"label": "High Risk", "value": high_risk, "format": "integer", "color": "#c81e1e", "icon": "fa-exclamation-triangle"},
		])
		scorecard_html = (
			"<div class='alert alert-info'>"
			f"{active_count} projects active, {on_schedule_pct:.1f}% on schedule, {on_budget_pct:.1f}% on budget. "
			f"Budget {_fmt_cents(total_budget)}; spent {_fmt_cents(total_spent)}; billed {_fmt_cents(total_billed)}."
			"</div>"
		)
		status_table_rows = [
			{"status": status_name.title().replace("_", " "), "count": count}
			for status_name, count in status_counts.items()
		]
		status_table_html = "<h4>Portfolio Health by Status</h4>" + _table(
			["Status", "Projects"],
			status_table_rows,
			["status", "count"],
		)
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
		return _page("Project Portfolio", kpi_html, scorecard_html + status_table_html + table_html)


class EVMReportView(BaseERPView):
	"""Earned value management KPI report."""

	route_base = "/projects/reports/evm"
	default_view = "index"
	show_columns = ["project_id", "period", "pv_cents", "ev_cents", "ac_cents", "cpi", "spi"]
	label_columns = EVM_REPORT_LABELS
	search_columns = ["project_id", "period"]

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id") or self._tenant_id()
		project_id = request.args.get("project_id", "")
		as_of = date.fromisoformat(request.args.get("as_of_date") or date.today().isoformat())
		portfolio_projects = session.execute(
			sa.select(Project).where(Project.tenant_id == tenant_id)
		).scalars().all()
		on_budget_count = 0
		over_budget_count = 0
		for project in portfolio_projects:
			budget = int(project.revised_budget_cents or project.original_budget_cents or 0)
			forecast = int(project.forecast_at_completion_cents or project.original_budget_cents or 0)
			if budget and forecast > budget:
				over_budget_count += 1
			else:
				on_budget_count += 1
		if not project_id:
			kpi_html = self.kpi_cards([
				{"label": "Project Required", "value": 0, "format": "integer", "color": "#c81e1e", "icon": "fa-exclamation-triangle"},
				{"label": "On Budget", "value": on_budget_count, "format": "integer", "color": "#057a55", "icon": "fa-check-circle"},
				{"label": "Over Budget", "value": over_budget_count, "format": "integer", "color": "#c81e1e", "icon": "fa-exclamation-triangle"},
			])
			table_html = "<p class='text-muted'>Provide ?project_id= to calculate EVM for a project.</p>"
			return _page("EVM Dashboard", kpi_html, table_html)
		period_days = max(1, min(int(request.args.get("period_days") or 7), 31))
		period_dates = [as_of - timedelta(days=period_days * offset) for offset in range(7, -1, -1)]
		series: list[dict[str, Any]] = []
		result: dict[str, Any] = {}
		# No EVMSnapshot/EVMMetric model exists; derive each period from current WBS state.
		for period_date in period_dates:
			result = ProjectService.calculate_evm(session, project_id, period_date, tenant_id)
			series.append({
				"period": period_date.isoformat(),
				"pv_cents": int(result["PV"]),
				"ev_cents": int(result["EV"]),
				"ac_cents": int(result["AC"]),
			})
		health_score = {"GREEN": 1, "AMBER": 0.75, "RED": 0}.get(str(result["health"]), 0)
		kpi_html = self.kpi_cards([
			{"label": "CPI", "value": result["CPI"], "format": "number", "color": "#057a55", "icon": "fa-tachometer"},
			{"label": "SPI", "value": result["SPI"], "format": "number", "color": "#1a56db", "icon": "fa-clock-o"},
			{"label": "EAC", "value": int(result["EAC"]) // 100, "format": "currency", "color": "#7e3af2", "icon": "fa-line-chart"},
			{"label": f"Health {result['health']}", "value": health_score, "format": "number", "color": "#c81e1e" if result["health"] == "RED" else "#057a55", "icon": "fa-heartbeat"},
			{"label": "On Budget", "value": on_budget_count, "format": "integer", "color": "#057a55", "icon": "fa-check-circle"},
			{"label": "Over Budget", "value": over_budget_count, "format": "integer", "color": "#c81e1e", "icon": "fa-exclamation-triangle"},
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
		series_rows = [
			{
				"period": row["period"],
				"pv": _fmt_cents(row["pv_cents"]),
				"ev": _fmt_cents(row["ev_cents"]),
				"ac": _fmt_cents(row["ac_cents"]),
				"cpi": _index_badge(_ratio(row["ev_cents"], row["ac_cents"])),
				"spi": _index_badge(_ratio(row["ev_cents"], row["pv_cents"])),
			}
			for row in series
		]
		series_html = "<h4>EVM Time Series</h4>" + _table(
			["Period", "PV", "EV", "AC", "CPI", "SPI"],
			series_rows,
			["period", "pv", "ev", "ac", "cpi", "spi"],
			raw_columns={"cpi", "spi"},
		)
		health_html = (
			"<div class='alert alert-info'>"
			f"Project health summary: {on_budget_count} on budget, {over_budget_count} over budget."
			"</div>"
		)
		return _page("EVM Dashboard", kpi_html, health_html + table_html + series_html)


class ResourceUtilizationReportView(BaseERPView):
	"""Resource utilization KPI report."""

	route_base = "/projects/reports/utilization"
	default_view = "index"
	show_columns = ["employee_id", "allocated_hours", "actual_hours", "utilization_pct", "status"]
	label_columns = UTILIZATION_REPORT_LABELS
	search_columns = ["employee_id", "status"]

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id") or self._tenant_id()
		to_date = date.fromisoformat(request.args.get("to_date") or date.today().isoformat())
		from_date = date.fromisoformat(request.args.get("from_date") or (to_date - timedelta(days=30)).isoformat())
		rows = ProjectService.get_resource_utilization(session, from_date, to_date, tenant_id)
		quarter_start, quarter_end = _quarter_bounds(date.today())
		# ProjectResource has employee_id as the resource identifier; no resource_id field exists.
		allocation_rows = session.execute(
			sa.select(
				ProjectResource.employee_id,
				sa.func.coalesce(sa.func.sum(ProjectResource.allocated_hours), 0).label("allocated_hours"),
				sa.func.coalesce(sa.func.sum(ProjectResource.actual_hours), 0).label("actual_hours"),
			)
			.where(
				ProjectResource.tenant_id == tenant_id,
				ProjectResource.start_date <= quarter_end,
				ProjectResource.end_date >= quarter_start,
			)
			.group_by(ProjectResource.employee_id)
			.order_by(ProjectResource.employee_id)
		).all()
		total_hours = sum(float(row.get("total_hours") or 0) for row in rows)
		total_bill = sum(int(row.get("total_bill_cents") or 0) for row in rows)
		avg_utilization = sum(float(row.get("utilization_pct") or 0) for row in rows) / len(rows) if rows else 0
		total_allocated = sum(float(row.allocated_hours or 0) for row in allocation_rows)
		total_actual = sum(float(row.actual_hours or 0) for row in allocation_rows)
		kpi_html = self.kpi_cards([
			{"label": "Resources", "value": len(allocation_rows), "format": "integer", "color": "#1a56db", "icon": "fa-users"},
			{"label": "Allocated Hours", "value": round(total_allocated, 2), "format": "number", "color": "#1a56db", "icon": "fa-calendar"},
			{"label": "Actual Hours", "value": round(total_actual, 2), "format": "number", "color": "#057a55", "icon": "fa-clock-o"},
			{"label": "Total Hours", "value": round(total_hours, 2), "format": "number", "color": "#057a55", "icon": "fa-clock-o"},
			{"label": "Avg Utilization", "value": round(avg_utilization, 2), "format": "percent", "color": "#7e3af2", "icon": "fa-tachometer"},
			{"label": "Billable Value", "value": total_bill // 100, "format": "currency", "color": "#d97706", "icon": "fa-money"},
		])
		allocation_table_rows = []
		for row in allocation_rows:
			allocated = float(row.allocated_hours or 0)
			actual = float(row.actual_hours or 0)
			utilization_pct = (actual / allocated * 100) if allocated else 0
			allocation_table_rows.append({
				"employee_id": row.employee_id,
				"allocated_hours": f"{allocated:.2f}",
				"actual_hours": f"{actual:.2f}",
				"utilization_pct": f"{utilization_pct:.1f}%",
				"status": _utilization_badge(utilization_pct),
			})
		allocation_table_html = (
			f"<h4>Current Quarter Allocation ({quarter_start.isoformat()} to {quarter_end.isoformat()})</h4>"
			+ _table(
				["Resource", "Allocated", "Actual", "Utilization", "Status"],
				allocation_table_rows,
				["employee_id", "allocated_hours", "actual_hours", "utilization_pct", "status"],
				raw_columns={"status"},
			)
		)
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
		return _page("Resource Utilization", kpi_html, allocation_table_html + "<h4>Approved Timesheet Utilization</h4>" + table_html)


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
