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
]
