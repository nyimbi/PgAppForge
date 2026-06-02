"""
pgappforge/plugins/erp/finance/treasury/models.py

Treasury Management models.

Design rules:
  - All PKs: UUID v4 via gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All monetary amounts: INTEGER cents — never float
  - All models: tenant_id UUID NOT NULL + AuditMixin
  - Financial records: IMMUTABLE — INSERT correction entries only, NEVER UPDATE
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured metadata
  - Table name convention: erp_tr_<entity>

Key domains:
  - Bank account master + real-time balance tracking
  - Daily cash position (actual vs forecast)
  - FX deals (spot/forward/swap) with hedge designation (IFRS 9)
  - Bank statement import + line-by-line reconciliation
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
from pgappforge.plugins.rules.mixin import RulesMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# BankAccount
# ---------------------------------------------------------------------------

class BankAccount(RulesMixin, AuditMixin, Model):
	"""Bank account master record.

	balance_cents and available_balance_cents are maintained by the service
	layer on each payment/receipt posting. They are denormalised for fast
	cash-position queries and must stay in sync with CashPosition daily totals.

	account_type:
	  CURRENT   — standard operating account
	  SAVINGS   — deposit / interest-bearing account
	  OVERDRAFT — account with approved overdraft facility
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tr_bank_account"
	__table_args__ = (
		UniqueConstraint("tenant_id", "account_number", name="uq_erp_tr_bank_account_number"),
		Index("ix_erp_tr_bank_account_tenant", "tenant_id"),
		Index("ix_erp_tr_bank_account_currency", "currency_code"),
		{"extend_existing": True},
	)

	_rules_mutable_fields = frozenset({"balance_cents", "available_balance_cents", "last_reconciled_date"})

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	account_number = Column(String(50), nullable=False)
	bank_name = Column(String(200), nullable=False)
	bank_bic = Column(
		String(11),
		nullable=True,
		comment="SWIFT/BIC code e.g. GTBINGLA",
	)
	iban = Column(
		String(34),
		nullable=True,
		comment="International Bank Account Number (where applicable)",
	)
	currency_code = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=False,
		comment="ISO 4217 currency code",
	)
	account_type = Column(
		String(20),
		nullable=False,
		default="CURRENT",
		comment="CURRENT | SAVINGS | OVERDRAFT",
	)
	gl_account = Column(
		String(50),
		nullable=False,
		comment="Chart of accounts GL code for this bank account",
	)
	balance_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Current confirmed balance (ledger balance)",
	)
	available_balance_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Available balance net of holds and uncleared items",
	)
	overdraft_limit_cents = Column(
		Integer,
		nullable=True,
		comment="Approved overdraft facility limit (OVERDRAFT accounts)",
	)
	last_reconciled_date = Column(Date, nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)
	is_default = Column(Boolean, nullable=False, default=False)
	metadata_: dict[str, Any] = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
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

	# Relationships
	cash_positions: list[CashPosition] = relationship(
		"CashPosition",
		back_populates="bank_account",
		lazy="select",
		order_by="CashPosition.position_date",
	)
	statements: list[BankStatement] = relationship(
		"BankStatement",
		back_populates="bank_account",
		lazy="select",
	)
	fx_deals_buy: list[FXDeal] = relationship(
		"FXDeal",
		foreign_keys="FXDeal.buy_bank_account_id",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<BankAccount {self.account_number!r} {self.bank_name!r} "
			f"ccy={self.currency_code!r} bal={self.balance_cents}>"
		)


# ---------------------------------------------------------------------------
# CashPosition  (append-only daily snapshot)
# ---------------------------------------------------------------------------

