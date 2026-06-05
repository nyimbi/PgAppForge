"""
pgappforge/plugins/fintech/sacco/events.py

Domain events for the SACCO / MFI / Chama plugin.

All events are subclasses of DomainEvent from the ERP foundation.
Monetary fields use INTEGER cents.

Event type naming convention: sc.<aggregate>.<verb>

Subscribers register via::

	from pgappforge.plugins.erp.foundation.events import subscribe
	from pgappforge.plugins.fintech.sacco.events import MemberRegisteredEvent

	subscribe("sc.member.registered", my_handler)
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# SACCO / Member events
# ---------------------------------------------------------------------------

@dataclass
class MemberRegisteredEvent(DomainEvent):
	"""Emitted when a new member is accepted into a SACCO."""
	event_type: str = "sc.member.registered"
	member_id: str = ""
	member_number: str = ""
	sacco_id: str = ""
	party_id: str = ""
	initial_shares: int = 0
	share_value_cents: int = 0
	membership_date: str = ""  # ISO date


@dataclass
class MemberContributionPostedEvent(DomainEvent):
	"""Emitted when a monthly savings contribution is processed."""
	event_type: str = "sc.member.contribution_posted"
	member_id: str = ""
	member_number: str = ""
	sacco_id: str = ""
	amount_cents: int = 0
	deposit_account_id: str = ""
	contribution_date: str = ""  # ISO date


@dataclass
class MemberExitCalculatedEvent(DomainEvent):
	"""Emitted when a member exit value is calculated (before payout)."""
	event_type: str = "sc.member.exit_calculated"
	member_id: str = ""
	member_number: str = ""
	sacco_id: str = ""
	shares_value_cents: int = 0
	deposits_cents: int = 0
	outstanding_loans_cents: int = 0
	active_guarantees_cents: int = 0
	net_payable_cents: int = 0


# ---------------------------------------------------------------------------
# SACCO Loan events
# ---------------------------------------------------------------------------

@dataclass
class SACCOLoanApplicationCreatedEvent(DomainEvent):
	"""Emitted when a member submits a SACCO loan application."""
	event_type: str = "sc.loan.application_created"
	application_id: str = ""
	member_id: str = ""
	member_number: str = ""
	sacco_id: str = ""
	product_id: str = ""
	amount_cents: int = 0
	tenor_months: int = 0
	guarantor_ids: list = None  # type: ignore[assignment]

	def __post_init__(self) -> None:
		if self.guarantor_ids is None:
			self.guarantor_ids = []


@dataclass
class SACCOLoanApprovedEvent(DomainEvent):
	"""Emitted when a SACCO loan application passes eligibility checks."""
	event_type: str = "sc.loan.approved"
	application_id: str = ""
	member_id: str = ""
	sacco_id: str = ""
	approved_amount_cents: int = 0
	tenor_months: int = 0
	interest_rate_pa: str = ""  # string from Numeric


# ---------------------------------------------------------------------------
# Dividend events
# ---------------------------------------------------------------------------

@dataclass
class DividendDeclaredEvent(DomainEvent):
	"""Emitted when an AGM declares a dividend for a financial year."""
	event_type: str = "sc.dividend.declared"
	dividend_id: str = ""
	sacco_id: str = ""
	financial_year: int = 0
	dividend_rate_pct: str = ""   # string from Numeric
	interest_rebate_pct: str = "" # string from Numeric
	total_dividend_pool_cents: int = 0
	approved_date: str = ""  # ISO date


@dataclass
class DividendPaidEvent(DomainEvent):
	"""Emitted after all member dividend credits have been posted."""
	event_type: str = "sc.dividend.paid"
	dividend_id: str = ""
	sacco_id: str = ""
	financial_year: int = 0
	total_paid_cents: int = 0
	members_credited: int = 0
	payment_date: str = ""  # ISO date


# ---------------------------------------------------------------------------
# Chama events
# ---------------------------------------------------------------------------

@dataclass
class ChamaCreatedEvent(DomainEvent):
	"""Emitted when a new Chama is formed."""
	event_type: str = "sc.chama.created"
	chama_id: str = ""
	chama_name: str = ""
	chama_type: str = ""
	founding_member_ids: list = None  # type: ignore[assignment]

	def __post_init__(self) -> None:
		if self.founding_member_ids is None:
			self.founding_member_ids = []


@dataclass
class ChamaContributionPostedEvent(DomainEvent):
	"""Emitted when a Chama member makes a contribution."""
	event_type: str = "sc.chama.contribution_posted"
	chama_id: str = ""
	member_id: str = ""
	amount_cents: int = 0
	new_pool_cents: int = 0
	contribution_date: str = ""  # ISO date


@dataclass
class MerryGoRoundDisbursedEvent(DomainEvent):
	"""Emitted when the merry-go-round pool is paid to the current recipient."""
	event_type: str = "sc.chama.merry_go_round_disbursed"
	chama_id: str = ""
	recipient_member_id: str = ""
	amount_cents: int = 0
	next_recipient_member_id: str = ""
	disbursement_date: str = ""  # ISO date


@dataclass
class TableBankingLoanCreatedEvent(DomainEvent):
	"""Emitted when a table-banking loan is issued from a Chama pool."""
	event_type: str = "sc.chama.table_banking_loan_created"
	chama_id: str = ""
	borrower_id: str = ""
	amount_cents: int = 0
	repayment_weeks: int = 0
	due_date: str = ""  # ISO date


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Member
	"MemberRegisteredEvent",
	"MemberContributionPostedEvent",
	"MemberExitCalculatedEvent",
	# SACCO loan
	"SACCOLoanApplicationCreatedEvent",
	"SACCOLoanApprovedEvent",
	# Dividend
	"DividendDeclaredEvent",
	"DividendPaidEvent",
	# Chama
	"ChamaCreatedEvent",
	"ChamaContributionPostedEvent",
	"MerryGoRoundDisbursedEvent",
	"TableBankingLoanCreatedEvent",
]
