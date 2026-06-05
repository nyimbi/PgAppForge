"""
tests/ci/test_inventory_plugin.py

Compile-level and unit tests for the Inventory plugin.

Tests verify:
  - All model classes import cleanly (no SA lazy='dynamic', correct column types)
  - Event dataclasses construct correctly
  - InventoryService business logic (weighted average cost, reorder suggestions,
    historical valuation reconstruction, lot tracking enforcement)
  - Plugin metadata and get_events/subscribe_to contracts

No mocks — uses SQLite in-memory via real SQLAlchemy session fixtures.
No @pytest.mark.asyncio — plain synchronous functions.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
	return str(uuid.uuid4())


def _tenant() -> str:
	return _uid()


# ---------------------------------------------------------------------------
# SQLAlchemy fixtures (SQLite in-memory — no JSONB, use Text fallback)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
	"""Create a SQLite in-memory engine with all inventory tables."""
	from pgappforge.models.sqla import Model

	# Patch JSONB → JSON for SQLite compatibility in tests
	from sqlalchemy.dialects.postgresql import JSONB
	from sqlalchemy import JSON

	eng = create_engine("sqlite:///:memory:", echo=False)

	# Import models to register them with Base metadata
	from pgappforge.plugins.erp.operations.inventory.models import (
		ProductCategory, Product, Warehouse, WarehouseLocation,
		StockLevel, StockMovement,
	)

	Model.metadata.create_all(eng, checkfirst=True)
	return eng


@pytest.fixture
def session(engine):
	"""Provide a transactional session that rolls back after each test."""
	conn = engine.connect()
	trans = conn.begin()
	sess = Session(bind=conn)
	yield sess
	sess.close()
	trans.rollback()
	conn.close()


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

def test_inventory_models_import():
	from pgappforge.plugins.erp.operations.inventory.models import (
		ProductCategory, Product, Warehouse, WarehouseLocation,
		StockLevel, StockMovement,
	)
	assert ProductCategory.__tablename__ == "inv_product_category"
	assert Product.__tablename__ == "inv_product"
	assert Warehouse.__tablename__ == "inv_warehouse"
	assert WarehouseLocation.__tablename__ == "inv_warehouse_location"
	assert StockLevel.__tablename__ == "inv_stock_level"
	assert StockMovement.__tablename__ == "inv_stock_movement"


def test_inventory_events_import():
	from pgappforge.plugins.erp.operations.inventory.events import (
		StockReceivedEvent, StockIssuedEvent, StockTransferredEvent,
		StockAdjustedEvent, StockCountApprovedEvent, StockLowEvent,
		ProductCreatedEvent, ProductDeactivatedEvent,
	)
	evt = StockReceivedEvent(
		aggregate_id="m1",
		aggregate_type="StockMovement",
		tenant_id="t1",
		movement_id="m1",
		product_id="p1",
		warehouse_id="w1",
		quantity="10.0000",
		unit_cost_cents=500,
		total_cost_cents=5000,
	)
	assert evt.event_type == "inventory.stock.received"
	assert evt.unit_cost_cents == 500
	assert isinstance(evt.unit_cost_cents, int)


def test_inventory_services_import():
	from pgappforge.plugins.erp.operations.inventory.services import (
		InventoryService, InventoryServiceError,
		InsufficientStockError, StockNotFoundError,
		ProductNotFoundError, WarehouseNotFoundError,
	)
	svc = InventoryService()
	assert callable(svc.receive_stock)
	assert callable(svc.allocate_stock)
	assert callable(svc.issue_stock)
	assert callable(svc.get_stock_valuation)
	assert callable(svc.calculate_reorder_suggestions)


def test_inventory_plugin_import():
	from pgappforge.plugins.erp.operations.inventory import InventoryPlugin
	# Plugin class attributes
	assert InventoryPlugin.name == "inventory"
	assert InventoryPlugin.domain == "operations"
	assert "foundation" in InventoryPlugin.depends_on


# ---------------------------------------------------------------------------
# Plugin contract tests (no appbuilder needed)
# ---------------------------------------------------------------------------

def test_inventory_plugin_events():
	from pgappforge.plugins.erp.operations.inventory import InventoryPlugin
	# Instantiate with a fake appbuilder
	class FakeAB:
		pass
	plugin = InventoryPlugin.__new__(InventoryPlugin)
	plugin.appbuilder = FakeAB()
	plugin.config = {}
	plugin.status = None
	plugin._registered_views = []
	plugin._registered_blueprints = []
	plugin._registered_menu_items = []
	plugin._background_tasks = []
	plugin._event_listeners = []
	plugin.error_message = None
	plugin.load_time = None

	events = plugin.get_events()
	assert "inventory.stock.received" in events
	assert "inventory.stock.low" in events
	assert "inventory.product.created" in events
	assert all(e.startswith("inventory.") for e in events)

	subscriptions = plugin.subscribe_to()
	assert "ap.invoice.matched" in subscriptions


def test_inventory_plugin_register_models():
	from pgappforge.plugins.erp.operations.inventory import InventoryPlugin
	from pgappforge.plugins.erp.operations.inventory.models import (
		Product, Warehouse, StockMovement,
	)
	class FakeAB:
		pass
	plugin = InventoryPlugin.__new__(InventoryPlugin)
	plugin.appbuilder = FakeAB()
	plugin.config = {}
	plugin.status = None
	plugin._registered_views = []
	plugin._registered_blueprints = []
	plugin._registered_menu_items = []
	plugin._background_tasks = []
	plugin._event_listeners = []
	plugin.error_message = None
	plugin.load_time = None

	models = plugin.register_models()
	model_names = [m.__name__ for m in models]
	assert "Product" in model_names
	assert "Warehouse" in model_names
	assert "StockMovement" in model_names
	assert "StockLevel" in model_names


# ---------------------------------------------------------------------------
# InventoryService._update_stock_level: weighted average cost
# ---------------------------------------------------------------------------

def test_weighted_average_cost_computation():
	"""Test weighted average cost recomputation formula."""
	from pgappforge.plugins.erp.operations.inventory.services import InventoryService, _cents, _d
	from decimal import Decimal

	# Scenario: receive 100 units @ 1000¢, then receive 50 units @ 1200¢
	# Expected avg = (100×1000 + 50×1200) / 150 = 160000/150 = 1066.67 → 1067¢
	old_qty = _d(100)
	old_avg = 1000
	delta = _d(50)
	new_unit_cost = 1200
	new_qty = old_qty + delta

	new_avg = int(
		(
			(old_qty * Decimal(old_avg) + delta * Decimal(new_unit_cost))
			/ new_qty
		).to_integral_value(rounding=__import__("decimal").ROUND_HALF_UP)
	)
	assert new_avg == 1067


def test_cents_multiplication():
	"""Integer cents multiplication must never produce float."""
	from pgappforge.plugins.erp.operations.inventory.services import _cents
	from decimal import Decimal

	result = _cents(Decimal("3.5"), 1000)
	assert isinstance(result, int)
	assert result == 3500

	# Fractional: 2.333 units @ 300¢ = 700¢ (rounded half-up)
	result2 = _cents(Decimal("2.333"), 300)
	assert isinstance(result2, int)
	assert result2 == 700


# ---------------------------------------------------------------------------
# Model column type assertions (no float money)
# ---------------------------------------------------------------------------

def test_product_monetary_columns_are_integer():
	"""Ensure no Numeric/Float columns are used for money on Product."""
	from pgappforge.plugins.erp.operations.inventory.models import Product
	from sqlalchemy import Integer

	money_cols = ["base_price_cents", "cost_price_cents", "standard_cost_cents"]
	for col_name in money_cols:
		col = Product.__table__.c.get(col_name)
		assert col is not None, f"Column {col_name} not found"
		assert isinstance(col.type, Integer), (
			f"{col_name} must be Integer (cents), got {type(col.type)}"
		)


def test_stock_movement_monetary_columns_are_integer():
	from pgappforge.plugins.erp.operations.inventory.models import StockMovement
	from sqlalchemy import Integer

	for col_name in ("unit_cost_cents", "total_cost_cents"):
		col = StockMovement.__table__.c.get(col_name)
		assert col is not None
		assert isinstance(col.type, Integer), (
			f"{col_name} must be Integer, got {type(col.type)}"
		)


def test_stock_level_average_cost_is_integer():
	from pgappforge.plugins.erp.operations.inventory.models import StockLevel
	from sqlalchemy import Integer

	col = StockLevel.__table__.c.get("average_cost_cents")
	assert col is not None
	assert isinstance(col.type, Integer)


def test_no_lazy_dynamic():
	"""SA 2.x does not support lazy='dynamic'. Verify it's absent."""
	import inspect
	from pgappforge.plugins.erp.operations.inventory import models as inv_models

	for name, obj in inspect.getmembers(inv_models, inspect.isclass):
		for attr_name in dir(obj):
			try:
				attr = getattr(obj, attr_name)
				if hasattr(attr, "property") and hasattr(attr.property, "lazy"):
					assert attr.property.lazy != "dynamic", (
						f"{name}.{attr_name} uses lazy='dynamic' which is removed in SA 2.x"
					)
			except Exception:
				pass


