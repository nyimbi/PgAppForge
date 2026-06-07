"""
pgappforge/plugins/erp/finance/product_costing/models.py

SQLAlchemy models for the Product Costing plugin.

Design rules enforced:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - Every model: tenant_id UUID NOT NULL
  - Monetary amounts: BigInteger cents ONLY — never Numeric/float for money
  - AuditMixin on all mutable entities
  - PostgreSQL-only: JSONB, UUID, gen_random_uuid()

Table name convention: cst_<entity>
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Version type / status constants (VARCHAR CHECK — no SA Enum, PG-only)
# ---------------------------------------------------------------------------

VERSION_TYPES = ("STANDARD", "PLANNED", "ACTUAL")
VERSION_STATUSES = ("DRAFT", "ACTIVE", "HISTORICAL")
ELEMENT_TYPES = ("MATERIAL", "LABOR", "OVERHEAD", "SUBCONTRACTING", "SETUP")


# ---------------------------------------------------------------------------
# CostVersion
# ---------------------------------------------------------------------------

class CostVersion(AuditMixin, Model):
	"""Cost version header — groups cost elements for one product/period.

	A product may have multiple versions (STANDARD, PLANNED, ACTUAL).
	Only one ACTIVE standard version per product at any time — enforced by
	ProductCostingService.release_standard_cost().

	status transitions: DRAFT → ACTIVE → HISTORICAL
	"""

	__allow_unmapped__ = True
	__tablename__ = "cst_version"
	__table_args__ = (
		Index("ix_cst_version_tenant_product_type", "tenant_id", "product_id", "version_type"),
		Index("ix_cst_version_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Soft FK — product lives in inventory/production domain
	product_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK to inventory/production product; no DB-level FK to allow domain decoupling",
	)
	version_type = Column(
		String(20),
		nullable=False,
		comment="STANDARD | PLANNED | ACTUAL",
	)
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT | ACTIVE | HISTORICAL",
	)
	currency_code = Column(String(3), nullable=False, default="USD", server_default="USD")

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

	elements: list[CostElement] = relationship(
		"CostElement",
		back_populates="version",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CostVersion product={self.product_id!r} type={self.version_type!r} "
			f"status={self.status!r} id={self.id!r}>"
		)


# ---------------------------------------------------------------------------
# CostElement
# ---------------------------------------------------------------------------

class CostElement(AuditMixin, Model):
	"""One cost element within a CostVersion.

	total_cost_cents = round(quantity * unit_cost_cents).
	Stored explicitly for immutability and audit; recomputed by service on add.

	For OVERHEAD element_type: overhead_rate is the % of direct costs (material+labor).
	source_component_id links to a BOM component or work center (soft FK).
	"""

	__allow_unmapped__ = True
	__tablename__ = "cst_element"
	__table_args__ = (
		Index("ix_cst_element_version_type", "version_id", "element_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	version_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cst_version.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	element_type = Column(
		String(30),
		nullable=False,
		comment="MATERIAL | LABOR | OVERHEAD | SUBCONTRACTING | SETUP",
	)
	description = Column(String(200), nullable=False)
	quantity = Column(Numeric(15, 4), nullable=False, default=1, server_default="1")
	unit_cost_cents = Column(
		BigInteger,
		nullable=False,
		comment="Cost per unit in cents — integer only",
	)
	total_cost_cents = Column(
		BigInteger,
		nullable=False,
		comment="quantity * unit_cost_cents, rounded — stored for immutability",
	)
	# Soft FK — BOM component or work center
	source_component_id = Column(
		String(50),
		nullable=True,
		comment="Soft FK to BOM component or work center; null for manually entered elements",
	)
	# Only populated for OVERHEAD elements
	overhead_rate = Column(
		Numeric(8, 4),
		nullable=True,
		comment="OVERHEAD only: percentage of direct costs (e.g. 15.5000 = 15.5%)",
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

	version: CostVersion = relationship("CostVersion", back_populates="elements", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<CostElement type={self.element_type!r} desc={self.description!r} "
			f"total={self.total_cost_cents}¢>"
		)


# ---------------------------------------------------------------------------
# ProductStandardCost
# ---------------------------------------------------------------------------

class ProductStandardCost(AuditMixin, Model):
	"""Published standard cost for a product at a given effective date.

	Created/updated by ProductCostingService.rollup_standard_cost().
	One row per (tenant_id, product_id, effective_from) — unique constraint.
	Historical rows are never deleted; new effective dates add new rows.

	material_cost_cents + labor_cost_cents + overhead_cost_cents == total_standard_cost_cents
	(enforced by service, not DB — allows rounding tolerance).
	"""

	__allow_unmapped__ = True
	__tablename__ = "cst_standard"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "product_id", "effective_from",
			name="uq_cst_standard_tenant_product_date",
		),
		Index("ix_cst_standard_tenant_product", "tenant_id", "product_id"),
		Index("ix_cst_standard_tenant_date", "tenant_id", "effective_from"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	product_id = Column(String(50), nullable=False, index=True)
	effective_from = Column(Date, nullable=False)

	# Component buckets — integer cents
	material_cost_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	labor_cost_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	overhead_cost_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	total_standard_cost_cents = Column(
		BigInteger,
		nullable=False,
		comment="Sum of all element buckets; authoritative standard cost",
	)
	currency_code = Column(String(3), nullable=False, default="USD", server_default="USD")

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
			f"<ProductStandardCost product={self.product_id!r} "
			f"from={self.effective_from!r} total={self.total_standard_cost_cents}¢>"
		)


# ---------------------------------------------------------------------------
# ProductionOrderActualCost
# ---------------------------------------------------------------------------

class ProductionOrderActualCost(AuditMixin, Model):
	"""Actual cost record for a completed production order.

	total_variance_cents = total_actual_cents - total_standard_cents
	Positive variance = actual exceeded standard (unfavourable).
	Negative variance = actual below standard (favourable).

	price_variance and qty_variance are sub-components of total_variance:
	  price_variance_cents = (actual_unit_cost - std_unit_cost) * actual_qty
	  qty_variance_cents   = (actual_qty - std_qty) * std_unit_cost

	One record per production order per tenant (unique on production_order_id + tenant_id).
	"""

	__allow_unmapped__ = True
	__tablename__ = "cst_actual"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "production_order_id",
			name="uq_cst_actual_tenant_order",
		),
		Index("ix_cst_actual_tenant_product_period", "tenant_id", "product_id", "period"),
		Index("ix_cst_actual_order", "production_order_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	production_order_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK to production order; unique per tenant",
	)
	product_id = Column(String(50), nullable=False, index=True)
	period = Column(String(20), nullable=False, comment="e.g. 2026-06 or 2026-Q2")

	# Actual cost buckets — integer cents
	material_actual_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	labor_actual_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	overhead_actual_cents = Column(BigInteger, nullable=False, default=0, server_default="0")
	total_actual_cents = Column(BigInteger, nullable=False, comment="Sum of actual buckets")

	# Standard cost (snapshot at computation time)
	total_standard_cents = Column(
		BigInteger,
		nullable=False,
		comment="Standard cost snapshot at time of computation",
	)

	# Variance analysis — all cents, signed
	total_variance_cents = Column(
		BigInteger,
		nullable=False,
		comment="actual - standard; positive = unfavourable",
	)
	price_variance_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="(actual_unit - std_unit) * actual_qty",
	)
	qty_variance_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="(actual_qty - std_qty) * std_unit_cost",
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
			f"<ProductionOrderActualCost order={self.production_order_id!r} "
			f"actual={self.total_actual_cents}¢ variance={self.total_variance_cents:+d}¢>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"CostVersion",
	"CostElement",
	"ProductStandardCost",
	"ProductionOrderActualCost",
]
