"""
pgappforge/plugins/fintech/core_banking/models.py

Core Banking models — customer accounts, ledger entries, interest accrual,
product catalogue, account holds, and statements.

Design rules enforced here:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents/kobo/fils — never Decimal/float in storage
  - LEDGER ENTRIES: ImmutableRecordMixin (insert-only, no UPDATE)
  - INTEREST ACCRUAL: ImmutableRecordMixin (insert-only, no UPDATE)

Table name convention: cb_<entity>
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, date, timezone
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# PostgreSQL sequence for race-safe account number generation
# ---------------------------------------------------------------------------

# Global sequence — guarantees uniqueness under concurrent open_account() calls.
# The seq number is used as the SEQNO component of YYYYMMDD-BRANCH-SEQNO.
# Uniqueness is the invariant; contiguous per-branch-per-day numbering is NOT
# guaranteed (and not required for production).
CB_ACCOUNT_SEQ = sa.Sequence("cb_account_seq", start=1, increment=1)


# ---------------------------------------------------------------------------
# BankProduct — product catalogue
# ---------------------------------------------------------------------------

class BankProduct(AuditMixin, Model):
	"""Product catalogue — defines rates, fees, and rules per product type.

	product_type discriminates behaviour in the service layer:
	  SAVINGS / CURRENT / FIXED_DEPOSIT / CALL /
	  LOAN / OVERDRAFT / MORTGAGE / SME_LOAN / CONSUMER_LOAN

	interest_calculation: DAILY_BALANCE | AVERAGE_DAILY_BALANCE | FLAT
	interest_crediting_frequency: DAILY | MONTHLY | QUARTERLY | ANNUALLY

	fees JSONB shape:
	  {maintenance_fee_cents, transfer_fee_cents, atm_fee_cents, ...}

	For deposits: interest_rate_pa is rate paid TO customer.
	For loans:    interest_rate_pa is rate charged TO customer.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_product"
	__table_args__ = (
		Index("ix_cb_product_code", "product_code"),
		Index("ix_cb_product_tenant", "tenant_id"),
		Index("ix_cb_product_type", "product_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		String(64),
		nullable=False,
		index=True,
		comment="Tenant identifier",
	)
	product_code = Column(
		String(30),
		unique=True,
		nullable=False,
		comment="Short unique code e.g. SAV001, FXD90D",
	)
	product_name = Column(String(200), nullable=False)
	product_type = Column(
		String(30),
		nullable=False,
		comment=(
			"SAVINGS | CURRENT | FIXED_DEPOSIT | CALL | LOAN | "
			"OVERDRAFT | MORTGAGE | SME_LOAN | CONSUMER_LOAN"
		),
	)
	currency_code = Column(String(3), nullable=False, default="KES")

	# Balance / opening constraints (cents)
	min_balance_cents = Column(Integer, nullable=False, default=0)
	min_opening_balance_cents = Column(Integer, nullable=False, default=0)

	# Interest
	interest_rate_pa = Column(
		Numeric(10, 6),
		nullable=False,
		default=0,
		comment="Annual interest rate. For deposits: paid to customer. For loans: charged to customer.",
	)
	interest_calculation = Column(
		String(30),
		nullable=False,
		default="DAILY_BALANCE",
		comment="DAILY_BALANCE | AVERAGE_DAILY_BALANCE | FLAT",
	)
	interest_crediting_frequency = Column(
		String(20),
		nullable=False,
		default="MONTHLY",
		comment="DAILY | MONTHLY | QUARTERLY | ANNUALLY",
	)
	penalty_rate_pa = Column(
		Numeric(10, 6),
		nullable=False,
		default=0,
		comment="Additional penalty rate p.a. charged on overdue loan balances",
	)

	# Fees — flexible JSONB: {maintenance_fee_cents, transfer_fee_cents, atm_fee_cents, ...}
	fees: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Fee schedule: maintenance_fee_cents, transfer_fee_cents, atm_fee_cents, etc.",
	)

	# Limits
	max_withdrawal_per_day_cents = Column(
		Integer,
		nullable=True,
		comment="NULL = unlimited",
	)
	allowed_channels: list[str] = Column(
		ARRAY(String),
		nullable=False,
		default=lambda: ["BRANCH", "ATM", "MOBILE", "ONLINE"],
		comment="BRANCH | ATM | MOBILE | ONLINE | API | SWIFT | RTGS",
	)
	dormancy_threshold_days = Column(
		Integer,
		nullable=False,
		default=365,
		comment="Days of inactivity before account is marked DORMANT",
	)

	# Flags
	is_islamic = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="Sharia-compliant product (profit-sharing, not interest)",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	# Audit timestamps
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
	accounts: list[Account] = relationship(
		"Account",
		back_populates="product",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<BankProduct {self.product_code!r} type={self.product_type!r}>"


# ---------------------------------------------------------------------------
# Account — customer account
# ---------------------------------------------------------------------------

class Account(AuditMixin, Model):
	"""Customer Account — the core entity of the core banking system.

	current_balance_cents: actual ledger balance.
	available_balance_cents: current minus holds (funds usable for transactions).
	accrued_interest_cents: interest accrued since last capitalisation.
	holds_cents: total of all active holds (derived; maintained in sync by service).

	status flow:
	  PENDING_ACTIVATION → ACTIVE → DORMANT (auto)
	                               → FROZEN (manual/AML)
	                               → SUSPENDED (compliance)
	                               → CLOSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_account"
	__table_args__ = (
		Index("ix_cb_account_number", "account_number"),
		Index("ix_cb_account_customer", "customer_id"),
		Index("ix_cb_account_product", "product_id"),
		Index("ix_cb_account_tenant", "tenant_id"),
		Index("ix_cb_account_status", "status"),
		Index("ix_cb_account_iban", "iban"),
		UniqueConstraint("account_number", name="uq_cb_account_number"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	account_number = Column(
		String(30),
		unique=True,
		nullable=False,
		index=True,
		comment="Human-readable account number e.g. YYYYMMDD-BRANCH-SEQNO",
	)
	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_product.id"),
		nullable=False,
		index=True,
	)
	customer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id"),
		nullable=False,
		index=True,
		comment="FK to foundation Party (customer)",
	)
	currency_code = Column(String(3), nullable=False, default="KES")

	# Balances (all in integer cents)
	current_balance_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Ledger balance — sum of all posted debit/credit entries",
	)
	available_balance_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="current_balance minus active holds",
	)
	accrued_interest_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Interest accrued but not yet capitalised",
	)
	holds_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total of all ACTIVE hold amounts on this account",
	)

	# Status
	status = Column(
		String(20),
		nullable=False,
		default="PENDING_ACTIVATION",
		comment=(
			"PENDING_ACTIVATION | ACTIVE | DORMANT | FROZEN | CLOSED | SUSPENDED"
		),
	)

	# Dates
	opened_date = Column(Date, nullable=False)
	closed_date = Column(Date, nullable=True)
	last_transaction_at = Column(DateTime(timezone=True), nullable=True)
	last_interest_accrual_date = Column(Date, nullable=True)
	maturity_date = Column(
		Date,
		nullable=True,
		comment="For FIXED_DEPOSIT; NULL for demand accounts",
	)
	dormancy_notified_at = Column(DateTime(timezone=True), nullable=True)

	# Administrative
	branch_code = Column(String(20), nullable=True)
	relationship_manager_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to Party (staff member) — nullable FK not enforced at DB level",
	)
	iban = Column(
		String(34),
		nullable=True,
		unique=True,
		comment="International Bank Account Number (optional, ISO 13616)",
	)
	# Loan-specific: original disbursed principal for FLAT interest calculation.
	# NULL for deposit products.  Populated by the service at disbursement.
	original_principal_cents = Column(
		sa.BigInteger,
		nullable=True,
		comment="Original loan principal (cents) — used for FLAT interest calculation",
	)

	# Audit timestamps
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
	product: BankProduct = relationship("BankProduct", back_populates="accounts", lazy="select")
	ledger_entries: list[LedgerEntry] = relationship(
		"LedgerEntry",
		back_populates="account",
		lazy="select",
		order_by="LedgerEntry.created_at.desc()",
	)
	interest_accruals: list[InterestAccrual] = relationship(
		"InterestAccrual",
		back_populates="account",
		lazy="select",
	)
	holds: list[AccountHold] = relationship(
		"AccountHold",
		back_populates="account",
		lazy="select",
	)
	statements: list[AccountStatement] = relationship(
		"AccountStatement",
		back_populates="account",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Account {self.account_number!r} "
			f"status={self.status!r} "
			f"balance={self.current_balance_cents}>"
		)


# ---------------------------------------------------------------------------
# LedgerEntry — IMMUTABLE double-entry bookkeeping
# ---------------------------------------------------------------------------

class LedgerEntry(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable double-entry ledger entry.

	Every financial transaction creates exactly TWO entries sharing the same
	journal_id: one DEBIT and one CREDIT.

	CRITICAL INVARIANT: rows are INSERT-ONLY.  Never UPDATE or DELETE.
	To reverse a posting, create a new pair of entries with
	transaction_type=REVERSAL and reversal_of_id pointing to the original entry.

	amount_cents is ALWAYS positive; entry_type (DEBIT/CREDIT) carries the sign.

	balance_after_cents: running account balance after this entry is applied.
	This denormalises the balance for fast statement queries but must be
	kept consistent by the service layer (computed at post time).
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_ledger_entry"
	__table_args__ = (
		Index("ix_cb_ledger_journal", "journal_id"),
		Index("ix_cb_ledger_account", "account_id"),
		Index("ix_cb_ledger_reference", "reference_number"),
		Index("ix_cb_ledger_value_date", "value_date"),
		Index("ix_cb_ledger_posting_date", "posting_date"),
		Index("ix_cb_ledger_tenant", "tenant_id"),
		Index(
			"ix_cb_ledger_account_posting",
			"account_id",
			"posting_date",
			postgresql_using="brin",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	journal_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Groups the DEBIT + CREDIT pair for one transaction",
	)
	entry_type = Column(
		String(6),
		nullable=False,
		comment="DEBIT | CREDIT",
	)
	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id"),
		nullable=False,
		index=True,
	)
	gl_account_code = Column(
		String(20),
		nullable=True,
		comment="Mirror to GL chart-of-accounts code (optional)",
	)

	# Amount (always positive; sign encoded in entry_type)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Transaction amount in minor currency units (always positive)",
	)
	currency_code = Column(String(3), nullable=False, default="KES")
	exchange_rate = Column(
		Numeric(15, 6),
		nullable=False,
		default=1,
		comment="FX rate applied: 1 account_currency = exchange_rate base_currency",
	)
	balance_after_cents = Column(
		Integer,
		nullable=False,
		comment="Account current_balance_cents after this entry is applied",
	)

	# Dates
	value_date = Column(
		Date,
		nullable=False,
		comment="Economic date of the transaction",
	)
	posting_date = Column(
		Date,
		nullable=False,
		comment="Date the entry was posted to the ledger",
	)

	# Classification
	transaction_type = Column(
		String(50),
		nullable=False,
		comment=(
			"DEPOSIT | WITHDRAWAL | TRANSFER_IN | TRANSFER_OUT | "
			"INTEREST_CREDIT | INTEREST_DEBIT | FEE | "
			"LOAN_DISBURSEMENT | LOAN_REPAYMENT | REVERSAL | ADJUSTMENT"
		),
	)
	channel = Column(
		String(20),
		nullable=True,
		comment="BRANCH | ATM | MOBILE | ONLINE | API | STANDING_ORDER | DIRECT_DEBIT | SWIFT | RTGS",
	)
	reference_number = Column(
		String(100),
		nullable=True,
		index=True,
		comment="External reference (cheque no, transfer ref, etc.)",
	)
	narrative = Column(Text, nullable=True)

	# Reversal linkage
	reversal_of_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_ledger_entry.id"),
		nullable=True,
		comment="Points to the original entry that this entry reverses",
	)

	# Classification flags
	is_interest = Column(Boolean, nullable=False, default=False)
	is_fee = Column(Boolean, nullable=False, default=False)

	# Audit timestamps (ImmutableRecordMixin blocks updates)
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
		comment="Set once at insert; UPDATE blocked by ImmutableRecordMixin",
	)

	# Relationships
	account: Account = relationship(
		"Account",
		back_populates="ledger_entries",
		lazy="select",
	)
	reversal_of: LedgerEntry | None = relationship(
		"LedgerEntry",
		remote_side="LedgerEntry.id",
		foreign_keys=[reversal_of_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LedgerEntry {self.id!r} "
			f"{self.entry_type} {self.amount_cents}c "
			f"acct={self.account_id!r}>"
		)


# Register immutability guard after class is fully defined
LedgerEntry._register_immutability()


# ---------------------------------------------------------------------------
# InterestAccrual — daily accumulation before capitalisation
# ---------------------------------------------------------------------------

class InterestAccrual(ImmutableRecordMixin, AuditMixin, Model):
	"""Daily interest accrual record.

	The accrual batch runs once per day and creates one row per active account.
	Rows are IMMUTABLE — the capitalisation batch marks them by updating
	is_capitalized + capitalized_at via a direct SQL UPDATE that bypasses ORM
	(or by using a service-level workaround after removing the immutability guard
	from this specific field pair).

	accrued_cents: this day's interest in minor units.
	cumulative_accrued_cents: running total since last capitalisation event.

	Note on rounding: interest_cents = floor(balance * rate_pa / 365).
	Using integer arithmetic throughout.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_interest_accrual"
	__table_args__ = (
		Index("ix_cb_accrual_account", "account_id"),
		Index("ix_cb_accrual_date", "accrual_date"),
		Index("ix_cb_accrual_capitalized", "is_capitalized"),
		Index("ix_cb_accrual_tenant", "tenant_id"),
		UniqueConstraint(
			"account_id", "accrual_date",
			name="uq_cb_interest_accrual_account_date",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id"),
		nullable=False,
		index=True,
	)
	accrual_date = Column(Date, nullable=False)
	opening_balance_cents = Column(
		Integer,
		nullable=False,
		comment="Account balance at start of accrual_date",
	)
	rate_applied_pa = Column(
		Numeric(10, 6),
		nullable=False,
		comment="Annual rate applied for this day's accrual",
	)
	accrued_cents = Column(
		Integer,
		nullable=False,
		comment="Interest earned/charged for this single day",
	)
	cumulative_accrued_cents = Column(
		Integer,
		nullable=False,
		comment="Running cumulative accrual since last capitalisation",
	)

	# Capitalisation state (updated by capitalise_interest service method)
	is_capitalized = Column(Boolean, nullable=False, default=False)
	capitalized_at = Column(DateTime(timezone=True), nullable=True)

	# Audit timestamps
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
	)

	# Relationships
	account: Account = relationship(
		"Account",
		back_populates="interest_accruals",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<InterestAccrual {self.id!r} "
			f"acct={self.account_id!r} "
			f"date={self.accrual_date!r} "
			f"accrued={self.accrued_cents}c>"
		)


# Register immutability guard
InterestAccrual._register_immutability()


# ---------------------------------------------------------------------------
# AccountHold — temporary freeze on a subset of funds
# ---------------------------------------------------------------------------

class AccountHold(AuditMixin, Model):
	"""Temporary hold on a portion of an account's balance.

	Holds reduce available_balance_cents but do NOT reduce current_balance_cents.
	Service methods place_hold / release_hold keep holds_cents on Account in sync.

	hold_reason:
	  CHEQUE_CLEARING | COURT_ORDER | AML_INVESTIGATION |
	  PAYMENT_PENDING | REGULATORY

	status flow: ACTIVE → RELEASED (manual) | EXPIRED (cron) | CONVERTED (to transaction)
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_account_hold"
	__table_args__ = (
		Index("ix_cb_hold_account", "account_id"),
		Index("ix_cb_hold_status", "status"),
		Index("ix_cb_hold_expires", "expires_at"),
		Index("ix_cb_hold_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id"),
		nullable=False,
		index=True,
	)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Amount placed on hold (minor currency units)",
	)
	hold_reason = Column(
		String(100),
		nullable=False,
		comment=(
			"CHEQUE_CLEARING | COURT_ORDER | AML_INVESTIGATION | "
			"PAYMENT_PENDING | REGULATORY"
		),
	)
	reference_number = Column(
		String(100),
		nullable=False,
		comment="External reference (cheque number, court order number, etc.)",
	)
	expires_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL = hold does not auto-expire",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | RELEASED | EXPIRED | CONVERTED",
	)

	# Audit timestamps
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
	account: Account = relationship(
		"Account",
		back_populates="holds",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AccountHold {self.id!r} "
			f"acct={self.account_id!r} "
			f"amount={self.amount_cents}c "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# AccountStatement
# ---------------------------------------------------------------------------

class AccountStatement(AuditMixin, Model):
	"""Periodic statement of account (monthly, on-demand, etc.).

	Carries pre-computed totals for the statement period; the underlying
	detail is always in LedgerEntry.  statement_url points to the generated
	PDF/CSV stored in object storage.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_account_statement"
	__table_args__ = (
		Index("ix_cb_stmt_account", "account_id"),
		Index("ix_cb_stmt_period", "statement_period_start", "statement_period_end"),
		Index("ix_cb_stmt_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id"),
		nullable=False,
		index=True,
	)
	statement_period_start = Column(Date, nullable=False)
	statement_period_end = Column(Date, nullable=False)

	# Pre-computed totals (cents)
	opening_balance_cents = Column(Integer, nullable=False)
	total_debits_cents = Column(Integer, nullable=False)
	total_credits_cents = Column(Integer, nullable=False)
	closing_balance_cents = Column(Integer, nullable=False)
	interest_earned_cents = Column(Integer, nullable=False, default=0)
	fees_charged_cents = Column(Integer, nullable=False, default=0)

	# Generation / delivery metadata
	generated_at = Column(DateTime(timezone=True), nullable=False)
	delivery_method = Column(
		String(20),
		nullable=False,
		default="EMAIL",
		comment="EMAIL | SMS | PRINT | PORTAL",
	)
	delivered_at = Column(DateTime(timezone=True), nullable=True)
	statement_url = Column(
		Text,
		nullable=True,
		comment="URL to generated PDF/CSV in object storage",
	)

	# Audit timestamps
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
	account: Account = relationship(
		"Account",
		back_populates="statements",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AccountStatement {self.id!r} "
			f"acct={self.account_id!r} "
			f"{self.statement_period_start}–{self.statement_period_end}>"
		)


# ---------------------------------------------------------------------------
# AMLScreeningResult — AML transaction monitoring gate
# ---------------------------------------------------------------------------

class AMLScreeningResult(AuditMixin, Model):
	"""Records the AML screening decision for each transaction gate.

	A row is created by CoreBankingService._run_aml_check() for every
	deposit/withdrawal/transfer before entries are posted.

	status values:
	  PASSED  — clear to proceed
	  FLAGGED — suspicious; hold placed, transaction queued for review
	  BLOCKED — transaction rejected
	  PENDING — sent to external provider, awaiting callback

	CRITICAL INVARIANT: rows are INSERT-ONLY for audit trail integrity.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_aml_screening"
	__table_args__ = (
		Index("ix_cb_aml_journal", "journal_ref"),
		Index("ix_cb_aml_account", "account_id"),
		Index("ix_cb_aml_status", "status"),
		Index("ix_cb_aml_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	# The journal_ref links this screening record to the transaction that
	# triggered it.  Uses a VARCHAR rather than a strict FK so the record
	# can be written before the LedgerEntry is committed (pre-check pattern).
	journal_ref = Column(
		String(64),
		nullable=False,
		index=True,
		comment="Reference to the journal_id being screened",
	)
	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id"),
		nullable=False,
		index=True,
	)
	amount_cents = Column(sa.BigInteger, nullable=False)
	currency_code = Column(String(3), nullable=False, default="KES")
	transaction_type = Column(String(30), nullable=False, comment="DEPOSIT | WITHDRAWAL | TRANSFER etc.")
	screening_provider = Column(
		String(50),
		nullable=False,
		default="INTERNAL",
		comment="Provider name: INTERNAL, COMPLY_ADVANTAGE, ORACLE_FCCM, etc.",
	)
	screening_ref = Column(
		String(100),
		nullable=True,
		comment="Provider's own reference / case ID",
	)
	risk_score = Column(
		sa.Numeric(5, 2),
		nullable=True,
		comment="Normalised 0-100 risk score from provider",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PASSED | FLAGGED | BLOCKED | PENDING",
	)
	flagged_reason = Column(Text, nullable=True)
	screened_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	resolved_at = Column(DateTime(timezone=True), nullable=True)
	resolved_by = Column(UUID(as_uuid=False), nullable=True)

	# Audit timestamps
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
			f"<AMLScreeningResult {self.id!r} "
			f"journal={self.journal_ref!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# GLAccountMapping — tenant-configurable GL codes
# ---------------------------------------------------------------------------

class GLAccountMapping(AuditMixin, Model):
	"""Per-tenant override of the default GL chart-of-accounts codes.

	The core banking service maintains a module-level fallback dict (_CB_GL).
	This model allows operators to override individual codes per tenant without
	redeploying code — required for multi-entity/multi-subsidiary deployments
	where each legal entity has its own chart of accounts.

	Example: tenant "acme_ke" might map CUSTOMER_DEPOSITS → "2000-100" while
	tenant "acme_tz" maps the same key → "L-DEP-001".

	cb_account_key examples:
	  CUSTOMER_DEPOSITS, CASH_NOSTRO, INTEREST_INCOME, FEE_INCOME,
	  INTEREST_EXPENSE, LOAN_PORTFOLIO, ACCRUED_INTEREST_ASSET,
	  ACCRUED_INTEREST_LIABILITY
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_gl_mapping"
	__table_args__ = (
		UniqueConstraint("tenant_id", "cb_account_key", name="uq_cb_gl_mapping_tenant_key"),
		Index("ix_cb_gl_mapping_tenant", "tenant_id"),
		Index("ix_cb_gl_mapping_key", "cb_account_key"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	cb_account_key = Column(
		String(50),
		nullable=False,
		comment="Logical CB key e.g. CUSTOMER_DEPOSITS, CASH_NOSTRO, FEE_INCOME",
	)
	gl_account_code = Column(
		String(20),
		nullable=False,
		comment="Tenant's own chart-of-accounts code for this CB key",
	)
	description = Column(Text, nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)

	# Audit timestamps
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
			f"<GLAccountMapping tenant={self.tenant_id!r} "
			f"key={self.cb_account_key!r} code={self.gl_account_code!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"BankProduct",
	"Account",
	"LedgerEntry",
	"InterestAccrual",
	"AccountHold",
	"AccountStatement",
	"AMLScreeningResult",
	"GLAccountMapping",
	"CB_ACCOUNT_SEQ",
]
