"""
pgappforge/plugins/fintech/lending/events.py

Domain events for the Lending plugin (LOS + LMS).

All lending events are subclasses of DomainEvent from the ERP foundation.
Monetary fields use INTEGER cents.

Event type naming convention: ln.<aggregate>.<verb>

Subscribers register via::

	from pgappforge.plugins.erp.foundation.events import subscribe
	from pgappforge.plugins.fintech.lending.events import LoanDisbursedEvent

	subscribe("ln.loan.disbursed", my_handler)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Loan Origination System (LOS) events
# ---------------------------------------------------------------------------

@dataclass
class ApplicationSubmittedEvent(DomainEvent):
	"""Emitted when applicant formally submits a loan application."""
	event_type: str = "ln.application.submitted"
	application_id: str = ""
	application_number: str = ""
	applicant_id: str = ""
	product_code: str = ""
	requested_amount_cents: int = 0
	requested_tenor_months: int = 0
	channel: str = ""


@dataclass
class LoanApprovedEvent(DomainEvent):
	"""Emitted when an underwriter approves a loan application."""
	event_type: str = "ln.loan.approved"
	application_id: str = ""
	application_number: str = ""
	applicant_id: str = ""
	approved_amount_cents: int = 0
	approved_tenor_months: int = 0
	approved_rate_pa: str = ""  # stored as string — Decimal from Numeric field
	approver_id: str = ""


@dataclass
class LoanRejectedEvent(DomainEvent):
	"""Emitted when an application is declined."""
	event_type: str = "ln.loan.rejected"
	application_id: str = ""
	application_number: str = ""
	applicant_id: str = ""
	rejection_reason: str = ""
	decision_by: str = ""


@dataclass
class LoanDisbursedEvent(DomainEvent):
	"""Emitted when loan funds are credited to the borrower's account."""
	event_type: str = "ln.loan.disbursed"
	loan_id: str = ""
	loan_number: str = ""
	application_id: str = ""
	borrower_id: str = ""
	principal_cents: int = 0
	disbursement_date: str = ""  # ISO date string
	maturity_date: str = ""


# ---------------------------------------------------------------------------
# Loan Management System (LMS) events
# ---------------------------------------------------------------------------

@dataclass
class RepaymentReceivedEvent(DomainEvent):
	"""Emitted when a repayment is applied to a loan."""
	event_type: str = "ln.repayment.received"
	repayment_id: str = ""
	loan_id: str = ""
	loan_number: str = ""
	amount_cents: int = 0
	principal_applied_cents: int = 0
	interest_applied_cents: int = 0
	penalty_applied_cents: int = 0
	remaining_principal_cents: int = 0
	source: str = ""
	payment_date: str = ""


@dataclass
class LoanOverdueEvent(DomainEvent):
	"""Emitted by daily aging when a loan crosses into overdue state."""
	event_type: str = "ln.loan.overdue"
	loan_id: str = ""
	loan_number: str = ""
	borrower_id: str = ""
	days_past_due: int = 0
	arrears_principal_cents: int = 0
	arrears_interest_cents: int = 0
	as_of_date: str = ""


@dataclass
class LoanNpaClassifiedEvent(DomainEvent):
	"""Emitted when NPA classification changes (e.g. PERFORMING → WATCH)."""
	event_type: str = "ln.loan.npa_classified"
	loan_id: str = ""
	loan_number: str = ""
	borrower_id: str = ""
	previous_classification: str = ""
	new_classification: str = ""
	days_past_due: int = 0
	provision_rate_pct: str = ""  # string from Numeric
	provision_amount_cents: int = 0
	as_of_date: str = ""


@dataclass
class LoanWrittenOffEvent(DomainEvent):
	"""Emitted when a loan is written off the books."""
	event_type: str = "ln.loan.written_off"
	loan_id: str = ""
	loan_number: str = ""
	borrower_id: str = ""
	written_off_amount_cents: int = 0
	written_off_date: str = ""
	reason: str = ""


@dataclass
class LoanSettledEvent(DomainEvent):
	"""Emitted when a loan is fully repaid and closed."""
	event_type: str = "ln.loan.settled"
	loan_id: str = ""
	loan_number: str = ""
	borrower_id: str = ""
	settled_date: str = ""
	total_paid_cents: int = 0


@dataclass
class LoanRestructuredEvent(DomainEvent):
	"""Emitted when a loan is restructured into a new loan record."""
	event_type: str = "ln.loan.restructured"
	original_loan_id: str = ""
	original_loan_number: str = ""
	new_loan_id: str = ""
	new_loan_number: str = ""
	borrower_id: str = ""
	new_tenor_months: int = 0
	new_rate_pa: str = ""
	reason: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# LOS
	"ApplicationSubmittedEvent",
	"LoanApprovedEvent",
	"LoanRejectedEvent",
	"LoanDisbursedEvent",
	# LMS
	"RepaymentReceivedEvent",
	"LoanOverdueEvent",
	"LoanNpaClassifiedEvent",
	"LoanWrittenOffEvent",
	"LoanSettledEvent",
	"LoanRestructuredEvent",
]
