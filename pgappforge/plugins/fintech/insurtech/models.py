"""
pgappforge/plugins/fintech/insurtech/models.py

InsurTech models — insurance products, policyholders, policies, premiums,
and claims.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - InsurancePremium: mutable (DUE → PAID/OVERDUE/WAIVED lifecycle tracking)
  - InsuranceClaim: mutable (SUBMITTED → UNDER_REVIEW → APPROVED/REJECTED lifecycle)
  - All monetary amounts: INTEGER CENTS (no floats, no decimals in DB)
  - policy_number and claim_number: application-generated, UNIQUE

Table name convention: ft_ins_*
"""
from __future__ import annotations

import uuid
import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# InsuranceProduct — product catalogue
# ---------------------------------------------------------------------------

class InsuranceProduct(AuditMixin, Model):
	"""An insurance product definition with a premium formula.

	product_line: LIFE | HEALTH | PROPERTY | MOTOR | TRAVEL | CROP | MICROINSURANCE

	premium_formula JSONB schema:
	  {
	    "base_rate_pct": <float>,   # percentage of sum_insured
	    "risk_factors": [           # applied as multipliers in order
	      {"name": "<str>", "multiplier": <float>},
	      ...
	    ]
	  }
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_ins_product"
	__table_args__ = (
		UniqueConstraint("product_code", "tenant_id", name="uq_ft_ins_product_code_tenant"),
		Index("ix_ft_ins_product_tenant", "tenant_id"),
		Index("ix_ft_ins_product_line", "product_line"),
		Index("ix_ft_ins_product_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(200), nullable=False)
	product_code = Column(
		String(20),
		nullable=False,
		comment="Unique product code per tenant",
	)
	product_line = Column(
		String(20),
		nullable=False,
		comment="LIFE | HEALTH | PROPERTY | MOTOR | TRAVEL | CROP | MICROINSURANCE",
	)
	premium_formula: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment=(
			"Premium formula: {base_rate_pct, risk_factors: [{name, multiplier}]}"
		),
	)
	min_sum_insured_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Minimum sum insured in integer cents",
	)
	max_sum_insured_cents = Column(
		Integer,
		nullable=True,
		comment="Maximum sum insured in integer cents; NULL = unlimited",
	)
	min_term_months = Column(Integer, nullable=False, default=1)
	max_term_months = Column(Integer, nullable=True, comment="NULL = unlimited")
	underwriter_name = Column(String(200), nullable=False)
	is_active = Column(Boolean, nullable=False, default=True)

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
	policies: list[InsurancePolicy] = relationship(
		"InsurancePolicy",
		back_populates="product",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<InsuranceProduct {self.id!r} "
			f"code={self.product_code!r} "
			f"line={self.product_line!r}>"
		)


# ---------------------------------------------------------------------------
# PolicyHolder — customer insurance profile
# ---------------------------------------------------------------------------

class PolicyHolder(AuditMixin, Model):
	"""Insurance policyholder profile linked to a customer.

	kyc_tier: KYC verification level (1=basic, 2=enhanced, 3=full).
	risk_rating: Internal underwriting risk score (1=low, 5=high).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_ins_policyholder"
	__table_args__ = (
		UniqueConstraint("customer_id", "tenant_id", name="uq_ft_ins_ph_customer_tenant"),
		Index("ix_ft_ins_ph_tenant", "tenant_id"),
		Index("ix_ft_ins_ph_customer", "customer_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	customer_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK to core banking customer; not enforced by FK constraint for portability",
	)
	full_name = Column(String(200), nullable=False)
	date_of_birth = Column(Date, nullable=True)
	kyc_tier = Column(
		Integer,
		nullable=False,
		default=1,
		comment="KYC verification level: 1=basic, 2=enhanced, 3=full",
	)
	risk_rating = Column(
		Integer,
		nullable=False,
		default=1,
		comment="Underwriting risk score 1 (low) – 5 (high)",
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
	policies: list[InsurancePolicy] = relationship(
		"InsurancePolicy",
		back_populates="holder",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<PolicyHolder {self.id!r} "
			f"customer={self.customer_id!r} "
			f"name={self.full_name!r}>"
		)


# ---------------------------------------------------------------------------
# InsurancePolicy — individual policy record
# ---------------------------------------------------------------------------

class InsurancePolicy(AuditMixin, Model):
	"""An individual insurance policy.

	status flow:
	  PENDING  → ACTIVE   (issue_policy / payment of first premium)
	  ACTIVE   → LAPSED   (run_lapse_check — overdue premiums > grace period)
	  LAPSED   → REINSTATED (collect_premium pays off all overdue)
	  ACTIVE   → CANCELLED (cancel_policy)
	  ACTIVE   → EXPIRED  (end_date passed)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_ins_policy"
	__table_args__ = (
		UniqueConstraint("policy_number", name="uq_ft_ins_policy_number"),
		Index("ix_ft_ins_policy_tenant", "tenant_id"),
		Index("ix_ft_ins_policy_holder", "holder_id"),
		Index("ix_ft_ins_policy_product", "product_id"),
		Index("ix_ft_ins_policy_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	policy_number = Column(
		String(30),
		nullable=False,
		unique=True,
		comment="Application-generated unique policy number",
	)
	holder_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_ins_policyholder.id"),
		nullable=False,
		index=True,
	)
	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_ins_product.id"),
		nullable=False,
		index=True,
	)
	sum_insured_cents = Column(
		Integer,
		nullable=False,
		comment="Coverage amount in integer cents",
	)
	annual_premium_cents = Column(
		Integer,
		nullable=False,
		comment="Annual premium in integer cents",
	)
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		comment=(
			"PENDING | ACTIVE | LAPSED | CANCELLED | EXPIRED | REINSTATED"
		),
	)
	cancellation_date = Column(Date, nullable=True)
	cancellation_reason = Column(Text, nullable=True)

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
	holder: PolicyHolder = relationship(
		"PolicyHolder",
		back_populates="policies",
		lazy="select",
	)
	product: InsuranceProduct = relationship(
		"InsuranceProduct",
		back_populates="policies",
		lazy="select",
	)
	premiums: list[InsurancePremium] = relationship(
		"InsurancePremium",
		back_populates="policy",
		lazy="select",
	)
	claims: list[InsuranceClaim] = relationship(
		"InsuranceClaim",
		back_populates="policy",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<InsurancePolicy {self.id!r} "
			f"number={self.policy_number!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# InsurancePremium — monthly billing record
# ---------------------------------------------------------------------------

class InsurancePremium(Model):
	"""Monthly premium record for a policy.

	Tracks the billing status for one calendar month.

	period: "YYYY-MM" string matching the billing month.
	status: DUE → PAID | OVERDUE | WAIVED
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_ins_premium"
	__table_args__ = (
		UniqueConstraint("policy_id", "period", name="uq_ft_ins_premium_policy_period"),
		Index("ix_ft_ins_premium_tenant", "tenant_id"),
		Index("ix_ft_ins_premium_policy", "policy_id"),
		Index("ix_ft_ins_premium_status", "status"),
		Index("ix_ft_ins_premium_due_date", "due_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	policy_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_ins_policy.id"),
		nullable=False,
		index=True,
	)
	period = Column(
		String(7),
		nullable=False,
		comment="Billing period in YYYY-MM format",
	)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Premium amount in integer cents",
	)
	due_date = Column(Date, nullable=False)
	paid_date = Column(Date, nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="DUE",
		comment="DUE | PAID | OVERDUE | WAIVED",
	)
	gl_journal_id = Column(
		String(50),
		nullable=True,
		comment="GL journal entry ID after posting",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	policy: InsurancePolicy = relationship(
		"InsurancePolicy",
		back_populates="premiums",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<InsurancePremium {self.id!r} "
			f"period={self.period!r} "
			f"status={self.status!r} "
			f"amount={self.amount_cents}c>"
		)


# ---------------------------------------------------------------------------
# InsuranceClaim — claim lifecycle
# ---------------------------------------------------------------------------

class InsuranceClaim(Model):
	"""An insurance claim filed against a policy.

	claim_type: DEATH | HOSPITALIZATION | PROPERTY_DAMAGE | THEFT |
	            ACCIDENT | CROP_LOSS | CRITICAL_ILLNESS

	status flow:
	  SUBMITTED → UNDER_REVIEW (assess_claim)
	  UNDER_REVIEW → APPROVED (approve_claim) | REJECTED (reject_claim)
	  APPROVED → PAID (GL payout posted)
	  PAID | REJECTED → CLOSED (admin)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_ins_claim"
	__table_args__ = (
		UniqueConstraint("claim_number", name="uq_ft_ins_claim_number"),
		Index("ix_ft_ins_claim_tenant", "tenant_id"),
		Index("ix_ft_ins_claim_policy", "policy_id"),
		Index("ix_ft_ins_claim_status", "status"),
		Index("ix_ft_ins_claim_submitted_at", "submitted_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	policy_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_ins_policy.id"),
		nullable=False,
		index=True,
	)
	claim_number = Column(
		String(30),
		nullable=False,
		unique=True,
		comment="Application-generated unique claim number",
	)
	claim_type = Column(
		String(20),
		nullable=False,
		comment=(
			"DEATH | HOSPITALIZATION | PROPERTY_DAMAGE | THEFT | "
			"ACCIDENT | CROP_LOSS | CRITICAL_ILLNESS"
		),
	)
	incident_date = Column(Date, nullable=False)
	description = Column(Text, nullable=False)
	amount_claimed_cents = Column(
		Integer,
		nullable=False,
		comment="Amount claimed in integer cents",
	)
	amount_approved_cents = Column(
		Integer,
		nullable=True,
		comment="Amount approved for payout in integer cents",
	)
	status = Column(
		String(15),
		nullable=False,
		default="SUBMITTED",
		comment="SUBMITTED | UNDER_REVIEW | APPROVED | REJECTED | PAID | CLOSED",
	)
	submitted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	decided_at = Column(DateTime(timezone=True), nullable=True)
	decided_by = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="UUID of the underwriter/adjuster who made the decision",
	)

	# Relationships
	policy: InsurancePolicy = relationship(
		"InsurancePolicy",
		back_populates="claims",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<InsuranceClaim {self.id!r} "
			f"number={self.claim_number!r} "
			f"type={self.claim_type!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"InsuranceProduct",
	"PolicyHolder",
	"InsurancePolicy",
	"InsurancePremium",
	"InsuranceClaim",
]
