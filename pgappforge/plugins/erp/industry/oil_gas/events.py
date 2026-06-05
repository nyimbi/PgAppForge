"""
pgappforge/plugins/erp/industry/oil_gas/events.py

Domain events for the Oil & Gas plugin.

All cost amounts are integer cents.  Timestamps are ISO-8601 strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


@dataclass
class MaintenanceScheduledEvent(DomainEvent):
	"""Emitted when a new maintenance work order is created."""
	event_type: str = "oil_gas.maintenance.scheduled"
	work_order_id: str = ""
	work_order_number: str = ""
	asset_id: str = ""
	work_type: str = ""
	scheduled_start: str = ""     # ISO datetime string
	estimated_cost_cents: int = 0


@dataclass
class MaintenanceCompletedEvent(DomainEvent):
	"""Emitted when a work order transitions to COMPLETED."""
	event_type: str = "oil_gas.maintenance.completed"
	work_order_id: str = ""
	work_order_number: str = ""
	asset_id: str = ""
	actual_cost_cents: int = 0
	actual_end: str = ""          # ISO datetime string


@dataclass
class ProductionRecordedEvent(DomainEvent):
	"""Emitted when a production record is written."""
	event_type: str = "oil_gas.production.recorded"
	record_id: str = ""
	facility_id: str = ""
	production_date: str = ""     # ISO date string
	product_type: str = ""
	quantity: str = ""            # Decimal as string to avoid float
	unit: str = ""


@dataclass
class IncidentReportedEvent(DomainEvent):
	"""Emitted when an HSE incident is logged."""
	event_type: str = "oil_gas.incident.reported"
	incident_id: str = ""
	facility_id: str = ""
	incident_type: str = ""
	severity: str = ""
	occurred_at: str = ""         # ISO datetime string
	casualties: int = 0
	injuries: int = 0


@dataclass
class HAZOPCompletedEvent(DomainEvent):
	"""Emitted when a HAZOP review moves to COMPLETED."""
	event_type: str = "oil_gas.hazop.completed"
	hazop_id: str = ""
	asset_id: str = ""
	review_date: str = ""         # ISO date string
	findings_count: int = 0
	open_action_items: int = 0


@dataclass
class FacilityStatusChangedEvent(DomainEvent):
	"""Emitted when a Facility status changes (e.g. ACTIVE → SHUTDOWN)."""
	event_type: str = "oil_gas.facility.status_changed"
	facility_id: str = ""
	facility_code: str = ""
	old_status: str = ""
	new_status: str = ""


__all__ = [
	"MaintenanceScheduledEvent",
	"MaintenanceCompletedEvent",
	"ProductionRecordedEvent",
	"IncidentReportedEvent",
	"HAZOPCompletedEvent",
	"FacilityStatusChangedEvent",
	"emit_event",
]
