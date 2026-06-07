"""
pgappforge/plugins/erp/operations/assembly/models.py

SQLAlchemy models for the Assembly Management plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - ALL monetary amounts: BigInteger cents (NEVER Numeric/float for money)
  - ALL models: tenant_id VARCHAR(50) NOT NULL (soft UUID — cross-plugin safe)
  - Soft FKs only across plugin boundaries (VARCHAR, no DB-level FK constraint)
  - PostgreSQL: JSONB, TIMESTAMPTZ, Numeric(15,4) for quantities
  - AuditMixin on every mutable entity

Table prefix: asm_
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
)
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# AssemblyOrder
# ---------------------------------------------------------------------------

class AssemblyOrder(AuditMixin, Model):
	"""Assembly production order: consume components → produce finished goods.

	Lifecycle: DRAFT → IN_PROGRESS → POSTED | CANCELLED

	standard_cost_cents  — planned cost: sum(planned_qty × unit_cost) across all lines.
	actual_cost_cents    — real cost after posting: sum of consumed quantities × weighted avg cost.
	variance_cents       — actual_cost_cents - standard_cost_cents; posted to GL account 5990.

	warehouse_id is a soft FK to inv_warehouse.id (VARCHAR cross-plugin reference).
	output_product_id is a soft FK to inv_product.id.
	entity_id is optional multi-entity/IC scoping.
	"""

	__allow_unmapped__ = True
	__tablename__ = "asm_order"
	__table_args__ = (
		Index("ix_asm_order_tenant_status", "tenant_id", "status"),
		Index("ix_asm_order_tenant_product", "tenant_id", "output_product_id"),
		CheckConstraint(
			"status IN ('DRAFT','IN_PROGRESS','POSTED','CANCELLED')",
			name="ck_asm_order_status",
		),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	# Product and warehouse — soft FKs (cross-plugin, VARCHAR)
	output_product_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK → inv_product.id: the finished good being assembled",
	)
	output_qty = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Expected quantity of finished goods to produce",
	)
	warehouse_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK → inv_warehouse.id: production warehouse",
	)

	# Lifecycle
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | IN_PROGRESS | POSTED | CANCELLED",
	)
	planned_date = Column(Date, nullable=True, comment="Planned production date")
	posted_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when order was posted (status=POSTED)",
	)

	# Cost accounting — all cents (BigInteger)
	standard_cost_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Expected total component cost: sum(planned_qty × unit_cost_cents)",
	)
	actual_cost_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Actual total cost after posting: sum of consumed costs",
	)
	variance_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="actual_cost_cents - standard_cost_cents; posted to GL 5990 when nonzero",
	)

	notes = Column(Text, nullable=True)
	entity_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Multi-entity scoping; soft FK to entity registry",
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

	# Relationships
	lines: list[AssemblyLine] = relationship(
		"AssemblyLine",
		back_populates="order",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AssemblyOrder id={self.id!r} product={self.output_product_id!r} "
			f"qty={self.output_qty} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# AssemblyLine
# ---------------------------------------------------------------------------

class AssemblyLine(AuditMixin, Model):
	"""Bill-of-materials component line for an AssemblyOrder.

	planned_qty    — quantity specified at order creation (BOM qty).
	actual_qty     — quantity actually consumed during posting; NULL until posted.
	unit_cost_cents — unit cost at time of line creation (from product master or override).
	total_cost_cents — actual_qty × unit_cost_cents (or weighted avg), set on posting.

	component_product_id is a soft FK to inv_product.id.
	"""

	__allow_unmapped__ = True
	__tablename__ = "asm_line"
	__table_args__ = (
		Index("ix_asm_line_order_component", "order_id", "component_product_id"),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	order_id = Column(
		String(50),
		ForeignKey("asm_order.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
		comment="Parent assembly order",
	)
	component_product_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK → inv_product.id: component to consume",
	)

	# Quantities — Numeric(15,4) for fractional UOMs
	planned_qty = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Quantity planned per BOM at order creation",
	)
	actual_qty = Column(
		Numeric(15, 4),
		nullable=True,
		comment="Quantity actually consumed during posting; NULL until posted",
	)

	# Costing — BigInteger cents
	unit_cost_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Unit cost at order creation; may be overridden by weighted avg at post time",
	)
	total_cost_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="actual_qty × effective_unit_cost; set during posting",
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

	# Relationships
	order: AssemblyOrder = relationship(
		"AssemblyOrder",
		back_populates="lines",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AssemblyLine order={self.order_id!r} component={self.component_product_id!r} "
			f"planned={self.planned_qty} actual={self.actual_qty}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"AssemblyOrder",
	"AssemblyLine",
]
