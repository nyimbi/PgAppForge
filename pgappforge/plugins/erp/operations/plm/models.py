"""
pgappforge/plugins/erp/operations/plm/models.py

SQLAlchemy 2.x models for the Product Lifecycle Management (PLM) plugin.

Design invariants:
  - ALL PKs: UUID(as_uuid=False) — gen_random_uuid() server default + Python default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - JSONB for BOM items and ECO attachments
  - Composite indexes for tenant + status hot paths
  - Table prefix: plm_
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
# PlmProduct
# ---------------------------------------------------------------------------

class PlmProduct(AuditMixin, Model):
	"""Master product record in the PLM system.

	lifecycle_stage:
	  CONCEPT → DEVELOPMENT → PILOT → PRODUCTION → EOL

	current_version: denormalised from the latest RELEASED PlmProductVersion.
	"""

	__allow_unmapped__ = True
	__tablename__ = "plm_product"
	__table_args__ = (
		UniqueConstraint("tenant_id", "product_code", name="uq_plm_product_tenant_code"),
		Index("ix_plm_product_tenant_stage", "tenant_id", "lifecycle_stage"),
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
	product_code = Column(String(100), nullable=False, comment="Unique per tenant")
	description = Column(Text, nullable=True)
	category = Column(String(100), nullable=True)
	lifecycle_stage = Column(String(30), nullable=False, default="CONCEPT")
	current_version = Column(String(20), nullable=True)
	created_by = Column(String(50), nullable=True)
	entity_id = Column(String(50), nullable=True, comment="Cross-plugin entity reference")

	# Stores stage-gate log and other metadata:
	# {"stage_gates": [{"gate": "...", "passed_at": "...", "approved_by": "..."}]}
	metadata_ = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="'{}'::jsonb",
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

	versions: list[PlmProductVersion] = relationship(
		"PlmProductVersion",
		back_populates="product",
		lazy="select",
		cascade="all, delete-orphan",
	)
	boms: list[BillOfMaterials] = relationship(
		"BillOfMaterials",
		back_populates="product",
		lazy="select",
		cascade="all, delete-orphan",
	)
	ecos: list[EngineeringChangeOrder] = relationship(
		"EngineeringChangeOrder",
		back_populates="product",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<PlmProduct {self.product_code!r} {self.name!r} [{self.lifecycle_stage}]>"


# ---------------------------------------------------------------------------
# PlmProductVersion
# ---------------------------------------------------------------------------

class PlmProductVersion(AuditMixin, Model):
	"""Versioned snapshot of a PlmProduct.

	status: DRAFT → REVIEW → APPROVED → RELEASED → OBSOLETE
	version_type: MAJOR | MINOR | PATCH
	"""

	__allow_unmapped__ = True
	__tablename__ = "plm_version"
	__table_args__ = (
		UniqueConstraint("product_id", "version_number", name="uq_plm_version_product_num"),
		Index("ix_plm_version_product", "product_id"),
		Index("ix_plm_version_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("plm_product.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	version_number = Column(String(20), nullable=False)
	version_type = Column(String(20), nullable=False, default="MINOR")
	status = Column(String(20), nullable=False, default="DRAFT")
	changes = Column(Text, nullable=True)
	approved_by = Column(String(50), nullable=True)
	released_at = Column(DateTime(timezone=True), nullable=True)

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

	product: PlmProduct = relationship(
		"PlmProduct",
		back_populates="versions",
		lazy="select",
	)
	boms: list[BillOfMaterials] = relationship(
		"BillOfMaterials",
		back_populates="version",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<PlmProductVersion {self.version_number!r} [{self.status}] product={self.product_id}>"


# ---------------------------------------------------------------------------
# BillOfMaterials
# ---------------------------------------------------------------------------

class BillOfMaterials(AuditMixin, Model):
	"""Bill of materials for a specific product version.

	status: DRAFT → REVIEW → RELEASED → OBSOLETE

	items: [{component_id, component_name, quantity, unit, notes}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "plm_bom"
	__table_args__ = (
		Index("ix_plm_bom_product", "product_id"),
		Index("ix_plm_bom_version", "version_id"),
		Index("ix_plm_bom_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("plm_product.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	version_id = Column(
		UUID(as_uuid=False),
		ForeignKey("plm_version.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	version_number = Column(Integer, nullable=False, default=1, comment="BOM revision counter")
	status = Column(String(20), nullable=False, default="DRAFT")

	items = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="'[]'::jsonb",
		comment="[{component_id, component_name, quantity, unit, notes}]",
	)

	effective_from = Column(Date, nullable=True)
	released_by = Column(String(50), nullable=True)

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

	product: PlmProduct = relationship(
		"PlmProduct",
		back_populates="boms",
		lazy="select",
	)
	version: PlmProductVersion = relationship(
		"PlmProductVersion",
		back_populates="boms",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<BillOfMaterials product={self.product_id} v{self.version_number} [{self.status}]>"


# ---------------------------------------------------------------------------
# EngineeringChangeOrder
# ---------------------------------------------------------------------------

class EngineeringChangeOrder(AuditMixin, Model):
	"""Engineering Change Order (ECO) tracking proposed or approved product changes.

	eco_type: DEFECT_FIX | DESIGN_CHANGE | COST_REDUCTION | SAFETY | REGULATORY
	priority: LOW | MEDIUM | HIGH | CRITICAL
	status: DRAFT → SUBMITTED → REVIEW → APPROVED | REJECTED → IMPLEMENTED
	"""

	__allow_unmapped__ = True
	__tablename__ = "plm_eco"
	__table_args__ = (
		Index("ix_plm_eco_product_status", "product_id", "status"),
		Index("ix_plm_eco_tenant_status", "tenant_id", "status"),
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
	description = Column(Text, nullable=False)

	product_id = Column(
		UUID(as_uuid=False),
		ForeignKey("plm_product.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	current_version_id = Column(
		UUID(as_uuid=False),
		ForeignKey("plm_version.id"),
		nullable=True,
		index=True,
	)

	eco_type = Column(String(30), nullable=False)
	priority = Column(String(20), nullable=False, default="MEDIUM")
	status = Column(String(20), nullable=False, default="DRAFT")

	submitted_by = Column(String(50), nullable=True)
	approved_by = Column(String(50), nullable=True)
	implemented_at = Column(DateTime(timezone=True), nullable=True)

	attachments = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="'[]'::jsonb",
		comment="[{filename, url, uploaded_at}]",
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

	product: PlmProduct = relationship(
		"PlmProduct",
		back_populates="ecos",
		lazy="select",
	)
	current_version: PlmProductVersion | None = relationship(
		"PlmProductVersion",
		foreign_keys=[current_version_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<EngineeringChangeOrder {self.title!r} [{self.status}] product={self.product_id}>"


__all__ = [
	"PlmProduct",
	"PlmProductVersion",
	"BillOfMaterials",
	"EngineeringChangeOrder",
]
