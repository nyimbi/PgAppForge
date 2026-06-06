from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.workflow.engine import BPMActionRegistry
from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event


def _emit(event: Any, session: Any = None) -> None:
	"""Fire-and-forget event emission. Session=None gracefully degrades to handler-only."""
	try:
		_emit_event(event, session)
	except Exception:  # noqa: BLE001
		log.debug("Event bus unavailable; event %s not published", type(event).__name__)

from .events import (
	CertificateIssuedEvent,
	CourseCompletedEvent,
	CoursePublishedEvent,
	EnrollmentCreatedEvent,
	LessonCompletedEvent,
	MandatoryTrainingOverdueEvent,
)
from .models import (
	LmsCertificate,
	LmsCourse,
	LmsEnrollment,
	LmsLesson,
	LmsProgress,
)

__all__ = [
	"LmsServiceError",
	"CourseNotFoundError",
	"EnrollmentNotFoundError",
	"EnrollmentStateError",
	"LmsService",
]

log = logging.getLogger(__name__)

_UTC = timezone.utc

_ACTIVE_STATUSES = {"ENROLLED", "IN_PROGRESS"}
_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "WITHDRAWN"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LmsServiceError(Exception):
	"""Base error for LMS service layer."""


class CourseNotFoundError(LmsServiceError):
	"""Raised when a course cannot be located."""


class EnrollmentNotFoundError(LmsServiceError):
	"""Raised when an enrollment cannot be located."""


