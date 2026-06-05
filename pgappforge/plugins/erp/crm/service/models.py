"""
pgappforge/plugins/erp/crm/service/models.py

SQLAlchemy models for the Service Cloud plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - RulesMixin on Case for rules engine integration
  - lazy='select' throughout (SA 2.x)
  - ARRAY types via postgresql.ARRAY for knowledge_articles_used / tags

Table prefix: sc_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.rules.mixin import RulesMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations (VARCHAR + CHECK — no SA Enum, PG-only)
# ---------------------------------------------------------------------------

CASE_PRIORITY = ("P1", "P2", "P3", "P4")
CASE_STATUS = ("NEW", "OPEN", "PENDING_CUSTOMER", "ESCALATED", "RESOLVED", "CLOSED")
CASE_CHANNEL = ("EMAIL", "PHONE", "CHAT", "WEB", "SOCIAL")
ARTICLE_STATUS = ("DRAFT", "REVIEW", "PUBLISHED", "ARCHIVED")
COMMENT_CHANNEL = ("INTERNAL", "EMAIL", "CHAT")
SURVEY_TYPE = ("CSAT", "NPS", "CES")


# ---------------------------------------------------------------------------
# SLAPolicy
# ---------------------------------------------------------------------------

class SLAPolicy(AuditMixin, Model):
	"""SLA configuration per priority level.

	Drives sla_breach_at computation on Case creation/escalation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_sla_policy"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_sc_sla_policy_tenant_name"),
		Index("ix_sc_sla_policy_tenant", "tenant_id"),
		Index("ix_sc_sla_policy_priority", "priority"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	priority = Column(
		String(5),
		nullable=False,
		comment="P1|P2|P3|P4",
	)
	first_response_minutes = Column(
		Integer,
		nullable=False,
		comment="Minutes to first agent response",
	)
	resolution_minutes = Column(
		Integer,
		nullable=False,
		comment="Minutes to case resolution",
	)
	business_hours_only = Column(
		Boolean,
		nullable=False,
		default=True,
		server_default="true",
		comment="When true, SLA clock pauses outside business hours",
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

	cases: list[Case] = relationship(
		"Case",
		back_populates="sla_policy",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SLAPolicy {self.name!r} priority={self.priority!r}>"


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------

class Case(RulesMixin, AuditMixin, Model):
	"""Support case — central entity for Service Cloud.

	SLA breach tracking: sla_breach_at is set at creation based on SLAPolicy
	and priority. Escalation re-calculates.

	RulesMixin fires rules engine on create/update via SA mapper events.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_case"
	__table_args__ = (
		UniqueConstraint("tenant_id", "case_number", name="uq_sc_case_tenant_number"),
		Index("ix_sc_case_tenant", "tenant_id"),
		Index("ix_sc_case_account", "account_id"),
		Index("ix_sc_case_contact", "contact_id"),
		Index("ix_sc_case_status", "status"),
		Index("ix_sc_case_priority", "priority"),
		Index("ix_sc_case_owner", "owner_id"),
		Index("ix_sc_case_sla_breach", "sla_breach_at"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"status", "priority", "owner_id", "escalated_to",
		"sla_breach_at", "resolved_at", "csat_score",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	case_number = Column(String(30), nullable=False, comment="Human-readable case ID; unique per tenant")

	# Relationships to other ERP entities (soft FKs — no hard constraints to crm/sales)
	account_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK SalesAccount.id")
	contact_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK SalesContact.id")

	# Case details
	subject = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	priority = Column(
		String(5),
		nullable=False,
		default="P3",
		server_default="P3",
		comment="P1|P2|P3|P4",
	)
	status = Column(
		String(25),
		nullable=False,
		default="NEW",
		server_default="NEW",
		comment="NEW|OPEN|PENDING_CUSTOMER|ESCALATED|RESOLVED|CLOSED",
	)
	category = Column(String(100), nullable=True)
	subcategory = Column(String(100), nullable=True)
	channel = Column(
		String(15),
		nullable=False,
		default="WEB",
		server_default="WEB",
		comment="EMAIL|PHONE|CHAT|WEB|SOCIAL",
	)

	# Assignment
	owner_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK Employee.id — assigned agent",
	)
	escalated_to = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK Employee.id — escalation target",
	)

	# SLA
	sla_policy_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_sla_policy.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	sla_breach_at = Column(
		DateTime(timezone=True),
		nullable=True,
		index=True,
		comment="TIMESTAMPTZ — when SLA is breached",
	)

	# Resolution
	resolved_at = Column(DateTime(timezone=True), nullable=True)
	csat_score = Column(
		Integer,
		nullable=True,
		comment="Customer satisfaction score 1-5",
	)
	resolution_notes = Column(Text, nullable=True)
	knowledge_articles_used = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		default=list,
		server_default="{}",
		comment="Array of KnowledgeArticle UUIDs used during resolution",
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
	sla_policy: SLAPolicy = relationship("SLAPolicy", back_populates="cases", lazy="select")
	comments: list[CaseComment] = relationship(
		"CaseComment",
		back_populates="case",
		cascade="all, delete-orphan",
		lazy="select",
	)
	survey_responses: list[SurveyResponse] = relationship(
		"SurveyResponse",
		back_populates="case",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Case {self.case_number!r} status={self.status!r} priority={self.priority!r}>"


# ---------------------------------------------------------------------------
# KnowledgeArticle
# ---------------------------------------------------------------------------

class KnowledgeArticle(AuditMixin, Model):
	"""Knowledge base article with optional vector embedding for semantic search."""

	__allow_unmapped__ = True
	__tablename__ = "sc_knowledge_article"
	__table_args__ = (
		Index("ix_sc_ka_tenant", "tenant_id"),
		Index("ix_sc_ka_status", "status"),
		Index("ix_sc_ka_category", "category"),
		Index("ix_sc_ka_author", "author_id"),
		Index("ix_sc_ka_content_gin", "content_tsv", postgresql_using="gin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	title = Column(String(255), nullable=False)
	category = Column(String(100), nullable=True)
	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT|REVIEW|PUBLISHED|ARCHIVED",
	)
	content = Column(Text, nullable=False)
	tags = Column(
		ARRAY(String),
		nullable=False,
		default=list,
		server_default="{}",
	)
	author_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK Employee.id")
	views = Column(Integer, nullable=False, default=0, server_default="0")
	helpful_votes = Column(Integer, nullable=False, default=0, server_default="0")
	last_published_at = Column(DateTime(timezone=True), nullable=True)

	# Vector embedding — nullable; populated by AI pipeline (pgvector extension)
	# Stored as JSONB array when pgvector is not available; cast at query time.
	embedding: Any = Column(
		JSONB,
		nullable=True,
		comment="1536-dim embedding vector stored as JSON array; use pgvector cast at query time",
	)

	# Full-text search vector — maintained via PostgreSQL trigger on INSERT/UPDATE.
	# Trigger DDL (run once per schema migration):
	#   CREATE OR REPLACE FUNCTION sc_ka_tsv_update() RETURNS trigger LANGUAGE plpgsql AS $$
	#   BEGIN
	#     NEW.content_tsv := to_tsvector('english', coalesce(NEW.title,'') || ' ' || coalesce(NEW.content,''));
	#     RETURN NEW;
	#   END $$;
	#   CREATE TRIGGER trg_sc_ka_tsv BEFORE INSERT OR UPDATE ON sc_knowledge_article
	#     FOR EACH ROW EXECUTE FUNCTION sc_ka_tsv_update();
	content_tsv = Column(
		TSVECTOR,
		nullable=True,
		comment="Full-text search vector over title+content; maintained by PostgreSQL trigger",
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
		return f"<KnowledgeArticle {self.title!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# CaseComment
# ---------------------------------------------------------------------------

class CaseComment(AuditMixin, Model):
	"""Comment or communication on a case — internal notes or customer-facing."""

	__allow_unmapped__ = True
	__tablename__ = "sc_case_comment"
	__table_args__ = (
		Index("ix_sc_case_comment_case", "case_id"),
		Index("ix_sc_case_comment_author", "author_id"),
		Index("ix_sc_case_comment_tenant", "tenant_id"),
		Index("ix_sc_case_comment_sent", "sent_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	case_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_case.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	author_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK Employee.id or contact")
	is_public = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
		comment="False = internal note; True = visible to customer",
	)
	body = Column(Text, nullable=False)
	sent_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	channel = Column(
		String(15),
		nullable=False,
		default="INTERNAL",
		server_default="INTERNAL",
		comment="INTERNAL|EMAIL|CHAT",
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

	case: Case = relationship("Case", back_populates="comments", lazy="select")

	def __repr__(self) -> str:
		return f"<CaseComment case={self.case_id!r} public={self.is_public}>"


# ---------------------------------------------------------------------------
# SurveyResponse
# ---------------------------------------------------------------------------

class SurveyResponse(Model):
	"""Customer satisfaction / NPS / CES survey result linked to a closed case.

	Append-only — never update submitted responses.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_survey_response"
	__table_args__ = (
		Index("ix_sc_survey_case", "case_id"),
		Index("ix_sc_survey_contact", "contact_id"),
		Index("ix_sc_survey_tenant", "tenant_id"),
		Index("ix_sc_survey_type", "survey_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	case_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_case.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	contact_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	survey_type = Column(
		String(10),
		nullable=False,
		comment="CSAT|NPS|CES",
	)
	score = Column(Integer, nullable=False, comment="CSAT: 1-5, NPS: 0-10, CES: 1-7")
	comment = Column(Text, nullable=True)
	submitted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# No updated_at — append-only
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	case: Case = relationship("Case", back_populates="survey_responses", lazy="select")

	def __repr__(self) -> str:
		return f"<SurveyResponse case={self.case_id!r} type={self.survey_type!r} score={self.score}>"


# ---------------------------------------------------------------------------
# CaseFeedback
# ---------------------------------------------------------------------------

class CaseFeedback(Model):
	"""Post-resolution customer feedback on a specific case.

	Append-only — never update submitted feedback.
	rating: 1 (very dissatisfied) → 5 (very satisfied).
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_case_feedback"
	__table_args__ = (
		Index("ix_sc_cf_case", "case_id"),
		Index("ix_sc_cf_tenant", "tenant_id"),
		Index("ix_sc_cf_submitted", "submitted_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	case_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_case.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	rating = Column(
		Integer,
		nullable=False,
		comment="1=very dissatisfied … 5=very satisfied",
	)
	comments = Column(Text, nullable=True)
	submitted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	is_resolved_as_expected = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
	)

	# No updated_at — append-only
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	case: Case = relationship("Case", lazy="select", foreign_keys=[case_id])

	def __repr__(self) -> str:
		return f"<CaseFeedback case={self.case_id!r} rating={self.rating}>"


# ---------------------------------------------------------------------------
# CaseEscalation
# ---------------------------------------------------------------------------

class CaseEscalation(Model):
	"""Audit record for each escalation event on a case.

	Immutable once created — corrections are new rows.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_case_escalation"
	__table_args__ = (
		Index("ix_sc_ce_case", "case_id"),
		Index("ix_sc_ce_tenant", "tenant_id"),
		Index("ix_sc_ce_escalated_to", "escalated_to"),
		Index("ix_sc_ce_escalated_at", "escalated_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	case_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_case.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	escalated_to = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK Employee.id — escalation target",
	)
	escalated_by = Column(
		UUID(as_uuid=False),
		nullable=False,
		comment="FK Employee.id — who triggered the escalation",
	)
	reason = Column(Text, nullable=False)
	escalated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	resolved_at = Column(DateTime(timezone=True), nullable=True)

	# No updated_at — append-only audit record
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	case: Case = relationship("Case", lazy="select", foreign_keys=[case_id])

	def __repr__(self) -> str:
		return (
			f"<CaseEscalation case={self.case_id!r} "
			f"escalated_to={self.escalated_to!r} at={self.escalated_at!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SLAPolicy",
	"Case",
	"KnowledgeArticle",
	"CaseComment",
	"SurveyResponse",
	"CaseFeedback",
	"CaseEscalation",
]
