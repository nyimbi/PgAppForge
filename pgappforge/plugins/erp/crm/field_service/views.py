"""
pgappforge/plugins/erp/crm/field_service/views.py

Flask views for the Field Service plugin.

Route summary
-------------
ServiceTerritoryView   /field-service/territories/
ServiceResourceView    /field-service/resources/
WorkOrderView          /field-service/work-orders/
ServiceAppointmentView /field-service/appointments/
FieldServiceReportView /field-service/reports/
  ├─ /open-work-orders      — Open Work Orders (HTML)
  ├─ /resource-utilisation  — Resource utilisation by territory (HTML)
  └─ /completion-rate       — Completion rate by work type (HTML)
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


# ---------------------------------------------------------------------------
# ServiceTerritoryView
# ---------------------------------------------------------------------------

class ServiceTerritoryView(BaseERPView):
	"""Service Territory CRUD."""

	route_base = "/field-service/territories"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.field_service.models import ServiceTerritory
		session = _get_session()
		rows_data = session.execute(
			sa.select(ServiceTerritory).order_by(ServiceTerritory.name)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(t.id)}</td><td>{_he(t.name)}</td><td>{_he(t.manager_id or '')}</td></tr>"
			for t in rows_data
		)
		return make_response(
			f"<html><body><h2>Service Territories</h2><table border='1'>"
			f"<tr><th>ID</th><th>Name</th><th>Manager</th></tr>{rows}</table></body></html>"
		)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.crm.field_service.models import ServiceTerritory
		data = request.get_json(force=True) or {}
		if not data.get("name") or not data.get("tenant_id"):
			return jsonify({"error": "name and tenant_id required"}), 400
		session = _get_session()
		t = ServiceTerritory(
			tenant_id=data["tenant_id"],
			name=data["name"],
			manager_id=data.get("manager_id"),
		)
		session.add(t)
		session.commit()
		return jsonify({"id": t.id, "name": t.name}), 201


# ---------------------------------------------------------------------------
# ServiceResourceView
# ---------------------------------------------------------------------------

class ServiceResourceView(BaseERPView):
	"""Service Resource CRUD."""

	route_base = "/field-service/resources"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.field_service.models import ServiceResource
		session = _get_session()
		resources = session.execute(sa.select(ServiceResource)).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(r.id)}</td><td>{_he(r.employee_id)}</td>"
			f"<td>{_he(r.territory_id or '')}</td><td>{r.capacity_per_day}</td></tr>"
			for r in resources
		)
		return make_response(
			f"<html><body><h2>Service Resources</h2><table border='1'>"
			f"<tr><th>ID</th><th>Employee</th><th>Territory</th><th>Capacity/Day</th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/<string:resource_id>/schedule")
	@has_access
	def schedule(self, resource_id: str):
		from pgappforge.plugins.erp.crm.field_service.services import FieldServiceService
		date_from_str = request.args.get("from", datetime.now(timezone.utc).date().isoformat())
		date_to_str = request.args.get("to", datetime.now(timezone.utc).date().isoformat())
		session = _get_session()
		wos = FieldServiceService.resource_schedule(
			resource_id,
			datetime.fromisoformat(date_from_str),
			datetime.fromisoformat(date_to_str),
			session,
		)
		return jsonify([
			{
				"id": wo.id,
				"work_order_number": wo.work_order_number,
				"work_type": wo.work_type,
				"scheduled_start": wo.scheduled_start.isoformat() if wo.scheduled_start else None,
				"scheduled_end": wo.scheduled_end.isoformat() if wo.scheduled_end else None,
				"status": wo.status,
			}
			for wo in wos
		])


# ---------------------------------------------------------------------------
# WorkOrderView
# ---------------------------------------------------------------------------

class WorkOrderView(BaseERPView):
	"""Work Order CRUD + schedule/complete actions."""

	route_base = "/field-service/work-orders"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder
		session = _get_session()
		wos = session.execute(
			sa.select(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(200)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(w.work_order_number)}</td><td>{_he(w.work_type)}</td>"
			f"<td>{_he(w.status)}</td>"
			f"<td>{_he(w.scheduled_start.isoformat() if w.scheduled_start else '')}</td></tr>"
			for w in wos
		)
		return make_response(
			f"<html><body><h2>Work Orders</h2><table border='1'>"
			f"<tr><th>Number</th><th>Type</th><th>Status</th><th>Scheduled Start</th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.crm.field_service.services import FieldServiceService, FieldServiceValidationError
		data = request.get_json(force=True) or {}
		for f in ("tenant_id", "work_order_number", "work_type"):
			if not data.get(f):
				return jsonify({"error": f"Missing field: {f}"}), 400
		session = _get_session()
		try:
			wo = FieldServiceService.create_work_order(data, session)
			session.commit()
			return jsonify({"id": wo.id, "work_order_number": wo.work_order_number}), 201
		except FieldServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:wo_id>/schedule", methods=["POST"])
	@has_access
	def schedule(self, wo_id: str):
		from pgappforge.plugins.erp.crm.field_service.services import (
			FieldServiceService, FieldServiceValidationError,
			WorkOrderNotFoundError, ResourceNotFoundError,
		)
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			wo = FieldServiceService.schedule_work_order(
				wo_id,
				data["resource_id"],
				datetime.fromisoformat(data["scheduled_start"]),
				datetime.fromisoformat(data["scheduled_end"]),
				session,
			)
			session.commit()
			return jsonify({"id": wo.id, "status": wo.status})
		except WorkOrderNotFoundError:
			return jsonify({"error": "Work order not found"}), 404
		except (FieldServiceValidationError, ResourceNotFoundError, KeyError) as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:wo_id>/complete", methods=["POST"])
	@has_access
	def complete(self, wo_id: str):
		from pgappforge.plugins.erp.crm.field_service.services import (
			FieldServiceService, FieldServiceValidationError, WorkOrderNotFoundError,
		)
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			wo = FieldServiceService.complete_work_order(wo_id, data, session)
			session.commit()
			return jsonify({"id": wo.id, "status": wo.status, "labor_minutes": wo.labor_minutes})
		except WorkOrderNotFoundError:
			return jsonify({"error": "Work order not found"}), 404
		except FieldServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ServiceAppointmentView
# ---------------------------------------------------------------------------

class ServiceAppointmentView(BaseERPView):
	"""Service Appointment: propose/confirm/cancel."""

	route_base = "/field-service/appointments"

	@expose("/propose", methods=["POST"])
	@has_access
	def propose(self):
		from pgappforge.plugins.erp.crm.field_service.services import FieldServiceService, WorkOrderNotFoundError
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			appt = FieldServiceService.propose_appointment(
				data["work_order_id"],
				data.get("slots", []),
				data.get("contact_id"),
				session,
			)
			session.commit()
			return jsonify({"id": appt.id, "status": appt.status}), 201
		except WorkOrderNotFoundError:
			return jsonify({"error": "Work order not found"}), 404

	@expose("/<string:appt_id>/confirm", methods=["POST"])
	@has_access
	def confirm(self, appt_id: str):
		from pgappforge.plugins.erp.crm.field_service.services import (
			FieldServiceService, FieldServiceValidationError, AppointmentNotFoundError,
		)
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			appt = FieldServiceService.confirm_appointment(appt_id, data.get("slot_index", 0), session)
			session.commit()
			return jsonify({"id": appt.id, "status": appt.status, "confirmed_slot": appt.confirmed_slot})
		except AppointmentNotFoundError:
			return jsonify({"error": "Appointment not found"}), 404
		except FieldServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:appt_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, appt_id: str):
		from pgappforge.plugins.erp.crm.field_service.services import (
			FieldServiceService, FieldServiceValidationError, AppointmentNotFoundError,
		)
		session = _get_session()
		try:
			appt = FieldServiceService.cancel_appointment(appt_id, session)
			session.commit()
			return jsonify({"id": appt.id, "status": appt.status})
		except AppointmentNotFoundError:
			return jsonify({"error": "Appointment not found"}), 404
		except FieldServiceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# FieldServiceReportView — 3 ReportForge-compatible report endpoints
# ---------------------------------------------------------------------------

class FieldServiceReportView(BaseERPView):
	"""Field Service reports."""

	route_base = "/field-service/reports"

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		"""Field Service dashboard — KPIs."""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder, ServiceResource
		import sqlalchemy.func as func
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		now = datetime.now(timezone.utc)
		today = now.date()

		q_today = sa.select(sa.func.count(WorkOrder.id)).where(
			sa.func.date(WorkOrder.scheduled_start) == today
		)
		q_completed = sa.select(sa.func.count(WorkOrder.id)).where(
			sa.func.date(WorkOrder.scheduled_start) == today,
			WorkOrder.status == "COMPLETED",
		)
		q_resources = sa.select(sa.func.count(ServiceResource.id)).where(
			ServiceResource.is_active.is_(True)
		)
		# avg response hours: mean of (actual_start - created_at) in hours
		q_response = sa.select(
			sa.func.coalesce(
				sa.func.avg(
					sa.func.extract(
						"epoch",
						WorkOrder.actual_start - WorkOrder.created_at,
					) / 3600
				),
				0,
			)
		).where(WorkOrder.actual_start.isnot(None))
		if tenant_id:
			q_today = q_today.where(WorkOrder.tenant_id == tenant_id)
			q_completed = q_completed.where(WorkOrder.tenant_id == tenant_id)
			q_resources = q_resources.where(ServiceResource.tenant_id == tenant_id)
			q_response = q_response.where(WorkOrder.tenant_id == tenant_id)

		work_orders_today = int(session.execute(q_today).scalar() or 0)
		completed_today = int(session.execute(q_completed).scalar() or 0)
		technicians_active = int(session.execute(q_resources).scalar() or 0)
		avg_response_hours = float(session.execute(q_response).scalar() or 0)

		kpi_html = self.kpi_cards([
			{"label": "Work Orders Today", "value": work_orders_today, "format": "integer", "color": "#1a56db", "icon": "fa-tools"},
			{"label": "Completed Today", "value": completed_today, "format": "integer", "color": "#057a55", "icon": "fa-check"},
			{"label": "Technicians Active", "value": technicians_active, "format": "integer", "color": "#9061f9", "icon": "fa-hard-hat"},
			{"label": "Avg Response (hrs)", "value": avg_response_hours, "format": "number", "color": "#d97706", "icon": "fa-clock"},
		])

		return make_response(
			f"<html><head><meta charset='utf-8'><title>Field Service Dashboard</title>"
			f"<link rel='stylesheet' href='https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css'>"
			f"</head><body style='padding:24px'>"
			f"<h3>Field Service Dashboard</h3>{kpi_html}</body></html>"
		)

	@expose("/open-work-orders")
	@has_access
	def open_work_orders(self):
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder
		import sqlalchemy.func as func
		session = _get_session()
		rows_data = session.execute(
			sa.select(WorkOrder.work_type, WorkOrder.status, func.count(WorkOrder.id).label("cnt"))
			.where(WorkOrder.status.in_(("DRAFT", "SCHEDULED", "IN_PROGRESS")))
			.group_by(WorkOrder.work_type, WorkOrder.status)
		).all()
		rows = "".join(
			f"<tr><td>{_he(r.work_type)}</td><td>{_he(r.status)}</td><td>{r.cnt}</td></tr>"
			for r in rows_data
		)
		return make_response(
			f"<html><body><h2>Open Work Orders</h2><table border='1'>"
			f"<tr><th>Work Type</th><th>Status</th><th>Count</th></tr>{rows}</table></body></html>"
		)

	@expose("/resource-utilisation")
	@has_access
	def resource_utilisation(self):
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder, ServiceResource, ServiceTerritory
		import sqlalchemy.func as func
		session = _get_session()
		rows_data = session.execute(
			sa.select(
				ServiceTerritory.name.label("territory"),
				func.count(WorkOrder.id).label("wo_count"),
				func.sum(WorkOrder.labor_minutes).label("total_labor"),
			)
			.join(ServiceResource, ServiceResource.id == WorkOrder.assigned_to)
			.join(ServiceTerritory, ServiceTerritory.id == ServiceResource.territory_id)
			.where(WorkOrder.status == "COMPLETED")
			.group_by(ServiceTerritory.name)
		).all()
		rows = "".join(
			f"<tr><td>{_he(r.territory)}</td><td>{r.wo_count}</td><td>{r.total_labor or 0}</td></tr>"
			for r in rows_data
		)
		return make_response(
			f"<html><body><h2>Resource Utilisation by Territory</h2><table border='1'>"
			f"<tr><th>Territory</th><th>Completed WOs</th><th>Total Labor (min)</th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/completion-rate")
	@has_access
	def completion_rate(self):
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder
		import sqlalchemy.func as func
		session = _get_session()
		rows_data = session.execute(
			sa.select(WorkOrder.work_type, WorkOrder.status, func.count(WorkOrder.id).label("cnt"))
			.group_by(WorkOrder.work_type, WorkOrder.status)
		).all()

		by_type: dict[str, dict[str, int]] = {}
		for r in rows_data:
			by_type.setdefault(r.work_type, {})[r.status] = r.cnt

		rows = ""
		for wt, counts in sorted(by_type.items()):
			total = sum(counts.values())
			completed = counts.get("COMPLETED", 0)
			pct = round(completed / total * 100, 1) if total else 0
			rows += f"<tr><td>{_he(wt)}</td><td>{completed}</td><td>{total}</td><td>{pct}%</td></tr>"

		return make_response(
			f"<html><body><h2>Completion Rate by Work Type</h2><table border='1'>"
			f"<tr><th>Work Type</th><th>Completed</th><th>Total</th><th>Rate</th></tr>"
			f"{rows}</table></body></html>"
		)
