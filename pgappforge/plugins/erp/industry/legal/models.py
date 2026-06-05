"""
pgappforge/plugins/erp/industry/legal/models.py

Legal Services — SQLAlchemy models.

Design rules:
  - All PKs: UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL + AuditMixin
  - All monetary amounts: integer cents
  - All FKs to foundation.Party: UUID string
  - JSONB for semi-structured data (parties list, legal_issues)
  - Akoma Ntoso FRBR URI convention for legislative references

Table prefix: leg_
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# LegalMatter
# ---------------------------------------------------------------------------

class LegalMatter(AuditMixin, Model):
	"""A legal matter / case file.

	One row per distinct legal engagement (litigation, transaction, advisory,
	compliance review, or IP filing). Links to foundation.Party for client,
	lead counsel, and opposing party.

	Budget and billed amounts are integer cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "leg_matter"
	__table_args__ = (
		UniqueConstraint("matter_number", name="uq_leg_matter_number"),
		Index("ix_leg_matter_client", "client_id"),
		Index("ix_leg_matter_tenant_status", "tenant_id", "status"),
		Index("ix_leg_matter_lead_counsel", "lead_counsel_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	matter_number = Column(
		String(50),
		nullable=False,
		comment="Unique matter reference number e.g. MAT-2026-001",
	)
	matter_type = Column(
		String(20),
		nullable=False,
		comment="LITIGATION | TRANSACTION | ADVISORY | COMPLIANCE | IP",
	)

	# Parties (foundation.Party UUIDs)
	client_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Client party UUID (foundation.Party)",
	)
	lead_counsel_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Lead attorney/counsel party UUID",
	)
	opposing_party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		comment="Opposing party UUID (NULL for advisory/transactional matters)",
	)

	# Court / jurisdiction
	jurisdiction = Column(String(100), nullable=False)
	court = Column(String(200), nullable=True)

	status = Column(
		String(15),
		nullable=False,
		default="INTAKE",
		comment="INTAKE | ACTIVE | DISCOVERY | TRIAL | APPEAL | SETTLED | CLOSED",
	)
	description = Column(Text, nullable=True)
	filed_date = Column(Date, nullable=True)
	target_resolution_date = Column(Date, nullable=True)

	# Financials — integer cents
	budget_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Approved matter budget in cents",
	)
	billed_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total billed to date in cents",
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
	documents: list[LegalDocument] = relationship(
		"LegalDocument",
		back_populates="matter",
		cascade="all, delete-orphan",
		lazy="select",
	)
	time_entries: list[LegalTimeEntry] = relationship(
		"LegalTimeEntry",
		back_populates="matter",
		cascade="all, delete-orphan",
		lazy="select",
	)
	deadlines: list[Deadline] = relationship(
		"Deadline",
		back_populates="matter",
		cascade="all, delete-orphan",
		lazy="select",
	)
	invoices: list[LegalInvoice] = relationship(
		"LegalInvoice",
		back_populates="matter",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LegalMatter {self.id!r} #{self.matter_number!r} "
			f"type={self.matter_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# LegalDocument
# ---------------------------------------------------------------------------

class LegalDocument(AuditMixin, Model):
	"""A legal document associated with a matter.

	Supports versioning (version field), lifecycle status, digital execution
	tracking (executed_at), and SHA-256 integrity checksum.

	parties JSONB carries structured signatory data:
	  [{"party_id": "...", "role": "SIGNATORY", "signed_at": "..."}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "leg_document"
	__table_args__ = (
		Index("ix_leg_doc_matter", "matter_id"),
		Index("ix_leg_doc_tenant_type", "tenant_id", "document_type"),
		Index("ix_leg_doc_author", "author_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	matter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("leg_matter.id", ondelete="RESTRICT"),
		nullable=False,
	)

	document_type = Column(
		String(15),
		nullable=False,
		comment="CONTRACT | PLEADING | BRIEF | ORDER | JUDGMENT | MEMO",
	)
	title = Column(String(500), nullable=False)
	version = Column(String(20), nullable=False, default="1.0")
	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | REVIEW | FINAL | EXECUTED | SUPERSEDED",
	)

	author_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		comment="Authoring party UUID (foundation.Party)",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	executed_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp of document execution/signing (NULL until EXECUTED)",
	)

	content_url = Column(Text, nullable=True, comment="Object storage URL for document binary")
	checksum_sha256 = Column(
		String(64),
		nullable=True,
		comment="SHA-256 hex digest of document content for integrity verification",
	)
	parties: list[Any] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="Structured signatory list: [{party_id, role, signed_at}]",
	)
	expiry_date = Column(Date, nullable=True)

	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	matter: LegalMatter = relationship(
		"LegalMatter",
		back_populates="documents",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LegalDocument {self.id!r} title={self.title!r} "
			f"v={self.version!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# LegalTimeEntry
# ---------------------------------------------------------------------------

class LegalTimeEntry(AuditMixin, Model):
	"""Billable (or non-billable) time entry for a legal matter.

	hours is NUMERIC(5,2) — up to 999.99 hours.
	rate_cents_per_hour and amount_cents are integer cents.
	Activity codes follow UTBMS (Uniform Task-Based Management System).
	"""

	__allow_unmapped__ = True
	__tablename__ = "leg_time_entry"
	__table_args__ = (
		Index("ix_leg_te_matter", "matter_id"),
		Index("ix_leg_te_timekeeper", "timekeeper_id"),
		Index("ix_leg_te_tenant_status", "tenant_id", "status"),
		Index("ix_leg_te_work_date", "work_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	matter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("leg_matter.id", ondelete="RESTRICT"),
		nullable=False,
	)
	timekeeper_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Attorney/paralegal party UUID (foundation.Party)",
	)

	work_date = Column(Date, nullable=False)
	hours = Column(
		Numeric(5, 2),
		nullable=False,
		comment="Time in decimal hours e.g. 1.50 = 90 minutes",
	)
	rate_cents_per_hour = Column(
		Integer,
		nullable=False,
		comment="Billing rate in cents per hour",
	)
	amount_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="hours * rate_cents_per_hour, stored as integer cents",
	)
	activity_code = Column(
		String(20),
		nullable=False,
		comment="UTBMS activity code e.g. A101, L110",
	)
	description = Column(Text, nullable=False)
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | APPROVED | BILLED",
	)
	is_billable = Column(Boolean, nullable=False, default=True)

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

	matter: LegalMatter = relationship(
		"LegalMatter",
		back_populates="time_entries",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LegalTimeEntry {self.id!r} matter={self.matter_id!r} "
			f"hours={self.hours} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Deadline
# ---------------------------------------------------------------------------

class Deadline(AuditMixin, Model):
	"""A tracked legal deadline or court date.

	is_hard_deadline=True means missing it has irreversible legal consequences
	(e.g. statute of limitations expiry, appeal window close).
	"""

	__allow_unmapped__ = True
	__tablename__ = "leg_deadline"
	__table_args__ = (
		Index("ix_leg_dl_matter", "matter_id"),
		Index("ix_leg_dl_tenant_date", "tenant_id", "deadline_date"),
		Index("ix_leg_dl_responsible", "responsible_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	matter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("leg_matter.id", ondelete="RESTRICT"),
		nullable=False,
	)

	deadline_type = Column(
		String(30),
		nullable=False,
		comment="STATUTE_OF_LIMITATIONS | FILING | HEARING | DISCOVERY_CLOSE",
	)
	deadline_date = Column(Date, nullable=False)
	description = Column(Text, nullable=False)
	is_hard_deadline = Column(
		Boolean,
		nullable=False,
		default=True,
		comment="True = irreversible legal consequence if missed",
	)
	status = Column(
		String(10),
		nullable=False,
		default="PENDING",
		comment="PENDING | MET | MISSED | EXTENDED",
	)
	responsible_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		comment="Responsible attorney/paralegal party UUID",
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

	matter: LegalMatter = relationship(
		"LegalMatter",
		back_populates="deadlines",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Deadline {self.id!r} type={self.deadline_type!r} "
			f"date={self.deadline_date!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# LegalInvoice
# ---------------------------------------------------------------------------

class LegalInvoice(AuditMixin, Model):
	"""Invoice generated from time entries and disbursements for a matter.

	All monetary columns are integer cents. The total is:
	  total_cents = time_charges_cents + disbursements_cents + tax_cents
	"""

	__allow_unmapped__ = True
	__tablename__ = "leg_invoice"
	__table_args__ = (
		UniqueConstraint("invoice_number", name="uq_leg_invoice_number"),
		Index("ix_leg_inv_matter", "matter_id"),
		Index("ix_leg_inv_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	matter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("leg_matter.id", ondelete="RESTRICT"),
		nullable=False,
	)

	invoice_number = Column(String(50), nullable=False)
	billing_period_start = Column(Date, nullable=False)
	billing_period_end = Column(Date, nullable=False)

	# Monetary breakdown — integer cents
	time_charges_cents = Column(Integer, nullable=False, default=0)
	disbursements_cents = Column(Integer, nullable=False, default=0)
	tax_cents = Column(Integer, nullable=False, default=0)
	total_cents = Column(Integer, nullable=False, default=0)

	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SENT | PAID | DISPUTED",
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

	matter: LegalMatter = relationship(
		"LegalMatter",
		back_populates="invoices",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LegalInvoice {self.id!r} #{self.invoice_number!r} "
			f"total={self.total_cents} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Precedent
# ---------------------------------------------------------------------------

class Precedent(AuditMixin, Model):
	"""Case law precedent record for research and citation tracking.

	legal_issues and relevance_tags are TEXT[] PostgreSQL arrays, enabling
	efficient overlap (&&) queries for issue-based search.

	citation must be unique (e.g. "[2020] UKSC 12", "142 S.Ct. 2228").
	"""

	__allow_unmapped__ = True
	__tablename__ = "leg_precedent"
	__table_args__ = (
		UniqueConstraint("citation", name="uq_leg_precedent_citation"),
		Index("ix_leg_prec_jurisdiction", "jurisdiction"),
		Index("ix_leg_prec_tenant", "tenant_id"),
		Index("ix_leg_prec_decided_date", "decided_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	jurisdiction = Column(String(100), nullable=False)
	court = Column(String(200), nullable=True)
	case_name = Column(String(500), nullable=False)
	citation = Column(
		String(200),
		nullable=False,
		comment="Unique legal citation e.g. [2020] UKSC 12",
	)
	decided_date = Column(Date, nullable=True)
	outcome = Column(
		String(50),
		nullable=True,
		comment="e.g. AFFIRMED, REVERSED, REMANDED, DISMISSED",
	)

	legal_issues = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
		comment="Array of legal issue tags for overlap search",
	)
	summary = Column(Text, nullable=True)
	full_text_url = Column(Text, nullable=True)
	relevance_tags = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
		comment="Custom relevance/practice-area tags",
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

	def __repr__(self) -> str:
		return (
			f"<Precedent {self.id!r} citation={self.citation!r} "
			f"jurisdiction={self.jurisdiction!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LegalMatter",
	"LegalDocument",
	"LegalTimeEntry",
	"Deadline",
	"LegalInvoice",
	"Precedent",
]