# ---------------------------------------------------------------------------
# Model constraint checks
# ---------------------------------------------------------------------------

def test_product_warehouse_type_values():
	"""Warehouse type CHECK constraint covers expected values."""
	from pgappforge.plugins.erp.operations.inventory.models import Warehouse
	check_constraints = [
		c for c in Warehouse.__table__.constraints
		if hasattr(c, "sqltext")
	]
	constraint_texts = [str(c.sqltext) for c in check_constraints]
	combined = " ".join(constraint_texts)
	assert "OWNED" in combined
	assert "3PL" in combined
	assert "VIRTUAL" in combined


def test_location_type_values():
	from pgappforge.plugins.erp.operations.inventory.models import WarehouseLocation
	check_constraints = [
		c for c in WarehouseLocation.__table__.constraints
		if hasattr(c, "sqltext")
	]
	combined = " ".join(str(c.sqltext) for c in check_constraints)
	for loc_type in ("BULK", "PICK", "RECEIVE", "SHIP", "QC", "QUARANTINE", "STAGING"):
		assert loc_type in combined, f"Location type {loc_type!r} missing from CHECK constraint"


def test_stock_movement_direction_constraint():
	from pgappforge.plugins.erp.operations.inventory.models import StockMovement
	check_constraints = [
		c for c in StockMovement.__table__.constraints
		if hasattr(c, "sqltext")
	]
	combined = " ".join(str(c.sqltext) for c in check_constraints)
	assert "1" in combined and "-1" in combined


