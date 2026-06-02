"""
pgappforge/plugins/erp/hcm/talent/models.py

SQLAlchemy models for the HCM Talent Management plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - lazy='select' throughout (SA 2.x removed lazy='dynamic')
  - JSONB for semi-structured fields (skills, scorecard, goals_achievement)
  - PostgreSQL ARRAY(UUID) for interviewer_ids (multi-interviewer panel)

Table prefix: tal_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Requisition
# ---------------------------------------------------------------------------

class Requisition(AuditMixin, Model):
	"""Job requisition — approved headcount request for a position.

	salary_range_min/max_cents define the approved compensation band.
	required_skills JSONB: [{name, level, required: bool}, ...]

	Status machine:
	  DRAFT → APPROVED → POSTED → IN_PROGRESS → FILLED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_requisition"
	__table_args__ = (
		Index("ix_tal_req_tenant", "tenant_id"),
		Index("ix_tal_req_tenant_status", "tenant_id", "status"),
		Index("ix_tal_req_position", "position_id"),
		Index("ix_tal_req_hiring_manager", "hiring_manager_id"),
		UniqueConstraint("tenant_id", "requisition_number", name="uq_tal_req_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	requisition_number = Column(String(30), nullable=False, comment="Human-readable REQ-YYYY-NNNN; unique per tenant")

	# Organizational links (soft FKs for cross-plugin safety)
	position_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to position master")
	hiring_manager_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to HCM employee")
	recruiter_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to HCM employee")
	department_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to department master")

	headcount = Column(Integer, nullable=False, default=1, comment="Number of seats to fill")
	target_start_date = Column(Date, nullable=True)

	# Compensation band — integer cents
	salary_range_min_cents = Column(Integer, nullable=True)
	salary_range_max_cents = Column(Integer, nullable=True)
	currency_code = Column(String(3), nullable=False, default="USD")

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | APPROVED | POSTED | IN_PROGRESS | FILLED | CANCELLED",
	)

	job_description = Column(Text, nullable=True)
	required_skills = Column(JSONB, nullable=False, default=list, comment="[{name, level, required: bool}]")
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — HR approver")
	approved_at = Column(DateTime(timezone=True), nullable=True)
	filled_at = Column(DateTime(timezone=True), nullable=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	applications: list[Application] = relationship("Application", back_populates="requisition", lazy="select")

	def __repr__(self) -> str:
		return f"<Requisition {self.requisition_number!r} status={self.status!r} headcount={self.headcount}>"


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

class Candidate(AuditMixin, Model):
	"""Candidate master record.

	party_id links to foundation.Party when the candidate exists in the system
	(e.g. an internal transfer); NULL for external candidates.

	skills JSONB: [{name, years, proficiency: BEGINNER|INTERMEDIATE|EXPERT}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_candidate"
	__table_args__ = (
		Index("ix_tal_candidate_tenant", "tenant_id"),
		Index("ix_tal_candidate_party", "party_id"),
		Index("ix_tal_candidate_source", "source"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Link to foundation Party (soft FK)
	party_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to erp_party.id (nullable — external candidates)")

	# Source channel
	source = Column(
		String(20),
		nullable=False,
		default="DIRECT",
		comment="REFERRAL | JOB_BOARD | LINKEDIN | AGENCY | DIRECT",
	)

	# Professional snapshot (mutable — updated per application)
	current_employer = Column(String(255), nullable=True)
	current_title = Column(String(255), nullable=True)
	desired_salary_cents = Column(Integer, nullable=True, comment="Candidate's stated desired annual salary in cents")
	notice_period_days = Column(Integer, nullable=True)
	work_authorization = Column(String(100), nullable=True, comment="e.g. CITIZEN, PR, H1B, OPT, VISA_REQUIRED")
	experience_years = Column(Numeric(4, 1), nullable=True)

	# Skills & presence
	skills = Column(JSONB, nullable=False, default=list, comment="[{name, years, proficiency}]")
	linkedin_url = Column(String(500), nullable=True)
	portfolio_url = Column(String(500), nullable=True)
	resume_url = Column(String(500), nullable=True, comment="Object-store URL / path to uploaded resume")

	# Contact (denormalized for recruiter convenience)
	full_name = Column(String(255), nullable=True, comment="Full name; sourced from Party if party_id set")
	email = Column(String(255), nullable=True)
	phone = Column(String(50), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	applications: list[Application] = relationship("Application", back_populates="candidate", lazy="select")

	def __repr__(self) -> str:
		return f"<Candidate {self.full_name!r} source={self.source!r}>"


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class Application(AuditMixin, Model):
	"""Candidate application to a requisition.

	stage tracks pipeline position:
	  APPLIED → SCREENING → INTERVIEW → OFFER → ACCEPTED | REJECTED

	One candidate can apply to multiple requisitions (many-to-many via this table).
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_application"
	__table_args__ = (
		Index("ix_tal_app_requisition", "requisition_id"),
		Index("ix_tal_app_candidate", "candidate_id"),
		Index("ix_tal_app_tenant", "tenant_id"),
		Index("ix_tal_app_tenant_stage", "tenant_id", "stage"),
		UniqueConstraint("requisition_id", "candidate_id", name="uq_tal_app_req_candidate"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	requisition_id = Column(UUID(as_uuid=False), ForeignKey("tal_requisition.id"), nullable=False, index=True)
	candidate_id = Column(UUID(as_uuid=False), ForeignKey("tal_candidate.id"), nullable=False, index=True)

	applied_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	stage = Column(
		String(20),
		nullable=False,
		default="APPLIED",
		comment="APPLIED | SCREENING | INTERVIEW | OFFER | ACCEPTED | REJECTED",
	)
	rejection_reason = Column(String(200), nullable=True)
	source = Column(String(20), nullable=True, comment="Channel override for this application")
	recruiter_notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	requisition: Requisition = relationship("Requisition", back_populates="applications", lazy="select")
	candidate: Candidate = relationship("Candidate", back_populates="applications", lazy="select")
	interviews: list[Interview] = relationship("Interview", back_populates="application", cascade="all, delete-orphan", lazy="select")
	offer: Offer | None = relationship("Offer", back_populates="application", uselist=False, lazy="select")

	def __repr__(self) -> str:
		return f"<Application req={self.requisition_id!r} candidate={self.candidate_id!r} stage={self.stage!r}>"


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------

class Interview(AuditMixin, Model):
	"""Scheduled interview for an application.

	interviewer_ids: PostgreSQL UUID[] — supports panel interviews without
	a separate join table.  Access via session.execute(select(...)) with
	unnest() for filtering.

	scorecard JSONB: {dimension: score, ...} — recruiter fills after completion.
	overall_rating: 1.0–5.0 scale.
	recommendation: HIRE | NO_HIRE | MAYBE
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_interview"
	__table_args__ = (
		Index("ix_tal_interview_application", "application_id"),
		Index("ix_tal_interview_tenant", "tenant_id"),
		Index("ix_tal_interview_scheduled_at", "scheduled_at"),
		Index("ix_tal_interview_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	application_id = Column(UUID(as_uuid=False), ForeignKey("tal_application.id", ondelete="CASCADE"), nullable=False, index=True)

	interview_type = Column(
		String(20),
		nullable=False,
		comment="PHONE | VIDEO | ONSITE | TECHNICAL | PANEL",
	)
	scheduled_at = Column(DateTime(timezone=True), nullable=False)
	duration_minutes = Column(Integer, nullable=False, default=60)
	interviewer_ids = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		default=list,
		comment="Array of ab_user UUIDs; supports panel interviews",
	)
	location = Column(String(500), nullable=True, comment="Physical address or video call URL")
	status = Column(
		String(20),
		nullable=False,
		default="SCHEDULED",
		comment="SCHEDULED | COMPLETED | CANCELLED",
	)

	# Post-interview scoring
	scorecard = Column(JSONB, nullable=False, default=dict, comment="{dimension: score, notes: str}")
	overall_rating = Column(Numeric(3, 1), nullable=True, comment="1.0–5.0 aggregate rating")
	recommendation = Column(String(10), nullable=True, comment="HIRE | NO_HIRE | MAYBE")
	completed_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	application: Application = relationship("Application", back_populates="interviews", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Interview type={self.interview_type!r} "
			f"at={self.scheduled_at} status={self.status!r} "
			f"rating={self.overall_rating}>"
		)


# ---------------------------------------------------------------------------
# Offer
# ---------------------------------------------------------------------------

class Offer(AuditMixin, Model):
	"""Employment offer extended to a candidate.

	One offer per application (one-to-one via FK unique constraint).
	Multiple revisions modelled as new rows with status=EXPIRED on prior.

	equity_details JSONB: {shares, cliff_months, vest_months, strike_price_cents}

	IMMUTABLE: once status=ACCEPTED or DECLINED, do not mutate.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_offer"
	__table_args__ = (
		Index("ix_tal_offer_application", "application_id"),
		Index("ix_tal_offer_tenant", "tenant_id"),
		Index("ix_tal_offer_status", "tenant_id", "status"),
		UniqueConstraint("application_id", name="uq_tal_offer_application"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	application_id = Column(UUID(as_uuid=False), ForeignKey("tal_application.id"), nullable=False, index=True)

	# Compensation — integer cents
	base_salary_cents = Column(Integer, nullable=False, comment="Annual base salary in cents")
	currency_code = Column(String(3), nullable=False, default="USD")
	signing_bonus_cents = Column(Integer, nullable=False, default=0)
	equity_details = Column(JSONB, nullable=False, default=dict, comment="{shares, cliff_months, vest_months, strike_price_cents}")

	# Logistics
	start_date = Column(Date, nullable=False)
	expiry_date = Column(Date, nullable=False, comment="Offer expires if not accepted by this date")

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SENT | ACCEPTED | DECLINED | EXPIRED",
	)
	sent_at = Column(DateTime(timezone=True), nullable=True)
	responded_at = Column(DateTime(timezone=True), nullable=True)
	decline_reason = Column(String(255), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	application: Application = relationship("Application", back_populates="offer", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Offer app={self.application_id!r} "
			f"base={self.base_salary_cents}¢ status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# PerformanceReview
# ---------------------------------------------------------------------------

class PerformanceReview(AuditMixin, Model):
	"""Employee performance review.

	review_cycle: ANNUAL | MID_YEAR | PROBATION | 360
	goals_achievement JSONB: [{goal_id, goal_text, target, actual, score}]
	competency_scores JSONB: [{competency, weight, score}]
	overall_rating: 1.0–5.0; rating_label: EXCEEDS/MEETS/BELOW/PIP

	Status machine: DRAFT → SUBMITTED → CALIBRATED → FINAL
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_performance_review"
	__table_args__ = (
		Index("ix_tal_pr_employee", "employee_id"),
		Index("ix_tal_pr_reviewer", "reviewer_id"),
		Index("ix_tal_pr_tenant", "tenant_id"),
		Index("ix_tal_pr_tenant_status", "tenant_id", "status"),
		Index("ix_tal_pr_cycle_period", "employee_id", "review_cycle", "period_start"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee master")
	reviewer_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee (manager/reviewer)")

	review_cycle = Column(
		String(20),
		nullable=False,
		comment="ANNUAL | MID_YEAR | PROBATION | 360",
	)
	period_start = Column(Date, nullable=False)
	period_end = Column(Date, nullable=False)

	overall_rating = Column(Numeric(3, 1), nullable=True, comment="1.0–5.0 aggregate score")
	rating_label = Column(String(50), nullable=True, comment="EXCEEDS_EXPECTATIONS | MEETS_EXPECTATIONS | BELOW_EXPECTATIONS | PIP")

	goals_achievement = Column(JSONB, nullable=False, default=list, comment="[{goal_id, goal_text, target, actual, score}]")
	competency_scores = Column(JSONB, nullable=False, default=list, comment="[{competency, weight, score}]")
	development_plan = Column(Text, nullable=True, comment="Free-text development plan / next steps")

	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | CALIBRATED | FINAL",
	)
	submitted_at = Column(DateTime(timezone=True), nullable=True)
	calibrated_at = Column(DateTime(timezone=True), nullable=True)
	finalised_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<PerformanceReview employee={self.employee_id!r} "
			f"cycle={self.review_cycle!r} rating={self.overall_rating} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# TrainingCourse
# ---------------------------------------------------------------------------

class TrainingCourse(AuditMixin, Model):
	"""Training course catalogue entry.

	skills_taught JSONB: [{name, proficiency_gained}]
	course_code: unique per tenant — used as reference in Learning Management.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_training_course"
	__table_args__ = (
		Index("ix_tal_course_tenant", "tenant_id"),
		Index("ix_tal_course_delivery", "delivery"),
		UniqueConstraint("tenant_id", "course_code", name="uq_tal_course_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	course_code = Column(String(50), nullable=False, comment="Unique course reference per tenant")
	title = Column(String(255), nullable=False)
	provider = Column(String(255), nullable=True, comment="External provider name or 'Internal'")
	delivery = Column(
		String(20),
		nullable=False,
		default="ONLINE",
		comment="ONLINE | CLASSROOM | BLENDED",
	)
	duration_hours = Column(Numeric(5, 1), nullable=False, default=0)
	cost_cents = Column(Integer, nullable=False, default=0, comment="Per-seat cost in cents")
	skills_taught = Column(JSONB, nullable=False, default=list, comment="[{name, proficiency_gained}]")
	is_active = Column(Boolean, nullable=False, default=True)
	description = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	enrollments: list[TrainingEnrollment] = relationship("TrainingEnrollment", back_populates="course", lazy="select")

	def __repr__(self) -> str:
		return f"<TrainingCourse {self.course_code!r} {self.title!r} delivery={self.delivery!r}>"


# ---------------------------------------------------------------------------
# TrainingEnrollment
# ---------------------------------------------------------------------------

class TrainingEnrollment(AuditMixin, Model):
	"""Employee enrollment in a training course.

	status: ENROLLED | IN_PROGRESS | COMPLETED | WITHDRAWN | FAILED
	certificate_url: object-store URL; populated after completion.
	score: 0.00–100.00 exam/assessment score.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_training_enrollment"
	__table_args__ = (
		Index("ix_tal_enroll_employee", "employee_id"),
		Index("ix_tal_enroll_course", "course_id"),
		Index("ix_tal_enroll_tenant", "tenant_id"),
		Index("ix_tal_enroll_status", "tenant_id", "status"),
		UniqueConstraint("employee_id", "course_id", name="uq_tal_enroll_employee_course"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee master")
	course_id = Column(UUID(as_uuid=False), ForeignKey("tal_training_course.id"), nullable=False, index=True)

	enrolled_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	completed_at = Column(DateTime(timezone=True), nullable=True)
	score = Column(Numeric(5, 2), nullable=True, comment="Assessment score 0.00–100.00")
	certificate_url = Column(String(500), nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="ENROLLED",
		comment="ENROLLED | IN_PROGRESS | COMPLETED | WITHDRAWN | FAILED",
	)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	course: TrainingCourse = relationship("TrainingCourse", back_populates="enrollments", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<TrainingEnrollment employee={self.employee_id!r} "
			f"course={self.course_id!r} status={self.status!r}>"
		)


__all__ = [
	"Requisition",
	"Candidate",
	"Application",
	"Interview",
	"Offer",
	"PerformanceReview",
	"TrainingCourse",
	"TrainingEnrollment",
]
