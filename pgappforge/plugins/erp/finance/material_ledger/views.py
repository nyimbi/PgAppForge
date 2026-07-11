from __future__ import annotations
from flask_babel import lazy_gettext as _

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.material_ledger.models import (
	MaterialLedger,
	MaterialMovement,
	CostingPeriod,
	CostSettlement,
)


class MaterialLedgerEntryView(ModelView):
	datamodel = SQLAInterface(MaterialLedger)

	list_columns = ['material_id', 'plant_id', 'period_id', 'costing_status',
					'standard_price_cents', 'closing_value_cents', 'actual_price_cents']
	show_columns = ['id', 'material_id', 'plant_id', 'currency_code',
					'opening_qty', 'opening_value_cents', 'standard_price_cents',
					'receipts_qty', 'receipts_value_cents', 'issues_qty',
					'issues_value_cents', 'purchase_price_variance_cents',
					'exchange_rate_difference_cents', 'production_variance_cents',
					'multilevel_variance_cents', 'closing_qty',
					'closing_value_cents', 'actual_price_cents',
					'revaluation_cents', 'costing_status', 'metadata_',
					'created_at', 'updated_at']
	label_columns = {
		'material_id': _('Material'),
		'plant_id': _('Plant'),
		'period_id': _('Costing Period'),
		'costing_status': _('Costing Status'),
		'standard_price_cents': _('Standard Price (cents)'),
		'closing_value_cents': _('Closing Value (cents)'),
		'actual_price_cents': _('Actual Price (cents)'),
		'currency_code': _('Currency'),
		'opening_qty': _('Opening Quantity'),
		'opening_value_cents': _('Opening Value (cents)'),
		'receipts_qty': _('Receipts Quantity'),
		'receipts_value_cents': _('Receipts Value (cents)'),
		'issues_qty': _('Issues Quantity'),
		'issues_value_cents': _('Issues Value (cents)'),
		'purchase_price_variance_cents': _('Purchase Price Variance (cents)'),
		'exchange_rate_difference_cents': _('Exchange Rate Difference (cents)'),
		'production_variance_cents': _('Production Variance (cents)'),
		'multilevel_variance_cents': _('Multilevel Variance (cents)'),
		'closing_qty': _('Closing Quantity'),
		'revaluation_cents': _('Revaluation (cents)'),
		'metadata_': _('Metadata'),
		'created_at': _('Created At'),
		'updated_at': _('Updated At'),
	}
	search_columns = ['material_id', 'plant_id', 'period_id', 'costing_status', 'currency_code']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class MaterialMovementView(ModelView):
	datamodel = SQLAInterface(MaterialMovement)

	list_columns = ['ledger_id', 'posting_date', 'movement_type', 'quantity',
					'preliminary_value_cents', 'variance_type']
	show_columns = ['id', 'ledger_id', 'posting_date', 'movement_type', 'quantity',
					'unit_of_measure', 'preliminary_value_cents',
					'actual_value_cents', 'variance_cents', 'variance_type',
					'source_document_type', 'source_document_id', 'is_reversal',
					'posting_reference', 'created_at']
	label_columns = {
		'ledger_id': _('Material Ledger'),
		'posting_date': _('Posting Date'),
		'movement_type': _('Movement Type'),
		'quantity': _('Quantity'),
		'preliminary_value_cents': _('Preliminary Value (cents)'),
		'variance_type': _('Variance Type'),
		'unit_of_measure': _('Unit of Measure'),
		'actual_value_cents': _('Actual Value (cents)'),
		'variance_cents': _('Variance (cents)'),
		'source_document_type': _('Source Document Type'),
		'source_document_id': _('Source Document'),
		'is_reversal': _('Reversal'),
		'posting_reference': _('Posting Reference'),
		'created_at': _('Created At'),
	}
	search_columns = ['ledger_id', 'movement_type', 'variance_type',
					  'source_document_type', 'source_document_id',
					  'posting_reference']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


class ActualCostRevaluationView(ModelView):
	datamodel = SQLAInterface(CostSettlement)

	list_title = 'Actual Cost Settlement Runs'
	list_columns = ['period_id', 'plant_id', 'status', 'run_at',
					'materials_processed', 'total_variance_cents']
	show_columns = ['id', 'period_id', 'plant_id', 'run_at', 'run_by', 'status',
					'levels_processed', 'materials_processed',
					'total_variance_cents', 'error_log', 'completed_at',
					'created_at']
	label_columns = {
		'period_id': _('Costing Period'),
		'plant_id': _('Plant'),
		'status': _('Status'),
		'run_at': _('Run At'),
		'materials_processed': _('Materials Processed'),
		'total_variance_cents': _('Total Variance (cents)'),
		'run_by': _('Run By'),
		'levels_processed': _('Levels Processed'),
		'error_log': _('Error Log'),
		'completed_at': _('Completed At'),
		'created_at': _('Created At'),
	}
	search_columns = ['period_id', 'plant_id', 'status', 'run_by']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


__all__ = [
	'MaterialLedgerEntryView',
	'MaterialMovementView',
	'ActualCostRevaluationView',
]
