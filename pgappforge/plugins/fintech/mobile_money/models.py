"""
pgappforge/plugins/fintech/mobile_money/models.py

SQLAlchemy models for the Mobile Money + Agency Banking plugin.

Tables
------
mm_wallet            — mobile wallet per MSISDN (customer-facing)
mm_transaction       — immutable ledger of every MM transaction
mm_agent             — agent/aggregator/master-agent hierarchy
mm_agent_commission  — immutable per-period commission accrual records
mm_merchant_till     — merchant Buy-Goods / Pay-Bill tills

Design rules
------------
- All PKs: UUID via gen_random_uuid() / Python uuid4()
- All monetary amounts: INTEGER cents/kobo/fils — never Decimal/float in storage
- All timestamps: TIMESTAMPTZ DEFAULT NOW()
- All mutable models: tenant_id VARCHAR(64) NOT NULL + created_at/updated_at
- Ledger models (mm_transaction, mm_agent_commission): ImmutableRecordMixin
- KYC tier limits follow CBK Mobile Money Regulations (Kenya)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
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
	SmallInteger,
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
# MobileWallet
# ---------------------------------------------------------------------------

class MobileWallet(AuditMixin, Model):
	"""Customer mobile wallet keyed by MSISDN.

	Tier limits (CBK Mobile Money Regulations 2021):
	  TIER_1 (basic): max balance 100 000 KES, daily limit 30 000 KES
	  TIER_2 (verified): max balance 300 000 KES, daily limit 150 000 KES
	  TIER_3 (full): max balance 1 000 000 KES, daily limit 500 000 KES

	All monetary columns are in *cents* (1 KES = 100 cents).
	pin_hash stores SHA-256 of the raw PIN — never the plain PIN.
	daily_used_cents resets to 0 at midnight KE time (handled by service layer).
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_wallet"
	__table_args__ = (
		Index("ix_mm_wallet_msisdn", "msisdn"),
		Index("ix_mm_wallet_customer_id", "customer_id"),
		Index("ix_mm_wallet_tenant_id", "tenant_id"),
		UniqueConstraint("msisdn", name="uq_mm_wallet_msisdn"),
		{"extend_existing": True},
	)

	__audit_pii_fields__ = frozenset({"msisdn", "pin_hash", "device_imei"})

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)
	msisdn: str = Column(String(20), unique=True, nullable=False, index=True)
	customer_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("foundation_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	linked_account_id: str | None = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id", ondelete="SET NULL"),
		nullable=True,
	)
	# STANDARD / PREMIUM / MERCHANT / AGENT
	wallet_type: str = Column(String(20), nullable=False, default="STANDARD")
	# TIER_1 / TIER_2 / TIER_3
	kyc_tier: str = Column(String(10), nullable=False, default="TIER_1")

	# Balances and limits (all INTEGER cents)
	balance_cents: int = Column(Integer, nullable=False, default=0)
	max_balance_cents: int = Column(Integer, nullable=False, default=10_000_000)   # 100k KES
	daily_limit_cents: int = Column(Integer, nullable=False, default=3_000_000)    # 30k KES
	daily_used_cents: int = Column(Integer, nullable=False, default=0)

	# PIN security
	pin_hash: str | None = Column(String(64), nullable=True)
	pin_attempts: int = Column(Integer, nullable=False, default=0)
	pin_locked_until: datetime | None = Column(DateTime(timezone=True), nullable=True)

	# Lifecycle
	# ACTIVE / SUSPENDED / CLOSED / PENDING_KYC
	status: str = Column(String(20), nullable=False, default="ACTIVE")
	last_transaction_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	device_imei: str | None = Column(String(20), nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	transactions_sent: list["MobileTransaction"] = relationship(
		"MobileTransaction",
		foreign_keys="MobileTransaction.sender_msisdn",
		primaryjoin="MobileWallet.msisdn == MobileTransaction.sender_msisdn",
		back_populates="sender_wallet",
		viewonly=True,
	)

	def __repr__(self) -> str:
		return (
			f"<MobileWallet msisdn={self.msisdn!r}"
			f" tier={self.kyc_tier!r}"
			f" balance={self.balance_cents}"
			f" status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# MobileTransaction  (IMMUTABLE ledger)
# ---------------------------------------------------------------------------

class MobileTransaction(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable ledger record for every mobile money transaction.

	transaction_id follows M-Pesa convention: MPxxxxxxxxxxxxxxxxx (17 chars).
	confirmation_code is the short human-readable code sent via SMS, e.g. QJ123ABC.
	ImmutableRecordMixin blocks any UPDATE on committed rows — use REVERSAL type
	to correct a completed transaction.

	All monetary amounts are INTEGER cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_transaction"
	__table_args__ = (
		Index("ix_mm_txn_transaction_id", "transaction_id"),
		Index("ix_mm_txn_sender", "sender_msisdn"),
		Index("ix_mm_txn_recipient", "recipient_msisdn"),
		Index("ix_mm_txn_agent_id", "agent_id"),
		Index("ix_mm_txn_tenant_id", "tenant_id"),
		Index("ix_mm_txn_initiated_at", "initiated_at"),
		Index("ix_mm_txn_idempotency", "idempotency_key"),
		UniqueConstraint("transaction_id", name="uq_mm_transaction_id"),
		UniqueConstraint("idempotency_key", name="uq_mm_txn_idempotency_key"),
		{"extend_existing": True},
	)

	__audit_pii_fields__ = frozenset({"sender_msisdn", "recipient_msisdn"})

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	# M-Pesa style reference
	transaction_id: str = Column(String(50), unique=True, nullable=False, index=True)

	# DEPOSIT / WITHDRAWAL / SEND_MONEY / BUY_GOODS / PAY_BILL /
	# AGENT_DEPOSIT / AGENT_WITHDRAWAL / AIRTIME_PURCHASE /
	# LOAN_REPAYMENT / BANK_DEPOSIT / BANK_WITHDRAWAL / REVERSAL
	transaction_type: str = Column(String(30), nullable=False)

	sender_msisdn: str | None = Column(String(20), nullable=True, index=True)
	recipient_msisdn: str | None = Column(String(20), nullable=True, index=True)
	recipient_name: str | None = Column(String(200), nullable=True)
	merchant_code: str | None = Column(String(20), nullable=True)

	# Amounts (INTEGER cents)
	amount_cents: int = Column(Integer, nullable=False)
	fee_cents: int = Column(Integer, nullable=False, default=0)
	sender_balance_before_cents: int | None = Column(Integer, nullable=True)
	sender_balance_after_cents: int | None = Column(Integer, nullable=True)

	# Channel: USSD / APP / API / STK_PUSH / AGENT
	channel: str = Column(String(20), nullable=False, default="USSD")

	# Status: PENDING / COMPLETED / FAILED / REVERSED / EXPIRED
	status: str = Column(String(20), nullable=False, default="COMPLETED")

	initiated_at: datetime = Column(DateTime(timezone=True), nullable=False)
	completed_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	failure_reason: str | None = Column(Text, nullable=True)

	# Daraja / payment-switch integration
	stk_push_request_id: str | None = Column(String(100), nullable=True)
	confirmation_code: str | None = Column(String(20), nullable=True)

	# Agent linkage (nullable — only set for agent-channel transactions)
	agent_id: str | None = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_agent.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	# For REVERSAL transactions — points back to original
	original_transaction_id: str | None = Column(String(50), nullable=True)

	# Idempotency — unique client-supplied key; replay returns existing txn
	idempotency_key: str | None = Column(String(128), nullable=True, index=True)

	# Fraud scoring (0–100; ≥80 blocks, 50–79 requires OTP re-auth)
	fraud_score: int | None = Column(SmallInteger, nullable=True)

	# Partial reversal support — cents actually reversed (may differ from amount_cents)
	reversal_amount_cents: int | None = Column(Integer, nullable=True)
	reversal_reason_code: str | None = Column(String(30), nullable=True)

	# Audit timestamps (created_at is the immutable insert time)
	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	# updated_at present for AuditMixin compatibility; ImmutableRecordMixin blocks mutations
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	agent: "Agent | None" = relationship("Agent", foreign_keys=[agent_id], back_populates="transactions")
	sender_wallet: "MobileWallet | None" = relationship(
		"MobileWallet",
		foreign_keys=[sender_msisdn],
		primaryjoin="MobileTransaction.sender_msisdn == MobileWallet.msisdn",
		back_populates="transactions_sent",
		viewonly=True,
	)

	def __repr__(self) -> str:
		return (
			f"<MobileTransaction {self.transaction_id!r}"
			f" type={self.transaction_type!r}"
			f" amount={self.amount_cents}"
			f" status={self.status!r}>"
		)


# Register immutability block on MobileTransaction
MobileTransaction._register_immutability()


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent(AuditMixin, Model):
	"""Mobile money agent / aggregator / master-agent.

	Hierarchy: Head Office → MASTER_AGENT → AGGREGATOR → SUBAGENT
	parent_agent_id implements the hierarchy via self-referential FK.

	float_account_id links to a core-banking account that holds working capital.
	commission_rate_pct uses NUMERIC(5,4) — e.g. 0.0150 means 1.50%.
	location JSONB: {lat, lng, address, county, town}
	operating_hours JSONB: {mon: "08:00-18:00", ...}
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_agent"
	__table_args__ = (
		Index("ix_mm_agent_agent_code", "agent_code"),
		Index("ix_mm_agent_party_id", "party_id"),
		Index("ix_mm_agent_parent", "parent_agent_id"),
		Index("ix_mm_agent_tenant_id", "tenant_id"),
		UniqueConstraint("agent_code", name="uq_mm_agent_code"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)
	agent_code: str = Column(String(20), unique=True, nullable=False)

	party_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("foundation_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	# MASTER_AGENT / AGGREGATOR / SUBAGENT
	agent_type: str = Column(String(20), nullable=False, default="SUBAGENT")

	parent_agent_id: str | None = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_agent.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

	float_account_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id", ondelete="RESTRICT"),
		nullable=False,
	)

	# Float thresholds (INTEGER cents)
	min_float_cents: int = Column(Integer, nullable=False, default=500_000)      # 5k KES
	max_float_cents: int = Column(Integer, nullable=False, default=100_000_000)  # 1M KES
	current_float_cents: int = Column(Integer, nullable=False, default=0)

	# Commission (NUMERIC — stored as-is, never used for arithmetic on non-cents)
	commission_rate_pct: Any = Column(Numeric(5, 4), nullable=False, default=0)

	# Geo / schedule metadata
	location: dict | None = Column(JSONB, nullable=True)
	operating_hours: dict | None = Column(JSONB, nullable=True)

	# ACTIVE / SUSPENDED / DEREGISTERED
	status: str = Column(String(20), nullable=False, default="ACTIVE")

	# Running totals (denormalised for fast dashboard queries)
	total_transactions: int = Column(Integer, nullable=False, default=0)
	total_volume_cents: int = Column(Integer, nullable=False, default=0)
	last_float_top_up_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

	# NUMERIC(3,1) — e.g. 4.5
	rating: Any = Column(Numeric(3, 1), nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	parent: "Agent | None" = relationship(
		"Agent",
		remote_side="Agent.id",
		foreign_keys=[parent_agent_id],
		back_populates="children",
	)
	children: list["Agent"] = relationship(
		"Agent",
		foreign_keys=[parent_agent_id],
		back_populates="parent",
	)
	transactions: list["MobileTransaction"] = relationship(
		"MobileTransaction",
		foreign_keys="MobileTransaction.agent_id",
		back_populates="agent",
	)
	commissions: list["AgentCommission"] = relationship(
		"AgentCommission",
		foreign_keys="AgentCommission.agent_id",
		back_populates="agent",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return (
			f"<Agent {self.agent_code!r}"
			f" type={self.agent_type!r}"
			f" float={self.current_float_cents}"
			f" status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# AgentCommission  (IMMUTABLE — one row per period per agent)
# ---------------------------------------------------------------------------

class AgentCommission(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable commission accrual record for an agent per billing period.

	One row is created at period close via calculate_agent_commission().
	Corrections are handled by creating a new row with adjusted figures, never
	updating the original (ImmutableRecordMixin enforces this).
	commission_paid_cents tracks how much of commission_earned_cents has been
	disbursed (updated via a separate payment record in the payments plugin).
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_agent_commission"
	__table_args__ = (
		Index("ix_mm_agent_comm_agent_id", "agent_id"),
		Index("ix_mm_agent_comm_period", "period_start", "period_end"),
		Index("ix_mm_agent_comm_tenant_id", "tenant_id"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	agent_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_agent.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	period_start: Any = Column(Date, nullable=False)
	period_end: Any = Column(Date, nullable=False)

	transaction_count: int = Column(Integer, nullable=False)
	transaction_volume_cents: int = Column(Integer, nullable=False)
	commission_earned_cents: int = Column(Integer, nullable=False)
	commission_paid_cents: int = Column(Integer, nullable=False, default=0)

	# PENDING / APPROVED / PAID
	status: str = Column(String(20), nullable=False, default="PENDING")

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	agent: "Agent" = relationship("Agent", foreign_keys=[agent_id], back_populates="commissions")

	def __repr__(self) -> str:
		return (
			f"<AgentCommission agent={self.agent_id}"
			f" period={self.period_start}..{self.period_end}"
			f" earned={self.commission_earned_cents}"
			f" status={self.status!r}>"
		)


AgentCommission._register_immutability()


# ---------------------------------------------------------------------------
# MerchantTill
# ---------------------------------------------------------------------------

class MerchantTill(AuditMixin, Model):
	"""Merchant Buy-Goods till or Pay-Bill shortcode.

	till_number is the 5-6 digit Buy-Goods till (e.g. 123456).
	paybill_number is the Pay-Bill business number (e.g. 400200); unique when set.
	settlement_account_id: core-banking account that receives daily sweeps.
	daily_settlement: when True the service layer sweeps collected funds to
	  settlement_account_id once per day.
	total_received_cents: running total for dashboard display (denormalised).
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_merchant_till"
	__table_args__ = (
		Index("ix_mm_till_merchant_id", "merchant_id"),
		Index("ix_mm_till_tenant_id", "tenant_id"),
		UniqueConstraint("till_number", name="uq_mm_till_number"),
		UniqueConstraint("paybill_number", name="uq_mm_paybill_number"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)
	till_number: str = Column(String(20), unique=True, nullable=False)
	business_name: str = Column(String(200), nullable=False)

	merchant_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("foundation_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	settlement_account_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id", ondelete="RESTRICT"),
		nullable=False,
	)

	# BUY_GOODS / PAY_BILL
	till_type: str = Column(String(20), nullable=False, default="BUY_GOODS")
	paybill_number: str | None = Column(String(20), nullable=True, unique=True)
	category: str | None = Column(String(50), nullable=True)

	# ACTIVE / SUSPENDED / DEREGISTERED
	status: str = Column(String(20), nullable=False, default="ACTIVE")
	daily_settlement: bool = Column(Boolean, nullable=False, default=True)
	last_settlement_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	total_received_cents: int = Column(Integer, nullable=False, default=0)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	def __repr__(self) -> str:
		return (
			f"<MerchantTill {self.till_number!r}"
			f" type={self.till_type!r}"
			f" business={self.business_name!r}"
			f" status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# FeeSchedule  (CRITICAL: configurable fee product table)
# ---------------------------------------------------------------------------

class FeeSchedule(AuditMixin, Model):
	"""Configurable fee product table — replaces hard-coded tier arrays.

	Each row defines one fee band for a given product + tier + channel combo.
	Bands are ordered by band_max_cents ascending; the first band whose
	band_max_cents >= transaction amount wins.

	flat_fee_cents is charged as-is.
	pct_bps is basis-points of transaction amount (10000 bps = 100%).
	VAT and excise are computed as fractions of (flat_fee_cents + pct_fee_cents).
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_fee_schedule"
	__table_args__ = (
		Index("ix_mm_fee_product_tier", "product_code", "tier", "channel"),
		Index("ix_mm_fee_effective", "effective_date", "expiry_date"),
		Index("ix_mm_fee_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	# e.g. "SEND_MONEY", "WITHDRAWAL", "BUY_GOODS", "PAY_BILL"
	product_code: str = Column(String(40), nullable=False)
	# "TIER_1" / "TIER_2" / "TIER_3" / "*" (wildcard matches any tier)
	tier: str = Column(String(10), nullable=False, default="*")
	# "USSD" / "APP" / "API" / "STK_PUSH" / "AGENT" / "*"
	channel: str = Column(String(20), nullable=False, default="*")

	# Band boundaries (INTEGER cents); band_min_cents=0 for the first band
	band_min_cents: int = Column(Integer, nullable=False, default=0)
	band_max_cents: int = Column(Integer, nullable=False)

	# Fee components (INTEGER cents / bps)
	flat_fee_cents: int = Column(Integer, nullable=False, default=0)
	# Basis points of transaction amount: 150 = 1.50%
	pct_bps: int = Column(Integer, nullable=False, default=0)
	# VAT rate bps applied to (flat + pct) fee; e.g. 1600 = 16%
	vat_bps: int = Column(Integer, nullable=False, default=1600)
	# Excise duty bps applied to (flat + pct) fee; e.g. 2000 = 20%
	excise_bps: int = Column(Integer, nullable=False, default=0)

	effective_date: Any = Column(Date, nullable=False)
	expiry_date: Any = Column(Date, nullable=True)

	# ACTIVE / SUPERSEDED
	status: str = Column(String(20), nullable=False, default="ACTIVE")

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	def __repr__(self) -> str:
		return (
			f"<FeeSchedule product={self.product_code!r}"
			f" tier={self.tier!r} band=[{self.band_min_cents},{self.band_max_cents}]"
			f" flat={self.flat_fee_cents} pct={self.pct_bps}bps>"
		)


# ---------------------------------------------------------------------------
# MMOutboxEvent  (CRITICAL: transactional outbox for durable event delivery)
# ---------------------------------------------------------------------------

class MMOutboxEvent(Model):
	"""Transactional outbox — written in same DB txn as wallet mutation.

	A background worker (or Postgres LISTEN/NOTIFY) delivers events and
	marks delivered_at.  This guarantees at-least-once delivery even if the
	process crashes between commit and the in-process emit_event call.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_outbox_event"
	__table_args__ = (
		Index("ix_mm_outbox_undelivered", "delivered_at"),
		Index("ix_mm_outbox_tenant", "tenant_id"),
		Index("ix_mm_outbox_created", "created_at"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	# Fully-qualified event type string, e.g. "mm.transaction.send_money"
	event_type: str = Column(String(80), nullable=False, index=True)
	# Aggregate that owns this event (MobileTransaction.id, MobileWallet.id, …)
	aggregate_id: str = Column(String(64), nullable=False, index=True)
	aggregate_type: str = Column(String(60), nullable=False)

	# Full event payload serialised to JSON
	payload: dict = Column(JSONB, nullable=False, default=dict)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	# Null until delivered; worker sets this to mark delivery
	delivered_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	# Number of delivery attempts
	attempts: int = Column(Integer, nullable=False, default=0)
	# Last delivery error message (if any)
	last_error: str | None = Column(Text, nullable=True)

	def __repr__(self) -> str:
		return (
			f"<MMOutboxEvent {self.event_type!r}"
			f" agg={self.aggregate_id!r}"
			f" delivered={self.delivered_at is not None}>"
		)


# ---------------------------------------------------------------------------
# GLEntry / GLJournalLine  (CRITICAL: double-entry GL subledger)
# ---------------------------------------------------------------------------

class MMGLJournalLine(ImmutableRecordMixin, Model):
	"""Immutable double-entry GL subledger line for mobile money transactions.

	Every debit/credit pair posts in the same DB transaction as the wallet
	mutation.  The sum of dr_cents - cr_cents across all lines for a given
	journal_id must equal zero (balanced entry).

	account_code references the chart of accounts; cost_centre is optional.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_gl_journal_line"
	__table_args__ = (
		Index("ix_mm_gl_journal_id", "journal_id"),
		Index("ix_mm_gl_account_code", "account_code"),
		Index("ix_mm_gl_txn_id", "mm_transaction_id"),
		Index("ix_mm_gl_tenant", "tenant_id"),
		Index("ix_mm_gl_posted_at", "posted_at"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	# Groups all lines for a single atomic GL posting
	journal_id: str = Column(String(64), nullable=False, index=True)

	# FK to mm_transaction (nullable — some GL entries are journal-only)
	mm_transaction_id: str | None = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_transaction.id", ondelete="RESTRICT"),
		nullable=True,
		index=True,
	)

	# Chart-of-accounts code, e.g. "1001" (Cash), "4001" (Fee Revenue)
	account_code: str = Column(String(20), nullable=False)
	cost_centre: str | None = Column(String(30), nullable=True)

	# Exactly one of dr_cents / cr_cents is non-zero per line
	dr_cents: int = Column(BigInteger, nullable=False, default=0)
	cr_cents: int = Column(BigInteger, nullable=False, default=0)

	narration: str = Column(String(255), nullable=False, default="")
	currency: str = Column(String(3), nullable=False, default="KES")
	posted_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<GLJournalLine journal={self.journal_id!r}"
			f" acct={self.account_code!r}"
			f" dr={self.dr_cents} cr={self.cr_cents}>"
		)


MMGLJournalLine._register_immutability()


# ---------------------------------------------------------------------------
# MMStandingOrder  (HIGH: recurring payments)
# ---------------------------------------------------------------------------

class MMStandingOrder(AuditMixin, Model):
	"""Recurring payment / standing order.

	Frequencies: DAILY / WEEKLY / MONTHLY.
	Status: ACTIVE / SUSPENDED / COMPLETED / CANCELLED.
	Failure increments retry_count; after 3 failures status → SUSPENDED.
	max_executions = None means unlimited.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_standing_order"
	__table_args__ = (
		Index("ix_mm_so_wallet_id", "wallet_id"),
		Index("ix_mm_so_next_exec", "next_execution_at"),
		Index("ix_mm_so_status", "status"),
		Index("ix_mm_so_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	wallet_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_wallet.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	# Destination: MSISDN for P2P, till/paybill for merchant payments
	beneficiary_msisdn: str | None = Column(String(20), nullable=True)
	beneficiary_till: str | None = Column(String(20), nullable=True)
	# "SEND_MONEY" / "PAY_BILL" / "BUY_GOODS"
	payment_type: str = Column(String(20), nullable=False, default="SEND_MONEY")
	# For PAY_BILL: account/reference number
	account_reference: str | None = Column(String(50), nullable=True)

	amount_cents: int = Column(Integer, nullable=False)
	# DAILY / WEEKLY / MONTHLY
	frequency: str = Column(String(10), nullable=False)

	next_execution_at: datetime = Column(DateTime(timezone=True), nullable=False)
	max_executions: int | None = Column(Integer, nullable=True)
	executions_done: int = Column(Integer, nullable=False, default=0)
	retry_count: int = Column(Integer, nullable=False, default=0)

	# ACTIVE / SUSPENDED / COMPLETED / CANCELLED
	status: str = Column(String(20), nullable=False, default="ACTIVE")
	last_executed_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	last_txn_id: str | None = Column(String(50), nullable=True)
	suspension_reason: str | None = Column(String(255), nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	wallet: "MobileWallet" = relationship("MobileWallet", foreign_keys=[wallet_id])

	def __repr__(self) -> str:
		return (
			f"<MMStandingOrder id={self.id!r}"
			f" type={self.payment_type!r}"
			f" freq={self.frequency!r}"
			f" status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# DisbursementBatch / DisbursementLine  (HIGH: B2C bulk pay)
# ---------------------------------------------------------------------------

class DisbursementBatch(AuditMixin, Model):
	"""Header record for a bulk B2C disbursement run.

	Status: DRAFT / APPROVED / PROCESSING / COMPLETED / FAILED / CANCELLED.
	approved_by stores the user ID that authorised the batch.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_disbursement_batch"
	__table_args__ = (
		Index("ix_mm_batch_initiator", "initiator_id"),
		Index("ix_mm_batch_status", "status"),
		Index("ix_mm_batch_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	initiator_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("foundation_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	batch_reference: str = Column(String(80), nullable=False, default="")
	description: str | None = Column(Text, nullable=True)

	total_recipients: int = Column(Integer, nullable=False, default=0)
	total_amount_cents: int = Column(BigInteger, nullable=False, default=0)
	processed_count: int = Column(Integer, nullable=False, default=0)
	success_count: int = Column(Integer, nullable=False, default=0)
	failure_count: int = Column(Integer, nullable=False, default=0)

	# DRAFT / APPROVED / PROCESSING / COMPLETED / FAILED / CANCELLED
	status: str = Column(String(20), nullable=False, default="DRAFT")
	approved_by: str | None = Column(String(64), nullable=True)
	approved_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	started_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	completed_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

	# Summary of results as JSONB (success_ids, failure_reasons, etc.)
	result_summary: dict | None = Column(JSONB, nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	lines: list["DisbursementLine"] = relationship(
		"DisbursementLine",
		foreign_keys="DisbursementLine.batch_id",
		back_populates="batch",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return (
			f"<DisbursementBatch {self.id!r}"
			f" ref={self.batch_reference!r}"
			f" status={self.status!r}"
			f" total={self.total_amount_cents}>"
		)


class DisbursementLine(Model):
	"""Single recipient line within a DisbursementBatch.

	Status: PENDING / COMPLETED / FAILED / SKIPPED.
	txn_id is set once send_money completes for this line.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_disbursement_line"
	__table_args__ = (
		Index("ix_mm_dline_batch_id", "batch_id"),
		Index("ix_mm_dline_status", "status"),
		Index("ix_mm_dline_msisdn", "msisdn"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)

	batch_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_disbursement_batch.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	msisdn: str = Column(String(20), nullable=False)
	amount_cents: int = Column(Integer, nullable=False)
	narration: str | None = Column(String(255), nullable=True)

	# PENDING / COMPLETED / FAILED / SKIPPED
	status: str = Column(String(20), nullable=False, default="PENDING")
	txn_id: str | None = Column(String(50), nullable=True)
	failure_reason: str | None = Column(Text, nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	processed_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

	batch: "DisbursementBatch" = relationship(
		"DisbursementBatch",
		foreign_keys=[batch_id],
		back_populates="lines",
	)

	def __repr__(self) -> str:
		return (
			f"<DisbursementLine msisdn={self.msisdn!r}"
			f" amount={self.amount_cents}"
			f" status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# FraudSignal  (HIGH: fraud scoring + device/SIM-swap detection)
# ---------------------------------------------------------------------------

class FraudSignal(ImmutableRecordMixin, Model):
	"""Immutable fraud signal written on every transaction attempt.

	signal_type values: SIM_SWAP_RECENT / NEW_DEVICE_FINGERPRINT /
	VELOCITY_BREACH / GEO_ANOMALY / ROUND_TRIP_DETECTED / NEW_ACCOUNT_LARGE_CREDIT.
	score is 0–100; ≥80 blocks the transaction, 50–79 triggers OTP re-auth.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_fraud_signal"
	__table_args__ = (
		Index("ix_mm_fraud_wallet_id", "wallet_id"),
		Index("ix_mm_fraud_type", "signal_type"),
		Index("ix_mm_fraud_score", "score"),
		Index("ix_mm_fraud_created", "created_at"),
		Index("ix_mm_fraud_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	wallet_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_wallet.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	# Nullable — signal may be raised before txn is persisted
	mm_transaction_id: str | None = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_transaction.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

	signal_type: str = Column(String(40), nullable=False)
	# 0–100 composite score for this signal
	score: int = Column(SmallInteger, nullable=False, default=0)
	# Raw signal metadata (device info, geo coords, velocity window, etc.)
	metadata_json: dict | None = Column(JSONB, nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	wallet: "MobileWallet" = relationship("MobileWallet", foreign_keys=[wallet_id])

	def __repr__(self) -> str:
		return (
			f"<FraudSignal wallet={self.wallet_id!r}"
			f" type={self.signal_type!r}"
			f" score={self.score}>"
		)


FraudSignal._register_immutability()


# ---------------------------------------------------------------------------
# NotificationRequest  (HIGH: transactional notification queue)
# ---------------------------------------------------------------------------

class NotificationRequest(Model):
	"""Transactional notification record written in the same DB txn as the payment.

	channel: SMS / PUSH / USSD / WHATSAPP.
	priority: 1 (highest) – 5 (lowest).
	A delivery worker resolves template_code, renders it with context_json,
	and dispatches via pluggable NotificationAdapter.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_notification_request"
	__table_args__ = (
		Index("ix_mm_notif_msisdn", "recipient_msisdn"),
		Index("ix_mm_notif_channel", "channel"),
		Index("ix_mm_notif_scheduled", "scheduled_at"),
		Index("ix_mm_notif_sent", "sent_at"),
		Index("ix_mm_notif_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	recipient_msisdn: str = Column(String(20), nullable=False, index=True)
	# SMS / PUSH / USSD / WHATSAPP
	channel: str = Column(String(20), nullable=False, default="SMS")
	# Template key, e.g. "mm.send_money.debit_advice"
	template_code: str = Column(String(80), nullable=False)
	# Variables for template rendering
	context_json: dict = Column(JSONB, nullable=False, default=dict)

	# 1 = highest priority
	priority: int = Column(SmallInteger, nullable=False, default=2)
	scheduled_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	sent_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	# PENDING / SENT / FAILED / CANCELLED
	status: str = Column(String(20), nullable=False, default="PENDING")
	failure_reason: str | None = Column(Text, nullable=True)
	attempts: int = Column(Integer, nullable=False, default=0)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<NotificationRequest {self.template_code!r}"
			f" to={self.recipient_msisdn!r}"
			f" channel={self.channel!r}"
			f" status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# MMReconciliationRun / ReconciliationBreak  (HIGH: EOD reconciliation)
# ---------------------------------------------------------------------------

class MMReconciliationRun(AuditMixin, Model):
	"""End-of-day reconciliation run record.

	Status: RUNNING / COMPLETED / FAILED.
	A run checks every active wallet's computed balance against its
	mm_transaction ledger sum and GL subledger balance.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_reconciliation_run"
	__table_args__ = (
		Index("ix_mm_recon_run_date", "run_date"),
		Index("ix_mm_recon_status", "status"),
		Index("ix_mm_recon_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "run_date", name="uq_mm_recon_run_date"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	run_date: Any = Column(Date, nullable=False)
	# RUNNING / COMPLETED / FAILED
	status: str = Column(String(20), nullable=False, default="RUNNING")

	total_wallets_checked: int = Column(Integer, nullable=False, default=0)
	breaks_found: int = Column(Integer, nullable=False, default=0)
	breaks_auto_resolved: int = Column(Integer, nullable=False, default=0)

	started_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	completed_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	error_message: str | None = Column(Text, nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	breaks: list["ReconciliationBreak"] = relationship(
		"ReconciliationBreak",
		foreign_keys="ReconciliationBreak.run_id",
		back_populates="run",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return (
			f"<MMReconciliationRun date={self.run_date}"
			f" status={self.status!r}"
			f" breaks={self.breaks_found}>"
		)


class ReconciliationBreak(ImmutableRecordMixin, Model):
	"""Immutable record of a balance discrepancy found during a reconciliation run.

	break_type: LEDGER_MISMATCH / GL_MISMATCH / MISSING_WALLET / UNPOSTED_TXN.
	Auto-resolved timing differences are marked resolved_at with resolution_note.
	Residual breaks are escalated to ops via event emission.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_reconciliation_break"
	__table_args__ = (
		Index("ix_mm_recon_break_run", "run_id"),
		Index("ix_mm_recon_break_wallet", "wallet_id"),
		Index("ix_mm_recon_break_type", "break_type"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)

	run_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_reconciliation_run.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	wallet_id: str | None = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_wallet.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)

	# LEDGER_MISMATCH / GL_MISMATCH / MISSING_WALLET / UNPOSTED_TXN
	break_type: str = Column(String(30), nullable=False)

	expected_balance_cents: int = Column(BigInteger, nullable=False, default=0)
	actual_balance_cents: int = Column(BigInteger, nullable=False, default=0)
	gl_balance_cents: int = Column(BigInteger, nullable=False, default=0)
	# Difference: expected - actual
	variance_cents: int = Column(BigInteger, nullable=False, default=0)

	# OPEN / AUTO_RESOLVED / ESCALATED
	resolution_status: str = Column(String(20), nullable=False, default="OPEN")
	resolved_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	resolution_note: str | None = Column(Text, nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	run: "MMReconciliationRun" = relationship(
		"MMReconciliationRun",
		foreign_keys=[run_id],
		back_populates="breaks",
	)

	def __repr__(self) -> str:
		return (
			f"<ReconciliationBreak type={self.break_type!r}"
			f" wallet={self.wallet_id!r}"
			f" variance={self.variance_cents}>"
		)


ReconciliationBreak._register_immutability()


# ---------------------------------------------------------------------------
# WalletAuditEvent  (HIGH: immutable audit trail)
# ---------------------------------------------------------------------------

class WalletAuditEvent(ImmutableRecordMixin, Model):
	"""Append-only audit log for every wallet state transition.

	Captures actor, IP, device fingerprint, and before/after state JSON.
	No UPDATE/DELETE should ever be issued against this table.
	event_type examples: PIN_SET / KYC_UPGRADED / STATUS_CHANGED /
	LIMIT_OVERRIDE / TRANSACTION / REACTIVATION.
	"""

	__allow_unmapped__ = True
	__tablename__ = "mm_wallet_audit_event"
	__table_args__ = (
		Index("ix_mm_audit_wallet_id", "wallet_id"),
		Index("ix_mm_audit_event_type", "event_type"),
		Index("ix_mm_audit_actor", "actor_id"),
		Index("ix_mm_audit_created", "created_at"),
		Index("ix_mm_audit_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id: str = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id: str = Column(String(64), nullable=False, index=True)

	wallet_id: str = Column(
		UUID(as_uuid=False),
		ForeignKey("mm_wallet.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	# e.g. "PIN_SET", "KYC_UPGRADED", "STATUS_CHANGED", "TRANSACTION", "REACTIVATION"
	event_type: str = Column(String(40), nullable=False)

	# Actor who triggered the event
	actor_id: str | None = Column(String(64), nullable=True)
	# CUSTOMER / AGENT / OPERATOR / SYSTEM
	actor_type: str = Column(String(20), nullable=False, default="SYSTEM")
	ip_address: str | None = Column(String(45), nullable=True)
	device_fingerprint: str | None = Column(String(128), nullable=True)

	before_state_json: dict | None = Column(JSONB, nullable=True)
	after_state_json: dict | None = Column(JSONB, nullable=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	wallet: "MobileWallet" = relationship("MobileWallet", foreign_keys=[wallet_id])

	def __repr__(self) -> str:
		return (
			f"<WalletAuditEvent wallet={self.wallet_id!r}"
			f" type={self.event_type!r}"
			f" actor={self.actor_id!r}>"
		)


WalletAuditEvent._register_immutability()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"MobileWallet",
	"MobileTransaction",
	"Agent",
	"AgentCommission",
	"MerchantTill",
	# New models — CRITICAL
	"FeeSchedule",
	"MMOutboxEvent",
	"MMGLJournalLine",
	# New models — HIGH
	"MMStandingOrder",
	"DisbursementBatch",
	"DisbursementLine",
	"FraudSignal",
	"NotificationRequest",
	"MMReconciliationRun",
	"ReconciliationBreak",
	"WalletAuditEvent",
]
