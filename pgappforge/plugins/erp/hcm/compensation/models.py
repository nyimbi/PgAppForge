from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

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
	Numeric,
	Text,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"CompensationGrade",
	"CompensationPackage",
	"AllowanceDefinition",
	"EmployeeAllowance",
	"DeductionDefinition",
	"EmployeeDeduction",
	"CompensationReviewCycle",
]


def _uuid4() -> str:
	return str(uuid.uuid4())


class CompensationGrade(AuditMixin, Model):
	__tablename__ = "comp_grade"
	__table_args__ = (
		UniqueConstraint("tenant_id", "grade_code", "effective_from", name="uq_comp_grade_tenant_code_eff"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	grade_code = Column(VARCHAR(50), nullable=False)
	name = Column(VARCHAR(200), nullable=False)
	min_salary_cents = Column(BigInteger, nullable=False)
	midpoint_cents = Column(BigInteger, nullable=False)
	max_salary_cents = Column(BigInteger, nullable=False)
	currency_code = Column(VARCHAR(3), nullable=False, default="KES")
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)
	entity_id = Column(VARCHAR(50), nullable=True)

	packages = relationship("CompensationPackage", back_populates="grade", lazy="select")


class CompensationPackage(AuditMixin, Model):
	"""Immutable compensation ledger — insert-only, never update salary fields after creation."""

	__tablename__ = "comp_package"
	__table_args__ = (
		Index("ix_comp_package_emp_eff", "employee_id", "effective_from"),
		Index("ix_comp_package_tenant_emp", "tenant_id", "employee_id"),
		Index("ix_comp_package_tenant_type", "tenant_id", "package_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	employee_id = Column(VARCHAR(50), nullable=False)
	grade_id = Column(
		UUID(as_uuid=False),
		ForeignKey("comp_grade.id", ondelete="SET NULL"),
		nullable=True,
	)
	base_salary_cents = Column(BigInteger, nullable=False)
	pay_frequency = Column(
		VARCHAR(20),
		nullable=False,
		default="MONTHLY",
		comment="MONTHLY/BIWEEKLY/WEEKLY/SEMIMONTHLY",
	)
	package_type = Column(
		VARCHAR(30),
		nullable=False,
		default="STANDARD",
		comment="STANDARD/PROBATION/PROMOTION/MERIT/MARKET_ADJUST/OFF_CYCLE",
	)
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)
	approved_by = Column(VARCHAR(50), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)
	metadata_ = Column("metadata_", JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
	currency_code = Column(VARCHAR(3), nullable=False, default="KES")

	grade = relationship("CompensationGrade", back_populates="packages", lazy="select")


class AllowanceDefinition(AuditMixin, Model):
	__tablename__ = "comp_allowance_def"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_comp_allowance_def_tenant_code"),
		{"extend_existing": True},
	)

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
	allowance_type = Column(
		VARCHAR(30),
		nullable=False,
		comment="HOUSING/TRANSPORT/MEDICAL/EDUCATION/AIRTIME/LUNCH/OTHER",
	)
	amount_cents = Column(BigInteger, nullable=False, default=0, comment="Flat amount; 0 means use percentage")
	percentage_of_basic = Column(
		Numeric(6, 4),
		nullable=False,
		default=0.0,
		comment="e.g. 0.1500 = 15%",
	)
	is_taxable = Column(Boolean, nullable=False, default=True)
	is_pensionable = Column(Boolean, nullable=False, default=False)
	currency_code = Column(VARCHAR(3), nullable=False, default="KES")
	is_active = Column(Boolean, nullable=False, default=True)
	entity_id = Column(VARCHAR(50), nullable=True)

	employee_allowances = relationship("EmployeeAllowance", back_populates="allowance_def", lazy="select")


class EmployeeAllowance(AuditMixin, Model):
	__tablename__ = "comp_employee_allowance"
	__table_args__ = (
		Index("ix_comp_emp_allowance_def", "employee_id", "allowance_def_id"),
		Index("ix_comp_emp_allowance_eff", "employee_id", "effective_from"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	employee_id = Column(VARCHAR(50), nullable=False)
	allowance_def_id = Column(
		UUID(as_uuid=False),
		ForeignKey("comp_allowance_def.id", ondelete="CASCADE"),
		nullable=False,
	)
	override_amount_cents = Column(BigInteger, nullable=True, comment="Overrides definition amount if set")
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)
	notes = Column(Text, nullable=True)

	allowance_def = relationship("AllowanceDefinition", back_populates="employee_allowances", lazy="select")


class DeductionDefinition(AuditMixin, Model):
	__tablename__ = "comp_deduction_def"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_comp_deduction_def_tenant_code"),
		{"extend_existing": True},
	)

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
	deduction_type = Column(
		VARCHAR(30),
		nullable=False,
		comment="SACCO/LOAN/WELFARE/UNION/GARNISHMENT/OTHER",
	)
	is_pre_tax = Column(Boolean, nullable=False, default=False)
	max_amount_cents = Column(BigInteger, nullable=True)
	currency_code = Column(VARCHAR(3), nullable=False, default="KES")
	is_active = Column(Boolean, nullable=False, default=True)
	entity_id = Column(VARCHAR(50), nullable=True)

	employee_deductions = relationship("EmployeeDeduction", back_populates="deduction_def", lazy="select")


class EmployeeDeduction(AuditMixin, Model):
	__tablename__ = "comp_employee_deduction"
	__table_args__ = (
		Index("ix_comp_emp_deduction_priority", "employee_id", "priority"),
		Index("ix_comp_emp_deduction_eff", "employee_id", "effective_from"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	employee_id = Column(VARCHAR(50), nullable=False)
	deduction_def_id = Column(
		UUID(as_uuid=False),
		ForeignKey("comp_deduction_def.id", ondelete="CASCADE"),
		nullable=False,
	)
	amount_cents = Column(BigInteger, nullable=False)
	balance_remaining_cents = Column(
		BigInteger,
		nullable=True,
		comment="NULL = indefinite recurring; non-null = loan balance",
	)
	priority = Column(Integer, nullable=False, default=1)
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)
	notes = Column(Text, nullable=True)

	deduction_def = relationship("DeductionDefinition", back_populates="employee_deductions", lazy="select")


class CompensationReviewCycle(AuditMixin, Model):
	__tablename__ = "comp_review_cycle"
	__table_args__ = (
		Index("ix_comp_review_cycle_tenant_status", "tenant_id", "status"),
		Index("ix_comp_review_cycle_tenant_year", "tenant_id", "review_year"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	cycle_type = Column(
		VARCHAR(30),
		nullable=False,
		comment="ANNUAL_MERIT/MID_YEAR/MARKET/PROMOTION/ADHOC",
	)
	review_year = Column(Integer, nullable=False)
	status = Column(
		VARCHAR(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT/IN_PROGRESS/APPROVED/CLOSED",
	)
	budget_pool_cents = Column(BigInteger, nullable=False, default=0)
	committed_cents = Column(BigInteger, nullable=False, default=0)
	period_start = Column(Date, nullable=False)
	period_end = Column(Date, nullable=False)
	approved_by = Column(VARCHAR(50), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	entity_id = Column(VARCHAR(50), nullable=True)
	metadata_ = Column("metadata_", JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
