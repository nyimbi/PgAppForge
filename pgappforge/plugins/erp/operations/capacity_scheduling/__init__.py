"""
pgappforge/plugins/erp/operations/capacity_scheduling/__init__.py

CapacitySchedulingPlugin — Finite capacity scheduling for production work centers.

Domain: operations
Depends on: foundation

Full lifecycle:
  WorkCenter           — production resource with daily capacity + calendar
  CapacityLoad         — daily load accumulator per work center
  ProductionSchedule   — booked production slot (PLANNED → CONFIRMED → COMPLETED)

  schedule_order()         → backward finite-capacity scheduling
  run_capacity_leveling()  → EDD-based load leveling across a date range
  get_load_report()        → utilization report with overload/underload flags
  detect_bottleneck()      → top-3 bottleneck work centers by avg utilization

Events emitted:
  ops.capacity.scheduled
  ops.capacity.overload
  ops.capacity.leveled
  ops.capacity.bottleneck

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.capacity_scheduling",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.capacity_scheduling import CapacitySchedulingPlugin
    plugin = CapacitySchedulingPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class CapacitySchedulingPlugin(BasePlugin):
	"""Finite Capacity Scheduling ERP plugin.

	Provides work center management, backward scheduling, capacity leveling,
	load reporting, and bottleneck detection for production planning.
	"""

	name = "capacity_scheduling"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="capacity_scheduling",
			version="1.0.0",
			description=(
				"Finite Capacity Scheduling — work center management, backward scheduling, "
				"EDD-based capacity leveling, load reporting, and bottleneck detection."
			),
			author="PgAppForge Contributors",
			tags=[
				"operations", "manufacturing", "capacity", "scheduling",
				"finite-capacity", "bottleneck",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_csc_work_center_list",
				"can_csc_work_center_create",
				"can_csc_schedule_order",
				"can_csc_capacity_level",
				"can_csc_load_report",
				"can_csc_bottleneck_report",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.capacity.scheduled",
			"ops.capacity.overload",
			"ops.capacity.leveled",
			"ops.capacity.bottleneck",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CSC_MENU_CATEGORY": "Capacity Planning",
			"CSC_DEFAULT_WORK_DAY_HOURS": 8.0,
			"CSC_MAX_SCHEDULING_HORIZON_DAYS": 90,
			"CSC_OVERLOAD_THRESHOLD_PCT": 100.0,
			"CSC_BOTTLENECK_THRESHOLD_PCT": 80.0,
		}
		self.config = {**defaults, **self.config}
		log.info("CapacitySchedulingPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.operations.capacity_scheduling.views import (
			CapacityGanttView,
			WorkCenterView,
			CapacityLoadView,
			ProductionScheduleView,
		)
		cat = self.config.get("CSC_MENU_CATEGORY", "Capacity Planning")
		self.add_view(CapacityGanttView, "Capacity Gantt", icon="fa-tachometer", category=cat)
		self.add_view(WorkCenterView, "Work Centers", icon="fa-industry", category=cat)
		self.add_view(CapacityLoadView, "Capacity Loads", icon="fa-bar-chart", category=cat)
		self.add_view(ProductionScheduleView, "Production Schedules", icon="fa-calendar", category=cat)
		log.info("CapacitySchedulingPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.capacity_scheduling.models import (
			WorkCenter,
			CapacityLoad,
			ProductionSchedule,
		)
		return [WorkCenter, CapacityLoad, ProductionSchedule]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> CapacitySchedulingPlugin:
	"""Construct a CapacitySchedulingPlugin without activating it."""
	return CapacitySchedulingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.capacity_scheduling.models import (  # noqa: E402
	WorkCenter,
	CapacityLoad,
	ProductionSchedule,
)
from pgappforge.plugins.erp.operations.capacity_scheduling.events import (  # noqa: E402
	ProductionScheduledEvent,
	CapacityOverloadDetectedEvent,
	ScheduleLeveledEvent,
	BottleneckDetectedEvent,
)
from pgappforge.plugins.erp.operations.capacity_scheduling.services import (  # noqa: E402
	CapacityScheduler,
	CapacitySchedulingError,
	WorkCenterNotFoundError,
	ScheduleNotFoundError,
	InsufficientCapacityError,
)

__all__ = [
	# plugin
	"CapacitySchedulingPlugin",
	"create_plugin",
	# models
	"WorkCenter",
	"CapacityLoad",
	"ProductionSchedule",
	# events
	"ProductionScheduledEvent",
	"CapacityOverloadDetectedEvent",
	"ScheduleLeveledEvent",
	"BottleneckDetectedEvent",
	# services
	"CapacityScheduler",
	"CapacitySchedulingError",
	"WorkCenterNotFoundError",
	"ScheduleNotFoundError",
	"InsufficientCapacityError",
]