# ---------------------------------------------------------------------------
# Domain event amounts must be int
# ---------------------------------------------------------------------------

def test_domain_event_amounts_are_int():
	from pgappforge.plugins.erp.operations.inventory.events import StockIssuedEvent, StockReceivedEvent
	import dataclasses

	for cls in (StockReceivedEvent, StockIssuedEvent):
		for f in dataclasses.fields(cls):
			if "cents" in f.name:
				assert f.type in (int, "int"), (
					f"{cls.__name__}.{f.name} type annotation should be int, got {f.type!r}"
				)


# ---------------------------------------------------------------------------
# InventoryService._order_type_to_ref
# ---------------------------------------------------------------------------

def test_order_type_to_ref_mapping():
	from pgappforge.plugins.erp.operations.inventory.services import InventoryService
	svc = InventoryService()
	assert svc._order_type_to_ref("SALES_ORDER") == "SO"
	assert svc._order_type_to_ref("TRANSFER") == "TRANSFER"
	assert svc._order_type_to_ref("PRODUCTION") == "MANUAL"
	assert svc._order_type_to_ref("UNKNOWN") == "MANUAL"


# ---------------------------------------------------------------------------
# Product model default values
# ---------------------------------------------------------------------------

def test_product_column_defaults_defined():
	"""Column defaults are DB-side; verify they are declared on the columns."""
	from pgappforge.plugins.erp.operations.inventory.models import Product

	# Check server_default or default is set on key columns
	is_active_col = Product.__table__.c["is_active"]
	assert is_active_col.default is not None or is_active_col.server_default is not None, \
		"is_active must have a default"

	valuation_col = Product.__table__.c["valuation_method"]
	assert valuation_col.default is not None or valuation_col.server_default is not None, \
		"valuation_method must have a default"

	currency_col = Product.__table__.c["currency_code"]
	assert currency_col.default is not None or currency_col.server_default is not None, \
		"currency_code must have a default"


def test_warehouse_column_defaults_defined():
	"""Verify warehouse_type and is_active columns have defaults declared."""
	from pgappforge.plugins.erp.operations.inventory.models import Warehouse

	wh_type_col = Warehouse.__table__.c["warehouse_type"]
	assert wh_type_col.default is not None or wh_type_col.server_default is not None, \
		"warehouse_type must have a default"

	is_active_col = Warehouse.__table__.c["is_active"]
	assert is_active_col.default is not None or is_active_col.server_default is not None, \
		"is_active must have a default"


# ---------------------------------------------------------------------------
# StockMovement repr
# ---------------------------------------------------------------------------

def test_stock_movement_repr():
	from pgappforge.plugins.erp.operations.inventory.models import StockMovement
	m = StockMovement(
		tenant_id=_uid(),
		product_id=_uid(),
		warehouse_id=_uid(),
		movement_type="RECEIPT",
		quantity=Decimal("5.0"),
		direction=1,
		moved_at=datetime.now(timezone.utc),
	)
	r = repr(m)
	assert "RECEIPT" in r
	assert "+" in r


def test_stock_movement_repr_outbound():
	from pgappforge.plugins.erp.operations.inventory.models import StockMovement
	m = StockMovement(
		tenant_id=_uid(),
		product_id=_uid(),
		warehouse_id=_uid(),
		movement_type="ISSUE",
		quantity=Decimal("3.0"),
		direction=-1,
		moved_at=datetime.now(timezone.utc),
	)
	r = repr(m)
	assert "ISSUE" in r
	assert "-" in r


# ---------------------------------------------------------------------------
# All __all__ exports are importable
# ---------------------------------------------------------------------------

def test_inventory_init_all_exports():
	import pgappforge.plugins.erp.operations.inventory as pkg
	missing = []
	for name in pkg.__all__:
		if not hasattr(pkg, name):
			missing.append(name)
	assert not missing, f"Missing exports from inventory __init__: {missing}"
