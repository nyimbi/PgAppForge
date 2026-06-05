"""
pgappforge/plugins/fintech/treasury/models.py

Treasury models — FX rates, FX deals, open positions, and treasury limits.

Design rules enforced here:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: BigInteger cents — never Decimal/float in storage
  - Rates: Numeric(18, 8) — sufficient precision for FX mid-market rates
  - FintechFXDeal rows are INSERT-ONLY once settled (status changes tracked via
    UPDATE on the same row; positional P&L is computed at settlement time)
  - PostgreSQL ONLY — JSONB for extensible metadata

Table name convention: fx_<entity>
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, date, timezone
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
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# FXRate — live and historical exchange rates
# ---------------------------------------------------------------------------

class FXRate(AuditMixin, Model):
	"""Exchange rate record — bid/offer/mid for a currency pair.

	A new row is inserted for every rate upload; the previous active rate
	for the same (tenant_id, base_currency, quote_currency, rate_type) pair
	is marked is_active=False and valid_to is stamped at upload time.

	rate_type discriminates tenors:
	  SPOT | FORWARD_1M | FORWARD_3M | FORWARD_6M | FORWARD_12M | SWAP

	rate_source:
	  REUTERS | BLOOMBERG | CBK | MANUAL

	All rates are quoted as: 1 unit of base_currency = rate units of quote_currency.
	e.g. base=USD, quote=KES, mid_rate=130.5 → 1 USD = 130.5 KES
	"""

	__allow_unmapped__ = True
	__tablename__ = "fx_rate"
	__table_args__ = (
		Index("ix_fx_rate_pair", "tenant_id", "base_currency", "quote_currency"),
		Index("ix_fx_rate_type", "rate_type"),
		Index("ix_fx_rate_active", "is_active"),
		Index("ix_fx_rate_valid_from", "valid_from"),
		Index("ix_fx_rate_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	base_currency = Column(
		String(3),
		nullable=False,
		comment="ISO 4217 base currency code e.g. USD",
	)
	quote_currency = Column(
		String(3),
		nullable=False,
		comment="ISO 4217 quote currency code e.g. KES",
	)
	rate_type = Column(
		String(20),
		nullable=False,
		default="SPOT",
		comment="SPOT | FORWARD_1M | FORWARD_3M | FORWARD_6M | FORWARD_12M | SWAP",
	)

	# Rates — stored with 8dp to accommodate cross-rates and exotics
	bid_rate = Column(
		Numeric(18, 8),
		nullable=False,
		comment="Interbank bid: rate at which market makers buy base currency",
	)
	offer_rate = Column(
		Numeric(18, 8),
		nullable=False,
		comment="Interbank offer: rate at which market makers sell base currency",
	)
	mid_rate = Column(
		Numeric(18, 8),
		nullable=False,
		comment="Mid-market rate = (bid + offer) / 2",
	)

	rate_source = Column(
		String(50),
		nullable=False,
		default="MANUAL",
		comment="REUTERS | BLOOMBERG | CBK | MANUAL",
	)

	valid_from = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		comment="Timestamp from which this rate is effective",
	)
	valid_to = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL = currently active; stamped when superseded by a new rate",
	)
	is_active = Column(
		Boolean,
		nullable=False,
		default=True,
		comment="True only for the current live rate for this pair/type",
	)

	# Extensible metadata (pip spreads, fixing source, etc.)
	meta: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
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

	def __repr__(self) -> str:
		return (
			f"<FXRate {self.base_currency}/{self.quote_currency} "
			f"type={self.rate_type!r} mid={self.mid_rate} "
			f"active={self.is_active}>"
		)


# ---------------------------------------------------------------------------
# FintechFXDeal — individual foreign exchange deal
# ---------------------------------------------------------------------------

class FintechFXDeal(AuditMixin, Model):
	"""Individual FX deal — spot, forward, swap, or NDF.

	Monetary amounts are stored as BigInteger cents in the respective currency
	(not a single base currency).  The exchange_rate column records the agreed
	contractual rate.

	deal_type:
	  SPOT     — settlement T+2 (or same-day for KES domestic)
	  FORWARD  — settlement at a fixed future date (maturity_date)
	  SWAP     — simultaneous spot buy + forward sell (or vice-versa)
	  NDF      — non-deliverable forward; cash-settled at maturity

	status flow:
	  BOOKED → CONFIRMED → SETTLED
	                      → CANCELLED (only before confirmation)

	pnl_cents: realised P&L computed at settlement vs revaluation_rate.
	revaluation_rate: MTM rate used for unrealised P&L (updated daily).
	"""

	__allow_unmapped__ = True
	__tablename__ = "fx_deal"
	__table_args__ = (
		Index("ix_fx_deal_number", "deal_number"),
		Index("ix_fx_deal_tenant", "tenant_id"),
		Index("ix_fx_deal_status", "status"),
		Index("ix_fx_deal_value_date", "value_date"),
		Index("ix_fx_deal_counterparty", "counterparty_id"),
		Index("ix_fx_deal_trader", "trader_id"),
		UniqueConstraint("tenant_id", "deal_number", name="uq_fx_deal_number_tenant"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	deal_number = Column(
		String(20),
		nullable=False,
		comment="Human-readable deal reference e.g. FX-20260604-001",
	)
	deal_type = Column(
		String(10),
		nullable=False,
		comment="SPOT | FORWARD | SWAP | NDF",
	)
	status = Column(
		String(20),
		nullable=False,
		default="BOOKED",
		comment="BOOKED | CONFIRMED | SETTLED | CANCELLED",
	)

	# Currency pair and amounts
	bought_currency = Column(
		String(3),
		nullable=False,
		comment="Currency the bank is buying (receiving)",
	)
	sold_currency = Column(
		String(3),
		nullable=False,
		comment="Currency the bank is selling (paying)",
	)
	bought_amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Amount bought in minor units of bought_currency",
	)
	sold_amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Amount sold in minor units of sold_currency",
	)
	exchange_rate = Column(
		Numeric(18, 8),
		nullable=False,
		comment="Agreed contractual rate: 1 bought_currency = exchange_rate sold_currency",
	)

	# Dates
	trade_date = Column(Date, nullable=False, comment="Date the deal was executed")
	value_date = Column(
		Date,
		nullable=False,
		comment="Settlement date (T+2 for SPOT; forward date otherwise)",
	)
	maturity_date = Column(
		Date,
		nullable=True,
		comment="Maturity date for FORWARD/SWAP/NDF; NULL for SPOT",
	)

	# Settlement / confirmation
	counterparty_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id"),
		nullable=False,
		index=True,
		comment="FK to erp_party (counterparty bank/client)",
	)
	nostro_account_code = Column(
		String(20),
		nullable=False,
		comment="Bank's nostro account code for the bought currency leg",
	)
	vostro_account_code = Column(
		String(20),
		nullable=False,
		comment="Bank's vostro/correspondent account for the sold currency leg",
	)
	trader_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to erp_party (trader/dealer); nullable for API-booked deals",
	)
	our_reference = Column(
		String(20),
		nullable=False,
		comment="Our internal deal reference sent to counterparty",
	)
	their_reference = Column(
		String(20),
		nullable=True,
		comment="Counterparty's reference for confirmation matching",
	)
	confirmation_sent_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp SWIFT/email confirmation was dispatched",
	)
	settled_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp settlement was marked complete",
	)

	# P&L tracking
	pnl_cents = Column(
		BigInteger,
		nullable=True,
		comment=(
			"Realised P&L in base currency cents at settlement. "
			"Positive = gain, negative = loss. NULL until settled."
		),
	)
	revaluation_rate = Column(
		Numeric(18, 8),
		nullable=True,
		comment="Latest MTM rate used for unrealised P&L (updated by revalue_positions)",
	)

	# Extensible metadata (SWIFT MTs, broker details, etc.)
	meta: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
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

	def __repr__(self) -> str:
		return (
			f"<FintechFXDeal {self.deal_number!r} "
			f"{self.bought_currency}/{self.sold_currency} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# FXPosition — net open position per currency per day
# ---------------------------------------------------------------------------

class FXPosition(AuditMixin, Model):
	"""Net open FX position for a currency on a given date.

	Maintained in real-time by TreasuryService as deals are booked and settled.
	One row per (tenant_id, currency_code, position_date); updated in-place
	via atomic SQL UPDATE to avoid race conditions.

	long_amount_cents:  total bought (inflows) in this currency today
	short_amount_cents: total sold (outflows) in this currency today
	net_position_cents: long - short (positive = net long, negative = net short)

	revaluation_pnl_cents: unrealised MTM P&L from latest revaluation run.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fx_position"
	__table_args__ = (
		Index("ix_fx_position_tenant", "tenant_id"),
		Index("ix_fx_position_currency", "currency_code"),
		Index("ix_fx_position_date", "position_date"),
		UniqueConstraint(
			"tenant_id", "currency_code", "position_date",
			name="uq_fx_position_tenant_ccy_date",
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

	currency_code = Column(String(3), nullable=False, comment="ISO 4217 currency code")
	position_date = Column(Date, nullable=False, comment="Business date for this position snapshot")

	long_amount_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Total bought (inflow) in this currency on position_date",
	)
	short_amount_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Total sold (outflow) in this currency on position_date",
	)
	# net_position_cents is a Python property; not a DB-generated column so it
	# remains portable and avoids DDL complexity.  Queries that need to filter
	# on net position should compute (long - short) in SQL directly.

	revaluation_rate = Column(
		Numeric(18, 8),
		nullable=True,
		comment="Latest revaluation rate applied (vs KES or functional currency)",
	)
	revaluation_pnl_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Unrealised MTM P&L in functional currency cents from latest revaluation",
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

	@property
	def net_position_cents(self) -> int:
		"""Computed net position: positive = net long, negative = net short."""
		return (self.long_amount_cents or 0) - (self.short_amount_cents or 0)

	def __repr__(self) -> str:
		return (
			f"<FXPosition {self.currency_code} "
			f"date={self.position_date!r} "
			f"net={self.net_position_cents}c>"
		)


