from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Text,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"SkillDomain",
	"SkillCategory",
	"Skill",
	"EmployeeSkill",
	"JobRequiredSkill",
]


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now_utc() -> datetime:
	return datetime.now(tz=__import__("datetime").timezone.utc)


class SkillDomain(AuditMixin, Model):
	__tablename__ = "sk_domain"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	code = Column(VARCHAR(50), nullable=False)
	name = Column(VARCHAR(200), nullable=False)
	description = Column(Text, nullable=True)

	categories = relationship(
		"SkillCategory",
		back_populates="domain",
		cascade="all, delete-orphan",
		lazy="select",
	)

	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_sk_domain_tenant_code"),
		Index("ix_sk_domain_tenant_code", "tenant_id", "code"),
	)


class SkillCategory(AuditMixin, Model):
	__tablename__ = "sk_category"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	domain_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sk_domain.id", ondelete="CASCADE"),
		nullable=False,
	)
	code = Column(VARCHAR(50), nullable=False)
	name = Column(VARCHAR(200), nullable=False)

	domain = relationship("SkillDomain", back_populates="categories", lazy="select")
	skills = relationship(
		"Skill",
		back_populates="category",
		cascade="all, delete-orphan",
		lazy="select",
	)

	__table_args__ = (
		Index("ix_sk_category_domain_id", "domain_id"),
		Index("ix_sk_category_tenant_code", "tenant_id", "code"),
	)


class Skill(AuditMixin, Model):
	__tablename__ = "sk_skill"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	category_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sk_category.id", ondelete="CASCADE"),
		nullable=False,
	)
	code = Column(VARCHAR(50), nullable=False)
	name = Column(VARCHAR(200), nullable=False)
	description = Column(Text, nullable=True)
	is_technical = Column(Boolean, nullable=False, default=True)

	category = relationship("SkillCategory", back_populates="skills", lazy="select")
	employee_skills = relationship(
		"EmployeeSkill",
		back_populates="skill",
		cascade="all, delete-orphan",
		lazy="select",
	)
	job_requirements = relationship(
		"JobRequiredSkill",
		back_populates="skill",
		cascade="all, delete-orphan",
		lazy="select",
	)

	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_sk_skill_tenant_code"),
		Index("ix_sk_skill_tenant_code", "tenant_id", "code"),
		Index("ix_sk_skill_category_id", "category_id"),
	)


class EmployeeSkill(AuditMixin, Model):
	"""
	Records a skill held by an employee at a given proficiency level.

	proficiency_level: 1=aware, 2=beginner, 3=proficient, 4=advanced, 5=expert
	"""
	__tablename__ = "sk_employee_skill"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	skill_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sk_skill.id", ondelete="CASCADE"),
		nullable=False,
	)
	# 1=aware, 2=beginner, 3=proficient, 4=advanced, 5=expert
	proficiency_level = Column(Integer, nullable=False)
	verified_at = Column(DateTime(timezone=True), nullable=True)
	endorsed_by = Column(VARCHAR(50), nullable=True)
	evidence_url = Column(Text, nullable=True)

	skill = relationship("Skill", back_populates="employee_skills", lazy="select")

	__table_args__ = (
		UniqueConstraint("employee_id", "skill_id", name="uq_sk_employee_skill"),
		Index("ix_sk_employee_skill_employee_skill", "employee_id", "skill_id"),
		Index("ix_sk_employee_skill_skill_proficiency", "skill_id", "proficiency_level"),
	)


class JobRequiredSkill(AuditMixin, Model):
	"""Maps a position code to a required skill and minimum proficiency level."""
	__tablename__ = "sk_job_required"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	position_code = Column(VARCHAR(100), nullable=False)
	skill_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sk_skill.id", ondelete="CASCADE"),
		nullable=False,
	)
	# 1=aware, 2=beginner, 3=proficient, 4=advanced, 5=expert
	required_level = Column(Integer, nullable=False)
	is_mandatory = Column(Boolean, nullable=False, default=True)

	skill = relationship("Skill", back_populates="job_requirements", lazy="select")

	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "position_code", "skill_id",
			name="uq_sk_job_required_tenant_position_skill",
		),
		Index("ix_sk_job_required_tenant_position", "tenant_id", "position_code"),
	)
