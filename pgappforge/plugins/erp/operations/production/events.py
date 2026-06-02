"""
pgappforge/plugins/erp/operations/production/events.py

Domain events for the Production Planning plugin.

Emitted events:
  pp.bom.activated          — BOM version promoted to ACTIVE
  pp.bom.obsoleted          — BOM version set to OBSOLETE
  pp.production_order.released   — order moves PLANNED → RELEASED
  pp.production_order.started    — order moves RELEASED → IN_PROGRESS
  pp.production_order.completed  — order moves IN_PROGRESS → COMPLETED
  pp.production_order.cancelled  — order CANCELLED at any stage
  pp.component.issued       — material issued to shop floor
  pp.operation.completed    — routing operation step confirmed
  pp.forecast.updated       — demand forecast revised

Consumed events (from upstream):
  scm.purchase_order.goods_received  — may trigger material availability update
  qc.inspection.failed               — may block production order release
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class BOMActivatedEvent(DomainEvent):
	event_type: str = "pp.bom.activated"
	bom_id: str = ""
	product_id: str = ""
	version: str = ""


@dataclass
class BOMObsoletedEvent(DomainEvent):
	event_type: str = "pp.bom.obsoleted"
	bom_id: str = ""
	product_id: str = ""
	version: str = ""
	superseded_by_version: str = ""


@dataclass
class ProductionOrderReleasedEvent(DomainEvent):
	event_type: str = "pp.production_order.released"
	order_id: str = ""
	order_number: str = ""
	product_id: str = ""
	planned_quantity: str = ""  # Decimal as string — never float
	start_date: str = ""
	work_center_id: str = ""


@dataclass
class ProductionOrderStartedEvent(DomainEvent):
	event_type: str = "pp.production_order.started"
	order_id: str = ""
	order_number: str = ""
	product_id: str = ""
	work_center_id: str = ""


@dataclass
class ProductionOrderCompletedEvent(DomainEvent):
	event_type: str = "pp.production_order.completed"
	order_id: str = ""
	order_number: str = ""
	product_id: str = ""
	produced_quantity: str = ""  # Decimal as string
	actual_cost_cents: int = 0
	planned_cost_cents: int = 0


@dataclass
class ProductionOrderCancelledEvent(DomainEvent):
	event_type: str = "pp.production_order.cancelled"
	order_id: str = ""
	order_number: str = ""
	product_id: str = ""
	reason: str = ""


@dataclass
class ComponentIssuedEvent(DomainEvent):
	event_type: str = "pp.component.issued"
	production_order_id: str = ""
	order_number: str = ""
	component_product_id: str = ""
	issued_quantity: str = ""  # Decimal as string
	uom: str = ""
	warehouse_id: str = ""


@dataclass
class OperationCompletedEvent(DomainEvent):
	event_type: str = "pp.operation.completed"
	production_order_id: str = ""
	operation_id: str = ""
	operation_number: int = 0
	work_center_id: str = ""
	actual_time_minutes: int = 0
	labor_cost_cents: int = 0
	completed_by: str = ""


@dataclass
class DemandForecastUpdatedEvent(DomainEvent):
	event_type: str = "pp.forecast.updated"
	forecast_id: str = ""
	product_id: str = ""
	warehouse_id: str = ""
	forecast_date: str = ""
	forecast_quantity: str = ""  # Decimal as string
	forecast_method: str = ""


__all__ = [
	"BOMActivatedEvent",
	"BOMObsoletedEvent",
	"ProductionOrderReleasedEvent",
	"ProductionOrderStartedEvent",
	"ProductionOrderCompletedEvent",
	"ProductionOrderCancelledEvent",
	"ComponentIssuedEvent",
	"OperationCompletedEvent",
	"DemandForecastUpdatedEvent",
]
