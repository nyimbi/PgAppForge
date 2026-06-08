"""
pgappforge/plugins/erp/operations/fleet/views.py

Flask views for the Fleet Management plugin.

Registered views:
  VehicleView        — CRUD + status transition
  DriverView         — CRUD
  TripLogView        — CRUD + close-trip action
  FuelRecordView     — CRUD
  FleetReportView    — Dashboard with KPI tiles:
                       total_vehicles, active_on_road,
                       in_maintenance, avg_utilization_pct
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
# VehicleView
# ---------------------------------------------------------------------------

class VehicleView(BaseERPView):
	"""Vehicle register CRUD + status transitions.

	GET  /fleet/vehicles/               — list with filters
	GET  /fleet/vehicles/<id>           — detail (JSON)
	POST /fleet/vehicles/               — create
	PUT  /fleet/vehicles/<id>           — update
	POST /fleet/vehicles/<id>/status    — change status
	"""

	route_base = "/fleet/vehicles"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.fleet.models import Vehicle
		session = _get_session()
		q = sa.select(Vehicle).order_by(Vehicle.reg_number)
		for field, col in (
			("tenant_id", Vehicle.tenant_id),
			("status", Vehicle.status),
			("fuel_type", Vehicle.fuel_type),
			("body_type", Vehicle.body_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		vehicles = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"vehicles": [
				{
					"id": v.id, "reg_number": v.reg_number,
					"make": v.make, "model": v.model,
					"year_of_manufacture": v.year_of_manufacture,
					"fuel_type": v.fuel_type, "body_type": v.body_type,
					"status": v.status,
					"current_odometer_km": str(v.current_odometer_km),
					"assigned_driver_id": v.assigned_driver_id,
				}
				for v in vehicles
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(v.reg_number)}</td>"
			f"<td>{_he(v.make)} {_he(v.model)} ({v.year_of_manufacture})</td>"
			f"<td>{_he(v.fuel_type)}</td>"
			f"<td><span class='label label-{'success' if v.status=='ACTIVE' else 'warning'}'>"
			f"{_he(v.status)}</span></td>"
			f"<td class='text-right'>{_he(v.current_odometer_km)}</td>"
			f"<td><a href='/fleet/vehicles/{_he(v.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for v in vehicles
		)
		body = (
			'<h3>Fleet Vehicles</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>Reg #</th><th>Vehicle</th><th>Fuel</th>'
			'<th>Status</th><th>Odometer (km)</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Fleet Vehicles", body), 200)

	@expose("/<string:vehicle_id>")
	@has_access
	def detail(self, vehicle_id: str):
		from pgappforge.plugins.erp.operations.fleet.models import Vehicle
		session = _get_session()
		v = session.get(Vehicle, vehicle_id)
		if v is None:
			abort(404)
		return jsonify({
			"id": v.id, "tenant_id": v.tenant_id,
			"reg_number": v.reg_number,
			"make": v.make, "model": v.model,
			"year_of_manufacture": v.year_of_manufacture,
			"chassis_number": v.chassis_number, "engine_number": v.engine_number,
			"fuel_type": v.fuel_type, "body_type": v.body_type,
			"colour": v.colour, "seating_capacity": v.seating_capacity,
			"payload_kg": str(v.payload_kg) if v.payload_kg else None,
			"acquisition_date": v.acquisition_date.isoformat() if v.acquisition_date else None,
			"acquisition_cost_cents": v.acquisition_cost_cents,
			"current_odometer_km": str(v.current_odometer_km),
			"status": v.status,
			"assigned_driver_id": v.assigned_driver_id,
			"department_id": v.department_id,
			"gps_device_id": v.gps_device_id,
			"average_fuel_consumption_per_100km": str(v.average_fuel_consumption_per_100km) if v.average_fuel_consumption_per_100km else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.fleet.models import Vehicle
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "reg_number", "make", "model", "year_of_manufacture", "acquisition_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		v = Vehicle(
			tenant_id=data["tenant_id"],
			reg_number=data["reg_number"],
			make=data["make"],
			model=data["model"],
			year_of_manufacture=int(data["year_of_manufacture"]),
			chassis_number=data.get("chassis_number"),
			engine_number=data.get("engine_number"),
			fuel_type=data.get("fuel_type", "PETROL"),
			body_type=data.get("body_type", "SALOON"),
			colour=data.get("colour", ""),
			seating_capacity=int(data.get("seating_capacity", 5)),
			payload_kg=data.get("payload_kg"),
			acquisition_date=date_type.fromisoformat(data["acquisition_date"]),
			acquisition_cost_cents=int(data.get("acquisition_cost_cents", 0)),
			current_odometer_km=data.get("current_odometer_km", 0),
			status=data.get("status", "ACTIVE"),
			assigned_driver_id=data.get("assigned_driver_id"),
			department_id=data.get("department_id"),
			gps_device_id=data.get("gps_device_id"),
		)
		session.add(v)
		session.commit()
		return jsonify({"ok": True, "id": v.id}), 201

	@expose("/<string:vehicle_id>", methods=["PUT"])
	@has_access
	def update(self, vehicle_id: str):
		from pgappforge.plugins.erp.operations.fleet.models import Vehicle
		session = _get_session()
		v = session.get(Vehicle, vehicle_id)
		if v is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("colour", "seating_capacity", "assigned_driver_id",
		          "department_id", "gps_device_id", "current_odometer_km"):
			if f in data:
				setattr(v, f, data[f])
		v.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:vehicle_id>/status", methods=["POST"])
	@has_access
	def set_status(self, vehicle_id: str):
		from pgappforge.plugins.erp.operations.fleet.models import Vehicle, VEHICLE_STATUSES
		session = _get_session()
		v = session.get(Vehicle, vehicle_id)
		if v is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		new_status = data.get("status")
		if new_status not in VEHICLE_STATUSES:
			return jsonify({"ok": False, "error": f"status must be one of {sorted(VEHICLE_STATUSES)}"}), 400
		v.status = new_status
		v.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "status": v.status})


# ---------------------------------------------------------------------------
# DriverView
# ---------------------------------------------------------------------------

class DriverView(BaseERPView):
	"""Fleet driver CRUD.

	GET  /fleet/drivers/         — list
	GET  /fleet/drivers/<id>     — detail (JSON)
	POST /fleet/drivers/         — create
	PUT  /fleet/drivers/<id>     — update
	"""

	route_base = "/fleet/drivers"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.fleet.models import Driver
		session = _get_session()
		q = sa.select(Driver).order_by(Driver.license_number)
		for field, col in (
			("tenant_id", Driver.tenant_id),
			("status", Driver.status),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		drivers = session.execute(q.limit(500)).scalars().all()
		return jsonify({"drivers": [
			{
				"id": d.id, "employee_id": str(d.employee_id),
				"license_number": d.license_number,
				"license_class": d.license_class,
				"license_expiry": d.license_expiry.isoformat() if d.license_expiry else None,
				"status": d.status, "demerit_points": d.demerit_points,
				"total_trips": d.total_trips,
				"total_km": str(d.total_km),
			}
			for d in drivers
		]})

	@expose("/<string:driver_id>")
	@has_access
	def detail(self, driver_id: str):
		from pgappforge.plugins.erp.operations.fleet.models import Driver
		session = _get_session()
		d = session.get(Driver, driver_id)
		if d is None:
			abort(404)
		return jsonify({
			"id": d.id, "tenant_id": d.tenant_id,
			"employee_id": str(d.employee_id),
			"license_number": d.license_number,
			"license_class": d.license_class,
			"license_expiry": d.license_expiry.isoformat() if d.license_expiry else None,
			"psvb_expiry": d.psvb_expiry.isoformat() if d.psvb_expiry else None,
			"medical_expiry": d.medical_expiry.isoformat() if d.medical_expiry else None,
			"status": d.status, "demerit_points": d.demerit_points,
			"total_trips": d.total_trips, "total_km": str(d.total_km),
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.fleet.models import Driver
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "employee_id", "license_number", "license_class", "license_expiry")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		d = Driver(
			tenant_id=data["tenant_id"],
			employee_id=data["employee_id"],
			license_number=data["license_number"],
			license_class=data["license_class"],
			license_expiry=date_type.fromisoformat(data["license_expiry"]),
			psvb_expiry=date_type.fromisoformat(data["psvb_expiry"]) if data.get("psvb_expiry") else None,
			medical_expiry=date_type.fromisoformat(data["medical_expiry"]) if data.get("medical_expiry") else None,
			status=data.get("status", "ACTIVE"),
		)
		session.add(d)
		session.commit()
		return jsonify({"ok": True, "id": d.id}), 201

	@expose("/<string:driver_id>", methods=["PUT"])
	@has_access
	def update(self, driver_id: str):
		from pgappforge.plugins.erp.operations.fleet.models import Driver
		from datetime import date as date_type
		session = _get_session()
		d = session.get(Driver, driver_id)
		if d is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("license_class", "status", "demerit_points"):
			if f in data:
				setattr(d, f, data[f])
		for date_f in ("license_expiry", "psvb_expiry", "medical_expiry"):
			if data.get(date_f):
				setattr(d, date_f, date_type.fromisoformat(data[date_f]))
		d.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# TripLogView
# ---------------------------------------------------------------------------

class TripLogView(BaseERPView):
	"""Trip log CRUD + close-trip action.

	GET  /fleet/trips/              — list
	GET  /fleet/trips/<id>          — detail
	POST /fleet/trips/              — open a new trip
	POST /fleet/trips/<id>/close    — close trip (record end odometer + distance)
	"""

	route_base = "/fleet/trips"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.fleet.models import TripLog
		session = _get_session()
		q = sa.select(TripLog).order_by(sa.desc(TripLog.start_datetime))
		for field, col in (
			("tenant_id", TripLog.tenant_id),
			("vehicle_id", TripLog.vehicle_id),
			("driver_id", TripLog.driver_id),
			("trip_type", TripLog.trip_type),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		trips = session.execute(q.limit(500)).scalars().all()
		return jsonify({"trips": [
			{
				"id": t.id, "vehicle_id": t.vehicle_id, "driver_id": t.driver_id,
				"trip_type": t.trip_type,
				"start_datetime": t.start_datetime.isoformat() if t.start_datetime else None,
				"end_datetime": t.end_datetime.isoformat() if t.end_datetime else None,
				"distance_km": str(t.distance_km) if t.distance_km else None,
				"start_location": t.start_location, "end_location": t.end_location,
			}
			for t in trips
		]})

	@expose("/<string:trip_id>")
	@has_access
	def detail(self, trip_id: str):
		from pgappforge.plugins.erp.operations.fleet.models import TripLog
		session = _get_session()
		t = session.get(TripLog, trip_id)
		if t is None:
			abort(404)
		return jsonify({
			"id": t.id, "tenant_id": t.tenant_id,
			"vehicle_id": t.vehicle_id, "driver_id": t.driver_id,
			"trip_purpose": t.trip_purpose, "trip_type": t.trip_type,
			"start_datetime": t.start_datetime.isoformat() if t.start_datetime else None,
			"end_datetime": t.end_datetime.isoformat() if t.end_datetime else None,
			"start_odometer": str(t.start_odometer),
			"end_odometer": str(t.end_odometer) if t.end_odometer else None,
			"distance_km": str(t.distance_km) if t.distance_km else None,
			"start_location": t.start_location, "end_location": t.end_location,
			"authorized_by": str(t.authorized_by) if t.authorized_by else None,
			"fuel_used_litres": str(t.fuel_used_litres) if t.fuel_used_litres else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.fleet.models import TripLog
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "vehicle_id", "driver_id", "trip_purpose",
		            "start_datetime", "start_odometer", "start_location")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		t = TripLog(
			tenant_id=data["tenant_id"],
			vehicle_id=data["vehicle_id"],
			driver_id=data["driver_id"],
			trip_purpose=data["trip_purpose"],
			trip_type=data.get("trip_type", "OFFICIAL"),
			start_datetime=datetime.fromisoformat(data["start_datetime"]),
			start_odometer=data["start_odometer"],
			start_location=data["start_location"],
			end_location=data.get("end_location", ""),
			authorized_by=data.get("authorized_by"),
		)
		session.add(t)
		session.commit()
		return jsonify({"ok": True, "id": t.id}), 201

	@expose("/<string:trip_id>/close", methods=["POST"])
	@has_access
	def close(self, trip_id: str):
		from pgappforge.plugins.erp.operations.fleet.models import TripLog, Vehicle
		from decimal import Decimal
		session = _get_session()
		t = session.get(TripLog, trip_id)
		if t is None:
			abort(404)
		if t.end_datetime is not None:
			return jsonify({"ok": False, "error": "Trip already closed"}), 400
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("end_odometer", "end_location") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		t.end_odometer = Decimal(str(data["end_odometer"]))
		t.end_location = data["end_location"]
		t.end_datetime = datetime.now(timezone.utc)
		t.distance_km = t.end_odometer - t.start_odometer
		if data.get("fuel_used_litres"):
			t.fuel_used_litres = Decimal(str(data["fuel_used_litres"]))
		t.updated_at = datetime.now(timezone.utc)
		# update vehicle odometer
		v = session.get(Vehicle, t.vehicle_id)
		if v and t.end_odometer > v.current_odometer_km:
			v.current_odometer_km = t.end_odometer
			v.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True, "distance_km": str(t.distance_km)})


# ---------------------------------------------------------------------------
# FuelRecordView
# ---------------------------------------------------------------------------

class FuelRecordView(BaseERPView):
	"""Fuel record CRUD.

	GET  /fleet/fuel/       — list (filter by vehicle, date range)
	POST /fleet/fuel/       — create
	"""

	route_base = "/fleet/fuel"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.fleet.models import FuelRecord
		session = _get_session()
		q = sa.select(FuelRecord).order_by(sa.desc(FuelRecord.fuelling_date))
		for field, col in (
			("tenant_id", FuelRecord.tenant_id),
			("vehicle_id", FuelRecord.vehicle_id),
			("driver_id", FuelRecord.driver_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		records = session.execute(q.limit(500)).scalars().all()
		return jsonify({"fuel_records": [
			{
				"id": r.id,
				"vehicle_id": r.vehicle_id, "driver_id": r.driver_id,
				"fuelling_date": r.fuelling_date.isoformat() if r.fuelling_date else None,
				"fuel_type": r.fuel_type,
				"litres": str(r.litres),
				"total_cost_cents": r.total_cost_cents,
				"odometer_km": str(r.odometer_km),
				"station_name": r.station_name,
				"payment_method": r.payment_method,
			}
			for r in records
		]})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.fleet.models import FuelRecord
		from datetime import date as date_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "vehicle_id", "driver_id", "fuelling_date",
		            "fuel_type", "litres", "cost_per_litre_cents", "total_cost_cents", "odometer_km")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		r = FuelRecord(
			tenant_id=data["tenant_id"],
			vehicle_id=data["vehicle_id"],
			driver_id=data["driver_id"],
			fuelling_date=date_type.fromisoformat(data["fuelling_date"]),
			fuel_type=data["fuel_type"],
			litres=data["litres"],
			cost_per_litre_cents=int(data["cost_per_litre_cents"]),
			total_cost_cents=int(data["total_cost_cents"]),
			odometer_km=data["odometer_km"],
			station_name=data.get("station_name"),
			receipt_number=data.get("receipt_number"),
			payment_method=data.get("payment_method", "CASH"),
		)
		session.add(r)
		session.commit()
		return jsonify({"ok": True, "id": r.id}), 201


# ---------------------------------------------------------------------------
# FleetReportView — dashboard
# ---------------------------------------------------------------------------

class FleetReportView(BaseERPView):
	"""Fleet dashboard and reports.

	GET /fleet/reports/     — Dashboard with KPI tiles:
	                          total_vehicles, active_on_road,
	                          in_maintenance, avg_utilization_pct
	"""

	route_base = "/fleet/reports"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		"""Fleet dashboard — total vehicles, active on road, in maintenance, utilization."""
		from pgappforge.plugins.erp.operations.fleet.models import Vehicle, TripLog
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		total_vehicles: int = 0
		active_on_road: int = 0
		in_maintenance: int = 0
		avg_utilization_pct: float = 0.0

		try:
			total_vehicles = session.execute(
				sa.select(sa.func.count()).select_from(Vehicle).where(
					Vehicle.status != "DISPOSED",
					*([Vehicle.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			active_on_road = session.execute(
				sa.select(sa.func.count()).select_from(Vehicle).where(
					Vehicle.status == "ACTIVE",
					*([Vehicle.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			in_maintenance = session.execute(
				sa.select(sa.func.count()).select_from(Vehicle).where(
					Vehicle.status == "IN_MAINTENANCE",
					*([Vehicle.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			# Utilization: vehicles with open trips / active vehicles * 100
			open_trips = session.execute(
				sa.select(sa.func.count(sa.func.distinct(TripLog.vehicle_id))).where(
					TripLog.end_datetime.is_(None),
					*([TripLog.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0
			avg_utilization_pct = round(open_trips / active_on_road * 100, 1) if active_on_road else 0.0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "Total Vehicles", "value": total_vehicles, "format": "integer",
			 "color": "#1a56db", "icon": "fa-car"},
			{"label": "Active on Road", "value": active_on_road, "format": "integer",
			 "color": "#057a55", "icon": "fa-road"},
			{"label": "In Maintenance", "value": in_maintenance, "format": "integer",
			 "color": "#e3a008", "icon": "fa-wrench"},
			{"label": "Avg Utilization %", "value": avg_utilization_pct, "format": "percent",
			 "color": "#9061f9", "icon": "fa-chart-line"},
		])

		if request.args.get("format") == "json":
			return jsonify({
				"total_vehicles": total_vehicles,
				"active_on_road": active_on_road,
				"in_maintenance": in_maintenance,
				"avg_utilization_pct": avg_utilization_pct,
			})

		body = (
			"<h3>Fleet Dashboard</h3>"
			+ str(kpi_html)
			+ '<p><a href="/fleet/vehicles/" class="btn btn-default">All Vehicles</a> '
			+ '<a href="/fleet/trips/" class="btn btn-default">Trip Logs</a></p>'
		)
		return make_response(_page_html("Fleet Dashboard", body), 200)


__all__ = [
	"VehicleView",
	"DriverView",
	"TripLogView",
	"FuelRecordView",
	"FleetReportView",
]
