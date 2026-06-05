"""
pgappforge/plugins/erp/platform/credentials/models.py

Digital Credentials (W3C Verifiable Credentials + Open Badges 3.0) models.

Entities:
  CredentialSchema     — badge/certificate definition template
  IssuedCredential     — single issued credential instance (IMMUTABLE after issue)
  CredentialShare      — share record per platform/recipient
  CredentialVerification — verification attempt log

Design notes:
  - All PKs: UUID v4 strings
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - IssuedCredential is effectively immutable after creation; revocation
    sets status=REVOKED and records revoked_at + revocation_reason rather
    than deleting the row.
  - vc_jwt stores the signed W3C VC JWT for external verification.
  - share_token is CHAR(64) — 64-char hex from secrets.token_hex(32).
  - evidence and alignment stored as JSONB for schema flexibility.
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
	String,
	Text,
	UniqueConstraint,
	Integer,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# CredentialSchema
# ---------------------------------------------------------------------------

class CredentialSchema(AuditMixin, Model):
	"""Badge / certificate definition template.

	Defines what a credential represents, who issues it, and how recipients
	earn it.  Multiple IssuedCredential rows reference one schema.

	evidence_schema: JSON Schema fragment describing valid evidence structure.
	alignment: JSONB array of alignment objects (O*NET, CASE, IMS CTDL).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_credential_schema"
	__table_args__ = (
		UniqueConstraint("schema_id", name="uq_erp_cred_schema_schema_id"),
		Index("ix_erp_cred_schema_issuer", "issuer_id"),
		Index("ix_erp_cred_schema_tenant", "tenant_id"),
		Index("ix_erp_cred_schema_type", "credential_type"),
		Index("ix_erp_cred_schema_published", "is_published"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	schema_id = Column(
		String(200),
		nullable=False,
		unique=True,
		comment="Globally unique schema IRI or slug",
	)
	name = Column(String(255), nullable=False)
	version = Column(String(20), nullable=False, default="1.0")
	credential_type = Column(
		String(12),
		nullable=False,
		comment="CERTIFICATE | BADGE | LICENSE | DEGREE | MEMBERSHIP | AWARD",
	)
	issuer_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		comment="FK to foundation Party (issuing organisation)",
	)
	description = Column(Text, nullable=True)
	criteria_narrative = Column(
		Text, nullable=True,
		comment="Plain-text or HTML description of earning criteria",
	)
	evidence_schema: dict[str, Any] = Column(
		JSONB, nullable=True,
		comment="JSON Schema fragment for valid evidence structure",
	)

	# Visual identity
	image_url = Column(Text, nullable=True, comment="Badge/certificate visual image")
	background_image_url = Column(Text, nullable=True)

	# Standards alignment
	alignment: list[dict] = Column(
		JSONB, nullable=True, default=list,
		comment="Array of {targetName, targetUrl, targetFramework} objects",
	)
	tags = Column(
		ARRAY(Text), nullable=True, default=list,
		comment="Discovery tags e.g. ARRAY['python','data-science']",
	)
	is_published = Column(Boolean, nullable=False, default=True)

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

	issued_credentials = relationship("IssuedCredential", backref="schema")

	def __repr__(self) -> str:
		return (
			f"<CredentialSchema {self.id!r} name={self.name!r}"
			f" type={self.credential_type!r} v{self.version}>"
		)


# ---------------------------------------------------------------------------
# IssuedCredential
# ---------------------------------------------------------------------------

class IssuedCredential(Model):
	"""Single awarded credential instance.  IMMUTABLE after issue.

	Revocation: set status=REVOKED, revoked_at=now(), revocation_reason.
	Do NOT delete or UPDATE other fields post-issuance.

	credential_number: human-readable unique identifier (e.g. CERT-2026-00001).
	verification_url: publicly accessible URL for external verification.
	qr_code_url: URL of pre-rendered QR code image.
	vc_jwt: signed W3C VC JWT string for cryptographic verification.
	achievement_id: Open Badges 3.0 Achievement IRI.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_issued_credential"
	__table_args__ = (
		UniqueConstraint("credential_number", name="uq_erp_issued_cred_number"),
		UniqueConstraint("verification_url", name="uq_erp_issued_cred_verif_url"),
		Index("ix_erp_issued_cred_schema", "schema_id"),
		Index("ix_erp_issued_cred_recipient", "recipient_id"),
		Index("ix_erp_issued_cred_tenant", "tenant_id"),
		Index("ix_erp_issued_cred_status", "status"),
		Index("ix_erp_issued_cred_expires", "expires_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	credential_number = Column(
		String(100), nullable=False, unique=True,
		comment="Human-readable unique credential reference e.g. CERT-2026-00001",
	)
	schema_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_credential_schema.id", ondelete="RESTRICT"),
		nullable=False,
	)
	recipient_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		comment="FK to foundation Party (recipient)",
	)
	recipient_email = Column(String(255), nullable=False)

	issued_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	expires_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL = no expiry",
	)

	evidence: dict[str, Any] = Column(
		JSONB, nullable=True, default=dict,
		comment="Evidence payload conforming to schema.evidence_schema",
	)
	narrative = Column(Text, nullable=True, comment="Personalised earning narrative")
	achievement_id = Column(
		String(200), nullable=True,
		comment="Open Badges 3.0 Achievement IRI",
	)
	verification_url = Column(
		Text, nullable=False, unique=True,
		comment="Public URL for verification portal",
	)
	qr_code_url = Column(Text, nullable=True)
	vc_jwt = Column(Text, nullable=True, comment="Signed W3C VC JWT")

	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | REVOKED | EXPIRED",
	)
	revoked_at = Column(DateTime(timezone=True), nullable=True)
	revocation_reason = Column(Text, nullable=True)

	shares = relationship("CredentialShare", backref="credential")
	verifications = relationship("CredentialVerification", backref="credential")

	def __repr__(self) -> str:
		return (
			f"<IssuedCredential {self.credential_number!r}"
			f" status={self.status!r} recipient={self.recipient_id!r}>"
		)


# ---------------------------------------------------------------------------
# CredentialShare
# ---------------------------------------------------------------------------

class CredentialShare(Model):
	"""Share record tracking how a credential was shared externally.

	share_token: 64-char opaque hex token for the share link.
	platform: LINKEDIN | EMAIL | URL | API.
	view_count: incremented each time the share link is accessed.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_credential_share"
	__table_args__ = (
		UniqueConstraint("share_token", name="uq_erp_cred_share_token"),
		Index("ix_erp_cred_share_credential", "credential_id"),
		Index("ix_erp_cred_share_tenant", "tenant_id"),
		Index("ix_erp_cred_share_platform", "platform"),
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
		ForeignKey("erp_issued_credential.id", ondelete="CASCADE"),
		nullable=False,
	)
	shared_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	share_token = Column(
		String(64), nullable=False, unique=True,
		comment="64-char hex token for the share link",
	)
	platform = Column(
		String(10), nullable=False,
		comment="LINKEDIN | EMAIL | URL | API",
	)
	recipient_email = Column(String(255), nullable=True)
	view_count = Column(Integer, nullable=False, default=0)
	expires_at = Column(DateTime(timezone=True), nullable=True)

	def __repr__(self) -> str:
		return (
			f"<CredentialShare {self.id!r} platform={self.platform!r}"
			f" credential={self.credential_id!r} views={self.view_count}>"
		)


# ---------------------------------------------------------------------------
# CredentialVerification
# ---------------------------------------------------------------------------

class CredentialVerification(Model):
	"""Log of each verification attempt against a credential.

	result: VALID | INVALID | EXPIRED | REVOKED | NOT_FOUND.
	verification_details: JSON object with signature check results, chain info.
	credential_id may be NULL when verification_token does not resolve to a
	known credential (result=NOT_FOUND).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_credential_verification"
	__table_args__ = (
		Index("ix_erp_cred_verif_credential", "credential_id"),
		Index("ix_erp_cred_verif_token", "verification_token"),
		Index("ix_erp_cred_verif_tenant", "tenant_id"),
		Index("ix_erp_cred_verif_result", "result"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=True, index=True)

	credential_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_issued_credential.id", ondelete="SET NULL"),
		nullable=True,
	)
	verification_token = Column(
		String(100), nullable=False,
		comment="Token or URL fragment presented by the verifier",
	)
	verified_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	verifier_id = Column(
		UUID(as_uuid=False), nullable=True,
		comment="FK to foundation Party if verifier is a known party",
	)
	verifier_email = Column(String(255), nullable=True)
	result = Column(
		String(10), nullable=False,
		comment="VALID | INVALID | EXPIRED | REVOKED | NOT_FOUND",
	)
	verification_details: dict[str, Any] = Column(
		JSONB, nullable=True, default=dict,
		comment="Signature check results, chain info, timestamp proofs",
	)

	def __repr__(self) -> str:
		return (
			f"<CredentialVerification {self.id!r}"
			f" result={self.result!r} token={self.verification_token!r}>"
		)


__all__ = [
	"CredentialSchema",
	"IssuedCredential",
	"CredentialShare",
	"CredentialVerification",
]
