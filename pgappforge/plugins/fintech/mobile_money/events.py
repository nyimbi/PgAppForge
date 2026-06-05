"""
pgappforge/plugins/fintech/mobile_money/events.py

Domain events for the Mobile Money + Agency Banking plugin.

All events inherit from DomainEvent (erp.foundation).
Monetary fields are INTEGER cents — never float.

Usage
-----
	from pgappforge.plugins.fintech.mobile_money.events import (
		WalletRegisteredEvent,
		MoneyTransferredEvent,
		AgentDepositEvent,
		AgentWithdrawalEvent,
		BuyGoodsEvent,
		PayBillEvent,
		STKPushInitiatedEvent,
		C2BNotificationEvent,
		AgentFloatToppedUpEvent,
		AgentCommissionCalculatedEvent,
		MerchantSettledEvent,
		KYCUpgradedEvent,
		TransactionReversedEvent,
		emit_mm_event,
	)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event


# ---------------------------------------------------------------------------
# Wallet events
# ---------------------------------------------------------------------------

@dataclass
class WalletRegisteredEvent(DomainEvent):
	"""Emitted when a new mobile wallet is created."""
	event_type: str = "mm.wallet.registered"
	wallet_id: str = ""
	msisdn: str = ""
	kyc_tier: str = ""
	wallet_type: str = ""


@dataclass
class KYCUpgradedEvent(DomainEvent):
	"""Emitted when a wallet's KYC tier is upgraded."""
	event_type: str = "mm.wallet.kyc_upgraded"
	wallet_id: str = ""
	msisdn: str = ""
	old_tier: str = ""
	new_tier: str = ""
	new_max_balance_cents: int = 0
	new_daily_limit_cents: int = 0
	verified_by: str = ""


@dataclass
class WalletStatusChangedEvent(DomainEvent):
	"""Emitted on any wallet status transition (suspend, close, activate)."""
	event_type: str = "mm.wallet.status_changed"
	wallet_id: str = ""
	msisdn: str = ""
	old_status: str = ""
	new_status: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Transaction events
# ---------------------------------------------------------------------------

@dataclass
class MoneyTransferredEvent(DomainEvent):
	"""Emitted when a send-money (P2P) transaction completes."""
	event_type: str = "mm.transaction.send_money"
	transaction_id: str = ""
	confirmation_code: str = ""
	sender_msisdn: str = ""
	recipient_msisdn: str = ""
	amount_cents: int = 0
	fee_cents: int = 0
	channel: str = ""


@dataclass
class AgentDepositEvent(DomainEvent):
	"""Customer deposits cash at agent; wallet balance increases."""
	event_type: str = "mm.transaction.agent_deposit"
	transaction_id: str = ""
	confirmation_code: str = ""
	msisdn: str = ""
	agent_code: str = ""
	amount_cents: int = 0
	agent_float_after_cents: int = 0


@dataclass
class AgentWithdrawalEvent(DomainEvent):
	"""Customer withdraws cash at agent; wallet and agent float decrease."""
	event_type: str = "mm.transaction.agent_withdrawal"
	transaction_id: str = ""
	confirmation_code: str = ""
	msisdn: str = ""
	agent_code: str = ""
	amount_cents: int = 0
	fee_cents: int = 0
	agent_float_after_cents: int = 0


@dataclass
class BuyGoodsEvent(DomainEvent):
	"""Customer pays a merchant Buy-Goods till."""
	event_type: str = "mm.transaction.buy_goods"
	transaction_id: str = ""
	confirmation_code: str = ""
	msisdn: str = ""
	till_number: str = ""
	amount_cents: int = 0
	fee_cents: int = 0


@dataclass
class PayBillEvent(DomainEvent):
	"""Customer pays a Pay-Bill (utility / loan / subscription)."""
	event_type: str = "mm.transaction.pay_bill"
	transaction_id: str = ""
	confirmation_code: str = ""
	msisdn: str = ""
	paybill_number: str = ""
	account_number: str = ""
	amount_cents: int = 0
	fee_cents: int = 0


@dataclass
class STKPushInitiatedEvent(DomainEvent):
	"""Daraja STK Push request submitted; awaiting customer PIN entry."""
	event_type: str = "mm.stk_push.initiated"
	checkout_request_id: str = ""
	msisdn: str = ""
	merchant_code: str = ""
	reference: str = ""
	amount_cents: int = 0


@dataclass
class C2BNotificationEvent(DomainEvent):
	"""Daraja C2B callback processed; transaction record created."""
	event_type: str = "mm.c2b.notification"
	transaction_id: str = ""
	confirmation_code: str = ""
	sender_msisdn: str = ""
	merchant_code: str = ""
	amount_cents: int = 0


