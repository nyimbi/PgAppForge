from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.procurement.trade_compliance.models import (
	TradeRestrictionList,
	TradeScreeningResult,
	HSCodeMapping,
)


class TradeRestrictionListView(ModelView):
	datamodel = SQLAInterface(TradeRestrictionList)

	list_columns = ['list_name', 'entry_count', 'is_active', 'last_updated']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class TradeScreeningResultView(ModelView):
	datamodel = SQLAInterface(TradeScreeningResult)

	list_columns = ['entity_name', 'status', 'screened_at', 'hit_count',
					'top_match_name', 'top_match_score', 'matched_list',
					'source_document_type']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class HSCodeMappingView(ModelView):
	datamodel = SQLAInterface(HSCodeMapping)

	list_columns = ['product_code', 'hs_code', 'country_code',
					'duty_rate_pct', 'is_controlled']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'TradeRestrictionListView',
	'TradeScreeningResultView',
	'HSCodeMappingView',
]
