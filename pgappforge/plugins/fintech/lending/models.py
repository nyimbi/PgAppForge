"""
pgappforge/plugins/fintech/lending/models.py

Lending plugin models — full LOS + LMS data layer.

Design rules enforced:
  - All PKs: UUID via gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - Monetary amounts: INTEGER cents — never Decimal/float in storage
  - RepaymentSchedule + LoanRepayment: ImmutableRecordMixin (insert-only)
  - JSONB for semi-structured attributes
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, date
from decimal import Decimal
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
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# LoanProduct
# ---------------------------------------------------------------------------

class LoanProduct(AuditMixin, Model):
	"""Loan product configuration — defines the rules for a lending product.

	Extends cb_product concepts for loan-specific config.  All rate fields
	use NUMERIC(10,6) for precision; monetary limits use INTEGER cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_product"
	__table_args__ = (
		UniqueConstraint("product_code", name="uq_ln_product_code"),
		Index("ix_ln_product_tenant", "tenant_id"),
		Index("ix_ln_product_type", "loan_type"),
		Index("ix_ln_product_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	product_code = Column(String(30), nullable=False, comment="Unique product code")
	product_name = Column(String(200), nullable=False)
	loan_type = Column(
		String(30),
		nullable=False,
		comment="PERSONAL/MORTGAGE/SME/ASSET_FINANCE/TRADE_FINANCE/OVERDRAFT/MICRO/AGRICULTURAL/STUDENT",
	)

	# Limits (integer cents)
	min_amount_cents = Column(Integer, nullable=False, comment="Minimum loan amount in cents")
	max_amount_cents = Column(Integer, nullable=False, comment="Maximum loan amount in cents")
	min_tenor_months = Column(Integer, nullable=False, default=1)
	max_tenor_months = Column(Integer, nullable=False)

	# Rates
	base_rate_pa = Column(Numeric(10, 6), nullable=False, comment="Annual base rate e.g. 0.140000 = 14%")
	rate_type = Column(String(20), nullable=False, default="FIXED", comment="FIXED/VARIABLE/PRIME_PLUS")
	repayment_method = Column(
		String(20),
		nullable=False,
		default="REDUCING_BALANCE",
		comment="REDUCING_BALANCE/FLAT_RATE/BULLET/INTEREST_ONLY",
	)

	# Fees (percentage, NUMERIC)
	processing_fee_pct = Column(Numeric(5, 2), nullable=False, default=0)
	insurance_fee_pct = Column(Numeric(5, 2), nullable=False, default=0)

	# Risk controls
	grace_period_days = Column(Integer, nullable=False, default=0)
	penalty_rate_per_day = Column(Numeric(8, 6), nullable=False, default=0)
	max_ltv_pct = Column(Numeric(5, 2), nullable=True, comment="Loan-to-value cap for secured loans")
	required_collateral_types = Column(JSONB, nullable=False, default=list, server_default="[]")
	credit_score_min = Column(Integer, nullable=False, default=0)

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

	# Relationships
	applications: list[LoanApplication] = relationship(
		"LoanApplication", back_populates="product", lazy="select"
	)
	loans: list[Loan] = relationship("Loan", back_populates="product", lazy="select")

	def __repr__(self) -> str:
		return f"<LoanProduct {self.product_code!r} {self.loan_type!r}>"


# ---------------------------------------------------------------------------
# LoanApplication
# ---------------------------------------------------------------------------

class LoanApplication(AuditMixin, Model):
	"""Loan application entity — tracks the full origination lifecycle.

	Status FSM:
	  DRAFT → SUBMITTED → UNDER_REVIEW → CREDIT_CHECK →
	  APPROVED | CONDITIONALLY_APPROVED | REJECTED | WITHDRAWN → DISBURSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_application"
	__table_args__ = (
		UniqueConstraint("application_number", name="uq_ln_application_number"),
		Index("ix_ln_application_tenant", "tenant_id"),
		Index("ix_ln_application_applicant", "applicant_id"),
		Index("ix_ln_application_product", "product_id"),
		Index("ix_ln_application_status", "status"),
		Index("ix_ln_application_submitted_at", "submitted_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	application_number = Column(String(30), nullable=False)
	applicant_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	co_applicant_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_product.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Request fields (integer cents)
	requested_amount_cents = Column(Integer, nullable=False)
	requested_tenor_months = Column(Integer, nullable=False)
	purpose = Column(String(200), nullable=False)
	channel = Column(
		String(20),
		nullable=False,
		default="BRANCH",
		comment="BRANCH/MOBILE/ONLINE/AGENT/DIRECT_SALES",
	)

	# Credit assessment
	credit_score = Column(Integer, nullable=True)
	dti_ratio = Column(Numeric(5, 2), nullable=True, comment="Debt-to-income ratio")
	ltv_ratio = Column(Numeric(5, 2), nullable=True, comment="Loan-to-value ratio")

	# Approved terms (integer cents)
	approved_amount_cents = Column(Integer, nullable=True)
	approved_tenor_months = Column(Integer, nullable=True)
	approved_rate_pa = Column(Numeric(10, 6), nullable=True)

	# State
	status = Column(
		String(30),
		nullable=False,
		default="DRAFT",
		comment=(
			"DRAFT/SUBMITTED/UNDER_REVIEW/CREDIT_CHECK/APPROVED/"
			"CONDITIONALLY_APPROVED/REJECTED/WITHDRAWN/DISBURSED"
		),
	)

	# Timestamps
	submitted_at = Column(DateTime(timezone=True), nullable=True)
	credit_checked_at = Column(DateTime(timezone=True), nullable=True)
	decision_at = Column(DateTime(timezone=True), nullable=True)
	decision_by = Column(UUID(as_uuid=False), nullable=True)

	# Decision details
	rejection_reason = Column(Text, nullable=True)
	conditions = Column(JSONB, nullable=False, default=list, server_default="[]",
		comment="Conditions for conditional approval")
	documents_checklist = Column(JSONB, nullable=False, default=dict, server_default="{}",
		comment="Required documents and their submission status")
	credit_bureau_response = Column(JSONB, nullable=True)
	internal_notes = Column(Text, nullable=True)

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
	product: LoanProduct = relationship("LoanProduct", back_populates="applications", lazy="select")
	collaterals: list[Collateral] = relationship(
		"Collateral", back_populates="application", cascade="all, delete-orphan", lazy="select"
	)
	loan: Loan = relationship("Loan", back_populates="application", uselist=False, lazy="select")

	def __repr__(self) -> str:
		return f"<LoanApplication {self.application_number!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Collateral
# ---------------------------------------------------------------------------

class Collateral(AuditMixin, Model):
	"""Collateral pledged against a loan application.

	estimated_value_cents and forced_sale_value_cents are INTEGER cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_collateral"
	__table_args__ = (
		Index("ix_ln_collateral_application", "application_id"),
		Index("ix_ln_collateral_tenant", "tenant_id"),
		Index("ix_ln_collateral_type", "collateral_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	application_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_application.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	collateral_type = Column(
		String(50),
		nullable=False,
		comment=(
			"PROPERTY/VEHICLE/MACHINERY/STOCK/CASH_DEPOSIT/"
			"GOVERNMENT_BOND/GUARANTEE/SALARY_ASSIGNMENT"
		),
	)
	description = Column(Text, nullable=False)

	# Values (integer cents)
	estimated_value_cents = Column(Integer, nullable=False)
	forced_sale_value_cents = Column(Integer, nullable=True)

	# Valuation details
	valuation_date = Column(Date, nullable=True)
	valuer_id = Column(UUID(as_uuid=False), nullable=True)
	location = Column(JSONB, nullable=True)
	title_number = Column(String(100), nullable=True)
	is_verified = Column(Boolean, nullable=False, default=False)

	# Insurance
	insurance_policy_number = Column(String(100), nullable=True)
	insurance_expiry_date = Column(Date, nullable=True)

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

	application: LoanApplication = relationship(
		"LoanApplication", back_populates="collaterals", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<Collateral {self.id!r} type={self.collateral_type!r}>"


# ---------------------------------------------------------------------------
# Loan
# ---------------------------------------------------------------------------

class Loan(AuditMixin, Model):
	"""Active loan record — the living state of a disbursed loan.

	All monetary fields are INTEGER cents.  outstanding_principal_cents is
	decremented on each repayment application; arrears fields are updated by
	the daily aging job.

	npa_classification follows CBK prudential guidelines:
	  PERFORMING / WATCH / SUBSTANDARD / DOUBTFUL / LOSS
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_loan"
	__table_args__ = (
		UniqueConstraint("loan_number", name="uq_ln_loan_number"),
		Index("ix_ln_loan_tenant", "tenant_id"),
		Index("ix_ln_loan_borrower", "borrower_id"),
		Index("ix_ln_loan_product", "product_id"),
		Index("ix_ln_loan_status", "status"),
		Index("ix_ln_loan_npa", "npa_classification"),
		Index("ix_ln_loan_dpd", "days_past_due"),
		Index("ix_ln_loan_maturity", "maturity_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_number = Column(String(30), nullable=False)
	application_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_application.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	borrower_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Core banking linkage
	loan_account_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		unique=True,
		comment="cb_account tracking outstanding principal",
	)
	repayment_account_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="Customer savings account debited for repayments",
	)
	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_product.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Terms (integer cents for money, NUMERIC for rates)
	principal_cents = Column(Integer, nullable=False)
	interest_rate_pa = Column(Numeric(10, 6), nullable=False)
	tenor_months = Column(Integer, nullable=False)

	# Dates
	disbursement_date = Column(Date, nullable=False)
	first_repayment_date = Column(Date, nullable=False)
	maturity_date = Column(Date, nullable=False)

	# Current balances (integer cents — updated by repayment engine)
	outstanding_principal_cents = Column(Integer, nullable=False)
	outstanding_interest_cents = Column(Integer, nullable=False, default=0)
	accrued_interest_cents = Column(Integer, nullable=False, default=0)
	arrears_principal_cents = Column(Integer, nullable=False, default=0)
	arrears_interest_cents = Column(Integer, nullable=False, default=0)
	penalty_cents = Column(Integer, nullable=False, default=0)

	# Arrears / NPA tracking
	days_past_due = Column(Integer, nullable=False, default=0)
	npa_classification = Column(
		String(20),
		nullable=False,
		default="PERFORMING",
		comment="PERFORMING/WATCH/SUBSTANDARD/DOUBTFUL/LOSS (CBK prudential)",
	)
	provision_rate_pct = Column(Numeric(5, 2), nullable=False, default=0, comment="IFRS 9 ECL provision rate")
	provision_amount_cents = Column(Integer, nullable=False, default=0)

	# Status
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE/DEFAULTED/WRITTEN_OFF/SETTLED/RESTRUCTURED/LEGAL",
	)

	# Restructuring chain
	restructured_from_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="SET NULL"),
		nullable=True,
	)

	# Write-off & recovery (integer cents)
	written_off_date = Column(Date, nullable=True)
	written_off_amount_cents = Column(Integer, nullable=True)
	recovery_amount_cents = Column(Integer, nullable=False, default=0)

	# Last repayment info
	last_repayment_date = Column(Date, nullable=True)
	last_repayment_amount_cents = Column(Integer, nullable=True)

	# Insurance
	insurance_policy_id = Column(UUID(as_uuid=False), nullable=True)

	# Next installment (denormalised for fast collection queries)
	next_installment_date = Column(Date, nullable=True)
	next_installment_amount_cents = Column(Integer, nullable=True)

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
	application: LoanApplication = relationship(
		"LoanApplication", back_populates="loan", lazy="select"
	)
	product: LoanProduct = relationship("LoanProduct", back_populates="loans", lazy="select")
	repayment_schedules: list[RepaymentSchedule] = relationship(
		"RepaymentSchedule",
		back_populates="loan",
		cascade="all, delete-orphan",
		order_by="RepaymentSchedule.installment_number",
		lazy="select",
	)
	repayments: list[LoanRepayment] = relationship(
		"LoanRepayment",
		back_populates="loan",
		cascade="all, delete-orphan",
		order_by="LoanRepayment.payment_date",
		lazy="select",
	)
	restructured_from: Loan = relationship(
		"Loan",
		remote_side="Loan.id",
		foreign_keys=[restructured_from_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Loan {self.loan_number!r} status={self.status!r} dpd={self.days_past_due}>"


# ---------------------------------------------------------------------------
# RepaymentSchedule  (IMMUTABLE)
# ---------------------------------------------------------------------------

class RepaymentSchedule(ImmutableRecordMixin, AuditMixin, Model):
	"""Amortisation schedule row — one per installment, generated at disbursement.

	IMMUTABLE: financial integrity demands no in-place edits.
	If schedule changes are needed (restructuring), create a new schedule
	linked to the new Loan record.

	All monetary fields are INTEGER cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_repayment_schedule"
	__table_args__ = (
		UniqueConstraint("loan_id", "installment_number", name="uq_ln_sched_loan_installment"),
		Index("ix_ln_sched_loan", "loan_id"),
		Index("ix_ln_sched_due_date", "due_date"),
		Index("ix_ln_sched_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	installment_number = Column(Integer, nullable=False)
	due_date = Column(Date, nullable=False, index=True)

	# Scheduled amounts (integer cents)
	opening_principal_cents = Column(Integer, nullable=False)
	principal_due_cents = Column(Integer, nullable=False)
	interest_due_cents = Column(Integer, nullable=False)
	insurance_due_cents = Column(Integer, nullable=False, default=0)
	total_due_cents = Column(Integer, nullable=False)
	closing_principal_cents = Column(Integer, nullable=False)

	# Paid amounts (integer cents — updated by repayment engine)
	paid_principal_cents = Column(Integer, nullable=False, default=0)
	paid_interest_cents = Column(Integer, nullable=False, default=0)
	paid_total_cents = Column(Integer, nullable=False, default=0)
	paid_date = Column(Date, nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING/PARTIAL/PAID/OVERDUE/WAIVED",
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

	loan: Loan = relationship("Loan", back_populates="repayment_schedules", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<RepaymentSchedule loan={self.loan_id!r} "
			f"#{self.installment_number} due={self.due_date!r} status={self.status!r}>"
		)


# Register immutability enforcement after class definition
RepaymentSchedule._register_immutability()


# ---------------------------------------------------------------------------
# LoanRepayment  (IMMUTABLE — financial ledger)
# ---------------------------------------------------------------------------

class LoanRepayment(ImmutableRecordMixin, AuditMixin, Model):
	"""Individual repayment transaction — insert-only financial ledger.

	Waterfall allocation: penalty → interest → principal.
	Links back to core banking ledger via ledger_entry_id.

	IMMUTABLE: never UPDATE. To reverse, create a reversal entry.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_repayment"
	__table_args__ = (
		Index("ix_ln_repayment_loan", "loan_id"),
		Index("ix_ln_repayment_date", "payment_date"),
		Index("ix_ln_repayment_reference", "reference_number"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	payment_date = Column(Date, nullable=False)
	amount_cents = Column(Integer, nullable=False, comment="Total payment received in cents")

	# Waterfall allocation (integer cents)
	principal_applied_cents = Column(Integer, nullable=False)
	interest_applied_cents = Column(Integer, nullable=False)
	penalty_applied_cents = Column(Integer, nullable=False, default=0)
	fees_applied_cents = Column(Integer, nullable=False, default=0)

	source = Column(
		String(30),
		nullable=False,
		comment="STANDING_ORDER/MOBILE_MONEY/BRANCH/DIRECT_DEBIT/AGENT/SWEEP",
	)
	reference_number = Column(String(100), nullable=True)
	ledger_entry_id = Column(UUID(as_uuid=False), nullable=True, comment="Links to cb_ledger_entry")

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

	loan: Loan = relationship("Loan", back_populates="repayments", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<LoanRepayment loan={self.loan_id!r} "
			f"date={self.payment_date!r} amount={self.amount_cents}>"
		)


# Register immutability enforcement after class definition
LoanRepayment._register_immutability()


# ---------------------------------------------------------------------------
# CRITICAL 1 — GL Journal Entry (double-entry, immutable)
# ---------------------------------------------------------------------------

class LnGLJournalEntry(ImmutableRecordMixin, AuditMixin, Model):
	"""Double-entry GL journal line for lending events.

	Each economic event produces TWO rows (debit + credit) sharing an
	event_id.  The pair must balance: sum(amount_cents) grouped by event_id
	should equal zero when DR is positive and CR is negative.

	IMMUTABLE: never UPDATE posted entries.  Reversals create new offsetting rows.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_gl_journal_entry"
	__table_args__ = (
		# Idempotency: one DR and one CR leg per (event_id, leg_type)
		UniqueConstraint("event_id", "leg_type", name="uq_ln_gl_event_leg"),
		Index("ix_ln_gl_loan", "loan_id"),
		Index("ix_ln_gl_event_type", "event_type"),
		Index("ix_ln_gl_value_date", "value_date"),
		Index("ix_ln_gl_period", "period_id"),
		Index("ix_ln_gl_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="RESTRICT"),
		nullable=True,
		index=True,
		comment="NULL for facility/product-level entries",
	)

	# Event correlation — groups the DR+CR pair
	event_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Shared UUID for all legs of the same economic event",
	)
	event_type = Column(
		String(40),
		nullable=False,
		comment=(
			"DISBURSEMENT/REPAYMENT/INTEREST_ACCRUAL/FEE/WRITE_OFF/"
			"RECOVERY/PROVISION/REVERSAL/FX_REVALUATION"
		),
	)
	leg_type = Column(
		String(2),
		nullable=False,
		comment="DR or CR",
	)

	@property
	def leg(self) -> str:
		"""Alias for leg_type — short form used in tests and reports."""
		return self.leg_type

	# Account codes
	account_code = Column(String(30), nullable=False, comment="Chart-of-accounts code")
	account_name = Column(String(100), nullable=True)

	# Amount (always positive; leg_type determines DR/CR)
	amount_cents = Column(
		sa.BigInteger,
		nullable=False,
		comment="Always positive integer cents",
	)
	currency = Column(String(3), nullable=False, default="KES")

	# Period / date
	value_date = Column(Date, nullable=False)
	period_id = Column(
		String(7),
		nullable=False,
		comment="YYYY-MM accounting period",
	)

	# Posting metadata
	posted_by = Column(UUID(as_uuid=False), nullable=True)
	reversed_by = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_gl_journal_entry.id", ondelete="SET NULL"),
		nullable=True,
		comment="ID of the reversal entry that offsets this one",
	)
	status = Column(
		String(10),
		nullable=False,
		default="POSTED",
		comment="POSTED/REVERSED",
	)
	narration = Column(Text, nullable=True)

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
			f"<LnGLJournalEntry {self.event_type!r} {self.leg_type} "
			f"account={self.account_code!r} amount={self.amount_cents}>"
		)


LnGLJournalEntry._register_immutability()


# ---------------------------------------------------------------------------
# CRITICAL 2 — Fee Engine
# ---------------------------------------------------------------------------

class LoanFee(AuditMixin, Model):
	"""Fee schedule attached to a loan product.

	calculation_basis:
	  flat             → rate_or_amount_cents is the flat fee in cents
	  percent_principal → rate_or_amount_cents is basis points (* 0.01%) of original principal
	  percent_outstanding → rate_or_amount_cents is basis points of outstanding balance
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_fee"
	__table_args__ = (
		Index("ix_ln_fee_product", "product_id"),
		Index("ix_ln_fee_type", "fee_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_product.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	fee_type = Column(
		String(20),
		nullable=False,
		comment="origination/processing/late/prepayment/insurance/annual",
	)
	calculation_basis = Column(
		String(20),
		nullable=False,
		comment="flat/percent_principal/percent_outstanding",
	)
	# Flat fees in cents; percent fees in basis points (integer, /10000 = rate)
	rate_or_amount_cents = Column(
		sa.BigInteger,
		nullable=False,
		comment="Flat: cents.  Percent: basis points (100 bps = 1%)",
	)
	capitalisable = Column(Boolean, nullable=False, default=False)
	waivable = Column(Boolean, nullable=False, default=True)
	gl_account_code = Column(String(30), nullable=True)

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

	product: LoanProduct = relationship("LoanProduct", lazy="select")

	def __repr__(self) -> str:
		return f"<LoanFee product={self.product_id!r} type={self.fee_type!r}>"


class LoanFeeCharge(ImmutableRecordMixin, AuditMixin, Model):
	"""A computed fee charge instance applied to a specific loan.

	Immutable once posted.  Waivers create a zero-amount offsetting record.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_fee_charge"
	__table_args__ = (
		Index("ix_ln_fee_charge_loan", "loan_id"),
		Index("ix_ln_fee_charge_fee", "fee_id"),
		Index("ix_ln_fee_charge_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	fee_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_fee.id", ondelete="RESTRICT"),
		nullable=False,
	)
	fee_type = Column(String(20), nullable=False)
	amount_cents = Column(sa.BigInteger, nullable=False)
	status = Column(
		String(10),
		nullable=False,
		default="PENDING",
		comment="PENDING/PAID/WAIVED/CAPITALISED",
	)
	charge_date = Column(Date, nullable=False)
	waived_by = Column(UUID(as_uuid=False), nullable=True)
	waiver_reason = Column(Text, nullable=True)
	waived_at = Column(DateTime(timezone=True), nullable=True)
	gl_journal_event_id = Column(UUID(as_uuid=False), nullable=True)

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

	loan: Loan = relationship("Loan", lazy="select")
	fee: LoanFee = relationship("LoanFee", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<LoanFeeCharge loan={self.loan_id!r} type={self.fee_type!r} "
			f"amount={self.amount_cents} status={self.status!r}>"
		)


LoanFeeCharge._register_immutability()


# ---------------------------------------------------------------------------
# CRITICAL 3 — Interest Accrual Engine
# ---------------------------------------------------------------------------

class InterestAccrualEntry(ImmutableRecordMixin, AuditMixin, Model):
	"""Daily interest accrual line — one row per loan per accrual date.

	On NPA transition, status moves from 'accrued' → 'suspended' and GL
	entries reverse the receivable into the suspense account.
	Cash-basis recognition: on receipt, a 'reversed' entry offsets the
	suspended amount.

	IMMUTABLE: never UPDATE.  State changes produce new offsetting entries.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_interest_accrual"
	__table_args__ = (
		UniqueConstraint("loan_id", "accrual_date", name="uq_ln_accrual_loan_date"),
		Index("ix_ln_accrual_loan", "loan_id"),
		Index("ix_ln_accrual_date", "accrual_date"),
		Index("ix_ln_accrual_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	accrual_date = Column(Date, nullable=False)
	days = Column(Integer, nullable=False, default=1, comment="Days covered by this accrual")
	outstanding_principal_cents = Column(sa.BigInteger, nullable=False)
	rate = Column(
		Numeric(10, 8),
		nullable=False,
		comment="Daily rate = annual_rate / 365",
	)
	accrued_interest_cents = Column(sa.BigInteger, nullable=False)
	status = Column(
		String(10),
		nullable=False,
		default="accrued",
		comment="accrued/suspended/reversed",
	)
	gl_event_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="GL event_id for the paired DR/CR entries",
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

	loan: Loan = relationship("Loan", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<InterestAccrualEntry loan={self.loan_id!r} "
			f"date={self.accrual_date!r} amount={self.accrued_interest_cents} "
			f"status={self.status!r}>"
		)


InterestAccrualEntry._register_immutability()


# ---------------------------------------------------------------------------
# CRITICAL 4 — Reversal tracking on LoanRepayment
# (reversed_repayment_id column added via separate Column definition below)
# ---------------------------------------------------------------------------

# SQLAlchemy allows adding columns to existing mapped classes before first
# mapper configuration.  We attach reversed_repayment_id to LoanRepayment here.
LoanRepayment.repayment_type = Column(
	String(15),
	nullable=False,
	default="NORMAL",
	comment="NORMAL/REVERSAL",
)
LoanRepayment.reversed_repayment_id = Column(
	UUID(as_uuid=False),
	nullable=True,
	index=True,
	comment="FK to the original LoanRepayment this entry reverses",
)
LoanRepayment.reversal_reason = Column(Text, nullable=True)
LoanRepayment.reversed_by = Column(UUID(as_uuid=False), nullable=True)
LoanRepayment.approved_by = Column(
	UUID(as_uuid=False),
	nullable=True,
	comment="Dual-control: approver_id must differ from reversed_by",
)


# ---------------------------------------------------------------------------
# HIGH 1 — Standing Orders / Auto-Debit Mandates
# ---------------------------------------------------------------------------

class StandingOrder(AuditMixin, Model):
	"""Recurring auto-debit mandate for a loan repayment.

	amount_strategy:
	  fixed          → debit fixed_amount_cents each cycle
	  scheduled_emi  → debit the EMI amount from the next due schedule
	  minimum_due    → debit the minimum of all overdue instalments
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_standing_order"
	__table_args__ = (
		Index("ix_ln_so_loan", "loan_id"),
		Index("ix_ln_so_status", "status"),
		Index("ix_ln_so_execution_day", "execution_day"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	linked_account_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		comment="Source account to debit",
	)
	amount_strategy = Column(
		String(15),
		nullable=False,
		default="scheduled_emi",
		comment="fixed/scheduled_emi/minimum_due",
	)
	fixed_amount_cents = Column(
		sa.BigInteger,
		nullable=True,
		comment="Used only when amount_strategy=fixed",
	)
	execution_day = Column(
		Integer,
		nullable=False,
		comment="Day of month (1-28) to execute debit",
	)
	currency = Column(String(3), nullable=False, default="KES")
	valid_from = Column(Date, nullable=False)
	valid_to = Column(Date, nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE/SUSPENDED/CANCELLED/EXPIRED",
	)
	failure_retry_count = Column(Integer, nullable=False, default=0)
	max_retries = Column(Integer, nullable=False, default=3)
	last_executed_date = Column(Date, nullable=True)
	last_failure_reason = Column(Text, nullable=True)
	next_execution_date = Column(Date, nullable=True)

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

	loan: Loan = relationship("Loan", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<StandingOrder loan={self.loan_id!r} "
			f"strategy={self.amount_strategy!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# HIGH 2 — Batch Job Idempotency Guard
# ---------------------------------------------------------------------------

class BatchJobRun(Model):
	"""Idempotency guard for batch jobs.

	SELECT FOR UPDATE on (job_name, run_date) at the start of each batch.
	If status=completed, abort immediately.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_batch_job_run"
	__table_args__ = (
		UniqueConstraint("job_name", "run_date", name="uq_ln_batch_job_run"),
		Index("ix_ln_batch_job_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	job_name = Column(String(60), nullable=False)
	run_date = Column(Date, nullable=False)
	status = Column(
		String(10),
		nullable=False,
		default="running",
		comment="running/completed/failed",
	)
	started_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	records_processed = Column(Integer, nullable=False, default=0)
	error_detail = Column(Text, nullable=True)

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
		return f"<BatchJobRun {self.job_name!r} {self.run_date!r} {self.status!r}>"


# ---------------------------------------------------------------------------
# HIGH 3 — Credit Facility (revolving lines)
# ---------------------------------------------------------------------------

class CreditFacility(AuditMixin, Model):
	"""Revolving credit facility with utilisation tracking.

	available_balance_cents is decremented atomically on each drawdown
	using optimistic locking (version column).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_credit_facility"
	__table_args__ = (
		Index("ix_ln_cf_customer", "customer_id"),
		Index("ix_ln_cf_product", "product_id"),
		Index("ix_ln_cf_status", "status"),
		Index("ix_ln_cf_expiry", "expiry_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	customer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_product.id", ondelete="RESTRICT"),
		nullable=False,
	)
	approved_limit_cents = Column(sa.BigInteger, nullable=False)
	available_balance_cents = Column(sa.BigInteger, nullable=False)
	utilised_cents = Column(sa.BigInteger, nullable=False, default=0)
	expiry_date = Column(Date, nullable=False)
	review_date = Column(Date, nullable=True)
	currency = Column(String(3), nullable=False, default="KES")
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE/SUSPENDED/EXPIRED/CANCELLED",
	)
	# Optimistic lock version
	version = Column(Integer, nullable=False, default=0)

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
			f"<CreditFacility customer={self.customer_id!r} "
			f"limit={self.approved_limit_cents} avail={self.available_balance_cents}>"
		)


# ---------------------------------------------------------------------------
# HIGH 4 — Transactional Outbox (event durability)
# ---------------------------------------------------------------------------

class LnOutboxEvent(Model):
	"""Transactional outbox for durable event publishing.

	Written inside the same DB transaction as the state change.
	A separate relay process polls WHERE status='pending' and publishes
	to the message broker, then marks status='published'.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_outbox_event"
	__table_args__ = (
		Index("ix_ln_outbox_status", "status"),
		Index("ix_ln_outbox_aggregate", "aggregate_type", "aggregate_id"),
		Index("ix_ln_outbox_created", "created_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	aggregate_type = Column(String(40), nullable=False, comment="e.g. Loan, StandingOrder")
	aggregate_id = Column(UUID(as_uuid=False), nullable=False)
	event_type = Column(String(80), nullable=False, comment="e.g. ln.loan.disbursed")
	payload_json = Column(JSONB, nullable=False, default=dict, server_default="{}")
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	published_at = Column(DateTime(timezone=True), nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="pending",
		comment="pending/published/failed",
	)
	retry_count = Column(Integer, nullable=False, default=0)
	error_detail = Column(Text, nullable=True)

	def __repr__(self) -> str:
		return f"<LnOutboxEvent {self.event_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# HIGH 4b — Loan Notification (borrower / ops alerting)
# ---------------------------------------------------------------------------

class LoanNotification(Model):
	"""Borrower and ops-team notification record with delivery tracking."""

	__allow_unmapped__ = True
	__tablename__ = "ln_notification"
	__table_args__ = (
		Index("ix_ln_notif_loan", "loan_id"),
		Index("ix_ln_notif_status", "status"),
		Index("ix_ln_notif_scheduled", "scheduled_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	notification_type = Column(String(40), nullable=False)
	channel = Column(
		String(10),
		nullable=False,
		comment="sms/email/push/in_app",
	)
	recipient = Column(String(200), nullable=False)
	payload_json = Column(JSONB, nullable=False, default=dict, server_default="{}")
	scheduled_at = Column(DateTime(timezone=True), nullable=False)
	sent_at = Column(DateTime(timezone=True), nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="pending",
		comment="pending/sent/failed/cancelled",
	)
	provider_ref = Column(String(200), nullable=True)
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
			f"<LoanNotification loan={self.loan_id!r} "
			f"type={self.notification_type!r} channel={self.channel!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# HIGH 5 — AML Screening Result (immutable audit record)
# ---------------------------------------------------------------------------

class LnAMLScreeningResult(ImmutableRecordMixin, AuditMixin, Model):
	"""AML / sanctions screening result — immutable audit trail.

	status:
	  clear   → proceed with disbursement
	  review  → hold in PENDING_AML_REVIEW, awaiting compliance officer
	  blocked → reject disbursement, flag for SAR
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_aml_screening"
	__table_args__ = (
		Index("ix_ln_aml_loan", "loan_id"),
		Index("ix_ln_aml_status", "status"),
		Index("ix_ln_aml_screened_at", "screened_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="RESTRICT"),
		nullable=True,
		index=True,
		comment="NULL for application-stage KYC screens",
	)
	application_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_application.id", ondelete="RESTRICT"),
		nullable=True,
		index=True,
	)
	customer_id = Column(UUID(as_uuid=False), nullable=False)
	amount_cents = Column(sa.BigInteger, nullable=True)
	counterparty_account = Column(String(100), nullable=True)
	screened_at = Column(DateTime(timezone=True), nullable=False)
	provider = Column(String(50), nullable=False, default="internal")
	status = Column(
		String(10),
		nullable=False,
		comment="clear/review/blocked",
	)
	risk_score = Column(Integer, nullable=True)
	hit_details_json = Column(JSONB, nullable=True)

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
			f"<LnAMLScreeningResult loan={self.loan_id!r} "
			f"status={self.status!r} score={self.risk_score}>"
		)


LnAMLScreeningResult._register_immutability()


# ---------------------------------------------------------------------------
# HIGH 6 — Fraud Signal
# ---------------------------------------------------------------------------

class LnFraudSignal(ImmutableRecordMixin, AuditMixin, Model):
	"""Fraud score and behavioural signal captured at origination or repayment.

	action:
	  allow     → proceed normally
	  step_up   → require additional authentication before proceeding
	  decline   → reject the operation
	"""

	__allow_unmapped__ = True
	__tablename__ = "ln_fraud_signal"
	__table_args__ = (
		Index("ix_ln_fraud_loan", "loan_id"),
		Index("ix_ln_fraud_action", "action"),
		Index("ix_ln_fraud_captured", "captured_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	loan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_loan.id", ondelete="RESTRICT"),
		nullable=True,
		index=True,
	)
	application_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ln_application.id", ondelete="RESTRICT"),
		nullable=True,
		index=True,
	)
	signal_source = Column(String(60), nullable=False, comment="Provider name or internal")
	signal_type = Column(
		String(25),
		nullable=False,
		comment="device_fingerprint/velocity/synthetic_identity/account_takeover",
	)
	score = Column(Integer, nullable=False, comment="0–1000, higher = riskier")
	threshold = Column(Integer, nullable=False, comment="Score above which action triggers")
	action = Column(
		String(10),
		nullable=False,
		comment="allow/step_up/decline",
	)
	captured_at = Column(DateTime(timezone=True), nullable=False)
	raw_payload_json = Column(JSONB, nullable=True)

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
			f"<LnFraudSignal loan={self.loan_id!r} "
			f"type={self.signal_type!r} score={self.score} action={self.action!r}>"
		)


LnFraudSignal._register_immutability()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LoanProduct",
	"LoanApplication",
	"Collateral",
	"Loan",
	"RepaymentSchedule",
	"LoanRepayment",
	# CRITICAL additions
	"LnGLJournalEntry",
	"LoanFee",
	"LoanFeeCharge",
	"InterestAccrualEntry",
	# HIGH additions
	"StandingOrder",
	"BatchJobRun",
	"CreditFacility",
	"LnOutboxEvent",
	"LoanNotification",
	"LnAMLScreeningResult",
	"LnFraudSignal",
]
