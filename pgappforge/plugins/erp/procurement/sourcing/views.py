from __future__ import annotations

from decimal import Decimal

from flask import flash, redirect, request

from pgappforge import ModelView
from pgappforge.actions import action
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.procurement.sourcing.models import (
	ProcurementSavings,
	RFQ,
	SupplierBid,
)
from pgappforge.plugins.erp.procurement.sourcing.services import SourcingService


def _format_cents(value):
	if value is None:
		return ""
	return f"{Decimal(int(value)) / Decimal('100'):,.2f}"


class RFQView(ModelView):
	datamodel = SQLAInterface(RFQ)

	list_columns = ['rfq_ref', 'title', 'rfq_type', 'status',
					'submission_deadline', 'auction_mode', 'reserve_price_cents',
					'current_best_bid_cents', 'auction_end_time']
	add_columns = ['tenant_id', 'title', 'description', 'rfq_ref', 'rfq_type',
				   'status', 'submission_deadline', 'evaluation_criteria', 'items',
				   'invited_suppliers', 'auction_mode', 'reserve_price_cents',
				   'current_best_bid_cents', 'auction_end_time', 'auction_bids',
				   'entity_id', 'created_by']
	edit_columns = add_columns
	formatters_columns = {
		'reserve_price_cents': _format_cents,
		'current_best_bid_cents': _format_cents,
	}

	@action('start_auction', 'Start Auction', 'Start a 60 minute reverse auction', 'fa-gavel')
	def start_auction(self, items):
		session = self.datamodel.session
		started = 0
		for item in items:
			try:
				reserve_price_cents = int(item.reserve_price_cents or item.current_best_bid_cents or 0)
				if reserve_price_cents <= 0:
					estimated = sum(
						int(line.get('estimated_unit_price_cents', 0) or 0)
						* int(line.get('qty', 1) or 1)
						for line in item.items or []
					)
					reserve_price_cents = estimated
				SourcingService.start_reverse_auction(
					rfq_id=item.id,
					duration_minutes=60,
					reserve_price_cents=reserve_price_cents,
					session=session,
				)
				started += 1
			except Exception as exc:
				flash(f"Could not start auction for {item.rfq_ref}: {exc}", "warning")
		if started:
			session.commit()
			flash(f"Started {started} reverse auction(s)", "success")
		return redirect(request.referrer)


class SupplierBidView(ModelView):
	datamodel = SQLAInterface(SupplierBid)

	list_columns = ['rfq_id', 'supplier_id', 'status', 'total_bid_cents',
					'currency_code', 'composite_score', 'delivery_days']
	add_columns = ['tenant_id', 'rfq_id', 'supplier_id', 'submitted_at', 'status',
				   'total_bid_cents', 'currency_code', 'validity_days', 'delivery_days',
				   'quality_notes', 'line_items', 'technical_score', 'commercial_score',
				   'composite_score']
	edit_columns = add_columns
	formatters_columns = {'total_bid_cents': _format_cents}


class ProcurementSavingsView(ModelView):
	datamodel = SQLAInterface(ProcurementSavings)

	list_columns = ['rfq_id', 'baseline_price_cents', 'awarded_price_cents',
					'savings_cents', 'savings_pct', 'category', 'recorded_at']
	add_columns = ['tenant_id', 'rfq_id', 'baseline_price_cents', 'awarded_price_cents',
				   'savings_cents', 'savings_pct', 'category', 'recorded_at']
	edit_columns = add_columns
	formatters_columns = {
		'baseline_price_cents': _format_cents,
		'awarded_price_cents': _format_cents,
		'savings_cents': _format_cents,
	}


__all__ = [
	'RFQView',
	'SupplierBidView',
	'ProcurementSavingsView',
]
