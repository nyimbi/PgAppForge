"""Ledger tables: accounts, entries, postings.

Naming follows the project's ``ab_`` convention. Amounts are ``Numeric(20, 4)``
so intermediate rates and unit quantities keep four decimal places; balances are
materialised on the account row as a cache and are always rebuildable from the
postings. Nothing in the schema permits an entry without exactly two balanced
postings except through :class:`~pgappforge.ledger.service.LedgerService`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal


from sqlalchemy import (
	Boolean,
	CheckConstraint,
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
from sqlalchemy.orm import relationship, validates

from pgappforge import Model
from pgappforge.models.mixins import AuditMixin

MONEY = Numeric(20, 4)
ZERO = Decimal("0.0000")


class LedgerAccount(AuditMixin, Model):
	"""A named account. Normal balances: asset and expense debit, liability and
	income credit. The sign convention is enforced by ``normal_sign`` only as a
	default; the service validates the resulting signed balance."""

	__tablename__ = "ab_ledger_accounts"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_ledger_account_tenant_code"),
		CheckConstraint(
			"balance >= -abs(overdraft_limit) OR allow_negative = true",
			name="ck_ledger_account_not_overdrawn",
		),
		Index("ix_ledger_accounts_tenant_type", "tenant_id", "account_type"),
	)

	id = Column(Integer, primary_key=True)
	tenant_id = Column(Integer, nullable=True, index=True)
	code = Column(String(32), nullable=False)
	name = Column(String(200), nullable=False)
	account_type = Column(String(20), nullable=False)  # asset|liability|income|expense|equity
	currency = Column(String(3), nullable=False, default="KES")
	normal_sign = Column(Integer, nullable=False, default=1)  # +1 credit, -1 debit
	allow_negative = Column(Boolean, nullable=False, default=False)
	overdraft_limit = Column(MONEY, nullable=False, default=ZERO, server_default="0")
	parent_id = Column(Integer, ForeignKey("ab_ledger_accounts.id"), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")
	balance = Column(MONEY, nullable=False, default=ZERO, server_default="0")
	created_on = Column(DateTime, default=lambda: datetime.now(tz=timezone.utc))
	updated_on = Column(
		DateTime,
		default=lambda: datetime.now(tz=timezone.utc),
		onupdate=lambda: datetime.now(tz=timezone.utc),
	)

	postings = relationship("LedgerPosting", back_populates="account", lazy="select")

	@validates("normal_sign")
	def _validate_sign(self, key: str, value: int) -> int:
		if value not in (-1, 1):
			raise ValueError("normal_sign must be +1 (credit) or -1 (debit)")
		return value

	@property
	def available(self) -> Decimal:
		"""Balance plus the permitted overdraft."""
		return Decimal(self.balance) + Decimal(self.overdraft_limit)

	def __repr__(self) -> str:  # pragma: no cover - debug aid
		return f"<LedgerAccount {self.code} {self.currency} {self.balance}>"


class LedgerEntry(AuditMixin, Model):
	"""One balanced movement. ``idempotency_key`` makes replay a no-op."""

	__tablename__ = "ab_ledger_entries"
	__table_args__ = (
		UniqueConstraint("idempotency_key", name="uq_ledger_entry_idempotency"),
		Index("ix_ledger_entries_tenant_date", "tenant_id", "entry_date"),
		Index("ix_ledger_entries_reference", "reference"),
	)

	id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
	tenant_id = Column(Integer, nullable=True, index=True)
	entry_date = Column(
		DateTime,
		nullable=False,
		default=lambda: datetime.now(tz=timezone.utc),
		index=True,
	)
	idempotency_key = Column(String(128), nullable=True)
	reference = Column(String(128), nullable=True, index=True)
	entry_type = Column(String(32), nullable=False, default="transfer")
	description = Column(Text, nullable=True)
	currency = Column(String(3), nullable=False, default="KES")
	total_amount = Column(MONEY, nullable=False, default=ZERO, server_default="0")
	reversal_of_id = Column(String(36), ForeignKey("ab_ledger_entries.id"), nullable=True)
	causation_id = Column(String(64), nullable=True)  # e.g. checkout request id
	posted_by = Column(Integer, nullable=True)  # user id
	metadata_json = Column(Text, nullable=True)  # JSON string (renamed: `metadata` is reserved)
	created_on = Column(DateTime, default=lambda: datetime.now(tz=timezone.utc))

	postings = relationship(
		"LedgerPosting",
		back_populates="entry",
		cascade="all, delete-orphan",
		order_by="LedgerPosting.id",
	)
	reversal_of = relationship("LedgerEntry", remote_side=[id])

	@property
	def is_balanced(self) -> bool:
		debits = sum((p.amount for p in self.postings if p.direction == "debit"), ZERO)
		credits = sum((p.amount for p in self.postings if p.direction == "credit"), ZERO)
		return debits == credits and debits > ZERO


class LedgerPosting(AuditMixin, Model):
	"""A leg of an entry: exactly one of debit or credit, always an amount > 0."""

	__tablename__ = "ab_ledger_postings"
	__table_args__ = (
		CheckConstraint("amount > 0", name="ck_ledger_posting_positive"),
		Index("ix_ledger_postings_account", "account_id"),
	)

	id = Column(Integer, primary_key=True)
	entry_id = Column(String(36), ForeignKey("ab_ledger_entries.id"), nullable=False, index=True)
	account_id = Column(Integer, ForeignKey("ab_ledger_accounts.id"), nullable=False)
	direction = Column(String(6), nullable=False)  # debit | credit
	amount = Column(MONEY, nullable=False)
	currency = Column(String(3), nullable=False, default="KES")
	amount_base = Column(MONEY, nullable=True)  # amount in the account's currency
	memo = Column(Text, nullable=True)
	created_on = Column(DateTime, default=lambda: datetime.now(tz=timezone.utc))

	entry = relationship("LedgerEntry", back_populates="postings")
	account = relationship("LedgerAccount", back_populates="postings")

	@validates("direction")
	def _validate_direction(self, key: str, value: str) -> str:
		if value not in ("debit", "credit"):
			raise ValueError("direction must be 'debit' or 'credit'")
		return value

	@validates("amount")
	def _validate_amount(self, key: str, value) -> Decimal:
		value = Decimal(str(value))
		if value <= ZERO:
			raise ValueError("posting amount must be positive; direction carries the sign")
		return value

	@property
	def signed_amount(self) -> Decimal:
		"""Effect on the account balance: debits add, credits subtract.

		Keeping "debit adds" everywhere (declaration, validation, SQL sum)
		means an account's ``normal_sign`` alone decides whether it is a debit
		or credit account; the stored balance is simply the sum of these.
		"""
		return Decimal(self.amount) if self.direction == "debit" else -Decimal(self.amount)
