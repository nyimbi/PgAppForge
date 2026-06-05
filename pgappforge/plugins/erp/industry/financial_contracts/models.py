"""
pgappforge/plugins/erp/industry/financial_contracts/models.py

SQLAlchemy models for the Financial Contracts plugin (ACTUS-based).

Design invariants:
  - All PKs:         UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps:  DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - All models:      tenant_id UUID NOT NULL
  - All amounts:     Integer cents (INTEGER) — NEVER float or Numeric for money
  - CashFlowSchedule, ContractValuation: IMMUTABLE (insert-only)
  - FKs:             UUID strings (as_uuid=False)
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
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# FinancialContract
# ---------------------------------------------------------------------------

class FinancialContract(AuditMixin, Model):
	"""Master record for an ACTUS financial contract.

	contract_type follows ACTUS type codes:
	  PAM = Principal At Maturity (bullet bond / term loan)
	  ANN = Annuity (amortising loan)
	  CLM = Call Money
	  BND = Bond with embedded options
	  LAX = Linear Amortiser
	  NAM = Negative Amortiser

	contract_role: RPA = receive principal (asset side),
	               RPL = pay principal (liability side).

	notional_principal_cents: face value in integer cents.
	nominal_interest_rate: decimal (0.05 = 5% p.a.), stored Numeric(10,8).
	"""

	__allow_unmapped__ = True
	__tablename__ = "fc_contract"
	__table_args__ = (
		UniqueConstraint("tenant_id", "contract_id", name="uq_fc_contract_tenant_cid"),
		Index("ix_fc_contract_tenant", "tenant_id"),
		Index("ix_fc_contract_type", "contract_type"),
		Index("ix_fc_contract_status", "status"),
		Index("ix_fc_contract_party_a", "counterparty_a_id"),
		Index("ix_fc_contract_party_b", "counterparty_b_id"),
		Index("ix_fc_contract_maturity", "maturity_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(
		String(100),
		nullable=False,
		comment="Business-level contract identifier (e.g. ISIN or internal ref)",
	)
	contract_type = Column(
		String(10),
		nullable=False,
		comment="ACTUS type: PAM|ANN|CLM|BND|LAX|NAM",
	)
	counterparty_a_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
		comment="First counterparty (typically the issuer/borrower)",
	)
	counterparty_b_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
		comment="Second counterparty (typically the investor/lender)",
	)
	currency_code = Column(String(3), nullable=False, comment="ISO 4217")
	notional_principal_cents = Column(
		Integer,
		nullable=False,
		comment="Face value in integer cents",
	)
	nominal_interest_rate = Column(
		Numeric(10, 8),
		nullable=False,
		comment="Contractual rate as decimal: 0.05 = 5% p.a.",
	)
	day_count_convention = Column(
		String(20),
		nullable=False,
		comment="ACTUS DCC code: A360, A365, 30E360, ACT/ACT, etc.",
	)
	initial_exchange_date = Column(
		Date,
		nullable=False,
		comment="IED — date of first principal exchange",
	)
	maturity_date = Column(
		Date,
		nullable=False,
		comment="MD — final principal repayment date",
	)
	contract_role = Column(
		String(10),
		nullable=False,
		comment="RPA=receive principal (long) | RPL=pay principal (short)",
	)
	settlement_period = Column(
		String(20),
		nullable=False,
		default="P0D",
		comment="ISO 8601 duration for settlement lag, e.g. P2D",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE|MATURED|DEFAULTED|CANCELLED",
	)
	contract_terms = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Full ACTUS attribute set per contract type data dictionary",
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

	cash_flows: list[CashFlowSchedule] = relationship(
		"CashFlowSchedule",
		back_populates="contract",
		lazy="select",
		order_by="CashFlowSchedule.schedule_date",
	)
	valuations: list[ContractValuation] = relationship(
		"ContractValuation",
		back_populates="contract",
		lazy="select",
		order_by="ContractValuation.valuation_date",
	)

	def __repr__(self) -> str:
		return (
			f"<FinancialContract {self.contract_id!r} type={self.contract_type!r} "
			f"role={self.contract_role!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# CashFlowSchedule  (IMMUTABLE)
# ---------------------------------------------------------------------------

class CashFlowSchedule(ImmutableRecordMixin, Model):
	"""Scheduled (and settled) cash flow event for a contract.

	IMMUTABLE: rows are inserted by generate_cash_flows(); never updated.
	Corrections require voiding the schedule and regenerating.

	event_type follows ACTUS event codes:
	  IED = Initial Exchange Date (principal disbursement)
	  IP  = Interest Payment
	  PR  = Principal Redemption (partial)
	  PP  = Principal Prepayment
	  MD  = Maturity Date (final principal)
	  AD  = Accrued Interest Date
	  TD  = Termination Date
	  STD = Settlement Date
	  PRF = Performance Date
	"""

	__allow_unmapped__ = True
	__tablename__ = "fc_cash_flow_schedule"
	__table_args__ = (
		Index("ix_fc_cf_contract", "contract_id"),
		Index("ix_fc_cf_tenant", "tenant_id"),
		Index("ix_fc_cf_date", "schedule_date"),
		Index("ix_fc_cf_event_type", "event_type"),
		Index("ix_fc_cf_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fc_contract.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	schedule_date = Column(Date, nullable=False)
	event_type = Column(
		String(4),
		nullable=False,
		comment="ACTUS event code: IED|IP|PR|PP|MD|AD|TD|STD|PRF",
	)
	scheduled_amount_cents = Column(
		Integer,
		nullable=False,
		comment="Calculated cash flow in integer cents",
	)
	currency_code = Column(String(3), nullable=False, comment="ISO 4217")
	actual_amount_cents = Column(
		Integer,
		nullable=True,
		comment="Settled amount in integer cents (NULL = not yet settled)",
	)
	actual_date = Column(Date, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="SCHEDULED",
		comment="SCHEDULED|SETTLED|MISSED|WAIVED",
	)
	# Immutable: no updated_at
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	contract: FinancialContract = relationship(
		"FinancialContract",
		back_populates="cash_flows",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CashFlowSchedule contract={self.contract_id!r} "
			f"date={self.schedule_date!r} type={self.event_type!r} "
			f"amt={self.scheduled_amount_cents} {self.status!r}>"
		)


# ---------------------------------------------------------------------------
# RiskFactor
# ---------------------------------------------------------------------------

class RiskFactor(AuditMixin, Model):
	"""Market risk factor used by ACTUS simulation algorithms.

	factor_type: INTEREST_RATE (yield curves), FX_RATE, CREDIT_SPREAD, EQUITY.
	base_value: current/reference level as Numeric(20,8).
	current_value: as-of-date observed value.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fc_risk_factor"
	__table_args__ = (
		UniqueConstraint("tenant_id", "factor_code", name="uq_fc_rf_tenant_code"),
		Index("ix_fc_rf_tenant", "tenant_id"),
		Index("ix_fc_rf_type", "factor_type"),
		Index("ix_fc_rf_as_of", "as_of_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	factor_code = Column(
		String(50),
		nullable=False,
		comment="ACTUS market object code, e.g. LIBOR_3M, EUR/USD, EURIBOR_6M",
	)
	factor_type = Column(
		String(20),
		nullable=False,
		comment="INTEREST_RATE|FX_RATE|CREDIT_SPREAD|EQUITY",
	)
	currency_code = Column(
		String(3),
		nullable=True,
		comment="Base currency for FX factors; denomination for rate factors",
	)
	base_value = Column(
		Numeric(20, 8),
		nullable=False,
		comment="Reference/baseline value for scenario analysis",
	)
	current_value = Column(
		Numeric(20, 8),
		nullable=False,
		comment="As-of-date observed market value",
	)
	as_of_date = Column(Date, nullable=False)
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
			f"<RiskFactor {self.factor_code!r} type={self.factor_type!r} "
			f"current={self.current_value} as_of={self.as_of_date!r}>"
		)


