"""
pgappforge/plugins/erp/operations/inventory/__init__.py

InventoryPlugin — full inventory lifecycle ERP plugin.

Domain: operations
Depends on: foundation

Events emitted:
  inventory.stock.received
  inventory.stock.issued
  inventory.stock.transferred
  inventory.stock.adjusted
  inventory.stock.count_approved
  inventory.stock.low
  inventory.product.created
  inventory.product.deactivated

Events consumed:
  ap.invoice.matched    — update in-transit qty when GRN matched to invoice

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.inventory",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.inventory import InventoryPlugin
    plugin = InventoryPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class InventoryPlugin(BasePlugin):
	"""Inventory Management ERP plugin.

	Registers 6 view groups and 3 report endpoints.
	Pre-configures 5 Rules Engine rulesets on first run.
	"""

	name = "inventory"
	domain = "operations"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="inventory",
			version="1.0.0",
			description=(
				"Inventory Management — full product lifecycle: product master, "
				"warehouse and location management, lot/serial/batch tracking, "
				"event-sourced stock movements, weighted average costing, "
				"reorder point automation, and stock valuation."
			),
			author="PgAppForge Contributors",
			tags=["erp", "operations", "inventory", "warehouse", "stock", "procurement"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_inv_product_list",
				"can_inv_product_write",
				"can_inv_product_deactivate",
				"can_inv_category_list",
				"can_inv_category_write",
				"can_inv_warehouse_list",
				"can_inv_warehouse_write",
				"can_inv_stock_list",
				"can_inv_movement_list",
				"can_inv_receive_stock",
				"can_inv_issue_stock",
				"can_inv_adjust_stock",
				"can_inv_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"inventory.stock.received",
			"inventory.stock.issued",
			"inventory.stock.transferred",
			"inventory.stock.adjusted",
			"inventory.stock.count_approved",
			"inventory.stock.low",
			"inventory.product.created",
			"inventory.product.deactivated",
		]

	def subscribe_to(self) -> list[str]:
		"""Consume AP events to keep in-transit quantities accurate."""
		return [
			"ap.invoice.matched",   # GRN confirmed → stock received
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"INV_MENU_CATEGORY": "Inventory",
			"INV_DEFAULT_VALUATION_METHOD": "WEIGHTED_AVG",
			"INV_LOW_STOCK_ALERT_ENABLED": True,
			"INV_REORDER_CHECK_ON_ISSUE": True,
		}
		self.config = {**defaults, **self.config}
		log.info("InventoryPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.operations.inventory.views import (
			InventoryReportView,
			ProductCategoryView,
			ProductView,
			StockLevelView,
			StockMovementView,
			WarehouseView,
		)

		cat = self.config.get("INV_MENU_CATEGORY", "Inventory")

		self.add_view(ProductCategoryView, "Product Categories", icon="fa-sitemap", category=cat)
		self.add_view(ProductView, "Products", icon="fa-box", category=cat)
		self.add_view(WarehouseView, "Warehouses", icon="fa-warehouse", category=cat)
		self.add_view(StockLevelView, "Stock Levels", icon="fa-cubes", category=cat)
		self.add_view(StockMovementView, "Stock Movements", icon="fa-exchange", category=cat)
		self.add_view(InventoryReportView, "Inventory Reports", icon="fa-bar-chart", category=cat)

		log.info("InventoryPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.inventory.models import (
			Product,
			ProductCategory,
			StockLevel,
			StockMovement,
			Warehouse,
			WarehouseLocation,
		)
		return [
			ProductCategory,
			Product,
			Warehouse,
			WarehouseLocation,
			StockLevel,
			StockMovement,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 Rules Engine rulesets for inventory domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("InventoryPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "inv.product.require_uom",
				"description": "Product UOM must be set before saving",
				"model_name": "Product",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_uom_on_create",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "uom", "op": "eq", "value": ""},
						],
						"actions_json": [
							{"type": "raise_error", "message": "Product UOM is required"}
						],
					},
				],
			},
			{
				"name": "inv.product.positive_costs",
				"description": "Product cost prices must be non-negative integers",
				"model_name": "Product",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_non_negative_cost",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "cost_price_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error", "message": "cost_price_cents must be >= 0"}
						],
					},
				],
			},
			{
				"name": "inv.product.reorder_consistency",
				"description": "reorder_quantity must be > 0 when reorder_point > 0",
				"model_name": "Product",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_reorder_qty_with_point",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "reorder_point", "op": "gt", "value": 0},
							{"field": "reorder_quantity", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "reorder_quantity must be > 0 when reorder_point is set"}
						],
					},
				],
			},
			{
				"name": "inv.stock_movement.positive_quantity",
				"description": "StockMovement quantity must be positive",
				"model_name": "StockMovement",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_quantity",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "quantity", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "StockMovement.quantity must be positive"}
						],
					},
				],
			},
			{
				"name": "inv.stock_movement.direction_constraint",
				"description": "StockMovement direction must be 1 or -1",
				"model_name": "StockMovement",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_valid_direction",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "direction", "op": "not_in", "value": [1, -1]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "StockMovement.direction must be 1 (inbound) or -1 (outbound)"}
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
		log.info("InventoryPlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> InventoryPlugin:
	"""Construct an InventoryPlugin without activating it."""
	return InventoryPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.inventory.models import (  # noqa: E402
	Product,
	ProductCategory,
	StockLevel,
	StockMovement,
	Warehouse,
	WarehouseLocation,
)
from pgappforge.plugins.erp.operations.inventory.events import (  # noqa: E402
	ProductCreatedEvent,
	ProductDeactivatedEvent,
	StockAdjustedEvent,
	StockCountApprovedEvent,
	StockIssuedEvent,
	StockLowEvent,
	StockReceivedEvent,
	StockTransferredEvent,
)
from pgappforge.plugins.erp.operations.inventory.services import (  # noqa: E402
	InventoryService,
	InventoryServiceError,
	InsufficientStockError,
	ProductNotFoundError,
	StockNotFoundError,
	WarehouseNotFoundError,
)

__all__ = [
	# plugin
	"InventoryPlugin",
	"create_plugin",
	# models
	"ProductCategory",
	"Product",
	"Warehouse",
	"WarehouseLocation",
	"StockLevel",
	"StockMovement",
	# events
	"StockReceivedEvent",
	"StockIssuedEvent",
	"StockTransferredEvent",
	"StockAdjustedEvent",
	"StockCountApprovedEvent",
	"StockLowEvent",
	"ProductCreatedEvent",
	"ProductDeactivatedEvent",
	# services
	"InventoryService",
	"InventoryServiceError",
	"InsufficientStockError",
	"StockNotFoundError",
	"ProductNotFoundError",
	"WarehouseNotFoundError",
]
