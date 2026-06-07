from __future__ import annotations
from dataclasses import dataclass, field
from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class AccountingBookCreatedEvent(DomainEvent):
	event_type: str = "finance.multi_book.book.created"
	book_id: str = ""
	name: str = ""
	book_type: str = ""
	tenant_id: str = ""


@dataclass
class BookJournalPostedEvent(DomainEvent):
	event_type: str = "finance.multi_book.journal.posted"
	entry_id: str = ""
	book_id: str = ""
	source_journal_id: str = ""
	debit_cents: int = 0
	credit_cents: int = 0


@dataclass
class BookDifferenceDetectedEvent(DomainEvent):
	event_type: str = "finance.multi_book.difference.detected"
	book_a_id: str = ""
	book_b_id: str = ""
	account: str = ""
	amount_cents: int = 0
	period: str = ""


@dataclass
class MultiBookReconciliationRunEvent(DomainEvent):
	event_type: str = "finance.multi_book.reconciliation.run"
	tenant_id: str = ""
	period: str = ""
	books_compared: int = 0
	differences_count: int = 0


@dataclass
class BookClosedEvent(DomainEvent):
	event_type: str = "finance.multi_book.book.closed"
	book_id: str = ""
	period: str = ""
	closed_by: str = ""


__all__ = [
	"AccountingBookCreatedEvent",
	"BookJournalPostedEvent",
	"BookDifferenceDetectedEvent",
	"MultiBookReconciliationRunEvent",
	"BookClosedEvent",
]
