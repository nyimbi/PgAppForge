from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Text,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"LmsCourse",
	"LmsLesson",
	"LmsEnrollment",
	"LmsProgress",
	"LmsCertificate",
]


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now_utc() -> datetime:
	return datetime.now(tz=__import__("datetime").timezone.utc)


class LmsCourse(AuditMixin, Model):
	__tablename__ = "lms_course"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	code = Column(VARCHAR(50), nullable=True)
	title = Column(VARCHAR(300), nullable=False)
	description = Column(Text, nullable=True)
	course_type = Column(VARCHAR(30), nullable=False, default="INTERNAL")
	# INTERNAL / EXTERNAL / SCORM / BLENDED / WEBINAR
	status = Column(VARCHAR(20), nullable=False, default="DRAFT")
	# DRAFT / PUBLISHED / ARCHIVED
	duration_minutes = Column(Integer, nullable=False, default=0)
	passing_score = Column(Integer, nullable=False, default=70)
	max_attempts = Column(Integer, nullable=False, default=3)
	is_mandatory = Column(Boolean, nullable=False, default=False)
	mandatory_roles = Column(JSONB, nullable=False, default=list)
	due_days = Column(Integer, nullable=True)
	content_url = Column(Text, nullable=True)
	scorm_manifest = Column(JSONB, nullable=False, default=dict)
	thumbnail_url = Column(Text, nullable=True)
	tags = Column(JSONB, nullable=False, default=list)
	entity_id = Column(VARCHAR(50), nullable=True)
	created_by = Column(VARCHAR(50), nullable=True)
	published_at = Column(DateTime(timezone=True), nullable=True)

	lessons = relationship(
		"LmsLesson",
		back_populates="course",
		cascade="all, delete-orphan",
		lazy="select",
	)
	enrollments = relationship(
		"LmsEnrollment",
		back_populates="course",
		cascade="all, delete-orphan",
		lazy="select",
	)
	certificates = relationship(
		"LmsCertificate",
		back_populates="course",
		cascade="all, delete-orphan",
		lazy="select",
	)

	__table_args__ = (
		Index("ix_lms_course_tenant_status", "tenant_id", "status"),
		Index("ix_lms_course_tenant_mandatory", "tenant_id", "is_mandatory"),
	)


class LmsLesson(AuditMixin, Model):
	__tablename__ = "lms_lesson"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	course_id = Column(
		UUID(as_uuid=False),
		ForeignKey("lms_course.id", ondelete="CASCADE"),
		nullable=False,
	)
	title = Column(VARCHAR(300), nullable=False)
	lesson_type = Column(VARCHAR(30), nullable=False, default="VIDEO")
	# VIDEO / READING / QUIZ / SCORM / ASSIGNMENT
	order_num = Column(Integer, nullable=False, default=0)
	content_url = Column(Text, nullable=True)
	duration_minutes = Column(Integer, nullable=False, default=0)
	is_required = Column(Boolean, nullable=False, default=True)
	pass_score = Column(Integer, nullable=False, default=70)

	course = relationship("LmsCourse", back_populates="lessons", lazy="select")
	progress_rows = relationship(
		"LmsProgress",
		back_populates="lesson",
		cascade="all, delete-orphan",
		lazy="select",
	)

	__table_args__ = (
		Index("ix_lms_lesson_course_order", "course_id", "order_num"),
	)


class LmsEnrollment(AuditMixin, Model):
	__tablename__ = "lms_enrollment"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	course_id = Column(
		UUID(as_uuid=False),
		ForeignKey("lms_course.id", ondelete="CASCADE"),
		nullable=False,
	)
	status = Column(VARCHAR(20), nullable=False, default="ENROLLED")
	# ENROLLED / IN_PROGRESS / COMPLETED / FAILED / WITHDRAWN
	enrolled_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=_now_utc,
	)
	due_date = Column(Date, nullable=True)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	final_score = Column(Integer, nullable=True)
	passed = Column(Boolean, nullable=True)
	attempt_number = Column(Integer, nullable=False, default=1)
	assigned_by = Column(VARCHAR(50), nullable=True)

	course = relationship("LmsCourse", back_populates="enrollments", lazy="select")
	progress_rows = relationship(
		"LmsProgress",
		back_populates="enrollment",
		cascade="all, delete-orphan",
		lazy="select",
	)
	certificate = relationship(
		"LmsCertificate",
		back_populates="enrollment",
		uselist=False,
		lazy="select",
	)

	__table_args__ = (
		UniqueConstraint(
			"employee_id", "course_id", "attempt_number",
			name="uq_lms_enrollment_employee_course_attempt",
		),
		Index("ix_lms_enrollment_employee_status", "employee_id", "status"),
		Index("ix_lms_enrollment_course_status", "course_id", "status"),
	)


class LmsProgress(AuditMixin, Model):
	__tablename__ = "lms_progress"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	enrollment_id = Column(
		UUID(as_uuid=False),
		ForeignKey("lms_enrollment.id", ondelete="CASCADE"),
		nullable=False,
	)
	lesson_id = Column(
		UUID(as_uuid=False),
		ForeignKey("lms_lesson.id", ondelete="CASCADE"),
		nullable=False,
	)
	status = Column(VARCHAR(20), nullable=False, default="NOT_STARTED")
	# NOT_STARTED / IN_PROGRESS / COMPLETED
	score = Column(Integer, nullable=True)
	attempts = Column(Integer, nullable=False, default=0)
	started_at = Column(DateTime(timezone=True), nullable=True)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	time_spent_seconds = Column(Integer, nullable=False, default=0)
	scorm_data = Column(JSONB, nullable=False, default=dict)

	enrollment = relationship(
		"LmsEnrollment", back_populates="progress_rows", lazy="select"
	)
	lesson = relationship(
		"LmsLesson", back_populates="progress_rows", lazy="select"
	)

	__table_args__ = (
		UniqueConstraint(
			"enrollment_id", "lesson_id",
			name="uq_lms_progress_enrollment_lesson",
		),
	)


class LmsCertificate(AuditMixin, Model):
	__tablename__ = "lms_certificate"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	course_id = Column(
		UUID(as_uuid=False),
		ForeignKey("lms_course.id", ondelete="CASCADE"),
		nullable=False,
	)
	enrollment_id = Column(
		UUID(as_uuid=False),
		ForeignKey("lms_enrollment.id", ondelete="CASCADE"),
		nullable=False,
	)
	issued_at = Column(DateTime(timezone=True), nullable=False)
	expires_at = Column(Date, nullable=True)
	certificate_ref = Column(VARCHAR(100), nullable=False)
	credential_url = Column(Text, nullable=True)

	course = relationship("LmsCourse", back_populates="certificates", lazy="select")
	enrollment = relationship(
		"LmsEnrollment", back_populates="certificate", lazy="select"
	)

	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "certificate_ref",
			name="uq_lms_certificate_tenant_ref",
		),
		Index("ix_lms_certificate_employee_course", "employee_id", "course_id"),
		Index("ix_lms_certificate_tenant_issued", "tenant_id", "issued_at"),
	)
