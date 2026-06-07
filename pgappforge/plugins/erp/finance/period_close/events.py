"""
pgappforge/plugins/erp/finance/period_close/events.py

Domain events for the Period Close Checklist plugin.

Events emitted
--------------
  finance.period_close.started          — close process kicked off
  finance.period_close.task.completed   — individual task marked complete
  finance.period_close.task.skipped     — non-mandatory task skipped
  finance.period_close.finalized        — all tasks done; period sealed
  finance.period_close.blocked          — finalize attempted with outstanding mandatory tasks
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class PeriodCloseStartedEvent(DomainEvent):
	"""Emitted when a PeriodClose record transitions to IN_PROGRESS."""
	event_type: str = "finance.period_close.started"
	close_id: str = ""
	period: str = ""        # e.g. "2025-01"
	entity_id: str = ""
	tenant_id: str = ""


@dataclass
class PeriodCloseTaskCompletedEvent(DomainEvent):
	"""Emitted when a PeriodCloseTask is marked COMPLETE."""
	event_type: str = "finance.period_close.task.completed"
	task_id: str = ""
	close_id: str = ""
	task_code: str = ""
	completed_by: str = ""


@dataclass
class PeriodCloseTaskSkippedEvent(DomainEvent):
	"""Emitted when a non-mandatory PeriodCloseTask is skipped."""
	event_type: str = "finance.period_close.task.skipped"
	task_id: str = ""
	close_id: str = ""
	task_code: str = ""
	reason: str = ""


@dataclass
class PeriodCloseFinalizedEvent(DomainEvent):
	"""Emitted when all mandatory tasks are done and the period is sealed CLOSED."""
	event_type: str = "finance.period_close.finalized"
	close_id: str = ""
	period: str = ""
	entity_id: str = ""
	closed_by: str = ""


@dataclass
class PeriodCloseBlockedEvent(DomainEvent):
	"""Emitted when finalize is attempted but mandatory tasks are still outstanding."""
	event_type: str = "finance.period_close.blocked"
	close_id: str = ""
	period: str = ""
	blocking_task_codes: list[str] = field(default_factory=list)


__all__ = [
	"PeriodCloseStartedEvent",
	"PeriodCloseTaskCompletedEvent",
	"PeriodCloseTaskSkippedEvent",
	"PeriodCloseFinalizedEvent",
	"PeriodCloseBlockedEvent",
]
