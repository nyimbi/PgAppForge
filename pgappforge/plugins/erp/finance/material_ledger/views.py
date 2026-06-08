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
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class MaterialMovementView(ModelView):
	datamodel = SQLAInterface(MaterialMovement)

	list_columns = ['ledger_id', 'posting_date', 'movement_type', 'quantity',
					'preliminary_value_cents', 'variance_type']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


class ActualCostRevaluationView(ModelView):
	datamodel = SQLAInterface(CostSettlement)

	list_title = 'Actual Cost Settlement Runs'
	list_columns = ['period_id', 'plant_id', 'status', 'run_at',
					'materials_processed', 'total_variance_cents']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


__all__ = [
	'MaterialLedgerEntryView',
	'MaterialMovementView',
	'ActualCostRevaluationView',
]
