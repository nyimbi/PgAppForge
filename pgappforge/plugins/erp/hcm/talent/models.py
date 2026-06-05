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
from sqlalchemy.orm import backref as sa_backref
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


# ---------------------------------------------------------------------------
# Goal (OKR)
# ---------------------------------------------------------------------------

class Goal(AuditMixin, Model):
	"""First-class OKR/Goal entity.

	Supports company → department → individual cascade via self-referential
	parent_goal_id.  key_results JSONB: [{kr_text, target_value, current_value, unit}]

	Status machine: DRAFT → ACTIVE → COMPLETED | CANCELLED
	progress_pct: 0–100, updated by TalentService.update_goal_progress() which
	  also rolls up weighted averages to parent goals.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_goal"
	__table_args__ = (
		Index("ix_tal_goal_tenant", "tenant_id"),
		Index("ix_tal_goal_employee", "employee_id"),
		Index("ix_tal_goal_parent", "parent_goal_id"),
		Index("ix_tal_goal_cycle", "cycle_id"),
		Index("ix_tal_goal_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Goal owner — soft FK to HCM employee")
	parent_goal_id = Column(UUID(as_uuid=False), ForeignKey("tal_goal.id", ondelete="SET NULL"), nullable=True, index=True, comment="Self-referential for cascade alignment")
	cycle_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="Soft FK to PerformanceCycle")

	title = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	level = Column(
		String(20),
		nullable=False,
		default="INDIVIDUAL",
		comment="COMPANY | DEPARTMENT | INDIVIDUAL",
	)
	weight = Column(Numeric(4, 1), nullable=False, default=100, comment="Weight % within parent; children weights should sum to 100")
	key_results = Column(JSONB, nullable=False, default=list, comment="[{kr_text, target_value, current_value, unit}]")
	progress_pct = Column(Numeric(5, 2), nullable=False, default=0, comment="0.00–100.00; computed from key_results or manually set")
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | ACTIVE | COMPLETED | CANCELLED",
	)
	period = Column(String(20), nullable=True, comment="e.g. '2026-Q1', '2026-H1', '2026'")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	children: list[Goal] = relationship("Goal", backref=sa_backref("parent", remote_side=[id]), lazy="select")

	def __repr__(self) -> str:
		return f"<Goal {self.title!r} level={self.level!r} progress={self.progress_pct}% status={self.status!r}>"


# ---------------------------------------------------------------------------
# 360-Degree Appraisal
# ---------------------------------------------------------------------------

class PerformanceCycle(AuditMixin, Model):
	"""A governed performance review cycle (annual, 360, probation, etc.).

	Status machine: PLANNING → IN_PROGRESS → CALIBRATION → CLOSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_performance_cycle"
	__table_args__ = (
		Index("ix_tal_pcycle_tenant", "tenant_id"),
		Index("ix_tal_pcycle_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "period", "cycle_type", name="uq_tal_pcycle_period_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(255), nullable=False)
	period = Column(String(20), nullable=False, comment="e.g. '2026-Q1', '2026'")
	cycle_type = Column(String(20), nullable=False, default="ANNUAL", comment="ANNUAL | MID_YEAR | PROBATION | 360")
	status = Column(
		String(20),
		nullable=False,
		default="PLANNING",
		comment="PLANNING | IN_PROGRESS | CALIBRATION | CLOSED",
	)
	launched_at = Column(DateTime(timezone=True), nullable=True)
	closed_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	participants: list[ReviewParticipant] = relationship("ReviewParticipant", back_populates="cycle", lazy="select")

	def __repr__(self) -> str:
		return f"<PerformanceCycle {self.name!r} period={self.period!r} status={self.status!r}>"


class ReviewParticipant(AuditMixin, Model):
	"""Multi-rater participant record for 360-degree reviews.

	One row per (cycle, appraisee, appraiser) pair.
	responses JSONB: [{competency_code, score, comments}]

	Status machine: INVITED → SUBMITTED | DECLINED
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_review_participant"
	__table_args__ = (
		Index("ix_tal_rp_cycle", "cycle_id"),
		Index("ix_tal_rp_appraisee", "appraisee_id"),
		Index("ix_tal_rp_appraiser", "appraiser_id"),
		Index("ix_tal_rp_tenant", "tenant_id"),
		UniqueConstraint("cycle_id", "appraisee_id", "appraiser_id", name="uq_tal_rp_cycle_pair"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	cycle_id = Column(UUID(as_uuid=False), ForeignKey("tal_performance_cycle.id", ondelete="CASCADE"), nullable=False, index=True)
	appraisee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Employee being reviewed")
	appraiser_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Employee providing feedback")
	relationship_type = Column(
		String(20),
		nullable=False,
		comment="SELF | PEER | MANAGER | SUBORDINATE | SKIP_LEVEL",
	)
	status = Column(
		String(20),
		nullable=False,
		default="INVITED",
		comment="INVITED | SUBMITTED | DECLINED",
	)
	responses = Column(JSONB, nullable=False, default=list, comment="[{competency_code, score, comments}]")
	submitted_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	cycle: PerformanceCycle = relationship("PerformanceCycle", back_populates="participants", lazy="select")

	def __repr__(self) -> str:
		return f"<ReviewParticipant cycle={self.cycle_id!r} appraisee={self.appraisee_id!r} rel={self.relationship_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Performance Improvement Plan (PIP)
# ---------------------------------------------------------------------------

class PIP(AuditMixin, Model):
	"""Structured Performance Improvement Plan with workflow and check-ins.

	improvement_areas JSONB: [{area, target_behaviour, success_criterion}]
	Status machine: ACTIVE → EXTENDED | PASSED | TERMINATED
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_pip"
	__table_args__ = (
		Index("ix_tal_pip_employee", "employee_id"),
		Index("ix_tal_pip_tenant", "tenant_id"),
		Index("ix_tal_pip_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Employee on PIP — soft FK")
	manager_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Responsible manager — soft FK")
	triggered_by_review_id = Column(UUID(as_uuid=False), ForeignKey("tal_performance_review.id", ondelete="SET NULL"), nullable=True, index=True)

	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	improvement_areas = Column(JSONB, nullable=False, default=list, comment="[{area, target_behaviour, success_criterion}]")
	check_in_frequency = Column(String(20), nullable=False, default="WEEKLY", comment="WEEKLY | BIWEEKLY")
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | EXTENDED | PASSED | TERMINATED",
	)
	outcome_notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	checkins: list[PIPCheckin] = relationship("PIPCheckin", back_populates="pip", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return f"<PIP employee={self.employee_id!r} {self.start_date}→{self.end_date} status={self.status!r}>"


class PIPCheckin(AuditMixin, Model):
	"""Timestamped progress note for a PIP check-in."""

	__allow_unmapped__ = True
	__tablename__ = "tal_pip_checkin"
	__table_args__ = (
		Index("ix_tal_pipc_pip", "pip_id"),
		Index("ix_tal_pipc_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	pip_id = Column(UUID(as_uuid=False), ForeignKey("tal_pip.id", ondelete="CASCADE"), nullable=False, index=True)
	conducted_by = Column(UUID(as_uuid=False), nullable=False, comment="Manager or HR — soft FK")
	notes = Column(Text, nullable=False)
	progress_rating = Column(String(20), nullable=True, comment="ON_TRACK | AT_RISK | FAILING")
	checkin_date = Column(Date, nullable=False)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	pip: PIP = relationship("PIP", back_populates="checkins", lazy="select")

	def __repr__(self) -> str:
		return f"<PIPCheckin pip={self.pip_id!r} date={self.checkin_date} rating={self.progress_rating!r}>"


# ---------------------------------------------------------------------------
# Succession Planning
# ---------------------------------------------------------------------------

class SuccessionPlan(AuditMixin, Model):
	"""Succession plan for a critical role/position.

	bench_strength_score: 0–100 computed metric derived from successor readiness mix.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_succession_plan"
	__table_args__ = (
		Index("ix_tal_sp_tenant", "tenant_id"),
		Index("ix_tal_sp_position", "position_id"),
		UniqueConstraint("tenant_id", "position_id", name="uq_tal_sp_position"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	position_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Critical role — soft FK to position master")
	review_date = Column(Date, nullable=True)
	risk_level = Column(String(10), nullable=False, default="MEDIUM", comment="HIGH | MEDIUM | LOW")
	bench_strength_score = Column(Numeric(5, 2), nullable=True, comment="0–100; computed from successor readiness")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	successors: list[SuccessorCandidate] = relationship("SuccessorCandidate", back_populates="plan", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return f"<SuccessionPlan position={self.position_id!r} risk={self.risk_level!r} bench={self.bench_strength_score}>"


class SuccessorCandidate(AuditMixin, Model):
	"""A nominated successor for a succession plan.

	readiness: READY_NOW | 1_2_YEARS | 3_5_YEARS
	development_actions JSONB: [{action, owner, due_date, status}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_successor_candidate"
	__table_args__ = (
		Index("ix_tal_sc_plan", "plan_id"),
		Index("ix_tal_sc_employee", "employee_id"),
		Index("ix_tal_sc_tenant", "tenant_id"),
		UniqueConstraint("plan_id", "employee_id", name="uq_tal_sc_plan_employee"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	plan_id = Column(UUID(as_uuid=False), ForeignKey("tal_succession_plan.id", ondelete="CASCADE"), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Nominated successor — soft FK to HCM employee")
	readiness = Column(String(20), nullable=False, comment="READY_NOW | 1_2_YEARS | 3_5_YEARS")
	flight_risk = Column(Boolean, nullable=False, default=False)
	development_actions = Column(JSONB, nullable=False, default=list, comment="[{action, owner, due_date, status}]")
	development_notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	plan: SuccessionPlan = relationship("SuccessionPlan", back_populates="successors", lazy="select")

	def __repr__(self) -> str:
		return f"<SuccessorCandidate plan={self.plan_id!r} employee={self.employee_id!r} readiness={self.readiness!r}>"


# ---------------------------------------------------------------------------
# HiPo / 9-Box Grid
# ---------------------------------------------------------------------------

class NineBoxPlacement(AuditMixin, Model):
	"""9-box grid placement for talent review.

	performance_axis: 1 (Low) → 3 (High)
	potential_axis:   1 (Low) → 3 (High)
	box_label: computed from axes, e.g. 'STAR' (3,3), 'CORE_PLAYER' (2,2), etc.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_nine_box_placement"
	__table_args__ = (
		Index("ix_tal_nbp_employee", "employee_id"),
		Index("ix_tal_nbp_cycle", "cycle_id"),
		Index("ix_tal_nbp_tenant", "tenant_id"),
		UniqueConstraint("cycle_id", "employee_id", name="uq_tal_nbp_cycle_employee"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee")
	cycle_id = Column(UUID(as_uuid=False), ForeignKey("tal_performance_cycle.id", ondelete="CASCADE"), nullable=False, index=True)
	performance_axis = Column(Integer, nullable=False, comment="1=Low, 2=Medium, 3=High")
	potential_axis = Column(Integer, nullable=False, comment="1=Low, 2=Medium, 3=High")
	box_label = Column(String(50), nullable=True, comment="STAR | HIGH_POTENTIAL | CORE_PLAYER | etc.; stored for query efficiency")
	placed_by = Column(UUID(as_uuid=False), nullable=False, comment="Manager/HR who placed — soft FK")
	development_track_id = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to development track")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<NineBoxPlacement employee={self.employee_id!r} perf={self.performance_axis} potential={self.potential_axis} label={self.box_label!r}>"


# ---------------------------------------------------------------------------
# Competency Framework (governed catalogue)
# ---------------------------------------------------------------------------

class Competency(AuditMixin, Model):
	"""Master competency catalogue entry.

	behavioural_indicators JSONB: [{level (1-5), indicator_text}]
	competency_type: CORE | FUNCTIONAL | LEADERSHIP | TECHNICAL
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_competency"
	__table_args__ = (
		Index("ix_tal_comp_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "code", name="uq_tal_competency_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(50), nullable=False, comment="Short unique code, e.g. 'LEAD_01'")
	name = Column(String(255), nullable=False)
	competency_type = Column(String(20), nullable=False, comment="CORE | FUNCTIONAL | LEADERSHIP | TECHNICAL")
	description = Column(Text, nullable=True)
	behavioural_indicators = Column(JSONB, nullable=False, default=list, comment="[{level, indicator_text}]")
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<Competency {self.code!r} {self.name!r} type={self.competency_type!r}>"


class CompetencyProfile(AuditMixin, Model):
	"""Links a position to its required competencies with weights.

	required_level: 1–5 expected proficiency for this position.
	weight: importance % within role profile; should sum to 100 per position.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_competency_profile"
	__table_args__ = (
		Index("ix_tal_cp_position", "position_id"),
		Index("ix_tal_cp_tenant", "tenant_id"),
		UniqueConstraint("position_id", "competency_id", name="uq_tal_cp_position_comp"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	position_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to position master")
	competency_id = Column(UUID(as_uuid=False), ForeignKey("tal_competency.id"), nullable=False, index=True)
	required_level = Column(Integer, nullable=False, default=3, comment="1–5 proficiency required")
	weight = Column(Numeric(4, 1), nullable=False, default=10, comment="% importance in role profile")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	competency: Competency = relationship("Competency", lazy="select")

	def __repr__(self) -> str:
		return f"<CompetencyProfile position={self.position_id!r} competency={self.competency_id!r} req_level={self.required_level}>"


# ---------------------------------------------------------------------------
# Career Pathing
# ---------------------------------------------------------------------------

class CareerPath(AuditMixin, Model):
	"""Defines possible moves between positions.

	move_type: LATERAL | UPWARD | CROSS_FUNCTIONAL
	required_competencies JSONB: [{competency_code, required_level}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_career_path"
	__table_args__ = (
		Index("ix_tal_cp2_from", "from_position_id"),
		Index("ix_tal_cp2_tenant", "tenant_id"),
		UniqueConstraint("from_position_id", "to_position_id", name="uq_tal_career_path"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	from_position_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to position master")
	to_position_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to position master")
	move_type = Column(String(20), nullable=False, comment="LATERAL | UPWARD | CROSS_FUNCTIONAL")
	typical_tenure_months = Column(Integer, nullable=True)
	required_competencies = Column(JSONB, nullable=False, default=list, comment="[{competency_code, required_level}]")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<CareerPath {self.from_position_id!r}→{self.to_position_id!r} type={self.move_type!r}>"


# ---------------------------------------------------------------------------
# Employee NPS / Pulse Survey
# ---------------------------------------------------------------------------

class Survey(AuditMixin, Model):
	"""Survey definition for eNPS, pulse, exit, or onboarding surveys.

	anonymised=True: survey_response.employee_id stored as NULL.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_survey"
	__table_args__ = (
		Index("ix_tal_survey_tenant", "tenant_id"),
		Index("ix_tal_survey_type", "survey_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	title = Column(String(255), nullable=False)
	survey_type = Column(String(20), nullable=False, comment="ENPS | PULSE | EXIT | ONBOARDING")
	period = Column(String(20), nullable=True, comment="e.g. '2026-Q1'")
	anonymised = Column(Boolean, nullable=False, default=False)
	status = Column(String(20), nullable=False, default="DRAFT", comment="DRAFT | ACTIVE | CLOSED")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	questions: list[SurveyQuestion] = relationship("SurveyQuestion", back_populates="survey", cascade="all, delete-orphan", lazy="select")
	responses: list[TalentSurveyResponse] = relationship("TalentSurveyResponse", back_populates="survey", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return f"<Survey {self.title!r} type={self.survey_type!r} status={self.status!r}>"


class SurveyQuestion(AuditMixin, Model):
	"""A question within a survey.

	question_type: SCALE | CHOICE | TEXT
	scale_min/max: applicable when question_type=SCALE (e.g. 0–10 for eNPS).
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_survey_question"
	__table_args__ = (
		Index("ix_tal_sq_survey", "survey_id"),
		Index("ix_tal_sq_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	survey_id = Column(UUID(as_uuid=False), ForeignKey("tal_survey.id", ondelete="CASCADE"), nullable=False, index=True)
	question_text = Column(Text, nullable=False)
	question_type = Column(String(10), nullable=False, comment="SCALE | CHOICE | TEXT")
	scale_min = Column(Integer, nullable=True)
	scale_max = Column(Integer, nullable=True)
	choices = Column(JSONB, nullable=True, comment="[{value, label}] for CHOICE type")
	sort_order = Column(Integer, nullable=False, default=0)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	survey: Survey = relationship("Survey", back_populates="questions", lazy="select")

	def __repr__(self) -> str:
		return f"<SurveyQuestion survey={self.survey_id!r} type={self.question_type!r}>"


class TalentSurveyResponse(AuditMixin, Model):
	"""A submitted survey response.

	employee_id is NULL when survey.anonymised=True.
	responses JSONB: [{question_id, answer}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_survey_response"
	__table_args__ = (
		Index("ix_tal_sr_survey", "survey_id"),
		Index("ix_tal_sr_employee", "employee_id"),
		Index("ix_tal_sr_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	survey_id = Column(UUID(as_uuid=False), ForeignKey("tal_survey.id", ondelete="CASCADE"), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="NULL when survey is anonymised")
	responses = Column(JSONB, nullable=False, default=list, comment="[{question_id, answer}]")
	submitted_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	survey: Survey = relationship("Survey", back_populates="responses", lazy="select")

	def __repr__(self) -> str:
		return f"<TalentSurveyResponse survey={self.survey_id!r} employee={self.employee_id!r}>"


# ---------------------------------------------------------------------------
# L&D: Certification tracking
# ---------------------------------------------------------------------------

class Certification(AuditMixin, Model):
	"""Employee certification record with expiry tracking.

	Distinct from TrainingEnrollment — an employee can earn a certification
	through multiple routes (external exam, CPD portfolio, etc.).
	renewal_required: True triggers expiring_certifications() alerts.
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_certification"
	__table_args__ = (
		Index("ix_tal_cert_employee", "employee_id"),
		Index("ix_tal_cert_tenant", "tenant_id"),
		Index("ix_tal_cert_expiry", "expiry_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="Soft FK to HCM employee")
	certification_name = Column(String(255), nullable=False)
	issuing_body = Column(String(255), nullable=True)
	issued_date = Column(Date, nullable=False)
	expiry_date = Column(Date, nullable=True, comment="NULL means does not expire")
	renewal_required = Column(Boolean, nullable=False, default=True)
	course_id = Column(UUID(as_uuid=False), ForeignKey("tal_training_course.id", ondelete="SET NULL"), nullable=True, index=True, comment="Optional link to the training that produced this cert")
	certificate_url = Column(String(500), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	course: TrainingCourse | None = relationship("TrainingCourse", lazy="select")

	def __repr__(self) -> str:
		return f"<Certification {self.certification_name!r} employee={self.employee_id!r} expiry={self.expiry_date}>"


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

class TalentOnboardingPlan(AuditMixin, Model):
	"""Onboarding plan created automatically on hire acceptance.

	status: PENDING | IN_PROGRESS | COMPLETED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_onboarding_plan"
	__table_args__ = (
		Index("ix_tal_op_employee", "employee_id"),
		Index("ix_tal_op_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="New hire — soft FK to HCM employee")
	template_id = Column(UUID(as_uuid=False), nullable=True, comment="Soft FK to onboarding template")
	buddy_id = Column(UUID(as_uuid=False), nullable=True, comment="Assigned buddy — soft FK to HCM employee")
	target_start_date = Column(Date, nullable=False)
	status = Column(String(20), nullable=False, default="PENDING", comment="PENDING | IN_PROGRESS | COMPLETED | CANCELLED")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	tasks: list[OnboardingTask] = relationship("OnboardingTask", back_populates="plan", cascade="all, delete-orphan", lazy="select")

	def __repr__(self) -> str:
		return f"<TalentOnboardingPlan employee={self.employee_id!r} start={self.target_start_date} status={self.status!r}>"


class OnboardingTask(AuditMixin, Model):
	"""Individual task within an onboarding plan.

	task_type: DOCUMENT | IT_ACCESS | TRAINING | MEETING | EQUIPMENT | OTHER
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_onboarding_task"
	__table_args__ = (
		Index("ix_tal_ot_plan", "plan_id"),
		Index("ix_tal_ot_tenant", "tenant_id"),
		Index("ix_tal_ot_assigned", "assigned_to"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	plan_id = Column(UUID(as_uuid=False), ForeignKey("tal_onboarding_plan.id", ondelete="CASCADE"), nullable=False, index=True)
	task_type = Column(String(20), nullable=False, comment="DOCUMENT | IT_ACCESS | TRAINING | MEETING | EQUIPMENT | OTHER")
	title = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	due_date = Column(Date, nullable=True)
	assigned_to = Column(UUID(as_uuid=False), nullable=True, index=True, comment="Responsible person — soft FK")
	completed_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	plan: TalentOnboardingPlan = relationship("TalentOnboardingPlan", back_populates="tasks", lazy="select")

	def __repr__(self) -> str:
		return f"<OnboardingTask {self.title!r} type={self.task_type!r} due={self.due_date}>"


# ---------------------------------------------------------------------------
# Interview Debrief
# ---------------------------------------------------------------------------

class InterviewDebrief(AuditMixin, Model):
	"""Post-interview debrief: structured calibration before offer creation.

	attendee_ids: PostgreSQL UUID[] — all interviewers present.
	aggregate_scorecard JSONB: {dimension: avg_score, ...}
	hiring_decision: PROCEED_OFFER | HOLD | REJECT
	"""

	__allow_unmapped__ = True
	__tablename__ = "tal_interview_debrief"
	__table_args__ = (
		Index("ix_tal_idbf_application", "application_id"),
		Index("ix_tal_idbf_tenant", "tenant_id"),
		UniqueConstraint("application_id", name="uq_tal_idbf_application"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	application_id = Column(UUID(as_uuid=False), ForeignKey("tal_application.id", ondelete="CASCADE"), nullable=False, index=True)
	facilitated_by = Column(UUID(as_uuid=False), nullable=False, comment="Hiring manager or recruiter — soft FK")
	scheduled_at = Column(DateTime(timezone=True), nullable=False)
	attendee_ids = Column(ARRAY(UUID(as_uuid=False)), nullable=False, default=list, comment="UUID[] of attendees")
	aggregate_scorecard = Column(JSONB, nullable=False, default=dict, comment="{dimension: avg_score}")
	hiring_decision = Column(String(20), nullable=True, comment="PROCEED_OFFER | HOLD | REJECT")
	decision_rationale = Column(Text, nullable=True)
	decided_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	application: Application = relationship("Application", lazy="select")

	def __repr__(self) -> str:
		return f"<InterviewDebrief app={self.application_id!r} decision={self.hiring_decision!r}>"


__all__ = [
	"Requisition",
	"Candidate",
	"Application",
	"Interview",
	"Offer",
	"PerformanceReview",
	"TrainingCourse",
	"TrainingEnrollment",
	# OKR / Goals
	"Goal",
	# 360 Appraisal
	"PerformanceCycle",
	"ReviewParticipant",
	# PIP
	"PIP",
	"PIPCheckin",
	# Succession
	"SuccessionPlan",
	"SuccessorCandidate",
	# HiPo
	"NineBoxPlacement",
	# Competency framework
	"Competency",
	"CompetencyProfile",
	# Career pathing
	"CareerPath",
	# Surveys / eNPS
	"Survey",
	"SurveyQuestion",
	"TalentSurveyResponse",
	# L&D certifications
	"Certification",
	# Onboarding
	"TalentOnboardingPlan",
	"OnboardingTask",
	# Interview debrief
	"InterviewDebrief",
]
