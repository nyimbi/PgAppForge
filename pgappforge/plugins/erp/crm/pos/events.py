"""
pgappforge/plugins/erp/crm/pos/events.py

Domain events for the Point of Sale plugin.

Emitted:
  pos.till.opened          — till opened for a shift
  pos.sale.completed       — sale transaction finalised
  pos.transaction.voided   — transaction voided
  pos.return.processed     — return / refund processed
  pos.till.closed          — shift reconciliation completed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


@dataclass
class TillOpenedEvent(DomainEvent):
	"""Fired when a POS till is opened for a shift."""
	event_type: str = "pos.till.opened"
	till_id: str = ""
	till_code: str = ""
	cashier_id: str = ""
	opening_float_cents: int = 0


@dataclass
class SaleCompletedEvent(DomainEvent):
	"""Fired when a sale transaction is finalised."""
	event_type: str = "pos.sale.completed"
	transaction_id: str = ""
	till_id: str = ""
	cashier_id: str = ""
	receipt_number: str = ""
	total_cents: int = 0
	customer_id: str = ""


@dataclass
class TransactionVoidedEvent(DomainEvent):
	"""Fired when a POS transaction is voided."""
	event_type: str = "pos.transaction.voided"
	transaction_id: str = ""
	till_id: str = ""
	void_reason: str = ""
	original_total_cents: int = 0


@dataclass
class ReturnProcessedEvent(DomainEvent):
	"""Fired when a return / refund transaction is created."""
	event_type: str = "pos.return.processed"
	return_txn_id: str = ""
	original_txn_id: str = ""
	till_id: str = ""
	refund_cents: int = 0
	refund_method: str = ""


@dataclass
class TillClosedEvent(DomainEvent):
	"""Fired when a till shift is closed and reconciled."""
	event_type: str = "pos.till.closed"
	till_id: str = ""
	till_code: str = ""
	closed_by: str = ""
	variance_cents: int = 0
	transaction_count: int = 0
	reconciliation_id: str = ""


__all__ = [
	"TillOpenedEvent",
	"SaleCompletedEvent",
	"TransactionVoidedEvent",
	"ReturnProcessedEvent",
	"TillClosedEvent",
	"emit_event",
]
