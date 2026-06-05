"""
pgappforge/plugins/erp/industry/insurance/models.py

SQLAlchemy models for the Insurance plugin (ACORD-aligned).

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY
  - JSONB for coverage_terms, exclusions, beneficiaries, incident_location, documents

Table name convention: ins_<entity>
"""
from __future__ import annotations

import uuid
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
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

PRODUCT_TYPE = ("LIFE", "PROPERTY", "CASUALTY", "HEALTH", "LIABILITY")
PAYMENT_FREQUENCY = ("MONTHLY", "QUARTERLY", "ANNUAL")
POLICY_STATUS = ("DRAFT", "ACTIVE", "LAPSED", "CANCELLED", "EXPIRED")
PREMIUM_STATUS = ("DUE", "PAID", "OVERDUE", "WAIVED")
CLAIM_STATUS = ("REPORTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "PAID", "CLOSED")
CESSION_TYPE = ("PROPORTIONAL", "NON_PROPORTIONAL")


# ---------------------------------------------------------------------------
# InsuranceProduct
# ---------------------------------------------------------------------------

class InsuranceProduct(AuditMixin, Model):
	"""Insurance product definition (life, property, casualty, health, liability).

	coverage_terms JSONB: {inclusions, exclusions, conditions, sub_limits}
	base_premium_cents: starting premium before underwriting adjustments.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ins_product"
	__table_args__ = (
		UniqueConstraint("tenant_id", "product_code", name="uq_ins_product_tenant_code"),
		Index("ix_ins_product_tenant", "tenant_id"),
		Index("ix_ins_product_type", "product_type"),
		Index("ix_ins_product_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	product_code = Column(String(50), nullable=False, comment="Unique product code per tenant")
	product_type = Column(
		String(20),
		nullable=False,
		comment="LIFE/PROPERTY/CASUALTY/HEALTH/LIABILITY",
	)
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)

	# Coverage bounds — integer cents
	min_coverage_cents = Column(Integer, nullable=False, default=0)
	max_coverage_cents = Column(Integer, nullable=False, default=0)
	base_premium_cents = Column(Integer, nullable=False, default=0)

	coverage_terms = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{inclusions, exclusions, conditions, sub_limits}",
	)
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")

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

	policies: list[Policy] = relationship(
		"Policy",
		back_populates="product",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<InsuranceProduct {self.product_code!r} type={self.product_type!r}>"


# ---------------------------------------------------------------------------
# PolicyHolder
# ---------------------------------------------------------------------------

class PolicyHolder(AuditMixin, Model):
	"""Policyholder profile — underwriting data for a party.

	party_id soft-FK to foundation.Party.
	risk_score: 0.0000–1.0000 composite underwriting risk score.
	claims_history: count of prior claims.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ins_policy_holder"
	__table_args__ = (
		UniqueConstraint("tenant_id", "party_id", name="uq_ins_holder_tenant_party"),
		Index("ix_ins_holder_tenant", "tenant_id"),
		Index("ix_ins_holder_party", "party_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Soft FK to foundation.Party
	party_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Underwriting attributes
	date_of_birth = Column(Date, nullable=True)
	occupation = Column(String(255), nullable=True)
	credit_score = Column(Integer, nullable=True, comment="300–850 credit score")
	claims_history = Column(Integer, nullable=False, default=0, server_default="0", comment="Count of prior claims")
	risk_score = Column(
		Numeric(5, 4),
		nullable=True,
		comment="0.0000–1.0000 composite risk score from underwriting engine",
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

	policies: list[Policy] = relationship(
		"Policy",
		back_populates="holder",
		foreign_keys="Policy.holder_id",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<PolicyHolder party={self.party_id!r} risk={self.risk_score}>"


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class Policy(AuditMixin, Model):
	"""Master insurance policy contract.

	beneficiaries JSONB: [{party_id, name, relationship, pct_share}]
	exclusions JSONB: [{type, description}]
	agent_id soft-FK to foundation.Party (the selling agent).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ins_policy"
	__table_args__ = (
		UniqueConstraint("tenant_id", "policy_number", name="uq_ins_policy_tenant_number"),
		Index("ix_ins_policy_tenant", "tenant_id"),
		Index("ix_ins_policy_product", "product_id"),
		Index("ix_ins_policy_holder", "holder_id"),
		Index("ix_ins_policy_status", "status"),
		Index("ix_ins_policy_coverage_end", "coverage_end"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	policy_number = Column(String(100), nullable=False)
	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ins_product.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	holder_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ins_policy_holder.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	# insured_party_id: soft FK to foundation.Party (may differ from holder)
	insured_party_id = Column(UUID(as_uuid=False), nullable=False)

	# Coverage period
	coverage_start = Column(Date, nullable=False)
	coverage_end = Column(Date, nullable=False)

	# Financials — integer cents
	coverage_amount_cents = Column(Integer, nullable=False, default=0, comment="Total insured amount in cents")
	annual_premium_cents = Column(Integer, nullable=False, default=0, comment="Annual premium in cents")
	payment_frequency = Column(
		String(15),
		nullable=False,
		default="ANNUAL",
		comment="MONTHLY/QUARTERLY/ANNUAL",
	)

	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT/ACTIVE/LAPSED/CANCELLED/EXPIRED",
	)

	exclusions = Column(JSONB, nullable=False, default=list, server_default="[]")
	beneficiaries = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{party_id, name, relationship, pct_share}]",
	)

	# Selling agent (soft FK to foundation.Party)
	agent_id = Column(UUID(as_uuid=False), nullable=True)

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

	product: InsuranceProduct = relationship("InsuranceProduct", back_populates="policies", lazy="select")
	holder: PolicyHolder = relationship("PolicyHolder", back_populates="policies", foreign_keys=[holder_id], lazy="select")
	premiums: list[Premium] = relationship(
		"Premium",
		back_populates="policy",
		cascade="all, delete-orphan",
		lazy="select",
	)
	claims: list[Claim] = relationship(
		"Claim",
		back_populates="policy",
		lazy="select",
	)
	reinsurances: list[Reinsurance] = relationship(
		"Reinsurance",
		back_populates="policy",
		foreign_keys="Reinsurance.policy_id",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Policy {self.policy_number!r} status={self.status!r} "
			f"coverage={self.coverage_amount_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Premium
# ---------------------------------------------------------------------------

class Premium(AuditMixin, Model):
	"""Individual premium installment schedule record.

	One row per scheduled payment. paid_at NULL means not yet paid.
	receipt_number assigned on payment confirmation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ins_premium"
	__table_args__ = (
		Index("ix_ins_premium_policy", "policy_id"),
		Index("ix_ins_premium_tenant", "tenant_id"),
		Index("ix_ins_premium_due_date", "due_date"),
		Index("ix_ins_premium_status", "status"),
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
		ForeignKey("ins_policy.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	due_date = Column(Date, nullable=False)
	amount_cents = Column(Integer, nullable=False, default=0, comment="Scheduled premium amount in cents")
	paid_at = Column(DateTime(timezone=True), nullable=True, comment="NULL = not yet paid")
	paid_amount_cents = Column(Integer, nullable=False, default=0, server_default="0")
	payment_method = Column(String(50), nullable=True)
	receipt_number = Column(String(100), nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="DUE",
		server_default="DUE",
		comment="DUE/PAID/OVERDUE/WAIVED",
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

	policy: Policy = relationship("Policy", back_populates="premiums", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Premium policy={self.policy_id!r} due={self.due_date} "
			f"amount={self.amount_cents}¢ status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class Claim(AuditMixin, Model):
	"""Insurance claim against a policy.

	incident_location JSONB: {address, city, state, country_code, lat, lng}
	documents JSONB: [{url, doc_type, uploaded_at, description}]
	adjudication_notes: adjuster's narrative on the decision.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ins_claim"
	__table_args__ = (
		UniqueConstraint("tenant_id", "claim_number", name="uq_ins_claim_tenant_number"),
		Index("ix_ins_claim_tenant", "tenant_id"),
		Index("ix_ins_claim_policy", "policy_id"),
		Index("ix_ins_claim_status", "status"),
		Index("ix_ins_claim_claimant", "claimant_id"),
		Index("ix_ins_claim_incident_date", "incident_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	claim_number = Column(String(100), nullable=False)
	policy_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ins_policy.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	# claimant soft FK to foundation.Party
	claimant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	incident_date = Column(Date, nullable=False)
	reported_date = Column(Date, nullable=False)
	claim_type = Column(String(100), nullable=True)
	incident_description = Column(Text, nullable=True)
	incident_location = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{address, city, state, country_code, lat, lng}",
	)

	# Financials — integer cents
	claimed_amount_cents = Column(Integer, nullable=False, default=0)
	assessed_amount_cents = Column(Integer, nullable=True, comment="NULL until assessed")
	approved_amount_cents = Column(Integer, nullable=False, default=0, server_default="0")
	paid_amount_cents = Column(Integer, nullable=False, default=0, server_default="0")

	status = Column(
		String(15),
		nullable=False,
		default="REPORTED",
		server_default="REPORTED",
		comment="REPORTED/UNDER_REVIEW/APPROVED/REJECTED/PAID/CLOSED",
	)

	assessor_id = Column(UUID(as_uuid=False), nullable=True)
	adjudication_notes = Column(Text, nullable=True)
	documents = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{url, doc_type, uploaded_at, description}]",
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

	policy: Policy = relationship("Policy", back_populates="claims", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Claim {self.claim_number!r} status={self.status!r} "
			f"claimed={self.claimed_amount_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Reinsurance
# ---------------------------------------------------------------------------

class Reinsurance(AuditMixin, Model):
	"""Reinsurance cession record.

	Links a policy (or treaty-level if policy_id is NULL) to a reinsurer party.
	cession_pct: percentage of risk ceded.
	retention_cents: amount retained by the primary insurer (cents).
	recovery_cents: amount recovered from reinsurer on a claim (cents).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ins_reinsurance"
	__table_args__ = (
		Index("ix_ins_reinsurance_policy", "policy_id"),
		Index("ix_ins_reinsurance_tenant", "tenant_id"),
		Index("ix_ins_reinsurance_reinsurer", "reinsurer_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# policy_id NULL = treaty-level reinsurance arrangement
	policy_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ins_policy.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

	treaty_name = Column(String(255), nullable=False)
	# reinsurer_id soft FK to foundation.Party
	reinsurer_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	cession_type = Column(
		String(20),
		nullable=False,
		comment="PROPORTIONAL/NON_PROPORTIONAL",
	)
	cession_pct = Column(Numeric(5, 2), nullable=False, default=0, comment="% of risk ceded")

	# Financials — integer cents
	retention_cents = Column(Integer, nullable=False, default=0, comment="Amount retained by primary insurer")
	ceded_premium_cents = Column(Integer, nullable=False, default=0, comment="Premium ceded to reinsurer")
	recovery_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="Amount recovered from reinsurer")

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

	policy: Policy | None = relationship(
		"Policy",
		back_populates="reinsurances",
		foreign_keys=[policy_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Reinsurance treaty={self.treaty_name!r} "
			f"type={self.cession_type!r} cession={self.cession_pct}%>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"InsuranceProduct",
	"PolicyHolder",
	"Policy",
	"Premium",
	"Claim",
	"Reinsurance",
]
