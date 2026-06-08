from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.hedge_accounting.models import (
	HedgeRelationship,
	HedgeEffectivenessTest,
	HedgeFairValueMovement,
)


class HedgeRelationshipView(ModelView):
	datamodel = SQLAInterface(HedgeRelationship)

	list_columns = ['hedge_reference', 'hedge_type', 'status', 'designation_date',
					'maturity_date', 'hedged_risk', 'oci_balance_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class HedgeEffectivenessTestView(ModelView):
	datamodel = SQLAInterface(HedgeEffectivenessTest)

	list_columns = ['relationship_id', 'test_date', 'test_type', 'effectiveness_ratio',
					'is_effective', 'effective_portion_cents', 'ineffective_portion_cents']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


class HedgeFairValueMovementView(ModelView):
	datamodel = SQLAInterface(HedgeFairValueMovement)

	list_columns = ['relationship_id', 'valuation_date', 'instrument_fair_value_cents',
					'oci_movement_cents', 'pl_movement_cents', 'cumulative_oci_cents']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


class HedgeJournalEntryView(ModelView):
	datamodel = SQLAInterface(HedgeFairValueMovement)

	list_title = 'Hedge Journal Entries'
	list_columns = ['relationship_id', 'valuation_date', 'oci_movement_cents',
					'pl_movement_cents', 'reclassified_to_pl_cents', 'gl_journal_id']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


__all__ = [
	'HedgeRelationshipView',
	'HedgeEffectivenessTestView',
	'HedgeFairValueMovementView',
	'HedgeJournalEntryView',
]
