from __future__ import annotations
from flask_babel import lazy_gettext as _

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.procurement.supplier_portal.models import (
	SupplierProfile,
	SupplierPerformanceCard,
	SupplierRisk,
	SupplierScorecard,
)


class SupplierProfileView(ModelView):
	datamodel = SQLAInterface(SupplierProfile)

	label_columns = {
		'supplier_ref': _('Supplier Ref'),
		'company_name': _('Company Name'),
		'company_reg_number': _('Company Registration'),
		'tax_id': _('Tax ID'),
		'country_code': _('Country'),
		'contact_email': _('Contact Email'),
		'contact_phone': _('Contact Phone'),
		'primary_category': _('Primary Category'),
		'kyc_status': _('KYC Status'),
		'kyc_approved_by': _('KYC Approved By'),
		'kyc_approved_at': _('KYC Approved At'),
		'kyc_documents': _('KYC Documents'),
		'bank_name': _('Bank Name'),
		'bank_account_number': _('Bank Account Number'),
		'bank_branch': _('Bank Branch'),
		'bank_swift': _('Bank SWIFT'),
		'bank_verified': _('Bank Verified'),
		'bank_verified_at': _('Bank Verified At'),
		'overall_score': _('Overall Score'),
		'is_preferred': _('Preferred'),
		'risk_level': _('Risk Level'),
	}
	list_columns = ['supplier_ref', 'company_name', 'country_code', 'primary_category',
					'kyc_status', 'overall_score', 'risk_level', 'is_preferred',
					'bank_verified']
	show_columns = ['tenant_id', 'supplier_ref', 'company_name', 'company_reg_number',
					'tax_id', 'country_code', 'contact_email', 'contact_phone',
					'primary_category', 'kyc_status', 'kyc_approved_by',
					'kyc_approved_at', 'kyc_documents', 'bank_name',
					'bank_account_number', 'bank_branch', 'bank_swift',
					'bank_verified', 'bank_verified_at', 'overall_score',
					'is_preferred', 'risk_level', 'created_at', 'updated_at']
	search_columns = ['supplier_ref', 'company_name', 'tax_id', 'country_code',
					  'contact_email', 'contact_phone', 'primary_category',
					  'kyc_status', 'risk_level']
	add_columns = ['tenant_id', 'company_name', 'supplier_ref', 'company_reg_number',
				   'tax_id', 'country_code', 'contact_email', 'contact_phone',
				   'primary_category', 'kyc_status', 'kyc_approved_by',
				   'kyc_approved_at', 'kyc_documents', 'bank_name',
				   'bank_account_number', 'bank_branch', 'bank_swift',
				   'bank_verified', 'bank_verified_at', 'overall_score',
				   'is_preferred', 'risk_level']
	edit_columns = add_columns
	show_fieldsets = [
		('Supplier', {'fields': ['supplier_ref', 'company_name', 'country_code',
								 'primary_category', 'kyc_status', 'risk_level']}),
		('Scorecard Summary', {'fields': ['overall_score', 'is_preferred',
										   'bank_verified']}),
		('Contact', {'fields': ['contact_email', 'contact_phone', 'tax_id']}),
	]


class SupplierPerformanceCardView(ModelView):
	datamodel = SQLAInterface(SupplierPerformanceCard)

	label_columns = {
		'supplier_id': _('Supplier'),
		'period': _('Period'),
		'composite_score': _('Composite Score'),
		'on_time_delivery_pct': _('On-Time Delivery'),
		'quality_acceptance_pct': _('Quality Acceptance'),
		'invoice_accuracy_pct': _('Invoice Accuracy'),
		'responsiveness_score': _('Responsiveness'),
		'po_count': _('PO Count'),
		'grn_count': _('GRN Count'),
	}
	list_columns = ['supplier_id', 'period', 'composite_score',
					'on_time_delivery_pct', 'quality_acceptance_pct',
					'invoice_accuracy_pct', 'responsiveness_score']
	show_columns = ['tenant_id', 'supplier_id', 'period', 'on_time_delivery_pct',
					'quality_acceptance_pct', 'invoice_accuracy_pct',
					'responsiveness_score', 'composite_score', 'po_count',
					'grn_count', 'created_at', 'updated_at']
	search_columns = ['period']
	add_columns = ['tenant_id', 'supplier_id', 'period', 'on_time_delivery_pct',
				   'quality_acceptance_pct', 'invoice_accuracy_pct',
				   'responsiveness_score', 'composite_score', 'po_count', 'grn_count']
	edit_columns = add_columns


class SupplierScorecardView(ModelView):
	datamodel = SQLAInterface(SupplierScorecard)

	label_columns = {
		'supplier_id': _('Supplier'),
		'period': _('Period'),
		'overall_score': _('Overall Score'),
		'on_time_delivery_pct': _('On-Time Delivery'),
		'quality_score': _('Quality'),
		'price_competitiveness': _('Price Competitiveness'),
		'responsiveness_score': _('Responsiveness'),
		'notes': _('Notes'),
		'scored_by': _('Scored By'),
		'scored_at': _('Scored At'),
	}
	list_columns = ['supplier_id', 'period', 'overall_score', 'on_time_delivery_pct',
					'quality_score', 'price_competitiveness', 'responsiveness_score',
					'scored_by', 'scored_at']
	show_columns = ['tenant_id', 'supplier_id', 'period', 'on_time_delivery_pct',
					'quality_score', 'price_competitiveness',
					'responsiveness_score', 'overall_score', 'notes',
					'scored_by', 'scored_at']
	search_columns = ['period', 'notes', 'scored_by']
	add_columns = ['tenant_id', 'supplier_id', 'period', 'on_time_delivery_pct',
				   'quality_score', 'price_competitiveness', 'responsiveness_score',
				   'overall_score', 'notes', 'scored_by', 'scored_at']
	edit_columns = add_columns


class SupplierRiskView(ModelView):
	datamodel = SQLAInterface(SupplierRisk)

	label_columns = {
		'supplier_id': _('Supplier'),
		'risk_type': _('Risk Type'),
		'severity': _('Severity'),
		'notes': _('Notes'),
		'created_at': _('Created At'),
	}
	list_columns = ['supplier_id', 'risk_type', 'severity', 'notes', 'created_at']
	show_columns = ['tenant_id', 'supplier_id', 'risk_type', 'severity', 'notes',
					'created_at']
	search_columns = ['risk_type', 'severity', 'notes']
	add_columns = ['tenant_id', 'supplier_id', 'risk_type', 'severity', 'notes',
				   'created_at']
	edit_columns = add_columns


__all__ = [
	'SupplierProfileView',
	'SupplierPerformanceCardView',
	'SupplierScorecardView',
	'SupplierRiskView',
]
