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
# Enumerations (commerce order domain)
# ---------------------------------------------------------------------------

ORDER_CHANNEL = ("B2C", "B2B", "API")
ORDER_STATUS = ("DRAFT", "CONFIRMED", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED", "REFUNDED")
PAYMENT_STATUS = ("PENDING", "PAID", "PARTIALLY_PAID", "REFUNDED")
PAYMENT_METHOD = ("MPESA", "CARD", "BANK_TRANSFER", "CREDIT", "CASH")
PAYMENT_TXN_STATUS = ("PENDING", "COMPLETED", "FAILED", "REFUNDED")
CART_STATUS = ("ACTIVE", "ABANDONED", "CONVERTED")
COUPON_DISCOUNT_TYPE = ("PERCENTAGE", "FIXED_AMOUNT")


# ---------------------------------------------------------------------------
# ProductCatalogue
# ---------------------------------------------------------------------------

class ProductCatalogue(AuditMixin, Model):
	"""Sellable product / service definition.

	unit_price_cents: catalogue list price in smallest currency unit.
	attributes: arbitrary product attributes (colour, size, spec sheet, etc.).
	images: ordered list of public image URLs.
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_product_catalogue"
	__table_args__ = (
		UniqueConstraint("tenant_id", "product_code", name="uq_com_product_tenant_code"),
		Index("ix_com_product_tenant", "tenant_id"),
		Index("ix_com_product_category", "category"),
		Index("ix_com_product_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	product_code = Column(String(30), nullable=False)
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)
	category = Column(String(50), nullable=True)
	unit_price_cents = Column(BigInteger, nullable=False, comment="List price in smallest currency unit")
	currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")
	tax_code = Column(String(20), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")
	images: Any = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="Ordered list of public image URLs",
	)
	attributes: Any = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Arbitrary product attributes",
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
		return f"<ProductCatalogue {self.product_code!r} {self.name!r} price={self.unit_price_cents}¢>"


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

class Cart(AuditMixin, Model):
	"""Shopping cart — persisted to allow abandoned-cart recovery.

	items: JSONB list of {product_code, qty, unit_price_cents, discount_cents}.
	session_token: anonymous / guest cart identifier (unique per tenant).
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_cart"
	__table_args__ = (
		UniqueConstraint("tenant_id", "session_token", name="uq_com_cart_tenant_token"),
		Index("ix_com_cart_tenant", "tenant_id"),
		Index("ix_com_cart_customer", "customer_id"),
		Index("ix_com_cart_status", "status"),
		Index("ix_com_cart_expires", "expires_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	customer_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK Party.id; NULL for guest")
	session_token = Column(String(64), nullable=False, comment="Unique per tenant; ties guest session to cart")
	status = Column(
		String(15),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE|ABANDONED|CONVERTED",
	)
	expires_at = Column(DateTime(timezone=True), nullable=True)
	items: Any = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{product_code, qty, unit_price_cents, discount_cents}]",
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

	orders: list[Order] = relationship(
		"Order",
		back_populates="cart",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Cart {self.id!r} customer={self.customer_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

class Order(RulesMixin, AuditMixin, Model):
	"""Sales order — created from a cart or directly via API/B2B.

	All monetary amounts are in cents (smallest currency unit).
	total_cents = subtotal_cents - discount_cents + tax_cents + shipping_cents
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_order"
	__table_args__ = (
		UniqueConstraint("tenant_id", "order_number", name="uq_com_order_tenant_number"),
		Index("ix_com_order_tenant", "tenant_id"),
		Index("ix_com_order_customer", "customer_id"),
		Index("ix_com_order_status", "status"),
		Index("ix_com_order_payment_status", "payment_status"),
		Index("ix_com_order_cart", "cart_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"status", "payment_status", "discount_cents", "notes",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	order_number = Column(String(20), nullable=False, comment="Human-readable; unique per tenant")
	customer_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK Party.id")
	cart_id = Column(
		UUID(as_uuid=False),
		ForeignKey("com_cart.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	channel = Column(
		String(5),
		nullable=False,
		default="B2C",
		server_default="B2C",
		comment="B2C|B2B|API",
	)
	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT|CONFIRMED|PROCESSING|SHIPPED|DELIVERED|CANCELLED|REFUNDED",
	)
	subtotal_cents = Column(BigInteger, nullable=False, default=0)
	discount_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	tax_cents = Column(BigInteger, nullable=False, default=0)
	shipping_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	total_cents = Column(BigInteger, nullable=False, default=0)
	payment_status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		server_default="PENDING",
		comment="PENDING|PAID|PARTIALLY_PAID|REFUNDED",
	)
	shipping_address: Any = Column(JSONB, nullable=False, default=dict, server_default="{}")
	billing_address: Any = Column(JSONB, nullable=False, default=dict, server_default="{}")
	notes = Column(Text, nullable=True)

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

	cart: Cart | None = relationship("Cart", back_populates="orders", lazy="select")
	lines: list[OrderLine] = relationship(
		"OrderLine",
		back_populates="order",
		cascade="all, delete-orphan",
		lazy="select",
	)
	payments: list[PaymentTransaction] = relationship(
		"PaymentTransaction",
		back_populates="order",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Order {self.order_number!r} status={self.status!r} "
			f"total={self.total_cents}¢ payment={self.payment_status!r}>"
		)


# ---------------------------------------------------------------------------
# OrderLine
# ---------------------------------------------------------------------------

class OrderLine(AuditMixin, Model):
	"""Single line on an Order.

	line_total_cents = (unit_price_cents - discount_cents) * quantity + tax_cents
	fulfilled_qty tracks partial fulfilment.
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_order_line"
	__table_args__ = (
		Index("ix_com_ol_order", "order_id"),
		Index("ix_com_ol_product", "product_code"),
		Index("ix_com_ol_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("com_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	product_code = Column(String(30), nullable=False)
	description = Column(String(255), nullable=False)
	quantity = Column(Numeric(8, 3), nullable=False)
	unit_price_cents = Column(BigInteger, nullable=False)
	discount_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	tax_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	line_total_cents = Column(BigInteger, nullable=False)
	fulfilled_qty = Column(Numeric(8, 3), nullable=False, default=0, server_default="0")

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

	order: Order = relationship("Order", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<OrderLine order={self.order_id!r} product={self.product_code!r} "
			f"qty={self.quantity} total={self.line_total_cents}¢>"
		)


# ---------------------------------------------------------------------------
# PaymentTransaction
# ---------------------------------------------------------------------------

class PaymentTransaction(AuditMixin, Model):
	"""Immutable payment event linked to an Order.

	Each attempt (including retries and refunds) is a separate row.
	provider_response: raw gateway response payload for audit/reconciliation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_payment_transaction"
	__table_args__ = (
		Index("ix_com_pt_order", "order_id"),
		Index("ix_com_pt_tenant", "tenant_id"),
		Index("ix_com_pt_status", "status"),
		Index("ix_com_pt_reference", "reference"),
		Index("ix_com_pt_processed", "processed_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("com_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	payment_method = Column(
		String(20),
		nullable=False,
		comment="MPESA|CARD|BANK_TRANSFER|CREDIT|CASH",
	)
	amount_cents = Column(BigInteger, nullable=False)
	currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")
	reference = Column(String(100), nullable=False, index=True, comment="Gateway/provider reference")
	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		server_default="PENDING",
		comment="PENDING|COMPLETED|FAILED|REFUNDED",
	)
	provider_response: Any = Column(JSONB, nullable=True)
	processed_at = Column(DateTime(timezone=True), nullable=True)

	# Append-only but carry created_at for query convenience
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

	order: Order = relationship("Order", back_populates="payments", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<PaymentTransaction order={self.order_id!r} method={self.payment_method!r} "
			f"amount={self.amount_cents}¢ status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Coupon
# ---------------------------------------------------------------------------

class Coupon(AuditMixin, Model):
	"""Discount coupon redeemable at checkout.

	discount_type PERCENTAGE: discount_value is a percentage (e.g. 10.00 = 10%).
	discount_type FIXED_AMOUNT: discount_value is subtracted in the order currency
	  (caller scales to cents at application time).
	max_uses: NULL = unlimited.
	"""

	__allow_unmapped__ = True
	__tablename__ = "com_coupon"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_com_coupon_tenant_code"),
		Index("ix_com_coupon_tenant", "tenant_id"),
		Index("ix_com_coupon_active", "is_active"),
		Index("ix_com_coupon_valid_to", "valid_to"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(30), nullable=False, comment="Unique per tenant")
	discount_type = Column(
		String(15),
		nullable=False,
		comment="PERCENTAGE|FIXED_AMOUNT",
	)
	discount_value = Column(
		Numeric(8, 2),
		nullable=False,
		comment="Percentage (e.g. 10.00) or fixed amount in display currency",
	)
	min_order_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	max_uses = Column(Integer, nullable=True, comment="NULL = unlimited")
	uses_count = Column(Integer, nullable=False, default=0, server_default="0")
	valid_from = Column(Date, nullable=False)
	valid_to = Column(Date, nullable=True, comment="NULL = no expiry")
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")

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
			f"<Coupon {self.code!r} type={self.discount_type!r} "
			f"value={self.discount_value} uses={self.uses_count}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ShippingMethod",
	"TaxRule",
	"SubscriptionPlan",
	"Subscription",
	"ProductCatalogue",
	"Cart",
	"Order",
	"OrderLine",
	"PaymentTransaction",
	"Coupon",
]
