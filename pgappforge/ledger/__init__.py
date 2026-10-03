"""Event-sourced double-entry ledger (proposal P1).

Every movement of money is an append-only ``LedgerEntry`` balanced across two
``LedgerPosting`` rows; a balance is the sum of postings on an account and is
always derivable with :func:`rebuild_account_balances`. Writes are idempotent on
``idempotency_key`` and account rows are locked with ``SELECT ... FOR UPDATE``
before any mutation, which makes concurrent double-spends structurally
impossible rather than merely unlikely.

Usage::

    from pgappforge.ledger import LedgerService, get_ledger_service

    ledger = get_ledger_service()
    ledger.post(debit_account_id=cash, credit_account_id=fee_income,
                amount=Decimal("10.00"), currency="KES",
                idempotency_key="mpesa:ws_1", memo="STK fee")
"""

from .service import (
	AccountNotFoundError,
	DoubleEntryError,
	IdempotencyConflict,
	InsufficientFundsError,
	LedgerAccount,
	LedgerEntry,
	LedgerPosting,
	LedgerService,
	LockedAccount,
	Posting,
	get_ledger_service,
	rebuild_account_balances,
)

__all__ = [
	"AccountNotFoundError",
	"DoubleEntryError",
	"IdempotencyConflict",
	"InsufficientFundsError",
	"LedgerAccount",
	"LedgerEntry",
	"LedgerPosting",
	"LedgerService",
	"LockedAccount",
	"Posting",
	"get_ledger_service",
	"rebuild_account_balances",
]
