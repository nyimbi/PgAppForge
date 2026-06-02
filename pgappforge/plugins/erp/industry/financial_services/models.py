"""
pgappforge/plugins/erp/industry/financial_services/models.py

Financial Services Cloud — SQLAlchemy models.

Design rules:
  - All PKs: UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL + AuditMixin
  - Monetary amounts: INTEGER cents — NEVER float
  - Financial records: NEVER UPDATE — INSERT correction entries only
  - lazy='select' throughout (SA 2.x, no 'dynamic')
  - JSONB for semi-structured data
  - Proper composite indexes for tenant-scoped queries

Table prefix: fin_
"""
from __future__ import annotations

import logging
import uuid
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

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# FinancialClient
# ---------------------------------------------------------------------------

class FinancialClient(AuditMixin, Model):
	"""A regulated financial-services client.

	Links to foundation.Party for identity (name, contacts, addresses, KYB
	documents).  This model carries only FS-specific attributes: risk profile,
	KYC status, AML score, sanctions state, relationship manager, and AUM.

	Immutable ledger note: never UPDATE total_aum_cents / net_worth_cents
	directly for audit purposes — issue a ClientWealthUpdatedEvent and INSERT
	a ClientHolding correction instead.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fin_financial_client"
	__table_args__ = (
		UniqueConstraint("client_number", name="uq_fin_client_number"),
		Index("ix_fin_client_tenant_type", "tenant_id", "client_type"),
		Index("ix_fin_client_kyc_status", "kyc_status"),
		Index("ix_fin_client_rm", "relationship_manager_id"),
		Index("ix_fin_client_party", "party_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Party linkage (foundation.Party)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
	)

	# Client identity
	client_number = Column(
		String(50),
		nullable=False,
		comment="Unique client reference number (auto-generated or user-supplied)",
	)
	client_type = Column(
		String(20),
		nullable=False,
		comment="INDIVIDUAL | CORPORATE | INSTITUTION",
	)

	# Risk & compliance
	risk_profile = Column(
		String(15),
		nullable=False,
		default="MEDIUM",
		comment="LOW | MEDIUM | HIGH | SPECULATIVE",
	)
	kyc_status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		comment="PENDING | APPROVED | REJECTED | EXPIRED",
	)
	kyc_completed_at = Column(DateTime(timezone=True), nullable=True)
	aml_score = Column(
		Numeric(5, 4),
		nullable=True,
		comment="Anti-money laundering risk score [0.0000, 1.0000]",
	)
	sanctions_screened_at = Column(DateTime(timezone=True), nullable=True)

	# Relationship
	relationship_manager_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
		comment="FK to ab_user (Employee/RM)",
	)
	onboarded_at = Column(DateTime(timezone=True), nullable=True)

	# Wealth (integer cents — never float)
	total_aum_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Total assets under management in minor currency units (cents)",
	)
	net_worth_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Declared net worth in minor currency units (cents)",
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
	accounts: list[PortfolioAccount] = relationship(
		"PortfolioAccount",
		back_populates="client",
		cascade="all, delete-orphan",
		lazy="select",
	)
	holdings: list[ClientHolding] = relationship(
		"ClientHolding",
		back_populates="client",
		cascade="all, delete-orphan",
		lazy="select",
	)
	screening_results: list[SanctionsScreeningResult] = relationship(
		"SanctionsScreeningResult",
		primaryjoin="FinancialClient.party_id == foreign(SanctionsScreeningResult.party_id)",
		lazy="select",
		viewonly=True,
	)

	def __repr__(self) -> str:
		return (
			f"<FinancialClient {self.id!r} #{self.client_number!r} "
			f"type={self.client_type!r} kyc={self.kyc_status!r}>"
		)


# ---------------------------------------------------------------------------
# PortfolioAccount
# ---------------------------------------------------------------------------

class PortfolioAccount(AuditMixin, Model):
	"""An account held by a FinancialClient.

	Balances are INTEGER cents. NEVER update balance_cents / available_balance_cents
	directly in application code — go through PortfolioAccountService.post_transaction()
	which maintains an immutable transaction ledger and emits domain events.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fin_portfolio_account"
	__table_args__ = (
		UniqueConstraint("account_number", name="uq_fin_account_number"),
		Index("ix_fin_account_client", "client_id"),
		Index("ix_fin_account_tenant_status", "tenant_id", "status"),
		Index("ix_fin_account_currency", "currency_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	client_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fin_financial_client.id", ondelete="RESTRICT"),
		nullable=False,
	)

	account_number = Column(String(50), nullable=False)
	account_type = Column(
		String(15),
		nullable=False,
		comment="SAVINGS | CHECKING | INVESTMENT | PENSION | INSURANCE",
	)
	currency_code = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=False,
		default="USD",
	)

	# Balances — always integer cents
	balance_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Ledger balance (booked) in minor units",
	)
	available_balance_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Available balance after holds in minor units",
	)

	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | DORMANT | FROZEN | CLOSED",
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

	client: FinancialClient = relationship(
		"FinancialClient",
		back_populates="accounts",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<PortfolioAccount {self.id!r} #{self.account_number!r} "
			f"type={self.account_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# FinancialProduct
# ---------------------------------------------------------------------------

class FinancialProduct(AuditMixin, Model):
	"""Configurable financial product catalogue entry.

	Rates and limits are stored as NUMERIC(8,4) (rate_pct) / INTEGER cents.
	Never use float for any monetary or rate field.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fin_financial_product"
	__table_args__ = (
		UniqueConstraint("product_code", name="uq_fin_product_code"),
		Index("ix_fin_product_tenant_type", "tenant_id", "product_type"),
		Index("ix_fin_product_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	product_code = Column(String(50), nullable=False)
	product_type = Column(
		String(15),
		nullable=False,
		comment="LOAN | DEPOSIT | INSURANCE | INVESTMENT | CARD",
	)
	name = Column(String(300), nullable=False)
	description = Column(Text, nullable=True)

	# Limits — integer cents
	min_amount_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Minimum deal amount in minor units",
	)
	max_amount_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Maximum deal amount in minor units (0 = unlimited)",
	)

	# Rate — NUMERIC(8,4), never float
	interest_rate_pct = Column(
		Numeric(8, 4),
		nullable=True,
		comment="Annual interest rate percent e.g. 12.5000 = 12.5%",
	)
	term_months = Column(
		Integer,
		nullable=True,
		comment="Standard product term in months; NULL = open-ended",
	)

	risk_category = Column(String(50), nullable=True)
	regulatory_category = Column(String(100), nullable=True)
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
			f"<FinancialProduct {self.product_code!r} "
			f"type={self.product_type!r} active={self.is_active}>"
		)


# ---------------------------------------------------------------------------
# ClientHolding
# ---------------------------------------------------------------------------

class ClientHolding(AuditMixin, Model):
	"""Point-in-time snapshot of a client's instrument holding.

	Immutable ledger: each revaluation or trade creates a NEW row — do not
	UPDATE existing rows.  as_of_date discriminates snapshots.

	All monetary values are INTEGER cents. quantity is NUMERIC(20,8) to support
	fractional securities.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fin_client_holding"
	__table_args__ = (
		Index("ix_fin_holding_client_isin", "client_id", "instrument_isin"),
		Index("ix_fin_holding_tenant_date", "tenant_id", "as_of_date"),
		Index("ix_fin_holding_isin", "instrument_isin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	client_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fin_financial_client.id", ondelete="RESTRICT"),
		nullable=False,
	)

	# Instrument
	instrument_isin = Column(
		String(12),
		nullable=False,
		comment="ISO 6166 ISIN code e.g. US0378331005",
	)
	instrument_name = Column(String(500), nullable=False)

	# Position — NUMERIC(20,8) for fractional shares
	quantity = Column(
		Numeric(20, 8),
		nullable=False,
		default=0,
		comment="Number of units/shares held (fractional supported)",
	)

	# Cost basis and valuation — INTEGER cents
	avg_cost_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Average cost per unit in minor currency units",
	)
	current_value_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Current market value of total position in minor units",
	)
	unrealized_pnl_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Unrealized profit/loss: current_value - (avg_cost * quantity)",
	)

	# Snapshot date
	as_of_date = Column(
		Date,
		nullable=False,
		comment="Valuation date for this snapshot",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	client: FinancialClient = relationship(
		"FinancialClient",
		back_populates="holdings",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ClientHolding {self.id!r} client={self.client_id!r} "
			f"isin={self.instrument_isin!r} date={self.as_of_date!r}>"
		)


# ---------------------------------------------------------------------------
# SanctionsScreeningResult
# ---------------------------------------------------------------------------

class SanctionsScreeningResult(AuditMixin, Model):
	"""Immutable record of a sanctions list screening attempt.

	NEVER UPDATE — each re-screen produces a new row.  Query the most recent
	row per party_id + list_type for current status.

	match_details carries raw match evidence as JSONB for audit purposes.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fin_sanctions_screening"
	__table_args__ = (
		Index("ix_fin_sanctions_party", "party_id"),
		Index("ix_fin_sanctions_date", "screening_date"),
		Index("ix_fin_sanctions_tenant_status", "tenant_id", "status"),
		Index("ix_fin_sanctions_list_type", "list_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Screened subject (foundation.Party)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
	)

	screening_date = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	list_type = Column(
		String(10),
		nullable=False,
		comment="OFAC | EU | UN | UK | LOCAL",
	)

	match_found = Column(Boolean, nullable=False, default=False)
	match_score = Column(
		Numeric(5, 4),
		nullable=True,
		comment="Fuzzy match confidence [0.0000, 1.0000]; NULL if no match",
	)
	match_details: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Raw match evidence from screening provider",
	)

	# Clearance (for POTENTIAL_MATCH → CLEAR after human review)
	cleared_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	cleared_at = Column(DateTime(timezone=True), nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="CLEAR",
		comment="CLEAR | POTENTIAL_MATCH | CONFIRMED_MATCH",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<SanctionsScreeningResult {self.id!r} party={self.party_id!r} "
			f"list={self.list_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"FinancialClient",
	"PortfolioAccount",
	"FinancialProduct",
	"ClientHolding",
	"SanctionsScreeningResult",
]
