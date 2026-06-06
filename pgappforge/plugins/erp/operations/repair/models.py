"""
pgappforge/plugins/erp/operations/repair/models.py

SQLAlchemy 2.x models for the Repair / RMA plugin.

Design invariants:
  - ALL PKs: UUID(as_uuid=False) — gen_random_uuid() server default + Python default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - Monetary amounts: Integer cents (never Numeric/float for money)
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - JSONB for semi-structured fields (parts_used)
  - Composite indexes for tenant + status hot paths
  - Table prefix: rpr_
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
# RepairOrder
# ---------------------------------------------------------------------------

class RepairOrder(AuditMixin, Model):
	"""Central record tracking a product through the repair/RMA lifecycle.

	status transitions (governed by RepairService):
	  RECEIVED → DIAGNOSING → AWAITING_PARTS → IN_REPAIR → QC
	           → READY_FOR_PICKUP → RETURNED | CANCELLED

	parts_used: [{part_name, quantity, unit_cost_cents}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "rpr_order"
	__table_args__ = (
		UniqueConstraint("tenant_id", "order_ref", name="uq_rpr_order_tenant_ref"),
		Index("ix_rpr_order_tenant_status", "tenant_id", "status"),
		Index("ix_rpr_order_tech_status", "assigned_technician_id", "status"),
		Index("ix_rpr_order_customer", "customer_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	order_ref = Column(String(50), nullable=False, comment="Unique repair reference per tenant")

	# Customer
	customer_id = Column(String(50), nullable=True, index=True)
	customer_name = Column(String(200), nullable=False)
	customer_email = Column(String(320), nullable=True)
	customer_phone = Column(String(30), nullable=True)

	# Product
	product_name = Column(String(300), nullable=False)
	serial_number = Column(String(200), nullable=True)
	problem_description = Column(Text, nullable=False)

	# Workflow
	status = Column(String(30), nullable=False, default="RECEIVED")
	assigned_technician_id = Column(String(50), nullable=True, index=True)

	# Diagnosis
	diagnosis = Column(Text, nullable=True)
	diagnosis_at = Column(DateTime(timezone=True), nullable=True)
	estimated_cost_cents = Column(Integer, nullable=True)
	actual_cost_cents = Column(Integer, nullable=True)

	# Warranty
	warranty_applicable = Column(Boolean, nullable=False, default=False)
	under_warranty = Column(Boolean, nullable=False, default=False)

	# Parts consumed during repair
	parts_used = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="'[]'::jsonb",
		comment="[{part_name, quantity, unit_cost_cents}]",
	)

	# Dates
	received_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	promised_by = Column(Date, nullable=True)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	returned_at = Column(DateTime(timezone=True), nullable=True)

	notes = Column(Text, nullable=True)
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

	warranty_claims: list[WarrantyClaim] = relationship(
		"WarrantyClaim",
		back_populates="repair_order",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<RepairOrder {self.order_ref!r} [{self.status}] product={self.product_name!r}>"


# ---------------------------------------------------------------------------
# WarrantyClaim
# ---------------------------------------------------------------------------

class WarrantyClaim(AuditMixin, Model):
	"""Warranty claim linked (optionally) to a RepairOrder.

	status: OPEN → APPROVED | REJECTED → REPAIRED | REPLACED → CLOSED
	resolution_type: REPAIRED | REPLACED | REFUNDED | REJECTED
	"""

	__allow_unmapped__ = True
	__tablename__ = "rpr_warranty"
	__table_args__ = (
		Index("ix_rpr_warranty_tenant_status", "tenant_id", "status"),
		Index("ix_rpr_warranty_serial", "serial_number"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	repair_order_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rpr_order.id", ondelete="CASCADE"),
		nullable=True,
		index=True,
	)

	product_name = Column(String(300), nullable=False)
	serial_number = Column(String(200), nullable=True)
	customer_name = Column(String(200), nullable=False)
	customer_email = Column(String(320), nullable=True)

	purchase_date = Column(Date, nullable=True)
	warranty_expiry_date = Column(Date, nullable=True)
	claim_description = Column(Text, nullable=False)

	status = Column(String(20), nullable=False, default="OPEN")
	resolution_type = Column(String(30), nullable=True)
	resolution_notes = Column(Text, nullable=True)
	resolved_at = Column(DateTime(timezone=True), nullable=True)

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

	repair_order: RepairOrder | None = relationship(
		"RepairOrder",
		back_populates="warranty_claims",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<WarrantyClaim {self.id!r} [{self.status}] product={self.product_name!r}>"


__all__ = [
	"RepairOrder",
	"WarrantyClaim",
]
