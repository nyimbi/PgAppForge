"""
pgappforge/plugins/billing/models.py

Full billing domain models for the SaaS billing plugin.

Tables
------
billing_plan            — subscription plans (monthly / annual / usage)
billing_subscription    — per-tenant subscription lifecycle
billing_invoice         — invoices generated per period
billing_invoice_item    — line items on an invoice
billing_payment         — payment attempts against an invoice
billing_usage_record    — metered usage events per subscription
billing_dunning_attempt — dunning schedule per past-due subscription
billing_coupon          — discount coupons applicable to plans
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

# Import Model from pgappforge (SQLAlchemy declarative base wrapper)
from pgappforge import Model


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PlanInterval(PyEnum):
	MONTHLY = "monthly"
	ANNUAL = "annual"
	USAGE = "usage"


class SubscriptionStatus(PyEnum):
	TRIALING = "trialing"
	ACTIVE = "active"
	PAST_DUE = "past_due"
	CANCELED = "canceled"
	PAUSED = "paused"


class InvoiceStatus(PyEnum):
	DRAFT = "draft"
	OPEN = "open"
	PAID = "paid"
	VOID = "void"
	UNCOLLECTIBLE = "uncollectible"


class PaymentStatus(PyEnum):
	PENDING = "pending"
	SUCCEEDED = "succeeded"
	FAILED = "failed"
	REFUNDED = "refunded"


class DiscountType(PyEnum):
	PERCENT = "percent"
	FIXED = "fixed"


class DunningStatus(PyEnum):
	PENDING = "pending"
	SENT = "sent"
	FAILED = "failed"
	SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

class Plan(Model):
	"""
	A pricing plan offered to tenants.

	``features`` is a JSONB dict mapping feature-slug → bool (or numeric limit).
	``stripe_price_id`` links to the corresponding Stripe Price object; may be
	NULL for plans that are billed entirely outside Stripe (e.g. enterprise).
	"""
	__allow_unmapped__ = True
	__tablename__ = "billing_plan"
	__table_args__ = (
		UniqueConstraint("name", name="uq_billing_plan_name"),
		Index("ix_billing_plan_active", "is_active"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	name: str = Column(String(100), nullable=False)
	interval: str = Column(
		String(20), nullable=False, default=PlanInterval.MONTHLY.value
	)
	"""One of PlanInterval values."""
	price_cents: int = Column(Integer, nullable=False, default=0)
	"""Base recurring price in the smallest currency unit (e.g. cents for USD)."""
	currency: str = Column(String(3), nullable=False, default="USD")
	features: dict[str, Any] = Column(JSONB, nullable=False, default=dict)
	"""Feature flags / limits, e.g. {"api_calls": 10000, "advanced_export": true}."""
	trial_days: int = Column(Integer, nullable=False, default=0)
	is_active: bool = Column(Boolean, nullable=False, default=True)
	stripe_price_id: str | None = Column(String(255), nullable=True, index=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	subscriptions: list["Subscription"] = relationship(
		"Subscription", back_populates="plan", passive_deletes=True
	)

	@hybrid_property
	def price_dollars(self) -> float:
		return self.price_cents / 100.0

	@hybrid_property
	def is_free(self) -> bool:
		return self.price_cents == 0

	def has_feature(self, feature_name: str) -> bool:
		"""Return truthy value for feature_name from the plan's feature dict."""
		return bool((self.features or {}).get(feature_name, False))

	def __repr__(self) -> str:
		return f"<Plan id={self.id} name={self.name!r} interval={self.interval!r}>"


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

