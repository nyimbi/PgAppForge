"""
tests/ci/test_recruiting_plugin.py

CI tests for the HCM Recruiting / ATS plugin.

Uses real objects + pytest fixtures; no mocks.
Async tests use plain async functions + event loop.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone, timedelta
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Minimal in-memory session stub for unit-level tests
# (avoids requiring a live DB in CI)
# ---------------------------------------------------------------------------

class _Store:
	"""Tiny in-memory object store mimicking Session.get / add / flush."""

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
		"""Return empty results; tests that need real queries use fixtures."""
		return _EmptyResult()

	def scalar(self, stmt: Any) -> Any:
		return None


class _EmptyResult:
	def scalars(self) -> "_EmptyResult":
		return self

	def all(self) -> list:
		return []

	def scalar_one_or_none(self) -> Any:
		return None

	def scalar_one(self) -> int:
		return 0

	def one_or_none(self) -> Any:
		return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session() -> _Store:
	return _Store()


@pytest.fixture
def tenant_id() -> str:
	return "tenant-rec-test-0001"


@pytest.fixture
def svc():
	from pgappforge.plugins.erp.hcm.recruiting.services import RecruitingService
	return RecruitingService()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_event_types_are_correct() -> None:
	from pgappforge.plugins.erp.hcm.recruiting.events import (
		RequisitionPostedEvent,
		ApplicationReceivedEvent,
		InterviewScheduledEvent,
		OfferExtendedEvent,
		OfferAcceptedEvent,
		RequisitionFilledEvent,
	)
	assert RequisitionPostedEvent.event_type == "hcm.recruiting.requisition.posted"
	assert ApplicationReceivedEvent.event_type == "hcm.recruiting.application.received"
	assert InterviewScheduledEvent.event_type == "hcm.recruiting.interview.scheduled"
	assert OfferExtendedEvent.event_type == "hcm.recruiting.offer.extended"
	assert OfferAcceptedEvent.event_type == "hcm.recruiting.offer.accepted"
	assert RequisitionFilledEvent.event_type == "hcm.recruiting.requisition.filled"


# ---------------------------------------------------------------------------
# Models import
# ---------------------------------------------------------------------------

def test_models_importable() -> None:
	from pgappforge.plugins.erp.hcm.recruiting.models import (
		JobRequisition,
		JobApplication,
		InterviewSchedule,
		OfferLetter,
	)
	assert JobRequisition.__tablename__ == "rec_requisition"
	assert JobApplication.__tablename__ == "rec_application"
	assert InterviewSchedule.__tablename__ == "rec_interview"
	assert OfferLetter.__tablename__ == "rec_offer"


# ---------------------------------------------------------------------------
# post_requisition
# ---------------------------------------------------------------------------

def test_post_requisition_creates_open_req(svc, session, tenant_id) -> None:
	req = svc.post_requisition(
		"Senior Engineer",
		tenant_id,
		session,
		headcount=2,
		employment_type="FULL_TIME",
	)
	assert req.status == "OPEN"
	assert req.title == "Senior Engineer"
	assert req.headcount == 2
	assert req.posted_at is not None


# ---------------------------------------------------------------------------
# receive_application
# ---------------------------------------------------------------------------

def test_receive_application_against_open_req(svc, session, tenant_id) -> None:
	req = svc.post_requisition("Data Analyst", tenant_id, session)
	app = svc.receive_application(
		req.id,
		"Alice Kamau",
		"alice@example.com",
		session,
		source="LINKEDIN",
	)
	assert app.status == "APPLIED"
	assert app.candidate_name == "Alice Kamau"
	assert app.source == "LINKEDIN"
	assert app.requisition_id == req.id


def test_receive_application_closed_req_raises(svc, session, tenant_id) -> None:
	from pgappforge.plugins.erp.hcm.recruiting.services import RecruitingStateError

	req = svc.post_requisition("Analyst", tenant_id, session)
	req.status = "ON_HOLD"

	with pytest.raises(RecruitingStateError, match="OPEN"):
		svc.receive_application(req.id, "Bob", "bob@example.com", session)


# ---------------------------------------------------------------------------
# advance_status
# ---------------------------------------------------------------------------

def test_advance_status_valid_transition(svc, session, tenant_id) -> None:
	req = svc.post_requisition("PM", tenant_id, session)
	app = svc.receive_application(req.id, "Carol", "carol@example.com", session)
	app = svc.advance_status(app.id, "SCREENING", session)
	assert app.status == "SCREENING"


def test_advance_status_invalid_transition_raises(svc, session, tenant_id) -> None:
	from pgappforge.plugins.erp.hcm.recruiting.services import RecruitingStateError

	req = svc.post_requisition("Dev", tenant_id, session)
	app = svc.receive_application(req.id, "Dave", "dave@example.com", session)
	with pytest.raises(RecruitingStateError):
		svc.advance_status(app.id, "HIRED", session)  # APPLIED → HIRED is not allowed


def test_advance_to_rejected_stores_reason(svc, session, tenant_id) -> None:
	req = svc.post_requisition("QA", tenant_id, session)
	app = svc.receive_application(req.id, "Eve", "eve@example.com", session)
	app = svc.advance_status(app.id, "REJECTED", session, rejection_reason="Not enough experience")
	assert app.status == "REJECTED"
	assert "Not enough experience" in app.rejection_reason


# ---------------------------------------------------------------------------
# schedule_interview
# ---------------------------------------------------------------------------

def test_schedule_interview_creates_record(svc, session, tenant_id) -> None:
	req = svc.post_requisition("Designer", tenant_id, session)
	app = svc.receive_application(req.id, "Frank", "frank@example.com", session)

	when = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
	schedule = svc.schedule_interview(
		app.id, "interviewer-001", when, session,
		duration_minutes=45,
		format="VIDEO",
	)
	assert schedule.interviewer_id == "interviewer-001"
	assert schedule.duration_minutes == 45
	assert schedule.format == "VIDEO"
	assert schedule.completed_at is None


# ---------------------------------------------------------------------------
# submit_feedback
# ---------------------------------------------------------------------------

def test_submit_feedback_marks_complete(svc, session, tenant_id) -> None:
	req = svc.post_requisition("Devops", tenant_id, session)
	app = svc.receive_application(req.id, "Grace", "grace@example.com", session)
	when = datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc)
	schedule = svc.schedule_interview(app.id, "interviewer-002", when, session)

	schedule = svc.submit_feedback(
		schedule.id, "Strong candidate", 4, "YES", session
	)
	assert schedule.feedback == "Strong candidate"
	assert schedule.rating == 4
	assert schedule.recommendation == "YES"
	assert schedule.completed_at is not None


def test_submit_feedback_invalid_rating_raises(svc, session, tenant_id) -> None:
	req = svc.post_requisition("Ops", tenant_id, session)
	app = svc.receive_application(req.id, "Hank", "hank@example.com", session)
	when = datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)
	schedule = svc.schedule_interview(app.id, "interviewer-003", when, session)

	with pytest.raises(AssertionError):
		svc.submit_feedback(schedule.id, "ok", 6, "YES", session)


# ---------------------------------------------------------------------------
# create_offer
# ---------------------------------------------------------------------------

def test_create_offer_creates_draft(svc, session, tenant_id) -> None:
	req = svc.post_requisition("Lead", tenant_id, session)
	app = svc.receive_application(req.id, "Irene", "irene@example.com", session)
	# advance to INTERVIEW stage first
	app = svc.advance_status(app.id, "SCREENING", session)
	app = svc.advance_status(app.id, "PHONE_SCREEN", session)
	app = svc.advance_status(app.id, "INTERVIEW", session)

	offer = svc.create_offer(
		app.id,
		salary_cents=5_000_000,
		start_date=date(2026, 8, 1),
		expiry_date=date(2026, 7, 15),
		tenant_id=tenant_id,
		session=session,
		bonus_cents=500_000,
		currency_code="KES",
	)
	assert offer.offered_salary_cents == 5_000_000
	assert offer.bonus_cents == 500_000
	assert offer.currency_code == "KES"
	assert offer.status == "DRAFT"
	# application should have advanced to OFFER
	assert app.status == "OFFER"


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

def test_plugin_metadata() -> None:
	from pgappforge.plugins.erp.hcm.recruiting import RecruitingPlugin

	plugin = RecruitingPlugin(None)
	meta = plugin.metadata
	assert meta.name == "recruiting"
	assert meta.version == "1.0.0"
	assert "ats" in meta.tags
	assert "hcm" in meta.tags


def test_plugin_subscribe_to() -> None:
	from pgappforge.plugins.erp.hcm.recruiting import RecruitingPlugin

	plugin = RecruitingPlugin(None)
	assert "hcm.employee.hired" in plugin.subscribe_to()


def test_plugin_register_models() -> None:
	from pgappforge.plugins.erp.hcm.recruiting import RecruitingPlugin

	plugin = RecruitingPlugin(None)
	models = plugin.register_models()
	names = [m.__tablename__ for m in models]
	assert "rec_requisition" in names
	assert "rec_application" in names
	assert "rec_interview" in names
	assert "rec_offer" in names
