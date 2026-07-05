from __future__ import annotations

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
		'material_id': 'Material',
		'plant_id': 'Plant',
		'period_id': 'Costing Period',
		'costing_status': 'Costing Status',
		'standard_price_cents': 'Standard Price (cents)',
		'closing_value_cents': 'Closing Value (cents)',
		'actual_price_cents': 'Actual Price (cents)',
		'currency_code': 'Currency',
		'opening_qty': 'Opening Quantity',
		'opening_value_cents': 'Opening Value (cents)',
		'receipts_qty': 'Receipts Quantity',
		'receipts_value_cents': 'Receipts Value (cents)',
		'issues_qty': 'Issues Quantity',
		'issues_value_cents': 'Issues Value (cents)',
		'purchase_price_variance_cents': 'Purchase Price Variance (cents)',
		'exchange_rate_difference_cents': 'Exchange Rate Difference (cents)',
		'production_variance_cents': 'Production Variance (cents)',
		'multilevel_variance_cents': 'Multilevel Variance (cents)',
		'closing_qty': 'Closing Quantity',
		'revaluation_cents': 'Revaluation (cents)',
		'metadata_': 'Metadata',
		'created_at': 'Created At',
		'updated_at': 'Updated At',
	}
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class MaterialMovementView(ModelView):
	datamodel = SQLAInterface(MaterialMovement)

	list_columns = ['ledger_id', 'posting_date', 'movement_type', 'quantity',
					'preliminary_value_cents', 'variance_type']
	show_columns = ['id', 'posting_date', 'movement_type', 'quantity',
					'unit_of_measure', 'preliminary_value_cents',
					'actual_value_cents', 'variance_cents', 'variance_type',
					'source_document_type', 'source_document_id', 'is_reversal',
					'posting_reference', 'created_at']
	label_columns = {
		'ledger_id': 'Material Ledger',
		'posting_date': 'Posting Date',
		'movement_type': 'Movement Type',
		'quantity': 'Quantity',
		'preliminary_value_cents': 'Preliminary Value (cents)',
		'variance_type': 'Variance Type',
		'unit_of_measure': 'Unit of Measure',
		'actual_value_cents': 'Actual Value (cents)',
		'variance_cents': 'Variance (cents)',
		'source_document_type': 'Source Document Type',
		'source_document_id': 'Source Document',
		'is_reversal': 'Reversal',
		'posting_reference': 'Posting Reference',
		'created_at': 'Created At',
	}
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


class ActualCostRevaluationView(ModelView):
	datamodel = SQLAInterface(CostSettlement)

	list_title = 'Actual Cost Settlement Runs'
	list_columns = ['period_id', 'plant_id', 'status', 'run_at',
					'materials_processed', 'total_variance_cents']
	show_columns = ['id', 'plant_id', 'run_at', 'run_by', 'status',
					'levels_processed', 'materials_processed',
					'total_variance_cents', 'error_log', 'completed_at',
					'created_at']
	label_columns = {
		'period_id': 'Costing Period',
		'plant_id': 'Plant',
		'status': 'Status',
		'run_at': 'Run At',
		'materials_processed': 'Materials Processed',
		'total_variance_cents': 'Total Variance (cents)',
		'run_by': 'Run By',
		'levels_processed': 'Levels Processed',
		'error_log': 'Error Log',
		'completed_at': 'Completed At',
		'created_at': 'Created At',
	}
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


__all__ = [
	'MaterialLedgerEntryView',
	'MaterialMovementView',
	'ActualCostRevaluationView',
]