@dataclass
class TransactionReversedEvent(DomainEvent):
	"""A completed transaction reversed; correction entry created."""
	event_type: str = "mm.transaction.reversed"
	reversal_transaction_id: str = ""
	original_transaction_id: str = ""
	amount_cents: int = 0
	reason: str = ""


# ---------------------------------------------------------------------------
# Agent / Float events
# ---------------------------------------------------------------------------

@dataclass
class AgentFloatToppedUpEvent(DomainEvent):
	"""Agent float account topped up from a source account."""
	event_type: str = "mm.agent.float_top_up"
	agent_id: str = ""
	agent_code: str = ""
	amount_cents: int = 0
	float_before_cents: int = 0
	float_after_cents: int = 0
	source_account_id: str = ""


@dataclass
class AgentFloatLowEvent(DomainEvent):
	"""Agent float fell below min_float_cents threshold (warning)."""
	event_type: str = "mm.agent.float_low"
	agent_id: str = ""
	agent_code: str = ""
	current_float_cents: int = 0
	min_float_cents: int = 0


@dataclass
class AgentCommissionCalculatedEvent(DomainEvent):
	"""Commission accrual record created for an agent period."""
	event_type: str = "mm.agent.commission_calculated"
	commission_id: str = ""
	agent_id: str = ""
	agent_code: str = ""
	period_start: str = ""
	period_end: str = ""
	commission_earned_cents: int = 0
	transaction_count: int = 0


# ---------------------------------------------------------------------------
# Merchant events
# ---------------------------------------------------------------------------

@dataclass
class MerchantSettledEvent(DomainEvent):
	"""Daily settlement sweep to merchant account completed."""
	event_type: str = "mm.merchant.settled"
	till_id: str = ""
	till_number: str = ""
	settlement_date: str = ""
	amount_swept_cents: int = 0
	settlement_account_id: str = ""


# ---------------------------------------------------------------------------
# Fee events
# ---------------------------------------------------------------------------

@dataclass
class FeeCalculatedEvent(DomainEvent):
	"""Emitted when a fee is computed via the FeeSchedule engine."""
	event_type: str = "mm.fee.calculated"
	transaction_id: str = ""
	product_code: str = ""
	amount_cents: int = 0
	fee_cents: int = 0
	vat_cents: int = 0
	excise_cents: int = 0


# ---------------------------------------------------------------------------
# Idempotency events
# ---------------------------------------------------------------------------

@dataclass
class IdempotentReplayEvent(DomainEvent):
	"""Emitted when a duplicate idempotency_key is detected; original txn returned."""
	event_type: str = "mm.transaction.idempotent_replay"
	idempotency_key: str = ""
	original_transaction_id: str = ""


# ---------------------------------------------------------------------------
# GL posting events
# ---------------------------------------------------------------------------

@dataclass
class GLJournalPostedEvent(DomainEvent):
	"""Emitted when a double-entry GL journal is posted for a MM transaction."""
	event_type: str = "mm.gl.journal_posted"
	journal_id: str = ""
	mm_transaction_id: str = ""
	total_dr_cents: int = 0
	total_cr_cents: int = 0
	line_count: int = 0


# ---------------------------------------------------------------------------
# Standing order events
# ---------------------------------------------------------------------------

@dataclass
class StandingOrderExecutedEvent(DomainEvent):
	"""Emitted when a standing order payment executes successfully."""
	event_type: str = "mm.standing_order.executed"
	order_id: str = ""
	transaction_id: str = ""
	amount_cents: int = 0
	executions_done: int = 0


@dataclass
class StandingOrderSuspendedEvent(DomainEvent):
	"""Emitted when a standing order is suspended after max retries."""
	event_type: str = "mm.standing_order.suspended"
	order_id: str = ""
	retry_count: int = 0
	reason: str = ""


# ---------------------------------------------------------------------------
# Batch disbursement events
# ---------------------------------------------------------------------------

@dataclass
class DisbursementBatchStartedEvent(DomainEvent):
	"""Emitted when a disbursement batch begins processing."""
	event_type: str = "mm.disbursement.batch_started"
	batch_id: str = ""
	total_recipients: int = 0
	total_amount_cents: int = 0


@dataclass
class DisbursementBatchCompletedEvent(DomainEvent):
	"""Emitted when a disbursement batch finishes (success or partial)."""
	event_type: str = "mm.disbursement.batch_completed"
	batch_id: str = ""
	success_count: int = 0
	failure_count: int = 0
	total_amount_cents: int = 0


# ---------------------------------------------------------------------------
# AML events
# ---------------------------------------------------------------------------

