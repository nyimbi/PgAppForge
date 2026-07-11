from __future__ import annotations
from flask_babel import lazy_gettext as _

from decimal import Decimal

from flask import flash, redirect, request

from pgappforge import ModelView, expose
from pgappforge.actions import action
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.procurement.sourcing.models import (
	ProcurementSavings,
	RFQ,
	RFQAward,
	SupplierBid,
)
from pgappforge.plugins.erp.procurement.sourcing.services import SourcingService
from pgappforge.plugins.erp.operations.scm.models import PurchaseRequisition


def _format_cents(value):
	if value is None:
		return ""
	return f"{Decimal(int(value)) / Decimal('100'):,.2f}"


def _purchase_requisition_amount_cents(req: PurchaseRequisition) -> int:
	total = Decimal("0")
	for item in req.items or []:
		qty = Decimal(str(item.get("qty", item.get("quantity", 1)) or 0))
		unit_cents = Decimal(str(item.get("estimated_unit_cost_cents", item.get("unit_cost_cents", 0)) or 0))
		total += qty * unit_cents
	return int(total)


class RFQView(ModelView):
	datamodel = SQLAInterface(RFQ)

	label_columns = {
		'rfq_ref': _('RFQ Ref'),
		'title': _('Title'),
		'rfq_type': _('RFQ Type'),
		'status': _('Status'),
		'submission_deadline': _('Submission Deadline'),
		'auction_mode': _('Auction Mode'),
		'reserve_price_cents': _('Reserve Price'),
		'current_best_bid_cents': _('Current Best Bid'),
		'auction_end_time': _('Auction End Time'),
		'evaluation_criteria': _('Evaluation Criteria'),
		'invited_suppliers': _('Invited Suppliers'),
		'auction_bids': _('Auction Bids'),
		'entity_id': _('Entity'),
		'created_by': _('Created By'),
	}
	list_columns = ['rfq_ref', 'title', 'rfq_type', 'status',
					'submission_deadline', 'auction_mode', 'reserve_price_cents',
					'current_best_bid_cents', 'auction_end_time']
	show_columns = ['tenant_id', 'rfq_ref', 'title', 'description', 'rfq_type',
					'status', 'submission_deadline', 'evaluation_criteria', 'items',
					'invited_suppliers', 'auction_mode', 'reserve_price_cents',
					'current_best_bid_cents', 'auction_end_time', 'auction_bids',
					'entity_id', 'created_by', 'created_at', 'updated_at']
	search_columns = ['rfq_ref', 'title', 'rfq_type', 'status', 'entity_id',
					  'created_by']
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

	label_columns = {
		'rfq_id': _('RFQ'),
		'supplier_id': _('Supplier'),
		'status': _('Status'),
		'total_bid_cents': _('Total Bid'),
		'currency_code': _('Currency'),
		'composite_score': _('Composite Score'),
		'delivery_days': _('Delivery Days'),
		'submitted_at': _('Submitted At'),
		'validity_days': _('Validity Days'),
		'quality_notes': _('Quality Notes'),
		'line_items': _('Line Items'),
		'technical_score': _('Technical Score'),
		'commercial_score': _('Commercial Score'),
	}
	list_columns = ['rfq_id', 'supplier_id', 'status', 'total_bid_cents',
					'currency_code', 'composite_score', 'delivery_days']
	show_columns = ['tenant_id', 'rfq_id', 'supplier_id', 'submitted_at', 'status',
					'total_bid_cents', 'currency_code', 'validity_days',
					'delivery_days', 'quality_notes', 'line_items',
					'technical_score', 'commercial_score', 'composite_score',
					'created_at', 'updated_at']
	search_columns = ['supplier_id', 'status', 'currency_code', 'quality_notes']
	add_columns = ['tenant_id', 'rfq_id', 'supplier_id', 'submitted_at', 'status',
				   'total_bid_cents', 'currency_code', 'validity_days', 'delivery_days',
				   'quality_notes', 'line_items', 'technical_score', 'commercial_score',
				   'composite_score']
	edit_columns = add_columns
	formatters_columns = {'total_bid_cents': _format_cents}


