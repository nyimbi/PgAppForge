"""
pgappforge/plugins/erp/industry/utilities/__init__.py

Utilities / Smart Grid plugin — IEC CIM + Green Button AMI.

Covers: grid asset topology (IEC 61968/61970 CIM), AMI meter data ingestion
(Green Button ESPI), outage event management (OMS), reliability indices
(SAIDI/SAIFI/CAIDI), demand response, and load forecasting.

Events emitted:
  utilities.ami.data_ingested
  utilities.outage.detected / restored
  utilities.demand_response.dispatched / completed
  utilities.reliability.indices_calculated

Events consumed:
  party.created         — register utility customers
  foundation.asset.decommissioned — set grid asset OUT_OF_SERVICE

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.industry.utilities"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class UtilitiesPlugin(BasePlugin):
	"""Utilities / Smart Grid plugin — IEC CIM, AMI, OMS, DR, reliability."""

	name = "industry.utilities"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="industry.utilities",
			version="1.0.0",
			description=(
				"Utilities / Smart Grid — IEC CIM grid topology (IEC 61968/61970), "
				"AMI meter data (Green Button ESPI), outage management (SAIDI/SAIFI/CAIDI), "
				"demand response, and probabilistic load forecasting."
			),
			author="PgAppForge Contributors",
			tags=[
				"utilities", "smart-grid", "iec-cim", "ami", "green-button",
				"outage", "saidi", "demand-response", "energy",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_utilities_grid_read",
				"can_utilities_grid_write",
				"can_utilities_meters_read",
				"can_utilities_meters_write",
				"can_utilities_ami_ingest",
				"can_utilities_outages_read",
				"can_utilities_outages_write",
				"can_utilities_dr_read",
				"can_utilities_dr_dispatch",
				"can_utilities_reliability_read",
				"can_utilities_greenbutton_export",
				"can_utilities_forecast_read",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"utilities.ami.data_ingested",
			"utilities.outage.detected",
			"utilities.outage.restored",
			"utilities.demand_response.dispatched",
			"utilities.demand_response.completed",
			"utilities.reliability.indices_calculated",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"party.created",
			"foundation.asset.decommissioned",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"UTILITIES_MENU_CATEGORY": "Utilities",
			"UTILITIES_DEFAULT_FORECAST_HOURS": 24,
			"UTILITIES_RELIABILITY_CUSTOMERS": 1,
			"UTILITIES_GREEN_BUTTON_BASE_URL": "/utilities/greenbutton",
		}
		self.config = {**defaults, **self.config}
		log.info("UtilitiesPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.utilities.views import (
			GridView,
			MeterView,
			OutageView,
			LoadForecastView,
			DemandResponseView,
			ReliabilityView,
			GreenButtonView,
		)
		cat = self.config.get("UTILITIES_MENU_CATEGORY", "Utilities")
		self.add_view(GridView, "Grid Assets", icon="fa-bolt", category=cat)
		self.add_view(MeterView, "Meters", icon="fa-tachometer", category=cat)
		self.add_view(OutageView, "Outages", icon="fa-exclamation-triangle", category=cat)
		self.add_view(DemandResponseView, "Demand Response", icon="fa-sliders", category=cat)
		self.add_view(ReliabilityView, "Reliability Indices", icon="fa-bar-chart", category=cat)
		self.add_view(LoadForecastView, "Load Forecast", icon="fa-line-chart", category=cat)
		self.add_view_no_menu(GreenButtonView)
		log.info("UtilitiesPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.industry.utilities.models import (
			GridAsset,
			GridTopology,
			EnergyMeter,
			IntervalData,
			OutageEvent,
			DemandResponseEvent,
		)
		return [
			GridAsset,
			GridTopology,
			EnergyMeter,
			IntervalData,
			OutageEvent,
			DemandResponseEvent,
		]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure validation rulesets for the Utilities domain."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "util.grid_asset.type_valid",
				"description": (
					"asset_type must be SUBSTATION|TRANSFORMER|LINE|SWITCH|METER|GENERATOR"
				),
				"model_name": "GridAsset",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_asset_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "asset_type",
								"op": "not_in",
								"value": [
									"SUBSTATION", "TRANSFORMER", "LINE",
									"SWITCH", "METER", "GENERATOR",
								],
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"asset_type must be SUBSTATION, TRANSFORMER, LINE, "
									"SWITCH, METER, or GENERATOR"
								),
							}
						],
					}
				],
			},
			{
				"name": "util.outage.type_valid",
				"description": "outage_type must be PLANNED|UNPLANNED|EMERGENCY",
				"model_name": "OutageEvent",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_outage_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "outage_type",
								"op": "not_in",
								"value": ["PLANNED", "UNPLANNED", "EMERGENCY"],
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "outage_type must be PLANNED, UNPLANNED, or EMERGENCY",
							}
						],
					}
				],
			},
			{
				"name": "util.interval_data.positive_consumption",
				"description": "consumption_kwh must be >= 0",
				"model_name": "IntervalData",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_consumption_positive",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "consumption_kwh",
								"op": "lt",
								"value": 0,
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "consumption_kwh must be >= 0",
							}
						],
					}
				],
			},
			{
				"name": "util.interval_data.interval_ordering",
				"description": "interval_end must be after interval_start",
				"model_name": "IntervalData",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_interval_ordering",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "interval_end",
								"op": "lte",
								"value": "{{interval_start}}",
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "interval_end must be after interval_start",
							}
						],
					}
				],
			},
			{
				"name": "util.demand_response.positive_target",
				"description": "target_reduction_kw must be > 0",
				"model_name": "DemandResponseEvent",
				"stop_on_match": True,
				"rules": [
					{
						"name": "validate_dr_target",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "target_reduction_kw",
								"op": "lte",
								"value": 0,
							}
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "target_reduction_kw must be > 0",
							}
						],
					}
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
		log.info(
			"UtilitiesPlugin.setup_rules: %d rulesets configured",
			len(RULESETS),
		)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> UtilitiesPlugin:
	return UtilitiesPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.industry.utilities.models import (  # noqa: E402
	GridAsset,
	GridTopology,
	EnergyMeter,
	IntervalData,
	OutageEvent,
	DemandResponseEvent,
)
from pgappforge.plugins.erp.industry.utilities.services import (  # noqa: E402
	UtilitiesService,
	UtilitiesServiceError,
	MeterNotFoundError,
	OutageNotFoundError,
	InvalidIntervalError,
)

__all__ = [
	"UtilitiesPlugin",
	"create_plugin",
	# models
	"GridAsset",
	"GridTopology",
	"EnergyMeter",
	"IntervalData",
	"OutageEvent",
	"DemandResponseEvent",
	# service
	"UtilitiesService",
	"UtilitiesServiceError",
	"MeterNotFoundError",
	"OutageNotFoundError",
	"InvalidIntervalError",
]
