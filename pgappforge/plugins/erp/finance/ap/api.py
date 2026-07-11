"""REST APIs for ERP models in this plugin."""
from __future__ import annotations

from pgappforge.api import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface

from .models import (
	APSupplier,
	APPurchaseOrder,
	APPOLine,
	APGoodsReceipt,
	APGRNLine,
	APPaymentRun,
	APInvoice,
	APInvoiceLine,
	APApprovalWorkflow,
	APPayment,
)


class APSupplierRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/ap_supplier'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APSupplier)
	list_columns = [
		'id',
		'tenant_id',
		'party_id',
		'account_number',
		'name',
		'supplier_type',
		'status',
		'payment_terms_days',
		'payment_method',
		'currency_code',
		'bank_account_iban',
		'bank_bic',
		'bank_account_name',
		'bank_details',
		'tax_id',
		'vat_number',
		'w9_on_file',
		'reporting_1099',
		'gl_payable_account',
		'approved_supplier',
		'credit_rating',
		'dynamic_discounting_eligible',
		'early_payment_discount_pct',
		'early_payment_days',
		'contact_email',
		'contact_phone',
		'address',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'party_id',
		'account_number',
		'name',
		'supplier_type',
		'status',
		'payment_terms_days',
		'payment_method',
		'currency_code',
		'bank_account_iban',
		'bank_bic',
		'bank_account_name',
		'bank_details',
		'tax_id',
		'vat_number',
		'w9_on_file',
		'reporting_1099',
		'gl_payable_account',
		'approved_supplier',
		'credit_rating',
		'dynamic_discounting_eligible',
		'early_payment_discount_pct',
		'early_payment_days',
		'contact_email',
		'contact_phone',
		'address',
	]
	edit_columns = add_columns
	search_columns = [
		'party_id',
		'account_number',
		'name',
		'supplier_type',
		'status',
		'payment_method',
		'currency_code',
		'bank_account_iban',
		'bank_account_name',
		'vat_number',
		'gl_payable_account',
		'approved_supplier',
	]


class APPurchaseOrderRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/ap_purchase_order'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APPurchaseOrder)
	list_columns = [
		'id',
		'tenant_id',
		'po_number',
		'supplier_id',
		'requisitioner_id',
		'approved_by',
		'approval_date',
		'order_date',
		'delivery_date',
		'currency_code',
		'subtotal_cents',
		'tax_cents',
		'total_cents',
		'received_cents',
		'invoiced_cents',
		'paid_cents',
		'status',
		'notes',
		'metadata_',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'po_number',
		'supplier_id',
		'requisitioner_id',
		'approved_by',
		'approval_date',
		'order_date',
		'delivery_date',
		'currency_code',
		'subtotal_cents',
		'tax_cents',
		'total_cents',
		'received_cents',
		'invoiced_cents',
		'paid_cents',
		'status',
		'notes',
		'metadata_',
	]
	edit_columns = add_columns
	search_columns = [
		'po_number',
		'supplier_id',
		'currency_code',
		'status',
		'notes',
	]


class APPOLineRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/appo_line'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APPOLine)
	list_columns = [
		'id',
		'tenant_id',
		'po_id',
		'line_number',
		'description',
		'quantity',
		'uom',
		'unit_cost_cents',
		'line_amount_cents',
		'quantity_received',
		'quantity_invoiced',
		'gl_expense_account',
		'cost_center',
		'project_code',
		'product_id',
		'product_sku',
		'status',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'po_id',
		'line_number',
		'description',
		'quantity',
		'uom',
		'unit_cost_cents',
		'line_amount_cents',
		'quantity_received',
		'quantity_invoiced',
		'gl_expense_account',
		'cost_center',
		'project_code',
		'product_id',
		'product_sku',
		'status',
	]
	edit_columns = add_columns
	search_columns = [
		'line_number',
		'description',
		'gl_expense_account',
		'project_code',
		'status',
	]


class APGoodsReceiptRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/ap_goods_receipt'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APGoodsReceipt)
	list_columns = [
		'id',
		'tenant_id',
		'grn_number',
		'po_id',
		'supplier_id',
		'received_by',
		'received_date',
		'warehouse_id',
		'status',
		'notes',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'grn_number',
		'po_id',
		'supplier_id',
		'received_by',
		'received_date',
		'warehouse_id',
		'status',
		'notes',
	]
	edit_columns = add_columns
	search_columns = [
		'grn_number',
		'supplier_id',
		'status',
		'notes',
	]


class APGRNLineRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/apgrn_line'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APGRNLine)
	list_columns = [
		'id',
		'tenant_id',
		'grn_id',
		'po_line_id',
		'description',
		'quantity_received',
		'quantity_accepted',
		'quantity_rejected',
		'rejection_reason',
		'unit_cost_cents',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'grn_id',
		'po_line_id',
		'description',
		'quantity_received',
		'quantity_accepted',
		'quantity_rejected',
		'rejection_reason',
		'unit_cost_cents',
	]
	edit_columns = add_columns
	search_columns = [
		'description',
		'rejection_reason',
	]


class APPaymentRunRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/ap_payment_run'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APPaymentRun)
	list_columns = [
		'id',
		'tenant_id',
		'run_number',
		'run_date',
		'value_date',
		'bank_account',
		'bic',
		'currency_code',
		'total_payments',
		'total_amount_cents',
		'payment_file_ref',
		'iso20022_xml',
		'status',
		'approved_by',
		'approved_at',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'run_number',
		'run_date',
		'value_date',
		'bank_account',
		'bic',
		'currency_code',
		'total_payments',
		'total_amount_cents',
		'payment_file_ref',
		'iso20022_xml',
		'status',
		'approved_by',
		'approved_at',
	]
	edit_columns = add_columns
	search_columns = [
		'run_number',
		'bank_account',
		'currency_code',
		'payment_file_ref',
		'status',
	]


class APInvoiceRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/ap_invoice'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APInvoice)
	list_columns = [
		'id',
		'tenant_id',
		'invoice_number_supplier',
		'supplier_id',
		'po_id',
		'grn_id',
		'payment_run_id',
		'invoice_date',
		'due_date',
		'currency_code',
		'exchange_rate',
		'subtotal_cents',
		'discount_cents',
		'tax_cents',
		'total_cents',
		'paid_cents',
		'early_payment_discount_taken_cents',
		'gl_payable_account',
		'match_status',
		'approval_status',
		'status',
		'notes',
		'metadata_',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'invoice_number_supplier',
		'supplier_id',
		'po_id',
		'grn_id',
		'payment_run_id',
		'invoice_date',
		'due_date',
		'currency_code',
		'exchange_rate',
		'subtotal_cents',
		'discount_cents',
		'tax_cents',
		'total_cents',
		'paid_cents',
		'early_payment_discount_taken_cents',
		'gl_payable_account',
		'match_status',
		'approval_status',
		'status',
		'notes',
		'metadata_',
	]
	edit_columns = add_columns
	search_columns = [
		'invoice_number_supplier',
		'supplier_id',
		'currency_code',
		'gl_payable_account',
		'match_status',
		'approval_status',
		'status',
		'notes',
	]


class APInvoiceLineRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/ap_invoice_line'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APInvoiceLine)
	list_columns = [
		'id',
		'tenant_id',
		'invoice_id',
		'line_number',
		'po_line_id',
		'grn_line_id',
		'description',
		'quantity',
		'uom',
		'unit_cost_cents',
		'line_amount_cents',
		'tax_category',
		'tax_rate',
		'tax_cents',
		'gl_expense_account',
		'cost_center',
		'project_code',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'invoice_id',
		'line_number',
		'po_line_id',
		'grn_line_id',
		'description',
		'quantity',
		'uom',
		'unit_cost_cents',
		'line_amount_cents',
		'tax_category',
		'tax_rate',
		'tax_cents',
		'gl_expense_account',
		'cost_center',
		'project_code',
	]
	edit_columns = add_columns
	search_columns = [
		'line_number',
		'description',
		'tax_category',
		'gl_expense_account',
		'project_code',
	]


class APApprovalWorkflowRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/ap_approval_workflow'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APApprovalWorkflow)
	list_columns = [
		'id',
		'tenant_id',
		'invoice_id',
		'approver_id',
		'approval_level',
		'amount_threshold_cents',
		'status',
		'actioned_at',
		'comments',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'invoice_id',
		'approver_id',
		'approval_level',
		'amount_threshold_cents',
		'status',
		'actioned_at',
		'comments',
	]
	edit_columns = add_columns
	search_columns = [
		'status',
	]


class APPaymentRestApi(ModelRestApi):
	resource_name = 'erp/finance/ap/ap_payment'
	openapi_spec_tag = 'Finance'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(APPayment)
	list_columns = [
		'id',
		'tenant_id',
		'payment_run_id',
		'supplier_id',
		'invoice_id',
		'payment_date',
		'amount_cents',
		'currency_code',
		'exchange_rate',
		'bank_reference',
		'uetr',
		'status',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'payment_run_id',
		'supplier_id',
		'invoice_id',
		'payment_date',
		'amount_cents',
		'currency_code',
		'exchange_rate',
		'bank_reference',
		'uetr',
		'status',
	]
	edit_columns = add_columns
	search_columns = [
		'supplier_id',
		'currency_code',
		'bank_reference',
		'status',
	]
