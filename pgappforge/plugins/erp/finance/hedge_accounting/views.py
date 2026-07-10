from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.hedge_accounting.models import (
	HedgeRelationship,
	HedgeJournalEntry,
)


class HedgeRelationshipView(ModelView):
	datamodel = SQLAInterface(HedgeRelationship)

	list_columns = ['name', 'hedged_item_type', 'hedging_instrument_type',
					'notional_cents', 'currency_code', 'start_date',
					'maturity_date', 'status']
	show_columns = ['id', 'name', 'hedged_item_type', 'hedging_instrument_type',
					'notional_cents', 'currency_code', 'start_date',
					'maturity_date', 'effectiveness_lower', 'effectiveness_upper',
					'status']
	label_columns = {
		'name': 'Name',
		'hedged_item_type': 'Hedged Item Type',
		'hedging_instrument_type': 'Hedging Instrument Type',
		'notional_cents': 'Notional (cents)',
		'currency_code': 'Currency',
		'start_date': 'Start Date',
		'maturity_date': 'Maturity Date',
		'status': 'Status',
		'effectiveness_lower': 'Effectiveness Lower %',
		'effectiveness_upper': 'Effectiveness Upper %',
	}
	search_columns = ['name', 'hedged_item_type', 'hedging_instrument_type', 'currency_code', 'status']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


# HedgeEffectivenessTest and HedgeFairValueMovement models do not exist in
# models.py, so their ModelViews are intentionally skipped.


class HedgeJournalEntryView(ModelView):
	datamodel = SQLAInterface(HedgeJournalEntry)

	list_title = 'Hedge Journal Entries'
	list_columns = ['hedge_id', 'period', 'hedging_instrument_change_cents',
					'hedged_item_change_cents', 'effectiveness_ratio',
					'effective_gain_cents', 'ineffective_gain_cents', 'oci_cents',
					'pl_cents', 'gl_posted']
	show_columns = ['id', 'hedge_id', 'period', 'hedging_instrument_change_cents',
					'hedged_item_change_cents', 'effectiveness_ratio',
					'effective_gain_cents', 'ineffective_gain_cents', 'oci_cents',
					'pl_cents', 'gl_posted', 'created_at']
	label_columns = {
		'hedge_id': 'Hedge',
		'period': 'Period',
		'hedging_instrument_change_cents': 'Hedging Instrument Change (cents)',
		'hedged_item_change_cents': 'Hedged Item Change (cents)',
		'effectiveness_ratio': 'Effectiveness Ratio',
		'effective_gain_cents': 'Effective Gain (cents)',
		'ineffective_gain_cents': 'Ineffective Gain (cents)',
		'oci_cents': 'OCI (cents)',
		'pl_cents': 'P&L (cents)',
		'gl_posted': 'GL Posted',
		'created_at': 'Created At',
	}
	search_columns = ['hedge_id', 'period', 'gl_posted']
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


__all__ = [
	'HedgeRelationshipView',
	'HedgeJournalEntryView',
]
