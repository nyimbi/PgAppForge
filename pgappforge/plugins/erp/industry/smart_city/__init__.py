"""
pgappforge/plugins/erp/industry/smart_city/__init__.py

SmartCityPlugin — Smart City / IoT platform plugin (FIWARE-aligned).

Depends on: foundation

Events emitted
--------------
  smart_city.device.registered
  smart_city.device.online
  smart_city.device.offline
  smart_city.device.low_battery
  smart_city.telemetry.ingested
  smart_city.telemetry.anomaly
  smart_city.asset.faulted
  smart_city.asset.maintenance_dispatched
  smart_city.alert.issued
  smart_city.alert.acknowledged
  smart_city.alert.resolved
  smart_city.service_request.created
  smart_city.service_request.routed
  smart_city.service_request.resolved

Events consumed
---------------
  foundation.party.created  — citizen constituent registration hook (stub)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.smart_city",
    ]

PostGIS note
------------
The models use JSONB {lat, lng} for geometry columns at import time to avoid
a hard PostGIS dependency.  After deploying the plugin, run the provided
Alembic migration to convert location columns to GEOMETRY(Point, 4326) for
full spatial query support (ST_DWithin, ST_Within, etc.).
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SmartCityPlugin(BasePlugin):
	"""Smart City / IoT platform plugin (FIWARE Smart Data Models aligned).

	Provides:
	  - IoT device registry with online/offline lifecycle
	  - Time-series telemetry ingestion (batched)
	  - Statistical anomaly detection (z-score)
	  - Smart asset catalogue with maintenance dispatch
	  - City alert management (device / citizen / system sources)
	  - Digital twin state snapshots
	  - Citizen service request routing (311-style)
	  - City operations dashboard with traffic density
	"""

	name = "smart_city"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="smart_city",
			version="1.0.0",
			description=(
				"Smart City / IoT platform — FIWARE-aligned device registry, sensor telemetry, "
				"smart asset management, city alerts, digital twins, and 311 service requests."
			),
			author="PgAppForge Contributors",
			tags=["industry", "smart-city", "iot", "fiware", "telemetry", "311"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_sc_device_list",
				"can_sc_device_write",
				"can_sc_device_telemetry",
				"can_sc_asset_list",
				"can_sc_asset_write",
				"can_sc_asset_maintenance",
				"can_sc_alert_list",
				"can_sc_alert_write",
				"can_sc_alert_acknowledge",
				"can_sc_twin_list",
				"can_sc_service_request_list",
				"can_sc_service_request_write",
				"can_sc_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"smart_city.device.registered",
			"smart_city.device.online",
			"smart_city.device.offline",
			"smart_city.device.low_battery",
			"smart_city.telemetry.ingested",
			"smart_city.telemetry.anomaly",
			"smart_city.asset.faulted",
			"smart_city.asset.maintenance_dispatched",
			"smart_city.alert.issued",
			"smart_city.alert.acknowledged",
			"smart_city.alert.resolved",
			"smart_city.service_request.created",
			"smart_city.service_request.routed",
			"smart_city.service_request.resolved",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"foundation.party.created",  # stub: citizen constituent registration
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"SC_MENU_CATEGORY": "Smart City / IoT",
			"SC_ANOMALY_Z_THRESHOLD": 3.0,
			"SC_DEVICE_OFFLINE_MINUTES": 15,
			"SC_TELEMETRY_BATCH_MAX": 1000,
			"SC_DEFAULT_CONGESTION_THRESHOLD_OCC": 0.8,
			"SC_SLA_DEFAULT_HOURS": 72,
		}
		self.config = {**defaults, **self.config}
		log.info("SmartCityPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		self._subscribe_to_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.smart_city.views import (
			AlertView,
			CityDashboard,
			DeviceView,
			ServiceRequestView,
		)

		cat = self.config.get("SC_MENU_CATEGORY", "Smart City / IoT")
		self.add_view(DeviceView, "IoT Devices", icon="fa-microchip", category=cat)
		self.add_view(AlertView, "City Alerts", icon="fa-bell", category=cat)
		self.add_view(ServiceRequestView, "Service Requests", icon="fa-ticket", category=cat)
		self.add_view(CityDashboard, "City Dashboard", icon="fa-city", category=cat)
		log.info("SmartCityPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.smart_city.models import (
			CityAlert,
			CityServiceRequest,
			DigitalTwin,
			IoTDevice,
			SensorReading,
			SmartAsset,
		)
		return [IoTDevice, SensorReading, SmartAsset, CityAlert, DigitalTwin, CityServiceRequest]

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("foundation.party.created", self._on_party_created)
		except Exception as exc:
			log.warning("SmartCityPlugin._subscribe_to_events failed: %s", exc)

	def _on_party_created(self, event: Any) -> None:
		log.debug(
			"SmartCityPlugin._on_party_created: party=%s — constituent registration stub",
			getattr(event, "party_id", "?"),
		)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> SmartCityPlugin:
	"""Construct and return a SmartCityPlugin bound to *appbuilder*."""
	return SmartCityPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.smart_city.models import (  # noqa: E402
	CityAlert,
	CityServiceRequest,
	DigitalTwin,
	IoTDevice,
	SensorReading,
	SmartAsset,
)
from pgappforge.plugins.erp.industry.smart_city.events import (  # noqa: E402
	AnomalyDetectedEvent,
	AssetFaultedEvent,
	CityAlertAcknowledgedEvent,
	CityAlertIssuedEvent,
	CityAlertResolvedEvent,
	DeviceLowBatteryEvent,
	DeviceOfflineEvent,
	DeviceOnlineEvent,
	DeviceRegisteredEvent,
	MaintenanceDispatchedEvent,
	ServiceRequestCreatedEvent,
	ServiceRequestResolvedEvent,
	ServiceRequestRoutedEvent,
	TelemetryIngestedEvent,
)
from pgappforge.plugins.erp.industry.smart_city.services import (  # noqa: E402
	AssetNotFoundError,
	DeviceNotFoundError,
	ServiceRequestNotFoundError,
	SmartCityService,
	SmartCityServiceError,
)

__all__ = [
	# plugin
	"SmartCityPlugin",
	"create_plugin",
	# models
	"IoTDevice",
	"SensorReading",
	"SmartAsset",
	"CityAlert",
	"DigitalTwin",
	"CityServiceRequest",
	# events
	"DeviceRegisteredEvent",
	"DeviceOnlineEvent",
	"DeviceOfflineEvent",
	"DeviceLowBatteryEvent",
	"TelemetryIngestedEvent",
	"AnomalyDetectedEvent",
	"AssetFaultedEvent",
	"MaintenanceDispatchedEvent",
	"CityAlertIssuedEvent",
	"CityAlertAcknowledgedEvent",
	"CityAlertResolvedEvent",
	"ServiceRequestCreatedEvent",
	"ServiceRequestRoutedEvent",
	"ServiceRequestResolvedEvent",
	# services
	"SmartCityService",
	"SmartCityServiceError",
	"DeviceNotFoundError",
	"AssetNotFoundError",
	"ServiceRequestNotFoundError",
]
