"""
pgappforge/plugins/erp/crm/subscriptions/models.py

SQLAlchemy models for the Subscriptions Management plugin.

Design rules enforced here:
  - All PKs: UUID v4, server_default=gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: Integer CENTS — never float/Numeric for money
  - JSONB for semi-structured data (features, limits, line_items, metadata)
  - PostgreSQL ONLY — no SQLite/MySQL portability shims
  - lazy='select' throughout (SA 2.x)
  - AuditMixin on every mutable entity

Table prefix: sub_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fractions import Fraction
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
# Enumeration constants (documented here; CHECK constraints via DB migrations)
# ---------------------------------------------------------------------------

BILLING_INTERVAL = ("WEEKLY", "MONTHLY", "QUARTERLY", "ANNUALLY")
SUBSCRIPTION_STATUS = ("TRIALING", "ACTIVE", "PAST_DUE", "CANCELLED", "EXPIRED", "PAUSED")
INVOICE_STATUS = ("DRAFT", "OPEN", "PAID", "VOID", "UNCOLLECTIBLE")


# ---------------------------------------------------------------------------
# SubscriptionPlan
# ---------------------------------------------------------------------------

class SubscriptionPlan(AuditMixin, Model):
	"""Defines a recurring billing plan that subscriptions reference.

	plan_code is unique per tenant, enabling programmatic lookup.
	features is a list of feature-name strings; limits is a dict of
	{metric: max_value} pairs (e.g. {"api_calls": 10000, "users": 5}).
	base_price_cents is the full undiscounted price per billing interval.
	"""
	__tablename__ = "sub_plan"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)
	plan_code = Column(String(50), nullable=False)
	billing_interval = Column(String(20), nullable=False)        # MONTHLY/QUARTERLY/ANNUALLY/WEEKLY
	billing_interval_count = Column(Integer, nullable=False, default=1)
	base_price_cents = Column(Integer, nullable=False)
	currency_code = Column(String(3), nullable=False, default="KES")
	trial_days = Column(Integer, nullable=False, default=0)
	features = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
	limits = Column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
	is_active = Column(Boolean, nullable=False, default=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))

	# Unique plan_code per tenant
	__table_args__ = (
		UniqueConstraint("tenant_id", "plan_code", name="uq_sub_plan_tenant_code"),
		Index("ix_sub_plan_tenant_active", "tenant_id", "is_active"),
	)

	subscriptions = relationship(
		"Subscription",
		back_populates="plan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SubscriptionPlan {self.plan_code} {self.billing_interval} {self.base_price_cents}c>"

	def monthly_equivalent_cents(self) -> int:
		"""Return approximate monthly price in cents for MRR calculations."""
		mapping = {
			"WEEKLY": Fraction(52, 12),
			"MONTHLY": 1,
			"QUARTERLY": Fraction(1, 3),
			"ANNUALLY": Fraction(1, 12),
		}
		interval = (self.billing_interval or "MONTHLY").upper()
		count = self.billing_interval_count or 1
		if interval not in mapping:
			return self.base_price_cents
		multiplier = mapping[interval]
		# multiplier is per-interval converted to per-month; divide by count for custom intervals
		result = Fraction(self.base_price_cents) * Fraction(multiplier) / Fraction(count)
		return int(result)


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

class Subscription(AuditMixin, Model):
	"""A customer's active (or historical) subscription to a plan.

	status lifecycle:
	  TRIALING → ACTIVE → PAST_DUE → (ACTIVE via retry) | CANCELLED | EXPIRED
	  Any status → PAUSED (manual admin action)
	  PAUSED → ACTIVE (resume)

	cancel_at_period_end=True means the subscription stays ACTIVE until
	current_period_end, then transitions to CANCELLED on the next renewal run.
	"""
	__tablename__ = "sub_subscription"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	customer_id = Column(String(50), nullable=False)
	plan_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sub_plan.id", ondelete="SET NULL"),
		nullable=True,
	)
	status = Column(String(20), nullable=False, default="TRIALING")
	current_period_start = Column(Date, nullable=False)
	current_period_end = Column(Date, nullable=False)
	trial_end = Column(Date, nullable=True)
	cancel_at_period_end = Column(Boolean, nullable=False, default=False)
	cancelled_at = Column(DateTime(timezone=True), nullable=True)
	cancel_reason = Column(Text, nullable=True)
	quantity = Column(Integer, nullable=False, default=1)
	discount_pct = Column(Numeric(5, 2), nullable=False, default=0)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
	entity_id = Column(String(50), nullable=True)

	__table_args__ = (
		Index("ix_sub_subscription_customer_status", "customer_id", "status"),
		Index("ix_sub_subscription_tenant_status", "tenant_id", "status"),
		Index("ix_sub_subscription_tenant_period_end", "tenant_id", "current_period_end"),
	)

	plan = relationship(
		"SubscriptionPlan",
		back_populates="subscriptions",
		lazy="select",
	)
	invoices = relationship(
		"SubscriptionInvoice",
		back_populates="subscription",
		lazy="select",
		cascade="all, delete-orphan",
	)
	usage_records = relationship(
		"SubscriptionUsage",
		back_populates="subscription",
		lazy="select",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return f"<Subscription {self.id} customer={self.customer_id} status={self.status}>"


# ---------------------------------------------------------------------------
# SubscriptionInvoice
# ---------------------------------------------------------------------------

class SubscriptionInvoice(AuditMixin, Model):
	"""Invoice generated for each billing period of a subscription.

	amount_cents is the total due after any plan-level discounts.
	line_items is a list of {description, quantity, unit_price_cents, total_cents} dicts.
	invoice_ref is unique per tenant and used for human-readable reference numbers.
	"""
	__tablename__ = "sub_invoice"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	subscription_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sub_subscription.id", ondelete="CASCADE"),
		nullable=False,
	)
	customer_id = Column(String(50), nullable=False)
	invoice_ref = Column(String(50), nullable=False)
	amount_cents = Column(Integer, nullable=False)
	currency_code = Column(String(3), nullable=False, default="KES")
	status = Column(String(20), nullable=False, default="DRAFT")
	due_date = Column(Date, nullable=False)
	paid_at = Column(DateTime(timezone=True), nullable=True)
	period_start = Column(Date, nullable=False)
	period_end = Column(Date, nullable=False)
	payment_method = Column(String(50), nullable=True)
	payment_ref = Column(String(100), nullable=True)
	line_items = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))

	__table_args__ = (
		UniqueConstraint("tenant_id", "invoice_ref", name="uq_sub_invoice_tenant_ref"),
		Index("ix_sub_invoice_sub_status", "subscription_id", "status"),
		Index("ix_sub_invoice_tenant_due", "tenant_id", "due_date"),
		Index("ix_sub_invoice_customer_status", "customer_id", "status"),
	)

	subscription = relationship(
		"Subscription",
		back_populates="invoices",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SubscriptionInvoice {self.invoice_ref} {self.amount_cents}c {self.status}>"


# ---------------------------------------------------------------------------
# SubscriptionUsage
# ---------------------------------------------------------------------------

class SubscriptionUsage(AuditMixin, Model):
	"""Metered usage record — one row per (subscription, metric, period).

	quantity accumulates via upsert (record_usage adds to existing quantity).
	period is a YYYY-MM string for monthly bucketing; other granularities
	use whatever string the caller passes (e.g. "2025-W03" for weekly).
	"""
	__tablename__ = "sub_usage"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	subscription_id = Column(
		UUID(as_uuid=False),
		ForeignKey("sub_subscription.id", ondelete="CASCADE"),
		nullable=False,
	)
	metric_name = Column(String(100), nullable=False)
	period = Column(String(20), nullable=False)
	quantity = Column(Numeric(15, 4), nullable=False, default=0)
	recorded_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	__table_args__ = (
		UniqueConstraint(
			"subscription_id", "metric_name", "period",
			name="uq_sub_usage_sub_metric_period",
		),
		Index("ix_sub_usage_sub_period", "subscription_id", "period"),
	)

	subscription = relationship(
		"Subscription",
		back_populates="usage_records",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<SubscriptionUsage sub={self.subscription_id} {self.metric_name}/{self.period} qty={self.quantity}>"


__all__ = [
	"SubscriptionPlan",
	"Subscription",
	"SubscriptionInvoice",
	"SubscriptionUsage",
	"BILLING_INTERVAL",
	"SUBSCRIPTION_STATUS",
	"INVOICE_STATUS",
]
