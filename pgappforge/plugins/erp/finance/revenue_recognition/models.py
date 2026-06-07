"""
pgappforge/plugins/erp/finance/revenue_recognition/models.py

SQLAlchemy models for the Revenue Recognition plugin (ASC 606 / IFRS 15).

Design invariants:
  - All PKs:         UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps:  DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - All models:      tenant_id UUID NOT NULL
  - All amounts:     Integer cents (BigInteger) — NEVER float or Numeric for money
  - PostgreSQL only: JSONB, UUID, gen_random_uuid()
  - Table prefix:    rev_
  - AuditMixin:      applied to all mutable entities
  - Indexes:         composite indexes matching common query patterns

ASC 606 / IFRS 15 five-step model:
  1. Identify the contract(s) with a customer             → RevRecContract
  2. Identify performance obligations                     → RevRecObligation
  3. Determine the transaction price (incl. variable)     → VariableConsideration
  4. Allocate transaction price to obligations            → RevRecObligation.allocated_transaction_price_cents
  5. Recognize revenue when/as obligations are satisfied  → RevRecJournalEntry
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
# RevRecContract — Step 1: identify the contract
# ---------------------------------------------------------------------------

class RevRecContract(AuditMixin, Model):
	"""Revenue recognition contract (ASC 606 / IFRS 15 unit of account).

	One contract per commercial arrangement with a customer.
	total_transaction_price_cents is the aggregate price allocated across
	performance obligations; it may differ from the invoice amount when
	variable consideration or discounts are present.

	status transitions: OPEN → PARTIALLY_SATISFIED → FULLY_SATISFIED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "rev_contract"
	__table_args__ = (
		Index("ix_rev_contract_tenant_status", "tenant_id", "status"),
		Index("ix_rev_contract_customer_tenant", "customer_id", "tenant_id"),
		Index("ix_rev_contract_source", "source_module", "source_record_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)
	customer_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Reference to CRM / party customer record",
	)
	contract_ref = Column(
		String(100),
		nullable=True,
		comment="Human-readable contract reference number",
	)
	contract_date = Column(
		Date,
		nullable=False,
		default=date.today,
		comment="Contract inception date per ASC 606-10-25-1",
	)
	total_transaction_price_cents = Column(
		BigInteger,
		nullable=False,
		comment=(
			"Total transaction price in minor currency units (integer cents). "
			"Allocated among performance obligations. Never float."
		),
	)
	variable_consideration_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment=(
			"Constrained variable consideration included in transaction price "
			"per ASC 606-10-32-11 / IFRS 15.56"
		),
	)
	contract_mod_number = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Incremented each time the contract is modified",
	)
	status = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN | PARTIALLY_SATISFIED | FULLY_SATISFIED | CANCELLED",
	)
	source_module = Column(
		String(100),
		nullable=True,
		comment="Originating module e.g. crm.subscriptions",
	)
	source_record_id = Column(
		String(50),
		nullable=True,
		comment="PK of the source record (subscription_id, order_id, etc.)",
	)
	metadata_ = Column(
		"metadata_",
		JSONB,
		nullable=False,
		default=dict,
		comment="Extensible JSON attributes (custom fields, tags, etc.)",
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
	obligations: list[RevRecObligation] = relationship(
		"RevRecObligation",
		back_populates="contract",
		cascade="all, delete-orphan",
		lazy="select",
	)
	journal_entries: list[RevRecJournalEntry] = relationship(
		"RevRecJournalEntry",
		back_populates="contract",
		cascade="all, delete-orphan",
		lazy="select",
	)
	variable_consideration: VariableConsideration = relationship(
		"VariableConsideration",
		back_populates="contract",
		uselist=False,
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RevRecContract {self.id!r} cust={self.customer_id!r} "
			f"status={self.status!r} total={self.total_transaction_price_cents}>"
		)


# ---------------------------------------------------------------------------
# RevRecObligation — Step 2: performance obligations
# ---------------------------------------------------------------------------

class RevRecObligation(AuditMixin, Model):
	"""Performance obligation within a revenue recognition contract.

	Each obligation carries:
	  - standalone_selling_price_cents: the SSP used for allocation
	  - allocated_transaction_price_cents: recomputed on each contract modification
	  - satisfied_cents: cumulative amount recognized to date
	  - remaining_cents: server-computed (allocated - satisfied)

	satisfaction_type drives WHEN revenue is recognized:
	  POINT_IN_TIME — recognize on the satisfaction event
	  OVER_TIME     — recognize via recognize_period() using recognition_method

	status transitions: UNSATISFIED → PARTIALLY → FULLY_SATISFIED
	"""

	__allow_unmapped__ = True
	__tablename__ = "rev_obligation"
	__table_args__ = (
		Index("ix_rev_obligation_contract_status", "contract_id", "status"),
		Index("ix_rev_obligation_tenant_type", "tenant_id", "satisfaction_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
	)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rev_contract.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	description = Column(
		Text,
		nullable=False,
		comment="Human-readable description of the performance obligation",
	)
	standalone_selling_price_cents = Column(
		BigInteger,
		nullable=False,
		comment=(
			"Standalone selling price in integer cents — the observable or "
			"estimated SSP used to allocate the transaction price "
			"(ASC 606-10-32-31 / IFRS 15.76)"
		),
	)
	allocated_transaction_price_cents = Column(
		BigInteger,
		nullable=False,
		comment=(
			"Portion of the contract transaction price allocated to this obligation. "
			"Recomputed on contract modification."
		),
	)
	satisfied_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Cumulative recognized amount in integer cents",
	)
	# remaining_cents is maintained in application code (allocated - satisfied)
	# It is stored as a regular column (not a DB computed column) for
	# portability and to avoid DDL complexity.  Service layer keeps it in sync.
	remaining_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="allocated - satisfied; maintained by service layer",
	)
	satisfaction_type = Column(
		String(20),
		nullable=False,
		comment="POINT_IN_TIME | OVER_TIME (ASC 606-10-25-14 / IFRS 15.35)",
	)
	recognition_method = Column(
		String(30),
		nullable=False,
		default="STRAIGHT_LINE",
		comment=(
			"For OVER_TIME obligations: "
			"STRAIGHT_LINE | OUTPUT | INPUT | COMPLETED_CONTRACT"
		),
	)
	start_date = Column(
		Date,
		nullable=True,
		comment="Service period start for OVER_TIME obligations",
	)
	end_date = Column(
		Date,
		nullable=True,
		comment="Service period end for OVER_TIME obligations",
	)
	status = Column(
		String(20),
		nullable=False,
		default="UNSATISFIED",
		comment="UNSATISFIED | PARTIALLY | FULLY_SATISFIED",
	)

	# ── Series obligations (ASC 606-10-25-15 / IFRS 15.22–23) ──────────────
	is_series = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True for a series of distinct services that are substantially the same",
	)

	# ── Percentage-of-completion (POC) method fields ─────────────────────────
	poc_method = Column(
		String(30),
		nullable=True,
		comment="OUTPUT method: UNITS_DELIVERED. INPUT method: COSTS_INCURRED | MILESTONES",
	)
	total_units = Column(
		Integer,
		nullable=True,
		comment="Total expected units for OUTPUT/UNITS_DELIVERED method",
	)
	delivered_units = Column(
		Integer,
		nullable=True,
		comment="Units delivered to date for OUTPUT method",
	)
	total_estimated_cost_cents = Column(
		BigInteger,
		nullable=True,
		comment="Total estimated cost in integer cents for INPUT/COSTS_INCURRED method",
	)
	costs_incurred_cents = Column(
		BigInteger,
		nullable=True,
		default=0,
		comment="Cumulative costs incurred to date in integer cents (INPUT method)",
	)

	metadata_ = Column(
		"metadata_",
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
	contract: RevRecContract = relationship(
		"RevRecContract",
		back_populates="obligations",
		lazy="select",
	)
	journal_entries: list[RevRecJournalEntry] = relationship(
		"RevRecJournalEntry",
		back_populates="obligation",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RevRecObligation {self.id!r} contract={self.contract_id!r} "
			f"type={self.satisfaction_type!r} status={self.status!r} "
			f"remaining={self.remaining_cents}>"
		)


# ---------------------------------------------------------------------------
# RevRecJournalEntry — Step 5: recognition entries
# ---------------------------------------------------------------------------

class RevRecJournalEntry(AuditMixin, Model):
	"""Revenue recognition journal entry (deferred revenue → revenue).

	Immutable once written — corrections require new entries.
	Links back to the GL journal via gl_journal_id for full audit trail.

	Accounting entry:
	  DR Deferred Revenue (deferred_revenue_account)  recognized_cents
	  CR Revenue          (revenue_account)            recognized_cents
	"""

	__allow_unmapped__ = True
	__tablename__ = "rev_journal_entry"
	__table_args__ = (
		Index("ix_rev_je_contract_period", "contract_id", "period"),
		Index("ix_rev_je_obligation_period", "obligation_id", "period"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
	)
	obligation_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rev_obligation.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rev_contract.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	period = Column(
		String(20),
		nullable=False,
		comment="Accounting period string e.g. '2025-01'",
	)
	recognized_cents = Column(
		BigInteger,
		nullable=False,
		comment="Amount recognized in this entry — integer cents, never float",
	)
	gl_journal_id = Column(
		String(50),
		nullable=True,
		comment="Reference to the GL journal entry id posted by GLService",
	)
	deferred_revenue_account = Column(
		String(20),
		nullable=False,
		default="2500",
		comment="GL account code for deferred revenue (DR side)",
	)
	revenue_account = Column(
		String(20),
		nullable=False,
		default="4000",
		comment="GL account code for recognized revenue (CR side)",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	# No updated_at — entries are immutable once written

	# Relationships
	obligation: RevRecObligation = relationship(
		"RevRecObligation",
		back_populates="journal_entries",
		lazy="select",
	)
	contract: RevRecContract = relationship(
		"RevRecContract",
		back_populates="journal_entries",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RevRecJournalEntry {self.id!r} contract={self.contract_id!r} "
			f"period={self.period!r} recognized={self.recognized_cents}>"
		)


# ---------------------------------------------------------------------------
# VariableConsideration — Step 3: estimate variable consideration
# ---------------------------------------------------------------------------

class VariableConsideration(AuditMixin, Model):
	"""Variable consideration estimate for a contract (ASC 606-10-32-5 / IFRS 15.50).

	Records the estimation method, constraint application, and resulting
	constrained amount that feeds into the transaction price.

	One-to-one with RevRecContract (unique constraint on contract_id).
	"""

	__allow_unmapped__ = True
	__tablename__ = "rev_variable_consideration"
	__table_args__ = (
		UniqueConstraint("contract_id", name="uq_rev_vc_contract"),
		Index("ix_rev_vc_contract", "contract_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
	)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rev_contract.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
		index=True,
	)
	estimation_method = Column(
		String(30),
		nullable=False,
		comment="EXPECTED_VALUE | MOST_LIKELY_AMOUNT (ASC 606-10-32-8 / IFRS 15.53)",
	)
	constraint_applied = Column(
		Boolean,
		nullable=False,
		default=True,
		comment=(
			"True = constraint applied per ASC 606-10-32-11 / IFRS 15.56; "
			"only the constrained amount is included in transaction price"
		),
	)
	estimated_cents = Column(
		BigInteger,
		nullable=False,
		comment="Gross estimated variable consideration in integer cents",
	)
	constrained_cents = Column(
		BigInteger,
		nullable=False,
		comment=(
			"Constrained amount included in transaction price — "
			"<= estimated_cents when constraint_applied=True"
		),
	)
	last_estimated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		comment="Timestamp of last re-estimation (required for disclosure)",
	)
	basis = Column(
		Text,
		nullable=True,
		comment="Narrative explaining the estimation basis (audit support)",
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
	contract: RevRecContract = relationship(
		"RevRecContract",
		back_populates="variable_consideration",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<VariableConsideration contract={self.contract_id!r} "
			f"method={self.estimation_method!r} constrained={self.constrained_cents}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"RevRecContract",
	"RevRecObligation",
	"RevRecJournalEntry",
	"VariableConsideration",
]
