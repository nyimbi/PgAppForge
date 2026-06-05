"""
pgappforge/plugins/fintech/payments/events.py

Payments Engine domain events.

All events extend DomainEvent from erp.foundation.events.
Emitted by PaymentsService; persisted atomically within the same session.

Event catalogue
---------------
  py.payment.initiated       — new PaymentOrder created (PENDING)
  py.payment.validated       — sanctions + AML + balance checks passed
  py.payment.authorized      — authorizer approved the order
  py.payment.submitted       — order sent to clearing rail
  py.payment.settled         — clearing house confirmed settlement
  py.payment.rejected        — clearing house rejected the order
  py.payment.returned        — previously settled payment returned by beneficiary bank
  py.payment.cancelled       — order cancelled before submission

  py.batch.created           — new PaymentBatch assembled
  py.batch.submitted         — batch file dispatched to clearing house
  py.batch.settled           — full batch settled
  py.batch.partially_settled — some items settled, some rejected

  py.standing_order.created  — new PayStandingOrder set up
  py.standing_order.executed — single execution of a standing order succeeded
  py.standing_order.failed   — single execution failed (insufficient funds, etc.)
  py.standing_order.cancelled — standing order cancelled

  py.inbound.received        — inbound payment received and credited
  py.reconciliation.complete — settlement file processed; stats reported
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Payment lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class PaymentInitiatedEvent(DomainEvent):
	"""Emitted when a new PaymentOrder is created (status=PENDING)."""
	event_type: str = "py.payment.initiated"
	payment_order_id: str = ""
	payment_reference: str = ""
	payment_type: str = ""
	debtor_account_id: str = ""
	creditor_name: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	value_date: str = ""		# ISO date string
	channel: str = ""


@dataclass
class PaymentValidatedEvent(DomainEvent):
	"""Emitted after sanctions, AML, and balance checks pass."""
	event_type: str = "py.payment.validated"
	payment_order_id: str = ""
	payment_reference: str = ""
	payment_type: str = ""
	amount_cents: int = 0
	sanctions_checked: bool = False
	aml_flagged: bool = False
	hold_placed: bool = False


@dataclass
class PaymentAuthorizedEvent(DomainEvent):
	"""Emitted when an authorizer approves the payment."""
	event_type: str = "py.payment.authorized"
	payment_order_id: str = ""
	payment_reference: str = ""
	authorizer_id: str = ""
	authorization_code: str = ""
	amount_cents: int = 0
	currency_code: str = ""


@dataclass
class PaymentSubmittedEvent(DomainEvent):
	"""Emitted when the order is dispatched to the clearing rail."""
	event_type: str = "py.payment.submitted"
	payment_order_id: str = ""
	payment_reference: str = ""
	payment_type: str = ""
	rail_code: str = ""
	uetr: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	submitted_at: str = ""		# ISO datetime string


@dataclass
class PaymentSettledEvent(DomainEvent):
	"""Emitted when the clearing house confirms settlement."""
	event_type: str = "py.payment.settled"
	payment_order_id: str = ""
	payment_reference: str = ""
	payment_type: str = ""
	rail_code: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	settled_at: str = ""		# ISO datetime string
	clearing_reference: str = ""


@dataclass
class PaymentRejectedEvent(DomainEvent):
	"""Emitted when the clearing house rejects the order."""
	event_type: str = "py.payment.rejected"
	payment_order_id: str = ""
	payment_reference: str = ""
	rejection_code: str = ""
	rejection_reason: str = ""
	amount_cents: int = 0
	hold_released: bool = False


@dataclass
class PaymentReturnedEvent(DomainEvent):
	"""Emitted when a previously settled payment is returned."""
	event_type: str = "py.payment.returned"
	payment_order_id: str = ""
	payment_reference: str = ""
	return_reason_code: str = ""
	return_reason: str = ""
	amount_cents: int = 0
	returned_at: str = ""		# ISO datetime string
	reversal_journal_id: str = ""


@dataclass
class PaymentCancelledEvent(DomainEvent):
	"""Emitted when an order is cancelled before submission."""
	event_type: str = "py.payment.cancelled"
	payment_order_id: str = ""
	payment_reference: str = ""
	cancelled_by: str = ""
	cancellation_reason: str = ""
	hold_released: bool = False


# ---------------------------------------------------------------------------
# Batch events
# ---------------------------------------------------------------------------

@dataclass
class BatchCreatedEvent(DomainEvent):
	"""Emitted when a new PaymentBatch is assembled."""
	event_type: str = "py.batch.created"
	batch_id: str = ""
	batch_number: str = ""
	batch_type: str = ""
	total_payments: int = 0
	total_amount_cents: int = 0
	currency_code: str = ""
	value_date: str = ""		# ISO date string


@dataclass
class BatchSubmittedEvent(DomainEvent):
	"""Emitted when the batch file is dispatched to the clearing house."""
	event_type: str = "py.batch.submitted"
	batch_id: str = ""
	batch_number: str = ""
	batch_type: str = ""
	rail_code: str = ""
	total_payments: int = 0
	total_amount_cents: int = 0
	submitted_at: str = ""		# ISO datetime string


@dataclass
class BatchSettledEvent(DomainEvent):
	"""Emitted when the full batch settles."""
	event_type: str = "py.batch.settled"
	batch_id: str = ""
	batch_number: str = ""
	accepted_count: int = 0
	rejected_count: int = 0
	total_amount_cents: int = 0
	clearing_reference: str = ""


@dataclass
class BatchPartiallySettledEvent(DomainEvent):
	"""Emitted when some items in a batch settled but others were rejected."""
	event_type: str = "py.batch.partially_settled"
	batch_id: str = ""
	batch_number: str = ""
	accepted_count: int = 0
	rejected_count: int = 0
	accepted_amount_cents: int = 0
	rejected_amount_cents: int = 0
	clearing_reference: str = ""


# ---------------------------------------------------------------------------
# Standing Order events
# ---------------------------------------------------------------------------

@dataclass
class StandingOrderCreatedEvent(DomainEvent):
	"""Emitted when a new PayStandingOrder is registered."""
	event_type: str = "py.standing_order.created"
	standing_order_id: str = ""
	reference_number: str = ""
	debtor_account_id: str = ""
	amount_cents: int = 0
	frequency: str = ""
	start_date: str = ""		# ISO date string
	next_execution_date: str = ""


@dataclass
class StandingOrderExecutedEvent(DomainEvent):
	"""Emitted after a successful standing order execution."""
	event_type: str = "py.standing_order.executed"
	standing_order_id: str = ""
	reference_number: str = ""
	payment_order_id: str = ""
	payment_reference: str = ""
	execution_date: str = ""	# ISO date string
	amount_cents: int = 0
	next_execution_date: str = ""
	total_executed: int = 0


@dataclass
class StandingOrderFailedEvent(DomainEvent):
	"""Emitted when a standing order execution fails."""
	event_type: str = "py.standing_order.failed"
	standing_order_id: str = ""
	reference_number: str = ""
	execution_date: str = ""	# ISO date string
	amount_cents: int = 0
	failure_reason: str = ""
	total_failed: int = 0
	will_retry: bool = False


@dataclass
class StandingOrderPausedEvent(DomainEvent):
	"""Emitted when a standing order is paused."""
	event_type: str = "py.standing_order.paused"
	standing_order_id: str = ""
	reference_number: str = ""
	paused_by: str = ""
	total_executed: int = 0


@dataclass
class StandingOrderResumedEvent(DomainEvent):
	"""Emitted when a paused standing order is resumed."""
	event_type: str = "py.standing_order.resumed"
	standing_order_id: str = ""
	reference_number: str = ""
	resumed_by: str = ""
	next_execution_date: str = ""


@dataclass
class StandingOrderCancelledEvent(DomainEvent):
	"""Emitted when a standing order is cancelled."""
	event_type: str = "py.standing_order.cancelled"
	standing_order_id: str = ""
	reference_number: str = ""
	cancelled_by: str = ""
	total_executed: int = 0


# ---------------------------------------------------------------------------
# Inbound payment events
# ---------------------------------------------------------------------------

@dataclass
class InboundPaymentReceivedEvent(DomainEvent):
	"""Emitted when an inbound credit is received and posted to an account."""
	event_type: str = "py.inbound.received"
	payment_order_id: str = ""
	payment_reference: str = ""
	payment_type: str = ""
	creditor_account_id: str = ""
	amount_cents: int = 0
	currency_code: str = ""
	debtor_name: str = ""
	debtor_bank_code: str = ""
	remittance_info: str = ""
	rail_code: str = ""
	journal_id: str = ""


# ---------------------------------------------------------------------------
# Reconciliation events
# ---------------------------------------------------------------------------

@dataclass
class ReconciliationCompleteEvent(DomainEvent):
	"""Emitted after a settlement file has been fully processed."""
	event_type: str = "py.reconciliation.complete"
	rail_code: str = ""
	settlement_date: str = ""	# ISO date string
	total_processed: int = 0
	matched_count: int = 0
	unmatched_count: int = 0
	settled_amount_cents: int = 0
	returned_amount_cents: int = 0
	exceptions: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Event type string constants
# ---------------------------------------------------------------------------

PY_PAYMENT_INITIATED = "py.payment.initiated"
PY_PAYMENT_VALIDATED = "py.payment.validated"
PY_PAYMENT_AUTHORIZED = "py.payment.authorized"
PY_PAYMENT_SUBMITTED = "py.payment.submitted"
PY_PAYMENT_SETTLED = "py.payment.settled"
PY_PAYMENT_REJECTED = "py.payment.rejected"
PY_PAYMENT_RETURNED = "py.payment.returned"
PY_PAYMENT_CANCELLED = "py.payment.cancelled"

PY_BATCH_CREATED = "py.batch.created"
PY_BATCH_SUBMITTED = "py.batch.submitted"
PY_BATCH_SETTLED = "py.batch.settled"
PY_BATCH_PARTIALLY_SETTLED = "py.batch.partially_settled"

PY_STANDING_ORDER_CREATED = "py.standing_order.created"
PY_STANDING_ORDER_EXECUTED = "py.standing_order.executed"
PY_STANDING_ORDER_FAILED = "py.standing_order.failed"
PY_STANDING_ORDER_PAUSED = "py.standing_order.paused"
PY_STANDING_ORDER_RESUMED = "py.standing_order.resumed"
PY_STANDING_ORDER_CANCELLED = "py.standing_order.cancelled"

PY_INBOUND_RECEIVED = "py.inbound.received"
PY_RECONCILIATION_COMPLETE = "py.reconciliation.complete"

ALL_PY_EVENT_TYPES: list[str] = [
	PY_PAYMENT_INITIATED,
	PY_PAYMENT_VALIDATED,
	PY_PAYMENT_AUTHORIZED,
	PY_PAYMENT_SUBMITTED,
	PY_PAYMENT_SETTLED,
	PY_PAYMENT_REJECTED,
	PY_PAYMENT_RETURNED,
	PY_PAYMENT_CANCELLED,
	PY_BATCH_CREATED,
	PY_BATCH_SUBMITTED,
	PY_BATCH_SETTLED,
	PY_BATCH_PARTIALLY_SETTLED,
	PY_STANDING_ORDER_CREATED,
	PY_STANDING_ORDER_EXECUTED,
	PY_STANDING_ORDER_FAILED,
	PY_STANDING_ORDER_PAUSED,
	PY_STANDING_ORDER_RESUMED,
	PY_STANDING_ORDER_CANCELLED,
	PY_INBOUND_RECEIVED,
	PY_RECONCILIATION_COMPLETE,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"PaymentInitiatedEvent",
	"PaymentValidatedEvent",
	"PaymentAuthorizedEvent",
	"PaymentSubmittedEvent",
	"PaymentSettledEvent",
	"PaymentRejectedEvent",
	"PaymentReturnedEvent",
	"PaymentCancelledEvent",
	"BatchCreatedEvent",
	"BatchSubmittedEvent",
	"BatchSettledEvent",
	"BatchPartiallySettledEvent",
	"StandingOrderCreatedEvent",
	"StandingOrderExecutedEvent",
	"StandingOrderFailedEvent",
	"StandingOrderPausedEvent",
	"StandingOrderResumedEvent",
	"StandingOrderCancelledEvent",
	"InboundPaymentReceivedEvent",
	"ReconciliationCompleteEvent",
	# type constants
	"PY_PAYMENT_INITIATED",
	"PY_PAYMENT_VALIDATED",
	"PY_PAYMENT_AUTHORIZED",
	"PY_PAYMENT_SUBMITTED",
	"PY_PAYMENT_SETTLED",
	"PY_PAYMENT_REJECTED",
	"PY_PAYMENT_RETURNED",
	"PY_PAYMENT_CANCELLED",
	"PY_BATCH_CREATED",
	"PY_BATCH_SUBMITTED",
	"PY_BATCH_SETTLED",
	"PY_BATCH_PARTIALLY_SETTLED",
	"PY_STANDING_ORDER_CREATED",
	"PY_STANDING_ORDER_EXECUTED",
	"PY_STANDING_ORDER_FAILED",
	"PY_STANDING_ORDER_PAUSED",
	"PY_STANDING_ORDER_RESUMED",
	"PY_STANDING_ORDER_CANCELLED",
	"PY_INBOUND_RECEIVED",
	"PY_RECONCILIATION_COMPLETE",
	"ALL_PY_EVENT_TYPES",
]
