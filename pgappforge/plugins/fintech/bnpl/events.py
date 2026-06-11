"""
pgappforge/plugins/fintech/bnpl/events.py

Buy-Now-Pay-Later domain events.

All events extend DomainEvent from erp.foundation.events.
They are emitted by BNPLService and persisted atomically to
the DomainEventLog within the same SQLAlchemy session.

Event catalogue
---------------
  bnpl.application.approved     — application approved, plan created
  bnpl.application.declined     — application declined (credit/affordability fail)
  bnpl.installment.due          — an instalment is coming due (reminder)
  bnpl.installment.paid         — an instalment payment processed
  bnpl.installment.overdue      — instalment past due, penalty applied
  bnpl.settlement.paid          — merchant settlement disbursed
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Application lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class BNPLApprovedEvent(DomainEvent):
	"""Emitted when an application is approved and a plan is created."""
	event_type: str = "bnpl.application.approved"
	application_id: str = ""
	customer_id: str = ""
	merchant_id: str = ""
	plan_id: str = ""
	approved_limit_cents: int = 0
	plan_type: str = ""
	installment_count: int = 0


@dataclass
class BNPLDeclinedEvent(DomainEvent):
	"""Emitted when an application is declined."""
	event_type: str = "bnpl.application.declined"
	application_id: str = ""
	customer_id: str = ""
	merchant_id: str = ""
	reason: str = ""
	credit_score: int = 0
	affordability_score: int = 0


# ---------------------------------------------------------------------------
# Instalment lifecycle events
# ---------------------------------------------------------------------------

@dataclass
class InstallmentDueEvent(DomainEvent):
	"""Emitted when an instalment is approaching its due date (reminder)."""
	event_type: str = "bnpl.installment.due"
	installment_id: str = ""
	plan_id: str = ""
	customer_id: str = ""
	installment_number: int = 0
	due_date: str = ""		# ISO date string
	amount_cents: int = 0


@dataclass
class InstallmentPaidEvent(DomainEvent):
	"""Emitted when an instalment payment is successfully processed."""
	event_type: str = "bnpl.installment.paid"
	installment_id: str = ""
	plan_id: str = ""
	customer_id: str = ""
	installment_number: int = 0
	paid_amount_cents: int = 0
	paid_date: str = ""		# ISO date string


@dataclass
class InstallmentOverdueEvent(DomainEvent):
	"""Emitted when an instalment is marked OVERDUE and a penalty is applied."""
	event_type: str = "bnpl.installment.overdue"
	installment_id: str = ""
	plan_id: str = ""
	customer_id: str = ""
	installment_number: int = 0
	due_date: str = ""		# ISO date string
	amount_cents: int = 0
	penalty_cents: int = 0


# ---------------------------------------------------------------------------
# Settlement events
# ---------------------------------------------------------------------------

@dataclass
class MerchantSettledEvent(DomainEvent):
	"""Emitted when a merchant settlement is marked PAID."""
	event_type: str = "bnpl.settlement.paid"
	settlement_id: str = ""
	merchant_id: str = ""
	period: str = ""
	gross_sales_cents: int = 0
	commission_cents: int = 0
	net_payout_cents: int = 0


# ---------------------------------------------------------------------------
# Event type string constants
# ---------------------------------------------------------------------------

BNPL_APPLICATION_APPROVED = "bnpl.application.approved"
BNPL_APPLICATION_DECLINED = "bnpl.application.declined"
BNPL_INSTALLMENT_DUE = "bnpl.installment.due"
BNPL_INSTALLMENT_PAID = "bnpl.installment.paid"
BNPL_INSTALLMENT_OVERDUE = "bnpl.installment.overdue"
BNPL_SETTLEMENT_PAID = "bnpl.settlement.paid"

ALL_BNPL_EVENT_TYPES: list[str] = [
	BNPL_APPLICATION_APPROVED,
	BNPL_APPLICATION_DECLINED,
	BNPL_INSTALLMENT_DUE,
	BNPL_INSTALLMENT_PAID,
	BNPL_INSTALLMENT_OVERDUE,
	BNPL_SETTLEMENT_PAID,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"BNPLApprovedEvent",
	"BNPLDeclinedEvent",
	"InstallmentDueEvent",
	"InstallmentPaidEvent",
	"InstallmentOverdueEvent",
	"MerchantSettledEvent",
	# event type string constants
	"BNPL_APPLICATION_APPROVED",
	"BNPL_APPLICATION_DECLINED",
	"BNPL_INSTALLMENT_DUE",
	"BNPL_INSTALLMENT_PAID",
	"BNPL_INSTALLMENT_OVERDUE",
	"BNPL_SETTLEMENT_PAID",
	"ALL_BNPL_EVENT_TYPES",
]
