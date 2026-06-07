"""
pgappforge/plugins/erp/operations/assembly/events.py

Domain events for the Assembly Management plugin.

All monetary amounts are integer cents — never float.
Quantities are Decimal-compatible strings where precision matters.

Events emitted:
  ops.assembly.created            — new assembly order created
  ops.assembly.posted             — order posted; components consumed, FG added
  ops.assembly.component.consumed — single component line consumed during posting
  ops.assembly.cancelled          — order cancelled before posting
  ops.assembly.variance           — actual vs standard cost variance posted to GL
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Assembly order lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class AssemblyOrderCreatedEvent(DomainEvent):
	"""Emitted when a new assembly order is created in DRAFT status."""
	event_type: str = "ops.assembly.created"
	order_id: str = ""
	output_product_id: str = ""
	qty: str = ""        # Decimal string — avoid float
	tenant_id: str = ""


@dataclass
class AssemblyOrderPostedEvent(DomainEvent):
	"""Emitted when assembly order posting completes: FG added to stock."""
	event_type: str = "ops.assembly.posted"
	order_id: str = ""
	output_product_id: str = ""
	qty: str = ""        # Decimal string
	cost_cents: int = 0  # Actual total cost in cents


@dataclass
class AssemblyComponentConsumedEvent(DomainEvent):
	"""Emitted once per component line when stock is consumed during posting."""
	event_type: str = "ops.assembly.component.consumed"
	order_id: str = ""
	component_id: str = ""
	qty: str = ""        # Decimal string — actual quantity consumed
	cost_cents: int = 0  # Total cost for this component in cents


@dataclass
class AssemblyOrderCancelledEvent(DomainEvent):
	"""Emitted when an assembly order is cancelled before posting."""
	event_type: str = "ops.assembly.cancelled"
	order_id: str = ""
	reason: str = ""


@dataclass
class AssemblyVariancePostedEvent(DomainEvent):
	"""Emitted when actual_cost_cents != standard_cost_cents and GL variance is posted."""
	event_type: str = "ops.assembly.variance"
	order_id: str = ""
	variance_cents: int = 0  # Signed: positive = over-cost, negative = under-cost


__all__ = [
	"AssemblyOrderCreatedEvent",
	"AssemblyOrderPostedEvent",
	"AssemblyComponentConsumedEvent",
	"AssemblyOrderCancelledEvent",
	"AssemblyVariancePostedEvent",
]
