"""
pgappforge/plugins/erp/platform/education_platform/models.py

Education Platform models — LMS/tools integration, learning objects, paths,
learner activity tracking, and verifiable credentials.

NOT the Education industry plugin (student records) — this covers the
LMS/eLearning infrastructure layer (LTI 1.3, xAPI, SCORM, AICC).

Entities:
  LMSTool              — registered external learning tool (LTI 1.3/SCORM/xAPI/AICC)
  LearningObject       — single addressable piece of content
  LearningPath         — ordered sequence of LearningObjects toward a role/goal
  PathItem             — join table: path → learning object with sequence + prereqs
  LearnerActivity      — immutable xAPI-style event log per learner × LO
  VerifiableCredential — credential definition (certificate/badge/degree/license)
  EduIssuedCredential     — immutable issuance record for one recipient

Design:
  - All PKs: UUID v4
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id on all mutable entities
  - Monetary amounts: N/A for this domain
  - JSONB for competencies, configuration, evidence, xapi_statements
  - ImmutableRecordMixin on LearnerActivity and EduIssuedCredential
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
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# LMSTool
# ---------------------------------------------------------------------------

class LMSTool(AuditMixin, Model):
	"""Registered external learning tool — LTI 1.3, SCORM, xAPI, or AICC.

	Stores all credentials and endpoint URLs required to launch the tool.
	configuration JSONB carries tool-specific settings (e.g. deep_link_url,
	custom_params, grade_passback settings).
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_lms_tool"
	__table_args__ = (
		Index("ix_edu_lms_tool_tenant", "tenant_id"),
		Index("ix_edu_lms_tool_type", "tool_type"),
		Index("ix_edu_lms_tool_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	tool_name = Column(String(255), nullable=False)
	tool_type = Column(
		String(20),
		nullable=False,
		comment="LTI_1P3 | SCORM | XAPI | AICC",
	)
	launch_url = Column(Text, nullable=False)
	client_id = Column(String(200), nullable=True, comment="OAuth2 client_id for LTI 1.3")
	deployment_id = Column(String(200), nullable=True, comment="IMS deployment_id")
	jwks_url = Column(Text, nullable=True, comment="Platform JWKS URL for LTI 1.3 key verification")
	auth_login_url = Column(Text, nullable=True, comment="OIDC login initiation URL")
	auth_token_url = Column(Text, nullable=True, comment="OAuth2 token endpoint")
	is_active = Column(Boolean, nullable=False, default=True)
	configuration: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Tool-specific config: deep_link_url, custom_params, grade_passback, etc.",
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

	learning_objects: list[LearningObject] = relationship(
		"LearningObject",
		back_populates="tool",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<LMSTool {self.tool_name!r} type={self.tool_type!r}>"


# ---------------------------------------------------------------------------
# LearningObject
# ---------------------------------------------------------------------------

class LearningObject(AuditMixin, Model):
	"""A single addressable piece of learning content.

	lo_id is a stable external identifier (e.g. course ISBN, SCORM package ID,
	xAPI activity IRI).  tool_id is nullable — standalone content has no tool.
	competencies JSONB is a list of competency objects:
	  [{"id": "...", "name": "...", "level": "INTERMEDIATE"}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_learning_object"
	__table_args__ = (
		UniqueConstraint("tenant_id", "lo_id", name="uq_edu_lo_tenant_lo_id"),
		Index("ix_edu_lo_tenant", "tenant_id"),
		Index("ix_edu_lo_type", "lo_type"),
		Index("ix_edu_lo_published", "is_published"),
		Index("ix_edu_lo_tool", "tool_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	lo_id = Column(String(200), nullable=False, comment="Stable external identifier / activity IRI")
	title = Column(String(500), nullable=False)
	description = Column(Text, nullable=True)
	lo_type = Column(
		String(20),
		nullable=False,
		comment="MODULE | QUIZ | ASSIGNMENT | VIDEO | READING | SIMULATION",
	)
	tool_id = Column(
		UUID(as_uuid=False),
		ForeignKey("edu_lms_tool.id", ondelete="SET NULL"),
		nullable=True,
	)
	external_id = Column(
		String(200),
		nullable=True,
		comment="Tool-specific resource identifier (e.g. SCORM package ID)",
	)
	estimated_duration_minutes = Column(Integer, nullable=True)
	competencies: list[dict] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="List of competency objects: [{id, name, level}]",
	)
	difficulty = Column(
		String(20),
		nullable=False,
		default="INTERMEDIATE",
		comment="BEGINNER | INTERMEDIATE | ADVANCED",
	)
	is_published = Column(Boolean, nullable=False, default=False)

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

	tool: LMSTool | None = relationship(
		"LMSTool",
		back_populates="learning_objects",
		lazy="select",
	)
	path_items: list[PathItem] = relationship(
		"PathItem",
		back_populates="learning_object",
		lazy="select",
	)
	activities: list[LearnerActivity] = relationship(
		"LearnerActivity",
		back_populates="learning_object",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<LearningObject {self.lo_id!r} {self.title!r} type={self.lo_type!r}>"


# ---------------------------------------------------------------------------
# VerifiableCredential  (defined before LearningPath for FK resolution)
# ---------------------------------------------------------------------------

class VerifiableCredential(AuditMixin, Model):
	"""Credential definition — what can be awarded and under what criteria.

	evidence_schema JSONB describes required evidence fields (JSON Schema subset).
	valid_duration_days NULL means the credential never expires.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_verifiable_credential"
	__table_args__ = (
		Index("ix_edu_vc_tenant", "tenant_id"),
		Index("ix_edu_vc_type", "credential_type"),
		Index("ix_edu_vc_active", "is_active"),
		Index("ix_edu_vc_issuer", "issuer_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	credential_type = Column(
		String(20),
		nullable=False,
		comment="CERTIFICATE | BADGE | DEGREE | LICENSE",
	)
	name = Column(String(500), nullable=False)
	description = Column(Text, nullable=True)
	issuer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Party (organisation) that issues this credential",
	)
	criteria = Column(
		Text,
		nullable=False,
		comment="Human-readable criteria for earning this credential",
	)
	image_url = Column(Text, nullable=True, comment="Badge/certificate image URL")
	evidence_schema: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="JSON Schema describing required evidence fields",
	)
	valid_duration_days = Column(
		Integer,
		nullable=True,
		comment="NULL = never expires",
	)
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

	issued_credentials: list[EduIssuedCredential] = relationship(
		"EduIssuedCredential",
		back_populates="credential",
		lazy="select",
	)
	learning_paths: list[LearningPath] = relationship(
		"LearningPath",
		back_populates="certification",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<VerifiableCredential {self.name!r} type={self.credential_type!r}>"


# ---------------------------------------------------------------------------
# LearningPath
# ---------------------------------------------------------------------------

class LearningPath(AuditMixin, Model):
	"""Ordered sequence of LearningObjects targeted at a role or outcome.

	is_mandatory: when True, assigned to a role and completion is tracked.
	certification_id: optional — completing the path triggers credential issuance.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_learning_path"
	__table_args__ = (
		Index("ix_edu_lp_tenant", "tenant_id"),
		Index("ix_edu_lp_mandatory", "is_mandatory"),
		Index("ix_edu_lp_cert", "certification_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(String(500), nullable=False)
	description = Column(Text, nullable=True)
	target_role = Column(String(100), nullable=True, comment="Job role this path prepares for")
	estimated_hours = Column(Numeric(5, 1), nullable=True)
	is_mandatory = Column(Boolean, nullable=False, default=False)
	certification_id = Column(
		UUID(as_uuid=False),
		ForeignKey("edu_verifiable_credential.id", ondelete="SET NULL"),
		nullable=True,
		comment="Credential issued on path completion",
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

	items: list[PathItem] = relationship(
		"PathItem",
		back_populates="path",
		cascade="all, delete-orphan",
		order_by="PathItem.sequence",
		lazy="select",
	)
	certification: VerifiableCredential | None = relationship(
		"VerifiableCredential",
		back_populates="learning_paths",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<LearningPath {self.name!r} mandatory={self.is_mandatory}>"


# ---------------------------------------------------------------------------
# PathItem
# ---------------------------------------------------------------------------

class PathItem(AuditMixin, Model):
	"""Join table: LearningPath → LearningObject with ordering and prerequisites.

	prerequisite_item_ids: UUID[] of PathItem.id values that must be completed
	before this item is unlocked.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_path_item"
	__table_args__ = (
		UniqueConstraint("path_id", "lo_id", name="uq_edu_path_item_path_lo"),
		Index("ix_edu_path_item_path", "path_id"),
		Index("ix_edu_path_item_lo", "lo_id"),
		Index("ix_edu_path_item_seq", "path_id", "sequence"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	path_id = Column(
		UUID(as_uuid=False),
		ForeignKey("edu_learning_path.id", ondelete="CASCADE"),
		nullable=False,
	)
	lo_id = Column(
		UUID(as_uuid=False),
		ForeignKey("edu_learning_object.id", ondelete="RESTRICT"),
		nullable=False,
	)
	sequence = Column(Integer, nullable=False, comment="1-based ordering within the path")
	is_required = Column(Boolean, nullable=False, default=True)
	prerequisite_item_ids: list[str] = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		server_default="{}",
		default=list,
		comment="PathItem.id UUIDs that must be completed first",
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

	path: LearningPath = relationship("LearningPath", back_populates="items", lazy="select")
	learning_object: LearningObject = relationship(
		"LearningObject",
		back_populates="path_items",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<PathItem path={self.path_id!r} lo={self.lo_id!r} seq={self.sequence}>"


# ---------------------------------------------------------------------------
# LearnerActivity  (IMMUTABLE — insert only)
# ---------------------------------------------------------------------------

class LearnerActivity(ImmutableRecordMixin, Model):
	"""Immutable xAPI-style event log: one row per learner × LO × attempt.

	progress_pct: 0.00–100.00, updated only by inserting a new activity row
	  for multi-attempt content (attempts counter increments).
	xapi_statements: raw xAPI statement objects for LRS interoperability.

	NEVER UPDATE rows — insert a new record for each state change.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_learner_activity"
	__table_args__ = (
		Index("ix_edu_la_learner", "learner_id"),
		Index("ix_edu_la_lo", "lo_id"),
		Index("ix_edu_la_tenant", "tenant_id"),
		Index("ix_edu_la_started", "started_at"),
		Index("ix_edu_la_learner_lo", "learner_id", "lo_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	learner_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
	)
	lo_id = Column(
		UUID(as_uuid=False),
		ForeignKey("edu_learning_object.id", ondelete="RESTRICT"),
		nullable=False,
	)
	started_at = Column(DateTime(timezone=True), nullable=False)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	progress_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=0,
		comment="0.00–100.00",
	)
	score = Column(Numeric(5, 2), nullable=True, comment="Raw score 0–100")
	passed = Column(Boolean, nullable=True)
	time_spent_seconds = Column(Integer, nullable=False, default=0)
	attempts = Column(Integer, nullable=False, default=1)
	xapi_statements: list[dict] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="Raw xAPI statement objects for LRS interoperability",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	learning_object: LearningObject = relationship(
		"LearningObject",
		back_populates="activities",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LearnerActivity learner={self.learner_id!r} lo={self.lo_id!r}"
			f" pct={self.progress_pct} passed={self.passed}>"
		)


# Register immutability guard after class definition
LearnerActivity._register_immutability()


# ---------------------------------------------------------------------------
# EduIssuedCredential  (IMMUTABLE — insert only)
# ---------------------------------------------------------------------------

class EduIssuedCredential(ImmutableRecordMixin, Model):
	"""Immutable credential issuance record.

	verification_url is globally unique — used as the credential's public
	verification endpoint.  Revocation is recorded by setting revoked_at
	via a NEW correction row (never updating existing rows).

	NEVER UPDATE rows.
	"""

	__allow_unmapped__ = True
	__tablename__ = "edu_issued_credential"
	__table_args__ = (
		UniqueConstraint("verification_url", name="uq_edu_ic_verification_url"),
		Index("ix_edu_ic_credential", "credential_id"),
		Index("ix_edu_ic_recipient", "recipient_id"),
		Index("ix_edu_ic_tenant", "tenant_id"),
		Index("ix_edu_ic_issued_at", "issued_at"),
		Index("ix_edu_ic_expires", "expires_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	credential_id = Column(
		UUID(as_uuid=False),
		ForeignKey("edu_verifiable_credential.id", ondelete="RESTRICT"),
		nullable=False,
	)
	recipient_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
	)
	issued_at = Column(DateTime(timezone=True), nullable=False)
	expires_at = Column(DateTime(timezone=True), nullable=True)
	evidence: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Evidence data matching the credential's evidence_schema",
	)
	verification_url = Column(
		Text,
		nullable=False,
		unique=True,
		comment="Public URL for verifying this credential",
	)
	revoked_at = Column(DateTime(timezone=True), nullable=True)
	revocation_reason = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	credential: VerifiableCredential = relationship(
		"VerifiableCredential",
		back_populates="issued_credentials",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<EduIssuedCredential credential={self.credential_id!r}"
			f" recipient={self.recipient_id!r} issued={self.issued_at!r}>"
		)


# Register immutability guard after class definition
EduIssuedCredential._register_immutability()


__all__ = [
	"LMSTool",
	"LearningObject",
	"LearningPath",
	"PathItem",
	"LearnerActivity",
	"VerifiableCredential",
	"EduIssuedCredential",
]
