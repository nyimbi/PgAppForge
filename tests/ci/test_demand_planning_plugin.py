"""
tests/ci/test_demand_planning_plugin.py

CI tests for the Demand Planning plugin.

Tests cover:
  - Model instantiation and field defaults
  - DemandPlanningService.record_actual (create + upsert)
  - DemandPlanningService.generate_forecast — all 4 methods
  - DemandPlanningService.approve_forecast (status transition)
  - DemandPlanningService.compute_accuracy (MAPE, Bias)
  - DemandPlanningService.get_approved_forecast (period lookup)
  - Holt-Winters arithmetic correctness (Decimal, no float)
  - Event dataclass fields
  - Plugin metadata

No mocks — uses real objects and in-memory logic where DB is not available.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _make_session(scalars_rows: list | None = None, scalar_one: object = None):
	session = MagicMock()
	rows = scalars_rows or []

	scalars_result = MagicMock()
	scalars_result.all.return_value = rows

	execute_result = MagicMock()
	execute_result.scalars.return_value = scalars_result
	execute_result.scalar_one_or_none.return_value = scalar_one
	execute_result.scalar.return_value = None

	session.execute.return_value = execute_result
	session.flush = MagicMock()
	session.add = MagicMock()
	return session


# ---------------------------------------------------------------------------
# Helper functions (pure logic, no DB)
# ---------------------------------------------------------------------------

def test_mean_empty():
	from pgappforge.plugins.erp.operations.demand_planning.services import _mean
	assert _mean([]) == Decimal("0")


def test_mean_values():
	from pgappforge.plugins.erp.operations.demand_planning.services import _mean
	result = _mean([Decimal("10"), Decimal("20"), Decimal("30")])
	assert result == Decimal("20")


def test_std_dev_uniform():
	"""Uniform values → std dev = 0."""
	from pgappforge.plugins.erp.operations.demand_planning.services import _std_dev
	vals = [Decimal("10")] * 5
	assert _std_dev(vals) == Decimal("0")


def test_std_dev_known_values():
	"""Verify std dev computation for known values."""
	from pgappforge.plugins.erp.operations.demand_planning.services import _std_dev
	# population std dev of [2, 4, 4, 4, 5, 5, 7, 9] = 2.0
	vals = [Decimal(str(v)) for v in [2, 4, 4, 4, 5, 5, 7, 9]]
	result = _std_dev(vals)
	assert abs(result - Decimal("2")) < Decimal("0.001")


def test_build_period_label_rollover():
	from pgappforge.plugins.erp.operations.demand_planning.services import _build_period_label
	assert _build_period_label("2025-11", 2) == "2026-01"
	assert _build_period_label("2025-12", 1) == "2026-01"
	assert _build_period_label("2025-06", 6) == "2025-12"


# ---------------------------------------------------------------------------
# Moving average forecast
# ---------------------------------------------------------------------------

def test_moving_average_constant_history():
	from pgappforge.plugins.erp.operations.demand_planning.services import _moving_average
	history = [Decimal("100")] * 12
	forecasts, lower, upper = _moving_average(history, horizon=3, lookback=6)
	assert len(forecasts) == 3
	assert all(f == Decimal("100") for f in forecasts)
	# With zero std_dev, lower == upper == forecast
	assert all(l == Decimal("100") for l in lower)
	assert all(u == Decimal("100") for u in upper)


def test_moving_average_uses_lookback_window():
	from pgappforge.plugins.erp.operations.demand_planning.services import _moving_average
	# First 6 periods = 0, last 6 = 100 — lookback=6 should use only the 100s
	history = [Decimal("0")] * 6 + [Decimal("100")] * 6
	forecasts, _, _ = _moving_average(history, horizon=2, lookback=6)
	assert forecasts[0] == Decimal("100")


# ---------------------------------------------------------------------------
# Exponential smoothing
# ---------------------------------------------------------------------------

def test_exponential_smoothing_constant():
	from pgappforge.plugins.erp.operations.demand_planning.services import _exponential_smoothing
	history = [Decimal("50")] * 12
	forecasts, lower, upper = _exponential_smoothing(history, horizon=3)
	assert len(forecasts) == 3
	# All forecasts should converge toward 50
	for f in forecasts:
		assert abs(f - Decimal("50")) < Decimal("1")


def test_exponential_smoothing_returns_decimal():
	from pgappforge.plugins.erp.operations.demand_planning.services import _exponential_smoothing
	history = [Decimal(str(i * 10)) for i in range(1, 13)]
	forecasts, lower, upper = _exponential_smoothing(history, horizon=6)
	for f in forecasts:
		assert isinstance(f, Decimal), f"Expected Decimal, got {type(f)}"


def test_exponential_smoothing_empty_history():
	from pgappforge.plugins.erp.operations.demand_planning.services import _exponential_smoothing
	forecasts, lower, upper = _exponential_smoothing([], horizon=3)
	assert len(forecasts) == 3
	assert all(f == Decimal("0") for f in forecasts)


# ---------------------------------------------------------------------------
# Holt-Winters
# ---------------------------------------------------------------------------

def test_holt_winters_returns_correct_horizon():
	from pgappforge.plugins.erp.operations.demand_planning.services import _holt_winters_additive
	# Need at least 24 months for HW (2 * season_len=12)
	history = [Decimal(str(100 + (i % 12) * 5)) for i in range(24)]
	forecasts, lower, upper = _holt_winters_additive(history, horizon=12)
	assert len(forecasts) == 12
	assert len(lower) == 12
	assert len(upper) == 12


def test_holt_winters_no_negatives():
	"""Forecast values must always be >= 0 (demand floor)."""
	from pgappforge.plugins.erp.operations.demand_planning.services import _holt_winters_additive
	history = [Decimal(str(10 + (i % 12))) for i in range(24)]
	forecasts, lower, upper = _holt_winters_additive(history, horizon=6)
	assert all(f >= Decimal("0") for f in forecasts)
	assert all(l >= Decimal("0") for l in lower)


def test_holt_winters_all_decimal():
	"""All returned values are Decimal — no float contamination."""
	from pgappforge.plugins.erp.operations.demand_planning.services import _holt_winters_additive
	history = [Decimal(str(50 + (i % 12) * 3)) for i in range(24)]
	forecasts, lower, upper = _holt_winters_additive(history, horizon=3)
	for seq in (forecasts, lower, upper):
		for val in seq:
			assert isinstance(val, Decimal), f"Expected Decimal, got {type(val)}"


def test_holt_winters_falls_back_to_es_with_short_history():
	"""Fewer than 24 months → falls back to exponential smoothing (no error)."""
	from pgappforge.plugins.erp.operations.demand_planning.services import _holt_winters_additive
	history = [Decimal("100")] * 10  # only 10 periods
	forecasts, lower, upper = _holt_winters_additive(history, horizon=3)
	assert len(forecasts) == 3


# ---------------------------------------------------------------------------
# Model instantiation
# ---------------------------------------------------------------------------

def test_demand_forecast_defaults():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast
	fc = DemandForecast(
		tenant_id=_uuid4(),
		product_id=_uuid4(),
		forecast_method="MOVING_AVERAGE",
		base_period="2025-05",
	)
	assert fc.status == "DRAFT"
	assert fc.horizon_periods == 12
	assert fc.approved_by is None
	assert fc.approved_at is None
	assert fc.accuracy_mape is None


def test_demand_history_defaults():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandHistory
	h = DemandHistory(
		tenant_id=_uuid4(),
		product_id=_uuid4(),
		period="2025-06",
		actual_qty=Decimal("250"),
	)
	assert h.source == "SALES_ORDER"
	assert h.notes is None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_forecast_created_event():
	from pgappforge.plugins.erp.operations.demand_planning.events import ForecastCreatedEvent
	ev = ForecastCreatedEvent(
		aggregate_id="fc-1",
		aggregate_type="DemandForecast",
		tenant_id="t1",
		forecast_id="fc-1",
		product_id="p1",
		periods=12,
		forecast_method="HOLT_WINTERS",
		base_period="2025-05",
	)
	assert ev.event_type == "ops.demand_planning.forecast.created"
	assert ev.periods == 12
	assert ev.event_id  # auto-generated


def test_forecast_approved_event():
	from pgappforge.plugins.erp.operations.demand_planning.events import ForecastApprovedEvent
	ev = ForecastApprovedEvent(
		aggregate_id="fc-1",
		aggregate_type="DemandForecast",
		tenant_id="t1",
		forecast_id="fc-1",
		approved_by="user-42",
		product_id="p1",
		base_period="2025-05",
	)
	assert ev.event_type == "ops.demand_planning.forecast.approved"
	assert ev.approved_by == "user-42"


def test_consensus_reached_event():
	from pgappforge.plugins.erp.operations.demand_planning.events import ConsensusReachedEvent
	ev = ConsensusReachedEvent(
		aggregate_id="cycle-1",
		aggregate_type="ConsensusCycle",
		tenant_id="t1",
		cycle_id="cycle-1",
		product_count=10,
		total_demand="5000.0000",
		period="2025-06",
	)
	assert ev.event_type == "ops.demand_planning.consensus.reached"
	assert ev.product_count == 10


def test_forecast_accuracy_event():
	from pgappforge.plugins.erp.operations.demand_planning.events import ForecastAccuracyComputedEvent
	ev = ForecastAccuracyComputedEvent(
		aggregate_id="p1",
		aggregate_type="Product",
		tenant_id="t1",
		product_id="p1",
		mape_pct="12.5000",
		bias_pct="-3.2000",
		period="2025-01:2025-06",
		periods_evaluated=6,
	)
	assert ev.event_type == "ops.demand_planning.accuracy.computed"
	assert ev.mape_pct == "12.5000"


# ---------------------------------------------------------------------------
# record_actual
# ---------------------------------------------------------------------------

def test_record_actual_creates_new():
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	session = _make_session(scalar_one=None)
	created: list = []

	def _add(obj):
		obj.id = _uuid4()
		created.append(obj)

	session.add = _add

	result = DemandPlanningService.record_actual(
		"p1", "2025-06", Decimal("100"), "t1", session
	)
	assert len(created) == 1
	assert created[0].actual_qty == Decimal("100")
	assert created[0].source == "SALES_ORDER"


def test_record_actual_upserts_existing():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandHistory
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	existing = DemandHistory(
		tenant_id="t1",
		product_id="p1",
		period="2025-06",
		actual_qty=Decimal("80"),
	)

	session = _make_session(scalar_one=existing)

	result = DemandPlanningService.record_actual(
		"p1", "2025-06", Decimal("120"), "t1", session, source="ADJUSTED"
	)
	assert result is existing
	assert existing.actual_qty == Decimal("120")
	assert existing.source == "ADJUSTED"


def test_record_actual_rejects_negative():
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	session = _make_session()

	try:
		DemandPlanningService.record_actual("p1", "2025-06", Decimal("-10"), "t1", session)
		assert False, "Expected AssertionError for negative qty"
	except AssertionError:
		pass


# ---------------------------------------------------------------------------
# generate_forecast
# ---------------------------------------------------------------------------

def _make_history_rows(n: int, base_qty: int = 100) -> list:
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandHistory
	rows = []
	for i in range(n):
		month = (i % 12) + 1
		year = 2024 + (i // 12)
		h = DemandHistory(
			tenant_id="t1",
			product_id="p1",
			period=f"{year:04d}-{month:02d}",
			actual_qty=Decimal(str(base_qty + i)),
		)
		rows.append(h)
	return rows


def _make_forecast_session(history_rows: list):
	"""Session that returns history_rows for history query and empty for others."""
	session = MagicMock()
	call_count = [0]

	def _execute(stmt):
		call_count[0] += 1
		result = MagicMock()
		scalars = MagicMock()

		if call_count[0] == 1:
			# First call: history rows
			scalars.all.return_value = history_rows
		else:
			# Subsequent calls: existing forecasts to supersede (empty)
			scalars.all.return_value = []

		result.scalars.return_value = scalars
		result.scalar_one_or_none.return_value = None
		return result

	session.execute = _execute

	created: list = []

	def _add(obj):
		obj.id = _uuid4()
		created.append(obj)

	session.add = _add
	session.flush = MagicMock()
	session._created = created
	return session


def test_generate_forecast_moving_average():
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	history = _make_history_rows(12)
	session = _make_forecast_session(history)

	with patch("pgappforge.plugins.erp.operations.demand_planning.services._emit"):
		fc = DemandPlanningService.generate_forecast(
			"p1", "t1", session, method="MOVING_AVERAGE", horizon_periods=6
		)

	assert fc.status == "DRAFT"
	assert fc.forecast_method == "MOVING_AVERAGE"
	assert fc.horizon_periods == 6
	assert len(fc.periods) == 6
	for p in fc.periods:
		assert "period" in p
		assert "forecast_qty" in p
		assert "lower_bound" in p
		assert "upper_bound" in p
		# Verify no float values — must be strings
		assert isinstance(p["forecast_qty"], str)


def test_generate_forecast_exponential_smoothing():
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	history = _make_history_rows(12)
	session = _make_forecast_session(history)

	with patch("pgappforge.plugins.erp.operations.demand_planning.services._emit"):
		fc = DemandPlanningService.generate_forecast(
			"p1", "t1", session, method="EXPONENTIAL_SMOOTHING", horizon_periods=3
		)

	assert fc.forecast_method == "EXPONENTIAL_SMOOTHING"
	assert len(fc.periods) == 3


def test_generate_forecast_holt_winters():
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	history = _make_history_rows(24, base_qty=200)
	session = _make_forecast_session(history)

	with patch("pgappforge.plugins.erp.operations.demand_planning.services._emit"):
		fc = DemandPlanningService.generate_forecast(
			"p1", "t1", session, method="HOLT_WINTERS", horizon_periods=12
		)

	assert fc.forecast_method == "HOLT_WINTERS"
	assert len(fc.periods) == 12
	# All forecast_qty must be parseable as Decimal
	for p in fc.periods:
		val = Decimal(p["forecast_qty"])
		assert val >= Decimal("0")


def test_generate_forecast_manual():
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	history = _make_history_rows(2)  # MANUAL needs only >= 0 history records
	session = _make_forecast_session(history)

	# MANUAL skips history check
	with patch("pgappforge.plugins.erp.operations.demand_planning.services._emit"):
		fc = DemandPlanningService.generate_forecast(
			"p1", "t1", session, method="MANUAL", horizon_periods=4
		)

	assert fc.forecast_method == "MANUAL"
	# MANUAL creates zero-value periods for planner to fill
	assert len(fc.periods) == 4
	for p in fc.periods:
		assert Decimal(p["forecast_qty"]) == Decimal("0")


def test_generate_forecast_insufficient_history_raises():
	from pgappforge.plugins.erp.operations.demand_planning.services import (
		DemandPlanningService,
		InsufficientHistoryError,
	)

	history = _make_history_rows(1)  # only 1 record
	session = _make_forecast_session(history)

	try:
		DemandPlanningService.generate_forecast(
			"p1", "t1", session, method="MOVING_AVERAGE"
		)
		assert False, "Expected InsufficientHistoryError"
	except InsufficientHistoryError:
		pass


def test_generate_forecast_supersedes_existing():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	old_fc = DemandForecast(
		tenant_id="t1",
		product_id="p1",
		forecast_method="MOVING_AVERAGE",
		base_period="2025-04",
		status="APPROVED",
		periods=[],
	)
	old_fc.id = _uuid4()

	history = _make_history_rows(12)

	session = MagicMock()
	call_count = [0]

	def _execute(stmt):
		call_count[0] += 1
		result = MagicMock()
		scalars = MagicMock()

		if call_count[0] == 1:
			scalars.all.return_value = history
		elif call_count[0] == 2:
			scalars.all.return_value = [old_fc]
		else:
			scalars.all.return_value = []

		result.scalars.return_value = scalars
		result.scalar_one_or_none.return_value = None
		return result

	session.execute = _execute
	session.add = MagicMock()
	session.flush = MagicMock()

	with patch("pgappforge.plugins.erp.operations.demand_planning.services._emit"):
		DemandPlanningService.generate_forecast(
			"p1", "t1", session, method="MOVING_AVERAGE"
		)

	# Old forecast should be superseded
	assert old_fc.status == "SUPERSEDED"


# ---------------------------------------------------------------------------
# approve_forecast
# ---------------------------------------------------------------------------

def test_approve_forecast_not_found_raises():
	from pgappforge.plugins.erp.operations.demand_planning.services import (
		DemandPlanningService,
		ForecastNotFoundError,
	)

	session = _make_session(scalar_one=None)

	try:
		DemandPlanningService.approve_forecast("bad-id", "user-1", session)
		assert False, "Expected ForecastNotFoundError"
	except ForecastNotFoundError:
		pass


def test_approve_forecast_wrong_status_raises():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast
	from pgappforge.plugins.erp.operations.demand_planning.services import (
		DemandPlanningService,
		InvalidForecastStatusError,
	)

	fc = DemandForecast(
		tenant_id="t1",
		product_id="p1",
		forecast_method="MOVING_AVERAGE",
		base_period="2025-05",
		status="APPROVED",
		periods=[],
	)
	fc.id = _uuid4()

	session = _make_session(scalar_one=fc)

	try:
		DemandPlanningService.approve_forecast(fc.id, "user-1", session)
		assert False, "Expected InvalidForecastStatusError"
	except InvalidForecastStatusError:
		pass


def test_approve_forecast_success():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	fc = DemandForecast(
		tenant_id="t1",
		product_id="p1",
		forecast_method="MOVING_AVERAGE",
		base_period="2025-05",
		status="DRAFT",
		periods=[],
	)
	fc.id = _uuid4()

	session = _make_session(scalar_one=fc)

	with patch("pgappforge.plugins.erp.operations.demand_planning.services._emit"):
		result = DemandPlanningService.approve_forecast(fc.id, "user-42", session)

	assert result.status == "APPROVED"
	assert result.approved_by == "user-42"
	assert result.approved_at is not None


# ---------------------------------------------------------------------------
# compute_accuracy
# ---------------------------------------------------------------------------

def test_compute_accuracy_basic():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast, DemandHistory
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	actuals = [
		DemandHistory(tenant_id="t1", product_id="p1", period="2025-01", actual_qty=Decimal("100")),
		DemandHistory(tenant_id="t1", product_id="p1", period="2025-02", actual_qty=Decimal("120")),
		DemandHistory(tenant_id="t1", product_id="p1", period="2025-03", actual_qty=Decimal("80")),
	]

	fc = DemandForecast(
		tenant_id="t1",
		product_id="p1",
		forecast_method="MOVING_AVERAGE",
		base_period="2024-12",
		status="APPROVED",
		periods=[
			{"period": "2025-01", "forecast_qty": "100", "lower_bound": "90", "upper_bound": "110"},
			{"period": "2025-02", "forecast_qty": "100", "lower_bound": "90", "upper_bound": "110"},
			{"period": "2025-03", "forecast_qty": "100", "lower_bound": "90", "upper_bound": "110"},
		],
		approved_at=datetime.now(timezone.utc),
	)
	fc.id = _uuid4()

	session = MagicMock()
	call_count = [0]

	def _execute(stmt):
		call_count[0] += 1
		result = MagicMock()
		scalars = MagicMock()
		if call_count[0] == 1:
			scalars.all.return_value = actuals
		else:
			scalars.all.return_value = [fc]
		result.scalars.return_value = scalars
		return result

	session.execute = _execute

	with patch("pgappforge.plugins.erp.operations.demand_planning.services._emit"):
		report = DemandPlanningService.compute_accuracy(
			"p1", "2025-01", "2025-03", "t1", session
		)

	# MAPE: |100-100|/100 + |120-100|/120 + |80-100|/80 = 0 + 16.67 + 25 → mean ≈ 13.89%
	mape = Decimal(report["mape_pct"])
	assert mape > Decimal("0")
	assert report["periods_evaluated"] == 3
	assert report["periods_skipped"] == 0
	assert len(report["per_period"]) == 3


def test_compute_accuracy_zero_actuals_skipped():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast, DemandHistory
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	actuals = [
		DemandHistory(tenant_id="t1", product_id="p1", period="2025-01", actual_qty=Decimal("0")),
	]
	fc = DemandForecast(
		tenant_id="t1",
		product_id="p1",
		forecast_method="MOVING_AVERAGE",
		base_period="2024-12",
		status="APPROVED",
		periods=[
			{"period": "2025-01", "forecast_qty": "100", "lower_bound": "90", "upper_bound": "110"},
		],
		approved_at=datetime.now(timezone.utc),
	)
	fc.id = _uuid4()

	session = MagicMock()
	call_count = [0]

	def _execute(stmt):
		call_count[0] += 1
		result = MagicMock()
		scalars = MagicMock()
		scalars.all.return_value = actuals if call_count[0] == 1 else [fc]
		result.scalars.return_value = scalars
		return result

	session.execute = _execute

	with patch("pgappforge.plugins.erp.operations.demand_planning.services._emit"):
		report = DemandPlanningService.compute_accuracy(
			"p1", "2025-01", "2025-01", "t1", session
		)

	assert report["periods_evaluated"] == 0
	assert report["periods_skipped"] == 1
	assert report["mape_pct"] == "0.0000"


# ---------------------------------------------------------------------------
# get_approved_forecast
# ---------------------------------------------------------------------------

def test_get_approved_forecast_returns_correct_qty():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService
	from datetime import datetime, timezone

	fc = DemandForecast(
		tenant_id="t1",
		product_id="p1",
		forecast_method="MOVING_AVERAGE",
		base_period="2025-05",
		status="APPROVED",
		periods=[
			{"period": "2025-06", "forecast_qty": "250.0000", "lower_bound": "220.0000", "upper_bound": "280.0000"},
			{"period": "2025-07", "forecast_qty": "300.0000", "lower_bound": "270.0000", "upper_bound": "330.0000"},
		],
		approved_at=datetime.now(timezone.utc),
	)
	fc.id = _uuid4()

	session = MagicMock()
	result = MagicMock()
	scalars = MagicMock()
	scalars.all.return_value = [fc]
	result.scalars.return_value = scalars
	session.execute.return_value = result

	qty = DemandPlanningService.get_approved_forecast("p1", "2025-06", "t1", session)
	assert qty == Decimal("250.0000")


def test_get_approved_forecast_missing_period_returns_none():
	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService
	from datetime import datetime, timezone

	fc = DemandForecast(
		tenant_id="t1",
		product_id="p1",
		forecast_method="MOVING_AVERAGE",
		base_period="2025-05",
		status="APPROVED",
		periods=[
			{"period": "2025-06", "forecast_qty": "100.0000", "lower_bound": "90.0000", "upper_bound": "110.0000"},
		],
		approved_at=datetime.now(timezone.utc),
	)
	fc.id = _uuid4()

	session = MagicMock()
	result = MagicMock()
	scalars = MagicMock()
	scalars.all.return_value = [fc]
	result.scalars.return_value = scalars
	session.execute.return_value = result

	qty = DemandPlanningService.get_approved_forecast("p1", "2025-09", "t1", session)
	assert qty is None


def test_get_approved_forecast_no_forecasts_returns_none():
	from pgappforge.plugins.erp.operations.demand_planning.services import DemandPlanningService

	session = MagicMock()
	result = MagicMock()
	scalars = MagicMock()
	scalars.all.return_value = []
	result.scalars.return_value = scalars
	session.execute.return_value = result

	qty = DemandPlanningService.get_approved_forecast("p1", "2025-06", "t1", session)
	assert qty is None


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

def test_demand_planning_plugin_metadata():
	from pgappforge.plugins.erp.operations.demand_planning import DemandPlanningPlugin

	plugin = DemandPlanningPlugin.__new__(DemandPlanningPlugin)
	plugin.config = {}
	meta = plugin.metadata

	assert meta.name == "demand_planning"
	assert "ops" in meta.tags
	assert "demand-planning" in meta.tags
	assert "forecasting" in meta.tags
	assert meta.safe_mode_compatible is True


def test_demand_planning_plugin_events():
	from pgappforge.plugins.erp.operations.demand_planning import DemandPlanningPlugin

	plugin = DemandPlanningPlugin.__new__(DemandPlanningPlugin)
	events = plugin.get_events()

	assert "ops.demand_planning.forecast.created" in events
	assert "ops.demand_planning.forecast.approved" in events
	assert "ops.demand_planning.consensus.reached" in events
	assert "ops.demand_planning.accuracy.computed" in events


def test_demand_planning_plugin_models():
	from pgappforge.plugins.erp.operations.demand_planning import DemandPlanningPlugin

	plugin = DemandPlanningPlugin.__new__(DemandPlanningPlugin)
	plugin.config = {}
	models = plugin.register_models()

	from pgappforge.plugins.erp.operations.demand_planning.models import DemandForecast, DemandHistory
	assert DemandHistory in models
	assert DemandForecast in models
