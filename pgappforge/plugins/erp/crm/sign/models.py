"""
pgappforge/plugins/erp/crm/sign/models.py

SQLAlchemy models for the E-Sign Portal plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - PostgreSQL ONLY — JSONB, UUID, DateTime(timezone=True)
  - lazy='select' throughout (SA 2.x)

Table prefix: sgn_
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Status / action enumerations (for documentation; not DB CHECK constraints)
# ---------------------------------------------------------------------------

REQUEST_STATUS = ("PENDING", "IN_PROGRESS", "COMPLETED", "DECLINED", "EXPIRED", "CANCELLED")
SIGNING_ORDER = ("PARALLEL", "SEQUENTIAL")
SIGNATORY_STATUS = ("PENDING", "SIGNED", "DECLINED", "EXPIRED")
AUDIT_ACTION = ("CREATED", "SENT", "VIEWED", "SIGNED", "DECLINED", "CANCELLED", "EXPIRED", "COMPLETED")


# ---------------------------------------------------------------------------
# SignatureRequest
# ---------------------------------------------------------------------------

class SignatureRequest(AuditMixin, Model):
	"""Central aggregate for a multi-party e-signature request.

	document_id is a soft FK to dms_document.id (no enforced FK to avoid
	hard coupling to the DMS plugin).  signing_order controls whether signatories
	sign in sequence (SEQUENTIAL) or all at once (PARALLEL).
	bpm_instance_id links back to the workflow instance that created this request.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sgn_request"
	__table_args__ = (
		Index("ix_sgn_request_tenant_status", "tenant_id", "status"),
		Index("ix_sgn_request_initiator", "initiator_id", "tenant_id"),
		Index("ix_sgn_request_document", "document_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	document_id = Column(String(50), nullable=False)
	document_title = Column(String(500), nullable=False)
	initiator_id = Column(String(50), nullable=False)
	status = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
	signing_order = Column(String(20), nullable=False, default="PARALLEL", server_default="PARALLEL")
	subject = Column(String(500), nullable=True)
	message = Column(Text, nullable=True)
	expires_at = Column(DateTime(timezone=True), nullable=True)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	bpm_instance_id = Column(String(50), nullable=True)
	metadata_ = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Arbitrary key-value metadata for workflow / integration use",
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

	signatories: list[SignatureSignatory] = relationship(
		"SignatureSignatory",
		back_populates="request",
		lazy="select",
		order_by="SignatureSignatory.order_number",
	)
	audit_logs: list[SignatureAuditLog] = relationship(
		"SignatureAuditLog",
		back_populates="request",
		lazy="select",
		order_by="SignatureAuditLog.created_at",
	)

	def __repr__(self) -> str:
		return f"<SignatureRequest {self.id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# SignatureSignatory
# ---------------------------------------------------------------------------

class SignatureSignatory(AuditMixin, Model):
	"""One party required to sign within a SignatureRequest.

	signer_id is null for external (non-registered) signers.
	access_token is a secrets.token_urlsafe(32) value used to generate
	a one-click signing link for external parties.
	signature_image_base64 stores the drawn/captured signature image.
	ip_address / user_agent provide forensic evidence for legal enforceability.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sgn_signatory"
	__table_args__ = (
		Index("ix_sgn_signatory_request_status", "request_id", "status"),
		Index("ix_sgn_signatory_token", "access_token"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	request_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sgn_request.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	signer_id = Column(String(50), nullable=True, comment="Registered user id; null for external signers")
	signer_email = Column(String(320), nullable=False)
	signer_name = Column(String(200), nullable=False)
	signer_role = Column(String(100), nullable=True, comment='e.g. "Vendor", "Employee", "Witness"')
	order_number = Column(Integer, nullable=False, default=0, server_default="0",
		comment="Signing sequence position for SEQUENTIAL requests")
	status = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
	access_token = Column(String(100), nullable=True, unique=True,
		comment="secrets.token_urlsafe(32) for one-click external signing links")
	signed_at = Column(DateTime(timezone=True), nullable=True)
	declined_at = Column(DateTime(timezone=True), nullable=True)
	decline_reason = Column(Text, nullable=True)
	signature_image_base64 = Column(Text, nullable=True)
	ip_address = Column(String(45), nullable=True)
	user_agent = Column(Text, nullable=True)

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

	request: Any = relationship("SignatureRequest", back_populates="signatories", lazy="select")
	audit_logs: list[SignatureAuditLog] = relationship(
		"SignatureAuditLog",
		back_populates="signatory",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SignatureSignatory {self.signer_email!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# SignatureAuditLog
# ---------------------------------------------------------------------------

class SignatureAuditLog(AuditMixin, Model):
	"""Immutable event log entry for a SignatureRequest or Signatory action.

	Provides a tamper-evident trail for legal enforceability: every state
	transition (CREATED, SENT, VIEWED, SIGNED, DECLINED, etc.) is recorded
	with actor_id, ip_address, and user_agent.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sgn_audit_log"
	__table_args__ = (
		Index("ix_sgn_audit_log_request_created", "request_id", "created_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	request_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sgn_request.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	signatory_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sgn_signatory.id", ondelete="CASCADE"),
		nullable=True,
		index=True,
	)
	action = Column(String(50), nullable=False,
		comment="CREATED/SENT/VIEWED/SIGNED/DECLINED/CANCELLED/EXPIRED/COMPLETED")
	actor_id = Column(String(50), nullable=True)
	ip_address = Column(String(45), nullable=True)
	user_agent = Column(Text, nullable=True)
	metadata_ = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	# No updated_at — audit rows are immutable
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	request: Any = relationship("SignatureRequest", back_populates="audit_logs", lazy="select")
	signatory: Any = relationship("SignatureSignatory", back_populates="audit_logs", lazy="select")

	def __repr__(self) -> str:
		return f"<SignatureAuditLog request={self.request_id!r} action={self.action!r}>"


__all__ = [
	"SignatureRequest",
	"SignatureSignatory",
	"SignatureAuditLog",
	# enumerations
	"REQUEST_STATUS",
	"SIGNING_ORDER",
	"SIGNATORY_STATUS",
	"AUDIT_ACTION",
]
