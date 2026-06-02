"""
pgappforge/plugins/erp/operations/scm/events.py

Domain events for the Supply Chain Management plugin.

Emitted events:
  scm.supplier.created         — new supplier onboarded
  scm.supplier.approved        — supplier set as preferred/approved
  scm.supplier.kpi_updated     — rating / OTD% / quality_score recalculated
  scm.supplier_product.created — new sourcing price record added
  scm.shipment.created         — new shipment tracking record
  scm.shipment.status_changed  — shipment milestone update
  scm.shipment.delivered       — shipment reached destination
  scm.shipment.exception       — shipment exception flagged

Consumed events (from upstream):
  ap.invoice.approved          — may trigger lead-time / quality KPI refresh
  pp.production_order.released — may trigger replenishment purchase order creation
  qc.inspection.failed         — feeds supplier quality_score recalculation
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class SupplierCreatedEvent(DomainEvent):
	event_type: str = "scm.supplier.created"
	supplier_id: str = ""
	supplier_code: str = ""
	name: str = ""
	party_id: str = ""


@dataclass
class SupplierApprovedEvent(DomainEvent):
	event_type: str = "scm.supplier.approved"
	supplier_id: str = ""
	supplier_code: str = ""
	approved_by: str = ""


@dataclass
class SupplierKPIUpdatedEvent(DomainEvent):
	event_type: str = "scm.supplier.kpi_updated"
	supplier_id: str = ""
	supplier_code: str = ""
	rating: str = ""          # Decimal as string
	on_time_delivery_pct: str = ""
	quality_score: str = ""
	period_days: int = 365


@dataclass
class SupplierProductCreatedEvent(DomainEvent):
	event_type: str = "scm.supplier_product.created"
	supplier_product_id: str = ""
	supplier_id: str = ""
	product_id: str = ""
	price_cents: int = 0
	currency_code: str = ""
	lead_time_days: int = 0
	valid_from: str = ""


@dataclass
class ShipmentCreatedEvent(DomainEvent):
	event_type: str = "scm.shipment.created"
	shipment_id: str = ""
	carrier: str = ""
	tracking_number: str = ""
	supplier_id: str = ""
	destination_warehouse_id: str = ""
	estimated_arrival: str = ""


@dataclass
class ShipmentStatusChangedEvent(DomainEvent):
	event_type: str = "scm.shipment.status_changed"
	shipment_id: str = ""
	carrier: str = ""
	tracking_number: str = ""
	old_status: str = ""
	new_status: str = ""
	location: str = ""
	note: str = ""


@dataclass
class ShipmentDeliveredEvent(DomainEvent):
	event_type: str = "scm.shipment.delivered"
	shipment_id: str = ""
	carrier: str = ""
	tracking_number: str = ""
	supplier_id: str = ""
	destination_warehouse_id: str = ""
	actual_arrival: str = ""
	estimated_arrival: str = ""
	days_variance: int = 0    # positive = late, negative = early


@dataclass
class ShipmentExceptionEvent(DomainEvent):
	event_type: str = "scm.shipment.exception"
	shipment_id: str = ""
	carrier: str = ""
	tracking_number: str = ""
	exception_description: str = ""
	location: str = ""


__all__ = [
	"SupplierCreatedEvent",
	"SupplierApprovedEvent",
	"SupplierKPIUpdatedEvent",
	"SupplierProductCreatedEvent",
	"ShipmentCreatedEvent",
	"ShipmentStatusChangedEvent",
	"ShipmentDeliveredEvent",
	"ShipmentExceptionEvent",
]
