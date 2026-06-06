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
	Text,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"ReferralProgram",
	"ReferralSubmission",
	"ReferralReward",
]


def _uuid4() -> str:
	import uuid
	return str(uuid.uuid4())


class ReferralProgram(AuditMixin, Model):
	__tablename__ = "ref_program"
	__table_args__ = (
		Index("ix_ref_program_tenant_status", "tenant_id", "status"),
		Index("ix_ref_program_dates", "starts_at", "ends_at"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(VARCHAR(200), nullable=False)
	# ACTIVE / PAUSED / CLOSED
	status = Column(VARCHAR(20), nullable=False, default="ACTIVE")
	reward_amount_cents = Column(BigInteger, nullable=False, default=0)
	# CASH / GIFT / LEAVE_DAYS
	reward_type = Column(VARCHAR(20), nullable=False, default="CASH")
	# e.g. {after_days: 90, must_pass_probation: true}
	reward_conditions = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
	# empty list = all positions eligible
	eligible_positions = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
	starts_at = Column(Date, nullable=False)
	ends_at = Column(Date, nullable=True)

	# relationships
	submissions = relationship("ReferralSubmission", back_populates="program", lazy="select")


class ReferralSubmission(AuditMixin, Model):
	__tablename__ = "ref_submission"
	__table_args__ = (
		Index("ix_ref_submission_tenant_status", "tenant_id", "status"),
		Index("ix_ref_submission_referrer", "referrer_id"),
		Index("ix_ref_submission_program", "program_id"),
		Index("ix_ref_submission_candidate_email", "candidate_email"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	referrer_id = Column(VARCHAR(50), nullable=False)
	program_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ref_program.id", ondelete="CASCADE"),
		nullable=False,
	)
	candidate_name = Column(VARCHAR(200), nullable=False)
	candidate_email = Column(VARCHAR(200), nullable=False)
	candidate_phone = Column(VARCHAR(50), nullable=True)
	position = Column(VARCHAR(200), nullable=True)
	# SUBMITTED / SCREENING / INTERVIEWING / OFFERED / HIRED / REJECTED / WITHDRAWN / EXPIRED
	status = Column(VARCHAR(20), nullable=False, default="SUBMITTED")
	resume_url = Column(Text, nullable=True)
	notes = Column(Text, nullable=True)
	submitted_at = Column(DateTime(timezone=True), nullable=False)
	hired_at = Column(DateTime(timezone=True), nullable=True)
	reward_eligible = Column(Boolean, nullable=False, default=False)

	# relationships
	program = relationship("ReferralProgram", back_populates="submissions", lazy="select")
	reward = relationship(
		"ReferralReward",
		back_populates="submission",
		uselist=False,
		lazy="select",
	)


class ReferralReward(AuditMixin, Model):
	__tablename__ = "ref_reward"
	__table_args__ = (
		UniqueConstraint("submission_id", name="uq_ref_reward_submission"),
		Index("ix_ref_reward_referrer_status", "referrer_id", "status"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	submission_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ref_submission.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
	)
	referrer_id = Column(VARCHAR(50), nullable=False)
	reward_amount_cents = Column(BigInteger, nullable=False)
	# CASH / GIFT / LEAVE_DAYS
	reward_type = Column(VARCHAR(20), nullable=False)
	# PENDING / APPROVED / PAID
	status = Column(VARCHAR(20), nullable=False, default="PENDING")
	approved_by = Column(VARCHAR(50), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	paid_at = Column(DateTime(timezone=True), nullable=True)
	payment_ref = Column(VARCHAR(100), nullable=True)

	# relationships
	submission = relationship("ReferralSubmission", back_populates="reward", lazy="select")
