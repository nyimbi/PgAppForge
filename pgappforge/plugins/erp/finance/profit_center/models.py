"""
pgappforge/plugins/erp/finance/profit_center/models.py

SQLAlchemy models for the Profit Center Accounting plugin.

Design invariants:
  - All PKs:         UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps:  DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - All models:      tenant_id UUID NOT NULL
  - All amounts:     Integer cents (BigInteger) — NEVER float or Numeric
  - Table prefix:    pc_
  - JSONB:           used for extensible/list attributes
  - Indexes:         composite indexes matching common query patterns
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
# ProfitCenter
# ---------------------------------------------------------------------------

class ProfitCenter(AuditMixin, Model):
	"""Profit center master — a segment of the business for P&L reporting.

	Supports self-referential hierarchy via parent_id for org-tree roll-ups.
	code is unique per tenant (enforced via UniqueConstraint).

	budget_annual_cents is the annual budget target used in variance reporting.
	metadata_ holds extensible attributes (tags, custom dimensions, etc.).
	"""

	__allow_unmapped__ = True
	__tablename__ = "pc_profit_center"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_pc_tenant_code"),
		Index("ix_pc_tenant_code", "tenant_id", "code"),
		Index("ix_pc_tenant_entity", "tenant_id", "entity_id"),
		Index("ix_pc_parent", "parent_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(50), nullable=False, comment="Unique profit center code per tenant")
	name = Column(String(200), nullable=False)
	parent_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pc_profit_center.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="Self-referential parent for hierarchy roll-ups",
	)
	manager_id = Column(
		String(50),
		nullable=True,
		comment="Employee ID of the profit center manager",
	)
	cost_center_code = Column(
		String(50),
		nullable=True,
		comment="Optional soft-link to GL cost center code",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	entity_id = Column(
		String(50),
		nullable=True,
		comment="Legal entity this profit center belongs to",
	)
	budget_annual_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Annual budget target in integer cents",
	)
	metadata_: dict[str, Any] = Column(
		"metadata_",
		JSONB,
		nullable=False,
		default=dict,
		comment="Extensible attributes: tags, custom dimensions, reporting groups",
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

	# Self-referential hierarchy
	parent: ProfitCenter = relationship(
		"ProfitCenter",
		remote_side="ProfitCenter.id",
		foreign_keys=[parent_id],
		lazy="select",
	)
	children: list[ProfitCenter] = relationship(
		"ProfitCenter",
		foreign_keys=[parent_id],
		back_populates="parent",
		lazy="select",
	)
	journals: list[ProfitCenterJournal] = relationship(
		"ProfitCenterJournal",
		back_populates="profit_center",
		cascade="all, delete-orphan",
		lazy="select",
	)
	allocation_rules: list[ProfitCenterAllocationRule] = relationship(
		"ProfitCenterAllocationRule",
		back_populates="source_profit_center",
		cascade="all, delete-orphan",
		lazy="select",
		foreign_keys="ProfitCenterAllocationRule.source_profit_center_id",
	)

	def __repr__(self) -> str:
		return f"<ProfitCenter {self.code!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# ProfitCenterJournal
# ---------------------------------------------------------------------------

class ProfitCenterJournal(AuditMixin, Model):
	"""A debit or credit posting to a profit center for a given GL account and period.

	Either debit_cents or credit_cents will be non-zero (never both zero, never both
	non-zero for the same economic side — validation is in the service layer).

	reference_id links back to the originating GL journal entry or source document.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pc_journal"
	__table_args__ = (
		Index("ix_pc_journal_pc_period", "profit_center_id", "period"),
		Index("ix_pc_journal_tenant_period_account", "tenant_id", "period", "gl_account"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	profit_center_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pc_profit_center.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	gl_account = Column(
		String(20),
		nullable=False,
		comment="GL account code e.g. 4000 (revenue) or 5100 (COGS)",
	)
	debit_cents = Column(BigInteger, nullable=False, default=0)
	credit_cents = Column(BigInteger, nullable=False, default=0)
	period = Column(
		String(20),
		nullable=False,
		comment="Accounting period e.g. 2025-01",
	)
	description = Column(Text, nullable=True)
	reference_id = Column(
		String(50),
		nullable=True,
		comment="GL journal entry ID or other source document reference",
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

	profit_center: ProfitCenter = relationship(
		"ProfitCenter",
		back_populates="journals",
		lazy="select",
	)

	def __repr__(self) -> str:
		side = f"DR {self.debit_cents}" if self.debit_cents else f"CR {self.credit_cents}"
		return (
			f"<ProfitCenterJournal pc={self.profit_center_id!r} "
			f"acct={self.gl_account!r} {side} period={self.period!r}>"
		)


# ---------------------------------------------------------------------------
# ProfitCenterAllocationRule
# ---------------------------------------------------------------------------

class ProfitCenterAllocationRule(AuditMixin, Model):
	"""Defines how costs from a source profit center are allocated to targets.

	allocation_method:
	  FIXED_PERCENTAGE — apply explicit percentages from targets list
	  HEADCOUNT        — allocate proportional to headcount of each target PC
	  REVENUE          — allocate proportional to revenue of each target PC

	targets JSONB:
	  [{"profit_center_id": str, "percentage": float}, ...]
	  Percentages must sum to 100 for FIXED_PERCENTAGE method.

	gl_accounts JSONB:
	  [] = allocate all GL accounts; otherwise restrict to listed account codes.
	"""

	__allow_unmapped__ = True
	__tablename__ = "pc_allocation_rule"
	__table_args__ = (
		Index("ix_pc_alloc_rule_source_active", "source_profit_center_id", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	source_profit_center_id = Column(
		UUID(as_uuid=False),
		ForeignKey("pc_profit_center.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	name = Column(String(200), nullable=False)
	allocation_method = Column(
		String(30),
		nullable=False,
		comment="FIXED_PERCENTAGE|HEADCOUNT|REVENUE",
	)
	targets: list[dict[str, Any]] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{profit_center_id, percentage}] — percentages sum to 100 for FIXED",
	)
	gl_accounts: list[str] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="GL account codes to allocate; empty list = all accounts",
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

	source_profit_center: ProfitCenter = relationship(
		"ProfitCenter",
		back_populates="allocation_rules",
		lazy="select",
		foreign_keys=[source_profit_center_id],
	)

	def __repr__(self) -> str:
		return (
			f"<ProfitCenterAllocationRule {self.name!r} "
			f"method={self.allocation_method!r} "
			f"source={self.source_profit_center_id!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ProfitCenter",
	"ProfitCenterJournal",
	"ProfitCenterAllocationRule",
]
