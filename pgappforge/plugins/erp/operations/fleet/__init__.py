"""
pgappforge/plugins/erp/operations/fleet/__init__.py

Fleet Management — vehicle register, driver management, fuel, maintenance,
KRA compliance, TCO analytics.

Domain: operations
Depends on: foundation

Scope:
  - Vehicle registry (reg number, make/model, chassis, GPS device)
  - Driver register with NTSA licence, PSV badge, medical cert tracking
  - Trip logging with odometer-based distance computation
  - Fuel purchase recording with GL double-entry and rolling consumption
  - Workshop service recording with GL double-entry and schedule updates
  - Incident management with demerit logic and auto-suspension
  - Compliance document expiry alerts (KRA road tax, insurance, inspection)
  - Total Cost of Ownership analytics (fuel + maintenance + insurance + depreciation)
  - Maintenance schedule due-alerts (km and calendar triggers)
  - Fleet operations dashboard

Events emitted:
  fleet.vehicle.registered
  fleet.driver.assigned
  fleet.trip.completed
  fleet.fuel.recorded
  fleet.incident.reported
  fleet.driver.suspended
  fleet.maintenance.due

Events consumed:
  (none — fleet is a standalone operations plugin)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.fleet",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.fleet import FleetPlugin
    plugin = FleetPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class FleetPlugin(BasePlugin):
	"""Fleet Management plugin.

	Provides:
	  - Vehicle registry with full KRA-compliant document tracking
	  - Driver register with NTSA licence / PSV badge / medical cert expiry alerts
	  - Trip log with odometer validation and driver/vehicle total updates
	  - Fuel recording with GL double-entry (DR 6300 / CR 1011) and rolling
	    litres-per-100km consumption tracking
	  - Workshop service recording with GL double-entry (DR 6350 / CR 2000)
	    and automatic MaintenanceSchedule refresh
	  - Incident management with configurable demerit points and auto-suspension
	    at >= 12 points
	  - Compliance document expiry alerts (30-day horizon, configurable per doc)
	  - TCO report: fuel + maintenance + insurance + straight-line depreciation,
	    with cost-per-km output
	  - Maintenance due alerts: km-based (within 500km) and calendar-based (7 days)
	  - Fleet operations dashboard with MTD spend, open incidents, expiring docs
	"""

	name = "fleet"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="fleet",
			version="1.0.0",
			description=(
				"Fleet Management — vehicle register, driver management, fuel, "
				"maintenance, KRA compliance, TCO analytics."
			),
			author="PgAppForge Contributors",
			tags=["erp", "operations", "fleet", "vehicles", "drivers", "maintenance", "kenya", "kra"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_fleet_vehicle_list",
				"can_fleet_vehicle_write",
				"can_fleet_vehicle_dispose",
				"can_fleet_document_list",
				"can_fleet_document_write",
				"can_fleet_driver_list",
				"can_fleet_driver_write",
				"can_fleet_driver_suspend",
				"can_fleet_trip_list",
				"can_fleet_trip_create",
				"can_fleet_fuel_list",
				"can_fleet_fuel_create",
				"can_fleet_service_list",
				"can_fleet_service_create",
				"can_fleet_incident_list",
				"can_fleet_incident_create",
				"can_fleet_incident_investigate",
				"can_fleet_incident_close",
				"can_fleet_schedule_list",
				"can_fleet_schedule_write",
				"can_fleet_reports",
				"can_fleet_dashboard",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"fleet.vehicle.registered",
			"fleet.driver.assigned",
			"fleet.trip.completed",
			"fleet.fuel.recorded",
			"fleet.incident.reported",
			"fleet.driver.suspended",
			"fleet.maintenance.due",
		]

	def subscribe_to(self) -> list[str]:
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"FLEET_MENU_CATEGORY": "Fleet",
			"FLEET_DEMERIT_SUSPENSION_THRESHOLD": 12,
			"FLEET_MAINTENANCE_KM_ALERT_BUFFER": 500,
			"FLEET_MAINTENANCE_DATE_ALERT_DAYS": 7,
			"FLEET_DOCUMENT_ALERT_DAYS": 30,
			"FLEET_GL_FUEL_EXPENSE_ACCOUNT": "6300",
			"FLEET_GL_CASH_ACCOUNT": "1011",
			"FLEET_GL_MAINTENANCE_EXPENSE_ACCOUNT": "6350",
			"FLEET_GL_AP_ACCOUNT": "2000",
			"FLEET_DEPRECIATION_YEARS": 5,
		}
		self.config = {**defaults, **self.config}
		log.info("FleetPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		cat = self.config.get("FLEET_MENU_CATEGORY", "Fleet")
		log.info(
			"FleetPlugin: views would be registered under category %r (views.py not yet added)", cat
		)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.fleet.models import (
			Driver,
			FleetIncident,
			FuelRecord,
			MaintenanceSchedule,
			TripLog,
			Vehicle,
			VehicleDocument,
			VehicleService,
		)
		return [
			Vehicle,
			VehicleDocument,
			Driver,
			TripLog,
			FuelRecord,
			VehicleService,
			FleetIncident,
			MaintenanceSchedule,
		]

	def activate(self) -> None:
		"""Full plugin activation: initialise config, register models."""
		self.initialize()
		models = self.register_models()
		log.info("FleetPlugin activated — %d models registered", len(models))
		return models


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> FleetPlugin:
	"""Construct a FleetPlugin without activating it."""
	return FleetPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.fleet.models import (  # noqa: E402
	Driver,
	FleetIncident,
	FuelRecord,
	MaintenanceSchedule,
	TripLog,
	Vehicle,
	VehicleDocument,
	VehicleService,
	# enum sets
	BODY_TYPES,
	DOC_TYPES,
	DRIVER_STATUSES,
	FUEL_TYPES,
	INCIDENT_STATUSES,
	INCIDENT_TYPES,
	PAYMENT_METHODS,
	SCHEDULE_TYPES,
	SERVICE_TYPES,
	TRIP_TYPES,
	VEHICLE_STATUSES,
)
from pgappforge.plugins.erp.operations.fleet.events import (  # noqa: E402
	DriverAssignedEvent,
	DriverSuspendedEvent,
	FuelRecordedEvent,
	IncidentReportedEvent,
	MaintenanceDueEvent,
	TripCompletedEvent,
	VehicleRegisteredEvent,
)
from pgappforge.plugins.erp.operations.fleet.services import (  # noqa: E402
	FleetService,
	FleetServiceError,
	VehicleNotFoundError,
	DriverNotFoundError,
	DriverNotActiveError,
	VehicleNotActiveError,
	TripNotFoundError,
)

__all__ = [
	# plugin
	"FleetPlugin",
	"create_plugin",
	# models
	"Vehicle",
	"VehicleDocument",
	"Driver",
	"TripLog",
	"FuelRecord",
	"VehicleService",
	"FleetIncident",
	"MaintenanceSchedule",
	# enum sets
	"FUEL_TYPES",
	"BODY_TYPES",
	"VEHICLE_STATUSES",
	"DOC_TYPES",
	"DRIVER_STATUSES",
	"TRIP_TYPES",
	"PAYMENT_METHODS",
	"SERVICE_TYPES",
	"INCIDENT_TYPES",
	"INCIDENT_STATUSES",
	"SCHEDULE_TYPES",
	# events
	"VehicleRegisteredEvent",
	"DriverAssignedEvent",
	"TripCompletedEvent",
	"FuelRecordedEvent",
	"IncidentReportedEvent",
	"DriverSuspendedEvent",
	"MaintenanceDueEvent",
	# services
	"FleetService",
	"FleetServiceError",
	"VehicleNotFoundError",
	"DriverNotFoundError",
	"DriverNotActiveError",
	"VehicleNotActiveError",
	"TripNotFoundError",
]
