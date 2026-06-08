"""
pgappforge/plugins/erp/operations/production/views.py

Flask views for the Production Planning plugin.

Registered views:
  BOMView                — CRUD + activate BOM action
  WorkCenterView         — CRUD
  ProductionOrderView    — CRUD + release/start/complete/cancel actions
  DemandForecastView     — CRUD
  PPReportView           — 3 reports:
                           * Production Schedule (orders by date/work center)
                           * BOM Cost Roll-up
                           * Demand vs Actual (forecast accuracy)
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


# ---------------------------------------------------------------------------
# Shared helpers (mirrors AP pattern)
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
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px} @media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


# ---------------------------------------------------------------------------
# BOMView
# ---------------------------------------------------------------------------

class BOMView(BaseERPView):
	"""BOM CRUD + activation.

	GET  /pp/bom/              — list
	GET  /pp/bom/<id>          — detail with lines
	POST /pp/bom/              — create BOM header
	POST /pp/bom/<id>/lines    — add BOM line
	POST /pp/bom/<id>/activate — DRAFT → ACTIVE (obsoletes current active)
	"""

	route_base = "/pp/bom"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.production.models import BillOfMaterials
		session = _get_session()
		q = sa.select(BillOfMaterials).order_by(sa.desc(BillOfMaterials.effective_from))
		if request.args.get("product_id"):
			q = q.where(BillOfMaterials.product_id == request.args["product_id"])
		if request.args.get("status"):
			q = q.where(BillOfMaterials.status == request.args["status"])
		boms = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"boms": [
				{
					"id": b.id, "product_id": b.product_id,
					"version": b.version, "status": b.status,
					"effective_from": b.effective_from.isoformat() if b.effective_from else None,
					"effective_to": b.effective_to.isoformat() if b.effective_to else None,
					"is_phantom": b.is_phantom,
				}
				for b in boms
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(b.product_id)}</td>"
			f"<td>{_he(b.version)}</td>"
			f"<td><span class='label label-{'success' if b.status=='ACTIVE' else 'default'}'>{_he(b.status)}</span></td>"
			f"<td>{_he(b.effective_from)}</td>"
			f"<td>{_he(b.effective_to or '—')}</td>"
			f"<td><a href='/pp/bom/{_he(b.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for b in boms
		)
		body = (
			'<h3>Bills of Materials</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Product</th><th>Version</th><th>Status</th>'
			'<th>From</th><th>To</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Bills of Materials", body), 200)

	@expose("/<string:bom_id>")
	@has_access
	def detail(self, bom_id: str):
		from pgappforge.plugins.erp.operations.production.models import BillOfMaterials
		session = _get_session()
		bom = session.get(BillOfMaterials, bom_id)
		if bom is None:
			abort(404)
		return jsonify({
			"id": bom.id, "tenant_id": bom.tenant_id,
			"product_id": bom.product_id, "version": bom.version,
			"status": bom.status, "is_phantom": bom.is_phantom,
			"effective_from": bom.effective_from.isoformat() if bom.effective_from else None,
			"effective_to": bom.effective_to.isoformat() if bom.effective_to else None,
			"uom": bom.uom, "yield_pct": str(bom.yield_pct),
			"lines": [
				{
					"id": l.id, "component_product_id": l.component_product_id,
					"quantity": str(l.quantity), "uom": l.uom,
					"position": l.position,
					"scrap_factor": str(l.scrap_factor),
					"is_critical": l.is_critical,
				}
				for l in bom.lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.production.models import BillOfMaterials, BOMLine
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "product_id", "effective_from")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		bom = BillOfMaterials(
			tenant_id=data["tenant_id"],
			product_id=data["product_id"],
			version=data.get("version", "1"),
			effective_from=date_type.fromisoformat(data["effective_from"]),
			effective_to=date_type.fromisoformat(data["effective_to"]) if data.get("effective_to") else None,
			status="DRAFT",
			is_phantom=bool(data.get("is_phantom", False)),
			description=data.get("description"),
			uom=data.get("uom", "EA"),
			yield_pct=data.get("yield_pct", 100),
		)
		session.add(bom)
		session.flush()

		for i, ld in enumerate(data.get("lines", []), start=1):
			session.add(BOMLine(
				tenant_id=data["tenant_id"],
				bom_id=bom.id,
				component_product_id=ld["component_product_id"],
				quantity=ld["quantity"],
				uom=ld.get("uom", "EA"),
				position=ld.get("position", i),
				scrap_factor=ld.get("scrap_factor", 0),
				is_critical=bool(ld.get("is_critical", False)),
			))

		session.commit()
		return jsonify({"ok": True, "id": bom.id}), 201

	@expose("/<string:bom_id>/activate", methods=["POST"])
	@has_access
	def activate(self, bom_id: str):
		from pgappforge.plugins.erp.operations.production.services import PPService, PPServiceError
		session = _get_session()
		svc = PPService()
		try:
			bom = svc.activate_bom(bom_id, session)
			session.commit()
			return jsonify({"ok": True, "status": bom.status})
		except PPServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# WorkCenterView
# ---------------------------------------------------------------------------

class WorkCenterView(BaseERPView):
	"""Work Center CRUD.

	GET  /pp/work-centers/         — list
	GET  /pp/work-centers/<id>     — detail
	POST /pp/work-centers/         — create
	PUT  /pp/work-centers/<id>     — update
	"""

	route_base = "/pp/work-centers"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.production.models import WorkCenter
		session = _get_session()
		q = sa.select(WorkCenter).order_by(WorkCenter.code)
		if request.args.get("tenant_id"):
			q = q.where(WorkCenter.tenant_id == request.args["tenant_id"])
		if request.args.get("active") == "1":
			q = q.where(WorkCenter.is_active == True)
		wcs = session.execute(q.limit(500)).scalars().all()
		return jsonify({"work_centers": [
			{
				"id": w.id, "code": w.code, "name": w.name,
				"capacity_units_per_hour": str(w.capacity_units_per_hour),
				"overhead_rate_per_hour_cents": w.overhead_rate_per_hour_cents,
				"gl_cost_center": w.gl_cost_center,
				"is_active": w.is_active,
			}
			for w in wcs
		]})

	@expose("/<string:wc_id>")
	@has_access
	def detail(self, wc_id: str):
		from pgappforge.plugins.erp.operations.production.models import WorkCenter
		session = _get_session()
		wc = session.get(WorkCenter, wc_id)
		if wc is None:
			abort(404)
		return jsonify({
			"id": wc.id, "tenant_id": wc.tenant_id, "code": wc.code,
			"name": wc.name, "description": wc.description,
			"capacity_units_per_hour": str(wc.capacity_units_per_hour),
			"overhead_rate_per_hour_cents": wc.overhead_rate_per_hour_cents,
			"gl_cost_center": wc.gl_cost_center,
			"is_active": wc.is_active,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.production.models import WorkCenter
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "code", "name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		wc = WorkCenter(
			tenant_id=data["tenant_id"],
			code=data["code"],
			name=data["name"],
			description=data.get("description"),
			capacity_units_per_hour=data.get("capacity_units_per_hour", 1),
			overhead_rate_per_hour_cents=int(data.get("overhead_rate_per_hour_cents", 0)),
			gl_cost_center=data.get("gl_cost_center"),
			is_active=bool(data.get("is_active", True)),
		)
		session.add(wc)
		session.commit()
		return jsonify({"ok": True, "id": wc.id}), 201

	@expose("/<string:wc_id>", methods=["PUT"])
	@has_access
	def update(self, wc_id: str):
		from pgappforge.plugins.erp.operations.production.models import WorkCenter
		session = _get_session()
		wc = session.get(WorkCenter, wc_id)
		if wc is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "description", "capacity_units_per_hour",
		          "overhead_rate_per_hour_cents", "gl_cost_center", "is_active"):
			if f in data:
				setattr(wc, f, data[f])
		wc.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# ProductionOrderView
# ---------------------------------------------------------------------------

class ProductionOrderView(BaseERPView):
	"""Production Order CRUD + lifecycle.

	GET  /pp/orders/              — list
	GET  /pp/orders/dashboard     — KPI tiles + approval buttons for QC pending orders
	GET  /pp/orders/<id>          — detail with lines and operations
	POST /pp/orders/              — create
	POST /pp/orders/<id>/release  — PLANNED → RELEASED
	POST /pp/orders/<id>/start    — RELEASED → IN_PROGRESS
	POST /pp/orders/<id>/complete — IN_PROGRESS → COMPLETED
	POST /pp/orders/<id>/cancel   — → CANCELLED
	POST /pp/orders/<id>/issue-component — issue material to shop floor
	"""

	route_base = "/pp/orders"
	default_view = "dashboard"

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		"""Production dashboard — KPI tiles and approval buttons for orders pending QC sign-off."""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		open_orders: int = 0
		completed_today: int = 0
		avg_yield_pct: float = 0.0
		wip_value_cents: int = 0
		pending_qc: list = []

		try:
			from datetime import date as _date
			open_orders = session.execute(
				sa.select(sa.func.count()).select_from(ProductionOrder).where(
					ProductionOrder.status.in_(("PLANNED", "RELEASED", "IN_PROGRESS")),
					*([ProductionOrder.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			today = _date.today()
			completed_today = session.execute(
				sa.select(sa.func.count()).select_from(ProductionOrder).where(
					ProductionOrder.status == "COMPLETED",
					sa.func.date(ProductionOrder.actual_end_date) == today,
					*([ProductionOrder.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			pending_qc = session.execute(
				sa.select(ProductionOrder).where(
					ProductionOrder.status == "IN_PROGRESS",
					*([ProductionOrder.tenant_id == tenant_id] if tenant_id else []),
				).limit(10)
			).scalars().all()
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Open Orders", "value": open_orders, "format": "integer",
			 "color": "#1a56db", "icon": "fa-industry"},
			{"label": "Completed Today", "value": completed_today, "format": "integer",
			 "color": "#057a55", "icon": "fa-check-circle"},
			{"label": "Avg Yield %", "value": avg_yield_pct, "format": "percent",
			 "color": "#e3a008", "icon": "fa-percentage"},
			{"label": "WIP Value", "value": wip_value_cents / 100, "format": "currency",
			 "color": "#9061f9", "icon": "fa-dollar-sign"},
		])

		approval_html_parts: list[str] = []
		for order in pending_qc:
			btn_html = self.approval_buttons(
				{"process_instance_id": order.id, "current_step": order.status},
				advance_url=f"/pp/orders/{order.id}/complete",
				reject_url=f"/pp/orders/{order.id}/cancel",
				instance_id_col="process_instance_id",
				step_col="current_step",
			)
			approval_html_parts.append(
				f'<div style="margin-bottom:8px"><strong>{_he(order.order_number)}</strong> '
				f'— {_he(order.product_id)} — {_he(order.status)}: {btn_html}</div>'
			)

		if request.args.get("format") == "json":
			return jsonify({
				"open_orders": open_orders,
				"completed_today": completed_today,
				"avg_yield_pct": avg_yield_pct,
				"wip_value_cents": wip_value_cents,
				"pending_qc_count": len(pending_qc),
			})

		approval_section = (
			"<h4>Orders Pending QC Sign-off</h4>" + "".join(approval_html_parts)
			if approval_html_parts else ""
		)
		body = (
			"<h3>Production Dashboard</h3>"
			+ str(kpi_html)
			+ approval_section
			+ '<p><a href="/pp/orders/" class="btn btn-default">All Orders</a> '
			+ '<a href="/pp/reports/schedule" class="btn btn-default">Schedule</a></p>'
		)
		return make_response(_page_html("Production Dashboard", body), 200)

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		session = _get_session()
		q = sa.select(ProductionOrder).order_by(ProductionOrder.start_date)
		for field, col in (
			("tenant_id", ProductionOrder.tenant_id),
			("product_id", ProductionOrder.product_id),
			("status", ProductionOrder.status),
			("work_center_id", ProductionOrder.work_center_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		orders = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"production_orders": [
				{
					"id": o.id, "order_number": o.order_number,
					"product_id": o.product_id,
					"planned_quantity": str(o.planned_quantity),
					"produced_quantity": str(o.produced_quantity),
					"start_date": o.start_date.isoformat() if o.start_date else None,
					"end_date": o.end_date.isoformat() if o.end_date else None,
					"status": o.status,
					"actual_cost_cents": o.actual_cost_cents,
					"planned_cost_cents": o.planned_cost_cents,
				}
				for o in orders
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(o.order_number)}</td>"
			f"<td>{_he(o.product_id)}</td>"
			f"<td>{_he(o.planned_quantity)}</td>"
			f"<td>{_he(o.start_date)} → {_he(o.end_date)}</td>"
			f"<td><span class='label label-info'>{_he(o.status)}</span></td>"
			f"<td><a href='/pp/orders/{_he(o.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for o in orders
		)
		body = (
			'<h3>Production Orders</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Order #</th><th>Product</th><th>Planned Qty</th>'
			'<th>Dates</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Production Orders", body), 200)

	@expose("/<string:order_id>")
	@has_access
	def detail(self, order_id: str):
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		session = _get_session()
		order = session.get(ProductionOrder, order_id)
		if order is None:
			abort(404)
		return jsonify({
			"id": order.id, "tenant_id": order.tenant_id,
			"order_number": order.order_number, "product_id": order.product_id,
			"bom_id": order.bom_id, "work_center_id": order.work_center_id,
			"planned_quantity": str(order.planned_quantity),
			"produced_quantity": str(order.produced_quantity),
			"uom": order.uom,
			"start_date": order.start_date.isoformat() if order.start_date else None,
			"end_date": order.end_date.isoformat() if order.end_date else None,
			"actual_start_date": order.actual_start_date.isoformat() if order.actual_start_date else None,
			"actual_end_date": order.actual_end_date.isoformat() if order.actual_end_date else None,
			"status": order.status,
			"planned_cost_cents": order.planned_cost_cents,
			"actual_cost_cents": order.actual_cost_cents,
			"lines": [
				{
					"id": l.id, "component_product_id": l.component_product_id,
					"required_quantity": str(l.required_quantity),
					"issued_quantity": str(l.issued_quantity),
					"uom": l.uom, "status": l.status,
				}
				for l in order.lines
			],
			"operations": [
				{
					"id": op.id, "operation_number": op.operation_number,
					"work_center_id": op.work_center_id,
					"setup_time_minutes": op.setup_time_minutes,
					"run_time_minutes": op.run_time_minutes,
					"actual_time_minutes": op.actual_time_minutes,
					"status": op.status,
					"labor_cost_cents": op.labor_cost_cents,
				}
				for op in order.operations
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.production.models import (
			ProductionOrder, ProductionOrderLine, WorkOrderOperation,
		)
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "product_id", "planned_quantity", "start_date", "end_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		order = ProductionOrder(
			tenant_id=data["tenant_id"],
			order_number=data.get("order_number") or f"MO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
			product_id=data["product_id"],
			bom_id=data.get("bom_id"),
			work_center_id=data.get("work_center_id"),
			planned_quantity=data["planned_quantity"],
			uom=data.get("uom", "EA"),
			start_date=date_type.fromisoformat(data["start_date"]),
			end_date=date_type.fromisoformat(data["end_date"]),
			status="PLANNED",
			planned_cost_cents=data.get("planned_cost_cents"),
			notes=data.get("notes"),
		)
		session.add(order)
		session.flush()

		for ld in data.get("lines", []):
			session.add(ProductionOrderLine(
				tenant_id=data["tenant_id"],
				production_order_id=order.id,
				component_product_id=ld["component_product_id"],
				required_quantity=ld["required_quantity"],
				uom=ld.get("uom", "EA"),
				unit_cost_cents=ld.get("unit_cost_cents"),
				status="PENDING",
			))

		for op_data in data.get("operations", []):
			session.add(WorkOrderOperation(
				tenant_id=data["tenant_id"],
				production_order_id=order.id,
				operation_number=op_data["operation_number"],
				work_center_id=op_data.get("work_center_id", data.get("work_center_id")),
				description=op_data.get("description"),
				setup_time_minutes=int(op_data.get("setup_time_minutes", 0)),
				run_time_minutes=int(op_data.get("run_time_minutes", 0)),
				status="PENDING",
			))

		session.commit()
		return jsonify({"ok": True, "id": order.id, "order_number": order.order_number}), 201

	@expose("/<string:order_id>/release", methods=["POST"])
	@has_access
	def release(self, order_id: str):
		from pgappforge.plugins.erp.operations.production.services import PPService, PPServiceError
		session = _get_session()
		try:
			order = PPService().release_production_order(order_id, session)
			session.commit()
			return jsonify({"ok": True, "status": order.status})
		except PPServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:order_id>/start", methods=["POST"])
	@has_access
	def start(self, order_id: str):
		from pgappforge.plugins.erp.operations.production.services import PPService, PPServiceError
		session = _get_session()
		try:
			order = PPService().start_production_order(order_id, session)
			session.commit()
			return jsonify({"ok": True, "status": order.status})
		except PPServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:order_id>/complete", methods=["POST"])
	@has_access
	def complete(self, order_id: str):
		from decimal import Decimal
		from pgappforge.plugins.erp.operations.production.services import PPService, PPServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		qty_str = data.get("produced_quantity")
		if not qty_str:
			return jsonify({"ok": False, "error": "produced_quantity required"}), 400
		try:
			order = PPService().complete_production_order(order_id, Decimal(str(qty_str)), session)
			session.commit()
			return jsonify({
				"ok": True, "status": order.status,
				"produced_quantity": str(order.produced_quantity),
				"actual_cost_cents": order.actual_cost_cents,
			})
		except PPServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:order_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, order_id: str):
		from pgappforge.plugins.erp.operations.production.services import PPService, PPServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			order = PPService().cancel_production_order(order_id, data.get("reason", ""), session)
			session.commit()
			return jsonify({"ok": True, "status": order.status})
		except PPServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:order_id>/issue-component", methods=["POST"])
	@has_access
	def issue_component(self, order_id: str):
		from decimal import Decimal
		from pgappforge.plugins.erp.operations.production.services import PPService, PPServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		line_id = data.get("line_id")
		qty_str = data.get("quantity")
		if not line_id or not qty_str:
			return jsonify({"ok": False, "error": "line_id and quantity required"}), 400
		try:
			line = PPService().issue_component(
				line_id, Decimal(str(qty_str)), data.get("warehouse_id"), session,
			)
			session.commit()
			return jsonify({
				"ok": True,
				"issued_quantity": str(line.issued_quantity),
				"status": line.status,
			})
		except PPServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# DemandForecastView
# ---------------------------------------------------------------------------

class DemandForecastView(BaseERPView):
	"""Demand Forecast CRUD.

	GET  /pp/forecasts/         — list (filter by product, warehouse, method)
	GET  /pp/forecasts/<id>     — detail
	POST /pp/forecasts/         — create
	"""

	route_base = "/pp/forecasts"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.production.models import DemandForecast
		session = _get_session()
		q = sa.select(DemandForecast).where(DemandForecast.is_active == True).order_by(DemandForecast.forecast_date)
		for field, col in (
			("product_id", DemandForecast.product_id),
			("warehouse_id", DemandForecast.warehouse_id),
			("forecast_method", DemandForecast.forecast_method),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		forecasts = session.execute(q.limit(1000)).scalars().all()
		return jsonify({"forecasts": [
			{
				"id": f.id, "product_id": f.product_id,
				"warehouse_id": f.warehouse_id,
				"forecast_date": f.forecast_date.isoformat() if f.forecast_date else None,
				"forecast_quantity": str(f.forecast_quantity),
				"uom": f.uom,
				"forecast_method": f.forecast_method,
				"confidence_interval": f.confidence_interval,
				"created_by_model": f.created_by_model,
			}
			for f in forecasts
		]})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.production.models import DemandForecast
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "product_id", "forecast_date", "forecast_quantity")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		fc = DemandForecast(
			tenant_id=data["tenant_id"],
			product_id=data["product_id"],
			warehouse_id=data.get("warehouse_id"),
			forecast_date=date_type.fromisoformat(data["forecast_date"]),
			forecast_quantity=data["forecast_quantity"],
			uom=data.get("uom", "EA"),
			forecast_method=data.get("forecast_method", "MANUAL"),
			confidence_interval=data.get("confidence_interval") or {},
			created_by_model=data.get("created_by_model"),
			notes=data.get("notes"),
		)
		session.add(fc)
		session.commit()
		return jsonify({"ok": True, "id": fc.id}), 201


# ---------------------------------------------------------------------------
# PPReportView — 3 canned reports
# ---------------------------------------------------------------------------

class PPReportView(BaseERPView):
	"""Production Planning reports.

	GET /pp/reports/schedule         — Production Schedule (orders by date/WC)
	GET /pp/reports/bom-cost-rollup  — BOM cost roll-up by product
	GET /pp/reports/forecast-accuracy — Demand forecast vs actual production
	"""

	route_base = "/pp/reports"
	default_view = "schedule"

	@expose("/schedule")
	@has_access
	def schedule(self):
		"""Production Schedule: open orders grouped by work center and date."""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder, WorkCenter
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(ProductionOrder, WorkCenter)
			.outerjoin(WorkCenter, ProductionOrder.work_center_id == WorkCenter.id)
			.where(ProductionOrder.status.notin_(["COMPLETED", "CANCELLED"]))
			.order_by(ProductionOrder.start_date, WorkCenter.code)
		)
		if tenant_id:
			q = q.where(ProductionOrder.tenant_id == tenant_id)

		rows_raw = session.execute(q.limit(500)).all()
		data = [
			{
				"order_number": o.order_number,
				"product_id": o.product_id,
				"planned_quantity": str(o.planned_quantity),
				"start_date": o.start_date.isoformat() if o.start_date else None,
				"end_date": o.end_date.isoformat() if o.end_date else None,
				"work_center_code": wc.code if wc else None,
				"work_center_name": wc.name if wc else None,
				"status": o.status,
			}
			for o, wc in rows_raw
		]

		if request.args.get("format") == "json":
			return jsonify({"schedule": data, "count": len(data)})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['order_number'])}</td>"
			f"<td>{_he(r['product_id'])}</td>"
			f"<td>{_he(r['planned_quantity'])}</td>"
			f"<td>{_he(r['start_date'])} → {_he(r['end_date'])}</td>"
			f"<td>{_he(r['work_center_code'] or '—')}</td>"
			f"<td><span class='label label-info'>{_he(r['status'])}</span></td>"
			f"</tr>"
			for r in data
		)
		body = (
			'<h3>Production Schedule</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Order #</th><th>Product</th><th>Qty</th>'
			'<th>Dates</th><th>Work Center</th><th>Status</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Production Schedule", body), 200)

	@expose("/bom-cost-rollup")
	@has_access
	def bom_cost_rollup(self):
		"""BOM cost roll-up: planned vs actual cost per product across orders."""
		from pgappforge.plugins.erp.operations.production.models import ProductionOrder
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				ProductionOrder.product_id,
				sa.func.count().label("order_count"),
				sa.func.sum(ProductionOrder.planned_cost_cents).label("total_planned_cents"),
				sa.func.sum(ProductionOrder.actual_cost_cents).label("total_actual_cents"),
				sa.func.sum(ProductionOrder.produced_quantity).label("total_produced"),
			)
			.where(ProductionOrder.status == "COMPLETED")
			.group_by(ProductionOrder.product_id)
			.order_by(sa.desc(sa.func.sum(ProductionOrder.actual_cost_cents)))
		)
		if tenant_id:
			q = q.where(ProductionOrder.tenant_id == tenant_id)

		rows = session.execute(q.limit(200)).all()
		data = [
			{
				"product_id": r.product_id,
				"order_count": r.order_count,
				"total_planned_cents": r.total_planned_cents or 0,
				"total_actual_cents": r.total_actual_cents or 0,
				"variance_cents": (r.total_actual_cents or 0) - (r.total_planned_cents or 0),
				"total_produced": str(r.total_produced or 0),
			}
			for r in rows
		]

		if request.args.get("format") == "json":
			return jsonify({"bom_cost_rollup": data})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['product_id'])}</td>"
			f"<td class='text-right'>{r['order_count']}</td>"
			f"<td class='text-right'>{r['total_planned_cents'] / 100:,.2f}</td>"
			f"<td class='text-right'>{r['total_actual_cents'] / 100:,.2f}</td>"
			f"<td class='text-right {'text-danger' if r['variance_cents'] > 0 else 'text-success'}'>"
			f"{r['variance_cents'] / 100:+,.2f}</td>"
			f"<td class='text-right'>{r['total_produced']}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			'<h3>BOM Cost Roll-up</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Product</th><th>Orders</th><th>Planned Cost</th>'
			'<th>Actual Cost</th><th>Variance</th><th>Total Produced</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("BOM Cost Roll-up", body), 200)

	@expose("/forecast-accuracy")
	@has_access
	def forecast_accuracy(self):
		"""Demand forecast accuracy: forecasted vs actual produced quantity."""
		from pgappforge.plugins.erp.operations.production.models import DemandForecast, ProductionOrder
		from datetime import timedelta
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		from datetime import date as date_type
		since = date_type.today() - timedelta(days=int(request.args.get("days", 90)))

		forecasts = session.execute(
			sa.select(DemandForecast).where(
				DemandForecast.forecast_date >= since,
				DemandForecast.is_active == True,
				*([DemandForecast.tenant_id == tenant_id] if tenant_id else []),
			).order_by(DemandForecast.forecast_date)
		).scalars().all()

		rows_data = []
		for fc in forecasts:
			actual = session.execute(
				sa.select(sa.func.sum(ProductionOrder.produced_quantity))
				.where(
					ProductionOrder.product_id == fc.product_id,
					ProductionOrder.status == "COMPLETED",
					ProductionOrder.actual_end_date == fc.forecast_date,
				)
			).scalar() or 0
			from decimal import Decimal
			forecast_qty = float(Decimal(str(fc.forecast_quantity)))
			actual_qty = float(Decimal(str(actual)))
			accuracy = (
				100 - abs(forecast_qty - actual_qty) / max(forecast_qty, 0.0001) * 100
			) if forecast_qty else 0
			rows_data.append({
				"product_id": fc.product_id,
				"forecast_date": fc.forecast_date.isoformat(),
				"forecast_quantity": forecast_qty,
				"actual_quantity": actual_qty,
				"accuracy_pct": round(accuracy, 1),
				"method": fc.forecast_method,
			})

		if request.args.get("format") == "json":
			return jsonify({"forecast_accuracy": rows_data})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['product_id'])}</td>"
			f"<td>{_he(r['forecast_date'])}</td>"
			f"<td class='text-right'>{r['forecast_quantity']:,.2f}</td>"
			f"<td class='text-right'>{r['actual_quantity']:,.2f}</td>"
			f"<td class='text-right {'text-success' if r['accuracy_pct'] >= 90 else 'text-danger'}'>"
			f"{r['accuracy_pct']:.1f}%</td>"
			f"<td>{_he(r['method'])}</td>"
			f"</tr>"
			for r in rows_data
		)
		body = (
			'<h3>Demand Forecast Accuracy</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Product</th><th>Date</th><th>Forecast Qty</th>'
			'<th>Actual Qty</th><th>Accuracy %</th><th>Method</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Forecast Accuracy", body), 200)


__all__ = [
	"BOMView",
	"WorkCenterView",
	"ProductionOrderView",
	"DemandForecastView",
	"PPReportView",
]
