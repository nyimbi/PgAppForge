"""
pgappforge/plugins/erp/industry/water/events.py

Domain events for the Water Management plugin.

Emitted events:
  water.quality.violation      — quality threshold exceeded
  water.contamination.detected — multi-parameter contamination event
  water.flood_warning.issued   — flood warning issued for a water body
  water.flood_warning.cancelled — flood warning cancelled/expired
  water.allocation.created     — new water allocation/permit registered
  water.allocation.exceeded    — usage approaching/exceeding allocation
  water.flow.alert             — flow rate threshold crossed
  water.station.offline        — monitoring station has stopped reporting
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class WaterQualityViolationEvent(DomainEvent):
	"""Single parameter threshold exceeded."""
	event_type: str = "water.quality.violation"
	station_id: str = ""
	water_body_id: str = ""
	parameter: str = ""
	value: str = ""     # Decimal as string
	unit: str = ""
	threshold: str = ""  # Decimal as string
	quality_flag: str = ""


@dataclass
class ContaminationDetectedEvent(DomainEvent):
	"""Multiple concurrent quality violations — likely contamination event."""
	event_type: str = "water.contamination.detected"
	water_body_id: str = ""
	station_id: str = ""
	violated_parameters: list = field(default_factory=list)
	# [{"parameter": "NITRATE", "value": "45.2", "threshold": "10.0"}]
	severity: str = ""  # LOW | MEDIUM | HIGH | CRITICAL


@dataclass
class FloodWarningIssuedEvent(DomainEvent):
	event_type: str = "water.flood_warning.issued"
	warning_id: str = ""
	water_body_id: str = ""
	water_body_name: str = ""
	warning_level: str = ""  # ADVISORY | WATCH | WARNING | EMERGENCY
	forecast_peak_level_m: str = ""  # Decimal as string
	forecast_peak_at: str = ""       # ISO datetime string
	affected_area_count: int = 0


@dataclass
class FloodWarningCancelledEvent(DomainEvent):
	event_type: str = "water.flood_warning.cancelled"
	warning_id: str = ""
	water_body_id: str = ""
	cancelled_by: str = ""
	reason: str = ""


@dataclass
class WaterAllocationCreatedEvent(DomainEvent):
	event_type: str = "water.allocation.created"
	allocation_id: str = ""
	holder_id: str = ""
	water_body_id: str = ""
	allocation_type: str = ""
	allocated_m3_per_year: str = ""  # Decimal as string
	permit_number: str = ""


@dataclass
class AllocationExceededEvent(DomainEvent):
	"""Usage is approaching (>80%) or has exceeded (>100%) the annual allocation."""
	event_type: str = "water.allocation.exceeded"
	allocation_id: str = ""
	permit_number: str = ""
	holder_id: str = ""
	allocated_m3: str = ""   # Decimal as string
	used_m3: str = ""        # Decimal as string
	usage_pct: str = ""      # Decimal as string
	severity: str = ""       # WARNING (>80%) | CRITICAL (>100%)


@dataclass
class FlowAlertEvent(DomainEvent):
	"""River flow rate has crossed a configured threshold (low flow or high flow)."""
	event_type: str = "water.flow.alert"
	station_id: str = ""
	water_body_id: str = ""
	alert_type: str = ""    # LOW_FLOW | HIGH_FLOW | RAPID_RISE
	flow_m3_per_s: str = "" # Decimal as string
	water_level_m: str = "" # Decimal as string
	threshold_m3_per_s: str = ""  # Decimal as string


@dataclass
class StationOfflineEvent(DomainEvent):
	"""Monitoring station has not reported within the expected interval."""
	event_type: str = "water.station.offline"
	station_id: str = ""
	station_code: str = ""
	water_body_id: str = ""
	last_seen_at: str = ""   # ISO datetime string
	silence_hours: int = 0


__all__ = [
	"WaterQualityViolationEvent",
	"ContaminationDetectedEvent",
	"FloodWarningIssuedEvent",
	"FloodWarningCancelledEvent",
	"WaterAllocationCreatedEvent",
	"AllocationExceededEvent",
	"FlowAlertEvent",
	"StationOfflineEvent",
]