class Subscription(Model):
	"""
	One tenant's active (or historical) subscription to a Plan.

	``cancel_at_period_end`` mirrors the Stripe flag: the subscription remains
	active until ``current_period_end`` then transitions to CANCELED without
	an immediate cancellation.
	"""
	__allow_unmapped__ = True
	__tablename__ = "billing_subscription"
	__table_args__ = (
		Index("ix_billing_sub_tenant", "tenant_id"),
		Index("ix_billing_sub_status", "status"),
		Index("ix_billing_sub_stripe", "stripe_subscription_id"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	tenant_id: int = Column(
		Integer, ForeignKey("tenancy_tenant.id", ondelete="CASCADE"), nullable=False
	)
	plan_id: int = Column(
		Integer, ForeignKey("billing_plan.id", ondelete="RESTRICT"), nullable=False
	)
	status: str = Column(
		String(20), nullable=False, default=SubscriptionStatus.TRIALING.value
	)
	current_period_start: datetime | None = Column(DateTime(timezone=True), nullable=True)
	current_period_end: datetime | None = Column(DateTime(timezone=True), nullable=True)
	trial_end: datetime | None = Column(DateTime(timezone=True), nullable=True)
	stripe_subscription_id: str | None = Column(String(255), nullable=True, unique=True)
	cancel_at_period_end: bool = Column(Boolean, nullable=False, default=False)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	plan: "Plan" = relationship("Plan", back_populates="subscriptions")
	invoices: list["Invoice"] = relationship(
		"Invoice", back_populates="subscription", cascade="all, delete-orphan"
	)
	usage_records: list["UsageRecord"] = relationship(
		"UsageRecord", back_populates="subscription", cascade="all, delete-orphan"
	)
	dunning_attempts: list["DunningAttempt"] = relationship(
		"DunningAttempt", back_populates="subscription", cascade="all, delete-orphan"
	)

	@hybrid_property
	def is_active(self) -> bool:
		return self.status in (
			SubscriptionStatus.ACTIVE.value,
			SubscriptionStatus.TRIALING.value,
		)

	@hybrid_property
	def is_trialing(self) -> bool:
		return self.status == SubscriptionStatus.TRIALING.value

	@hybrid_property
	def trial_days_remaining(self) -> int | None:
		if self.trial_end is None:
			return None
		now = datetime.now(timezone.utc)
		delta = self.trial_end - now
		return max(0, delta.days)

	def __repr__(self) -> str:
		return (
			f"<Subscription id={self.id} tenant_id={self.tenant_id} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------

class Invoice(Model):
	"""
	An invoice issued to a tenant for a billing period.

	``amount_cents`` is the total due.  Individual line items are tracked in
	``InvoiceItem``.  ``stripe_invoice_id`` is populated once synced to Stripe.
	"""
	__allow_unmapped__ = True
	__tablename__ = "billing_invoice"
	__table_args__ = (
		Index("ix_billing_invoice_sub", "subscription_id"),
		Index("ix_billing_invoice_status", "status"),
		Index("ix_billing_invoice_stripe", "stripe_invoice_id"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	subscription_id: int = Column(
		Integer, ForeignKey("billing_subscription.id", ondelete="CASCADE"), nullable=False
	)
	status: str = Column(String(20), nullable=False, default=InvoiceStatus.DRAFT.value)
	amount_cents: int = Column(Integer, nullable=False, default=0)
	currency: str = Column(String(3), nullable=False, default="USD")
	due_date: datetime | None = Column(DateTime(timezone=True), nullable=True)
	paid_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	stripe_invoice_id: str | None = Column(String(255), nullable=True, unique=True)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)
	updated_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	subscription: "Subscription" = relationship("Subscription", back_populates="invoices")
	items: list["InvoiceItem"] = relationship(
		"InvoiceItem", back_populates="invoice", cascade="all, delete-orphan"
	)
	payments: list["Payment"] = relationship(
		"Payment", back_populates="invoice", cascade="all, delete-orphan"
	)

	@hybrid_property
	def amount_dollars(self) -> float:
		return self.amount_cents / 100.0

	@hybrid_property
	def is_paid(self) -> bool:
		return self.status == InvoiceStatus.PAID.value

	@hybrid_property
	def is_overdue(self) -> bool:
		if self.status in (InvoiceStatus.PAID.value, InvoiceStatus.VOID.value):
			return False
		if self.due_date is None:
			return False
		return datetime.now(timezone.utc) > self.due_date

	def __repr__(self) -> str:
		return (
			f"<Invoice id={self.id} sub_id={self.subscription_id} "
			f"status={self.status!r} amount={self.amount_cents}>"
		)


# ---------------------------------------------------------------------------
# InvoiceItem
# ---------------------------------------------------------------------------

class InvoiceItem(Model):
	"""A single line item on an Invoice."""
	__allow_unmapped__ = True
	__tablename__ = "billing_invoice_item"
	__table_args__ = (
		Index("ix_billing_invoice_item_invoice", "invoice_id"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	invoice_id: int = Column(
		Integer, ForeignKey("billing_invoice.id", ondelete="CASCADE"), nullable=False
	)
	description: str = Column(String(500), nullable=False)
	quantity: int = Column(Integer, nullable=False, default=1)
	unit_price_cents: int = Column(Integer, nullable=False, default=0)
	amount_cents: int = Column(Integer, nullable=False, default=0)
	"""Computed: quantity × unit_price_cents.  Stored for audit immutability."""

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)

	invoice: "Invoice" = relationship("Invoice", back_populates="items")

	@hybrid_property
	def amount_dollars(self) -> float:
		return self.amount_cents / 100.0

	def __repr__(self) -> str:
		return (
			f"<InvoiceItem id={self.id} invoice_id={self.invoice_id} "
			f"desc={self.description!r} amount={self.amount_cents}>"
		)


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

class Payment(Model):
	"""
	A payment attempt against an Invoice.

	Multiple Payment rows may exist per Invoice (initial attempt + retries).
	``stripe_payment_intent_id`` ties back to Stripe's PaymentIntent.
	"""
	__allow_unmapped__ = True
	__tablename__ = "billing_payment"
	__table_args__ = (
		Index("ix_billing_payment_invoice", "invoice_id"),
		Index("ix_billing_payment_status", "status"),
		Index("ix_billing_payment_stripe", "stripe_payment_intent_id"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	invoice_id: int = Column(
		Integer, ForeignKey("billing_invoice.id", ondelete="CASCADE"), nullable=False
	)
	amount_cents: int = Column(Integer, nullable=False)
	method: str = Column(String(50), nullable=False, default="card")
	"""E.g. 'card', 'bank_transfer', 'sepa_debit'."""
	status: str = Column(String(20), nullable=False, default=PaymentStatus.PENDING.value)
	stripe_payment_intent_id: str | None = Column(String(255), nullable=True, index=True)
	failure_reason: str | None = Column(Text, nullable=True)
	attempted_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)

	invoice: "Invoice" = relationship("Invoice", back_populates="payments")

	@hybrid_property
	def succeeded(self) -> bool:
		return self.status == PaymentStatus.SUCCEEDED.value

	def __repr__(self) -> str:
		return (
			f"<Payment id={self.id} invoice_id={self.invoice_id} "
			f"status={self.status!r} amount={self.amount_cents}>"
		)


# ---------------------------------------------------------------------------
# UsageRecord
# ---------------------------------------------------------------------------

class UsageRecord(Model):
	"""
	A single metered usage event for a subscription.

	``metric_name`` identifies the billable dimension (e.g. 'api_calls',
	'storage_gb', 'seats').  ``metadata`` holds arbitrary context (request IDs,
	source IP, etc.) for audit purposes.
	"""
	__allow_unmapped__ = True
	__tablename__ = "billing_usage_record"
	__table_args__ = (
		Index("ix_billing_usage_sub_metric", "subscription_id", "metric_name"),
		Index("ix_billing_usage_recorded_at", "recorded_at"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	subscription_id: int = Column(
		Integer, ForeignKey("billing_subscription.id", ondelete="CASCADE"), nullable=False
	)
	metric_name: str = Column(String(100), nullable=False)
	quantity: Numeric = Column(Numeric(precision=18, scale=6), nullable=False, default=1)
	recorded_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		index=True,
	)
	metadata: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

	subscription: "Subscription" = relationship(
		"Subscription", back_populates="usage_records"
	)

	def __repr__(self) -> str:
		return (
			f"<UsageRecord id={self.id} sub_id={self.subscription_id} "
			f"metric={self.metric_name!r} qty={self.quantity}>"
		)


# ---------------------------------------------------------------------------
# DunningAttempt
# ---------------------------------------------------------------------------

class DunningAttempt(Model):
	"""
	One step in the dunning (failed-payment retry) schedule for a subscription.

	Schedule: day 1, 3, 7, 14 after first failure → cancel after 14 days unpaid.
	``attempt_number`` is 1-indexed.  ``next_attempt_at`` is NULL on final attempt.
	"""
	__allow_unmapped__ = True
	__tablename__ = "billing_dunning_attempt"
	__table_args__ = (
		Index("ix_billing_dunning_sub", "subscription_id"),
		Index("ix_billing_dunning_next", "next_attempt_at"),
		UniqueConstraint(
			"subscription_id", "attempt_number",
			name="uq_billing_dunning_sub_attempt",
		),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	subscription_id: int = Column(
		Integer, ForeignKey("billing_subscription.id", ondelete="CASCADE"), nullable=False
	)
	attempt_number: int = Column(Integer, nullable=False)
	attempted_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)
	status: str = Column(String(20), nullable=False, default=DunningStatus.PENDING.value)
	next_attempt_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
	failure_reason: str | None = Column(Text, nullable=True)

	subscription: "Subscription" = relationship(
		"Subscription", back_populates="dunning_attempts"
	)

	# Dunning schedule: attempt_number → days offset from first failure
	SCHEDULE_DAYS: dict[int, int] = {1: 1, 2: 3, 3: 7, 4: 14}
	MAX_ATTEMPTS: int = 4

	def __repr__(self) -> str:
		return (
			f"<DunningAttempt id={self.id} sub_id={self.subscription_id} "
			f"attempt={self.attempt_number} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Coupon
# ---------------------------------------------------------------------------

class Coupon(Model):
	"""
	Discount coupon redeemable against a subscription.

	``applicable_plans`` is a JSONB list of plan names.  Empty list means the
	coupon applies to all plans.  ``max_redemptions`` of NULL means unlimited.
	"""
	__allow_unmapped__ = True
	__tablename__ = "billing_coupon"
	__table_args__ = (
		UniqueConstraint("code", name="uq_billing_coupon_code"),
		Index("ix_billing_coupon_valid_until", "valid_until"),
	)

	id: int = Column(Integer, primary_key=True, autoincrement=True)
	code: str = Column(String(50), nullable=False)
	discount_type: str = Column(String(10), nullable=False, default=DiscountType.PERCENT.value)
	"""'percent' or 'fixed' (fixed = cents off)."""
	discount_value: Numeric = Column(
		Numeric(precision=10, scale=2), nullable=False, default=0
	)
	"""Percentage (0-100) for percent; cents for fixed."""
	valid_until: datetime | None = Column(DateTime(timezone=True), nullable=True)
	max_redemptions: int | None = Column(Integer, nullable=True)
	times_redeemed: int = Column(Integer, nullable=False, default=0)
	applicable_plans: list[str] = Column(JSONB, nullable=False, default=list)

	created_at: datetime = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)

	@hybrid_property
	def is_valid(self) -> bool:
		now = datetime.now(timezone.utc)
		if self.valid_until and now > self.valid_until:
			return False
		if self.max_redemptions is not None and self.times_redeemed >= self.max_redemptions:
			return False
		return True

	def applies_to_plan(self, plan_name: str) -> bool:
		plans = self.applicable_plans or []
		return len(plans) == 0 or plan_name in plans

	def compute_discount_cents(self, amount_cents: int) -> int:
		"""Return the discount amount in cents for a given invoice total."""
		if self.discount_type == DiscountType.PERCENT.value:
			return int(amount_cents * float(self.discount_value) / 100)
		# fixed — discount_value is already in cents
		return min(int(self.discount_value), amount_cents)

	def __repr__(self) -> str:
		return (
			f"<Coupon id={self.id} code={self.code!r} "
			f"type={self.discount_type!r} value={self.discount_value}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Plan",
	"Subscription",
	"Invoice",
	"InvoiceItem",
	"Payment",
	"UsageRecord",
	"DunningAttempt",
	"Coupon",
	# Enums
	"PlanInterval",
	"SubscriptionStatus",
	"InvoiceStatus",
	"PaymentStatus",
	"DiscountType",
	"DunningStatus",
]
