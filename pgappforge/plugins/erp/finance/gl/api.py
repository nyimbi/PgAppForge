"""REST APIs for ERP models in this plugin."""
from __future__ import annotations

from pgappforge.api import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface

from .models import (
	GLAccount,
	GLCostCenter,
	GLFiscalYear,
	GLPeriod,
	GLJournalBatch,
	GLJournalEntry,
	GLJournalLine,
	GLAccountBalance,
	GLBudget,
	GLDimensionDefinition,
)


class GLAccountRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_account'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLAccount)
	list_columns = [
		'account_code',
		'tenant_id',
		'account_name',
		'account_type',
		'account_subtype',
		'normal_balance',
		'parent_code',
		'is_posting_account',
		'is_reconciliation_account',
		'currency_code',
		'ifrs_concept',
		'gaap_concept',
		'is_statistical',
		'stat_unit',
		'is_active',
		'description',
		'attributes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'account_code',
		'tenant_id',
		'account_name',
		'account_type',
		'account_subtype',
		'normal_balance',
		'parent_code',
		'is_posting_account',
		'is_reconciliation_account',
		'currency_code',
		'ifrs_concept',
		'gaap_concept',
		'is_statistical',
		'stat_unit',
		'is_active',
		'description',
		'attributes',
	]
	edit_columns = add_columns
	search_columns = [
		'account_code',
		'account_name',
		'account_type',
		'account_subtype',
		'parent_code',
		'is_posting_account',
		'is_reconciliation_account',
		'currency_code',
		'description',
	]


class GLCostCenterRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_cost_center'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLCostCenter)
	list_columns = [
		'id',
		'tenant_id',
		'code',
		'name',
		'parent_code',
		'manager_party_id',
		'department',
		'business_unit',
		'is_active',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'code',
		'name',
		'parent_code',
		'manager_party_id',
		'department',
		'business_unit',
		'is_active',
	]
	edit_columns = add_columns
	search_columns = [
		'code',
		'name',
		'parent_code',
		'manager_party_id',
		'department',
	]


class GLFiscalYearRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_fiscal_year'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLFiscalYear)
	list_columns = [
		'id',
		'tenant_id',
		'year_code',
		'fiscal_year',
		'start_date',
		'end_date',
		'status',
		'closed_by',
		'closed_at',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'year_code',
		'fiscal_year',
		'start_date',
		'end_date',
		'status',
		'closed_by',
		'closed_at',
	]
	edit_columns = add_columns
	search_columns = [
		'year_code',
		'fiscal_year',
		'status',
	]


class GLPeriodRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_period'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLPeriod)
	list_columns = [
		'id',
		'tenant_id',
		'fiscal_year_id',
		'period_number',
		'period_name',
		'start_date',
		'end_date',
		'status',
		'closed_by',
		'closed_at',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'fiscal_year_id',
		'period_number',
		'period_name',
		'start_date',
		'end_date',
		'status',
		'closed_by',
		'closed_at',
	]
	edit_columns = add_columns
	search_columns = [
		'fiscal_year_id',
		'period_number',
		'period_name',
		'status',
	]


class GLJournalBatchRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_journal_batch'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLJournalBatch)
	list_columns = [
		'id',
		'tenant_id',
		'batch_number',
		'batch_type',
		'period_id',
		'description',
		'total_debits',
		'total_credits',
		'is_balanced',
		'status',
		'submitted_by',
		'submitted_at',
		'approved_by',
		'approved_at',
		'posted_by',
		'posted_at',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'batch_number',
		'batch_type',
		'period_id',
		'description',
		'total_debits',
		'total_credits',
		'is_balanced',
		'status',
		'submitted_by',
		'submitted_at',
		'approved_by',
		'approved_at',
		'posted_by',
		'posted_at',
	]
	edit_columns = add_columns
	search_columns = [
		'batch_number',
		'batch_type',
		'period_id',
		'description',
		'status',
	]


class GLJournalEntryRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_journal_entry'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLJournalEntry)
	list_columns = [
		'id',
		'tenant_id',
		'batch_id',
		'entry_number',
		'entry_type',
		'posting_date',
		'description',
		'source_document_type',
		'source_document_id',
		'reversal_of_entry_id',
		'auto_reverse',
		'auto_reverse_date',
		'status',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'batch_id',
		'entry_number',
		'entry_type',
		'posting_date',
		'description',
		'source_document_type',
		'source_document_id',
		'reversal_of_entry_id',
		'auto_reverse',
		'auto_reverse_date',
		'status',
	]
	edit_columns = add_columns
	search_columns = [
		'entry_number',
		'entry_type',
		'description',
		'source_document_type',
		'source_document_id',
		'status',
	]


class GLJournalLineRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_journal_line'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLJournalLine)
	list_columns = [
		'id',
		'tenant_id',
		'entry_id',
		'line_number',
		'account_code',
		'cost_center_code',
		'project_code',
		'debit_amount',
		'credit_amount',
		'currency_code',
		'fx_rate',
		'base_debit',
		'base_credit',
		'description',
		'reference',
		'party_id',
		'tax_code',
		'dimensions',
		'quantity',
		'created_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'entry_id',
		'line_number',
		'account_code',
		'cost_center_code',
		'project_code',
		'debit_amount',
		'credit_amount',
		'currency_code',
		'fx_rate',
		'base_debit',
		'base_credit',
		'description',
		'reference',
		'party_id',
		'tax_code',
		'dimensions',
		'quantity',
	]
	edit_columns = add_columns
	search_columns = [
		'line_number',
		'account_code',
		'cost_center_code',
		'project_code',
		'currency_code',
		'description',
		'reference',
		'party_id',
		'tax_code',
	]


class GLAccountBalanceRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_account_balance'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLAccountBalance)
	list_columns = [
		'id',
		'tenant_id',
		'account_code',
		'period_id',
		'opening_debit',
		'opening_credit',
		'period_debit',
		'period_credit',
		'closing_debit',
		'closing_credit',
		'ytd_debit',
		'ytd_credit',
		'dimensions',
		'refreshed_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'account_code',
		'period_id',
		'opening_debit',
		'opening_credit',
		'period_debit',
		'period_credit',
		'closing_debit',
		'closing_credit',
		'ytd_debit',
		'ytd_credit',
		'dimensions',
	]
	edit_columns = add_columns
	search_columns = [
		'account_code',
		'period_id',
		'period_debit',
		'period_credit',
		'refreshed_at',
	]


class GLBudgetRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_budget'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLBudget)
	list_columns = [
		'id',
		'tenant_id',
		'account_code',
		'cost_center_code',
		'period_id',
		'version',
		'budget_amount',
		'revised_budget_amount',
		'forecast_amount',
		'notes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'account_code',
		'cost_center_code',
		'period_id',
		'version',
		'budget_amount',
		'revised_budget_amount',
		'forecast_amount',
		'notes',
	]
	edit_columns = add_columns
	search_columns = [
		'account_code',
		'cost_center_code',
		'period_id',
		'notes',
	]


class GLDimensionDefinitionRestApi(ModelRestApi):
	resource_name = 'erp/finance/gl/gl_dimension_definition'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(GLDimensionDefinition)
	list_columns = [
		'id',
		'tenant_id',
		'dimension_code',
		'name',
		'is_required',
		'allowed_values',
		'is_active',
		'description',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'dimension_code',
		'name',
		'is_required',
		'allowed_values',
		'is_active',
		'description',
	]
	edit_columns = add_columns
	search_columns = [
		'dimension_code',
		'name',
		'description',
	]
