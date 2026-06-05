"""
pgappforge/plugins/erp/industry/manufacturing/__init__.py

Manufacturing Cloud plugin — production planning, MES, maintenance, OEE, sustainability.

Domain: industry
Depends on: foundation, inventory, quality

Events emitted:
  manufacturing.order.released
  manufacturing.order.completed
  manufacturing.oee.calculated
  manufacturing.maintenance.triggered

Subscribed events:
  inventory.stock.low
  quality.inspection.failed

Usage
-----
Add to PGAPPFORGE_PLUGINS::

    "pgappforge.plugins.erp.industry.manufacturing"

Or instantiate directly::

    from pgappforge.plugins.erp.industry.manufacturing import ManufacturingPlugin
    plugin = ManufacturingPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ManufacturingPlugin(BasePlugin):
	"""Manufacturing Cloud ERP plugin.

	Registers 5 view groups covering:
	  - Manufacturing Orders lifecycle (DRAFT → RELEASED → COMPLETED)
	  - Work Center management
	  - OEE dashboard (availability × performance × quality)
	  - Maintenance work orders (corrective, preventive, predictive)
	  - Production schedule (Gantt-style capacity view)
	"""

	name = "manufacturing"
	domain = "industry"
	depends_on: list[str] = ["foundation", "inventory", "quality"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="manufacturing",
			version="1.0.0",
			description=(
				"Manufacturing Cloud — production orders, MES, work centers, "
				"OEE analytics, maintenance work orders, MRP, sustainability."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "manufacturing", "oee", "maintenance", "mrp", "mes"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_mfg_order_list",
				"can_mfg_order_write",
				"can_mfg_order_release",
				"can_mfg_order_complete",
				"can_mfg_work_center_list",
				"can_mfg_work_center_write",
				"can_mfg_oee_view",
				"can_mfg_maintenance_list",
				"can_mfg_maintenance_write",
				"can_mfg_schedule_view",
				"can_mfg_mrp_run",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"manufacturing.order.released",
			"manufacturing.order.completed",
			"manufacturing.oee.calculated",
			"manufacturing.maintenance.triggered",
		]

	def subscribe_to(self) -> list[str]:
		"""MFG consumes:
		- inventory.stock.low:          may block MO release on critical shortage
		- quality.inspection.failed:    may trigger rework or scrap on MO
		"""
		return [
			"inventory.stock.low",
			"quality.inspection.failed",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"MFG_MENU_CATEGORY": "Manufacturing",
			"MFG_BLOCK_RELEASE_ON_SHORTAGE": False,
			"MFG_OEE_WORLD_CLASS_THRESHOLD": "0.8500",
			"MFG_DEFAULT_SHIFT_MINUTES": 480,
		}
		self.config = {**defaults, **self.config}
		log.info("ManufacturingPlugin initialised (config: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.manufacturing.views import (
			ManufacturingOrderView,
			WorkCenterView,
			OEEDashboardView,
			MaintenanceWorkView,
			ProductionScheduleView,
		)
		cat = self.config.get("MFG_MENU_CATEGORY", "Manufacturing")
		self.add_view(ManufacturingOrderView, "Manufacturing Orders", icon="fa-cogs", category=cat)
		self.add_view(WorkCenterView, "Work Centers", icon="fa-industry", category=cat)
		self.add_view(OEEDashboardView, "OEE Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(MaintenanceWorkView, "Maintenance Work Orders", icon="fa-wrench", category=cat)
		self.add_view(ProductionScheduleView, "Production Schedule", icon="fa-calendar", category=cat)
		log.info("ManufacturingPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.manufacturing.models import (
			ManufacturingOrder,
			ProductionSchedule,
			MaintenanceWork,
			AssetSensor,
			OEESnapshot,
		)
		return [
			ManufacturingOrder,
			ProductionSchedule,
			MaintenanceWork,
			AssetSensor,
			OEESnapshot,
		]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> ManufacturingPlugin:
	return ManufacturingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.manufacturing.models import (  # noqa: E402
	ManufacturingOrder,
	ProductionSchedule,
	MaintenanceWork,
	AssetSensor,
	OEESnapshot,
)
from pgappforge.plugins.erp.industry.manufacturing.events import (  # noqa: E402
	ManufacturingOrderReleasedEvent,
	ManufacturingOrderCompletedEvent,
	OEESnapshotCreatedEvent,
	AssetAnomalyDetectedEvent,
	MaintenanceWorkOrderRaisedEvent,
)
from pgappforge.plugins.erp.industry.manufacturing.services import (  # noqa: E402
	ManufacturingService,
	ManufacturingServiceError,
	ManufacturingOrderNotFoundError,
	InvalidStatusTransitionError,
	BOMValidationError,
)

__all__ = [
	"ManufacturingPlugin",
	"create_plugin",
	# models
	"ManufacturingOrder",
	"ProductionSchedule",
	"MaintenanceWork",
	"AssetSensor",
	"OEESnapshot",
	# events
	"ManufacturingOrderReleasedEvent",
	"ManufacturingOrderCompletedEvent",
	"OEESnapshotCreatedEvent",
	"AssetAnomalyDetectedEvent",
	"MaintenanceWorkOrderRaisedEvent",
	# services
	"ManufacturingService",
	"ManufacturingServiceError",
	"ManufacturingOrderNotFoundError",
	"InvalidStatusTransitionError",
	"BOMValidationError",
]
