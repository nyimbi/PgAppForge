"""
pgappforge/plugins/erp/industry/consumer_goods/models.py

SQLAlchemy models for the Consumer Goods plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid()
  - ALL monetary amounts: Integer cents (NEVER float)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - JSONB for mechanics, findings, photos, shelf metadata
  - lazy='select' throughout

Table prefix: cg_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# TradePromotion
# ---------------------------------------------------------------------------

class TradePromotion(AuditMixin, Model):
	"""Trade promotion header.

	Represents an off-invoice or billback promotion targeted at a retailer
	or customer group.  mechanics JSONB captures promo-type-specific rules:
	e.g. {buy_qty, get_qty, discount_pct} for BOGO or {threshold_cents,
	rebate_pct} for volume rebates.

	budget_cents is the approved spend ceiling — immutable once APPROVED.
	committed_cents is updated as claims are submitted.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cg_trade_promotion"
	__table_args__ = (
		Index("ix_cg_tp_tenant", "tenant_id"),
		Index("ix_cg_tp_retailer", "target_retailer_id"),
		Index("ix_cg_tp_tenant_status", "tenant_id", "status"),
		Index("ix_cg_tp_date_range", "start_date", "end_date"),
		UniqueConstraint("tenant_id", "promo_number", name="uq_cg_tp_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	promo_number = Column(String(50), nullable=False, comment="Unique promo reference per tenant")
	name = Column(String(255), nullable=False)
	promo_type = Column(
		String(30),
		nullable=False,
		comment="OFF_INVOICE|BILLBACK|SCAN_DOWN|BOGO|VOLUME_REBATE|DISPLAY|COOP_ADVERTISING",
	)
	target_retailer_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to foundation Party (retailer)")
	target_retailer_name = Column(String(255), nullable=True, comment="Denormalized for display")
	channel = Column(String(30), nullable=True, comment="MT|GT|ECOMMERCE|WHOLESALE")

	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)

	# Budget — integer cents
	budget_cents = Column(Integer, nullable=False, comment="Approved spend ceiling; immutable once APPROVED")
	committed_cents = Column(Integer, nullable=False, default=0, comment="Sum of submitted claim amounts; add-only")
	paid_cents = Column(Integer, nullable=False, default=0, comment="Sum of approved + paid claims; add-only")

	currency_code = Column(String(3), nullable=False, default="USD")
	mechanics = Column(JSONB, nullable=False, default=dict, comment="Promo-type-specific rules and thresholds")
	products_in_scope = Column(JSONB, nullable=False, default=list, comment="[{product_id, sku, included: bool}]")

	status = Column(String(20), nullable=False, default="DRAFT", comment="DRAFT|SUBMITTED|APPROVED|ACTIVE|CLOSED|CANCELLED")
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	approved_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	claims: list[PromotionClaim] = relationship("PromotionClaim", back_populates="promotion", lazy="select")

	def __repr__(self) -> str:
		return f"<TradePromotion {self.promo_number!r} type={self.promo_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# PromotionClaim
# ---------------------------------------------------------------------------

class PromotionClaim(AuditMixin, Model):
	"""Claim against a trade promotion by the retailer or sales rep.

	actual_spend_cents is the amount the retailer claims was spent under
	the promo mechanics.  approved_cents is set by the trade spend team
	after validation (may differ from claimed amount).

	IMMUTABLE once status=PAID — insert correction entries only.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cg_promotion_claim"
	__table_args__ = (
		Index("ix_cg_claim_promo", "promo_id"),
		Index("ix_cg_claim_tenant", "tenant_id"),
		Index("ix_cg_claim_tenant_status", "tenant_id", "status"),
		Index("ix_cg_claim_claimed_at", "claimed_at"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	promo_id = Column(UUID(as_uuid=False), ForeignKey("cg_trade_promotion.id"), nullable=False, index=True)
	claim_number = Column(String(50), nullable=True)
	retailer_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to foundation Party (retailer)")

	claimed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
	claim_period_start = Column(Date, nullable=True)
	claim_period_end = Column(Date, nullable=True)

	# Amounts — integer cents
	actual_spend_cents = Column(Integer, nullable=False, comment="Retailer-claimed spend amount")
	approved_cents = Column(Integer, nullable=True, comment="Amount approved after validation; NULL until reviewed")
	paid_cents = Column(Integer, nullable=False, default=0, comment="Amount actually paid; add-only")

	currency_code = Column(String(3), nullable=False, default="USD")
	supporting_docs = Column(JSONB, nullable=False, default=list, comment="[{url, doc_type, uploaded_at}]")
	status = Column(
		String(20),
		nullable=False,
		default="SUBMITTED",
		comment="SUBMITTED|UNDER_REVIEW|APPROVED|REJECTED|PAID|DISPUTED",
	)
	reviewed_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	reviewed_at = Column(DateTime(timezone=True), nullable=True)
	rejection_reason = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	promotion: TradePromotion = relationship("TradePromotion", back_populates="claims", lazy="select")

	def __repr__(self) -> str:
		return f"<PromotionClaim promo={self.promo_id!r} claimed={self.actual_spend_cents}¢ status={self.status!r}>"


# ---------------------------------------------------------------------------
# RetailExecution
# ---------------------------------------------------------------------------

class RetailExecution(AuditMixin, Model):
	"""Field sales / merchandiser store visit record.

	findings JSONB captures structured audit results per category
	(e.g. [{category: 'shelf_share', score: 0.72, notes: '...'}]).
	photos JSONB stores photo URLs per finding:
	  [{url, category, taken_at, thumbnail_url}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "cg_retail_execution"
	__table_args__ = (
		Index("ix_cg_re_tenant", "tenant_id"),
		Index("ix_cg_re_store", "store_id"),
		Index("ix_cg_re_auditor", "auditor_id"),
		Index("ix_cg_re_visit_date", "visit_date"),
		Index("ix_cg_re_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	store_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to foundation Party (store/outlet)")
	store_name = Column(String(255), nullable=True, comment="Denormalized for display")
	store_type = Column(String(30), nullable=True, comment="HYPERMARKET|SUPERMARKET|CONVENIENCE|PHARMACY|WHOLESALE")
	auditor_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to ab_user (field rep)")

	visit_date = Column(Date, nullable=False)
	check_in_at = Column(DateTime(timezone=True), nullable=True)
	check_out_at = Column(DateTime(timezone=True), nullable=True)

	findings = Column(JSONB, nullable=False, default=list, comment="[{category, score, compliant, notes}]")
	photos = Column(JSONB, nullable=False, default=list, comment="[{url, category, taken_at, thumbnail_url}]")
	gps_location = Column(JSONB, nullable=True, comment="{lat, lng, accuracy_m}")

	overall_score = Column(Numeric(5, 4), nullable=True, comment="Weighted compliance score 0.0000–1.0000")
	status = Column(String(20), nullable=False, default="DRAFT", comment="DRAFT|SUBMITTED|REVIEWED|APPROVED")
	reviewer_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user")
	reviewed_at = Column(DateTime(timezone=True), nullable=True)
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<RetailExecution store={self.store_id!r} date={self.visit_date} score={self.overall_score}>"


# ---------------------------------------------------------------------------
# PlanoGram
# ---------------------------------------------------------------------------

class PlanoGram(AuditMixin, Model):
	"""Shelf planogram — defines expected shelf position and facing for a SKU.

	Represents the ideal shelf layout standard for a product at a given
	store type.  Deviations are captured via RetailExecution findings.

	effective_from/to govern which planogram version is active for a
	given period (allows seasonal resets).
	"""

	__allow_unmapped__ = True
	__tablename__ = "cg_planogram"
	__table_args__ = (
		Index("ix_cg_pg_tenant", "tenant_id"),
		Index("ix_cg_pg_product", "product_id"),
		Index("ix_cg_pg_store_type", "store_type"),
		Index("ix_cg_pg_tenant_product_store", "tenant_id", "product_id", "store_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product master")
	product_sku = Column(String(100), nullable=True, comment="Denormalized SKU")
	store_type = Column(String(30), nullable=False, comment="HYPERMARKET|SUPERMARKET|CONVENIENCE|PHARMACY|WHOLESALE")

	shelf_position = Column(String(50), nullable=True, comment="e.g. EYE_LEVEL|FLOOR|TOP|END_CAP")
	bay_number = Column(Integer, nullable=True)
	shelf_number = Column(Integer, nullable=True)
	position_from_left = Column(Integer, nullable=True, comment="Column position counting from left")
	facing_count = Column(Integer, nullable=False, default=1, comment="Number of product facings required")
	depth_count = Column(Integer, nullable=False, default=1, comment="Depth of stack required")

	category = Column(String(100), nullable=True, comment="Shelf category / segment")
	effective_from = Column(Date, nullable=True)
	effective_to = Column(Date, nullable=True)
	image_url = Column(String(500), nullable=True, comment="Reference planogram image")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<PlanoGram sku={self.product_sku!r} store_type={self.store_type!r} facings={self.facing_count}>"


__all__ = [
	"TradePromotion",
	"PromotionClaim",
	"RetailExecution",
	"PlanoGram",
]
