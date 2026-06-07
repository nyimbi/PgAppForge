"""
pgappforge/plugins/erp/finance/consolidation/models.py

SQLAlchemy models for the Group Consolidation plugin.

Design invariants:
  - All PKs:         UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps:  DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - All models:      tenant_id UUID NOT NULL
  - All amounts:     Integer cents (BigInteger) — NEVER float or Numeric
  - Table prefix:    con_
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
# ConsolidationGroup
# ---------------------------------------------------------------------------

class ConsolidationGroup(AuditMixin, Model):
	"""Defines a group of legal entities to be consolidated.

	members is a JSONB list of:
	    [{"entity_id": str, "ownership_pct": float, "method": "FULL|EQUITY|PROPORTIONAL"}, ...]

	reporting_entity_id is the parent/holding entity that produces the
	consolidated financial statements.

	Ownership percentages across members need not sum to 100% — minority
	interest is computed for subsidiaries below 100%.
	"""

	__allow_unmapped__ = True
	__tablename__ = "con_group"
	__table_args__ = (
		Index("ix_con_group_tenant_entity", "tenant_id", "reporting_entity_id"),
		Index("ix_con_group_active", "is_active"),
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
	description = Column(Text, nullable=True)
	reporting_entity_id = Column(
		String(50),
		nullable=False,
		comment="Parent/holding entity that owns the consolidated statements",
	)
	reporting_currency = Column(
		String(3),
		nullable=False,
		default="USD",
		comment="ISO 4217 code for the consolidated reporting currency",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	members: list[dict[str, Any]] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{entity_id, ownership_pct, method: FULL|EQUITY|PROPORTIONAL}]",
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

	runs: list[ConsolidationRun] = relationship(
		"ConsolidationRun",
		back_populates="group",
		lazy="select",
		order_by="ConsolidationRun.started_at.desc()",
	)

	def __repr__(self) -> str:
		return f"<ConsolidationGroup {self.name!r} entity={self.reporting_entity_id!r}>"


# ---------------------------------------------------------------------------
# ConsolidationRun
# ---------------------------------------------------------------------------

class ConsolidationRun(AuditMixin, Model):
	"""Represents a single consolidation execution for a group and period.

	result_data stores the full consolidated trial balance keyed by account_code:
	    {
	        "trial_balance": [{"account_code": str, "net_cents": int, ...}],
	        "fx_translations": [...],
	        "summary": {...},
	    }

	status transitions: IN_PROGRESS → COMPLETED | FAILED
	"""

	__allow_unmapped__ = True
	__tablename__ = "con_run"
	__table_args__ = (
		Index("ix_con_run_group_period", "group_id", "period"),
		Index("ix_con_run_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	group_id = Column(
		UUID(as_uuid=False),
		ForeignKey("con_group.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	period = Column(
		String(20),
		nullable=False,
		comment="Accounting period e.g. 2025-01",
	)
	status = Column(
		String(20),
		nullable=False,
		default="IN_PROGRESS",
		comment="IN_PROGRESS|COMPLETED|FAILED",
	)
	started_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	entities_processed = Column(Integer, nullable=False, default=0)
	eliminations_count = Column(Integer, nullable=False, default=0)
	error_message = Column(Text, nullable=True)
	result_data: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Consolidated trial balance, FX summary, and metadata",
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

	group: ConsolidationGroup = relationship(
		"ConsolidationGroup",
		back_populates="runs",
		lazy="select",
	)
	eliminations: list[IntercompanyElimination] = relationship(
		"IntercompanyElimination",
		back_populates="run",
		cascade="all, delete-orphan",
		lazy="select",
	)
	minority_interests: list[MinorityInterest] = relationship(
		"MinorityInterest",
		back_populates="run",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ConsolidationRun period={self.period!r} "
			f"status={self.status!r} group={self.group_id!r}>"
		)


# ---------------------------------------------------------------------------
# IntercompanyElimination
# ---------------------------------------------------------------------------

class IntercompanyElimination(AuditMixin, Model):
	"""Records a single intercompany elimination entry within a consolidation run.

	elimination_type values:
	  AR_AP             — eliminate intercompany receivable/payable
	  INVESTMENT_EQUITY — eliminate parent investment against subsidiary equity
	  INTERCO_REVENUE   — eliminate intercompany sales/purchases
	  DIVIDEND          — eliminate intercompany dividend income/distribution

	amount_cents is always positive; the service posts DR to debtor_entity_id
	and CR to creditor_entity_id on account_code.
	"""

	__allow_unmapped__ = True
	__tablename__ = "con_elimination"
	__table_args__ = (
		Index("ix_con_elim_run_type", "run_id", "elimination_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	run_id = Column(
		UUID(as_uuid=False),
		ForeignKey("con_run.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	debtor_entity_id = Column(
		String(50),
		nullable=False,
		comment="Entity that carries the receivable / investment",
	)
	creditor_entity_id = Column(
		String(50),
		nullable=False,
		comment="Entity that carries the payable / equity",
	)
	elimination_type = Column(
		String(30),
		nullable=False,
		comment="AR_AP|INVESTMENT_EQUITY|INTERCO_REVENUE|DIVIDEND",
	)
	amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Elimination amount in reporting currency, integer cents",
	)
	currency_code = Column(String(3), nullable=False)
	account_code = Column(
		String(20),
		nullable=False,
		comment="GL account affected by the elimination",
	)
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

	run: ConsolidationRun = relationship(
		"ConsolidationRun",
		back_populates="eliminations",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<IntercompanyElimination {self.elimination_type!r} "
			f"amount={self.amount_cents} {self.currency_code} "
			f"dr={self.debtor_entity_id!r} cr={self.creditor_entity_id!r}>"
		)


# ---------------------------------------------------------------------------
# MinorityInterest
# ---------------------------------------------------------------------------

class MinorityInterest(AuditMixin, Model):
	"""Records the computed minority interest for a subsidiary in a consolidation run.

	minority_ownership_pct = 100% - parent ownership percentage
	minority_interest_cents = subsidiary_equity_cents * minority_ownership_pct / 100
	"""

	__allow_unmapped__ = True
	__tablename__ = "con_minority"
	__table_args__ = (
		Index("ix_con_minority_run_entity", "run_id", "subsidiary_entity_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	run_id = Column(
		UUID(as_uuid=False),
		ForeignKey("con_run.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	subsidiary_entity_id = Column(String(50), nullable=False)
	minority_ownership_pct = Column(
		Numeric(8, 4),
		nullable=False,
		comment="Percentage not owned by the parent e.g. 20.0000",
	)
	subsidiary_equity_cents = Column(
		BigInteger,
		nullable=False,
		comment="Total equity of subsidiary translated to reporting currency",
	)
	minority_interest_cents = Column(
		BigInteger,
		nullable=False,
		comment="minority_ownership_pct / 100 * subsidiary_equity_cents",
	)
	period = Column(String(20), nullable=False)
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

	run: ConsolidationRun = relationship(
		"ConsolidationRun",
		back_populates="minority_interests",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<MinorityInterest subsidiary={self.subsidiary_entity_id!r} "
			f"pct={self.minority_ownership_pct} "
			f"mi_cents={self.minority_interest_cents}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ConsolidationGroup",
	"ConsolidationRun",
	"IntercompanyElimination",
	"MinorityInterest",
]
