"""
pgappforge/plugins/erp/industry/water/__init__.py

WaterPlugin — Water quality, hydrology and allocation management ERP plugin.

Implements OGC WaterML 2.0 concepts extended with operational governance:
  WaterBody → MonitoringStation → WaterQualityMeasurement / WaterFlowRecord
  FloodWarning (lifecycle: ACTIVE → CANCELLED/EXPIRED)
  WaterAllocation (permit tracking with usage enforcement)

Domain: industry/water
Depends on: foundation
Cross-plugin: emits water.* events; subscribes to agritech irrigation usage
             so farm abstraction volumes post against allocations.

Usage
-----
Add to PGAPPFORGE_PLUGINS::

    "pgappforge.plugins.erp.industry.water"

Or instantiate directly::

    from pgappforge.plugins.erp.industry.water import WaterPlugin
    plugin = WaterPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class WaterPlugin(BasePlugin):
	"""Water Management ERP plugin — hydrology, quality monitoring and allocation."""

	name = "water"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="water",
			version="1.0.0",
			description=(
				"Water Management — water body registry, monitoring station network, "
				"water quality measurements (OGC WaterML 2.0), flow records, "
				"flood warning lifecycle, water allocation permit tracking."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "water", "hydrology", "environmental", "ogc", "waterml", "flood"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_water_body_list",
				"can_water_body_write",
				"can_water_station_list",
				"can_water_station_write",
				"can_water_quality_list",
				"can_water_quality_ingest",
				"can_water_flow_ingest",
				"can_water_flood_list",
				"can_water_flood_issue",
				"can_water_flood_cancel",
				"can_water_allocation_list",
				"can_water_allocation_write",
				"can_water_abstraction_record",
				"can_water_dashboard",
				"can_water_reports",
				"can_water_contamination_scan",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"water.quality.violation",
			"water.contamination.detected",
			"water.flood_warning.issued",
			"water.flood_warning.cancelled",
			"water.allocation.created",
			"water.allocation.exceeded",
			"water.flow.alert",
			"water.station.offline",
		]

	def subscribe_to(self) -> list[str]:
		"""Water plugin consumes:
		- agri.input.applied: IRRIGATION type events may record abstraction against allocation
		- finance.ap.invoice.paid: water utility billing reconciliation
		"""
		return [
			"agri.input.applied",
			"finance.ap.invoice.paid",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"WATER_MENU_CATEGORY": "Water Management",
			"WATER_QUALITY_CHECK_INTERVAL_MINUTES": 15,
			"WATER_FLOOD_ALERT_THRESHOLD_M": 3.0,
			"WATER_ALLOCATION_WARN_PCT": 80,
			"WATER_STATION_OFFLINE_THRESHOLD_HOURS": 2,
			"WATER_CONTAMINATION_VIOLATION_THRESHOLD": 2,
		}
		self.config = {**defaults, **self.config}
		log.info("WaterPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.water.views import (
			WaterBodyView,
			MonitoringView,
			FloodWarningView,
			AllocationView,
			WaterDashboardView,
		)
		cat = self.config.get("WATER_MENU_CATEGORY", "Water Management")
		self.add_view(WaterDashboardView, "Dashboard", icon="fa-tint", category=cat)
		self.add_view(WaterBodyView, "Water Bodies", icon="fa-water", category=cat)
		self.add_view(MonitoringView, "Monitoring Stations", icon="fa-broadcast-tower", category=cat)
		self.add_view(FloodWarningView, "Flood Warnings", icon="fa-exclamation-triangle", category=cat)
		self.add_view(AllocationView, "Water Allocations", icon="fa-certificate", category=cat)
		log.info("WaterPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.water.models import (
			WaterBody,
			MonitoringStation,
			WaterQualityMeasurement,
			WaterFlowRecord,
			FloodWarning,
			WaterAllocation,
		)
		return [
			WaterBody,
			MonitoringStation,
			WaterQualityMeasurement,
			WaterFlowRecord,
			FloodWarning,
			WaterAllocation,
		]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Water Management validation rulesets. Idempotent."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("WaterPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "water.allocation.positive_volume",
				"description": "Allocated volume must be positive",
				"model_name": "WaterAllocation",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_allocation",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "allocated_m3_per_year", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error", "message": "allocated_m3_per_year must be positive"}
						],
					},
				],
			},
			{
				"name": "water.quality.valid_ph_range",
				"description": "pH measurements must be in plausible range (0-14)",
				"model_name": "WaterQualityMeasurement",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_ph_range",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "parameter", "op": "eq", "value": "PH"},
							{"field": "value", "op": "gt", "value": 14},
						],
						"actions_json": [
							{"type": "raise_error", "message": "pH value cannot exceed 14"}
						],
					},
				],
			},
			{
				"name": "water.flood_warning.valid_level",
				"description": "Flood warning level must be a recognised code",
				"model_name": "FloodWarning",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_warning_level",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "warning_level", "op": "not_in",
							 "value": ["ADVISORY", "WATCH", "WARNING", "EMERGENCY"]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "warning_level must be ADVISORY, WATCH, WARNING or EMERGENCY"}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("WaterPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> WaterPlugin:
	return WaterPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.water.models import (  # noqa: E402
	WaterBody,
	MonitoringStation,
	WaterQualityMeasurement,
	WaterFlowRecord,
	FloodWarning,
	WaterAllocation,
)
from pgappforge.plugins.erp.industry.water.events import (  # noqa: E402
	WaterQualityViolationEvent,
	ContaminationDetectedEvent,
	FloodWarningIssuedEvent,
	FloodWarningCancelledEvent,
	WaterAllocationCreatedEvent,
	AllocationExceededEvent,
	FlowAlertEvent,
	StationOfflineEvent,
)
from pgappforge.plugins.erp.industry.water.services import (  # noqa: E402
	WaterService,
	WaterServiceError,
	WaterBodyNotFoundError,
	StationNotFoundError,
	AllocationNotFoundError,
	InvalidWarningLevelError,
)

__all__ = [
	"WaterPlugin",
	"create_plugin",
	# models
	"WaterBody",
	"MonitoringStation",
	"WaterQualityMeasurement",
	"WaterFlowRecord",
	"FloodWarning",
	"WaterAllocation",
	# events
	"WaterQualityViolationEvent",
	"ContaminationDetectedEvent",
	"FloodWarningIssuedEvent",
	"FloodWarningCancelledEvent",
	"WaterAllocationCreatedEvent",
	"AllocationExceededEvent",
	"FlowAlertEvent",
	"StationOfflineEvent",
	# services
	"WaterService",
	"WaterServiceError",
	"WaterBodyNotFoundError",
	"StationNotFoundError",
	"AllocationNotFoundError",
	"InvalidWarningLevelError",
]
