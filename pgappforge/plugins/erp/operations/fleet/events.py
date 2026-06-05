"""
pgappforge/plugins/erp/operations/fleet/events.py

Domain events for the Fleet Management plugin.

All monetary amounts are integer cents — never float.
Odometer / distance values are Decimal-compatible strings.

Events emitted:
  fleet.vehicle.registered         — new vehicle added to the register
  fleet.driver.assigned            — driver assigned to a vehicle
  fleet.trip.completed             — trip log closed with end odometer
  fleet.fuel.recorded              — fuelling transaction posted
  fleet.incident.reported          — accident/breakdown/violation logged
  fleet.driver.suspended           — driver auto-suspended on demerit threshold
  fleet.maintenance.due            — maintenance schedule alert triggered
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Vehicle events
# ---------------------------------------------------------------------------

@dataclass
class VehicleRegisteredEvent(DomainEvent):
	"""Emitted when a new Vehicle row is created."""
	event_type: str = "fleet.vehicle.registered"
	vehicle_id: str = ""
	reg_number: str = ""
	make: str = ""
	model: str = ""
	year_of_manufacture: int = 0
	fuel_type: str = ""
	body_type: str = ""
	acquisition_cost_cents: int = 0


@dataclass
class DriverAssignedEvent(DomainEvent):
	"""Emitted when a driver is assigned to a vehicle."""
	event_type: str = "fleet.driver.assigned"
	vehicle_id: str = ""
	reg_number: str = ""
	driver_id: str = ""           # Driver.id (fleet driver record)
	employee_id: str = ""         # Driver.employee_id (HR reference)


# ---------------------------------------------------------------------------
# Trip events
# ---------------------------------------------------------------------------

@dataclass
class TripCompletedEvent(DomainEvent):
	"""Emitted when a TripLog is closed (end_odometer set)."""
	event_type: str = "fleet.trip.completed"
	trip_id: str = ""
	vehicle_id: str = ""
	driver_id: str = ""
	trip_type: str = ""           # OFFICIAL / PERSONAL / DELIVERY / PASSENGER
	distance_km: str = ""         # Decimal string
	fuel_used_litres: str = ""    # Decimal string; "" when not recorded
	start_datetime: str = ""      # ISO datetime
	end_datetime: str = ""        # ISO datetime


# ---------------------------------------------------------------------------
# Fuel events
# ---------------------------------------------------------------------------

@dataclass
class FuelRecordedEvent(DomainEvent):
	"""Emitted after a FuelRecord is persisted and GL entry posted."""
	event_type: str = "fleet.fuel.recorded"
	fuel_record_id: str = ""
	vehicle_id: str = ""
	driver_id: str = ""
	fuelling_date: str = ""       # ISO date
	litres: str = ""              # Decimal string
	total_cost_cents: int = 0
	odometer_km: str = ""         # Decimal string
	gl_journal_id: str = ""       # populated when GL plugin is active


# ---------------------------------------------------------------------------
# Incident events
# ---------------------------------------------------------------------------

@dataclass
class IncidentReportedEvent(DomainEvent):
	"""Emitted when a FleetIncident is created."""
	event_type: str = "fleet.incident.reported"
	incident_id: str = ""
	vehicle_id: str = ""
	driver_id: str = ""           # "" when no driver linked
	incident_type: str = ""       # ACCIDENT / BREAKDOWN / TRAFFIC_VIOLATION / THEFT / VANDALISM / OTHER
	incident_date: str = ""       # ISO date
	location: str = ""
	estimated_damage_cents: int = 0
	demerit_points_applied: int = 0


@dataclass
class DriverSuspendedEvent(DomainEvent):
	"""Emitted when a driver is auto-suspended after reaching 12 demerit points."""
	event_type: str = "fleet.driver.suspended"
	driver_id: str = ""
	employee_id: str = ""
	demerit_points: int = 0
	triggering_incident_id: str = ""


# ---------------------------------------------------------------------------
# Maintenance events
# ---------------------------------------------------------------------------

@dataclass
class MaintenanceDueEvent(DomainEvent):
	"""Emitted when maintenance_due_alerts() detects an overdue schedule."""
	event_type: str = "fleet.maintenance.due"
	schedule_id: str = ""
	vehicle_id: str = ""
	reg_number: str = ""
	schedule_type: str = ""       # ROUTINE_SERVICE / OIL_CHANGE / etc.
	next_due_km: str = ""         # Decimal string; "" when trigger is date-based
	next_due_date: str = ""       # ISO date; "" when trigger is km-based
	current_odometer_km: str = "" # Decimal string


__all__ = [
	"VehicleRegisteredEvent",
	"DriverAssignedEvent",
	"TripCompletedEvent",
	"FuelRecordedEvent",
	"IncidentReportedEvent",
	"DriverSuspendedEvent",
	"MaintenanceDueEvent",
]