# ---------------------------------------------------------------------------
# TreasuryLimit — risk limits on open positions, counterparties, etc.
# ---------------------------------------------------------------------------

class TreasuryLimit(AuditMixin, Model):
	"""Treasury risk limit — open position, counterparty, stop-loss, or deal size.

	limit_type:
	  OPEN_POSITION  — maximum net open position in a single currency
	  COUNTERPARTY   — maximum aggregate exposure to one counterparty
	  STOP_LOSS      — maximum cumulative daily loss before trading halts
	  DEAL_SIZE      — maximum single deal size

	breach_action:
	  WARN  — log breach and emit FXLimitBreachedEvent; deal proceeds
	  BLOCK — raise TreasuryLimitBreachError; deal is rejected

	currency_code and counterparty_id are contextual:
	  OPEN_POSITION limits → currency_code required
	  COUNTERPARTY limits  → counterparty_id required
	  STOP_LOSS/DEAL_SIZE  → currency_code optional (applies globally if NULL)
	"""

	__allow_unmapped__ = True
	__tablename__ = "fx_treasury_limit"
	__table_args__ = (
		Index("ix_fx_limit_tenant", "tenant_id"),
		Index("ix_fx_limit_type", "limit_type"),
		Index("ix_fx_limit_currency", "currency_code"),
		Index("ix_fx_limit_counterparty", "counterparty_id"),
		Index("ix_fx_limit_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")

	limit_type = Column(
		String(30),
		nullable=False,
		comment="OPEN_POSITION | COUNTERPARTY | STOP_LOSS | DEAL_SIZE",
	)
	currency_code = Column(
		String(3),
		nullable=True,
		comment="Applies to this currency only; NULL = applies globally",
	)
	counterparty_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="Applies to this counterparty only (COUNTERPARTY limit type)",
	)

	limit_amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Maximum allowed amount in functional currency cents",
	)
	current_utilisation_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Current utilisation in functional currency cents (updated in-place)",
	)

	breach_action = Column(
		String(10),
		nullable=False,
		default="WARN",
		comment="WARN = log + emit event; BLOCK = reject transaction",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	# Extensible metadata (approval details, review date, etc.)
	meta: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
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

	def __repr__(self) -> str:
		return (
			f"<TreasuryLimit {self.limit_type!r} "
			f"ccy={self.currency_code!r} "
			f"limit={self.limit_amount_cents}c "
			f"action={self.breach_action!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"FXRate",
	"FintechFXDeal",
	"FXPosition",
	"TreasuryLimit",
]
