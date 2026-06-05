"""
pgappforge/plugins/erp/industry/real_estate/events.py

Domain events for the Real Estate plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  realestate.property.listed      — new property listed on MLS
  realestate.property.sold        — property sold (transaction closed)
  realestate.transaction.closed   — transaction reached CLOSED status
  realestate.lease.signed         — lease agreement activated
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Property events
# ---------------------------------------------------------------------------

@dataclass
class PropertyListedEvent(DomainEvent):
	"""Emitted when a new property is listed (status=ACTIVE)."""
	event_type: str = "realestate.property.listed"
	property_id: str = ""
	mls_number: str = ""
	property_type: str = ""
	list_price_cents: int = 0
	listing_agent_id: str = ""
	listing_date: str = ""        # ISO date


@dataclass
class PropertySoldEvent(DomainEvent):
	"""Emitted when a property status transitions to SOLD."""
	event_type: str = "realestate.property.sold"
	property_id: str = ""
	mls_number: str = ""
	sold_price_cents: int = 0
	closing_date: str = ""        # ISO date
	days_on_market: int = 0


# ---------------------------------------------------------------------------
# Transaction events
# ---------------------------------------------------------------------------

@dataclass
class TransactionClosedEvent(DomainEvent):
	"""Emitted when a real estate transaction reaches CLOSED status."""
	event_type: str = "realestate.transaction.closed"
	transaction_id: str = ""
	property_id: str = ""
	sale_price_cents: int = 0
	commission_cents: int = 0
	closing_date: str = ""        # ISO date
	listing_agent_id: str = ""
	buyers_agent_id: str = ""


# ---------------------------------------------------------------------------
# Lease events
# ---------------------------------------------------------------------------

@dataclass
class LeaseSignedEvent(DomainEvent):
	"""Emitted when a lease agreement transitions to ACTIVE."""
	event_type: str = "realestate.lease.signed"
	lease_id: str = ""
	property_id: str = ""
	tenant_party_id: str = ""
	landlord_party_id: str = ""
	monthly_rent_cents: int = 0
	lease_start: str = ""         # ISO date
	lease_end: str = ""           # ISO date


__all__ = [
	"PropertyListedEvent",
	"PropertySoldEvent",
	"TransactionClosedEvent",
	"LeaseSignedEvent",
]
