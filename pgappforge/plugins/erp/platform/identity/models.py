"""
pgappforge/plugins/erp/platform/identity/models.py

Identity & Access Management models.

Entities:
  IdentityProvider — SSO/auth provider config (SAML/OIDC/LDAP/LOCAL)
  UserSession      — active session with MFA state, IP, expiry
  MFADevice        — per-user MFA device registration (TOTP/SMS/EMAIL/WEBAUTHN)
  AccessPolicy     — fine-grained ALLOW/DENY policy rows

Design:
  - secret_encrypted is the encrypted TOTP seed / WebAuthn credential blob.
    Encryption is the caller's responsibility (use app-level KMS wrapper).
  - INET stored as String(45) — PostgreSQL INET type via server_default;
    Python layer stores as string, DB validates.
  - All PKs: UUID v4
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# IdentityProvider
# ---------------------------------------------------------------------------

class IdentityProvider(AuditMixin, Model):
	"""External or local authentication provider configuration.

	config JSONB stores provider-specific settings:
	  SAML  — entity_id, sso_url, x509_cert, attribute_mappings
	  OIDC  — client_id, client_secret_encrypted, discovery_url, scopes
	  LDAP  — host, port, bind_dn, base_dn, user_filter, tls
	  LOCAL — password_policy hash_algo rounds complexity_rules
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_identity_provider"
	__table_args__ = (
		Index("ix_erp_idp_tenant", "tenant_id"),
		Index("ix_erp_idp_default", "tenant_id", "is_default"),
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
	provider_type = Column(
		String(10),
		nullable=False,
		comment="SAML | OIDC | LDAP | LOCAL",
	)
	config: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Provider-specific configuration blob",
	)
	is_default = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="At most one default per tenant",
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

	def __repr__(self) -> str:
		return (
			f"<IdentityProvider {self.id!r} name={self.name!r}"
			f" type={self.provider_type!r} default={self.is_default}>"
		)


# ---------------------------------------------------------------------------
# UserSession
# ---------------------------------------------------------------------------

class UserSession(Model):
	"""Active user session with MFA verification state.

	session_token is a 64-char hex token stored hashed in production
	(the model stores the value; hashing is the auth layer's responsibility).

	ip_address: stored as String(45) to accommodate IPv6.
	expires_at: hard expiry; last_activity_at is used for sliding expiry.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_user_session"
	__table_args__ = (
		UniqueConstraint("session_token", name="uq_erp_usersession_token"),
		Index("ix_erp_usersession_user", "user_id"),
		Index("ix_erp_usersession_tenant", "tenant_id"),
		Index("ix_erp_usersession_expires", "expires_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	user_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="CASCADE"),
		nullable=False,
	)
	session_token = Column(
		String(64),
		nullable=False,
		unique=True,
		comment="64-char opaque token; store hashed in production",
	)
	ip_address = Column(
		String(45),
		nullable=True,
		comment="IPv4 or IPv6 address string",
	)
	user_agent = Column(Text, nullable=True)
	started_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	last_activity_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	expires_at = Column(
		DateTime(timezone=True),
		nullable=False,
		comment="Hard expiry; token rejected after this timestamp",
	)
	mfa_verified = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True once a valid MFA challenge has been passed this session",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	def __repr__(self) -> str:
		return (
			f"<UserSession {self.id!r} user={self.user_id}"
			f" mfa={self.mfa_verified} expires={self.expires_at!r}>"
		)


# ---------------------------------------------------------------------------
# MFADevice
# ---------------------------------------------------------------------------

class MFADevice(AuditMixin, Model):
	"""User-registered MFA device.

	secret_encrypted: KMS-encrypted seed (TOTP) or credential blob (WebAuthn).
	is_primary: only one device per user may be primary; enforced in service layer.
	verified_at: NULL until the user completes a verification challenge.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_mfa_device"
	__table_args__ = (
		Index("ix_erp_mfadev_user", "user_id"),
		Index("ix_erp_mfadev_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	user_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="CASCADE"),
		nullable=False,
	)
	device_type = Column(
		String(10),
		nullable=False,
		comment="TOTP | SMS | EMAIL | WEBAUTHN",
	)
	device_name = Column(
		String(200),
		nullable=False,
		comment="User-visible label e.g. 'Google Authenticator'",
	)
	secret_encrypted = Column(
		Text,
		nullable=False,
		comment="KMS-encrypted TOTP seed or WebAuthn credential blob",
	)
	is_primary = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="Exactly one PRIMARY device per user; service-layer enforced",
	)
	verified_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL until user completes first verification challenge",
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
			f"<MFADevice {self.id!r} user={self.user_id}"
			f" type={self.device_type!r} primary={self.is_primary}>"
		)


# ---------------------------------------------------------------------------
# AccessPolicy
# ---------------------------------------------------------------------------

class AccessPolicy(AuditMixin, Model):
	"""Fine-grained access control policy row.

	Maps a principal (user, role, or group) to a resource with an ALLOW/DENY
	effect and optional condition JSONB (JSONLogic expression).

	Evaluation: DENY overrides ALLOW (explicit deny wins).
	resource_id=NULL means the policy applies to all instances of resource_type.

	permissions: PostgreSQL TEXT[] of action strings e.g. ['read', 'write'].
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_access_policy"
	__table_args__ = (
		Index("ix_erp_acpol_principal", "principal_type", "principal_id"),
		Index("ix_erp_acpol_resource", "resource_type", "resource_id"),
		Index("ix_erp_acpol_tenant", "tenant_id"),
		Index("ix_erp_acpol_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	policy_name = Column(String(300), nullable=False, unique=True)

	# Resource
	resource_type = Column(
		String(200),
		nullable=False,
		comment="Model class name or '*' for all",
	)
	resource_id = Column(
		String(64),
		nullable=True,
		comment="NULL = applies to all instances of resource_type",
	)

	# Principal
	principal_type = Column(
		String(10),
		nullable=False,
		comment="USER | ROLE | GROUP",
	)
	principal_id = Column(
		String(64),
		nullable=False,
		comment="User ID, role name, or group name",
	)

	# Permissions and effect
	permissions = Column(
		ARRAY(String),
		nullable=False,
		default=list,
		comment="Array of action strings e.g. ARRAY['read','write']",
	)
	conditions: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="JSONLogic condition expression; {} = always applies",
	)
	effect = Column(
		String(5),
		nullable=False,
		default="ALLOW",
		comment="ALLOW | DENY",
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

	def __repr__(self) -> str:
		return (
			f"<AccessPolicy {self.policy_name!r}"
			f" {self.principal_type}/{self.principal_id}"
			f" → {self.effect} {self.permissions}>"
		)


__all__ = [
	"IdentityProvider",
	"UserSession",
	"MFADevice",
	"AccessPolicy",
]
