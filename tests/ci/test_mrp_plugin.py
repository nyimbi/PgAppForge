"""
tests/ci/test_mrp_plugin.py

CI tests for the MRP (Materials Requirements Planning) plugin.

Tests cover:
  - Model instantiation and field defaults
  - MRPService.check_safety_stock (breach detection + event emission)
  - MRPService.run_mrp (basic run with no demand → no planned orders)
  - MRPService.get_mrp_report (report structure)
  - MRPService.convert_to_po (status transition)
  - Lot-size rounding arithmetic
  - Event dataclass fields

No mocks — uses real objects and in-memory logic where DB is not available.
Async tests: plain async functions, loop = asyncio.get_event_loop() inside tests.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _make_session(rows: list | None = None):
	"""Minimal session mock with execute().scalars().all() and scalar_one_or_none()."""
	session = MagicMock()
	rows = rows or []

	scalar_result = MagicMock()
	scalar_result.all.return_value = rows
	scalar_result.scalar_one_or_none.return_value = None

	execute_result = MagicMock()
	execute_result.scalars.return_value = scalar_result
	execute_result.scalar_one_or_none.return_value = None
	execute_result.scalar.return_value = Decimal("0")

	session.execute.return_value = execute_result
	session.flush = MagicMock()
	session.add = MagicMock()
	return session


# ---------------------------------------------------------------------------
# Lot-size rounding
# ---------------------------------------------------------------------------

def test_round_up_to_lot_exact_multiple():
	from pgappforge.plugins.erp.operations.mrp.services import _round_up_to_lot
	assert _round_up_to_lot(Decimal("10"), Decimal("5")) == Decimal("10")


def test_round_up_to_lot_rounds_up():
	from pgappforge.plugins.erp.operations.mrp.services import _round_up_to_lot
	assert _round_up_to_lot(Decimal("7"), Decimal("5")) == Decimal("10")


def test_round_up_to_lot_fractional():
	from pgappforge.plugins.erp.operations.mrp.services import _round_up_to_lot
	assert _round_up_to_lot(Decimal("0.3"), Decimal("1")) == Decimal("1")


def test_round_up_to_lot_zero_lot_size_defaults_to_one():
	from pgappforge.plugins.erp.operations.mrp.services import _round_up_to_lot
	# lot_size=0 should default to 1
	result = _round_up_to_lot(Decimal("3.5"), Decimal("0"))
	assert result == Decimal("4")


# ---------------------------------------------------------------------------
# Model instantiation
# ---------------------------------------------------------------------------

def test_mrp_run_explicit_values():
	"""Column(default=...) fires at INSERT, not Python instantiation.
	Verify that explicitly-set values round-trip correctly."""
	from pgappforge.plugins.erp.operations.mrp.models import MRPRun
	run = MRPRun(
		tenant_id=_uuid4(),
		period="2025-06",
		status="IN_PROGRESS",
		horizon_days=90,
		planned_orders_count=0,
		purchase_reqs_count=0,
	)
	assert run.status == "IN_PROGRESS"
	assert run.horizon_days == 90
	assert run.planned_orders_count == 0
	assert run.purchase_reqs_count == 0
	assert run.period == "2025-06"


def test_mrp_product_config_explicit_values():
	"""Verify MRPProductConfig stores explicitly-passed values correctly."""
	from pgappforge.plugins.erp.operations.mrp.models import MRPProductConfig
	cfg = MRPProductConfig(
		tenant_id=_uuid4(),
		product_id=_uuid4(),
		procurement_type="EXTERNAL",
		lead_time_days=7,
		lot_size_qty=Decimal("1"),
		safety_stock_qty=Decimal("0"),
		reorder_point_qty=Decimal("0"),
	)
	assert cfg.procurement_type == "EXTERNAL"
	assert cfg.lead_time_days == 7
	assert cfg.lot_size_qty == Decimal("1")
	assert cfg.safety_stock_qty == Decimal("0")
	assert cfg.reorder_point_qty == Decimal("0")


def test_mrp_planned_order_explicit_values():
	"""Verify MRPPlannedOrder stores explicitly-passed values correctly."""
	from pgappforge.plugins.erp.operations.mrp.models import MRPPlannedOrder
	order = MRPPlannedOrder(
		tenant_id=_uuid4(),
		run_id=_uuid4(),
		product_id=_uuid4(),
		required_qty=Decimal("10"),
		planned_qty=Decimal("10"),
		required_date=date.today() + timedelta(days=30),
		planned_start_date=date.today() + timedelta(days=23),
		order_type="PURCHASE",
		status="PLANNED",
		converted_to_id=None,
	)
	assert order.status == "PLANNED"
	assert order.converted_to_id is None
	assert order.order_type == "PURCHASE"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_mrp_run_started_event_fields():
	from pgappforge.plugins.erp.operations.mrp.events import MRPRunStartedEvent
	ev = MRPRunStartedEvent(
		aggregate_id="run-1",
		aggregate_type="MRPRun",
		tenant_id="t1",
		run_id="run-1",
		period="2025-06",
		horizon_days=90,
	)
	assert ev.event_type == "ops.mrp.run.started"
	assert ev.run_id == "run-1"
	assert ev.horizon_days == 90
	assert ev.event_id  # auto-generated UUID


def test_planned_order_created_event_fields():
	from pgappforge.plugins.erp.operations.mrp.events import PlannedOrderCreatedEvent
	ev = PlannedOrderCreatedEvent(
		aggregate_id="o1",
		aggregate_type="MRPPlannedOrder",
		tenant_id="t1",
		order_id="o1",
		product_id="p1",
		required_qty="10.0000",
		planned_qty="10.0000",
		required_date="2025-07-01",
		planned_start_date="2025-06-24",
		order_type="PURCHASE",
		run_id="run-1",
	)
	assert ev.event_type == "ops.mrp.planned_order.created"
	assert ev.order_type == "PURCHASE"


def test_purchase_req_created_event_fields():
	from pgappforge.plugins.erp.operations.mrp.events import PurchaseRequisitionCreatedEvent
	ev = PurchaseRequisitionCreatedEvent(
		aggregate_id="r1",
		aggregate_type="MRPPlannedOrder",
		tenant_id="t1",
		req_id="r1",
		product_id="p1",
		qty="50.0000",
		supplier_id="s1",
		required_date="2025-07-01",
		run_id="run-1",
	)
	assert ev.event_type == "ops.mrp.purchase_req.created"
	assert ev.supplier_id == "s1"


def test_production_order_recommended_event_fields():
	from pgappforge.plugins.erp.operations.mrp.events import ProductionOrderRecommendedEvent
	ev = ProductionOrderRecommendedEvent(
		aggregate_id="o1",
		aggregate_type="MRPPlannedOrder",
		tenant_id="t1",
		product_id="p1",
		qty="100.0000",
		start_date="2025-06-01",
		end_date="2025-06-15",
		bom_id="bom-1",
		run_id="run-1",
	)
	assert ev.event_type == "ops.mrp.production_order.recommended"
	assert ev.bom_id == "bom-1"


def test_mrp_run_completed_event_fields():
	from pgappforge.plugins.erp.operations.mrp.events import MRPRunCompletedEvent
	ev = MRPRunCompletedEvent(
		aggregate_id="run-1",
		aggregate_type="MRPRun",
		tenant_id="t1",
		run_id="run-1",
		planned_orders_count=5,
		requisitions_count=3,
		duration_seconds=1.23,
		period="2025-06",
	)
	assert ev.event_type == "ops.mrp.run.completed"
	assert ev.planned_orders_count == 5
	assert ev.requisitions_count == 3


def test_safety_stock_breach_event_fields():
	from pgappforge.plugins.erp.operations.mrp.events import SafetyStockBreachEvent
	ev = SafetyStockBreachEvent(
		aggregate_id="p1",
		aggregate_type="Product",
		tenant_id="t1",
		product_id="p1",
		current_stock="5.0000",
		safety_stock_qty="20.0000",
		deficit="15.0000",
	)
	assert ev.event_type == "ops.mrp.safety_stock.breach"
	assert ev.deficit == "15.0000"


# ---------------------------------------------------------------------------
# check_safety_stock
# ---------------------------------------------------------------------------

def test_check_safety_stock_no_configs():
	from pgappforge.plugins.erp.operations.mrp.services import MRPService
	session = _make_session(rows=[])
	result = MRPService.check_safety_stock("tenant-1", session)
	assert result == []


def test_check_safety_stock_no_breach_above_safety():
	from pgappforge.plugins.erp.operations.mrp.models import MRPProductConfig
	from pgappforge.plugins.erp.operations.mrp.services import MRPService

	cfg = MRPProductConfig(
		tenant_id="t1",
		product_id="p1",
		safety_stock_qty=Decimal("10"),
	)
	session = _make_session(rows=[cfg])

	# current_stock = 50 (above safety_stock=10) — no breach
	with patch(
		"pgappforge.plugins.erp.operations.mrp.services._get_current_stock",
		return_value=Decimal("50"),
	):
		breaches = MRPService.check_safety_stock("t1", session)

	assert breaches == []


def test_check_safety_stock_breach_detected():
	from pgappforge.plugins.erp.operations.mrp.models import MRPProductConfig
	from pgappforge.plugins.erp.operations.mrp.services import MRPService

	cfg = MRPProductConfig(
		tenant_id="t1",
		product_id="p1",
		safety_stock_qty=Decimal("20"),
	)
	session = _make_session(rows=[cfg])

	with patch(
		"pgappforge.plugins.erp.operations.mrp.services._get_current_stock",
		return_value=Decimal("5"),
	), patch("pgappforge.plugins.erp.operations.mrp.services._emit"):
		breaches = MRPService.check_safety_stock("t1", session)

	assert len(breaches) == 1
	assert breaches[0]["product_id"] == "p1"
	assert Decimal(breaches[0]["deficit"]) == Decimal("15")


def test_check_safety_stock_zero_safety_stock_skipped():
	"""Products with safety_stock_qty=0 should never trigger breach."""
	from pgappforge.plugins.erp.operations.mrp.models import MRPProductConfig
	from pgappforge.plugins.erp.operations.mrp.services import MRPService

	cfg = MRPProductConfig(
		tenant_id="t1",
		product_id="p1",
		safety_stock_qty=Decimal("0"),
	)
	session = _make_session(rows=[cfg])

	with patch(
		"pgappforge.plugins.erp.operations.mrp.services._get_current_stock",
		return_value=Decimal("0"),
	):
		breaches = MRPService.check_safety_stock("t1", session)

	assert breaches == []


# ---------------------------------------------------------------------------
# run_mrp
# ---------------------------------------------------------------------------

def test_run_mrp_no_configs_completes():
	"""MRP run with zero product configs completes successfully with no orders."""
	from pgappforge.plugins.erp.operations.mrp.services import MRPService

	session = _make_session(rows=[])

	# Patch flush to auto-assign id to MRPRun
	created_objects: list = []

	def _fake_flush():
		for obj in created_objects:
			if not getattr(obj, "id", None):
				obj.id = _uuid4()

	session.flush = _fake_flush

	def _fake_add(obj):
		obj.id = _uuid4()
		created_objects.append(obj)

	session.add = _fake_add

	with patch("pgappforge.plugins.erp.operations.mrp.services._emit"):
		run = MRPService.run_mrp("tenant-1", session, horizon_days=90)

	assert run.status == "COMPLETED"
	assert run.planned_orders_count == 0
	assert run.purchase_reqs_count == 0


def test_run_mrp_with_external_product_demand():
	"""EXTERNAL product with demand > stock generates PURCHASE planned order."""
	from pgappforge.plugins.erp.operations.mrp.models import MRPProductConfig
	from pgappforge.plugins.erp.operations.mrp.services import MRPService

	cfg = MRPProductConfig(
		tenant_id="t1",
		product_id="prod-1",
		safety_stock_qty=Decimal("5"),
		reorder_point_qty=Decimal("10"),
		lot_size_qty=Decimal("10"),
		lead_time_days=7,
		procurement_type="EXTERNAL",
		preferred_supplier_id="sup-1",
	)

	created_objects: list = []

	session = MagicMock()

	def _fake_execute(stmt):
		result = MagicMock()
		scalars_result = MagicMock()
		# Return configs on first call, empty on subsequent (planned order queries)
		scalars_result.all.return_value = [cfg]
		scalars_result.scalar_one_or_none.return_value = None
		result.scalars.return_value = scalars_result
		result.scalar_one_or_none.return_value = None
		result.scalar.return_value = Decimal("0")
		return result

	session.execute = _fake_execute

	def _fake_add(obj):
		obj.id = _uuid4()
		created_objects.append(obj)

	session.add = _fake_add
	session.flush = MagicMock()

	demand_date = date.today() + timedelta(days=30)

	with (
		patch(
			"pgappforge.plugins.erp.operations.mrp.services._get_current_stock",
			return_value=Decimal("2"),		# below safety_stock=5 → net_req = demand - (2-5)
		),
		patch(
			"pgappforge.plugins.erp.operations.mrp.services._get_open_demand",
			return_value=[(Decimal("50"), demand_date)],
		),
		patch("pgappforge.plugins.erp.operations.mrp.services._emit"),
	):
		run = MRPService.run_mrp("t1", session, horizon_days=90)

	assert run.status == "COMPLETED"
	assert run.planned_orders_count >= 1
	assert run.purchase_reqs_count >= 1


# ---------------------------------------------------------------------------
# get_mrp_report
# ---------------------------------------------------------------------------

def test_get_mrp_report_not_found_raises():
	from pgappforge.plugins.erp.operations.mrp.services import MRPRunNotFoundError, MRPService

	session = MagicMock()
	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	session.execute.return_value = result

	try:
		MRPService.get_mrp_report("nonexistent-id", session)
		assert False, "Expected MRPRunNotFoundError"
	except MRPRunNotFoundError:
		pass


def test_get_mrp_report_structure():
	from pgappforge.plugins.erp.operations.mrp.models import MRPPlannedOrder, MRPRun
	from pgappforge.plugins.erp.operations.mrp.services import MRPService
	from datetime import datetime, timezone

	run = MRPRun(
		tenant_id="t1",
		period="2025-06",
		horizon_days=90,
		status="COMPLETED",
		started_at=datetime.now(timezone.utc),
	)
	run.id = _uuid4()

	order = MRPPlannedOrder(
		tenant_id="t1",
		run_id=run.id,
		product_id="p1",
		required_qty=Decimal("50"),
		planned_qty=Decimal("50"),
		required_date=date.today() + timedelta(days=30),
		planned_start_date=date.today() + timedelta(days=23),
		order_type="PURCHASE",
		status="PLANNED",
	)
	order.id = _uuid4()

	session = MagicMock()
	call_count = [0]

	def _fake_execute(stmt):
		call_count[0] += 1
		result = MagicMock()
		if call_count[0] == 1:
			result.scalar_one_or_none.return_value = run
		else:
			scalars = MagicMock()
			scalars.all.return_value = [order]
			result.scalars.return_value = scalars
		return result

	session.execute = _fake_execute

	report = MRPService.get_mrp_report(run.id, session)

	assert "run" in report
	assert "by_product" in report
	assert "by_type" in report
	assert "totals" in report
	assert report["run"]["period"] == "2025-06"
	assert report["totals"]["planned_orders_count"] == 1
	assert report["totals"]["purchase_orders_count"] == 1
	assert "p1" in report["by_product"]


# ---------------------------------------------------------------------------
# convert_to_po
# ---------------------------------------------------------------------------

def test_convert_to_po_not_found_raises():
	from pgappforge.plugins.erp.operations.mrp.services import MRPService, PlannedOrderNotFoundError

	session = MagicMock()
	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	session.execute.return_value = result

	try:
		MRPService.convert_to_po("bad-id", session)
		assert False, "Expected PlannedOrderNotFoundError"
	except PlannedOrderNotFoundError:
		pass


def test_convert_to_po_wrong_status_raises():
	from pgappforge.plugins.erp.operations.mrp.models import MRPPlannedOrder
	from pgappforge.plugins.erp.operations.mrp.services import InvalidMRPStatusError, MRPService

	order = MRPPlannedOrder(
		tenant_id="t1",
		run_id=_uuid4(),
		product_id="p1",
		required_qty=Decimal("10"),
		planned_qty=Decimal("10"),
		required_date=date.today() + timedelta(days=30),
		planned_start_date=date.today() + timedelta(days=23),
		order_type="PURCHASE",
		status="RELEASED",  # already released
	)
	order.id = _uuid4()

	session = MagicMock()
	result = MagicMock()
	result.scalar_one_or_none.return_value = order
	session.execute.return_value = result

	try:
		MRPService.convert_to_po(order.id, session)
		assert False, "Expected InvalidMRPStatusError"
	except InvalidMRPStatusError:
		pass


def test_convert_to_po_success():
	from pgappforge.plugins.erp.operations.mrp.models import MRPPlannedOrder, MRPProductConfig
	from pgappforge.plugins.erp.operations.mrp.services import MRPService

	order = MRPPlannedOrder(
		tenant_id="t1",
		run_id=_uuid4(),
		product_id="p1",
		required_qty=Decimal("50"),
		planned_qty=Decimal("50"),
		required_date=date.today() + timedelta(days=30),
		planned_start_date=date.today() + timedelta(days=23),
		order_type="PURCHASE",
		status="PLANNED",
	)
	order.id = _uuid4()

	cfg = MRPProductConfig(
		tenant_id="t1",
		product_id="p1",
		preferred_supplier_id="sup-1",
	)

	session = MagicMock()
	call_count = [0]

	def _fake_execute(stmt):
		call_count[0] += 1
		result = MagicMock()
		if call_count[0] == 1:
			result.scalar_one_or_none.return_value = order
		else:
			result.scalar_one_or_none.return_value = cfg
		return result

	session.execute = _fake_execute
	session.flush = MagicMock()

	# Patch the SCM import so the lazy-import path hits ImportError → stub PO ID
	with patch.dict("sys.modules", {"pgappforge.plugins.erp.operations.scm.services": None}):
		result = MRPService.convert_to_po(order.id, session)

	assert result["status"] == "RELEASED"
	assert result["product_id"] == "p1"
	assert result["qty"] == "50"
	assert order.status == "RELEASED"
	assert order.converted_to_id is not None


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

def test_mrp_plugin_metadata():
	from pgappforge.plugins.erp.operations.mrp import MRPPlugin

	plugin = MRPPlugin.__new__(MRPPlugin)
	plugin.config = {}
	meta = plugin.metadata

	assert meta.name == "mrp"
	assert "ops" in meta.tags
	assert "mrp" in meta.tags
	assert "manufacturing" in meta.tags
	assert meta.safe_mode_compatible is True


def test_mrp_plugin_events():
	from pgappforge.plugins.erp.operations.mrp import MRPPlugin

	plugin = MRPPlugin.__new__(MRPPlugin)
	events = plugin.get_events()

	assert "ops.mrp.run.started" in events
	assert "ops.mrp.planned_order.created" in events
	assert "ops.mrp.purchase_req.created" in events
	assert "ops.mrp.production_order.recommended" in events
	assert "ops.mrp.run.completed" in events
	assert "ops.mrp.safety_stock.breach" in events
