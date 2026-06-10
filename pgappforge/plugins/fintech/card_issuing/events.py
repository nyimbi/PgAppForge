"""
pgappforge/plugins/fintech/card_issuing/events.py

Card Issuing domain events.

All events extend DomainEvent from erp.foundation.events.
They are emitted by CardIssuingService and should be persisted atomically
within the same SQLAlchemy session as the triggering operation.

Event catalogue
---------------
  card.issued       — new virtual card issued
  card.activated    — card status transitions INACTIVE → ACTIVE
  card.blocked      — card blocked (fraud, PIN lockout, operator)
  card.pin_set      — PIN set or changed
  card.authorized   — authorization attempt (approved or declined)
  card.replaced     — card replaced (old blocked, new issued)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Card lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class CardIssuedEvent(DomainEvent):
	"""Emitted when a new virtual card is issued."""
	event_type: str = "card.issued"
	card_id: str = ""
	account_id: str = ""
	bin_code: str = ""
	card_number_masked: str = ""
	card_number_last4: str = ""
	cardholder_name: str = ""
	is_virtual: bool = True
	expiry_month: int = 0
	expiry_year: int = 0


@dataclass
class CardActivatedEvent(DomainEvent):
	"""Emitted when a card is activated (INACTIVE → ACTIVE)."""
	event_type: str = "card.activated"
	card_id: str = ""
	account_id: str = ""
	card_number_masked: str = ""
	activated_at: str = ""  # ISO datetime string


@dataclass
class CardBlockedEvent(DomainEvent):
	"""Emitted when a card is blocked."""
	event_type: str = "card.blocked"
	card_id: str = ""
	account_id: str = ""
	card_number_masked: str = ""
	block_reason: str = ""


@dataclass
class CardPINSetEvent(DomainEvent):
	"""Emitted when a card PIN is set or changed."""
	event_type: str = "card.pin_set"
	card_id: str = ""
	account_id: str = ""
	card_number_masked: str = ""
	pin_set_at: str = ""  # ISO datetime string


@dataclass
class CardAuthorizationEvent(DomainEvent):
	"""Emitted for every card authorization attempt (approved or declined)."""
	event_type: str = "card.authorized"
	card_id: str = ""
	account_id: str = ""
	card_number_masked: str = ""
	authorization_type: str = ""
	amount_cents: int = 0
	currency_code: str = "KES"
	result: str = ""
	authorization_code: str = ""
	decline_reason: str = ""
	rrn: str = ""
	merchant_name: str = ""
	merchant_category_code: str = ""


@dataclass
class CardReplacedEvent(DomainEvent):
	"""Emitted when a card is replaced (old card blocked, new card issued)."""
	event_type: str = "card.replaced"
	old_card_id: str = ""
	new_card_id: str = ""
	account_id: str = ""
	old_card_masked: str = ""
	new_card_masked: str = ""
	replace_reason: str = ""


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

CI_CARD_ISSUED = "card.issued"
CI_CARD_ACTIVATED = "card.activated"
CI_CARD_BLOCKED = "card.blocked"
CI_CARD_PIN_SET = "card.pin_set"
CI_CARD_AUTHORIZED = "card.authorized"
CI_CARD_REPLACED = "card.replaced"

ALL_CI_EVENT_TYPES: list[str] = [
	CI_CARD_ISSUED,
	CI_CARD_ACTIVATED,
	CI_CARD_BLOCKED,
	CI_CARD_PIN_SET,
	CI_CARD_AUTHORIZED,
	CI_CARD_REPLACED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"CardIssuedEvent",
	"CardActivatedEvent",
	"CardBlockedEvent",
	"CardPINSetEvent",
	"CardAuthorizationEvent",
	"CardReplacedEvent",
	# event type constants
	"CI_CARD_ISSUED",
	"CI_CARD_ACTIVATED",
	"CI_CARD_BLOCKED",
	"CI_CARD_PIN_SET",
	"CI_CARD_AUTHORIZED",
	"CI_CARD_REPLACED",
	"ALL_CI_EVENT_TYPES",
]
