"""
pgappforge/plugins/fintech/agency/models.py

Agency Banking models — outlets, agents, transactions, float management,
and commission settlement.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents — never Decimal/float in storage
  - AgencyTransaction: ImmutableRecordMixin (insert-only)
  - Table name convention: ft_agency_<entity>
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
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
# AgencyOutlet — physical or virtual service point
# ---------------------------------------------------------------------------

class AgencyOutlet(AuditMixin, Model):
	"""A physical outlet (shop, kiosk, van, etc.) that offers agency services.

	outlet_type:
	  RETAIL_SHOP / PETROL_STATION / PHARMACY / BANK_BRANCH / SUPERMARKET /
	  MPESA_SHOP / MOBILE_VAN / SCHOOL / HOSPITAL / POST_OFFICE

	location JSONB: {region, lat, lng, address}

	services JSONB list:
	  CASH_IN / CASH_OUT / ACCOUNT_OPENING / LOAN_DISBURSEMENT /
	  LOAN_REPAYMENT / BILL_PAYMENT / GOVT_PAYMENTS / REMITTANCE /
	  AIRTIME / INSURANCE

	float_minimum_cents: low-float alert threshold (default KES 5 000).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_agency_outlet"
	__table_args__ = (
		Index("ix_ft_agency_outlet_tenant", "tenant_id"),
		Index("ix_ft_agency_outlet_status", "status"),
		Index("ix_ft_agency_outlet_type", "outlet_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	name = Column(String(200), nullable=False)
	outlet_type = Column(
		String(20),
		nullable=False,
		comment=(
			"RETAIL_SHOP / PETROL_STATION / PHARMACY / BANK_BRANCH / "
			"SUPERMARKET / MPESA_SHOP / MOBILE_VAN / SCHOOL / HOSPITAL / POST_OFFICE"
		),
	)
	location = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{region, lat, lng, address}",
	)
	services = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment=(
			"List of offered services: CASH_IN / CASH_OUT / ACCOUNT_OPENING / "
			"LOAN_DISBURSEMENT / LOAN_REPAYMENT / BILL_PAYMENT / GOVT_PAYMENTS / "
			"REMITTANCE / AIRTIME / INSURANCE"
		),
	)
	float_balance_cents = Column(Integer, nullable=False, default=0)
	float_minimum_cents = Column(Integer, nullable=False, default=500_000)
	status = Column(String(10), nullable=False, default="ACTIVE", comment="ACTIVE / SUSPENDED / CLOSED")

	# relationships
	agents = relationship("AgencyAgent", back_populates="outlet", lazy="dynamic")
	float_account = relationship("AgencyFloat", back_populates="outlet", uselist=False)
	transactions = relationship("AgencyTransaction", back_populates="outlet", lazy="dynamic")


# ---------------------------------------------------------------------------
# AgencyAgent — accredited individual running an outlet
# ---------------------------------------------------------------------------

