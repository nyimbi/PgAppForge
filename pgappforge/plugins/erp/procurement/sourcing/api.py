"""REST APIs for ERP models in this plugin."""
from __future__ import annotations

from pgappforge.api import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface

from .models import (
	RFQ,
	ProcurementSavings,
	SupplierBid,
)

try:
	from .models import RFQAward
except ImportError:  # RFQAward may exist only in local/unreleased sourcing work.
	RFQAward = None


class RFQRestApi(ModelRestApi):
	resource_name = 'erp/procurement/sourcing/rfq'
	openapi_spec_tag = 'Procurement Sourcing'
	datamodel = SQLAInterface(RFQ)
	list_columns = [
		'id',
		'tenant_id',
		'title',
		'description',
		'rfq_ref',
		'rfq_type',
		'status',
		'submission_deadline',
		'evaluation_criteria',
		'items',
		'invited_suppliers',
		'auction_mode',
		'reserve_price_cents',
		'current_best_bid_cents',
		'auction_end_time',
		'auction_bids',
		'entity_id',
		'created_by',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'title',
		'description',
		'rfq_ref',
		'rfq_type',
		'status',
		'submission_deadline',
		'evaluation_criteria',
		'items',
		'invited_suppliers',
		'auction_mode',
		'reserve_price_cents',
		'current_best_bid_cents',
		'auction_end_time',
		'auction_bids',
		'entity_id',
		'created_by',
	]
	edit_columns = add_columns
	search_columns = [
		'title',
		'description',
		'rfq_ref',
		'rfq_type',
		'status',
		'invited_suppliers',
		'entity_id',
	]


class SupplierBidRestApi(ModelRestApi):
	resource_name = 'erp/procurement/sourcing/supplier_bid'
	openapi_spec_tag = 'Procurement Sourcing'
	datamodel = SQLAInterface(SupplierBid)
	list_columns = [
		'id',
		'tenant_id',
		'rfq_id',
		'supplier_id',
		'submitted_at',
		'status',
		'total_bid_cents',
		'currency_code',
		'validity_days',
		'delivery_days',
		'quality_notes',
		'line_items',
		'technical_score',
		'commercial_score',
		'composite_score',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'rfq_id',
		'supplier_id',
		'submitted_at',
		'status',
		'total_bid_cents',
		'currency_code',
		'validity_days',
		'delivery_days',
		'quality_notes',
		'line_items',
		'technical_score',
		'commercial_score',
		'composite_score',
	]
	edit_columns = add_columns
	search_columns = [
		'supplier_id',
		'status',
		'currency_code',
		'quality_notes',
	]


if RFQAward is not None:

	class RFQAwardRestApi(ModelRestApi):
		resource_name = 'erp/procurement/sourcing/rfq_award'
		openapi_spec_tag = 'Procurement Sourcing'
		datamodel = SQLAInterface(RFQAward)
		list_columns = [
			'id',
			'tenant_id',
			'rfq_id',
			'supplier_id',
			'award_price_cents',
			'award_source',
			'award_details',
			'awarded_at',
		]
		show_columns = list_columns
		add_columns = [
			'tenant_id',
			'rfq_id',
			'supplier_id',
			'award_price_cents',
			'award_source',
			'award_details',
			'awarded_at',
		]
		edit_columns = add_columns
		search_columns = [
			'supplier_id',
			'award_source',
		]


class ProcurementSavingsRestApi(ModelRestApi):
	resource_name = 'erp/procurement/sourcing/procurement_savings'
	openapi_spec_tag = 'Procurement Sourcing'
	datamodel = SQLAInterface(ProcurementSavings)
	list_columns = [
		'id',
		'tenant_id',
		'rfq_id',
		'baseline_price_cents',
		'awarded_price_cents',
		'savings_cents',
		'savings_pct',
		'category',
		'recorded_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'rfq_id',
		'baseline_price_cents',
		'awarded_price_cents',
		'savings_cents',
		'savings_pct',
		'category',
		'recorded_at',
	]
	edit_columns = add_columns
	search_columns = [
		'category',
	]


API_CLASSES = [
	RFQRestApi,
	SupplierBidRestApi,
	ProcurementSavingsRestApi,
]

if RFQAward is not None:
	API_CLASSES.insert(2, RFQAwardRestApi)
