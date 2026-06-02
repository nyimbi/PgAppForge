"""
pgappforge/plugins/erp/finance/tax/events.py

Domain events for the Tax Management plugin.

Emitted events:
  tax.transaction_posted    — tax line posted from a source document
  tax.return_generated      — draft tax return generated for a period
  tax.return_filed          — return submitted to authority
  tax.return_paid           — tax payment made
  tax.rate_expired          — a TaxCode's effective_to date has passed

Subscribed events (upstream):
  invoice.posted            — from AR/AP plugins to trigger tax calculation
  payment.posted            — for WHT transaction creation
  exchange_rate.updated     — for multicurrency tax restatement
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event


@dataclass
class TaxTransactionPostedEvent(DomainEvent):
	"""Fired when a tax transaction line is posted."""
	event_type: str = "tax.transaction_posted"
	tax_transaction_id: str = ""
	tax_code_id: str = ""
	source_document_type: str = ""
	source_document_id: str = ""
	taxable_amount_cents: int = 0
	tax_amount_cents: int = 0
	posting_date: str = ""
	is_recoverable: bool = True


@dataclass
class TaxReturnGeneratedEvent(DomainEvent):
	"""Fired when a draft tax return is generated for a period."""
	event_type: str = "tax.return_generated"
	tax_return_id: str = ""
	jurisdiction_id: str = ""
	period_start: str = ""
	period_end: str = ""
	output_tax_cents: int = 0
	input_tax_cents: int = 0
	net_tax_cents: int = 0


@dataclass
class TaxReturnFiledEvent(DomainEvent):
	"""Fired when a tax return is submitted to the authority."""
	event_type: str = "tax.return_filed"
	tax_return_id: str = ""
	jurisdiction_id: str = ""
	reference_number: str = ""
	filing_date: str = ""
	net_tax_cents: int = 0


@dataclass
class TaxReturnPaidEvent(DomainEvent):
	"""Fired when the tax liability from a return is settled."""
	event_type: str = "tax.return_paid"
	tax_return_id: str = ""
	jurisdiction_id: str = ""
	payment_reference: str = ""
	payment_date: str = ""
	amount_paid_cents: int = 0


@dataclass
class TaxRateExpiredEvent(DomainEvent):
	"""Fired when a TaxCode's effective_to date is reached."""
	event_type: str = "tax.rate_expired"
	tax_code_id: str = ""
	jurisdiction_id: str = ""
	code: str = ""
	expired_rate: str = ""   # string — never float
	expiry_date: str = ""


__all__ = [
	"TaxTransactionPostedEvent",
	"TaxReturnGeneratedEvent",
	"TaxReturnFiledEvent",
	"TaxReturnPaidEvent",
	"TaxRateExpiredEvent",
	"emit_event",
]
