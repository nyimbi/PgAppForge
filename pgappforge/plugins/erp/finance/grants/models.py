"""
pgappforge/plugins/erp/finance/grants/models.py

SQLAlchemy models for the Grant/Fund Accounting plugin.

Design invariants:
  - All PKs: UUID4 string, gen_random_uuid() server default
  - All timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - All monetary amounts: BigInteger cents (NEVER float)
  - All models: tenant_id VARCHAR NOT NULL
  - JSONB for semi-structured fields (reporting_requirements)
  - Composite indexes for tenant + status hot paths

Table prefix: gnt_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	DateTime,
	Index,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fund
# ---------------------------------------------------------------------------

class Fund(AuditMixin, Model):
	"""Fund master — represents a named pool of money with a restriction type.

	fund_type drives accounting treatment:
	  UNRESTRICTED   — general operating funds, no donor restrictions
	  TEMP_RESTRICTED — purpose/time restricted; releases on condition fulfillment
	  PERM_RESTRICTED — corpus must be maintained; only investment income spendable

	gl_dimension_value maps to the GL dimensions.fund key for journal posting.
	"""

	__allow_unmapped__ = True
	__tablename__ = "gnt_fund"
	__table_args__ = (
		Index("ix_gnt_fund_tenant_type", "tenant_id", "fund_type"),
		Index("ix_gnt_fund_tenant_code", "tenant_id", "fund_code"),
		UniqueConstraint("tenant_id", "fund_code", name="uq_gnt_fund_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(
		String(36),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()::text"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)
	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)
	fund_type = Column(String(30), nullable=False)  # UNRESTRICTED/TEMP_RESTRICTED/PERM_RESTRICTED
	fund_code = Column(String(50), nullable=False)
	entity_id = Column(String(50), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True, server_default=sa.text("true"))
	gl_dimension_value = Column(String(50), nullable=True)
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
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)


# ---------------------------------------------------------------------------
# Grant
# ---------------------------------------------------------------------------

class Grant(AuditMixin, Model):
	"""Grant record — award from a grantor to a specific fund.

	indirect_cost_rate is a Numeric(6,4) fraction, e.g. 0.1500 = 15% overhead.
	reporting_requirements is a JSONB list of {report_type, due_date, description} dicts.
	status lifecycle: PENDING → ACTIVE → REPORTING → CLOSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "gnt_grant"
	__table_args__ = (
		Index("ix_gnt_grant_fund_status", "fund_id", "status"),
		Index("ix_gnt_grant_tenant_status", "tenant_id", "status"),
		UniqueConstraint("tenant_id", "grant_ref", name="uq_gnt_grant_tenant_ref"),
		{"extend_existing": True},
	)

	id = Column(
		String(36),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()::text"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)
	fund_id = Column(
		String(36),
		sa.ForeignKey("gnt_fund.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	grant_ref = Column(String(50), nullable=False)
	grantor_name = Column(String(300), nullable=False)
	grantor_contact = Column(Text, nullable=True)
	amount_cents = Column(BigInteger, nullable=False)
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	status = Column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
	reporting_requirements = Column(JSONB, nullable=False, default=list, server_default="[]")
	indirect_cost_rate = Column(
		Numeric(6, 4),
		nullable=False,
		default=0,
		server_default=sa.text("0"),
	)
	approved_by = Column(String(50), nullable=True)
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
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)


# ---------------------------------------------------------------------------
# FundBalance
# ---------------------------------------------------------------------------

class FundBalance(AuditMixin, Model):
	"""Period-level fund balance snapshot.

	closing_cents = opening_cents + receipts_cents - expenditures_cents
	period is a string like "2026-Q1" or "2026-06".
	"""

	__allow_unmapped__ = True
	__tablename__ = "gnt_fund_balance"
	__table_args__ = (
		Index("ix_gnt_fund_balance_fund_period", "fund_id", "period"),
		UniqueConstraint("fund_id", "period", name="uq_gnt_fund_balance_fund_period"),
		{"extend_existing": True},
	)

	id = Column(
		String(36),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()::text"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)
	fund_id = Column(
		String(36),
		sa.ForeignKey("gnt_fund.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	period = Column(String(20), nullable=False)
	opening_cents = Column(BigInteger, nullable=False, default=0, server_default=sa.text("0"))
	receipts_cents = Column(BigInteger, nullable=False, default=0, server_default=sa.text("0"))
	expenditures_cents = Column(BigInteger, nullable=False, default=0, server_default=sa.text("0"))
	closing_cents = Column(BigInteger, nullable=False)
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
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)


# ---------------------------------------------------------------------------
# GrantExpenditure
# ---------------------------------------------------------------------------

class GrantExpenditure(AuditMixin, Model):
	"""Expenditure posted against a grant for a given period.

	indirect_cost_cents is computed from grant.indirect_cost_rate at posting time.
	gl_journal_id is a soft FK to the GL journal entry (VARCHAR, cross-plugin).
	"""

	__allow_unmapped__ = True
	__tablename__ = "gnt_expenditure"
	__table_args__ = (
		Index("ix_gnt_expenditure_grant_period", "grant_id", "period"),
		Index("ix_gnt_expenditure_tenant_period", "tenant_id", "period"),
		{"extend_existing": True},
	)

	id = Column(
		String(36),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()::text"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)
	grant_id = Column(
		String(36),
		sa.ForeignKey("gnt_grant.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	period = Column(String(20), nullable=False)
	amount_cents = Column(BigInteger, nullable=False)
	indirect_cost_cents = Column(BigInteger, nullable=False, default=0, server_default=sa.text("0"))
	purpose = Column(String(300), nullable=False)
	gl_journal_id = Column(String(50), nullable=True)   # soft FK to GL journal
	approved_by = Column(String(50), nullable=True)
	expenditure_date = Column(Date, nullable=False, default=date.today)
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
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)


__all__ = [
	"Fund",
	"Grant",
	"FundBalance",
	"GrantExpenditure",
]
