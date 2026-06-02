"""
pgappforge/plugins/erp/industry/public_sector/models.py

SQLAlchemy models for the Public Sector plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid()
  - ALL monetary amounts: Integer cents (NEVER float)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - PII fields (national_id) stored encrypted via application-layer encryption
  - lazy='select' throughout
  - eligibility_score: NUMERIC(5,4) in [0,1]

Table prefix: ps_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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
# Constituent
# ---------------------------------------------------------------------------

class Constituent(AuditMixin, Model):
	"""Government constituent — citizen, business, or NGO.

	Links to foundation.Party (party_id) for shared contact/address data.
	national_id_encrypted stores the national ID / company registration
	encrypted at the application layer (AES-256-GCM) — the DB column
	holds the ciphertext + IV as a hex string.

	benefits_enrolled JSONB: [{program_code, enrolled_at, status}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "ps_constituent"
	__table_args__ = (
		Index("ix_ps_const_tenant", "tenant_id"),
		Index("ix_ps_const_party", "party_id"),
		Index("ix_ps_const_tenant_type", "tenant_id", "constituent_type"),
		Index("ix_ps_const_case_worker", "case_worker_id"),
		UniqueConstraint("tenant_id", "constituent_number", name="uq_ps_const_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	party_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation Party (soft)")
	constituent_number = Column(String(50), nullable=False, comment="Internal constituent reference; unique per tenant")

	constituent_type = Column(
		String(20),
		nullable=False,
		comment="CITIZEN|BUSINESS|NGO|GOVERNMENT_ENTITY",
	)

	# PII — application-layer encrypted
	national_id_encrypted = Column(
		Text,
		nullable=True,
		comment="National ID / company reg number — AES-256-GCM ciphertext (hex IV:ciphertext)",
	)
	date_of_birth = Column(Date, nullable=True, comment="Encrypted at rest via DB column encryption in production")
	gender = Column(String(10), nullable=True)

	# Welfare / benefits
	benefits_enrolled = Column(JSONB, nullable=False, default=list, comment="[{program_code, enrolled_at, status}]")
	vulnerability_flags = Column(JSONB, nullable=False, default=list, comment="[ELDERLY, DISABLED, SINGLE_PARENT, …]")

	case_worker_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ab_user (assigned case worker)")
	preferred_language = Column(String(10), nullable=True, comment="ISO 639-1 language code")
	contact_email = Column(String(255), nullable=True)
	contact_phone = Column(String(50), nullable=True)
	address = Column(JSONB, nullable=False, default=dict, comment="{line1,line2,city,state,postal_code,country}")

	status = Column(String(20), nullable=False, default="ACTIVE", comment="ACTIVE|INACTIVE|DECEASED|MERGED")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	cases: list[GovernmentCase] = relationship("GovernmentCase", back_populates="constituent", lazy="select")

	def __repr__(self) -> str:
		return f"<Constituent {self.constituent_number!r} type={self.constituent_type!r}>"


# ---------------------------------------------------------------------------
# GovernmentCase
# ---------------------------------------------------------------------------

class GovernmentCase(AuditMixin, Model):
	"""A government service delivery case for a constituent.

	Tracks benefit eligibility determination, grant awards, and
	service delivery for a specific program.

	eligibility_score: NUMERIC(5,4) — computed by rules engine or ML model,
	range [0.0000, 1.0000].

	benefits_granted JSONB: [{benefit_type, amount_cents, frequency, start_date}]
	IMMUTABLE: once status=CLOSED, insert a new case for modifications.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ps_government_case"
	__table_args__ = (
		Index("ix_ps_case_tenant", "tenant_id"),
		Index("ix_ps_case_constituent", "constituent_id"),
		Index("ix_ps_case_tenant_status", "tenant_id", "status"),
		Index("ix_ps_case_program_type", "program_type"),
		Index("ix_ps_case_case_worker", "case_worker_id"),
		UniqueConstraint("tenant_id", "case_number", name="uq_ps_case_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	case_number = Column(String(50), nullable=False, comment="Unique case reference per tenant")
	constituent_id = Column(UUID(as_uuid=False), ForeignKey("ps_constituent.id"), nullable=False, index=True)
	case_worker_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ab_user")
	verified_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — supervisor verification")

	program_type = Column(
		String(50),
		nullable=False,
		comment="SOCIAL_GRANT|HOUSING|HEALTH|EDUCATION|BUSINESS_SUPPORT|DISABILITY|UNEMPLOYMENT",
	)

	eligibility_score = Column(Numeric(5, 4), nullable=True, comment="Computed eligibility [0.0000–1.0000]")
	benefits_granted = Column(JSONB, nullable=False, default=list, comment="[{benefit_type, amount_cents, frequency}]")
	total_benefit_amount_cents = Column(Integer, nullable=False, default=0, comment="Sum of all periodic benefit amounts")

	grant_start = Column(Date, nullable=True, comment="Benefit start date")
	grant_end = Column(Date, nullable=True, comment="Benefit end date; NULL = open-ended")
	next_review_date = Column(Date, nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN|UNDER_REVIEW|APPROVED|REJECTED|ACTIVE|SUSPENDED|CLOSED|APPEALED",
	)
	rejection_reason = Column(Text, nullable=True)
	supporting_documents = Column(JSONB, nullable=False, default=list, comment="[{url, doc_type, uploaded_at}]")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	constituent: Constituent = relationship("Constituent", back_populates="cases", lazy="select")

	def __repr__(self) -> str:
		return f"<GovernmentCase {self.case_number!r} program={self.program_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# PublicFundingGrant
# ---------------------------------------------------------------------------

class PublicFundingGrant(AuditMixin, Model):
	"""Public funding grant received by or administered by the public entity.

	Represents external funding (from central/federal/donor) awarded to
	the public agency for a specific purpose.

	disbursed_cents is updated as tranches are released — add-only.
	conditions JSONB: [{condition_text, due_date, met: bool, evidence_url}]

	IMMUTABLE LEDGER: disbursements are recorded as separate entries;
	disbursed_cents is a running total, never decremented.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ps_public_funding_grant"
	__table_args__ = (
		Index("ix_ps_grant_tenant", "tenant_id"),
		Index("ix_ps_grant_grantor", "grantor_id"),
		Index("ix_ps_grant_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "grant_number", name="uq_ps_grant_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	grant_number = Column(String(100), nullable=False, comment="Grantor's grant reference number; unique per tenant")
	grantor = Column(String(255), nullable=False, comment="Grantor name (government body, foundation, NGO)")
	grantor_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation Party (grantor)")

	# Amounts — integer cents
	amount_cents = Column(Integer, nullable=False, comment="Total awarded grant amount")
	disbursed_cents = Column(Integer, nullable=False, default=0, comment="Running disbursed total; add-only")
	currency_code = Column(String(3), nullable=False, default="USD")

	purpose = Column(Text, nullable=False, comment="Specific purpose/project description")
	conditions = Column(JSONB, nullable=False, default=list, comment="[{condition_text, due_date, met, evidence_url}]")
	reporting_schedule = Column(JSONB, nullable=False, default=list, comment="[{due_date, report_type, submitted_at}]")

	award_date = Column(Date, nullable=True)
	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="AWARDED",
		comment="AWARDED|ACTIVE|SUSPENDED|COMPLETED|TERMINATED|CLOSED",
	)
	programme_manager_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<PublicFundingGrant {self.grant_number!r} grantor={self.grantor!r} status={self.status!r}>"


__all__ = [
	"Constituent",
	"GovernmentCase",
	"PublicFundingGrant",
]
