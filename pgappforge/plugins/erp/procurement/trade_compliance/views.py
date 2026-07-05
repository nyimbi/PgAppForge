from __future__ import annotations

from decimal import Decimal

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.procurement.trade_compliance.models import (
	CustomsDeclaration,
	TradeRestrictionList,
	TradeScreeningResult,
	HSCodeMapping,
)


def _format_cents(value):
	if value is None:
		return ""
	return f"{Decimal(int(value)) / Decimal('100'):,.2f}"


class TradeRestrictionListView(ModelView):
	datamodel = SQLAInterface(TradeRestrictionList)

	list_columns = ['list_name', 'entry_count', 'is_active', 'last_updated']
	add_columns = ['tenant_id', 'list_name', 'description', 'last_updated',
				   'entry_count', 'is_active', 'entries']
	edit_columns = add_columns


class TradeScreeningResultView(ModelView):
	datamodel = SQLAInterface(TradeScreeningResult)

	list_columns = ['entity_name', 'status', 'screened_at', 'hit_count',
					'top_match_name', 'top_match_score', 'matched_list',
					'source_document_type']
	add_columns = ['tenant_id', 'entity_name', 'screened_at', 'hit_count',
				   'top_match_name', 'top_match_score', 'matched_list', 'status',
				   'source_document_type', 'source_document_id']
	edit_columns = add_columns


class HSCodeMappingView(ModelView):
	datamodel = SQLAInterface(HSCodeMapping)

	list_columns = ['product_code', 'hs_code', 'country_code',
					'duty_rate_pct', 'is_controlled']
	add_columns = ['tenant_id', 'product_code', 'hs_code', 'description',
				   'country_code', 'duty_rate_pct', 'is_controlled']
	edit_columns = add_columns


class CustomsDeclarationView(ModelView):
	datamodel = SQLAInterface(CustomsDeclaration)

	list_columns = ['shipment_id', 'export_country', 'import_country', 'status',
					'total_value_cents', 'total_duty_cents', 'submitted_at',
					'declaration_reference']
	add_columns = ['tenant_id', 'shipment_id', 'export_country', 'import_country',
				   'total_value_cents', 'total_duty_cents', 'lines', 'status',
				   'submitted_at', 'cleared_at', 'declaration_reference']
	edit_columns = add_columns
	formatters_columns = {
		'total_value_cents': _format_cents,
		'total_duty_cents': _format_cents,
	}


__all__ = [
	'TradeRestrictionListView',
	'TradeScreeningResultView',
	'HSCodeMappingView',
	'CustomsDeclarationView',
]
