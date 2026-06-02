"""
pgappforge/plugins/erp/industry/education/models.py

SQLAlchemy models for the Education plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid()
  - GPA: NUMERIC(4,2) — 0.00 to 4.00 (or institution scale)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - attendance_pct: NUMERIC(5,2) — 0.00 to 100.00
  - risk_score: NUMERIC(5,4) — 0.0000 to 1.0000
  - lazy='select' throughout

Table prefix: edu_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	ARRAY,
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------

class Student(AuditMixin, Model):
	"""Student master record.

	Links to foundation.Party for shared person/contact data.
	gpa is the current cumulative GPA — updated by the grade processing
	service after each term. NUMERIC(4,2) supports 0.00–9.99 to
	accommodate international grading scales.

	program_id links to the academic program/degree being pursued.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_student"
	__table_args__ = (
		Index("ix_edu_student_tenant", "tenant_id"),
		Index("ix_edu_student_party", "party_id"),
		Index("ix_edu_student_program", "program_id"),
		Index("ix_edu_student_advisor", "advisor_id"),
		Index("ix_edu_student_status", "enrollment_status"),
		UniqueConstraint("tenant_id", "student_number", name="uq_edu_student_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	party_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation Party (soft)")
	student_number = Column(String(50), nullable=False, comment="Unique student ID per tenant")

	enrollment_status = Column(
		String(20),
		nullable=False,
		default="ENROLLED",
		comment="ENROLLED|GRADUATED|WITHDRAWN|SUSPENDED|DEFERRED|TRANSFERRED",
	)
	program_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to academic program master")
	program_name = Column(String(255), nullable=True, comment="Denormalized")
	year_of_study = Column(Integer, nullable=True, comment="1st year, 2nd year, etc.")
	advisor_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ab_user (academic advisor)")

	gpa = Column(Numeric(4, 2), nullable=True, comment="Current cumulative GPA (4.00 scale or institutional)")
	total_credits_earned = Column(Integer, nullable=False, default=0)
	credits_required = Column(Integer, nullable=True, comment="Program credit requirement")

	enrollment_date = Column(Date, nullable=True)
	expected_graduation_date = Column(Date, nullable=True)
	actual_graduation_date = Column(Date, nullable=True)

	financial_aid_status = Column(String(30), nullable=True, comment="FULL|PARTIAL|NONE|SCHOLARSHIP|LOAN")
	outstanding_fees_cents = Column(Integer, nullable=False, default=0, comment="Current outstanding tuition/fees; add-only")

	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	enrollments: list[Enrollment] = relationship("Enrollment", back_populates="student", lazy="select")
	interventions: list[Intervention] = relationship("Intervention", back_populates="student", lazy="select")

	def __repr__(self) -> str:
		return f"<Student {self.student_number!r} status={self.enrollment_status!r} gpa={self.gpa}>"


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------

class Course(AuditMixin, Model):
	"""Academic course catalogue entry.

	prerequisites is a PostgreSQL TEXT[] array of course_codes that must
	be completed before enrollment.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_course"
	__table_args__ = (
		Index("ix_edu_course_tenant", "tenant_id"),
		Index("ix_edu_course_instructor", "instructor_id"),
		Index("ix_edu_course_dept", "department"),
		UniqueConstraint("tenant_id", "course_code", name="uq_edu_course_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	course_code = Column(String(20), nullable=False, comment="Unique course code per tenant e.g. CS101")
	title = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	department = Column(String(100), nullable=True, index=True)
	credits = Column(Integer, nullable=False, default=3)

	instructor_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ab_user (primary instructor)")
	instructor_name = Column(String(255), nullable=True, comment="Denormalized")

	capacity = Column(Integer, nullable=True, comment="Max enrollment; NULL = unlimited")
	current_enrollment = Column(Integer, nullable=False, default=0, comment="Live count; updated by enrollment service")

	prerequisites = Column(ARRAY(String), nullable=False, default=list, comment="TEXT[] of prerequisite course_codes")
	level = Column(String(20), nullable=True, comment="UNDERGRADUATE|POSTGRADUATE|DOCTORATE|PROFESSIONAL")
	delivery_mode = Column(String(20), nullable=True, comment="IN_PERSON|ONLINE|HYBRID")
	status = Column(String(20), nullable=False, default="ACTIVE", comment="ACTIVE|INACTIVE|ARCHIVED")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	enrollments: list[Enrollment] = relationship("Enrollment", back_populates="course", lazy="select")

	def __repr__(self) -> str:
		return f"<Course {self.course_code!r} {self.title!r} credits={self.credits}>"


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

class Enrollment(AuditMixin, Model):
	"""Student enrollment in a course for a specific term.

	grade is VARCHAR(5) to support letter grades (A+, B-, WF, INC, P/F)
	and numeric grades as strings.
	attendance_pct: NUMERIC(5,2), 0.00–100.00.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_enrollment"
	__table_args__ = (
		Index("ix_edu_enroll_student", "student_id"),
		Index("ix_edu_enroll_course", "course_id"),
		Index("ix_edu_enroll_term", "term"),
		Index("ix_edu_enroll_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "student_id", "course_id", "term", name="uq_edu_enroll_student_course_term"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	student_id = Column(UUID(as_uuid=False), ForeignKey("edu_student.id"), nullable=False, index=True)
	course_id = Column(UUID(as_uuid=False), ForeignKey("edu_course.id"), nullable=False, index=True)
	term = Column(String(20), nullable=False, comment="e.g. 2026-S1, 2025-FA, 2026-SP")

	enrolled_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
	dropped_at = Column(DateTime(timezone=True), nullable=True)

	grade = Column(String(5), nullable=True, comment="A+|A|B|C|D|F|WF|INC|P|NP etc.")
	grade_points = Column(Numeric(4, 2), nullable=True, comment="Grade point value for GPA calculation")
	grade_submitted_at = Column(DateTime(timezone=True), nullable=True)

	attendance_pct = Column(Numeric(5, 2), nullable=True, comment="0.00–100.00 attendance percentage")
	midterm_grade = Column(String(5), nullable=True)

	status = Column(String(20), nullable=False, default="ENROLLED", comment="ENROLLED|COMPLETED|DROPPED|WITHDRAWN|FAILED")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	student: Student = relationship("Student", back_populates="enrollments", lazy="select")
	course: Course = relationship("Course", back_populates="enrollments", lazy="select")

	def __repr__(self) -> str:
		return f"<Enrollment student={self.student_id!r} course={self.course_id!r} term={self.term!r} grade={self.grade!r}>"


# ---------------------------------------------------------------------------
# Intervention
# ---------------------------------------------------------------------------

class Intervention(AuditMixin, Model):
	"""Student support intervention triggered by risk indicators.

	risk_score: NUMERIC(5,4) in [0.0000, 1.0000] — computed by the
	early-alert service from academic, financial, social, and attendance
	signals.  Higher = higher dropout/failure risk.

	action_plan is a free-text field describing agreed support actions;
	structured action tracking can be added via a separate InterventionAction
	table if required.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_intervention"
	__table_args__ = (
		Index("ix_edu_intv_student", "student_id"),
		Index("ix_edu_intv_advisor", "assigned_advisor_id"),
		Index("ix_edu_intv_tenant", "tenant_id"),
		Index("ix_edu_intv_tenant_status", "tenant_id", "status"),
		Index("ix_edu_intv_trigger_type", "trigger_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	student_id = Column(UUID(as_uuid=False), ForeignKey("edu_student.id"), nullable=False, index=True)
	assigned_advisor_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ab_user")

	trigger_type = Column(
		String(20),
		nullable=False,
		comment="ACADEMIC|FINANCIAL|SOCIAL|ATTENDANCE|BEHAVIOURAL",
	)
	risk_score = Column(Numeric(5, 4), nullable=False, comment="Computed risk score [0.0000–1.0000]")
	risk_factors = Column(JSONB, nullable=False, default=list, comment="[{factor, weight, value}]")

	triggered_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
	action_plan = Column(Text, nullable=True)
	follow_up_date = Column(Date, nullable=True)
	resolved_at = Column(DateTime(timezone=True), nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN|IN_PROGRESS|RESOLVED|ESCALATED|CLOSED",
	)
	outcome = Column(Text, nullable=True, comment="Documented outcome after resolution")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	student: Student = relationship("Student", back_populates="interventions", lazy="select")

	def __repr__(self) -> str:
		return f"<Intervention student={self.student_id!r} trigger={self.trigger_type!r} risk={float(self.risk_score):.2%}>"


__all__ = [
	"Student",
	"Course",
	"Enrollment",
	"Intervention",
]
