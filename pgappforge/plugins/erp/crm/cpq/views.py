"""
pgappforge/plugins/erp/crm/cpq/views.py

Flask views for the Configure-Price-Quote (CPQ) plugin.

Route summary
-------------
ProductCatalogView      /cpq/catalogs/
PricingRuleView         /cpq/pricing-rules/
ProductBundleView       /cpq/bundles/
QuoteView               /cpq/quotes/
  ├─ POST /cpq/quotes/<id>/lines          — add line
  ├─ POST /cpq/quotes/<id>/send           — DRAFT → SENT
  ├─ POST /cpq/quotes/<id>/accept         — customer accepts
  ├─ POST /cpq/quotes/<id>/reject         — customer rejects
  ├─ POST /cpq/quotes/<id>/submit-approval — submit for approval
  ├─ POST /cpq/quotes/<id>/approve        — approver approves
  └─ POST /cpq/quotes/<id>/reject-approval — approver rejects
CPQReportView           /cpq/reports/
  ├─ /quote-summary     — Quote Status Summary (HTML)
  ├─ /win-rate          — Win Rate by Month (HTML)
  └─ /discount-analysis — Discount Analysis (HTML)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

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
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _cents(cents: int | None, currency: str = "USD") -> str:
	if cents is None:
		return "—"
	major = cents // 100
	minor = abs(cents) % 100
	sign = "-" if cents < 0 else ""
	return f"{sign}{major:,}.{minor:02d} {currency}"


# ---------------------------------------------------------------------------
# ProductCatalogView
# ---------------------------------------------------------------------------

class ProductCatalogView(BaseView):
	"""Product Catalog CRUD.

	GET  /cpq/catalogs/          — list (JSON)
	GET  /cpq/catalogs/<id>      — detail (JSON)
	POST /cpq/catalogs/          — create (JSON)
	PUT  /cpq/catalogs/<id>      — update (JSON)
	"""

	route_base = "/cpq/catalogs"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import ProductCatalog
		tenant_id = request.args.get("tenant_id")
		q = (
			sa.select(ProductCatalog)
			.order_by(sa.desc(ProductCatalog.effective_from))
			.limit(200)
		)
		if tenant_id:
			q = q.where(ProductCatalog.tenant_id == tenant_id)
		catalogs = session.execute(q).scalars().all()
		return jsonify({
			"catalogs": [
				{
					"id": c.id,
					"name": c.name,
					"effective_from": c.effective_from.isoformat() if c.effective_from else None,
					"effective_to": c.effective_to.isoformat() if c.effective_to else None,
					"currency_code": c.currency_code,
					"is_active": c.is_active,
				}
				for c in catalogs
			]
		})

	@expose("/<string:catalog_id>")
	@has_access
	def detail(self, catalog_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import ProductCatalog
		c = session.get(ProductCatalog, catalog_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"tenant_id": c.tenant_id,
			"name": c.name,
			"effective_from": c.effective_from.isoformat() if c.effective_from else None,
			"effective_to": c.effective_to.isoformat() if c.effective_to else None,
			"currency_code": c.currency_code,
			"is_active": c.is_active,
			"description": c.description,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import ProductCatalog
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "name", "effective_from") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400
		c = ProductCatalog(
			tenant_id=data["tenant_id"],
			name=data["name"],
			effective_from=date.fromisoformat(data["effective_from"]),
			effective_to=date.fromisoformat(data["effective_to"]) if data.get("effective_to") else None,
			currency_code=(data.get("currency_code") or "USD").upper(),
			is_active=bool(data.get("is_active", True)),
			description=data.get("description"),
		)
		session.add(c)
		session.commit()
		return jsonify({"ok": True, "id": c.id}), 201

	@expose("/<string:catalog_id>", methods=["PUT"])
	@has_access
	def update(self, catalog_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import ProductCatalog
		c = session.get(ProductCatalog, catalog_id)
		if c is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "is_active", "description"):
			if f in data:
				setattr(c, f, data[f])
		if "effective_to" in data:
			c.effective_to = date.fromisoformat(data["effective_to"]) if data["effective_to"] else None
		c.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# PricingRuleView
# ---------------------------------------------------------------------------

class PricingRuleView(BaseView):
	"""Pricing Rule CRUD.

	GET  /cpq/pricing-rules/                  — list (JSON, filter by catalog_id)
	POST /cpq/pricing-rules/                  — create (JSON)
	PUT  /cpq/pricing-rules/<id>              — update (JSON)
	DELETE /cpq/pricing-rules/<id>            — deactivate (soft delete)
	"""

	route_base = "/cpq/pricing-rules"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import PricingRule
		catalog_id = request.args.get("catalog_id")
		q = sa.select(PricingRule).order_by(PricingRule.priority).limit(500)
		if catalog_id:
			q = q.where(PricingRule.catalog_id == catalog_id)
		rules = session.execute(q).scalars().all()
		return jsonify({
			"pricing_rules": [
				{
					"id": r.id,
					"catalog_id": r.catalog_id,
					"rule_name": r.rule_name,
					"rule_type": r.rule_type,
					"discount_pct": str(r.discount_pct) if r.discount_pct is not None else None,
					"fixed_price_cents": r.fixed_price_cents,
					"priority": r.priority,
					"is_active": r.is_active,
					"conditions": r.conditions,
				}
				for r in rules
			]
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import PricingRule
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "catalog_id", "rule_name", "rule_type") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400
		r = PricingRule(
			tenant_id=data["tenant_id"],
			catalog_id=data["catalog_id"],
			rule_name=data["rule_name"],
			rule_type=data["rule_type"].upper(),
			conditions=data.get("conditions") or [],
			discount_pct=data.get("discount_pct"),
			fixed_price_cents=data.get("fixed_price_cents"),
			priority=int(data.get("priority") or 100),
			is_active=bool(data.get("is_active", True)),
		)
		session.add(r)
		session.commit()
		return jsonify({"ok": True, "id": r.id}), 201

	@expose("/<string:rule_id>", methods=["PUT"])
	@has_access
	def update(self, rule_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import PricingRule
		r = session.get(PricingRule, rule_id)
		if r is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("rule_name", "conditions", "discount_pct", "fixed_price_cents", "priority", "is_active"):
			if f in data:
				setattr(r, f, data[f])
		r.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:rule_id>", methods=["DELETE"])
	@has_access
	def deactivate(self, rule_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import PricingRule
		r = session.get(PricingRule, rule_id)
		if r is None:
			abort(404)
		r.is_active = False
		r.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "is_active": False})


# ---------------------------------------------------------------------------
# ProductBundleView
# ---------------------------------------------------------------------------

class ProductBundleView(BaseView):
	"""Product Bundle CRUD.

	GET  /cpq/bundles/             — list (JSON)
	GET  /cpq/bundles/<id>         — detail with lines (JSON)
	POST /cpq/bundles/             — create bundle (JSON)
	POST /cpq/bundles/<id>/lines   — add bundle line (JSON)
	PUT  /cpq/bundles/<id>         — update bundle (JSON)
	"""

	route_base = "/cpq/bundles"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import ProductBundle
		tenant_id = request.args.get("tenant_id")
		q = (
			sa.select(ProductBundle)
			.where(ProductBundle.is_active.is_(True))
			.order_by(ProductBundle.name)
			.limit(200)
		)
		if tenant_id:
			q = q.where(ProductBundle.tenant_id == tenant_id)
		bundles = session.execute(q).scalars().all()
		return jsonify({
			"bundles": [
				{
					"id": b.id,
					"bundle_code": b.bundle_code,
					"name": b.name,
					"bundle_type": b.bundle_type,
					"base_price_cents": b.base_price_cents,
					"discount_pct": str(b.discount_pct),
					"is_active": b.is_active,
				}
				for b in bundles
			]
		})

	@expose("/<string:bundle_id>")
	@has_access
	def detail(self, bundle_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import ProductBundle, BundleLine
		b = session.get(ProductBundle, bundle_id)
		if b is None:
			abort(404)
		lines = session.execute(
			sa.select(BundleLine).where(BundleLine.bundle_id == bundle_id)
		).scalars().all()
		return jsonify({
			"id": b.id,
			"tenant_id": b.tenant_id,
			"bundle_code": b.bundle_code,
			"name": b.name,
			"bundle_type": b.bundle_type,
			"base_price_cents": b.base_price_cents,
			"discount_pct": str(b.discount_pct),
			"description": b.description,
			"is_active": b.is_active,
			"lines": [
				{
					"id": l.id,
					"product_id": l.product_id,
					"quantity": str(l.quantity),
					"is_required": l.is_required,
					"price_override_cents": l.price_override_cents,
				}
				for l in lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import ProductBundle
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "bundle_code", "name") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400
		b = ProductBundle(
			tenant_id=data["tenant_id"],
			bundle_code=data["bundle_code"],
			name=data["name"],
			bundle_type=(data.get("bundle_type") or "FIXED").upper(),
			base_price_cents=data.get("base_price_cents"),
			discount_pct=Decimal(str(data.get("discount_pct") or 0)),
			description=data.get("description"),
			is_active=True,
		)
		session.add(b)
		session.commit()
		return jsonify({"ok": True, "id": b.id}), 201

	@expose("/<string:bundle_id>/lines", methods=["POST"])
	@has_access
	def add_line(self, bundle_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import ProductBundle, BundleLine
		b = session.get(ProductBundle, bundle_id)
		if b is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		if not data.get("product_id"):
			return jsonify({"ok": False, "error": "product_id required"}), 400
		line = BundleLine(
			tenant_id=b.tenant_id,
			bundle_id=bundle_id,
			product_id=data["product_id"],
			quantity=Decimal(str(data.get("quantity") or 1)),
			is_required=bool(data.get("is_required", True)),
			price_override_cents=data.get("price_override_cents"),
		)
		session.add(line)
		session.commit()
		return jsonify({"ok": True, "id": line.id}), 201


# ---------------------------------------------------------------------------
# QuoteView
# ---------------------------------------------------------------------------

class QuoteView(BaseView):
	"""CPQ Quote CRUD + lifecycle actions.

	GET  /cpq/quotes/                         — list (HTML)
	GET  /cpq/quotes/<id>                     — detail with lines (JSON)
	POST /cpq/quotes/                         — create quote (JSON)
	POST /cpq/quotes/<id>/lines               — add line (JSON)
	POST /cpq/quotes/<id>/send                — DRAFT → SENT
	POST /cpq/quotes/<id>/accept              — customer accepts
	POST /cpq/quotes/<id>/reject              — customer rejects
	POST /cpq/quotes/<id>/submit-approval     — submit for approval
	POST /cpq/quotes/<id>/approve             — approver approves
	POST /cpq/quotes/<id>/reject-approval     — approver rejects
	POST /cpq/quotes/expire                   — expire stale quotes (batch)
	POST /cpq/quotes/configure-product        — validate product configuration
	"""

	route_base = "/cpq/quotes"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import Quote
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		q = (
			sa.select(Quote)
			.order_by(sa.desc(Quote.created_at))
			.limit(500)
		)
		if tenant_id:
			q = q.where(Quote.tenant_id == tenant_id)
		if status:
			q = q.where(Quote.status == status.upper())
		quotes = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(q.quote_number)}</td>"
			f"<td>{_he(q.status)}</td>"
			f"<td>{_he(q.approval_status or '—')}</td>"
			f"<td class='text-right'>{_cents(q.total_cents, q.currency_code)}</td>"
			f"<td>{_he(q.valid_until or '—')}</td>"
			f"<td><a href='/cpq/quotes/{_he(q.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for q in quotes
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>CPQ Quotes</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>CPQ Quotes <small>({len(quotes)})</small></h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>Quote #</th><th>Status</th><th>Approval</th><th>Total</th>
<th>Valid Until</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:quote_id>")
	@has_access
	def detail(self, quote_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import Quote, QuoteLine
		q = session.get(Quote, quote_id)
		if q is None:
			abort(404)
		lines = session.execute(
			sa.select(QuoteLine)
			.where(QuoteLine.quote_id == quote_id)
			.order_by(QuoteLine.line_number)
		).scalars().all()
		return jsonify({
			"id": q.id,
			"quote_number": q.quote_number,
			"opportunity_id": q.opportunity_id,
			"account_id": q.account_id,
			"status": q.status,
			"approval_status": q.approval_status,
			"valid_until": q.valid_until.isoformat() if q.valid_until else None,
			"currency_code": q.currency_code,
			"subtotal_cents": q.subtotal_cents,
			"discount_cents": q.discount_cents,
			"tax_cents": q.tax_cents,
			"total_cents": q.total_cents,
			"owner_id": q.owner_id,
			"approved_by": q.approved_by,
			"approved_at": q.approved_at.isoformat() if q.approved_at else None,
			"approval_notes": q.approval_notes,
			"notes": q.notes,
			"lines": [
				{
					"id": ln.id,
					"line_number": ln.line_number,
					"product_id": ln.product_id,
					"description": ln.description,
					"quantity": str(ln.quantity),
					"list_price_cents": ln.list_price_cents,
					"discount_pct": str(ln.discount_pct),
					"net_price_cents": ln.net_price_cents,
					"cost_cents": ln.cost_cents,
					"margin_pct": str(ln.margin_pct) if ln.margin_pct is not None else None,
					"configuration": ln.configuration,
				}
				for ln in lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Generate a new CPQ quote.

		JSON body::
		    {
		        "opportunity_id": "<uuid>",   # optional
		        "account_id": "<uuid>",       # required
		        "tenant_id": "<uuid>",        # required
		        "currency_code": "USD",
		        "owner_id": "<uuid>",
		        "valid_days": 30,
		        "line_items": [
		            {
		                "description": "Product A",
		                "quantity": 2,
		                "list_price_cents": 10000,
		                "product_id": "<uuid>",
		                "discount_pct": 5,
		                "cost_cents": 4000,
		                "configuration": {}
		            }
		        ]
		    }
		"""
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService, CPQServiceError
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "account_id") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400
		svc = CPQService()
		try:
			quote = svc.generate_quote(
				opportunity_id=data.get("opportunity_id"),
				account_id=data["account_id"],
				line_items=data.get("line_items") or [],
				session=session,
				tenant_id=data["tenant_id"],
				currency_code=(data.get("currency_code") or "USD").upper(),
				owner_id=data.get("owner_id"),
				quote_number=data.get("quote_number"),
				valid_days=int(data.get("valid_days") or 30),
			)
			session.commit()
			return jsonify({"ok": True, "id": quote.id, "quote_number": quote.quote_number,
			                "total_cents": quote.total_cents}), 201
		except CPQServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:quote_id>/lines", methods=["POST"])
	@has_access
	def add_line(self, quote_id: str):
		"""Add a single line to a DRAFT quote."""
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import Quote, QuoteLine
		from pgappforge.plugins.erp.crm.cpq.services import CPQService
		q = session.get(Quote, quote_id)
		if q is None:
			abort(404)
		if q.status != "DRAFT":
			return jsonify({"ok": False, "error": "Lines can only be added to DRAFT quotes"}), 400
		data = request.get_json(silent=True) or {}
		if not data.get("description"):
			return jsonify({"ok": False, "error": "description required"}), 400

		svc = CPQService()
		quantity = Decimal(str(data.get("quantity") or 1))
		list_price_cents = int(data.get("list_price_cents") or 0)

		# Resolve catalog
		catalog_id = svc._resolve_catalog_id(q.tenant_id, q.currency_code, session)
		priced = svc.price_line(
			product_id=data.get("product_id"),
			quantity=quantity,
			list_price_cents=list_price_cents,
			override_discount_pct=data.get("discount_pct"),
			catalog_id=catalog_id,
			session=session,
		)

		# Next line number
		max_line = session.execute(
			sa.select(sa.func.coalesce(sa.func.max(QuoteLine.line_number), 0))
			.where(QuoteLine.quote_id == quote_id)
		).scalar() or 0

		line = QuoteLine(
			tenant_id=q.tenant_id,
			quote_id=quote_id,
			line_number=max_line + 1,
			product_id=data.get("product_id"),
			description=data["description"],
			quantity=quantity,
			list_price_cents=list_price_cents,
			discount_pct=priced["discount_pct"],
			net_price_cents=priced["net_price_cents"],
			cost_cents=data.get("cost_cents"),
			configuration=data.get("configuration") or {},
		)
		session.add(line)

		# Recompute quote totals
		q.subtotal_cents += int((quantity * list_price_cents).to_integral_value())
		q.discount_cents += int((quantity * list_price_cents).to_integral_value()) - priced["net_price_cents"]
		q.total_cents = q.subtotal_cents - q.discount_cents + q.tax_cents
		q.updated_at = datetime.now(timezone.utc)

		session.commit()
		return jsonify({
			"ok": True, "id": line.id, "line_number": line.line_number,
			"net_price_cents": line.net_price_cents,
		}), 201

	@expose("/<string:quote_id>/send", methods=["POST"])
	@has_access
	def send(self, quote_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService, CPQServiceError, ApprovalRequiredError
		svc = CPQService()
		try:
			q = svc.send_quote(quote_id, session)
			session.commit()
			return jsonify({"ok": True, "status": q.status})
		except ApprovalRequiredError as exc:
			return jsonify({"ok": False, "error": str(exc), "approval_required": True}), 422
		except CPQServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:quote_id>/accept", methods=["POST"])
	@has_access
	def accept(self, quote_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService, CPQServiceError
		svc = CPQService()
		try:
			q = svc.accept_quote(quote_id, session)
			session.commit()
			return jsonify({"ok": True, "status": q.status})
		except CPQServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:quote_id>/reject", methods=["POST"])
	@has_access
	def reject(self, quote_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService, CPQServiceError
		data = request.get_json(silent=True) or {}
		svc = CPQService()
		try:
			q = svc.reject_quote(quote_id, data.get("reason", ""), session)
			session.commit()
			return jsonify({"ok": True, "status": q.status})
		except CPQServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:quote_id>/submit-approval", methods=["POST"])
	@has_access
	def submit_approval(self, quote_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService, CPQServiceError
		svc = CPQService()
		try:
			q = svc.submit_for_approval(quote_id, session)
			session.commit()
			return jsonify({"ok": True, "approval_status": q.approval_status})
		except CPQServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:quote_id>/approve", methods=["POST"])
	@has_access
	def approve(self, quote_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService, CPQServiceError
		data = request.get_json(silent=True) or {}
		approver_id = data.get("approver_id", "")
		svc = CPQService()
		try:
			q = svc.approve_quote(quote_id, approver_id, data.get("notes", ""), session)
			session.commit()
			return jsonify({"ok": True, "approval_status": q.approval_status})
		except CPQServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:quote_id>/reject-approval", methods=["POST"])
	@has_access
	def reject_approval(self, quote_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService, CPQServiceError
		data = request.get_json(silent=True) or {}
		svc = CPQService()
		try:
			q = svc.reject_approval(
				quote_id, data.get("approver_id", ""), data.get("reason", ""), session
			)
			session.commit()
			return jsonify({"ok": True, "approval_status": q.approval_status})
		except CPQServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/expire", methods=["POST"])
	@has_access
	def expire(self):
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService
		data = request.get_json(silent=True) or {}
		tenant_id = data.get("tenant_id")
		if not tenant_id:
			return jsonify({"ok": False, "error": "tenant_id required"}), 400
		as_of_date_str = data.get("as_of_date")
		as_of_date = date.fromisoformat(as_of_date_str) if as_of_date_str else date.today()
		svc = CPQService()
		n = svc.expire_quotes(tenant_id, as_of_date, session)
		session.commit()
		return jsonify({"ok": True, "expired": n})

	@expose("/configure-product", methods=["POST"])
	@has_access
	def configure_product(self):
		"""Validate a product configuration without creating a quote."""
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.services import CPQService, CPQServiceError
		data = request.get_json(silent=True) or {}
		product_id = data.get("product_id")
		config = data.get("configuration") or {}
		if not product_id:
			return jsonify({"ok": False, "error": "product_id required"}), 400
		svc = CPQService()
		try:
			validated = svc.configure_product(product_id, config, session)
			return jsonify({"ok": True, "configuration": validated})
		except CPQServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# CPQReportView — 3 standard reports
# ---------------------------------------------------------------------------

class CPQReportView(BaseView):
	"""Standard CPQ reports.

	GET /cpq/reports/quote-summary       — Quote Status Summary (HTML)
	GET /cpq/reports/win-rate            — Win Rate by Month (HTML)
	GET /cpq/reports/discount-analysis   — Discount Analysis (HTML)
	"""

	route_base = "/cpq/reports"
	default_view = "quote_summary"

	# ------------------------------------------------------------------
	# Report 1: Quote Status Summary
	# ------------------------------------------------------------------

	@expose("/quote-summary")
	@has_access
	def quote_summary(self):
		"""Quote Status Summary — count and value by status."""
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import Quote

		tenant_id = request.args.get("tenant_id")
		q = (
			sa.select(
				Quote.status,
				sa.func.count(Quote.id).label("count"),
				sa.func.coalesce(sa.func.sum(Quote.total_cents), 0).label("total_cents"),
			)
			.group_by(Quote.status)
			.order_by(Quote.status)
		)
		if tenant_id:
			q = q.where(Quote.tenant_id == tenant_id)

		rows_data = session.execute(q).all()
		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(r.status)}</td>"
			f"<td class='text-right'>{r.count}</td>"
			f"<td class='text-right'>{_cents(int(r.total_cents))}</td>"
			f"</tr>"
			for r in rows_data
		)
		grand_total = sum(int(r.total_cents) for r in rows_data)
		grand_count = sum(r.count for r in rows_data)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Quote Summary</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} @media print{{.noprint{{display:none}}}}</style>
</head><body>
<div class="noprint" style="margin-bottom:12px">
  <h3>Quote Status Summary</h3>
  <button onclick="window.print()" class="btn btn-xs btn-primary">Print</button>
</div>
<table class="table table-bordered table-condensed">
<thead><tr><th>Status</th><th class="text-right">Count</th><th class="text-right">Total Value</th></tr></thead>
<tbody>{table_rows}</tbody>
<tfoot><tr class="active">
  <td><strong>TOTAL</strong></td>
  <td class="text-right"><strong>{grand_count}</strong></td>
  <td class="text-right"><strong>{_cents(grand_total)}</strong></td>
</tr></tfoot>
</table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	# ------------------------------------------------------------------
	# Report 2: Win Rate by Month
	# ------------------------------------------------------------------

	@expose("/win-rate")
	@has_access
	def win_rate(self):
		"""Win Rate by Month — ACCEPTED vs REJECTED/EXPIRED quotes."""
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import Quote

		tenant_id = request.args.get("tenant_id")

		# Monthly aggregation using date_trunc
		q = (
			sa.select(
				sa.func.date_trunc("month", Quote.created_at).label("month"),
				Quote.status,
				sa.func.count(Quote.id).label("count"),
				sa.func.coalesce(sa.func.sum(Quote.total_cents), 0).label("total_cents"),
			)
			.where(Quote.status.in_(["ACCEPTED", "REJECTED", "EXPIRED"]))
			.group_by(sa.func.date_trunc("month", Quote.created_at), Quote.status)
			.order_by(sa.func.date_trunc("month", Quote.created_at).desc())
			.limit(120)  # 10 years
		)
		if tenant_id:
			q = q.where(Quote.tenant_id == tenant_id)

		rows_data = session.execute(q).all()

		# Pivot: month -> {ACCEPTED: count, REJECTED+EXPIRED: count}
		months: dict[str, dict] = {}
		for r in rows_data:
			month_str = r.month.strftime("%Y-%m") if r.month else "?"
			if month_str not in months:
				months[month_str] = {"accepted": 0, "lost": 0, "accepted_value": 0}
			if r.status == "ACCEPTED":
				months[month_str]["accepted"] += r.count
				months[month_str]["accepted_value"] += int(r.total_cents)
			else:
				months[month_str]["lost"] += r.count

		def _win_rate(d: dict) -> str:
			total = d["accepted"] + d["lost"]
			return f"{d['accepted'] / total * 100:.1f}%" if total > 0 else "—"

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(month)}</td>"
			f"<td class='text-right'>{d['accepted']}</td>"
			f"<td class='text-right'>{d['lost']}</td>"
			f"<td class='text-right'>{_win_rate(d)}</td>"
			f"<td class='text-right'>{_cents(d['accepted_value'])}</td>"
			f"</tr>"
			for month, d in sorted(months.items(), reverse=True)
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Quote Win Rate</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style>
</head><body>
<h3>Quote Win Rate by Month</h3>
<table class="table table-bordered table-condensed table-hover">
<thead><tr><th>Month</th><th class="text-right">Won</th><th class="text-right">Lost/Expired</th>
<th class="text-right">Win Rate</th><th class="text-right">Won Value</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	# ------------------------------------------------------------------
	# Report 3: Discount Analysis
	# ------------------------------------------------------------------

	@expose("/discount-analysis")
	@has_access
	def discount_analysis(self):
		"""Discount Analysis — average discount % and total discount value by rep."""
		session = _get_session()
		from pgappforge.plugins.erp.crm.cpq.models import Quote

		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				Quote.owner_id,
				sa.func.count(Quote.id).label("quote_count"),
				sa.func.coalesce(sa.func.sum(Quote.subtotal_cents), 0).label("subtotal"),
				sa.func.coalesce(sa.func.sum(Quote.discount_cents), 0).label("total_discount"),
				sa.func.coalesce(sa.func.sum(Quote.total_cents), 0).label("total_net"),
			)
			.where(Quote.status.in_(["SENT", "ACCEPTED", "REJECTED", "EXPIRED"]))
			.group_by(Quote.owner_id)
			.order_by(sa.desc(sa.func.sum(Quote.discount_cents)))
			.limit(100)
		)
		if tenant_id:
			q = q.where(Quote.tenant_id == tenant_id)

		def _disc_pct(subtotal: int, discount: int) -> str:
			return f"{discount / subtotal * 100:.1f}%" if subtotal > 0 else "—"

		rows_data = session.execute(q).all()
		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(r.owner_id)}</td>"
			f"<td class='text-right'>{r.quote_count}</td>"
			f"<td class='text-right'>{_cents(int(r.subtotal))}</td>"
			f"<td class='text-right'>{_cents(int(r.total_discount))}</td>"
			f"<td class='text-right'>{_disc_pct(int(r.subtotal), int(r.total_discount))}</td>"
			f"<td class='text-right'>{_cents(int(r.total_net))}</td>"
			f"</tr>"
			for r in rows_data
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Discount Analysis</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style>
</head><body>
<h3>Discount Analysis by Rep</h3>
<table class="table table-bordered table-condensed table-hover">
<thead><tr><th>Rep</th><th class="text-right">Quotes</th><th class="text-right">Subtotal</th>
<th class="text-right">Total Discount</th><th class="text-right">Avg Discount %</th>
<th class="text-right">Net Revenue</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"ProductCatalogView",
	"PricingRuleView",
	"ProductBundleView",
	"QuoteView",
	"CPQReportView",
]
