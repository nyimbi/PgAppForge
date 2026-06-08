from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.procurement.supplier_portal.models import (
	SupplierProfile,
	SupplierPerformanceCard,
)


class SupplierProfileView(ModelView):
	datamodel = SQLAInterface(SupplierProfile)

	list_columns = ['supplier_ref', 'company_name', 'country_code', 'primary_category',
					'kyc_status', 'overall_score', 'is_preferred', 'bank_verified']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class SupplierPerformanceCardView(ModelView):
	datamodel = SQLAInterface(SupplierPerformanceCard)

	list_columns = ['supplier_id', 'period', 'composite_score',
					'on_time_delivery_pct', 'quality_acceptance_pct',
					'invoice_accuracy_pct', 'responsiveness_score']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'SupplierProfileView',
	'SupplierPerformanceCardView',
]
