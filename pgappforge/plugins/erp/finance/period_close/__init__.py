"""
pgappforge/plugins/erp/finance/period_close/__init__.py

PeriodClosePlugin — month-end / period-close checklist for Finance.

Events emitted
--------------
  finance.period_close.started          — close run kicked off
  finance.period_close.task.completed   — task marked complete
  finance.period_close.task.skipped     — non-mandatory task skipped
  finance.period_close.finalized        — period sealed CLOSED
  finance.period_close.blocked          — finalize blocked by outstanding tasks

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.period_close",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.period_close import PeriodClosePlugin
    plugin = PeriodClosePlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PeriodClosePlugin(BasePlugin):
	"""Month-end / period-close checklist plugin.

	Provides a 12-task default template covering AR, AP, bank, inventory,
	accruals, prepayments, depreciation, payroll, intercompany elimination,
	revenue recognition, tax accrual, and CFO trial-balance sign-off.

	Class-level attributes for dependency resolution:
	    name       = "period_close"
	    domain     = "finance"
	    depends_on = ["foundation"]
	"""

	name = "period_close"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="period_close",
			version="1.0.0",
			description=(
				"Period Close Checklist — structured month-end / period-close workflow "
				"with 12-task default template, dependency-aware task advancement, "
				"mandatory-task gating, and CFO sign-off before period seal."
			),
			author="PgAppForge Contributors",
			tags=["finance", "period-close", "month-end", "closing-checklist"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_period_close_list",
				"can_period_close_start",
				"can_period_close_task_complete",
				"can_period_close_task_skip",
				"can_period_close_finalize",
				"can_period_close_template_manage",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"finance.period_close.started",
			"finance.period_close.task.completed",
			"finance.period_close.task.skipped",
			"finance.period_close.finalized",
			"finance.period_close.blocked",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"PERIOD_CLOSE_MENU_CATEGORY": "Period Close",
			"PERIOD_CLOSE_SESSION_TTL_HOURS": 8,
		}
		self.config = {**defaults, **self.config}
		log.info("PeriodClosePlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.period_close.models import (
			PeriodClose,
			PeriodCloseTask,
			PeriodCloseTemplate,
		)
		return [PeriodCloseTemplate, PeriodClose, PeriodCloseTask]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> PeriodClosePlugin:
	"""Construct and return a PeriodClosePlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return PeriodClosePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.period_close.models import (  # noqa: E402
	PeriodClose,
	PeriodCloseTask,
	PeriodCloseTemplate,
)
from pgappforge.plugins.erp.finance.period_close.events import (  # noqa: E402
	PeriodCloseBlockedEvent,
	PeriodCloseFinalizedEvent,
	PeriodCloseStartedEvent,
	PeriodCloseTaskCompletedEvent,
	PeriodCloseTaskSkippedEvent,
)
from pgappforge.plugins.erp.finance.period_close.services import (  # noqa: E402
	PeriodCloseError,
	PeriodCloseNotFoundError,
	PeriodCloseService,
	PeriodCloseTaskNotFoundError,
	PeriodCloseValidationError,
)

__all__ = [
	# plugin
	"PeriodClosePlugin",
	"create_plugin",
	# models
	"PeriodCloseTemplate",
	"PeriodClose",
	"PeriodCloseTask",
	# events
	"PeriodCloseStartedEvent",
	"PeriodCloseTaskCompletedEvent",
	"PeriodCloseTaskSkippedEvent",
	"PeriodCloseFinalizedEvent",
	"PeriodCloseBlockedEvent",
	# services
	"PeriodCloseService",
	"PeriodCloseError",
	"PeriodCloseNotFoundError",
	"PeriodCloseTaskNotFoundError",
	"PeriodCloseValidationError",
]
