"""
pgappforge/plugins/erp/hcm/recruiting/models.py

SQLAlchemy models for the HCM Recruiting / ATS plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary values: BigInteger cents (no floats)
  - ALL models: tenant_id NOT NULL + AuditMixin
  - PostgreSQL only: JSONB, UUID types used directly
  - lazy='select' throughout (SA 2.x)

Table prefix: rec_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# JobRequisition
# ---------------------------------------------------------------------------

class JobRequisition(AuditMixin, Model):
	"""An approved headcount request to hire for a specific role.

	Status machine:
	  DRAFT → OPEN → ON_HOLD → FILLED
	  OPEN  → CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "rec_requisition"
	__table_args__ = (
		Index("ix_rec_req_tenant_status", "tenant_id", "status"),
		Index("ix_rec_req_entity_status", "entity_id", "status"),
		Index("ix_rec_req_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	title = Column(String(200), nullable=False)
	department_id = Column(String(50), nullable=True)
	entity_id = Column(String(50), nullable=True, index=True)
	grade_level = Column(String(50), nullable=True)
	headcount = Column(Integer, nullable=False, default=1)
	salary_min_cents = Column(BigInteger, nullable=True)
	salary_max_cents = Column(BigInteger, nullable=True)
	employment_type = Column(
		String(20),
		nullable=False,
		default="FULL_TIME",
		comment="FULL_TIME | PART_TIME | CONTRACT | INTERNSHIP",
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | OPEN | ON_HOLD | FILLED | CANCELLED",
	)
	hiring_manager_id = Column(String(50), nullable=True)
	job_description = Column(Text, nullable=True)
	requirements = Column(Text, nullable=True)
	posted_at = Column(DateTime(timezone=True), nullable=True)
	closed_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	applications: list[JobApplication] = relationship(
		"JobApplication", back_populates="requisition", cascade="all, delete-orphan", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<JobRequisition {self.title!r} status={self.status!r} headcount={self.headcount}>"


# ---------------------------------------------------------------------------
# JobApplication
# ---------------------------------------------------------------------------

class JobApplication(AuditMixin, Model):
	"""A candidate's application against a job requisition.

	Status machine (simplified pipeline):
	  APPLIED → SCREENING → PHONE_SCREEN → INTERVIEW → ASSESSMENT
	         → OFFER → HIRED
	         → REJECTED (from any stage)
	         → WITHDRAWN (candidate withdraws)
	"""

	__allow_unmapped__ = True
	__tablename__ = "rec_application"
	__table_args__ = (
		Index("ix_rec_app_req_status", "requisition_id", "status"),
		Index("ix_rec_app_tenant_status_applied", "tenant_id", "status", "applied_at"),
		Index("ix_rec_app_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	requisition_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rec_requisition.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	candidate_name = Column(String(200), nullable=False)
	candidate_email = Column(String(320), nullable=False)
	candidate_phone = Column(String(30), nullable=True)
	source = Column(
		String(30),
		nullable=False,
		default="DIRECT",
		comment="REFERRAL | JOB_BOARD | LINKEDIN | AGENCY | DIRECT | INTERNAL",
	)
	resume_url = Column(Text, nullable=True)
	cover_letter = Column(Text, nullable=True)
	status = Column(
		String(30),
		nullable=False,
		default="APPLIED",
		comment="APPLIED | SCREENING | PHONE_SCREEN | INTERVIEW | ASSESSMENT | OFFER | HIRED | REJECTED | WITHDRAWN",
	)
	referrer_employee_id = Column(String(50), nullable=True)
	rejection_reason = Column(Text, nullable=True)
	applied_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	requisition: JobRequisition = relationship(
		"JobRequisition", back_populates="applications", lazy="select"
	)
	interviews: list[InterviewSchedule] = relationship(
		"InterviewSchedule", back_populates="application", cascade="all, delete-orphan", lazy="select"
	)
	offer: OfferLetter | None = relationship(
		"OfferLetter", back_populates="application", uselist=False, lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<JobApplication {self.candidate_name!r} "
			f"req={self.requisition_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# InterviewSchedule
# ---------------------------------------------------------------------------

class InterviewSchedule(AuditMixin, Model):
	"""A scheduled interview event for a job application.

	One application may have multiple interview rounds (PHONE_SCREEN,
	technical, panel, etc.).
	"""

	__allow_unmapped__ = True
	__tablename__ = "rec_interview"
	__table_args__ = (
		Index("ix_rec_interview_app", "application_id"),
		Index("ix_rec_interview_interviewer_time", "interviewer_id", "scheduled_at"),
		Index("ix_rec_interview_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	application_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rec_application.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	interviewer_id = Column(String(50), nullable=False)
	scheduled_at = Column(DateTime(timezone=True), nullable=False)
	duration_minutes = Column(Integer, nullable=False, default=60)
	format = Column(
		String(20),
		nullable=False,
		default="VIDEO",
		comment="VIDEO | IN_PERSON | PHONE | PANEL",
	)
	location = Column(Text, nullable=True)
	feedback = Column(Text, nullable=True)
	rating = Column(Integer, nullable=True, comment="1-5")
	recommendation = Column(
		String(20),
		nullable=True,
		comment="STRONG_YES | YES | MAYBE | NO | STRONG_NO",
	)
	completed_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	application: JobApplication = relationship(
		"JobApplication", back_populates="interviews", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<InterviewSchedule app={self.application_id!r} "
			f"interviewer={self.interviewer_id!r} at={self.scheduled_at!r}>"
		)


# ---------------------------------------------------------------------------
# OfferLetter
# ---------------------------------------------------------------------------

class OfferLetter(AuditMixin, Model):
	"""An offer letter tied 1:1 to a job application.

	Status machine:
	  DRAFT → PENDING_APPROVAL → SENT → ACCEPTED
	                           → SENT → DECLINED
	                                  → EXPIRED
	"""

	__allow_unmapped__ = True
	__tablename__ = "rec_offer"
	__table_args__ = (
		Index("ix_rec_offer_app_status", "application_id", "status"),
		Index("ix_rec_offer_tenant", "tenant_id"),
		UniqueConstraint("application_id", name="uq_rec_offer_application"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	application_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rec_application.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
	)
	offered_salary_cents = Column(BigInteger, nullable=False)
	bonus_cents = Column(BigInteger, nullable=False, default=0)
	start_date = Column(Date, nullable=True)
	expiry_date = Column(Date, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | PENDING_APPROVAL | SENT | ACCEPTED | DECLINED | EXPIRED",
	)
	currency_code = Column(String(3), nullable=False, default="KES")
	offer_letter_url = Column(Text, nullable=True)
	accepted_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	application: JobApplication = relationship(
		"JobApplication", back_populates="offer", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<OfferLetter app={self.application_id!r} "
			f"salary={self.offered_salary_cents} status={self.status!r}>"
		)


__all__ = [
	"JobRequisition",
	"JobApplication",
	"InterviewSchedule",
	"OfferLetter",
]
