"""
pgappforge/plugins/erp/industry/water/models.py

SQLAlchemy models for the Water Management plugin.

Extends OGC WaterML 2.0 concepts (waterml.json) with operational
water governance: water bodies, monitoring stations, quality measurements,
flow records, flood warnings and water allocations.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields
  - PostGIS GEOMETRY columns stored as WKT Text (geoalchemy2 optional)

Table prefix: water_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
# WaterBody
# ---------------------------------------------------------------------------

class WaterBody(AuditMixin, Model):
	"""Named water body — the top-level hydrological entity.

	body_type: RIVER | LAKE | RESERVOIR | GROUNDWATER | WETLAND
	location: PostGIS Geometry (Polygon or MultiPolygon for reservoirs/lakes,
	          LineString for rivers) — stored as WKT
	catchment_area_km2: total drainage area in km²
	status: GOOD | MODERATE | POOR | BAD  (EU WFD ecological status classification)
	monitoring_authority: organisation responsible for the water body
	"""

	__allow_unmapped__ = True
	__tablename__ = "water_body"
	__table_args__ = (
		Index("ix_water_body_tenant", "tenant_id"),
		Index("ix_water_body_type", "body_type"),
		Index("ix_water_body_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(200), nullable=False)
	body_type = Column(
		String(15),
		nullable=False,
		default="RIVER",
		comment="RIVER | LAKE | RESERVOIR | GROUNDWATER | WETLAND",
	)
	location = Column(Text, nullable=True, comment="GEOMETRY WKT — polygon/linestring of water body")
	catchment_area_km2 = Column(Numeric(12, 2), nullable=True, comment="Drainage catchment area in km²")
	monitoring_authority = Column(String(200), nullable=True, comment="Organisation responsible for monitoring")
	status = Column(
		String(10),
		nullable=False,
		default="MODERATE",
		comment="GOOD | MODERATE | POOR | BAD (EU WFD ecological status)",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	stations: list[MonitoringStation] = relationship("MonitoringStation", back_populates="water_body", cascade="all, delete-orphan", lazy="select")
	flood_warnings: list[FloodWarning] = relationship("FloodWarning", back_populates="water_body", lazy="select")
	allocations: list[WaterAllocation] = relationship("WaterAllocation", back_populates="water_body", lazy="select")

	def __repr__(self) -> str:
		return f"<WaterBody {self.name!r} type={self.body_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# MonitoringStation
# ---------------------------------------------------------------------------

class MonitoringStation(AuditMixin, Model):
	"""Physical monitoring station on a water body.

	station_code: unique external/national identifier (e.g. USGS site number)
	parameters_monitored: ARRAY of VARCHAR — list of WaterML parameter codes
	operator_id: FK to foundation Party — the organisation operating this station
	"""

	__allow_unmapped__ = True
	__tablename__ = "water_monitoring_station"
	__table_args__ = (
		Index("ix_water_ms_tenant", "tenant_id"),
		Index("ix_water_ms_water_body", "water_body_id"),
		Index("ix_water_ms_active", "is_active"),
		UniqueConstraint("tenant_id", "station_code", name="uq_water_ms_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	station_code = Column(String(50), nullable=False, comment="Unique station code within tenant")
	water_body_id = Column(UUID(as_uuid=False), ForeignKey("water_body.id", ondelete="CASCADE"), nullable=False, index=True)
	name = Column(String(200), nullable=False)
	location = Column(Text, nullable=True, comment="GEOMETRY(Point,4326) WKT — station position")
	installation_date = Column(Date, nullable=True)
	parameters_monitored = Column(
		ARRAY(String(30)),
		nullable=False,
		default=list,
		server_default="{}",
		comment="Array of WaterML parameter codes e.g. {PH, DO, TURBIDITY}",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	operator_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to foundation Party — operating organisation")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	water_body: WaterBody = relationship("WaterBody", back_populates="stations", lazy="select")
	quality_measurements: list[WaterQualityMeasurement] = relationship(
		"WaterQualityMeasurement", back_populates="station", cascade="all, delete-orphan", lazy="select",
	)
	flow_records: list[WaterFlowRecord] = relationship(
		"WaterFlowRecord", back_populates="station", cascade="all, delete-orphan", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<MonitoringStation {self.station_code!r} {self.name!r} active={self.is_active}>"


# ---------------------------------------------------------------------------
# WaterQualityMeasurement
# ---------------------------------------------------------------------------

class WaterQualityMeasurement(AuditMixin, Model):
	"""Single water quality parameter measurement at a station.

	parameter: PH | DO | TURBIDITY | CONDUCTIVITY | NITRATE | PHOSPHATE | ECOLI
	quality_flag: GOOD | SUSPECT | BAD
	value: Numeric(12,4) — in units specified by 'unit'
	method: analytical method (e.g. spectrophotometry, ion chromatography)

	High-volume table — partitioned by measured_at in production.
	"""

	__allow_unmapped__ = True
	__tablename__ = "water_quality_measurement"
	__table_args__ = (
		Index("ix_water_qm_station", "station_id"),
		Index("ix_water_qm_tenant", "tenant_id"),
		Index("ix_water_qm_measured_at", "measured_at"),
		Index("ix_water_qm_station_param", "station_id", "parameter"),
		Index("ix_water_qm_station_time", "station_id", "measured_at"),
		Index("ix_water_qm_flag", "quality_flag"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	station_id = Column(UUID(as_uuid=False), ForeignKey("water_monitoring_station.id", ondelete="CASCADE"), nullable=False, index=True)
	measured_at = Column(DateTime(timezone=True), nullable=False, index=True)
	parameter = Column(
		String(15),
		nullable=False,
		comment="PH | DO | TURBIDITY | CONDUCTIVITY | NITRATE | PHOSPHATE | ECOLI",
	)
	value = Column(Numeric(12, 4), nullable=False, comment="Measured value in specified unit")
	unit = Column(String(20), nullable=False, default="mg/L", comment="Unit of measure e.g. mg/L, NTU, pH, CFU/100mL")
	quality_flag = Column(
		String(10),
		nullable=False,
		default="GOOD",
		comment="GOOD | SUSPECT | BAD",
	)
	method = Column(String(50), nullable=True, comment="Analytical/measurement method")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	station: MonitoringStation = relationship("MonitoringStation", back_populates="quality_measurements", lazy="select")

	def __repr__(self) -> str:
		return f"<WaterQualityMeasurement station={self.station_id!r} param={self.parameter!r} value={self.value} flag={self.quality_flag!r}>"


# ---------------------------------------------------------------------------
# WaterFlowRecord
# ---------------------------------------------------------------------------

class WaterFlowRecord(AuditMixin, Model):
	"""Hydrological flow and stage measurement at a station.

	flow_m3_per_s: discharge in cubic metres per second (m³/s)
	water_level_m: stage height in metres above gauge datum
	quality_flag: GOOD | SUSPECT | BAD

	High-volume table — partitioned by measured_at in production.
	"""

	__allow_unmapped__ = True
	__tablename__ = "water_flow_record"
	__table_args__ = (
		Index("ix_water_fr_station", "station_id"),
		Index("ix_water_fr_tenant", "tenant_id"),
		Index("ix_water_fr_measured_at", "measured_at"),
		Index("ix_water_fr_station_time", "station_id", "measured_at"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	station_id = Column(UUID(as_uuid=False), ForeignKey("water_monitoring_station.id", ondelete="CASCADE"), nullable=False, index=True)
	measured_at = Column(DateTime(timezone=True), nullable=False, index=True)
	flow_m3_per_s = Column(Numeric(12, 4), nullable=True, comment="Discharge m³/s")
	water_level_m = Column(Numeric(8, 3), nullable=True, comment="Stage height in metres above gauge datum")
	quality_flag = Column(
		String(10),
		nullable=False,
		default="GOOD",
		comment="GOOD | SUSPECT | BAD",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	station: MonitoringStation = relationship("MonitoringStation", back_populates="flow_records", lazy="select")

	def __repr__(self) -> str:
		return f"<WaterFlowRecord station={self.station_id!r} at={self.measured_at!r} flow={self.flow_m3_per_s}m³/s level={self.water_level_m}m>"


# ---------------------------------------------------------------------------
# FloodWarning
# ---------------------------------------------------------------------------

class FloodWarning(AuditMixin, Model):
	"""Flood warning issued for a water body.

	warning_level: ADVISORY | WATCH | WARNING | EMERGENCY
	status: ACTIVE | CANCELLED | EXPIRED
	affected_areas: JSONB — [{name, population, geometry_wkt}]
	forecast_peak_level_m: projected maximum stage in metres
	forecast_peak_at: projected time of peak
	"""

	__allow_unmapped__ = True
	__tablename__ = "water_flood_warning"
	__table_args__ = (
		Index("ix_water_fw_tenant", "tenant_id"),
		Index("ix_water_fw_water_body", "water_body_id"),
		Index("ix_water_fw_issued_at", "issued_at"),
		Index("ix_water_fw_status", "status"),
		Index("ix_water_fw_level", "warning_level"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	water_body_id = Column(UUID(as_uuid=False), ForeignKey("water_body.id"), nullable=False, index=True)
	warning_level = Column(
		String(15),
		nullable=False,
		comment="ADVISORY | WATCH | WARNING | EMERGENCY",
	)
	issued_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
	forecast_peak_level_m = Column(Numeric(8, 3), nullable=True, comment="Projected peak stage in metres")
	forecast_peak_at = Column(DateTime(timezone=True), nullable=True, comment="Projected time of peak stage")
	affected_areas = Column(JSONB, nullable=False, default=list, server_default="[]", comment="[{name, population, geometry_wkt}]")
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | CANCELLED | EXPIRED",
	)
	issued_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user who issued this warning")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	water_body: WaterBody = relationship("WaterBody", back_populates="flood_warnings", lazy="select")

	def __repr__(self) -> str:
		return f"<FloodWarning {self.water_body_id!r} level={self.warning_level!r} status={self.status!r} issued={self.issued_at!r}>"


# ---------------------------------------------------------------------------
# WaterAllocation
# ---------------------------------------------------------------------------

class WaterAllocation(AuditMixin, Model):
	"""Water abstraction permit / allocation for a party.

	allocation_type: AGRICULTURAL | MUNICIPAL | INDUSTRIAL | ENVIRONMENTAL
	allocated_m3_per_year: annual volume entitlement in m³
	used_m3_this_year: running total of abstracted volume this year
	permit_number: unique permit reference (national water authority)
	status: string — ACTIVE | SUSPENDED | EXPIRED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "water_allocation"
	__table_args__ = (
		Index("ix_water_alloc_tenant", "tenant_id"),
		Index("ix_water_alloc_holder", "holder_id"),
		Index("ix_water_alloc_water_body", "water_body_id"),
		Index("ix_water_alloc_type", "allocation_type"),
		Index("ix_water_alloc_status", "status"),
		UniqueConstraint("tenant_id", "permit_number", name="uq_water_alloc_permit"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	holder_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to foundation.Party — permit holder")
	water_body_id = Column(UUID(as_uuid=False), ForeignKey("water_body.id"), nullable=False, index=True)
	allocation_type = Column(
		String(15),
		nullable=False,
		comment="AGRICULTURAL | MUNICIPAL | INDUSTRIAL | ENVIRONMENTAL",
	)
	allocated_m3_per_year = Column(Numeric(15, 2), nullable=False, comment="Annual entitlement in m³")
	used_m3_this_year = Column(Numeric(15, 2), nullable=False, default=0, server_default="0", comment="Abstracted volume this calendar year in m³")
	valid_from = Column(Date, nullable=False, comment="Permit start date")
	valid_to = Column(Date, nullable=True, comment="Permit expiry date; NULL = open-ended")
	permit_number = Column(String(100), nullable=False, comment="National water authority permit reference")
	status = Column(String(15), nullable=False, default="ACTIVE", comment="ACTIVE | SUSPENDED | EXPIRED | CANCELLED")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	water_body: WaterBody = relationship("WaterBody", back_populates="allocations", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<WaterAllocation permit={self.permit_number!r} holder={self.holder_id!r} "
			f"type={self.allocation_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"WaterBody",
	"MonitoringStation",
	"WaterQualityMeasurement",
	"WaterFlowRecord",
	"FloodWarning",
	"WaterAllocation",
]
