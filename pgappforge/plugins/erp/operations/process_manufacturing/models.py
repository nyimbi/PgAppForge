"""
pgappforge/plugins/erp/operations/process_manufacturing/models.py

SQLAlchemy models for the Process Manufacturing plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - ALL monetary amounts: BigInteger cents (NEVER Numeric/float for money)
  - ALL models: tenant_id VARCHAR(50) NOT NULL (soft UUID — cross-plugin safe)
  - Soft FKs only across plugin boundaries (VARCHAR, no DB-level FK constraint)
  - PostgreSQL: JSONB, TIMESTAMPTZ, Numeric(15,4) for quantities
  - AuditMixin on every mutable entity

Table prefix: prm_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------

class Recipe(AuditMixin, Model):
	"""Process manufacturing recipe / formula.

	Lifecycle: DRAFT → UNDER_REVIEW → APPROVED → OBSOLETE

	A recipe defines the expected batch size, yield percentage, process parameters
	(pH, temperature, time), and the list of ingredients required to produce one
	batch of a given product.

	product_id is a soft FK to inv_product.id.
	entity_id is optional multi-entity scoping.
	"""

	__allow_unmapped__ = True
	__tablename__ = "prm_recipe"
	__table_args__ = (
		UniqueConstraint("tenant_id", "product_id", "version", name="uq_prm_recipe_tenant_product_version"),
		Index("ix_prm_recipe_tenant_product_status", "tenant_id", "product_id", "status"),
		CheckConstraint(
			"status IN ('DRAFT','UNDER_REVIEW','APPROVED','OBSOLETE')",
			name="ck_prm_recipe_status",
		),
		CheckConstraint(
			"batch_size_unit IN ('KG','L','UNITS','MT')",
			name="ck_prm_recipe_batch_size_unit",
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

	product_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK → inv_product.id: the product this recipe produces",
	)
	version = Column(
		String(20),
		nullable=False,
		default="1.0",
		comment="Recipe version string e.g. '1.0', '2.1'",
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | UNDER_REVIEW | APPROVED | OBSOLETE",
	)

	# Batch parameters
	batch_size = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Expected batch size in batch_size_unit",
	)
	batch_size_unit = Column(
		String(20),
		nullable=False,
		comment="KG | L | UNITS | MT",
	)
	yield_pct = Column(
		Numeric(6, 4),
		nullable=False,
		default=sa.text("1.0"),
		comment="Expected yield fraction e.g. 0.95 = 95%",
	)

	# Process parameters (nullable — not all processes have pH/temperature constraints)
	ph_min = Column(Numeric(6, 3), nullable=True, comment="Minimum acceptable pH")
	ph_max = Column(Numeric(6, 3), nullable=True, comment="Maximum acceptable pH")
	temp_min_celsius = Column(Numeric(6, 2), nullable=True, comment="Minimum process temperature °C")
	temp_max_celsius = Column(Numeric(6, 2), nullable=True, comment="Maximum process temperature °C")
	process_time_minutes = Column(Integer, nullable=True, comment="Expected process duration in minutes")

	instructions = Column(Text, nullable=True, comment="Step-by-step process instructions")

	# Approval tracking
	approved_by = Column(String(50), nullable=True, comment="User ID who approved this recipe")
	approved_at = Column(DateTime(timezone=True), nullable=True, comment="Approval timestamp")

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
	ingredients: list[RecipeIngredient] = relationship(
		"RecipeIngredient",
		back_populates="recipe",
		cascade="all, delete-orphan",
		lazy="select",
	)
	batch_records: list[BatchRecord] = relationship(
		"BatchRecord",
		back_populates="recipe",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Recipe id={self.id!r} product={self.product_id!r} "
			f"version={self.version!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# RecipeIngredient
# ---------------------------------------------------------------------------

class RecipeIngredient(AuditMixin, Model):
	"""Ingredient (input material) line within a process manufacturing recipe.

	ingredient_product_id is a soft FK to inv_product.id.
	substitutes is a JSONB list of alternative product_ids.
	"""

	__allow_unmapped__ = True
	__tablename__ = "prm_ingredient"
	__table_args__ = (
		Index("ix_prm_ingredient_recipe_product", "recipe_id", "ingredient_product_id"),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	recipe_id = Column(
		String(50),
		ForeignKey("prm_recipe.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
		comment="Parent recipe",
	)
	ingredient_product_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK → inv_product.id: input material",
	)

	quantity = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Required quantity per batch in unit",
	)
	unit = Column(String(20), nullable=False, comment="Unit of measure e.g. KG, L, UNITS")
	is_critical = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True if this ingredient cannot be substituted or omitted",
	)
	substitutes = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default=sa.text("'[]'::jsonb"),
		comment="List of alternative ingredient_product_ids",
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
	recipe: Recipe = relationship(
		"Recipe",
		back_populates="ingredients",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RecipeIngredient recipe={self.recipe_id!r} "
			f"product={self.ingredient_product_id!r} qty={self.quantity} unit={self.unit!r}>"
		)


# ---------------------------------------------------------------------------
# BatchRecord
# ---------------------------------------------------------------------------

class BatchRecord(AuditMixin, Model):
	"""Production batch record tracking actual execution of a recipe.

	Lifecycle: PLANNED → IN_PROCESS → COMPLETED | REJECTED

	actual_ingredients: JSONB list of {product_id, planned_qty, actual_qty, variance}
	quality_checks:     JSONB list of {parameter, min_value, max_value, actual_value, passed}

	production_order_id is a soft FK to any production order system.
	operator_id is a soft FK to user/employee registry.
	"""

	__allow_unmapped__ = True
	__tablename__ = "prm_batch_record"
	__table_args__ = (
		Index("ix_prm_batch_recipe_status", "recipe_id", "status"),
		Index("ix_prm_batch_tenant_status_started", "tenant_id", "status", "started_at"),
		CheckConstraint(
			"status IN ('PLANNED','IN_PROCESS','COMPLETED','REJECTED')",
			name="ck_prm_batch_status",
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

	recipe_id = Column(
		String(50),
		ForeignKey("prm_recipe.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
		comment="Recipe used for this batch",
	)
	batch_number = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Unique batch identifier per tenant",
	)
	production_order_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Soft FK to production order system",
	)

	# Quantities
	planned_quantity = Column(
		Numeric(15, 4),
		nullable=False,
		comment="Planned output quantity for this batch",
	)
	actual_yield = Column(
		Numeric(15, 4),
		nullable=True,
		comment="Actual output quantity after completion",
	)
	yield_variance_pct = Column(
		Numeric(8, 4),
		nullable=True,
		comment="(actual_yield - planned_quantity) / planned_quantity × 100",
	)

	# Operational tracking
	operator_id = Column(String(50), nullable=True, comment="Soft FK to operator/employee")
	started_at = Column(DateTime(timezone=True), nullable=True, comment="Batch start timestamp")
	completed_at = Column(DateTime(timezone=True), nullable=True, comment="Batch completion timestamp")
	status = Column(
		String(20),
		nullable=False,
		default="PLANNED",
		comment="PLANNED | IN_PROCESS | COMPLETED | REJECTED",
	)

	# Execution details stored as JSONB
	actual_ingredients = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default=sa.text("'[]'::jsonb"),
		comment="[{product_id, planned_qty, actual_qty, variance}]",
	)
	quality_checks = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default=sa.text("'[]'::jsonb"),
		comment="[{parameter, min_value, max_value, actual_value, passed}]",
	)

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

	# Relationships
	recipe: Recipe = relationship(
		"Recipe",
		back_populates="batch_records",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<BatchRecord id={self.id!r} batch={self.batch_number!r} "
			f"recipe={self.recipe_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Recipe",
	"RecipeIngredient",
	"BatchRecord",
]
