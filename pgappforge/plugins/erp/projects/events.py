"""
pgappforge/plugins/erp/projects/events.py

Domain events for the Project Management / PSA plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  projects.project.created            — new project record created
  projects.timesheet.approved         — timesheet entry approved for billing
  projects.invoice.generated          — project invoice produced
  projects.revenue.recognised         — IFRS 15 revenue recognition entry posted
  projects.change_order.approved      — change order approved; budget/schedule updated
  projects.risk.raised                — new project risk logged
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Project events
# ---------------------------------------------------------------------------

@dataclass
class ProjectCreatedEvent(DomainEvent):
	"""Emitted when create_project() successfully inserts a new project."""
	event_type: str = "projects.project.created"
	project_id: str = ""
	project_code: str = ""
	project_type: str = ""      # FIXED_FEE | T_AND_M | RETAINER | MILESTONE
	customer_id: str = ""
	owner_id: str = ""
	original_budget_cents: int = 0
	currency_code: str = "KES"
	start_date: str = ""        # ISO date
	end_date: str = ""          # ISO date


# ---------------------------------------------------------------------------
# Timesheet events
# ---------------------------------------------------------------------------

@dataclass
class TimesheetApprovedEvent(DomainEvent):
	"""Emitted when approve_timesheet() moves a timesheet to APPROVED status."""
	event_type: str = "projects.timesheet.approved"
	timesheet_id: str = ""
	project_id: str = ""
	employee_id: str = ""
	wbs_element_id: str = ""
	work_date: str = ""         # ISO date
	hours: str = ""             # Decimal string e.g. "7.50"
	approved_by: str = ""


# ---------------------------------------------------------------------------
# Invoice events
# ---------------------------------------------------------------------------

@dataclass
class InvoiceGeneratedEvent(DomainEvent):
	"""Emitted when generate_invoice() creates a ProjectInvoice."""
	event_type: str = "projects.invoice.generated"
	invoice_id: str = ""
	project_id: str = ""
	invoice_number: str = ""
	invoice_type: str = ""      # MILESTONE | T_AND_M | RETAINER | ADVANCE
	amount_cents: int = 0
	tax_cents: int = 0
	total_cents: int = 0
	currency_code: str = "KES"
	invoice_date: str = ""      # ISO date


# ---------------------------------------------------------------------------
# Revenue recognition events
# ---------------------------------------------------------------------------

@dataclass
class RevenueRecognisedEvent(DomainEvent):
	"""Emitted when recognise_revenue() posts a revenue recognition entry."""
	event_type: str = "projects.revenue.recognised"
	project_id: str = ""
	method: str = ""            # POC | MILESTONE | COMPLETED_CONTRACT
	as_of_date: str = ""        # ISO date
	recognised_amount_cents: int = 0
	cumulative_recognised_cents: int = 0
	percent_complete: str = ""  # Decimal string e.g. "42.50"
	gl_journal_id: str = ""


# ---------------------------------------------------------------------------
# Change order events
# ---------------------------------------------------------------------------

@dataclass
class ChangeOrderApprovedEvent(DomainEvent):
	"""Emitted when approve_change_order() transitions a ChangeOrder to APPROVED."""
	event_type: str = "projects.change_order.approved"
	change_order_id: str = ""
	project_id: str = ""
	co_number: str = ""
	budget_delta_cents: int = 0
	schedule_delta_days: int = 0
	new_revised_budget_cents: int = 0
	new_end_date: str = ""      # ISO date
	approved_by: str = ""


# ---------------------------------------------------------------------------
# Risk events
# ---------------------------------------------------------------------------

@dataclass
class RiskRaisedEvent(DomainEvent):
	"""Emitted when a new ProjectRisk is added to a project."""
	event_type: str = "projects.risk.raised"
	risk_id: str = ""
	project_id: str = ""
	title: str = ""
	probability: int = 0        # 1–5
	impact: int = 0             # 1–5
	risk_score: int = 0         # probability × impact
	risk_owner_id: str = ""
	status: str = "OPEN"


__all__ = [
	"ProjectCreatedEvent",
	"TimesheetApprovedEvent",
	"InvoiceGeneratedEvent",
	"RevenueRecognisedEvent",
	"ChangeOrderApprovedEvent",
	"RiskRaisedEvent",
]
