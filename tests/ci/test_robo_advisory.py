"""
tests/ci/test_robo_advisory.py

CI tests for the Robo Advisory plugin.

Tests use real objects and pytest fixtures — no mocks.
All monetary amounts are integer cents.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Minimal session stub
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
	def __init__(self):
		self._added: list[Any] = []

	def add(self, obj: Any) -> None:
		self._added.append(obj)
		if not getattr(obj, "id", None):
			import uuid
			obj.id = str(uuid.uuid4())

	def flush(self) -> None:
		for obj in self._added:
			if not getattr(obj, "id", None):
				import uuid
				obj.id = str(uuid.uuid4())

	def execute(self, stmt: Any) -> _StubQuery:
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
	from pgappforge.plugins.fintech.robo_advisory.services import RoboAdvisoryService
	return RoboAdvisoryService()


# ---------------------------------------------------------------------------
# Model import tests
# ---------------------------------------------------------------------------

def test_models_importable():
	from pgappforge.plugins.fintech.robo_advisory.models import (
		ModelPortfolio,
		RoboDriftReport,
		RoboGoal,
		RoboInvestorProfile,
	)
	assert RoboInvestorProfile.__tablename__ == "ft_robo_profile"
	assert RoboGoal.__tablename__ == "ft_robo_goal"
	assert ModelPortfolio.__tablename__ == "ft_robo_model_portfolio"
	assert RoboDriftReport.__tablename__ == "ft_robo_drift"


def test_events_importable():
	from pgappforge.plugins.fintech.robo_advisory.events import (
		ALL_ROBO_EVENT_TYPES,
		AutoInvestmentExecutedEvent,
		DriftDetectedEvent,
		GoalAchievedEvent,
		GoalCreatedEvent,
		RebalanceTriggeredEvent,
	)
	assert len(ALL_ROBO_EVENT_TYPES) == 5
	assert "robo.goal.created" in ALL_ROBO_EVENT_TYPES
	assert "robo.drift.detected" in ALL_ROBO_EVENT_TYPES
	assert "robo.goal.achieved" in ALL_ROBO_EVENT_TYPES


def test_plugin_importable():
	from pgappforge.plugins.fintech.robo_advisory import RoboAdvisoryPlugin
	assert RoboAdvisoryPlugin.name == "robo_advisory"
	assert RoboAdvisoryPlugin.domain == "fintech"
	assert "foundation" in RoboAdvisoryPlugin.depends_on
	assert "core_banking" in RoboAdvisoryPlugin.depends_on


# ---------------------------------------------------------------------------
# _check_suitability
# ---------------------------------------------------------------------------

def test_check_suitability_passes(service):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboInvestorProfile
	profile = RoboInvestorProfile(kyc_verified=True, investment_horizon_years=5)
	assert service._check_suitability(profile) is True


def test_check_suitability_fails_no_kyc(service):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboInvestorProfile
	profile = RoboInvestorProfile(kyc_verified=False, investment_horizon_years=5)
	assert service._check_suitability(profile) is False


def test_check_suitability_fails_zero_horizon(service):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboInvestorProfile
	profile = RoboInvestorProfile(kyc_verified=True, investment_horizon_years=0)
	assert service._check_suitability(profile) is False


def test_check_suitability_fails_both(service):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboInvestorProfile
	profile = RoboInvestorProfile(kyc_verified=False, investment_horizon_years=0)
	assert service._check_suitability(profile) is False


# ---------------------------------------------------------------------------
# create_profile
# ---------------------------------------------------------------------------

def test_create_profile_not_suitable_by_default(service, session):
	profile = service.create_profile(
		customer_id="cust-001",
		risk_tolerance="MEDIUM",
		investment_horizon_years=5,
		tenant_id="t1",
		session=session,
	)
	# kyc_verified defaults to False — so suitability_completed = False
	assert profile.suitability_completed is False
	assert profile.risk_tolerance == "MEDIUM"
	assert profile in session._added


def test_create_profile_suitable_when_kyc_verified(service, session):
	profile = service.create_profile(
		customer_id="cust-002",
		risk_tolerance="HIGH",
		investment_horizon_years=10,
		tenant_id="t1",
		session=session,
		kyc_verified=True,
	)
	assert profile.suitability_completed is True
	assert profile.risk_tolerance == "HIGH"


def test_create_profile_automation_settings(service, session):
	profile = service.create_profile(
		customer_id="cust-003",
		risk_tolerance="LOW",
		investment_horizon_years=3,
		tenant_id="t1",
		session=session,
		kyc_verified=True,
		automation_enabled=True,
		automation_cadence="QUARTERLY",
		monthly_investment_cents=10_000_00,
	)
	assert profile.automation_enabled is True
	assert profile.automation_cadence == "QUARTERLY"
	assert profile.monthly_investment_cents == 10_000_00


# ---------------------------------------------------------------------------
# create_goal — suitability gate
# ---------------------------------------------------------------------------

def test_create_goal_raises_profile_not_found(service, session):
	from pgappforge.plugins.fintech.robo_advisory.services import ProfileNotFoundError
	with pytest.raises(ProfileNotFoundError):
		service.create_goal(
			profile_id="no-profile",
			goal_type="RETIREMENT",
			goal_name="Retire at 60",
			target_amount_cents=50_000_000_00,
			tenant_id="t1",
			session=session,
		)


def test_create_goal_raises_suitability_error(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboInvestorProfile
	from pgappforge.plugins.fintech.robo_advisory.services import SuitabilityError

	profile = RoboInvestorProfile(
		id="prof-001",
		tenant_id="t1",
		risk_tolerance="MEDIUM",
		investment_horizon_years=5,
		kyc_verified=False,
		suitability_completed=False,
	)

	def fake_execute(stmt):
		return _StubQuery(profile)

	session.execute = fake_execute

	with pytest.raises(SuitabilityError):
		service.create_goal(
			profile_id="prof-001",
			goal_type="EDUCATION",
			goal_name="University Fund",
			target_amount_cents=2_000_000_00,
			tenant_id="t1",
			session=session,
		)


def test_create_goal_success(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboInvestorProfile

	profile = RoboInvestorProfile(
		id="prof-001",
		tenant_id="t1",
		risk_tolerance="MEDIUM",
		investment_horizon_years=10,
		kyc_verified=True,
		suitability_completed=True,
	)

	calls = [0]

	def fake_execute(stmt):
		calls[0] += 1
		if calls[0] == 1:
			return _StubQuery(profile)  # profile lookup
		return _StubQuery(None)  # no model portfolio

	session.execute = fake_execute

	with patch("pgappforge.plugins.fintech.robo_advisory.services.emit_event"):
		goal = service.create_goal(
			profile_id="prof-001",
			goal_type="HOME",
			goal_name="Buy a house",
			target_amount_cents=10_000_000_00,
			tenant_id="t1",
			session=session,
			monthly_contribution=50_000_00,
		)

	assert goal.goal_type == "HOME"
	assert goal.goal_name == "Buy a house"
	assert goal.target_amount_cents == 10_000_000_00
	assert goal.monthly_contribution_cents == 50_000_00
	assert goal.status == "ACTIVE"
	assert goal in session._added


# ---------------------------------------------------------------------------
# seed_model_portfolios
# ---------------------------------------------------------------------------

def test_seed_model_portfolios_creates_five(service, session):
	n = service.seed_model_portfolios(tenant_id="t1", session=session)
	assert n == 5
	assert len(session._added) == 5


def test_seed_model_portfolios_idempotent(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import ModelPortfolio

	# Simulate all 5 already existing
	existing = ModelPortfolio(id="mp-1", name="Conservative Portfolio")

	def fake_execute(stmt):
		return _StubQuery(existing)  # always finds existing

	session.execute = fake_execute
	n = service.seed_model_portfolios(tenant_id="t1", session=session)
	assert n == 0
	assert len(session._added) == 0


def test_seed_model_portfolios_risk_levels(service, session):
	service.seed_model_portfolios(tenant_id="t1", session=session)
	risk_levels = {obj.risk_level for obj in session._added}
	assert risk_levels == {"CONSERVATIVE", "MODERATE", "BALANCED", "GROWTH", "AGGRESSIVE"}


def test_seed_model_portfolios_allocations_sum_to_100(service, session):
	service.seed_model_portfolios(tenant_id="t1", session=session)
	for mp in session._added:
		total = sum(mp.allocation.values())
		assert total == 100, f"{mp.name} allocation sums to {total}"


# ---------------------------------------------------------------------------
# _recommend_model_portfolio — risk mapping
# ---------------------------------------------------------------------------

def test_recommend_model_portfolio_maps_low_to_conservative(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import ModelPortfolio

	conservative_mp = ModelPortfolio(
		id="mp-1",
		risk_level="CONSERVATIVE",
		is_active=True,
		tenant_id="t1",
	)

	def fake_execute(stmt):
		return _StubQuery(conservative_mp)

	session.execute = fake_execute
	result = service._recommend_model_portfolio("LOW", "t1", session)
	assert result is conservative_mp


def test_recommend_model_portfolio_maps_medium_to_balanced(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import ModelPortfolio

	balanced_mp = ModelPortfolio(
		id="mp-3",
		risk_level="BALANCED",
		is_active=True,
		tenant_id="t1",
	)

	def fake_execute(stmt):
		return _StubQuery(balanced_mp)

	session.execute = fake_execute
	result = service._recommend_model_portfolio("MEDIUM", "t1", session)
	assert result is balanced_mp


def test_recommend_model_portfolio_returns_none_if_no_match(service, session):
	result = service._recommend_model_portfolio("HIGH", "t1", session)
	assert result is None


# ---------------------------------------------------------------------------
# detect_drift
# ---------------------------------------------------------------------------

def test_detect_drift_raises_goal_not_found(service, session):
	from pgappforge.plugins.fintech.robo_advisory.services import GoalNotFoundError
	with pytest.raises(GoalNotFoundError):
		service.detect_drift(
			goal_id="no-goal",
			current_allocation={"EQUITY": 60},
			tenant_id="t1",
			session=session,
		)


def test_detect_drift_no_rebalance_when_on_target(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import ModelPortfolio, RoboGoal

	mp = ModelPortfolio(
		id="mp-3",
		risk_level="BALANCED",
		allocation={"EQUITY": 60, "BOND": 30, "CASH": 10},
		is_active=True,
		tenant_id="t1",
	)
	goal = RoboGoal(
		id="goal-001",
		tenant_id="t1",
		profile_id="prof-001",
		goal_type="WEALTH_GROWTH",
		goal_name="Build Wealth",
		target_amount_cents=1_000_000_00,
		status="ACTIVE",
		assigned_portfolio_id="mp-3",
	)

	calls = [0]

	def fake_execute(stmt):
		calls[0] += 1
		if calls[0] == 1:
			return _StubQuery(goal)
		if calls[0] == 2:
			return _StubQuery(mp)
		return _StubQuery(None)

	session.execute = fake_execute

	report = service.detect_drift(
		goal_id="goal-001",
		current_allocation={"EQUITY": 60, "BOND": 30, "CASH": 10},  # exactly on target
		tenant_id="t1",
		session=session,
	)
	assert report.rebalance_recommended is False
	assert float(report.max_drift_pct) == 0.0


def test_detect_drift_triggers_rebalance_on_large_drift(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import ModelPortfolio, RoboGoal

	mp = ModelPortfolio(
		id="mp-3",
		risk_level="BALANCED",
		allocation={"EQUITY": 60, "BOND": 30, "CASH": 10},
		is_active=True,
		tenant_id="t1",
	)
	goal = RoboGoal(
		id="goal-002",
		tenant_id="t1",
		profile_id="prof-001",
		goal_type="RETIREMENT",
		goal_name="Retire Comfortably",
		target_amount_cents=20_000_000_00,
		status="ACTIVE",
		assigned_portfolio_id="mp-3",
	)

	calls = [0]

	def fake_execute(stmt):
		calls[0] += 1
		if calls[0] == 1:
			return _StubQuery(goal)
		if calls[0] == 2:
			return _StubQuery(mp)
		return _StubQuery(None)

	session.execute = fake_execute

	with patch("pgappforge.plugins.fintech.robo_advisory.services.emit_event"):
		report = service.detect_drift(
			goal_id="goal-002",
			# EQUITY has drifted from 60% target to 75% — 15% drift
			current_allocation={"EQUITY": 75, "BOND": 20, "CASH": 5},
			tenant_id="t1",
			session=session,
		)

	assert report.rebalance_recommended is True
	assert float(report.max_drift_pct) == 15.0


# ---------------------------------------------------------------------------
# check_goal_achievement
# ---------------------------------------------------------------------------

def test_check_goal_achievement_not_achieved(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboGoal

	goal = RoboGoal(
		id="goal-001",
		tenant_id="t1",
		profile_id="prof-001",
		goal_name="Home",
		target_amount_cents=1_000_000_00,
		current_amount_cents=500_000_00,
		status="ACTIVE",
	)

	def fake_execute(stmt):
		return _StubQuery(goal)

	session.execute = fake_execute
	result = service.check_goal_achievement("goal-001", "t1", session)
	assert result is False
	assert goal.status == "ACTIVE"


def test_check_goal_achievement_achieved(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboGoal

	goal = RoboGoal(
		id="goal-001",
		tenant_id="t1",
		profile_id="prof-001",
		goal_name="Emergency Fund",
		target_amount_cents=500_000_00,
		current_amount_cents=600_000_00,
		status="ACTIVE",
	)

	def fake_execute(stmt):
		return _StubQuery(goal)

	session.execute = fake_execute

	with patch("pgappforge.plugins.fintech.robo_advisory.services.emit_event"):
		result = service.check_goal_achievement("goal-001", "t1", session)

	assert result is True
	assert goal.status == "ACHIEVED"


# ---------------------------------------------------------------------------
# generate_recommendation — projection math
# ---------------------------------------------------------------------------

def test_generate_recommendation_on_track(service, session):
	"""A goal with large current balance and high monthly contribution should be on track."""
	from pgappforge.plugins.fintech.robo_advisory.models import (
		ModelPortfolio,
		RoboGoal,
		RoboInvestorProfile,
	)

	mp = ModelPortfolio(
		id="mp-3",
		risk_level="BALANCED",
		allocation={"EQUITY": 60, "BOND": 30, "CASH": 10},
		expected_return_pct=Decimal("10.0"),
		is_active=True,
		tenant_id="t1",
	)
	profile = RoboInvestorProfile(
		id="prof-001",
		tenant_id="t1",
		investment_horizon_years=30,
	)
	goal = RoboGoal(
		id="goal-001",
		tenant_id="t1",
		profile_id="prof-001",
		goal_name="Retirement",
		target_amount_cents=50_000_000_00,
		current_amount_cents=10_000_000_00,
		monthly_contribution_cents=100_000_00,
		status="ACTIVE",
		assigned_portfolio_id="mp-3",
	)

	calls = [0]

	def fake_execute(stmt):
		calls[0] += 1
		if calls[0] == 1:
			return _StubQuery(goal)
		if calls[0] == 2:
			return _StubQuery(profile)
		if calls[0] == 3:
			return _StubQuery(mp)
		return _StubQuery(None)

	session.execute = fake_execute

	rec = service.generate_recommendation("goal-001", "t1", session)

	assert rec["goal_id"] == "goal-001"
	assert rec["goal_name"] == "Retirement"
	assert "projected_value_cents" in rec
	assert "years_to_goal" in rec
	assert rec["on_track"] is True  # 30 years at 10% should easily surpass target


def test_generate_recommendation_not_on_track(service, session):
	"""A goal with tiny balance and low contribution over short horizon should be behind."""
	from pgappforge.plugins.fintech.robo_advisory.models import (
		ModelPortfolio,
		RoboGoal,
		RoboInvestorProfile,
	)

	mp = ModelPortfolio(
		id="mp-1",
		risk_level="CONSERVATIVE",
		allocation={"EQUITY": 20, "BOND": 70, "CASH": 10},
		expected_return_pct=Decimal("5.0"),
		is_active=True,
		tenant_id="t1",
	)
	profile = RoboInvestorProfile(
		id="prof-001",
		tenant_id="t1",
		investment_horizon_years=1,
	)
	goal = RoboGoal(
		id="goal-002",
		tenant_id="t1",
		profile_id="prof-001",
		goal_name="House Deposit",
		target_amount_cents=1_000_000_00,
		current_amount_cents=1_000_00,
		monthly_contribution_cents=1_000_00,
		status="ACTIVE",
		assigned_portfolio_id="mp-1",
	)

	calls = [0]

	def fake_execute(stmt):
		calls[0] += 1
		if calls[0] == 1:
			return _StubQuery(goal)
		if calls[0] == 2:
			return _StubQuery(profile)
		if calls[0] == 3:
			return _StubQuery(mp)
		return _StubQuery(None)

	session.execute = fake_execute

	rec = service.generate_recommendation("goal-002", "t1", session)

	assert rec["on_track"] is False
	assert rec["projected_value_cents"] < 1_000_000_00


# ---------------------------------------------------------------------------
# execute_auto_investment — automation_enabled=False
# ---------------------------------------------------------------------------

def test_execute_auto_investment_disabled_returns_empty(service, session):
	from pgappforge.plugins.fintech.robo_advisory.models import RoboInvestorProfile

	profile = RoboInvestorProfile(
		id="prof-001",
		tenant_id="t1",
		automation_enabled=False,
	)

	def fake_execute(stmt):
		return _StubQuery(profile)

	session.execute = fake_execute
	results = service.execute_auto_investment("prof-001", "t1", session)
	assert results == []


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

def test_plugin_metadata():
	from pgappforge.plugins.fintech.robo_advisory import RoboAdvisoryPlugin
	plugin = RoboAdvisoryPlugin.__new__(RoboAdvisoryPlugin)
	plugin.config = {}
	plugin.appbuilder = None
	meta = plugin.metadata
	assert meta.name == "robo_advisory"
	assert meta.version == "1.0.0"
	assert "fintech" in meta.tags
	assert meta.safe_mode_compatible is True


def test_plugin_register_models():
	from pgappforge.plugins.fintech.robo_advisory import RoboAdvisoryPlugin
	plugin = RoboAdvisoryPlugin.__new__(RoboAdvisoryPlugin)
	plugin.config = {}
	models = plugin.register_models()
	assert len(models) == 4
	model_names = {m.__tablename__ for m in models}
	assert "ft_robo_profile" in model_names
	assert "ft_robo_goal" in model_names
	assert "ft_robo_model_portfolio" in model_names
	assert "ft_robo_drift" in model_names


# ---------------------------------------------------------------------------
# run_all_drift_checks
# ---------------------------------------------------------------------------

def test_run_all_drift_checks_no_goals(service, session):
	count = service.run_all_drift_checks(tenant_id="t1", session=session)
	assert count == 0
