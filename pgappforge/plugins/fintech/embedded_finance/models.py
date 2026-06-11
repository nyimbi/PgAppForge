"""
pgappforge/plugins/fintech/embedded_finance/models.py

Embedded Finance models — partners, products, consent, and revenue share.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents — never Decimal/float in storage
  - EmbeddedRevShareRecord: ImmutableRecordMixin (insert-only)
  - API keys: SHA-256 hash stored; raw key shown to partner once only
  - Table name convention: ft_emb_<entity>
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
	Numeric,
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
# EmbeddedPartner — third-party platform consuming embedded finance APIs
# ---------------------------------------------------------------------------

class EmbeddedPartner(AuditMixin, Model):
	"""A platform partner embedding fintech capabilities via API.

	partner_type:
	  MARKETPLACE / SAAS / ECOMMERCE / NEOBANK / TELCO / INSURANCE / LOGISTICS

	api_key_hash: SHA-256 of the raw API key (raw key returned once on register).
	revenue_share_pct: decimal fraction of gross revenue shared with partner (e.g. 0.3000 = 30%).
	sandbox_mode: True = partner on sandbox, False = live production.
	status: ACTIVE / SUSPENDED / TERMINATED
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_emb_partner"
	__table_args__ = (
		Index("ix_ft_emb_partner_tenant", "tenant_id"),
		Index("ix_ft_emb_partner_status", "status"),
		Index("ix_ft_emb_partner_type", "partner_type"),
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
	partner_type = Column(
		String(20),
		nullable=False,
		comment="MARKETPLACE / SAAS / ECOMMERCE / NEOBANK / TELCO / INSURANCE / LOGISTICS",
	)
	api_key_hash = Column(
		String(64),
		nullable=False,
		comment="SHA-256 of raw API key — raw key shown once only",
	)
	revenue_share_pct = Column(
		Numeric(5, 4),
		nullable=False,
		default=0,
		server_default="0",
		comment="Decimal fraction e.g. 0.3000 = 30%",
	)
	sandbox_mode = Column(Boolean, nullable=False, default=True, server_default="true")
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE / SUSPENDED / TERMINATED",
	)
	onboarded_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# relationships
	products = relationship("EmbeddedProduct", back_populates="partner", lazy="dynamic")
	consents = relationship("EmbeddedConsent", back_populates="partner", lazy="dynamic")
	rev_share_records = relationship("EmbeddedRevShareRecord", back_populates="partner", lazy="dynamic")


# ---------------------------------------------------------------------------
# EmbeddedProduct — product/capability offered by a partner
# ---------------------------------------------------------------------------

class EmbeddedProduct(Model):
	"""A specific fintech product enabled for an EmbeddedPartner.

	product_type:
	  ACCOUNT / WALLET / PAYMENTS / CARDS / LOANS / BNPL / REMITTANCE / INSURANCE

	config JSONB: {limits, supported_currencies, kyc_tier_required}
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_emb_product"
	__table_args__ = (
		Index("ix_ft_emb_product_tenant", "tenant_id"),
		Index("ix_ft_emb_product_partner", "partner_id"),
		Index("ix_ft_emb_product_type", "product_type"),
		UniqueConstraint("partner_id", "product_type", name="uq_ft_emb_product_partner_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	partner_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_emb_partner.id"),
		nullable=False,
	)
	product_type = Column(
		String(20),
		nullable=False,
		comment="ACCOUNT / WALLET / PAYMENTS / CARDS / LOANS / BNPL / REMITTANCE / INSURANCE",
	)
	is_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
	config = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{limits, supported_currencies, kyc_tier_required}",
	)
	go_live_at = Column(DateTime(timezone=True), nullable=True)

	# relationships
	partner = relationship("EmbeddedPartner", back_populates="products")


# ---------------------------------------------------------------------------
# EmbeddedConsent — customer consent grant for a partner
# ---------------------------------------------------------------------------

class EmbeddedConsent(Model):
	"""Records a customer's explicit consent to share data/products with a partner.

	products_consented: JSONB list of product_type strings the customer approved.
	expires_at: None = indefinite consent.
	is_active: False = revoked.
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_emb_consent"
	__table_args__ = (
		Index("ix_ft_emb_consent_tenant", "tenant_id"),
		Index("ix_ft_emb_consent_customer", "customer_id"),
		Index("ix_ft_emb_consent_partner", "partner_id"),
		Index("ix_ft_emb_consent_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	customer_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	partner_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_emb_partner.id"),
		nullable=False,
	)
	products_consented = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="List of product_type strings consented to",
	)
	granted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	expires_at = Column(DateTime(timezone=True), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True, server_default="true")

	# relationships
	partner = relationship("EmbeddedPartner", back_populates="consents")


# ---------------------------------------------------------------------------
# EmbeddedRevShareRecord — immutable revenue share settlement record
# ---------------------------------------------------------------------------

class EmbeddedRevShareRecord(ImmutableRecordMixin, Model):
	"""Revenue share calculation record for a partner, period, and product — insert-only.

	net_cents = gross_revenue_cents - partner_share_cents
	"""

	__allow_unmapped__ = True
	__tablename__ = "ft_emb_rev_share"
	__table_args__ = (
		Index("ix_ft_emb_rev_share_tenant", "tenant_id"),
		Index("ix_ft_emb_rev_share_partner", "partner_id"),
		Index("ix_ft_emb_rev_share_period", "period"),
		UniqueConstraint(
			"partner_id", "period", "product_type",
			name="uq_ft_emb_rev_share_partner_period_product",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	partner_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_emb_partner.id"),
		nullable=False,
	)
	period = Column(String(7), nullable=False, comment="YYYY-MM")
	product_type = Column(String(20), nullable=False)
	gross_revenue_cents = Column(Integer, nullable=False)
	partner_share_cents = Column(Integer, nullable=False)
	net_cents = Column(Integer, nullable=False)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# relationships
	partner = relationship("EmbeddedPartner", back_populates="rev_share_records")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"EmbeddedPartner",
	"EmbeddedProduct",
	"EmbeddedConsent",
	"EmbeddedRevShareRecord",
]
