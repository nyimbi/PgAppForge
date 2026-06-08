"""
tests/ci/test_spend_analytics_plugin.py

CI tests for Spend Analytics plugin.

Tests are import-only / unit-level — no database required.
"""
from __future__ import annotations

from decimal import Decimal


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

def test_spend_events_importable():
	from pgappforge.plugins.erp.procurement.spend_analytics.events import (
		SpendCubeComputedEvent,
		SavingsOpportunityIdentifiedEvent,
	)
	assert SpendCubeComputedEvent().event_type == "procurement.spend.cube.computed"
	assert (
		SavingsOpportunityIdentifiedEvent().event_type
		== "procurement.spend.savings.identified"
	)


def test_spend_model_importable():
	from pgappforge.plugins.erp.procurement.spend_analytics.models import SpendSnapshot
	assert SpendSnapshot.__tablename__ == "spd_snapshot"


def test_spend_service_importable():
	from pgappforge.plugins.erp.procurement.spend_analytics.services import (
		SpendAnalyticsService,
	)
	assert callable(SpendAnalyticsService)


def test_spend_plugin_importable():
	from pgappforge.plugins.erp.procurement.spend_analytics import (
		SpendAnalyticsPlugin,
		create_plugin,
	)
	assert SpendAnalyticsPlugin.name == "spend_analytics"
	assert SpendAnalyticsPlugin.domain == "procurement"
	assert "foundation" in SpendAnalyticsPlugin.depends_on
	assert "finance.ap" in SpendAnalyticsPlugin.depends_on


# ---------------------------------------------------------------------------
# SpendAnalyticsPlugin metadata
# ---------------------------------------------------------------------------

def test_spend_plugin_metadata():
	from pgappforge.plugins.erp.procurement.spend_analytics import SpendAnalyticsPlugin

	class _FakeAB:
		pass

	plugin = SpendAnalyticsPlugin(_FakeAB())
	meta = plugin.metadata
	assert meta.version == "1.0.0"
	assert "tail-spend" in meta.tags
	assert "analytics" in meta.tags
	events = plugin.get_events()
	assert "procurement.spend.cube.computed" in events
	models = plugin.register_models()
	assert len(models) == 1


# ---------------------------------------------------------------------------
# compute_spend_cube with stubbed session
# ---------------------------------------------------------------------------

def test_compute_spend_cube_empty_session():
	"""Returns zeros gracefully when AP query fails (no DB)."""
	from pgappforge.plugins.erp.procurement.spend_analytics.services import (
		SpendAnalyticsService,
	)

	class _FakeSession:
		def execute(self, *a, **kw):
			raise RuntimeError("no db")

	svc = SpendAnalyticsService()
	result = svc.compute_spend_cube(
		tenant_id="t1",
		from_period="2024-01",
		to_period="2024-03",
		session=_FakeSession(),
	)
	assert result["total_spent_cents"] == 0
	assert result["supplier_count"] == 0
	assert result["by_supplier"] == []
	assert "2024-01" in result["period_range"]


# ---------------------------------------------------------------------------
# get_tail_spend arithmetic
# ---------------------------------------------------------------------------

def test_get_tail_spend_arithmetic(monkeypatch):
	"""Tail-spend threshold arithmetic — no DB required."""
	from pgappforge.plugins.erp.procurement.spend_analytics.services import (
		SpendAnalyticsService,
	)

	# Patch compute_spend_cube to return controlled data
	suppliers = [
		{"supplier_id": "S1", "amount_cents": 80000, "invoice_count": 10},  # 80%
		{"supplier_id": "S2", "amount_cents": 15000, "invoice_count": 5},   # 15%
		{"supplier_id": "S3", "amount_cents": 5000,  "invoice_count": 2},   # 5%
	]
	cube = {
		"total_spent_cents": 100000,
		"supplier_count": 3,
		"by_supplier": suppliers,
		"period_range": "2024-01 to 2024-01",
	}

	svc = SpendAnalyticsService()
	monkeypatch.setattr(svc, "compute_spend_cube", lambda *a, **kw: cube)

	# threshold 10% → suppliers below 10 000 cents are tail
	result = svc.get_tail_spend("t1", threshold_pct=10.0, period="2024-01", session=None)
	# S3 (5 000) is below threshold; S2 (15 000) is above
	assert result["tail_suppliers"] == 1
	assert result["tail_spend_cents"] == 5000
	# consolidation_opportunity_pct = 1/3 * 100 ≈ 33.33
	assert Decimal(str(result["consolidation_opportunity_pct"])) > Decimal("33")
	assert result["suppliers"][0]["supplier_id"] == "S3"


# ---------------------------------------------------------------------------
# get_savings_opportunities with stubbed session
# ---------------------------------------------------------------------------

def test_get_savings_opportunities_empty():
	from pgappforge.plugins.erp.procurement.spend_analytics.services import (
		SpendAnalyticsService,
	)

	class _FakeSession:
		def execute(self, *a, **kw):
			raise RuntimeError("no db")

	svc = SpendAnalyticsService()
	opps = svc.get_savings_opportunities(tenant_id="t1", session=_FakeSession())
	assert opps == []
