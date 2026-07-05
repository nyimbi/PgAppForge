from __future__ import annotations

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

	list_columns = ['supplier_ref', 'company_name', 'country_code', 'primary_category',
					'kyc_status', 'overall_score', 'risk_level', 'is_preferred',
					'bank_verified']
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

	list_columns = ['supplier_id', 'period', 'composite_score',
					'on_time_delivery_pct', 'quality_acceptance_pct',
					'invoice_accuracy_pct', 'responsiveness_score']
	add_columns = ['tenant_id', 'supplier_id', 'period', 'on_time_delivery_pct',
				   'quality_acceptance_pct', 'invoice_accuracy_pct',
				   'responsiveness_score', 'composite_score', 'po_count', 'grn_count']
	edit_columns = add_columns


class SupplierScorecardView(ModelView):
	datamodel = SQLAInterface(SupplierScorecard)

	list_columns = ['supplier_id', 'period', 'overall_score', 'on_time_delivery_pct',
					'quality_score', 'price_competitiveness', 'responsiveness_score',
					'scored_by', 'scored_at']
	add_columns = ['tenant_id', 'supplier_id', 'period', 'on_time_delivery_pct',
				   'quality_score', 'price_competitiveness', 'responsiveness_score',
				   'overall_score', 'notes', 'scored_by', 'scored_at']
	edit_columns = add_columns


class SupplierRiskView(ModelView):
	datamodel = SQLAInterface(SupplierRisk)

	list_columns = ['supplier_id', 'risk_type', 'severity', 'notes', 'created_at']
	add_columns = ['tenant_id', 'supplier_id', 'risk_type', 'severity', 'notes',
				   'created_at']
	edit_columns = add_columns


__all__ = [
	'SupplierProfileView',
	'SupplierPerformanceCardView',
	'SupplierScorecardView',
	'SupplierRiskView',
]
