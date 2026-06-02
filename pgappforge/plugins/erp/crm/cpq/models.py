"""
pgappforge/plugins/erp/crm/cpq/models.py

SQLAlchemy models for the Configure-Price-Quote (CPQ) plugin.

Design rules enforced:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY — never Numeric/float for money
  - AuditMixin on all mutable entities
  - RulesMixin on Quote, PricingRule for rules engine integration
  - lazy='select' throughout (SA 2.x)
  - JSONB for conditions, configuration, config_rules
  - Financial records immutable: QuoteLine amounts stored at quote time

Table name convention: cpq_<entity>
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

RULE_TYPE = ("FIXED", "PERCENT", "TIERED", "VOLUME_DISCOUNT")
BUNDLE_TYPE = ("FIXED", "CONFIGURABLE")
QUOTE_STATUS = ("DRAFT", "SENT", "ACCEPTED", "REJECTED", "EXPIRED")
APPROVAL_STATUS = ("PENDING", "APPROVED", "REJECTED")


# ---------------------------------------------------------------------------
# ProductCatalog
# ---------------------------------------------------------------------------

class ProductCatalog(AuditMixin, Model):
	"""Versioned price catalog — defines the pricing universe for a date range.

	Multiple catalogs can exist but only one should be active per tenant/currency
	at any time. effective_from / effective_to drive date-range lookups.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cpq_product_catalog"
	__table_args__ = (
		Index("ix_cpq_catalog_tenant", "tenant_id"),
		Index("ix_cpq_catalog_active", "is_active"),
		Index("ix_cpq_catalog_dates", "effective_from", "effective_to"),
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
	effective_from = Column(Date, nullable=False, comment="Catalog validity start")
	effective_to = Column(Date, nullable=True, comment="NULL = open-ended")
	currency_code = Column(String(3), nullable=False, default="USD", comment="ISO 4217")
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")
	description = Column(Text, nullable=True)

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

	pricing_rules: list[PricingRule] = relationship(
		"PricingRule",
		back_populates="catalog",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ProductCatalog {self.name!r} {self.effective_from}–{self.effective_to}>"


# ---------------------------------------------------------------------------
# PricingRule
# ---------------------------------------------------------------------------

class PricingRule(RulesMixin, AuditMixin, Model):
	"""Pricing rule within a catalog.

	rule_type determines how the rule is applied:
	  FIXED         — override price to fixed_price_cents
	  PERCENT       — apply discount_pct to list price
	  TIERED        — conditions JSONB contains quantity tier thresholds
	  VOLUME_DISCOUNT — discount based on total line quantity

	conditions JSONB example::
	    [{"field": "quantity", "op": "gte", "value": 10}]

	priority: lower number = higher priority; ties broken by rule insertion order.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cpq_pricing_rule"
	__table_args__ = (
		Index("ix_cpq_pricing_rule_catalog", "catalog_id"),
		Index("ix_cpq_pricing_rule_tenant", "tenant_id"),
		Index("ix_cpq_pricing_rule_active", "is_active"),
		Index("ix_cpq_pricing_rule_priority", "priority"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"is_active", "discount_pct", "fixed_price_cents", "priority",
	})
	__rules_context_fields__: list[str] = []

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	catalog_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cpq_product_catalog.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	rule_name = Column(String(255), nullable=False)
	rule_type = Column(
		String(30),
		nullable=False,
		comment="FIXED/PERCENT/TIERED/VOLUME_DISCOUNT",
	)

	# Conditions JSONB — evaluated by CPQ engine at quote time
	conditions: list[dict] = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="List of condition objects: [{field, op, value}]",
	)

	# Discount / override
	discount_pct = Column(
		Numeric(5, 2),
		nullable=True,
		comment="Percentage discount (0–100); used for PERCENT/VOLUME_DISCOUNT",
	)
	fixed_price_cents = Column(
		Integer,
		nullable=True,
		comment="Override price in cents; used for FIXED rule type",
	)

	priority = Column(
		Integer,
		nullable=False,
		default=100,
		server_default="100",
		comment="Lower = higher priority; 1 = highest",
	)
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

	catalog: ProductCatalog = relationship("ProductCatalog", back_populates="pricing_rules", lazy="select")

	def __repr__(self) -> str:
		return f"<PricingRule {self.rule_name!r} type={self.rule_type!r} priority={self.priority}>"


# ---------------------------------------------------------------------------
# ConfigurableProduct
# ---------------------------------------------------------------------------

class ConfigurableProduct(AuditMixin, Model):
	"""CPQ extension for configurable products.

	Links to an inventory Product (via product_id) and stores configuration
	rules in JSONB. Price bounds enforce min/max for configured variants.

	config_rules JSONB example::
	    {
	        "options": [
	            {"name": "color", "values": ["red", "blue"], "required": true},
	            {"name": "size", "values": ["S", "M", "L"], "required": true}
	        ],
	        "constraints": [
	            {"if": {"color": "blue"}, "then": {"size": ["M", "L"]}}
	        ]
	    }
	"""

	__allow_unmapped__ = True
	__tablename__ = "cpq_configurable_product"
	__table_args__ = (
		UniqueConstraint("tenant_id", "product_id", name="uq_cpq_configurable_product_tenant"),
		Index("ix_cpq_configurable_product_tenant", "tenant_id"),
		Index("ix_cpq_configurable_product_product", "product_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	product_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK to inventory product; not enforced to avoid cross-domain coupling",
	)
	is_configurable = Column(Boolean, nullable=False, default=True, server_default="true")

	# Configuration rules JSONB
	config_rules: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Option definitions and constraint rules",
	)

	# Price bounds in cents
	min_price_cents = Column(
		Integer,
		nullable=True,
		comment="Minimum allowed net price after configuration",
	)
	max_price_cents = Column(
		Integer,
		nullable=True,
		comment="Maximum allowed net price after configuration",
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
		return f"<ConfigurableProduct product_id={self.product_id!r} configurable={self.is_configurable}>"


# ---------------------------------------------------------------------------
# ProductBundle
# ---------------------------------------------------------------------------

class ProductBundle(AuditMixin, Model):
	"""Product bundle definition.

	FIXED bundles: all lines required, base_price_cents applies.
	CONFIGURABLE bundles: optional lines; final price depends on selections.

	discount_pct is applied on top of the sum of component list prices.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cpq_product_bundle"
	__table_args__ = (
		UniqueConstraint("tenant_id", "bundle_code", name="uq_cpq_bundle_tenant_code"),
		Index("ix_cpq_bundle_tenant", "tenant_id"),
		Index("ix_cpq_bundle_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	bundle_code = Column(String(50), nullable=False, comment="Human-readable bundle code; unique per tenant")
	name = Column(String(255), nullable=False)
	bundle_type = Column(
		String(20),
		nullable=False,
		default="FIXED",
		comment="FIXED/CONFIGURABLE",
	)
	base_price_cents = Column(
		Integer,
		nullable=True,
		comment="Override price for FIXED bundles; NULL = sum of component prices",
	)
	discount_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=0,
		server_default="0",
		comment="Bundle-level discount applied after component sum",
	)
	description = Column(Text, nullable=True)
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

	lines: list[BundleLine] = relationship(
		"BundleLine",
		back_populates="bundle",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ProductBundle {self.bundle_code!r} type={self.bundle_type!r}>"


# ---------------------------------------------------------------------------
# BundleLine
# ---------------------------------------------------------------------------

class BundleLine(AuditMixin, Model):
	"""One component line within a product bundle.

	price_override_cents: if set, overrides the product's catalog list price
	for this bundle position. NULL = use catalog price.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cpq_bundle_line"
	__table_args__ = (
		Index("ix_cpq_bundle_line_bundle", "bundle_id"),
		Index("ix_cpq_bundle_line_product", "product_id"),
		Index("ix_cpq_bundle_line_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	bundle_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cpq_product_bundle.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	product_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="FK to inventory product",
	)
	quantity = Column(Numeric(15, 4), nullable=False, default=1)
	is_required = Column(
		Boolean,
		nullable=False,
		default=True,
		server_default="true",
		comment="For CONFIGURABLE bundles: false = optional line",
	)
	price_override_cents = Column(
		Integer,
		nullable=True,
		comment="Override list price for this bundle position; NULL = use catalog",
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

	bundle: ProductBundle = relationship("ProductBundle", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<BundleLine bundle={self.bundle_id!r} product={self.product_id!r} "
			f"qty={self.quantity} required={self.is_required}>"
		)


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------

class Quote(RulesMixin, AuditMixin, Model):
	"""CPQ Quote header.

	Quotes are linked to an Opportunity (optional) and a SalesAccount.
	All monetary amounts are integer cents.

	approval_status: NULL until submitted for approval.
	Financial fields are set by CPQService.generate_quote() and are
	immutable once status = SENT (treat as ledger entries — correct via
	a new revision quote if needed).
	"""

	__allow_unmapped__ = True
	__tablename__ = "cpq_quote"
	__table_args__ = (
		UniqueConstraint("tenant_id", "quote_number", name="uq_cpq_quote_tenant_number"),
		Index("ix_cpq_quote_tenant", "tenant_id"),
		Index("ix_cpq_quote_opportunity", "opportunity_id"),
		Index("ix_cpq_quote_account", "account_id"),
		Index("ix_cpq_quote_status", "status"),
		Index("ix_cpq_quote_owner", "owner_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields: frozenset[str] = frozenset({
		"status", "approval_status", "valid_until",
	})
	__rules_context_fields__: list[str] = [
		"account.health_score",
	]

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# References
	opportunity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_opportunity.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_sales_account.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	quote_number = Column(String(50), nullable=False)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT/SENT/ACCEPTED/REJECTED/EXPIRED",
	)
	valid_until = Column(Date, nullable=True, comment="Quote expiry date")
	currency_code = Column(String(3), nullable=False, default="USD")

	# Amounts — integer cents (set by service, immutable after SENT)
	subtotal_cents = Column(Integer, nullable=False, default=0, server_default="0")
	discount_cents = Column(Integer, nullable=False, default=0, server_default="0")
	tax_cents = Column(Integer, nullable=False, default=0, server_default="0")
	total_cents = Column(Integer, nullable=False, default=0, server_default="0")

	# Ownership
	owner_id = Column(UUID(as_uuid=False), nullable=True, index=True)

	# Approval workflow
	approval_status = Column(
		String(20),
		nullable=True,
		comment="NULL/PENDING/APPROVED/REJECTED",
	)
	approved_by = Column(UUID(as_uuid=False), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)
	approval_notes = Column(Text, nullable=True)

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

	opportunity: Any = relationship(
		"Opportunity",
		foreign_keys=[opportunity_id],
		lazy="select",
	)
	account: Any = relationship(
		"SalesAccount",
		foreign_keys=[account_id],
		lazy="select",
	)
	lines: list[QuoteLine] = relationship(
		"QuoteLine",
		back_populates="quote",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Quote {self.quote_number!r} status={self.status!r} "
			f"total={self.total_cents}¢>"
		)


# ---------------------------------------------------------------------------
# QuoteLine
# ---------------------------------------------------------------------------

class QuoteLine(AuditMixin, Model):
	"""One line item on a CPQ quote.

	net_price_cents = round(list_price_cents * quantity * (1 - discount_pct/100))
	margin_pct = (net_price_cents - cost_cents) / net_price_cents * 100

	configuration JSONB stores the selected options for configurable products.
	All amounts stored at quote creation time — immutable after quote is SENT.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cpq_quote_line"
	__table_args__ = (
		UniqueConstraint("quote_id", "line_number", name="uq_cpq_quote_line_num"),
		Index("ix_cpq_quote_line_quote", "quote_id"),
		Index("ix_cpq_quote_line_product", "product_id"),
		Index("ix_cpq_quote_line_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	quote_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cpq_quote.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	line_number = Column(Integer, nullable=False, comment="1-based sequence within quote")
	product_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	description = Column(Text, nullable=False)
	quantity = Column(Numeric(15, 4), nullable=False, default=1)

	# Pricing — integer cents
	list_price_cents = Column(Integer, nullable=False, default=0, comment="Catalog list price per unit in cents")
	discount_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=0,
		server_default="0",
		comment="Line-level discount percent",
	)
	net_price_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="list_price * qty * (1 - discount_pct/100), rounded to int cents",
	)

	# Cost & margin
	cost_cents = Column(Integer, nullable=True, comment="Cost per unit in cents; NULL = unknown")
	margin_pct = Column(
		Numeric(5, 2),
		nullable=True,
		comment="(net_price - cost * qty) / net_price * 100; NULL if cost unknown",
	)

	# Configuration snapshot for configurable products
	configuration: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="Selected options for configurable product at quote time",
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

	quote: Quote = relationship("Quote", back_populates="lines", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<QuoteLine quote={self.quote_id!r} line={self.line_number} "
			f"net={self.net_price_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ProductCatalog",
	"PricingRule",
	"ConfigurableProduct",
	"ProductBundle",
	"BundleLine",
	"Quote",
	"QuoteLine",
]
