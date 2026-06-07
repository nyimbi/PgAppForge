"""
pgappforge/plugins/erp/finance/product_costing/__init__.py

ProductCostingPlugin — Product Costing ERP plugin.

Provides standard costing, planned costing, actual cost computation,
variance analysis, and GL variance posting for manufactured products.

Depends on: foundation
Integrates with: gl (variance posting), inventory (product soft FK),
                 production (production order soft FK)

Events emitted
--------------
  finance.costing.rollup.completed   — standard cost rollup finished
  finance.costing.actual.computed    — actual vs standard computed
  finance.costing.variance.posted    — variance posted to GL
  finance.costing.version.created    — new cost version created
  finance.costing.standard.released  — standard cost activated

BPM actions
-----------
  finance.costing.compute_actual     — compute actual vs standard

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.gl",
        "pgappforge.plugins.erp.finance.product_costing",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.product_costing import ProductCostingPlugin
    plugin = ProductCostingPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ProductCostingPlugin(BasePlugin):
	"""Product Costing ERP plugin.

	Registers cost version management, rollup, actual cost computation,
	and variance analysis views. Pre-configures 5 Rules Engine rulesets
	for costing controls.

	Class-level attributes for dependency resolution:
	    name       = "product_costing"
	    domain     = "finance"
	    depends_on = ["foundation"]
	"""

	name = "product_costing"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="product_costing",
			version="1.0.0",
			description=(
				"Product Costing — standard cost versions, cost element rollup, "
				"actual vs standard variance analysis, and GL variance posting "
				"for manufactured and purchased products."
			),
			author="PgAppForge Contributors",
			tags=["finance", "costing", "standard-cost", "actual-cost", "manufacturing"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_cost_version_list",
				"can_cost_version_write",
				"can_cost_version_release",
				"can_cost_element_write",
				"can_cost_rollup",
				"can_cost_actual_compute",
				"can_cost_history_view",
				"can_cost_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"finance.costing.rollup.completed",
			"finance.costing.actual.computed",
			"finance.costing.variance.posted",
			"finance.costing.version.created",
			"finance.costing.standard.released",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"production.order.completed",   # trigger actual cost computation
			"inventory.product.updated",    # invalidate cached standard costs
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"COSTING_MENU_CATEGORY": "Product Costing",
			"COSTING_DEFAULT_CURRENCY": "USD",
			"COSTING_GL_VARIANCE_ACCOUNT": "5990",
			"COSTING_GL_WIP_ACCOUNT": "1410",
			"COSTING_VARIANCE_THRESHOLD_CENTS": 1_000,
		}
		self.config = {**defaults, **self.config}
		log.info("ProductCostingPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Wire event subscriptions after init."""
		self._subscribe_to_production_events()

	def register_views(self) -> None:
		"""Register product costing views under the configured menu category."""
		# Views are lightweight — import lazily to keep plugin load fast
		try:
			from pgappforge.plugins.erp.finance.product_costing import views as v  # type: ignore[import]

			cat = self.config.get("COSTING_MENU_CATEGORY", "Product Costing")
			self.add_view(v.CostVersionView, "Cost Versions", icon="fa-layer-group", category=cat)
			self.add_view(v.CostElementView, "Cost Elements", icon="fa-list", category=cat)
			self.add_view(v.StandardCostView, "Standard Costs", icon="fa-tag", category=cat)
			self.add_view(v.ActualCostView, "Actual Costs", icon="fa-balance-scale", category=cat)
			self.add_view(v.CostVarianceReportView, "Variance Report", icon="fa-chart-bar", category=cat)
			log.info("ProductCostingPlugin: views registered under category %r", cat)
		except ImportError:
			log.debug("ProductCostingPlugin: views module not found — skipping view registration")

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate."""
		from pgappforge.plugins.erp.finance.product_costing.models import (
			CostElement,
			CostVersion,
			ProductionOrderActualCost,
			ProductStandardCost,
		)
		return [
			CostVersion,
			CostElement,
			ProductStandardCost,
			ProductionOrderActualCost,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for costing controls.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("ProductCostingPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Block element addition to non-DRAFT versions
			{
				"name": "costing.version.draft_only_elements",
				"description": "Cost elements can only be added to DRAFT versions",
				"model_name": "CostVersion",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_element_on_non_draft",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "version.status", "op": "not_in", "value": ["DRAFT"]},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cost elements can only be added to DRAFT versions",
							}
						],
					},
				],
			},
			# 2. Prevent releasing a version with no elements
			{
				"name": "costing.version.release_requires_elements",
				"description": "A cost version must have at least one element before release",
				"model_name": "CostVersion",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_empty_version_release",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "ACTIVE"},
							{"field": "element_count", "op": "eq", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot release a cost version with no elements; add at least one cost element",
							}
						],
					},
				],
			},
			# 3. Zero unit_cost_cents warning
			{
				"name": "costing.element.zero_cost_warning",
				"description": "Warn when a cost element has zero unit cost",
				"model_name": "CostElement",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_zero_unit_cost",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "unit_cost_cents", "op": "eq", "value": 0},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Cost element has zero unit cost — verify this is intentional",
							}
						],
					},
				],
			},
			# 4. Unfavourable variance threshold alert
			{
				"name": "costing.actual.large_unfavourable_variance",
				"description": "Flag unfavourable variances > 10% of standard cost",
				"model_name": "ProductionOrderActualCost",
				"stop_on_match": False,
				"rules": [
					{
						"name": "flag_large_unfavourable_variance",
						"trigger_event": "on_after_create",
						"conditions_json": [
							{"field": "total_variance_cents", "op": "gt", "value": 0},
							{
								"field": "total_variance_cents",
								"op": "gt",
								"value": "{{total_standard_cents * 0.1}}",
							},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Unfavourable production variance exceeds 10% of standard — review required",
							}
						],
					},
				],
			},
			# 5. Historical version immutability
			{
				"name": "costing.version.historical_immutable",
				"description": "HISTORICAL cost versions cannot be modified",
				"model_name": "CostVersion",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_historical_update",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "eq", "value": "HISTORICAL"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "HISTORICAL cost versions are immutable; create a new version",
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
		log.info("ProductCostingPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Production event subscriptions
	# ------------------------------------------------------------------

	def _subscribe_to_production_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("production.order.completed", self._on_production_order_completed)
			log.debug("ProductCostingPlugin: subscribed to production.order.completed")
		except Exception as exc:
			log.warning("ProductCostingPlugin._subscribe_to_production_events failed: %s", exc)

	def _on_production_order_completed(self, event: Any) -> None:
		"""No-op stub: real implementation would trigger compute_actual_cost workflow."""
		log.debug(
			"ProductCostingPlugin._on_production_order_completed: order=%s",
			getattr(event, "aggregate_id", "?"),
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ProductCostingPlugin:
	"""Construct and return a ProductCostingPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return ProductCostingPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.product_costing.models import (  # noqa: E402
	CostElement,
	CostVersion,
	ProductionOrderActualCost,
	ProductStandardCost,
)
from pgappforge.plugins.erp.finance.product_costing.events import (  # noqa: E402
	ActualCostComputedEvent,
	CostRollUpCompletedEvent,
	CostVariancePostedEvent,
	CostVersionCreatedEvent,
	StandardCostReleasedEvent,
)
from pgappforge.plugins.erp.finance.product_costing.services import (  # noqa: E402
	CostVersionNotFoundError,
	CostVersionStatusError,
	ProductCostingError,
	ProductCostingService,
	ProductionOrderCostError,
	StandardCostNotFoundError,
)

__all__ = [
	# plugin
	"ProductCostingPlugin",
	"create_plugin",
	# models
	"CostVersion",
	"CostElement",
	"ProductStandardCost",
	"ProductionOrderActualCost",
	# events
	"CostRollUpCompletedEvent",
	"ActualCostComputedEvent",
	"CostVariancePostedEvent",
	"CostVersionCreatedEvent",
	"StandardCostReleasedEvent",
	# services
	"ProductCostingService",
	"ProductCostingError",
	"CostVersionNotFoundError",
	"CostVersionStatusError",
	"StandardCostNotFoundError",
	"ProductionOrderCostError",
]
