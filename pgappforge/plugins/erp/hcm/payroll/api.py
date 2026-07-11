"""REST APIs for ERP models in this plugin."""
from __future__ import annotations

from pgappforge.api import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface

from .models import (
	PayrollCalendar,
	PayrollRun,
	Payslip,
	PayslipLine,
	TaxWithholding,
	PayrollYTD,
	BenefitInKind,
	PayslipAccessLog,
)


class PayrollCalendarRestApi(ModelRestApi):
	resource_name = 'erp/hcm/payroll/payroll_calendar'
	openapi_spec_tag = 'HCM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(PayrollCalendar)
	list_columns = [
		'id',
		'tenant_id',
		'entity_id',
		'name',
		'pay_frequency',
		'periods',
		'fiscal_year',
		'is_active',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'entity_id',
		'name',
		'pay_frequency',
		'periods',
		'fiscal_year',
		'is_active',
	]
	edit_columns = add_columns
	search_columns = [
		'entity_id',
		'name',
		'pay_frequency',
		'periods',
		'fiscal_year',
	]


class PayrollRunRestApi(ModelRestApi):
	resource_name = 'erp/hcm/payroll/payroll_run'
	openapi_spec_tag = 'HCM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(PayrollRun)
	list_columns = [
		'id',
		'tenant_id',
		'entity_id',
		'calendar_id',
		'period_start',
		'period_end',
		'pay_date',
		'payroll_type',
		'status',
		'employee_count',
		'total_gross_cents',
		'total_employee_tax_cents',
		'total_employer_tax_cents',
		'total_net_cents',
		'calculated_at',
		'approved_by',
		'approved_at',
		'paid_at',
		'gl_journal_id',
		'notes',
		'metadata_',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'entity_id',
		'calendar_id',
		'period_start',
		'period_end',
		'pay_date',
		'payroll_type',
		'status',
		'employee_count',
		'total_gross_cents',
		'total_employee_tax_cents',
		'total_employer_tax_cents',
		'total_net_cents',
		'calculated_at',
		'approved_by',
		'approved_at',
		'paid_at',
		'gl_journal_id',
		'notes',
		'metadata_',
	]
	edit_columns = add_columns
	search_columns = [
		'entity_id',
		'period_start',
		'period_end',
		'payroll_type',
		'status',
		'employee_count',
		'total_employee_tax_cents',
		'notes',
	]


class PayslipRestApi(ModelRestApi):
	resource_name = 'erp/hcm/payroll/payslip'
	openapi_spec_tag = 'HCM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(Payslip)
	list_columns = [
		'id',
		'tenant_id',
		'payrun_id',
		'employee_id',
		'gross_pay_cents',
		'income_tax_cents',
		'national_insurance_cents',
		'pension_employee_cents',
		'pension_employer_cents',
		'other_deductions_cents',
		'net_pay_cents',
		'bank_account_iban',
		'bank_account_number',
		'bank_name',
		'bank_branch_code',
		'currency_code',
		'payment_reference',
		'dispatched_at',
		'status',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'payrun_id',
		'employee_id',
		'gross_pay_cents',
		'income_tax_cents',
		'national_insurance_cents',
		'pension_employee_cents',
		'pension_employer_cents',
		'other_deductions_cents',
		'net_pay_cents',
		'bank_account_iban',
		'bank_account_number',
		'bank_name',
		'bank_branch_code',
		'currency_code',
		'payment_reference',
		'dispatched_at',
		'status',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'pension_employee_cents',
		'bank_account_iban',
		'bank_account_number',
		'bank_name',
		'bank_branch_code',
		'currency_code',
		'payment_reference',
		'status',
	]


class PayslipLineRestApi(ModelRestApi):
	resource_name = 'erp/hcm/payroll/payslip_line'
	openapi_spec_tag = 'HCM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(PayslipLine)
	list_columns = [
		'id',
		'tenant_id',
		'payslip_id',
		'line_type',
		'description',
		'units',
		'rate_cents',
		'amount_cents',
		'is_employer_cost',
		'gl_account',
		'cost_center',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'payslip_id',
		'line_type',
		'description',
		'units',
		'rate_cents',
		'amount_cents',
		'is_employer_cost',
		'gl_account',
		'cost_center',
	]
	edit_columns = add_columns
	search_columns = [
		'line_type',
		'description',
		'gl_account',
	]


class TaxWithholdingRestApi(ModelRestApi):
	resource_name = 'erp/hcm/payroll/tax_withholding'
	openapi_spec_tag = 'HCM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(TaxWithholding)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'jurisdiction_code',
		'filing_status',
		'allowances',
		'additional_withholding_cents',
		'effective_from',
		'notes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'jurisdiction_code',
		'filing_status',
		'allowances',
		'additional_withholding_cents',
		'effective_from',
		'notes',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'jurisdiction_code',
		'filing_status',
		'notes',
	]


class PayrollYTDRestApi(ModelRestApi):
	resource_name = 'erp/hcm/payroll/payroll_ytd'
	openapi_spec_tag = 'HCM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(PayrollYTD)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'payrun_id',
		'tax_year',
		'month',
		'gross_cents',
		'taxable_gross_cents',
		'paye_cents',
		'nssf_tier1_cents',
		'nssf_tier2_cents',
		'shif_cents',
		'housing_levy_cents',
		'nita_cents',
		'net_cents',
		'bik_cents',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'payrun_id',
		'tax_year',
		'month',
		'gross_cents',
		'taxable_gross_cents',
		'paye_cents',
		'nssf_tier1_cents',
		'nssf_tier2_cents',
		'shif_cents',
		'housing_levy_cents',
		'nita_cents',
		'net_cents',
		'bik_cents',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'tax_year',
	]


class BenefitInKindRestApi(ModelRestApi):
	resource_name = 'erp/hcm/payroll/benefit_in_kind'
	openapi_spec_tag = 'HCM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(BenefitInKind)
	list_columns = [
		'id',
		'tenant_id',
		'employee_id',
		'benefit_type',
		'description',
		'monthly_value_cents',
		'is_taxable',
		'effective_from',
		'effective_to',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'employee_id',
		'benefit_type',
		'description',
		'monthly_value_cents',
		'is_taxable',
		'effective_from',
		'effective_to',
	]
	edit_columns = add_columns
	search_columns = [
		'employee_id',
		'benefit_type',
		'description',
	]


class PayslipAccessLogRestApi(ModelRestApi):
	resource_name = 'erp/hcm/payroll/payslip_access_log'
	openapi_spec_tag = 'HCM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(PayslipAccessLog)
	list_columns = [
		'id',
		'tenant_id',
		'payslip_id',
		'accessed_by',
		'access_type',
		'ip_address',
		'accessed_at',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'payslip_id',
		'accessed_by',
		'access_type',
		'ip_address',
		'accessed_at',
	]
	edit_columns = add_columns
	search_columns = [
		'access_type',
	]
