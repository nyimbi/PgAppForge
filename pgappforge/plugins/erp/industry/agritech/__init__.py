"""
pgappforge/plugins/erp/industry/agritech/__init__.py

AgriTechPlugin — Precision farming and agronomy ERP plugin.

Full agricultural management lifecycle:
  Farm → Field → Crop → PlantingActivity → InputApplication →
  FieldObservation → HarvestRecord + WeatherRecord

Domain: industry/agritech
Depends on: foundation
Cross-plugin: emits agri.* events; subscribes to weather alerts and
              financial events from finance/ap for input purchase costs.

Usage
-----
Add to PGAPPFORGE_PLUGINS::

    "pgappforge.plugins.erp.industry.agritech"

Or instantiate directly::

    from pgappforge.plugins.erp.industry.agritech import AgriTechPlugin
    plugin = AgriTechPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AgriTechPlugin(BasePlugin):
	"""AgriTech ERP plugin — precision farming and agronomy management."""

	name = "agritech"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="agritech",
			version="1.0.0",
			description=(
				"AgriTech — farm registration, field mapping, crop planting, "
				"input applications, field observations, harvest recording, "
				"weather ingestion and agronomic dashboards."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "agriculture", "farming", "agritech", "precision-ag", "iot"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_agri_farm_list",
				"can_agri_farm_write",
				"can_agri_field_list",
				"can_agri_field_write",
				"can_agri_crop_list",
				"can_agri_crop_write",
				"can_agri_planting_list",
				"can_agri_planting_write",
				"can_agri_planting_advance",
				"can_agri_observation_list",
				"can_agri_observation_write",
				"can_agri_observation_critical",
				"can_agri_weather_list",
				"can_agri_weather_ingest",
				"can_agri_harvest_list",
				"can_agri_harvest_write",
				"can_agri_input_list",
				"can_agri_input_write",
				"can_agri_dashboard",
				"can_agri_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"agri.farm.created",
			"agri.planting.created",
			"agri.planting.status_changed",
			"agri.observation.created",
			"agri.observation.critical",
			"agri.harvest.recorded",
			"agri.input.applied",
			"agri.weather.alert",
		]

	def subscribe_to(self) -> list[str]:
		"""AgriTech consumes:
		- finance.ap.invoice.paid: may update input purchase cost tracking
		- water.flood_warning.issued: irrigation planning alert
		"""
		return [
			"finance.ap.invoice.paid",
			"water.flood_warning.issued",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"AGRI_MENU_CATEGORY": "AgriTech",
			"AGRI_DEFAULT_CURRENCY": "USD",
			"AGRI_WEATHER_ALERT_FROST_THRESHOLD_C": 2.0,
			"AGRI_WEATHER_ALERT_STORM_WIND_KMH": 80.0,
			"AGRI_CRITICAL_OBS_NOTIFY": True,
		}
		self.config = {**defaults, **self.config}
		log.info("AgriTechPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.agritech.views import (
			FarmView,
			FieldView,
			ObservationView,
			WeatherDashboardView,
			FarmDashboardView,
			PlantingView,
		)
		cat = self.config.get("AGRI_MENU_CATEGORY", "AgriTech")
		self.add_view(FarmDashboardView, "Farm Dashboard", icon="fa-tractor", category=cat)
		self.add_view(FarmView, "Farms", icon="fa-map-marker", category=cat)
		self.add_view(FieldView, "Fields", icon="fa-leaf", category=cat)
		self.add_view(PlantingView, "Planting Activities", icon="fa-seedling", category=cat)
		self.add_view(ObservationView, "Field Observations", icon="fa-eye", category=cat)
		self.add_view(WeatherDashboardView, "Weather", icon="fa-cloud", category=cat)
		log.info("AgriTechPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.agritech.models import (
			Crop,
			Farm,
			Field,
			PlantingActivity,
			FieldObservation,
			WeatherRecord,
			InputApplication,
			HarvestRecord,
		)
		return [
			Crop,
			Farm,
			Field,
			PlantingActivity,
			FieldObservation,
			WeatherRecord,
			InputApplication,
			HarvestRecord,
		]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure AgriTech validation rulesets. Idempotent."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("AgriTechPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "agri.planting.positive_seed_quantity",
				"description": "Seed quantity must be positive when provided",
				"model_name": "PlantingActivity",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_seed_qty",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "seed_quantity_kg", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error", "message": "seed_quantity_kg must be positive"}
						],
					},
				],
			},
			{
				"name": "agri.harvest.positive_quantity",
				"description": "Harvest quantity must be positive",
				"model_name": "HarvestRecord",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_harvest_qty",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "quantity_kg", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error", "message": "quantity_kg must be positive"}
						],
					},
				],
			},
			{
				"name": "agri.input.positive_quantity",
				"description": "Input application quantity must be positive",
				"model_name": "InputApplication",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_input_qty",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "quantity", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error", "message": "Input application quantity must be positive"}
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
		log.info("AgriTechPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> AgriTechPlugin:
	return AgriTechPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.agritech.models import (  # noqa: E402
	Crop,
	Farm,
	Field,
	PlantingActivity,
	FieldObservation,
	WeatherRecord,
	InputApplication,
	HarvestRecord,
)
from pgappforge.plugins.erp.industry.agritech.events import (  # noqa: E402
	FarmCreatedEvent,
	PlantingCreatedEvent,
	PlantingStatusChangedEvent,
	FieldObservationCreatedEvent,
	CriticalObservationEvent,
	HarvestRecordedEvent,
	InputAppliedEvent,
	WeatherAlertEvent,
)
from pgappforge.plugins.erp.industry.agritech.services import (  # noqa: E402
	AgriTechService,
	AgriServiceError,
	FarmNotFoundError,
	FieldNotFoundError,
	PlantingNotFoundError,
	InvalidStatusTransitionError,
)

__all__ = [
	"AgriTechPlugin",
	"create_plugin",
	# models
	"Crop",
	"Farm",
	"Field",
	"PlantingActivity",
	"FieldObservation",
	"WeatherRecord",
	"InputApplication",
	"HarvestRecord",
	# events
	"FarmCreatedEvent",
	"PlantingCreatedEvent",
	"PlantingStatusChangedEvent",
	"FieldObservationCreatedEvent",
	"CriticalObservationEvent",
	"HarvestRecordedEvent",
	"InputAppliedEvent",
	"WeatherAlertEvent",
	# services
	"AgriTechService",
	"AgriServiceError",
	"FarmNotFoundError",
	"FieldNotFoundError",
	"PlantingNotFoundError",
	"InvalidStatusTransitionError",
]
