"""REST APIs for ERP models in this plugin."""
from __future__ import annotations

from pgappforge.api import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface

from .models import (
	ARCustomer,
	ARInvoice,
	ARInvoiceLine,
	ARPayment,
	ARAllocation,
	ARCreditNote,
	ARDunningRun,
	ARDunningEvent,
	ARAging,
)


class ARCustomerRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_customer'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARCustomer)
	list_columns = [
		'id',
		'tenant_id',
		'party_id',
		'account_number',
		'customer_type',
		'credit_limit_cents',
		'credit_used_cents',
		'credit_hold',
		'payment_terms_days',
		'dunning_level',
		'dunning_blocked',
		'gl_reconciliation_account',
		'statement_frequency',
		'last_statement_date',
		'risk_score',
		'status',
		'billing_address',
		'contact_email',
		'contact_phone',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'party_id',
		'account_number',
		'customer_type',
		'credit_limit_cents',
		'credit_used_cents',
		'credit_hold',
		'payment_terms_days',
		'dunning_level',
		'dunning_blocked',
		'gl_reconciliation_account',
		'statement_frequency',
		'last_statement_date',
		'risk_score',
		'status',
		'billing_address',
		'contact_email',
		'contact_phone',
	]
	edit_columns = add_columns
	search_columns = [
		'party_id',
		'account_number',
		'customer_type',
		'gl_reconciliation_account',
		'statement_frequency',
		'status',
		'contact_email',
		'contact_phone',
	]


class ARInvoiceRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_invoice'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARInvoice)
	list_columns = [
		'id',
		'tenant_id',
		'invoice_number',
		'customer_id',
		'invoice_date',
		'due_date',
		'billing_period_start',
		'billing_period_end',
		'currency_code',
		'exchange_rate',
		'subtotal_cents',
		'discount_cents',
		'tax_cents',
		'total_cents',
		'paid_cents',
		'balance_due_cents',
		'write_off_cents',
		'status',
		'customer_pin',
		'tax_control_number',
		'gl_revenue_account',
		'gl_ar_account',
		'po_reference',
		'contract_reference',
		'billing_reference_id',
		'dunning_level',
		'last_dunning_date',
		'dispute_reason',
		'write_off_date',
		'write_off_reason',
		'paid_date',
		'delivery_address',
		'notes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'invoice_number',
		'customer_id',
		'invoice_date',
		'due_date',
		'billing_period_start',
		'billing_period_end',
		'currency_code',
		'exchange_rate',
		'subtotal_cents',
		'discount_cents',
		'tax_cents',
		'total_cents',
		'paid_cents',
		'balance_due_cents',
		'write_off_cents',
		'status',
		'customer_pin',
		'tax_control_number',
		'gl_revenue_account',
		'gl_ar_account',
		'po_reference',
		'contract_reference',
		'billing_reference_id',
		'dunning_level',
		'last_dunning_date',
		'dispute_reason',
		'write_off_date',
		'write_off_reason',
		'paid_date',
		'delivery_address',
		'notes',
	]
	edit_columns = add_columns
	search_columns = [
		'invoice_number',
		'customer_id',
		'billing_period_start',
		'billing_period_end',
		'currency_code',
		'status',
		'customer_pin',
		'tax_control_number',
		'gl_revenue_account',
		'gl_ar_account',
		'po_reference',
		'contract_reference',
	]


class ARInvoiceLineRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_invoice_line'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARInvoiceLine)
	list_columns = [
		'id',
		'tenant_id',
		'invoice_id',
		'line_number',
		'description',
		'quantity',
		'uom',
		'unit_price_cents',
		'discount_pct',
		'line_amount_cents',
		'tax_category',
		'tax_rate',
		'tax_cents',
		'gl_revenue_account',
		'cost_center',
		'project_code',
		'department',
		'product_id',
		'product_sku',
		'delivery_date',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'invoice_id',
		'line_number',
		'description',
		'quantity',
		'uom',
		'unit_price_cents',
		'discount_pct',
		'line_amount_cents',
		'tax_category',
		'tax_rate',
		'tax_cents',
		'gl_revenue_account',
		'cost_center',
		'project_code',
		'department',
		'product_id',
		'product_sku',
		'delivery_date',
	]
	edit_columns = add_columns
	search_columns = [
		'line_number',
		'description',
		'tax_category',
		'gl_revenue_account',
		'project_code',
		'department',
	]


class ARPaymentRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_payment'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARPayment)
	list_columns = [
		'id',
		'tenant_id',
		'payment_number',
		'customer_id',
		'payment_date',
		'payment_method',
		'currency_code',
		'amount_cents',
		'exchange_rate',
		'bank_reference',
		'bank_account_iban',
		'bank_bic',
		'remittance_info',
		'deposited_date',
		'status',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'payment_number',
		'customer_id',
		'payment_date',
		'payment_method',
		'currency_code',
		'amount_cents',
		'exchange_rate',
		'bank_reference',
		'bank_account_iban',
		'bank_bic',
		'remittance_info',
		'deposited_date',
		'status',
	]
	edit_columns = add_columns
	search_columns = [
		'payment_number',
		'customer_id',
		'payment_method',
		'currency_code',
		'bank_reference',
		'bank_account_iban',
		'status',
	]


class ARAllocationRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_allocation'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARAllocation)
	list_columns = [
		'id',
		'tenant_id',
		'payment_id',
		'invoice_id',
		'allocation_date',
		'allocated_cents',
		'discount_taken_cents',
		'notes',
		'created_at',
		'created_by',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'payment_id',
		'invoice_id',
		'allocation_date',
		'allocated_cents',
		'discount_taken_cents',
		'notes',
		'created_by',
	]
	edit_columns = add_columns
	search_columns = [
		'notes',
	]


class ARCreditNoteRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_credit_note'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARCreditNote)
	list_columns = [
		'id',
		'tenant_id',
		'credit_note_number',
		'customer_id',
		'original_invoice_id',
		'issue_date',
		'reason',
		'currency_code',
		'total_cents',
		'applied_cents',
		'status',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'credit_note_number',
		'customer_id',
		'original_invoice_id',
		'issue_date',
		'reason',
		'currency_code',
		'total_cents',
		'applied_cents',
		'status',
	]
	edit_columns = add_columns
	search_columns = [
		'credit_note_number',
		'customer_id',
		'reason',
		'currency_code',
		'status',
	]


class ARDunningRunRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_dunning_run'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARDunningRun)
	list_columns = [
		'id',
		'tenant_id',
		'run_date',
		'dunning_level',
		'batch_size',
		'emails_sent',
		'letters_sent',
		'status',
		'run_by',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'run_date',
		'dunning_level',
		'batch_size',
		'emails_sent',
		'letters_sent',
		'status',
		'run_by',
	]
	edit_columns = add_columns
	search_columns = [
		'emails_sent',
		'status',
	]


class ARDunningEventRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_dunning_event'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARDunningEvent)
	list_columns = [
		'id',
		'tenant_id',
		'dunning_run_id',
		'customer_id',
		'invoice_ids',
		'amount_overdue_cents',
		'method',
		'sent_at',
		'response',
		'promise_to_pay_date',
		'outcome',
		'contact_email',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'dunning_run_id',
		'customer_id',
		'invoice_ids',
		'amount_overdue_cents',
		'method',
		'sent_at',
		'response',
		'promise_to_pay_date',
		'outcome',
		'contact_email',
	]
	edit_columns = add_columns
	search_columns = [
		'customer_id',
		'method',
		'outcome',
		'contact_email',
	]


class ARAgingRestApi(ModelRestApi):
	resource_name = 'erp/finance/ar/ar_aging'
	openapi_spec_tag = 'Finance AR'
	datamodel = SQLAInterface(ARAging)
	list_columns = [
		'id',
		'tenant_id',
		'customer_id',
		'snapshot_date',
		'currency_code',
		'current_cents',
		'days_1_30',
		'days_31_60',
		'days_61_90',
		'days_91_120',
		'over_120',
		'total_outstanding_cents',
		'created_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'customer_id',
		'snapshot_date',
		'currency_code',
		'current_cents',
		'days_1_30',
		'days_31_60',
		'days_61_90',
		'days_91_120',
		'over_120',
		'total_outstanding_cents',
	]
	edit_columns = add_columns
	search_columns = [
		'customer_id',
		'currency_code',
	]
