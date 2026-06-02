"""
pgappforge/plugins/erp/crm/commerce/models.py

SQLAlchemy models for the Commerce plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All monetary amounts: INTEGER cents — never float
  - All models: tenant_id UUID NOT NULL
  - JSONB for features, config
  - lazy='select' throughout
  - Subscription billing records are immutable (append corrections)

Table prefix: com_
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
from pgappforge.plugins.rules.mixin import RulesMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

SUBSCRIPTION_STATUS = ("ACTIVE", "PAUSED", "CANCELLED", "TRIALING", "PAST_DUE")
BILLING_INTERVAL = ("MONTHLY", "ANNUAL", "QUARTERLY", "WEEKLY")


# ---------------------------------------------------------------------------
# ShippingMethod
# ---------------------------------------------------------------------------

class ShippingMethod(AuditMixin, Model):
	"""Carrier service level configuration for checkout shipping options.

	cost_cents: flat-rate cost in cents; zero = free.
	free_threshold_cents: order subtotal above which shipping is waived.
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_shipping_method"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", "carrier", name="uq_com_shipping_tenant_name_carrier"),
		Index("ix_com_shipping_tenant", "tenant_id"),
		Index("ix_com_shipping_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	carrier = Column(String(100), nullable=False, comment="e.g. DHL, FedEx, UPS, Royal Mail")
	service_level = Column(String(100), nullable=True, comment="e.g. Express, Standard, Economy")
	cost_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Flat rate shipping cost in cents",
	)
	free_threshold_cents = Column(
		Integer,
		nullable=True,
		comment="Order subtotal above which shipping is free; NULL = never free",
	)
	delivery_days_min = Column(Integer, nullable=False, default=1)
	delivery_days_max = Column(Integer, nullable=False, default=7)
	is_active = Column(
		Boolean,
		nullable=False,
		default=True,
		server_default="true",
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
		return f"<ShippingMethod {self.name!r} carrier={self.carrier!r} cost={self.cost_cents}¢>"


# ---------------------------------------------------------------------------
# TaxRule
# ---------------------------------------------------------------------------

class TaxRule(AuditMixin, Model):
	"""Jurisdiction-level product category tax rate configuration.

	tax_rate: NUMERIC(5,4) — e.g. 0.2000 = 20% VAT.
	is_inclusive: when true, prices are tax-inclusive (display-only deduction).
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_tax_rule"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "jurisdiction_code", "product_category",
			name="uq_com_tax_rule_jurisdiction_category",
		),
		Index("ix_com_tax_rule_tenant", "tenant_id"),
		Index("ix_com_tax_rule_jurisdiction", "jurisdiction_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	jurisdiction_code = Column(
		String(20),
		nullable=False,
		comment="ISO 3166-2 or custom code e.g. US-CA, GB, NG-LA",
	)
	product_category = Column(
		String(100),
		nullable=False,
		comment="Product category slug this rule applies to; '*' = all",
	)
	tax_rate = Column(
		Numeric(5, 4),
		nullable=False,
		comment="Decimal rate e.g. 0.2000 = 20%",
	)
	tax_name = Column(String(50), nullable=False, comment="Display name e.g. VAT, GST, Sales Tax")
	is_inclusive = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
		comment="True = price includes tax (e.g. UK retail VAT)",
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
			f"<TaxRule {self.jurisdiction_code!r}/{self.product_category!r} "
			f"rate={self.tax_rate} name={self.tax_name!r}>"
		)


# ---------------------------------------------------------------------------
# SubscriptionPlan
# ---------------------------------------------------------------------------

class SubscriptionPlan(AuditMixin, Model):
	"""Reusable subscription plan definition.

	amount_cents: recurring charge per billing cycle in cents.
	interval_months: 1=monthly, 12=annual, 3=quarterly, etc.
	features: JSONB dict of plan feature flags/limits.
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_subscription_plan"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_com_plan_tenant_name"),
		Index("ix_com_plan_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	description = Column(Text, nullable=True)
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Recurring charge in cents per billing cycle",
	)
	currency_code = Column(String(3), nullable=False, default="USD", comment="ISO 4217")
	interval_months = Column(
		Integer,
		nullable=False,
		default=1,
		comment="Billing cycle in months: 1=monthly, 3=quarterly, 12=annual",
	)
	trial_days = Column(
		Integer,
		nullable=False,
		default=0,
		server_default="0",
		comment="Free trial period in days; 0 = no trial",
	)
	features: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment='Feature flags/limits e.g. {"seats": 5, "storage_gb": 100}',
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

	subscriptions: list[Subscription] = relationship(
		"Subscription",
		back_populates="plan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SubscriptionPlan {self.name!r} amount={self.amount_cents}¢ interval={self.interval_months}mo>"


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

class Subscription(RulesMixin, AuditMixin, Model):
	"""Active customer subscription to a plan.

	Billing immutability: billing history is maintained in a separate
	ledger (BillingPlugin or AR invoices). Do not update amount_cents
	after ACTIVE — cancel and create a new subscription for plan changes.

	payment_method_id: soft FK to payment method stored in billing plugin
	or external payment gateway reference.
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_subscription"
	__table_args__ = (
		Index("ix_com_sub_tenant", "tenant_id"),
		Index("ix_com_sub_customer", "customer_id"),
		Index("ix_com_sub_plan", "plan_id"),
		Index("ix_com_sub_status", "status"),
		Index("ix_com_sub_next_billing", "next_billing_date"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"status", "next_billing_date", "payment_method_id",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	customer_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK Party.id or ARCustomer.id",
	)
	plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("com_subscription_plan.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	status = Column(
		String(15),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE|PAUSED|CANCELLED|TRIALING|PAST_DUE",
	)
	start_date = Column(Date, nullable=False)
	next_billing_date = Column(
		Date,
		nullable=True,
		index=True,
		comment="NULL when CANCELLED",
	)
	billing_interval = Column(
		String(15),
		nullable=False,
		default="MONTHLY",
		comment="MONTHLY|ANNUAL|QUARTERLY|WEEKLY",
	)

	# Amount snapshot at subscription creation — immutable after activation
	amount_cents = Column(
		Integer,
		nullable=False,
		comment="Billing amount in cents; snapshot from plan at subscription time",
	)
	currency_code = Column(String(3), nullable=False, default="USD")

	# Payment method reference (opaque ID to gateway/billing plugin)
	payment_method_id = Column(
		String(255),
		nullable=True,
		comment="Gateway payment method reference (e.g. Stripe pm_xxx)",
	)

	cancelled_at = Column(DateTime(timezone=True), nullable=True)
	cancellation_reason = Column(Text, nullable=True)

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

	plan: SubscriptionPlan = relationship("SubscriptionPlan", back_populates="subscriptions", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Subscription customer={self.customer_id!r} plan={self.plan_id!r} "
			f"status={self.status!r} amount={self.amount_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ShippingMethod",
	"TaxRule",
	"SubscriptionPlan",
	"Subscription",
]
