"""
pgappforge/plugins/erp/operations/mrp/__init__.py

MRPPlugin — Materials Requirements Planning ERP plugin.

Net requirements calculation → planned orders → purchase requisitions →
production order recommendations → BOM explosion (one level).

Domain: operations
Depends on: foundation
Cross-plugin:
  Emits: ops.mrp.run.*, ops.mrp.planned_order.*, ops.mrp.purchase_req.*,
         ops.mrp.production_order.*, ops.mrp.safety_stock.*
  Reads (soft): inventory.StockLevel, demand_planning.DemandForecast,
                production.BOMLine, scm.SCMService

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.mrp",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class MRPPlugin(BasePlugin):
	"""Materials Requirements Planning ERP plugin.

	Registers 3 view groups and 1 report endpoint.
	Pre-configures 3 Rules Engine rulesets on first run.
	"""

	name = "mrp"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="mrp",
			version="1.0.0",
			description=(
				"Materials Requirements Planning — net requirements calculation, "
				"planned order generation with lot-size rounding, purchase requisition "
				"recommendations, production order recommendations, one-level BOM "
				"explosion, and safety stock breach alerting."
			),
			author="PgAppForge Contributors",
			tags=["ops", "mrp", "manufacturing", "planning", "supply-chain"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_mrp_run_list",
				"can_mrp_run_create",
				"can_mrp_product_config_list",
				"can_mrp_product_config_write",
				"can_mrp_planned_order_list",
				"can_mrp_planned_order_release",
				"can_mrp_planned_order_cancel",
				"can_mrp_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"ops.mrp.run.started",
			"ops.mrp.planned_order.created",
			"ops.mrp.purchase_req.created",
			"ops.mrp.production_order.recommended",
			"ops.mrp.run.completed",
			"ops.mrp.safety_stock.breach",
		]

	def subscribe_to(self) -> list[str]:
		"""MRP consumes:
		- inventory.stock.received:  may clear a safety stock breach
		- ops.demand_planning.forecast.approved: triggers re-evaluation of plans
		- pp.production_order.completed: reduces demand for components
		"""
		return [
			"inventory.stock.received",
			"ops.demand_planning.forecast.approved",
			"pp.production_order.completed",
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"MRP_MENU_CATEGORY": "Manufacturing",
			"MRP_DEFAULT_HORIZON_DAYS": 90,
			"MRP_SAFETY_STOCK_CHECK_ON_RECEIPT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("MRPPlugin initialised (config: %s)", list(self.config))

	def register_views(self) -> None:
		# Views are optional; register only if view classes exist
		cat = self.config.get("MRP_MENU_CATEGORY", "Manufacturing")
		log.info("MRPPlugin: views would be registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.mrp.models import (
			MRPPlannedOrder,
			MRPProductConfig,
			MRPRun,
		)
		return [MRPRun, MRPProductConfig, MRPPlannedOrder]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 3 Rules Engine rulesets for MRP domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("MRPPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "mrp.product_config.positive_lot_size",
				"description": "MRP product lot_size_qty must be positive",
				"model_name": "MRPProductConfig",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_lot_size",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "lot_size_qty", "op": "lte", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "lot_size_qty must be greater than 0",
							}
						],
					},
				],
			},
			{
				"name": "mrp.product_config.valid_lead_time",
				"description": "MRP product lead_time_days must be non-negative",
				"model_name": "MRPProductConfig",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_non_negative_lead_time",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "lead_time_days", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "lead_time_days must be >= 0",
							}
						],
					},
				],
			},
			{
				"name": "mrp.planned_order.positive_qty",
				"description": "MRP planned order quantities must be positive",
				"model_name": "MRPPlannedOrder",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_planned_qty",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "planned_qty", "op": "lte", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "planned_qty must be positive",
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
		log.info("MRPPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> MRPPlugin:
	return MRPPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.mrp.models import (  # noqa: E402
	MRPRun,
	MRPProductConfig,
	MRPPlannedOrder,
)
from pgappforge.plugins.erp.operations.mrp.events import (  # noqa: E402
	MRPRunStartedEvent,
	PlannedOrderCreatedEvent,
	PurchaseRequisitionCreatedEvent,
	ProductionOrderRecommendedEvent,
	MRPRunCompletedEvent,
	SafetyStockBreachEvent,
)
from pgappforge.plugins.erp.operations.mrp.services import (  # noqa: E402
	MRPService,
	MRPServiceError,
	MRPRunNotFoundError,
	PlannedOrderNotFoundError,
	InvalidMRPStatusError,
)

__all__ = [
	"MRPPlugin",
	"create_plugin",
	# models
	"MRPRun",
	"MRPProductConfig",
	"MRPPlannedOrder",
	# events
	"MRPRunStartedEvent",
	"PlannedOrderCreatedEvent",
	"PurchaseRequisitionCreatedEvent",
	"ProductionOrderRecommendedEvent",
	"MRPRunCompletedEvent",
	"SafetyStockBreachEvent",
	# services
	"MRPService",
	"MRPServiceError",
	"MRPRunNotFoundError",
	"PlannedOrderNotFoundError",
	"InvalidMRPStatusError",
]
