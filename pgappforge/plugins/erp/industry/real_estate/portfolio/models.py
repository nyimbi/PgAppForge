"""
pgappforge/plugins/erp/industry/real_estate/portfolio/models.py

SQLAlchemy models for the Real Estate Portfolio Analytics sub-plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All monetary amounts: INTEGER cents ONLY
  - Decimal arithmetic (ROUND_HALF_UP) for ratios
  - JSONB for allocations, flexible payloads
  - PostgreSQL-only (no dialect fallback)

Table name convention: re_<entity>
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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# PropertyPortfolio
# ---------------------------------------------------------------------------

class PropertyPortfolio(AuditMixin, Model):
	"""Named collection of properties held under a common investment structure.

	status: ACTIVE (accepting new properties / investors) or CLOSED (wound down).
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_portfolio"
	__table_args__ = (
		Index("ix_re_portfolio_tenant", "tenant_id"),
		Index("ix_re_portfolio_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE/CLOSED",
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

	properties: list[PortfolioProperty] = relationship(
		"PortfolioProperty",
		back_populates="portfolio",
		cascade="all, delete-orphan",
		lazy="select",
	)
	investor_holdings: list[InvestorHolding] = relationship(
		"InvestorHolding",
		back_populates="portfolio",
		cascade="all, delete-orphan",
		lazy="select",
	)
	distributions: list[DistributionRecord] = relationship(
		"DistributionRecord",
		back_populates="portfolio",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<PropertyPortfolio name={self.name!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# PortfolioProperty
# ---------------------------------------------------------------------------

class PortfolioProperty(Model):
	"""Association between a portfolio and a property, with acquisition economics.

	acquisition_cost_cents: total price paid at acquisition (integer cents).
	current_value_cents: NULL until an external valuation is recorded.
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_portfolio_property"
	__table_args__ = (
		UniqueConstraint("portfolio_id", "property_id", name="uq_re_portfolio_property"),
		Index("ix_re_portfolio_property_portfolio", "portfolio_id"),
		Index("ix_re_portfolio_property_property", "property_id"),
		Index("ix_re_portfolio_property_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	portfolio_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_portfolio.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	acquisition_date = Column(Date, nullable=False)
	acquisition_cost_cents = Column(Integer, nullable=False, comment="Total acquisition price in cents")
	current_value_cents = Column(
		Integer,
		nullable=True,
		comment="Latest known market value in cents; NULL until first valuation",
	)

	portfolio: PropertyPortfolio = relationship("PropertyPortfolio", back_populates="properties", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<PortfolioProperty portfolio={self.portfolio_id!r} "
			f"property={self.property_id!r} acq={self.acquisition_cost_cents}¢>"
		)


# ---------------------------------------------------------------------------
# PropertyDebt
# ---------------------------------------------------------------------------

class PropertyDebt(AuditMixin, Model):
	"""Debt instrument secured against a property.

	interest_rate: annual percentage rate stored as NUMERIC(6,4), e.g. 7.5000 = 7.5%.
	lien_position: 1 = first lien (senior), 2 = second lien, etc.
	monthly_payment_cents: NULL for interest-only or variable-payment structures.
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_debt"
	__table_args__ = (
		Index("ix_re_debt_property", "property_id"),
		Index("ix_re_debt_tenant", "tenant_id"),
		Index("ix_re_debt_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	lender_name = Column(String(255), nullable=False)
	loan_type = Column(
		String(20),
		nullable=False,
		default="MORTGAGE",
		server_default="MORTGAGE",
		comment="MORTGAGE/CONSTRUCTION/BRIDGE/HELOC",
	)
	original_principal_cents = Column(Integer, nullable=False, comment="Original loan amount in cents")
	current_balance_cents = Column(Integer, nullable=False, comment="Outstanding principal balance in cents")
	interest_rate = Column(
		Numeric(6, 4),
		nullable=False,
		comment="Annual interest rate as %, e.g. 7.5000 = 7.5% p.a.",
	)
	amortization_years = Column(Integer, nullable=True, comment="Total amortization period in years; NULL = interest-only")
	maturity_date = Column(Date, nullable=True)
	payment_day_of_month = Column(Integer, nullable=False, default=1, server_default="1")
	monthly_payment_cents = Column(
		Integer,
		nullable=True,
		comment="Scheduled monthly payment in cents; NULL for variable-payment loans",
	)
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE/PAID_OFF/IN_DEFAULT",
	)
	lien_position = Column(
		Integer,
		nullable=False,
		default=1,
		server_default="1",
		comment="1=first lien (senior), 2=second lien, etc.",
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

	payments: list[DebtPayment] = relationship(
		"DebtPayment",
		back_populates="debt",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<PropertyDebt property={self.property_id!r} lender={self.lender_name!r} "
			f"balance={self.current_balance_cents}¢ rate={self.interest_rate}%>"
		)


# ---------------------------------------------------------------------------
# DebtPayment
# ---------------------------------------------------------------------------

class DebtPayment(Model):
	"""Individual payment applied to a PropertyDebt.

	principal_cents + interest_cents == total_payment_cents (enforced in service).
	remaining_balance_cents is the post-payment balance recorded at payment time.
	Immutable once created — corrections require a new DebtPayment record.
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_debt_payment"
	__table_args__ = (
		Index("ix_re_debt_payment_debt", "debt_id"),
		Index("ix_re_debt_payment_tenant", "tenant_id"),
		Index("ix_re_debt_payment_date", "payment_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	debt_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_debt.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	payment_date = Column(Date, nullable=False)
	total_payment_cents = Column(Integer, nullable=False, comment="Total payment amount in cents")
	principal_cents = Column(Integer, nullable=False, comment="Principal portion of payment in cents")
	interest_cents = Column(Integer, nullable=False, comment="Interest portion of payment in cents")
	remaining_balance_cents = Column(Integer, nullable=False, comment="Post-payment outstanding principal in cents")
	status = Column(
		String(10),
		nullable=False,
		default="PAID",
		server_default="PAID",
		comment="PAID/REVERSED",
	)

	debt: PropertyDebt = relationship("PropertyDebt", back_populates="payments", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<DebtPayment debt={self.debt_id!r} date={self.payment_date} "
			f"total={self.total_payment_cents}¢ principal={self.principal_cents}¢>"
		)


# ---------------------------------------------------------------------------
# CapExRecord
# ---------------------------------------------------------------------------

class CapExRecord(AuditMixin, Model):
	"""Capital expenditure or maintenance cost recorded against a property.

	is_capitalizable: True if the spend increases the asset's depreciable basis.
	budget_cents: NULL if no budget was pre-approved for this item.
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_capex"
	__table_args__ = (
		Index("ix_re_capex_property", "property_id"),
		Index("ix_re_capex_tenant", "tenant_id"),
		Index("ix_re_capex_date", "capex_date"),
		Index("ix_re_capex_category", "category"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	description = Column(String(500), nullable=False)
	capex_cents = Column(Integer, nullable=False, comment="Actual spend in cents")
	capex_date = Column(Date, nullable=False)
	category = Column(
		String(20),
		nullable=False,
		default="IMPROVEMENT",
		server_default="IMPROVEMENT",
		comment="IMPROVEMENT/REPAIR/REPLACEMENT/MAINTENANCE",
	)
	budget_cents = Column(Integer, nullable=True, comment="Pre-approved budget in cents; NULL if unbudgeted")
	vendor_name = Column(String(255), nullable=True)
	is_capitalizable = Column(
		Boolean,
		nullable=False,
		default=True,
		server_default="true",
		comment="True if spend increases depreciable asset basis",
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
			f"<CapExRecord property={self.property_id!r} "
			f"category={self.category!r} amount={self.capex_cents}¢ date={self.capex_date}>"
		)


# ---------------------------------------------------------------------------
# InvestorHolding
# ---------------------------------------------------------------------------

class InvestorHolding(AuditMixin, Model):
	"""Equity ownership stake held by an investor in a portfolio.

	ownership_pct: NUMERIC(7,4), range 0.0000–100.0000.
	investment_cents: total capital contributed by this investor (integer cents).
	investor_party_id: soft FK to foundation.Party — no cross-schema FK enforced.
	UniqueConstraint(portfolio_id, investor_party_id) scoped to ACTIVE holdings
	(partial unique index enforced at DB level; the model constraint is advisory).
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_investor_holding"
	__table_args__ = (
		Index("ix_re_investor_holding_portfolio", "portfolio_id"),
		Index("ix_re_investor_holding_investor", "investor_party_id"),
		Index("ix_re_investor_holding_tenant", "tenant_id"),
		Index("ix_re_investor_holding_status", "status"),
		# Partial unique index enforced at DDL level: one ACTIVE holding per investor per portfolio.
		# Declared here as a named index; actual UNIQUE WHERE status='ACTIVE' via migration.
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	portfolio_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_portfolio.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	investor_party_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Soft FK to foundation.Party — investor identity",
	)
	ownership_pct = Column(
		Numeric(7, 4),
		nullable=False,
		comment="Ownership percentage 0.0000–100.0000",
	)
	investment_cents = Column(
		Integer,
		nullable=False,
		comment="Total capital contributed by this investor in cents",
	)
	since_date = Column(Date, nullable=False, comment="Date investor joined the portfolio")
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE/EXITED",
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

	portfolio: PropertyPortfolio = relationship("PropertyPortfolio", back_populates="investor_holdings", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<InvestorHolding portfolio={self.portfolio_id!r} "
			f"investor={self.investor_party_id!r} pct={self.ownership_pct}% status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# DistributionRecord
# ---------------------------------------------------------------------------

class DistributionRecord(Model):
	"""Investor distribution for a portfolio period.

	period: ISO year-month string, e.g. "2025-11".
	allocations JSONB: [{investor_party_id, ownership_pct, amount_cents}]
	status: DRAFT (calculated, not yet paid) / PAID (disbursed to investors).
	distributed_at: NULL until status transitions to PAID.
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_distribution"
	__table_args__ = (
		Index("ix_re_distribution_portfolio", "portfolio_id"),
		Index("ix_re_distribution_tenant", "tenant_id"),
		Index("ix_re_distribution_period", "period"),
		Index("ix_re_distribution_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	portfolio_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_portfolio.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	period = Column(String(7), nullable=False, comment="ISO year-month, e.g. '2025-11'")
	total_distributable_cents = Column(
		Integer,
		nullable=False,
		comment="Total amount to distribute across all investors in cents",
	)
	allocations = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{investor_party_id, ownership_pct, amount_cents}]",
	)
	distributed_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when distribution was paid; NULL while DRAFT",
	)
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT/PAID",
	)

	portfolio: PropertyPortfolio = relationship("PropertyPortfolio", back_populates="distributions", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<DistributionRecord portfolio={self.portfolio_id!r} "
			f"period={self.period!r} total={self.total_distributable_cents}¢ status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"PropertyPortfolio",
	"PortfolioProperty",
	"PropertyDebt",
	"DebtPayment",
	"CapExRecord",
	"InvestorHolding",
	"DistributionRecord",
]
