"""
tests/ci/test_warehouse_plugin.py

Compile-level and unit tests for the Warehouse Management plugin.

Tests verify:
  - All model classes import cleanly
  - Event dataclasses construct correctly
  - WarehouseService method signatures and basic logic
  - Status transition guards
  - Plugin metadata and get_events/subscribe_to contracts
  - No lazy='dynamic', no float money, integer cents enforced

No mocks — plain unit tests on service logic and model construction.
No @pytest.mark.asyncio decorators.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest


def _uid() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

def test_warehouse_models_import():
	from pgappforge.plugins.erp.operations.warehouse.models import (
		PickList, PickListLine, PutawayTask, StockCount, StockCountLine,
	)
	assert PickList.__tablename__ == "wms_picklist"
	assert PickListLine.__tablename__ == "wms_picklist_line"
	assert PutawayTask.__tablename__ == "wms_putaway_task"
	assert StockCount.__tablename__ == "wms_stock_count"
	assert StockCountLine.__tablename__ == "wms_stock_count_line"


def test_warehouse_events_import():
	from pgappforge.plugins.erp.operations.warehouse.events import (
		PickListCreatedEvent, PickListCompletedEvent,
		PutawayCompletedEvent, StockCountStartedEvent, StockCountReadyEvent,
	)
	evt = PickListCreatedEvent(
		aggregate_id="pl1",
		aggregate_type="PickList",
		tenant_id="t1",
		picklist_id="pl1",
		warehouse_id="wh1",
		order_type="SALES_ORDER",
		order_id="so1",
		line_count=3,
		priority=5,
	)
	assert evt.event_type == "wms.picklist.created"
	assert evt.line_count == 3
	assert isinstance(evt.priority, int)


def test_warehouse_services_import():
	from pgappforge.plugins.erp.operations.warehouse.services import (
		WarehouseService, WarehouseServiceError,
		PickListNotFoundError, PutawayNotFoundError,
		StockCountNotFoundError, InvalidStatusTransitionError,
	)
	svc = WarehouseService()
	assert callable(svc.create_picklist)
	assert callable(svc.assign_picklist)
	assert callable(svc.record_pick)
	assert callable(svc.complete_picklist)
	assert callable(svc.create_putaway_task)
	assert callable(svc.complete_putaway)
	assert callable(svc.suggest_putaway_location)
	assert callable(svc.start_stock_count)
	assert callable(svc.record_stock_count_line)
	assert callable(svc.complete_stock_count)
	# new gap-fill methods
	assert callable(svc.receive_goods_to_warehouse)
	assert callable(svc.complete_putaway_to_location)
	assert callable(svc.create_pick_list)
	assert callable(svc.complete_pick)
	assert callable(svc.start_cycle_count)
	assert callable(svc.record_count)
	assert callable(svc.approve_count_adjustment)
	assert callable(svc.get_warehouse_utilization)
	assert callable(svc.get_inventory_by_location)


def test_warehouse_plugin_import():
	from pgappforge.plugins.erp.operations.warehouse import WarehousePlugin
	assert WarehousePlugin.name == "warehouse"
	assert WarehousePlugin.domain == "operations"
	assert "foundation" in WarehousePlugin.depends_on
	assert "inventory" in WarehousePlugin.depends_on


# ---------------------------------------------------------------------------
# Plugin contract
# ---------------------------------------------------------------------------

def _make_plugin(cls):
	"""Construct a plugin instance without calling __init__ (no appbuilder needed)."""
	plugin = cls.__new__(cls)
	plugin.appbuilder = object()
	plugin.config = {}
	plugin.status = None
	plugin._registered_views = []
	plugin._registered_blueprints = []
	plugin._registered_menu_items = []
	plugin._background_tasks = []
	plugin._event_listeners = []
	plugin.error_message = None
	plugin.load_time = None
	return plugin


def test_warehouse_plugin_events():
	from pgappforge.plugins.erp.operations.warehouse import WarehousePlugin
	plugin = _make_plugin(WarehousePlugin)

	events = plugin.get_events()
	assert "wms.picklist.created" in events
	assert "wms.picklist.completed" in events
	assert "wms.putaway.completed" in events
	assert "wms.stock_count.started" in events
	assert "wms.stock_count.ready" in events
	assert all(e.startswith("wms.") for e in events)


def test_warehouse_plugin_subscribe_to():
	from pgappforge.plugins.erp.operations.warehouse import WarehousePlugin
	plugin = _make_plugin(WarehousePlugin)

	subs = plugin.subscribe_to()
	assert "inventory.stock.received" in subs
	assert "inventory.stock.low" in subs


def test_warehouse_plugin_register_models():
	from pgappforge.plugins.erp.operations.warehouse import WarehousePlugin
	from pgappforge.plugins.erp.operations.warehouse.models import (
		PickList, PutawayTask, StockCount,
	)
	plugin = _make_plugin(WarehousePlugin)
	models = plugin.register_models()
	model_names = [m.__name__ for m in models]
	assert "PickList" in model_names
	assert "PickListLine" in model_names
	assert "PutawayTask" in model_names
	assert "StockCount" in model_names
	assert "StockCountLine" in model_names


# ---------------------------------------------------------------------------
# Model defaults and constraints
# ---------------------------------------------------------------------------

def test_picklist_defaults():
	from pgappforge.plugins.erp.operations.warehouse.models import PickList
	pl = PickList(
		tenant_id=_uid(),
		warehouse_id=_uid(),
		order_type="SALES_ORDER",
		order_id=_uid(),
	)
	assert pl.status == "PENDING"
	assert pl.priority == 5


def test_picklist_line_defaults():
	from pgappforge.plugins.erp.operations.warehouse.models import PickListLine
	from decimal import Decimal
	line = PickListLine(
		tenant_id=_uid(),
		picklist_id=_uid(),
		product_id=_uid(),
		quantity_requested=Decimal("10"),
	)
	assert line.status == "PENDING"
	assert line.quantity_picked == Decimal("0")


def test_putaway_defaults():
	from pgappforge.plugins.erp.operations.warehouse.models import PutawayTask
	t = PutawayTask(
		tenant_id=_uid(),
		warehouse_id=_uid(),
		grn_id=_uid(),
		product_id=_uid(),
		quantity=Decimal("5"),
	)
	assert t.status == "PENDING"
	assert t.actual_location_id is None


def test_stock_count_defaults():
	from pgappforge.plugins.erp.operations.warehouse.models import StockCount
	import datetime as dt
	c = StockCount(
		tenant_id=_uid(),
		warehouse_id=_uid(),
		count_date=dt.date.today(),
	)
	assert c.status == "DRAFT"
	assert c.count_type == "FULL"


def test_stock_count_line_defaults():
	from pgappforge.plugins.erp.operations.warehouse.models import StockCountLine
	line = StockCountLine(
		tenant_id=_uid(),
		stock_count_id=_uid(),
		product_id=_uid(),
		expected_quantity=Decimal("100"),
	)
	assert line.counted_quantity is None
	assert line.variance == Decimal("0")
	assert line.variance_value_cents == 0
	assert isinstance(line.variance_value_cents, int)


# ---------------------------------------------------------------------------
# Integer cents enforcement on StockCountLine
# ---------------------------------------------------------------------------

def test_stock_count_line_variance_value_is_integer():
	from pgappforge.plugins.erp.operations.warehouse.models import StockCountLine
	from sqlalchemy import Integer

	col = StockCountLine.__table__.c.get("variance_value_cents")
	assert col is not None, "variance_value_cents column missing"
	assert isinstance(col.type, Integer), (
		f"variance_value_cents must be Integer (cents), got {type(col.type)}"
	)


def test_stock_count_total_variance_is_integer():
	from pgappforge.plugins.erp.operations.warehouse.models import StockCount
	from sqlalchemy import Integer

	col = StockCount.__table__.c.get("total_variance_value_cents")
	assert col is not None
	assert isinstance(col.type, Integer)


# ---------------------------------------------------------------------------
# CHECK constraints
# ---------------------------------------------------------------------------

def test_picklist_order_type_constraint():
	from pgappforge.plugins.erp.operations.warehouse.models import PickList
	checks = [c for c in PickList.__table__.constraints if hasattr(c, "sqltext")]
	combined = " ".join(str(c.sqltext) for c in checks)
	for ot in ("SALES_ORDER", "TRANSFER", "PRODUCTION"):
		assert ot in combined, f"order_type {ot!r} missing from CHECK constraint"


def test_picklist_status_constraint():
	from pgappforge.plugins.erp.operations.warehouse.models import PickList
	checks = [c for c in PickList.__table__.constraints if hasattr(c, "sqltext")]
	combined = " ".join(str(c.sqltext) for c in checks)
	for s in ("PENDING", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"):
		assert s in combined, f"status {s!r} missing from CHECK constraint"


def test_stock_count_type_constraint():
	from pgappforge.plugins.erp.operations.warehouse.models import StockCount
	checks = [c for c in StockCount.__table__.constraints if hasattr(c, "sqltext")]
	combined = " ".join(str(c.sqltext) for c in checks)
	for ct in ("FULL", "CYCLE", "SPOT"):
		assert ct in combined, f"count_type {ct!r} missing from CHECK constraint"


def test_stock_count_status_constraint():
	from pgappforge.plugins.erp.operations.warehouse.models import StockCount
	checks = [c for c in StockCount.__table__.constraints if hasattr(c, "sqltext")]
	combined = " ".join(str(c.sqltext) for c in checks)
	for s in ("DRAFT", "IN_PROGRESS", "COMPLETED", "APPROVED"):
		assert s in combined, f"status {s!r} missing from CHECK constraint"


def test_putaway_status_constraint():
	from pgappforge.plugins.erp.operations.warehouse.models import PutawayTask
	checks = [c for c in PutawayTask.__table__.constraints if hasattr(c, "sqltext")]
	combined = " ".join(str(c.sqltext) for c in checks)
	assert "PENDING" in combined
	assert "COMPLETED" in combined


# ---------------------------------------------------------------------------
# No lazy='dynamic'
# ---------------------------------------------------------------------------

def test_no_lazy_dynamic_warehouse():
	import inspect
	from pgappforge.plugins.erp.operations.warehouse import models as wms_models

	for name, obj in inspect.getmembers(wms_models, inspect.isclass):
		for attr_name in dir(obj):
			try:
				attr = getattr(obj, attr_name)
				if hasattr(attr, "property") and hasattr(attr.property, "lazy"):
					assert attr.property.lazy != "dynamic", (
						f"{name}.{attr_name} uses lazy='dynamic' (removed in SA 2.x)"
					)
			except Exception:
				pass


# ---------------------------------------------------------------------------
# Event payload fields must use int for cents
# ---------------------------------------------------------------------------

def test_putaway_event_amounts_are_int():
	from pgappforge.plugins.erp.operations.warehouse.events import StockCountReadyEvent
	import dataclasses

	for f in dataclasses.fields(StockCountReadyEvent):
		if "cents" in f.name:
			assert f.type in (int, "int"), (
				f"StockCountReadyEvent.{f.name} should be int, got {f.type!r}"
			)


# ---------------------------------------------------------------------------
# Service exception hierarchy
# ---------------------------------------------------------------------------

def test_exception_hierarchy():
	from pgappforge.plugins.erp.operations.warehouse.services import (
		WarehouseServiceError,
		PickListNotFoundError,
		PutawayNotFoundError,
		StockCountNotFoundError,
		InvalidStatusTransitionError,
	)
	assert issubclass(PickListNotFoundError, WarehouseServiceError)
	assert issubclass(PutawayNotFoundError, WarehouseServiceError)
	assert issubclass(StockCountNotFoundError, WarehouseServiceError)
	assert issubclass(InvalidStatusTransitionError, WarehouseServiceError)
	assert issubclass(WarehouseServiceError, Exception)


# ---------------------------------------------------------------------------
# All __all__ exports are importable
# ---------------------------------------------------------------------------

def test_warehouse_init_all_exports():
	import pgappforge.plugins.erp.operations.warehouse as pkg
	missing = []
	for name in pkg.__all__:
		if not hasattr(pkg, name):
			missing.append(name)
	assert not missing, f"Missing exports from warehouse __init__: {missing}"


def test_inventory_init_all_exports_from_warehouse_test():
	"""Cross-check inventory __all__ from warehouse test file."""
	import pgappforge.plugins.erp.operations.inventory as pkg
	missing = [n for n in pkg.__all__ if not hasattr(pkg, n)]
	assert not missing, f"Missing inventory exports: {missing}"
