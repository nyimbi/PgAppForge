"""
pgappforge/plugins/fintech/treasury/events.py

Treasury domain events.

All events extend DomainEvent from erp.foundation.events.
Emitted by TreasuryService; wrapped in try/except at call sites so a
publish failure never aborts a financial transaction.

Event catalogue
---------------
  fx.deal.booked       — new FX deal booked (BOOKED status)
  fx.deal.settled      — FX deal settled (SETTLED status)
  fx.position.revalued — end-of-day position revaluation completed
  fx.limit.breached    — a treasury limit was breached (WARN) or would have
                         been breached (BLOCK action emitted before raising)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Deal events
# ---------------------------------------------------------------------------

@dataclass
class FXDealBookedEvent(DomainEvent):
	"""Emitted when a new FX deal is booked (status = BOOKED)."""
	event_type: str = "fx.deal.booked"
	deal_id: str = ""
	deal_number: str = ""
	deal_type: str = ""           # SPOT | FORWARD | SWAP | NDF
	bought_currency: str = ""
	sold_currency: str = ""
	bought_amount_cents: int = 0
	sold_amount_cents: int = 0
	exchange_rate: str = ""       # Decimal serialised as string
	trade_date: str = ""          # ISO date string
	value_date: str = ""          # ISO date string
	counterparty_id: str = ""
	trader_id: str = ""
	tenant_id: str = ""


@dataclass
class FXDealSettledEvent(DomainEvent):
	"""Emitted when an FX deal is settled (status = SETTLED)."""
	event_type: str = "fx.deal.settled"
	deal_id: str = ""
	deal_number: str = ""
	bought_currency: str = ""
	sold_currency: str = ""
	bought_amount_cents: int = 0
	sold_amount_cents: int = 0
	settled_at: str = ""          # ISO datetime string
	pnl_cents: int = 0
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Revaluation events
# ---------------------------------------------------------------------------

@dataclass
class FXPositionRevaluedEvent(DomainEvent):
	"""Emitted after end-of-day revaluation batch completes."""
	event_type: str = "fx.position.revalued"
	revaluation_date: str = ""    # ISO date string
	total_positions: int = 0
	total_pnl_cents: int = 0
	by_currency: dict = field(default_factory=dict)
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Limit events
# ---------------------------------------------------------------------------

@dataclass
class FXLimitBreachedEvent(DomainEvent):
	"""Emitted when a treasury limit is breached or would be breached.

	breach_action == WARN  → limit already breached, deal allowed through
	breach_action == BLOCK → deal rejected; event emitted before raising
	                         TreasuryLimitBreachError
	"""
	event_type: str = "fx.limit.breached"
	limit_id: str = ""
	limit_type: str = ""          # OPEN_POSITION | COUNTERPARTY | STOP_LOSS | DEAL_SIZE
	currency_code: str = ""
	counterparty_id: str = ""
	limit_amount_cents: int = 0
	current_utilisation_cents: int = 0
	additional_cents: int = 0
	breach_action: str = ""       # WARN | BLOCK
	tenant_id: str = ""


# ---------------------------------------------------------------------------
# Event type string constants
# ---------------------------------------------------------------------------

FX_DEAL_BOOKED = "fx.deal.booked"
FX_DEAL_SETTLED = "fx.deal.settled"
FX_POSITION_REVALUED = "fx.position.revalued"
FX_LIMIT_BREACHED = "fx.limit.breached"

ALL_TREASURY_EVENT_TYPES: list[str] = [
	FX_DEAL_BOOKED,
	FX_DEAL_SETTLED,
	FX_POSITION_REVALUED,
	FX_LIMIT_BREACHED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"FXDealBookedEvent",
	"FXDealSettledEvent",
	"FXPositionRevaluedEvent",
	"FXLimitBreachedEvent",
	# string constants
	"FX_DEAL_BOOKED",
	"FX_DEAL_SETTLED",
	"FX_POSITION_REVALUED",
	"FX_LIMIT_BREACHED",
	"ALL_TREASURY_EVENT_TYPES",
]