# ---------------------------------------------------------------------------
# ContractValuation  (IMMUTABLE)
# ---------------------------------------------------------------------------

class ContractValuation(ImmutableRecordMixin, Model):
	"""Point-in-time valuation snapshot for a contract.

	IMMUTABLE: one row per (contract, valuation_date, method) combination.
	npv_cents: net present value in integer cents.
	duration_years: Macaulay/modified duration.
	convexity: second-order price sensitivity.
	"""

	__allow_unmapped__ = True
	__tablename__ = "fc_contract_valuation"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "contract_id", "valuation_date", "valuation_method",
			name="uq_fc_val_contract_date_method",
		),
		Index("ix_fc_val_contract", "contract_id"),
		Index("ix_fc_val_tenant", "tenant_id"),
		Index("ix_fc_val_date", "valuation_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("fc_contract.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	valuation_date = Column(Date, nullable=False)
	valuation_method = Column(
		String(20),
		nullable=False,
		comment="MARKET|MODEL|HISTORICAL",
	)
	npv_cents = Column(
		Integer,
		nullable=False,
		comment="Net present value in integer cents",
	)
	duration_years = Column(
		Numeric(8, 4),
		nullable=True,
		comment="Macaulay or modified duration in years",
	)
	convexity = Column(
		Numeric(12, 6),
		nullable=True,
		comment="Dollar convexity (second derivative of price w.r.t. yield)",
	)
	risk_factors_used = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="{factor_code: value} snapshot used in this valuation",
	)
	model_parameters = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Model-specific parameters: discount curve, credit spread, etc.",
	)
	# Immutable: no updated_at
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	contract: FinancialContract = relationship(
		"FinancialContract",
		back_populates="valuations",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ContractValuation contract={self.contract_id!r} "
			f"date={self.valuation_date!r} method={self.valuation_method!r} "
			f"npv={self.npv_cents}>"
		)


# ---------------------------------------------------------------------------
# Register immutability hooks after class definitions
# ---------------------------------------------------------------------------

CashFlowSchedule._register_immutability()
ContractValuation._register_immutability()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"FinancialContract",
	"CashFlowSchedule",
	"RiskFactor",
	"ContractValuation",
]
