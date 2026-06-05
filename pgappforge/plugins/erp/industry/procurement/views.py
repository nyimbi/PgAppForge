"""
pgappforge/plugins/erp/industry/procurement/views.py

Flask views for the Public Procurement plugin.

Views:
  TenderNoticeView       — CRUD + publish action + OCDS release export
  BidView                — CRUD + evaluate bids action + award action
  ContractView           — CRUD + milestone tracking
  ContractMilestoneView  — CRUD for milestones within a contract
  ContractPaymentView    — Immutable read-only payment ledger
  ProcurementDashboard   — Spend analytics, tender pipeline, OCDS stats

Widget usage:
  CurrencyWidget         — all cent fields
  DatePickerWidget       — deadline_date, signed_date, start_date, end_date
  DateRangeWidget        — contract period (start_date–end_date)
  AdvancedChartsWidget   — spend by category/method bar charts
  JSONEditorWidget       — lots, items, documents, amendments (read-only on view)
  StarRatingWidget       — overall_score (0–5 stars mapped from 0–100)
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.commons import format_currency
from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	currency_widget,
	date_widget,
	date_range_widget,
	json_widget,
	star_widget,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.procurement.services import ProcurementService
	return ProcurementService()


# ---------------------------------------------------------------------------
# TenderNoticeView
# ---------------------------------------------------------------------------

class TenderNoticeView(BaseView):
	"""Tender notice CRUD + OCDS release export.

	Widgets used:
	  CurrencyWidget  — tender_value_estimate_cents
	  DatePickerWidget — publication_date, deadline_date
	  JSONEditorWidget — lots, items, documents (readonly on detail view)

	GET  /procurement/tenders/             — list
	GET  /procurement/tenders/<id>         — detail
	POST /procurement/tenders/             — publish tender
	GET  /procurement/tenders/<id>/ocds    — OCDS 1.1 release JSON
	"""

	route_base = "/procurement/tenders"
	default_view = "list"

	widgets = {
		"tender_value_estimate_cents": currency_widget("USD"),
		"publication_date": date_widget("YYYY-MM-DD"),
		"deadline_date": date_widget("YYYY-MM-DD"),
		"lots": json_widget(mode="view", readonly=True),
		"items": json_widget(mode="view", readonly=True),
		"documents": json_widget(mode="view", readonly=True),
	}

	list_columns = [
		"ocid", "title", "procurement_method", "main_procurement_category",
		"tender_value_estimate_cents", "deadline_date", "status",
	]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.procurement.models import TenderNotice
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		category = request.args.get("category")

		q = sa.select(TenderNotice).order_by(TenderNotice.publication_date.desc()).limit(500)
		if tenant_id:
			q = q.where(TenderNotice.tenant_id == tenant_id)
		if status:
			q = q.where(TenderNotice.status == status)
		if category:
			q = q.where(TenderNotice.main_procurement_category == category)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": t.id,
				"ocid": t.ocid,
				"title": t.title,
				"procurement_method": t.procurement_method,
				"main_procurement_category": t.main_procurement_category,
				"tender_value_estimate_cents": t.tender_value_estimate_cents,
				"currency_code": t.currency_code,
				"publication_date": t.publication_date.isoformat() if t.publication_date else None,
				"deadline_date": t.deadline_date.isoformat() if t.deadline_date else None,
				"status": t.status,
			}
			for t in rows
		])

	@expose("/<string:tender_id>")
	@has_access
	def detail(self, tender_id: str):
		from pgappforge.plugins.erp.industry.procurement.models import TenderNotice
		session = _get_session()
		t = session.get(TenderNotice, tender_id)
		if t is None:
			abort(404)
		return jsonify({
			"id": t.id,
			"tenant_id": t.tenant_id,
			"ocid": t.ocid,
			"title": t.title,
			"description": t.description,
			"procuring_entity_id": t.procuring_entity_id,
			"procurement_method": t.procurement_method,
			"main_procurement_category": t.main_procurement_category,
			"tender_value_estimate_cents": t.tender_value_estimate_cents,
			"currency_code": t.currency_code,
			"publication_date": t.publication_date.isoformat() if t.publication_date else None,
			"deadline_date": t.deadline_date.isoformat() if t.deadline_date else None,
			"eligibility_criteria": t.eligibility_criteria,
			"selection_criteria": t.selection_criteria,
			"lots": t.lots,
			"items": t.items,
			"documents": t.documents,
			"status": t.status,
			"_widget_hints": TenderNoticeView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Publish a new tender notice."""
		from datetime import datetime, timezone
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "ocid", "title", "procuring_entity_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		deadline = None
		if data.get("deadline_date"):
			try:
				deadline = datetime.fromisoformat(data["deadline_date"])
			except ValueError:
				return jsonify({"error": "Invalid deadline_date format; use ISO 8601"}), 400

		try:
			notice = _svc().publish_tender(
				tenant_id=data["tenant_id"],
				ocid=data["ocid"],
				title=data["title"],
				procuring_entity_id=data["procuring_entity_id"],
				procurement_method=data.get("procurement_method", "OPEN"),
				main_procurement_category=data.get("main_procurement_category", "GOODS"),
				description=data.get("description"),
				tender_value_estimate_cents=int(data["tender_value_estimate_cents"]) if data.get("tender_value_estimate_cents") else None,
				currency_code=data.get("currency_code", "USD"),
				deadline_date=deadline,
				eligibility_criteria=data.get("eligibility_criteria"),
				selection_criteria=data.get("selection_criteria"),
				lots=data.get("lots", []),
				items=data.get("items", []),
				documents=data.get("documents", []),
				session=session,
			)
			session.commit()
			return jsonify({"tender_id": notice.id, "ocid": notice.ocid, "status": notice.status}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:tender_id>/ocds")
	@has_access
	def ocds_release(self, tender_id: str):
		"""Return OCDS 1.1-compliant release JSON for a tender."""
		session = _get_session()
		try:
			release = _svc().generate_ocds_release(tender_id, session)
			return jsonify(release)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# BidView
# ---------------------------------------------------------------------------

class BidView(BaseView):
	"""Bid CRUD + evaluation + award actions.

	Widgets used:
	  CurrencyWidget   — bid_price_cents
	  StarRatingWidget — overall_score (0–100 mapped to 0–5 stars)
	  DatePickerWidget — submission_date
	  JSONEditorWidget — lot_bids, documents (readonly on detail)

	GET  /procurement/bids/                        — list
	GET  /procurement/bids/<id>                    — detail
	POST /procurement/bids/                        — submit bid
	POST /procurement/tenders/<tid>/evaluate       — evaluate all bids
	POST /procurement/bids/<id>/award              — award contract from bid
	"""

	route_base = "/procurement/bids"
	default_view = "list"

	widgets = {
		"bid_price_cents": currency_widget("USD"),
		"overall_score": star_widget(max_rating=5, readonly=True),
		"submission_date": date_widget("YYYY-MM-DD"),
		"lot_bids": json_widget(mode="view", readonly=True),
		"documents": json_widget(mode="view", readonly=True),
	}

	list_columns = [
		"tender_id", "bidder_id", "bid_price_cents", "currency_code",
		"technical_score", "overall_score", "status",
	]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.procurement.models import Bid
		session = _get_session()
		tender_id = request.args.get("tender_id")
		status = request.args.get("status")
		tenant_id = request.args.get("tenant_id")

		q = sa.select(Bid).order_by(Bid.submission_date.desc()).limit(500)
		if tender_id:
			q = q.where(Bid.tender_id == tender_id)
		if status:
			q = q.where(Bid.status == status)
		if tenant_id:
			q = q.where(Bid.tenant_id == tenant_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": b.id,
				"tender_id": b.tender_id,
				"bidder_id": b.bidder_id,
				"submission_date": b.submission_date.isoformat() if b.submission_date else None,
				"bid_price_cents": b.bid_price_cents,
				"currency_code": b.currency_code,
				"technical_score": float(b.technical_score) if b.technical_score is not None else None,
				"financial_score": float(b.financial_score) if b.financial_score is not None else None,
				"overall_score": float(b.overall_score) if b.overall_score is not None else None,
				"status": b.status,
			}
			for b in rows
		])

	@expose("/<string:bid_id>")
	@has_access
	def detail(self, bid_id: str):
		from pgappforge.plugins.erp.industry.procurement.models import Bid
		session = _get_session()
		b = session.get(Bid, bid_id)
		if b is None:
			abort(404)
		return jsonify({
			"id": b.id,
			"tenant_id": b.tenant_id,
			"tender_id": b.tender_id,
			"bidder_id": b.bidder_id,
			"submission_date": b.submission_date.isoformat() if b.submission_date else None,
			"bid_price_cents": b.bid_price_cents,
			"currency_code": b.currency_code,
			"technical_score": float(b.technical_score) if b.technical_score is not None else None,
			"financial_score": float(b.financial_score) if b.financial_score is not None else None,
			"overall_score": float(b.overall_score) if b.overall_score is not None else None,
			"lot_bids": b.lot_bids,
			"documents": b.documents,
			"status": b.status,
			"disqualification_reason": b.disqualification_reason,
			"_widget_hints": BidView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Submit a bid against a tender."""
		from datetime import datetime, timezone
		from pgappforge.plugins.erp.industry.procurement.models import Bid
		from pgappforge.plugins.erp.industry.procurement.events import BidSubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "tender_id", "bidder_id", "bid_price_cents")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		now = datetime.now(timezone.utc)
		bid = Bid(
			tenant_id=data["tenant_id"],
			tender_id=data["tender_id"],
			bidder_id=data["bidder_id"],
			submission_date=now,
			bid_price_cents=int(data["bid_price_cents"]),
			currency_code=data.get("currency_code", "USD"),
			technical_score=data.get("technical_score"),
			lot_bids=data.get("lot_bids", []),
			documents=data.get("documents", []),
			status="SUBMITTED",
		)
		session.add(bid)
		session.flush()
		emit_event(
			BidSubmittedEvent(
				aggregate_id=bid.id,
				aggregate_type="Bid",
				tenant_id=data["tenant_id"],
				bid_id=bid.id,
				tender_id=data["tender_id"],
				bidder_id=data["bidder_id"],
				bid_price_cents=bid.bid_price_cents,
				currency_code=bid.currency_code,
				submission_date=now.isoformat(),
			),
			session,
		)
		session.commit()
		return jsonify({"bid_id": bid.id, "status": bid.status}), 201

	@expose("/tender/<string:tender_id>/evaluate", methods=["POST"])
	@has_access
	def evaluate(self, tender_id: str):
		"""Evaluate and rank all bids for a tender."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			results = _svc().evaluate_bids(
				tender_id=tender_id,
				criteria_weights=data.get("criteria_weights"),
				session=session,
			)
			session.commit()
			return jsonify({
				"tender_id": tender_id,
				"evaluated_count": len(results),
				"ranked_bids": results,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:bid_id>/award", methods=["POST"])
	@has_access
	def award(self, bid_id: str):
		"""Award a contract from a winning bid."""
		from datetime import date
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			signed_date = date.fromisoformat(data["signed_date"]) if data.get("signed_date") else None
			start_date = date.fromisoformat(data["start_date"]) if data.get("start_date") else None
			end_date = date.fromisoformat(data["end_date"]) if data.get("end_date") else None
			contract = _svc().award_contract(
				bid_id=bid_id,
				title=data.get("title"),
				description=data.get("description"),
				signed_date=signed_date,
				start_date=start_date,
				end_date=end_date,
				performance_bond_pct=data.get("performance_bond_pct", 0),
				session=session,
			)
			session.commit()
			return jsonify({
				"contract_id": contract.id,
				"award_id": contract.award_id,
				"supplier_id": contract.supplier_id,
				"contract_value_cents": contract.contract_value_cents,
				"status": contract.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ContractView
# ---------------------------------------------------------------------------

class ContractView(BaseView):
	"""Contract CRUD + performance tracking.

	Widgets used:
	  CurrencyWidget   — contract_value_cents
	  DateRangeWidget  — start_date–end_date
	  DatePickerWidget — signed_date
	  JSONEditorWidget — amendments (readonly)
	  AdvancedChartsWidget — spend-over-time line chart in detail

	GET  /procurement/contracts/                 — list
	GET  /procurement/contracts/<id>             — detail
	GET  /procurement/contracts/<id>/performance — performance + milestone + payment summary
	"""

	route_base = "/procurement/contracts"
	default_view = "list"

	widgets = {
		"contract_value_cents": currency_widget("USD"),
		"contract_period": date_range_widget(),
		"signed_date": date_widget("YYYY-MM-DD"),
		"amendments": json_widget(mode="view", readonly=True),
		"spend_trend": {
			**chart_widget("line"),
			"label": "Spend Over Time",
			"data_endpoint": "/procurement/contracts/{id}/spend-data",
		},
	}

	list_columns = [
		"award_id", "tender_id", "supplier_id", "contract_value_cents",
		"signed_date", "start_date", "end_date", "status",
	]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.procurement.models import Contract
		session = _get_session()
		tender_id = request.args.get("tender_id")
		status = request.args.get("status")
		tenant_id = request.args.get("tenant_id")

		q = sa.select(Contract).order_by(Contract.signed_date.desc().nullslast()).limit(500)
		if tender_id:
			q = q.where(Contract.tender_id == tender_id)
		if status:
			q = q.where(Contract.status == status)
		if tenant_id:
			q = q.where(Contract.tenant_id == tenant_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": c.id,
				"award_id": c.award_id,
				"tender_id": c.tender_id,
				"supplier_id": c.supplier_id,
				"title": c.title,
				"contract_value_cents": c.contract_value_cents,
				"currency_code": c.currency_code,
				"signed_date": c.signed_date.isoformat() if c.signed_date else None,
				"start_date": c.start_date.isoformat() if c.start_date else None,
				"end_date": c.end_date.isoformat() if c.end_date else None,
				"status": c.status,
			}
			for c in rows
		])

	@expose("/<string:contract_id>")
	@has_access
	def detail(self, contract_id: str):
		from pgappforge.plugins.erp.industry.procurement.models import Contract
		session = _get_session()
		c = session.get(Contract, contract_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"tenant_id": c.tenant_id,
			"award_id": c.award_id,
			"tender_id": c.tender_id,
			"supplier_id": c.supplier_id,
			"title": c.title,
			"description": c.description,
			"contract_value_cents": c.contract_value_cents,
			"currency_code": c.currency_code,
			"signed_date": c.signed_date.isoformat() if c.signed_date else None,
			"start_date": c.start_date.isoformat() if c.start_date else None,
			"end_date": c.end_date.isoformat() if c.end_date else None,
			"status": c.status,
			"performance_bond_pct": float(c.performance_bond_pct or 0),
			"amendments": c.amendments,
			"_widget_hints": ContractView.widgets,
		})

	@expose("/<string:contract_id>/performance")
	@has_access
	def performance(self, contract_id: str):
		"""Return performance summary: milestones, payments, spend %."""
		session = _get_session()
		try:
			result = _svc().track_contract_performance(contract_id, session)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/<string:contract_id>/spend-data")
	@has_access
	def spend_data(self, contract_id: str):
		"""Time-series payment data for AdvancedChartsWidget (line chart)."""
		from pgappforge.plugins.erp.industry.procurement.models import ContractPayment
		session = _get_session()
		payments = session.execute(
			sa.select(ContractPayment)
			.where(ContractPayment.contract_id == contract_id)
			.order_by(ContractPayment.payment_date)
		).scalars().all()

		cumulative = 0
		data_points = []
		for p in payments:
			cumulative += p.amount_cents
			data_points.append({
				"x": p.payment_date.isoformat(),
				"y": cumulative,
				"payment_id": p.id,
				"invoice_reference": p.invoice_reference,
			})

		return jsonify({
			"chart_type": "line",
			"title": "Cumulative Contract Spend",
			"x_label": "Payment Date",
			"y_label": "Cumulative Spend (cents)",
			"data": data_points,
		})


# ---------------------------------------------------------------------------
# ContractMilestoneView
# ---------------------------------------------------------------------------

class ContractMilestoneView(BaseView):
	"""Contract milestone CRUD.

	GET  /procurement/milestones/               — list (filter by contract_id)
	GET  /procurement/milestones/<id>           — detail
	POST /procurement/milestones/               — create
	POST /procurement/milestones/<id>/met       — mark milestone met
	"""

	route_base = "/procurement/milestones"
	default_view = "list"

	widgets = {
		"due_date": date_widget("YYYY-MM-DD"),
		"achieved_date": date_widget("YYYY-MM-DD"),
		"payment_pct": {
			"type": "RangeSliderWidget",
			"config": {"min": 0, "max": 100, "step": 0.01, "unit": "%", "readonly": True},
		},
	}

	list_columns = ["contract_id", "title", "milestone_type", "due_date", "payment_pct", "status"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.procurement.models import ContractMilestone
		session = _get_session()
		contract_id = request.args.get("contract_id")
		status = request.args.get("status")

		q = sa.select(ContractMilestone).order_by(ContractMilestone.due_date)
		if contract_id:
			q = q.where(ContractMilestone.contract_id == contract_id)
		if status:
			q = q.where(ContractMilestone.status == status)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": m.id,
				"contract_id": m.contract_id,
				"title": m.title,
				"milestone_type": m.milestone_type,
				"due_date": m.due_date.isoformat(),
				"achieved_date": m.achieved_date.isoformat() if m.achieved_date else None,
				"payment_pct": float(m.payment_pct),
				"status": m.status,
			}
			for m in rows
		])

	@expose("/<string:milestone_id>")
	@has_access
	def detail(self, milestone_id: str):
		from pgappforge.plugins.erp.industry.procurement.models import ContractMilestone
		session = _get_session()
		m = session.get(ContractMilestone, milestone_id)
		if m is None:
			abort(404)
		return jsonify({
			"id": m.id,
			"tenant_id": m.tenant_id,
			"contract_id": m.contract_id,
			"title": m.title,
			"description": m.description,
			"milestone_type": m.milestone_type,
			"due_date": m.due_date.isoformat(),
			"achieved_date": m.achieved_date.isoformat() if m.achieved_date else None,
			"payment_pct": float(m.payment_pct),
			"status": m.status,
			"_widget_hints": ContractMilestoneView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from datetime import date
		from decimal import Decimal
		from pgappforge.plugins.erp.industry.procurement.models import ContractMilestone
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "contract_id", "title", "due_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		m = ContractMilestone(
			tenant_id=data["tenant_id"],
			contract_id=data["contract_id"],
			title=data["title"],
			description=data.get("description"),
			milestone_type=data.get("milestone_type", "DELIVERY"),
			due_date=date.fromisoformat(data["due_date"]),
			payment_pct=Decimal(str(data.get("payment_pct", 0))),
			status="PENDING",
		)
		session.add(m)
		session.commit()
		return jsonify({"milestone_id": m.id, "title": m.title, "status": m.status}), 201

	@expose("/<string:milestone_id>/met", methods=["POST"])
	@has_access
	def mark_met(self, milestone_id: str):
		"""Mark a milestone as MET, record achieved_date."""
		from datetime import date
		from pgappforge.plugins.erp.industry.procurement.models import ContractMilestone
		from pgappforge.plugins.erp.industry.procurement.events import MilestoneMet
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		m = session.get(ContractMilestone, milestone_id)
		if m is None:
			abort(404)

		data = request.get_json(force=True) or {}
		achieved = date.fromisoformat(data["achieved_date"]) if data.get("achieved_date") else date.today()
		m.achieved_date = achieved
		m.status = "MET"

		emit_event(
			MilestoneMet(
				aggregate_id=milestone_id,
				aggregate_type="ContractMilestone",
				tenant_id=m.tenant_id,
				milestone_id=milestone_id,
				contract_id=m.contract_id,
				title=m.title,
				milestone_type=m.milestone_type,
				achieved_date=achieved.isoformat(),
				payment_pct=str(m.payment_pct),
			),
			session,
		)
		session.commit()
		return jsonify({"milestone_id": milestone_id, "status": "MET", "achieved_date": achieved.isoformat()})


# ---------------------------------------------------------------------------
# ContractPaymentView — read-only immutable ledger
# ---------------------------------------------------------------------------

class ContractPaymentView(BaseView):
	"""Read-only view of the immutable contract payment ledger.

	No POST/PUT/DELETE — payments are recorded via a dedicated endpoint.

	POST /procurement/payments/               — record payment (insert-only)
	GET  /procurement/payments/               — list (filter by contract_id)
	GET  /procurement/payments/<id>           — detail
	"""

	route_base = "/procurement/payments"
	default_view = "list"

	widgets = {
		"amount_cents": currency_widget("USD"),
		"payment_date": date_widget("YYYY-MM-DD"),
	}

	list_columns = ["contract_id", "payment_date", "amount_cents", "invoice_reference", "milestone_id"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.procurement.models import ContractPayment
		session = _get_session()
		contract_id = request.args.get("contract_id")
		tenant_id = request.args.get("tenant_id")

		q = sa.select(ContractPayment).order_by(ContractPayment.payment_date.desc()).limit(500)
		if contract_id:
			q = q.where(ContractPayment.contract_id == contract_id)
		if tenant_id:
			q = q.where(ContractPayment.tenant_id == tenant_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"contract_id": p.contract_id,
				"milestone_id": p.milestone_id,
				"payment_date": p.payment_date.isoformat(),
				"amount_cents": p.amount_cents,
				"invoice_reference": p.invoice_reference,
				"description": p.description,
			}
			for p in rows
		])

	@expose("/<string:payment_id>")
	@has_access
	def detail(self, payment_id: str):
		from pgappforge.plugins.erp.industry.procurement.models import ContractPayment
		session = _get_session()
		p = session.get(ContractPayment, payment_id)
		if p is None:
			abort(404)
		return jsonify({
			"id": p.id,
			"tenant_id": p.tenant_id,
			"contract_id": p.contract_id,
			"milestone_id": p.milestone_id,
			"payment_date": p.payment_date.isoformat(),
			"amount_cents": p.amount_cents,
			"invoice_reference": p.invoice_reference,
			"description": p.description,
			"_immutable": True,
			"_widget_hints": ContractPaymentView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Record an immutable contract payment."""
		from datetime import date
		from pgappforge.plugins.erp.industry.procurement.models import ContractPayment
		from pgappforge.plugins.erp.industry.procurement.events import ContractPaymentMadeEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "contract_id", "payment_date", "amount_cents", "invoice_reference")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		p = ContractPayment(
			tenant_id=data["tenant_id"],
			contract_id=data["contract_id"],
			milestone_id=data.get("milestone_id"),
			payment_date=date.fromisoformat(data["payment_date"]),
			amount_cents=int(data["amount_cents"]),
			invoice_reference=data["invoice_reference"],
			description=data.get("description"),
		)
		session.add(p)
		session.flush()

		emit_event(
			ContractPaymentMadeEvent(
				aggregate_id=p.id,
				aggregate_type="ContractPayment",
				tenant_id=data["tenant_id"],
				payment_id=p.id,
				contract_id=data["contract_id"],
				milestone_id=data.get("milestone_id", ""),
				payment_date=data["payment_date"],
				amount_cents=p.amount_cents,
				invoice_reference=p.invoice_reference,
			),
			session,
		)
		session.commit()
		return jsonify({"payment_id": p.id, "amount_cents": p.amount_cents, "_immutable": True}), 201


# ---------------------------------------------------------------------------
# ProcurementDashboard
# ---------------------------------------------------------------------------

class ProcurementDashboard(BaseView):
	"""Spend analytics dashboard for a procuring entity.

	Widgets used:
	  AdvancedChartsWidget — spend by category (bar), spend by method (pie)

	GET /procurement/dashboard/spend/<entity_id>/<int:year>  — spend analytics
	GET /procurement/dashboard/pipeline/<entity_id>          — tender pipeline
	"""

	route_base = "/procurement/dashboard"
	default_view = "spend"

	widgets = {
		"spend_by_category": {
			**chart_widget("bar"),
			"label": "Spend by Category",
			"data_endpoint": "/procurement/dashboard/spend/{entity_id}/{year}",
		},
		"spend_by_method": {
			**chart_widget("pie"),
			"label": "Spend by Procurement Method",
			"data_endpoint": "/procurement/dashboard/spend/{entity_id}/{year}",
		},
	}

	@expose("/spend/<string:entity_id>/<int:year>")
	@has_access
	def spend(self, entity_id: str, year: int):
		"""Spend analytics for a procuring entity in a given year."""
		session = _get_session()
		try:
			result = _svc().calculate_spend_analytics(
				entity_id=entity_id,
				period_year=year,
				session=session,
			)
			# Add chart-friendly data structures
			result["charts"] = {
				"by_category": {
					"type": "bar",
					"labels": list(result["by_category"].keys()),
					"values": list(result["by_category"].values()),
				},
				"by_method": {
					"type": "pie",
					"labels": list(result["by_method"].keys()),
					"values": list(result["by_method"].values()),
				},
			}
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/pipeline/<string:entity_id>")
	@has_access
	def pipeline(self, entity_id: str):
		"""Tender pipeline summary for a procuring entity."""
		from pgappforge.plugins.erp.industry.procurement.models import TenderNotice
		session = _get_session()
		tenders = session.execute(
			sa.select(TenderNotice)
			.where(TenderNotice.procuring_entity_id == entity_id)
			.order_by(TenderNotice.publication_date.desc())
			.limit(100)
		).scalars().all()

		by_status: dict[str, int] = {}
		by_category: dict[str, int] = {}
		total_value = 0

		for t in tenders:
			by_status[t.status] = by_status.get(t.status, 0) + 1
			by_category[t.main_procurement_category] = by_category.get(t.main_procurement_category, 0) + 1
			total_value += t.tender_value_estimate_cents or 0

		return jsonify({
			"entity_id": entity_id,
			"tender_count": len(tenders),
			"total_estimated_value_cents": total_value,
			"by_status": by_status,
			"by_category": by_category,
			"recent_tenders": [
				{
					"id": t.id,
					"ocid": t.ocid,
					"title": t.title,
					"status": t.status,
					"deadline_date": t.deadline_date.isoformat() if t.deadline_date else None,
					"tender_value_estimate_cents": t.tender_value_estimate_cents,
				}
				for t in tenders[:10]
			],
		})


__all__ = [
	"TenderNoticeView",
	"BidView",
	"ContractView",
	"ContractMilestoneView",
	"ContractPaymentView",
	"ProcurementDashboard",
]
