"""
pgappforge/plugins/erp/industry/manufacturing/events.py

Domain events for the Manufacturing plugin.

Events emitted:
  manufacturing.order.released       — MO moved to RELEASED
  manufacturing.order.completed      — MO production finished
  manufacturing.oee.snapshot_created — OEE computed for a shift
  manufacturing.asset.anomaly_detected — sensor anomaly flagged
  manufacturing.maintenance.work_order_raised — new WO created
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ManufacturingOrderReleasedEvent(DomainEvent):
	"""Emitted when a manufacturing order transitions to RELEASED."""
	event_type: str = "manufacturing.order.released"
	order_id: str = ""
	order_number: str = ""
	product_id: str = ""
	planned_qty: float = 0.0
	scheduled_start: str = ""  # ISO datetime


@dataclass
class ManufacturingOrderCompletedEvent(DomainEvent):
	"""Emitted when a manufacturing order is marked COMPLETED."""
	event_type: str = "manufacturing.order.completed"
	order_id: str = ""
	order_number: str = ""
	product_id: str = ""
	actual_qty_produced: float = 0.0
	actual_qty_scrapped: float = 0.0
	actual_cost_cents: int = 0


@dataclass
class OEESnapshotCreatedEvent(DomainEvent):
	"""Emitted when an OEE snapshot is recorded for a shift."""
	event_type: str = "manufacturing.oee.snapshot_created"
	snapshot_id: str = ""
	work_center_id: str = ""
	shift_date: str = ""   # ISO date
	shift_name: str = ""
	oee_pct: str = ""      # Decimal string e.g. "0.8523"
	availability_pct: str = ""
	performance_pct: str = ""
	quality_pct: str = ""


@dataclass
class AssetAnomalyDetectedEvent(DomainEvent):
	"""Emitted when a sensor reading is flagged as anomalous."""
	event_type: str = "manufacturing.asset.anomaly_detected"
	sensor_reading_id: str = ""
	asset_id: str = ""
	sensor_type: str = ""
	value: str = ""        # Decimal string
	unit: str = ""
	anomaly_score: float = 0.0
	read_at: str = ""      # ISO datetime


@dataclass
class MaintenanceWorkOrderRaisedEvent(DomainEvent):
	"""Emitted when a maintenance work order is created."""
	event_type: str = "manufacturing.maintenance.work_order_raised"
	work_order_id: str = ""
	work_order_number: str = ""
	asset_id: str = ""
	maintenance_type: str = ""
	priority: str = ""


__all__ = [
	"ManufacturingOrderReleasedEvent",
	"ManufacturingOrderCompletedEvent",
	"OEESnapshotCreatedEvent",
	"AssetAnomalyDetectedEvent",
	"MaintenanceWorkOrderRaisedEvent",
]
