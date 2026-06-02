"""
pgappforge/plugins/erp/finance/ar/events.py

Domain events for the Accounts Receivable plugin.

All monetary fields are integer cents — never float.

Events emitted
--------------
  ar.invoice.issued    — invoice moved from DRAFT to ISSUED
  ar.invoice.paid      — invoice fully paid (balance_due_cents == 0)
  ar.payment.received  — new payment record created
  ar.customer.overdue  — customer has overdue invoices (dunning trigger)
  ar.credit_note.issued — credit note created
  ar.invoice.written_off — invoice written off as bad debt
  ar.dunning.run_completed — dunning batch finished
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Invoice events
# ---------------------------------------------------------------------------

@dataclass
class InvoiceIssuedEvent(DomainEvent):
	"""Emitted when an invoice transitions DRAFT → ISSUED.

	Triggers GL journal: DR Accounts Receivable / CR Revenue.
	"""
	event_type: str = "ar.invoice.issued"
	invoice_id: str = ""
	invoice_number: str = ""
	customer_id: str = ""
	total_cents: int = 0
	currency_code: str = ""
	due_date: str = ""          # ISO date string
	gl_ar_account: str = ""
	gl_revenue_account: str = ""


@dataclass
class InvoicePaidEvent(DomainEvent):
	"""Emitted when invoice balance_due_cents reaches zero (fully paid)."""
	event_type: str = "ar.invoice.paid"
	invoice_id: str = ""
	invoice_number: str = ""
	customer_id: str = ""
	total_cents: int = 0
	paid_cents: int = 0
	currency_code: str = ""
	paid_date: str = ""         # ISO date string


@dataclass
class InvoiceWrittenOffEvent(DomainEvent):
	"""Emitted when invoice is written off as bad debt.

	Triggers GL journal: DR Bad Debt Expense / CR Accounts Receivable.
	"""
	event_type: str = "ar.invoice.written_off"
	invoice_id: str = ""
	invoice_number: str = ""
	customer_id: str = ""
	write_off_cents: int = 0
	currency_code: str = ""
	reason: str = ""
	write_off_date: str = ""    # ISO date string


@dataclass
class InvoiceDisputedEvent(DomainEvent):
	"""Emitted when a customer raises a dispute on an invoice."""
	event_type: str = "ar.invoice.disputed"
	invoice_id: str = ""
	invoice_number: str = ""
	customer_id: str = ""
	dispute_reason: str = ""
	disputed_cents: int = 0


# ---------------------------------------------------------------------------
# Payment events
# ---------------------------------------------------------------------------

@dataclass
class PaymentReceivedEvent(DomainEvent):
	"""Emitted when a new payment record is created (before allocation)."""
	event_type: str = "ar.payment.received"
	payment_id: str = ""
	payment_number: str = ""
	customer_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	payment_method: str = ""
	payment_date: str = ""      # ISO date string


@dataclass
class PaymentAllocatedEvent(DomainEvent):
	"""Emitted after a payment is applied to one or more invoices."""
	event_type: str = "ar.payment.allocated"
	payment_id: str = ""
	payment_number: str = ""
	customer_id: str = ""
	allocated_cents: int = 0
	invoice_ids: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Customer / credit events
# ---------------------------------------------------------------------------

@dataclass
class CustomerOverdueEvent(DomainEvent):
	"""Emitted when a customer has overdue invoices (dunning trigger).

	Consumed by dunning runs and credit management.
	"""
	event_type: str = "ar.customer.overdue"
	customer_id: str = ""
	account_number: str = ""
	overdue_cents: int = 0
	currency_code: str = ""
	oldest_due_date: str = ""   # ISO date string
	dunning_level: int = 0


@dataclass
class CreditHoldPlacedEvent(DomainEvent):
	"""Emitted when a customer is placed on credit hold."""
	event_type: str = "ar.customer.credit_hold_placed"
	customer_id: str = ""
	account_number: str = ""
	credit_used_cents: int = 0
	credit_limit_cents: int = 0


@dataclass
class CreditHoldReleasedEvent(DomainEvent):
	"""Emitted when credit hold is lifted."""
	event_type: str = "ar.customer.credit_hold_released"
	customer_id: str = ""
	account_number: str = ""


# ---------------------------------------------------------------------------
# Credit note events
# ---------------------------------------------------------------------------

@dataclass
class CreditNoteIssuedEvent(DomainEvent):
	"""Emitted when a credit note is created."""
	event_type: str = "ar.credit_note.issued"
	credit_note_id: str = ""
	credit_note_number: str = ""
	customer_id: str = ""
	original_invoice_id: str = ""
	total_cents: int = 0
	currency_code: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Dunning events
# ---------------------------------------------------------------------------

@dataclass
class DunningRunCompletedEvent(DomainEvent):
	"""Emitted when a dunning batch completes."""
	event_type: str = "ar.dunning.run_completed"
	dunning_run_id: str = ""
	dunning_level: int = 0
	customers_contacted: int = 0
	emails_sent: int = 0
	total_overdue_cents: int = 0


# ---------------------------------------------------------------------------
# Aging events
# ---------------------------------------------------------------------------

@dataclass
class AgingSnapshotCreatedEvent(DomainEvent):
	"""Emitted when an aging snapshot run completes."""
	event_type: str = "ar.aging.snapshot_created"
	snapshot_date: str = ""     # ISO date string
	customers_snapshotted: int = 0
	total_outstanding_cents: int = 0


__all__ = [
	"InvoiceIssuedEvent",
	"InvoicePaidEvent",
	"InvoiceWrittenOffEvent",
	"InvoiceDisputedEvent",
	"PaymentReceivedEvent",
	"PaymentAllocatedEvent",
	"CustomerOverdueEvent",
	"CreditHoldPlacedEvent",
	"CreditHoldReleasedEvent",
	"CreditNoteIssuedEvent",
	"DunningRunCompletedEvent",
	"AgingSnapshotCreatedEvent",
]
