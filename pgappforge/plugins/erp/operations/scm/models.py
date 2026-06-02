"""
pgappforge/plugins/erp/operations/scm/models.py

SQLAlchemy models for the Supply Chain Management (SCM) plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (NEVER Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - lazy='select' throughout (SA 2.x)
  - JSONB for semi-structured fields (supplier events, confidence intervals)
  - Proper composite indexes for tenant + status hot paths

Table prefix: scm_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------

class Supplier(AuditMixin, Model):
	"""SCM supplier master — performance and sourcing profile.

	Links to foundation.Party via party_id for canonical name/address/contact
	data.  SCM-specific KPIs (rating, OTD %, quality score) live here.

	rating: composite 0-10 score; service layer recomputes from historical KPIs.
	on_time_delivery_pct: rolling 12-month on-time delivery percentage.
	quality_score: rolling 12-month acceptance rate.
	lead_time_days: default replenishment lead time for MRP.
	minimum_order_value_cents: integer cents — PO below this triggers a warning.
	preferred: preferred/approved supplier flag for sourcing rules.
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_supplier"
	__table_args__ = (
		Index("ix_scm_supplier_tenant", "tenant_id"),
		Index("ix_scm_supplier_party", "party_id"),
		Index("ix_scm_supplier_tenant_preferred", "tenant_id", "preferred"),
		UniqueConstraint("tenant_id", "supplier_code", name="uq_scm_supplier_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Link to foundation Party (soft FK — no DB constraint for cross-plugin safety)
	party_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to erp_party.id (soft — no DB constraint)",
	)
	supplier_code = Column(String(50), nullable=False, comment="Unique supplier code per tenant")
	name = Column(String(255), nullable=False, comment="Trading name; denormalized from Party for query convenience")

	# Performance KPIs
	rating = Column(
		Numeric(3, 1),
		nullable=True,
		comment="Composite supplier rating 0.0-10.0; NULL = not yet rated",
	)
	on_time_delivery_pct = Column(
		Numeric(5, 2),
		nullable=True,
		comment="Rolling 12-month on-time delivery percentage 0.00-100.00",
	)
	quality_score = Column(
		Numeric(5, 2),
		nullable=True,
		comment="Rolling 12-month acceptance rate 0.00-100.00",
	)

	# Sourcing parameters
	lead_time_days = Column(Integer, nullable=False, default=14, comment="Default replenishment lead time in days")
	minimum_order_value_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Minimum order value in cents; PO below this triggers warning",
	)
	preferred = Column(Boolean, nullable=False, default=False, comment="Preferred/approved source flag")
	is_active = Column(Boolean, nullable=False, default=True)

	# Payment & banking (mirrors AP supplier for cross-plugin usage without hard dep)
	payment_terms_days = Column(Integer, nullable=False, default=30)
	currency_code = Column(String(3), nullable=False, default="USD")

	notes = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	products: list[SupplierProduct] = relationship(
		"SupplierProduct", back_populates="supplier", cascade="all, delete-orphan", lazy="select",
	)
	shipments: list[ShipmentTracking] = relationship(
		"ShipmentTracking", back_populates="supplier", lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Supplier {self.supplier_code!r} {self.name!r} preferred={self.preferred}>"


# ---------------------------------------------------------------------------
# SupplierProduct
# ---------------------------------------------------------------------------

class SupplierProduct(AuditMixin, Model):
	"""Supplier-specific product catalogue entry.

	Associates a supplier with a purchasable product, carrying supplier-specific
	lead time, MOQ, price, and validity period.

	price_cents: integer cents in currency_code — always cents, never float.
	valid_from / valid_to: price/lead-time validity window.
	  NULL valid_to = currently open.
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_supplier_product"
	__table_args__ = (
		Index("ix_scm_sp_supplier", "supplier_id"),
		Index("ix_scm_sp_product", "product_id"),
		Index("ix_scm_sp_tenant", "tenant_id"),
		Index("ix_scm_sp_validity", "product_id", "valid_from", "valid_to"),
		UniqueConstraint("supplier_id", "product_id", "valid_from", name="uq_scm_sp_supplier_product_from"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("scm_supplier.id", ondelete="CASCADE"), nullable=False, index=True)
	product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product/item master (app-managed)")

	# Supplier-specific identity
	supplier_sku = Column(String(100), nullable=True, comment="Supplier's own part number / SKU")
	description = Column(Text, nullable=True, comment="Supplier's description of the product")

	# Sourcing terms
	lead_time_days = Column(Integer, nullable=False, default=14, comment="Supplier-specific lead time for this product")
	minimum_quantity = Column(Numeric(15, 4), nullable=False, default=1, comment="Minimum order quantity (MOQ)")
	uom = Column(String(20), nullable=False, default="EA")

	# Pricing — integer cents
	price_cents = Column(Integer, nullable=False, default=0, comment="Unit price in cents; NEVER float")
	currency_code = Column(String(3), nullable=False, default="USD")

	# Validity window
	valid_from = Column(Date, nullable=False, comment="Price/terms effective from this date")
	valid_to = Column(Date, nullable=True, comment="NULL = currently open / no expiry")

	is_preferred = Column(Boolean, nullable=False, default=False, comment="Preferred source for this product")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	supplier: Supplier = relationship("Supplier", back_populates="products", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<SupplierProduct supplier={self.supplier_id!r} product={self.product_id!r} "
			f"price={self.price_cents}¢ valid={self.valid_from!r}→{self.valid_to!r}>"
		)


# ---------------------------------------------------------------------------
# ShipmentTracking
# ---------------------------------------------------------------------------

class ShipmentTracking(AuditMixin, Model):
	"""In-transit shipment tracking record.

	Tracks a shipment from origin to destination warehouse with carrier
	and milestone events.

	events: JSONB array of milestone objects:
	  [{"ts": "ISO8601", "status": "DEPARTED_ORIGIN", "location": "Lagos Port", "note": "..."}, ...]

	Status machine:
	  IN_TRANSIT → DELIVERED | EXCEPTION | RETURNED

	IMMUTABLE NOTE: once status=DELIVERED, do not mutate shipment header.
	Append exception events to the events JSONB array instead.
	"""

	__allow_unmapped__ = True
	__tablename__ = "scm_shipment_tracking"
	__table_args__ = (
		Index("ix_scm_ship_tenant", "tenant_id"),
		Index("ix_scm_ship_supplier", "supplier_id"),
		Index("ix_scm_ship_status", "tenant_id", "status"),
		Index("ix_scm_ship_tracking", "carrier", "tracking_number"),
		Index("ix_scm_ship_eta", "estimated_arrival"),
		UniqueConstraint("tenant_id", "tracking_number", "carrier", name="uq_scm_ship_tenant_tracking"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Source document links (soft FKs)
	supplier_id = Column(UUID(as_uuid=False), ForeignKey("scm_supplier.id"), nullable=True, index=True)
	purchase_order_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to ap_purchase_order.id (soft)")
	shipment_reference = Column(String(100), nullable=True, comment="Internal shipment reference / ASN number")

	# Carrier info
	carrier = Column(String(100), nullable=False, comment="Carrier name e.g. DHL, FedEx, Maersk")
	tracking_number = Column(String(200), nullable=False, comment="Carrier tracking / bill of lading number")
	carrier_service = Column(String(100), nullable=True, comment="Service level e.g. EXPRESS, OCEAN_FCL")

	# Route
	origin_warehouse_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to warehouse (app-managed)")
	destination_warehouse_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to warehouse (app-managed)")
	origin_address = Column(JSONB, nullable=False, default=dict, comment="{city, country_code, port}")
	destination_address = Column(JSONB, nullable=False, default=dict, comment="{city, country_code, port}")

	# Timeline
	shipped_at = Column(DateTime(timezone=True), nullable=True, comment="Actual dispatch timestamp")
	estimated_arrival = Column(Date, nullable=True, comment="Carrier ETA")
	actual_arrival = Column(Date, nullable=True, comment="Date physically received at destination warehouse")

	# Status
	status = Column(
		String(15),
		nullable=False,
		default="IN_TRANSIT",
		comment="IN_TRANSIT | DELIVERED | EXCEPTION | RETURNED",
	)

	# Milestone event log — JSONB append-only array
	events: list[dict[str, Any]] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment='[{"ts":ISO8601, "status":"...", "location":"...", "note":"..."}]',
	)

	# Value & customs
	declared_value_cents = Column(Integer, nullable=True, comment="Customs declared value in cents")
	currency_code = Column(String(3), nullable=True)
	incoterms = Column(String(10), nullable=True, comment="e.g. FOB, CIF, DDP, EXW")

	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	supplier: Supplier | None = relationship("Supplier", back_populates="shipments", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<ShipmentTracking {self.carrier!r}/{self.tracking_number!r} "
			f"status={self.status!r} eta={self.estimated_arrival!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Supplier",
	"SupplierProduct",
	"ShipmentTracking",
]
