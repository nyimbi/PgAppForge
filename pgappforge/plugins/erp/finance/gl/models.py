"""
pgappforge/plugins/erp/finance/gl/models.py

SQLAlchemy models for the General Ledger plugin.

Design invariants:
  - All PKs:         UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps:  DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - All models:      tenant_id UUID NOT NULL
  - All amounts:     Integer cents (BigInteger) — NEVER float or Numeric
  - Financial rows:  NEVER UPDATE — INSERT correction entries only
  - lazy=:           'select' everywhere (SA 2.x removed 'dynamic')
  - AuditMixin:      applied to all mutable entities
  - JSONB:           used for extensible attributes
  - Indexes:         composite indexes matching common query patterns
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
# GLAccount  (chart of accounts — natural VARCHAR PK)
# ---------------------------------------------------------------------------

class GLAccount(AuditMixin, RulesMixin, Model):
	"""Chart of accounts entry.

	account_code is the natural primary key (e.g. "1000", "1000.10").
	Self-referential parent_code enables account hierarchies.
	is_posting_account=False means summary/header — no journal lines allowed.
	ifrs_concept / gaap_concept map to standard taxonomy nodes.

	NEVER update historical balances by modifying this row.  Changes to
	account metadata are fine; changes to posted transaction data require
	correction journal entries.
	"""

	__allow_unmapped__ = True
	__tablename__ = "gl_account"
	__table_args__ = (
		Index("ix_gl_account_tenant_type", "tenant_id", "account_type"),
		Index("ix_gl_account_parent", "parent_code"),
		Index("ix_gl_account_active", "is_active"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset = frozenset({
		"account_name", "account_subtype", "normal_balance",
		"is_posting_account", "is_reconciliation_account",
		"currency_code", "ifrs_concept", "gaap_concept", "is_active",
		"description",
	})

	account_code = Column(
		String(20),
		primary_key=True,
		comment="Natural PK e.g. 1000 or 1000.10",
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)
	account_name = Column(String(255), nullable=False)
	account_type = Column(
		String(20),
		nullable=False,
		comment="ASSET|LIABILITY|EQUITY|REVENUE|EXPENSE|STATISTICAL",
	)
	account_subtype = Column(String(50), nullable=True)
	normal_balance = Column(
		String(6),
		nullable=False,
		default="DEBIT",
		comment="DEBIT|CREDIT — determined by account_type",
	)
	parent_code = Column(
		String(20),
		ForeignKey("gl_account.account_code", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	is_posting_account = Column(
		Boolean,
		nullable=False,
		default=True,
		comment="False = summary/header account, no journal lines allowed",
	)
	is_reconciliation_account = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True = requires periodic reconciliation",
	)
	currency_code = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=True,
		comment="NULL = multi-currency; set for single-currency accounts",
	)
	ifrs_concept = Column(
		String(100),
		nullable=True,
		comment="IFRS taxonomy concept e.g. ifrs-full:Cash",
	)
	gaap_concept = Column(
		String(100),
		nullable=True,
		comment="US GAAP taxonomy concept",
	)
	is_statistical = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True for non-monetary statistical accounts (headcount, sq ft)",
	)
	stat_unit = Column(
		String(30),
		nullable=True,
		comment="Unit of measure for statistical accounts: FTE/SQFT/HOURS/COUNT",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	description = Column(Text, nullable=True)
	attributes: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Extensible metadata (tax flags, reporting tags, etc.)",
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
	parent: GLAccount = relationship(
		"GLAccount",
		remote_side="GLAccount.account_code",
		foreign_keys=[parent_code],
		lazy="select",
	)
	children: list[GLAccount] = relationship(
		"GLAccount",
		foreign_keys=[parent_code],
		back_populates="parent",
		lazy="select",
	)
	journal_lines: list[GLJournalLine] = relationship(
		"GLJournalLine",
		back_populates="account",
		lazy="select",
	)
	balances: list[GLAccountBalance] = relationship(
		"GLAccountBalance",
		back_populates="account",
		lazy="select",
	)
	budgets: list[GLBudget] = relationship(
		"GLBudget",
		back_populates="account",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<GLAccount {self.account_code!r} {self.account_name!r} {self.account_type!r}>"


# ---------------------------------------------------------------------------
# GLCostCenter
# ---------------------------------------------------------------------------

class GLCostCenter(AuditMixin, Model):
	"""Cost centre for management accounting dimensions.

	Self-referential parent_code for org hierarchy.
	"""

	__allow_unmapped__ = True
	__tablename__ = "gl_cost_center"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_gl_cost_center_tenant_code"),
		Index("ix_gl_cc_tenant", "tenant_id"),
		Index("ix_gl_cc_parent", "parent_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(20), nullable=False)
	name = Column(String(100), nullable=False)
	parent_code = Column(
		String(20),
		nullable=True,
		index=True,
		comment="Self-referential parent via code (no DB FK to avoid cross-tenant leak)",
	)
	manager_party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	department = Column(String(100), nullable=True)
	business_unit = Column(String(100), nullable=True)
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
		return f"<GLCostCenter {self.code!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# GLFiscalYear
# ---------------------------------------------------------------------------

class GLFiscalYear(AuditMixin, Model):
	"""Fiscal year master."""

	__allow_unmapped__ = True
	__tablename__ = "gl_fiscal_year"
	__table_args__ = (
		UniqueConstraint("tenant_id", "year_code", name="uq_gl_fy_tenant_code"),
		Index("ix_gl_fy_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	year_code = Column(String(20), nullable=False, comment="e.g. FY2025 or 2025")
	fiscal_year = Column(Integer, nullable=False, comment="Calendar year integer e.g. 2025")
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN|CLOSED|LOCKED",
	)
	closed_by = Column(UUID(as_uuid=False), nullable=True)
	closed_at = Column(DateTime(timezone=True), nullable=True)
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

	periods: list[GLPeriod] = relationship(
		"GLPeriod",
		back_populates="fiscal_year_rel",
		lazy="select",
		order_by="GLPeriod.period_number",
	)

	def __repr__(self) -> str:
		return f"<GLFiscalYear {self.year_code!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# GLPeriod
# ---------------------------------------------------------------------------

class GLPeriod(AuditMixin, Model):
	"""Accounting period (month) within a fiscal year."""

	__allow_unmapped__ = True
	__tablename__ = "gl_period"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "fiscal_year_id", "period_number",
			name="uq_gl_period_fy_num",
		),
		Index("ix_gl_period_tenant", "tenant_id"),
		Index("ix_gl_period_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	fiscal_year_id = Column(
		UUID(as_uuid=False),
		ForeignKey("gl_fiscal_year.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	period_number = Column(
		Integer,
		nullable=False,
		comment="1-12 (or 1-13 for 13-period calendars)",
	)
	period_name = Column(String(50), nullable=True, comment="e.g. January 2025")
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN|CLOSED|LOCKED",
	)
	closed_by = Column(UUID(as_uuid=False), nullable=True)
	closed_at = Column(DateTime(timezone=True), nullable=True)
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

	fiscal_year_rel: GLFiscalYear = relationship(
		"GLFiscalYear",
		back_populates="periods",
		lazy="select",
	)
	batches: list[GLJournalBatch] = relationship(
		"GLJournalBatch",
		back_populates="period",
		lazy="select",
	)
	balances: list[GLAccountBalance] = relationship(
		"GLAccountBalance",
		back_populates="period",
		lazy="select",
	)
	budgets: list[GLBudget] = relationship(
		"GLBudget",
		back_populates="period",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<GLPeriod {self.period_name!r} fy={self.fiscal_year_id!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# GLJournalBatch
# ---------------------------------------------------------------------------

class GLJournalBatch(AuditMixin, RulesMixin, Model):
	"""Container for one or more journal entries that post atomically.

	total_debits / total_credits are maintained in application code when lines
	are added; is_balanced is a derived flag set to True when they match.
	All amounts stored as integer cents (BigInteger).

	IMMUTABLE LEDGER: Once status=POSTED, this row must not be modified.
	To correct, reverse the entries and post new ones.
	"""

	__allow_unmapped__ = True
	__tablename__ = "gl_journal_batch"
	__table_args__ = (
		UniqueConstraint("tenant_id", "batch_number", name="uq_gl_batch_tenant_num"),
		Index("ix_gl_batch_period", "period_id"),
		Index("ix_gl_batch_status", "status"),
		Index("ix_gl_batch_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset = frozenset({
		"description", "batch_type", "status",
		"total_debits", "total_credits", "is_balanced",
	})

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	batch_number = Column(String(50), nullable=False)
	batch_type = Column(
		String(30),
		nullable=False,
		default="MANUAL",
		comment="MANUAL|AUTO|ACCRUAL|REVERSAL|IMPORT",
	)
	period_id = Column(
		UUID(as_uuid=False),
		ForeignKey("gl_period.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	description = Column(Text, nullable=True)
	# Integer cents — never float
	total_debits = Column(BigInteger, nullable=False, default=0)
	total_credits = Column(BigInteger, nullable=False, default=0)
	is_balanced = Column(Boolean, nullable=False, default=False)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|SUBMITTED|APPROVED|POSTED|REVERSED",
	)
	submitted_by = Column(UUID(as_uuid=False), nullable=True)
	submitted_at = Column(DateTime(timezone=True), nullable=True)
	approved_by = Column(UUID(as_uuid=False), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	posted_by = Column(UUID(as_uuid=False), nullable=True)
	posted_at = Column(DateTime(timezone=True), nullable=True)
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

	period: GLPeriod = relationship(
		"GLPeriod",
		back_populates="batches",
		lazy="select",
	)
	entries: list[GLJournalEntry] = relationship(
		"GLJournalEntry",
		back_populates="batch",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<GLJournalBatch {self.batch_number!r} type={self.batch_type!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# GLJournalEntry
# ---------------------------------------------------------------------------

class GLJournalEntry(AuditMixin, RulesMixin, Model):
	"""Individual accounting entry within a batch.

	An entry groups one or more lines that balance (sum(debit)==sum(credit)).
	reversal_of_entry_id links reversal entries back to their origin.
	auto_reverse / auto_reverse_date support automatic accrual reversal.

	IMMUTABLE LEDGER: Once status=POSTED, never modify.
	"""

	__allow_unmapped__ = True
	__tablename__ = "gl_journal_entry"
	__table_args__ = (
		UniqueConstraint("tenant_id", "entry_number", name="uq_gl_entry_tenant_num"),
		Index("ix_gl_entry_batch", "batch_id"),
		Index("ix_gl_entry_tenant", "tenant_id"),
		Index("ix_gl_entry_posting_date", "posting_date"),
		Index("ix_gl_entry_source_doc", "source_document_type", "source_document_id"),
		Index("ix_gl_entry_reversal_of", "reversal_of_entry_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset = frozenset({
		"description", "entry_type", "posting_date", "status",
		"auto_reverse", "auto_reverse_date",
	})

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	batch_id = Column(
		UUID(as_uuid=False),
		ForeignKey("gl_journal_batch.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	entry_number = Column(
		String(50),
		nullable=True,
		comment="Human-readable entry reference; unique per tenant",
	)
	entry_type = Column(
		String(30),
		nullable=False,
		default="MANUAL",
		comment="MANUAL|AUTO|REVERSAL|RECURRING",
	)
	posting_date = Column(Date, nullable=False)
	description = Column(Text, nullable=True)
	source_document_type = Column(
		String(50),
		nullable=True,
		comment="e.g. INVOICE, PAYMENT, EXPENSE_REPORT",
	)
	source_document_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
	)
	reversal_of_entry_id = Column(
		UUID(as_uuid=False),
		ForeignKey("gl_journal_entry.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	auto_reverse = Column(Boolean, nullable=False, default=False)
	auto_reverse_date = Column(Date, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|POSTED|REVERSED",
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

	batch: GLJournalBatch = relationship(
		"GLJournalBatch",
		back_populates="entries",
		lazy="select",
	)
	lines: list[GLJournalLine] = relationship(
		"GLJournalLine",
		back_populates="entry",
		cascade="all, delete-orphan",
		lazy="select",
		order_by="GLJournalLine.line_number",
	)
	reversal_of: GLJournalEntry = relationship(
		"GLJournalEntry",
		remote_side="GLJournalEntry.id",
		foreign_keys=[reversal_of_entry_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<GLJournalEntry {self.entry_number!r} date={self.posting_date!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# GLJournalLine
# ---------------------------------------------------------------------------

class GLJournalLine(AuditMixin, Model):
	"""Single debit or credit line within a journal entry.

	All monetary amounts are BigInteger (integer cents / kobo).
	debit_amount XOR credit_amount is non-zero per line (never both).
	base_debit / base_credit are the functional-currency equivalents after FX.

	IMMUTABLE LEDGER: Lines are never updated once the entry is posted.
	"""

	__allow_unmapped__ = True
	__tablename__ = "gl_journal_line"
	__table_args__ = (
		Index("ix_gl_line_entry", "entry_id"),
		Index("ix_gl_line_account", "account_code"),
		Index("ix_gl_line_tenant", "tenant_id"),
		Index("ix_gl_line_cost_center", "cost_center_code"),
		Index("ix_gl_line_party", "party_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entry_id = Column(
		UUID(as_uuid=False),
		ForeignKey("gl_journal_entry.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	line_number = Column(Integer, nullable=False)
	account_code = Column(
		String(20),
		ForeignKey("gl_account.account_code"),
		nullable=False,
		index=True,
	)
	cost_center_code = Column(
		String(20),
		nullable=True,
		index=True,
		comment="Soft FK to gl_cost_center.code (cross-tenant safe)",
	)
	project_code = Column(String(50), nullable=True)
	# Transactional currency amounts (integer minor units)
	debit_amount = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Integer cents in transaction currency",
	)
	credit_amount = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Integer cents in transaction currency",
	)
	currency_code = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=False,
		default="USD",
	)
	# FX conversion
	fx_rate = Column(
		Numeric(15, 6),
		nullable=False,
		default=1,
		comment="1 transaction_currency = fx_rate base_currency",
	)
	# Functional (base) currency amounts (integer minor units)
	base_debit = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Integer cents in functional/base currency",
	)
	base_credit = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Integer cents in functional/base currency",
	)
	description = Column(Text, nullable=True)
	reference = Column(String(200), nullable=True)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	tax_code = Column(String(20), nullable=True)
	dimensions = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Tenant-defined dimension values e.g. {project: PRJ001, grant: GRT001}",
	)
	quantity = Column(
		Numeric(15, 4),
		nullable=True,
		comment="For statistical accounts: quantity in stat_unit (no monetary amount)",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	# No updated_at: journal lines are immutable once posted.

	entry: GLJournalEntry = relationship(
		"GLJournalEntry",
		back_populates="lines",
		lazy="select",
	)
	account: GLAccount = relationship(
		"GLAccount",
		back_populates="journal_lines",
		lazy="select",
	)

	def __repr__(self) -> str:
		side = f"DR {self.debit_amount}" if self.debit_amount else f"CR {self.credit_amount}"
		return (
			f"<GLJournalLine {self.line_number} acct={self.account_code!r} "
			f"{side} {self.currency_code}>"
		)


# ---------------------------------------------------------------------------
# GLAccountBalance  (period snapshot — maintained by post_journal service)
# ---------------------------------------------------------------------------

class GLAccountBalance(Model):
	"""Period account balance snapshot.

	Written/updated by GLService.post_journal() and
	GLService.close_period().  The table acts as a materialized summary;
	for authoritative balances always recompute from gl_journal_line if
	the period is still OPEN.

	All amounts are BigInteger (integer cents / kobo).
	"""

	__allow_unmapped__ = True
	__tablename__ = "gl_account_balance"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "account_code", "period_id",
			name="uq_gl_balance_tenant_acct_period",
		),
		Index("ix_gl_balance_tenant", "tenant_id"),
		Index("ix_gl_balance_account", "account_code"),
		Index("ix_gl_balance_period", "period_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	account_code = Column(
		String(20),
		ForeignKey("gl_account.account_code"),
		nullable=False,
	)
	period_id = Column(
		UUID(as_uuid=False),
		ForeignKey("gl_period.id", ondelete="RESTRICT"),
		nullable=False,
	)
	opening_debit = Column(BigInteger, nullable=False, default=0)
	opening_credit = Column(BigInteger, nullable=False, default=0)
	period_debit = Column(BigInteger, nullable=False, default=0)
	period_credit = Column(BigInteger, nullable=False, default=0)
	closing_debit = Column(BigInteger, nullable=False, default=0)
	closing_credit = Column(BigInteger, nullable=False, default=0)
	ytd_debit = Column(BigInteger, nullable=False, default=0)
	ytd_credit = Column(BigInteger, nullable=False, default=0)
	dimensions = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Dimension values for this balance row",
	)
	refreshed_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	account: GLAccount = relationship(
		"GLAccount",
		back_populates="balances",
		lazy="select",
	)
	period: GLPeriod = relationship(
		"GLPeriod",
		back_populates="balances",
		lazy="select",
	)

	def __repr__(self) -> str:
		net = self.closing_debit - self.closing_credit
		return (
			f"<GLAccountBalance acct={self.account_code!r} "
			f"period={self.period_id!r} net={net}>"
		)


# ---------------------------------------------------------------------------
# GLBudget
# ---------------------------------------------------------------------------

class GLBudget(AuditMixin, Model):
	"""Budget vs actual tracking per account / cost centre / period.

	All amounts are BigInteger (integer cents / kobo).
	Multiple budget versions (ORIGINAL, REVISED, FORECAST) supported.
	"""

	__allow_unmapped__ = True
	__tablename__ = "gl_budget"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "account_code", "cost_center_code", "period_id", "version",
			name="uq_gl_budget_key",
		),
		Index("ix_gl_budget_tenant", "tenant_id"),
		Index("ix_gl_budget_account", "account_code"),
		Index("ix_gl_budget_period", "period_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	account_code = Column(
		String(20),
		ForeignKey("gl_account.account_code"),
		nullable=False,
	)
	cost_center_code = Column(String(20), nullable=True)
	period_id = Column(
		UUID(as_uuid=False),
		ForeignKey("gl_period.id", ondelete="RESTRICT"),
		nullable=False,
	)
	version = Column(
		String(20),
		nullable=False,
		default="ORIGINAL",
		comment="ORIGINAL|REVISED|FORECAST",
	)
	budget_amount = Column(BigInteger, nullable=False, default=0)
	revised_budget_amount = Column(BigInteger, nullable=True)
	forecast_amount = Column(BigInteger, nullable=True)
	notes = Column(Text, nullable=True)
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

	account: GLAccount = relationship(
		"GLAccount",
		back_populates="budgets",
		lazy="select",
	)
	period: GLPeriod = relationship(
		"GLPeriod",
		back_populates="budgets",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<GLBudget acct={self.account_code!r} cc={self.cost_center_code!r} "
			f"period={self.period_id!r} v={self.version!r} amt={self.budget_amount}>"
		)


# ---------------------------------------------------------------------------
# GLDimensionDefinition
# ---------------------------------------------------------------------------

class GLDimensionDefinition(AuditMixin, Model):
	"""Tenant-defined GL dimension catalogue (equivalent to Intacct dimension types).

	Examples: project, grant, department, location, product_line, fund.
	Up to 12 active dimensions per tenant (Intacct parity).
	"""

	__allow_unmapped__ = True
	__tablename__ = "gl_dimension_def"
	__table_args__ = (
		sa.UniqueConstraint("tenant_id", "dimension_code", name="uq_gl_dim_code"),
		sa.Index("ix_gl_dim_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	dimension_code = Column(String(50), nullable=False, comment="Machine key: project, grant, department")
	name = Column(String(200), nullable=False, comment="Human label: Project, Grant, Department")
	is_required = Column(Boolean, nullable=False, default=False)
	allowed_values = Column(JSONB, nullable=True, comment="If set, restricts valid values. None = any string")
	is_active = Column(Boolean, nullable=False, default=True)
	description = Column(Text, nullable=True)

	def __repr__(self) -> str:
		return f"<GLDimensionDefinition {self.dimension_code!r} tenant={self.tenant_id!r}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"GLAccount",
	"GLCostCenter",
	"GLFiscalYear",
	"GLPeriod",
	"GLJournalBatch",
	"GLJournalEntry",
	"GLJournalLine",
	"GLAccountBalance",
	"GLBudget",
	"GLDimensionDefinition",
]
