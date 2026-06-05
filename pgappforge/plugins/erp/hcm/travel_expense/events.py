"""
pgappforge/plugins/erp/hcm/travel_expense/events.py

Domain events for the HCM Travel & Expense plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  hcm.travel_expense.report.submitted      — report moved DRAFT→SUBMITTED
  hcm.travel_expense.report.approved       — report approved by authorised user
  hcm.travel_expense.report.paid           — reimbursement disbursed
  hcm.travel_expense.advance.disbursed     — cash advance paid out
  hcm.travel_expense.policy.breach         — expense line flagged for policy breach
  hcm.travel_expense.bik.flagged           — expense line marked as PAYE benefit-in-kind

Events consumed:
  hcm.payroll.run.requested  — triggers BIK inclusion in payroll
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# ExpenseReport events
# ---------------------------------------------------------------------------

@dataclass
class ExpenseReportSubmittedEvent(DomainEvent):
	"""Emitted when an expense report transitions DRAFT → SUBMITTED."""
	event_type: str = "hcm.travel_expense.report.submitted"
	report_id: str = ""
	employee_id: str = ""
	title: str = ""
	destination: str = ""
	trip_start: str = ""            # ISO date
	trip_end: str = ""              # ISO date
	total_claimed_cents: int = 0
	advance_received_cents: int = 0
	reimbursement_due_cents: int = 0
	currency_code: str = "KES"
	line_count: int = 0
	breach_count: int = 0           # lines with policy_breach=True


@dataclass
class ExpenseReportApprovedEvent(DomainEvent):
	"""Emitted when an expense report is approved by an authorised approver."""
	event_type: str = "hcm.travel_expense.report.approved"
	report_id: str = ""
	employee_id: str = ""
	approved_by: str = ""
	total_approved_cents: int = 0
	reimbursement_due_cents: int = 0
	currency_code: str = "KES"
	bik_cents: int = 0              # sum of BIK-flagged lines for PAYE


@dataclass
class ExpenseReportPaidEvent(DomainEvent):
	"""Emitted when reimbursement is disbursed and report status → PAID."""
	event_type: str = "hcm.travel_expense.report.paid"
	report_id: str = ""
	employee_id: str = ""
	reimbursement_due_cents: int = 0
	payment_ref: str = ""
	currency_code: str = "KES"
	gl_journal_id: str = ""
	bik_cents: int = 0              # total BIK forwarded to payroll


# ---------------------------------------------------------------------------
# CashAdvance events
# ---------------------------------------------------------------------------

@dataclass
class AdvanceDisbursedEvent(DomainEvent):
	"""Emitted when a cash advance is physically disbursed to the employee."""
	event_type: str = "hcm.travel_expense.advance.disbursed"
	advance_id: str = ""
	employee_id: str = ""
	amount_cents: int = 0
	currency_code: str = "KES"
	disbursement_ref: str = ""
	gl_journal_id: str = ""


# ---------------------------------------------------------------------------
# Policy / compliance events
# ---------------------------------------------------------------------------

@dataclass
class PolicyBreachFlaggedEvent(DomainEvent):
	"""Emitted when a policy check marks an expense line as non-compliant."""
	event_type: str = "hcm.travel_expense.policy.breach"
	report_id: str = ""
	line_id: str = ""
	employee_id: str = ""
	expense_category: str = ""
	amount_cents: int = 0
	limit_cents: int = 0
	breach_amount_cents: int = 0
	policy_applied: str = ""        # ExpensePolicy.name
	reason: str = ""


@dataclass
class BIKFlaggedEvent(DomainEvent):
	"""Emitted when an expense line is marked as a PAYE benefit-in-kind.

	Payroll plugin subscribes to this to include BIK in the next pay run.
	"""
	event_type: str = "hcm.travel_expense.bik.flagged"
	report_id: str = ""
	line_id: str = ""
	employee_id: str = ""
	bik_amount_cents: int = 0
	currency_code: str = "KES"
	expense_category: str = ""
	payroll_period: str = ""        # ISO date of expected pay run, may be empty


__all__ = [
	"ExpenseReportSubmittedEvent",
	"ExpenseReportApprovedEvent",
	"ExpenseReportPaidEvent",
	"AdvanceDisbursedEvent",
	"PolicyBreachFlaggedEvent",
	"BIKFlaggedEvent",
]
