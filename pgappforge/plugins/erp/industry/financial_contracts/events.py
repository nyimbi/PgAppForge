"""
pgappforge/plugins/erp/industry/financial_contracts/events.py

Domain events for the Financial Contracts plugin (ACTUS-based).

All monetary amounts are integer cents.  Dates are ISO-8601 strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


@dataclass
class CashFlowsGeneratedEvent(DomainEvent):
	"""Emitted when cash flow schedule is generated for a contract."""
	event_type: str = "financial_contracts.cash_flows.generated"
	contract_id: str = ""
	actus_contract_id: str = ""
	contract_type: str = ""
	flow_count: int = 0
	first_event_date: str = ""    # ISO date string
	maturity_date: str = ""       # ISO date string


@dataclass
class ContractValuedEvent(DomainEvent):
	"""Emitted when a contract valuation snapshot is created."""
	event_type: str = "financial_contracts.contract.valued"
	contract_id: str = ""
	valuation_date: str = ""      # ISO date string
	valuation_method: str = ""
	npv_cents: int = 0
	duration_years: str = ""      # Decimal as string


@dataclass
class CashFlowSettledEvent(DomainEvent):
	"""Emitted when a scheduled cash flow is marked as SETTLED."""
	event_type: str = "financial_contracts.cash_flow.settled"
	cash_flow_id: str = ""
	contract_id: str = ""
	schedule_date: str = ""       # ISO date string
	event_type_code: str = ""     # IED, IP, PR, MD, etc.
	scheduled_amount_cents: int = 0
	actual_amount_cents: int = 0
	variance_cents: int = 0       # actual - scheduled


@dataclass
class CashFlowMissedEvent(DomainEvent):
	"""Emitted when a cash flow due date passes without settlement."""
	event_type: str = "financial_contracts.cash_flow.missed"
	cash_flow_id: str = ""
	contract_id: str = ""
	schedule_date: str = ""       # ISO date string
	scheduled_amount_cents: int = 0
	days_overdue: int = 0


@dataclass
class ContractDefaultedEvent(DomainEvent):
	"""Emitted when a contract transitions to DEFAULTED status."""
	event_type: str = "financial_contracts.contract.defaulted"
	contract_id: str = ""
	actus_contract_id: str = ""
	defaulted_at: str = ""        # ISO datetime string
	outstanding_amount_cents: int = 0


@dataclass
class StressTestCompletedEvent(DomainEvent):
	"""Emitted after a stress test run completes."""
	event_type: str = "financial_contracts.stress_test.completed"
	contract_id: str = ""
	scenario_count: int = 0
	worst_case_npv_cents: int = 0
	best_case_npv_cents: int = 0


__all__ = [
	"CashFlowsGeneratedEvent",
	"ContractValuedEvent",
	"CashFlowSettledEvent",
	"CashFlowMissedEvent",
	"ContractDefaultedEvent",
	"StressTestCompletedEvent",
	"emit_event",
]
