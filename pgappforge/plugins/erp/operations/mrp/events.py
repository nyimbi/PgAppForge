"""
pgappforge/plugins/erp/operations/mrp/events.py

Domain events for the MRP (Materials Requirements Planning) plugin.

Quantities are Decimal-compatible strings — never float.
Events emitted:
  ops.mrp.run.started               — MRP run initiated
  ops.mrp.planned_order.created     — planned order created for a product
  ops.mrp.purchase_req.created      — purchase requisition recommended
  ops.mrp.production_order.recommended — production order recommended
  ops.mrp.run.completed             — MRP run finished successfully
  ops.mrp.safety_stock.breach       — product stock below safety level
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class MRPRunStartedEvent(DomainEvent):
	"""Emitted when an MRP run is initiated."""
	event_type: str = "ops.mrp.run.started"
	run_id: str = ""
	tenant_id: str = ""
	period: str = ""
	horizon_days: int = 90
	entity_id: str = ""


@dataclass
class PlannedOrderCreatedEvent(DomainEvent):
	"""Emitted when a planned order is created for a product during an MRP run."""
	event_type: str = "ops.mrp.planned_order.created"
	order_id: str = ""
	product_id: str = ""
	required_qty: str = ""		# Decimal string
	planned_qty: str = ""		# Decimal string — rounded to lot_size
	required_date: str = ""		# ISO date string
	planned_start_date: str = ""	# ISO date string
	order_type: str = ""		# PURCHASE | PRODUCTION
	run_id: str = ""


@dataclass
class PurchaseRequisitionCreatedEvent(DomainEvent):
	"""Emitted when a purchase requisition is recommended for a product."""
	event_type: str = "ops.mrp.purchase_req.created"
	req_id: str = ""
	product_id: str = ""
	qty: str = ""			# Decimal string
	supplier_id: str = ""
	required_date: str = ""		# ISO date string
	run_id: str = ""


@dataclass
class ProductionOrderRecommendedEvent(DomainEvent):
	"""Emitted when a production order is recommended during BOM explosion."""
	event_type: str = "ops.mrp.production_order.recommended"
	product_id: str = ""
	qty: str = ""			# Decimal string
	start_date: str = ""		# ISO date string
	end_date: str = ""		# ISO date string
	bom_id: str = ""
	run_id: str = ""


@dataclass
class MRPRunCompletedEvent(DomainEvent):
	"""Emitted when an MRP run finishes successfully."""
	event_type: str = "ops.mrp.run.completed"
	run_id: str = ""
	planned_orders_count: int = 0
	requisitions_count: int = 0
	duration_seconds: float = 0.0
	period: str = ""


@dataclass
class SafetyStockBreachEvent(DomainEvent):
	"""Emitted when a product's current stock falls below its safety stock qty."""
	event_type: str = "ops.mrp.safety_stock.breach"
	product_id: str = ""
	current_stock: str = ""		# Decimal string
	safety_stock_qty: str = ""	# Decimal string
	deficit: str = ""		# Decimal string — safety_stock_qty - current_stock


__all__ = [
	"MRPRunStartedEvent",
	"PlannedOrderCreatedEvent",
	"PurchaseRequisitionCreatedEvent",
	"ProductionOrderRecommendedEvent",
	"MRPRunCompletedEvent",
	"SafetyStockBreachEvent",
]
