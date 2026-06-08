"""
pgappforge/plugins/erp/operations/lean/__init__.py

LeanManufacturingPlugin — Lean / Kanban pull-system manufacturing plugin.

Domain: operations
Depends on: foundation

Full lifecycle:
  KanbanBoard   — value-stream board with named columns
  KanbanColumn  — stage with optional WIP limit and type (BACKLOG/WORK/REVIEW/DONE/CONSUME)
  KanbanCard    — work item with cycle-time tracking and pull-signal capability
  PullSignal    — replenishment order triggered when product card enters CONSUME column

  create_board()         → board + default columns (or custom)
  add_card()             → add work item to a column
  move_card()            → move card with WIP enforcement and cycle-time tracking
  trigger_pull_signal()  → create PullSignal + best-effort MRP/SCM fulfillment
  get_cycle_time()       → avg/min/max cycle time for a board/period
  get_flow_efficiency()  → touch-time / total-time ratio
  get_board_metrics()    → snapshot dashboard: cards/column, violations, age, throughput

Events emitted:
  ops.lean.board.created
  ops.lean.card.moved
  ops.lean.wip.breach
  ops.lean.pull.triggered
  ops.lean.cycle_time

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.lean",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.lean import LeanManufacturingPlugin
    plugin = LeanManufacturingPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class LeanManufacturingPlugin(BasePlugin):
	"""Lean / Kanban Manufacturing ERP plugin.

	Provides Kanban board management, WIP-limited pull-flow execution,
	cycle-time analytics, flow efficiency, and pull-signal replenishment
	integration with MRP and SCM plugins.

	Integrates with:
	  - MRP plugin (create_planned_order) for production pull signals
	  - SCM plugin (create_purchase_order) for procurement pull signals
	"""

	name = "lean"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="lean",
			version="1.0.0",
			description=(
				"Lean / Kanban Manufacturing — Kanban board management, WIP limit enforcement, "
				"pull-signal replenishment, cycle-time analytics, and flow efficiency metrics "
				"following Toyota Production System principles."
			),
			author="PgAppForge Contributors",
			tags=[
				"operations", "lean", "kanban", "wip", "pull",
				"flow-efficiency", "toyota",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_kbn_board_list",
				"can_kbn_board_create",
				"can_kbn_card_create",
				"can_kbn_card_move",
				"can_kbn_pull_signal_list",
				"can_kbn_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.lean.board.created",
			"ops.lean.card.moved",
			"ops.lean.wip.breach",
			"ops.lean.pull.triggered",
			"ops.lean.cycle_time",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"KBN_MENU_CATEGORY": "Lean / Kanban",
			"KBN_DEFAULT_WIP_WORK": 5,
			"KBN_DEFAULT_WIP_REVIEW": 3,
			"KBN_CYCLE_TIME_UNIT": "days",
		}
		self.config = {**defaults, **self.config}
		log.info("LeanManufacturingPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.operations.lean.views import KanbanBoardView
		cat = self.config.get("KBN_MENU_CATEGORY", "Lean / Kanban")
		self.add_view(KanbanBoardView, "Kanban Boards", icon="fa-columns", category=cat)
		log.info("LeanManufacturingPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.lean.models import (
			KanbanBoard,
			KanbanColumn,
			KanbanCard,
			PullSignal,
		)
		return [KanbanBoard, KanbanColumn, KanbanCard, PullSignal]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> LeanManufacturingPlugin:
	"""Construct a LeanManufacturingPlugin without activating it."""
	return LeanManufacturingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.lean.models import (  # noqa: E402
	KanbanBoard,
	KanbanColumn,
	KanbanCard,
	PullSignal,
)
from pgappforge.plugins.erp.operations.lean.events import (  # noqa: E402
	KanbanBoardCreatedEvent,
	KanbanCardMovedEvent,
	WIPLimitBreachedEvent,
	PullSignalTriggeredEvent,
	KanbanCycleTimeRecordedEvent,
)
from pgappforge.plugins.erp.operations.lean.services import (  # noqa: E402
	LeanManufacturingService,
	LeanServiceError,
	BoardNotFoundError,
	ColumnNotFoundError,
	CardNotFoundError,
	WIPLimitError,
)

__all__ = [
	# plugin
	"LeanManufacturingPlugin",
	"create_plugin",
	# models
	"KanbanBoard",
	"KanbanColumn",
	"KanbanCard",
	"PullSignal",
	# events
	"KanbanBoardCreatedEvent",
	"KanbanCardMovedEvent",
	"WIPLimitBreachedEvent",
	"PullSignalTriggeredEvent",
	"KanbanCycleTimeRecordedEvent",
	# services
	"LeanManufacturingService",
	"LeanServiceError",
	"BoardNotFoundError",
	"ColumnNotFoundError",
	"CardNotFoundError",
	"WIPLimitError",
]
