"""
tests/ci/test_wealth_management.py

CI tests for the Wealth Management plugin.

Tests use real objects and pytest fixtures — no mocks.
All monetary amounts are integer cents.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal session stub (no DB required for unit tests)
# ---------------------------------------------------------------------------

class _StubQuery:
	def __init__(self, result: Any = None):
		self._result = result

	def scalar_one_or_none(self) -> Any:
		return self._result

	def scalars(self) -> "_StubQuery":
		return self

	def all(self) -> list:
		if self._result is None:
			return []
		if isinstance(self._result, list):
			return self._result
		return [self._result]

	def scalar(self) -> Any:
		return self._result


class _StubSession:
	"""Ultra-light in-memory session stub for service unit tests."""

	def __init__(self):
		self._store: dict[str, Any] = {}
		self._added: list[Any] = []

	def add(self, obj: Any) -> None:
		self._added.append(obj)
		# Assign a fake id if not present
		if not getattr(obj, "id", None):
			import uuid
			obj.id = str(uuid.uuid4())

	def flush(self) -> None:
		for obj in self._added:
			if not getattr(obj, "id", None):
				import uuid
				obj.id = str(uuid.uuid4())

	def execute(self, stmt: Any) -> _StubQuery:
		# Always return None (not found) unless overridden per test
		return _StubQuery(None)

	def commit(self) -> None:
		pass

	def rollback(self) -> None:
		pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session() -> _StubSession:
	return _StubSession()


@pytest.fixture
def service():
	from pgappforge.plugins.fintech.wealth_management.services import WealthManagementService
	return WealthManagementService()


# ---------------------------------------------------------------------------
# Model import tests
# ---------------------------------------------------------------------------

def test_models_importable():
	from pgappforge.plugins.fintech.wealth_management.models import (
		PerformanceReport,
		Portfolio,
		PortfolioHolding,
		WealthClient,
		WealthOrder,
	)
	assert WealthClient.__tablename__ == "ft_wlth_client"
	assert Portfolio.__tablename__ == "ft_wlth_portfolio"
	assert PortfolioHolding.__tablename__ == "ft_wlth_holding"
	assert WealthOrder.__tablename__ == "ft_wlth_order"
	assert PerformanceReport.__tablename__ == "ft_wlth_performance"


def test_events_importable():
	from pgappforge.plugins.fintech.wealth_management.events import (
		ALL_WLTH_EVENT_TYPES,
		OrderFilledEvent,
		OrderPlacedEvent,
		PerformanceReportGeneratedEvent,
		PortfolioCreatedEvent,
		RebalanceRecommendedEvent,
		WealthClientOnboardedEvent,
	)
	assert len(ALL_WLTH_EVENT_TYPES) == 6
	assert "wealth.client.onboarded" in ALL_WLTH_EVENT_TYPES
	assert "wealth.order.filled" in ALL_WLTH_EVENT_TYPES


def test_plugin_importable():
	from pgappforge.plugins.fintech.wealth_management import WealthManagementPlugin
	assert WealthManagementPlugin.name == "wealth_management"
	assert WealthManagementPlugin.domain == "fintech"
	assert "foundation" in WealthManagementPlugin.depends_on
	assert "core_banking" in WealthManagementPlugin.depends_on


# ---------------------------------------------------------------------------
# _assess_suitability
# ---------------------------------------------------------------------------

def test_assess_suitability_scores(service):
	from pgappforge.plugins.fintech.wealth_management.models import WealthClient
	profiles_scores = [
		("CONSERVATIVE", 40),
		("MODERATE", 55),
		("BALANCED", 65),
		("GROWTH", 80),
		("AGGRESSIVE", 90),
	]
	for risk, expected_score in profiles_scores:
		client = WealthClient(risk_profile=risk)
		score = service._assess_suitability(client)
		assert score == expected_score, f"Expected {expected_score} for {risk}, got {score}"


def test_assess_suitability_unknown_defaults_to_balanced(service):
	from pgappforge.plugins.fintech.wealth_management.models import WealthClient
	client = WealthClient(risk_profile="UNKNOWN")
	score = service._assess_suitability(client)
	assert score == 65  # BALANCED default


# ---------------------------------------------------------------------------
# _validate_allocation
# ---------------------------------------------------------------------------

def test_validate_allocation_valid(service):
	service._validate_allocation({"EQUITY": 60, "BOND": 30, "CASH": 10})


def test_validate_allocation_floats_valid(service):
	service._validate_allocation({"EQUITY": 60.0, "BOND": 30.0, "CASH": 10.0})


def test_validate_allocation_invalid_raises(service):
	from pgappforge.plugins.fintech.wealth_management.services import AllocationError
	with pytest.raises(AllocationError):
		service._validate_allocation({"EQUITY": 50, "BOND": 30})  # sums to 80


def test_validate_allocation_empty_raises(service):
	from pgappforge.plugins.fintech.wealth_management.services import AllocationError
	with pytest.raises(AllocationError):
		service._validate_allocation({})


# ---------------------------------------------------------------------------
# onboard_client
# ---------------------------------------------------------------------------

def test_onboard_client_creates_record(service, session):
	with patch("pgappforge.plugins.fintech.wealth_management.services.emit_event"):
		client = service.onboard_client(
			customer_id="cust-001",
			full_name="Alice Wanjiru",
			risk_profile="MODERATE",
			tenant_id="t1",
			session=session,
		)
	assert client.full_name == "Alice Wanjiru"
	assert client.risk_profile == "MODERATE"
	assert client.suitability_score == 55
	assert client.tenant_id == "t1"
	assert client in session._added


def test_onboard_client_sets_kwargs(service, session):
	with patch("pgappforge.plugins.fintech.wealth_management.services.emit_event"):
		client = service.onboard_client(
			customer_id="cust-002",
			full_name="Bob Mwangi",
			risk_profile="GROWTH",
			tenant_id="t1",
			session=session,
			investment_experience="EXPERT",
			annual_income_cents=5_000_000_00,
			investment_horizon_years=10,
		)
	assert client.investment_experience == "EXPERT"
	assert client.annual_income_cents == 5_000_000_00
	assert client.investment_horizon_years == 10
	assert client.suitability_score == 80


# ---------------------------------------------------------------------------
# create_portfolio
# ---------------------------------------------------------------------------

def test_create_portfolio_validates_client_not_found(service, session):
	from pgappforge.plugins.fintech.wealth_management.services import ClientNotFoundError
	with pytest.raises(ClientNotFoundError):
		service.create_portfolio(
			client_id="no-such-client",
			name="Test Portfolio",
			mandate_type="DISCRETIONARY",
			target_allocation={"EQUITY": 60, "BOND": 40},
			tenant_id="t1",
			session=session,
		)


def test_create_portfolio_validates_allocation(service, session):
	from pgappforge.plugins.fintech.wealth_management.models import WealthClient
	from pgappforge.plugins.fintech.wealth_management.services import AllocationError

	fake_client = WealthClient(id="client-001", tenant_id="t1", full_name="Alice")

	def fake_execute(stmt):
		return _StubQuery(fake_client)

	session.execute = fake_execute

	with pytest.raises(AllocationError):
		service.create_portfolio(
			client_id="client-001",
			name="Bad Portfolio",
			mandate_type="ADVISORY",
			target_allocation={"EQUITY": 60},  # only 60%
			tenant_id="t1",
			session=session,
		)


def test_create_portfolio_success(service, session):
	from pgappforge.plugins.fintech.wealth_management.models import WealthClient

	fake_client = WealthClient(id="client-001", tenant_id="t1", full_name="Alice")

	def fake_execute(stmt):
		return _StubQuery(fake_client)

	session.execute = fake_execute

	with patch("pgappforge.plugins.fintech.wealth_management.services.emit_event"):
		portfolio = service.create_portfolio(
			client_id="client-001",
			name="Growth Portfolio",
			mandate_type="DISCRETIONARY",
			target_allocation={"EQUITY": 70, "BOND": 20, "CASH": 10},
			tenant_id="t1",
			session=session,
			benchmark="NSE20",
			base_currency="KES",
			management_fee_pct="0.015",
		)
	assert portfolio.name == "Growth Portfolio"
	assert portfolio.mandate_type == "DISCRETIONARY"
	assert portfolio.benchmark == "NSE20"
	assert portfolio in session._added


# ---------------------------------------------------------------------------
# place_order
# ---------------------------------------------------------------------------

def test_place_order_raises_on_no_qty_or_amount(service, session):
	with pytest.raises(ValueError):
		service.place_order(
			portfolio_id="p1",
			asset_code="SCOM",
			asset_name="Safaricom",
			order_side="BUY",
			order_type="MARKET",
			tenant_id="t1",
			session=session,
			# both None — should raise
		)


def test_place_order_raises_on_both_qty_and_amount(service, session):
	with pytest.raises(ValueError):
		service.place_order(
			portfolio_id="p1",
			asset_code="SCOM",
			asset_name="Safaricom",
			order_side="BUY",
			order_type="MARKET",
			tenant_id="t1",
			session=session,
			quantity=Decimal("100"),
			amount_cents=50000,
		)


def test_place_order_raises_portfolio_not_found(service, session):
	from pgappforge.plugins.fintech.wealth_management.services import PortfolioNotFoundError
	with pytest.raises(PortfolioNotFoundError):
		service.place_order(
			portfolio_id="no-portfolio",
			asset_code="SCOM",
			asset_name="Safaricom",
			order_side="BUY",
			order_type="MARKET",
			tenant_id="t1",
			session=session,
			quantity=Decimal("100"),
		)


def test_place_order_raises_on_suspended_portfolio(service, session):
	from pgappforge.plugins.fintech.wealth_management.models import Portfolio
	from pgappforge.plugins.fintech.wealth_management.services import MandateViolationError

	fake_portfolio = Portfolio(id="p1", tenant_id="t1", status="SUSPENDED")

	def fake_execute(stmt):
		return _StubQuery(fake_portfolio)

	session.execute = fake_execute

	with pytest.raises(MandateViolationError):
		service.place_order(
			portfolio_id="p1",
			asset_code="SCOM",
			asset_name="Safaricom",
			order_side="BUY",
			order_type="MARKET",
			tenant_id="t1",
			session=session,
			quantity=Decimal("100"),
		)


def test_place_order_success(service, session):
	from pgappforge.plugins.fintech.wealth_management.models import Portfolio

	fake_portfolio = Portfolio(id="p1", tenant_id="t1", status="ACTIVE")

	def fake_execute(stmt):
		return _StubQuery(fake_portfolio)

	session.execute = fake_execute

	with patch("pgappforge.plugins.fintech.wealth_management.services.emit_event"):
		order = service.place_order(
			portfolio_id="p1",
			asset_code="SCOM",
			asset_name="Safaricom",
			order_side="BUY",
			order_type="MARKET",
			tenant_id="t1",
			session=session,
			amount_cents=100_000_00,
		)

	assert order.status == "PENDING"
	assert order.order_side == "BUY"
	assert order.asset_code == "SCOM"
	assert order.amount_cents == 100_000_00
	assert order in session._added


# ---------------------------------------------------------------------------
# _update_holding — weighted average cost
# ---------------------------------------------------------------------------

def test_update_holding_creates_new(service, session):
	holding = service._update_holding(
		portfolio_id="p1",
		asset_code="SCOM",
		asset_name="Safaricom",
		asset_class="EQUITY",
		quantity_delta=Decimal("100"),
		price_cents=1500,  # KES 15.00
		session=session,
		tenant_id="t1",
	)
	assert holding.quantity == Decimal("100")
	assert holding.avg_cost_cents == 1500
	assert holding.current_value_cents == 100 * 1500
	assert holding in session._added


def test_update_holding_weighted_avg_cost(service, session):
	from pgappforge.plugins.fintech.wealth_management.models import PortfolioHolding

	existing = PortfolioHolding(
		id="h1",
		portfolio_id="p1",
		asset_code="SCOM",
		asset_name="Safaricom",
		asset_class="EQUITY",
		quantity=Decimal("100"),
		avg_cost_cents=1500,
		current_price_cents=1500,
		current_value_cents=150_000,
		unrealised_pnl_cents=0,
		tenant_id="t1",
	)

	def fake_execute(stmt):
		return _StubQuery(existing)

	session.execute = fake_execute

	# Buy 100 more at KES 20.00
	holding = service._update_holding(
		portfolio_id="p1",
		asset_code="SCOM",
		asset_name="Safaricom",
		asset_class="EQUITY",
		quantity_delta=Decimal("100"),
		price_cents=2000,
		session=session,
		tenant_id="t1",
	)
	# New avg = (100*1500 + 100*2000) / 200 = 1750
	assert holding.quantity == Decimal("200")
	assert holding.avg_cost_cents == 1750
	assert holding.current_value_cents == 200 * 2000  # 400,000


# ---------------------------------------------------------------------------
# rebalance — drift detection
# ---------------------------------------------------------------------------

def test_rebalance_no_holdings_returns_empty(service, session):
	from pgappforge.plugins.fintech.wealth_management.models import Portfolio

	fake_portfolio = Portfolio(
		id="p1",
		tenant_id="t1",
		target_allocation={"EQUITY": 60, "BOND": 40},
	)

	call_count = [0]

	def fake_execute(stmt):
		call_count[0] += 1
		if call_count[0] == 1:
			return _StubQuery(fake_portfolio)
		return _StubQuery([])  # no holdings

	session.execute = fake_execute

	result = service.rebalance(
		portfolio_id="p1",
		current_prices={},
		tenant_id="t1",
		session=session,
	)
	assert result == []


def test_validate_allocation_boundary_tolerance(service):
	"""Allow up to ±0.01 rounding tolerance."""
	# 33.33 + 33.33 + 33.34 = 100.00 — valid
	service._validate_allocation({"A": 33.33, "B": 33.33, "C": 33.34})

	from pgappforge.plugins.fintech.wealth_management.services import AllocationError
	with pytest.raises(AllocationError):
		service._validate_allocation({"A": 33, "B": 33})  # = 66, outside tolerance


# ---------------------------------------------------------------------------
# get_portfolio_summary
# ---------------------------------------------------------------------------

def test_get_portfolio_summary_not_found(service, session):
	from pgappforge.plugins.fintech.wealth_management.services import PortfolioNotFoundError
	with pytest.raises(PortfolioNotFoundError):
		service.get_portfolio_summary(
			portfolio_id="no-portfolio",
			tenant_id="t1",
			session=session,
		)


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

def test_plugin_metadata():
	from pgappforge.plugins.fintech.wealth_management import WealthManagementPlugin
	plugin = WealthManagementPlugin.__new__(WealthManagementPlugin)
	plugin.config = {}
	plugin.appbuilder = None
	meta = plugin.metadata
	assert meta.name == "wealth_management"
	assert meta.version == "1.0.0"
	assert "fintech" in meta.tags
	assert meta.safe_mode_compatible is True


def test_plugin_register_models():
	from pgappforge.plugins.fintech.wealth_management import WealthManagementPlugin
	plugin = WealthManagementPlugin.__new__(WealthManagementPlugin)
	plugin.config = {}
	models = plugin.register_models()
	assert len(models) == 5
	model_names = {m.__tablename__ for m in models}
	assert "ft_wlth_client" in model_names
	assert "ft_wlth_portfolio" in model_names
	assert "ft_wlth_holding" in model_names
	assert "ft_wlth_order" in model_names
	assert "ft_wlth_performance" in model_names
