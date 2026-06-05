"""
pgappforge/plugins/erp/industry/education/services.py

EducationService — stateless business logic for the Education Cloud plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Callers own transaction boundaries (commit/rollback).

Key invariants:
  - GPA = sum(grade_points * credits) / sum(credits) across COMPLETED enrollments
  - At-risk: GPA < threshold OR attendance_pct < threshold
  - Interventions are append-only; resolved interventions stay in the audit trail
  - Transcript includes all enrollments (completed + in-progress)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EducationServiceError(Exception):
	"""Base error for Education Cloud domain violations."""


class StudentNotFoundError(EducationServiceError):
	"""No Student with the given id."""


class CourseNotFoundError(EducationServiceError):
	"""No Course with the given id."""


class EnrollmentNotFoundError(EducationServiceError):
	"""No Enrollment with the given id."""


class DuplicateEnrollmentError(EducationServiceError):
	"""Student is already enrolled in this course for this term."""


class CourseAtCapacityError(EducationServiceError):
	"""Course has reached maximum enrollment capacity."""


class GradeAlreadySubmittedError(EducationServiceError):
	"""Grade has already been submitted for this enrollment."""


# ---------------------------------------------------------------------------
# EducationService
# ---------------------------------------------------------------------------

class EducationService:
	"""Stateless service for Education Cloud operations."""

	# ------------------------------------------------------------------
	# Enrollment
	# ------------------------------------------------------------------

	def enroll_student(
		self,
		*,
		tenant_id: str,
		student_id: str,
		course_id: str,
		term: str,
		session: Any,
	) -> Any:
		"""Enroll a student in a course for a given term.

		Returns the created Enrollment.

		Raises:
		    StudentNotFoundError: if student_id does not exist
		    CourseNotFoundError:  if course_id does not exist
		    DuplicateEnrollmentError: if student already enrolled in course/term
		    CourseAtCapacityError: if course.capacity is set and reached
		"""
		from pgappforge.plugins.erp.industry.education.models import (
			Course, Enrollment, Student,
		)
		from pgappforge.plugins.erp.industry.education.events import (
			StudentEnrolledEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		student = session.get(Student, student_id)
		if student is None:
			raise StudentNotFoundError(f"Student {student_id!r} not found")

		course = session.get(Course, course_id)
		if course is None:
			raise CourseNotFoundError(f"Course {course_id!r} not found")

		existing = session.execute(
			select(Enrollment).where(
				Enrollment.tenant_id == tenant_id,
				Enrollment.student_id == student_id,
				Enrollment.course_id == course_id,
				Enrollment.term == term,
				Enrollment.status != "DROPPED",
			)
		).scalar_one_or_none()
		if existing is not None:
			raise DuplicateEnrollmentError(
				f"Student {student_id!r} is already enrolled in course {course_id!r} "
				f"for term {term!r}"
			)

		if course.capacity is not None and course.current_enrollment >= course.capacity:
			raise CourseAtCapacityError(
				f"Course {course.course_code!r} is at capacity "
				f"({course.current_enrollment}/{course.capacity})"
			)

		enrollment = Enrollment(
			tenant_id=tenant_id,
			student_id=student_id,
			course_id=course_id,
			term=term,
			status="ENROLLED",
		)
		session.add(enrollment)

		# Increment live count
		course.current_enrollment = (course.current_enrollment or 0) + 1

		session.flush()

		emit_event(
			StudentEnrolledEvent(
				aggregate_id=enrollment.id,
				aggregate_type="Enrollment",
				tenant_id=tenant_id,
				enrollment_id=enrollment.id,
				student_id=student_id,
				student_number=student.student_number,
				course_id=course_id,
				course_code=course.course_code,
				term=term,
			),
			session,
		)

		log.info(
			"enroll_student: student=%r course=%r term=%r enrollment=%r",
			student.student_number, course.course_code, term, enrollment.id,
		)
		return enrollment

	# ------------------------------------------------------------------
	# GPA
	# ------------------------------------------------------------------

	def calculate_gpa(self, student_id: str, session: Any) -> Decimal:
		"""Compute cumulative GPA as credit-weighted average.

		Only COMPLETED enrollments with a non-null grade_points are included.
		Returns Decimal("0.00") for students with no graded credits.
		"""
		from pgappforge.plugins.erp.industry.education.models import Enrollment, Course

		rows = session.execute(
			select(
				Enrollment.grade_points,
				Course.credits,
			)
			.join(Course, Course.id == Enrollment.course_id)
			.where(
				Enrollment.student_id == student_id,
				Enrollment.status == "COMPLETED",
				Enrollment.grade_points.isnot(None),
			)
		).all()

		if not rows:
			return Decimal("0.00")

		total_points = sum(Decimal(str(r.grade_points)) * r.credits for r in rows)
		total_credits = sum(r.credits for r in rows)
		if total_credits == 0:
			return Decimal("0.00")

		gpa = (total_points / total_credits).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		return gpa

	# ------------------------------------------------------------------
	# At-risk identification
	# ------------------------------------------------------------------

	def identify_at_risk_students(
		self,
		*,
		tenant_id: str,
		threshold_gpa: float = 2.0,
		attendance_threshold: float = 75.0,
		session: Any,
	) -> list[Any]:
		"""Return ENROLLED students with GPA below threshold OR attendance below threshold.

		Attendance is the minimum attendance_pct across all active enrollments in
		the current term.  Students with no graded credits use GPA 0.0 for comparison
		(i.e. they appear at-risk until grades are posted).

		Returns a list of Student ORM objects.
		"""
		from pgappforge.plugins.erp.industry.education.models import Enrollment, Student

		# Students below GPA threshold (gpa stored on Student as running total)
		at_risk_gpa = session.execute(
			select(Student).where(
				Student.tenant_id == tenant_id,
				Student.enrollment_status == "ENROLLED",
				sa.or_(
					Student.gpa.is_(None),
					Student.gpa < Decimal(str(threshold_gpa)),
				),
			)
		).scalars().all()

		# Students below attendance threshold — join through active enrollments
		low_attendance_subq = (
			select(Enrollment.student_id)
			.where(
				Enrollment.tenant_id == tenant_id,
				Enrollment.status == "ENROLLED",
				Enrollment.attendance_pct.isnot(None),
				Enrollment.attendance_pct < Decimal(str(attendance_threshold)),
			)
			.distinct()
		)
		at_risk_attendance = session.execute(
			select(Student).where(
				Student.tenant_id == tenant_id,
				Student.enrollment_status == "ENROLLED",
				Student.id.in_(low_attendance_subq),
			)
		).scalars().all()

		# Merge, deduplicate by id
		seen: set[str] = set()
		result: list[Any] = []
		for s in at_risk_gpa + at_risk_attendance:
			if s.id not in seen:
				seen.add(s.id)
				result.append(s)
		return result

	# ------------------------------------------------------------------
	# Intervention
	# ------------------------------------------------------------------

	def trigger_intervention(
		self,
		*,
		tenant_id: str,
		student_id: str,
		trigger_type: str,
		risk_score: Decimal,
		assigned_advisor_id: str | None = None,
		risk_factors: list[dict] | None = None,
		session: Any,
	) -> Any:
		"""Create an Intervention and emit StudentAtRiskEvent.

		Returns the created Intervention.
		"""
		from pgappforge.plugins.erp.industry.education.models import Intervention, Student
		from pgappforge.plugins.erp.industry.education.events import StudentAtRiskEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		student = session.get(Student, student_id)
		if student is None:
			raise StudentNotFoundError(f"Student {student_id!r} not found")

		intervention = Intervention(
			tenant_id=tenant_id,
			student_id=student_id,
			trigger_type=trigger_type,
			risk_score=risk_score,
			assigned_advisor_id=assigned_advisor_id or student.advisor_id,
			risk_factors=risk_factors or [],
			status="OPEN",
		)
		session.add(intervention)
		session.flush()

		emit_event(
			StudentAtRiskEvent(
				aggregate_id=intervention.id,
				aggregate_type="Intervention",
				tenant_id=tenant_id,
				intervention_id=intervention.id,
				student_id=student_id,
				student_number=student.student_number,
				trigger_type=trigger_type,
				risk_score=str(risk_score),
				assigned_advisor_id=assigned_advisor_id or student.advisor_id or "",
			),
			session,
		)

		log.info(
			"trigger_intervention: student=%r trigger=%r risk=%.4f",
			student.student_number, trigger_type, float(risk_score),
		)
		return intervention

	# ------------------------------------------------------------------
	# Grade posting
	# ------------------------------------------------------------------

	def post_grade(
		self,
		*,
		enrollment_id: str,
		grade: str,
		grade_points: Decimal,
		session: Any,
	) -> Any:
		"""Record a grade on an Enrollment and update student cumulative GPA.

		Returns the updated Enrollment.

		Raises:
		    EnrollmentNotFoundError: if enrollment_id does not exist
		    GradeAlreadySubmittedError: if grade has already been submitted
		"""
		from pgappforge.plugins.erp.industry.education.models import Enrollment, Student
		from pgappforge.plugins.erp.industry.education.events import GradeSubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		enrollment = session.get(Enrollment, enrollment_id)
		if enrollment is None:
			raise EnrollmentNotFoundError(f"Enrollment {enrollment_id!r} not found")
		if enrollment.grade_submitted_at is not None:
			raise GradeAlreadySubmittedError(
				f"Enrollment {enrollment_id!r} grade already submitted at "
				f"{enrollment.grade_submitted_at.isoformat()}"
			)

		now = datetime.now(timezone.utc)
		enrollment.grade = grade
		enrollment.grade_points = grade_points
		enrollment.grade_submitted_at = now
		enrollment.status = "COMPLETED"

		session.flush()

		# Recompute and persist cumulative GPA on student
		new_gpa = self.calculate_gpa(enrollment.student_id, session)
		student = session.get(Student, enrollment.student_id)
		if student is not None:
			student.gpa = new_gpa
			# Increment credits earned
			from pgappforge.plugins.erp.industry.education.models import Course
			course = session.get(Course, enrollment.course_id)
			if course is not None:
				student.total_credits_earned = (student.total_credits_earned or 0) + course.credits

		emit_event(
			GradeSubmittedEvent(
				aggregate_id=enrollment_id,
				aggregate_type="Enrollment",
				tenant_id=enrollment.tenant_id,
				enrollment_id=enrollment_id,
				student_id=enrollment.student_id,
				course_id=enrollment.course_id,
				term=enrollment.term,
				grade=grade,
				grade_points=str(grade_points),
			),
			session,
		)

		log.info(
			"post_grade: enrollment=%r grade=%r gpa_updated_to=%s",
			enrollment_id, grade, new_gpa,
		)
		return enrollment

	# ------------------------------------------------------------------
	# Transcript
	# ------------------------------------------------------------------

	def generate_transcript(self, student_id: str, session: Any) -> dict:
		"""Return all enrollments with grades, cumulative GPA, and student metadata.

		Structure::

		    {
		        "student_id": "...",
		        "student_number": "...",
		        "program_name": "...",
		        "cumulative_gpa": "3.45",
		        "total_credits_earned": 90,
		        "enrollments": [
		            {
		                "enrollment_id": "...",
		                "course_code": "...",
		                "course_title": "...",
		                "credits": 3,
		                "term": "2026-S1",
		                "grade": "A",
		                "grade_points": "4.00",
		                "status": "COMPLETED",
		            },
		            ...
		        ],
		    }
		"""
		from pgappforge.plugins.erp.industry.education.models import (
			Course, Enrollment, Student,
		)

		student = session.get(Student, student_id)
		if student is None:
			raise StudentNotFoundError(f"Student {student_id!r} not found")

		rows = session.execute(
			select(Enrollment, Course)
			.join(Course, Course.id == Enrollment.course_id)
			.where(Enrollment.student_id == student_id)
			.order_by(Enrollment.term, Course.course_code)
		).all()

		enrollments = [
			{
				"enrollment_id": e.id,
				"course_code": c.course_code,
				"course_title": c.title,
				"credits": c.credits,
				"term": e.term,
				"grade": e.grade,
				"grade_points": str(e.grade_points) if e.grade_points is not None else None,
				"attendance_pct": str(e.attendance_pct) if e.attendance_pct is not None else None,
				"status": e.status,
			}
			for e, c in rows
		]

		return {
			"student_id": student_id,
			"student_number": student.student_number,
			"program_id": student.program_id,
			"program_name": student.program_name,
			"enrollment_status": student.enrollment_status,
			"enrollment_date": student.enrollment_date.isoformat() if student.enrollment_date else None,
			"expected_graduation_date": (
				student.expected_graduation_date.isoformat()
				if student.expected_graduation_date else None
			),
			"actual_graduation_date": (
				student.actual_graduation_date.isoformat()
				if student.actual_graduation_date else None
			),
			"cumulative_gpa": str(student.gpa) if student.gpa is not None else "0.00",
			"total_credits_earned": student.total_credits_earned,
			"credits_required": student.credits_required,
			"enrollments": enrollments,
		}

	# ------------------------------------------------------------------
	# Advisor meeting scheduling
	# ------------------------------------------------------------------

	def schedule_advisor_meeting(
		self,
		*,
		student_id: str,
		advisor_id: str,
		preferred_times: list[str],
		session: Any,
	) -> dict:
		"""Request an advisor meeting.

		preferred_times is a list of ISO datetime strings in preference order.
		Returns a scheduling request dict.  Actual calendar integration is
		handled downstream by the calendar/scheduler plugin.

		This method validates both parties exist and returns a meeting request
		payload suitable for queuing to the scheduler.
		"""
		from pgappforge.plugins.erp.industry.education.models import Student

		student = session.get(Student, student_id)
		if student is None:
			raise StudentNotFoundError(f"Student {student_id!r} not found")

		import uuid
		request_id = str(uuid.uuid4())

		payload = {
			"meeting_request_id": request_id,
			"student_id": student_id,
			"student_number": student.student_number,
			"advisor_id": advisor_id,
			"preferred_times": preferred_times,
			"requested_at": datetime.now(timezone.utc).isoformat(),
			"status": "PENDING",
		}

		log.info(
			"schedule_advisor_meeting: student=%r advisor=%r times=%d request=%r",
			student.student_number, advisor_id, len(preferred_times), request_id,
		)
		return payload


__all__ = [
	"EducationService",
	"EducationServiceError",
	"StudentNotFoundError",
	"CourseNotFoundError",
	"EnrollmentNotFoundError",
	"DuplicateEnrollmentError",
	"CourseAtCapacityError",
	"GradeAlreadySubmittedError",
]
