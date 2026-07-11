"""REST APIs for ERP models in this plugin."""
from __future__ import annotations

from pgappforge.api import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface

from .models import (
	Employee,
	EmployeeCompensation,
	EmployeeDocument,
	EmploymentContract,
	DisciplinaryCase,
	DisciplinaryAction,
	GrievanceCase,
	OnboardingPlan,
	EmployeeExit,
	OrgJobGrade,
	EmployeePositionHistory,
)


class EmployeeRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/employee'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(Employee)
	list_columns = [
		'id',
		'tenant_id',
		'employee_number',
		'party_id',
		'position_id',
		'entity_id',
		'org_unit_id',
		'manager_id',
		'employment_type',
		'employment_status',
		'start_date',
		'probation_end_date',
		'termination_date',
		'termination_type',
		'termination_reason',
		'rehire_eligible',
		'cost_center_code',
		'background_check_status',
		'background_check_provider',
		'background_check_ref',
		'national_id_encrypted',
		'tax_id_encrypted',
		'bank_account_iban_encrypted',
		'bank_bic',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_number',
		'party_id',
		'position_id',
		'entity_id',
		'org_unit_id',
		'manager_id',
		'employment_type',
		'employment_status',
		'start_date',
		'probation_end_date',
		'termination_date',
		'termination_type',
		'termination_reason',
		'rehire_eligible',
		'cost_center_code',
		'background_check_status',
		'background_check_provider',
		'background_check_ref',
		'national_id_encrypted',
		'tax_id_encrypted',
		'bank_account_iban_encrypted',
		'bank_bic',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_number',
		'party_id',
		'entity_id',
		'manager_id',
		'employment_type',
		'employment_status',
		'termination_type',
		'termination_reason',
		'cost_center_code',
		'background_check_status',
		'background_check_ref',
		'bank_account_iban_encrypted',
	]


class EmployeeCompensationRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/employee_compensation'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(EmployeeCompensation)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'effective_date',
		'pay_type',
		'amount_cents',
		'currency_code',
		'frequency',
		'grade_code',
		'reason',
		'approved_by',
		'approval_status',
		'approval_rejected_reason',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'effective_date',
		'pay_type',
		'amount_cents',
		'currency_code',
		'frequency',
		'grade_code',
		'reason',
		'approved_by',
		'approval_status',
		'approval_rejected_reason',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'pay_type',
		'currency_code',
		'frequency',
		'grade_code',
		'reason',
		'approval_status',
		'approval_rejected_reason',
	]


class EmployeeDocumentRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/employee_document'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(EmployeeDocument)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'document_type',
		'filename',
		'storage_url',
		'issued_date',
		'expiry_date',
		'is_verified',
		'version',
		'superseded_by_id',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'document_type',
		'filename',
		'storage_url',
		'issued_date',
		'expiry_date',
		'is_verified',
		'version',
		'superseded_by_id',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'document_type',
		'filename',
	]


class EmploymentContractRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/employment_contract'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(EmploymentContract)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'contract_type',
		'status',
		'offer_date',
		'accepted_date',
		'start_date',
		'end_date',
		'probation_end_date',
		'confirmed_date',
		'terminated_date',
		'notice_period_days',
		'notice_pay_in_lieu_cents',
		'amendments',
		'notes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'contract_type',
		'status',
		'offer_date',
		'accepted_date',
		'start_date',
		'end_date',
		'probation_end_date',
		'confirmed_date',
		'terminated_date',
		'notice_period_days',
		'notice_pay_in_lieu_cents',
		'amendments',
		'notes',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'contract_type',
		'status',
		'notice_period_days',
		'notes',
	]


class DisciplinaryCaseRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/disciplinary_case'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(DisciplinaryCase)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'case_number',
		'case_type',
		'status',
		'offence_description',
		'offence_date',
		'show_cause_issued_at',
		'show_cause_response',
		'show_cause_response_date',
		'hearing_date',
		'hearing_notes',
		'presiding_officer_id',
		'outcome',
		'outcome_date',
		'outcome_notes',
		'suspension_start_date',
		'suspension_end_date',
		'suspension_is_paid',
		'extra',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'case_number',
		'case_type',
		'status',
		'offence_description',
		'offence_date',
		'show_cause_issued_at',
		'show_cause_response',
		'show_cause_response_date',
		'hearing_date',
		'hearing_notes',
		'presiding_officer_id',
		'outcome',
		'outcome_date',
		'outcome_notes',
		'suspension_start_date',
		'suspension_end_date',
		'suspension_is_paid',
		'extra',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'case_number',
		'case_type',
		'status',
		'offence_description',
		'hearing_notes',
		'outcome',
		'outcome_date',
		'outcome_notes',
	]


class DisciplinaryActionRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/disciplinary_action'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(DisciplinaryAction)
	list_columns = [
		'id',
		'tenant_id',
		'case_id',
		'action_type',
		'issued_at',
		'issued_by',
		'notes',
		'letter_document_id',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'case_id',
		'action_type',
		'issued_at',
		'issued_by',
		'notes',
		'letter_document_id',
	]
	edit_columns = add_columns
	search_columns = [
		'action_type',
		'notes',
	]


class GrievanceCaseRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/grievance_case'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(GrievanceCase)
	list_columns = [
		'id',
		'tenant_id',
		'filed_by_employee_id',
		'respondent_employee_id',
		'assigned_to_id',
		'case_number',
		'grievance_type',
		'status',
		'description',
		'filed_date',
		'due_date',
		'acknowledged_date',
		'resolved_date',
		'closed_date',
		'resolution_notes',
		'escalation_reason',
		'escalated_to_id',
		'extra',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'filed_by_employee_id',
		'respondent_employee_id',
		'assigned_to_id',
		'case_number',
		'grievance_type',
		'status',
		'description',
		'filed_date',
		'due_date',
		'acknowledged_date',
		'resolved_date',
		'closed_date',
		'resolution_notes',
		'escalation_reason',
		'escalated_to_id',
		'extra',
	]
	edit_columns = add_columns
	search_columns = [
		'filed_by_employee_id',
		'respondent_employee_id',
		'case_number',
		'grievance_type',
		'status',
		'description',
		'resolution_notes',
		'escalation_reason',
	]


class OnboardingPlanRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/onboarding_plan'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(OnboardingPlan)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'template_id',
		'assigned_buddy_id',
		'induction_date',
		'target_completion_date',
		'completed_date',
		'status',
		'checklist_items',
		'extra',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'template_id',
		'assigned_buddy_id',
		'induction_date',
		'target_completion_date',
		'completed_date',
		'status',
		'checklist_items',
		'extra',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'status',
	]


class EmployeeExitRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/employee_exit'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(EmployeeExit)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'exit_type',
		'status',
		'resignation_date',
		'last_working_day',
		'exit_interview_date',
		'exit_reason',
		'severance_amount_cents',
		'notice_pay_in_lieu_cents',
		'final_settlement_amount_cents',
		'currency_code',
		'settlement_paid_date',
		'notice_period_days',
		'notice_waived',
		'notice_waiver_reason',
		'clearance_items',
		'cleared_by_id',
		'cleared_date',
		'closed_by_id',
		'closed_date',
		'certificate_issued',
		'certificate_issued_date',
		'extra',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'exit_type',
		'status',
		'resignation_date',
		'last_working_day',
		'exit_interview_date',
		'exit_reason',
		'severance_amount_cents',
		'notice_pay_in_lieu_cents',
		'final_settlement_amount_cents',
		'currency_code',
		'settlement_paid_date',
		'notice_period_days',
		'notice_waived',
		'notice_waiver_reason',
		'clearance_items',
		'cleared_by_id',
		'cleared_date',
		'closed_by_id',
		'closed_date',
		'certificate_issued',
		'certificate_issued_date',
		'extra',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'exit_type',
		'status',
		'exit_reason',
		'currency_code',
		'notice_period_days',
		'notice_waiver_reason',
	]


class OrgJobGradeRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/org_job_grade'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(OrgJobGrade)
	list_columns = [
		'id',
		'tenant_id',
		'grade_code',
		'label',
		'effective_date',
		'min_amount_cents',
		'max_amount_cents',
		'currency_code',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'grade_code',
		'label',
		'effective_date',
		'min_amount_cents',
		'max_amount_cents',
		'currency_code',
	]
	edit_columns = add_columns
	search_columns = [
		'grade_code',
		'currency_code',
	]


class EmployeePositionHistoryRestApi(ModelRestApi):
	resource_name = 'erp/hcm/personnel/employee_position_history'
	openapi_spec_tag = 'HCM Personnel'
	datamodel = SQLAInterface(EmployeePositionHistory)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'position_code',
		'position_title',
		'department_id',
		'manager_id',
		'org_unit_id',
		'change_reason',
		'changed_by',
		'effective_from',
		'effective_to',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'position_code',
		'position_title',
		'department_id',
		'manager_id',
		'org_unit_id',
		'change_reason',
		'changed_by',
		'effective_from',
		'effective_to',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'position_code',
		'position_title',
		'department_id',
		'manager_id',
		'change_reason',
	]
