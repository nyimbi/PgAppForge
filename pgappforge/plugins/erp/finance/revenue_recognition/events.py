"""
pgappforge/plugins/erp/finance/revenue_recognition/events.py

Domain events for the Revenue Recognition plugin (ASC 606 / IFRS 15).

All amounts are integer cents (no float, ever).
Emitted inside the same SQLAlchemy session as the mutating operation so
persistence is atomic with the business transaction.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Revenue Recognition events
# ---------------------------------------------------------------------------

@dataclass
class ContractCreatedEvent(DomainEvent):
	"""Emitted when a new ASC 606 / IFRS 15 contract is created."""
	event_type: str = "finance.rev_rec.contract.created"
	contract_id: str = ""
	customer_id: str = ""
	total_value_cents: int = 0
	tenant_id: str = ""


@dataclass
class PerformanceObligationSatisfiedEvent(DomainEvent):
	"""Emitted when a performance obligation is fully or partially satisfied."""
	event_type: str = "finance.rev_rec.po.satisfied"
	obligation_id: str = ""
	contract_id: str = ""
	recognized_cents: int = 0
	period: str = ""          # ISO period string e.g. "2025-01"


@dataclass
class RevenueRecognizedEvent(DomainEvent):
	"""Emitted when revenue is formally recognized for a contract period."""
	event_type: str = "finance.rev_rec.revenue.recognized"
	contract_id: str = ""
	period: str = ""          # ISO period string e.g. "2025-01"
	amount_cents: int = 0
	method: str = ""          # STRAIGHT_LINE | OUTPUT | INPUT | COMPLETED_CONTRACT


@dataclass
class ContractModifiedEvent(DomainEvent):
	"""Emitted when a contract is modified per ASC 606-10-25-18 / IFRS 15.18."""
	event_type: str = "finance.rev_rec.contract.modified"
	contract_id: str = ""
	modification_type: str = ""   # PROSPECTIVE | CUMULATIVE_CATCH_UP
	new_value_cents: int = 0


@dataclass
class VariableConsiderationEstimatedEvent(DomainEvent):
	"""Emitted when variable consideration is estimated or re-estimated."""
	event_type: str = "finance.rev_rec.variable.estimated"
	contract_id: str = ""
	estimated_cents: int = 0
	method: str = ""          # EXPECTED_VALUE | MOST_LIKELY_AMOUNT


@dataclass
class AllocationUpdatedEvent(DomainEvent):
	"""Emitted when transaction price allocation is recomputed across obligations."""
	event_type: str = "finance.rev_rec.allocation.updated"
	contract_id: str = ""
	obligation_count: int = 0


__all__ = [
	"ContractCreatedEvent",
	"PerformanceObligationSatisfiedEvent",
	"RevenueRecognizedEvent",
	"ContractModifiedEvent",
	"VariableConsiderationEstimatedEvent",
	"AllocationUpdatedEvent",
	"emit_event",
]
