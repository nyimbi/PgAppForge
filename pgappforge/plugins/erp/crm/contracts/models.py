"""
pgappforge/plugins/erp/crm/contracts/models.py

SQLAlchemy models for the Contract Lifecycle Management plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: BigInteger CENTS — never float/Decimal
  - JSONB for clause lists, change tracking, recurring rules
  - lazy='select' throughout (SA 2.x)

Table prefix: clm_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
# Enumerations (tuples used for CHECK constraint documentation)
# ---------------------------------------------------------------------------

CONTRACT_TYPE = (
	"NDA", "MSA", "SLA", "PURCHASE", "EMPLOYMENT",
	"LEASE", "LOAN", "PARTNERSHIP", "SERVICE", "OTHER",
)
CONTRACT_STATUS = (
	"DRAFT", "UNDER_REVIEW", "NEGOTIATION", "PENDING_SIGNATURE",
	"ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED", "CANCELLED",
)
CONFIDENTIALITY_LEVEL = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
RISK_LEVEL = ("LOW", "MEDIUM", "HIGH")
OBLIGATION_TYPE = ("PAYMENT", "DELIVERY", "REPORTING", "COMPLIANCE", "RENEWAL", "NOTICE", "OTHER")
OBLIGATION_STATUS = ("PENDING", "FULFILLED", "OVERDUE", "WAIVED")
RESPONSIBLE_PARTY = ("OUR_COMPANY", "COUNTERPARTY")
APPROVAL_ROLE = ("LEGAL", "FINANCE", "COMMERCIAL", "EXECUTIVE", "COMPLIANCE")
APPROVAL_STATUS = ("PENDING", "APPROVED", "REJECTED", "SKIPPED")
ESIG_PROVIDER = ("DOCUSIGN", "ADOBE_SIGN", "LOCAL", "MANUAL")
ESIG_STATUS = ("SENT", "VIEWED", "SIGNED", "DECLINED", "EXPIRED")
VERSION_STATUS = ("DRAFT", "NEGOTIATING", "FINAL", "SUPERSEDED")
LEASE_TYPE = ("FINANCE", "OPERATING")


# ---------------------------------------------------------------------------
# ContractTemplate
# ---------------------------------------------------------------------------

class ContractTemplate(AuditMixin, Model):
	"""Reusable template that seeds the body and standard clause list of new contracts.

	code is unique per tenant (max 30 chars), enabling programmatic lookup
	(e.g. CONTRACT_TEMPLATES["NDA_STANDARD"]).
	"""

	__allow_unmapped__ = True
	__tablename__ = "clm_contract_template"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_clm_template_tenant_code"),
		Index("ix_clm_template_tenant", "tenant_id"),
		Index("ix_clm_template_type", "contract_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(30), nullable=False)
	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)
	contract_type = Column(String(30), nullable=False, default="OTHER")
	template_body = Column(Text, nullable=False, default="")
	# list of clause_codes from ClauseLibrary
	standard_clauses: Any = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="Ordered list of clause_code strings from ClauseLibrary",
	)
	jurisdiction = Column(String(10), nullable=False, default="KE")
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

	def __repr__(self) -> str:
		return f"<ContractTemplate {self.code!r} type={self.contract_type!r}>"


# ---------------------------------------------------------------------------
# ClauseLibrary
# ---------------------------------------------------------------------------

class ClauseLibrary(AuditMixin, Model):
	"""Organisation-managed library of reusable contract clauses.

	clause_code is unique per tenant (max 30 chars).
	Approved clauses are locked by legal; risk_level drives review routing.
	"""

	__allow_unmapped__ = True
	__tablename__ = "clm_clause_library"
	__table_args__ = (
		UniqueConstraint("tenant_id", "clause_code", name="uq_clm_clause_tenant_code"),
		Index("ix_clm_clause_tenant", "tenant_id"),
		Index("ix_clm_clause_type", "clause_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	clause_code = Column(String(30), nullable=False)
	clause_name = Column(String(200), nullable=False)
	clause_type = Column(String(30), nullable=False)
	clause_text = Column(Text, nullable=False)
	is_standard = Column(Boolean, nullable=False, default=False, server_default="false")
	risk_level = Column(String(10), nullable=False, default="LOW")
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK Employee/User.id")
	approved_at = Column(DateTime(timezone=True), nullable=True)

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

	def __repr__(self) -> str:
		return f"<ClauseLibrary {self.clause_code!r} risk={self.risk_level!r}>"


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

class Contract(AuditMixin, Model):
	"""Central CLM aggregate: tracks the full lifecycle of a legal contract.

	Monetary values stored as integer cents (BigInteger) — currency_code carries the ISO code.
	IFRS 16 lease data lives in the related LeaseSchedule row.
	"""

	__allow_unmapped__ = True
	__tablename__ = "clm_contract"
	__table_args__ = (
		UniqueConstraint("tenant_id", "contract_number", name="uq_clm_contract_tenant_number"),
		Index("ix_clm_contract_tenant", "tenant_id"),
		Index("ix_clm_contract_counterparty", "counterparty_id"),
		Index("ix_clm_contract_status", "status"),
		Index("ix_clm_contract_expiry", "expiry_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_number = Column(String(30), nullable=False)
	title = Column(String(300), nullable=False)
	template_id = Column(
		UUID(as_uuid=False),
		ForeignKey("clm_contract_template.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	contract_type = Column(String(30), nullable=False, default="OTHER")
	counterparty_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	internal_owner_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	status = Column(String(30), nullable=False, default="DRAFT")

	effective_date = Column(Date, nullable=True)
	expiry_date = Column(Date, nullable=True)
	termination_notice_days = Column(Integer, nullable=False, default=30, server_default="30")
	auto_renew = Column(Boolean, nullable=False, default=False, server_default="false")
	renewal_notice_days = Column(Integer, nullable=False, default=60, server_default="60")

	contract_value_cents = Column(BigInteger, nullable=True)
	currency_code = Column(String(3), nullable=False, default="KES")
	payment_terms_days = Column(Integer, nullable=True)
	governing_law = Column(String(10), nullable=False, default="KE")
	confidentiality_level = Column(String(20), nullable=False, default="INTERNAL")

	signed_at = Column(DateTime(timezone=True), nullable=True)
	terminated_at = Column(DateTime(timezone=True), nullable=True)
	termination_reason = Column(Text, nullable=True)

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

	template: Any = relationship(
		"ContractTemplate",
		foreign_keys=[template_id],
		lazy="select",
	)
	versions: list[ContractVersion] = relationship(
		"ContractVersion",
		back_populates="contract",
		lazy="select",
		order_by="ContractVersion.version_number",
	)
	obligations: list[ContractObligation] = relationship(
		"ContractObligation",
		back_populates="contract",
		lazy="select",
	)
	approvals: list[ContractApproval] = relationship(
		"ContractApproval",
		back_populates="contract",
		lazy="select",
		order_by="ContractApproval.sequence_order",
	)
	signature_requests: list[ESignatureRequest] = relationship(
		"ESignatureRequest",
		back_populates="contract",
		lazy="select",
	)
	lease_schedule: Any = relationship(
		"LeaseSchedule",
		back_populates="contract",
		uselist=False,
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Contract {self.contract_number!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ContractVersion
# ---------------------------------------------------------------------------

class ContractVersion(AuditMixin, Model):
	"""Immutable snapshot of a contract body at a point in negotiation.

	Tracked diffs stored as JSONB (list of {op, path, value} patches).
	version_number increments per contract; FINAL versions become the signed text.
	"""

	__allow_unmapped__ = True
	__tablename__ = "clm_contract_version"
	__table_args__ = (
		UniqueConstraint("contract_id", "version_number", name="uq_clm_version_contract_num"),
		Index("ix_clm_version_contract", "contract_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("clm_contract.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	version_number = Column(Integer, nullable=False)
	body = Column(Text, nullable=False)
	change_summary = Column(Text, nullable=False, default="")
	created_by = Column(UUID(as_uuid=False), nullable=False)
	status = Column(String(20), nullable=False, default="DRAFT")
	changes_tracked: Any = Column(
		JSONB,
		nullable=True,
		comment="List of {op, path, value} JSON-Patch entries",
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

	contract: Any = relationship("Contract", back_populates="versions", lazy="select")

	def __repr__(self) -> str:
		return f"<ContractVersion contract={self.contract_id!r} v{self.version_number} {self.status!r}>"


# ---------------------------------------------------------------------------
# ContractObligation
# ---------------------------------------------------------------------------

class ContractObligation(AuditMixin, Model):
	"""A single trackable obligation arising from a contract.

	recurring_rule holds an iCalendar RRULE string for periodic obligations.
	amount_cents is non-null for PAYMENT obligations; NULL for others.
	"""

	__allow_unmapped__ = True
	__tablename__ = "clm_contract_obligation"
	__table_args__ = (
		Index("ix_clm_obligation_contract", "contract_id"),
		Index("ix_clm_obligation_due_date", "due_date"),
		Index("ix_clm_obligation_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("clm_contract.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	obligation_type = Column(String(20), nullable=False)
	description = Column(Text, nullable=False)
	due_date = Column(Date, nullable=True)
	recurring_rule = Column(String(50), nullable=True, comment="iCalendar RRULE string")
	amount_cents = Column(BigInteger, nullable=True)
	responsible_party = Column(String(20), nullable=False, default="OUR_COMPANY")
	status = Column(String(20), nullable=False, default="PENDING")
	fulfilled_at = Column(DateTime(timezone=True), nullable=True)
	alert_days_before = Column(Integer, nullable=False, default=14, server_default="14")

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

	contract: Any = relationship("Contract", back_populates="obligations", lazy="select")

	def __repr__(self) -> str:
		return f"<ContractObligation type={self.obligation_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ContractApproval
# ---------------------------------------------------------------------------

class ContractApproval(AuditMixin, Model):
	"""One approval step in the sequential approval workflow for a contract.

	sequence_order controls routing order; SKIPPED rows are bypassed.
	"""

	__allow_unmapped__ = True
	__tablename__ = "clm_contract_approval"
	__table_args__ = (
		Index("ix_clm_approval_contract", "contract_id"),
		Index("ix_clm_approval_approver", "approver_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("clm_contract.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	approver_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	approval_role = Column(String(20), nullable=False)
	status = Column(String(20), nullable=False, default="PENDING")
	comments = Column(Text, nullable=True)
	decided_at = Column(DateTime(timezone=True), nullable=True)
	sequence_order = Column(Integer, nullable=False, default=0, server_default="0")

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

	contract: Any = relationship("Contract", back_populates="approvals", lazy="select")

	def __repr__(self) -> str:
		return f"<ContractApproval role={self.approval_role!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ESignatureRequest
# ---------------------------------------------------------------------------

class ESignatureRequest(AuditMixin, Model):
	"""Tracks one signatory's e-signature request for a contract.

	provider_envelope_id is the external reference from DocuSign / Adobe Sign.
	LOCAL provider uses an in-app signing link; MANUAL records wet ink.
	"""

	__allow_unmapped__ = True
	__tablename__ = "clm_esignature_request"
	__table_args__ = (
		Index("ix_clm_esig_contract", "contract_id"),
		Index("ix_clm_esig_signatory", "signatory_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("clm_contract.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	signatory_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	signatory_name = Column(String(100), nullable=False)
	signatory_email = Column(String(200), nullable=False)
	signatory_role = Column(String(50), nullable=False)
	provider = Column(String(20), nullable=False, default="LOCAL")
	provider_envelope_id = Column(String(100), nullable=True)
	status = Column(String(20), nullable=False, default="SENT")
	sent_at = Column(DateTime(timezone=True), nullable=True)
	signed_at = Column(DateTime(timezone=True), nullable=True)

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

	contract: Any = relationship("Contract", back_populates="signature_requests", lazy="select")

	def __repr__(self) -> str:
		return f"<ESignatureRequest signatory={self.signatory_email!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# LeaseSchedule
# ---------------------------------------------------------------------------

class LeaseSchedule(AuditMixin, Model):
	"""IFRS 16 lease recognition data for a LEASE-type contract.

	One row per contract (unique FK).  Populated by CLMService.calculate_lease_schedule().
	All monetary fields stored as integer cents.
	discount_rate_pa is annualised (e.g. 0.1200 = 12%).
	"""

	__allow_unmapped__ = True
	__tablename__ = "clm_lease_schedule"
	__table_args__ = (
		UniqueConstraint("contract_id", name="uq_clm_lease_contract"),
		Index("ix_clm_lease_contract", "contract_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("clm_contract.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
		index=True,
	)
	lease_type = Column(String(20), nullable=False, default="OPERATING")
	asset_description = Column(Text, nullable=False)
	commencement_date = Column(Date, nullable=False)
	lease_term_months = Column(Integer, nullable=False)
	monthly_payment_cents = Column(BigInteger, nullable=False)
	discount_rate_pa = Column(
		Numeric(8, 4),
		nullable=False,
		comment="Annual discount rate e.g. 0.1200 = 12%",
	)
	rou_asset_cents = Column(BigInteger, nullable=False, default=0)
	lease_liability_cents = Column(BigInteger, nullable=False, default=0)
	initial_recognition_date = Column(Date, nullable=False)

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

	contract: Any = relationship("Contract", back_populates="lease_schedule", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<LeaseSchedule contract={self.contract_id!r} "
			f"type={self.lease_type!r} rou={self.rou_asset_cents}¢>"
		)


__all__ = [
	"ContractTemplate",
	"ClauseLibrary",
	"Contract",
	"ContractVersion",
	"ContractObligation",
	"ContractApproval",
	"ESignatureRequest",
	"LeaseSchedule",
	# enumerations
	"CONTRACT_TYPE",
	"CONTRACT_STATUS",
	"CONFIDENTIALITY_LEVEL",
	"RISK_LEVEL",
	"OBLIGATION_TYPE",
	"OBLIGATION_STATUS",
	"RESPONSIBLE_PARTY",
	"APPROVAL_ROLE",
	"APPROVAL_STATUS",
	"ESIG_PROVIDER",
	"ESIG_STATUS",
	"VERSION_STATUS",
	"LEASE_TYPE",
]
