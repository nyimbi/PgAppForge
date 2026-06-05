"""
pgappforge/plugins/erp/industry/smart_city/models.py

SQLAlchemy models for the Smart City / IoT plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Geometry columns: use String(255) as opaque placeholder — real deployments
    add PostGIS GEOMETRY via Alembic migration with op.execute(); keeping String
    here avoids a hard PostGIS dependency at import time while making the intent
    clear via column comments.
  - JSONB for semi-structured payloads (address, raw_payload, etc.)
  - AuditMixin on all mutable entities

Table name convention: sc_<entity>
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

DEVICE_TYPE = ("SENSOR", "ACTUATOR", "GATEWAY", "CAMERA", "METER")
PROTOCOL = ("MQTT", "HTTP", "COAP", "MODBUS", "BACnet")
READING_QUALITY = ("GOOD", "SUSPECT", "BAD")

ASSET_TYPE = (
	"STREETLIGHT", "PARKING_METER", "WASTE_BIN", "BENCH", "SIGN", "TRAFFIC_LIGHT"
)
ASSET_STATUS = ("OPERATIONAL", "MAINTENANCE", "FAULT", "REPLACED")

ALERT_SOURCE = ("DEVICE", "CITIZEN", "SYSTEM")
ALERT_SEVERITY = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
ALERT_STATUS = ("ACTIVE", "ACKNOWLEDGED", "RESOLVED")

SERVICE_CHANNEL = ("APP", "WEB", "PHONE", "311")
SERVICE_STATUS = ("OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED")


# ---------------------------------------------------------------------------
# IoTDevice
# ---------------------------------------------------------------------------

class IoTDevice(AuditMixin, Model):
	"""Physical or virtual IoT device registry.

	location is stored as a JSONB {lat, lng} stub; PostGIS GEOMETRY(Point,4326)
	is added via migration for production deployments.
	battery_level_pct NULL = mains-powered device.
	owner_id soft-references foundation.Party (no FK enforced cross-domain).
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_iot_device"
	__table_args__ = (
		UniqueConstraint("tenant_id", "device_id", name="uq_sc_iot_device_tenant_device"),
		Index("ix_sc_iot_device_tenant", "tenant_id"),
		Index("ix_sc_iot_device_type", "device_type"),
		Index("ix_sc_iot_device_online", "is_online"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	device_id = Column(String(100), nullable=False, comment="Unique device identifier per tenant")
	device_name = Column(String(255), nullable=False)
	device_type = Column(
		String(20),
		nullable=False,
		comment="SENSOR/ACTUATOR/GATEWAY/CAMERA/METER",
	)
	protocol = Column(
		String(20),
		nullable=False,
		default="MQTT",
		comment="MQTT/HTTP/COAP/MODBUS/BACnet",
	)

	# Geometry stored as JSONB {lat, lng}; PostGIS column added via migration
	location = Column(
		JSONB,
		nullable=True,
		comment="GEOMETRY(Point,4326) — stored as {lat, lng} until PostGIS migration applied",
	)
	address = Column(JSONB, nullable=True, comment="Structured address object")
	installation_date = Column(Date, nullable=True)
	firmware_version = Column(String(50), nullable=True)

	battery_level_pct = Column(
		Integer,
		nullable=True,
		comment="0–100; NULL = mains-powered",
	)
	is_online = Column(Boolean, nullable=False, default=False, server_default="false")
	last_seen_at = Column(DateTime(timezone=True), nullable=True)
	tags = Column(ARRAY(Text), nullable=False, default=list, server_default="{}")
	owner_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="Soft FK to foundation.Party",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	readings: list[SensorReading] = relationship(
		"SensorReading",
		back_populates="device",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<IoTDevice {self.device_id!r} type={self.device_type!r} online={self.is_online}>"


# ---------------------------------------------------------------------------
# SensorReading
# ---------------------------------------------------------------------------

class SensorReading(AuditMixin, Model):
	"""Time-series sensor reading from an IoTDevice.

	value NUMERIC(20,6) accommodates fine-grained measurements across domains
	(energy kWh, air quality ppb, temperature °C, etc.).
	quality: GOOD/SUSPECT/BAD per IEC 61968 data quality model.
	raw_payload JSONB: full device payload for re-processing/debugging.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_sensor_reading"
	__table_args__ = (
		Index("ix_sc_reading_device", "device_id"),
		Index("ix_sc_reading_measured_at", "measured_at"),
		Index("ix_sc_reading_parameter", "parameter"),
		Index("ix_sc_reading_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	device_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_iot_device.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	measured_at = Column(DateTime(timezone=True), nullable=False)
	parameter = Column(String(100), nullable=False, comment="e.g. temperature, co2_ppm, fill_level")
	value = Column(Numeric(20, 6), nullable=False)
	unit = Column(String(20), nullable=False, comment="SI unit or unit code")
	quality = Column(
		String(10),
		nullable=False,
		default="GOOD",
		server_default="GOOD",
		comment="GOOD/SUSPECT/BAD",
	)
	raw_payload = Column(JSONB, nullable=True, comment="Full device payload for replay/debug")

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	device: IoTDevice = relationship("IoTDevice", back_populates="readings", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<SensorReading device={self.device_id!r} "
			f"param={self.parameter!r} val={self.value} {self.unit}>"
		)


# ---------------------------------------------------------------------------
# SmartAsset
# ---------------------------------------------------------------------------

class SmartAsset(AuditMixin, Model):
	"""Physical smart city asset (streetlight, bin, sign, etc.).

	maintenance_schedule JSONB: {frequency, last_date, next_date, notes}
	device_id nullable — not all assets have IoT sensors attached.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_smart_asset"
	__table_args__ = (
		Index("ix_sc_asset_tenant", "tenant_id"),
		Index("ix_sc_asset_type", "asset_type"),
		Index("ix_sc_asset_status", "status"),
		Index("ix_sc_asset_zone", "zone"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	asset_name = Column(String(255), nullable=False)
	asset_type = Column(
		String(20),
		nullable=False,
		comment="STREETLIGHT/PARKING_METER/WASTE_BIN/BENCH/SIGN/TRAFFIC_LIGHT",
	)
	location = Column(
		JSONB,
		nullable=True,
		comment="GEOMETRY(Point,4326) — stored as {lat, lng} until PostGIS migration applied",
	)
	zone = Column(String(100), nullable=True, comment="City zone / district code")
	installation_date = Column(Date, nullable=True)

	maintenance_schedule = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{frequency, last_date, next_date, notes}",
	)
	status = Column(
		String(20),
		nullable=False,
		default="OPERATIONAL",
		server_default="OPERATIONAL",
		comment="OPERATIONAL/MAINTENANCE/FAULT/REPLACED",
	)
	device_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_iot_device.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	last_inspection_date = Column(Date, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	device: IoTDevice | None = relationship("IoTDevice", foreign_keys=[device_id], lazy="select")

	def __repr__(self) -> str:
		return f"<SmartAsset {self.asset_name!r} type={self.asset_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# CityAlert
# ---------------------------------------------------------------------------

class CityAlert(AuditMixin, Model):
	"""Operational alert from device, citizen report, or system.

	location JSONB {lat, lng}: incident point.
	geo_area JSONB: optional polygon/circle for area-based alerts.
	acknowledged_by UUID: soft FK to foundation.Party.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_city_alert"
	__table_args__ = (
		Index("ix_sc_alert_tenant", "tenant_id"),
		Index("ix_sc_alert_severity", "severity"),
		Index("ix_sc_alert_status", "status"),
		Index("ix_sc_alert_issued", "issued_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	source_type = Column(
		String(10),
		nullable=False,
		comment="DEVICE/CITIZEN/SYSTEM",
	)
	source_id = Column(String(100), nullable=False, comment="Device ID, citizen ID, or system name")
	alert_type = Column(String(100), nullable=False)
	severity = Column(
		String(10),
		nullable=False,
		default="MEDIUM",
		comment="LOW/MEDIUM/HIGH/CRITICAL",
	)
	message = Column(Text, nullable=False)

	location = Column(
		JSONB,
		nullable=True,
		comment="GEOMETRY(Point,4326) stored as {lat, lng}",
	)
	geo_area = Column(
		JSONB,
		nullable=True,
		comment="GEOMETRY polygon/circle for area-wide alerts",
	)

	issued_at = Column(DateTime(timezone=True), nullable=False)
	expires_at = Column(DateTime(timezone=True), nullable=True, comment="NULL = no expiry")

	status = Column(
		String(15),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE/ACKNOWLEDGED/RESOLVED",
	)
	acknowledged_by = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="Soft FK to foundation.Party",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return f"<CityAlert type={self.alert_type!r} sev={self.severity!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# DigitalTwin
# ---------------------------------------------------------------------------

class DigitalTwin(AuditMixin, Model):
	"""Digital twin state snapshot for a city asset.

	current_state JSONB: live sensor-fused state of the twin.
	simulation_params JSONB: parameters for forward simulation.
	health_score NUMERIC(5,4): composite health 0.0000–1.0000.
	asset_id is a logical identifier (not a FK) to support heterogeneous asset types.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_digital_twin"
	__table_args__ = (
		Index("ix_sc_twin_tenant", "tenant_id"),
		Index("ix_sc_twin_asset", "asset_id"),
		Index("ix_sc_twin_type", "twin_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	asset_id = Column(String(100), nullable=False, comment="Logical asset identifier")
	twin_type = Column(String(50), nullable=False, comment="e.g. building, grid_node, vehicle, water_main")

	current_state = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Live sensor-fused state snapshot",
	)
	simulation_params = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Parameters for forward simulation runs",
	)
	last_synced_at = Column(DateTime(timezone=True), nullable=False)
	health_score = Column(
		Numeric(5, 4),
		nullable=False,
		default=1.0,
		server_default="1.0",
		comment="Composite health 0.0000–1.0000",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<DigitalTwin asset={self.asset_id!r} type={self.twin_type!r} "
			f"health={self.health_score}>"
		)


# ---------------------------------------------------------------------------
# CityServiceRequest
# ---------------------------------------------------------------------------

class CityServiceRequest(AuditMixin, Model):
	"""Citizen service request (311 / mobile / web channels).

	constituent_id: soft FK to foundation.Party — nullable (anonymous reports allowed).
	photos JSONB: [{url, caption, taken_at}, ...]
	assigned_to: soft FK to foundation.Party (department/operator).
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_city_service_request"
	__table_args__ = (
		Index("ix_sc_sr_tenant", "tenant_id"),
		Index("ix_sc_sr_status", "status"),
		Index("ix_sc_sr_type", "request_type"),
		Index("ix_sc_sr_created", "created_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	constituent_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="Soft FK to foundation.Party; NULL = anonymous",
	)
	channel = Column(
		String(10),
		nullable=False,
		default="WEB",
		comment="APP/WEB/PHONE/311",
	)
	request_type = Column(String(100), nullable=False)
	location = Column(
		JSONB,
		nullable=True,
		comment="GEOMETRY(Point,4326) stored as {lat, lng}",
	)
	address = Column(JSONB, nullable=True, comment="Structured address")
	description = Column(Text, nullable=False)
	photos = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{url, caption, taken_at}]",
	)

	status = Column(
		String(15),
		nullable=False,
		default="OPEN",
		server_default="OPEN",
		comment="OPEN/ASSIGNED/IN_PROGRESS/RESOLVED",
	)
	assigned_to = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="Soft FK to foundation.Party (department/operator)",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	resolved_at = Column(DateTime(timezone=True), nullable=True)

	def __repr__(self) -> str:
		return (
			f"<CityServiceRequest type={self.request_type!r} "
			f"status={self.status!r} channel={self.channel!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"IoTDevice",
	"SensorReading",
	"SmartAsset",
	"CityAlert",
	"DigitalTwin",
	"CityServiceRequest",
	"DEVICE_TYPE",
	"PROTOCOL",
	"READING_QUALITY",
	"ASSET_TYPE",
	"ASSET_STATUS",
	"ALERT_SOURCE",
	"ALERT_SEVERITY",
	"ALERT_STATUS",
	"SERVICE_CHANNEL",
	"SERVICE_STATUS",
]
