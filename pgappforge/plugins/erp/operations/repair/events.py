"""
pgappforge/plugins/erp/operations/repair/events.py

Domain events for the Repair / RMA plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  ops.repair.created            — new repair order received
  ops.repair.diagnosed          — technician recorded diagnosis
  ops.repair.completed          — repair work finished, moved to QC/READY
  ops.repair.returned           — unit returned to customer
  ops.repair.warranty.created   — warranty claim opened
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class RepairOrderCreatedEvent(DomainEvent):
	"""Emitted when a new RepairOrder is created."""
	event_type: str = "ops.repair.created"
	order_id: str = ""
	customer_id: str = ""
	product_name: str = ""


@dataclass
class RepairDiagnosedEvent(DomainEvent):
	"""Emitted when a technician records diagnosis on a RepairOrder."""
	event_type: str = "ops.repair.diagnosed"
	order_id: str = ""
	technician_id: str = ""
	diagnosis: str = ""
	estimated_cost_cents: int = 0


@dataclass
class RepairCompletedEvent(DomainEvent):
	"""Emitted when repair work is completed and order moves to QC."""
	event_type: str = "ops.repair.completed"
	order_id: str = ""
	technician_id: str = ""
	actual_cost_cents: int = 0


@dataclass
class RepairReturnedToCustomerEvent(DomainEvent):
	"""Emitted when a repaired unit is returned to the customer."""
	event_type: str = "ops.repair.returned"
	order_id: str = ""
	customer_id: str = ""
	return_date: str = ""   # ISO date string


@dataclass
class WarrantyClaimCreatedEvent(DomainEvent):
	"""Emitted when a new WarrantyClaim is opened."""
	event_type: str = "ops.repair.warranty.created"
	claim_id: str = ""
	order_id: str = ""
	serial_number: str = ""


__all__ = [
	"RepairOrderCreatedEvent",
	"RepairDiagnosedEvent",
	"RepairCompletedEvent",
	"RepairReturnedToCustomerEvent",
	"WarrantyClaimCreatedEvent",
]
