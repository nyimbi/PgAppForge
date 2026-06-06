"""
pgappforge/plugins/erp/operations/rental/models.py

SQLAlchemy 2.x models for the Rental Management plugin.

Design invariants:
  - ALL PKs: UUID(as_uuid=False) — gen_random_uuid() server default + Python default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - Monetary amounts: Integer cents (never Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - JSONB for semi-structured metadata
  - Composite indexes for tenant + status hot paths
  - Table prefix: rnt_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
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
# RentalAsset
# ---------------------------------------------------------------------------

class RentalAsset(AuditMixin, Model):
	"""Inventory of assets available for rental.

	status transitions:
	  AVAILABLE → RENTED (on order activation)
	  RENTED → AVAILABLE (on return or cancellation)
	  AVAILABLE | RENTED → MAINTENANCE → AVAILABLE
	  any → RETIRED

	condition_rating: 1 (worst) to 10 (best).
	metadata_: arbitrary tenant-specific key-value store.
	"""

	__allow_unmapped__ = True
	__tablename__ = "rnt_asset"
	__table_args__ = (
		UniqueConstraint("tenant_id", "asset_code", name="uq_rnt_asset_tenant_code"),
		Index("ix_rnt_asset_tenant_status_cat", "tenant_id", "status", "category"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(String(300), nullable=False)
	asset_code = Column(String(50), nullable=False, comment="Short code, unique per tenant")
	category = Column(String(100), nullable=True)
	status = Column(String(20), nullable=False, default="AVAILABLE")

	# Rates (integer cents per period)
	daily_rate_cents = Column(Integer, nullable=False)
	weekly_rate_cents = Column(Integer, nullable=True)
	monthly_rate_cents = Column(Integer, nullable=True)
	deposit_amount_cents = Column(Integer, nullable=False, default=0)

	description = Column(Text, nullable=True)
	condition_rating = Column(Integer, nullable=False, default=5, comment="1=worst, 10=best")

	metadata_ = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="'{}'::jsonb",
		comment="Arbitrary tenant-specific key-value store",
	)
	entity_id = Column(String(50), nullable=True, comment="Cross-plugin entity reference")

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

	rental_orders: list[RentalOrder] = relationship(
		"RentalOrder",
		back_populates="asset",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<RentalAsset {self.asset_code!r} {self.name!r} [{self.status}]>"


# ---------------------------------------------------------------------------
# RentalOrder
# ---------------------------------------------------------------------------

class RentalOrder(AuditMixin, Model):
	"""A rental booking for a specific asset over a date range.

	rental_amount_cents: computed on creation as (end_date - start_date).days * daily_rate_cents
	                     snapshot of the rate at booking time.

	deposit_status:
	  PENDING → COLLECTED → REFUNDED | RETAINED

	status: PENDING → ACTIVE → COMPLETED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "rnt_order"
	__table_args__ = (
		UniqueConstraint("tenant_id", "order_ref", name="uq_rnt_order_tenant_ref"),
		Index("ix_rnt_order_asset_status", "asset_id", "status"),
		Index("ix_rnt_order_customer", "customer_id"),
		Index("ix_rnt_order_tenant_status_start", "tenant_id", "status", "start_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rnt_asset.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	customer_id = Column(String(50), nullable=True, index=True)
	customer_name = Column(String(200), nullable=False)
	customer_email = Column(String(320), nullable=True)

	order_ref = Column(String(50), nullable=False, comment="Unique order reference per tenant")

	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	actual_return_date = Column(Date, nullable=True)

	status = Column(String(20), nullable=False, default="PENDING")

	# Rate snapshot at booking time
	daily_rate_cents = Column(Integer, nullable=False)
	deposit_amount_cents = Column(Integer, nullable=False)
	deposit_status = Column(String(20), nullable=False, default="PENDING")

	# Amounts (integer cents)
	rental_amount_cents = Column(Integer, nullable=False, comment="Computed: days * daily_rate_cents")
	discount_cents = Column(Integer, nullable=False, default=0)
	damage_charge_cents = Column(Integer, nullable=False, default=0)

	notes = Column(Text, nullable=True)
	return_condition_notes = Column(Text, nullable=True)

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

	asset: RentalAsset = relationship(
		"RentalAsset",
		back_populates="rental_orders",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<RentalOrder {self.order_ref!r} [{self.status}] asset={self.asset_id}>"


__all__ = [
	"RentalAsset",
	"RentalOrder",
]
