"""REST APIs for ERP models in this plugin."""
from __future__ import annotations

from pgappforge.api import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface

from .models import (
	Program,
	Project,
	WBSElement,
	ProjectResource,
	ProjectTimesheet,
	ProjectMilestone,
	ProjectRisk,
	ChangeOrder,
	ProjectInvoice,
)


class ProgramRestApi(ModelRestApi):
	resource_name = 'erp/projects/program'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(Program)
	list_columns = [
		'id',
		'tenant_id',
		'code',
		'name',
		'owner_id',
		'status',
		'budget_cents',
		'currency_code',
		'description',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'code',
		'name',
		'owner_id',
		'status',
		'budget_cents',
		'currency_code',
		'description',
	]
	edit_columns = add_columns
	search_columns = [
		'code',
		'name',
		'owner_id',
		'status',
		'currency_code',
		'description',
	]


class ProjectRestApi(ModelRestApi):
	resource_name = 'erp/projects/project'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(Project)
	list_columns = [
		'id',
		'tenant_id',
		'program_id',
		'code',
		'name',
		'project_type',
		'customer_id',
		'owner_id',
		'start_date',
		'end_date',
		'status',
		'original_budget_cents',
		'revised_budget_cents',
		'forecast_at_completion_cents',
		'billed_to_date_cents',
		'recognised_revenue_cents',
		'percent_complete',
		'risk_level',
		'currency_code',
		'description',
		'metadata_',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'program_id',
		'code',
		'name',
		'project_type',
		'customer_id',
		'owner_id',
		'start_date',
		'end_date',
		'status',
		'original_budget_cents',
		'revised_budget_cents',
		'forecast_at_completion_cents',
		'billed_to_date_cents',
		'recognised_revenue_cents',
		'percent_complete',
		'risk_level',
		'currency_code',
		'description',
		'metadata_',
	]
	edit_columns = add_columns
	search_columns = [
		'code',
		'name',
		'project_type',
		'customer_id',
		'owner_id',
		'status',
		'currency_code',
		'description',
	]


class WBSElementRestApi(ModelRestApi):
	resource_name = 'erp/projects/wbs_element'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(WBSElement)
	list_columns = [
		'id',
		'tenant_id',
		'project_id',
		'parent_id',
		'code',
		'name',
		'element_type',
		'planned_start',
		'planned_end',
		'actual_start',
		'actual_end',
		'planned_hours',
		'actual_hours',
		'planned_cost_cents',
		'actual_cost_cents',
		'status',
		'predecessor_ids',
		'notes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'project_id',
		'parent_id',
		'code',
		'name',
		'element_type',
		'planned_start',
		'planned_end',
		'actual_start',
		'actual_end',
		'planned_hours',
		'actual_hours',
		'planned_cost_cents',
		'actual_cost_cents',
		'status',
		'predecessor_ids',
		'notes',
	]
	edit_columns = add_columns
	search_columns = [
		'code',
		'name',
		'element_type',
		'status',
		'notes',
	]


class ProjectResourceRestApi(ModelRestApi):
	resource_name = 'erp/projects/project_resource'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(ProjectResource)
	list_columns = [
		'id',
		'tenant_id',
		'project_id',
		'employee_id',
		'role',
		'allocated_hours',
		'actual_hours',
		'bill_rate_cents_per_hour',
		'cost_rate_cents_per_hour',
		'start_date',
		'end_date',
		'is_active',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'project_id',
		'employee_id',
		'role',
		'allocated_hours',
		'actual_hours',
		'bill_rate_cents_per_hour',
		'cost_rate_cents_per_hour',
		'start_date',
		'end_date',
		'is_active',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'role',
	]


class ProjectTimesheetRestApi(ModelRestApi):
	resource_name = 'erp/projects/project_timesheet'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(ProjectTimesheet)
	list_columns = [
		'id',
		'tenant_id',
		'project_id',
		'wbs_element_id',
		'employee_id',
		'work_date',
		'hours',
		'description',
		'status',
		'cost_cents',
		'bill_amount_cents',
		'approved_by',
		'approved_at',
		'invoice_id',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'project_id',
		'wbs_element_id',
		'employee_id',
		'work_date',
		'hours',
		'description',
		'status',
		'cost_cents',
		'bill_amount_cents',
		'approved_by',
		'approved_at',
		'invoice_id',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'description',
		'status',
	]


class ProjectMilestoneRestApi(ModelRestApi):
	resource_name = 'erp/projects/project_milestone'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(ProjectMilestone)
	list_columns = [
		'id',
		'tenant_id',
		'project_id',
		'name',
		'due_date',
		'achieved_date',
		'amount_cents',
		'status',
		'invoice_id',
		'notes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'project_id',
		'name',
		'due_date',
		'achieved_date',
		'amount_cents',
		'status',
		'invoice_id',
		'notes',
	]
	edit_columns = add_columns
	search_columns = [
		'name',
		'status',
		'notes',
	]


class ProjectRiskRestApi(ModelRestApi):
	resource_name = 'erp/projects/project_risk'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(ProjectRisk)
	list_columns = [
		'id',
		'tenant_id',
		'project_id',
		'title',
		'description',
		'probability',
		'impact',
		'risk_score',
		'mitigation',
		'risk_owner_id',
		'status',
		'review_date',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'project_id',
		'title',
		'description',
		'probability',
		'impact',
		'risk_score',
		'mitigation',
		'risk_owner_id',
		'status',
		'review_date',
	]
	edit_columns = add_columns
	search_columns = [
		'title',
		'description',
		'risk_owner_id',
		'status',
	]


class ChangeOrderRestApi(ModelRestApi):
	resource_name = 'erp/projects/change_order'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(ChangeOrder)
	list_columns = [
		'id',
		'tenant_id',
		'project_id',
		'co_number',
		'description',
		'budget_delta_cents',
		'schedule_delta_days',
		'status',
		'submitted_by',
		'submitted_at',
		'approved_by',
		'approved_at',
		'rejection_reason',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'project_id',
		'co_number',
		'description',
		'budget_delta_cents',
		'schedule_delta_days',
		'status',
		'submitted_by',
		'submitted_at',
		'approved_by',
		'approved_at',
		'rejection_reason',
	]
	edit_columns = add_columns
	search_columns = [
		'co_number',
		'description',
		'status',
		'rejection_reason',
	]


class ProjectInvoiceRestApi(ModelRestApi):
	resource_name = 'erp/projects/project_invoice'
	openapi_spec_tag = 'Projects'
	datamodel = SQLAInterface(ProjectInvoice)
	list_columns = [
		'id',
		'tenant_id',
		'project_id',
		'invoice_number',
		'invoice_type',
		'invoice_date',
		'due_date',
		'amount_cents',
		'tax_cents',
		'total_cents',
		'status',
		'paid_at',
		'gl_journal_id',
		'notes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'project_id',
		'invoice_number',
		'invoice_type',
		'invoice_date',
		'due_date',
		'amount_cents',
		'tax_cents',
		'total_cents',
		'status',
		'paid_at',
		'gl_journal_id',
		'notes',
	]
	edit_columns = add_columns
	search_columns = [
		'invoice_number',
		'invoice_type',
		'status',
		'notes',
	]
