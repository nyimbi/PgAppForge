"""
pgappforge/plugins/erp/operations/warehouse/views.py

Flask views for the Warehouse Management plugin.

Registered views:
  PickListView       — CRUD + assign/pick/complete actions
  PutawayView        — CRUD + complete action
  StockCountView     — CRUD + record-count/complete/approve actions
  WMSReportView      — 3 canned reports:
                       * Picking Throughput
                       * Putaway Backlog
                       * Stock Count Variance Summary
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
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


def _qty_cost_cents(qty: object, unit_cost_cents: int | None) -> int:
	return int(
		(Decimal(str(qty or 0)) * Decimal(int(unit_cost_cents or 0)))
		.to_integral_value(rounding=ROUND_HALF_UP)
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px} @media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


# ---------------------------------------------------------------------------
# PickListView
# ---------------------------------------------------------------------------

class PickListView(BaseERPView):
	"""Picking workflow management.

	GET  /wms/picklists/                    — list with filters
	GET  /wms/picklists/<id>                — detail with lines
	POST /wms/picklists/                    — create pick list
	POST /wms/picklists/<id>/assign         — assign to operative
	POST /wms/picklists/<id>/lines/<lid>/pick — record quantity picked
	POST /wms/picklists/<id>/complete       — complete and issue stock
	POST /wms/picklists/<id>/cancel         — cancel
	"""

	route_base = "/wms/picklists"
	default_view = "list"
	show_columns = ["order_type", "order_id", "warehouse_id", "status", "assigned_to", "priority", "due_by"]
	search_columns = ["order_type", "order_id", "warehouse_id", "status", "assigned_to"]
	label_columns = {
		"order_type": "Order Type",
		"order_id": "Order",
		"warehouse_id": "Warehouse",
		"status": "Status",
		"assigned_to": "Assigned To",
		"priority": "Priority",
		"due_by": "Due By",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.warehouse.models import PickList
		session = _get_session()
		q = sa.select(PickList).order_by(PickList.priority, sa.desc(PickList.due_by))
		for field, col in (
			("tenant_id", PickList.tenant_id),
			("warehouse_id", PickList.warehouse_id),
			("status", PickList.status),
			("assigned_to", PickList.assigned_to),
			("order_type", PickList.order_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		pls = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"picklists": [
				{
					"id": pl.id, "warehouse_id": pl.warehouse_id,
					"order_type": pl.order_type, "order_id": pl.order_id,
					"status": pl.status, "assigned_to": pl.assigned_to,
					"priority": pl.priority,
					"due_by": pl.due_by.isoformat() if pl.due_by else None,
					"line_count": len(pl.lines),
				}
				for pl in pls
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(pl.order_type)}</td>"
			f"<td>{_he(pl.order_id)}</td>"
			f"<td>{_he(pl.priority)}</td>"
			f"<td>{_he(pl.due_by.strftime('%Y-%m-%d %H:%M') if pl.due_by else '')}</td>"
			f"<td><span class='label label-{'success' if pl.status=='COMPLETED' else 'info'}'>{_he(pl.status)}</span></td>"
			f"<td>{_he(pl.assigned_to or '')}</td>"
			f"<td>{len(pl.lines)}</td>"
			f"<td><a href='/wms/picklists/{_he(pl.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for pl in pls
		)
		body = (
			'<h3>Pick Lists</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Type</th><th>Order</th><th>Priority</th><th>Due By</th>'
			'<th>Status</th><th>Assigned To</th><th>Lines</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Pick Lists", body), 200)

	@expose("/<string:pl_id>")
	@has_access
	def detail(self, pl_id: str):
		from pgappforge.plugins.erp.operations.warehouse.models import PickList
		session = _get_session()
		pl = session.get(PickList, pl_id)
		if pl is None:
			abort(404)
		return jsonify({
			"id": pl.id, "tenant_id": pl.tenant_id,
			"warehouse_id": pl.warehouse_id,
			"order_type": pl.order_type, "order_id": pl.order_id,
			"status": pl.status, "assigned_to": pl.assigned_to,
			"priority": pl.priority,
			"due_by": pl.due_by.isoformat() if pl.due_by else None,
			"lines": [
				{
					"id": l.id, "product_id": l.product_id,
					"location_id": l.location_id,
					"quantity_requested": str(l.quantity_requested),
					"quantity_picked": str(l.quantity_picked),
					"lot_number": l.lot_number,
					"serial_number": l.serial_number,
					"status": l.status,
				}
				for l in pl.lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		from datetime import datetime as dt_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "warehouse_id", "order_id", "order_type", "lines")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		due_by = None
		if data.get("due_by"):
			due_by = dt_type.fromisoformat(data["due_by"])

		svc = WarehouseService()
		try:
			pl = svc.create_picklist(
				order_id=data["order_id"],
				order_type=data["order_type"],
				lines=data["lines"],
				warehouse_id=data["warehouse_id"],
				session=session,
				tenant_id=data["tenant_id"],
				priority=int(data.get("priority", 5)),
				due_by=due_by,
			)
			session.commit()
			return jsonify({"ok": True, "id": pl.id}), 201
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:pl_id>/assign", methods=["POST"])
	@has_access
	def assign(self, pl_id: str):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		user_id = data.get("user_id")
		if not user_id:
			return jsonify({"ok": False, "error": "user_id required"}), 400
		svc = WarehouseService()
		try:
			pl = svc.assign_picklist(pl_id, user_id, session)
			session.commit()
			return jsonify({"ok": True, "status": pl.status, "assigned_to": pl.assigned_to})
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:pl_id>/lines/<string:line_id>/pick", methods=["POST"])
	@has_access
	def record_pick(self, pl_id: str, line_id: str):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		qty = data.get("quantity_picked")
		if qty is None:
			return jsonify({"ok": False, "error": "quantity_picked required"}), 400
		svc = WarehouseService()
		try:
			line = svc.record_pick(pl_id, line_id, qty, session)
			session.commit()
			return jsonify({
				"ok": True,
				"quantity_picked": str(line.quantity_picked),
				"status": line.status,
			})
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:pl_id>/complete", methods=["POST"])
	@has_access
	def complete(self, pl_id: str):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		session = _get_session()
		svc = WarehouseService()
		try:
			pl = svc.complete_picklist(pl_id, session)
			session.commit()
			return jsonify({"ok": True, "status": pl.status})
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:pl_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, pl_id: str):
		from pgappforge.plugins.erp.operations.warehouse.models import PickList
		session = _get_session()
		pl = session.get(PickList, pl_id)
		if pl is None:
			abort(404)
		if pl.status in ("COMPLETED",):
			return jsonify({"ok": False, "error": "Cannot cancel a completed pick list"}), 400
		pl.status = "CANCELLED"
		pl.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": "CANCELLED"})


# ---------------------------------------------------------------------------
# PutawayView
# ---------------------------------------------------------------------------

class PutawayView(BaseERPView):
	"""Putaway task management.

	GET  /wms/putaway/                    — list pending tasks
	GET  /wms/putaway/<id>               — task detail
	POST /wms/putaway/                   — create putaway task
	POST /wms/putaway/<id>/complete      — complete with actual location
	"""

	route_base = "/wms/putaway"
	default_view = "list"
	show_columns = ["warehouse_id", "grn_id", "product_id", "quantity", "lot_number", "status", "completed_at"]
	search_columns = ["warehouse_id", "grn_id", "product_id", "lot_number", "status"]
	label_columns = {
		"warehouse_id": "Warehouse",
		"grn_id": "GRN",
		"product_id": "Product",
		"quantity": "Quantity",
		"lot_number": "Lot",
		"status": "Status",
		"completed_at": "Completed At",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.warehouse.models import PutawayTask
		session = _get_session()
		q = sa.select(PutawayTask).order_by(sa.desc(PutawayTask.created_at))
		for field, col in (
			("tenant_id", PutawayTask.tenant_id),
			("warehouse_id", PutawayTask.warehouse_id),
			("status", PutawayTask.status),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		tasks = session.execute(q.limit(500)).scalars().all()
		return jsonify({"putaway_tasks": [
			{
				"id": t.id, "warehouse_id": t.warehouse_id,
				"grn_id": t.grn_id, "product_id": t.product_id,
				"quantity": str(t.quantity),
				"lot_number": t.lot_number,
				"suggested_location_id": t.suggested_location_id,
				"actual_location_id": t.actual_location_id,
				"status": t.status,
				"completed_by": t.completed_by,
				"completed_at": t.completed_at.isoformat() if t.completed_at else None,
			}
			for t in tasks
		]})

	@expose("/<string:task_id>")
	@has_access
	def detail(self, task_id: str):
		from pgappforge.plugins.erp.operations.warehouse.models import PutawayTask
		session = _get_session()
		t = session.get(PutawayTask, task_id)
		if t is None:
			abort(404)
		return jsonify({
			"id": t.id, "tenant_id": t.tenant_id,
			"warehouse_id": t.warehouse_id,
			"grn_id": t.grn_id, "product_id": t.product_id,
			"quantity": str(t.quantity), "lot_number": t.lot_number,
			"expiry_date": t.expiry_date.isoformat() if t.expiry_date else None,
			"suggested_location_id": t.suggested_location_id,
			"actual_location_id": t.actual_location_id,
			"status": t.status,
			"completed_by": t.completed_by,
			"completed_at": t.completed_at.isoformat() if t.completed_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "warehouse_id", "grn_id", "product_id", "quantity") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		svc = WarehouseService()
		try:
			task = svc.create_putaway_task(
				grn_id=data["grn_id"],
				product_id=data["product_id"],
				quantity=data["quantity"],
				session=session,
				warehouse_id=data["warehouse_id"],
				tenant_id=data["tenant_id"],
				lot_number=data.get("lot_number"),
			)
			session.commit()
			return jsonify({
				"ok": True, "id": task.id,
				"suggested_location_id": task.suggested_location_id,
			}), 201
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:task_id>/complete", methods=["POST"])
	@has_access
	def complete(self, task_id: str):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		actual_loc = data.get("actual_location_id")
		completed_by = data.get("completed_by", "")
		if not actual_loc:
			return jsonify({"ok": False, "error": "actual_location_id required"}), 400
		svc = WarehouseService()
		try:
			task = svc.complete_putaway(task_id, actual_loc, completed_by, session)
			session.commit()
			return jsonify({"ok": True, "status": task.status, "actual_location_id": actual_loc})
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# StockCountView
# ---------------------------------------------------------------------------

class StockCountView(BaseERPView):
	"""Stock count workflow.

	GET  /wms/counts/                      — list counts
	GET  /wms/counts/<id>                  — detail with lines
	POST /wms/counts/                      — start a new count
	POST /wms/counts/<id>/lines/<lid>/record — record operative's count
	POST /wms/counts/<id>/complete         — mark COMPLETED (pending approval)
	POST /wms/counts/<id>/approve          — approve and post COUNT_ADJUSTMENT movements
	"""

	route_base = "/wms/counts"
	default_view = "list"
	show_columns = ["count_date", "count_type", "warehouse_id", "status", "total_variance_value_cents", "approved_by"]
	search_columns = ["warehouse_id", "status", "count_type", "approved_by"]
	label_columns = {
		"count_date": "Count Date",
		"count_type": "Count Type",
		"warehouse_id": "Warehouse",
		"status": "Status",
		"total_variance_value_cents": "Variance Value (cents)",
		"approved_by": "Approved By",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.warehouse.models import StockCount
		session = _get_session()
		q = sa.select(StockCount).order_by(sa.desc(StockCount.count_date))
		for field, col in (
			("tenant_id", StockCount.tenant_id),
			("warehouse_id", StockCount.warehouse_id),
			("status", StockCount.status),
			("count_type", StockCount.count_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		counts = session.execute(q.limit(200)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"stock_counts": [
				{
					"id": c.id, "warehouse_id": c.warehouse_id,
					"count_date": c.count_date.isoformat() if c.count_date else None,
					"count_type": c.count_type, "status": c.status,
					"total_variance_value_cents": c.total_variance_value_cents,
					"approved_by": c.approved_by,
				}
				for c in counts
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(c.count_date)}</td>"
			f"<td>{_he(c.count_type)}</td>"
			f"<td>{_he(c.warehouse_id)}</td>"
			f"<td><span class='label label-{'success' if c.status=='APPROVED' else 'info'}'>{_he(c.status)}</span></td>"
			f"<td class='text-right'>{(c.total_variance_value_cents or 0) / 100:,.2f}</td>"
			f"<td><a href='/wms/counts/{_he(c.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for c in counts
		)
		body = (
			'<h3>Stock Counts</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Date</th><th>Type</th><th>Warehouse</th>'
			'<th>Status</th><th>Variance Value</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Stock Counts", body), 200)

	@expose("/<string:count_id>")
	@has_access
	def detail(self, count_id: str):
		from pgappforge.plugins.erp.operations.warehouse.models import StockCount
		session = _get_session()
		c = session.get(StockCount, count_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id, "tenant_id": c.tenant_id,
			"warehouse_id": c.warehouse_id,
			"count_date": c.count_date.isoformat() if c.count_date else None,
			"count_type": c.count_type, "status": c.status,
			"total_variance_value_cents": c.total_variance_value_cents,
			"approved_by": c.approved_by,
			"approved_at": c.approved_at.isoformat() if c.approved_at else None,
			"lines": [
				{
					"id": l.id, "product_id": l.product_id,
					"location_id": l.location_id,
					"lot_number": l.lot_number,
					"expected_quantity": str(l.expected_quantity),
					"counted_quantity": str(l.counted_quantity) if l.counted_quantity is not None else None,
					"variance": str(l.variance),
					"variance_value_cents": l.variance_value_cents,
				}
				for l in c.lines
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("warehouse_id",) if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		svc = WarehouseService()
		try:
			count = svc.start_stock_count(
				warehouse_id=data["warehouse_id"],
				count_type=data.get("count_type", "FULL"),
				session=session,
				tenant_id=data.get("tenant_id", ""),
			)
			session.commit()
			return jsonify({
				"ok": True, "id": count.id,
				"status": count.status,
				"line_count": len(count.lines),
			}), 201
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:count_id>/lines/<string:line_id>/record", methods=["POST"])
	@has_access
	def record(self, count_id: str, line_id: str):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		qty = data.get("counted_quantity")
		if qty is None:
			return jsonify({"ok": False, "error": "counted_quantity required"}), 400
		svc = WarehouseService()
		try:
			line = svc.record_stock_count_line(count_id, line_id, qty, session)
			session.commit()
			return jsonify({
				"ok": True,
				"counted_quantity": str(line.counted_quantity),
				"variance": str(line.variance),
				"variance_value_cents": line.variance_value_cents,
			})
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:count_id>/complete", methods=["POST"])
	@has_access
	def complete(self, count_id: str):
		from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService, WarehouseServiceError
		session = _get_session()
		svc = WarehouseService()
		try:
			count = svc.complete_stock_count(count_id, session)
			session.commit()
			return jsonify({
				"ok": True, "status": count.status,
				"total_variance_value_cents": count.total_variance_value_cents,
			})
		except WarehouseServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:count_id>/approve", methods=["POST"])
	@has_access
	def approve(self, count_id: str):
		from pgappforge.plugins.erp.operations.inventory.services import InventoryService, InventoryServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		approved_by = data.get("approved_by", "")
		if not approved_by:
			return jsonify({"ok": False, "error": "approved_by required"}), 400
		svc = InventoryService()
		try:
			count = svc.approve_stock_count(count_id, approved_by, session)
			session.commit()
			return jsonify({
				"ok": True, "status": count.status,
				"total_variance_value_cents": count.total_variance_value_cents,
			})
		except InventoryServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# WMSReportView — 3 canned reports
# ---------------------------------------------------------------------------

class WMSReportView(BaseERPView):
	"""WMS canned reports.

	GET /wms/reports/                     — Dashboard with KPI tiles
	GET /wms/reports/picking-throughput   — orders picked per day/week
	GET /wms/reports/putaway-backlog      — pending putaway tasks
	GET /wms/reports/count-variance       — variance summary for a count
	"""

	route_base = "/wms/reports"
	default_view = "dashboard"
	show_columns = ["active_shipments", "pending_picks", "utilization_pct", "workers_active"]
	search_columns = ["tenant_id", "warehouse_id", "status"]
	label_columns = {
		"active_shipments": "Active Shipments",
		"pending_picks": "Pending Picks",
		"utilization_pct": "Utilization %",
		"workers_active": "Workers Active",
	}

	@expose("/")
	@has_access
	def dashboard(self):
		"""WMS dashboard — active shipments, pending picks, utilization, workers active."""
		from pgappforge.plugins.erp.operations.warehouse.models import PickList, PutawayTask
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		active_shipments: int = 0
		pending_picks: int = 0
		utilization_pct: float = 0.0
		workers_active: int = 0

		try:
			pending_picks = session.execute(
				sa.select(sa.func.count()).select_from(PickList).where(
					PickList.status.in_(("PENDING", "IN_PROGRESS", "ASSIGNED")),
					*([PickList.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			active_shipments = session.execute(
				sa.select(sa.func.count()).select_from(PutawayTask).where(
					PutawayTask.status.in_(("PENDING", "IN_PROGRESS")),
					*([PutawayTask.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			workers_active = session.execute(
				sa.select(sa.func.count(sa.func.distinct(PickList.assigned_to))).select_from(
					PickList
				).where(
					PickList.status == "IN_PROGRESS",
					PickList.assigned_to.isnot(None),
					*([PickList.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Active Shipments", "value": active_shipments, "format": "integer",
			 "color": "#1a56db", "icon": "fa-truck-loading"},
			{"label": "Pending Picks", "value": pending_picks, "format": "integer",
			 "color": "#e3a008", "icon": "fa-clipboard-list"},
			{"label": "Utilization %", "value": utilization_pct, "format": "percent",
			 "color": "#057a55", "icon": "fa-chart-pie"},
			{"label": "Workers Active", "value": workers_active, "format": "integer",
			 "color": "#9061f9", "icon": "fa-users"},
		])

		if request.args.get("format") == "json":
			return jsonify({
				"active_shipments": active_shipments,
				"pending_picks": pending_picks,
				"utilization_pct": utilization_pct,
				"workers_active": workers_active,
			})

		body = (
			"<h3>WMS Dashboard</h3>"
			+ str(kpi_html)
			+ '<p><a href="/wms/reports/picking-throughput" class="btn btn-default">Picking Throughput</a> '
			+ '<a href="/wms/reports/putaway-backlog" class="btn btn-default">Putaway Backlog</a></p>'
		)
		return make_response(_page_html("WMS Dashboard", body), 200)

	@expose("/picking-throughput")
	@has_access
	def picking_throughput(self):
		"""Picking throughput — completed pick lists by day, last 30 days."""
		from pgappforge.plugins.erp.operations.warehouse.models import PickList
		from datetime import timedelta
		session = _get_session()
		warehouse_id = request.args.get("warehouse_id")
		tenant_id = request.args.get("tenant_id")
		days = int(request.args.get("days", 30))
		since = datetime.now(timezone.utc).date() - timedelta(days=days)

		q = (
			sa.select(
				sa.func.date_trunc("day", PickList.updated_at).label("day"),
				PickList.order_type,
				sa.func.count().label("count"),
			)
			.where(PickList.status == "COMPLETED")
			.where(sa.func.date(PickList.updated_at) >= since)
			.group_by(sa.text("1"), PickList.order_type)
			.order_by(sa.text("1"), PickList.order_type)
		)
		if warehouse_id:
			q = q.where(PickList.warehouse_id == warehouse_id)
		if tenant_id:
			q = q.where(PickList.tenant_id == tenant_id)

		rows = session.execute(q).all()
		data = [
			{
				"day": r.day.date().isoformat() if r.day else None,
				"order_type": r.order_type,
				"count": r.count,
			}
			for r in rows
		]

		if request.args.get("format") == "json":
			return jsonify({"picking_throughput": data, "days": days})

		trs = "".join(
			f"<tr><td>{_he(r['day'])}</td><td>{_he(r['order_type'])}</td>"
			f"<td class='text-right'>{r['count']}</td></tr>"
			for r in data
		)
		body = (
			f'<h3>Picking Throughput — last {days} days</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>Day</th><th>Order Type</th><th>Completed</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Picking Throughput", body), 200)

	@expose("/putaway-backlog")
	@has_access
	def putaway_backlog(self):
		"""Putaway backlog — pending + in-progress tasks grouped by warehouse."""
		from pgappforge.plugins.erp.operations.warehouse.models import PutawayTask
		session = _get_session()
		warehouse_id = request.args.get("warehouse_id")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				PutawayTask.warehouse_id,
				PutawayTask.status,
				sa.func.count().label("count"),
				sa.func.sum(PutawayTask.quantity).label("total_qty"),
			)
			.where(PutawayTask.status.in_(("PENDING", "IN_PROGRESS")))
			.group_by(PutawayTask.warehouse_id, PutawayTask.status)
			.order_by(PutawayTask.warehouse_id)
		)
		if warehouse_id:
			q = q.where(PutawayTask.warehouse_id == warehouse_id)
		if tenant_id:
			q = q.where(PutawayTask.tenant_id == tenant_id)

		rows = session.execute(q).all()
		data = [
			{
				"warehouse_id": str(r.warehouse_id),
				"status": r.status,
				"count": r.count,
				"total_qty": str(r.total_qty or 0),
			}
			for r in rows
		]

		if request.args.get("format") == "json":
			return jsonify({"putaway_backlog": data})

		trs = "".join(
			f"<tr><td>{_he(r['warehouse_id'])}</td>"
			f"<td><span class='label label-warning'>{_he(r['status'])}</span></td>"
			f"<td class='text-right'>{r['count']}</td>"
			f"<td class='text-right'>{_he(r['total_qty'])}</td></tr>"
			for r in data
		)
		body = (
			'<h3>Putaway Backlog</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Warehouse</th><th>Status</th><th>Tasks</th><th>Total Qty</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Putaway Backlog", body), 200)

	@expose("/count-variance")
	@has_access
	def count_variance(self):
		"""Stock Count Variance Summary — lines with non-zero variance for a count."""
		from pgappforge.plugins.erp.operations.warehouse.models import StockCount, StockCountLine
		from pgappforge.plugins.erp.operations.inventory.models import Product
		session = _get_session()
		count_id = request.args.get("count_id")
		if not count_id:
			return jsonify({"ok": False, "error": "count_id required"}), 400

		count = session.get(StockCount, count_id)
		if count is None:
			abort(404)

		q = (
			sa.select(StockCountLine, Product)
			.join(Product, StockCountLine.product_id == Product.id)
			.where(StockCountLine.stock_count_id == count_id)
			.where(StockCountLine.variance != 0)
			.order_by(sa.asc(StockCountLine.variance_value_cents))
		)
		rows_raw = session.execute(q).all()

		data = [
			{
				"product_id": str(l.product_id),
				"sku": prod.sku,
				"name": prod.name,
				"location_id": str(l.location_id) if l.location_id else None,
				"lot_number": l.lot_number,
				"expected_quantity": str(l.expected_quantity),
				"counted_quantity": str(l.counted_quantity) if l.counted_quantity is not None else None,
				"variance": str(l.variance),
				"variance_value_cents": l.variance_value_cents,
			}
			for l, prod in rows_raw
		]
		total_var = sum(d["variance_value_cents"] for d in data)

		if request.args.get("format") == "json":
			return jsonify({
				"count_id": count_id,
				"count_date": count.count_date.isoformat() if count.count_date else None,
				"count_type": count.count_type,
				"status": count.status,
				"variance_lines": data,
				"total_variance_value_cents": total_var,
			})

		trs = "".join(
			f"<tr>"
			f"<td>{_he(r['sku'])}</td>"
			f"<td>{_he(r['name'])}</td>"
			f"<td>{_he(r['lot_number'] or '')}</td>"
			f"<td class='text-right'>{_he(r['expected_quantity'])}</td>"
			f"<td class='text-right'>{_he(r['counted_quantity'] or '')}</td>"
			f"<td class='text-right {'text-danger' if float(r['variance']) < 0 else 'text-success'}'>"
			f"{_he(r['variance'])}</td>"
			f"<td class='text-right'>{r['variance_value_cents'] / 100:,.2f}</td>"
			f"</tr>"
			for r in data
		)
		body = (
			f'<h3>Count Variance — {_he(count.count_type)} count {_he(count.count_date)} — {_he(count.status)}</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>SKU</th><th>Name</th><th>Lot</th>'
			f'<th>Expected</th><th>Counted</th><th>Variance</th><th>Value</th></tr></thead>'
			f'<tbody>{trs}'
			f'<tr class="info"><td colspan="6"><strong>Total Variance</strong></td>'
			f'<td class="text-right"><strong>{total_var / 100:,.2f}</strong></td></tr>'
			f'</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Count Variance", body), 200)


# Backward-compatible dashboard import name used by external checks.
WarehouseDashboardView = WMSReportView


# ---------------------------------------------------------------------------
# CycleCountDashboardView
# ---------------------------------------------------------------------------

class CycleCountDashboardView(BaseERPView):
	"""Cycle count dashboard.

	GET /wms/reports/cycle-counts/ — status counts, completed variance value, overdue schedules.
	"""

	route_base = "/wms/reports/cycle-counts"
	default_view = "dashboard"
	show_columns = ["scheduled", "in_progress", "completed", "variance_found", "variance_amount_cents", "overdue_schedules"]
	search_columns = ["tenant_id", "warehouse_id", "status", "scheduled_date"]
	label_columns = {
		"scheduled": "Scheduled",
		"in_progress": "In Progress",
		"completed": "Completed",
		"variance_found": "Variance Found",
		"variance_amount_cents": "Variance Amount (cents)",
		"overdue_schedules": "Overdue Schedules",
	}

	@expose("/")
	@has_access
	def dashboard(self):
		from pgappforge.plugins.erp.operations.inventory.models import Product
		from pgappforge.plugins.erp.operations.warehouse.models import CycleCount, CycleCountLine

		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		warehouse_id = request.args.get("warehouse_id")
		today = date.today()

		filters = []
		if tenant_id:
			filters.append(CycleCount.tenant_id == tenant_id)
		if warehouse_id:
			filters.append(CycleCount.warehouse_id == warehouse_id)

		def count_for_status(statuses: tuple[str, ...]) -> int:
			return int(session.execute(
				sa.select(sa.func.count()).select_from(CycleCount).where(
					CycleCount.status.in_(statuses),
					*filters,
				)
			).scalar() or 0)

		status_counts = {
			"scheduled": count_for_status(("PLANNED", "SCHEDULED")),
			"in_progress": count_for_status(("IN_PROGRESS",)),
			"completed": count_for_status(("COMPLETED",)),
			"variance_found": int(session.execute(
				sa.select(sa.func.count(sa.distinct(CycleCount.id))).select_from(CycleCount)
				.join(CycleCountLine, CycleCountLine.count_id == CycleCount.id)
				.where(
					CycleCountLine.variance.is_not(None),
					CycleCountLine.variance != 0,
					*filters,
				)
			).scalar() or 0),
		}

		variance_rows = session.execute(
			sa.select(CycleCountLine.variance, Product.cost_price_cents)
			.join(CycleCount, CycleCountLine.count_id == CycleCount.id)
			.outerjoin(
				Product,
				sa.and_(
					Product.sku == CycleCountLine.product_code,
					Product.tenant_id == CycleCountLine.tenant_id,
				),
			)
			.where(
				CycleCount.status == "COMPLETED",
				CycleCountLine.variance.is_not(None),
				CycleCountLine.variance != 0,
				*filters,
			)
		).all()
		variance_amount_cents = int(sum(
			_qty_cost_cents(abs(Decimal(str(row.variance or 0))), row.cost_price_cents)
			for row in variance_rows
		))

		overdue_counts = session.execute(
			sa.select(CycleCount)
			.where(
				CycleCount.scheduled_date < today,
				CycleCount.status.notin_(("COMPLETED", "CANCELLED")),
				*filters,
			)
			.order_by(CycleCount.scheduled_date)
			.limit(50)
		).scalars().all()
		overdue_schedules = [
			{
				"id": c.id,
				"count_reference": c.count_reference,
				"warehouse_id": c.warehouse_id,
				"zone_code": c.zone_code,
				"scheduled_date": c.scheduled_date.isoformat() if c.scheduled_date else None,
				"status": c.status,
			}
			for c in overdue_counts
		]

		if request.args.get("format") == "json":
			return jsonify({
				"status_counts": status_counts,
				"variance_amount_cents": variance_amount_cents,
				"overdue_schedules": overdue_schedules,
			})

		kpi_html = self.kpi_cards([
			{"label": "Scheduled", "value": status_counts["scheduled"], "format": "integer",
			 "color": "#2563eb", "icon": "fa-calendar"},
			{"label": "In Progress", "value": status_counts["in_progress"], "format": "integer",
			 "color": "#d97706", "icon": "fa-spinner"},
			{"label": "Completed", "value": status_counts["completed"], "format": "integer",
			 "color": "#047857", "icon": "fa-check-circle"},
			{"label": "Variance Found", "value": status_counts["variance_found"], "format": "integer",
			 "color": "#dc2626", "icon": "fa-exclamation-circle"},
			{"label": "Completed Variance (cents)", "value": variance_amount_cents, "format": "integer",
			 "color": "#7c2d12", "icon": "fa-dollar-sign"},
			{"label": "Overdue", "value": len(overdue_schedules), "format": "integer",
			 "color": "#991b1b", "icon": "fa-clock"},
		])
		rows = "".join(
			f"<tr>"
			f"<td>{_he(c['count_reference'])}</td>"
			f"<td>{_he(c['warehouse_id'])}</td>"
			f"<td>{_he(c['zone_code'] or '')}</td>"
			f"<td>{_he(c['scheduled_date'])}</td>"
			f"<td><span class='label label-warning'>{_he(c['status'])}</span></td>"
			f"</tr>"
			for c in overdue_schedules
		)
		body = (
			"<h3>Cycle Count Dashboard</h3>"
			+ str(kpi_html)
			+ '<h4>Overdue Schedules</h4>'
			+ '<table class="table table-bordered table-condensed table-hover">'
			+ '<thead><tr><th>Reference</th><th>Warehouse</th><th>Zone</th><th>Scheduled</th><th>Status</th></tr></thead>'
			+ f"<tbody>{rows}</tbody></table>"
		)
		return make_response(_page_html("Cycle Count Dashboard", body), 200)


__all__ = [
	"PickListView",
	"PutawayView",
	"StockCountView",
	"WMSReportView",
	"WarehouseDashboardView",
	"CycleCountDashboardView",
]
