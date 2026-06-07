"""
pgappforge/plugins/erp/procurement/spend_analytics/events.py

Spend Analytics domain events.

Events emitted:
  procurement.spend.cube.computed      — spend cube computation completed
  procurement.spend.savings.identified — savings opportunity flagged for a supplier
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class SpendCubeComputedEvent(DomainEvent):
	event_type: str = "procurement.spend.cube.computed"
	tenant_id: str = ""
	period: str = ""
	total_cents: int = 0
	supplier_count: int = 0


@dataclass
class SavingsOpportunityIdentifiedEvent(DomainEvent):
	event_type: str = "procurement.spend.savings.identified"
	supplier_id: str = ""
	potential_savings_cents: int = 0
	reason: str = ""


__all__ = [
	"SpendCubeComputedEvent",
	"SavingsOpportunityIdentifiedEvent",
]
