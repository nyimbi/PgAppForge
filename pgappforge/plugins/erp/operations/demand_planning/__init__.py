"""
pgappforge/plugins/erp/operations/demand_planning/__init__.py

DemandPlanningPlugin — statistical demand forecasting ERP plugin.

Actual demand history → statistical forecast (MA / ES / Holt-Winters) →
forecast approval workflow → accuracy KPI computation.

Domain: operations
Depends on: foundation
Cross-plugin:
  Emits: ops.demand_planning.forecast.*, ops.demand_planning.consensus.*,
         ops.demand_planning.accuracy.*
  Consumed by: ops.mrp (get_approved_forecast for net requirements)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.demand_planning",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class DemandPlanningPlugin(BasePlugin):
	"""Demand Planning ERP plugin.

	Registers 2 view groups and 1 report endpoint.
	Pre-configures 2 Rules Engine rulesets on first run.
	"""

	name = "demand_planning"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="demand_planning",
			version="1.0.0",
			description=(
				"Demand Planning — actual demand history recording, statistical "
				"forecast generation (Moving Average, Exponential Smoothing, "
				"Holt-Winters additive with monthly seasonality), planner approval "
				"workflow, consensus planning support, and MAPE/Bias accuracy KPIs. "
				"Pure Decimal arithmetic — no numpy/scipy dependency."
			),
			author="PgAppForge Contributors",
			tags=["ops", "demand-planning", "forecasting", "scm", "supply-chain"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_dp_forecast_list",
				"can_dp_forecast_create",
				"can_dp_forecast_approve",
				"can_dp_history_list",
				"can_dp_history_write",
				"can_dp_accuracy_view",
				"can_dp_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.demand_planning.forecast.created",
			"ops.demand_planning.forecast.approved",
			"ops.demand_planning.consensus.reached",
			"ops.demand_planning.accuracy.computed",
		]

	def subscribe_to(self) -> list[str]:
		"""Demand Planning consumes:
		- so.line.shipped: actual demand actuals from sales
		- so.line.cancelled: adjust demand downward
		"""
		return [
			"so.line.shipped",
			"so.line.cancelled",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"DP_MENU_CATEGORY": "Supply Chain",
			"DP_DEFAULT_HORIZON_PERIODS": 12,
			"DP_DEFAULT_LOOKBACK_PERIODS": 6,
			"DP_DEFAULT_METHOD": "MOVING_AVERAGE",
		}
		self.config = {**defaults, **self.config}
		log.info("DemandPlanningPlugin initialised (config: %s)", list(self.config))

	def register_views(self) -> None:
		cat = self.config.get("DP_MENU_CATEGORY", "Supply Chain")
		log.info("DemandPlanningPlugin: views would be registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.demand_planning.models import (
			DemandForecast,
			DemandHistory,
		)
		return [DemandHistory, DemandForecast]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 2 Rules Engine rulesets for demand planning domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("DemandPlanningPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "dp.history.non_negative_actual",
				"description": "DemandHistory actual_qty must be non-negative",
				"model_name": "DemandHistory",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_non_negative_actual_qty",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "actual_qty", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "actual_qty must be >= 0",
							}
						],
					},
				],
			},
			{
				"name": "dp.forecast.positive_horizon",
				"description": "DemandForecast horizon_periods must be positive",
				"model_name": "DemandForecast",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_horizon",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "horizon_periods", "op": "lte", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "horizon_periods must be positive",
							}
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
		log.info("DemandPlanningPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> DemandPlanningPlugin:
	return DemandPlanningPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.demand_planning.models import (  # noqa: E402
	DemandForecast,
	DemandHistory,
)
from pgappforge.plugins.erp.operations.demand_planning.events import (  # noqa: E402
	ForecastCreatedEvent,
	ForecastApprovedEvent,
	ConsensusReachedEvent,
	ForecastAccuracyComputedEvent,
)
from pgappforge.plugins.erp.operations.demand_planning.services import (  # noqa: E402
	DemandPlanningService,
	DemandPlanningError,
	ForecastNotFoundError,
	InsufficientHistoryError,
	InvalidForecastStatusError,
)

__all__ = [
	"DemandPlanningPlugin",
	"create_plugin",
	# models
	"DemandForecast",
	"DemandHistory",
	# events
	"ForecastCreatedEvent",
	"ForecastApprovedEvent",
	"ConsensusReachedEvent",
	"ForecastAccuracyComputedEvent",
	# services
	"DemandPlanningService",
	"DemandPlanningError",
	"ForecastNotFoundError",
	"InsufficientHistoryError",
	"InvalidForecastStatusError",
]