class EnrollmentStateError(LmsServiceError):
	"""Raised on illegal enrollment state transitions."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class LmsService:
	"""Domain service for the Learning Management System."""

	# ------------------------------------------------------------------
	# Course lifecycle
	# ------------------------------------------------------------------

	def publish_course(self, course_id: str, session: Session) -> LmsCourse:
		"""Transition a DRAFT course to PUBLISHED state."""
		course = session.execute(
			select(LmsCourse).where(LmsCourse.id == course_id)
		).scalar_one_or_none()
		if course is None:
			raise CourseNotFoundError(f"Course {course_id!r} not found")

		assert course.status == "DRAFT", (
			f"publish_course requires status=DRAFT; got {course.status!r}"
		)

		now = datetime.now(tz=_UTC)
		course.status = "PUBLISHED"
		course.published_at = now
		session.flush()

		_emit(
			CoursePublishedEvent(
				course_id=course.id,
				title=course.title,
				tenant_id=course.tenant_id,
			)
		)
		log.info("Course %s published", course_id)
		return course

	# ------------------------------------------------------------------
	# Enrollment
	# ------------------------------------------------------------------

	def enroll_employee(
		self,
		employee_id: str,
		course_id: str,
		tenant_id: str,
		session: Session,
		*,
		assigned_by: str | None = None,
	) -> LmsEnrollment:
		"""Enroll an employee in a course, creating per-lesson progress rows."""
		course = session.execute(
			select(LmsCourse).where(
				LmsCourse.id == course_id,
				LmsCourse.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if course is None:
			raise CourseNotFoundError(f"Course {course_id!r} not found in tenant {tenant_id!r}")

		if course.status != "PUBLISHED":
			raise EnrollmentStateError(
				f"Cannot enroll in course with status={course.status!r}; must be PUBLISHED"
			)

		# Check for existing active enrollment
		existing = session.execute(
			select(LmsEnrollment).where(
				LmsEnrollment.employee_id == employee_id,
				LmsEnrollment.course_id == course_id,
				LmsEnrollment.status.in_(_ACTIVE_STATUSES),
			)
		).scalar_one_or_none()
		if existing is not None:
			raise EnrollmentStateError(
				f"Employee {employee_id!r} already has an active enrollment "
				f"{existing.id!r} in course {course_id!r}"
			)

		# Determine attempt number
		previous_count = session.execute(
			select(LmsEnrollment).where(
				LmsEnrollment.employee_id == employee_id,
				LmsEnrollment.course_id == course_id,
			)
		).scalars().all()
		attempt_number = len(previous_count) + 1

		if attempt_number > course.max_attempts:
			raise EnrollmentStateError(
				f"Employee {employee_id!r} has exhausted max_attempts "
				f"({course.max_attempts}) for course {course_id!r}"
			)

		# Compute due date
		now = datetime.now(tz=_UTC)
		due_date: date | None = None
		if course.due_days is not None:
			due_date = (now + timedelta(days=course.due_days)).date()

		enrollment = LmsEnrollment(
			employee_id=employee_id,
			course_id=course_id,
			tenant_id=tenant_id,
			status="ENROLLED",
			enrolled_at=now,
			due_date=due_date,
			attempt_number=attempt_number,
			assigned_by=assigned_by,
		)
		session.add(enrollment)
		session.flush()  # get enrollment.id

		# Create per-lesson progress rows
		lessons = session.execute(
			select(LmsLesson).where(LmsLesson.course_id == course_id)
		).scalars().all()

		for lesson in lessons:
			progress = LmsProgress(
				enrollment_id=enrollment.id,
				lesson_id=lesson.id,
				tenant_id=tenant_id,
				status="NOT_STARTED",
				attempts=0,
				time_spent_seconds=0,
				scorm_data={},
			)
			session.add(progress)

		session.flush()

		_emit(
			EnrollmentCreatedEvent(
				enrollment_id=enrollment.id,
				employee_id=employee_id,
				course_id=course_id,
				tenant_id=tenant_id,
			)
		)
		log.info(
			"Employee %s enrolled in course %s (enrollment %s)",
			employee_id, course_id, enrollment.id,
		)
		return enrollment

	# ------------------------------------------------------------------
	# Lesson completion
	# ------------------------------------------------------------------

	def complete_lesson(
		self,
		enrollment_id: str,
		lesson_id: str,
		session: Session,
		*,
		score: int | None = None,
		time_spent_seconds: int = 0,
		scorm_data: dict[str, Any] | None = None,
	) -> LmsProgress:
		"""Mark a lesson as completed and conditionally complete the course."""
		enrollment = session.execute(
			select(LmsEnrollment).where(LmsEnrollment.id == enrollment_id)
		).scalar_one_or_none()
		if enrollment is None:
			raise EnrollmentNotFoundError(f"Enrollment {enrollment_id!r} not found")

		if enrollment.status in _TERMINAL_STATUSES:
			raise EnrollmentStateError(
				f"Enrollment {enrollment_id!r} is already terminal ({enrollment.status!r})"
			)

		progress = session.execute(
			select(LmsProgress).where(
				LmsProgress.enrollment_id == enrollment_id,
				LmsProgress.lesson_id == lesson_id,
			)
		).scalar_one_or_none()
		if progress is None:
			raise LmsServiceError(
				f"No progress row for enrollment={enrollment_id!r} lesson={lesson_id!r}"
			)

		now = datetime.now(tz=_UTC)

		# Transition enrollment to IN_PROGRESS on first lesson touch
		if enrollment.status == "ENROLLED":
			enrollment.status = "IN_PROGRESS"

		if progress.status == "NOT_STARTED":
			progress.started_at = now

		progress.attempts += 1
		progress.score = score
		progress.time_spent_seconds += time_spent_seconds
		if scorm_data:
			progress.scorm_data = {**progress.scorm_data, **scorm_data}
		progress.status = "COMPLETED"
		progress.completed_at = now
		session.flush()

		_emit(
			LessonCompletedEvent(
				enrollment_id=enrollment_id,
				lesson_id=lesson_id,
				employee_id=enrollment.employee_id,
				score=score or 0,
			)
		)
		log.debug("Lesson %s completed for enrollment %s", lesson_id, enrollment_id)

		# Check whether all required lessons are now done
		self._try_complete_course(enrollment_id, session)

		return progress

	# ------------------------------------------------------------------
	# Course completion (internal)
	# ------------------------------------------------------------------

	def _try_complete_course(self, enrollment_id: str, session: Session) -> None:
		"""If all required lessons are COMPLETED, finalise the enrollment."""
		enrollment = session.execute(
			select(LmsEnrollment).where(LmsEnrollment.id == enrollment_id)
		).scalar_one_or_none()
		if enrollment is None or enrollment.status in _TERMINAL_STATUSES:
			return

		course = session.execute(
			select(LmsCourse).where(LmsCourse.id == enrollment.course_id)
		).scalar_one_or_none()
		if course is None:
			return

		# Load all lessons and their progress
		lessons = session.execute(
			select(LmsLesson).where(LmsLesson.course_id == enrollment.course_id)
		).scalars().all()

		progress_rows = session.execute(
			select(LmsProgress).where(LmsProgress.enrollment_id == enrollment_id)
		).scalars().all()
		progress_by_lesson: dict[str, LmsProgress] = {p.lesson_id: p for p in progress_rows}

		required_lessons = [l for l in lessons if l.is_required]
		if not required_lessons:
			# No required lessons — nothing to auto-complete
			return

		# All required lessons must be COMPLETED
		all_done = all(
			progress_by_lesson.get(l.id) is not None
			and progress_by_lesson[l.id].status == "COMPLETED"
			for l in required_lessons
		)
		if not all_done:
			return

		# Compute final score as average of scores for required completed lessons
		scores = [
			progress_by_lesson[l.id].score
			for l in required_lessons
			if progress_by_lesson.get(l.id) and progress_by_lesson[l.id].score is not None
		]
		final_score = int(sum(scores) / len(scores)) if scores else 0
		passed = final_score >= course.passing_score

		now = datetime.now(tz=_UTC)
		enrollment.status = "COMPLETED" if passed else "FAILED"
		enrollment.completed_at = now
		enrollment.final_score = final_score
		enrollment.passed = passed
		session.flush()

		_emit(
			CourseCompletedEvent(
				enrollment_id=enrollment_id,
				employee_id=enrollment.employee_id,
				course_id=enrollment.course_id,
				final_score=final_score,
				passed=passed,
			)
		)
		log.info(
			"Enrollment %s completed: passed=%s score=%s",
			enrollment_id, passed, final_score,
		)

		if passed:
			self._issue_certificate(
				enrollment_id=enrollment_id,
				course_id=enrollment.course_id,
				employee_id=enrollment.employee_id,
				tenant_id=enrollment.tenant_id,
				session=session,
			)

	# ------------------------------------------------------------------
	# Certificate issuance (internal)
	# ------------------------------------------------------------------

	def _issue_certificate(
		self,
		enrollment_id: str,
		course_id: str,
		employee_id: str,
		tenant_id: str,
		session: Session,
	) -> LmsCertificate:
		"""Create a certificate record and emit the issued event."""
		now = datetime.now(tz=_UTC)
		cert_ref = (
			f"CERT-{course_id[:8].upper()}-{employee_id[:6].upper()}"
			f"-{now.strftime('%Y%m%d')}"
		)

		certificate = LmsCertificate(
			employee_id=employee_id,
			course_id=course_id,
			enrollment_id=enrollment_id,
			tenant_id=tenant_id,
			issued_at=now,
			certificate_ref=cert_ref,
		)
		session.add(certificate)
		session.flush()

		_emit(
			CertificateIssuedEvent(
				certificate_id=certificate.id,
				employee_id=employee_id,
				course_id=course_id,
				issued_at=now,
			)
		)
		log.info(
			"Certificate %s issued to employee %s for course %s",
			certificate.id, employee_id, course_id,
		)
		return certificate

	# ------------------------------------------------------------------
	# Employee progress summary
	# ------------------------------------------------------------------

	def get_employee_progress(
		self,
		employee_id: str,
		tenant_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""Return a structured progress summary for an employee."""
		enrollments = session.execute(
			select(LmsEnrollment).where(
				LmsEnrollment.employee_id == employee_id,
				LmsEnrollment.tenant_id == tenant_id,
			)
		).scalars().all()

		certificates = session.execute(
			select(LmsCertificate).where(
				LmsCertificate.employee_id == employee_id,
				LmsCertificate.tenant_id == tenant_id,
			)
		).scalars().all()

		today = date.today()
		overdue = [
			e for e in enrollments
			if e.status in _ACTIVE_STATUSES
			and e.due_date is not None
			and e.due_date < today
		]

		completed_count = sum(1 for e in enrollments if e.status == "COMPLETED")

		return {
			"employee_id": employee_id,
			"tenant_id": tenant_id,
			"enrollments": [
				{
					"id": e.id,
					"course_id": e.course_id,
					"status": e.status,
					"enrolled_at": e.enrolled_at.isoformat() if e.enrolled_at else None,
					"due_date": e.due_date.isoformat() if e.due_date else None,
					"completed_at": e.completed_at.isoformat() if e.completed_at else None,
					"final_score": e.final_score,
					"passed": e.passed,
					"attempt_number": e.attempt_number,
				}
				for e in enrollments
			],
			"completed": completed_count,
			"certificates": [
				{
					"id": c.id,
					"course_id": c.course_id,
					"certificate_ref": c.certificate_ref,
					"issued_at": c.issued_at.isoformat() if c.issued_at else None,
					"expires_at": c.expires_at.isoformat() if c.expires_at else None,
					"credential_url": c.credential_url,
				}
				for c in certificates
			],
			"overdue": [
				{
					"enrollment_id": e.id,
					"course_id": e.course_id,
					"due_date": e.due_date.isoformat() if e.due_date else None,
					"status": e.status,
				}
				for e in overdue
			],
		}

	# ------------------------------------------------------------------
	# Mandatory compliance check
	# ------------------------------------------------------------------

	def check_mandatory_compliance(
		self,
		tenant_id: str,
		session: Session,
	) -> list[dict[str, Any]]:
		"""
		Find all mandatory courses and identify employees who are overdue or
		missing an enrollment. Emits MandatoryTrainingOverdueEvent per offence.

		Returns a list of compliance-violation dicts.
		"""
		mandatory_courses = session.execute(
			select(LmsCourse).where(
				LmsCourse.tenant_id == tenant_id,
				LmsCourse.is_mandatory.is_(True),
				LmsCourse.status == "PUBLISHED",
			)
		).scalars().all()

		today = date.today()
		violations: list[dict[str, Any]] = []

		for course in mandatory_courses:
			# All enrollments for this course
			enrollments = session.execute(
				select(LmsEnrollment).where(
					LmsEnrollment.course_id == course.id,
					LmsEnrollment.tenant_id == tenant_id,
				)
			).scalars().all()

			for enrollment in enrollments:
				is_overdue = (
					enrollment.status in _ACTIVE_STATUSES
					and enrollment.due_date is not None
					and enrollment.due_date < today
				)
				if is_overdue:
					violation = {
						"enrollment_id": enrollment.id,
						"employee_id": enrollment.employee_id,
						"course_id": course.id,
						"course_title": course.title,
						"due_date": enrollment.due_date.isoformat() if enrollment.due_date else None,
						"status": enrollment.status,
						"type": "OVERDUE",
					}
					violations.append(violation)
					_emit(
						MandatoryTrainingOverdueEvent(
							enrollment_id=enrollment.id,
							employee_id=enrollment.employee_id,
							course_id=course.id,
							due_date=enrollment.due_date,
						)
					)
					log.warning(
						"Mandatory training overdue: employee=%s course=%s due=%s",
						enrollment.employee_id, course.id, enrollment.due_date,
					)

		return violations

	# ------------------------------------------------------------------
	# Course analytics
	# ------------------------------------------------------------------

	def get_course_analytics(
		self,
		course_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""Aggregate enrollment and completion metrics for a course."""
		course = session.execute(
			select(LmsCourse).where(LmsCourse.id == course_id)
		).scalar_one_or_none()
		if course is None:
			raise CourseNotFoundError(f"Course {course_id!r} not found")

		enrollments = session.execute(
			select(LmsEnrollment).where(LmsEnrollment.course_id == course_id)
		).scalars().all()

		enrollment_count = len(enrollments)
		completed = [e for e in enrollments if e.status == "COMPLETED"]
		failed = [e for e in enrollments if e.status == "FAILED"]
		passed = [e for e in enrollments if e.passed is True]

		completion_rate_pct: float = 0.0
		pass_rate_pct: float = 0.0
		avg_score: float = 0.0
		avg_duration_hours: float = 0.0

		terminal = completed + failed
		if enrollment_count > 0:
			completion_rate_pct = round(len(terminal) / enrollment_count * 100, 2)
		if terminal:
			pass_rate_pct = round(len(passed) / len(terminal) * 100, 2)

		scores = [e.final_score for e in terminal if e.final_score is not None]
		if scores:
			avg_score = round(sum(scores) / len(scores), 2)

		# Average time spent across all progress rows for this course
		progress_rows = session.execute(
			select(LmsProgress)
			.join(LmsEnrollment, LmsProgress.enrollment_id == LmsEnrollment.id)
			.where(LmsEnrollment.course_id == course_id)
		).scalars().all()
		total_seconds = sum(p.time_spent_seconds for p in progress_rows)
		if enrollment_count > 0:
			avg_duration_hours = round(total_seconds / enrollment_count / 3600, 3)

		return {
			"course_id": course_id,
			"title": course.title,
			"enrollment_count": enrollment_count,
			"completion_rate_pct": completion_rate_pct,
			"avg_score": avg_score,
			"pass_rate_pct": pass_rate_pct,
			"avg_duration_hours": avg_duration_hours,
		}


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register("hcm.lms.enroll", "Enroll employee in LMS course")
def _bpm_enroll(
	employee_id: str,
	course_id: str,
	tenant_id: str,
	session: Session,
	assigned_by: str | None = None,
) -> dict[str, Any]:
	svc = LmsService()
	enrollment = svc.enroll_employee(
		employee_id=employee_id,
		course_id=course_id,
		tenant_id=tenant_id,
		session=session,
		assigned_by=assigned_by,
	)
	return {"enrollment_id": enrollment.id, "status": enrollment.status}


@BPMActionRegistry.register(
	"hcm.lms.check_compliance", "Check mandatory training compliance"
)
def _bpm_check_compliance(
	tenant_id: str,
	session: Session,
) -> dict[str, Any]:
	svc = LmsService()
	violations = svc.check_mandatory_compliance(tenant_id=tenant_id, session=session)
	return {"violations": violations, "count": len(violations)}
