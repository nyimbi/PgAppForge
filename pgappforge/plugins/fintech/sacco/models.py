"""
pgappforge/plugins/fintech/sacco/models.py

SACCO / MFI / Chama data layer.

Design rules enforced:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents — never Decimal/float in storage
  - Dividend: ImmutableRecordMixin (insert-only, no UPDATE)
  - JSONB for semi-structured attributes (address, rules, guarantees, etc.)

Table name convention: sc_<entity>

Depends on:
  fintech.core_banking  — cb_account (share/deposit/group accounts)
  erp.foundation        — erp_party (members / chairpersons)
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# SACCO — Savings and Credit Co-operative Organisation
# ---------------------------------------------------------------------------

class SACCO(AuditMixin, Model):
	"""SACCO institution record.

	sacco_type discriminates regulatory regime and permitted activities:
	  DEPOSIT_TAKING   — licensed to take deposits from the public (FOSA arm)
	  NON_DEPOSIT_TAKING — back-office only (BOSA arm), no public deposits
	  FOSA             — Front Office Service Activity (deposit-taking branch of a BOSA SACCO)

	regulator:
	  SASRA  — Kenya (Sacco Societies Regulatory Authority)
	  UCSCU  — Uganda Co-operative Savings & Credit Union
	  CRDB   — Tanzania
	  ACCOSCA — Pan-African

	common_bond describes the eligibility criterion:
	  e.g. "Teachers in Nairobi County", "Employees of ABC Ltd", "Members of XYZ Church"

	All monetary aggregates are INTEGER cents — updated by nightly batch reconciliation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_sacco"
	__table_args__ = (
		UniqueConstraint("registration_number", name="uq_sc_sacco_reg_number"),
		Index("ix_sc_sacco_tenant", "tenant_id"),
		Index("ix_sc_sacco_type", "sacco_type"),
		Index("ix_sc_sacco_regulator", "regulator"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	registration_number = Column(
		String(50),
		unique=True,
		nullable=False,
		comment="Official registration number (e.g. CS/SACCO/001/2010)",
	)
	name = Column(String(200), nullable=False)
	sacco_type = Column(
		String(30),
		nullable=False,
		default="DEPOSIT_TAKING",
		comment="DEPOSIT_TAKING | NON_DEPOSIT_TAKING | FOSA",
	)
	regulator = Column(
		String(50),
		nullable=False,
		default="SASRA",
		comment="SASRA (Kenya) | UCSCU (Uganda) | CRDB (Tanzania) | ACCOSCA",
	)
	license_number = Column(String(50), nullable=True)
	license_expiry_date = Column(Date, nullable=True)

	# Common bond — what members share
	common_bond = Column(
		String(100),
		nullable=True,
		comment="e.g. 'Employees of ABC Ltd' / 'Teachers, Nairobi County'",
	)

	# Structured common bond eligibility rules (JSONB)
	# e.g. {"type": "EMPLOYER", "values": ["SAFARICOM", "KCB"]}
	# NOTE: This column was added in migration 2026-06-11. If the column is absent,
	# run: ALTER TABLE sc_sacco ADD COLUMN common_bond_rules JSONB NOT NULL DEFAULT '{}';
	common_bond_rules: dict[str, Any] = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
		comment=(
			"Structured eligibility rules: "
			"{type: EMPLOYER|REGION|PROFESSION, values: [...]}"
		),
	)

	# Aggregate statistics (updated by nightly batch — NOT transactional source of truth)
	membership_count = Column(Integer, nullable=False, default=0)
	total_shares_cents = Column(
		Integer, nullable=False, default=0,
		comment="Sum of all member share values in cents",
	)
	total_deposits_cents = Column(
		Integer, nullable=False, default=0,
		comment="Total FOSA/BOSA deposits in cents",
	)
	total_loans_outstanding_cents = Column(
		Integer, nullable=False, default=0,
		comment="Outstanding loan book in cents",
	)
	reserve_fund_cents = Column(
		Integer, nullable=False, default=0,
		comment="Statutory reserve fund in cents (typically 20% of surplus)",
	)

	# Regulatory ratios (updated by batch — stored as Numeric for display only)
	institutional_capital_pct = Column(
		Numeric(5, 2), nullable=False, default=0,
		comment="Institutional capital as % of total assets (SASRA min 8%)",
	)
	delinquency_rate_pct = Column(
		Numeric(5, 2), nullable=False, default=0,
		comment="Loan delinquency rate % (SASRA max 5%)",
	)

	address: dict[str, Any] = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
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
	members: list[Member] = relationship(
		"Member", back_populates="sacco", lazy="select",
	)
	loan_products: list[SACCOLoanProduct] = relationship(
		"SACCOLoanProduct", back_populates="sacco", lazy="select",
	)
	dividends: list[Dividend] = relationship(
		"Dividend", back_populates="sacco", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SACCO {self.registration_number!r} {self.name!r} type={self.sacco_type!r}>"


# ---------------------------------------------------------------------------
# Member — SACCO membership record
# ---------------------------------------------------------------------------

class Member(AuditMixin, Model):
	"""SACCO member.

	Links an erp_party (individual / corporate) to a SACCO via a membership number.
	Each member has two core accounts in the core_banking system:
	  share_account_id   — tracks share capital (cb_account)
	  deposit_account_id — tracks savings/deposits (cb_account)

	guarantees_given: JSONB list of loan IDs this member has guaranteed.
	Kept as JSONB for flexibility; the service layer keeps guarantees_active_cents
	in sync for quick eligibility checks.

	Membership status FSM:
	  ACTIVE → SUSPENDED (non-compliance) → ACTIVE
	  ACTIVE → WITHDRAWN (voluntary) → [terminal]
	  ACTIVE → DECEASED  → [terminal]
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_member"
	__table_args__ = (
		UniqueConstraint("member_number", name="uq_sc_member_number"),
		Index("ix_sc_member_sacco", "sacco_id"),
		Index("ix_sc_member_party", "party_id"),
		Index("ix_sc_member_status", "membership_status"),
		Index("ix_sc_member_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	member_number = Column(
		String(30), unique=True, nullable=False,
		comment="Human-readable member ID e.g. SACCO/2018/00142",
	)
	sacco_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_sacco.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False, index=True,
		comment="FK to foundation Party (individual or corporate member)",
	)

	membership_date = Column(Date, nullable=False)
	membership_status = Column(
		String(20), nullable=False, default="ACTIVE",
		comment="ACTIVE | SUSPENDED | WITHDRAWN | DECEASED",
	)

	# Core banking account links (nullable — created on membership activation)
	share_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id", ondelete="SET NULL"),
		nullable=True,
		comment="cb_account tracking this member's share capital",
	)
	deposit_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id", ondelete="SET NULL"),
		nullable=True,
		comment="cb_account tracking this member's FOSA/savings deposits",
	)

	# Share capital
	shares_held = Column(
		Integer, nullable=False, default=0,
		comment="Number of share units held",
	)
	share_value_cents = Column(
		Integer, nullable=False, default=10000,
		comment="Par value per share in cents (e.g. 10000 = KES 100.00)",
	)
	total_shares_value_cents = Column(
		Integer, nullable=False, default=0,
		comment="shares_held × share_value_cents — denormalised for fast queries",
	)

	# Monthly contribution obligation
	monthly_contribution_cents = Column(
		Integer, nullable=False, default=0,
		comment="Contractual monthly savings contribution in cents",
	)

	# FOSA deposit balance (maintained by FOSABridgeService)
	fosa_balance_cents = Column(
		Integer, nullable=False, default=0,
		comment="Member FOSA deposit balance in cents (synced from SaccoLedgerEntry)",
	)

	# Payroll deduction flags (set by HCM integration)
	payroll_deduction_enabled = Column(
		Boolean, nullable=False, default=False,
		comment="True if member has authorised payroll deduction for SACCO contributions",
	)

	# Guarantor exposure
	guarantees_given: list = Column(
		JSONB, nullable=False, default=list, server_default="[]",
		comment="List of loan IDs this member has guaranteed",
	)
	guarantees_active_cents = Column(
		Integer, nullable=False, default=0,
		comment="Total outstanding value of active guarantees in cents",
	)

	# Dividend / distribution
	dividend_account = Column(
		String(30), nullable=True,
		comment="Account number to credit dividend payments",
	)

	# Exit information
	exit_date = Column(Date, nullable=True)
	exit_reason = Column(Text, nullable=True)
	withdrawal_balance_cents = Column(
		Integer, nullable=False, default=0,
		comment="Amount payable to member upon exit (shares + deposits - loans - holds)",
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
	sacco: SACCO = relationship("SACCO", back_populates="members", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Member {self.member_number!r} "
			f"sacco={self.sacco_id!r} "
			f"status={self.membership_status!r} "
			f"shares={self.shares_held}>"
		)


# ---------------------------------------------------------------------------
# SACCOLoanProduct — product catalogue for SACCO lending
# ---------------------------------------------------------------------------

class SACCOLoanProduct(AuditMixin, Model):
	"""SACCO-specific loan product.

	SACCO lending differs from commercial banking in key ways:
	  1. Loan limits are multiples of a member's deposits/shares (max_multiple_of_savings).
	  2. Guarantors must cover a % of the loan with their own shares.
	  3. Lower rates (typically 1% per month = 12% p.a. reducing balance).

	loan_type covers the East African SACCO product taxonomy:
	  DEVELOPMENT    — general development / long-term (e.g. housing, business)
	  EMERGENCY      — quick-turnaround personal emergency
	  SCHOOL_FEES    — school fees advance, repaid over school terms
	  ASSET          — asset acquisition (vehicle, equipment)
	  AGRI           — agricultural seasonal loan
	  MICRO          — micro-enterprise / group lending
	  SALARY_ADVANCE — payslip-backed advance; auto-deducted from payroll

	guarantor_coverage_pct: guarantors must collectively cover X% of loan
	  value with their eligible savings/shares as collateral.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_loan_product"
	__table_args__ = (
		Index("ix_sc_lp_sacco", "sacco_id"),
		Index("ix_sc_lp_type", "loan_type"),
		Index("ix_sc_lp_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	sacco_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_sacco.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	product_name = Column(String(100), nullable=False)
	loan_type = Column(
		String(30), nullable=False,
		comment=(
			"DEVELOPMENT | EMERGENCY | SCHOOL_FEES | ASSET | "
			"AGRI | MICRO | SALARY_ADVANCE"
		),
	)

	# Loan limit = member's eligible savings × max_multiple_of_savings
	max_multiple_of_savings = Column(
		Numeric(4, 1), nullable=False, default=3,
		comment="Max loan = member eligible savings × this multiplier",
	)
	max_amount_cents = Column(
		Integer, nullable=True,
		comment="Absolute cap in cents (NULL = no cap beyond the savings multiple)",
	)

	# Pricing
	interest_rate_pa = Column(
		Numeric(10, 6), nullable=False,
		comment="Annual interest rate e.g. 0.120000 = 12% p.a.",
	)
	max_tenor_months = Column(Integer, nullable=False)
	processing_fee_pct = Column(
		Numeric(5, 2), nullable=False, default=1,
		comment="Processing fee as % of loan amount",
	)

	# Guarantor requirements
	requires_guarantors = Column(Boolean, nullable=False, default=True)
	min_guarantors = Column(Integer, nullable=False, default=2)
	guarantor_coverage_pct = Column(
		Numeric(5, 2), nullable=False, default=100,
		comment=(
			"Guarantors must collectively cover this % of the loan "
			"value with their eligible shares/savings"
		),
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

	# Relationships
	sacco: SACCO = relationship("SACCO", back_populates="loan_products", lazy="select")

	def __repr__(self) -> str:
		return f"<SACCOLoanProduct {self.product_name!r} type={self.loan_type!r}>"


# ---------------------------------------------------------------------------
# Dividend — annual surplus distribution (IMMUTABLE)
# ---------------------------------------------------------------------------

class Dividend(ImmutableRecordMixin, AuditMixin, Model):
	"""SACCO dividend / interest rebate declaration.

	IMMUTABLE — once a dividend is declared it cannot be altered.
	To correct a declared dividend, mark it CANCELLED and create a new record.

	dividend_rate_pct: rate applied to member's share capital
	  (e.g. 12.00 = 12% of shares held)

	interest_rebate_pct: rebate applied to interest paid by borrowers
	  (refund of excess interest after cost of funds; common in co-operatives)

	total_dividend_pool_cents: total amount to be distributed (authorised by AGM).
	  The service layer distributes this proportionally to eligible members.

	Status FSM: DECLARED → PAID
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_dividend"
	__table_args__ = (
		UniqueConstraint("sacco_id", "financial_year", name="uq_sc_dividend_sacco_year"),
		Index("ix_sc_dividend_sacco", "sacco_id"),
		Index("ix_sc_dividend_year", "financial_year"),
		Index("ix_sc_dividend_status", "status"),
		Index("ix_sc_dividend_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	sacco_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_sacco.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	financial_year = Column(
		Integer, nullable=False,
		comment="4-digit financial year e.g. 2024",
	)
	dividend_rate_pct = Column(
		Numeric(5, 2), nullable=False,
		comment="Dividend rate applied to member share capital (percent)",
	)
	interest_rebate_pct = Column(
		Numeric(5, 2), nullable=False, default=0,
		comment="Interest rebate as % of interest paid by borrowing members",
	)
	total_dividend_pool_cents = Column(
		Integer, nullable=False,
		comment="AGM-approved total pool for distribution in cents",
	)
	approved_date = Column(Date, nullable=False)
	payment_date = Column(Date, nullable=True)
	status = Column(
		String(20), nullable=False, default="DECLARED",
		comment="DECLARED | PAID | CANCELLED",
	)

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
	sacco: SACCO = relationship("SACCO", back_populates="dividends", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Dividend sacco={self.sacco_id!r} "
			f"year={self.financial_year} "
			f"rate={self.dividend_rate_pct}% "
			f"status={self.status!r}>"
		)


# Register immutability guard after class is fully defined
Dividend._register_immutability()


# ---------------------------------------------------------------------------
# Chama — savings group / investment club
# ---------------------------------------------------------------------------

class Chama(AuditMixin, Model):
	"""Informal savings group (Chama / table-banking / merry-go-round).

	chama_type governs the distribution mechanism:
	  MERRY_GO_ROUND  — pool rotates to one member per cycle
	  TABLE_BANKING   — pool is lent out at interest; members share profits
	  INVESTMENT_CLUB — pool invested in assets / securities
	  WELFARE_GROUP   — mutual aid (funerals, medical, etc.)

	meeting_frequency: WEEKLY | BIWEEKLY | MONTHLY | QUARTERLY

	contribution_amount_cents: fixed contribution per meeting per member.
	  For table_banking this is also the minimum lending unit.

	current_pool_cents: running total of undistributed funds.
	  Updated by record_contribution and process_merry_go_round.

	rules JSONB: flexible policy storage
	  {late_penalty_pct, absentee_penalty_cents, loan_interest_rate_pw,
	   max_loan_weeks, quorum_pct, ...}
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_chama"
	__table_args__ = (
		Index("ix_sc_chama_tenant", "tenant_id"),
		Index("ix_sc_chama_type", "chama_type"),
		Index("ix_sc_chama_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	chama_name = Column(String(200), nullable=False)
	chama_type = Column(
		String(30), nullable=False, default="MERRY_GO_ROUND",
		comment="MERRY_GO_ROUND | TABLE_BANKING | INVESTMENT_CLUB | WELFARE_GROUP",
	)
	formation_date = Column(Date, nullable=False)
	meeting_frequency = Column(
		String(20), nullable=False, default="MONTHLY",
		comment="WEEKLY | BIWEEKLY | MONTHLY | QUARTERLY",
	)

	contribution_amount_cents = Column(
		Integer, nullable=False,
		comment="Fixed contribution per member per meeting in cents",
	)
	current_pool_cents = Column(
		Integer, nullable=False, default=0,
		comment="Undistributed pool in cents",
	)

	# Linked bank account in core_banking (optional)
	group_account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id", ondelete="SET NULL"),
		nullable=True,
		comment="cb_account for group funds",
	)

	# Office bearers (FK to erp_party)
	chairperson_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
	)
	treasurer_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
	)
	secretary_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
	)

	# Governance rules
	rules: dict[str, Any] = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
		comment=(
			"Governance rules: {late_penalty_pct, absentee_penalty_cents, "
			"loan_interest_rate_pw, max_loan_weeks, quorum_pct}"
		),
	)

	status = Column(
		String(20), nullable=False, default="ACTIVE",
		comment="ACTIVE | DORMANT | DISSOLVED",
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
	chama_members: list[ChamaMember] = relationship(
		"ChamaMember", back_populates="chama",
		cascade="all, delete-orphan", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Chama {self.chama_name!r} type={self.chama_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ChamaMember — individual participation in a Chama
# ---------------------------------------------------------------------------

class ChamaMember(AuditMixin, Model):
	"""Individual member's participation in a Chama.

	total_contributed_cents: cumulative sum of all contributions made.
	total_received_cents:    cumulative payouts received (merry-go-round disbursements).

	is_current_recipient: flags the member currently due for a merry-go-round payout.
	  The service layer rotates this flag after each successful payout.

	contribution_streak: consecutive meeting cycles where contribution was made.
	  Governs eligibility for table-banking loans (e.g. must have 3 consecutive months).
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_chama_member"
	__table_args__ = (
		UniqueConstraint("chama_id", "member_id", name="uq_sc_chama_member"),
		Index("ix_sc_chama_member_chama", "chama_id"),
		Index("ix_sc_chama_member_party", "member_id"),
		Index("ix_sc_chama_member_recipient", "is_current_recipient"),
		Index("ix_sc_chama_member_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	chama_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_chama.id", ondelete="CASCADE"),
		nullable=False, index=True,
	)
	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False, index=True,
		comment="FK to foundation Party",
	)
	join_date = Column(Date, nullable=False)

	total_contributed_cents = Column(
		Integer, nullable=False, default=0,
		comment="Cumulative contributions made by this member in cents",
	)
	total_received_cents = Column(
		Integer, nullable=False, default=0,
		comment="Cumulative merry-go-round payouts received in cents",
	)

	is_current_recipient = Column(
		Boolean, nullable=False, default=False,
		comment="True for the member currently due for merry-go-round payout",
	)
	contribution_streak = Column(
		Integer, nullable=False, default=0,
		comment="Consecutive meeting cycles with on-time contribution",
	)

	status = Column(
		String(20), nullable=False, default="ACTIVE",
		comment="ACTIVE | SUSPENDED | EXITED",
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
	chama: Chama = relationship("Chama", back_populates="chama_members", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ChamaMember chama={self.chama_id!r} "
			f"member={self.member_id!r} "
			f"contributed={self.total_contributed_cents}c "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# CRITICAL GAP 1 — Fee and Charge Engine models
# ---------------------------------------------------------------------------

class FeeCharge(AuditMixin, Model):
	"""Fee definition attached to a SACCO loan or savings product.

	fee_type:
	  FLAT                — fixed amount regardless of principal
	  PERCENT_DISBURSEMENT — % of loan disbursement amount (processing fee)
	  PERCENT_OUTSTANDING  — % of outstanding balance (insurance / management fee)
	  TIERED               — amount determined by a tier table in amount_or_rate JSONB

	collection_trigger:
	  DISBURSEMENT — deducted at loan origination
	  MONTHLY      — charged on each monthly repayment
	  ANNUAL       — charged once per year on loan anniversary
	  EVENT        — charged when a named event fires (e.g. late payment)

	amount_or_rate: for FLAT = cents; for PERCENT_* = basis points (100 = 1%);
	  for TIERED = JSONB list [{min_cents, max_cents, fee_cents}, …]
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_fee_charge"
	__table_args__ = (
		Index("ix_sc_fee_product", "product_id"),
		Index("ix_sc_fee_type", "fee_type"),
		Index("ix_sc_fee_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	# Links to either a loan product or NULL for SACCO-wide fees
	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_loan_product.id", ondelete="CASCADE"),
		nullable=True, index=True,
		comment="NULL = SACCO-wide fee; set = product-specific",
	)
	fee_name = Column(String(100), nullable=False)
	fee_type = Column(
		String(30), nullable=False,
		comment="FLAT | PERCENT_DISBURSEMENT | PERCENT_OUTSTANDING | TIERED",
	)
	amount_or_rate = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
		comment="cents for FLAT; bps for PERCENT_*; tier list for TIERED",
	)
	collection_trigger = Column(
		String(20), nullable=False, default="DISBURSEMENT",
		comment="DISBURSEMENT | MONTHLY | ANNUAL | EVENT",
	)
	event_name = Column(
		String(100), nullable=True,
		comment="For EVENT trigger: the event name that fires this fee",
	)
	waivable = Column(Boolean, nullable=False, default=False)
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
		return f"<FeeCharge {self.fee_name!r} type={self.fee_type!r} trigger={self.collection_trigger!r}>"


class FeeLineItem(AuditMixin, Model):
	"""Immutable record of a fee charged against a member transaction.

	Each row is INSERT-only.  fee_waived records manual waivers with reason.
	gl_posted tracks whether this fee has been written to the GL.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_fee_line_item"
	__table_args__ = (
		Index("ix_sc_fli_member", "member_id"),
		Index("ix_sc_fli_loan", "loan_id"),
		Index("ix_sc_fli_fee", "fee_charge_id"),
		Index("ix_sc_fli_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_member.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	loan_id = Column(
		UUID(as_uuid=False),
		nullable=True, index=True,
		comment="NULL for non-loan fees (e.g. account maintenance)",
	)
	fee_charge_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_fee_charge.id", ondelete="RESTRICT"),
		nullable=False,
	)
	amount_cents = Column(Integer, nullable=False, comment="Fee amount in cents (always positive)")
	currency = Column(String(3), nullable=False, default="KES")
	charge_date = Column(Date, nullable=False)
	collection_trigger = Column(String(20), nullable=False)
	fee_waived = Column(Boolean, nullable=False, default=False)
	waiver_reason = Column(Text, nullable=True)
	waived_by = Column(String(64), nullable=True)
	gl_posted = Column(Boolean, nullable=False, default=False)
	transaction_ref = Column(String(100), nullable=True)

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
		return f"<FeeLineItem member={self.member_id!r} amount={self.amount_cents}c waived={self.fee_waived}>"


# ---------------------------------------------------------------------------
# CRITICAL GAP 2 — Transaction Reversal models
# ---------------------------------------------------------------------------

class SaccoLedgerEntry(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable double-entry ledger row for SACCO member transactions.

	Every monetary event (contribution, loan disbursement, repayment, dividend,
	fee) inserts a SaccoLedgerEntry.  Reversals insert a mirror entry with negated
	amount and point original.reversed_by → reversal.id.

	entry_type:
	  CONTRIBUTION | LOAN_DISBURSEMENT | LOAN_REPAYMENT | DIVIDEND |
	  FEE | REVERSAL | ADJUSTMENT | WITHDRAWAL | TRANSFER

	dr_account / cr_account use the SACCO chart-of-accounts codes:
	  1010 — Member Savings (liability)
	  1020 — Member Shares (equity)
	  2010 — Loans Receivable (asset)
	  3010 — Interest Income
	  3020 — Fee Income
	  4010 — Dividend Expense
	  5010 — Cash / Mobile Money
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_ledger_entry"
	__table_args__ = (
		Index("ix_sc_le_member", "member_id"),
		Index("ix_sc_le_entry_type", "entry_type"),
		Index("ix_sc_le_value_date", "value_date"),
		Index("ix_sc_le_reversed_by", "reversed_by"),
		Index("ix_sc_le_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_member.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	entry_type = Column(
		String(30), nullable=False,
		comment=(
			"CONTRIBUTION | LOAN_DISBURSEMENT | LOAN_REPAYMENT | "
			"DIVIDEND | FEE | REVERSAL | ADJUSTMENT | WITHDRAWAL | TRANSFER"
		),
	)
	amount_cents = Column(
		Integer, nullable=False,
		comment="Signed: positive = credit to member, negative = debit from member",
	)
	currency = Column(String(3), nullable=False, default="KES")
	dr_account = Column(String(20), nullable=False, comment="Debit account code")
	cr_account = Column(String(20), nullable=False, comment="Credit account code")
	running_balance_cents = Column(
		Integer, nullable=False, default=0,
		comment="Member deposit running balance after this entry",
	)
	value_date = Column(Date, nullable=False)
	narrative = Column(Text, nullable=True)
	transaction_ref = Column(String(100), nullable=True, index=True)

	# Reversal linkage — both fields are NULL on non-reversed/non-reversal entries
	reversed_by = Column(
		UUID(as_uuid=False), nullable=True, index=True,
		comment="ID of the reversal SaccoLedgerEntry that negates this row",
	)
	reverses = Column(
		UUID(as_uuid=False), nullable=True,
		comment="ID of the original SaccoLedgerEntry this row reverses",
	)
	reversal_reason = Column(Text, nullable=True)
	reversed_by_user = Column(String(64), nullable=True)

	extra: dict[str, Any] = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
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
			f"<SaccoLedgerEntry member={self.member_id!r} type={self.entry_type!r} "
			f"amount={self.amount_cents}c date={self.value_date}>"
		)


# ---------------------------------------------------------------------------
# CRITICAL GAP 3 — Loan Repayment Schedule
# ---------------------------------------------------------------------------

class LoanRepaymentSchedule(AuditMixin, Model):
	"""Amortisation schedule row generated at loan origination.

	One row per installment.  The row is INSERT-only at origination; the
	service marks paid_cents as each repayment is processed.

	method:
	  FLAT             — equal total payment each period (interest on original principal)
	  REDUCING_BALANCE — interest on outstanding balance (annuity / French amortisation)
	  RULE_OF_78       — actuarial sum-of-digits front-loading
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_loan_repayment_schedule"
	__table_args__ = (
		Index("ix_sc_lrs_loan", "loan_id"),
		Index("ix_sc_lrs_due_date", "due_date"),
		Index("ix_sc_lrs_status", "status"),
		Index("ix_sc_lrs_tenant", "tenant_id"),
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
		nullable=False, index=True,
		comment="References the loan record (application-level reference)",
	)
	installment_number = Column(Integer, nullable=False, comment="1-based sequence number")
	due_date = Column(Date, nullable=False)
	method = Column(
		String(20), nullable=False,
		comment="FLAT | REDUCING_BALANCE | RULE_OF_78",
	)

	# Amounts due
	principal_due_cents = Column(Integer, nullable=False, default=0)
	interest_due_cents = Column(Integer, nullable=False, default=0)
	fees_due_cents = Column(Integer, nullable=False, default=0)
	total_due_cents = Column(Integer, nullable=False, default=0)

	# Opening balance before this installment
	balance_before_cents = Column(Integer, nullable=False, default=0)
	# Expected balance after payment
	balance_after_cents = Column(Integer, nullable=False, default=0)

	# Payment tracking
	paid_principal_cents = Column(Integer, nullable=False, default=0)
	paid_interest_cents = Column(Integer, nullable=False, default=0)
	paid_fees_cents = Column(Integer, nullable=False, default=0)
	paid_date = Column(Date, nullable=True)

	status = Column(
		String(20), nullable=False, default="PENDING",
		comment="PENDING | PARTIAL | PAID | OVERDUE | WAIVED",
	)
	days_past_due = Column(Integer, nullable=False, default=0)

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
			f"<LoanRepaymentSchedule loan={self.loan_id!r} "
			f"#{self.installment_number} due={self.due_date} "
			f"total={self.total_due_cents}c status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# HIGH GAP 1 — Standing Orders / Auto-Debit Instructions
# ---------------------------------------------------------------------------

class SaccoStandingOrder(AuditMixin, Model):
	"""Recurring payment instruction for a SACCO member.

	instruction_type:
	  SAVINGS_CONTRIBUTION — periodic savings deposit
	  LOAN_REPAYMENT       — automatic loan instalment debit
	  SHARE_PURCHASE       — periodic share acquisition

	frequency:
	  WEEKLY | MONTHLY | QUARTERLY

	source_account / destination_account: references to cb_account IDs or
	  external account strings (for mobile money debit).

	After max_failures consecutive execution failures the order is SUSPENDED
	and a notification is sent to the member.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_standing_order"
	__table_args__ = (
		Index("ix_sc_so_member", "member_id"),
		Index("ix_sc_so_next_exec", "next_execution_date"),
		Index("ix_sc_so_status", "status"),
		Index("ix_sc_so_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_member.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	instruction_type = Column(
		String(30), nullable=False,
		comment="SAVINGS_CONTRIBUTION | LOAN_REPAYMENT | SHARE_PURCHASE",
	)
	amount_cents = Column(Integer, nullable=False, comment="Fixed debit amount per execution")
	currency = Column(String(3), nullable=False, default="KES")
	frequency = Column(
		String(15), nullable=False,
		comment="WEEKLY | MONTHLY | QUARTERLY",
	)
	next_execution_date = Column(Date, nullable=False)
	source_account = Column(
		String(100), nullable=False,
		comment="cb_account ID or mobile money reference for debit",
	)
	destination_account = Column(
		String(100), nullable=True,
		comment="Target account (e.g. loan_id for repayments)",
	)
	max_failures = Column(Integer, nullable=False, default=3)
	failure_count = Column(Integer, nullable=False, default=0)
	last_run_date = Column(Date, nullable=True)
	last_run_status = Column(
		String(20), nullable=True,
		comment="SUCCESS | FAILED | SKIPPED",
	)
	last_failure_reason = Column(Text, nullable=True)
	status = Column(
		String(20), nullable=False, default="ACTIVE",
		comment="ACTIVE | SUSPENDED | CANCELLED | COMPLETED",
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
			f"<SaccoStandingOrder member={self.member_id!r} "
			f"type={self.instruction_type!r} "
			f"amount={self.amount_cents}c "
			f"next={self.next_execution_date} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# HIGH GAP 2 — Batch Job / End-of-Day Processing
# ---------------------------------------------------------------------------

class BatchRunLog(AuditMixin, Model):
	"""Idempotency log for batch job steps.

	A (run_date, job_type, sacco_id) triple is unique — re-running the batch
	on the same date is safe because the service checks for an existing COMPLETED
	row before executing.

	job_type:
	  ACCRUE_SAVINGS_INTEREST | ACCRUE_LOAN_INTEREST |
	  CHARGE_OVERDUE_PENALTIES | CHECK_DORMANCY | EOD_RECONCILIATION
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_batch_run_log"
	__table_args__ = (
		UniqueConstraint("run_date", "job_type", "sacco_id", name="uq_sc_brl_run"),
		Index("ix_sc_brl_run_date", "run_date"),
		Index("ix_sc_brl_job_type", "job_type"),
		Index("ix_sc_brl_sacco", "sacco_id"),
		Index("ix_sc_brl_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	sacco_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_sacco.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	run_date = Column(Date, nullable=False)
	job_type = Column(
		String(50), nullable=False,
		comment=(
			"ACCRUE_SAVINGS_INTEREST | ACCRUE_LOAN_INTEREST | "
			"CHARGE_OVERDUE_PENALTIES | CHECK_DORMANCY | EOD_RECONCILIATION"
		),
	)
	status = Column(
		String(20), nullable=False, default="RUNNING",
		comment="RUNNING | COMPLETED | FAILED",
	)
	records_processed = Column(Integer, nullable=False, default=0)
	records_failed = Column(Integer, nullable=False, default=0)
	total_amount_cents = Column(Integer, nullable=False, default=0)
	error_detail = Column(Text, nullable=True)
	started_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	completed_at = Column(DateTime(timezone=True), nullable=True)

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
			f"<BatchRunLog date={self.run_date} "
			f"job={self.job_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# HIGH GAP 3 — Transactional Limits and Controls
# ---------------------------------------------------------------------------

class LimitConfig(AuditMixin, Model):
	"""Per-scope transaction limit configuration.

	scope:
	  MEMBER  — applies to a specific member (member_ref = member.id)
	  PRODUCT — applies to all members on a product (member_ref = product.id)
	  SACCO   — applies to entire SACCO (member_ref = sacco.id)

	limit_type:
	  DAILY_WITHDRAWAL   — max total withdrawal in a calendar day
	  MIN_BALANCE        — minimum balance that must remain after any debit
	  MAX_LOAN_EXPOSURE  — max outstanding loan balance for a member
	  SINGLE_TXN         — maximum single-transaction amount
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_limit_config"
	__table_args__ = (
		UniqueConstraint("scope", "limit_type", "scope_ref_id", name="uq_sc_lc_scope_type"),
		Index("ix_sc_lc_scope", "scope"),
		Index("ix_sc_lc_limit_type", "limit_type"),
		Index("ix_sc_lc_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	scope = Column(
		String(20), nullable=False,
		comment="MEMBER | PRODUCT | SACCO",
	)
	scope_ref_id = Column(
		UUID(as_uuid=False), nullable=False, index=True,
		comment="ID of the member / product / sacco this limit targets",
	)
	limit_type = Column(
		String(30), nullable=False,
		comment="DAILY_WITHDRAWAL | MIN_BALANCE | MAX_LOAN_EXPOSURE | SINGLE_TXN",
	)
	amount_cents = Column(Integer, nullable=False, comment="Limit threshold in cents")
	currency = Column(String(3), nullable=False, default="KES")
	is_active = Column(Boolean, nullable=False, default=True)
	effective_from = Column(Date, nullable=False, default=date.today)
	effective_to = Column(Date, nullable=True, comment="NULL = no expiry")

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
			f"<LimitConfig scope={self.scope!r} "
			f"type={self.limit_type!r} "
			f"amount={self.amount_cents}c>"
		)


# ---------------------------------------------------------------------------
# HIGH GAP 4 — Durable Event Outbox
# ---------------------------------------------------------------------------

class SaccoOutboxEvent(AuditMixin, Model):
	"""Transactional outbox for reliable at-least-once event delivery.

	Written inside the same DB transaction as the business operation.
	A background OutboxRelay polls status=PENDING rows, publishes to
	Kafka/Redis Streams, and marks status=PUBLISHED.

	Guarantees: if the business transaction commits, the event will eventually
	be published even if the process crashes between write and publish.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_outbox_event"
	__table_args__ = (
		Index("ix_sc_oe_status", "status"),
		Index("ix_sc_oe_aggregate", "aggregate_type", "aggregate_id"),
		Index("ix_sc_oe_event_type", "event_type"),
		Index("ix_sc_oe_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	aggregate_type = Column(String(100), nullable=False, comment="e.g. Member, Loan, Chama")
	aggregate_id = Column(String(100), nullable=False)
	event_type = Column(String(100), nullable=False, comment="e.g. sc.member.contribution_posted")
	payload_json: dict[str, Any] = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
	)
	status = Column(
		String(20), nullable=False, default="PENDING",
		comment="PENDING | PUBLISHED | FAILED | SKIPPED",
	)
	publish_attempts = Column(Integer, nullable=False, default=0)
	last_error = Column(Text, nullable=True)
	published_at = Column(DateTime(timezone=True), nullable=True)

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
			f"<SaccoOutboxEvent {self.event_type!r} "
			f"aggregate={self.aggregate_type}/{self.aggregate_id} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# HIGH GAP 5 — AML / Sanctions Screening
# ---------------------------------------------------------------------------

class SaccoSAR(AuditMixin, Model):
	"""SAR (Suspicious Activity Report) raised by AML screening.

	sar_type:
	  CTR              — Currency Transaction Report (above threshold)
	  STRUCTURING      — multiple sub-threshold transactions in 24 h
	  SANCTIONS_HIT    — member matched on sanctions list
	  VELOCITY         — unusual velocity / rapid successive transactions
	  GEOGRAPHY        — unexpected geography / new country

	status:
	  PENDING_REVIEW | ESCALATED | CLEARED | FILED
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_sar"
	__table_args__ = (
		Index("ix_sc_sar_member", "member_id"),
		Index("ix_sc_sar_status", "status"),
		Index("ix_sc_sar_sar_type", "sar_type"),
		Index("ix_sc_sar_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_member.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	transaction_ref = Column(String(100), nullable=True, index=True)
	amount_cents = Column(Integer, nullable=False)
	currency = Column(String(3), nullable=False, default="KES")
	sar_type = Column(
		String(30), nullable=False,
		comment="CTR | STRUCTURING | SANCTIONS_HIT | VELOCITY | GEOGRAPHY",
	)
	trigger_details: dict[str, Any] = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
		comment="Machine-readable evidence (daily volume, matched entity, etc.)",
	)
	narrative = Column(Text, nullable=True, comment="Human-readable description")
	status = Column(
		String(20), nullable=False, default="PENDING_REVIEW",
		comment="PENDING_REVIEW | ESCALATED | CLEARED | FILED",
	)
	reviewed_by = Column(String(64), nullable=True)
	reviewed_at = Column(DateTime(timezone=True), nullable=True)
	review_notes = Column(Text, nullable=True)
	transaction_blocked = Column(Boolean, nullable=False, default=False)

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
			f"<SaccoSAR member={self.member_id!r} "
			f"type={self.sar_type!r} status={self.status!r}>"
		)


class SaccoSanctionsList(AuditMixin, Model):
	"""Local cache of sanctions / PEP list entries for offline screening.

	Refreshed by a background job from OFAC, UN, EU, or national lists.
	match_keys is a JSONB array of normalised name tokens / ID numbers
	for efficient fuzzy search.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_sanctions_list"
	__table_args__ = (
		Index("ix_sc_sl_list_source", "list_source"),
		Index("ix_sc_sl_status", "status"),
		Index("ix_sc_sl_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	list_source = Column(
		String(50), nullable=False,
		comment="OFAC | UN | EU | NATIONAL | PEP",
	)
	entity_name = Column(String(300), nullable=False)
	entity_type = Column(
		String(30), nullable=False, default="INDIVIDUAL",
		comment="INDIVIDUAL | ENTITY | VESSEL | AIRCRAFT",
	)
	match_keys: list[Any] = Column(
		JSONB, nullable=False, default=list, server_default="[]",
		comment="Normalised tokens for fuzzy match: names, IDs, aliases",
	)
	additional_info: dict[str, Any] = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
	)
	listed_date = Column(Date, nullable=True)
	status = Column(
		String(20), nullable=False, default="ACTIVE",
		comment="ACTIVE | DELISTED",
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
		return f"<SaccoSanctionsList {self.entity_name!r} source={self.list_source!r}>"


# ---------------------------------------------------------------------------
# HIGH GAP 6 — Fraud Signal Generation
# ---------------------------------------------------------------------------

class SaccoFraudSignal(AuditMixin, Model):
	"""Raw fraud signal record for model training and manual review.

	signal_type:
	  UNUSUAL_HOUR | ATYPICAL_AMOUNT | NEW_DEVICE | RAPID_SUCCESSION |
	  GEOGRAPHY_MISMATCH | VELOCITY_BREACH | PATTERN_ANOMALY

	risk_score: 0–1000 where 700+ = block, 400–699 = flag for review.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_fraud_signal"
	__table_args__ = (
		Index("ix_sc_fs_member", "member_id"),
		Index("ix_sc_fs_signal_type", "signal_type"),
		Index("ix_sc_fs_risk_score", "risk_score"),
		Index("ix_sc_fs_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_member.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	transaction_ref = Column(String(100), nullable=True, index=True)
	signal_type = Column(
		String(40), nullable=False,
		comment=(
			"UNUSUAL_HOUR | ATYPICAL_AMOUNT | NEW_DEVICE | "
			"RAPID_SUCCESSION | GEOGRAPHY_MISMATCH | VELOCITY_BREACH | PATTERN_ANOMALY"
		),
	)
	risk_score = Column(
		Integer, nullable=False,
		comment="0–1000; 700+ = block; 400–699 = review",
	)
	action_taken = Column(
		String(20), nullable=False, default="NONE",
		comment="NONE | FLAGGED | BLOCKED",
	)
	signal_data: dict[str, Any] = Column(
		JSONB, nullable=False, default=dict, server_default="{}",
		comment="Raw features: amount_cents, hour, ip_hash, device_id, coords, etc.",
	)
	resolved = Column(Boolean, nullable=False, default=False)
	resolved_by = Column(String(64), nullable=True)
	resolved_at = Column(DateTime(timezone=True), nullable=True)

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
			f"<SaccoFraudSignal member={self.member_id!r} "
			f"type={self.signal_type!r} score={self.risk_score} action={self.action_taken!r}>"
		)


# ---------------------------------------------------------------------------
# HIGH GAP 7 — Notification Templates and Dispatch Log
# ---------------------------------------------------------------------------

class NotificationTemplate(AuditMixin, Model):
	"""Template for outbound member notifications.

	channel: SMS | EMAIL | PUSH
	event_type matches sc.* event names, e.g. sc.member.contribution_posted
	body_template: Jinja2-compatible string with {{ member_name }}, {{ amount }}, etc.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_notification_template"
	__table_args__ = (
		UniqueConstraint("event_type", "channel", "locale", name="uq_sc_nt_event_channel_locale"),
		Index("ix_sc_nt_event_type", "event_type"),
		Index("ix_sc_nt_channel", "channel"),
		Index("ix_sc_nt_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	event_type = Column(String(100), nullable=False)
	channel = Column(String(10), nullable=False, comment="SMS | EMAIL | PUSH")
	locale = Column(String(10), nullable=False, default="en", comment="ISO 639-1 locale code")
	subject_template = Column(Text, nullable=True, comment="Email subject (NULL for SMS/PUSH)")
	body_template = Column(Text, nullable=False)
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
		return f"<NotificationTemplate event={self.event_type!r} channel={self.channel!r} locale={self.locale!r}>"


class NotificationLog(AuditMixin, Model):
	"""Delivery log for outbound notifications.

	status: PENDING | SENT | FAILED | BOUNCED
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_notification_log"
	__table_args__ = (
		Index("ix_sc_nl_member", "member_id"),
		Index("ix_sc_nl_status", "status"),
		Index("ix_sc_nl_channel", "channel"),
		Index("ix_sc_nl_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_member.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	template_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_notification_template.id", ondelete="RESTRICT"),
		nullable=True,
	)
	channel = Column(String(10), nullable=False)
	recipient = Column(String(200), nullable=False, comment="Phone / email address / device token")
	subject = Column(Text, nullable=True)
	body = Column(Text, nullable=False)
	event_type = Column(String(100), nullable=False)
	status = Column(String(20), nullable=False, default="PENDING")
	provider_ref = Column(String(100), nullable=True, comment="AfricasTalking / Twilio message ID")
	attempts = Column(Integer, nullable=False, default=0)
	last_error = Column(Text, nullable=True)
	sent_at = Column(DateTime(timezone=True), nullable=True)

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
			f"<NotificationLog member={self.member_id!r} "
			f"channel={self.channel!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# CRITICAL GAP 1 — GL Chart of Accounts mapping (SACCO-specific)
# ---------------------------------------------------------------------------

class SACCOAccountMap(AuditMixin, Model):
	"""Maps SACCO transaction types to GL account codes.

	This table drives the GL posting logic in SACCOService.  A default row
	is seeded for each new SACCO; the finance team can override per-product.

	transaction_type maps to SaccoLedgerEntry.entry_type values.
	dr_account / cr_account are account codes in the erp.finance.gl chart.
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_account_map"
	__table_args__ = (
		UniqueConstraint("sacco_id", "transaction_type", name="uq_sc_am_sacco_txn"),
		Index("ix_sc_am_sacco", "sacco_id"),
		Index("ix_sc_am_txn_type", "transaction_type"),
		Index("ix_sc_am_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	sacco_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_sacco.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	transaction_type = Column(
		String(30), nullable=False,
		comment="CONTRIBUTION | LOAN_DISBURSEMENT | LOAN_REPAYMENT | DIVIDEND | FEE | WITHDRAWAL",
	)
	dr_account = Column(String(20), nullable=False, comment="GL debit account code")
	cr_account = Column(String(20), nullable=False, comment="GL credit account code")
	description_template = Column(
		String(200), nullable=True,
		comment="Narrative template for GL line, e.g. 'Contribution {member_number}'",
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
			f"<SACCOAccountMap sacco={self.sacco_id!r} "
			f"txn={self.transaction_type!r} "
			f"DR={self.dr_account!r} CR={self.cr_account!r}>"
		)


# ---------------------------------------------------------------------------
# FOSAAccountLink — member ↔ core banking account mapping for FOSA
# ---------------------------------------------------------------------------

class FOSAAccountLink(AuditMixin, Model):
	"""Links a SACCO member's FOSA account to a core banking account.

	One row per member per account_type (FOSA / BOSA / SHARES).
	Created by FOSABridgeService.provision_fosa_account() when a member is
	onboarded or when their FOSA arm is activated.

	cb_account_number: the core banking account number (from cb_account table).
	"""

	__allow_unmapped__ = True
	__tablename__ = "sc_fosa_account_link"
	__table_args__ = (
		UniqueConstraint("member_id", "account_type", "tenant_id", name="uq_sc_fal_member_type"),
		Index("ix_sc_fal_member", "member_id"),
		Index("ix_sc_fal_sacco", "sacco_id"),
		Index("ix_sc_fal_account_type", "account_type"),
		Index("ix_sc_fal_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)

	sacco_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_sacco.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	member_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sc_member.id", ondelete="RESTRICT"),
		nullable=False, index=True,
	)
	account_type = Column(
		String(20), nullable=False, default="FOSA",
		comment="FOSA | BOSA | SHARES",
	)
	cb_account_number = Column(
		String(50), nullable=True,
		comment="Core banking account number from cb_account",
	)
	cb_account_id = Column(
		UUID(as_uuid=False), nullable=True,
		comment="FK reference to cb_account.id (denormalised for fast lookups)",
	)
	currency_code = Column(String(3), nullable=False, default="KES")
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
		return (
			f"<FOSAAccountLink member={self.member_id!r} "
			f"type={self.account_type!r} "
			f"cb_acct={self.cb_account_number!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SACCO",
	"Member",
	"SACCOLoanProduct",
	"Dividend",
	"Chama",
	"ChamaMember",
	# CRITICAL gaps
	"FeeCharge",
	"FeeLineItem",
	"SaccoLedgerEntry",
	"LoanRepaymentSchedule",
	"SACCOAccountMap",
	"FOSAAccountLink",
	# HIGH gaps
	"SaccoStandingOrder",
	"BatchRunLog",
	"LimitConfig",
	"SaccoOutboxEvent",
	"SaccoSAR",
	"SaccoSanctionsList",
	"SaccoFraudSignal",
	"NotificationTemplate",
	"NotificationLog",
]