class RFQAwardView(ModelView):
	datamodel = SQLAInterface(RFQAward)

	label_columns = {
		'rfq_id': _('RFQ'),
		'supplier_id': _('Supplier'),
		'award_price_cents': _('Award Price'),
		'award_source': _('Award Source'),
		'award_details': _('Award Details'),
		'awarded_at': _('Awarded At'),
	}
	list_columns = ['rfq_id', 'supplier_id', 'award_price_cents', 'award_source',
					'awarded_at']
	show_columns = ['tenant_id', 'rfq_id', 'supplier_id', 'award_price_cents',
					'award_source', 'award_details', 'awarded_at']
	search_columns = ['supplier_id', 'award_source']
	add_columns = ['tenant_id', 'rfq_id', 'supplier_id', 'award_price_cents',
				   'award_source', 'award_details', 'awarded_at']
	edit_columns = add_columns
	formatters_columns = {'award_price_cents': _format_cents}


class ProcurementSavingsView(ModelView):
	datamodel = SQLAInterface(ProcurementSavings)

	label_columns = {
		'rfq_id': _('RFQ'),
		'baseline_price_cents': _('Baseline Price'),
		'awarded_price_cents': _('Awarded Price'),
		'savings_cents': _('Savings'),
		'savings_pct': _('Savings Percent'),
		'category': _('Category'),
		'recorded_at': _('Recorded At'),
	}
	list_columns = ['rfq_id', 'baseline_price_cents', 'awarded_price_cents',
					'savings_cents', 'savings_pct', 'category', 'recorded_at']
	show_columns = ['tenant_id', 'rfq_id', 'baseline_price_cents',
					'awarded_price_cents', 'savings_cents', 'savings_pct',
					'category', 'recorded_at']
	search_columns = ['category']
	add_columns = ['tenant_id', 'rfq_id', 'baseline_price_cents', 'awarded_price_cents',
				   'savings_cents', 'savings_pct', 'category', 'recorded_at']
	edit_columns = add_columns
	formatters_columns = {
		'baseline_price_cents': _format_cents,
		'awarded_price_cents': _format_cents,
		'savings_cents': _format_cents,
	}


class PurchaseRequisitionView(ModelView):
	datamodel = SQLAInterface(PurchaseRequisition)

	label_columns = {
		"requester_id": "Requester",
		"department_id": "Department",
		"req_date": "Request Date",
		"required_by": "Required By",
		"status": "Status",
	}
	list_columns = ["requester_id", "department_id", "req_date", "required_by", "status"]
	show_columns = ["tenant_id", "requester_id", "department_id", "req_date", "required_by", "status", "items", "approved_by", "approved_at", "notes"]
	search_columns = ["requester_id", "department_id", "status"]

	@expose('/submit-approval/<string:doc_id>', methods=['POST'])
	@has_access
	def submit_approval(self, doc_id):
		from pgappforge.plugins.erp.platform.approvals.views import submit_document_approval
		return submit_document_approval(
			document_type="purchase_requisition",
			document_id=doc_id,
			document_model=PurchaseRequisition,
			session=self.datamodel.session,
			amount_getter=_purchase_requisition_amount_cents,
			requester_getter=lambda doc: str(getattr(doc, "requester_id", "")),
		)

	@expose('/approve/<string:request_id>', methods=['POST'])
	@has_access
	def approve(self, request_id):
		from pgappforge.plugins.erp.platform.approvals.views import approve_document_approval
		return approve_document_approval(request_id, self.datamodel.session)

	@expose('/reject/<string:request_id>', methods=['POST'])
	@has_access
	def reject(self, request_id):
		from pgappforge.plugins.erp.platform.approvals.views import reject_document_approval
		return reject_document_approval(request_id, self.datamodel.session)


__all__ = [
	'RFQView',
	'SupplierBidView',
	'RFQAwardView',
	'ProcurementSavingsView',
	'PurchaseRequisitionView',
]
