"""
pgappforge/plugins/erp/crm/loyalty/models.py

SQLAlchemy models for the Loyalty Engine plugin.

Table prefix: loy_
PostgreSQL ONLY — BigInteger cents, JSONB config.
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enum constants
# ---------------------------------------------------------------------------

LOYALTY_TIER = ("BRONZE", "SILVER", "GOLD", "PLATINUM", "DIAMOND")
TRANSACTION_TYPE = ("EARN", "REDEEM", "EXPIRE", "ADJUST", "BONUS")
ACCOUNT_STATUS = ("ACTIVE", "SUSPENDED", "CLOSED")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class LoyaltyProgram(AuditMixin, Model):
	"""Defines a loyalty program with tier thresholds and earn/redeem rules."""

	__tablename__ = "loy_program"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)

	# Points-per-currency-unit earned on qualifying transactions
	earn_rate = Column(Numeric(10, 4), nullable=False, default=1.0)

	# Cents value of one redeemed point
	redemption_rate_cents = Column(BigInteger, nullable=False, default=1)

	# Points expiry in days (0 = never expire)
	expiry_days = Column(Integer, nullable=False, default=365)

	# Tier thresholds: {"SILVER": 1000, "GOLD": 5000, "PLATINUM": 20000}
	tier_thresholds = Column(JSONB, nullable=False, default=dict)

	is_active = Column(Boolean, nullable=False, default=True)

	# Relationships
	accounts = relationship("LoyaltyAccount", back_populates="program", lazy="select")

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_loy_program_name_tenant"),
	)

	def __repr__(self) -> str:
		return f"<LoyaltyProgram {self.name!r}>"


class LoyaltyAccount(AuditMixin, Model):
	"""A customer's membership account within a loyalty program."""

	__tablename__ = "loy_account"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	program_id = Column(
		String(36),
		ForeignKey("loy_program.id", ondelete="CASCADE"),
		nullable=False,
	)
	customer_id = Column(String(36), nullable=False)

	tier = Column(String(20), nullable=False, default="BRONZE")
	status = Column(String(20), nullable=False, default="ACTIVE")

	points_balance = Column(BigInteger, nullable=False, default=0)
	lifetime_points = Column(BigInteger, nullable=False, default=0)

	enrolled_at = Column(DateTime(timezone=True), nullable=False, default=_now)
	last_activity_at = Column(DateTime(timezone=True), nullable=True)

	# Relationships
	program = relationship("LoyaltyProgram", back_populates="accounts", lazy="select")
	transactions = relationship("LoyaltyTransaction", back_populates="account", lazy="select")

	__table_args__ = (
		UniqueConstraint("program_id", "customer_id", name="uq_loy_account_program_customer"),
		Index("ix_loy_account_customer", "tenant_id", "customer_id"),
		Index("ix_loy_account_tier", "tenant_id", "tier", "status"),
	)

	def __repr__(self) -> str:
		return f"<LoyaltyAccount {self.id} customer={self.customer_id} [{self.tier}]>"


class LoyaltyTransaction(AuditMixin, Model):
	"""Ledger row for each points earn, redeem, expire, or adjustment."""

	__tablename__ = "loy_transaction"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	account_id = Column(
		String(36),
		ForeignKey("loy_account.id", ondelete="CASCADE"),
		nullable=False,
	)

	transaction_type = Column(String(20), nullable=False)  # EARN/REDEEM/EXPIRE/ADJUST/BONUS
	points = Column(BigInteger, nullable=False)            # positive=earn/bonus, negative=redeem/expire
	balance_after = Column(BigInteger, nullable=False)

	# Source reference: order_id, invoice_id, etc.
	reference_id = Column(String(100), nullable=True)
	reference_type = Column(String(50), nullable=True)

	notes = Column(Text, nullable=True)
	occurred_at = Column(DateTime(timezone=True), nullable=False, default=_now)

	# Expiry for EARN transactions
	expires_at = Column(DateTime(timezone=True), nullable=True)
	is_expired = Column(Boolean, nullable=False, default=False)

	# Relationships
	account = relationship("LoyaltyAccount", back_populates="transactions", lazy="select")

	__table_args__ = (
		Index("ix_loy_txn_account_type", "account_id", "transaction_type"),
		Index("ix_loy_txn_expires", "expires_at", "is_expired"),
	)

	def __repr__(self) -> str:
		return f"<LoyaltyTransaction {self.transaction_type} {self.points:+d}>"
