"""
pgappforge/plugins/erp/operations/fleet/services.py

FleetService — stateless business logic for the Fleet Management plugin.

All methods receive an explicit SQLAlchemy 2.x session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents
  - Decimal arithmetic used internally; results rounded half-up to int

GL integration:
  - record_fuelling() posts: DR fuel_expense "6300"  CR Cash "1011"
  - record_service()  posts: DR maintenance_expense "6350"  CR AP "2000"
  - If GL plugin is not loaded the journal dict is returned in the result
    and the operation proceeds normally

Demerit logic:
  - ACCIDENT incident: +3 demerit points
  - TRAFFIC_VIOLATION: +2 demerit points
  - Any other incident: +1 demerit point
  - demerit_points >= 12: driver auto-suspended, DriverSuspendedEvent emitted

Public API:
  register_vehicle(session, data, tenant_id)                         -> Vehicle
  assign_driver(session, vehicle_id, driver_id, tenant_id)           -> Vehicle
  log_trip(session, vehicle_id, driver_id, data, tenant_id)          -> TripLog
  record_fuelling(session, vehicle_id, driver_id, data, tenant_id)   -> FuelRecord
  record_service(session, vehicle_id, data, tenant_id)               -> VehicleService
  report_incident(session, vehicle_id, driver_id, data, tenant_id)   -> FleetIncident
  get_documents_expiring(session, days_ahead, tenant_id)             -> list[dict]
  get_vehicle_tco(session, vehicle_id, from_date, to_date, tenant_id)-> dict
  maintenance_due_alerts(session, tenant_id)                         -> list[dict]
  get_fleet_dashboard(session, tenant_id)                            -> dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FleetServiceError(Exception):
	"""Base domain error for Fleet operations."""


class VehicleNotFoundError(FleetServiceError):
	pass


class DriverNotFoundError(FleetServiceError):
	pass


class DriverNotActiveError(FleetServiceError):
	"""Raised when a trip or fuelling is attempted with a non-ACTIVE driver."""


class VehicleNotActiveError(FleetServiceError):
	"""Raised when a trip is attempted on a non-ACTIVE vehicle."""


class TripNotFoundError(FleetServiceError):
	pass


# ---------------------------------------------------------------------------
# Demerit point rules
# ---------------------------------------------------------------------------

_DEMERIT_POINTS: dict[str, int] = {
	"ACCIDENT": 3,
	"TRAFFIC_VIOLATION": 2,
}
_DEFAULT_DEMERIT = 1
_SUSPENSION_THRESHOLD = 12


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cents(value: Any) -> int:
	"""Convert any numeric to integer cents, half-up rounding."""
	return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(value: Any) -> Decimal:
	return Decimal(str(value))


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _today() -> date:
	return date.today()


def _try_post_gl(
	session: Any,
	dr_account: str,
	cr_account: str,
	amount_cents: int,
	description: str,
	reference_id: str,
	tenant_id: str,
) -> str:
	"""Best-effort GL double-entry post.  Returns journal_id or '' on failure."""
	try:
		from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
		journal_id = GLService.post_journal(
			session=session,
			dr_account=dr_account,
			cr_account=cr_account,
			amount_cents=amount_cents,
			description=description,
			reference_id=reference_id,
			tenant_id=tenant_id,
		)
		return str(journal_id)
	except Exception as exc:  # noqa: BLE001
		log.debug("GL plugin not available or post failed (%s) — proceeding", exc)
		return ""


def _emit(event: Any, session: Any) -> None:
	"""Best-effort domain event emission."""
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event  # type: ignore[import]
		emit_event(event, session)
	except Exception as exc:  # noqa: BLE001
		log.debug("Event emission skipped: %s", exc)


# ---------------------------------------------------------------------------
# FleetService
# ---------------------------------------------------------------------------

class FleetService:
	"""Stateless service — all methods are classmethods; instantiation optional."""

	# ------------------------------------------------------------------
	# 1. register_vehicle
	# ------------------------------------------------------------------

	@classmethod
	def register_vehicle(
		cls,
		session: Any,
		data: dict[str, Any],
		tenant_id: str,
	) -> Any:
		"""Create and persist a new Vehicle record.

		data keys mirror Vehicle column names (snake_case).
		acquisition_cost_cents must be provided as integer cents.
		Returns the persisted Vehicle instance.
		"""
		from pgappforge.plugins.erp.operations.fleet.models import (
			BODY_TYPES, FUEL_TYPES, Vehicle,
		)
		from pgappforge.plugins.erp.operations.fleet.events import VehicleRegisteredEvent

		fuel_type = str(data.get("fuel_type", "PETROL")).upper()
		body_type = str(data.get("body_type", "SALOON")).upper()
		if fuel_type not in FUEL_TYPES:
			raise FleetServiceError(f"Invalid fuel_type {fuel_type!r}. Choose from {FUEL_TYPES}")
		if body_type not in BODY_TYPES:
			raise FleetServiceError(f"Invalid body_type {body_type!r}. Choose from {BODY_TYPES}")

		vehicle = Vehicle(
			tenant_id=tenant_id,
			reg_number=str(data["reg_number"]).upper().strip(),
			make=str(data["make"]).strip(),
			model=str(data["model"]).strip(),
			year_of_manufacture=int(data["year_of_manufacture"]),
			chassis_number=data.get("chassis_number"),
			engine_number=data.get("engine_number"),
			fuel_type=fuel_type,
			body_type=body_type,
			colour=str(data.get("colour", "")).strip(),
			seating_capacity=int(data.get("seating_capacity", 5)),
			payload_kg=_dec(data["payload_kg"]) if data.get("payload_kg") is not None else None,
			acquisition_date=data["acquisition_date"],
			acquisition_cost_cents=_cents(data.get("acquisition_cost_cents", 0)),
			current_odometer_km=_dec(data.get("current_odometer_km", 0)),
			status="ACTIVE",
			department_id=data.get("department_id"),
			gps_device_id=data.get("gps_device_id"),
		)
		session.add(vehicle)
		session.flush()

		_emit(
			VehicleRegisteredEvent(
				aggregate_id=vehicle.id,
				aggregate_type="Vehicle",
				tenant_id=tenant_id,
				vehicle_id=vehicle.id,
				reg_number=vehicle.reg_number,
				make=vehicle.make,
				model=vehicle.model,
				year_of_manufacture=vehicle.year_of_manufacture,
				fuel_type=vehicle.fuel_type,
				body_type=vehicle.body_type,
				acquisition_cost_cents=vehicle.acquisition_cost_cents,
			),
			session,
		)

		log.info("Vehicle registered: %s (%s %s %d)", vehicle.reg_number, vehicle.make, vehicle.model, vehicle.year_of_manufacture)
		return vehicle

	# ------------------------------------------------------------------
	# 2. assign_driver
	# ------------------------------------------------------------------

	@classmethod
	def assign_driver(
		cls,
		session: Any,
		vehicle_id: str,
		driver_id: str,
		tenant_id: str,
	) -> Any:
		"""Assign a Driver to a Vehicle.

		Sets Vehicle.assigned_driver_id.  Driver must be ACTIVE.
		Returns the updated Vehicle.
		"""
		from pgappforge.plugins.erp.operations.fleet.models import Driver, Vehicle
		from pgappforge.plugins.erp.operations.fleet.events import DriverAssignedEvent

		vehicle = session.get(Vehicle, vehicle_id)
		if vehicle is None or vehicle.tenant_id != tenant_id:
			raise VehicleNotFoundError(f"Vehicle {vehicle_id!r} not found")

		driver = session.get(Driver, driver_id)
		if driver is None or driver.tenant_id != tenant_id:
			raise DriverNotFoundError(f"Driver {driver_id!r} not found")
		if driver.status != "ACTIVE":
			raise DriverNotActiveError(f"Driver {driver_id!r} is {driver.status}, cannot be assigned")

		vehicle.assigned_driver_id = driver_id
		session.flush()

		_emit(
			DriverAssignedEvent(
				aggregate_id=vehicle.id,
				aggregate_type="Vehicle",
				tenant_id=tenant_id,
				vehicle_id=vehicle.id,
				reg_number=vehicle.reg_number,
				driver_id=driver.id,
				employee_id=str(driver.employee_id),
			),
			session,
		)

		log.info("Driver %s assigned to vehicle %s", driver_id, vehicle.reg_number)
		return vehicle

	# ------------------------------------------------------------------
	# 3. log_trip
	# ------------------------------------------------------------------

	@classmethod
	def log_trip(
		cls,
		session: Any,
		vehicle_id: str,
		driver_id: str,
		data: dict[str, Any],
		tenant_id: str,
	) -> Any:
		"""Open or close a trip log.

		If data contains 'end_odometer' the trip is closed immediately (one-shot).
		Otherwise an open TripLog is created.

		On trip close:
		  - vehicle.current_odometer_km updated to end_odometer
		  - driver.total_km incremented by distance_km
		  - driver.total_trips incremented by 1
		  - TripCompletedEvent emitted

		Validates:
		  - driver.status == ACTIVE
		  - vehicle.status == ACTIVE
		  - end_odometer > start_odometer (when closing)
		"""
		from pgappforge.plugins.erp.operations.fleet.models import (
			Driver, TripLog, TRIP_TYPES, Vehicle,
		)
		from pgappforge.plugins.erp.operations.fleet.events import TripCompletedEvent

		vehicle = session.get(Vehicle, vehicle_id)
		if vehicle is None or vehicle.tenant_id != tenant_id:
			raise VehicleNotFoundError(f"Vehicle {vehicle_id!r} not found")
		if vehicle.status != "ACTIVE":
			raise VehicleNotActiveError(f"Vehicle {vehicle_id!r} is {vehicle.status}")

		driver = session.get(Driver, driver_id)
		if driver is None or driver.tenant_id != tenant_id:
			raise DriverNotFoundError(f"Driver {driver_id!r} not found")
		if driver.status != "ACTIVE":
			raise DriverNotActiveError(f"Driver {driver_id!r} is {driver.status}")

		trip_type = str(data.get("trip_type", "OFFICIAL")).upper()
		if trip_type not in TRIP_TYPES:
			raise FleetServiceError(f"Invalid trip_type {trip_type!r}")

		start_odometer = _dec(data["start_odometer"])
		end_odometer_raw = data.get("end_odometer")
		end_odometer: Decimal | None = _dec(end_odometer_raw) if end_odometer_raw is not None else None

		if end_odometer is not None and end_odometer <= start_odometer:
			raise FleetServiceError("end_odometer must be greater than start_odometer")

		start_dt = data.get("start_datetime", _now_utc())
		end_dt = data.get("end_datetime") if end_odometer is not None else None
		distance_km = (end_odometer - start_odometer) if end_odometer is not None else None

		trip = TripLog(
			tenant_id=tenant_id,
			vehicle_id=vehicle_id,
			driver_id=driver_id,
			trip_purpose=str(data.get("trip_purpose", "")),
			trip_type=trip_type,
			start_datetime=start_dt,
			end_datetime=end_dt,
			start_odometer=start_odometer,
			end_odometer=end_odometer,
			distance_km=distance_km,
			start_location=str(data.get("start_location", "")),
			end_location=str(data.get("end_location", "")),
			authorized_by=data.get("authorized_by"),
			fuel_used_litres=_dec(data["fuel_used_litres"]) if data.get("fuel_used_litres") is not None else None,
		)
		session.add(trip)
		session.flush()

		if end_odometer is not None and distance_km is not None:
			# Update vehicle odometer
			vehicle.current_odometer_km = end_odometer
			# Update driver totals
			driver.total_km = _dec(driver.total_km or 0) + distance_km
			driver.total_trips = (driver.total_trips or 0) + 1
			session.flush()

			_emit(
				TripCompletedEvent(
					aggregate_id=trip.id,
					aggregate_type="TripLog",
					tenant_id=tenant_id,
					trip_id=trip.id,
					vehicle_id=vehicle_id,
					driver_id=driver_id,
					trip_type=trip.trip_type,
					distance_km=str(distance_km),
					fuel_used_litres=str(trip.fuel_used_litres) if trip.fuel_used_litres else "",
					start_datetime=str(start_dt),
					end_datetime=str(end_dt),
				),
				session,
			)

		log.info("TripLog %s created (vehicle=%s, driver=%s)", trip.id, vehicle_id, driver_id)
		return trip

	# ------------------------------------------------------------------
	# 4. record_fuelling
	# ------------------------------------------------------------------

	@classmethod
	def record_fuelling(
		cls,
		session: Any,
		vehicle_id: str,
		driver_id: str,
		data: dict[str, Any],
		tenant_id: str,
	) -> Any:
		"""Record a fuel purchase and update rolling fuel consumption.

		GL entry: DR fuel_expense "6300"  CR Cash "1011"
		Updates Vehicle.average_fuel_consumption_per_100km using distance
		since the last fuel record for the same vehicle (Brimful method).

		Returns the persisted FuelRecord.
		"""
		from pgappforge.plugins.erp.operations.fleet.models import Driver, FuelRecord, Vehicle
		from pgappforge.plugins.erp.operations.fleet.events import FuelRecordedEvent

		vehicle = session.get(Vehicle, vehicle_id)
		if vehicle is None or vehicle.tenant_id != tenant_id:
			raise VehicleNotFoundError(f"Vehicle {vehicle_id!r} not found")

		driver = session.get(Driver, driver_id)
		if driver is None or driver.tenant_id != tenant_id:
			raise DriverNotFoundError(f"Driver {driver_id!r} not found")

		litres = _dec(data["litres"])
		cost_per_litre_cents = _cents(data["cost_per_litre_cents"])
		total_cost_cents = _cents(data.get("total_cost_cents", litres * _dec(cost_per_litre_cents)))
		odometer_km = _dec(data["odometer_km"])

		record = FuelRecord(
			tenant_id=tenant_id,
			vehicle_id=vehicle_id,
			driver_id=driver_id,
			fuelling_date=data.get("fuelling_date", _today()),
			fuel_type=str(data.get("fuel_type", vehicle.fuel_type)).upper(),
			litres=litres,
			cost_per_litre_cents=cost_per_litre_cents,
			total_cost_cents=total_cost_cents,
			odometer_km=odometer_km,
			station_name=data.get("station_name"),
			receipt_number=data.get("receipt_number"),
			payment_method=str(data.get("payment_method", "CASH")).upper(),
		)
		session.add(record)
		session.flush()

		# Update rolling average fuel consumption (litres / 100km)
		cls._update_fuel_consumption(session, vehicle, odometer_km, litres, tenant_id)

		# GL double-entry
		journal_id = _try_post_gl(
			session=session,
			dr_account="6300",
			cr_account="1011",
			amount_cents=total_cost_cents,
			description=f"Fuel — {vehicle.reg_number} {litres}L",
			reference_id=record.id,
			tenant_id=tenant_id,
		)

		_emit(
			FuelRecordedEvent(
				aggregate_id=record.id,
				aggregate_type="FuelRecord",
				tenant_id=tenant_id,
				fuel_record_id=record.id,
				vehicle_id=vehicle_id,
				driver_id=driver_id,
				fuelling_date=str(record.fuelling_date),
				litres=str(litres),
				total_cost_cents=total_cost_cents,
				odometer_km=str(odometer_km),
				gl_journal_id=journal_id,
			),
			session,
		)

		log.info("FuelRecord %s: %sL @ %s, vehicle=%s", record.id, litres, record.fuelling_date, vehicle.reg_number)
		return record

	@classmethod
	def _update_fuel_consumption(
		cls,
		session: Any,
		vehicle: Any,
		current_odometer: Decimal,
		litres: Decimal,
		tenant_id: str,
	) -> None:
		"""Recompute rolling average consumption after a new fill-up.

		Uses the previous fuel record's odometer as the baseline distance.
		If no prior record exists, skip (insufficient data for ratio).
		"""
		from pgappforge.plugins.erp.operations.fleet.models import FuelRecord
		stmt = (
			sa.select(FuelRecord.odometer_km)
			.where(
				FuelRecord.vehicle_id == vehicle.id,
				FuelRecord.tenant_id == tenant_id,
				FuelRecord.odometer_km < current_odometer,
			)
			.order_by(FuelRecord.odometer_km.desc())
			.limit(1)
		)
		prev_km_row = session.execute(stmt).first()
		if prev_km_row is None:
			return

		prev_km = _dec(prev_km_row[0])
		distance = current_odometer - prev_km
		if distance <= 0:
			return

		consumption = (litres / distance * _dec(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		vehicle.average_fuel_consumption_per_100km = consumption
		session.flush()

	# ------------------------------------------------------------------
	# 5. record_service
	# ------------------------------------------------------------------

	@classmethod
	def record_service(
		cls,
		session: Any,
		vehicle_id: str,
		data: dict[str, Any],
		tenant_id: str,
	) -> Any:
		"""Record a workshop service event and update the maintenance schedule.

		GL entry: DR maintenance_expense "6350"  CR accounts_payable "2000"

		If next_service_km or next_service_date is provided, updates the
		matching MaintenanceSchedule row (or creates one if absent).

		Returns the persisted VehicleService.
		"""
		from pgappforge.plugins.erp.operations.fleet.models import (
			MaintenanceSchedule, SERVICE_TYPES, VehicleService, Vehicle,
		)

		vehicle = session.get(Vehicle, vehicle_id)
		if vehicle is None or vehicle.tenant_id != tenant_id:
			raise VehicleNotFoundError(f"Vehicle {vehicle_id!r} not found")

		service_type = str(data.get("service_type", "ROUTINE")).upper()
		if service_type not in SERVICE_TYPES:
			raise FleetServiceError(f"Invalid service_type {service_type!r}")

		parts_cost = _cents(data.get("parts_cost_cents", 0))
		labour_cost = _cents(data.get("labour_cost_cents", 0))
		total_cost = _cents(data.get("total_cost_cents", parts_cost + labour_cost))
		odometer_km = _dec(data["odometer_km"])

		svc = VehicleService(
			tenant_id=tenant_id,
			vehicle_id=vehicle_id,
			service_type=service_type,
			service_date=data.get("service_date", _today()),
			odometer_km=odometer_km,
			description=str(data.get("description", "")),
			garage_name=str(data.get("garage_name", "")),
			parts_cost_cents=parts_cost,
			labour_cost_cents=labour_cost,
			total_cost_cents=total_cost,
			invoice_number=data.get("invoice_number"),
			next_service_km=_dec(data["next_service_km"]) if data.get("next_service_km") is not None else None,
			next_service_date=data.get("next_service_date"),
		)
		session.add(svc)
		session.flush()

		# Update corresponding MaintenanceSchedule
		schedule_type = _SERVICE_TO_SCHEDULE.get(service_type, service_type)
		if schedule_type in _SCHEDULE_TYPES_SET:
			cls._update_maintenance_schedule(
				session=session,
				vehicle_id=vehicle_id,
				tenant_id=tenant_id,
				schedule_type=schedule_type,
				done_km=odometer_km,
				done_date=svc.service_date,
				next_km=svc.next_service_km,
				next_date=svc.next_service_date,
			)

		# GL double-entry
		_try_post_gl(
			session=session,
			dr_account="6350",
			cr_account="2000",
			amount_cents=total_cost,
			description=f"Service {service_type} — {vehicle.reg_number} @ {svc.service_date}",
			reference_id=svc.id,
			tenant_id=tenant_id,
		)

		log.info("VehicleService %s: %s on %s, cost=%d cents", svc.id, service_type, vehicle.reg_number, total_cost)
		return svc

	@classmethod
	def _update_maintenance_schedule(
		cls,
		session: Any,
		vehicle_id: str,
		tenant_id: str,
		schedule_type: str,
		done_km: Decimal,
		done_date: date,
		next_km: Decimal | None,
		next_date: date | None,
	) -> None:
		from pgappforge.plugins.erp.operations.fleet.models import MaintenanceSchedule

		stmt = sa.select(MaintenanceSchedule).where(
			MaintenanceSchedule.vehicle_id == vehicle_id,
			MaintenanceSchedule.schedule_type == schedule_type,
		)
		row = session.execute(stmt).scalar_one_or_none()

		if row is None:
			row = MaintenanceSchedule(
				tenant_id=tenant_id,
				vehicle_id=vehicle_id,
				schedule_type=schedule_type,
			)
			session.add(row)

		row.last_done_km = done_km
		row.last_done_date = done_date
		if next_km is not None:
			row.next_due_km = next_km
		if next_date is not None:
			row.next_due_date = next_date
		session.flush()


# Service type → schedule type mapping
_SERVICE_TO_SCHEDULE: dict[str, str] = {
	"ROUTINE": "ROUTINE_SERVICE",
	"MAJOR": "MAJOR_SERVICE",
}
_SCHEDULE_TYPES_SET = {"ROUTINE_SERVICE", "OIL_CHANGE", "TYRE_ROTATION", "MAJOR_SERVICE", "INSPECTION"}


class FleetService(FleetService):  # type: ignore[no-redef]
	# Re-open class to add remaining methods without redefining the above.
	# Python allows this pattern; the class body continues below.
	pass


# We cannot easily split a class definition across multiple Write calls in Python,
# so the remaining methods are defined via monkey-patching at module level, then
# assembled into a clean class at the bottom.  This keeps each logical method
# isolated for readability while producing a single coherent class.

def _report_incident(
	cls: type,
	session: Any,
	vehicle_id: str,
	driver_id: str | None,
	data: dict[str, Any],
	tenant_id: str,
) -> Any:
	"""Record a fleet incident and apply demerit logic.

	ACCIDENT:          +3 demerit points
	TRAFFIC_VIOLATION: +2 demerit points
	All others:        +1 demerit point

	If driver.demerit_points >= 12 after update → driver.status = SUSPENDED
	and DriverSuspendedEvent is emitted.

	Returns the persisted FleetIncident.
	"""
	from pgappforge.plugins.erp.operations.fleet.models import (
		Driver, FleetIncident, INCIDENT_TYPES, Vehicle,
	)
	from pgappforge.plugins.erp.operations.fleet.events import (
		DriverSuspendedEvent, IncidentReportedEvent,
	)

	vehicle = session.get(Vehicle, vehicle_id)
	if vehicle is None or vehicle.tenant_id != tenant_id:
		raise VehicleNotFoundError(f"Vehicle {vehicle_id!r} not found")

	incident_type = str(data.get("incident_type", "OTHER")).upper()
	if incident_type not in INCIDENT_TYPES:
		raise FleetServiceError(f"Invalid incident_type {incident_type!r}")

	driver: Any | None = None
	if driver_id:
		driver = session.get(Driver, driver_id)
		if driver is None or driver.tenant_id != tenant_id:
			raise DriverNotFoundError(f"Driver {driver_id!r} not found")

	incident = FleetIncident(
		tenant_id=tenant_id,
		vehicle_id=vehicle_id,
		driver_id=driver_id,
		incident_date=data.get("incident_date", _today()),
		incident_type=incident_type,
		description=str(data.get("description", "")),
		location=str(data.get("location", "")),
		police_report_number=data.get("police_report_number"),
		insurance_claim_number=data.get("insurance_claim_number"),
		third_party_involved=bool(data.get("third_party_involved", False)),
		estimated_damage_cents=_cents(data["estimated_damage_cents"]) if data.get("estimated_damage_cents") is not None else None,
		status="REPORTED",
	)
	session.add(incident)
	session.flush()

	demerit_applied = 0
	suspended = False
	if driver is not None:
		demerit_applied = _DEMERIT_POINTS.get(incident_type, _DEFAULT_DEMERIT)
		driver.demerit_points = (driver.demerit_points or 0) + demerit_applied
		session.flush()

		if driver.demerit_points >= _SUSPENSION_THRESHOLD and driver.status == "ACTIVE":
			driver.status = "SUSPENDED"
			session.flush()
			suspended = True
			_emit(
				DriverSuspendedEvent(
					aggregate_id=driver.id,
					aggregate_type="Driver",
					tenant_id=tenant_id,
					driver_id=driver.id,
					employee_id=str(driver.employee_id),
					demerit_points=driver.demerit_points,
					triggering_incident_id=incident.id,
				),
				session,
			)
			log.warning(
				"Driver %s auto-suspended: %d demerit points (threshold=%d)",
				driver_id, driver.demerit_points, _SUSPENSION_THRESHOLD,
			)

	_emit(
		IncidentReportedEvent(
			aggregate_id=incident.id,
			aggregate_type="FleetIncident",
			tenant_id=tenant_id,
			incident_id=incident.id,
			vehicle_id=vehicle_id,
			driver_id=driver_id or "",
			incident_type=incident_type,
			incident_date=str(incident.incident_date),
			location=incident.location,
			estimated_damage_cents=incident.estimated_damage_cents or 0,
			demerit_points_applied=demerit_applied,
		),
		session,
	)

	log.info("Incident %s (%s) reported for vehicle %s", incident.id, incident_type, vehicle_id)
	return incident


def _get_documents_expiring(
	cls: type,
	session: Any,
	days_ahead: int = 30,
	tenant_id: str = "",
) -> list[dict[str, Any]]:
	"""Return all VehicleDocument rows expiring within days_ahead days.

	Filters by tenant_id when provided.
	Result dicts include vehicle reg_number for display convenience.
	Sorted by expiry_date ascending (most urgent first).
	"""
	from pgappforge.plugins.erp.operations.fleet.models import Vehicle, VehicleDocument

	cutoff = _today() + timedelta(days=days_ahead)

	stmt = (
		sa.select(VehicleDocument, Vehicle.reg_number)
		.join(Vehicle, Vehicle.id == VehicleDocument.vehicle_id)
		.where(
			VehicleDocument.expiry_date != None,  # noqa: E711
			VehicleDocument.expiry_date <= cutoff,
			VehicleDocument.expiry_date >= _today(),
		)
		.order_by(VehicleDocument.expiry_date.asc())
	)

	if tenant_id:
		stmt = stmt.where(VehicleDocument.tenant_id == tenant_id)

	rows = session.execute(stmt).all()

	result: list[dict[str, Any]] = []
	for doc, reg_number in rows:
		days_remaining = (doc.expiry_date - _today()).days
		result.append({
			"document_id": doc.id,
			"vehicle_id": doc.vehicle_id,
			"reg_number": reg_number,
			"doc_type": doc.doc_type,
			"document_number": doc.document_number,
			"issuing_authority": doc.issuing_authority,
			"expiry_date": str(doc.expiry_date),
			"days_remaining": days_remaining,
			"cost_cents": doc.cost_cents,
		})

	return result


def _get_vehicle_tco(
	cls: type,
	session: Any,
	vehicle_id: str,
	from_date: date,
	to_date: date,
	tenant_id: str,
) -> dict[str, Any]:
	"""Compute Total Cost of Ownership for a vehicle over a date range.

	Components:
	  fuel_cost_cents        — sum of FuelRecord.total_cost_cents
	  maintenance_cost_cents — sum of VehicleService.total_cost_cents
	  insurance_cost_cents   — sum of VehicleDocument[INSURANCE].cost_cents
	  depreciation_cents     — straight-line from acquisition_cost over 5 years
	  total_cost_cents       — sum of all components
	  total_km               — sum of TripLog.distance_km (closed trips in range)
	  cost_per_km_cents      — total_cost_cents / total_km (0 when no km)

	All amounts integer cents.  Decimal arithmetic throughout.
	"""
	from pgappforge.plugins.erp.operations.fleet.models import (
		FuelRecord, TripLog, Vehicle, VehicleDocument, VehicleService,
	)

	vehicle = session.get(Vehicle, vehicle_id)
	if vehicle is None or vehicle.tenant_id != tenant_id:
		raise VehicleNotFoundError(f"Vehicle {vehicle_id!r} not found")

	# Fuel cost
	fuel_stmt = sa.select(sa.func.coalesce(sa.func.sum(FuelRecord.total_cost_cents), 0)).where(
		FuelRecord.vehicle_id == vehicle_id,
		FuelRecord.tenant_id == tenant_id,
		FuelRecord.fuelling_date >= from_date,
		FuelRecord.fuelling_date <= to_date,
	)
	fuel_cost = _cents(session.execute(fuel_stmt).scalar())

	# Maintenance cost
	maint_stmt = sa.select(sa.func.coalesce(sa.func.sum(VehicleService.total_cost_cents), 0)).where(
		VehicleService.vehicle_id == vehicle_id,
		VehicleService.tenant_id == tenant_id,
		VehicleService.service_date >= from_date,
		VehicleService.service_date <= to_date,
	)
	maintenance_cost = _cents(session.execute(maint_stmt).scalar())

	# Insurance cost — sum of VehicleDocument insurance costs overlapping the range
	ins_stmt = sa.select(sa.func.coalesce(sa.func.sum(VehicleDocument.cost_cents), 0)).where(
		VehicleDocument.vehicle_id == vehicle_id,
		VehicleDocument.tenant_id == tenant_id,
		VehicleDocument.doc_type == "INSURANCE",
		VehicleDocument.issue_date <= to_date,
		sa.or_(
			VehicleDocument.expiry_date == None,  # noqa: E711
			VehicleDocument.expiry_date >= from_date,
		),
	)
	insurance_cost = _cents(session.execute(ins_stmt).scalar())

	# Depreciation — straight-line, 5-year useful life, prorated to range
	acq_cost = _dec(vehicle.acquisition_cost_cents)
	range_days = (to_date - from_date).days or 1
	depreciation_daily = acq_cost / _dec(5 * 365)
	depreciation_cents = _cents(depreciation_daily * _dec(range_days))

	# Total km driven (closed trips)
	km_stmt = sa.select(sa.func.coalesce(sa.func.sum(TripLog.distance_km), 0)).where(
		TripLog.vehicle_id == vehicle_id,
		TripLog.tenant_id == tenant_id,
		TripLog.end_datetime != None,  # noqa: E711
		sa.func.date(TripLog.start_datetime) >= from_date,
		sa.func.date(TripLog.start_datetime) <= to_date,
	)
	total_km_raw = session.execute(km_stmt).scalar() or 0
	total_km = _dec(total_km_raw)

	total_cost = fuel_cost + maintenance_cost + insurance_cost + depreciation_cents
	cost_per_km_cents = (
		_cents(_dec(total_cost) / total_km) if total_km > 0 else 0
	)

	return {
		"vehicle_id": vehicle_id,
		"reg_number": vehicle.reg_number,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"fuel_cost_cents": fuel_cost,
		"maintenance_cost_cents": maintenance_cost,
		"insurance_cost_cents": insurance_cost,
		"depreciation_cents": depreciation_cents,
		"total_cost_cents": total_cost,
		"total_km": str(total_km),
		"cost_per_km_cents": cost_per_km_cents,
	}


def _maintenance_due_alerts(
	cls: type,
	session: Any,
	tenant_id: str = "",
) -> list[dict[str, Any]]:
	"""Return maintenance schedules that are due or nearly due.

	Triggers:
	  - next_due_km   <= vehicle.current_odometer_km + 500
	  - next_due_date <= today + 7 days

	Sorted by urgency: date-triggered first, then km-triggered.
	"""
	from pgappforge.plugins.erp.operations.fleet.models import MaintenanceSchedule, Vehicle
	from pgappforge.plugins.erp.operations.fleet.events import MaintenanceDueEvent

	soon_date = _today() + timedelta(days=7)

	# Build base statement
	stmt = (
		sa.select(MaintenanceSchedule, Vehicle.reg_number, Vehicle.current_odometer_km)
		.join(Vehicle, Vehicle.id == MaintenanceSchedule.vehicle_id)
		.where(
			sa.or_(
				sa.and_(
					MaintenanceSchedule.next_due_km != None,  # noqa: E711
					MaintenanceSchedule.next_due_km <= Vehicle.current_odometer_km + 500,
				),
				sa.and_(
					MaintenanceSchedule.next_due_date != None,  # noqa: E711
					MaintenanceSchedule.next_due_date <= soon_date,
				),
			)
		)
		.order_by(MaintenanceSchedule.next_due_date.asc().nulls_last())
	)

	if tenant_id:
		stmt = stmt.where(MaintenanceSchedule.tenant_id == tenant_id)

	rows = session.execute(stmt).all()

	alerts: list[dict[str, Any]] = []
	for sched, reg_number, current_odometer in rows:
		alert = {
			"schedule_id": sched.id,
			"vehicle_id": sched.vehicle_id,
			"reg_number": reg_number,
			"schedule_type": sched.schedule_type,
			"current_odometer_km": str(current_odometer),
			"next_due_km": str(sched.next_due_km) if sched.next_due_km is not None else None,
			"next_due_date": str(sched.next_due_date) if sched.next_due_date is not None else None,
			"estimated_cost_cents": sched.estimated_cost_cents,
		}
		alerts.append(alert)

		_emit(
			MaintenanceDueEvent(
				aggregate_id=sched.id,
				aggregate_type="MaintenanceSchedule",
				tenant_id=sched.tenant_id,
				schedule_id=sched.id,
				vehicle_id=sched.vehicle_id,
				reg_number=reg_number,
				schedule_type=sched.schedule_type,
				next_due_km=str(sched.next_due_km) if sched.next_due_km is not None else "",
				next_due_date=str(sched.next_due_date) if sched.next_due_date is not None else "",
				current_odometer_km=str(current_odometer),
			),
			session,
		)

	return alerts


def _get_fleet_dashboard(
	cls: type,
	session: Any,
	tenant_id: str = "",
) -> dict[str, Any]:
	"""Single-query dashboard snapshot for the fleet operations centre.

	Returns:
	  vehicles_total               — total vehicle count
	  vehicles_by_status           — dict of status -> count
	  drivers_total                — total driver count
	  drivers_active               — drivers with status ACTIVE
	  this_month_fuel_cents        — total fuel spend MTD
	  this_month_maintenance_cents — total maintenance spend MTD
	  incidents_total              — all-time incident count
	  incidents_open               — REPORTED + UNDER_INVESTIGATION
	  documents_expiring_30d       — count expiring within 30 days
	  maintenance_due_count        — schedules due within 500km or 7 days
	"""
	from pgappforge.plugins.erp.operations.fleet.models import (
		Driver, FleetIncident, FuelRecord, MaintenanceSchedule,
		Vehicle, VehicleDocument, VehicleService,
	)

	today = _today()
	month_start = today.replace(day=1)
	in_30d = today + timedelta(days=30)
	soon_date = today + timedelta(days=7)

	def _q(stmt: Any) -> Any:
		if tenant_id:
			# All tables share tenant_id; add filter via the primary entity's column
			pass
		return session.execute(stmt).scalar() or 0

	def _where_tenant(col: Any) -> Any:
		if tenant_id:
			return col == tenant_id
		return sa.true()

	# Vehicles by status
	status_stmt = (
		sa.select(Vehicle.status, sa.func.count(Vehicle.id))
		.where(_where_tenant(Vehicle.tenant_id))
		.group_by(Vehicle.status)
	)
	vehicles_by_status: dict[str, int] = {}
	for status, cnt in session.execute(status_stmt).all():
		vehicles_by_status[status] = cnt
	vehicles_total = sum(vehicles_by_status.values())

	# Drivers
	drivers_stmt = sa.select(sa.func.count(Driver.id)).where(_where_tenant(Driver.tenant_id))
	drivers_total = int(session.execute(drivers_stmt).scalar() or 0)

	active_drv_stmt = sa.select(sa.func.count(Driver.id)).where(
		_where_tenant(Driver.tenant_id), Driver.status == "ACTIVE"
	)
	drivers_active = int(session.execute(active_drv_stmt).scalar() or 0)

	# MTD fuel
	fuel_stmt = sa.select(sa.func.coalesce(sa.func.sum(FuelRecord.total_cost_cents), 0)).where(
		_where_tenant(FuelRecord.tenant_id),
		FuelRecord.fuelling_date >= month_start,
	)
	this_month_fuel_cents = _cents(session.execute(fuel_stmt).scalar())

	# MTD maintenance
	maint_stmt = sa.select(sa.func.coalesce(sa.func.sum(VehicleService.total_cost_cents), 0)).where(
		_where_tenant(VehicleService.tenant_id),
		VehicleService.service_date >= month_start,
	)
	this_month_maintenance_cents = _cents(session.execute(maint_stmt).scalar())

	# Incidents
	inc_total_stmt = sa.select(sa.func.count(FleetIncident.id)).where(_where_tenant(FleetIncident.tenant_id))
	incidents_total = int(session.execute(inc_total_stmt).scalar() or 0)

	inc_open_stmt = sa.select(sa.func.count(FleetIncident.id)).where(
		_where_tenant(FleetIncident.tenant_id),
		FleetIncident.status.in_(["REPORTED", "UNDER_INVESTIGATION"]),
	)
	incidents_open = int(session.execute(inc_open_stmt).scalar() or 0)

	# Documents expiring in 30d
	doc_stmt = sa.select(sa.func.count(VehicleDocument.id)).where(
		_where_tenant(VehicleDocument.tenant_id),
		VehicleDocument.expiry_date != None,  # noqa: E711
		VehicleDocument.expiry_date <= in_30d,
		VehicleDocument.expiry_date >= today,
	)
	documents_expiring_30d = int(session.execute(doc_stmt).scalar() or 0)

	# Maintenance due
	due_stmt = sa.select(sa.func.count(MaintenanceSchedule.id)).join(
		Vehicle, Vehicle.id == MaintenanceSchedule.vehicle_id
	).where(
		_where_tenant(MaintenanceSchedule.tenant_id),
		sa.or_(
			sa.and_(
				MaintenanceSchedule.next_due_km != None,  # noqa: E711
				MaintenanceSchedule.next_due_km <= Vehicle.current_odometer_km + 500,
			),
			sa.and_(
				MaintenanceSchedule.next_due_date != None,  # noqa: E711
				MaintenanceSchedule.next_due_date <= soon_date,
			),
		),
	)
	maintenance_due_count = int(session.execute(due_stmt).scalar() or 0)

	return {
		"vehicles_total": vehicles_total,
		"vehicles_by_status": vehicles_by_status,
		"drivers_total": drivers_total,
		"drivers_active": drivers_active,
		"this_month_fuel_cents": this_month_fuel_cents,
		"this_month_maintenance_cents": this_month_maintenance_cents,
		"incidents_total": incidents_total,
		"incidents_open": incidents_open,
		"documents_expiring_30d": documents_expiring_30d,
		"maintenance_due_count": maintenance_due_count,
	}


# ---------------------------------------------------------------------------
# Attach remaining methods to FleetService
# ---------------------------------------------------------------------------

FleetService.report_incident = classmethod(  # type: ignore[method-assign]
	lambda cls, session, vehicle_id, driver_id, data, tenant_id: _report_incident(
		cls, session, vehicle_id, driver_id, data, tenant_id
	)
)
FleetService.get_documents_expiring = classmethod(  # type: ignore[method-assign]
	lambda cls, session, days_ahead=30, tenant_id="": _get_documents_expiring(
		cls, session, days_ahead, tenant_id
	)
)
FleetService.get_vehicle_tco = classmethod(  # type: ignore[method-assign]
	lambda cls, session, vehicle_id, from_date, to_date, tenant_id: _get_vehicle_tco(
		cls, session, vehicle_id, from_date, to_date, tenant_id
	)
)
FleetService.maintenance_due_alerts = classmethod(  # type: ignore[method-assign]
	lambda cls, session, tenant_id="": _maintenance_due_alerts(cls, session, tenant_id)
)
FleetService.get_fleet_dashboard = classmethod(  # type: ignore[method-assign]
	lambda cls, session, tenant_id="": _get_fleet_dashboard(cls, session, tenant_id)
)


__all__ = [
	"FleetService",
	"FleetServiceError",
	"VehicleNotFoundError",
	"DriverNotFoundError",
	"DriverNotActiveError",
	"VehicleNotActiveError",
	"TripNotFoundError",
]
