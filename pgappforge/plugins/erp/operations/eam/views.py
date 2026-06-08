"""
pgappforge/plugins/erp/operations/eam/views.py

Flask views for the Enterprise Asset Management (EAM/CMMS) plugin.

Registered views:
  AssetLocationView       — CRUD for asset locations
  ManagedAssetView        — CRUD + status transitions
  MaintenancePlanView     — CRUD
  WorkOrderView           — CRUD + approve/assign/complete/cancel actions
  EAMReportView           — Dashboard with KPI tiles:
                            * total_assets, operational_pct,
                              overdue_maintenance, mtbf_days
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
# AssetLocationView
# ---------------------------------------------------------------------------

class AssetLocationView(BaseERPView):
	"""Asset location hierarchy CRUD.

	GET  /eam/locations/       — list
	GET  /eam/locations/<id>   — detail (JSON)
	POST /eam/locations/       — create
	PUT  /eam/locations/<id>   — update
	"""

	route_base = "/eam/locations"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.eam.models import AssetLocation
		session = _get_session()
		q = sa.select(AssetLocation).order_by(AssetLocation.level, AssetLocation.code)
		if request.args.get("tenant_id"):
			q = q.where(AssetLocation.tenant_id == request.args["tenant_id"])
		locs = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"locations": [
				{
					"id": l.id, "code": l.code, "name": l.name,
					"parent_location_id": l.parent_location_id,
					"level": l.level, "address": l.address,
				}
				for l in locs
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{'&nbsp;' * (l.level * 4)}{_he(l.code)}</td>"
			f"<td>{_he(l.name)}</td>"
			f"<td>{_he(l.address or '')}</td>"
			f"<td><a href='/eam/locations/{_he(l.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for l in locs
		)
		body = (
			'<h3>Asset Locations</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Code</th><th>Name</th><th>Address</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Asset Locations", body), 200)

	@expose("/<string:loc_id>")
	@has_access
	def detail(self, loc_id: str):
		from pgappforge.plugins.erp.operations.eam.models import AssetLocation
		session = _get_session()
		loc = session.get(AssetLocation, loc_id)
		if loc is None:
			abort(404)
		return jsonify({
			"id": loc.id, "tenant_id": loc.tenant_id,
			"code": loc.code, "name": loc.name,
			"parent_location_id": loc.parent_location_id,
			"level": loc.level, "address": loc.address,
			"gps_lat": str(loc.gps_lat) if loc.gps_lat else None,
			"gps_lng": str(loc.gps_lng) if loc.gps_lng else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.eam.models import AssetLocation
		session = _get_session()
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "code", "name") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		loc = AssetLocation(
			tenant_id=data["tenant_id"],
			code=data["code"],
			name=data["name"],
			parent_location_id=data.get("parent_location_id"),
			level=int(data.get("level", 0)),
			address=data.get("address"),
			gps_lat=data.get("gps_lat"),
			gps_lng=data.get("gps_lng"),
		)
		session.add(loc)
		session.commit()
		return jsonify({"ok": True, "id": loc.id}), 201

	@expose("/<string:loc_id>", methods=["PUT"])
	@has_access
	def update(self, loc_id: str):
		from pgappforge.plugins.erp.operations.eam.models import AssetLocation
		session = _get_session()
		loc = session.get(AssetLocation, loc_id)
		if loc is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "address", "gps_lat", "gps_lng", "parent_location_id", "level"):
			if f in data:
				setattr(loc, f, data[f])
		loc.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# ManagedAssetView
# ---------------------------------------------------------------------------

class ManagedAssetView(BaseERPView):
	"""Managed asset CRUD + lifecycle.

	GET  /eam/assets/              — list with filters
	GET  /eam/assets/<id>          — detail (JSON)
	POST /eam/assets/              — create
	PUT  /eam/assets/<id>          — update
	POST /eam/assets/<id>/status   — change status
	"""

	route_base = "/eam/assets"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.eam.models import ManagedAsset
		session = _get_session()
		q = sa.select(ManagedAsset).order_by(ManagedAsset.asset_code)
		for field, col in (
			("tenant_id", ManagedAsset.tenant_id),
			("status", ManagedAsset.status),
			("criticality", ManagedAsset.criticality),
			("asset_type", ManagedAsset.asset_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		assets = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"assets": [
				{
					"id": a.id, "asset_code": a.asset_code, "name": a.name,
					"asset_type": a.asset_type, "status": a.status,
					"criticality": a.criticality,
					"asset_location_id": a.asset_location_id,
					"install_date": a.install_date.isoformat() if a.install_date else None,
				}
				for a in assets
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(a.asset_code)}</td>"
			f"<td>{_he(a.name)}</td>"
			f"<td>{_he(a.asset_type)}</td>"
			f"<td><span class='label label-{'success' if a.status=='ACTIVE' else 'warning'}'>"
			f"{_he(a.status)}</span></td>"
			f"<td>{_he(a.criticality)}</td>"
			f"<td><a href='/eam/assets/{_he(a.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for a in assets
		)
		body = (
			'<h3>Assets</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Code</th><th>Name</th><th>Type</th>'
			'<th>Status</th><th>Criticality</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Assets", body), 200)

	@expose("/<string:asset_id>")
	@has_access
	def detail(self, asset_id: str):
		from pgappforge.plugins.erp.operations.eam.models import ManagedAsset
		session = _get_session()
		a = session.get(ManagedAsset, asset_id)
		if a is None:
			abort(404)
		return jsonify({
			"id": a.id, "tenant_id": a.tenant_id,
			"asset_code": a.asset_code, "name": a.name,
			"asset_location_id": a.asset_location_id,
			"parent_asset_id": a.parent_asset_id,
			"asset_type": a.asset_type,
			"manufacturer": a.manufacturer, "model_number": a.model_number,
			"serial_number": a.serial_number,
			"install_date": a.install_date.isoformat() if a.install_date else None,
			"warranty_expiry": a.warranty_expiry.isoformat() if a.warranty_expiry else None,
			"expected_life_years": a.expected_life_years,
			"replacement_cost_cents": a.replacement_cost_cents,
			"status": a.status, "criticality": a.criticality,
			"finance_asset_id": a.finance_asset_id,
			"created_at": a.created_at.isoformat() if a.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.eam.models import ManagedAsset
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "asset_code", "name", "asset_location_id", "asset_type", "install_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		a = ManagedAsset(
			tenant_id=data["tenant_id"],
			asset_code=data["asset_code"],
			name=data["name"],
			asset_location_id=data["asset_location_id"],
			parent_asset_id=data.get("parent_asset_id"),
			asset_type=data["asset_type"],
			manufacturer=data.get("manufacturer"),
			model_number=data.get("model_number"),
			serial_number=data.get("serial_number"),
			install_date=date_type.fromisoformat(data["install_date"]),
			warranty_expiry=date_type.fromisoformat(data["warranty_expiry"]) if data.get("warranty_expiry") else None,
			expected_life_years=data.get("expected_life_years"),
			replacement_cost_cents=int(data.get("replacement_cost_cents", 0)),
			status=data.get("status", "ACTIVE"),
			criticality=data.get("criticality", "MEDIUM"),
			finance_asset_id=data.get("finance_asset_id"),
		)
		session.add(a)
		session.commit()
		return jsonify({"ok": True, "id": a.id}), 201

	@expose("/<string:asset_id>", methods=["PUT"])
	@has_access
	def update(self, asset_id: str):
		from pgappforge.plugins.erp.operations.eam.models import ManagedAsset
		session = _get_session()
		a = session.get(ManagedAsset, asset_id)
		if a is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "manufacturer", "model_number", "criticality",
		          "expected_life_years", "replacement_cost_cents"):
			if f in data:
				setattr(a, f, data[f])
		a.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:asset_id>/status", methods=["POST"])
	@has_access
	def set_status(self, asset_id: str):
		from pgappforge.plugins.erp.operations.eam.models import ManagedAsset
		session = _get_session()
		a = session.get(ManagedAsset, asset_id)
		if a is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		new_status = data.get("status")
		valid = {"ACTIVE", "IN_MAINTENANCE", "OUT_OF_SERVICE", "DECOMMISSIONED"}
		if new_status not in valid:
			return jsonify({"ok": False, "error": f"status must be one of {sorted(valid)}"}), 400
		a.status = new_status
		a.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": a.status})


# ---------------------------------------------------------------------------
# MaintenancePlanView
# ---------------------------------------------------------------------------

class MaintenancePlanView(BaseERPView):
	"""Maintenance plan CRUD.

	GET  /eam/plans/           — list
	GET  /eam/plans/<id>       — detail (JSON)
	POST /eam/plans/           — create
	PUT  /eam/plans/<id>       — update
	"""

	route_base = "/eam/plans"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.eam.models import MaintenancePlan
		session = _get_session()
		q = sa.select(MaintenancePlan).where(MaintenancePlan.is_active.is_(True))
		for field, col in (
			("tenant_id", MaintenancePlan.tenant_id),
			("asset_id", MaintenancePlan.asset_id),
			("plan_type", MaintenancePlan.plan_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		plans = session.execute(q.order_by(MaintenancePlan.next_due_at).limit(500)).scalars().all()
		return jsonify({"plans": [
			{
				"id": p.id, "asset_id": p.asset_id, "plan_name": p.plan_name,
				"plan_type": p.plan_type,
				"trigger_interval_days": p.trigger_interval_days,
				"lead_days": p.lead_days,
				"next_due_at": p.next_due_at.isoformat() if p.next_due_at else None,
				"is_active": p.is_active,
			}
			for p in plans
		]})

	@expose("/<string:plan_id>")
	@has_access
	def detail(self, plan_id: str):
		from pgappforge.plugins.erp.operations.eam.models import MaintenancePlan
		session = _get_session()
		p = session.get(MaintenancePlan, plan_id)
		if p is None:
			abort(404)
		return jsonify({
			"id": p.id, "tenant_id": p.tenant_id,
			"asset_id": p.asset_id, "plan_name": p.plan_name,
			"plan_type": p.plan_type,
			"trigger_interval_days": p.trigger_interval_days,
			"trigger_meter_value": str(p.trigger_meter_value) if p.trigger_meter_value else None,
			"trigger_meter_type": p.trigger_meter_type,
			"lead_days": p.lead_days, "job_plan_id": p.job_plan_id,
			"last_generated_at": p.last_generated_at.isoformat() if p.last_generated_at else None,
			"next_due_at": p.next_due_at.isoformat() if p.next_due_at else None,
			"is_active": p.is_active,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.eam.models import MaintenancePlan
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "asset_id", "plan_name", "plan_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		p = MaintenancePlan(
			tenant_id=data["tenant_id"],
			asset_id=data["asset_id"],
			plan_name=data["plan_name"],
			plan_type=data["plan_type"],
			trigger_interval_days=data.get("trigger_interval_days"),
			trigger_meter_value=data.get("trigger_meter_value"),
			trigger_meter_type=data.get("trigger_meter_type"),
			lead_days=int(data.get("lead_days", 7)),
			job_plan_id=data.get("job_plan_id"),
			is_active=bool(data.get("is_active", True)),
		)
		session.add(p)
		session.commit()
		return jsonify({"ok": True, "id": p.id}), 201

	@expose("/<string:plan_id>", methods=["PUT"])
	@has_access
	def update(self, plan_id: str):
		from pgappforge.plugins.erp.operations.eam.models import MaintenancePlan
		session = _get_session()
		p = session.get(MaintenancePlan, plan_id)
		if p is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("plan_name", "trigger_interval_days", "trigger_meter_value",
		          "lead_days", "job_plan_id", "is_active"):
			if f in data:
				setattr(p, f, data[f])
		p.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# WorkOrderView
# ---------------------------------------------------------------------------

class WorkOrderView(BaseERPView):
	"""Maintenance work order CRUD + lifecycle.

	GET  /eam/work-orders/                   — list
	GET  /eam/work-orders/<id>               — detail
	POST /eam/work-orders/                   — create
	POST /eam/work-orders/<id>/approve       — PLANNED → APPROVED
	POST /eam/work-orders/<id>/assign        — assign operative
	POST /eam/work-orders/<id>/start         — ASSIGNED → IN_PROGRESS
	POST /eam/work-orders/<id>/complete      — → COMPLETED
	POST /eam/work-orders/<id>/cancel        — → CANCELLED
	"""

	route_base = "/eam/work-orders"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.eam.models import MaintenanceWorkOrder
		session = _get_session()
		q = sa.select(MaintenanceWorkOrder).order_by(
			MaintenanceWorkOrder.priority, sa.desc(MaintenanceWorkOrder.planned_start)
		)
		for field, col in (
			("tenant_id", MaintenanceWorkOrder.tenant_id),
			("status", MaintenanceWorkOrder.status),
			("work_type", MaintenanceWorkOrder.work_type),
			("asset_id", MaintenanceWorkOrder.asset_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		wos = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"work_orders": [
				{
					"id": wo.id, "wo_number": wo.wo_number,
					"asset_id": wo.asset_id,
					"work_type": wo.work_type, "priority": wo.priority,
					"status": wo.status,
					"planned_start": wo.planned_start.isoformat() if wo.planned_start else None,
					"planned_end": wo.planned_end.isoformat() if wo.planned_end else None,
					"actual_cost_cents": wo.actual_cost_cents,
				}
				for wo in wos
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(wo.wo_number)}</td>"
			f"<td>{_he(wo.work_type)}</td>"
			f"<td>{wo.priority}</td>"
			f"<td><span class='label label-info'>{_he(wo.status)}</span></td>"
			f"<td>{_he(wo.planned_start.strftime('%Y-%m-%d') if wo.planned_start else '')}</td>"
			f"<td><a href='/eam/work-orders/{_he(wo.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for wo in wos
		)
		body = (
			'<h3>Work Orders</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>WO #</th><th>Type</th><th>Priority</th>'
			'<th>Status</th><th>Planned Start</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Work Orders", body), 200)

	@expose("/<string:wo_id>")
	@has_access
	def detail(self, wo_id: str):
		from pgappforge.plugins.erp.operations.eam.models import MaintenanceWorkOrder
		session = _get_session()
		wo = session.get(MaintenanceWorkOrder, wo_id)
		if wo is None:
			abort(404)
		return jsonify({
			"id": wo.id, "tenant_id": wo.tenant_id,
			"wo_number": wo.wo_number, "asset_id": wo.asset_id,
			"work_type": wo.work_type, "priority": wo.priority,
			"status": wo.status, "description": wo.description,
			"job_plan_id": wo.job_plan_id,
			"failure_code": wo.failure_code, "cause_code": wo.cause_code,
			"remedy_code": wo.remedy_code,
			"assigned_to": str(wo.assigned_to) if wo.assigned_to else None,
			"planned_start": wo.planned_start.isoformat() if wo.planned_start else None,
			"planned_end": wo.planned_end.isoformat() if wo.planned_end else None,
			"actual_start": wo.actual_start.isoformat() if wo.actual_start else None,
			"actual_end": wo.actual_end.isoformat() if wo.actual_end else None,
			"estimated_cost_cents": wo.estimated_cost_cents,
			"actual_cost_cents": wo.actual_cost_cents,
			"downtime_hours": str(wo.downtime_hours) if wo.downtime_hours else None,
			"safety_permit_required": wo.safety_permit_required,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.eam.models import MaintenanceWorkOrder
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "asset_id", "work_type", "description", "planned_start", "planned_end")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		wo = MaintenanceWorkOrder(
			tenant_id=data["tenant_id"],
			wo_number=data.get("wo_number") or f"WO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
			asset_id=data["asset_id"],
			work_type=data["work_type"],
			priority=int(data.get("priority", 3)),
			status="PLANNED",
			job_plan_id=data.get("job_plan_id"),
			description=data["description"],
			failure_code=data.get("failure_code"),
			cause_code=data.get("cause_code"),
			remedy_code=data.get("remedy_code"),
			planned_start=datetime.fromisoformat(data["planned_start"]),
			planned_end=datetime.fromisoformat(data["planned_end"]),
			estimated_cost_cents=int(data.get("estimated_cost_cents", 0)),
			safety_permit_required=bool(data.get("safety_permit_required", False)),
		)
		session.add(wo)
		session.commit()
		return jsonify({"ok": True, "id": wo.id, "wo_number": wo.wo_number}), 201

	def _transition(self, wo_id: str, new_status: str, valid_from: set[str]):
		from pgappforge.plugins.erp.operations.eam.models import MaintenanceWorkOrder
		session = _get_session()
		wo = session.get(MaintenanceWorkOrder, wo_id)
		if wo is None:
			abort(404)
		if wo.status not in valid_from:
			return jsonify({"ok": False, "error": f"Cannot transition from {wo.status}"}), 400
		wo.status = new_status
		wo.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": wo.status})

	@expose("/<string:wo_id>/approve", methods=["POST"])
	@has_access
	def approve(self, wo_id: str):
		return self._transition(wo_id, "APPROVED", {"PLANNED"})

	@expose("/<string:wo_id>/assign", methods=["POST"])
	@has_access
	def assign(self, wo_id: str):
		from pgappforge.plugins.erp.operations.eam.models import MaintenanceWorkOrder
		session = _get_session()
		wo = session.get(MaintenanceWorkOrder, wo_id)
		if wo is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		employee_id = data.get("employee_id")
		if not employee_id:
			return jsonify({"ok": False, "error": "employee_id required"}), 400
		if wo.status not in {"APPROVED", "PLANNED"}:
			return jsonify({"ok": False, "error": f"Cannot assign from status {wo.status}"}), 400
		wo.assigned_to = employee_id
		wo.status = "ASSIGNED"
		wo.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": wo.status, "assigned_to": str(wo.assigned_to)})

	@expose("/<string:wo_id>/start", methods=["POST"])
	@has_access
	def start(self, wo_id: str):
		from pgappforge.plugins.erp.operations.eam.models import MaintenanceWorkOrder
		session = _get_session()
		wo = session.get(MaintenanceWorkOrder, wo_id)
		if wo is None:
			abort(404)
		if wo.status not in {"ASSIGNED", "APPROVED"}:
			return jsonify({"ok": False, "error": f"Cannot start from {wo.status}"}), 400
		wo.status = "IN_PROGRESS"
		wo.actual_start = datetime.now(timezone.utc)
		wo.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": wo.status})

	@expose("/<string:wo_id>/complete", methods=["POST"])
	@has_access
	def complete(self, wo_id: str):
		from pgappforge.plugins.erp.operations.eam.models import MaintenanceWorkOrder
		session = _get_session()
		wo = session.get(MaintenanceWorkOrder, wo_id)
		if wo is None:
			abort(404)
		if wo.status not in {"IN_PROGRESS", "PENDING_PARTS", "ON_HOLD"}:
			return jsonify({"ok": False, "error": f"Cannot complete from {wo.status}"}), 400
		data = request.get_json(silent=True) or {}
		wo.status = "COMPLETED"
		wo.actual_end = datetime.now(timezone.utc)
		if data.get("actual_cost_cents") is not None:
			wo.actual_cost_cents = int(data["actual_cost_cents"])
		if data.get("downtime_hours") is not None:
			wo.downtime_hours = data["downtime_hours"]
		if data.get("remedy_code"):
			wo.remedy_code = data["remedy_code"]
		wo.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": wo.status, "actual_cost_cents": wo.actual_cost_cents})

	@expose("/<string:wo_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, wo_id: str):
		return self._transition(wo_id, "CANCELLED", {"PLANNED", "APPROVED", "ASSIGNED"})


# ---------------------------------------------------------------------------
# EAMReportView — dashboard
# ---------------------------------------------------------------------------

class EAMReportView(BaseERPView):
	"""EAM dashboard and canned reports.

	GET /eam/reports/          — Dashboard with KPI tiles:
	                             total_assets, operational_pct,
	                             overdue_maintenance, mtbf_days
	"""

	route_base = "/eam/reports"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		"""EAM dashboard — total assets, operational %, overdue maintenance, MTBF days."""
		from pgappforge.plugins.erp.operations.eam.models import (
			ManagedAsset, MaintenancePlan, MaintenanceWorkOrder, FailureReport,
		)
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		total_assets: int = 0
		operational_pct: float = 0.0
		overdue_maintenance: int = 0
		mtbf_days: float = 0.0

		try:
			total_assets = session.execute(
				sa.select(sa.func.count()).select_from(ManagedAsset).where(
					ManagedAsset.status != "DECOMMISSIONED",
					*([ManagedAsset.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			active_assets = session.execute(
				sa.select(sa.func.count()).select_from(ManagedAsset).where(
					ManagedAsset.status == "ACTIVE",
					*([ManagedAsset.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0
			operational_pct = round(active_assets / total_assets * 100, 1) if total_assets else 0.0

			overdue_maintenance = session.execute(
				sa.select(sa.func.count()).select_from(MaintenancePlan).where(
					MaintenancePlan.next_due_at < sa.func.now(),
					MaintenancePlan.is_active.is_(True),
					*([MaintenancePlan.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			# Rough MTBF: avg days between failures per asset
			# Total days in window / total failures
			failure_count = session.execute(
				sa.select(sa.func.count()).select_from(FailureReport).where(
					*([FailureReport.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0
			if failure_count and total_assets:
				mtbf_days = round(365 * total_assets / failure_count, 1)
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Total Assets", "value": total_assets, "format": "integer",
			 "color": "#1a56db", "icon": "fa-cogs"},
			{"label": "Operational %", "value": operational_pct, "format": "percent",
			 "color": "#057a55", "icon": "fa-check-circle"},
			{"label": "Overdue Maintenance", "value": overdue_maintenance, "format": "integer",
			 "color": "#e02424", "icon": "fa-exclamation-triangle"},
			{"label": "MTBF (days)", "value": mtbf_days, "format": "number",
			 "color": "#9061f9", "icon": "fa-calendar-alt"},
		])

		if request.args.get("format") == "json":
			return jsonify({
				"total_assets": total_assets,
				"operational_pct": operational_pct,
				"overdue_maintenance": overdue_maintenance,
				"mtbf_days": mtbf_days,
			})

		body = (
			"<h3>EAM Dashboard</h3>"
			+ str(kpi_html)
			+ '<p><a href="/eam/assets/" class="btn btn-default">All Assets</a> '
			+ '<a href="/eam/work-orders/" class="btn btn-default">Work Orders</a></p>'
		)
		return make_response(_page_html("EAM Dashboard", body), 200)


__all__ = [
	"AssetLocationView",
	"ManagedAssetView",
	"MaintenancePlanView",
	"WorkOrderView",
	"EAMReportView",
]
