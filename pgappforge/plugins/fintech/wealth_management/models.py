"""
pgappforge/plugins/fintech/wealth_management/models.py

Wealth Management models — clients, portfolios, holdings, orders, performance.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True))
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents (BigInteger where very large)
  - Quantities: NUMERIC(18,6) for fractional share/unit support

Table name convention: ft_wlth_<entity>
"""
from __future__ import annotations

import uuid
import logging
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# WealthClient
# ---------------------------------------------------------------------------

class WealthClient(AuditMixin, Model):
	"""Wealth management client profile — suitability, AUM, and relationship data."""

	__allow_unmapped__ = True
	__tablename__ = "ft_wlth_client"
	__table_args__ = (
		Index("ix_ft_wlth_client_tenant", "tenant_id"),
		Index("ix_ft_wlth_client_customer", "customer_id"),
		Index("ix_ft_wlth_client_rm", "relationship_manager_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	customer_id = Column(UUID(as_uuid=False), nullable=False, comment="FK to core banking customer")
	full_name = Column(String(200), nullable=False)

	# Suitability
	risk_profile = Column(
		String(15),
		nullable=False,
		default="BALANCED",
		comment="CONSERVATIVE | MODERATE | BALANCED | GROWTH | AGGRESSIVE",
	)
	suitability_score = Column(
		Integer,
		nullable=True,
		comment="0-100; computed by _assess_suitability",
	)

	# AUM
	total_aum_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Total assets under management in cents",
	)

	# Financial profile
	investment_experience = Column(
		String(12),
		nullable=False,
		default="NONE",
		comment="NONE | BASIC | INTERMEDIATE | EXPERT",
	)
	annual_income_cents = Column(BigInteger, nullable=True)
	liquid_assets_cents = Column(BigInteger, nullable=True)
	investment_horizon_years = Column(Integer, nullable=True)

	# Relationship
	relationship_manager_id = Column(UUID(as_uuid=False), nullable=True)

	# Timestamps
	onboarded_at = Column(
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
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	portfolios: list["Portfolio"] = relationship(
		"Portfolio",
		back_populates="client",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def __repr__(self) -> str:
		return f"<WealthClient {self.full_name} risk={self.risk_profile}>"


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class Portfolio(AuditMixin, Model):
	"""Investment portfolio — holds mandate, benchmark, allocation target, and fee."""

	__allow_unmapped__ = True
	__tablename__ = "ft_wlth_portfolio"
	__table_args__ = (
		Index("ix_ft_wlth_portfolio_tenant", "tenant_id"),
		Index("ix_ft_wlth_portfolio_client", "client_id"),
		Index("ix_ft_wlth_portfolio_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	client_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_wlth_client.id", ondelete="CASCADE"),
		nullable=False,
	)
	name = Column(String(200), nullable=False)
	mandate_type = Column(
		String(20),
		nullable=False,
		comment="ADVISORY | DISCRETIONARY | MODEL | EXECUTION_ONLY",
	)
	benchmark = Column(String(50), nullable=True, comment='e.g. "NSE20"')
	base_currency = Column(String(3), nullable=False, default="KES")

	# Target allocation — {asset_class: pct, ...} — must sum to 100
	target_allocation: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Asset class allocation: {EQUITY: 60, BOND: 30, CASH: 10}",
	)

	management_fee_pct = Column(
		Numeric(5, 4),
		nullable=False,
		default=0,
		comment="Annual management fee as decimal (e.g. 0.0150 = 1.5%)",
	)
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | SUSPENDED | CLOSED",
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
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	client: "WealthClient" = relationship("WealthClient", back_populates="portfolios")
	holdings: list["PortfolioHolding"] = relationship(
		"PortfolioHolding",
		back_populates="portfolio",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)
	orders: list["WealthOrder"] = relationship(
		"WealthOrder",
		back_populates="portfolio",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)
	performance_reports: list["PerformanceReport"] = relationship(
		"PerformanceReport",
		back_populates="portfolio",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def __repr__(self) -> str:
		return f"<Portfolio {self.name} mandate={self.mandate_type}>"


# ---------------------------------------------------------------------------
# PortfolioHolding
# ---------------------------------------------------------------------------

class PortfolioHolding(AuditMixin, Model):
	"""Current holding of a specific asset within a portfolio."""

	__allow_unmapped__ = True
	__tablename__ = "ft_wlth_holding"
	__table_args__ = (
		Index("ix_ft_wlth_holding_tenant", "tenant_id"),
		Index("ix_ft_wlth_holding_portfolio", "portfolio_id"),
		Index("ix_ft_wlth_holding_asset", "asset_code"),
		UniqueConstraint("portfolio_id", "asset_code", name="uq_ft_wlth_holding_portfolio_asset"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	portfolio_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_wlth_portfolio.id", ondelete="CASCADE"),
		nullable=False,
	)

	asset_class = Column(
		String(30),
		nullable=False,
		comment="EQUITY | BOND | MONEY_MARKET | REAL_ESTATE | CASH | ALTERNATIVE",
	)
	asset_code = Column(String(20), nullable=False, comment="Ticker / ISIN / fund code")
	asset_name = Column(String(200), nullable=False)

	# Quantity / cost basis
	quantity = Column(Numeric(18, 6), nullable=False, default=0)
	avg_cost_cents = Column(BigInteger, nullable=False, default=0, comment="Weighted avg cost per unit in cents")

	# Mark-to-market
	current_price_cents = Column(BigInteger, nullable=False, default=0, comment="Last known price per unit in cents")
	current_value_cents = Column(BigInteger, nullable=False, default=0, comment="quantity * current_price_cents")
	unrealised_pnl_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="current_value_cents - (quantity * avg_cost_cents)",
	)

	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	portfolio: "Portfolio" = relationship("Portfolio", back_populates="holdings")

	def __repr__(self) -> str:
		return f"<PortfolioHolding {self.asset_code} qty={self.quantity}>"


# ---------------------------------------------------------------------------
# WealthOrder
# ---------------------------------------------------------------------------

class WealthOrder(AuditMixin, Model):
	"""Buy/sell order routed to a broker on behalf of a portfolio."""

	__allow_unmapped__ = True
	__tablename__ = "ft_wlth_order"
	__table_args__ = (
		Index("ix_ft_wlth_order_tenant", "tenant_id"),
		Index("ix_ft_wlth_order_portfolio", "portfolio_id"),
		Index("ix_ft_wlth_order_status", "status"),
		Index("ix_ft_wlth_order_broker_ref", "broker_reference"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	portfolio_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_wlth_portfolio.id", ondelete="CASCADE"),
		nullable=False,
	)

	asset_code = Column(String(20), nullable=False)
	asset_name = Column(String(200), nullable=False)
	order_side = Column(String(4), nullable=False, comment="BUY | SELL")
	order_type = Column(String(6), nullable=False, comment="MARKET | LIMIT")

	# Quantity or amount-driven order
	quantity = Column(Numeric(18, 6), nullable=True)
	amount_cents = Column(BigInteger, nullable=True, comment="Amount-driven order in cents")
	limit_price_cents = Column(BigInteger, nullable=True, comment="Limit price per unit in cents")

	status = Column(
		String(12),
		nullable=False,
		default="PENDING",
		comment="PENDING | SUBMITTED | PARTIALLY_FILLED | FILLED | CANCELLED | REJECTED",
	)

	# Execution tracking
	executed_quantity = Column(Numeric(18, 6), nullable=False, default=0)
	executed_amount_cents = Column(BigInteger, nullable=False, default=0)
	broker_reference = Column(String(100), nullable=True)

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
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	portfolio: "Portfolio" = relationship("Portfolio", back_populates="orders")

	def __repr__(self) -> str:
		return f"<WealthOrder {self.order_side} {self.asset_code} status={self.status}>"


# ---------------------------------------------------------------------------
# PerformanceReport
# ---------------------------------------------------------------------------

class PerformanceReport(AuditMixin, Model):
	"""Monthly performance snapshot for a portfolio."""

	__allow_unmapped__ = True
	__tablename__ = "ft_wlth_performance"
	__table_args__ = (
		Index("ix_ft_wlth_performance_tenant", "tenant_id"),
		Index("ix_ft_wlth_performance_portfolio", "portfolio_id"),
		UniqueConstraint("portfolio_id", "period", name="uq_ft_wlth_performance_portfolio_period"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	portfolio_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_wlth_portfolio.id", ondelete="CASCADE"),
		nullable=False,
	)

	period = Column(String(7), nullable=False, comment="YYYY-MM")

	# Values in cents
	opening_value_cents = Column(BigInteger, nullable=False, default=0)
	closing_value_cents = Column(BigInteger, nullable=False, default=0)
	net_contributions_cents = Column(BigInteger, nullable=False, default=0, comment="Deposits minus withdrawals")

	# P&L components
	realised_pnl_cents = Column(BigInteger, nullable=False, default=0)
	unrealised_pnl_cents = Column(BigInteger, nullable=False, default=0)
	management_fee_cents = Column(BigInteger, nullable=False, default=0)

	# Returns
	return_pct = Column(
		Numeric(8, 4),
		nullable=False,
		default=0,
		comment="(closing - opening - net_contributions) / opening * 100",
	)
	benchmark_return_pct = Column(Numeric(8, 4), nullable=True)

	generated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	portfolio: "Portfolio" = relationship("Portfolio", back_populates="performance_reports")

	def __repr__(self) -> str:
		return f"<PerformanceReport portfolio={self.portfolio_id} period={self.period} return={self.return_pct}%>"


__all__ = [
	"WealthClient",
	"Portfolio",
	"PortfolioHolding",
	"WealthOrder",
	"PerformanceReport",
]
