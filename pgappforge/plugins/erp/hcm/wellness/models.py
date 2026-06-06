from __future__ import annotations

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
	"WellnessProgram",
	"WellnessEnrollment",
	"WellnessCheckIn",
	"EapReferral",
]


def _uuid4() -> str:
	import uuid
	return str(uuid.uuid4())


class WellnessProgram(AuditMixin, Model):
	__tablename__ = "wel_program"
	__table_args__ = (
		Index("ix_wel_program_tenant_status", "tenant_id", "status"),
		Index("ix_wel_program_type", "program_type"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(VARCHAR(200), nullable=False)
	description = Column(Text, nullable=True)
	# PHYSICAL / MENTAL / FINANCIAL / SOCIAL / EAP / GENERAL
	program_type = Column(VARCHAR(20), nullable=False, default="GENERAL")
	# ACTIVE / PAUSED / ARCHIVED
	status = Column(VARCHAR(20), nullable=False, default="ACTIVE")
	provider = Column(VARCHAR(200), nullable=True)
	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)
	is_voluntary = Column(Boolean, nullable=False, default=True)
	# list of role identifiers; empty = all roles eligible
	target_roles = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
	max_participants = Column(Integer, nullable=True)

	# relationships
	enrollments = relationship("WellnessEnrollment", back_populates="program", lazy="select")


class WellnessEnrollment(AuditMixin, Model):
	__tablename__ = "wel_enrollment"
	__table_args__ = (
		UniqueConstraint("employee_id", "program_id", name="uq_wel_enrollment_employee_program"),
		Index("ix_wel_enrollment_employee_status", "employee_id", "status"),
		Index("ix_wel_enrollment_program_status", "program_id", "status"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	program_id = Column(
		UUID(as_uuid=False),
		ForeignKey("wel_program.id", ondelete="CASCADE"),
		nullable=False,
	)
	enrolled_at = Column(DateTime(timezone=True), nullable=False)
	# ACTIVE / COMPLETED / WITHDRAWN
	status = Column(VARCHAR(20), nullable=False, default="ACTIVE")
	completed_at = Column(DateTime(timezone=True), nullable=True)

	# relationships
	program = relationship("WellnessProgram", back_populates="enrollments", lazy="select")


class WellnessCheckIn(AuditMixin, Model):
	__tablename__ = "wel_checkin"
	__table_args__ = (
		UniqueConstraint("employee_id", "check_in_date", name="uq_wel_checkin_employee_date"),
		Index("ix_wel_checkin_tenant_date", "tenant_id", "check_in_date"),
		Index("ix_wel_checkin_employee_date", "employee_id", "check_in_date"),
		Index("ix_wel_checkin_score", "wellbeing_score"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	check_in_date = Column(Date, nullable=False)
	# 1-10 scale
	wellbeing_score = Column(Integer, nullable=False)
	# 1-10 scale, nullable
	energy_level = Column(Integer, nullable=True)
	# 1-10 scale, nullable
	stress_level = Column(Integer, nullable=True)
	# flags: BURNOUT_RISK / ISOLATION / FINANCIAL_STRESS / HIGH_STRESS etc.
	flags = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
	anonymous = Column(Boolean, nullable=False, default=False)
	notes = Column(Text, nullable=True)


class EapReferral(AuditMixin, Model):
	__tablename__ = "wel_eap_referral"
	__table_args__ = (
		Index("ix_wel_eap_referral_tenant_status", "tenant_id", "status"),
		Index("ix_wel_eap_referral_employee", "employee_id"),
		Index("ix_wel_eap_referral_category", "category"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	# MENTAL_HEALTH / SUBSTANCE / FINANCIAL / FAMILY / LEGAL / GRIEF / OTHER
	category = Column(VARCHAR(50), nullable=False)
	# OPEN / IN_PROGRESS / CLOSED
	status = Column(VARCHAR(20), nullable=False, default="OPEN")
	opened_at = Column(DateTime(timezone=True), nullable=False)
	closed_at = Column(DateTime(timezone=True), nullable=True)
	provider = Column(VARCHAR(200), nullable=True)
	sessions_count = Column(Integer, nullable=False, default=0)
	# confidential notes
	notes = Column(Text, nullable=True)
