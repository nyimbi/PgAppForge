"""
pgappforge/plugins/erp/industry/agritech/models.py

SQLAlchemy models for the AgriTech plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields
  - PostGIS GEOMETRY columns via geoalchemy2

Table prefix: agri_
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
# Crop  (reference catalogue — no farm FK, shared across tenants)
# ---------------------------------------------------------------------------

class Crop(AuditMixin, Model):
	"""Reference catalogue of crop species.

	category: CEREAL | LEGUME | VEGETABLE | FRUIT | CASH_CROP
	growing_season_days: typical days from planting to harvest
	water_requirement_mm: typical total water needed over full season
	typical_yield_kg_per_ha: benchmark yield under normal conditions
	"""

	__allow_unmapped__ = True
	__tablename__ = "agri_crop"
	__table_args__ = (
		Index("ix_agri_crop_tenant", "tenant_id"),
		Index("ix_agri_crop_category", "category"),
		UniqueConstraint("tenant_id", "crop_name", name="uq_agri_crop_tenant_name"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	crop_name = Column(String(100), nullable=False)
	scientific_name = Column(String(150), nullable=True)
	category = Column(
		String(20),
		nullable=False,
		default="CEREAL",
		comment="CEREAL | LEGUME | VEGETABLE | FRUIT | CASH_CROP",
	)
	growing_season_days = Column(Integer, nullable=True, comment="Typical days from planting to harvest")
	water_requirement_mm = Column(Integer, nullable=True, comment="Total mm of water over full season")
	typical_yield_kg_per_ha = Column(Numeric(10, 2), nullable=True, comment="Benchmark yield kg/ha under normal conditions")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	fields: list[Field] = relationship("Field", back_populates="current_crop", lazy="select", foreign_keys="Field.current_crop_id")
	planting_activities: list[PlantingActivity] = relationship("PlantingActivity", back_populates="crop", lazy="select")

	def __repr__(self) -> str:
		return f"<Crop {self.crop_name!r} category={self.category!r}>"


# ---------------------------------------------------------------------------
# Farm
# ---------------------------------------------------------------------------

class Farm(AuditMixin, Model):
	"""Top-level farm entity.

	farm_type: ARABLE | LIVESTOCK | MIXED | HORTICULTURE
	certification: JSONB — {"organic": true, "fair_trade": false, "certifier": "...", "expiry": "..."}
	location: PostGIS Point (WGS84 4326) — centroid of the farm
	address: JSONB using ADDRESS_SCHEMA
	elevation_m: metres above sea level
	"""

	__allow_unmapped__ = True
	__tablename__ = "agri_farm"
	__table_args__ = (
		Index("ix_agri_farm_tenant", "tenant_id"),
		Index("ix_agri_farm_party", "party_id"),
		Index("ix_agri_farm_tenant_type", "tenant_id", "farm_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	party_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation.Party (app-managed)")
	farm_name = Column(String(200), nullable=False)
	total_area_ha = Column(Numeric(12, 4), nullable=True, comment="Total farm area in hectares")
	# PostGIS — stored as WKT/WKB; use GeoAlchemy2 if available, else Text fallback
	location = Column(Text, nullable=True, comment="GEOMETRY(Point,4326) — WKT centroid")
	address = Column(JSONB, nullable=False, default=dict, server_default="{}", comment="Structured address JSONB")
	farm_type = Column(
		String(15),
		nullable=False,
		default="MIXED",
		comment="ARABLE | LIVESTOCK | MIXED | HORTICULTURE",
	)
	certification = Column(JSONB, nullable=False, default=dict, server_default="{}", comment="Certification records JSONB")
	soil_type = Column(String(50), nullable=True)
	elevation_m = Column(Integer, nullable=True, comment="Elevation in metres above sea level")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	fields: list[Field] = relationship("Field", back_populates="farm", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return f"<Farm {self.farm_name!r} type={self.farm_type!r} area={self.total_area_ha}ha>"


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------

class Field(AuditMixin, Model):
	"""Named parcel of land within a farm.

	boundary: PostGIS Polygon (WGS84 4326) — stored as WKT
	irrigation_type: RAIN_FED | DRIP | SPRINKLER | FLOOD
	current_crop_id: nullable FK to Crop (the crop currently growing)
	"""

	__allow_unmapped__ = True
	__tablename__ = "agri_field"
	__table_args__ = (
		Index("ix_agri_field_farm", "farm_id"),
		Index("ix_agri_field_tenant", "tenant_id"),
		Index("ix_agri_field_crop", "current_crop_id"),
		Index("ix_agri_field_tenant_irrigation", "tenant_id", "irrigation_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	farm_id = Column(UUID(as_uuid=False), ForeignKey("agri_farm.id", ondelete="CASCADE"), nullable=False, index=True)
	field_name = Column(String(200), nullable=False)
	area_ha = Column(Numeric(10, 4), nullable=True, comment="Measured area in hectares")
	boundary = Column(Text, nullable=True, comment="GEOMETRY(Polygon,4326) — WKT boundary polygon")
	soil_type = Column(String(50), nullable=True)
	current_crop_id = Column(UUID(as_uuid=False), ForeignKey("agri_crop.id"), nullable=True, index=True)
	irrigation_type = Column(
		String(15),
		nullable=False,
		default="RAIN_FED",
		comment="RAIN_FED | DRIP | SPRINKLER | FLOOD",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	farm: Farm = relationship("Farm", back_populates="fields", lazy="select")
	current_crop: Crop | None = relationship("Crop", back_populates="fields", lazy="select", foreign_keys=[current_crop_id])
	planting_activities: list[PlantingActivity] = relationship("PlantingActivity", back_populates="field", lazy="select")
	observations: list[FieldObservation] = relationship("FieldObservation", back_populates="field", cascade="all, delete-orphan", lazy="select")
	input_applications: list[InputApplication] = relationship("InputApplication", back_populates="field", lazy="select")

	def __repr__(self) -> str:
		return f"<Field {self.field_name!r} farm={self.farm_id!r} area={self.area_ha}ha irrigation={self.irrigation_type!r}>"


# ---------------------------------------------------------------------------
# PlantingActivity
# ---------------------------------------------------------------------------

class PlantingActivity(AuditMixin, Model):
	"""A crop planting event on a field for a season.

	status machine: PLANNED → PLANTED → GROWING → HARVESTED
	yield_kg and actual_harvest_date are populated on harvest.
	"""

	__allow_unmapped__ = True
	__tablename__ = "agri_planting_activity"
	__table_args__ = (
		Index("ix_agri_pa_field", "field_id"),
		Index("ix_agri_pa_crop", "crop_id"),
		Index("ix_agri_pa_tenant", "tenant_id"),
		Index("ix_agri_pa_tenant_status", "tenant_id", "status"),
		Index("ix_agri_pa_planting_date", "planting_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	field_id = Column(UUID(as_uuid=False), ForeignKey("agri_field.id"), nullable=False, index=True)
	crop_id = Column(UUID(as_uuid=False), ForeignKey("agri_crop.id"), nullable=False, index=True)
	planting_date = Column(Date, nullable=False)
	variety = Column(String(100), nullable=True, comment="Cultivar or hybrid name")
	seed_quantity_kg = Column(Numeric(10, 2), nullable=True, comment="Seed used in kg")
	seed_cost_cents = Column(Integer, nullable=True, comment="Total seed cost in integer cents")
	expected_harvest_date = Column(Date, nullable=True)
	actual_harvest_date = Column(Date, nullable=True)
	yield_kg = Column(Numeric(12, 2), nullable=True, comment="Actual yield in kg (populated on harvest)")
	status = Column(
		String(10),
		nullable=False,
		default="PLANNED",
		comment="PLANNED | PLANTED | GROWING | HARVESTED",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	field: Field = relationship("Field", back_populates="planting_activities", lazy="select")
	crop: Crop = relationship("Crop", back_populates="planting_activities", lazy="select")
	harvest_records: list[HarvestRecord] = relationship("HarvestRecord", back_populates="activity", lazy="select")
	input_applications: list[InputApplication] = relationship("InputApplication", back_populates="activity", lazy="select")

	def __repr__(self) -> str:
		return f"<PlantingActivity field={self.field_id!r} crop={self.crop_id!r} planted={self.planting_date!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# FieldObservation
# ---------------------------------------------------------------------------

class FieldObservation(AuditMixin, Model):
	"""Scouting / sensor observation on a field.

	observation_type: PEST | DISEASE | GROWTH_STAGE | SOIL_MOISTURE | IRRIGATION_NEED
	severity: LOW | MEDIUM | HIGH | CRITICAL (nullable — not applicable for GROWTH_STAGE)
	geo_point: PostGIS Point — exact location of observation within field
	sensor_data: JSONB — raw IoT/sensor readings
	photos: JSONB — [{url, caption, taken_at}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "agri_field_observation"
	__table_args__ = (
		Index("ix_agri_obs_field", "field_id"),
		Index("ix_agri_obs_tenant", "tenant_id"),
		Index("ix_agri_obs_observed_at", "observed_at"),
		Index("ix_agri_obs_type_severity", "observation_type", "severity"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	field_id = Column(UUID(as_uuid=False), ForeignKey("agri_field.id", ondelete="CASCADE"), nullable=False, index=True)
	observed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
	observer_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user who made the observation")
	observation_type = Column(
		String(20),
		nullable=False,
		comment="PEST | DISEASE | GROWTH_STAGE | SOIL_MOISTURE | IRRIGATION_NEED",
	)
	severity = Column(String(10), nullable=True, comment="LOW | MEDIUM | HIGH | CRITICAL")
	notes = Column(Text, nullable=True)
	photos = Column(JSONB, nullable=False, default=list, server_default="[]", comment="[{url, caption, taken_at}]")
	geo_point = Column(Text, nullable=True, comment="GEOMETRY(Point,4326) — WKT location within field")
	sensor_data = Column(JSONB, nullable=False, default=dict, server_default="{}", comment="Raw IoT/sensor readings")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	field: Field = relationship("Field", back_populates="observations", lazy="select")

	def __repr__(self) -> str:
		return f"<FieldObservation field={self.field_id!r} type={self.observation_type!r} severity={self.severity!r} at={self.observed_at!r}>"


# ---------------------------------------------------------------------------
# WeatherRecord
# ---------------------------------------------------------------------------

class WeatherRecord(AuditMixin, Model):
	"""Meteorological observation from a weather station.

	station_id: external/provider station code (not a FK — may be third-party)
	location: PostGIS Point — station position
	All numeric fields nullable — stations may not record all parameters.
	"""

	__allow_unmapped__ = True
	__tablename__ = "agri_weather_record"
	__table_args__ = (
		Index("ix_agri_wr_tenant", "tenant_id"),
		Index("ix_agri_wr_station_time", "station_id", "recorded_at"),
		Index("ix_agri_wr_recorded_at", "recorded_at"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	station_id = Column(String(50), nullable=False, index=True, comment="External station identifier")
	recorded_at = Column(DateTime(timezone=True), nullable=False, index=True)
	temperature_c = Column(Numeric(5, 2), nullable=True, comment="Air temperature °C")
	humidity_pct = Column(Numeric(5, 2), nullable=True, comment="Relative humidity %")
	rainfall_mm = Column(Numeric(7, 2), nullable=True, comment="Precipitation mm")
	wind_speed_kmh = Column(Numeric(6, 2), nullable=True, comment="Wind speed km/h")
	solar_radiation_wm2 = Column(Numeric(8, 2), nullable=True, comment="Solar radiation W/m²")
	location = Column(Text, nullable=True, comment="GEOMETRY(Point,4326) — station WKT position")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<WeatherRecord station={self.station_id!r} at={self.recorded_at!r} rain={self.rainfall_mm}mm>"


# ---------------------------------------------------------------------------
# InputApplication
# ---------------------------------------------------------------------------

class InputApplication(AuditMixin, Model):
	"""Application of agricultural input to a field.

	input_type: FERTILIZER | PESTICIDE | HERBICIDE | IRRIGATION | LIME
	activity_id: nullable FK to PlantingActivity (may be outside a planting context)
	cost_cents: integer cents — total cost of this application
	"""

	__allow_unmapped__ = True
	__tablename__ = "agri_input_application"
	__table_args__ = (
		Index("ix_agri_ia_field", "field_id"),
		Index("ix_agri_ia_activity", "activity_id"),
		Index("ix_agri_ia_tenant", "tenant_id"),
		Index("ix_agri_ia_date", "application_date"),
		Index("ix_agri_ia_type", "input_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	field_id = Column(UUID(as_uuid=False), ForeignKey("agri_field.id"), nullable=False, index=True)
	activity_id = Column(UUID(as_uuid=False), ForeignKey("agri_planting_activity.id"), nullable=True, index=True, comment="Optional link to planting activity")
	application_date = Column(Date, nullable=False)
	input_type = Column(
		String(15),
		nullable=False,
		comment="FERTILIZER | PESTICIDE | HERBICIDE | IRRIGATION | LIME",
	)
	product_name = Column(String(100), nullable=False)
	quantity = Column(Numeric(10, 3), nullable=False, comment="Quantity applied")
	unit = Column(String(20), nullable=False, default="kg", comment="Unit of measure (kg, L, mm, etc.)")
	cost_cents = Column(Integer, nullable=False, default=0, comment="Total application cost in integer cents")
	applied_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user who applied the input")
	method = Column(String(50), nullable=True, comment="Application method (broadcast, banded, foliar, etc.)")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	field: Field = relationship("Field", back_populates="input_applications", lazy="select")
	activity: PlantingActivity | None = relationship("PlantingActivity", back_populates="input_applications", lazy="select")

	def __repr__(self) -> str:
		return f"<InputApplication field={self.field_id!r} type={self.input_type!r} product={self.product_name!r} date={self.application_date!r}>"


# ---------------------------------------------------------------------------
# HarvestRecord
# ---------------------------------------------------------------------------

class HarvestRecord(AuditMixin, Model):
	"""Harvest summary for a planting activity.

	market_price_cents_per_kg: integer cents — price per kg at time of harvest
	total_revenue_cents: integer cents — market_price * quantity_kg
	quality_grade: buyer/market grade (A, B, Premium, etc.)
	"""

	__allow_unmapped__ = True
	__tablename__ = "agri_harvest_record"
	__table_args__ = (
		Index("ix_agri_hr_activity", "activity_id"),
		Index("ix_agri_hr_tenant", "tenant_id"),
		Index("ix_agri_hr_harvest_date", "harvest_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	activity_id = Column(UUID(as_uuid=False), ForeignKey("agri_planting_activity.id"), nullable=False, index=True)
	harvest_date = Column(Date, nullable=False)
	quantity_kg = Column(Numeric(12, 2), nullable=False, comment="Total harvested quantity in kg")
	quality_grade = Column(String(20), nullable=True, comment="Market quality grade (A, B, Premium, etc.)")
	moisture_pct = Column(Numeric(5, 2), nullable=True, comment="Grain/product moisture % at harvest")
	storage_location = Column(String(100), nullable=True)
	market_price_cents_per_kg = Column(Integer, nullable=True, comment="Price per kg in integer cents")
	total_revenue_cents = Column(Integer, nullable=True, comment="Total revenue = price * qty, in integer cents")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	activity: PlantingActivity = relationship("PlantingActivity", back_populates="harvest_records", lazy="select")

	def __repr__(self) -> str:
		return f"<HarvestRecord activity={self.activity_id!r} date={self.harvest_date!r} qty={self.quantity_kg}kg grade={self.quality_grade!r}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Crop",
	"Farm",
	"Field",
	"PlantingActivity",
	"FieldObservation",
	"WeatherRecord",
	"InputApplication",
	"HarvestRecord",
]
