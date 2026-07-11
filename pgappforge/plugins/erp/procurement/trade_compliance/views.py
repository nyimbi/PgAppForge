from __future__ import annotations
from flask_babel import lazy_gettext as _

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

	label_columns = {
		'list_name': _('List Name'),
		'description': _('Description'),
		'last_updated': _('Last Updated'),
		'entry_count': _('Entry Count'),
		'is_active': _('Active'),
		'entries': _('Entries'),
	}
	list_columns = ['list_name', 'entry_count', 'is_active', 'last_updated']
	show_columns = ['tenant_id', 'list_name', 'description', 'last_updated',
					'entry_count', 'is_active', 'entries', 'created_at',
					'updated_at']
	search_columns = ['list_name', 'description']
	add_columns = ['tenant_id', 'list_name', 'description', 'last_updated',
				   'entry_count', 'is_active', 'entries']
	edit_columns = add_columns


class TradeScreeningResultView(ModelView):
	datamodel = SQLAInterface(TradeScreeningResult)

	label_columns = {
		'entity_name': _('Entity Name'),
		'status': _('Status'),
		'screened_at': _('Screened At'),
		'hit_count': _('Hit Count'),
		'top_match_name': _('Top Match Name'),
		'top_match_score': _('Top Match Score'),
		'matched_list': _('Matched List'),
		'source_document_type': _('Source Document Type'),
		'source_document_id': _('Source Document ID'),
	}
	list_columns = ['entity_name', 'status', 'screened_at', 'hit_count',
					'top_match_name', 'top_match_score', 'matched_list',
					'source_document_type']
	show_columns = ['tenant_id', 'entity_name', 'screened_at', 'hit_count',
					'top_match_name', 'top_match_score', 'matched_list',
					'status', 'source_document_type', 'source_document_id',
					'created_at', 'updated_at']
	search_columns = ['entity_name', 'status', 'top_match_name', 'matched_list',
					  'source_document_type', 'source_document_id']
	add_columns = ['tenant_id', 'entity_name', 'screened_at', 'hit_count',
				   'top_match_name', 'top_match_score', 'matched_list', 'status',
				   'source_document_type', 'source_document_id']
	edit_columns = add_columns


class HSCodeMappingView(ModelView):
	datamodel = SQLAInterface(HSCodeMapping)

	label_columns = {
		'product_code': _('Product Code'),
		'hs_code': _('HS Code'),
		'description': _('Description'),
		'country_code': _('Country'),
		'duty_rate_pct': _('Duty Rate'),
		'is_controlled': _('Controlled'),
	}
	list_columns = ['product_code', 'hs_code', 'country_code',
					'duty_rate_pct', 'is_controlled']
	show_columns = ['tenant_id', 'product_code', 'hs_code', 'description',
					'country_code', 'duty_rate_pct', 'is_controlled',
					'created_at', 'updated_at']
	search_columns = ['product_code', 'hs_code', 'description', 'country_code']
	add_columns = ['tenant_id', 'product_code', 'hs_code', 'description',
				   'country_code', 'duty_rate_pct', 'is_controlled']
	edit_columns = add_columns


class CustomsDeclarationView(ModelView):
	datamodel = SQLAInterface(CustomsDeclaration)

	label_columns = {
		'shipment_id': _('Shipment'),
		'export_country': _('Export Country'),
		'import_country': _('Import Country'),
		'status': _('Status'),
		'total_value_cents': _('Total Value'),
		'total_duty_cents': _('Total Duty'),
		'lines': _('Lines'),
		'submitted_at': _('Submitted At'),
		'cleared_at': _('Cleared At'),
		'declaration_reference': _('Declaration Reference'),
	}
	list_columns = ['shipment_id', 'export_country', 'import_country', 'status',
					'total_value_cents', 'total_duty_cents', 'submitted_at',
					'declaration_reference']
	show_columns = ['tenant_id', 'shipment_id', 'export_country', 'import_country',
					'total_value_cents', 'total_duty_cents', 'lines', 'status',
					'submitted_at', 'cleared_at', 'declaration_reference',
					'created_at', 'updated_at']
	search_columns = ['shipment_id', 'export_country', 'import_country', 'status',
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
