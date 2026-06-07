"""
pgappforge/plugins/erp/grc/sod/models.py

SoD Analyzer models.

Tables:
  sod_conflict   — catalogue of function-pair conflicts (seed via service)
  sod_violation  — per-user detected violations with lifecycle status
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
# SodConflict
# ---------------------------------------------------------------------------

class SodConflict(AuditMixin, Model):
	"""Catalogue entry for a pair of functions that must not be held by one user.

	function_a / function_b are human-readable capability names that are matched
	against FAB role names via prefix matching in SodAnalyzerService.
	name must be unique per tenant (e.g. "P2P-02").
	"""

	__allow_unmapped__ = True
	__tablename__ = "sod_conflict"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_sod_conflict_tenant_name"),
		Index("ix_sod_conflict_risk_active", "tenant_id", "risk_level", "is_active"),
		Index("ix_sod_conflict_category", "tenant_id", "control_category"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(String(200), nullable=False, comment="e.g. P2P-02")
	function_a = Column(String(200), nullable=False, comment="e.g. Create Purchase Order")
	function_b = Column(String(200), nullable=False, comment="e.g. Approve Purchase Order")
	risk_level = Column(
		String(20),
		nullable=False,
		comment="CRITICAL | HIGH | MEDIUM | LOW",
	)
	description = Column(Text, nullable=False)
	control_category = Column(
		String(50),
		nullable=True,
		comment="PROCURE_TO_PAY | RECORD_TO_REPORT | ORDER_TO_CASH | PAYROLL | ACCESS",
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

	violations: list[SodViolation] = relationship(
		"SodViolation",
		back_populates="conflict",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<SodConflict {self.name!r} {self.function_a!r} ⟷ {self.function_b!r}"
			f" risk={self.risk_level!r}>"
		)


# ---------------------------------------------------------------------------
# SodViolation
# ---------------------------------------------------------------------------

class SodViolation(AuditMixin, Model):
	"""A detected instance of a user holding both sides of a SodConflict.

	risk_level is denormalised from SodConflict at detection time to allow
	efficient status/risk filtering without a join.

	role_ids: JSONB list of FAB role IDs that triggered the conflict.

	Status lifecycle:
	  OPEN → REMEDIATED  (roles removed)
	  OPEN → RISK_ACCEPTED  (accepted_by + mitigating_control set)
	  OPEN → ACCEPTED    (formal sign-off without a mitigating control)
	"""

	__allow_unmapped__ = True
	__tablename__ = "sod_violation"
	__table_args__ = (
		Index("ix_sod_violation_user_status", "tenant_id", "user_id", "status"),
		Index("ix_sod_violation_status_risk", "tenant_id", "status", "risk_level"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	user_id = Column(String(50), nullable=False)
	conflict_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sod_conflict.id", ondelete="CASCADE"),
		nullable=False,
	)
	# Denormalised from sod_conflict for efficient status+risk queries
	risk_level = Column(String(20), nullable=False)
	role_ids: list[Any] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="FAB role IDs causing the conflict",
	)
	detected_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)
	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN | REMEDIATED | ACCEPTED | RISK_ACCEPTED",
	)
	accepted_by = Column(String(50), nullable=True)
	accepted_at = Column(DateTime(timezone=True), nullable=True)
	mitigating_control = Column(Text, nullable=True)
	remediation_date = Column(Date, nullable=True)

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

	conflict: SodConflict = relationship(
		"SodConflict",
		back_populates="violations",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<SodViolation user={self.user_id!r} conflict={self.conflict_id!r}"
			f" status={self.status!r} risk={self.risk_level!r}>"
		)


__all__ = ["SodConflict", "SodViolation"]
