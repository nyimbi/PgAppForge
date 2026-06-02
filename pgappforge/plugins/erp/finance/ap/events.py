"""
pgappforge/plugins/erp/finance/ap/events.py

Domain events for the Accounts Payable plugin.

All monetary amounts are integer cents/kobo — never float.
Downstream plugins subscribe via emit_event / subscribe() from foundation.

Events emitted:
  ap.invoice.matched          — 2-way or 3-way match completed
  ap.invoice.approved         — invoice cleared approval workflow
  ap.invoice.posted_to_gl     — GL journal entries created
  ap.payment.initiated        — payment run transmitted to bank
  ap.payment.confirmed        — bank confirmed settlement
  ap.supplier.statement_reconciled — statement reconciliation finished

Events consumed:
  (none at this layer — AP is triggered by user actions / GRN confirmations)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Invoice events
# ---------------------------------------------------------------------------

@dataclass
class InvoiceMatchedEvent(DomainEvent):
	"""Emitted when match_invoice() succeeds (2-way or 3-way)."""
	event_type: str = "ap.invoice.matched"
	invoice_id: str = ""
	supplier_id: str = ""
	match_type: str = ""          # "2WAY" | "3WAY"
	total_cents: int = 0
	currency: str = ""
	po_id: str = ""
	grn_id: str = ""


@dataclass
class InvoiceApprovedEvent(DomainEvent):
	"""Emitted when the final approval level approves the invoice."""
	event_type: str = "ap.invoice.approved"
	invoice_id: str = ""
	supplier_id: str = ""
	total_cents: int = 0
	currency: str = ""
	due_date: str = ""            # ISO date string


@dataclass
class InvoicePostedToGLEvent(DomainEvent):
	"""Emitted after GL journal entries are created for an invoice."""
	event_type: str = "ap.invoice.posted_to_gl"
	invoice_id: str = ""
	supplier_id: str = ""
	debit_account: str = ""       # expense GL account
	credit_account: str = ""      # AP payable account
	amount_cents: int = 0
	currency: str = ""


@dataclass
class InvoiceDisputedEvent(DomainEvent):
	"""Emitted when an invoice is placed in DISPUTED status."""
	event_type: str = "ap.invoice.disputed"
	invoice_id: str = ""
	supplier_id: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Payment events
# ---------------------------------------------------------------------------

@dataclass
class PaymentInitiatedEvent(DomainEvent):
	"""Emitted when a payment run is transmitted to the bank."""
	event_type: str = "ap.payment.initiated"
	payment_run_id: str = ""
	run_number: str = ""
	total_payments: int = 0
	total_amount_cents: int = 0
	currency: str = ""
	value_date: str = ""          # ISO date
	iso20022_ref: str = ""        # payment file reference


@dataclass
class PaymentConfirmedEvent(DomainEvent):
	"""Emitted when the bank confirms settlement of a payment."""
	event_type: str = "ap.payment.confirmed"
	payment_id: str = ""
	payment_run_id: str = ""
	supplier_id: str = ""
	amount_cents: int = 0
	currency: str = ""
	bank_reference: str = ""
	uetr: str = ""                # SWIFT gpi UETR


@dataclass
class PaymentFailedEvent(DomainEvent):
	"""Emitted when a payment fails or is returned by the bank."""
	event_type: str = "ap.payment.failed"
	payment_id: str = ""
	supplier_id: str = ""
	amount_cents: int = 0
	currency: str = ""
	failure_reason: str = ""


# ---------------------------------------------------------------------------
# Supplier events
# ---------------------------------------------------------------------------

@dataclass
class SupplierStatementReconciledEvent(DomainEvent):
	"""Emitted after reconcile_supplier_statement() completes."""
	event_type: str = "ap.supplier.statement_reconciled"
	supplier_id: str = ""
	matched_count: int = 0
	unmatched_count: int = 0
	disputed_count: int = 0
	net_difference_cents: int = 0
	currency: str = ""


@dataclass
class SupplierApprovedEvent(DomainEvent):
	"""Emitted when a supplier is marked approved_supplier=True."""
	event_type: str = "ap.supplier.approved"
	supplier_id: str = ""
	account_number: str = ""


__all__ = [
	"InvoiceMatchedEvent",
	"InvoiceApprovedEvent",
	"InvoicePostedToGLEvent",
	"InvoiceDisputedEvent",
	"PaymentInitiatedEvent",
	"PaymentConfirmedEvent",
	"PaymentFailedEvent",
	"SupplierStatementReconciledEvent",
	"SupplierApprovedEvent",
]
