"""
pgappforge/plugins/erp/operations/eam/__init__.py

EAMPlugin — Enterprise Asset Management / CMMS plugin.

Domain: operations
Depends on: foundation

Scope: maintenance lifecycle only.
       Depreciation and book value are handled by the finance/assets plugin.
       ManagedAsset.finance_asset_id is an advisory cross-plugin reference.

Events emitted:
  eam.asset.created
  eam.work_order.created
  eam.work_order.completed
  eam.maintenance_plan.triggered
  eam.safety_permit.issued
  eam.asset.metrics_calculated

Events consumed:
  finance.asset.created   — optionally link ManagedAsset to finance asset record

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.eam",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.eam import EAMPlugin
    plugin = EAMPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EAMPlugin(BasePlugin):
	"""Enterprise Asset Management (EAM / CMMS) plugin.

	Provides:
	  - Asset registry with location hierarchy and finance cross-reference
	  - Meter / odometer readings with automatic plan trigger evaluation
	  - Job plan templates driving preventive work order generation
	  - Calendar and meter-based maintenance scheduling
	  - Corrective and emergency work order management
	  - Safety permit workflow (PTW — Permit to Work)
	  - Reliability KPIs: MTBF, MTTR, availability percentage
	  - Backlog reporting by priority and age bucket
	  - GL double-entry journal on WO completion (DR 6200 / CR 2000)
	"""

	name = "eam"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="eam",
			version="1.0.0",
			description=(
				"Enterprise Asset Management — full maintenance lifecycle: asset registry "
				"with location hierarchy, meter readings, job plan templates, calendar and "
				"meter-triggered preventive maintenance scheduling, corrective and emergency "
				"work orders, safety permit (PTW) workflow, MTBF/MTTR/availability KPIs, "
				"GL expense posting on completion, and backlog reporting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "operations", "eam", "cmms", "maintenance", "assets", "reliability"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_eam_asset_list",
				"can_eam_asset_write",
				"can_eam_asset_decommission",
				"can_eam_location_list",
				"can_eam_location_write",
				"can_eam_meter_reading_create",
				"can_eam_job_plan_list",
				"can_eam_job_plan_write",
				"can_eam_maintenance_plan_list",
				"can_eam_maintenance_plan_write",
				"can_eam_work_order_list",
				"can_eam_work_order_create",
				"can_eam_work_order_approve",
				"can_eam_work_order_complete",
				"can_eam_safety_permit_issue",
				"can_eam_failure_report_create",
				"can_eam_reports",
				"can_eam_schedule_batch",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"eam.asset.created",
			"eam.work_order.created",
			"eam.work_order.completed",
			"eam.maintenance_plan.triggered",
			"eam.safety_permit.issued",
			"eam.asset.metrics_calculated",
		]

	def subscribe_to(self) -> list[str]:
		"""Consume finance/assets events to link depreciation records."""
		return [
			"finance.asset.created",   # populate ManagedAsset.finance_asset_id
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"EAM_MENU_CATEGORY": "Maintenance",
			"EAM_DEFAULT_LEAD_DAYS": 7,
			"EAM_WO_LABOUR_RATE_CENTS_PER_HOUR": 5000,   # $50/hr default estimate
			"EAM_GL_MAINTENANCE_EXPENSE_ACCOUNT": "6200",
			"EAM_GL_AP_ACCOUNT": "2000",
			"EAM_BATCH_SCHEDULE_ENABLED": True,
		}
		self.config = {**defaults, **self.config}
		log.info("EAMPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		# Views are registered lazily to avoid circular imports at module load.
		# Uncomment and implement pgappforge/plugins/erp/operations/eam/views.py
		# when UI layer is added.
		cat = self.config.get("EAM_MENU_CATEGORY", "Maintenance")
		log.info("EAMPlugin: views would be registered under category %r (views.py not yet added)", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.eam.models import (
			AssetLocation,
			FailureReport,
			JobPlan,
			MaintenancePlan,
			MaintenanceWorkOrder,
			ManagedAsset,
			MeterReading,
			SafetyPermit,
			WorkOrderLabor,
			WorkOrderPart,
		)
		return [
			AssetLocation,
			ManagedAsset,
			MeterReading,
			JobPlan,
			MaintenancePlan,
			MaintenanceWorkOrder,
			WorkOrderLabor,
			WorkOrderPart,
			SafetyPermit,
			FailureReport,
		]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> EAMPlugin:
	"""Construct an EAMPlugin without activating it."""
	return EAMPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.eam.models import (  # noqa: E402
	AssetLocation,
	FailureReport,
	JobPlan,
	MaintenancePlan,
	MaintenanceWorkOrder,
	ManagedAsset,
	MeterReading,
	SafetyPermit,
	WorkOrderLabor,
	WorkOrderPart,
)
from pgappforge.plugins.erp.operations.eam.events import (  # noqa: E402
	AssetCreatedEvent,
	AssetMetricsCalculatedEvent,
	MaintenancePlanTriggeredEvent,
	SafetyPermitIssuedEvent,
	WorkOrderCompletedEvent,
	WorkOrderCreatedEvent,
)
from pgappforge.plugins.erp.operations.eam.services import (  # noqa: E402
	EAMService,
	EAMServiceError,
	AssetNotFoundError,
	WorkOrderNotFoundError,
	MaintenancePlanNotFoundError,
	InvalidStatusTransitionError,
	SafetyPermitRequiredError,
)

__all__ = [
	# plugin
	"EAMPlugin",
	"create_plugin",
	# models
	"AssetLocation",
	"ManagedAsset",
	"MeterReading",
	"JobPlan",
	"MaintenancePlan",
	"MaintenanceWorkOrder",
	"WorkOrderLabor",
	"WorkOrderPart",
	"SafetyPermit",
	"FailureReport",
	# events
	"AssetCreatedEvent",
	"AssetMetricsCalculatedEvent",
	"WorkOrderCreatedEvent",
	"WorkOrderCompletedEvent",
	"MaintenancePlanTriggeredEvent",
	"SafetyPermitIssuedEvent",
	# services
	"EAMService",
	"EAMServiceError",
	"AssetNotFoundError",
	"WorkOrderNotFoundError",
	"MaintenancePlanNotFoundError",
	"InvalidStatusTransitionError",
	"SafetyPermitRequiredError",
]
