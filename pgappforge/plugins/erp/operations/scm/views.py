"""
pgappforge/plugins/erp/operations/scm/views.py

Flask views for the Supply Chain Management plugin.

Registered views:
  SupplierView         — CRUD + approve action
  SupplierProductView  — CRUD (sourcing price records)
  ShipmentTrackingView — CRUD + add milestone event
  SCMReportView        — 3 reports:
                         * Supplier Scorecard
                         * Overdue Shipments
                         * Sourcing Price Comparison
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


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
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px} @media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


# ---------------------------------------------------------------------------
# SupplierView
# ---------------------------------------------------------------------------

class SupplierView(BaseERPView):
	"""SCM Supplier CRUD + approve.

	GET  /scm/suppliers/              — list
	GET  /scm/suppliers/<id>          — detail
	POST /scm/suppliers/              — create
	PUT  /scm/suppliers/<id>          — update
	POST /scm/suppliers/<id>/approve  — set preferred=True
	POST /scm/suppliers/<id>/refresh-kpis — recompute KPIs
	"""

	route_base = "/scm/suppliers"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.scm.models import Supplier
		session = _get_session()
		q = sa.select(Supplier).order_by(Supplier.name)
		if request.args.get("tenant_id"):
			q = q.where(Supplier.tenant_id == request.args["tenant_id"])
		if request.args.get("preferred") == "1":
			q = q.where(Supplier.preferred == True)
		if request.args.get("active") == "1":
			q = q.where(Supplier.is_active == True)
		suppliers = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"suppliers": [
				{
					"id": s.id, "supplier_code": s.supplier_code,
					"name": s.name, "preferred": s.preferred,
					"rating": str(s.rating) if s.rating is not None else None,
					"on_time_delivery_pct": str(s.on_time_delivery_pct) if s.on_time_delivery_pct is not None else None,
					"quality_score": str(s.quality_score) if s.quality_score is not None else None,
					"lead_time_days": s.lead_time_days,
					"is_active": s.is_active,
				}
				for s in suppliers
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(s.supplier_code)}</td>"
			f"<td>{_he(s.name)}</td>"
			f"<td class='text-right'>{_he(s.rating or '—')}</td>"
			f"<td class='text-right'>{_he(s.on_time_delivery_pct or '—')}</td>"
			f"<td class='text-right'>{_he(s.quality_score or '—')}</td>"
			f"<td>{'<span class=\"label label-success\">Yes</span>' if s.preferred else '<span class=\"label label-default\">No</span>'}</td>"
			f"<td><a href='/scm/suppliers/{_he(s.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for s in suppliers
		)
		body = (
			'<h3>SCM Suppliers</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Name</th><th>Rating</th>'
			'<th>OTD %</th><th>Quality %</th><th>Preferred</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("SCM Suppliers", body), 200)

	@expose("/<string:supplier_id>")
	@has_access
	def detail(self, supplier_id: str):
		from pgappforge.plugins.erp.operations.scm.models import Supplier
		session = _get_session()
		sup = session.get(Supplier, supplier_id)
		if sup is None:
			abort(404)
		return jsonify({
			"id": sup.id, "tenant_id": sup.tenant_id,
			"party_id": sup.party_id, "supplier_code": sup.supplier_code,
			"name": sup.name, "preferred": sup.preferred,
			"rating": str(sup.rating) if sup.rating is not None else None,
			"on_time_delivery_pct": str(sup.on_time_delivery_pct) if sup.on_time_delivery_pct is not None else None,
			"quality_score": str(sup.quality_score) if sup.quality_score is not None else None,
			"lead_time_days": sup.lead_time_days,
			"minimum_order_value_cents": sup.minimum_order_value_cents,
			"payment_terms_days": sup.payment_terms_days,
			"currency_code": sup.currency_code,
			"is_active": sup.is_active,
			"created_at": sup.created_at.isoformat() if sup.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.scm.models import Supplier
		from pgappforge.plugins.erp.operations.scm.events import SupplierCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "supplier_code", "name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		sup = Supplier(
			tenant_id=data["tenant_id"],
			supplier_code=data["supplier_code"],
			name=data["name"],
			party_id=data.get("party_id"),
			lead_time_days=int(data.get("lead_time_days", 14)),
			minimum_order_value_cents=int(data.get("minimum_order_value_cents", 0)),
			preferred=bool(data.get("preferred", False)),
			payment_terms_days=int(data.get("payment_terms_days", 30)),
			currency_code=data.get("currency_code", "USD"),
			is_active=bool(data.get("is_active", True)),
			notes=data.get("notes"),
		)
		session.add(sup)
		session.flush()
		emit_event(
			SupplierCreatedEvent(
				aggregate_id=sup.id,
				aggregate_type="Supplier",
				tenant_id=sup.tenant_id,
				supplier_id=sup.id,
				supplier_code=sup.supplier_code,
				name=sup.name,
				party_id=sup.party_id or "",
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": sup.id}), 201

	@expose("/<string:supplier_id>", methods=["PUT"])
	@has_access
	def update(self, supplier_id: str):
		from pgappforge.plugins.erp.operations.scm.models import Supplier
		session = _get_session()
		sup = session.get(Supplier, supplier_id)
		if sup is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "lead_time_days", "minimum_order_value_cents", "preferred",
		          "payment_terms_days", "currency_code", "is_active", "notes"):
			if f in data:
				setattr(sup, f, data[f])
		sup.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:supplier_id>/approve", methods=["POST"])
	@has_access
	def approve(self, supplier_id: str):
		from pgappforge.plugins.erp.operations.scm.services import SCMService, SCMServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			sup = SCMService().approve_supplier(supplier_id, data.get("approved_by", ""), session)
			session.commit()
			return jsonify({"ok": True, "preferred": sup.preferred})
		except SCMServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:supplier_id>/refresh-kpis", methods=["POST"])
	@has_access
	def refresh_kpis(self, supplier_id: str):
		from pgappforge.plugins.erp.operations.scm.services import SCMService, SCMServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			sup = SCMService().refresh_supplier_kpis(
				supplier_id, int(data.get("period_days", 365)), session,
			)
			session.commit()
			return jsonify({
				"ok": True,
				"rating": str(sup.rating),
				"on_time_delivery_pct": str(sup.on_time_delivery_pct),
				"quality_score": str(sup.quality_score),
			})
		except SCMServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# SupplierProductView
# ---------------------------------------------------------------------------

class SupplierProductView(BaseERPView):
	"""Supplier product catalogue / sourcing price records.

	GET  /scm/supplier-products/          — list (filter by supplier, product)
	GET  /scm/supplier-products/<id>      — detail
	POST /scm/supplier-products/          — create
	"""

	route_base = "/scm/supplier-products"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.scm.models import SupplierProduct
		session = _get_session()
		q = sa.select(SupplierProduct).order_by(SupplierProduct.valid_from.desc())
		for field, col in (
			("supplier_id", SupplierProduct.supplier_id),
			("product_id", SupplierProduct.product_id),
			("tenant_id", SupplierProduct.tenant_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		records = session.execute(q.limit(1000)).scalars().all()
		return jsonify({"supplier_products": [
			{
				"id": r.id, "supplier_id": r.supplier_id,
				"product_id": r.product_id, "supplier_sku": r.supplier_sku,
				"lead_time_days": r.lead_time_days,
				"minimum_quantity": str(r.minimum_quantity),
				"price_cents": r.price_cents, "currency_code": r.currency_code,
				"valid_from": r.valid_from.isoformat() if r.valid_from else None,
				"valid_to": r.valid_to.isoformat() if r.valid_to else None,
				"is_preferred": r.is_preferred,
			}
			for r in records
		]})

	@expose("/<string:sp_id>")
	@has_access
	def detail(self, sp_id: str):
		from pgappforge.plugins.erp.operations.scm.models import SupplierProduct
		session = _get_session()
		sp = session.get(SupplierProduct, sp_id)
		if sp is None:
			abort(404)
		return jsonify({
			"id": sp.id, "tenant_id": sp.tenant_id,
			"supplier_id": sp.supplier_id, "product_id": sp.product_id,
			"supplier_sku": sp.supplier_sku, "description": sp.description,
			"lead_time_days": sp.lead_time_days,
			"minimum_quantity": str(sp.minimum_quantity),
			"uom": sp.uom, "price_cents": sp.price_cents,
			"currency_code": sp.currency_code,
			"valid_from": sp.valid_from.isoformat() if sp.valid_from else None,
			"valid_to": sp.valid_to.isoformat() if sp.valid_to else None,
			"is_preferred": sp.is_preferred,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.scm.models import SupplierProduct
		from pgappforge.plugins.erp.operations.scm.events import SupplierProductCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "supplier_id", "product_id", "price_cents", "valid_from")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		sp = SupplierProduct(
			tenant_id=data["tenant_id"],
			supplier_id=data["supplier_id"],
			product_id=data["product_id"],
			supplier_sku=data.get("supplier_sku"),
			description=data.get("description"),
			lead_time_days=int(data.get("lead_time_days", 14)),
			minimum_quantity=data.get("minimum_quantity", 1),
			uom=data.get("uom", "EA"),
			price_cents=int(data["price_cents"]),
			currency_code=data.get("currency_code", "USD"),
			valid_from=date_type.fromisoformat(data["valid_from"]),
			valid_to=date_type.fromisoformat(data["valid_to"]) if data.get("valid_to") else None,
			is_preferred=bool(data.get("is_preferred", False)),
		)
		session.add(sp)
		session.flush()
		emit_event(
			SupplierProductCreatedEvent(
				aggregate_id=sp.id,
				aggregate_type="SupplierProduct",
				tenant_id=sp.tenant_id,
				supplier_product_id=sp.id,
				supplier_id=sp.supplier_id,
				product_id=sp.product_id,
				price_cents=sp.price_cents,
				currency_code=sp.currency_code,
				lead_time_days=sp.lead_time_days,
				valid_from=sp.valid_from.isoformat(),
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": sp.id}), 201


# ---------------------------------------------------------------------------
# ShipmentTrackingView
# ---------------------------------------------------------------------------

class ShipmentTrackingView(BaseERPView):
	"""Shipment tracking CRUD + milestone events.

	GET  /scm/shipments/                    — list
	GET  /scm/shipments/<id>               — detail with events
	POST /scm/shipments/                   — create
	POST /scm/shipments/<id>/add-event     — append milestone event
	"""

	route_base = "/scm/shipments"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.scm.models import ShipmentTracking
		session = _get_session()
		q = sa.select(ShipmentTracking).order_by(sa.desc(ShipmentTracking.shipped_at))
		for field, col in (
			("tenant_id", ShipmentTracking.tenant_id),
			("supplier_id", ShipmentTracking.supplier_id),
			("status", ShipmentTracking.status),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		shipments = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"shipments": [
				{
					"id": s.id, "carrier": s.carrier,
					"tracking_number": s.tracking_number,
					"supplier_id": s.supplier_id,
					"estimated_arrival": s.estimated_arrival.isoformat() if s.estimated_arrival else None,
					"actual_arrival": s.actual_arrival.isoformat() if s.actual_arrival else None,
					"status": s.status,
				}
				for s in shipments
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(s.carrier)}</td>"
			f"<td>{_he(s.tracking_number)}</td>"
			f"<td>{_he(s.estimated_arrival or '—')}</td>"
			f"<td>{_he(s.actual_arrival or '—')}</td>"
			f"<td><span class='label label-{'success' if s.status=='DELIVERED' else 'warning' if s.status=='IN_TRANSIT' else 'danger'}'>{_he(s.status)}</span></td>"
			f"<td><a href='/scm/shipments/{_he(s.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for s in shipments
		)
		body = (
			'<h3>Shipments</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Carrier</th><th>Tracking #</th>'
			'<th>ETA</th><th>Arrived</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Shipments", body), 200)

	@expose("/<string:shipment_id>")
	@has_access
	def detail(self, shipment_id: str):
		from pgappforge.plugins.erp.operations.scm.models import ShipmentTracking
		session = _get_session()
		s = session.get(ShipmentTracking, shipment_id)
		if s is None:
			abort(404)
		return jsonify({
			"id": s.id, "tenant_id": s.tenant_id,
			"supplier_id": s.supplier_id,
			"purchase_order_id": s.purchase_order_id,
			"carrier": s.carrier, "tracking_number": s.tracking_number,
			"carrier_service": s.carrier_service,
			"origin_warehouse_id": s.origin_warehouse_id,
			"destination_warehouse_id": s.destination_warehouse_id,
			"origin_address": s.origin_address,
			"destination_address": s.destination_address,
			"shipped_at": s.shipped_at.isoformat() if s.shipped_at else None,
			"estimated_arrival": s.estimated_arrival.isoformat() if s.estimated_arrival else None,
			"actual_arrival": s.actual_arrival.isoformat() if s.actual_arrival else None,
			"status": s.status,
			"events": s.events,
			"declared_value_cents": s.declared_value_cents,
			"currency_code": s.currency_code,
			"incoterms": s.incoterms,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.scm.models import ShipmentTracking
		from pgappforge.plugins.erp.operations.scm.events import ShipmentCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "carrier", "tracking_number")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		shipped_at = None
		if data.get("shipped_at"):
			from datetime import datetime as dt
			shipped_at = dt.fromisoformat(data["shipped_at"])

		s = ShipmentTracking(
			tenant_id=data["tenant_id"],
			supplier_id=data.get("supplier_id"),
			purchase_order_id=data.get("purchase_order_id"),
			shipment_reference=data.get("shipment_reference"),
			carrier=data["carrier"],
			tracking_number=data["tracking_number"],
			carrier_service=data.get("carrier_service"),
			origin_warehouse_id=data.get("origin_warehouse_id"),
			destination_warehouse_id=data.get("destination_warehouse_id"),
			origin_address=data.get("origin_address") or {},
			destination_address=data.get("destination_address") or {},
			shipped_at=shipped_at,
			estimated_arrival=date_type.fromisoformat(data["estimated_arrival"]) if data.get("estimated_arrival") else None,
			status="IN_TRANSIT",
			events=[],
			declared_value_cents=int(data["declared_value_cents"]) if data.get("declared_value_cents") else None,
			currency_code=data.get("currency_code"),
			incoterms=data.get("incoterms"),
			notes=data.get("notes"),
		)
		session.add(s)
		session.flush()
		emit_event(
			ShipmentCreatedEvent(
				aggregate_id=s.id,
				aggregate_type="ShipmentTracking",
				tenant_id=s.tenant_id,
				shipment_id=s.id,
				carrier=s.carrier,
				tracking_number=s.tracking_number,
				supplier_id=s.supplier_id or "",
				destination_warehouse_id=s.destination_warehouse_id or "",
				estimated_arrival=s.estimated_arrival.isoformat() if s.estimated_arrival else "",
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": s.id}), 201

	@expose("/<string:shipment_id>/add-event", methods=["POST"])
	@has_access
	def add_event(self, shipment_id: str):
		from pgappforge.plugins.erp.operations.scm.services import SCMService, SCMServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		status = data.get("status", "IN_TRANSIT")
		try:
			s = SCMService().add_shipment_event(
				shipment_id,
				status=status,
				location=data.get("location", ""),
				note=data.get("note", ""),
				session=session,
			)
			session.commit()
			return jsonify({"ok": True, "status": s.status, "events_count": len(s.events)})
		except SCMServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# SCMReportView — 3 canned reports
# ---------------------------------------------------------------------------

class SCMReportView(BaseERPView):
	"""SCM canned reports.

	GET /scm/reports/                   — Dashboard with KPI tiles
	GET /scm/reports/scorecard          — Supplier Scorecard
	GET /scm/reports/overdue-shipments  — Overdue Shipments
	GET /scm/reports/price-comparison   — Sourcing Price Comparison
	POST /scm/reports/p2p/process/<id>  — advance P2P workflow state
	"""

	route_base = "/scm/reports"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		"""SCM dashboard — KPI tiles for open POs, pending GRNs, approved suppliers, YTD spend."""
		from pgappforge.plugins.erp.operations.scm.models import Supplier, ShipmentTracking
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		open_pos: int = 0
		pending_grns: int = 0
		approved_suppliers: int = 0
		ytd_spend_cents: int = 0

		try:
			import sqlalchemy as _sa
			approved_suppliers = session.execute(
				_sa.select(_sa.func.count()).select_from(Supplier).where(
					Supplier.preferred.is_(True),
					Supplier.is_active.is_(True),
					*([Supplier.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			pending_grns = session.execute(
				_sa.select(_sa.func.count()).select_from(ShipmentTracking).where(
					ShipmentTracking.status == "IN_TRANSIT",
					*([ShipmentTracking.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Open POs", "value": open_pos, "format": "integer",
			 "color": "#1a56db", "icon": "fa-file-invoice"},
			{"label": "Pending GRNs", "value": pending_grns, "format": "integer",
			 "color": "#e3a008", "icon": "fa-truck"},
			{"label": "Approved Suppliers", "value": approved_suppliers, "format": "integer",
			 "color": "#057a55", "icon": "fa-check-circle"},
			{"label": "YTD Spend", "value": ytd_spend_cents / 100, "format": "currency",
			 "color": "#9061f9", "icon": "fa-dollar-sign"},
		])

		if request.args.get("format") == "json":
			return jsonify({
				"open_pos": open_pos,
				"pending_grns": pending_grns,
				"approved_suppliers": approved_suppliers,
				"ytd_spend_cents": ytd_spend_cents,
			})

		body = (
			"<h3>SCM Dashboard</h3>"
			+ str(kpi_html)
			+ '<p><a href="/scm/reports/scorecard" class="btn btn-default">Supplier Scorecard</a> '
			+ '<a href="/scm/reports/overdue-shipments" class="btn btn-default">Overdue Shipments</a></p>'
		)
		from flask import make_response as _mr
		return _mr(_page_html("SCM Dashboard", body), 200)

	@expose("/p2p/process/<string:record_id>", methods=["POST"])
	@has_access
	def process_p2p(self, record_id: str):
		from pgappforge.plugins.erp.operations.scm.services import SCMService, SCMServiceError
		session = _get_session()
		try:
			record = SCMService().advance_to_next_step(record_id, session)
			session.commit()
			return jsonify({
				"ok": True,
				"id": record.id,
				"type": record.__class__.__name__,
				"status": getattr(record, "status", None),
			})
		except SCMServiceError as exc:
			session.rollback()
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/scorecard")
	@has_access
	def scorecard(self):
		"""Supplier scorecard: rating, OTD%, quality score, lead time."""
		from pgappforge.plugins.erp.operations.scm.models import Supplier
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = sa.select(Supplier).where(Supplier.is_active == True).order_by(
			sa.desc(Supplier.rating).nullslast(), Supplier.name
		)
		if tenant_id:
			q = q.where(Supplier.tenant_id == tenant_id)
		suppliers = session.execute(q.limit(500)).scalars().all()

		data = [
			{
				"supplier_code": s.supplier_code, "name": s.name,
				"rating": float(s.rating) if s.rating is not None else None,
				"on_time_delivery_pct": float(s.on_time_delivery_pct) if s.on_time_delivery_pct is not None else None,
				"quality_score": float(s.quality_score) if s.quality_score is not None else None,
				"lead_time_days": s.lead_time_days,
				"preferred": s.preferred,
			}
			for s in suppliers
		]

		if request.args.get("format") == "json":
			return jsonify({"scorecard": data})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['supplier_code'])}</td>"
			f"<td>{_he(r['name'])}</td>"
			f"<td class='text-right'>{r['rating']:.1f if r['rating'] is not None else '—'}</td>"
			f"<td class='text-right'>{r['on_time_delivery_pct']:.1f if r['on_time_delivery_pct'] is not None else '—'}%</td>"
			f"<td class='text-right'>{r['quality_score']:.1f if r['quality_score'] is not None else '—'}%</td>"
			f"<td class='text-right'>{r['lead_time_days']}</td>"
			f"<td>{'<span class=\"label label-success\">Yes</span>' if r['preferred'] else ''}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			'<h3>Supplier Scorecard</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Name</th><th>Rating</th>'
			'<th>OTD %</th><th>Quality %</th><th>Lead Time (d)</th><th>Preferred</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Supplier Scorecard", body), 200)

	@expose("/overdue-shipments")
	@has_access
	def overdue_shipments(self):
		"""Overdue shipments: IN_TRANSIT past estimated arrival."""
		from pgappforge.plugins.erp.operations.scm.services import SCMService
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		shipments = SCMService().get_overdue_shipments(tenant_id, session)
		from datetime import date as date_type
		today = date_type.today()

		data = [
			{
				"id": s.id, "carrier": s.carrier,
				"tracking_number": s.tracking_number,
				"supplier_id": s.supplier_id,
				"estimated_arrival": s.estimated_arrival.isoformat() if s.estimated_arrival else None,
				"days_overdue": (today - s.estimated_arrival).days if s.estimated_arrival else None,
				"destination_warehouse_id": s.destination_warehouse_id,
			}
			for s in shipments
		]

		if request.args.get("format") == "json":
			return jsonify({"overdue_shipments": data, "count": len(data)})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['carrier'])}</td>"
			f"<td>{_he(r['tracking_number'])}</td>"
			f"<td>{_he(r['estimated_arrival'])}</td>"
			f"<td class='text-danger'><strong>{_he(r['days_overdue'])}</strong></td>"
			f"<td>{_he(r['destination_warehouse_id'] or '—')}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			f'<h3>Overdue Shipments ({len(data)})</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Carrier</th><th>Tracking #</th>'
			'<th>ETA</th><th>Days Overdue</th><th>Destination</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Overdue Shipments", body), 200)

	@expose("/price-comparison")
	@has_access
	def price_comparison(self):
		"""Sourcing price comparison: all active prices for a product."""
		from pgappforge.plugins.erp.operations.scm.models import SupplierProduct, Supplier
		from datetime import date as date_type
		session = _get_session()
		product_id = request.args.get("product_id")
		tenant_id = request.args.get("tenant_id")
		if not product_id:
			return jsonify({"ok": False, "error": "product_id required"}), 400

		today = date_type.today()
		q = (
			sa.select(SupplierProduct, Supplier)
			.join(Supplier, SupplierProduct.supplier_id == Supplier.id)
			.where(
				SupplierProduct.product_id == product_id,
				SupplierProduct.valid_from <= today,
				sa.or_(
					SupplierProduct.valid_to.is_(None),
					SupplierProduct.valid_to >= today,
				),
				Supplier.is_active == True,
			)
			.order_by(SupplierProduct.price_cents)
		)
		if tenant_id:
			q = q.where(SupplierProduct.tenant_id == tenant_id)

		rows_raw = session.execute(q).all()
		data = [
			{
				"supplier_code": sup.supplier_code, "supplier_name": sup.name,
				"supplier_sku": sp.supplier_sku,
				"price_cents": sp.price_cents, "currency_code": sp.currency_code,
				"lead_time_days": sp.lead_time_days,
				"minimum_quantity": str(sp.minimum_quantity),
				"is_preferred": sp.is_preferred,
				"rating": float(sup.rating) if sup.rating is not None else None,
			}
			for sp, sup in rows_raw
		]

		if request.args.get("format") == "json":
			return jsonify({"price_comparison": data, "product_id": product_id})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['supplier_code'])}</td>"
			f"<td>{_he(r['supplier_name'])}</td>"
			f"<td>{_he(r['supplier_sku'] or '—')}</td>"
			f"<td class='text-right'>{_he(r['currency_code'])} {r['price_cents'] / 100:,.4f}</td>"
			f"<td class='text-right'>{r['lead_time_days']}</td>"
			f"<td class='text-right'>{r['minimum_quantity']}</td>"
			f"<td>{'<span class=\"label label-success\">Yes</span>' if r['is_preferred'] else ''}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			f'<h3>Price Comparison — Product {_he(product_id)}</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Supplier</th><th>Name</th><th>Supplier SKU</th>'
			'<th>Unit Price</th><th>Lead Time</th><th>MOQ</th><th>Preferred</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Price Comparison", body), 200)


__all__ = [
	"SupplierView",
	"SupplierProductView",
	"ShipmentTrackingView",
	"SCMReportView",
]