class AgencyAgent(AuditMixin, Model):
	"""An agent accredited to operate at an AgencyOutlet.

	accreditation_status: PENDING / ACCREDITED / SUSPENDED / REVOKED
	kyc_tier: 1 = basic, 2 = enhanced, 3 = full
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_agency_agent"
	__table_args__ = (
		Index("ix_ft_agency_agent_tenant", "tenant_id"),
		Index("ix_ft_agency_agent_outlet", "outlet_id"),
		Index("ix_ft_agency_agent_msisdn", "msisdn"),
		Index("ix_ft_agency_agent_accreditation", "accreditation_status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	outlet_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_agency_outlet.id"),
		nullable=False,
	)
	agent_name = Column(String(200), nullable=False)
	msisdn = Column(String(20), nullable=False)
	national_id = Column(String(30), nullable=False)
	accreditation_status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		comment="PENDING / ACCREDITED / SUSPENDED / REVOKED",
	)
	accredited_at = Column(DateTime(timezone=True), nullable=True)
	kyc_tier = Column(Integer, nullable=False, default=1)

	# relationships
	outlet = relationship("AgencyOutlet", back_populates="agents")
	transactions = relationship("AgencyTransaction", back_populates="agent", lazy="dynamic")
	commissions = relationship("AgencyCommission", back_populates="agent", lazy="dynamic")


# ---------------------------------------------------------------------------
# AgencyTransaction — immutable transaction ledger
# ---------------------------------------------------------------------------

class AgencyTransaction(ImmutableRecordMixin, Model):
	"""Single agency service transaction — insert-only (ImmutableRecordMixin).

	service_type: one of the services listed on AgencyOutlet.services
	status: PENDING / COMPLETED / REVERSED / FAILED
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_agency_transaction"
	__table_args__ = (
		Index("ix_ft_agency_txn_tenant", "tenant_id"),
		Index("ix_ft_agency_txn_agent", "agent_id"),
		Index("ix_ft_agency_txn_outlet", "outlet_id"),
		Index("ix_ft_agency_txn_status", "status"),
		Index("ix_ft_agency_txn_created", "created_at"),
		UniqueConstraint("reference", name="uq_ft_agency_txn_reference"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	agent_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_agency_agent.id"),
		nullable=False,
	)
	outlet_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_agency_outlet.id"),
		nullable=False,
	)
	service_type = Column(String(30), nullable=False)
	customer_msisdn = Column(String(20), nullable=False)
	amount_cents = Column(Integer, nullable=False)
	fee_cents = Column(Integer, nullable=False, default=0)
	agent_commission_cents = Column(Integer, nullable=False, default=0)
	status = Column(String(10), nullable=False, comment="PENDING / COMPLETED / REVERSED / FAILED")
	reference = Column(String(50), nullable=False, unique=True)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# relationships
	agent = relationship("AgencyAgent", back_populates="transactions")
	outlet = relationship("AgencyOutlet", back_populates="transactions")


# ---------------------------------------------------------------------------
# AgencyFloat — per-outlet float balance ledger
# ---------------------------------------------------------------------------

class AgencyFloat(Model):
	"""Tracks the current float balance held at each outlet.

	One-to-one with AgencyOutlet (outlet_id UNIQUE).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_agency_float"
	__table_args__ = (
		Index("ix_ft_agency_float_tenant", "tenant_id"),
		UniqueConstraint("outlet_id", name="uq_ft_agency_float_outlet"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	outlet_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_agency_outlet.id"),
		nullable=False,
		unique=True,
	)
	current_balance_cents = Column(Integer, nullable=False, default=0)
	last_topped_up_at = Column(DateTime(timezone=True), nullable=True)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# relationships
	outlet = relationship("AgencyOutlet", back_populates="float_account")


# ---------------------------------------------------------------------------
# AgencyCommission — periodic agent commission settlement record
# ---------------------------------------------------------------------------

class AgencyCommission(Model):
	"""Aggregated commission record per agent per calendar period (YYYY-MM).

	status: PENDING / PAID
	tax_cents: withholding tax deducted before payout.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_agency_commission"
	__table_args__ = (
		Index("ix_ft_agency_commission_tenant", "tenant_id"),
		Index("ix_ft_agency_commission_agent", "agent_id"),
		Index("ix_ft_agency_commission_period", "period"),
		Index("ix_ft_agency_commission_status", "status"),
		UniqueConstraint("agent_id", "period", name="uq_ft_agency_commission_agent_period"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	agent_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_agency_agent.id"),
		nullable=False,
	)
	period = Column(String(7), nullable=False, comment="YYYY-MM")
	transactions_count = Column(Integer, nullable=False, default=0)
	gross_commission_cents = Column(Integer, nullable=False, default=0)
	tax_cents = Column(Integer, nullable=False, default=0)
	net_commission_cents = Column(Integer, nullable=False, default=0)
	status = Column(String(10), nullable=False, default="PENDING", comment="PENDING / PAID")
	paid_at = Column(DateTime(timezone=True), nullable=True)

	# relationships
	agent = relationship("AgencyAgent", back_populates="commissions")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"AgencyOutlet",
	"AgencyAgent",
	"AgencyTransaction",
	"AgencyFloat",
	"AgencyCommission",
]
