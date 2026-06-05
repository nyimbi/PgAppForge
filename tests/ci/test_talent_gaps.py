"""
tests/ci/test_talent_gaps.py

CI tests for all CRITICAL and HIGH gap implementations in the HCM Talent module.

Covers:
  - OKR / Goal management (create, cascade, progress rollup, close_for_period)
  - 360-degree appraisal (launch_cycle, invite_reviewers, submit_peer_feedback,
    calculate_aggregate_score)
  - PIP workflow (create_pip, record_pip_checkin, resolve_pip)
  - Succession planning (create_succession_plan, add_successor, bench_strength_report)
  - HiPo / 9-box placement (place_nine_box, upsert, label computation)
  - Career pathing / skills gap analysis (skills_gap_analysis)
  - eNPS / survey (compute_enps NPS formula)
  - L&D certifications (record_certification, expiring_certifications)
  - Onboarding (create_onboarding_plan, complete_onboarding_task)
  - Interview debrief (record_debrief)
  - Recruitment analytics (recruitment_metrics)
  - Model column invariants for all new tables
  - __all__ export completeness

No @pytest.mark.asyncio — plain sync functions.
No mocks — SQLAlchemy in-memory SQLite for structural tests; service-layer unit
tests use SQLAlchemy + real objects.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Engine / session fixture — SQLite in-memory (structural tests only;
# PostgreSQL-specific columns like ARRAY/JSONB/UUID are tested via import only)
# ---------------------------------------------------------------------------


def _build_talent_ddl(eng: Any) -> None:
	"""Create all tal_* tables in SQLite using raw DDL.

	Each table is created with only its non-FK columns plus a simple TEXT
	primary key column for 'id'.  SQLite doesn't enforce FK constraints so
	we drop all FK clauses entirely — the ORM will still INSERT/SELECT
	correctly because SQLite ignores unknown columns and constraint syntax.

	We emit raw CREATE TABLE … IF NOT EXISTS SQL so we don't fight
	SQLAlchemy's cross-metadata FK resolution during sort_tables.
	"""
	from pgappforge.models.sqla import Model
	from pgappforge.plugins.erp.hcm.talent import models as _m  # noqa: F401

	# SQLAlchemy type → SQLite affinity
	_TYPE_MAP = {
		"UUID": "TEXT",
		"VARCHAR": "TEXT",
		"TEXT": "TEXT",
		"BOOLEAN": "INTEGER",
		"INTEGER": "INTEGER",
		"BIGINTEGER": "INTEGER",
		"NUMERIC": "REAL",
		"DATE": "TEXT",
		"DATETIME": "TEXT",
		"JSONB": "TEXT",  # PostgreSQL JSONB → TEXT in SQLite
		"ARRAY": "TEXT",  # PostgreSQL ARRAY → TEXT in SQLite
		"NullType": "TEXT",
	}

	def _sa_type(col_type: Any) -> str:
		tn = type(col_type).__name__.upper()
		for k, v in _TYPE_MAP.items():
			if tn.startswith(k):
				return v
		return "TEXT"

	talent_tables = sorted(
		(t for t in Model.metadata.tables.values() if t.name.startswith("tal_")),
		key=lambda t: t.name,
	)

	with eng.connect() as conn:
		for tbl in talent_tables:
			col_sqls = []
			for c in tbl.columns:
				affinity = _sa_type(c.type)
				null_clause = "" if c.nullable else " NOT NULL"
				pk_clause = " PRIMARY KEY" if c.primary_key else ""
				col_sqls.append(f'"{c.name}" {affinity}{pk_clause}{null_clause}')
			ddl = f'CREATE TABLE IF NOT EXISTS "{tbl.name}" ({", ".join(col_sqls)})'
			conn.execute(sa.text(ddl))
		conn.commit()


@pytest.fixture(scope="module")
def engine():
	"""SQLite in-memory engine with all tal_* tables created via raw DDL."""
	eng = create_engine("sqlite:///:memory:", echo=False)
	_build_talent_ddl(eng)
	return eng


@pytest.fixture()
def session(engine):
	with Session(engine) as s:
		yield s
		s.rollback()


def _uid() -> str:
	return str(uuid.uuid4())


def _today() -> date:
	return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Helpers — minimal object factories
# ---------------------------------------------------------------------------


def _make_tenant() -> str:
	return _uid()


# ---------------------------------------------------------------------------
# 1. Model import / column invariant tests
# ---------------------------------------------------------------------------


class TestNewModelImports:
	"""All new models import and carry required columns."""

	def test_goal_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import Goal
		assert Goal.__tablename__ == "tal_goal"

	def test_performance_cycle_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceCycle
		assert PerformanceCycle.__tablename__ == "tal_performance_cycle"

	def test_review_participant_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import ReviewParticipant
		assert ReviewParticipant.__tablename__ == "tal_review_participant"

	def test_pip_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import PIP
		assert PIP.__tablename__ == "tal_pip"

	def test_pip_checkin_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import PIPCheckin
		assert PIPCheckin.__tablename__ == "tal_pip_checkin"

	def test_succession_plan_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import SuccessionPlan
		assert SuccessionPlan.__tablename__ == "tal_succession_plan"

	def test_successor_candidate_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import SuccessorCandidate
		assert SuccessorCandidate.__tablename__ == "tal_successor_candidate"

	def test_nine_box_placement_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import NineBoxPlacement
		assert NineBoxPlacement.__tablename__ == "tal_nine_box_placement"

	def test_competency_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import Competency
		assert Competency.__tablename__ == "tal_competency"

	def test_competency_profile_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import CompetencyProfile
		assert CompetencyProfile.__tablename__ == "tal_competency_profile"

	def test_career_path_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import CareerPath
		assert CareerPath.__tablename__ == "tal_career_path"

	def test_survey_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import Survey
		assert Survey.__tablename__ == "tal_survey"

	def test_survey_question_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import SurveyQuestion
		assert SurveyQuestion.__tablename__ == "tal_survey_question"

	def test_survey_response_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import SurveyResponse
		assert SurveyResponse.__tablename__ == "tal_survey_response"

	def test_certification_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import Certification
		assert Certification.__tablename__ == "tal_certification"

	def test_onboarding_plan_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import OnboardingPlan
		assert OnboardingPlan.__tablename__ == "tal_onboarding_plan"

	def test_onboarding_task_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import OnboardingTask
		assert OnboardingTask.__tablename__ == "tal_onboarding_task"

	def test_interview_debrief_importable(self):
		from pgappforge.plugins.erp.hcm.talent.models import InterviewDebrief
		assert InterviewDebrief.__tablename__ == "tal_interview_debrief"


class TestNewModelRequiredColumns:
	"""Every new model has tenant_id, created_at, updated_at."""

	@pytest.mark.parametrize("model_name", [
		"Goal", "PerformanceCycle", "ReviewParticipant",
		"PIP", "PIPCheckin", "SuccessionPlan", "SuccessorCandidate",
		"NineBoxPlacement", "Competency", "CompetencyProfile",
		"CareerPath", "Survey", "SurveyQuestion", "SurveyResponse",
		"Certification", "OnboardingPlan", "OnboardingTask", "InterviewDebrief",
	])
	def test_model_has_required_columns(self, model_name):
		import importlib
		mod = importlib.import_module("pgappforge.plugins.erp.hcm.talent.models")
		cls = getattr(mod, model_name)
		cols = {c.name for c in cls.__table__.columns}
		for required in ("id", "tenant_id", "created_at", "updated_at"):
			assert required in cols, f"{model_name} missing column {required!r}"


# ---------------------------------------------------------------------------
# 2. Service import
# ---------------------------------------------------------------------------


class TestServiceImports:

	def test_talent_service_importable(self):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		assert TalentService is not None

	def test_new_error_classes_importable(self):
		from pgappforge.plugins.erp.hcm.talent.services import (
			GoalNotFoundError,
			PIPNotFoundError,
			SuccessionPlanNotFoundError,
			CycleNotFoundError,
		)
		assert issubclass(GoalNotFoundError, Exception)
		assert issubclass(PIPNotFoundError, Exception)
		assert issubclass(SuccessionPlanNotFoundError, Exception)
		assert issubclass(CycleNotFoundError, Exception)

	def test_all_new_service_methods_present(self):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		expected_methods = [
			"create_goal", "update_goal_progress", "cascade_goals", "close_goals_for_period",
			"launch_cycle", "invite_reviewers", "submit_peer_feedback", "calculate_aggregate_score",
			"create_pip", "record_pip_checkin", "resolve_pip",
			"create_succession_plan", "add_successor", "get_bench_strength_report",
			"place_nine_box",
			"skills_gap_analysis",
			"compute_enps",
			"record_certification", "expiring_certifications",
			"create_onboarding_plan", "complete_onboarding_task",
			"record_debrief",
			"recruitment_metrics",
		]
		for m in expected_methods:
			assert hasattr(svc, m), f"TalentService missing method {m!r}"


# ---------------------------------------------------------------------------
# 3. OKR / Goal management
# ---------------------------------------------------------------------------


class TestGoalManagement:

	def test_create_goal_returns_goal(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		goal = svc.create_goal(tid, _uid(), "Grow Revenue", "COMPANY", "2026-Q1", session=session)
		assert goal.id is not None
		assert goal.status == "DRAFT"
		assert goal.level == "COMPANY"
		assert goal.period == "2026-Q1"
		assert float(goal.progress_pct) == 0.0

	def test_create_goal_invalid_level_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		with pytest.raises(TalentValidationError, match="Invalid goal level"):
			svc.create_goal(_make_tenant(), _uid(), "X", "TEAM", "2026-Q1", session=session)

	def test_create_goal_with_parent(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		parent = svc.create_goal(tid, _uid(), "Company Goal", "COMPANY", "2026-Q1", session=session)
		child = svc.create_goal(
			tid, _uid(), "Dept Goal", "DEPARTMENT", "2026-Q1",
			parent_goal_id=parent.id, weight=50.0, session=session,
		)
		assert child.parent_goal_id == parent.id

	def test_update_goal_progress(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		goal = svc.create_goal(tid, _uid(), "Hire Engineers", "INDIVIDUAL", "2026-Q1", session=session)
		updated = svc.update_goal_progress(goal.id, 75.0, session=session)
		assert float(updated.progress_pct) == 75.0

	def test_update_goal_progress_invalid_range_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		goal = svc.create_goal(tid, _uid(), "Goal", "INDIVIDUAL", "2026-Q1", session=session)
		with pytest.raises(TalentValidationError, match="0–100"):
			svc.update_goal_progress(goal.id, 110.0, session=session)

	def test_update_goal_progress_rolls_up_to_parent(self, session):
		from pgappforge.plugins.erp.hcm.talent.models import Goal
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		parent = svc.create_goal(tid, _uid(), "Parent", "COMPANY", "2026-Q1", weight=100, session=session)
		child1 = svc.create_goal(tid, _uid(), "Child1", "INDIVIDUAL", "2026-Q1", parent_goal_id=parent.id, weight=50, session=session)
		child2 = svc.create_goal(tid, _uid(), "Child2", "INDIVIDUAL", "2026-Q1", parent_goal_id=parent.id, weight=50, session=session)

		svc.update_goal_progress(child1.id, 100.0, session=session)
		svc.update_goal_progress(child2.id, 60.0, session=session)

		session.refresh(parent)
		# Weighted avg: (100*50 + 60*50) / 100 = 80
		assert float(parent.progress_pct) == 80.0

	def test_cascade_goals_creates_children(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		parent = svc.create_goal(tid, _uid(), "OKR Parent", "COMPANY", "2026-Q1", session=session)
		emp_ids = [_uid(), _uid(), _uid()]
		children = svc.cascade_goals(parent.id, emp_ids, session=session)
		assert len(children) == 3
		for c in children:
			assert c.parent_goal_id == parent.id
			assert c.level == "INDIVIDUAL"
			assert c.period == "2026-Q1"

	def test_close_goals_for_period(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		# Create 3 ACTIVE goals for 2026-Q1
		for _ in range(3):
			g = svc.create_goal(tid, _uid(), "Goal", "INDIVIDUAL", "2026-Q1", session=session)
			svc.update_goal_progress(g.id, 50.0, session=session)
			g.status = "ACTIVE"
		session.flush()

		count = svc.close_goals_for_period(tid, "2026-Q1", session=session)
		assert count == 3


# ---------------------------------------------------------------------------
# 4. 360-degree appraisal
# ---------------------------------------------------------------------------


class TestPerformanceCycle:

	def test_launch_cycle(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "2026 Annual Review", "2026", "ANNUAL", session=session)
		assert cycle.id is not None
		assert cycle.status == "IN_PROGRESS"
		assert cycle.cycle_type == "ANNUAL"
		assert cycle.launched_at is not None

	def test_launch_cycle_invalid_type_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		with pytest.raises(TalentValidationError, match="Invalid cycle_type"):
			svc.launch_cycle(_make_tenant(), "Bad Cycle", "2026", "QUARTERLY", session=session)

	def test_invite_reviewers(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "360 Cycle", "2026-Q2", "360", session=session)
		appraisee = _uid()
		reviewers = [
			{"appraiser_id": _uid(), "relationship_type": "SELF"},
			{"appraiser_id": _uid(), "relationship_type": "PEER"},
			{"appraiser_id": _uid(), "relationship_type": "MANAGER"},
		]
		participants = svc.invite_reviewers(cycle.id, appraisee, reviewers, session=session)
		assert len(participants) == 3
		rel_types = {p.relationship_type for p in participants}
		assert "SELF" in rel_types and "PEER" in rel_types and "MANAGER" in rel_types

	def test_invite_reviewers_invalid_rel_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "Cycle", "2026-Q2", "360", session=session)
		with pytest.raises(TalentValidationError, match="Invalid relationship_type"):
			svc.invite_reviewers(cycle.id, _uid(), [{"appraiser_id": _uid(), "relationship_type": "BOSS"}], session=session)

	def test_submit_peer_feedback(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "Cycle", "2026-Q2", "360", session=session)
		appraisee = _uid()
		participants = svc.invite_reviewers(
			cycle.id, appraisee,
			[{"appraiser_id": _uid(), "relationship_type": "PEER"}],
			session=session,
		)
		p = participants[0]
		responses = [{"competency_code": "LEAD_01", "score": 4, "comments": "Good leadership"}]
		submitted = svc.submit_peer_feedback(p.id, responses, session=session)
		assert submitted.status == "SUBMITTED"
		assert submitted.submitted_at is not None
		assert submitted.responses[0]["competency_code"] == "LEAD_01"

	def test_submit_peer_feedback_invalid_score_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "Cycle", "2026-Q2", "360", session=session)
		participants = svc.invite_reviewers(
			cycle.id, _uid(),
			[{"appraiser_id": _uid(), "relationship_type": "PEER"}],
			session=session,
		)
		with pytest.raises(TalentValidationError, match="Score must be 1–5"):
			svc.submit_peer_feedback(participants[0].id, [{"competency_code": "X", "score": 6}], session=session)

	def test_submit_peer_feedback_double_submit_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentStateError
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "Cycle", "2026", "360", session=session)
		participants = svc.invite_reviewers(
			cycle.id, _uid(),
			[{"appraiser_id": _uid(), "relationship_type": "SELF"}],
			session=session,
		)
		svc.submit_peer_feedback(participants[0].id, [{"competency_code": "C1", "score": 3}], session=session)
		with pytest.raises(TalentStateError, match="already submitted"):
			svc.submit_peer_feedback(participants[0].id, [{"competency_code": "C1", "score": 5}], session=session)

	def test_calculate_aggregate_score(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "Cycle", "2026", "360", session=session)
		appraisee = _uid()
		participants = svc.invite_reviewers(
			cycle.id, appraisee,
			[
				{"appraiser_id": _uid(), "relationship_type": "PEER"},
				{"appraiser_id": _uid(), "relationship_type": "MANAGER"},
			],
			session=session,
		)
		svc.submit_peer_feedback(participants[0].id, [{"competency_code": "C1", "score": 4, "comments": ""}], session=session)
		svc.submit_peer_feedback(participants[1].id, [{"competency_code": "C1", "score": 2, "comments": ""}], session=session)
		result = svc.calculate_aggregate_score(cycle.id, appraisee, session=session)

		assert result["cycle_id"] == cycle.id
		assert result["employee_id"] == appraisee
		assert result["participant_count"] == 2
		assert result["submitted_count"] == 2
		assert result["pending_count"] == 0
		assert result["overall_avg"] == 3.0  # (4+2)/2
		assert "C1" in result["by_competency"]
		assert result["by_competency"]["C1"] == 3.0


# ---------------------------------------------------------------------------
# 5. PIP workflow
# ---------------------------------------------------------------------------


class TestPIPWorkflow:

	def test_create_pip(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		start = _today()
		end = start + timedelta(days=90)
		pip = svc.create_pip(
			tid, _uid(), _uid(), start, end,
			[{"area": "Communication", "target_behaviour": "Listen actively", "success_criterion": "No escalations"}],
			session=session,
		)
		assert pip.status == "ACTIVE"
		assert pip.start_date == start
		assert pip.end_date == end
		assert len(pip.improvement_areas) == 1

	def test_create_pip_end_before_start_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		today = _today()
		with pytest.raises(TalentValidationError, match="end_date must be after"):
			svc.create_pip(
				_make_tenant(), _uid(), _uid(), today, today - timedelta(days=1),
				[], session=session,
			)

	def test_record_pip_checkin(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		start = _today()
		pip = svc.create_pip(tid, _uid(), _uid(), start, start + timedelta(days=60), [], session=session)
		checkin = svc.record_pip_checkin(pip.id, _uid(), "Good progress this week.", start, progress_rating="ON_TRACK", session=session)
		assert checkin.pip_id == pip.id
		assert checkin.progress_rating == "ON_TRACK"

	def test_record_pip_checkin_invalid_rating_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		start = _today()
		pip = svc.create_pip(tid, _uid(), _uid(), start, start + timedelta(days=60), [], session=session)
		with pytest.raises(TalentValidationError, match="Invalid progress_rating"):
			svc.record_pip_checkin(pip.id, _uid(), "Notes.", start, progress_rating="GOOD", session=session)

	def test_resolve_pip_passed(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		start = _today()
		pip = svc.create_pip(tid, _uid(), _uid(), start, start + timedelta(days=60), [], session=session)
		resolved = svc.resolve_pip(pip.id, "PASSED", "Met all criteria.", session=session)
		assert resolved.status == "PASSED"
		assert "Met all criteria" in resolved.outcome_notes

	def test_resolve_pip_terminated(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		start = _today()
		pip = svc.create_pip(tid, _uid(), _uid(), start, start + timedelta(days=60), [], session=session)
		resolved = svc.resolve_pip(pip.id, "TERMINATED", "Employment ended.", session=session)
		assert resolved.status == "TERMINATED"

	def test_resolve_pip_invalid_outcome_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		start = _today()
		pip = svc.create_pip(tid, _uid(), _uid(), start, start + timedelta(days=60), [], session=session)
		with pytest.raises(TalentValidationError, match="Invalid PIP outcome"):
			svc.resolve_pip(pip.id, "CLOSED", "Done.", session=session)

	def test_resolve_already_resolved_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentStateError
		svc = TalentService()
		tid = _make_tenant()
		start = _today()
		pip = svc.create_pip(tid, _uid(), _uid(), start, start + timedelta(days=60), [], session=session)
		svc.resolve_pip(pip.id, "PASSED", "Done.", session=session)
		with pytest.raises(TalentStateError, match="Cannot resolve PIP"):
			svc.resolve_pip(pip.id, "TERMINATED", "Again.", session=session)


# ---------------------------------------------------------------------------
# 6. Succession planning
# ---------------------------------------------------------------------------


class TestSuccessionPlanning:

	def test_create_succession_plan(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		pos = _uid()
		plan = svc.create_succession_plan(tid, pos, risk_level="HIGH", session=session)
		assert plan.position_id == pos
		assert plan.risk_level == "HIGH"

	def test_create_succession_plan_invalid_risk_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		with pytest.raises(TalentValidationError, match="Invalid risk_level"):
			svc.create_succession_plan(_make_tenant(), _uid(), risk_level="CRITICAL", session=session)

	def test_create_succession_plan_upsert(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		pos = _uid()
		p1 = svc.create_succession_plan(tid, pos, risk_level="HIGH", session=session)
		p2 = svc.create_succession_plan(tid, pos, risk_level="LOW", session=session)
		assert p1.id == p2.id  # same row updated
		assert p2.risk_level == "LOW"

	def test_add_successor_ready_now(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		plan = svc.create_succession_plan(tid, _uid(), session=session)
		candidate = svc.add_successor(plan.id, _uid(), "READY_NOW", session=session)
		assert candidate.readiness == "READY_NOW"
		session.refresh(plan)
		assert plan.bench_strength_score == 100.0

	def test_add_successor_updates_bench_strength(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		plan = svc.create_succession_plan(tid, _uid(), session=session)
		svc.add_successor(plan.id, _uid(), "READY_NOW", session=session)    # score 100
		svc.add_successor(plan.id, _uid(), "3_5_YEARS", session=session)   # score 30
		session.refresh(plan)
		# avg(100, 30) = 65
		assert float(plan.bench_strength_score) == 65.0

	def test_add_successor_invalid_readiness_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		plan = svc.create_succession_plan(tid, _uid(), session=session)
		with pytest.raises(TalentValidationError, match="Invalid readiness"):
			svc.add_successor(plan.id, _uid(), "NEXT_YEAR", session=session)

	def test_get_bench_strength_report_structure(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		plan = svc.create_succession_plan(tid, _uid(), risk_level="HIGH", session=session)
		svc.add_successor(plan.id, _uid(), "READY_NOW", session=session)
		svc.add_successor(plan.id, _uid(), "1_2_YEARS", session=session)

		report = svc.get_bench_strength_report(tid, session=session)
		assert "plans" in report
		assert "overall_bench_strength" in report
		assert "high_risk_vacancies" in report
		assert len(report["plans"]) >= 1
		row = report["plans"][0]
		assert "ready_now" in row and row["ready_now"] >= 1

	def test_bench_strength_high_risk_vacancy_flagged(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		# HIGH risk plan with NO READY_NOW successors → should count as high-risk vacancy
		plan = svc.create_succession_plan(tid, _uid(), risk_level="HIGH", session=session)
		svc.add_successor(plan.id, _uid(), "3_5_YEARS", session=session)

		report = svc.get_bench_strength_report(tid, session=session)
		assert report["high_risk_vacancies"] >= 1


# ---------------------------------------------------------------------------
# 7. HiPo / 9-box
# ---------------------------------------------------------------------------


class TestNineBoxPlacement:

	def test_place_nine_box_star(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "Talent Review", "2026", "ANNUAL", session=session)
		emp = _uid()
		placement = svc.place_nine_box(tid, emp, cycle.id, 3, 3, _uid(), session=session)
		assert placement.box_label == "STAR"
		assert placement.performance_axis == 3
		assert placement.potential_axis == 3

	@pytest.mark.parametrize("perf,pot,expected_label", [
		(3, 3, "STAR"),
		(3, 2, "HIGH_PERFORMER"),
		(3, 1, "EXPERT"),
		(2, 3, "HIGH_POTENTIAL"),
		(2, 2, "CORE_PLAYER"),
		(2, 1, "SOLID_CONTRIBUTOR"),
		(1, 3, "ENIGMA"),
		(1, 2, "NEEDS_COACHING"),
		(1, 1, "UNDERPERFORMER"),
	])
	def test_nine_box_labels(self, session, perf, pot, expected_label):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, f"Cycle {perf}{pot}", "2026", "ANNUAL", session=session)
		emp = _uid()
		p = svc.place_nine_box(tid, emp, cycle.id, perf, pot, _uid(), session=session)
		assert p.box_label == expected_label

	def test_place_nine_box_invalid_axis_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "Cycle", "2026", "ANNUAL", session=session)
		with pytest.raises(TalentValidationError, match="performance_axis must be 1, 2, or 3"):
			svc.place_nine_box(tid, _uid(), cycle.id, 4, 2, _uid(), session=session)

	def test_place_nine_box_upsert(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		cycle = svc.launch_cycle(tid, "Cycle", "2026", "ANNUAL", session=session)
		emp = _uid()
		p1 = svc.place_nine_box(tid, emp, cycle.id, 1, 1, _uid(), session=session)
		p2 = svc.place_nine_box(tid, emp, cycle.id, 3, 3, _uid(), session=session)
		assert p1.id == p2.id
		assert p2.box_label == "STAR"


# ---------------------------------------------------------------------------
# 8. Skills gap analysis
# ---------------------------------------------------------------------------


class TestSkillsGapAnalysis:

	def _setup_competency_profile(self, session, tid: str, position_id: str) -> None:
		"""Directly insert Competency + CompetencyProfile rows."""
		from pgappforge.plugins.erp.hcm.talent.models import Competency, CompetencyProfile

		c1 = Competency(
			tenant_id=tid, code="LEAD_01", name="Leadership",
			competency_type="LEADERSHIP", behavioural_indicators=[], is_active=True,
		)
		c2 = Competency(
			tenant_id=tid, code="SQL_01", name="SQL",
			competency_type="TECHNICAL", behavioural_indicators=[], is_active=True,
		)
		session.add_all([c1, c2])
		session.flush()

		session.add_all([
			CompetencyProfile(tenant_id=tid, position_id=position_id, competency_id=c1.id, required_level=3, weight=50),
			CompetencyProfile(tenant_id=tid, position_id=position_id, competency_id=c2.id, required_level=4, weight=50),
		])
		session.flush()

	def test_skills_gap_analysis_matched_and_gap(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		pos = _uid()
		self._setup_competency_profile(session, tid, pos)

		# Employee has Leadership=3 (meets req) but no SQL skill
		emp_skills = [{"name": "Leadership", "proficiency": "EXPERT"}]
		result = svc.skills_gap_analysis(_uid(), pos, employee_skills=emp_skills, session=session)

		assert result["target_position_id"] == pos
		matched_names = {r["name"] for r in result["matched"]}
		gap_names = {r["name"] for r in result["gap"]}
		assert "Leadership" in matched_names
		assert "SQL" in gap_names

	def test_skills_gap_analysis_excess(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		pos = _uid()
		self._setup_competency_profile(session, tid, pos)

		# Employee has Leadership=4 (exceeds req of 3) and SQL=4 (meets req)
		emp_skills = [
			{"name": "Leadership", "proficiency": 4},
			{"name": "SQL", "proficiency": 4},
		]
		result = svc.skills_gap_analysis(_uid(), pos, employee_skills=emp_skills, session=session)
		excess_names = {r["name"] for r in result["excess"]}
		assert "Leadership" in excess_names
		matched_names = {r["name"] for r in result["matched"]}
		assert "SQL" in matched_names

	def test_skills_gap_analysis_empty_profile_returns_empty(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		result = svc.skills_gap_analysis(_uid(), _uid(), employee_skills=[], session=session)
		assert result["matched"] == []
		assert result["gap"] == []
		assert result["excess"] == []


# ---------------------------------------------------------------------------
# 9. eNPS / survey
# ---------------------------------------------------------------------------


class TestComputeENPS:

	def _setup_enps_survey(self, session, tid: str) -> Any:
		from pgappforge.plugins.erp.hcm.talent.models import Survey, SurveyQuestion, SurveyResponse
		survey = Survey(tenant_id=tid, title="2026-Q1 eNPS", survey_type="ENPS", period="2026-Q1", anonymised=False, status="ACTIVE")
		session.add(survey)
		session.flush()

		question = SurveyQuestion(
			tenant_id=tid, survey_id=survey.id,
			question_text="How likely are you to recommend us as a place to work? (0-10)",
			question_type="SCALE", scale_min=0, scale_max=10, sort_order=0,
		)
		session.add(question)
		session.flush()

		# 3 promoters (score 9,10,10), 2 passives (7,8), 5 detractors (0,1,2,3,4)
		responses_data = [9, 10, 10, 7, 8, 0, 1, 2, 3, 4]
		for score in responses_data:
			resp = SurveyResponse(
				tenant_id=tid, survey_id=survey.id, employee_id=_uid(),
				responses=[{"question_id": question.id, "answer": score}],
			)
			session.add(resp)
		session.flush()
		return survey

	def test_compute_enps_correct_formula(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		survey = self._setup_enps_survey(session, tid)
		result = svc.compute_enps(survey.id, session=session)

		assert result["promoters"] == 3
		assert result["passives"] == 2
		assert result["detractors"] == 5
		assert result["response_count"] == 10
		# NPS = (3-5)/10 * 100 = -20.0
		assert result["enps_score"] == -20.0

	def test_compute_enps_wrong_type_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.models import Survey
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		survey = Survey(tenant_id=tid, title="Pulse", survey_type="PULSE", anonymised=False, status="ACTIVE")
		session.add(survey)
		session.flush()
		with pytest.raises(TalentValidationError, match="not ENPS"):
			svc.compute_enps(survey.id, session=session)

	def test_compute_enps_no_responses_returns_zero(self, session):
		from pgappforge.plugins.erp.hcm.talent.models import Survey, SurveyQuestion
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		survey = Survey(tenant_id=tid, title="Empty eNPS", survey_type="ENPS", anonymised=True, status="ACTIVE")
		session.add(survey)
		session.flush()
		q = SurveyQuestion(tenant_id=tid, survey_id=survey.id, question_text="Rate?", question_type="SCALE", scale_min=0, scale_max=10, sort_order=0)
		session.add(q)
		session.flush()
		result = svc.compute_enps(survey.id, session=session)
		assert result["enps_score"] == 0.0
		assert result["response_count"] == 0


# ---------------------------------------------------------------------------
# 10. L&D certifications
# ---------------------------------------------------------------------------


class TestCertifications:

	def test_record_certification(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		today = _today()
		cert = svc.record_certification(
			tid, _uid(), "CISA", today,
			issuing_body="ISACA",
			expiry_date=today + timedelta(days=365 * 3),
			renewal_required=True,
			session=session,
		)
		assert cert.certification_name == "CISA"
		assert cert.issuing_body == "ISACA"
		assert cert.renewal_required is True

	def test_expiring_certifications_found(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		today = _today()

		# One cert expiring in 15 days
		svc.record_certification(tid, _uid(), "CPA", today, expiry_date=today + timedelta(days=15), session=session)
		# One cert expiring in 60 days — outside default 30d window
		svc.record_certification(tid, _uid(), "CFA", today, expiry_date=today + timedelta(days=60), session=session)
		# One cert with no expiry — should not appear
		svc.record_certification(tid, _uid(), "No-Expiry Cert", today, expiry_date=None, renewal_required=True, session=session)

		expiring = svc.expiring_certifications(tid, within_days=30, session=session)
		names = [r["certification_name"] for r in expiring]
		assert "CPA" in names
		assert "CFA" not in names

	def test_expiring_certifications_days_until_expiry(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		today = _today()
		svc.record_certification(tid, _uid(), "PMP", today, expiry_date=today + timedelta(days=10), session=session)

		expiring = svc.expiring_certifications(tid, within_days=30, session=session)
		assert any(r["days_until_expiry"] == 10 for r in expiring if r["certification_name"] == "PMP")

	def test_expiring_certifications_renewal_not_required_excluded(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		today = _today()
		svc.record_certification(
			tid, _uid(), "One-Time Cert", today,
			expiry_date=today + timedelta(days=5),
			renewal_required=False,
			session=session,
		)
		expiring = svc.expiring_certifications(tid, within_days=30, session=session)
		names = [r["certification_name"] for r in expiring]
		assert "One-Time Cert" not in names


# ---------------------------------------------------------------------------
# 11. Onboarding
# ---------------------------------------------------------------------------


class TestOnboarding:

	def test_create_onboarding_plan_no_tasks(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		plan = svc.create_onboarding_plan(tid, _uid(), _today() + timedelta(days=14), session=session)
		assert plan.status == "PENDING"
		assert plan.target_start_date is not None

	def test_create_onboarding_plan_with_tasks(self, session):
		from pgappforge.plugins.erp.hcm.talent.models import OnboardingTask
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		tasks = [
			{"task_type": "DOCUMENT", "title": "Sign offer letter"},
			{"task_type": "IT_ACCESS", "title": "Setup laptop"},
			{"task_type": "MEETING", "title": "Meet the team"},
		]
		plan = svc.create_onboarding_plan(
			tid, _uid(), _today() + timedelta(days=7),
			default_tasks=tasks, session=session,
		)
		# Query tasks directly to avoid SQLite lazy-load uselist ambiguity
		task_rows = session.execute(
			sa.select(OnboardingTask).where(OnboardingTask.plan_id == plan.id)
		).scalars().all()
		assert len(task_rows) == 3
		task_titles = {t.title for t in task_rows}
		assert "Sign offer letter" in task_titles

	def test_complete_onboarding_task(self, session):
		from pgappforge.plugins.erp.hcm.talent.models import OnboardingTask
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		plan = svc.create_onboarding_plan(
			tid, _uid(), _today() + timedelta(days=7),
			default_tasks=[{"task_type": "DOCUMENT", "title": "ID Verification"}],
			session=session,
		)
		task = session.execute(
			sa.select(OnboardingTask).where(OnboardingTask.plan_id == plan.id).limit(1)
		).scalar_one()
		assert task.completed_at is None

		completed = svc.complete_onboarding_task(task.id, session=session)
		assert completed.completed_at is not None

	def test_complete_onboarding_task_twice_raises(self, session):
		from pgappforge.plugins.erp.hcm.talent.models import OnboardingTask
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentStateError
		svc = TalentService()
		tid = _make_tenant()
		plan = svc.create_onboarding_plan(
			tid, _uid(), _today() + timedelta(days=7),
			default_tasks=[{"task_type": "OTHER", "title": "Setup"}],
			session=session,
		)
		task = session.execute(
			sa.select(OnboardingTask).where(OnboardingTask.plan_id == plan.id).limit(1)
		).scalar_one()
		svc.complete_onboarding_task(task.id, session=session)
		with pytest.raises(TalentStateError, match="already completed"):
			svc.complete_onboarding_task(task.id, session=session)


# ---------------------------------------------------------------------------
# 12. Interview debrief
# ---------------------------------------------------------------------------


class TestInterviewDebrief:
	"""
	record_debrief() DB tests require PostgreSQL (ARRAY(UUID) column).
	Only the validation-path tests (which raise before any INSERT) run on SQLite.
	The DB-writing tests are marked xfail on SQLite.
	"""

	def _make_application(self, session, tid: str) -> Any:
		from pgappforge.plugins.erp.hcm.talent.models import Application, Candidate, Requisition
		req = Requisition(
			tenant_id=tid, requisition_number=f"REQ-{_uid()[:8]}",
			status="IN_PROGRESS", headcount=1, required_skills=[],
		)
		session.add(req)
		session.flush()

		cand = Candidate(tenant_id=tid, source="DIRECT", skills=[])
		session.add(cand)
		session.flush()

		app = Application(tenant_id=tid, requisition_id=req.id, candidate_id=cand.id, stage="INTERVIEW")
		session.add(app)
		session.flush()
		return app

	def test_record_debrief_invalid_decision_raises(self, session):
		"""Validation fires before INSERT — works on SQLite."""
		from pgappforge.plugins.erp.hcm.talent.services import TalentService, TalentValidationError
		svc = TalentService()
		tid = _make_tenant()
		app = self._make_application(session, tid)
		with pytest.raises(TalentValidationError, match="Invalid hiring_decision"):
			svc.record_debrief(
				tid, app.id, _uid(), datetime.now(timezone.utc), [],
				hiring_decision="MAYBE",
				session=session,
			)

	def test_record_debrief_app_not_found_raises(self, session):
		"""ApplicationNotFoundError fires before INSERT — works on SQLite."""
		from pgappforge.plugins.erp.hcm.talent.services import ApplicationNotFoundError, TalentService
		svc = TalentService()
		with pytest.raises(ApplicationNotFoundError):
			svc.record_debrief(
				_make_tenant(), _uid(), _uid(), datetime.now(timezone.utc), [],
				session=session,
			)

	@pytest.mark.xfail(
		reason="ARRAY(UUID) column requires PostgreSQL; SQLite can't bind a Python list",
		strict=False,
	)
	def test_record_debrief_basic(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		app = self._make_application(session, tid)
		now = datetime.now(timezone.utc)

		debrief = svc.record_debrief(
			tid, app.id, _uid(), now, [_uid(), _uid()],
			hiring_decision="PROCEED_OFFER",
			decision_rationale="Strong candidate.",
			session=session,
		)
		assert debrief.application_id == app.id
		assert debrief.hiring_decision == "PROCEED_OFFER"
		assert debrief.decided_at is not None

	@pytest.mark.xfail(
		reason="ARRAY(UUID) column requires PostgreSQL; SQLite can't bind a Python list",
		strict=False,
	)
	def test_record_debrief_upsert(self, session):
		from pgappforge.plugins.erp.hcm.talent.services import TalentService
		svc = TalentService()
		tid = _make_tenant()
		app = self._make_application(session, tid)
		now = datetime.now(timezone.utc)

		d1 = svc.record_debrief(tid, app.id, _uid(), now, [], session=session)
		d2 = svc.record_debrief(tid, app.id, _uid(), now, [], hiring_decision="REJECT", session=session)
		assert d1.id == d2.id
		assert d2.hiring_decision == "REJECT"


# ---------------------------------------------------------------------------
# 13. __all__ completeness
# ---------------------------------------------------------------------------


class TestAllExportsCompleteness:

	def test_models_all_includes_new_models(self):
		from pgappforge.plugins.erp.hcm.talent import models
		expected = {
			"Goal", "PerformanceCycle", "ReviewParticipant",
			"PIP", "PIPCheckin", "SuccessionPlan", "SuccessorCandidate",
			"NineBoxPlacement", "Competency", "CompetencyProfile",
			"CareerPath", "Survey", "SurveyQuestion", "SurveyResponse",
			"Certification", "OnboardingPlan", "OnboardingTask", "InterviewDebrief",
		}
		for name in expected:
			assert name in models.__all__, f"{name!r} missing from models.__all__"

	def test_services_all_includes_new_errors(self):
		from pgappforge.plugins.erp.hcm.talent import services
		expected = {"GoalNotFoundError", "PIPNotFoundError", "SuccessionPlanNotFoundError", "CycleNotFoundError"}
		for name in expected:
			assert name in services.__all__, f"{name!r} missing from services.__all__"

	def test_init_all_includes_new_models(self):
		import pgappforge.plugins.erp.hcm.talent as pkg
		expected_models = {
			"Goal", "PerformanceCycle", "ReviewParticipant",
			"PIP", "PIPCheckin", "SuccessionPlan", "SuccessorCandidate",
			"NineBoxPlacement", "Competency", "CompetencyProfile",
			"CareerPath", "Survey", "SurveyQuestion", "SurveyResponse",
			"Certification", "OnboardingPlan", "OnboardingTask", "InterviewDebrief",
		}
		for name in expected_models:
			assert name in pkg.__all__, f"{name!r} missing from talent package __all__"

	def test_init_all_includes_new_errors(self):
		import pgappforge.plugins.erp.hcm.talent as pkg
		for name in ("GoalNotFoundError", "PIPNotFoundError", "SuccessionPlanNotFoundError", "CycleNotFoundError"):
			assert name in pkg.__all__, f"{name!r} missing from talent package __all__"
