"""
pgappforge/plugins/fintech/core_banking/events.py

Core Banking domain events.

All events extend DomainEvent from erp.foundation.events.
They are emitted by CoreBankingService and persisted atomically
to the DomainEventLog within the same SQLAlchemy session.

Event catalogue
---------------
  cb.account.opened        — new account activated
  cb.account.credited      — funds deposited / transferred in
  cb.account.debited       — funds withdrawn / transferred out
  cb.account.transferred   — intra-bank transfer (both legs)
  cb.interest.accrued      — daily accrual batch completed
  cb.interest.capitalized  — accrued interest posted to account balance
  cb.account.closed        — account closed
  cb.account.dormant       — account marked dormant
  cb.hold.placed           — new hold placed on account
  cb.hold.released         — hold released
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Account lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class AccountOpenedEvent(DomainEvent):
	"""Emitted when a new account is activated (status → ACTIVE)."""
	event_type: str = "cb.account.opened"
	account_id: str = ""
	account_number: str = ""
	customer_id: str = ""
	product_code: str = ""
	currency_code: str = ""
	branch_code: str = ""
	opening_deposit_cents: int = 0


@dataclass
class AccountCreditedEvent(DomainEvent):
	"""Emitted whenever funds are credited to an account."""
	event_type: str = "cb.account.credited"
	account_id: str = ""
	account_number: str = ""
	journal_id: str = ""
	entry_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	transaction_type: str = ""
	channel: str = ""
	reference_number: str = ""
	new_balance_cents: int = 0


@dataclass
class AccountDebitedEvent(DomainEvent):
	"""Emitted whenever funds are debited from an account."""
	event_type: str = "cb.account.debited"
	account_id: str = ""
	account_number: str = ""
	journal_id: str = ""
	entry_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	transaction_type: str = ""
	channel: str = ""
	reference_number: str = ""
	new_balance_cents: int = 0


@dataclass
class AccountTransferredEvent(DomainEvent):
	"""Emitted once per intra-bank transfer (covers both DEBIT and CREDIT legs)."""
	event_type: str = "cb.account.transferred"
	journal_id: str = ""
	from_account_id: str = ""
	from_account_number: str = ""
	to_account_id: str = ""
	to_account_number: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	exchange_rate: str = "1"  # Decimal serialised as string
	reference_number: str = ""
	debit_entry_id: str = ""
	credit_entry_id: str = ""


@dataclass
class AccountClosedEvent(DomainEvent):
	"""Emitted when an account transitions to CLOSED status."""
	event_type: str = "cb.account.closed"
	account_id: str = ""
	account_number: str = ""
	customer_id: str = ""
	reason: str = ""
	closing_balance_cents: int = 0
	closing_balance_destination: str = ""


@dataclass
class AccountDormantEvent(DomainEvent):
	"""Emitted when a dormancy check marks an account DORMANT."""
	event_type: str = "cb.account.dormant"
	account_id: str = ""
	account_number: str = ""
	customer_id: str = ""
	last_transaction_date: str = ""  # ISO date string
	days_inactive: int = 0


# ---------------------------------------------------------------------------
# Interest events
# ---------------------------------------------------------------------------

@dataclass
class InterestAccruedEvent(DomainEvent):
	"""Emitted after the daily batch accrual run completes."""
	event_type: str = "cb.interest.accrued"
	accrual_date: str = ""  # ISO date string
	product_type: str = ""  # empty string = all products
	accounts_processed: int = 0
	total_accrued_cents: int = 0


@dataclass
class InterestCapitalizedEvent(DomainEvent):
	"""Emitted when accrued interest is capitalised (posted to balance)."""
	event_type: str = "cb.interest.capitalized"
	account_id: str = ""
	account_number: str = ""
	journal_id: str = ""
	capitalized_cents: int = 0
	new_balance_cents: int = 0
	capitalization_date: str = ""  # ISO date string
	accrual_records_count: int = 0


# ---------------------------------------------------------------------------
# Hold events
# ---------------------------------------------------------------------------

@dataclass
class HoldPlacedEvent(DomainEvent):
	"""Emitted when a new hold is placed on an account."""
	event_type: str = "cb.hold.placed"
	hold_id: str = ""
	account_id: str = ""
	account_number: str = ""
	amount_cents: int = 0
	hold_reason: str = ""
	reference_number: str = ""
	expires_at: str = ""  # ISO datetime string or empty


@dataclass
class HoldReleasedEvent(DomainEvent):
	"""Emitted when a hold is released (manually or via expiry)."""
	event_type: str = "cb.hold.released"
	hold_id: str = ""
	account_id: str = ""
	account_number: str = ""
	amount_cents: int = 0
	release_reason: str = ""


# ---------------------------------------------------------------------------
# Reversal events
# ---------------------------------------------------------------------------

@dataclass
class TransactionReversedEvent(DomainEvent):
	"""Emitted when a journal is reversed (new REVERSAL entries created)."""
	event_type: str = "cb.transaction.reversed"
	reversal_journal_id: str = ""
	reversed_journal_id: str = ""
	entries_reversed: int = 0
	reason: str = ""


# ---------------------------------------------------------------------------
# Fee events
# ---------------------------------------------------------------------------

@dataclass
class FeeChargedEvent(DomainEvent):
	"""Emitted when a fee is charged to an account."""
	event_type: str = "cb.fee.charged"
	account_id: str = ""
	account_number: str = ""
	journal_id: str = ""
	entry_id: str = ""
	fee_type: str = ""
	amount_cents: int = 0
	new_balance_cents: int = 0


# ---------------------------------------------------------------------------
# Hold expiry events
# ---------------------------------------------------------------------------

@dataclass
class HoldExpiredEvent(DomainEvent):
	"""Emitted when a hold is automatically expired (expires_at has passed)."""
	event_type: str = "cb.hold.expired"
	hold_id: str = ""
	account_id: str = ""
	account_number: str = ""
	amount_cents: int = 0
	release_reason: str = "EXPIRED"
	expired_at: str = ""  # ISO datetime string


# ---------------------------------------------------------------------------
# AML events
# ---------------------------------------------------------------------------

@dataclass
class AMLFlaggedEvent(DomainEvent):
	"""Emitted when a transaction is flagged by AML screening (not blocked)."""
	event_type: str = "cb.aml.flagged"
	account_id: str = ""
	account_number: str = ""
	journal_ref: str = ""
	amount_cents: int = 0
	risk_score: str = ""  # Decimal serialised as string; empty = unknown
	flagged_reason: str = ""
	screening_provider: str = "INTERNAL"


@dataclass
class AMLBlockedEvent(DomainEvent):
	"""Emitted when a transaction is blocked by AML screening."""
	event_type: str = "cb.aml.blocked"
	account_id: str = ""
	account_number: str = ""
	journal_ref: str = ""
	amount_cents: int = 0
	flagged_reason: str = ""
	screening_provider: str = "INTERNAL"


# ---------------------------------------------------------------------------
# Statement events
# ---------------------------------------------------------------------------

@dataclass
class StatementDeliveredEvent(DomainEvent):
	"""Emitted when a statement is successfully delivered to the customer."""
	event_type: str = "cb.statement.delivered"
	statement_id: str = ""
	account_id: str = ""
	account_number: str = ""
	delivery_method: str = ""
	statement_url: str = ""
	delivered_at: str = ""  # ISO datetime string


# ---------------------------------------------------------------------------
# Account freeze/unfreeze events
# ---------------------------------------------------------------------------

@dataclass
class AccountFrozenEvent(DomainEvent):
	"""Emitted when an account is frozen by an operator."""
	event_type: str = "cb.account.frozen"
	account_id: str = ""
	account_number: str = ""
	reason: str = ""


@dataclass
class AccountUnfrozenEvent(DomainEvent):
	"""Emitted when a frozen account is reinstated to ACTIVE."""
	event_type: str = "cb.account.unfrozen"
	account_id: str = ""
	account_number: str = ""


# ---------------------------------------------------------------------------
# Event type constants (for subscribe() calls and filtering)
# ---------------------------------------------------------------------------

CB_ACCOUNT_OPENED = "cb.account.opened"
CB_ACCOUNT_CREDITED = "cb.account.credited"
CB_ACCOUNT_DEBITED = "cb.account.debited"
CB_ACCOUNT_TRANSFERRED = "cb.account.transferred"
CB_ACCOUNT_CLOSED = "cb.account.closed"
CB_ACCOUNT_DORMANT = "cb.account.dormant"
CB_ACCOUNT_FROZEN = "cb.account.frozen"
CB_ACCOUNT_UNFROZEN = "cb.account.unfrozen"
CB_INTEREST_ACCRUED = "cb.interest.accrued"
CB_INTEREST_CAPITALIZED = "cb.interest.capitalized"
CB_HOLD_PLACED = "cb.hold.placed"
CB_HOLD_RELEASED = "cb.hold.released"
CB_TRANSACTION_REVERSED = "cb.transaction.reversed"
CB_FEE_CHARGED = "cb.fee.charged"
CB_HOLD_EXPIRED = "cb.hold.expired"
CB_AML_FLAGGED = "cb.aml.flagged"
CB_AML_BLOCKED = "cb.aml.blocked"
CB_STATEMENT_DELIVERED = "cb.statement.delivered"

ALL_CB_EVENT_TYPES: list[str] = [
	CB_ACCOUNT_OPENED,
	CB_ACCOUNT_CREDITED,
	CB_ACCOUNT_DEBITED,
	CB_ACCOUNT_TRANSFERRED,
	CB_ACCOUNT_CLOSED,
	CB_ACCOUNT_DORMANT,
	CB_ACCOUNT_FROZEN,
	CB_ACCOUNT_UNFROZEN,
	CB_INTEREST_ACCRUED,
	CB_INTEREST_CAPITALIZED,
	CB_HOLD_PLACED,
	CB_HOLD_RELEASED,
	CB_TRANSACTION_REVERSED,
	CB_FEE_CHARGED,
	CB_HOLD_EXPIRED,
	CB_AML_FLAGGED,
	CB_AML_BLOCKED,
	CB_STATEMENT_DELIVERED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"AccountOpenedEvent",
	"AccountCreditedEvent",
	"AccountDebitedEvent",
	"AccountTransferredEvent",
	"AccountClosedEvent",
	"AccountDormantEvent",
	"AccountFrozenEvent",
	"AccountUnfrozenEvent",
	"InterestAccruedEvent",
	"InterestCapitalizedEvent",
	"HoldPlacedEvent",
	"HoldReleasedEvent",
	"TransactionReversedEvent",
	"FeeChargedEvent",
	"HoldExpiredEvent",
	"AMLFlaggedEvent",
	"AMLBlockedEvent",
	"StatementDeliveredEvent",
	# event type string constants
	"CB_ACCOUNT_OPENED",
	"CB_ACCOUNT_CREDITED",
	"CB_ACCOUNT_DEBITED",
	"CB_ACCOUNT_TRANSFERRED",
	"CB_ACCOUNT_CLOSED",
	"CB_ACCOUNT_DORMANT",
	"CB_ACCOUNT_FROZEN",
	"CB_ACCOUNT_UNFROZEN",
	"CB_INTEREST_ACCRUED",
	"CB_INTEREST_CAPITALIZED",
	"CB_HOLD_PLACED",
	"CB_HOLD_RELEASED",
	"CB_TRANSACTION_REVERSED",
	"CB_FEE_CHARGED",
	"CB_HOLD_EXPIRED",
	"CB_AML_FLAGGED",
	"CB_AML_BLOCKED",
	"CB_STATEMENT_DELIVERED",
	"ALL_CB_EVENT_TYPES",
]
