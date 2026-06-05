"""
pgappforge/plugins/erp/industry/consumer_goods/views.py

Flask views for the Consumer Goods plugin.

Registered views:
  TradePromotionView    — CRUD + approve/launch actions
  RetailExecutionView   — CRUD field visit audits with compliance score display
  PlanoGramView         — CRUD + compliance check
  PromotionClaimView    — CRUD + approve/pay claim actions
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
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
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{_he(title)}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>'
		'body{padding:24px}'
		'.score-high{color:#27ae60;font-weight:bold}'
		'.score-mid{color:#f39c12;font-weight:bold}'
		'.score-low{color:#e74c3c;font-weight:bold}'
		'.stars{color:#f1c40f}'
		'@media print{.noprint{display:none}}'
		'</style>'
		f'</head><body>{body}</body></html>'
	)


def _status_badge(status: str) -> str:
	mapping = {
		"DRAFT": "default",
		"SUBMITTED": "info",
		"APPROVED": "primary",
		"ACTIVE": "success",
		"CLOSED": "warning",
		"CANCELLED": "danger",
		"UNDER_REVIEW": "info",
		"REJECTED": "danger",
		"PAID": "success",
		"DISPUTED": "warning",
		"REVIEWED": "primary",
	}
	cls = mapping.get(status, "default")
	return f"<span class='label label-{cls}'>{_he(status)}</span>"


def _score_class(score_str: str | None) -> str:
	if score_str is None:
		return ""
	try:
		v = float(score_str)
		if v >= 0.80:
			return "score-high"
		elif v >= 0.60:
			return "score-mid"
		return "score-low"
	except (ValueError, TypeError):
		return ""


def _star_rating(score_str: str | None, max_stars: int = 5) -> str:
	"""Render score 0–1 as filled/empty Unicode stars."""
	if score_str is None:
		return "—"
	try:
		v = float(score_str)
		filled = round(v * max_stars)
		return (
			f'<span class="stars">{"★" * filled}{"☆" * (max_stars - filled)}</span>'
			f' <small>({v:.0%})</small>'
		)
	except (ValueError, TypeError):
		return _he(score_str)


def _cents_display(cents: int | None, currency: str = "USD") -> str:
	if cents is None:
		return "—"
	return f"{currency} {int(cents) / 100:,.2f}"


# ---------------------------------------------------------------------------
# TradePromotionView
# ---------------------------------------------------------------------------

class TradePromotionView(BaseView):
	"""Trade Promotion CRUD + lifecycle.

	GET  /cg/promotions/                 — list
	GET  /cg/promotions/<id>             — detail
	POST /cg/promotions/                 — create
	POST /cg/promotions/<id>/approve     — DRAFT|SUBMITTED → APPROVED
	POST /cg/promotions/<id>/launch      — APPROVED → ACTIVE
	GET  /cg/promotions/<id>/roi         — ROI calculation
	"""

	route_base = "/cg/promotions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.consumer_goods.models import TradePromotion
		session = _get_session()
		q = sa.select(TradePromotion).order_by(sa.desc(TradePromotion.start_date))

		for param, col in (
			("tenant_id", TradePromotion.tenant_id),
			("status", TradePromotion.status),
			("promo_type", TradePromotion.promo_type),
			("target_retailer_id", TradePromotion.target_retailer_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)

		promos = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"promotions": [
				{
					"id": p.id,
					"promo_number": p.promo_number,
					"name": p.name,
					"promo_type": p.promo_type,
					"target_retailer_name": p.target_retailer_name,
					"start_date": p.start_date.isoformat() if p.start_date else None,
					"end_date": p.end_date.isoformat() if p.end_date else None,
					"budget_cents": p.budget_cents,
					"committed_cents": p.committed_cents,
					"paid_cents": p.paid_cents,
					"currency_code": p.currency_code,
					"status": p.status,
				}
				for p in promos
			]})

		rows = "".join(
			f"<tr>"
			f"<td><a href='/cg/promotions/{_he(p.id)}'>{_he(p.promo_number)}</a></td>"
			f"<td>{_he(p.name)}</td>"
			f"<td><span class='label label-default'>{_he(p.promo_type)}</span></td>"
			f"<td>{_he(p.target_retailer_name or '—')}</td>"
			f"<td>{_he(p.start_date)} → {_he(p.end_date)}</td>"
			f"<td class='text-right'>{_cents_display(p.budget_cents, p.currency_code)}</td>"
			f"<td>{_status_badge(p.status)}</td>"
			f"<td class='noprint'>"
			f"  <a href='/cg/promotions/{_he(p.id)}/roi' class='btn btn-xs btn-info'>ROI</a>"
			f"</td>"
			f"</tr>"
			for p in promos
		)
		body = (
			'<h3>Trade Promotions</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr>'
			'<th>Promo #</th><th>Name</th><th>Type</th><th>Retailer</th>'
			'<th>Period</th><th>Budget</th><th>Status</th><th class="noprint"></th>'
			'</tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">'
			f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Trade Promotions", body), 200)

	@expose("/<string:promo_id>")
	@has_access
	def detail(self, promo_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import TradePromotion
		session = _get_session()
		promo = session.get(TradePromotion, promo_id)
		if promo is None:
			abort(404)
		return jsonify({
			"id": promo.id,
			"tenant_id": promo.tenant_id,
			"promo_number": promo.promo_number,
			"name": promo.name,
			"promo_type": promo.promo_type,
			"target_retailer_id": promo.target_retailer_id,
			"target_retailer_name": promo.target_retailer_name,
			"channel": promo.channel,
			"start_date": promo.start_date.isoformat() if promo.start_date else None,
			"end_date": promo.end_date.isoformat() if promo.end_date else None,
			"budget_cents": promo.budget_cents,
			"committed_cents": promo.committed_cents,
			"paid_cents": promo.paid_cents,
			"currency_code": promo.currency_code,
			"mechanics": promo.mechanics,
			"products_in_scope": promo.products_in_scope,
			"status": promo.status,
			"approved_by": promo.approved_by,
			"approved_at": promo.approved_at.isoformat() if promo.approved_at else None,
			"notes": promo.notes,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.consumer_goods.services import (
			ConsumerGoodsService, ConsumerGoodsServiceError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			promo = ConsumerGoodsService().create_promotion(data, session)
			session.commit()
			return jsonify({
				"ok": True,
				"id": promo.id,
				"promo_number": promo.promo_number,
			}), 201
		except (ConsumerGoodsServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:promo_id>/approve", methods=["POST"])
	@has_access
	def approve(self, promo_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import TradePromotion
		from pgappforge.plugins.erp.industry.consumer_goods.events import PromotionApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		promo = session.get(TradePromotion, promo_id)
		if promo is None:
			abort(404)
		if promo.status not in ("DRAFT", "SUBMITTED"):
			return jsonify({"ok": False, "error": f"Cannot approve promo in status {promo.status!r}"}), 400
		data = request.get_json(silent=True) or {}
		promo.status = "APPROVED"
		promo.approved_by = data.get("approved_by")
		promo.approved_at = datetime.now(timezone.utc)
		promo.updated_at = datetime.now(timezone.utc)
		session.flush()
		emit_event(
			PromotionApprovedEvent(
				aggregate_id=promo.id,
				aggregate_type="TradePromotion",
				tenant_id=str(promo.tenant_id),
				promo_id=promo.id,
				promo_number=promo.promo_number,
				promo_type=promo.promo_type,
				budget_cents=promo.budget_cents,
				currency=promo.currency_code,
				retailer_id=str(promo.target_retailer_id or ""),
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "status": promo.status})

	@expose("/<string:promo_id>/launch", methods=["POST"])
	@has_access
	def launch(self, promo_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import TradePromotion
		session = _get_session()
		promo = session.get(TradePromotion, promo_id)
		if promo is None:
			abort(404)
		if promo.status != "APPROVED":
			return jsonify({"ok": False, "error": f"Cannot launch promo in status {promo.status!r}; must be APPROVED"}), 400
		promo.status = "ACTIVE"
		promo.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": promo.status})

	@expose("/<string:promo_id>/roi")
	@has_access
	def roi(self, promo_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.services import (
			ConsumerGoodsService, PromotionNotFoundError,
		)
		session = _get_session()
		try:
			result = ConsumerGoodsService().calculate_promo_roi(promo_id, session)
			return jsonify(result)
		except PromotionNotFoundError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 404


# ---------------------------------------------------------------------------
# RetailExecutionView
# ---------------------------------------------------------------------------

class RetailExecutionView(BaseView):
	"""Retail Execution / field visit CRUD.

	GET  /cg/retail/                      — list
	GET  /cg/retail/<id>                  — detail (includes photos, findings)
	POST /cg/retail/                      — create visit
	POST /cg/retail/<id>/submit           — DRAFT → SUBMITTED
	GET  /cg/retail/compliance            — shelf compliance check
	"""

	route_base = "/cg/retail"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.consumer_goods.models import RetailExecution
		session = _get_session()
		q = sa.select(RetailExecution).order_by(sa.desc(RetailExecution.visit_date))

		for param, col in (
			("tenant_id", RetailExecution.tenant_id),
			("store_id", RetailExecution.store_id),
			("auditor_id", RetailExecution.auditor_id),
			("status", RetailExecution.status),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)

		visits = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"retail_visits": [
				{
					"id": v.id,
					"store_id": v.store_id,
					"store_name": v.store_name,
					"store_type": v.store_type,
					"auditor_id": v.auditor_id,
					"visit_date": v.visit_date.isoformat() if v.visit_date else None,
					"overall_score": str(v.overall_score) if v.overall_score is not None else None,
					"status": v.status,
					"gps_location": v.gps_location,
					"findings_count": len(v.findings or []),
					"photos_count": len(v.photos or []),
				}
				for v in visits
			]})

		rows = "".join(
			f"<tr>"
			f"<td><a href='/cg/retail/{_he(v.id)}'>{_he(v.store_name or v.store_id)}</a></td>"
			f"<td>{_he(v.visit_date or '—')}</td>"
			f"<td>{_he(v.auditor_id or '—')}</td>"
			f"<td>{_star_rating(str(v.overall_score) if v.overall_score is not None else None)}</td>"
			f"<td>{_status_badge(v.status)}</td>"
			f"<td class='text-right'>{len(v.photos or [])}</td>"
			f"</tr>"
			for v in visits
		)
		body = (
			'<h3>Retail Execution Visits</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr>'
			'<th>Store</th><th>Visit Date</th><th>Auditor</th>'
			'<th>Compliance Score</th><th>Status</th><th>Photos</th>'
			'</tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">'
			f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Retail Execution", body), 200)

	@expose("/<string:visit_id>")
	@has_access
	def detail(self, visit_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import RetailExecution
		session = _get_session()
		v = session.get(RetailExecution, visit_id)
		if v is None:
			abort(404)
		return jsonify({
			"id": v.id,
			"tenant_id": v.tenant_id,
			"store_id": v.store_id,
			"store_name": v.store_name,
			"store_type": v.store_type,
			"auditor_id": v.auditor_id,
			"visit_date": v.visit_date.isoformat() if v.visit_date else None,
			"check_in_at": v.check_in_at.isoformat() if v.check_in_at else None,
			"check_out_at": v.check_out_at.isoformat() if v.check_out_at else None,
			"findings": v.findings,
			"photos": v.photos,
			"gps_location": v.gps_location,
			"overall_score": str(v.overall_score) if v.overall_score is not None else None,
			"status": v.status,
			"reviewer_id": v.reviewer_id,
			"reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None,
			"notes": v.notes,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from datetime import date as date_type
		from pgappforge.plugins.erp.industry.consumer_goods.services import (
			ConsumerGoodsService, ConsumerGoodsServiceError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		if not data.get("store_id"):
			return jsonify({"ok": False, "error": "store_id required"}), 400
		try:
			visit = ConsumerGoodsService().record_retail_visit(
				store_id=data["store_id"],
				findings=data.get("findings", []),
				photos=data.get("photos", []),
				session=session,
				auditor_id=data.get("auditor_id", ""),
				visit_date=date_type.fromisoformat(data["visit_date"]) if data.get("visit_date") else None,
				gps_location=data.get("gps_location"),
				check_in_at=datetime.fromisoformat(data["check_in_at"]) if data.get("check_in_at") else None,
				check_out_at=datetime.fromisoformat(data["check_out_at"]) if data.get("check_out_at") else None,
				store_name=data.get("store_name"),
				store_type=data.get("store_type"),
				tenant_id=data.get("tenant_id", ""),
			)
			session.commit()
			return jsonify({
				"ok": True,
				"id": visit.id,
				"overall_score": str(visit.overall_score) if visit.overall_score is not None else None,
			}), 201
		except (ConsumerGoodsServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:visit_id>/submit", methods=["POST"])
	@has_access
	def submit(self, visit_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import RetailExecution
		from pgappforge.plugins.erp.industry.consumer_goods.events import RetailVisitSubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		v = session.get(RetailExecution, visit_id)
		if v is None:
			abort(404)
		if v.status != "DRAFT":
			return jsonify({"ok": False, "error": f"Visit must be DRAFT to submit; got {v.status!r}"}), 400
		v.status = "SUBMITTED"
		v.updated_at = datetime.now(timezone.utc)
		session.flush()
		emit_event(
			RetailVisitSubmittedEvent(
				aggregate_id=v.id,
				aggregate_type="RetailExecution",
				tenant_id=str(v.tenant_id),
				visit_id=v.id,
				store_id=str(v.store_id),
				auditor_id=str(v.auditor_id),
				visit_date=v.visit_date.isoformat() if v.visit_date else "",
				overall_score=str(v.overall_score) if v.overall_score is not None else "0",
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "status": v.status})

	@expose("/compliance")
	@has_access
	def compliance(self):
		"""Shelf compliance check for a store/product pair."""
		from pgappforge.plugins.erp.industry.consumer_goods.services import ConsumerGoodsService
		session = _get_session()
		store_id = request.args.get("store_id")
		product_id = request.args.get("product_id")
		if not store_id or not product_id:
			return jsonify({"ok": False, "error": "store_id and product_id required"}), 400
		result = ConsumerGoodsService().check_shelf_compliance(
			store_id=store_id,
			product_id=product_id,
			session=session,
			store_type=request.args.get("store_type"),
			tenant_id=request.args.get("tenant_id", ""),
		)
		return jsonify(result)


# ---------------------------------------------------------------------------
# PlanoGramView
# ---------------------------------------------------------------------------

class PlanoGramView(BaseView):
	"""Planogram CRUD + compliance matrix.

	GET  /cg/planograms/                  — list
	GET  /cg/planograms/<id>              — detail
	POST /cg/planograms/                  — create
	PUT  /cg/planograms/<id>              — update
	GET  /cg/planograms/matrix            — compliance matrix for store type
	"""

	route_base = "/cg/planograms"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.consumer_goods.models import PlanoGram
		session = _get_session()
		q = sa.select(PlanoGram).order_by(PlanoGram.store_type, PlanoGram.product_sku)
		for param, col in (
			("tenant_id", PlanoGram.tenant_id),
			("product_id", PlanoGram.product_id),
			("store_type", PlanoGram.store_type),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)

		pgs = session.execute(q.limit(1000)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"planograms": [
				{
					"id": pg.id,
					"product_id": pg.product_id,
					"product_sku": pg.product_sku,
					"store_type": pg.store_type,
					"shelf_position": pg.shelf_position,
					"bay_number": pg.bay_number,
					"shelf_number": pg.shelf_number,
					"facing_count": pg.facing_count,
					"depth_count": pg.depth_count,
					"category": pg.category,
					"effective_from": pg.effective_from.isoformat() if pg.effective_from else None,
					"effective_to": pg.effective_to.isoformat() if pg.effective_to else None,
				}
				for pg in pgs
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(pg.product_sku or pg.product_id)}</td>"
			f"<td>{_he(pg.store_type)}</td>"
			f"<td>{_he(pg.shelf_position or '—')}</td>"
			f"<td class='text-right'>{pg.bay_number or '—'}</td>"
			f"<td class='text-right'>{pg.shelf_number or '—'}</td>"
			f"<td class='text-right'><b>{pg.facing_count}</b></td>"
			f"<td class='text-right'>{pg.depth_count}</td>"
			f"<td>{_he(pg.category or '—')}</td>"
			f"<td>"
			f"{_he(pg.effective_from or '—')} → {_he(pg.effective_to or '∞')}"
			f"</td>"
			f"</tr>"
			for pg in pgs
		)
		body = (
			'<h3>Planograms</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr>'
			'<th>SKU</th><th>Store Type</th><th>Position</th>'
			'<th>Bay</th><th>Shelf</th><th>Facings</th><th>Depth</th>'
			'<th>Category</th><th>Effective Period</th>'
			'</tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">'
			f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Planograms", body), 200)

	@expose("/<string:pg_id>")
	@has_access
	def detail(self, pg_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import PlanoGram
		session = _get_session()
		pg = session.get(PlanoGram, pg_id)
		if pg is None:
			abort(404)
		return jsonify({
			"id": pg.id,
			"tenant_id": pg.tenant_id,
			"product_id": pg.product_id,
			"product_sku": pg.product_sku,
			"store_type": pg.store_type,
			"shelf_position": pg.shelf_position,
			"bay_number": pg.bay_number,
			"shelf_number": pg.shelf_number,
			"position_from_left": pg.position_from_left,
			"facing_count": pg.facing_count,
			"depth_count": pg.depth_count,
			"category": pg.category,
			"effective_from": pg.effective_from.isoformat() if pg.effective_from else None,
			"effective_to": pg.effective_to.isoformat() if pg.effective_to else None,
			"image_url": pg.image_url,
			"notes": pg.notes,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from datetime import date as date_type
		from pgappforge.plugins.erp.industry.consumer_goods.models import PlanoGram
		from pgappforge.plugins.erp.industry.consumer_goods.events import PlanoGramUpdatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "product_id", "store_type", "facing_count")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		pg = PlanoGram(
			tenant_id=data["tenant_id"],
			product_id=data["product_id"],
			product_sku=data.get("product_sku"),
			store_type=data["store_type"],
			shelf_position=data.get("shelf_position"),
			bay_number=data.get("bay_number"),
			shelf_number=data.get("shelf_number"),
			position_from_left=data.get("position_from_left"),
			facing_count=int(data["facing_count"]),
			depth_count=int(data.get("depth_count", 1)),
			category=data.get("category"),
			effective_from=date_type.fromisoformat(data["effective_from"]) if data.get("effective_from") else None,
			effective_to=date_type.fromisoformat(data["effective_to"]) if data.get("effective_to") else None,
			image_url=data.get("image_url"),
			notes=data.get("notes"),
		)
		session.add(pg)
		session.flush()
		emit_event(
			PlanoGramUpdatedEvent(
				aggregate_id=pg.id,
				aggregate_type="PlanoGram",
				tenant_id=str(data["tenant_id"]),
				planogram_id=pg.id,
				product_id=str(data["product_id"]),
				store_type=data["store_type"],
				facing_count=int(data["facing_count"]),
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": pg.id}), 201

	@expose("/<string:pg_id>", methods=["PUT"])
	@has_access
	def update(self, pg_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import PlanoGram
		session = _get_session()
		pg = session.get(PlanoGram, pg_id)
		if pg is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("shelf_position", "bay_number", "shelf_number", "position_from_left",
		          "facing_count", "depth_count", "category", "image_url", "notes"):
			if f in data:
				setattr(pg, f, data[f])
		pg.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/matrix")
	@has_access
	def matrix(self):
		"""Planogram compliance matrix for a store type."""
		from pgappforge.plugins.erp.industry.consumer_goods.models import PlanoGram
		session = _get_session()
		store_type = request.args.get("store_type", "SUPERMARKET")
		tenant_id = request.args.get("tenant_id", "")

		q = sa.select(PlanoGram).where(PlanoGram.store_type == store_type)
		if tenant_id:
			q = q.where(PlanoGram.tenant_id == tenant_id)
		pgs = session.execute(q.order_by(PlanoGram.bay_number, PlanoGram.shelf_number).limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({
				"store_type": store_type,
				"planograms": [
					{
						"product_sku": pg.product_sku,
						"bay": pg.bay_number,
						"shelf": pg.shelf_number,
						"position": pg.position_from_left,
						"facings": pg.facing_count,
						"shelf_position": pg.shelf_position,
					}
					for pg in pgs
				],
			})

		# Build grid: rows = shelf, cols = bay
		cells = ""
		for pg in pgs:
			cells += (
				f"<tr>"
				f"<td>{_he(pg.product_sku or pg.product_id)}</td>"
				f"<td>{_he(pg.bay_number or '—')}</td>"
				f"<td>{_he(pg.shelf_number or '—')}</td>"
				f"<td>{_he(pg.position_from_left or '—')}</td>"
				f"<td><b>{pg.facing_count}</b></td>"
				f"<td>{_he(pg.shelf_position or '—')}</td>"
				f"</tr>"
			)
		body = (
			f'<h3>Planogram Matrix — {_he(store_type)}</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>SKU</th><th>Bay</th><th>Shelf</th><th>Position</th><th>Facings</th><th>Level</th></tr></thead>'
			f'<tbody>{cells or "<tr><td colspan=6 class=text-center><em>No planograms found</em></td></tr>"}</tbody></table>'
		)
		return make_response(_page_html(f"Planogram Matrix — {store_type}", body), 200)


# ---------------------------------------------------------------------------
# PromotionClaimView
# ---------------------------------------------------------------------------

class PromotionClaimView(BaseView):
	"""Promotion Claim CRUD + review lifecycle.

	GET  /cg/claims/                      — list
	GET  /cg/claims/<id>                  — detail
	POST /cg/claims/                      — submit claim (via service)
	POST /cg/claims/<id>/approve          — SUBMITTED|UNDER_REVIEW → APPROVED
	POST /cg/claims/<id>/pay              — APPROVED → PAID
	POST /cg/claims/<id>/reject           — → REJECTED
	"""

	route_base = "/cg/claims"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.consumer_goods.models import PromotionClaim
		session = _get_session()
		q = sa.select(PromotionClaim).order_by(sa.desc(PromotionClaim.claimed_at))

		for param, col in (
			("tenant_id", PromotionClaim.tenant_id),
			("promo_id", PromotionClaim.promo_id),
			("status", PromotionClaim.status),
			("retailer_id", PromotionClaim.retailer_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)

		claims = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"claims": [
				{
					"id": c.id,
					"claim_number": c.claim_number,
					"promo_id": c.promo_id,
					"retailer_id": c.retailer_id,
					"claimed_at": c.claimed_at.isoformat() if c.claimed_at else None,
					"actual_spend_cents": c.actual_spend_cents,
					"approved_cents": c.approved_cents,
					"paid_cents": c.paid_cents,
					"currency_code": c.currency_code,
					"status": c.status,
				}
				for c in claims
			]})

		rows = "".join(
			f"<tr>"
			f"<td><a href='/cg/claims/{_he(c.id)}'>{_he(c.claim_number or c.id[:8])}</a></td>"
			f"<td>{_he(c.promo_id)}</td>"
			f"<td>{_he(c.claimed_at.strftime('%Y-%m-%d') if c.claimed_at else '—')}</td>"
			f"<td class='text-right'>{_cents_display(c.actual_spend_cents, c.currency_code)}</td>"
			f"<td class='text-right'>{_cents_display(c.approved_cents, c.currency_code)}</td>"
			f"<td class='text-right'>{_cents_display(c.paid_cents, c.currency_code)}</td>"
			f"<td>{_status_badge(c.status)}</td>"
			f"</tr>"
			for c in claims
		)
		body = (
			'<h3>Promotion Claims</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr>'
			'<th>Claim #</th><th>Promo</th><th>Submitted</th>'
			'<th>Claimed</th><th>Approved</th><th>Paid</th><th>Status</th>'
			'</tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">'
			f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Promotion Claims", body), 200)

	@expose("/<string:claim_id>")
	@has_access
	def detail(self, claim_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import PromotionClaim
		session = _get_session()
		c = session.get(PromotionClaim, claim_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"tenant_id": c.tenant_id,
			"promo_id": c.promo_id,
			"claim_number": c.claim_number,
			"retailer_id": c.retailer_id,
			"claimed_at": c.claimed_at.isoformat() if c.claimed_at else None,
			"claim_period_start": c.claim_period_start.isoformat() if c.claim_period_start else None,
			"claim_period_end": c.claim_period_end.isoformat() if c.claim_period_end else None,
			"actual_spend_cents": c.actual_spend_cents,
			"approved_cents": c.approved_cents,
			"paid_cents": c.paid_cents,
			"currency_code": c.currency_code,
			"supporting_docs": c.supporting_docs,
			"status": c.status,
			"reviewed_by": c.reviewed_by,
			"reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
			"rejection_reason": c.rejection_reason,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.consumer_goods.services import (
			ConsumerGoodsService, ConsumerGoodsServiceError, BudgetExceededError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		promo_id = data.get("promo_id")
		if not promo_id:
			return jsonify({"ok": False, "error": "promo_id required"}), 400
		try:
			claim = ConsumerGoodsService().submit_claim(
				promo_id=promo_id,
				claim_details=data,
				session=session,
			)
			session.commit()
			return jsonify({
				"ok": True,
				"id": claim.id,
				"claim_number": claim.claim_number,
				"status": claim.status,
			}), 201
		except BudgetExceededError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422
		except (ConsumerGoodsServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:claim_id>/approve", methods=["POST"])
	@has_access
	def approve(self, claim_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import PromotionClaim
		session = _get_session()
		c = session.get(PromotionClaim, claim_id)
		if c is None:
			abort(404)
		if c.status not in ("SUBMITTED", "UNDER_REVIEW"):
			return jsonify({"ok": False, "error": f"Cannot approve claim in status {c.status!r}"}), 400
		data = request.get_json(silent=True) or {}
		approved_cents = data.get("approved_cents")
		if approved_cents is None:
			approved_cents = c.actual_spend_cents
		c.approved_cents = int(approved_cents)
		assert isinstance(c.approved_cents, int)
		c.status = "APPROVED"
		c.reviewed_by = data.get("reviewed_by")
		c.reviewed_at = datetime.now(timezone.utc)
		c.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": c.status, "approved_cents": c.approved_cents})

	@expose("/<string:claim_id>/pay", methods=["POST"])
	@has_access
	def pay(self, claim_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import PromotionClaim, TradePromotion
		from pgappforge.plugins.erp.industry.consumer_goods.events import PromotionClaimPaidEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		c = session.get(PromotionClaim, claim_id)
		if c is None:
			abort(404)
		if c.status != "APPROVED":
			return jsonify({"ok": False, "error": f"Claim must be APPROVED to pay; got {c.status!r}"}), 400
		data = request.get_json(silent=True) or {}
		pay_cents = int(data.get("pay_cents", c.approved_cents or 0))
		assert isinstance(pay_cents, int)

		# Immutable ledger: add-only
		c.paid_cents = int(c.paid_cents) + pay_cents
		c.status = "PAID"
		c.updated_at = datetime.now(timezone.utc)

		# Update promotion paid_cents (add-only)
		promo = session.get(TradePromotion, c.promo_id)
		if promo:
			promo.paid_cents = int(promo.paid_cents) + pay_cents
			promo.updated_at = datetime.now(timezone.utc)

		session.flush()
		emit_event(
			PromotionClaimPaidEvent(
				aggregate_id=c.id,
				aggregate_type="PromotionClaim",
				tenant_id=str(c.tenant_id),
				claim_id=c.id,
				promo_id=c.promo_id,
				paid_cents=pay_cents,
				currency=c.currency_code,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "status": c.status, "paid_cents": c.paid_cents})

	@expose("/<string:claim_id>/reject", methods=["POST"])
	@has_access
	def reject(self, claim_id: str):
		from pgappforge.plugins.erp.industry.consumer_goods.models import PromotionClaim
		session = _get_session()
		c = session.get(PromotionClaim, claim_id)
		if c is None:
			abort(404)
		if c.status in ("PAID",):
			return jsonify({"ok": False, "error": "Cannot reject a PAID claim"}), 400
		data = request.get_json(silent=True) or {}
		c.status = "REJECTED"
		c.rejection_reason = data.get("reason", "")
		c.reviewed_by = data.get("reviewed_by")
		c.reviewed_at = datetime.now(timezone.utc)
		c.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": c.status})


__all__ = [
	"TradePromotionView",
	"RetailExecutionView",
	"PlanoGramView",
	"PromotionClaimView",
]
