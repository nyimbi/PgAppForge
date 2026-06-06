from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"LunchOrderPlacedEvent",
	"LunchOrderCancelledEvent",
	"LunchSubsidyAppliedEvent",
	"LunchSupplierDeliveredEvent",
]


@dataclass
class LunchOrderPlacedEvent(DomainEvent):
	event_type: str = field(default="hcm.lunch.order.placed", init=False)
	order_id: str = ""
	employee_id: str = ""
	menu_date: str = ""  # ISO date string
	items: list[Any] = field(default_factory=list)
	total_cents: int = 0


@dataclass
class LunchOrderCancelledEvent(DomainEvent):
	event_type: str = field(default="hcm.lunch.order.cancelled", init=False)
	order_id: str = ""
	employee_id: str = ""
	reason: str = ""


@dataclass
class LunchSubsidyAppliedEvent(DomainEvent):
	event_type: str = field(default="hcm.lunch.subsidy.applied", init=False)
	order_id: str = ""
	employee_id: str = ""
	subsidy_cents: int = 0


@dataclass
class LunchSupplierDeliveredEvent(DomainEvent):
	event_type: str = field(default="hcm.lunch.supplier.delivered", init=False)
	supplier_id: str = ""
	menu_date: str = ""  # ISO date string
	items_count: int = 0
