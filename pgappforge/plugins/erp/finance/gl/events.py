"""
pgappforge/plugins/erp/finance/gl/events.py

Domain events for the General Ledger plugin.

All amounts are integer cents (no float, ever).
Emitted inside the same SQLAlchemy session as the mutating operation so
persistence is atomic with the business transaction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# GL events
# ---------------------------------------------------------------------------

@dataclass
class JournalPostedEvent(DomainEvent):
	"""Emitted once per GLJournalLine when a batch is posted."""
	event_type: str = "gl.journal.posted"
	entry_id: str = ""
	batch_id: str = ""
	account_code: str = ""
	# amount in base-currency minor units (integer cents / kobo)
	amount: int = 0
	debit_credit: str = ""        # "DEBIT" or "CREDIT"
	currency_code: str = ""
	posting_date: str = ""        # ISO date string


@dataclass
class PeriodClosedEvent(DomainEvent):
	"""Emitted when a GL period is successfully locked."""
	event_type: str = "gl.period.closed"
	period_id: str = ""
	fiscal_year: int = 0
	period_number: int = 0
	closed_by: str = ""           # user id


@dataclass
class BatchPostedEvent(DomainEvent):
	"""Emitted when an entire journal batch transitions to POSTED."""
	event_type: str = "gl.batch.posted"
	batch_id: str = ""
	batch_number: str = ""
	total_debits: int = 0         # integer cents
	total_credits: int = 0        # integer cents
	period_id: str = ""


@dataclass
class JournalReversedEvent(DomainEvent):
	"""Emitted when a reversal entry is created."""
	event_type: str = "gl.journal.reversed"
	original_entry_id: str = ""
	reversal_entry_id: str = ""
	reversal_date: str = ""       # ISO date string


__all__ = [
	"JournalPostedEvent",
	"PeriodClosedEvent",
	"BatchPostedEvent",
	"JournalReversedEvent",
	"emit_event",
]
