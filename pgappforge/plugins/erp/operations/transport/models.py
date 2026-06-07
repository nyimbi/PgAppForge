"""
pgappforge/plugins/erp/operations/transport/models.py

SQLAlchemy 2.x models for the Transport Management plugin.

Design invariants:
  - ALL PKs: UUID(as_uuid=False) — gen_random_uuid() server default + Python default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - Monetary amounts: BigInteger cents (never Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - Table prefix: trn_
  - JSONB for arrays/maps (PostgreSQL only)
  - Composite indexes for tenant + status hot paths
  - FKs within plugin are hard constraints; cross-plugin refs are advisory UUIDs

Carrier types: ROAD / AIR / SEA / RAIL / COURIER
Rate types: PER_KG / FLAT / PER_UNIT / PER_CBM
Shipment statuses: PLANNED / BOOKED / DISPATCHED / IN_TRANSIT / DELIVERED / CANCELLED
Source document types: SALES_ORDER / PURCHASE_ORDER / TRANSFER
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	CheckConstraint,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
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

CARRIER_TYPES = {"ROAD", "AIR", "SEA", "RAIL", "COURIER"}
RATE_TYPES = {"PER_KG", "FLAT", "PER_UNIT", "PER_CBM"}
SHIPMENT_STATUSES = {"PLANNED", "BOOKED", "DISPATCHED", "IN_TRANSIT", "DELIVERED", "CANCELLED"}
SOURCE_DOC_TYPES = {"SALES_ORDER", "PURCHASE_ORDER", "TRANSFER"}


# ---------------------------------------------------------------------------
# Carrier
# ---------------------------------------------------------------------------

class Carrier(AuditMixin, Model):
	"""Carrier (shipping company) register.

	code is unique per tenant — used as a human-readable identifier.
	on_time_delivery_rate_pct is recomputed by TransportService.update_carrier_performance().
	preferred_routes is a JSONB array of {origin_zone, destination_zone} pairs.
	"""

	__allow_unmapped__ = True
	__tablename__ = "trn_carrier"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_trn_carrier_tenant_code"),
		CheckConstraint(
			"carrier_type IN ('ROAD','AIR','SEA','RAIL','COURIER')",
			name="ck_trn_carrier_type",
		),
		Index("ix_trn_carrier_tenant_type_active", "tenant_id", "carrier_type", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(String(200), nullable=False)
	code = Column(String(50), nullable=False, comment="Human-readable carrier code, unique per tenant")
	carrier_type = Column(String(30), nullable=False, default="ROAD")
	contact_email = Column(String(320), nullable=True)
	contact_phone = Column(String(30), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)
	on_time_delivery_rate_pct = Column(
		Numeric(6, 2), nullable=False, default=100,
		comment="Rolling on-time delivery rate 0-100",
	)
	avg_damage_rate_pct = Column(
		Numeric(6, 2), nullable=False, default=0,
		comment="Rolling average damage rate 0-100",
	)
	preferred_routes = Column(
		JSONB, nullable=False,
		server_default=sa.text("'[]'::jsonb"),
		default=list,
		comment="[{origin_zone, destination_zone}]",
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

	rates: list[FreightRate] = relationship(
		"FreightRate", back_populates="carrier", lazy="select", cascade="all, delete-orphan"
	)
	shipments: list[Shipment] = relationship(
		"Shipment", back_populates="carrier", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<Carrier {self.code} [{self.carrier_type}] active={self.is_active}>"


# ---------------------------------------------------------------------------
# FreightRate
# ---------------------------------------------------------------------------

class FreightRate(AuditMixin, Model):
	"""Rate card entry for a carrier on a given origin→destination zone pair.

	weight_kg_max=None means "no upper limit" (catch-all bracket).
	rate_cents meaning depends on rate_type:
	  PER_KG   — cents per kg of gross weight
	  FLAT     — fixed cents for this zone pair regardless of weight
	  PER_UNIT — cents per unit / carton
	  PER_CBM  — cents per cubic metre
	effective_to=None means "currently active".
	"""

	__allow_unmapped__ = True
	__tablename__ = "trn_rate"
	__table_args__ = (
		CheckConstraint(
			"rate_type IN ('PER_KG','FLAT','PER_UNIT','PER_CBM')",
			name="ck_trn_rate_type",
		),
		Index("ix_trn_rate_carrier_zones", "carrier_id", "origin_zone", "destination_zone"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	carrier_id = Column(
		UUID(as_uuid=False),
		ForeignKey("trn_carrier.id", ondelete="CASCADE"),
		nullable=False,
	)

	origin_zone = Column(String(100), nullable=False)
	destination_zone = Column(String(100), nullable=False)
	weight_kg_min = Column(Numeric(10, 2), nullable=False, default=0)
	weight_kg_max = Column(Numeric(10, 2), nullable=True, comment="NULL = no upper limit")
	rate_type = Column(String(20), nullable=False, default="PER_KG")
	rate_cents = Column(BigInteger, nullable=False, comment="Rate in integer cents; semantic depends on rate_type")
	currency_code = Column(String(3), nullable=False, default="USD")
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True, comment="NULL = currently active")

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

	carrier: Carrier = relationship("Carrier", back_populates="rates", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<FreightRate carrier={self.carrier_id} "
			f"{self.origin_zone}→{self.destination_zone} "
			f"{self.rate_type} {self.rate_cents}¢>"
		)


# ---------------------------------------------------------------------------
# Shipment
# ---------------------------------------------------------------------------

class Shipment(AuditMixin, Model):
	"""One shipment movement from origin to destination.

	shipment_ref is unique per tenant — auto-generated as SHP-YYYYMMDD-NNNNN.
	tracking_events is a JSONB array of {timestamp, location, status, notes} dicts.
	carrier_id uses SET NULL on delete — a shipment survives carrier deletion.
	freight_cost_cents is populated by book_carrier() via compute_freight().
	pod_ref stores the proof-of-delivery reference number.
	"""

	__allow_unmapped__ = True
	__tablename__ = "trn_shipment"
	__table_args__ = (
		UniqueConstraint("tenant_id", "shipment_ref", name="uq_trn_shipment_tenant_ref"),
		CheckConstraint(
			"status IN ('PLANNED','BOOKED','DISPATCHED','IN_TRANSIT','DELIVERED','CANCELLED')",
			name="ck_trn_shipment_status",
		),
		CheckConstraint(
			"source_document_type IN ('SALES_ORDER','PURCHASE_ORDER','TRANSFER')",
			name="ck_trn_shipment_src_doc_type",
		),
		Index("ix_trn_shipment_carrier_status", "carrier_id", "status"),
		Index("ix_trn_shipment_tenant_status_date", "tenant_id", "status", "planned_delivery_date"),
		Index("ix_trn_shipment_source_doc", "source_document_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	shipment_ref = Column(String(50), nullable=False, comment="Auto-generated, unique per tenant")
	source_document_type = Column(String(30), nullable=True)
	source_document_id = Column(String(50), nullable=True, index=True)

	carrier_id = Column(
		UUID(as_uuid=False),
		ForeignKey("trn_carrier.id", ondelete="SET NULL"),
		nullable=True,
	)

	origin_address = Column(Text, nullable=False)
	destination_address = Column(Text, nullable=False)
	origin_zone = Column(String(100), nullable=True)
	destination_zone = Column(String(100), nullable=True)

	status = Column(String(20), nullable=False, default="PLANNED")
	weight_kg = Column(Numeric(10, 2), nullable=True)
	volume_cbm = Column(Numeric(10, 2), nullable=True)
	freight_cost_cents = Column(BigInteger, nullable=False, default=0)
	currency_code = Column(String(3), nullable=False, default="USD")

	planned_dispatch_date = Column(Date, nullable=True)
	actual_dispatch_at = Column(DateTime(timezone=True), nullable=True)
	planned_delivery_date = Column(Date, nullable=True)
	actual_delivery_at = Column(DateTime(timezone=True), nullable=True)

	driver_id = Column(String(50), nullable=True, comment="Advisory ref to fleet_driver.id or HR employee")
	vehicle_id = Column(String(50), nullable=True, comment="Advisory ref to fleet_vehicle.id")
	pod_ref = Column(String(100), nullable=True, comment="Proof of delivery reference number")

	tracking_events = Column(
		JSONB, nullable=False,
		server_default=sa.text("'[]'::jsonb"),
		default=list,
		comment="[{timestamp, location, status, notes}]",
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

	carrier: Carrier | None = relationship("Carrier", back_populates="shipments", lazy="select")

	def __repr__(self) -> str:
		return f"<Shipment {self.shipment_ref} [{self.status}] carrier={self.carrier_id}>"


__all__ = [
	"Carrier",
	"FreightRate",
	"Shipment",
	# enum sets
	"CARRIER_TYPES",
	"RATE_TYPES",
	"SHIPMENT_STATUSES",
	"SOURCE_DOC_TYPES",
]
