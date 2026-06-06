"""
pgappforge/plugins/erp/operations/rental/events.py

Domain events for the Rental Management plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  ops.rental.created          — rental order placed
  ops.rental.started          — rental period activated
  ops.rental.returned         — asset returned
  ops.rental.deposit.charged  — damage deposit charge applied
  ops.rental.invoiced         — rental invoice generated
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class RentalOrderCreatedEvent(DomainEvent):
	"""Emitted when a new RentalOrder is placed."""
	event_type: str = "ops.rental.created"
	order_id: str = ""
	asset_id: str = ""
	customer_id: str = ""
	start_date: str = ""   # ISO date
	end_date: str = ""     # ISO date


@dataclass
class RentalStartedEvent(DomainEvent):
	"""Emitted when a rental transitions from PENDING to ACTIVE."""
	event_type: str = "ops.rental.started"
	order_id: str = ""
	asset_id: str = ""
	start_date: str = ""   # ISO date


@dataclass
class RentalReturnedEvent(DomainEvent):
	"""Emitted when an asset is returned by the customer."""
	event_type: str = "ops.rental.returned"
	order_id: str = ""
	asset_id: str = ""
	return_date: str = ""   # ISO date
	condition: str = ""


@dataclass
class DamageDepositChargedEvent(DomainEvent):
	"""Emitted when a damage charge is applied against the deposit."""
	event_type: str = "ops.rental.deposit.charged"
	order_id: str = ""
	amount_cents: int = 0


@dataclass
class RentalInvoiceGeneratedEvent(DomainEvent):
	"""Emitted when a rental invoice is generated."""
	event_type: str = "ops.rental.invoiced"
	order_id: str = ""
	amount_cents: int = 0


__all__ = [
	"RentalOrderCreatedEvent",
	"RentalStartedEvent",
	"RentalReturnedEvent",
	"DamageDepositChargedEvent",
	"RentalInvoiceGeneratedEvent",
]
