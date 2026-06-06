from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
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
	"BenefitPlan",
	"BenefitEnrollment",
	"BenefitClaim",
	"BenefitDeduction",
	"OpenEnrollmentWindow",
]


def _uuid4() -> str:
	import uuid
	return str(uuid.uuid4())


class BenefitPlan(AuditMixin, Model):
	__tablename__ = "ben_plan"
	__table_args__ = (
		Index("ix_ben_plan_tenant_id", "tenant_id"),
		Index("ix_ben_plan_entity_id", "entity_id"),
		Index("ix_ben_plan_type_tenant", "plan_type", "tenant_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	entity_id = Column(VARCHAR(50), nullable=True)

	plan_code = Column(VARCHAR(50), nullable=False)
	name = Column(VARCHAR(200), nullable=False)
	plan_type = Column(
		VARCHAR(30),
		nullable=False,
		# MEDICAL / DENTAL / VISION / LIFE / DISABILITY / RETIREMENT / OTHER
	)
	carrier = Column(VARCHAR(200), nullable=True)
	is_active = Column(Boolean, default=True, nullable=False)

	# flat-rate premiums (nullable — use coverage_tiers for tiered plans)
	employee_premium_cents = Column(BigInteger, nullable=True)
	employer_premium_cents = Column(BigInteger, nullable=True)

	# tiered premiums: {SINGLE: {employee_cents, employer_cents}, EMPLOYEE_SPOUSE: {...}, FAMILY: {...}}
	coverage_tiers = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))

	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)

	country_code = Column(VARCHAR(3), nullable=False, default="KEN")
	statutory_nhif = Column(Boolean, nullable=False, default=False)

	metadata_ = Column("metadata_", JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))

	# relationships
	enrollments = relationship("BenefitEnrollment", back_populates="plan", lazy="select")


class BenefitEnrollment(AuditMixin, Model):
	__tablename__ = "ben_enrollment"
	__table_args__ = (
		UniqueConstraint("tenant_id", "employee_id", "plan_id", "effective_from",
		                 name="uq_ben_enrollment_tenant_employee_plan_date"),
		Index("ix_ben_enrollment_employee_status", "employee_id", "status"),
		Index("ix_ben_enrollment_plan_status", "plan_id", "status"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ben_plan.id", ondelete="CASCADE"),
		nullable=False,
	)
	coverage_tier = Column(VARCHAR(30), nullable=False, default="SINGLE")
	# PENDING / ACTIVE / TERMINATED / WAIVED
	status = Column(VARCHAR(20), nullable=False, default="PENDING")

	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)

	enrolled_by = Column(VARCHAR(50), nullable=True)
	enrolled_at = Column(DateTime(timezone=True), nullable=True)

	waiver_reason = Column(Text, nullable=True)

	# relationships
	plan = relationship("BenefitPlan", back_populates="enrollments", lazy="select")
	claims = relationship("BenefitClaim", back_populates="enrollment", lazy="select")
	deductions = relationship("BenefitDeduction", back_populates="enrollment", lazy="select")


class BenefitClaim(AuditMixin, Model):
	__tablename__ = "ben_claim"
	__table_args__ = (
		Index("ix_ben_claim_enrollment_status", "enrollment_id", "status"),
		Index("ix_ben_claim_employee_date", "employee_id", "claim_date"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	enrollment_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ben_enrollment.id", ondelete="CASCADE"),
		nullable=False,
	)
	employee_id = Column(VARCHAR(50), nullable=False)

	claim_ref = Column(VARCHAR(50), nullable=True)
	claim_date = Column(Date, nullable=False)
	service_date = Column(Date, nullable=True)

	claimed_amount_cents = Column(BigInteger, nullable=False)
	approved_amount_cents = Column(BigInteger, nullable=True)

	# SUBMITTED / UNDER_REVIEW / APPROVED / DENIED / PARTIALLY_APPROVED
	status = Column(VARCHAR(30), nullable=False, default="SUBMITTED")

	adjudicator_id = Column(VARCHAR(50), nullable=True)
	adjudicated_at = Column(DateTime(timezone=True), nullable=True)
	denial_reason = Column(Text, nullable=True)

	attachments = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))

	# relationships
	enrollment = relationship("BenefitEnrollment", back_populates="claims", lazy="select")


class BenefitDeduction(AuditMixin, Model):
	__tablename__ = "ben_deduction"
	__table_args__ = (
		UniqueConstraint("enrollment_id", "period", name="uq_ben_deduction_enrollment_period"),
		Index("ix_ben_deduction_employee_period", "employee_id", "period"),
		Index("ix_ben_deduction_status_period", "status", "period"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	enrollment_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ben_enrollment.id", ondelete="CASCADE"),
		nullable=False,
	)
	employee_id = Column(VARCHAR(50), nullable=False)

	period = Column(VARCHAR(20), nullable=False)  # e.g. "2025-01"

	employee_deduction_cents = Column(BigInteger, nullable=False)
	employer_contribution_cents = Column(BigInteger, nullable=False)

	# PENDING / PROCESSED / REVERSED
	status = Column(VARCHAR(20), nullable=False, default="PENDING")

	payrun_id = Column(VARCHAR(50), nullable=True)
	processed_at = Column(DateTime(timezone=True), nullable=True)

	# relationships
	enrollment = relationship("BenefitEnrollment", back_populates="deductions", lazy="select")


class OpenEnrollmentWindow(AuditMixin, Model):
	__tablename__ = "ben_open_enrollment"
	__table_args__ = (
		Index("ix_ben_oe_tenant_status", "tenant_id", "status"),
		Index("ix_ben_oe_tenant_year", "tenant_id", "plan_year"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	entity_id = Column(VARCHAR(50), nullable=True)

	# ANNUAL / NEW_HIRE / LIFE_EVENT
	window_type = Column(VARCHAR(30), nullable=False)
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	plan_year = Column(Integer, nullable=False)

	# list of plan_ids eligible for this window
	eligible_plans = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))

	# DRAFT / OPEN / CLOSED
	status = Column(VARCHAR(20), nullable=False, default="DRAFT")

	notes = Column(Text, nullable=True)
