"""
pgappforge/plugins/fintech/bnpl/models.py

Buy-Now-Pay-Later plugin models — merchants, applications, instalment plans,
individual instalments, and merchant settlement records.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents — never Decimal/float in storage
  - Table name convention: ft_bnpl_<entity>
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, date, timezone

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
	String,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# BNPLMerchant — registered merchants offering BNPL at checkout
# ---------------------------------------------------------------------------

class BNPLMerchant(AuditMixin, Model):
	"""A merchant enrolled in the BNPL programme.

	commission_pct: platform commission deducted from gross sales on settlement
	  (stored as decimal fraction, e.g. 0.0200 = 2%).
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_bnpl_merchant"
	__table_args__ = (
		Index("ix_ft_bnpl_merchant_tenant", "tenant_id"),
		Index("ix_ft_bnpl_merchant_active", "is_active"),
		Index("ix_ft_bnpl_merchant_category", "merchant_category"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	name = Column(String(200), nullable=False)
	merchant_category = Column(String(50), nullable=False)
	settlement_account_number = Column(String(50), nullable=False)
	commission_pct = Column(
		Numeric(5, 4),
		nullable=False,
		default=0,
		comment="Platform commission as decimal fraction e.g. 0.0200 = 2%",
	)
	is_active = Column(Boolean, nullable=False, default=True)

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

	# Relationships
	applications: list[BNPLApplication] = relationship(
		"BNPLApplication",
		back_populates="merchant",
		lazy="select",
	)
	settlements: list[BNPLMerchantSettlement] = relationship(
		"BNPLMerchantSettlement",
		back_populates="merchant",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<BNPLMerchant {self.name!r} active={self.is_active!r}>"


# ---------------------------------------------------------------------------
# BNPLApplication — customer BNPL credit application
# ---------------------------------------------------------------------------

class BNPLApplication(AuditMixin, Model):
	"""A customer's request to finance a merchant order via BNPL.

	plan_type drives how instalments are generated:
	  PAY_IN_3    — 3 equal monthly payments
	  PAY_IN_4    — 4 equal biweekly payments
	  MONTHLY     — customer-defined number of months
	  INVOICE_SPLIT — 2-payment split (50% upfront, 50% on delivery)

	status flow:
	  PENDING → APPROVED (credit pass) → ACTIVE (first instalment due)
	                                    → COMPLETED (all paid)
	                                    → DEFAULTED (missed instalments)
	          → DECLINED (credit fail)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_bnpl_application"
	__table_args__ = (
		Index("ix_ft_bnpl_app_tenant", "tenant_id"),
		Index("ix_ft_bnpl_app_customer", "customer_id"),
		Index("ix_ft_bnpl_app_merchant", "merchant_id"),
		Index("ix_ft_bnpl_app_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	customer_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="UUID of the customer (FK to party table not enforced at DB level)",
	)
	merchant_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_bnpl_merchant.id"),
		nullable=False,
		index=True,
	)
	order_amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Total order value to be financed (cents)",
	)
	plan_type = Column(
		String(20),
		nullable=False,
		comment="PAY_IN_3 | PAY_IN_4 | MONTHLY | INVOICE_SPLIT",
	)
	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		comment="PENDING | APPROVED | DECLINED | ACTIVE | COMPLETED | DEFAULTED",
	)
	credit_score = Column(Integer, nullable=True)
	affordability_score = Column(Integer, nullable=True)
	approved_limit_cents = Column(BigInteger, nullable=True)

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

	# Relationships
	merchant: BNPLMerchant = relationship(
		"BNPLMerchant",
		back_populates="applications",
		lazy="select",
	)
	plan: BNPLPlan | None = relationship(
		"BNPLPlan",
		back_populates="application",
		uselist=False,
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<BNPLApplication {self.id!r} "
			f"status={self.status!r} "
			f"amount={self.order_amount_cents}c>"
		)


# ---------------------------------------------------------------------------
# BNPLPlan — approved instalment schedule
# ---------------------------------------------------------------------------

class BNPLPlan(AuditMixin, Model):
	"""The approved instalment plan generated from a BNPLApplication.

	total_cents: total repayment (principal + interest if any).
	installment_amount_cents: per-instalment amount (may vary for last instalment
	  due to rounding; enforced by service layer).
	interest_rate_pct: annual rate; 0 for interest-free plans.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_bnpl_plan"
	__table_args__ = (
		Index("ix_ft_bnpl_plan_tenant", "tenant_id"),
		Index("ix_ft_bnpl_plan_application", "application_id"),
		Index("ix_ft_bnpl_plan_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	application_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_bnpl_application.id"),
		nullable=False,
		index=True,
	)
	total_cents = Column(BigInteger, nullable=False, comment="Total repayment amount (cents)")
	installment_count = Column(Integer, nullable=False)
	installment_amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Standard per-instalment amount (cents)",
	)
	interest_rate_pct = Column(
		Numeric(5, 4),
		nullable=False,
		default=0,
		comment="Annual interest rate as decimal fraction; 0 = interest-free",
	)
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | COMPLETED | CANCELLED",
	)
	first_payment_date = Column(Date, nullable=False)

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

	# Relationships
	application: BNPLApplication = relationship(
		"BNPLApplication",
		back_populates="plan",
		lazy="select",
	)
	installments: list[BNPLInstallment] = relationship(
		"BNPLInstallment",
		back_populates="plan",
		lazy="select",
		order_by="BNPLInstallment.installment_number",
	)

	def __repr__(self) -> str:
		return (
			f"<BNPLPlan {self.id!r} "
			f"count={self.installment_count} "
			f"total={self.total_cents}c "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# BNPLInstallment — individual repayment schedule row
# ---------------------------------------------------------------------------

class BNPLInstallment(Model):
	"""One scheduled repayment within a BNPLPlan.

	penalty_cents: late payment penalty accrued; applied by run_overdue_check().
	status flow: PENDING → PAID (on payment)
	                      → OVERDUE (past due_date, not paid)
	                      → WAIVED (operator override)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_bnpl_installment"
	__table_args__ = (
		Index("ix_ft_bnpl_inst_tenant", "tenant_id"),
		Index("ix_ft_bnpl_inst_plan", "plan_id"),
		Index("ix_ft_bnpl_inst_due_date", "due_date"),
		Index("ix_ft_bnpl_inst_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_bnpl_plan.id"),
		nullable=False,
		index=True,
	)
	installment_number = Column(Integer, nullable=False)
	due_date = Column(Date, nullable=False)
	amount_cents = Column(BigInteger, nullable=False)
	paid_date = Column(Date, nullable=True)
	paid_amount_cents = Column(BigInteger, nullable=True)
	status = Column(
		String(10),
		nullable=False,
		default="PENDING",
		comment="PENDING | PAID | OVERDUE | WAIVED",
	)
	penalty_cents = Column(BigInteger, nullable=False, default=0)

	# Relationships
	plan: BNPLPlan = relationship(
		"BNPLPlan",
		back_populates="installments",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<BNPLInstallment #{self.installment_number} "
			f"due={self.due_date!r} "
			f"amount={self.amount_cents}c "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# BNPLMerchantSettlement — monthly merchant payout record
# ---------------------------------------------------------------------------

class BNPLMerchantSettlement(Model):
	"""Monthly settlement record for a BNPL merchant.

	period: YYYY-MM string identifying the settlement month.
	net_payout_cents = gross_sales_cents - commission_cents
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_bnpl_settlement"
	__table_args__ = (
		UniqueConstraint("tenant_id", "merchant_id", "period", name="uq_ft_bnpl_settlement_period"),
		Index("ix_ft_bnpl_settlement_tenant", "tenant_id"),
		Index("ix_ft_bnpl_settlement_merchant", "merchant_id"),
		Index("ix_ft_bnpl_settlement_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	merchant_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_bnpl_merchant.id"),
		nullable=False,
		index=True,
	)
	period = Column(String(7), nullable=False, comment="YYYY-MM settlement period")
	gross_sales_cents = Column(BigInteger, nullable=False)
	commission_cents = Column(BigInteger, nullable=False)
	net_payout_cents = Column(BigInteger, nullable=False)
	status = Column(
		String(10),
		nullable=False,
		default="PENDING",
		comment="PENDING | PAID",
	)
	settled_at = Column(DateTime(timezone=True), nullable=True)

	# Relationships
	merchant: BNPLMerchant = relationship(
		"BNPLMerchant",
		back_populates="settlements",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<BNPLMerchantSettlement merchant={self.merchant_id!r} "
			f"period={self.period!r} "
			f"net={self.net_payout_cents}c "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"BNPLMerchant",
	"BNPLApplication",
	"BNPLPlan",
	"BNPLInstallment",
	"BNPLMerchantSettlement",
]
