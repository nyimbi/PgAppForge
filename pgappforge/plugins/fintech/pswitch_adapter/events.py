"""
pgappforge/plugins/fintech/pswitch_adapter/events.py

Pswitch Adapter domain events.

Emitted by PswitchAdapterService and persisted atomically to
DomainEventLog within the same SQLAlchemy session as the business mutation.

Event catalogue
---------------
  pswitch.card.authorized       — card authorization approved
  pswitch.card.declined         — card authorization declined
  pswitch.card.settled          — card transaction settled via settlement file
  pswitch.card.reversed         — card transaction reversed
  pswitch.settlement.processed  — settlement file fully processed / posted
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"CardAuthorizedEvent",
	"CardDeclinedEvent",
	"CardSettledEvent",
	"CardReversedEvent",
	"SettlementFileProcessedEvent",
	"ALL_PSWITCH_EVENT_TYPES",
]


# ---------------------------------------------------------------------------
# Card authorization events
# ---------------------------------------------------------------------------

@dataclass
class CardAuthorizedEvent(DomainEvent):
	"""Emitted when a card authorization is approved (response_code='00')."""
	event_type: str = "pswitch.card.authorized"
	card_transaction_id: str = ""
	pswitch_txn_id: str = ""
	account_id: str = ""
	account_number: str = ""
	card_pan_masked: str = ""
	card_scheme: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	auth_code: str = ""
	hold_id: str = ""
	merchant_name: str = ""
	merchant_category_code: str = ""
	terminal_id: str = ""


@dataclass
class CardDeclinedEvent(DomainEvent):
	"""Emitted when a card authorization is declined (response_code != '00')."""
	event_type: str = "pswitch.card.declined"
	card_transaction_id: str = ""
	pswitch_txn_id: str = ""
	account_id: str = ""
	account_number: str = ""
	card_pan_masked: str = ""
	card_scheme: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	response_code: str = ""
	decline_reason: str = ""
	merchant_name: str = ""
	merchant_category_code: str = ""
	terminal_id: str = ""


# ---------------------------------------------------------------------------
# Card settlement / reversal events
# ---------------------------------------------------------------------------

@dataclass
class CardSettledEvent(DomainEvent):
	"""Emitted when a card transaction is settled via a settlement file."""
	event_type: str = "pswitch.card.settled"
	card_transaction_id: str = ""
	pswitch_txn_id: str = ""
	account_id: str = ""
	settlement_file_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	ledger_entry_id: str = ""


@dataclass
class CardReversedEvent(DomainEvent):
	"""Emitted when a card transaction authorization is reversed."""
	event_type: str = "pswitch.card.reversed"
	card_transaction_id: str = ""
	pswitch_txn_id: str = ""
	account_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	reversal_reason: str = ""
	hold_released: bool = False


# ---------------------------------------------------------------------------
# Settlement file events
# ---------------------------------------------------------------------------

@dataclass
class SettlementFileProcessedEvent(DomainEvent):
	"""Emitted when a settlement file is fully processed and posted to GL."""
	event_type: str = "pswitch.settlement.processed"
	settlement_file_id: str = ""
	file_ref: str = ""
	source: str = ""
	record_count: int = 0
	processed: int = 0
	matched: int = 0
	unmatched: int = 0
	total_settled_cents: int = 0
	total_debits_cents: int = 0
	total_credits_cents: int = 0


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------

ALL_PSWITCH_EVENT_TYPES: list[str] = [
	"pswitch.card.authorized",
	"pswitch.card.declined",
	"pswitch.card.settled",
	"pswitch.card.reversed",
	"pswitch.settlement.processed",
]
