"""
pgappforge/plugins/erp/industry/agritech/events.py

Domain events for the AgriTech plugin.

Emitted events:
  agri.planting.created        — new planting activity recorded
  agri.planting.status_changed — PLANNED→PLANTED→GROWING→HARVESTED
  agri.observation.created     — field observation logged
  agri.observation.critical    — severity=CRITICAL observation — triggers alerts
  agri.harvest.recorded        — harvest record created
  agri.input.applied           — input application logged
  agri.farm.created            — new farm registered
  agri.weather.alert           — weather threshold exceeded (frost, storm, etc.)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class FarmCreatedEvent(DomainEvent):
	event_type: str = "agri.farm.created"
	farm_id: str = ""
	farm_name: str = ""
	farm_type: str = ""
	party_id: str = ""
	total_area_ha: str = ""  # Decimal as string


@dataclass
class PlantingCreatedEvent(DomainEvent):
	event_type: str = "agri.planting.created"
	activity_id: str = ""
	field_id: str = ""
	crop_id: str = ""
	planting_date: str = ""
	expected_harvest_date: str = ""


@dataclass
class PlantingStatusChangedEvent(DomainEvent):
	event_type: str = "agri.planting.status_changed"
	activity_id: str = ""
	field_id: str = ""
	crop_id: str = ""
	old_status: str = ""
	new_status: str = ""


@dataclass
class FieldObservationCreatedEvent(DomainEvent):
	event_type: str = "agri.observation.created"
	observation_id: str = ""
	field_id: str = ""
	observation_type: str = ""
	severity: str = ""


@dataclass
class CriticalObservationEvent(DomainEvent):
	"""Fired when severity=CRITICAL — downstream can page agronomists."""
	event_type: str = "agri.observation.critical"
	observation_id: str = ""
	field_id: str = ""
	farm_id: str = ""
	observation_type: str = ""
	notes: str = ""


@dataclass
class HarvestRecordedEvent(DomainEvent):
	event_type: str = "agri.harvest.recorded"
	harvest_id: str = ""
	activity_id: str = ""
	field_id: str = ""
	crop_id: str = ""
	quantity_kg: str = ""  # Decimal as string
	quality_grade: str = ""
	total_revenue_cents: int = 0


@dataclass
class InputAppliedEvent(DomainEvent):
	event_type: str = "agri.input.applied"
	application_id: str = ""
	field_id: str = ""
	input_type: str = ""
	product_name: str = ""
	quantity: str = ""  # Decimal as string
	unit: str = ""
	cost_cents: int = 0


@dataclass
class WeatherAlertEvent(DomainEvent):
	"""Fired when a weather record breaches a configured threshold."""
	event_type: str = "agri.weather.alert"
	station_id: str = ""
	alert_type: str = ""   # FROST | STORM | DROUGHT | FLOOD_RISK
	parameter: str = ""    # temperature_c | rainfall_mm | wind_speed_kmh
	value: str = ""        # Decimal as string
	threshold: str = ""    # Decimal as string
	affected_farm_ids: list = None  # type: ignore[assignment]

	def __post_init__(self) -> None:
		if self.affected_farm_ids is None:
			self.affected_farm_ids = []


__all__ = [
	"FarmCreatedEvent",
	"PlantingCreatedEvent",
	"PlantingStatusChangedEvent",
	"FieldObservationCreatedEvent",
	"CriticalObservationEvent",
	"HarvestRecordedEvent",
	"InputAppliedEvent",
	"WeatherAlertEvent",
]
