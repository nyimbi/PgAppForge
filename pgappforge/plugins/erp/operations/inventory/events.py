"""
pgappforge/plugins/erp/operations/inventory/events.py

Domain events for the Inventory plugin.

All monetary amounts are integer cents — never float.
Quantities are Decimal-compatible strings where precision matters.

Events emitted:
  inventory.stock.received          — GRN posted, stock received into warehouse
  inventory.stock.issued            — stock issued against a sales/production order
  inventory.stock.transferred       — internal warehouse transfer completed
  inventory.stock.adjusted          — manual adjustment posted
  inventory.stock.count_approved    — stock count approved, COUNT_ADJUSTMENT movements posted
  inventory.stock.low               — product crossed reorder_point threshold
  inventory.product.created         — new product registered
  inventory.product.deactivated     — product marked is_active=False

Events consumed:
  ap.invoice.matched                — trigger in-transit quantity update
  ap.payment.confirmed              — (informational; no stock impact)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Stock movement events
# ---------------------------------------------------------------------------

@dataclass
class StockReceivedEvent(DomainEvent):
	"""Emitted when a GRN is posted and stock enters the warehouse."""
	event_type: str = "inventory.stock.received"
	movement_id: str = ""
	product_id: str = ""
	warehouse_id: str = ""
	location_id: str = ""
	quantity: str = ""           # Decimal string — avoid float
	unit_cost_cents: int = 0
	total_cost_cents: int = 0
	lot_number: str = ""
	expiry_date: str = ""        # ISO date or ""
	reference_type: str = "PO"
	reference_id: str = ""


@dataclass
class StockIssuedEvent(DomainEvent):
	"""Emitted when stock is issued to fulfil a sales or production order."""
	event_type: str = "inventory.stock.issued"
	movement_id: str = ""
	product_id: str = ""
	warehouse_id: str = ""
	from_location_id: str = ""
	quantity: str = ""
	unit_cost_cents: int = 0
	total_cost_cents: int = 0
	lot_number: str = ""
	reference_type: str = "SO"
	reference_id: str = ""


@dataclass
class StockTransferredEvent(DomainEvent):
	"""Emitted when stock is moved between locations within or across warehouses."""
	event_type: str = "inventory.stock.transferred"
	movement_id: str = ""
	product_id: str = ""
	warehouse_id: str = ""
	from_location_id: str = ""
	to_location_id: str = ""
	quantity: str = ""
	lot_number: str = ""
	reference_id: str = ""


@dataclass
class StockAdjustedEvent(DomainEvent):
	"""Emitted when a manual ADJUSTMENT movement is posted."""
	event_type: str = "inventory.stock.adjusted"
	movement_id: str = ""
	product_id: str = ""
	warehouse_id: str = ""
	quantity: str = ""           # Signed: positive = gain, negative = loss
	unit_cost_cents: int = 0
	total_cost_cents: int = 0
	reason: str = ""


@dataclass
class StockCountApprovedEvent(DomainEvent):
	"""Emitted when a stock count is approved and COUNT_ADJUSTMENT movements are posted."""
	event_type: str = "inventory.stock.count_approved"
	stock_count_id: str = ""
	warehouse_id: str = ""
	count_type: str = ""         # FULL | CYCLE | SPOT
	lines_adjusted: int = 0
	total_variance_value_cents: int = 0
	approved_by: str = ""


@dataclass
class StockLowEvent(DomainEvent):
	"""Emitted when product quantity_available crosses reorder_point."""
	event_type: str = "inventory.stock.low"
	product_id: str = ""
	warehouse_id: str = ""
	quantity_available: str = ""
	reorder_point: str = ""
	reorder_quantity: str = ""
	lead_time_days: int = 0


# ---------------------------------------------------------------------------
# Product master events
# ---------------------------------------------------------------------------

@dataclass
class ProductCreatedEvent(DomainEvent):
	"""Emitted when a new product is created."""
	event_type: str = "inventory.product.created"
	product_id: str = ""
	sku: str = ""
	name: str = ""
	uom: str = ""
	valuation_method: str = ""


@dataclass
class ProductDeactivatedEvent(DomainEvent):
	"""Emitted when a product is marked is_active=False."""
	event_type: str = "inventory.product.deactivated"
	product_id: str = ""
	sku: str = ""
	reason: str = ""


__all__ = [
	"StockReceivedEvent",
	"StockIssuedEvent",
	"StockTransferredEvent",
	"StockAdjustedEvent",
	"StockCountApprovedEvent",
	"StockLowEvent",
	"ProductCreatedEvent",
	"ProductDeactivatedEvent",
]
