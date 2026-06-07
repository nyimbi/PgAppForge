"""
pgappforge/plugins/erp/finance/profit_center/events.py

Domain events for the Profit Center Accounting plugin.

All amounts are integer cents (no float, ever).
Emitted inside the same SQLAlchemy session as the mutating operation so
persistence is atomic with the business transaction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Profit Center events
# ---------------------------------------------------------------------------

@dataclass
class ProfitCenterCreatedEvent(DomainEvent):
	"""Emitted when a new profit center is created."""
	event_type: str = "finance.profit_center.created"
	pc_id: str = ""
	code: str = ""
	name: str = ""


@dataclass
class ProfitCenterJournalPostedEvent(DomainEvent):
	"""Emitted when a journal line is posted to a profit center."""
	event_type: str = "finance.profit_center.journal.posted"
	journal_id: str = ""
	pc_id: str = ""
	debit_cents: int = 0
	credit_cents: int = 0
	period: str = ""    # e.g. "2025-01"


@dataclass
class ProfitCenterReportGeneratedEvent(DomainEvent):
	"""Emitted when a P&L or hierarchy report is generated."""
	event_type: str = "finance.profit_center.report.generated"
	report_id: str = ""
	pc_ids: list[str] = field(default_factory=list)
	period: str = ""


@dataclass
class ProfitCenterAllocationDoneEvent(DomainEvent):
	"""Emitted when a cost allocation run completes between profit centers."""
	event_type: str = "finance.profit_center.allocation.done"
	source_pc_id: str = ""
	# list of {profit_center_id, amount_cents, period}
	allocations: list[dict[str, Any]] = field(default_factory=list)


__all__ = [
	"ProfitCenterCreatedEvent",
	"ProfitCenterJournalPostedEvent",
	"ProfitCenterReportGeneratedEvent",
	"ProfitCenterAllocationDoneEvent",
	"emit_event",
]
