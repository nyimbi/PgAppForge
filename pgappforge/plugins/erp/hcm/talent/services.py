"""
pgappforge/plugins/erp/hcm/talent/services.py

TalentService — stateless business logic for the HCM Talent Management plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Public methods:
  approve_requisition(req_id, approver_id, session)       -> Requisition
  post_requisition(req_id, session)                       -> Requisition
  advance_stage(application_id, new_stage, session)       -> Application
  schedule_interview(application_id, data, session)       -> Interview
  complete_interview(interview_id, scorecard, rating, recommendation, session) -> Interview
  extend_offer(application_id, offer_data, session)       -> Offer
  send_offer(offer_id, session)                           -> Offer
  accept_offer(offer_id, session)                         -> Offer
  decline_offer(offer_id, reason, session)                -> Offer
  expire_stale_offers(session)                            -> int  (count expired)
  submit_review(review_id, session)                       -> PerformanceReview
  finalise_review(review_id, session)                     -> PerformanceReview
  enroll_training(employee_id, course_id, session)        -> TrainingEnrollment
  complete_training(enrollment_id, score, certificate_url, session) -> TrainingEnrollment
  pipeline_summary(requisition_id, session)               -> dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TalentServiceError(Exception):
	"""Base domain error for talent operations."""


class RequisitionNotFoundError(TalentServiceError):
	pass


class ApplicationNotFoundError(TalentServiceError):
	pass


class OfferNotFoundError(TalentServiceError):
	pass


class ReviewNotFoundError(TalentServiceError):
	pass


class EnrollmentNotFoundError(TalentServiceError):
	pass


class TalentStateError(TalentServiceError):
	"""Invalid state transition."""


class TalentValidationError(TalentServiceError):
	"""Business rule violation."""


class GoalNotFoundError(TalentServiceError):
	pass


class PIPNotFoundError(TalentServiceError):
	pass


class SuccessionPlanNotFoundError(TalentServiceError):
	pass


class CycleNotFoundError(TalentServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today() -> date:
	return datetime.now(timezone.utc).date()


_STAGE_ORDER = ["APPLIED", "SCREENING", "INTERVIEW", "OFFER", "ACCEPTED", "REJECTED"]


def _validate_stage_transition(old: str, new: str) -> None:
	"""Enforce that stage advances forward (or jumps to REJECTED from anywhere)."""
	if new == "REJECTED":
		return
	try:
		if _STAGE_ORDER.index(new) <= _STAGE_ORDER.index(old):
			raise TalentStateError(
				f"Cannot move application stage from {old!r} to {new!r}: must advance forward"
			)
	except ValueError:
		raise TalentStateError(f"Unknown application stage: {new!r}")


# ---------------------------------------------------------------------------
# TalentService
# ---------------------------------------------------------------------------

class TalentService:
	"""Stateless talent domain service."""

	# ------------------------------------------------------------------
	# Requisition lifecycle
	# ------------------------------------------------------------------

	def approve_requisition(
		self,
		requisition_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Approve a DRAFT requisition.

		Transitions: DRAFT → APPROVED
		Emits RequisitionApprovedEvent.

		Raises:
			RequisitionNotFoundError
			TalentStateError: not DRAFT
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Requisition
		from pgappforge.plugins.erp.hcm.talent.events import RequisitionApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		req = session.get(Requisition, requisition_id)
		if req is None:
			raise RequisitionNotFoundError(f"Requisition {requisition_id!r} not found")
		if req.status != "DRAFT":
			raise TalentStateError(
				f"Requisition {requisition_id!r} is {req.status!r}; must be DRAFT to approve"
			)

		now = datetime.now(timezone.utc)
		req.approved_by = approver_id
		req.approved_at = now
		req.status = "APPROVED"
		req.updated_at = now

		emit_event(
			RequisitionApprovedEvent(
				aggregate_id=requisition_id,
				aggregate_type="Requisition",
				tenant_id=req.tenant_id,
				requisition_id=requisition_id,
				requisition_number=req.requisition_number,
				position_id=req.position_id or "",
				hiring_manager_id=req.hiring_manager_id or "",
				headcount=req.headcount,
				salary_range_min_cents=req.salary_range_min_cents or 0,
				salary_range_max_cents=req.salary_range_max_cents or 0,
				currency=req.currency_code,
			),
			session,
		)
		log.info("TalentService.approve_requisition: req=%s approver=%s", requisition_id, approver_id)
		return req

	def post_requisition(self, requisition_id: str, session: Any) -> Any:
		"""Transition APPROVED → POSTED (job board publication)."""
		from pgappforge.plugins.erp.hcm.talent.models import Requisition

		req = session.get(Requisition, requisition_id)
		if req is None:
			raise RequisitionNotFoundError(f"Requisition {requisition_id!r} not found")
		if req.status != "APPROVED":
			raise TalentStateError(f"Requisition {requisition_id!r} must be APPROVED to post")
		req.status = "POSTED"
		req.updated_at = datetime.now(timezone.utc)
		log.info("TalentService.post_requisition: req=%s", requisition_id)
		return req

	# ------------------------------------------------------------------
	# Application / pipeline
	# ------------------------------------------------------------------

	def advance_stage(
		self,
		application_id: str,
		new_stage: str,
		session: Any,
		rejection_reason: str = "",
		recruiter_notes: str = "",
	) -> Any:
		"""Move an application to a new pipeline stage.

		Validates forward-only transitions (REJECTED is always permitted).
		Emits ApplicationStageChangedEvent.
		When new_stage = ACCEPTED, checks that an ACCEPTED offer exists.

		Raises:
			ApplicationNotFoundError
			TalentStateError: invalid transition
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Application, Offer
		from pgappforge.plugins.erp.hcm.talent.events import ApplicationStageChangedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		app = session.get(Application, application_id)
		if app is None:
			raise ApplicationNotFoundError(f"Application {application_id!r} not found")

		old_stage = app.stage
		_validate_stage_transition(old_stage, new_stage)

		if new_stage == "ACCEPTED":
			# Offer must be accepted first
			offer = session.execute(
				sa.select(Offer).where(Offer.application_id == application_id)
			).scalar_one_or_none()
			if offer is None or offer.status != "ACCEPTED":
				raise TalentStateError(
					"Application cannot move to ACCEPTED without an ACCEPTED offer"
				)

		now = datetime.now(timezone.utc)
		app.stage = new_stage
		if rejection_reason:
			app.rejection_reason = rejection_reason
		if recruiter_notes:
			app.recruiter_notes = recruiter_notes
		app.updated_at = now

		emit_event(
			ApplicationStageChangedEvent(
				aggregate_id=application_id,
				aggregate_type="Application",
				tenant_id=app.tenant_id,
				application_id=application_id,
				requisition_id=app.requisition_id,
				candidate_id=app.candidate_id,
				old_stage=old_stage,
				new_stage=new_stage,
				rejection_reason=rejection_reason,
			),
			session,
		)

		# When filled, update requisition status if all headcount filled
		if new_stage == "ACCEPTED":
			self._check_requisition_filled(app.requisition_id, session)

		log.info(
			"TalentService.advance_stage: app=%s %s→%s",
			application_id, old_stage, new_stage,
		)
		return app

	def _check_requisition_filled(self, requisition_id: str, session: Any) -> None:
		"""Check if requisition headcount is fully filled; update status if so."""
		from pgappforge.plugins.erp.hcm.talent.models import Application, Requisition
		from pgappforge.plugins.erp.hcm.talent.events import RequisitionFilledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		req = session.get(Requisition, requisition_id)
		if req is None or req.status in ("FILLED", "CANCELLED"):
			return

		accepted_count = session.execute(
			sa.select(sa.func.count())
			.select_from(Application)
			.where(Application.requisition_id == requisition_id)
			.where(Application.stage == "ACCEPTED")
		).scalar()

		if accepted_count >= req.headcount:
			now = datetime.now(timezone.utc)
			days_to_fill = (now.date() - req.approved_at.date()).days if req.approved_at else 0
			req.status = "FILLED"
			req.filled_at = now
			req.updated_at = now

			emit_event(
				RequisitionFilledEvent(
					aggregate_id=requisition_id,
					aggregate_type="Requisition",
					tenant_id=req.tenant_id,
					requisition_id=requisition_id,
					requisition_number=req.requisition_number,
					filled_headcount=accepted_count,
					days_to_fill=days_to_fill,
				),
				session,
			)

	# ------------------------------------------------------------------
	# Interview management
	# ------------------------------------------------------------------

	def schedule_interview(
		self,
		application_id: str,
		data: dict,
		session: Any,
	) -> Any:
		"""Create a scheduled Interview for an application.

		data keys: interview_type, scheduled_at (ISO datetime str), duration_minutes,
		           interviewer_ids (list[str]), location (optional)

		Raises:
			ApplicationNotFoundError
			TalentValidationError: application not in INTERVIEW stage
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Application, Interview

		app = session.get(Application, application_id)
		if app is None:
			raise ApplicationNotFoundError(f"Application {application_id!r} not found")

		if app.stage not in ("SCREENING", "INTERVIEW"):
			raise TalentValidationError(
				f"Application {application_id!r} is in stage {app.stage!r}; "
				"must be SCREENING or INTERVIEW to schedule interview"
			)

		scheduled_at = (
			datetime.fromisoformat(data["scheduled_at"])
			if isinstance(data["scheduled_at"], str)
			else data["scheduled_at"]
		)

		interview = Interview(
			tenant_id=app.tenant_id,
			application_id=application_id,
			interview_type=data["interview_type"],
			scheduled_at=scheduled_at,
			duration_minutes=int(data.get("duration_minutes", 60)),
			interviewer_ids=data.get("interviewer_ids") or [],
			location=data.get("location"),
			status="SCHEDULED",
		)
		session.add(interview)

		# Auto-advance to INTERVIEW stage if still in SCREENING
		if app.stage == "SCREENING":
			app.stage = "INTERVIEW"
			app.updated_at = datetime.now(timezone.utc)

		log.info(
			"TalentService.schedule_interview: app=%s type=%s at=%s",
			application_id, data["interview_type"], scheduled_at,
		)
		return interview

	def complete_interview(
		self,
		interview_id: str,
		scorecard: dict,
		overall_rating: str,
		recommendation: str,
		session: Any,
	) -> Any:
		"""Record interview completion with scorecard.

		overall_rating: string decimal "1.0"–"5.0"
		recommendation: HIRE | NO_HIRE | MAYBE

		Raises:
			TalentStateError: interview not in SCHEDULED status
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Interview
		from decimal import Decimal

		interview = session.execute(
			sa.select(Interview).where(Interview.id == interview_id)
		).scalar_one_or_none()
		if interview is None:
			raise TalentServiceError(f"Interview {interview_id!r} not found")
		if interview.status != "SCHEDULED":
			raise TalentStateError(
				f"Interview {interview_id!r} is {interview.status!r}; must be SCHEDULED to complete"
			)
		if recommendation not in ("HIRE", "NO_HIRE", "MAYBE"):
			raise TalentValidationError(f"Invalid recommendation {recommendation!r}")

		now = datetime.now(timezone.utc)
		interview.scorecard = scorecard
		interview.overall_rating = Decimal(str(overall_rating))
		interview.recommendation = recommendation
		interview.status = "COMPLETED"
		interview.completed_at = now
		interview.updated_at = now

		log.info(
			"TalentService.complete_interview: id=%s rating=%s recommendation=%s",
			interview_id, overall_rating, recommendation,
		)
		return interview

	# ------------------------------------------------------------------
	# Offer management
	# ------------------------------------------------------------------

	def extend_offer(
		self,
		application_id: str,
		offer_data: dict,
		session: Any,
	) -> Any:
		"""Create a DRAFT offer for an application.

		offer_data keys: base_salary_cents (int), currency_code, start_date (ISO),
		                 expiry_date (ISO), signing_bonus_cents (int, default 0),
		                 equity_details (dict), notes

		Raises:
			ApplicationNotFoundError
			TalentValidationError: base_salary_cents must be positive int
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Application, Offer

		app = session.get(Application, application_id)
		if app is None:
			raise ApplicationNotFoundError(f"Application {application_id!r} not found")

		base_salary = int(offer_data["base_salary_cents"])
		assert isinstance(base_salary, int), "base_salary_cents must be int"
		if base_salary <= 0:
			raise TalentValidationError("base_salary_cents must be positive")

		signing_bonus = int(offer_data.get("signing_bonus_cents", 0))
		assert isinstance(signing_bonus, int)

		start_date = (
			date.fromisoformat(offer_data["start_date"])
			if isinstance(offer_data["start_date"], str)
			else offer_data["start_date"]
		)
		expiry_date = (
			date.fromisoformat(offer_data["expiry_date"])
			if isinstance(offer_data["expiry_date"], str)
			else offer_data["expiry_date"]
		)

		offer = Offer(
			tenant_id=app.tenant_id,
			application_id=application_id,
			base_salary_cents=base_salary,
			currency_code=offer_data.get("currency_code", "USD"),
			signing_bonus_cents=signing_bonus,
			equity_details=offer_data.get("equity_details") or {},
			start_date=start_date,
			expiry_date=expiry_date,
			status="DRAFT",
			notes=offer_data.get("notes"),
		)
		session.add(offer)
		log.info(
			"TalentService.extend_offer: app=%s base=%d¢",
			application_id, base_salary,
		)
		return offer

	def send_offer(self, offer_id: str, session: Any) -> Any:
		"""Transition DRAFT → SENT and emit OfferSentEvent."""
		from pgappforge.plugins.erp.hcm.talent.models import Offer
		from pgappforge.plugins.erp.hcm.talent.events import OfferSentEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		offer = session.get(Offer, offer_id)
		if offer is None:
			raise OfferNotFoundError(f"Offer {offer_id!r} not found")
		if offer.status != "DRAFT":
			raise TalentStateError(f"Offer {offer_id!r} is {offer.status!r}; must be DRAFT to send")

		now = datetime.now(timezone.utc)
		offer.status = "SENT"
		offer.sent_at = now
		offer.updated_at = now

		emit_event(
			OfferSentEvent(
				aggregate_id=offer_id,
				aggregate_type="Offer",
				tenant_id=offer.tenant_id,
				offer_id=offer_id,
				application_id=offer.application_id,
				candidate_id=offer.application.candidate_id if offer.application else "",
				base_salary_cents=offer.base_salary_cents,
				signing_bonus_cents=offer.signing_bonus_cents,
				currency=offer.currency_code,
				start_date=offer.start_date.isoformat(),
				expiry_date=offer.expiry_date.isoformat(),
			),
			session,
		)
		return offer

	def accept_offer(self, offer_id: str, session: Any) -> Any:
		"""Transition SENT → ACCEPTED and emit OfferAcceptedEvent."""
		from pgappforge.plugins.erp.hcm.talent.models import Offer
		from pgappforge.plugins.erp.hcm.talent.events import OfferAcceptedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		offer = session.get(Offer, offer_id)
		if offer is None:
			raise OfferNotFoundError(f"Offer {offer_id!r} not found")
		if offer.status != "SENT":
			raise TalentStateError(f"Offer {offer_id!r} is {offer.status!r}; must be SENT to accept")

		if offer.expiry_date < _today():
			raise TalentStateError(f"Offer {offer_id!r} expired on {offer.expiry_date}")

		now = datetime.now(timezone.utc)
		offer.status = "ACCEPTED"
		offer.responded_at = now
		offer.updated_at = now

		app = offer.application
		candidate_id = app.candidate_id if app else ""
		req_id = app.requisition_id if app else ""

		emit_event(
			OfferAcceptedEvent(
				aggregate_id=offer_id,
				aggregate_type="Offer",
				tenant_id=offer.tenant_id,
				offer_id=offer_id,
				application_id=offer.application_id,
				candidate_id=candidate_id,
				requisition_id=req_id,
				base_salary_cents=offer.base_salary_cents,
				currency=offer.currency_code,
				start_date=offer.start_date.isoformat(),
			),
			session,
		)
		log.info("TalentService.accept_offer: offer=%s", offer_id)
		return offer

	def decline_offer(self, offer_id: str, reason: str, session: Any) -> Any:
		"""Transition SENT → DECLINED and emit OfferDeclinedEvent."""
		from pgappforge.plugins.erp.hcm.talent.models import Offer
		from pgappforge.plugins.erp.hcm.talent.events import OfferDeclinedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		offer = session.get(Offer, offer_id)
		if offer is None:
			raise OfferNotFoundError(f"Offer {offer_id!r} not found")
		if offer.status != "SENT":
			raise TalentStateError(f"Offer {offer_id!r} is {offer.status!r}; must be SENT to decline")

		now = datetime.now(timezone.utc)
		offer.status = "DECLINED"
		offer.responded_at = now
		offer.decline_reason = reason
		offer.updated_at = now

		app = offer.application
		emit_event(
			OfferDeclinedEvent(
				aggregate_id=offer_id,
				aggregate_type="Offer",
				tenant_id=offer.tenant_id,
				offer_id=offer_id,
				application_id=offer.application_id,
				candidate_id=app.candidate_id if app else "",
				decline_reason=reason,
			),
			session,
		)
		return offer

	def expire_stale_offers(self, session: Any) -> int:
		"""Mark all SENT offers past expiry_date as EXPIRED.

		Returns count of offers expired.
		Intended for daily scheduled job.
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Offer

		now = datetime.now(timezone.utc)
		result = session.execute(
			sa.update(Offer)
			.where(Offer.status == "SENT")
			.where(Offer.expiry_date < now.date())
			.values(status="EXPIRED", updated_at=now)
		)
		count = result.rowcount
		if count:
			log.info("TalentService.expire_stale_offers: expired %d offers", count)
		return count

	# ------------------------------------------------------------------
	# Performance review
	# ------------------------------------------------------------------

	def submit_review(self, review_id: str, session: Any) -> Any:
		"""Transition DRAFT → SUBMITTED."""
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceReview

		review = session.get(PerformanceReview, review_id)
		if review is None:
			raise ReviewNotFoundError(f"PerformanceReview {review_id!r} not found")
		if review.status != "DRAFT":
			raise TalentStateError(f"Review {review_id!r} must be DRAFT to submit")

		now = datetime.now(timezone.utc)
		review.status = "SUBMITTED"
		review.submitted_at = now
		review.updated_at = now
		return review

	def finalise_review(self, review_id: str, session: Any) -> Any:
		"""Transition SUBMITTED | CALIBRATED → FINAL and emit PerformanceReviewFinalisedEvent."""
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceReview
		from pgappforge.plugins.erp.hcm.talent.events import PerformanceReviewFinalisedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		review = session.get(PerformanceReview, review_id)
		if review is None:
			raise ReviewNotFoundError(f"PerformanceReview {review_id!r} not found")
		if review.status not in ("SUBMITTED", "CALIBRATED"):
			raise TalentStateError(
				f"Review {review_id!r} is {review.status!r}; must be SUBMITTED or CALIBRATED to finalise"
			)
		if review.overall_rating is None:
			raise TalentValidationError("overall_rating must be set before finalising review")

		now = datetime.now(timezone.utc)
		review.status = "FINAL"
		review.finalised_at = now
		review.updated_at = now

		emit_event(
			PerformanceReviewFinalisedEvent(
				aggregate_id=review_id,
				aggregate_type="PerformanceReview",
				tenant_id=review.tenant_id,
				review_id=review_id,
				employee_id=review.employee_id,
				reviewer_id=review.reviewer_id,
				review_cycle=review.review_cycle,
				period_end=review.period_end.isoformat(),
				overall_rating=str(review.overall_rating),
				rating_label=review.rating_label or "",
			),
			session,
		)
		log.info(
			"TalentService.finalise_review: id=%s employee=%s rating=%s",
			review_id, review.employee_id, review.overall_rating,
		)
		return review

	# ------------------------------------------------------------------
	# Training
	# ------------------------------------------------------------------

	def enroll_training(
		self,
		employee_id: str,
		course_id: str,
		session: Any,
	) -> Any:
		"""Enroll an employee in a training course.

		Raises:
			TalentValidationError: course not active or employee already enrolled
		"""
		from pgappforge.plugins.erp.hcm.talent.models import TrainingCourse, TrainingEnrollment

		course = session.get(TrainingCourse, course_id)
		if course is None:
			raise TalentServiceError(f"TrainingCourse {course_id!r} not found")
		if not course.is_active:
			raise TalentValidationError(f"TrainingCourse {course_id!r} is inactive")

		existing = session.execute(
			sa.select(TrainingEnrollment)
			.where(TrainingEnrollment.employee_id == employee_id)
			.where(TrainingEnrollment.course_id == course_id)
		).scalar_one_or_none()
		if existing is not None and existing.status not in ("WITHDRAWN", "FAILED"):
			raise TalentValidationError(
				f"Employee {employee_id!r} already enrolled in course {course_id!r} "
				f"with status {existing.status!r}"
			)

		# Retrieve tenant_id from existing enrollment or default
		tenant_id = existing.tenant_id if existing else ""

		enrollment = TrainingEnrollment(
			tenant_id=tenant_id,
			employee_id=employee_id,
			course_id=course_id,
			status="ENROLLED",
		)
		session.add(enrollment)
		log.info(
			"TalentService.enroll_training: employee=%s course=%s",
			employee_id, course_id,
		)
		return enrollment

	def complete_training(
		self,
		enrollment_id: str,
		score: str,
		certificate_url: str,
		session: Any,
	) -> Any:
		"""Mark a training enrollment as COMPLETED.

		score: string decimal "0.00"–"100.00" (avoids float)
		Emits TrainingCompletedEvent.

		Raises:
			EnrollmentNotFoundError
			TalentStateError: enrollment not in ENROLLED or IN_PROGRESS
		"""
		from decimal import Decimal
		from pgappforge.plugins.erp.hcm.talent.models import TrainingEnrollment
		from pgappforge.plugins.erp.hcm.talent.events import TrainingCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		enrollment = session.get(TrainingEnrollment, enrollment_id)
		if enrollment is None:
			raise EnrollmentNotFoundError(f"TrainingEnrollment {enrollment_id!r} not found")
		if enrollment.status not in ("ENROLLED", "IN_PROGRESS"):
			raise TalentStateError(
				f"Enrollment {enrollment_id!r} is {enrollment.status!r}; "
				"must be ENROLLED or IN_PROGRESS to complete"
			)

		score_dec = Decimal(str(score))
		now = datetime.now(timezone.utc)
		enrollment.score = score_dec
		enrollment.certificate_url = certificate_url
		enrollment.status = "COMPLETED"
		enrollment.completed_at = now
		enrollment.updated_at = now

		course = enrollment.course
		emit_event(
			TrainingCompletedEvent(
				aggregate_id=enrollment_id,
				aggregate_type="TrainingEnrollment",
				tenant_id=enrollment.tenant_id,
				enrollment_id=enrollment_id,
				employee_id=enrollment.employee_id,
				course_id=enrollment.course_id,
				course_code=course.course_code if course else "",
				score=str(score_dec),
				certificate_url=certificate_url,
				duration_hours=str(course.duration_hours) if course else "0",
			),
			session,
		)
		log.info(
			"TalentService.complete_training: enrollment=%s employee=%s score=%s",
			enrollment_id, enrollment.employee_id, score,
		)
		return enrollment

	# ------------------------------------------------------------------
	# Reporting helper
	# ------------------------------------------------------------------

	# ------------------------------------------------------------------
	# OKR / Goal management
	# ------------------------------------------------------------------

	def create_goal(
		self,
		tenant_id: str,
		employee_id: str,
		title: str,
		level: str,
		period: str,
		*,
		description: str | None = None,
		weight: float = 100.0,
		parent_goal_id: str | None = None,
		cycle_id: str | None = None,
		key_results: list[dict[str, Any]] | None = None,
		session: Any,
	) -> Any:
		"""Create a goal/OKR for an employee.

		level: COMPANY | DEPARTMENT | INDIVIDUAL
		key_results: [{kr_text, target_value, current_value, unit}]
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Goal

		_VALID_LEVELS = {"COMPANY", "DEPARTMENT", "INDIVIDUAL"}
		if level not in _VALID_LEVELS:
			raise TalentValidationError(f"Invalid goal level {level!r}; must be one of {_VALID_LEVELS}")

		if parent_goal_id is not None:
			parent = session.get(Goal, parent_goal_id)
			if parent is None:
				raise TalentValidationError(f"Parent goal {parent_goal_id!r} not found")

		goal = Goal(
			tenant_id=tenant_id,
			employee_id=employee_id,
			title=title,
			level=level,
			period=period,
			description=description,
			weight=weight,
			parent_goal_id=parent_goal_id,
			cycle_id=cycle_id,
			key_results=key_results or [],
			status="DRAFT",
			progress_pct=0,
		)
		try:
			session.add(goal)
			session.flush()
		except Exception:
			log.exception("TalentService.create_goal: DB error employee=%s title=%r", employee_id, title)
			raise
		log.info("TalentService.create_goal: created goal=%s employee=%s level=%s", goal.id, employee_id, level)
		return goal

	def update_goal_progress(
		self,
		goal_id: str,
		progress_pct: float,
		*,
		key_results: list[dict[str, Any]] | None = None,
		session: Any,
	) -> Any:
		"""Update progress on a goal and recalculate weighted progress up the parent chain.

		progress_pct: 0–100.
		key_results: if provided, replaces the goal's key_results list.
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Goal

		if not (0 <= progress_pct <= 100):
			raise TalentValidationError(f"progress_pct must be 0–100, got {progress_pct}")

		goal = session.get(Goal, goal_id)
		if goal is None:
			raise TalentValidationError(f"Goal {goal_id!r} not found")

		try:
			goal.progress_pct = progress_pct
			if key_results is not None:
				goal.key_results = key_results
			goal.updated_at = datetime.now(timezone.utc)
			session.flush()

			# Roll weighted progress up to parent(s)
			current = goal
			while current.parent_goal_id is not None:
				parent = session.get(Goal, current.parent_goal_id)
				if parent is None:
					break
				siblings = session.execute(
					sa.select(Goal).where(Goal.parent_goal_id == parent.id)
				).scalars().all()
				total_weight = sum(float(s.weight) for s in siblings)
				if total_weight > 0:
					weighted_sum = sum(float(s.progress_pct) * float(s.weight) for s in siblings)
					parent.progress_pct = round(weighted_sum / total_weight, 2)
				parent.updated_at = datetime.now(timezone.utc)
				session.flush()
				current = parent
		except Exception:
			log.exception("TalentService.update_goal_progress: DB error goal=%s", goal_id)
			raise

		log.info("TalentService.update_goal_progress: goal=%s progress=%.1f%%", goal_id, progress_pct)
		return goal

	def cascade_goals(
		self,
		parent_goal_id: str,
		child_employee_ids: list[str],
		*,
		session: Any,
	) -> list[Any]:
		"""Create cloned child goals for each employee in child_employee_ids.

		Each child goal inherits title, description, level→INDIVIDUAL, period,
		cycle_id, and weight from the parent.
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Goal

		parent = session.get(Goal, parent_goal_id)
		if parent is None:
			raise TalentValidationError(f"Parent goal {parent_goal_id!r} not found")

		created: list[Any] = []
		try:
			for emp_id in child_employee_ids:
				child = Goal(
					tenant_id=parent.tenant_id,
					employee_id=emp_id,
					parent_goal_id=parent.id,
					title=parent.title,
					description=parent.description,
					level="INDIVIDUAL",
					period=parent.period,
					cycle_id=parent.cycle_id,
					weight=parent.weight,
					key_results=[],
					status="DRAFT",
					progress_pct=0,
				)
				session.add(child)
				created.append(child)
			session.flush()
		except Exception:
			log.exception("TalentService.cascade_goals: DB error parent=%s", parent_goal_id)
			raise

		log.info("TalentService.cascade_goals: cascaded parent=%s to %d employees", parent_goal_id, len(created))
		return created

	def close_goals_for_period(self, tenant_id: str, period: str, *, session: Any) -> int:
		"""Mark all ACTIVE goals for the given tenant+period as COMPLETED.

		Returns the count of goals closed.
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Goal

		try:
			result = session.execute(
				sa.update(Goal)
				.where(Goal.tenant_id == tenant_id)
				.where(Goal.period == period)
				.where(Goal.status == "ACTIVE")
				.values(status="COMPLETED", updated_at=datetime.now(timezone.utc))
			)
			count = result.rowcount
			session.flush()
		except Exception:
			log.exception("TalentService.close_goals_for_period: tenant=%s period=%s", tenant_id, period)
			raise

		log.info("TalentService.close_goals_for_period: closed %d goals tenant=%s period=%s", count, tenant_id, period)
		return count

	# ------------------------------------------------------------------
	# 360-degree appraisal
	# ------------------------------------------------------------------

	def launch_cycle(
		self,
		tenant_id: str,
		name: str,
		period: str,
		cycle_type: str,
		*,
		session: Any,
	) -> Any:
		"""Create and launch a performance cycle (moves to IN_PROGRESS immediately).

		cycle_type: ANNUAL | MID_YEAR | PROBATION | 360
		"""
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceCycle

		_VALID_TYPES = {"ANNUAL", "MID_YEAR", "PROBATION", "360"}
		if cycle_type not in _VALID_TYPES:
			raise TalentValidationError(f"Invalid cycle_type {cycle_type!r}")

		now = datetime.now(timezone.utc)
		cycle = PerformanceCycle(
			tenant_id=tenant_id,
			name=name,
			period=period,
			cycle_type=cycle_type,
			status="IN_PROGRESS",
			launched_at=now,
		)
		try:
			session.add(cycle)
			session.flush()
		except Exception:
			log.exception("TalentService.launch_cycle: DB error name=%r period=%r", name, period)
			raise

		log.info("TalentService.launch_cycle: cycle=%s name=%r period=%r type=%s", cycle.id, name, period, cycle_type)
		return cycle

	def invite_reviewers(
		self,
		cycle_id: str,
		appraisee_id: str,
		reviewers: list[dict[str, str]],
		*,
		session: Any,
	) -> list[Any]:
		"""Invite reviewers for an appraisee in a cycle.

		reviewers: [{appraiser_id, relationship_type}]
		relationship_type: SELF | PEER | MANAGER | SUBORDINATE | SKIP_LEVEL
		"""
		from pgappforge.plugins.erp.hcm.talent.models import PerformanceCycle, ReviewParticipant

		cycle = session.get(PerformanceCycle, cycle_id)
		if cycle is None:
			raise TalentValidationError(f"PerformanceCycle {cycle_id!r} not found")
		if cycle.status not in {"IN_PROGRESS", "PLANNING"}:
			raise TalentStateError(f"Cannot invite reviewers: cycle status is {cycle.status!r}")

		_VALID_REL = {"SELF", "PEER", "MANAGER", "SUBORDINATE", "SKIP_LEVEL"}
		participants: list[Any] = []
		try:
			for r in reviewers:
				rel = r.get("relationship_type", "PEER")
				if rel not in _VALID_REL:
					raise TalentValidationError(f"Invalid relationship_type {rel!r}")
				p = ReviewParticipant(
					tenant_id=cycle.tenant_id,
					cycle_id=cycle_id,
					appraisee_id=appraisee_id,
					appraiser_id=r["appraiser_id"],
					relationship_type=rel,
					status="INVITED",
					responses=[],
				)
				session.add(p)
				participants.append(p)
			session.flush()
		except TalentValidationError:
			raise
		except Exception:
			log.exception("TalentService.invite_reviewers: DB error cycle=%s appraisee=%s", cycle_id, appraisee_id)
			raise

		log.info("TalentService.invite_reviewers: cycle=%s appraisee=%s invited=%d", cycle_id, appraisee_id, len(participants))
		return participants

	def submit_peer_feedback(
		self,
		participant_id: str,
		responses: list[dict[str, Any]],
		*,
		session: Any,
	) -> Any:
		"""Submit feedback from a reviewer.

		responses: [{competency_code, score (1–5), comments}]
		Marks participant status=SUBMITTED.
		"""
		from pgappforge.plugins.erp.hcm.talent.models import ReviewParticipant

		participant = session.get(ReviewParticipant, participant_id)
		if participant is None:
			raise TalentValidationError(f"ReviewParticipant {participant_id!r} not found")
		if participant.status == "SUBMITTED":
			raise TalentStateError(f"Participant {participant_id!r} has already submitted feedback")
		if participant.status == "DECLINED":
			raise TalentStateError(f"Participant {participant_id!r} declined the review")

		for r in responses:
			score = r.get("score")
			if score is not None and not (1 <= float(score) <= 5):
				raise TalentValidationError(f"Score must be 1–5, got {score}")

		try:
			now = datetime.now(timezone.utc)
			participant.responses = responses
			participant.status = "SUBMITTED"
			participant.submitted_at = now
			participant.updated_at = now
			session.flush()
		except TalentValidationError:
			raise
		except Exception:
			log.exception("TalentService.submit_peer_feedback: DB error participant=%s", participant_id)
			raise

		log.info("TalentService.submit_peer_feedback: participant=%s submitted", participant_id)
		return participant

	def calculate_aggregate_score(self, cycle_id: str, employee_id: str, *, session: Any) -> dict[str, Any]:
		"""Compute aggregate 360 score for an appraisee in a cycle.

		Returns:
		  {
		    cycle_id, employee_id,
		    overall_avg: float,
		    by_relationship: {SELF: float, PEER: float, MANAGER: float, ...},
		    by_competency: {competency_code: float, ...},
		    participant_count: int,
		    submitted_count: int,
		    pending_count: int,
		  }
		"""
		from pgappforge.plugins.erp.hcm.talent.models import ReviewParticipant

		participants = session.execute(
			sa.select(ReviewParticipant)
			.where(ReviewParticipant.cycle_id == cycle_id)
			.where(ReviewParticipant.appraisee_id == employee_id)
		).scalars().all()

		submitted = [p for p in participants if p.status == "SUBMITTED"]
		pending = [p for p in participants if p.status == "INVITED"]

		by_relationship: dict[str, list[float]] = {}
		by_competency: dict[str, list[float]] = {}
		all_scores: list[float] = []

		for p in submitted:
			for r in (p.responses or []):
				score = r.get("score")
				if score is None:
					continue
				score = float(score)
				all_scores.append(score)
				rel = p.relationship_type
				by_relationship.setdefault(rel, []).append(score)
				code = r.get("competency_code", "UNKNOWN")
				by_competency.setdefault(code, []).append(score)

		def _avg(lst: list[float]) -> float:
			return round(sum(lst) / len(lst), 2) if lst else 0.0

		return {
			"cycle_id": cycle_id,
			"employee_id": employee_id,
			"overall_avg": _avg(all_scores),
			"by_relationship": {k: _avg(v) for k, v in by_relationship.items()},
			"by_competency": {k: _avg(v) for k, v in by_competency.items()},
			"participant_count": len(participants),
			"submitted_count": len(submitted),
			"pending_count": len(pending),
		}

	# ------------------------------------------------------------------
	# PIP workflow
	# ------------------------------------------------------------------

	def create_pip(
		self,
		tenant_id: str,
		employee_id: str,
		manager_id: str,
		start_date: date,
		end_date: date,
		improvement_areas: list[dict[str, Any]],
		*,
		triggered_by_review_id: str | None = None,
		check_in_frequency: str = "WEEKLY",
		session: Any,
	) -> Any:
		"""Create a PIP for an employee.

		improvement_areas: [{area, target_behaviour, success_criterion}]
		check_in_frequency: WEEKLY | BIWEEKLY
		"""
		from pgappforge.plugins.erp.hcm.talent.models import PIP

		if end_date <= start_date:
			raise TalentValidationError("PIP end_date must be after start_date")
		if check_in_frequency not in {"WEEKLY", "BIWEEKLY"}:
			raise TalentValidationError(f"Invalid check_in_frequency {check_in_frequency!r}")

		pip = PIP(
			tenant_id=tenant_id,
			employee_id=employee_id,
			manager_id=manager_id,
			triggered_by_review_id=triggered_by_review_id,
			start_date=start_date,
			end_date=end_date,
			improvement_areas=improvement_areas,
			check_in_frequency=check_in_frequency,
			status="ACTIVE",
		)
		try:
			session.add(pip)
			session.flush()
		except Exception:
			log.exception("TalentService.create_pip: DB error employee=%s", employee_id)
			raise

		log.info("TalentService.create_pip: pip=%s employee=%s manager=%s", pip.id, employee_id, manager_id)
		return pip

	def record_pip_checkin(
		self,
		pip_id: str,
		conducted_by: str,
		notes: str,
		checkin_date: date,
		*,
		progress_rating: str | None = None,
		session: Any,
	) -> Any:
		"""Record a PIP check-in progress note.

		progress_rating: ON_TRACK | AT_RISK | FAILING
		"""
		from pgappforge.plugins.erp.hcm.talent.models import PIP, PIPCheckin

		pip = session.get(PIP, pip_id)
		if pip is None:
			raise TalentValidationError(f"PIP {pip_id!r} not found")
		if pip.status not in {"ACTIVE", "EXTENDED"}:
			raise TalentStateError(f"Cannot check in on PIP with status {pip.status!r}")

		if progress_rating and progress_rating not in {"ON_TRACK", "AT_RISK", "FAILING"}:
			raise TalentValidationError(f"Invalid progress_rating {progress_rating!r}")

		checkin = PIPCheckin(
			tenant_id=pip.tenant_id,
			pip_id=pip_id,
			conducted_by=conducted_by,
			notes=notes,
			checkin_date=checkin_date,
			progress_rating=progress_rating,
		)
		try:
			session.add(checkin)
			session.flush()
		except Exception:
			log.exception("TalentService.record_pip_checkin: DB error pip=%s", pip_id)
			raise

		log.info("TalentService.record_pip_checkin: checkin=%s pip=%s date=%s", checkin.id, pip_id, checkin_date)
		return checkin

	def resolve_pip(
		self,
		pip_id: str,
		outcome: str,
		outcome_notes: str,
		*,
		session: Any,
	) -> Any:
		"""Resolve a PIP: outcome must be EXTENDED | PASSED | TERMINATED."""
		from pgappforge.plugins.erp.hcm.talent.models import PIP

		_VALID_OUTCOMES = {"EXTENDED", "PASSED", "TERMINATED"}
		if outcome not in _VALID_OUTCOMES:
			raise TalentValidationError(f"Invalid PIP outcome {outcome!r}")

		pip = session.get(PIP, pip_id)
		if pip is None:
			raise TalentValidationError(f"PIP {pip_id!r} not found")
		if pip.status not in {"ACTIVE", "EXTENDED"}:
			raise TalentStateError(f"Cannot resolve PIP with status {pip.status!r}")

		try:
			pip.status = outcome
			pip.outcome_notes = outcome_notes
			pip.updated_at = datetime.now(timezone.utc)
			session.flush()
		except Exception:
			log.exception("TalentService.resolve_pip: DB error pip=%s", pip_id)
			raise

		log.info("TalentService.resolve_pip: pip=%s outcome=%s", pip_id, outcome)
		return pip

	# ------------------------------------------------------------------
	# Succession planning
	# ------------------------------------------------------------------

	def create_succession_plan(
		self,
		tenant_id: str,
		position_id: str,
		*,
		risk_level: str = "MEDIUM",
		review_date: date | None = None,
		session: Any,
	) -> Any:
		"""Create or update a succession plan for a critical position."""
		from pgappforge.plugins.erp.hcm.talent.models import SuccessionPlan

		if risk_level not in {"HIGH", "MEDIUM", "LOW"}:
			raise TalentValidationError(f"Invalid risk_level {risk_level!r}")

		# Upsert: one plan per position per tenant
		existing = session.execute(
			sa.select(SuccessionPlan)
			.where(SuccessionPlan.tenant_id == tenant_id)
			.where(SuccessionPlan.position_id == position_id)
		).scalar_one_or_none()

		try:
			if existing is not None:
				existing.risk_level = risk_level
				if review_date is not None:
					existing.review_date = review_date
				existing.updated_at = datetime.now(timezone.utc)
				session.flush()
				log.info("TalentService.create_succession_plan: updated plan=%s position=%s", existing.id, position_id)
				return existing

			plan = SuccessionPlan(
				tenant_id=tenant_id,
				position_id=position_id,
				risk_level=risk_level,
				review_date=review_date,
				bench_strength_score=None,
			)
			session.add(plan)
			session.flush()
		except Exception:
			log.exception("TalentService.create_succession_plan: DB error position=%s", position_id)
			raise

		log.info("TalentService.create_succession_plan: plan=%s position=%s risk=%s", plan.id, position_id, risk_level)
		return plan

	def add_successor(
		self,
		plan_id: str,
		employee_id: str,
		readiness: str,
		*,
		flight_risk: bool = False,
		development_actions: list[dict[str, Any]] | None = None,
		development_notes: str | None = None,
		session: Any,
	) -> Any:
		"""Add a successor candidate to a succession plan and recompute bench strength."""
		from pgappforge.plugins.erp.hcm.talent.models import SuccessionPlan, SuccessorCandidate

		_VALID_READINESS = {"READY_NOW", "1_2_YEARS", "3_5_YEARS"}
		if readiness not in _VALID_READINESS:
			raise TalentValidationError(f"Invalid readiness {readiness!r}")

		plan = session.get(SuccessionPlan, plan_id)
		if plan is None:
			raise TalentValidationError(f"SuccessionPlan {plan_id!r} not found")

		try:
			candidate = SuccessorCandidate(
				tenant_id=plan.tenant_id,
				plan_id=plan_id,
				employee_id=employee_id,
				readiness=readiness,
				flight_risk=flight_risk,
				development_actions=development_actions or [],
				development_notes=development_notes,
			)
			session.add(candidate)
			session.flush()

			# Recompute bench strength: READY_NOW=100, 1_2_YEARS=60, 3_5_YEARS=30 weighted avg
			_WEIGHTS = {"READY_NOW": 100, "1_2_YEARS": 60, "3_5_YEARS": 30}
			all_candidates = session.execute(
				sa.select(SuccessorCandidate).where(SuccessorCandidate.plan_id == plan_id)
			).scalars().all()
			if all_candidates:
				avg_score = sum(_WEIGHTS.get(c.readiness, 0) for c in all_candidates) / len(all_candidates)
				plan.bench_strength_score = round(avg_score, 2)
				plan.updated_at = datetime.now(timezone.utc)
				session.flush()
		except TalentValidationError:
			raise
		except Exception:
			log.exception("TalentService.add_successor: DB error plan=%s employee=%s", plan_id, employee_id)
			raise

		log.info("TalentService.add_successor: plan=%s employee=%s readiness=%s", plan_id, employee_id, readiness)
		return candidate

	def get_bench_strength_report(self, tenant_id: str, *, session: Any) -> dict[str, Any]:
		"""Return bench strength across all succession plans for a tenant.

		Returns:
		  {
		    plans: [{position_id, risk_level, bench_strength_score, successor_count,
		             ready_now, one_two_years, three_five_years}],
		    overall_bench_strength: float,
		    high_risk_vacancies: int,
		  }
		"""
		from pgappforge.plugins.erp.hcm.talent.models import SuccessionPlan, SuccessorCandidate

		plans = session.execute(
			sa.select(SuccessionPlan).where(SuccessionPlan.tenant_id == tenant_id)
		).scalars().all()

		report_rows = []
		for plan in plans:
			counts = session.execute(
				sa.select(SuccessorCandidate.readiness, sa.func.count().label("cnt"))
				.where(SuccessorCandidate.plan_id == plan.id)
				.group_by(SuccessorCandidate.readiness)
			).all()
			by_readiness = {row.readiness: row.cnt for row in counts}
			total = sum(by_readiness.values())
			report_rows.append({
				"position_id": plan.position_id,
				"risk_level": plan.risk_level,
				"bench_strength_score": float(plan.bench_strength_score) if plan.bench_strength_score is not None else 0.0,
				"successor_count": total,
				"ready_now": by_readiness.get("READY_NOW", 0),
				"one_two_years": by_readiness.get("1_2_YEARS", 0),
				"three_five_years": by_readiness.get("3_5_YEARS", 0),
			})

		scores = [r["bench_strength_score"] for r in report_rows]
		overall = round(sum(scores) / len(scores), 2) if scores else 0.0
		high_risk = sum(1 for r in report_rows if r["risk_level"] == "HIGH" and r["ready_now"] == 0)

		return {
			"plans": report_rows,
			"overall_bench_strength": overall,
			"high_risk_vacancies": high_risk,
		}

	# ------------------------------------------------------------------
	# HiPo / 9-box placement
	# ------------------------------------------------------------------

	def place_nine_box(
		self,
		tenant_id: str,
		employee_id: str,
		cycle_id: str,
		performance_axis: int,
		potential_axis: int,
		placed_by: str,
		*,
		notes: str | None = None,
		development_track_id: str | None = None,
		session: Any,
	) -> Any:
		"""Place an employee on the 9-box grid for a performance cycle.

		performance_axis: 1 (Low) | 2 (Medium) | 3 (High)
		potential_axis:   1 (Low) | 2 (Medium) | 3 (High)

		box_label is computed and stored for query efficiency.
		"""
		from pgappforge.plugins.erp.hcm.talent.models import NineBoxPlacement

		for axis_name, val in (("performance_axis", performance_axis), ("potential_axis", potential_axis)):
			if val not in {1, 2, 3}:
				raise TalentValidationError(f"{axis_name} must be 1, 2, or 3; got {val}")

		# 3x3 label map (performance_axis, potential_axis) -> label
		_BOX_LABELS: dict[tuple[int, int], str] = {
			(3, 3): "STAR",
			(3, 2): "HIGH_PERFORMER",
			(3, 1): "EXPERT",
			(2, 3): "HIGH_POTENTIAL",
			(2, 2): "CORE_PLAYER",
			(2, 1): "SOLID_CONTRIBUTOR",
			(1, 3): "ENIGMA",
			(1, 2): "NEEDS_COACHING",
			(1, 1): "UNDERPERFORMER",
		}
		box_label = _BOX_LABELS[(performance_axis, potential_axis)]

		# Upsert: one placement per (cycle, employee)
		existing = session.execute(
			sa.select(NineBoxPlacement)
			.where(NineBoxPlacement.cycle_id == cycle_id)
			.where(NineBoxPlacement.employee_id == employee_id)
		).scalar_one_or_none()

		try:
			if existing is not None:
				existing.performance_axis = performance_axis
				existing.potential_axis = potential_axis
				existing.box_label = box_label
				existing.placed_by = placed_by
				existing.notes = notes
				existing.development_track_id = development_track_id
				existing.updated_at = datetime.now(timezone.utc)
				session.flush()
				log.info("TalentService.place_nine_box: updated placement=%s employee=%s label=%s", existing.id, employee_id, box_label)
				return existing

			placement = NineBoxPlacement(
				tenant_id=tenant_id,
				employee_id=employee_id,
				cycle_id=cycle_id,
				performance_axis=performance_axis,
				potential_axis=potential_axis,
				box_label=box_label,
				placed_by=placed_by,
				notes=notes,
				development_track_id=development_track_id,
			)
			session.add(placement)
			session.flush()
		except TalentValidationError:
			raise
		except Exception:
			log.exception("TalentService.place_nine_box: DB error employee=%s cycle=%s", employee_id, cycle_id)
			raise

		log.info("TalentService.place_nine_box: placement=%s employee=%s label=%s", placement.id, employee_id, box_label)
		return placement

	# ------------------------------------------------------------------
	# Career pathing / skills gap analysis
	# ------------------------------------------------------------------

	def skills_gap_analysis(
		self,
		employee_id: str,
		target_position_id: str,
		*,
		employee_skills: list[dict[str, Any]],
		session: Any,
	) -> dict[str, Any]:
		"""Compare employee skills against a target position's competency profile.

		employee_skills: [{name, proficiency}] — caller provides from employee record.

		Returns:
		  {
		    employee_id, target_position_id,
		    matched: [{competency_code, name, employee_level, required_level}],
		    gap:     [{competency_code, name, required_level, employee_level}],
		    excess:  [{competency_code, name, employee_level, required_level}],
		  }
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Competency, CompetencyProfile

		profile_rows = session.execute(
			sa.select(CompetencyProfile, Competency)
			.join(Competency, CompetencyProfile.competency_id == Competency.id)
			.where(CompetencyProfile.position_id == target_position_id)
		).all()

		# Build a simple name → level map from employee skills
		# proficiency values: BEGINNER=1, INTERMEDIATE=2, EXPERT=3 (or numeric)
		_PROF_MAP = {"BEGINNER": 1, "INTERMEDIATE": 2, "EXPERT": 3, "ADVANCED": 3}
		emp_skill_levels: dict[str, int] = {}
		for s in employee_skills:
			name_key = s.get("name", "").upper()
			prof = s.get("proficiency", s.get("level", 1))
			emp_skill_levels[name_key] = _PROF_MAP.get(str(prof).upper(), int(prof) if str(prof).isdigit() else 1)

		matched, gap, excess = [], [], []

		for profile_row, competency in profile_rows:
			req_level = profile_row.required_level
			emp_level = emp_skill_levels.get(competency.name.upper(), 0)

			entry = {
				"competency_code": competency.code,
				"name": competency.name,
				"required_level": req_level,
				"employee_level": emp_level,
			}
			if emp_level == 0:
				gap.append(entry)
			elif emp_level >= req_level:
				if emp_level > req_level:
					excess.append(entry)
				else:
					matched.append(entry)
			else:
				gap.append(entry)

		return {
			"employee_id": employee_id,
			"target_position_id": target_position_id,
			"matched": matched,
			"gap": gap,
			"excess": excess,
		}

	# ------------------------------------------------------------------
	# eNPS / Pulse surveys
	# ------------------------------------------------------------------

	def compute_enps(self, survey_id: str, *, session: Any) -> dict[str, Any]:
		"""Compute eNPS from a submitted ENPS survey.

		Assumes the eNPS question has scale 0–10 and is the first SCALE question.
		Standard NPS formula: %Promoters (9–10) − %Detractors (0–6).

		Returns:
		  {survey_id, enps_score, promoters, passives, detractors, response_count}
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Survey, SurveyQuestion, TalentSurveyResponse

		survey = session.get(Survey, survey_id)
		if survey is None:
			raise TalentValidationError(f"Survey {survey_id!r} not found")
		if survey.survey_type != "ENPS":
			raise TalentValidationError(f"Survey {survey_id!r} is type {survey.survey_type!r}, not ENPS")

		# Find the primary SCALE question (lowest sort_order)
		enps_question = session.execute(
			sa.select(SurveyQuestion)
			.where(SurveyQuestion.survey_id == survey_id)
			.where(SurveyQuestion.question_type == "SCALE")
			.order_by(SurveyQuestion.sort_order)
			.limit(1)
		).scalar_one_or_none()

		if enps_question is None:
			raise TalentValidationError(f"Survey {survey_id!r} has no SCALE question for eNPS computation")

		responses = session.execute(
			sa.select(TalentSurveyResponse).where(TalentSurveyResponse.survey_id == survey_id)
		).scalars().all()

		promoters = passives = detractors = 0
		for resp in responses:
			for item in (resp.responses or []):
				if item.get("question_id") == enps_question.id:
					try:
						score = int(item.get("answer", -1))
					except (TypeError, ValueError):
						continue
					if score >= 9:
						promoters += 1
					elif score >= 7:
						passives += 1
					else:
						detractors += 1
					break

		total = promoters + passives + detractors
		if total == 0:
			enps_score = 0.0
		else:
			enps_score = round(((promoters - detractors) / total) * 100, 1)

		return {
			"survey_id": survey_id,
			"enps_score": enps_score,
			"promoters": promoters,
			"passives": passives,
			"detractors": detractors,
			"response_count": total,
		}

	# ------------------------------------------------------------------
	# L&D: certifications
	# ------------------------------------------------------------------

	def record_certification(
		self,
		tenant_id: str,
		employee_id: str,
		certification_name: str,
		issued_date: date,
		*,
		issuing_body: str | None = None,
		expiry_date: date | None = None,
		renewal_required: bool = True,
		course_id: str | None = None,
		certificate_url: str | None = None,
		session: Any,
	) -> Any:
		"""Record a certification earned by an employee."""
		from pgappforge.plugins.erp.hcm.talent.models import Certification

		cert = Certification(
			tenant_id=tenant_id,
			employee_id=employee_id,
			certification_name=certification_name,
			issued_date=issued_date,
			issuing_body=issuing_body,
			expiry_date=expiry_date,
			renewal_required=renewal_required,
			course_id=course_id,
			certificate_url=certificate_url,
		)
		try:
			session.add(cert)
			session.flush()
		except Exception:
			log.exception("TalentService.record_certification: DB error employee=%s cert=%r", employee_id, certification_name)
			raise

		log.info("TalentService.record_certification: cert=%s employee=%s name=%r expiry=%s", cert.id, employee_id, certification_name, expiry_date)
		return cert

	def expiring_certifications(
		self,
		tenant_id: str,
		within_days: int = 30,
		*,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Return certifications expiring within `within_days` days for a tenant.

		Returns list of dicts: [{cert_id, employee_id, certification_name, expiry_date, days_until_expiry}]
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Certification

		today = _today()
		cutoff = date.fromordinal(today.toordinal() + within_days)

		certs = session.execute(
			sa.select(Certification)
			.where(Certification.tenant_id == tenant_id)
			.where(Certification.renewal_required == True)  # noqa: E712
			.where(Certification.expiry_date.isnot(None))
			.where(Certification.expiry_date <= cutoff)
			.order_by(Certification.expiry_date)
		).scalars().all()

		result = []
		for c in certs:
			days_left = (c.expiry_date - today).days
			result.append({
				"cert_id": c.id,
				"employee_id": c.employee_id,
				"certification_name": c.certification_name,
				"expiry_date": c.expiry_date,
				"days_until_expiry": days_left,
			})
		return result

	# ------------------------------------------------------------------
	# Onboarding
	# ------------------------------------------------------------------

	def create_onboarding_plan(
		self,
		tenant_id: str,
		employee_id: str,
		target_start_date: date,
		*,
		buddy_id: str | None = None,
		template_id: str | None = None,
		default_tasks: list[dict[str, Any]] | None = None,
		session: Any,
	) -> Any:
		"""Create an onboarding plan for a new hire.

		default_tasks: [{task_type, title, description, due_date, assigned_to}]
		Called automatically by accept_offer() when onboarding hook is active.
		"""
		from pgappforge.plugins.erp.hcm.talent.models import OnboardingPlan, OnboardingTask

		plan = OnboardingPlan(
			tenant_id=tenant_id,
			employee_id=employee_id,
			target_start_date=target_start_date,
			buddy_id=buddy_id,
			template_id=template_id,
			status="PENDING",
		)
		try:
			session.add(plan)
			session.flush()

			for t in (default_tasks or []):
				task = OnboardingTask(
					tenant_id=tenant_id,
					plan_id=plan.id,
					task_type=t.get("task_type", "OTHER"),
					title=t["title"],
					description=t.get("description"),
					due_date=t.get("due_date"),
					assigned_to=t.get("assigned_to"),
				)
				session.add(task)
			session.flush()
		except Exception:
			log.exception("TalentService.create_onboarding_plan: DB error employee=%s", employee_id)
			raise

		log.info("TalentService.create_onboarding_plan: plan=%s employee=%s tasks=%d", plan.id, employee_id, len(default_tasks or []))
		return plan

	def complete_onboarding_task(self, task_id: str, *, session: Any) -> Any:
		"""Mark an onboarding task as completed."""
		from pgappforge.plugins.erp.hcm.talent.models import OnboardingTask

		task = session.get(OnboardingTask, task_id)
		if task is None:
			raise TalentValidationError(f"OnboardingTask {task_id!r} not found")
		if task.completed_at is not None:
			raise TalentStateError(f"OnboardingTask {task_id!r} is already completed")

		try:
			task.completed_at = datetime.now(timezone.utc)
			task.updated_at = datetime.now(timezone.utc)
			session.flush()
		except Exception:
			log.exception("TalentService.complete_onboarding_task: DB error task=%s", task_id)
			raise

		log.info("TalentService.complete_onboarding_task: task=%s plan=%s", task_id, task.plan_id)
		return task

	# ------------------------------------------------------------------
	# Interview debrief
	# ------------------------------------------------------------------

	def record_debrief(
		self,
		tenant_id: str,
		application_id: str,
		facilitated_by: str,
		scheduled_at: datetime,
		attendee_ids: list[str],
		*,
		aggregate_scorecard: dict[str, Any] | None = None,
		hiring_decision: str | None = None,
		decision_rationale: str | None = None,
		session: Any,
	) -> Any:
		"""Record the interview debrief and consensus hiring decision.

		hiring_decision: PROCEED_OFFER | HOLD | REJECT
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Application, InterviewDebrief

		_VALID_DECISIONS = {"PROCEED_OFFER", "HOLD", "REJECT", None}
		if hiring_decision not in _VALID_DECISIONS:
			raise TalentValidationError(f"Invalid hiring_decision {hiring_decision!r}")

		app = session.get(Application, application_id)
		if app is None:
			raise ApplicationNotFoundError(f"Application {application_id!r} not found")

		# Upsert: one debrief per application
		existing = session.execute(
			sa.select(InterviewDebrief).where(InterviewDebrief.application_id == application_id)
		).scalar_one_or_none()

		now = datetime.now(timezone.utc)
		try:
			if existing is not None:
				existing.facilitated_by = facilitated_by
				existing.scheduled_at = scheduled_at
				existing.attendee_ids = attendee_ids
				existing.aggregate_scorecard = aggregate_scorecard or {}
				existing.hiring_decision = hiring_decision
				existing.decision_rationale = decision_rationale
				existing.decided_at = now if hiring_decision else existing.decided_at
				existing.updated_at = now
				session.flush()
				log.info("TalentService.record_debrief: updated debrief=%s app=%s decision=%s", existing.id, application_id, hiring_decision)
				return existing

			debrief = InterviewDebrief(
				tenant_id=tenant_id,
				application_id=application_id,
				facilitated_by=facilitated_by,
				scheduled_at=scheduled_at,
				attendee_ids=attendee_ids,
				aggregate_scorecard=aggregate_scorecard or {},
				hiring_decision=hiring_decision,
				decision_rationale=decision_rationale,
				decided_at=now if hiring_decision else None,
			)
			session.add(debrief)
			session.flush()
		except (TalentValidationError, ApplicationNotFoundError):
			raise
		except Exception:
			log.exception("TalentService.record_debrief: DB error app=%s", application_id)
			raise

		log.info("TalentService.record_debrief: debrief=%s app=%s decision=%s", debrief.id, application_id, hiring_decision)
		return debrief

	# ------------------------------------------------------------------
	# Recruitment analytics
	# ------------------------------------------------------------------

	def recruitment_metrics(
		self,
		tenant_id: str,
		from_date: date,
		to_date: date,
		*,
		session: Any,
	) -> dict[str, Any]:
		"""Compute standard recruitment KPIs for a date range.

		Returns:
		  {
		    avg_days_to_fill: float | None,
		    avg_days_to_hire: float | None,
		    offer_acceptance_rate: float | None,
		    hires_by_source: {source: count},
		    cost_per_hire_cents: int | None,
		  }
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Application, Candidate, Offer, Requisition

		# avg days to fill: FILLED requisitions — days from created_at to filled_at
		fill_rows = session.execute(
			sa.select(
				sa.func.avg(
					sa.func.extract("epoch", Requisition.filled_at - Requisition.created_at) / 86400
				).label("avg_days")
			)
			.where(Requisition.tenant_id == tenant_id)
			.where(Requisition.status == "FILLED")
			.where(Requisition.filled_at.isnot(None))
			.where(sa.cast(Requisition.filled_at, sa.Date) >= from_date)
			.where(sa.cast(Requisition.filled_at, sa.Date) <= to_date)
		).scalar()
		avg_days_to_fill = round(float(fill_rows), 1) if fill_rows is not None else None

		# avg days to hire: ACCEPTED offers — days from application.applied_at to offer.responded_at
		hire_rows = session.execute(
			sa.select(
				sa.func.avg(
					sa.func.extract("epoch", Offer.responded_at - Application.applied_at) / 86400
				).label("avg_days")
			)
			.join(Application, Offer.application_id == Application.id)
			.where(Application.tenant_id == tenant_id)
			.where(Offer.status == "ACCEPTED")
			.where(Offer.responded_at.isnot(None))
			.where(sa.cast(Offer.responded_at, sa.Date) >= from_date)
			.where(sa.cast(Offer.responded_at, sa.Date) <= to_date)
		).scalar()
		avg_days_to_hire = round(float(hire_rows), 1) if hire_rows is not None else None

		# Offer acceptance rate
		total_responded = session.execute(
			sa.select(sa.func.count())
			.select_from(Offer)
			.join(Application, Offer.application_id == Application.id)
			.where(Application.tenant_id == tenant_id)
			.where(Offer.status.in_(["ACCEPTED", "DECLINED"]))
			.where(Offer.responded_at.isnot(None))
			.where(sa.cast(Offer.responded_at, sa.Date) >= from_date)
			.where(sa.cast(Offer.responded_at, sa.Date) <= to_date)
		).scalar() or 0

		total_accepted = session.execute(
			sa.select(sa.func.count())
			.select_from(Offer)
			.join(Application, Offer.application_id == Application.id)
			.where(Application.tenant_id == tenant_id)
			.where(Offer.status == "ACCEPTED")
			.where(Offer.responded_at.isnot(None))
			.where(sa.cast(Offer.responded_at, sa.Date) >= from_date)
			.where(sa.cast(Offer.responded_at, sa.Date) <= to_date)
		).scalar() or 0

		offer_acceptance_rate = round(total_accepted / total_responded * 100, 1) if total_responded > 0 else None

		# Hires by source — join Application → Candidate for source channel
		source_rows = session.execute(
			sa.select(Candidate.source, sa.func.count().label("cnt"))
			.join(Application, Application.candidate_id == Candidate.id)
			.join(Offer, Offer.application_id == Application.id)
			.where(Application.tenant_id == tenant_id)
			.where(Offer.status == "ACCEPTED")
			.where(Offer.responded_at.isnot(None))
			.where(sa.cast(Offer.responded_at, sa.Date) >= from_date)
			.where(sa.cast(Offer.responded_at, sa.Date) <= to_date)
			.group_by(Candidate.source)
		).all()
		hires_by_source = {row.source: row.cnt for row in source_rows}

		# Cost per hire: total training + offer costs not tracked in base schema,
		# but we can sum offer base salaries as a proxy if cost data not present.
		# Use filled requisition count as divisor.
		cost_per_hire_cents: int | None = None  # Requires TrainingBudget integration — placeholder

		return {
			"avg_days_to_fill": avg_days_to_fill,
			"avg_days_to_hire": avg_days_to_hire,
			"offer_acceptance_rate": offer_acceptance_rate,
			"hires_by_source": hires_by_source,
			"cost_per_hire_cents": cost_per_hire_cents,
		}

	def pipeline_summary(self, requisition_id: str, session: Any) -> dict[str, Any]:
		"""Return stage counts and offer status for a requisition's pipeline.

		Returns:
		  {
		    requisition_id,
		    requisition_number,
		    status,
		    headcount,
		    stages: {stage: count, ...},
		    total_applications,
		    interviews_scheduled,
		    offers_sent,
		    offers_accepted,
		    avg_interview_rating: str | None,
		  }
		"""
		from pgappforge.plugins.erp.hcm.talent.models import Application, Interview, Offer, Requisition

		req = session.get(Requisition, requisition_id)
		if req is None:
			raise RequisitionNotFoundError(f"Requisition {requisition_id!r} not found")

		stage_counts_raw = session.execute(
			sa.select(Application.stage, sa.func.count().label("cnt"))
			.where(Application.requisition_id == requisition_id)
			.group_by(Application.stage)
		).all()
		stages = {row.stage: row.cnt for row in stage_counts_raw}
		total = sum(stages.values())

		interviews_scheduled = session.execute(
			sa.select(sa.func.count())
			.select_from(Interview)
			.join(Application, Interview.application_id == Application.id)
			.where(Application.requisition_id == requisition_id)
			.where(Interview.status == "SCHEDULED")
		).scalar() or 0

		avg_rating_row = session.execute(
			sa.select(sa.func.avg(Interview.overall_rating))
			.join(Application, Interview.application_id == Application.id)
			.where(Application.requisition_id == requisition_id)
			.where(Interview.status == "COMPLETED")
			.where(Interview.overall_rating.isnot(None))
		).scalar()
		avg_rating = str(round(float(avg_rating_row), 2)) if avg_rating_row else None

		offers_sent = session.execute(
			sa.select(sa.func.count())
			.select_from(Offer)
			.join(Application, Offer.application_id == Application.id)
			.where(Application.requisition_id == requisition_id)
			.where(Offer.status.in_(["SENT", "ACCEPTED", "DECLINED", "EXPIRED"]))
		).scalar() or 0

		offers_accepted = session.execute(
			sa.select(sa.func.count())
			.select_from(Offer)
			.join(Application, Offer.application_id == Application.id)
			.where(Application.requisition_id == requisition_id)
			.where(Offer.status == "ACCEPTED")
		).scalar() or 0

		return {
			"requisition_id": requisition_id,
			"requisition_number": req.requisition_number,
			"status": req.status,
			"headcount": req.headcount,
			"stages": stages,
			"total_applications": total,
			"interviews_scheduled": interviews_scheduled,
			"offers_sent": offers_sent,
			"offers_accepted": offers_accepted,
			"avg_interview_rating": avg_rating,
		}


__all__ = [
	"TalentService",
	"TalentServiceError",
	"RequisitionNotFoundError",
	"ApplicationNotFoundError",
	"OfferNotFoundError",
	"ReviewNotFoundError",
	"EnrollmentNotFoundError",
	"TalentStateError",
	"TalentValidationError",
	# new error classes
	"GoalNotFoundError",
	"PIPNotFoundError",
	"SuccessionPlanNotFoundError",
	"CycleNotFoundError",
]
