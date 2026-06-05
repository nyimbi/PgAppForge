"""
pgappforge/plugins/erp/industry/manufacturing/views.py

Flask views for the Manufacturing plugin.

Registered views:
  ManufacturingOrderView  — CRUD + Release Order / Complete Order / View BOM actions
  WorkCenterView          — CRUD
  OEEDashboardView        — custom view at /manufacturing/oee/ (OEE gauge + trend)
  MaintenanceWorkView     — CRUD maintenance work orders
  ProductionScheduleView  — custom view at /manufacturing/schedule/ (Gantt-style)
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
		'.oee-gauge{font-size:2.5em;font-weight:bold}'
		'.oee-world-class{color:#27ae60}'
		'.oee-acceptable{color:#f39c12}'
		'.oee-poor{color:#e74c3c}'
		'.gantt-bar{display:inline-block;height:18px;background:#3498db;border-radius:3px;min-width:4px}'
		'.gantt-conflict{background:#e74c3c}'
		'@media print{.noprint{display:none}}'
		'</style>'
		f'</head><body>{body}</body></html>'
	)


def _status_label(status: str) -> str:
	mapping = {
		"DRAFT": "default",
		"RELEASED": "primary",
		"IN_PROGRESS": "info",
		"COMPLETED": "success",
		"CANCELLED": "warning",
		"SCRAPPED": "danger",
	}
	cls = mapping.get(status, "default")
	return f"<span class='label label-{cls}'>{_he(status)}</span>"


def _maint_priority_label(priority: str) -> str:
	mapping = {
		"LOW": "default",
		"MEDIUM": "info",
		"HIGH": "warning",
		"CRITICAL": "danger",
	}
	cls = mapping.get(priority, "default")
	return f"<span class='label label-{cls}'>{_he(priority)}</span>"


# ---------------------------------------------------------------------------
# ManufacturingOrderView
# ---------------------------------------------------------------------------

class ManufacturingOrderView(BaseView):
	"""Manufacturing Order CRUD + lifecycle actions.

	GET  /manufacturing/orders/                  — list
	GET  /manufacturing/orders/<id>              — detail with schedule / OEE
	POST /manufacturing/orders/                  — create
	POST /manufacturing/orders/<id>/release      — DRAFT → RELEASED
	POST /manufacturing/orders/<id>/complete     — RELEASED|IN_PROGRESS → COMPLETED
	GET  /manufacturing/orders/<id>/bom          — proxy to BOM detail
	"""

	route_base = "/manufacturing/orders"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.manufacturing.models import ManufacturingOrder
		session = _get_session()
		q = sa.select(ManufacturingOrder).order_by(ManufacturingOrder.scheduled_start)

		for param, col in (
			("tenant_id", ManufacturingOrder.tenant_id),
			("product_id", ManufacturingOrder.product_id),
			("status", ManufacturingOrder.status),
			("work_center_id", ManufacturingOrder.work_center_id),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)

		orders = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"manufacturing_orders": [
				{
					"id": o.id,
					"order_number": o.order_number,
					"product_id": o.product_id,
					"product_sku": o.product_sku,
					"status": o.status,
					"planned_qty": str(o.planned_qty),
					"actual_qty_produced": str(o.actual_qty_produced),
					"actual_qty_scrapped": str(o.actual_qty_scrapped),
					"scheduled_start": o.scheduled_start.isoformat() if o.scheduled_start else None,
					"scheduled_end": o.scheduled_end.isoformat() if o.scheduled_end else None,
					"work_center_id": o.work_center_id,
					"priority": o.priority,
					"actual_cost_cents": o.actual_cost_cents,
				}
				for o in orders
			]})

		rows = "".join(
			f"<tr>"
			f"<td><a href='/manufacturing/orders/{_he(o.id)}'>{_he(o.order_number)}</a></td>"
			f"<td>{_he(o.product_sku or o.product_id)}</td>"
			f"<td>{_status_label(o.status)}</td>"
			f"<td class='text-right'>{_he(o.planned_qty)}</td>"
			f"<td class='text-right'>{_he(o.actual_qty_produced)}</td>"
			f"<td>{_he(o.scheduled_start.strftime('%Y-%m-%d') if o.scheduled_start else '—')}</td>"
			f"<td class='noprint'>"
			f"  <form method='post' action='/manufacturing/orders/{_he(o.id)}/release' style='display:inline'>"
			f"    <button class='btn btn-xs btn-primary' {'disabled' if o.status != 'DRAFT' else ''}>Release</button>"
			f"  </form>"
			f"  <a href='/manufacturing/orders/{_he(o.id)}/bom' class='btn btn-xs btn-default'>BOM</a>"
			f"</td>"
			f"</tr>"
			for o in orders
		)
		body = (
			'<h3>Manufacturing Orders</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr>'
			'<th>Order #</th><th>Product</th><th>Status</th>'
			'<th>Planned Qty</th><th>Produced</th><th>Start</th><th class="noprint">Actions</th>'
			'</tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">'
			f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Manufacturing Orders", body), 200)

	@expose("/<string:order_id>")
	@has_access
	def detail(self, order_id: str):
		from pgappforge.plugins.erp.industry.manufacturing.models import ManufacturingOrder
		session = _get_session()
		mo = session.get(ManufacturingOrder, order_id)
		if mo is None:
			abort(404)
		return jsonify({
			"id": mo.id,
			"tenant_id": mo.tenant_id,
			"order_number": mo.order_number,
			"product_id": mo.product_id,
			"product_sku": mo.product_sku,
			"bom_id": mo.bom_id,
			"routing_id": mo.routing_id,
			"work_center_id": mo.work_center_id,
			"planned_qty": str(mo.planned_qty),
			"actual_qty_produced": str(mo.actual_qty_produced),
			"actual_qty_scrapped": str(mo.actual_qty_scrapped),
			"uom": mo.uom,
			"planned_material_cost_cents": mo.planned_material_cost_cents,
			"planned_labour_cost_cents": mo.planned_labour_cost_cents,
			"planned_overhead_cost_cents": mo.planned_overhead_cost_cents,
			"actual_cost_cents": mo.actual_cost_cents,
			"scheduled_start": mo.scheduled_start.isoformat() if mo.scheduled_start else None,
			"scheduled_end": mo.scheduled_end.isoformat() if mo.scheduled_end else None,
			"actual_start": mo.actual_start.isoformat() if mo.actual_start else None,
			"actual_end": mo.actual_end.isoformat() if mo.actual_end else None,
			"priority": mo.priority,
			"status": mo.status,
			"notes": mo.notes,
			"metadata": mo.metadata_,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.manufacturing.models import ManufacturingOrder
		from datetime import datetime as dt
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "product_id", "planned_qty")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		mo = ManufacturingOrder(
			tenant_id=data["tenant_id"],
			order_number=data.get("order_number") or f"MO-{dt.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
			product_id=data["product_id"],
			product_sku=data.get("product_sku"),
			bom_id=data.get("bom_id"),
			routing_id=data.get("routing_id"),
			work_center_id=data.get("work_center_id"),
			planned_qty=data["planned_qty"],
			uom=data.get("uom", "EA"),
			priority=int(data.get("priority", 50)),
			status="DRAFT",
			notes=data.get("notes"),
			scheduled_start=dt.fromisoformat(data["scheduled_start"]) if data.get("scheduled_start") else None,
			scheduled_end=dt.fromisoformat(data["scheduled_end"]) if data.get("scheduled_end") else None,
			planned_material_cost_cents=int(data.get("planned_material_cost_cents", 0)),
			planned_labour_cost_cents=int(data.get("planned_labour_cost_cents", 0)),
			planned_overhead_cost_cents=int(data.get("planned_overhead_cost_cents", 0)),
		)
		session.add(mo)
		session.commit()
		return jsonify({"ok": True, "id": mo.id, "order_number": mo.order_number}), 201

	@expose("/<string:order_id>/release", methods=["POST"])
	@has_access
	def release(self, order_id: str):
		from pgappforge.plugins.erp.industry.manufacturing.services import (
			ManufacturingService, ManufacturingServiceError,
		)
		session = _get_session()
		try:
			mo = ManufacturingService().release_order(order_id, session)
			session.commit()
			return jsonify({"ok": True, "status": mo.status, "order_number": mo.order_number})
		except ManufacturingServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:order_id>/complete", methods=["POST"])
	@has_access
	def complete(self, order_id: str):
		from decimal import Decimal
		from pgappforge.plugins.erp.industry.manufacturing.services import (
			ManufacturingService, ManufacturingServiceError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		actual_qty = data.get("actual_qty")
		if actual_qty is None:
			return jsonify({"ok": False, "error": "actual_qty required"}), 400
		scrap_qty = data.get("scrap_qty", "0")
		try:
			mo = ManufacturingService().complete_order(
				order_id, Decimal(str(actual_qty)), Decimal(str(scrap_qty)), session,
			)
			session.commit()
			return jsonify({
				"ok": True,
				"status": mo.status,
				"actual_qty_produced": str(mo.actual_qty_produced),
				"actual_qty_scrapped": str(mo.actual_qty_scrapped),
				"actual_cost_cents": mo.actual_cost_cents,
			})
		except ManufacturingServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:order_id>/bom")
	@has_access
	def bom(self, order_id: str):
		"""Proxy: return BOM detail for the MO's product."""
		from pgappforge.plugins.erp.industry.manufacturing.models import ManufacturingOrder
		session = _get_session()
		mo = session.get(ManufacturingOrder, order_id)
		if mo is None:
			abort(404)

		try:
			from pgappforge.plugins.erp.operations.production.models import BillOfMaterials, BOMLine
			bom_id = mo.bom_id
			if bom_id:
				bom = session.get(BillOfMaterials, bom_id)
			else:
				bom = session.execute(
					sa.select(BillOfMaterials).where(
						BillOfMaterials.product_id == mo.product_id,
						BillOfMaterials.status == "ACTIVE",
					).limit(1)
				).scalar_one_or_none()

			if bom is None:
				return jsonify({"ok": False, "error": "No active BOM found for this product"}), 404

			lines = session.execute(
				sa.select(BOMLine).where(BOMLine.bom_id == bom.id).order_by(BOMLine.position)
			).scalars().all()

			return jsonify({
				"bom_id": bom.id,
				"product_id": str(bom.product_id),
				"version": bom.version,
				"status": bom.status,
				"yield_pct": str(bom.yield_pct),
				"lines": [
					{
						"component_product_id": str(l.component_product_id),
						"quantity": str(l.quantity),
						"uom": l.uom,
						"position": l.position,
						"scrap_factor": str(l.scrap_factor),
						"is_critical": l.is_critical,
					}
					for l in lines
				],
			})
		except ImportError:
			return jsonify({"ok": False, "error": "Production plugin not loaded; BOM unavailable"}), 503


