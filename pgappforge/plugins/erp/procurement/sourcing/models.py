"""
pgappforge/plugins/erp/procurement/sourcing/models.py

SQLAlchemy 2.x models for the Strategic Sourcing plugin.

Design invariants:
  - ALL PKs: UUID(as_uuid=False) — gen_random_uuid() server default + Python default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - Monetary amounts: BigInteger cents (never Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - Table prefix: src_
  - JSONB for structured arrays/objects (PostgreSQL only)
  - Composite indexes for tenant + status hot paths

RFQ types: SOLE_SOURCE / COMPETITIVE / LIMITED
RFQ statuses: DRAFT / PUBLISHED / CLOSED / AWARDED / CANCELLED
Bid statuses: SUBMITTED / EVALUATED / AWARDED / REJECTED
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	CheckConstraint,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enum constant sets
# ---------------------------------------------------------------------------

RFQ_TYPES = {"SOLE_SOURCE", "COMPETITIVE", "LIMITED"}
RFQ_STATUSES = {"DRAFT", "PUBLISHED", "CLOSED", "AWARDED", "CANCELLED"}
BID_STATUSES = {"SUBMITTED", "EVALUATED", "AWARDED", "REJECTED"}


# ---------------------------------------------------------------------------
# RFQ
# ---------------------------------------------------------------------------

class RFQ(AuditMixin, Model):
	"""Request for Quotation header.

	rfq_ref is auto-generated as RFQ-YYYYMMDD-NNNNN, unique per tenant.
	items is a JSONB array of line items:
	  [{item_code, description, qty, unit, estimated_unit_price_cents}]
	invited_suppliers is a JSONB array of supplier_id strings.
	evaluation_criteria defaults to {price_weight:60, quality_weight:20, delivery_weight:20}.
	submission_deadline gates bid acceptance in submit_bid().
	"""

	__allow_unmapped__ = True
	__tablename__ = "src_rfq"
	__table_args__ = (
		UniqueConstraint("tenant_id", "rfq_ref", name="uq_src_rfq_tenant_ref"),
		CheckConstraint(
			"rfq_type IN ('SOLE_SOURCE','COMPETITIVE','LIMITED')",
			name="ck_src_rfq_type",
		),
		CheckConstraint(
			"status IN ('DRAFT','PUBLISHED','CLOSED','AWARDED','CANCELLED')",
			name="ck_src_rfq_status",
		),
		Index("ix_src_rfq_tenant_status", "tenant_id", "status"),
		Index("ix_src_rfq_tenant_type", "tenant_id", "rfq_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	title = Column(String(300), nullable=False)
	description = Column(Text, nullable=True)
	rfq_ref = Column(String(50), nullable=False, comment="Auto-generated, unique per tenant")
	rfq_type = Column(String(20), nullable=False, default="COMPETITIVE")
	status = Column(String(20), nullable=False, default="DRAFT")
	submission_deadline = Column(DateTime(timezone=True), nullable=True)
	evaluation_criteria = Column(
		JSONB, nullable=False,
		server_default=sa.text("'{\"price_weight\": 60, \"quality_weight\": 20, \"delivery_weight\": 20}'::jsonb"),
		default=lambda: {"price_weight": 60, "quality_weight": 20, "delivery_weight": 20},
		comment="{price_weight, quality_weight, delivery_weight} — must sum to 100",
	)
	items = Column(
		JSONB, nullable=False,
		server_default=sa.text("'[]'::jsonb"),
		default=list,
		comment="[{item_code, description, qty, unit, estimated_unit_price_cents}]",
	)
	invited_suppliers = Column(
		JSONB, nullable=False,
		server_default=sa.text("'[]'::jsonb"),
		default=list,
		comment="List of supplier_id strings",
	)
	entity_id = Column(String(50), nullable=True, comment="Advisory FK to entity/company")
	created_by = Column(String(50), nullable=True, comment="Advisory FK to user/employee who created the RFQ")

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

	bids: list[SupplierBid] = relationship(
		"SupplierBid", back_populates="rfq", lazy="select", cascade="all, delete-orphan"
	)

	def __repr__(self) -> str:
		return f"<RFQ {self.rfq_ref} [{self.status}] type={self.rfq_type}>"


# ---------------------------------------------------------------------------
# SupplierBid
# ---------------------------------------------------------------------------

class SupplierBid(AuditMixin, Model):
	"""One supplier's bid against an RFQ.

	UniqueConstraint(rfq_id, supplier_id) — one bid per supplier per RFQ.
	composite_score is computed by SourcingService.evaluate_bids() using
	weighted formula: price_score * price_weight + tech_score * quality_weight
	  + (1/delivery_days)*100 * delivery_weight.
	line_items mirrors RFQ items with per-unit prices:
	  [{item_code, unit_price_cents, qty, discount_pct}]
	technical_score and commercial_score are set by evaluators (0-100).
	"""

	__allow_unmapped__ = True
	__tablename__ = "src_bid"
	__table_args__ = (
		UniqueConstraint("rfq_id", "supplier_id", name="uq_src_bid_rfq_supplier"),
		CheckConstraint(
			"status IN ('SUBMITTED','EVALUATED','AWARDED','REJECTED')",
			name="ck_src_bid_status",
		),
		Index("ix_src_bid_rfq_status", "rfq_id", "status"),
		Index("ix_src_bid_supplier_rfq", "supplier_id", "rfq_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	rfq_id = Column(
		UUID(as_uuid=False),
		ForeignKey("src_rfq.id", ondelete="CASCADE"),
		nullable=False,
	)

	supplier_id = Column(String(50), nullable=False, comment="Advisory FK to sup_profile.id")
	submitted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	status = Column(String(20), nullable=False, default="SUBMITTED")
	total_bid_cents = Column(BigInteger, nullable=False, comment="Total bid value in integer cents")
	currency_code = Column(String(3), nullable=False, default="USD")
	validity_days = Column(Integer, nullable=False, default=30)
	delivery_days = Column(Integer, nullable=True, comment="Quoted lead time in calendar days")
	quality_notes = Column(Text, nullable=True)
	line_items = Column(
		JSONB, nullable=False,
		server_default=sa.text("'[]'::jsonb"),
		default=list,
		comment="[{item_code, unit_price_cents, qty, discount_pct}]",
	)
	technical_score = Column(Numeric(6, 2), nullable=True, comment="0-100, set by technical evaluator")
	commercial_score = Column(Numeric(6, 2), nullable=True, comment="0-100, set by commercial evaluator")
	composite_score = Column(Numeric(6, 2), nullable=True, comment="Weighted composite, computed by evaluate_bids()")

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

	rfq: RFQ = relationship("RFQ", back_populates="bids", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<SupplierBid supplier={self.supplier_id} rfq={self.rfq_id} "
			f"total={self.total_bid_cents}¢ [{self.status}]>"
		)


__all__ = [
	"RFQ",
	"SupplierBid",
	# enum sets
	"RFQ_TYPES",
	"RFQ_STATUSES",
	"BID_STATUSES",
]
