"""
pgappforge/plugins/erp/industry/smart_city/events.py

Domain events for the Smart City / IoT plugin.

Payloads are intentionally lean — location coordinates and sensor values
are not embedded to avoid event log bloat; consumers should fetch detail
via the service layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Device lifecycle
# ---------------------------------------------------------------------------

@dataclass
class DeviceRegisteredEvent(DomainEvent):
	"""New IoT device registered in the platform."""
	event_type: str = "smart_city.device.registered"
	device_id: str = ""
	device_type: str = ""
	protocol: str = ""


@dataclass
class DeviceOnlineEvent(DomainEvent):
	"""Device transitioned to online state."""
	event_type: str = "smart_city.device.online"
	device_id: str = ""
	device_type: str = ""


@dataclass
class DeviceOfflineEvent(DomainEvent):
	"""Device not seen for longer than expected heartbeat window."""
	event_type: str = "smart_city.device.offline"
	device_id: str = ""
	device_type: str = ""
	last_seen_at: str = ""   # ISO timestamp string


@dataclass
class DeviceLowBatteryEvent(DomainEvent):
	"""Device battery dropped below threshold."""
	event_type: str = "smart_city.device.low_battery"
	device_id: str = ""
	battery_level_pct: int = 0


# ---------------------------------------------------------------------------
# Telemetry / anomaly detection
# ---------------------------------------------------------------------------

@dataclass
class TelemetryIngestedEvent(DomainEvent):
	"""Batch of sensor readings persisted."""
	event_type: str = "smart_city.telemetry.ingested"
	device_id: str = ""
	reading_count: int = 0
	parameter: str = ""


@dataclass
class AnomalyDetectedEvent(DomainEvent):
	"""Statistical anomaly detected in device telemetry."""
	event_type: str = "smart_city.telemetry.anomaly"
	device_id: str = ""
	parameter: str = ""
	anomaly_count: int = 0
	lookback_hours: int = 24


# ---------------------------------------------------------------------------
# Asset events
# ---------------------------------------------------------------------------

@dataclass
class AssetFaultedEvent(DomainEvent):
	"""Smart asset transitioned to FAULT status."""
	event_type: str = "smart_city.asset.faulted"
	asset_id: str = ""
	asset_type: str = ""
	zone: str = ""


@dataclass
class MaintenanceDispatchedEvent(DomainEvent):
	"""Maintenance crew dispatched for a faulted asset."""
	event_type: str = "smart_city.asset.maintenance_dispatched"
	asset_id: str = ""
	asset_type: str = ""
	fault_description: str = ""


# ---------------------------------------------------------------------------
# City alerts
# ---------------------------------------------------------------------------

@dataclass
class CityAlertIssuedEvent(DomainEvent):
	"""New city alert issued."""
	event_type: str = "smart_city.alert.issued"
	alert_id: str = ""
	alert_type: str = ""
	severity: str = ""
	source_type: str = ""


@dataclass
class CityAlertAcknowledgedEvent(DomainEvent):
	"""City alert acknowledged by an operator."""
	event_type: str = "smart_city.alert.acknowledged"
	alert_id: str = ""
	acknowledged_by: str = ""


@dataclass
class CityAlertResolvedEvent(DomainEvent):
	"""City alert marked RESOLVED."""
	event_type: str = "smart_city.alert.resolved"
	alert_id: str = ""


# ---------------------------------------------------------------------------
# Service requests
# ---------------------------------------------------------------------------

@dataclass
class ServiceRequestCreatedEvent(DomainEvent):
	"""New citizen service request submitted."""
	event_type: str = "smart_city.service_request.created"
	request_id: str = ""
	request_type: str = ""
	channel: str = ""


@dataclass
class ServiceRequestRoutedEvent(DomainEvent):
	"""Service request assigned to a department with SLA."""
	event_type: str = "smart_city.service_request.routed"
	request_id: str = ""
	assigned_to: str = ""
	sla_hours: int = 0


@dataclass
class ServiceRequestResolvedEvent(DomainEvent):
	"""Service request marked RESOLVED."""
	event_type: str = "smart_city.service_request.resolved"
	request_id: str = ""
	request_type: str = ""


__all__ = [
	"emit_event",
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
]