class CashPosition(AuditMixin, Model):
	"""Daily cash position snapshot per bank account.

	IMMUTABLE: one row per (bank_account_id, position_date). Corrections
	are made by inserting a new row for the same date with adjusted values
	(the service layer uses MAX(created_at) to determine the current position).

	forecast_balance_cents is populated by the cash-flow forecast engine
	for future dates; actual values update it once the day closes.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tr_cash_position"
	__table_args__ = (
		Index("ix_erp_tr_cash_position_account_date", "bank_account_id", "position_date"),
		Index("ix_erp_tr_cash_position_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	bank_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tr_bank_account.id", ondelete="RESTRICT"),
		nullable=False,
	)
	position_date = Column(Date, nullable=False)
	opening_balance_cents = Column(Integer, nullable=False, default=0)
	receipts_cents = Column(Integer, nullable=False, default=0)
	payments_cents = Column(Integer, nullable=False, default=0)
	closing_balance_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="opening + receipts - payments",
	)
	forecast_balance_cents = Column(
		Integer,
		nullable=True,
		comment="Forecast closing balance from cash-flow model",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	bank_account: BankAccount = relationship(
		"BankAccount",
		back_populates="cash_positions",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CashPosition account={self.bank_account_id!r} "
			f"date={self.position_date!r} closing={self.closing_balance_cents}>"
		)


# ---------------------------------------------------------------------------
# FXDeal
# ---------------------------------------------------------------------------

class FXDeal(RulesMixin, AuditMixin, Model):
	"""Foreign exchange deal (spot, forward, or swap).

	All amounts in minor currency units (cents) of the respective currency.
	contracted_rate is NUMERIC(20,8) — never float.

	Hedge designations per IFRS 9:
	  FAIR_VALUE       — hedge of fair value exposure
	  CASH_FLOW        — hedge of variable cash flow
	  NET_INVESTMENT   — hedge of net investment in foreign operation
	  NONE             — speculative / undesignated

	Status lifecycle: OPEN → SETTLED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tr_fx_deal"
	__table_args__ = (
		UniqueConstraint("tenant_id", "deal_reference", name="uq_erp_tr_fx_deal_ref"),
		Index("ix_erp_tr_fx_deal_tenant", "tenant_id"),
		Index("ix_erp_tr_fx_deal_settlement", "settlement_date"),
		Index("ix_erp_tr_fx_deal_status", "status"),
		Index("ix_erp_tr_fx_deal_counterparty", "counterparty_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields = frozenset({"status"})

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	deal_reference = Column(
		String(50),
		nullable=False,
		comment="Unique deal reference e.g. FX-2026-00001",
	)
	deal_type = Column(
		String(10),
		nullable=False,
		comment="SPOT | FORWARD | SWAP",
	)
	buy_currency = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=False,
	)
	sell_currency = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=False,
	)
	buy_amount_cents = Column(
		Integer,
		nullable=False,
		comment="Amount received (buy side) in minor units",
	)
	sell_amount_cents = Column(
		Integer,
		nullable=False,
		comment="Amount paid (sell side) in minor units",
	)
	contracted_rate = Column(
		Numeric(20, 8),
		nullable=False,
		comment="Contracted FX rate: 1 sell_currency = contracted_rate buy_currency",
	)
	market_rate = Column(
		Numeric(20, 8),
		nullable=True,
		comment="Market rate at deal booking for P&L calculation",
	)
	settlement_date = Column(Date, nullable=False)
	trade_date = Column(
		Date,
		nullable=False,
		default=date.today,
		server_default=sa.text("CURRENT_DATE"),
	)
	counterparty_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="FK to erp_party.id — bank/counterparty",
	)
	buy_bank_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tr_bank_account.id", ondelete="SET NULL"),
		nullable=True,
		comment="Bank account to receive the bought currency",
	)
	sell_bank_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tr_bank_account.id", ondelete="SET NULL"),
		nullable=True,
		comment="Bank account from which the sold currency is debited",
	)
	hedge_designation = Column(
		String(20),
		nullable=False,
		default="NONE",
		comment="FAIR_VALUE | CASH_FLOW | NET_INVESTMENT | NONE",
	)
	hedged_item_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="Logical FK to the hedged exposure (e.g. invoice_id)",
	)
	hedged_item_type = Column(
		String(100),
		nullable=True,
		comment="Model name of the hedged item e.g. 'SalesInvoice'",
	)
	status = Column(
		String(15),
		nullable=False,
		default="OPEN",
		comment="OPEN | SETTLED | CANCELLED",
	)
	mtm_value_cents = Column(
		Integer,
		nullable=True,
		comment="Mark-to-market fair value in reporting currency (updated by MTM job)",
	)
	settlement_confirmation = Column(Text, nullable=True)
	notes = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
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
			f"<FXDeal {self.deal_reference!r} {self.deal_type!r} "
			f"{self.sell_currency}->{self.buy_currency} "
			f"rate={self.contracted_rate!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# BankStatement
