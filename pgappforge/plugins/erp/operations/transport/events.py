"""
pgappforge/plugins/erp/operations/transport/events.py

Domain events for the Transport Management plugin.

All monetary amounts are integer cents — never float.
Timestamps are ISO-format strings; dates are ISO date strings.

Events emitted:
  ops.transport.shipment.created     — new shipment row created
  ops.transport.shipment.dispatched  — shipment handed to driver/vehicle
  ops.transport.shipment.delivered   — proof of delivery recorded
  ops.transport.freight.computed     — freight cost computed against a rate card
  ops.transport.carrier.performance  — carrier on-time rate refreshed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Shipment events
# ---------------------------------------------------------------------------

@dataclass
class ShipmentCreatedEvent(DomainEvent):
	"""Emitted when a new Shipment row is created."""
	event_type: str = "ops.transport.shipment.created"
	shipment_id: str = ""
	origin: str = ""
	destination: str = ""
	carrier_id: str = ""       # "" when no carrier assigned yet
	tenant_id: str = ""


@dataclass
class ShipmentDispatchedEvent(DomainEvent):
	"""Emitted when a shipment transitions BOOKED → DISPATCHED."""
	event_type: str = "ops.transport.shipment.dispatched"
	shipment_id: str = ""
	dispatched_at: str = ""    # ISO datetime
	driver_id: str = ""


@dataclass
class ShipmentDeliveredEvent(DomainEvent):
	"""Emitted when a shipment transitions IN_TRANSIT → DELIVERED."""
	event_type: str = "ops.transport.shipment.delivered"
	shipment_id: str = ""
	delivered_at: str = ""     # ISO datetime
	pod_ref: str = ""          # proof-of-delivery reference


# ---------------------------------------------------------------------------
# Freight cost event
# ---------------------------------------------------------------------------

@dataclass
class FreightCostComputedEvent(DomainEvent):
	"""Emitted after freight cost is calculated and stored on a Shipment."""
	event_type: str = "ops.transport.freight.computed"
	shipment_id: str = ""
	cost_cents: int = 0
	rate_id: str = ""          # FreightRate.id that was used


# ---------------------------------------------------------------------------
# Carrier performance event
# ---------------------------------------------------------------------------

@dataclass
class CarrierPerformanceUpdatedEvent(DomainEvent):
	"""Emitted when a carrier's on-time delivery rate is recomputed."""
	event_type: str = "ops.transport.carrier.performance"
	carrier_id: str = ""
	on_time_rate_pct: str = ""  # Decimal string
	period: str = ""            # e.g. "2025-Q1" or "2025-05"


__all__ = [
	"ShipmentCreatedEvent",
	"ShipmentDispatchedEvent",
	"ShipmentDeliveredEvent",
	"FreightCostComputedEvent",
	"CarrierPerformanceUpdatedEvent",
]
