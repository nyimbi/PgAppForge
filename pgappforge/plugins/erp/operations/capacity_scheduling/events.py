"""
pgappforge/plugins/erp/operations/capacity_scheduling/events.py

Domain events for the Finite Capacity Scheduling plugin.

Events emitted:
  ops.capacity.scheduled   — production order scheduled on a work center
  ops.capacity.overload    — work center capacity utilization > 100%
  ops.capacity.leveled     — capacity leveling run completed for an entity
  ops.capacity.bottleneck  — bottleneck work center identified (avg util > 80%)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class ProductionScheduledEvent(DomainEvent):
	"""Emitted when a production order is scheduled on a work center."""
	event_type: str = "ops.capacity.scheduled"
	order_id: str = ""
	work_center_id: str = ""
	start_datetime: str = ""   # ISO-8601 string
	end_datetime: str = ""     # ISO-8601 string
	tenant_id: str = ""


@dataclass
class CapacityOverloadDetectedEvent(DomainEvent):
	"""Emitted when a work center's daily utilization exceeds 100%."""
	event_type: str = "ops.capacity.overload"
	work_center_id: str = ""
	date: str = ""             # ISO-8601 date string
	utilization_pct: str = ""  # Decimal string


@dataclass
class ScheduleLeveledEvent(DomainEvent):
	"""Emitted after a capacity leveling run shifts orders to reduce overloads."""
	event_type: str = "ops.capacity.leveled"
	entity_id: str = ""
	from_date: str = ""        # ISO-8601 date string
	to_date: str = ""          # ISO-8601 date string
	orders_shifted: int = 0


@dataclass
class BottleneckDetectedEvent(DomainEvent):
	"""Emitted for each work center identified as a bottleneck (avg util > 80%)."""
	event_type: str = "ops.capacity.bottleneck"
	work_center_id: str = ""
	avg_utilization_pct: str = ""  # Decimal string
	period: str = ""               # e.g. "2026-06-01/2026-06-30"


__all__ = [
	"ProductionScheduledEvent",
	"CapacityOverloadDetectedEvent",
	"ScheduleLeveledEvent",
	"BottleneckDetectedEvent",
]
