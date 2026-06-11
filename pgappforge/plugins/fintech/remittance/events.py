"""
pgappforge/plugins/fintech/remittance/events.py

Remittance domain events.

All events extend DomainEvent from erp.foundation.events.
They are emitted by RemittanceService and persisted atomically
to the DomainEventLog within the same SQLAlchemy session.

Event catalogue
---------------
  remittance.quote.generated      — FX quote created for a corridor
  remittance.transfer.initiated   — transfer created, compliance running
  remittance.transfer.paid        — payout confirmed by provider
  remittance.transfer.cancelled   — transfer cancelled by customer/operator
  remittance.compliance.checked   — a compliance check completed (any type)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Quote events
# ---------------------------------------------------------------------------

@dataclass
class QuoteGeneratedEvent(DomainEvent):
	"""Emitted when a new FX quote is created for a corridor."""
	event_type: str = "remittance.quote.generated"
	quote_id: str = ""
	corridor_id: str = ""
	from_country: str = ""
	to_country: str = ""
	send_amount_cents: int = 0
	receive_amount_cents: int = 0
	fx_rate: str = ""		# Decimal serialised as string
	fee_cents: int = 0
	payout_method: str = ""
	expires_at: str = ""	# ISO datetime string


# ---------------------------------------------------------------------------
# Transfer lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class TransferInitiatedEvent(DomainEvent):
	"""Emitted when a transfer is created from a quote (status=PENDING/PROCESSING)."""
	event_type: str = "remittance.transfer.initiated"
	transaction_id: str = ""
	reference: str = ""
	quote_id: str = ""
	sender_customer_id: str = ""
	receiver_name: str = ""
	payout_method: str = ""
	send_amount_cents: int = 0
	receive_amount_cents: int = 0
	status: str = ""


@dataclass
class TransferPaidEvent(DomainEvent):
	"""Emitted when payout is confirmed by the provider (status=PAID)."""
	event_type: str = "remittance.transfer.paid"
	transaction_id: str = ""
	reference: str = ""
	provider_reference: str = ""
	send_amount_cents: int = 0
	receive_amount_cents: int = 0
	payout_method: str = ""


@dataclass
class TransferCancelledEvent(DomainEvent):
	"""Emitted when a transfer is cancelled."""
	event_type: str = "remittance.transfer.cancelled"
	transaction_id: str = ""
	reference: str = ""
	reason: str = ""
	prior_status: str = ""


# ---------------------------------------------------------------------------
# Compliance events
# ---------------------------------------------------------------------------

@dataclass
class ComplianceCheckEvent(DomainEvent):
	"""Emitted after each compliance check (AML / KYC / OFAC / CBK_REPORT)."""
	event_type: str = "remittance.compliance.checked"
	compliance_log_id: str = ""
	transaction_id: str = ""
	check_type: str = ""	# AML | KYC | OFAC | CBK_REPORT
	result: str = ""		# PASS | FAIL | PENDING


# ---------------------------------------------------------------------------
# Event type string constants
# ---------------------------------------------------------------------------

REM_QUOTE_GENERATED = "remittance.quote.generated"
REM_TRANSFER_INITIATED = "remittance.transfer.initiated"
REM_TRANSFER_PAID = "remittance.transfer.paid"
REM_TRANSFER_CANCELLED = "remittance.transfer.cancelled"
REM_COMPLIANCE_CHECKED = "remittance.compliance.checked"

ALL_REM_EVENT_TYPES: list[str] = [
	REM_QUOTE_GENERATED,
	REM_TRANSFER_INITIATED,
	REM_TRANSFER_PAID,
	REM_TRANSFER_CANCELLED,
	REM_COMPLIANCE_CHECKED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"QuoteGeneratedEvent",
	"TransferInitiatedEvent",
	"TransferPaidEvent",
	"TransferCancelledEvent",
	"ComplianceCheckEvent",
	# event type string constants
	"REM_QUOTE_GENERATED",
	"REM_TRANSFER_INITIATED",
	"REM_TRANSFER_PAID",
	"REM_TRANSFER_CANCELLED",
	"REM_COMPLIANCE_CHECKED",
	"ALL_REM_EVENT_TYPES",
]
