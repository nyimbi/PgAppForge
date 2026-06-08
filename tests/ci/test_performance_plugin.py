"""
tests/ci/test_performance_plugin.py

CI tests for the HCM Performance Review plugin.

Uses real objects + pytest fixtures; no mocks.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Minimal in-memory session stub
# ---------------------------------------------------------------------------

class _Store:
	def __init__(self) -> None:
		self._objects: dict[str, Any] = {}
		self._added: list[Any] = []

	def add(self, obj: Any) -> None:
		self._added.append(obj)

	def flush(self) -> None:
		for obj in self._added:
			if not getattr(obj, "id", None):
				import uuid
				obj.id = str(uuid.uuid4())
			self._objects[obj.id] = obj
		self._added.clear()

	def get(self, model: Any, pk: str) -> Any | None:
		return self._objects.get(pk)

	def execute(self, stmt: Any) -> Any:
		return _EmptyResult()


class _EmptyResult:
	def scalars(self) -> "_EmptyResult":
		return self

	def all(self) -> list:
		return []

	def scalar_one_or_none(self) -> Any:
		return None

	def scalar_one(self) -> int:
		return 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session() -> _Store:
	return _Store()


@pytest.fixture
def tenant_id() -> str:
	return "tenant-perf-test-0001"


@pytest.fixture
def svc():
	from pgappforge.plugins.erp.hcm.performance.services import PerformanceService
	return PerformanceService()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_event_types_are_correct() -> None:
	from pgappforge.plugins.erp.hcm.performance.events import (
		PerformanceCycleStartedEvent,
		ReviewSubmittedEvent,
		GoalCreatedEvent,
		GoalProgressUpdatedEvent,
		FeedbackGivenEvent,
	)
	assert PerformanceCycleStartedEvent.event_type == "hcm.performance.cycle.started"
	assert ReviewSubmittedEvent.event_type == "hcm.performance.review.submitted"
	assert GoalCreatedEvent.event_type == "hcm.performance.goal.created"
	assert GoalProgressUpdatedEvent.event_type == "hcm.performance.goal.progress"
	assert FeedbackGivenEvent.event_type == "hcm.performance.feedback.given"


# ---------------------------------------------------------------------------
# Models import
# ---------------------------------------------------------------------------

def test_models_importable() -> None:
	from pgappforge.plugins.erp.hcm.performance.models import (
		PerformanceCycle,
		PerformanceReview,
		Goal,
		ContinuousFeedback,
	)
	assert PerformanceCycle.__tablename__ == "prf_cycle"
	assert PerformanceReview.__tablename__ == "prf_review"
	assert Goal.__tablename__ == "prf_goal"
	assert ContinuousFeedback.__tablename__ == "prf_feedback"


# ---------------------------------------------------------------------------
# start_cycle
# ---------------------------------------------------------------------------

def test_start_cycle_creates_active_cycle(svc, session, tenant_id) -> None:
	cycle = svc.start_cycle(
		"2026 Annual Review",
		"ANNUAL",
		date(2026, 1, 1),
		date(2026, 12, 31),
		tenant_id,
		session,
	)
	assert cycle.status == "ACTIVE"
	assert cycle.name == "2026 Annual Review"
	assert cycle.cycle_type == "ANNUAL"
	assert "competencies" in cycle.review_form
	assert "weights" in cycle.review_form


def test_start_cycle_with_custom_form(svc, session, tenant_id) -> None:
	custom_form = {
		"competencies": [{"name": "Delivery", "description": "Ships on time", "max_rating": 5}],
		"weights": {"self": 30, "manager": 70, "peer": 0},
	}
	cycle = svc.start_cycle(
		"Q1 2026",
		"QUARTERLY",
		date(2026, 1, 1),
		date(2026, 3, 31),
		tenant_id,
		session,
		review_form=custom_form,
	)
	assert cycle.review_form["weights"]["self"] == 30


# ---------------------------------------------------------------------------
# request_reviews
# ---------------------------------------------------------------------------

def test_request_reviews_creates_pending_reviews(svc, session, tenant_id) -> None:
	cycle = svc.start_cycle(
		"2026 Q2",
		"QUARTERLY",
		date(2026, 4, 1),
		date(2026, 6, 30),
		tenant_id,
		session,
	)
	reviewers = ["mgr-001", "peer-001", "peer-002"]
	reviews = svc.request_reviews("emp-001", cycle.id, reviewers, "PEER", session)
	assert len(reviews) == 3
	assert all(r.status == "PENDING" for r in reviews)
	assert all(r.employee_id == "emp-001" for r in reviews)
	assert all(r.review_type == "PEER" for r in reviews)


def test_request_reviews_wrong_cycle_status_raises(svc, session, tenant_id) -> None:
	from pgappforge.plugins.erp.hcm.performance.services import PerformanceStateError

	cycle = svc.start_cycle(
		"Old Cycle",
		"ANNUAL",
		date(2025, 1, 1),
		date(2025, 12, 31),
		tenant_id,
		session,
	)
	cycle.status = "CLOSED"

	with pytest.raises(PerformanceStateError, match="ACTIVE"):
		svc.request_reviews("emp-001", cycle.id, ["mgr-001"], "MANAGER", session)


# ---------------------------------------------------------------------------
# submit_review
# ---------------------------------------------------------------------------

def test_submit_review_sets_submitted_status(svc, session, tenant_id) -> None:
	cycle = svc.start_cycle(
		"2026 Annual",
		"ANNUAL",
		date(2026, 1, 1),
		date(2026, 12, 31),
		tenant_id,
		session,
	)
	[review] = svc.request_reviews("emp-002", cycle.id, ["mgr-002"], "MANAGER", session)

	review = svc.submit_review(
		review.id,
		overall_rating=4.0,
		competency_scores={"Execution": 4.0, "Collaboration": 3.5},
		session=session,
		strengths="Excellent delivery",
		dev_areas="Communication",
	)
	assert review.status == "SUBMITTED"
	assert review.overall_rating == Decimal("4.00")
	assert review.submitted_at is not None
	assert review.strengths == "Excellent delivery"


def test_submit_review_out_of_range_rating_raises(svc, session, tenant_id) -> None:
	cycle = svc.start_cycle(
		"Cycle",
		"ANNUAL",
		date(2026, 1, 1),
		date(2026, 12, 31),
		tenant_id,
		session,
	)
	[review] = svc.request_reviews("emp-003", cycle.id, ["mgr-003"], "MANAGER", session)

	with pytest.raises(AssertionError):
		svc.submit_review(review.id, 6.0, {}, session)


def test_submit_review_already_submitted_raises(svc, session, tenant_id) -> None:
	from pgappforge.plugins.erp.hcm.performance.services import PerformanceStateError

	cycle = svc.start_cycle(
		"Cycle2",
		"ANNUAL",
		date(2026, 1, 1),
		date(2026, 12, 31),
		tenant_id,
		session,
	)
	[review] = svc.request_reviews("emp-004", cycle.id, ["mgr-004"], "MANAGER", session)
	svc.submit_review(review.id, 3.5, {}, session)

	with pytest.raises(PerformanceStateError, match="SUBMITTED"):
		svc.submit_review(review.id, 4.0, {}, session)


# ---------------------------------------------------------------------------
# create_goal
# ---------------------------------------------------------------------------

def test_create_goal_creates_active_goal(svc, session, tenant_id) -> None:
	goal = svc.create_goal(
		"emp-005",
		"Launch new product",
		"OKR",
		"2026-Q3",
		tenant_id,
		session,
		key_results=[{"kr_text": "Hit 1000 users", "target": 1000, "current": 0, "unit": "users"}],
		weight_pct=30,
	)
	assert goal.status == "ACTIVE"
	assert goal.goal_type == "OKR"
	assert goal.period == "2026-Q3"
	assert goal.weight_pct == Decimal("30.00")
	assert len(goal.key_results) == 1


# ---------------------------------------------------------------------------
# update_progress
# ---------------------------------------------------------------------------

def test_update_progress_updates_pct(svc, session, tenant_id) -> None:
	goal = svc.create_goal("emp-006", "Reduce churn", "SMART", "2026", tenant_id, session)
	goal = svc.update_progress(goal.id, 45.5, session)
	assert goal.progress_pct == Decimal("45.50")


def test_update_progress_100_auto_completes(svc, session, tenant_id) -> None:
	goal = svc.create_goal("emp-007", "Ship v2", "OKR", "2026-Q1", tenant_id, session)
	goal = svc.update_progress(goal.id, 100.0, session)
	assert goal.status == "COMPLETED"
	assert goal.progress_pct == Decimal("100.00")


def test_update_progress_out_of_range_raises(svc, session, tenant_id) -> None:
	goal = svc.create_goal("emp-008", "Goal", "OKR", "2026", tenant_id, session)
	with pytest.raises(AssertionError):
		svc.update_progress(goal.id, 150.0, session)


# ---------------------------------------------------------------------------
# give_feedback
# ---------------------------------------------------------------------------

def test_give_feedback_creates_record(svc, session, tenant_id) -> None:
	fb = svc.give_feedback(
		"emp-010",
		"emp-011",
		"Great collaboration on the Q2 project.",
		tenant_id,
		session,
		visibility="MANAGER_VISIBLE",
		tags=["collaboration", "teamwork"],
		context="Q2 2026 project",
	)
	assert fb.from_employee_id == "emp-010"
	assert fb.to_employee_id == "emp-011"
	assert "collaboration" in fb.tags
	assert fb.visibility == "MANAGER_VISIBLE"
	assert fb.context == "Q2 2026 project"


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

def test_plugin_metadata() -> None:
	from pgappforge.plugins.erp.hcm.performance import PerformancePlugin

	plugin = PerformancePlugin(None)
	meta = plugin.metadata
	assert meta.name == "performance"
	assert meta.version == "1.0.0"
	assert "okr" in meta.tags
	assert "360" in meta.tags


def test_plugin_register_models() -> None:
	from pgappforge.plugins.erp.hcm.performance import PerformancePlugin

	plugin = PerformancePlugin(None)
	models = plugin.register_models()
	names = [m.__tablename__ for m in models]
	assert "prf_cycle" in names
	assert "prf_review" in names
	assert "prf_goal" in names
	assert "prf_feedback" in names
