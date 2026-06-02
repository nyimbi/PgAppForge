"""
pgappforge/plugins/erp/operations/warehouse/events.py

Domain events for the Warehouse Management plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  wms.picklist.created          — new pick list generated for an order
  wms.picklist.completed        — all lines picked; ready to ship
  wms.putaway.completed         — stock directed to final storage location
  wms.stock_count.started       — count run moved to IN_PROGRESS
  wms.stock_count.approved      — count approved, adjustments ready to post

Events consumed:
  inventory.stock.received      — triggers PutawayTask creation for new receipts
  inventory.stock.low           — can trigger priority pick escalation
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class PickListCreatedEvent(DomainEvent):
	"""Emitted when a PickList is created for an outbound order."""
	event_type: str = "wms.picklist.created"
	picklist_id: str = ""
	warehouse_id: str = ""
	order_type: str = ""       # SALES_ORDER | TRANSFER | PRODUCTION
	order_id: str = ""
	line_count: int = 0
	priority: int = 5


@dataclass
class PickListCompletedEvent(DomainEvent):
	"""Emitted when all PickListLines reach COMPLETED status."""
	event_type: str = "wms.picklist.completed"
	picklist_id: str = ""
	warehouse_id: str = ""
	order_type: str = ""
	order_id: str = ""
	picked_by: str = ""


@dataclass
class PutawayCompletedEvent(DomainEvent):
	"""Emitted when a PutawayTask is marked COMPLETED."""
	event_type: str = "wms.putaway.completed"
	putaway_task_id: str = ""
	warehouse_id: str = ""
	product_id: str = ""
	quantity: str = ""         # Decimal string
	from_location_id: str = ""
	actual_location_id: str = ""
	lot_number: str = ""
	completed_by: str = ""


@dataclass
class StockCountStartedEvent(DomainEvent):
	"""Emitted when a StockCount moves to IN_PROGRESS."""
	event_type: str = "wms.stock_count.started"
	stock_count_id: str = ""
	warehouse_id: str = ""
	count_type: str = ""
	count_date: str = ""       # ISO date


@dataclass
class StockCountReadyEvent(DomainEvent):
	"""Emitted when a StockCount reaches COMPLETED and is pending approval."""
	event_type: str = "wms.stock_count.ready"
	stock_count_id: str = ""
	warehouse_id: str = ""
	lines_with_variance: int = 0
	total_variance_value_cents: int = 0


__all__ = [
	"PickListCreatedEvent",
	"PickListCompletedEvent",
	"PutawayCompletedEvent",
	"StockCountStartedEvent",
	"StockCountReadyEvent",
]
