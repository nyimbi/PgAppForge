"""
pgappforge/plugins/erp/operations/warehouse/__init__.py

WarehousePlugin — warehouse execution system (WMS) ERP plugin.

Domain: operations
Depends on: foundation, inventory

Events emitted:
  wms.picklist.created
  wms.picklist.completed
  wms.putaway.completed
  wms.stock_count.started
  wms.stock_count.ready

Events consumed:
  inventory.stock.received   — auto-create PutawayTask for inbound stock
  inventory.stock.low        — optional: escalate open pick lists

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.inventory",
        "pgappforge.plugins.erp.operations.warehouse",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.operations.warehouse import WarehousePlugin
    plugin = WarehousePlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class WarehousePlugin(BasePlugin):
	"""Warehouse Management System (WMS) ERP plugin.

	Registers 4 view groups and 3 report endpoints.
	Pre-configures 4 Rules Engine rulesets on first run.

	Depends on InventoryPlugin for stock movement execution.
	"""

	name = "warehouse"
	domain = "operations"
	depends_on: list[str] = ["foundation", "inventory"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="warehouse",
			version="1.0.0",
			description=(
				"Warehouse Management System — directed picking with priority queues, "
				"putaway task management with location suggestions, "
				"FULL/CYCLE/SPOT stock counts with approval-gated adjustments."
			),
			author="PgAppForge Contributors",
			tags=["erp", "operations", "warehouse", "wms", "picking", "putaway", "stock-count"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_wms_picklist_list",
				"can_wms_picklist_write",
				"can_wms_picklist_assign",
				"can_wms_picklist_pick",
				"can_wms_picklist_complete",
				"can_wms_putaway_list",
				"can_wms_putaway_write",
				"can_wms_putaway_complete",
				"can_wms_count_list",
				"can_wms_count_write",
				"can_wms_count_record",
				"can_wms_count_complete",
				"can_wms_count_approve",
				"can_wms_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"wms.picklist.created",
			"wms.picklist.completed",
			"wms.putaway.completed",
			"wms.stock_count.started",
			"wms.stock_count.ready",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"inventory.stock.received",  # auto-create putaway tasks for inbound stock
			"inventory.stock.low",       # optional: escalate pick priority
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"WMS_MENU_CATEGORY": "Warehouse",
			"WMS_AUTO_CREATE_PUTAWAY": True,
			"WMS_DEFAULT_PICK_PRIORITY": 5,
			"WMS_CYCLE_COUNT_FREQUENCY_DAYS": 30,
		}
		self.config = {**defaults, **self.config}

		# Wire up event subscription for auto-putaway task creation
		if self.config.get("WMS_AUTO_CREATE_PUTAWAY"):
			self._register_stock_received_handler()

		log.info("WarehousePlugin initialised (config keys: %s)", list(self.config))

	def _register_stock_received_handler(self) -> None:
		"""Subscribe to inventory.stock.received to auto-create putaway tasks."""
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe

			def _on_stock_received(event: Any) -> None:
				"""Best-effort auto-create PutawayTask; logged on failure."""
				try:
					from flask import current_app
					db = current_app.extensions.get("sqlalchemy")
					if db is None:
						return
					from pgappforge.plugins.erp.operations.warehouse.services import WarehouseService
					svc = WarehouseService()
					with db.session.begin_nested():
						svc.create_putaway_task(
							grn_id=event.reference_id or "",
							product_id=event.product_id,
							quantity=event.quantity,
							session=db.session,
							warehouse_id=event.warehouse_id,
							tenant_id=event.tenant_id,
							lot_number=event.lot_number or None,
						)
				except Exception as exc:
					log.warning("WarehousePlugin auto-putaway failed (non-fatal): %s", exc)

			subscribe("inventory.stock.received", _on_stock_received)
			log.debug("WarehousePlugin: subscribed to inventory.stock.received")
		except ImportError:
			log.debug("WarehousePlugin: foundation events not available, skipping subscription")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.operations.warehouse.views import (
			CycleCountDashboardView,
			PickListView,
			PutawayView,
			StockCountView,
			WMSReportView,
		)

		cat = self.config.get("WMS_MENU_CATEGORY", "Warehouse")

		self.add_view(PickListView, "Pick Lists", icon="fa-list-alt", category=cat)
		self.add_view(PutawayView, "Putaway Tasks", icon="fa-arrow-circle-down", category=cat)
		self.add_view(StockCountView, "Stock Counts", icon="fa-calculator", category=cat)
		self.add_view(WMSReportView, "WMS Reports", icon="fa-bar-chart", category=cat)
		self.add_view(CycleCountDashboardView, "Cycle Count Dashboard", icon="fa-calendar-check", category=cat)

		log.info("WarehousePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.operations.warehouse.models import (
			StorageLocation,
			PickList,
			PickListLine,
			PickTask,
			PutawayTask,
			CycleCount,
			CycleCountLine,
			StockCount,
			StockCountLine,
		)
		return [
			StorageLocation,
			PickList,
			PickListLine,
			PickTask,
			PutawayTask,
			CycleCount,
			CycleCountLine,
			StockCount,
			StockCountLine,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 Rules Engine rulesets for the WMS domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("WarehousePlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "wms.picklist.require_warehouse",
				"description": "PickList must reference a valid warehouse",
				"model_name": "PickList",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_warehouse_id",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "warehouse_id", "op": "eq", "value": None},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "PickList.warehouse_id is required"}
						],
					},
				],
			},
			{
				"name": "wms.picklist.valid_order_type",
				"description": "PickList order_type must be SALES_ORDER, TRANSFER, or PRODUCTION",
				"model_name": "PickList",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_valid_order_type",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "order_type", "op": "not_in",
							 "value": ["SALES_ORDER", "TRANSFER", "PRODUCTION"]},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "PickList.order_type must be SALES_ORDER, TRANSFER, or PRODUCTION"}
						],
					},
				],
			},
			{
				"name": "wms.stock_count.no_reopen_approved",
				"description": "An APPROVED stock count cannot be re-opened",
				"model_name": "StockCount",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_reopen_approved_count",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "APPROVED"},
							{"field": "_new_status", "op": "neq", "value": "APPROVED"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "APPROVED stock counts are immutable; create a new SPOT count to make corrections"}
						],
					},
				],
			},
			{
				"name": "wms.putaway.positive_quantity",
				"description": "PutawayTask quantity must be positive",
				"model_name": "PutawayTask",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_putaway_qty",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "quantity", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "PutawayTask.quantity must be positive"}
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
		log.info("WarehousePlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> WarehousePlugin:
	"""Construct a WarehousePlugin without activating it."""
	return WarehousePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.warehouse.models import (  # noqa: E402
	StorageLocation,
	PickList,
	PickListLine,
	PickTask,
	PutawayTask,
	CycleCount,
	CycleCountLine,
	StockCount,
	StockCountLine,
)
from pgappforge.plugins.erp.operations.warehouse.events import (  # noqa: E402
	PickListCompletedEvent,
	PickListCreatedEvent,
	PutawayCompletedEvent,
	StockCountReadyEvent,
	StockCountStartedEvent,
)
from pgappforge.plugins.erp.operations.warehouse.services import (  # noqa: E402
	WarehouseService,
	WarehouseServiceError,
	InvalidStatusTransitionError,
	PickListNotFoundError,
	PickTaskNotFoundError,
	PutawayNotFoundError,
	StockCountNotFoundError,
	CycleCountNotFoundError,
	StorageLocationNotFoundError,
)

__all__ = [
	# plugin
	"WarehousePlugin",
	"create_plugin",
	# models
	"StorageLocation",
	"PickList",
	"PickListLine",
	"PickTask",
	"PutawayTask",
	"CycleCount",
	"CycleCountLine",
	"StockCount",
	"StockCountLine",
	# events
	"PickListCreatedEvent",
	"PickListCompletedEvent",
	"PutawayCompletedEvent",
	"StockCountStartedEvent",
	"StockCountReadyEvent",
	# services
	"WarehouseService",
	"WarehouseServiceError",
	"InvalidStatusTransitionError",
	"PickListNotFoundError",
	"PickTaskNotFoundError",
	"PutawayNotFoundError",
	"StockCountNotFoundError",
	"CycleCountNotFoundError",
	"StorageLocationNotFoundError",
]
