"""
pgappforge/plugins/erp/platform/row_security/models.py

Row-Level Security models.

Design invariants:
  - All PKs:        UUID(as_uuid=False) via gen_random_uuid()
  - All timestamps: DateTime(timezone=True)
  - tenant_id:      UUID NOT NULL on every model
  - Table prefix:   rls_
  - JSONB:          allowed_values list, computed_scope dict
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	DateTime,
	Index,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


__all__ = [
	"RowSecurityPolicy",
	"SecurityContext",
]


# ---------------------------------------------------------------------------
# RowSecurityPolicy
# ---------------------------------------------------------------------------

class RowSecurityPolicy(AuditMixin, Model):
	"""Defines which field values a FAB role may see for a given entity type.

	entity_type: EMPLOYEE | GL_ACCOUNT | PROJECT | GRANT | INVOICE | ANY
	scope_field: entity_id | department_id | cost_center_code | fund_code
	allowed_values: JSONB list of allowed values e.g. ["HR", "FINANCE"]
	role_id: FAB role name (VARCHAR soft FK — roles live in FAB security tables)
	"""

	__allow_unmapped__ = True
	__tablename__ = "rls_policy"
	__table_args__ = (
		Index("ix_rls_policy_tenant_role", "tenant_id", "role_id"),
		Index("ix_rls_policy_tenant_entity_type", "tenant_id", "entity_type"),
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
	entity_type = Column(
		String(50),
		nullable=False,
		comment="EMPLOYEE|GL_ACCOUNT|PROJECT|GRANT|INVOICE|ANY",
	)
	scope_field = Column(
		String(100),
		nullable=False,
		comment="entity_id|department_id|cost_center_code|fund_code",
	)
	allowed_values = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="List of allowed scope values for this role+entity_type combination",
	)
	role_id = Column(
		String(50),
		nullable=False,
		comment="FAB role name — soft FK to ab_role.name",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	description = Column(Text, nullable=True)
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
			f"<RowSecurityPolicy {self.name!r} entity={self.entity_type!r} "
			f"role={self.role_id!r} active={self.is_active}>"
		)


# ---------------------------------------------------------------------------
# SecurityContext
# ---------------------------------------------------------------------------

class SecurityContext(Model):
	"""Cached per-user computed scope — invalidated on policy changes.

	computed_scope: {entity_type: {scope_field: [allowed_values]}}
	e.g. {"EMPLOYEE": {"department_id": ["HR", "FINANCE"]}}

	Expires when expires_at is set and now() > expires_at.
	Invalidated by RowSecurityService.define_policy() via bulk delete.
	"""

	__allow_unmapped__ = True
	__tablename__ = "rls_context"
	__table_args__ = (
		UniqueConstraint("tenant_id", "user_id", name="uq_rls_context_tenant_user"),
		Index("ix_rls_context_tenant_user", "tenant_id", "user_id"),
		Index("ix_rls_context_user_id", "user_id"),
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
		String(50),
		nullable=False,
		comment="FAB user id (string) — unique per tenant via UQ above",
	)
	computed_scope = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="{entity_type: {scope_field: [allowed_values]}}",
	)
	computed_at = Column(DateTime(timezone=True), nullable=False)
	expires_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL = never expires; set for time-limited contexts",
	)

	def __repr__(self) -> str:
		return (
			f"<SecurityContext user={self.user_id!r} tenant={self.tenant_id!r} "
			f"computed_at={self.computed_at!r}>"
		)