@dataclass
class AMLBlockedEvent(DomainEvent):
	"""Emitted when an AML checkpoint blocks a transaction."""
	event_type: str = "mm.aml.blocked"
	wallet_id: str = ""
	amount_cents: int = 0
	rule_ids: list = field(default_factory=list)
	txn_type: str = ""


@dataclass
class AMLReviewFlaggedEvent(DomainEvent):
	"""Emitted when an AML checkpoint flags a transaction for review."""
	event_type: str = "mm.aml.review_flagged"
	wallet_id: str = ""
	amount_cents: int = 0
	rule_ids: list = field(default_factory=list)
	txn_type: str = ""


# ---------------------------------------------------------------------------
# Fraud events
# ---------------------------------------------------------------------------

@dataclass
class FraudBlockedEvent(DomainEvent):
	"""Emitted when fraud score ≥ 80 blocks a transaction."""
	event_type: str = "mm.fraud.blocked"
	wallet_id: str = ""
	fraud_score: int = 0
	signal_types: list = field(default_factory=list)


@dataclass
class FraudOTPRequiredEvent(DomainEvent):
	"""Emitted when fraud score 50–79 requires OTP re-authentication."""
	event_type: str = "mm.fraud.otp_required"
	wallet_id: str = ""
	fraud_score: int = 0
	signal_types: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Dormancy events
# ---------------------------------------------------------------------------

@dataclass
class WalletDormantEvent(DomainEvent):
	"""Emitted when a wallet is moved to DORMANT status."""
	event_type: str = "mm.wallet.dormant"
	wallet_id: str = ""
	msisdn: str = ""
	last_transaction_at: str = ""


@dataclass
class WalletReactivatedEvent(DomainEvent):
	"""Emitted when a dormant wallet is reactivated by customer action."""
	event_type: str = "mm.wallet.reactivated"
	wallet_id: str = ""
	msisdn: str = ""


# ---------------------------------------------------------------------------
# Reconciliation events
# ---------------------------------------------------------------------------

@dataclass
class ReconciliationCompletedEvent(DomainEvent):
	"""Emitted when an EOD reconciliation run finishes."""
	event_type: str = "mm.reconciliation.completed"
	run_id: str = ""
	run_date: str = ""
	total_wallets_checked: int = 0
	breaks_found: int = 0
	breaks_auto_resolved: int = 0


@dataclass
class ReconciliationBreakEscalatedEvent(DomainEvent):
	"""Emitted when a reconciliation break cannot be auto-resolved."""
	event_type: str = "mm.reconciliation.break_escalated"
	break_id: str = ""
	run_id: str = ""
	wallet_id: str = ""
	break_type: str = ""
	variance_cents: int = 0


# ---------------------------------------------------------------------------
# Convenience emit wrapper
# ---------------------------------------------------------------------------

def emit_mm_event(event: DomainEvent, session: Any) -> None:
	"""Thin wrapper around foundation emit_event.

	Swallows all exceptions — event emission must never fail a service call.
	Delegates to erp.foundation.commons.emit_event (which already swallows).
	"""
	try:
		emit_event(event, session)
	except Exception:
		pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Wallet
	"WalletRegisteredEvent",
	"KYCUpgradedEvent",
	"WalletStatusChangedEvent",
	# Transactions
	"MoneyTransferredEvent",
	"AgentDepositEvent",
	"AgentWithdrawalEvent",
	"BuyGoodsEvent",
	"PayBillEvent",
	"STKPushInitiatedEvent",
	"C2BNotificationEvent",
	"TransactionReversedEvent",
	# Agent / Float
	"AgentFloatToppedUpEvent",
	"AgentFloatLowEvent",
	"AgentCommissionCalculatedEvent",
	# Merchant
	"MerchantSettledEvent",
	# Fee engine
	"FeeCalculatedEvent",
	# Idempotency
	"IdempotentReplayEvent",
	# GL
	"GLJournalPostedEvent",
	# Standing orders
	"StandingOrderExecutedEvent",
	"StandingOrderSuspendedEvent",
	# Batch disbursement
	"DisbursementBatchStartedEvent",
	"DisbursementBatchCompletedEvent",
	# AML
	"AMLBlockedEvent",
	"AMLReviewFlaggedEvent",
	# Fraud
	"FraudBlockedEvent",
	"FraudOTPRequiredEvent",
	# Dormancy
	"WalletDormantEvent",
	"WalletReactivatedEvent",
	# Reconciliation
	"ReconciliationCompletedEvent",
	"ReconciliationBreakEscalatedEvent",
	# Helpers
	"emit_mm_event",
]
