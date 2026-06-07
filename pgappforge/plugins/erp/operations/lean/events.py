"""
pgappforge/plugins/erp/operations/lean/events.py

Domain events for the Lean / Kanban plugin.

Events emitted:
  ops.lean.board.created   — new Kanban board created
  ops.lean.card.moved      — card moved between columns
  ops.lean.wip.breach      — WIP limit breached on a column
  ops.lean.pull.triggered  — pull signal triggered for replenishment
  ops.lean.cycle_time      — cycle-time metrics recorded for a board/period
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class KanbanBoardCreatedEvent(DomainEvent):
	"""Emitted when a new Kanban board is created."""
	event_type: str = "ops.lean.board.created"
	board_id: str = ""
	name: str = ""
	tenant_id: str = ""


@dataclass
class KanbanCardMovedEvent(DomainEvent):
	"""Emitted when a card is moved from one column to another."""
	event_type: str = "ops.lean.card.moved"
	card_id: str = ""
	from_column: str = ""
	to_column: str = ""
	moved_by: str = ""


@dataclass
class WIPLimitBreachedEvent(DomainEvent):
	"""Emitted when a card move would breach a column's WIP limit."""
	event_type: str = "ops.lean.wip.breach"
	column_id: str = ""
	column_name: str = ""
	current_cards: int = 0
	wip_limit: int = 0


@dataclass
class PullSignalTriggeredEvent(DomainEvent):
	"""Emitted when a pull signal is created from a CONSUME column card."""
	event_type: str = "ops.lean.pull.triggered"
	card_id: str = ""
	product_id: str = ""
	quantity: str = ""   # Decimal string
	order_id: str = ""   # Fulfillment order created (PO or production order), may be empty


@dataclass
class KanbanCycleTimeRecordedEvent(DomainEvent):
	"""Emitted when cycle-time metrics are computed for a board/period."""
	event_type: str = "ops.lean.cycle_time"
	board_id: str = ""
	period: str = ""               # e.g. "2026-06-01/2026-06-30"
	avg_cycle_time_days: str = ""  # Decimal string


__all__ = [
	"KanbanBoardCreatedEvent",
	"KanbanCardMovedEvent",
	"WIPLimitBreachedEvent",
	"PullSignalTriggeredEvent",
	"KanbanCycleTimeRecordedEvent",
]