# ---------------------------------------------------------------------------

class BankStatement(AuditMixin, Model):
	"""Imported bank statement header.

	status:
	  IMPORTED   — raw import, no reconciliation started
	  RECONCILED — all lines matched
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tr_bank_statement"
	__table_args__ = (
		Index("ix_erp_tr_bank_statement_account", "bank_account_id"),
		Index("ix_erp_tr_bank_statement_date", "statement_date"),
		Index("ix_erp_tr_bank_statement_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	bank_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tr_bank_account.id", ondelete="RESTRICT"),
		nullable=False,
	)
	statement_date = Column(Date, nullable=False)
	opening_balance_cents = Column(Integer, nullable=False)
	closing_balance_cents = Column(Integer, nullable=False)
	status = Column(
		String(15),
		nullable=False,
		default="IMPORTED",
		comment="IMPORTED | RECONCILED",
	)
	import_reference = Column(String(100), nullable=True)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	bank_account: BankAccount = relationship(
		"BankAccount",
		back_populates="statements",
		lazy="select",
	)
	lines: list[BankStatementLine] = relationship(
		"BankStatementLine",
		back_populates="statement",
		cascade="all, delete-orphan",
		lazy="select",
		order_by="BankStatementLine.transaction_date",
	)

	def __repr__(self) -> str:
		return (
			f"<BankStatement account={self.bank_account_id!r} "
			f"date={self.statement_date!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# BankStatementLine
# ---------------------------------------------------------------------------

class BankStatementLine(Model):
	"""Individual line from an imported bank statement.

	match_status:
	  UNMATCHED  — not yet reconciled
	  MATCHED    — linked to a book entry
	  EXCEPTION  — flagged for manual review

	matched_document_type + matched_document_id form a logical FK to any
	ERP document (payment, receipt, journal entry, etc.).

	is_debit: True = money out (debit to bank account in bank's books =
	credit to cash in company's books). Convention follows the bank's
	statement perspective.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_tr_bank_statement_line"
	__table_args__ = (
		Index("ix_erp_tr_bsl_statement", "statement_id"),
		Index("ix_erp_tr_bsl_match_status", "match_status"),
		Index("ix_erp_tr_bsl_matched_doc", "matched_document_type", "matched_document_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	statement_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_tr_bank_statement.id", ondelete="CASCADE"),
		nullable=False,
	)
	transaction_date = Column(Date, nullable=False)
	value_date = Column(Date, nullable=True, comment="Date funds are available")
	description = Column(String(500), nullable=False)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Always positive; direction determined by is_debit",
	)
	is_debit = Column(
		Boolean,
		nullable=False,
		comment="True = debit (money out of account in bank's view)",
	)
	bank_reference = Column(
		String(100),
		nullable=True,
		comment="Bank's own transaction reference number",
	)
	match_status = Column(
		String(15),
		nullable=False,
		default="UNMATCHED",
		comment="UNMATCHED | MATCHED | EXCEPTION",
	)
	matched_document_type = Column(String(100), nullable=True)
	matched_document_id = Column(String(64), nullable=True)
	matched_at = Column(DateTime(timezone=True), nullable=True)
	exception_reason = Column(Text, nullable=True)

	# Relationships
	statement: BankStatement = relationship(
		"BankStatement",
		back_populates="lines",
		lazy="select",
	)

	def __repr__(self) -> str:
		direction = "DR" if self.is_debit else "CR"
		return (
			f"<BankStatementLine {self.transaction_date!r} "
			f"{direction} {self.amount_cents} match={self.match_status!r}>"
		)


__all__ = [
	"BankAccount",
	"CashPosition",
	"FXDeal",
	"BankStatement",
	"BankStatementLine",
]
