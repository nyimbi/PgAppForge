"""
pgappforge/plugins/erp/hcm/payroll/events.py

Domain events for the HCM Payroll plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  hcm.payroll.run.calculated       — calculate_payrun() completed
  hcm.payroll.run.approved         — payrun approved by authorised user
  hcm.payroll.run.paid             — bank file transmitted / payments confirmed
  hcm.payroll.payslip.reversed     — payslip reversal posted
  hcm.payroll.gl.posted            — payroll GL journal created
  hcm.payroll.statutory.filed      — statutory return submitted

Events consumed:
  hcm.employee.salary_changed      — triggers recalculation checks
  hcm.employee.terminated          — triggers termination payroll run creation
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# PayrollRun events
# ---------------------------------------------------------------------------

@dataclass
class PayrollRunCalculatedEvent(DomainEvent):
	"""Emitted when calculate_payrun() successfully computes all payslips."""
	event_type: str = "hcm.payroll.run.calculated"
	payrun_id: str = ""
	entity_id: str = ""
	period_start: str = ""        # ISO date
	period_end: str = ""          # ISO date
	pay_date: str = ""            # ISO date
	payroll_type: str = ""
	employee_count: int = 0
	total_gross_cents: int = 0
	total_employee_tax_cents: int = 0
	total_employer_tax_cents: int = 0
	total_net_cents: int = 0
	currency: str = ""


@dataclass
class PayrollRunApprovedEvent(DomainEvent):
	"""Emitted when a payrun is approved and ready for payment."""
	event_type: str = "hcm.payroll.run.approved"
	payrun_id: str = ""
	entity_id: str = ""
	approved_by: str = ""
	total_net_cents: int = 0
	pay_date: str = ""


@dataclass
class PayrollRunPaidEvent(DomainEvent):
	"""Emitted when payrun status transitions to PAID (bank file confirmed)."""
	event_type: str = "hcm.payroll.run.paid"
	payrun_id: str = ""
	entity_id: str = ""
	pay_date: str = ""
	total_net_cents: int = 0
	employee_count: int = 0
	currency: str = ""
	bank_file_ref: str = ""


# ---------------------------------------------------------------------------
# Payslip events
# ---------------------------------------------------------------------------

@dataclass
class PayslipReversedEvent(DomainEvent):
	"""Emitted when a payslip is reversed (correction entry posted)."""
	event_type: str = "hcm.payroll.payslip.reversed"
	payslip_id: str = ""
	original_payslip_id: str = ""
	employee_id: str = ""
	payrun_id: str = ""
	net_pay_cents: int = 0       # negative — reversal amount
	reason: str = ""


# ---------------------------------------------------------------------------
# GL / statutory events
# ---------------------------------------------------------------------------

@dataclass
class PayrollGLPostedEvent(DomainEvent):
	"""Emitted after payroll GL journal entries are created."""
	event_type: str = "hcm.payroll.gl.posted"
	payrun_id: str = ""
	journal_id: str = ""
	salary_expense_account: str = ""
	bank_account: str = ""
	tax_payable_account: str = ""
	total_gross_cents: int = 0
	total_net_cents: int = 0
	currency: str = ""


@dataclass
class StatutoryReportFiledEvent(DomainEvent):
	"""Emitted after a statutory payroll return is submitted to authorities."""
	event_type: str = "hcm.payroll.statutory.filed"
	entity_id: str = ""
	jurisdiction_code: str = ""
	report_year: int = 0
	report_period: str = ""      # e.g. "Q1", "annual"
	filing_reference: str = ""
	total_tax_cents: int = 0


__all__ = [
	"PayrollRunCalculatedEvent",
	"PayrollRunApprovedEvent",
	"PayrollRunPaidEvent",
	"PayslipReversedEvent",
	"PayrollGLPostedEvent",
	"StatutoryReportFiledEvent",
]