# ---------------------------------------------------------------------------
# WorkCenterView
# ---------------------------------------------------------------------------

class WorkCenterView(BaseView):
	"""Work Center CRUD.

	GET  /manufacturing/work-centers/        — list (code, name, capacity, active)
	GET  /manufacturing/work-centers/<id>    — detail
	POST /manufacturing/work-centers/        — create
	PUT  /manufacturing/work-centers/<id>    — update
	"""

	route_base = "/manufacturing/work-centers"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		# WorkCenter model lives in the operations/production plugin
		try:
			from pgappforge.plugins.erp.operations.production.models import WorkCenter
		except ImportError:
			return jsonify({"error": "Production plugin (WorkCenter) not loaded"}), 503

		session = _get_session()
		q = sa.select(WorkCenter).order_by(WorkCenter.code)
		if request.args.get("tenant_id"):
			q = q.where(WorkCenter.tenant_id == request.args["tenant_id"])
		if request.args.get("active") == "1":
			q = q.where(WorkCenter.is_active == True)  # noqa: E712

		wcs = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"work_centers": [
				{
					"id": w.id,
					"code": w.code,
					"name": w.name,
					"capacity_units_per_hour": str(w.capacity_units_per_hour),
					"overhead_rate_per_hour_cents": w.overhead_rate_per_hour_cents,
					"is_active": w.is_active,
				}
				for w in wcs
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(w.code)}</td>"
			f"<td>{_he(w.name)}</td>"
			f"<td class='text-right'>{_he(w.capacity_units_per_hour)}</td>"
			f"<td>{'<span class=\"label label-success\">Active</span>' if w.is_active else '<span class=\"label label-default\">Inactive</span>'}</td>"
			f"<td><a href='/manufacturing/work-centers/{_he(w.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for w in wcs
		)
		body = (
			'<h3>Work Centers</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Name</th><th>Capacity (units/hr)</th><th>Status</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Work Centers", body), 200)

	@expose("/<string:wc_id>")
	@has_access
	def detail(self, wc_id: str):
		try:
			from pgappforge.plugins.erp.operations.production.models import WorkCenter
		except ImportError:
			abort(503)
		session = _get_session()
		wc = session.get(WorkCenter, wc_id)
		if wc is None:
			abort(404)
		return jsonify({
			"id": wc.id,
			"tenant_id": wc.tenant_id,
			"code": wc.code,
			"name": wc.name,
			"description": wc.description,
			"capacity_units_per_hour": str(wc.capacity_units_per_hour),
			"overhead_rate_per_hour_cents": wc.overhead_rate_per_hour_cents,
			"gl_cost_center": wc.gl_cost_center,
			"is_active": wc.is_active,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		try:
			from pgappforge.plugins.erp.operations.production.models import WorkCenter
		except ImportError:
			return jsonify({"error": "Production plugin not loaded"}), 503
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
		try:
			from pgappforge.plugins.erp.operations.production.models import WorkCenter
		except ImportError:
			abort(503)
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
# OEEDashboardView
# ---------------------------------------------------------------------------

class OEEDashboardView(BaseView):
	"""OEE Dashboard — availability × performance × quality gauges and trends.

	GET /manufacturing/oee/                     — dashboard HTML
	GET /manufacturing/oee/data                 — JSON data for charts
	GET /manufacturing/oee/trend                — trend data (last N shifts)
	POST /manufacturing/oee/record              — record a new OEE snapshot
	"""

	route_base = "/manufacturing/oee"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		from pgappforge.plugins.erp.industry.manufacturing.models import OEESnapshot
		session = _get_session()

		# Last 20 snapshots across all work centers
		snapshots = session.execute(
			sa.select(OEESnapshot).order_by(sa.desc(OEESnapshot.shift_date), sa.desc(OEESnapshot.created_at)).limit(20)
		).scalars().all()

		def _oee_class(oee_val: float) -> str:
			if oee_val >= 0.85:
				return "oee-world-class"
			elif oee_val >= 0.65:
				return "oee-acceptable"
			return "oee-poor"

		cards = ""
		for snap in snapshots[:6]:  # top 6 as gauge cards
			oee_f = float(snap.oee_pct)
			avail_f = float(snap.availability_pct)
			perf_f = float(snap.performance_pct)
			qual_f = float(snap.quality_pct)
			cls = _oee_class(oee_f)
			cards += (
				f'<div class="col-md-4" style="margin-bottom:16px">'
				f'<div class="panel panel-default">'
				f'<div class="panel-heading"><b>{_he(snap.work_center_id)}</b> — {_he(snap.shift_date)} {_he(snap.shift_name)}</div>'
				f'<div class="panel-body text-center">'
				f'<div class="oee-gauge {cls}">{oee_f:.1%}</div>'
				f'<small>OEE</small>'
				f'<hr style="margin:8px 0">'
				f'<div class="row">'
				f'<div class="col-xs-4"><b>{avail_f:.1%}</b><br><small>Avail</small></div>'
				f'<div class="col-xs-4"><b>{perf_f:.1%}</b><br><small>Perf</small></div>'
				f'<div class="col-xs-4"><b>{qual_f:.1%}</b><br><small>Qual</small></div>'
				f'</div>'
				f'</div></div></div>'
			)

		trend_rows = "".join(
			f"<tr>"
			f"<td>{_he(s.shift_date)}</td>"
			f"<td>{_he(s.shift_name)}</td>"
			f"<td>{_he(s.work_center_id)}</td>"
			f"<td class='text-right {_oee_class(float(s.oee_pct))}'><b>{float(s.oee_pct):.1%}</b></td>"
			f"<td class='text-right'>{float(s.availability_pct):.1%}</td>"
			f"<td class='text-right'>{float(s.performance_pct):.1%}</td>"
			f"<td class='text-right'>{float(s.quality_pct):.1%}</td>"
			f"<td class='text-right'>{s.downtime_minutes}</td>"
			f"</tr>"
			for s in snapshots
		)

		body = (
			'<h3>OEE Dashboard <small>Overall Equipment Effectiveness</small></h3>'
			'<div class="row">' + cards + '</div>'
			'<h4>Recent Shifts</h4>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr>'
			'<th>Date</th><th>Shift</th><th>Work Center</th>'
			'<th>OEE</th><th>Availability</th><th>Performance</th><th>Quality</th><th>Downtime (min)</th>'
			'</tr></thead>'
			f'<tbody>{trend_rows}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">World-class OEE ≥ 85% | '
			f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("OEE Dashboard", body), 200)

	@expose("/data")
	@has_access
	def data(self):
		"""JSON OEE data for chart rendering."""
		from pgappforge.plugins.erp.industry.manufacturing.models import OEESnapshot
		session = _get_session()
		q = sa.select(OEESnapshot).order_by(sa.desc(OEESnapshot.shift_date)).limit(100)
		if request.args.get("work_center_id"):
			q = q.where(OEESnapshot.work_center_id == request.args["work_center_id"])
		if request.args.get("tenant_id"):
			q = q.where(OEESnapshot.tenant_id == request.args["tenant_id"])
		snaps = session.execute(q).scalars().all()
		return jsonify({"snapshots": [
			{
				"id": s.id,
				"work_center_id": s.work_center_id,
				"shift_date": s.shift_date.isoformat(),
				"shift_name": s.shift_name,
				"oee_pct": str(s.oee_pct),
				"availability_pct": str(s.availability_pct),
				"performance_pct": str(s.performance_pct),
				"quality_pct": str(s.quality_pct),
				"downtime_minutes": s.downtime_minutes,
				"planned_production_minutes": s.planned_production_minutes,
				"total_units_run": str(s.total_units_run),
				"good_units": str(s.good_units),
				"reject_qty": str(s.reject_qty),
			}
			for s in snaps
		]})

	@expose("/record", methods=["POST"])
	@has_access
	def record(self):
		"""Record a new OEE snapshot via the service."""
		from datetime import date as date_type
		from decimal import Decimal
		from pgappforge.plugins.erp.industry.manufacturing.services import (
			ManufacturingService, ManufacturingServiceError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("work_center_id", "shift_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			snap = ManufacturingService().calculate_oee(
				work_center_id=data["work_center_id"],
				shift_date=date_type.fromisoformat(data["shift_date"]),
				session=session,
				shift_name=data.get("shift_name", "MORNING"),
				planned_production_minutes=data.get("planned_production_minutes"),
				downtime_minutes=int(data.get("downtime_minutes", 0)),
				total_units_run=Decimal(str(data.get("total_units_run", 0))),
				good_units=Decimal(str(data.get("good_units", 0))),
				reject_qty=Decimal(str(data.get("reject_qty", 0))),
				ideal_cycle_time_seconds=data.get("ideal_cycle_time_seconds"),
				manufacturing_order_id=data.get("manufacturing_order_id"),
				tenant_id=data.get("tenant_id", ""),
			)
			session.commit()
			return jsonify({
				"ok": True,
				"id": snap.id,
				"oee_pct": str(snap.oee_pct),
				"availability_pct": str(snap.availability_pct),
				"performance_pct": str(snap.performance_pct),
				"quality_pct": str(snap.quality_pct),
			}), 201
		except (ManufacturingServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# MaintenanceWorkView
# ---------------------------------------------------------------------------

class MaintenanceWorkView(BaseView):
	"""Maintenance Work Order CRUD.

	GET  /manufacturing/maintenance/             — list
	GET  /manufacturing/maintenance/<id>         — detail
	POST /manufacturing/maintenance/             — create (schedule_maintenance)
	PUT  /manufacturing/maintenance/<id>/status  — update status
	"""

	route_base = "/manufacturing/maintenance"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.manufacturing.models import MaintenanceWork
		session = _get_session()
		q = sa.select(MaintenanceWork).order_by(
			MaintenanceWork.scheduled_date, MaintenanceWork.priority
		)
		for param, col in (
			("tenant_id", MaintenanceWork.tenant_id),
			("asset_id", MaintenanceWork.asset_id),
			("status", MaintenanceWork.status),
			("maintenance_type", MaintenanceWork.maintenance_type),
			("priority", MaintenanceWork.priority),
		):
			val = request.args.get(param)
			if val:
				q = q.where(col == val)

		works = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"maintenance_work_orders": [
				{
					"id": w.id,
					"work_order_number": w.work_order_number,
					"asset_id": w.asset_id,
					"asset_tag": w.asset_tag,
					"maintenance_type": w.maintenance_type,
					"priority": w.priority,
					"status": w.status,
					"scheduled_date": w.scheduled_date.isoformat() if w.scheduled_date else None,
					"assigned_technician_id": w.assigned_technician_id,
					"estimated_cost_cents": w.estimated_cost_cents,
					"actual_total_cost_cents": w.actual_total_cost_cents,
					"downtime_minutes": w.downtime_minutes,
				}
				for w in works
			]})

		rows = "".join(
			f"<tr>"
			f"<td><a href='/manufacturing/maintenance/{_he(w.id)}'>{_he(w.work_order_number)}</a></td>"
			f"<td>{_he(w.asset_tag or w.asset_id)}</td>"
			f"<td>{_he(w.maintenance_type)}</td>"
			f"<td>{_maint_priority_label(w.priority)}</td>"
			f"<td>{_he(w.scheduled_date or '—')}</td>"
			f"<td>{_status_label(w.status)}</td>"
			f"<td>{_he(w.assigned_technician_id or '—')}</td>"
			f"<td class='text-right'>{w.estimated_cost_cents / 100:,.2f}</td>"
			f"</tr>"
			for w in works
		)
		body = (
			'<h3>Maintenance Work Orders</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr>'
			'<th>WO #</th><th>Asset</th><th>Type</th><th>Priority</th>'
			'<th>Scheduled</th><th>Status</th><th>Technician</th><th>Est. Cost</th>'
			'</tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">'
			f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Maintenance Work Orders", body), 200)

	@expose("/<string:work_id>")
	@has_access
	def detail(self, work_id: str):
		from pgappforge.plugins.erp.industry.manufacturing.models import MaintenanceWork
		session = _get_session()
		work = session.get(MaintenanceWork, work_id)
		if work is None:
			abort(404)
		return jsonify({
			"id": work.id,
			"tenant_id": work.tenant_id,
			"work_order_number": work.work_order_number,
			"asset_id": work.asset_id,
			"asset_tag": work.asset_tag,
			"assigned_technician_id": work.assigned_technician_id,
			"maintenance_type": work.maintenance_type,
			"priority": work.priority,
			"description": work.description,
			"root_cause": work.root_cause,
			"requested_date": work.requested_date.isoformat() if work.requested_date else None,
			"scheduled_date": work.scheduled_date.isoformat() if work.scheduled_date else None,
			"completed_date": work.completed_date.isoformat() if work.completed_date else None,
			"downtime_minutes": work.downtime_minutes,
			"estimated_cost_cents": work.estimated_cost_cents,
			"labour_cost_cents": work.labour_cost_cents,
			"parts_cost_cents": work.parts_cost_cents,
			"overhead_cost_cents": work.overhead_cost_cents,
			"actual_total_cost_cents": work.actual_total_cost_cents,
			"status": work.status,
			"parts_used": work.parts_used,
			"attachments": work.attachments,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from datetime import date as date_type
		from pgappforge.plugins.erp.industry.manufacturing.services import (
			ManufacturingService, ManufacturingServiceError,
		)
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("asset_id", "maintenance_type", "due_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			work = ManufacturingService().schedule_maintenance(
				asset_id=data["asset_id"],
				maintenance_type=data["maintenance_type"],
				due_date=date_type.fromisoformat(data["due_date"]),
				session=session,
				description=data.get("description", ""),
				priority=data.get("priority", "MEDIUM"),
				assigned_technician_id=data.get("assigned_technician_id"),
				estimated_cost_cents=int(data.get("estimated_cost_cents", 0)),
				tenant_id=data.get("tenant_id", ""),
			)
			session.commit()
			return jsonify({
				"ok": True,
				"id": work.id,
				"work_order_number": work.work_order_number,
			}), 201
		except (ManufacturingServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:work_id>/status", methods=["PUT"])
	@has_access
	def update_status(self, work_id: str):
		from pgappforge.plugins.erp.industry.manufacturing.models import MaintenanceWork
		session = _get_session()
		work = session.get(MaintenanceWork, work_id)
		if work is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		new_status = data.get("status")
		valid = {"OPEN", "ASSIGNED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED"}
		if new_status not in valid:
			return jsonify({"ok": False, "error": f"status must be one of {valid}"}), 400
		work.status = new_status
		if new_status == "COMPLETED":
			from datetime import date as date_type
			work.completed_date = date_type.today()
			if data.get("root_cause"):
				work.root_cause = data["root_cause"]
		work.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": work.status})


# ---------------------------------------------------------------------------
# ProductionScheduleView
# ---------------------------------------------------------------------------

class ProductionScheduleView(BaseView):
	"""Production Schedule — Gantt-style capacity view.

	GET /manufacturing/schedule/             — Gantt HTML view
	GET /manufacturing/schedule/data         — JSON schedule data
	GET /manufacturing/schedule/mrp          — run MRP for a product
	"""

	route_base = "/manufacturing/schedule"
	default_view = "gantt"

	@expose("/")
	@has_access
	def gantt(self):
		from datetime import date as date_type, timedelta
		from pgappforge.plugins.erp.industry.manufacturing.services import ManufacturingService
		session = _get_session()

		start_str = request.args.get("start")
		end_str = request.args.get("end")
		today = date_type.today()
		start_date = date_type.fromisoformat(start_str) if start_str else today
		end_date = date_type.fromisoformat(end_str) if end_str else today + timedelta(days=14)
		tenant_id = request.args.get("tenant_id", "")

		schedule = ManufacturingService().get_production_schedule(
			start_date, end_date, session, tenant_id=tenant_id,
		)

		# Group by work center
		from collections import defaultdict
		by_wc: dict[str, list[dict]] = defaultdict(list)
		for entry in schedule:
			by_wc[entry["work_center_id"]].append(entry)

		# Gantt HTML: one row per work center, bars proportional to run_minutes
		total_minutes = max((end_date - start_date).days * 480, 480)  # 8h/day
		gantt_rows = ""
		for wc_id, entries in sorted(by_wc.items()):
			cells = ""
			for e in entries:
				bar_pct = min(100, max(1, (e["run_minutes"] + e["setup_minutes"]) / total_minutes * 100))
				conflict_cls = " gantt-conflict" if e["conflict_flag"] else ""
				e_order = _he(e["order_number"])
				e_op = _he(e["operation_name"] or "")
				e_start = _he(e["slot_start"][:16])
				e_run = e["run_minutes"]
				e_conflict_txt = "⚠ CONFLICT" if e["conflict_flag"] else ""
				cells += (
					f'<span class="gantt-bar{conflict_cls}" style="width:{bar_pct:.1f}%" '
					f'title="{e_order} | {e_op} | start:{e_start} | run:{e_run}min | {e_conflict_txt}">'
					f'&nbsp;</span> '
				)
			gantt_rows += (
				f"<tr>"
				f"<td style='white-space:nowrap;width:200px'>{_he(wc_id[:20])}</td>"
				f"<td>{cells or '<em style=\"color:#aaa\">—</em>'}</td>"
				f"<td class='text-right'>{len(entries)}</td>"
				f"</tr>"
			)

		nav = (
			f'<form method="get" class="form-inline noprint" style="margin-bottom:16px">'
			f'<label>From: <input type="date" name="start" value="{start_date}" class="form-control input-sm"></label>'
			f'&nbsp;<label>To: <input type="date" name="end" value="{end_date}" class="form-control input-sm"></label>'
			f'&nbsp;<button class="btn btn-sm btn-default">Refresh</button>'
			f'&nbsp;<a href="/manufacturing/schedule/data?start={start_date}&end={end_date}" class="btn btn-sm btn-default">JSON</a>'
			f'</form>'
		)
		body = (
			f'<h3>Production Schedule <small>{start_date} → {end_date}</small></h3>'
			+ nav +
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Work Center</th><th>Schedule (proportional)</th><th>Slots</th></tr></thead>'
			f'<tbody>{gantt_rows or "<tr><td colspan=3 class=text-center><em>No schedule entries</em></td></tr>"}</tbody></table>'
			'<p><span class="gantt-bar" style="width:20px">&nbsp;</span> Normal &nbsp;'
			'<span class="gantt-bar gantt-conflict" style="width:20px">&nbsp;</span> Conflict</p>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Production Schedule", body), 200)

	@expose("/data")
	@has_access
	def data(self):
		"""JSON schedule data."""
		from datetime import date as date_type, timedelta
		from pgappforge.plugins.erp.industry.manufacturing.services import ManufacturingService
		session = _get_session()
		today = date_type.today()
		start_str = request.args.get("start")
		end_str = request.args.get("end")
		start_date = date_type.fromisoformat(start_str) if start_str else today
		end_date = date_type.fromisoformat(end_str) if end_str else today + timedelta(days=14)
		tenant_id = request.args.get("tenant_id", "")
		schedule = ManufacturingService().get_production_schedule(
			start_date, end_date, session, tenant_id=tenant_id,
		)
		return jsonify({"schedule": schedule, "count": len(schedule)})

	@expose("/mrp")
	@has_access
	def mrp(self):
		"""Run MRP explosion for a product+qty+date."""
		from datetime import date as date_type, timedelta
		from decimal import Decimal
		from pgappforge.plugins.erp.industry.manufacturing.services import (
			ManufacturingService, ManufacturingServiceError,
		)
		session = _get_session()
		product_id = request.args.get("product_id")
		required_qty = request.args.get("required_qty", "1")
		required_date_str = request.args.get("required_date")
		if not product_id:
			return jsonify({"ok": False, "error": "product_id required"}), 400
		required_date = (
			date_type.fromisoformat(required_date_str)
			if required_date_str
			else date_type.today() + timedelta(days=30)
		)
		try:
			planned = ManufacturingService().run_mrp(
				product_id=product_id,
				required_qty=Decimal(required_qty),
				required_date=required_date,
				session=session,
				tenant_id=request.args.get("tenant_id", ""),
			)
			return jsonify({"planned_orders": planned, "count": len(planned)})
		except (ManufacturingServiceError, AssertionError) as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


__all__ = [
	"ManufacturingOrderView",
	"WorkCenterView",
	"OEEDashboardView",
	"MaintenanceWorkView",
	"ProductionScheduleView",
]
