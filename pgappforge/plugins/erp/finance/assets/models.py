"""
pgappforge/plugins/erp/finance/assets/models.py

Asset Accounting (AA) models.

Design rules:
  - All PKs: UUID v4 via gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All monetary amounts: INTEGER cents — never float
  - All models: tenant_id UUID NOT NULL + AuditMixin
  - Financial records: IMMUTABLE — INSERT correction entries only, NEVER UPDATE
  - lazy='select' throughout (SA 2.x removed lazy='dynamic')
  - JSONB for semi-structured metadata
  - Table name convention: erp_aa_<entity>

Depreciation methods:
  STRAIGHT_LINE:  (cost - residual) / useful_life
  DECLINING:      book_value * (2 / useful_life)   [double-declining balance]
  UNITS_OF_PRODUCTION: (cost - residual) / expected_units * actual_units
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
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.rules.mixin import RulesMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# AssetClass
# ---------------------------------------------------------------------------

class AssetClass(AuditMixin, Model):
	"""Asset classification with depreciation policy.

	Defines the accounting treatment for a category of fixed assets.
	GL account references are string codes pointing to the GL chart of accounts.

	Depreciation methods:
	  STRAIGHT_LINE        — equal charges over useful life
	  DECLINING            — double-declining balance (2/N * NBV)
	  UNITS_OF_PRODUCTION  — charge per unit of output (requires units tracking)
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_aa_asset_class"
	__table_args__ = (
		UniqueConstraint("tenant_id", "code", name="uq_erp_aa_asset_class_tenant_code"),
		Index("ix_erp_aa_asset_class_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	code = Column(String(20), nullable=False, comment="e.g. BLDG, MACH, FURN, VEHICLE")
	name = Column(String(200), nullable=False)
	useful_life_years = Column(
		Numeric(5, 2),
		nullable=False,
		comment="Default useful life for assets in this class",
	)
	depreciation_method = Column(
		String(30),
		nullable=False,
		default="STRAIGHT_LINE",
		comment="STRAIGHT_LINE | DECLINING | UNITS_OF_PRODUCTION",
	)
	gl_asset_account = Column(
		String(50),
		nullable=False,
		comment="GL account for asset cost (debit on capitalise)",
	)
	gl_accumulated_depreciation_account = Column(
		String(50),
		nullable=False,
		comment="GL contra-asset account for accumulated depreciation",
	)
	gl_depreciation_expense_account = Column(
		String(50),
		nullable=False,
		comment="GL P&L account for depreciation charge",
	)
	gl_disposal_gain_account = Column(
		String(50),
		nullable=True,
		comment="GL account for disposal gain (credit)",
	)
	gl_disposal_loss_account = Column(
		String(50),
		nullable=True,
		comment="GL account for disposal loss (debit)",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	metadata_: dict[str, Any] = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
	)

	# Relationships
	assets: list[FixedAsset] = relationship(
		"FixedAsset",
		back_populates="asset_class",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<AssetClass {self.code!r} {self.name!r} method={self.depreciation_method!r}>"


# ---------------------------------------------------------------------------
# FixedAsset
# ---------------------------------------------------------------------------

class FixedAsset(RulesMixin, AuditMixin, Model):
	"""Fixed asset register entry.

	Immutable ledger note: book_value fields are updated by depreciation runs,
	but individual depreciation charges are recorded in AssetDepreciation
	(append-only). Disposal and impairment are also separate immutable records.

	Status lifecycle:
	  ACTIVE → (depreciation runs) → FULLY_DEPRECIATED
	  ACTIVE → IMPAIRED → ACTIVE (after recoverable reassessment)
	  ACTIVE | IMPAIRED | FULLY_DEPRECIATED → DISPOSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_aa_fixed_asset"
	__table_args__ = (
		UniqueConstraint("tenant_id", "asset_number", name="uq_erp_aa_fixed_asset_number"),
		Index("ix_erp_aa_fixed_asset_tenant", "tenant_id"),
		Index("ix_erp_aa_fixed_asset_class", "asset_class_id"),
		Index("ix_erp_aa_fixed_asset_status", "status"),
		Index("ix_erp_aa_fixed_asset_custodian", "custodian_id"),
		{"extend_existing": True},
	)

	_rules_mutable_fields = frozenset({
		"status", "location", "custodian_id", "description",
	})
	__rules_context_fields__ = ["asset_class.depreciation_method"]

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	asset_number = Column(
		String(50),
		nullable=False,
		comment="Unique human-readable asset identifier e.g. FA-2026-00001",
	)
	asset_class_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_aa_asset_class.id", ondelete="RESTRICT"),
		nullable=False,
	)
	description = Column(String(500), nullable=False)
	acquisition_date = Column(Date, nullable=False)
	acquisition_cost_cents = Column(
		Integer,
		nullable=False,
		comment="Original cost in minor currency units (cents/kobo)",
	)
	residual_value_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Estimated salvage value at end of useful life",
	)
	useful_life_years = Column(
		Numeric(5, 2),
		nullable=False,
		comment="Asset-specific useful life (may differ from class default)",
	)
	depreciation_method = Column(
		String(30),
		nullable=False,
		default="STRAIGHT_LINE",
		comment="Inherited from AssetClass but can be overridden per asset",
	)
	current_book_value_cents = Column(
		Integer,
		nullable=False,
		comment="Net Book Value = cost - accumulated depreciation - impairment",
	)
	accumulated_depreciation_cents = Column(
		Integer,
		nullable=False,
		default=0,
	)
	location = Column(String(200), nullable=True, comment="Physical location / branch")
	custodian_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="FK to erp_party.id — party responsible for the asset",
	)
	serial_number = Column(String(100), nullable=True)
	status = Column(
		String(25),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | DISPOSED | IMPAIRED | FULLY_DEPRECIATED",
	)
	last_depreciation_date = Column(Date, nullable=True)
	disposal_date = Column(Date, nullable=True)
	disposal_proceeds_cents = Column(Integer, nullable=True)
	disposal_gain_loss_cents = Column(
		Integer,
		nullable=True,
		comment="Positive = gain, negative = loss on disposal",
	)
	# Units-of-production tracking
	expected_total_units = Column(
		Integer,
		nullable=True,
		comment="Required when depreciation_method = UNITS_OF_PRODUCTION",
	)
	notes = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
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
	asset_class: AssetClass = relationship(
		"AssetClass",
		back_populates="assets",
		lazy="select",
	)
	depreciation_entries: list[AssetDepreciation] = relationship(
		"AssetDepreciation",
		back_populates="asset",
		lazy="select",
		order_by="AssetDepreciation.period_id",
	)
	impairments: list[AssetImpairment] = relationship(
		"AssetImpairment",
		back_populates="asset",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<FixedAsset {self.asset_number!r} class={self.asset_class_id!r} "
			f"nbv={self.current_book_value_cents} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# AssetDepreciation  (IMMUTABLE — append-only)
# ---------------------------------------------------------------------------

class AssetDepreciation(AuditMixin, Model):
	"""Depreciation charge for one period.

	CRITICAL: NEVER UPDATE rows. Each depreciation run inserts a new row.
	Corrections are handled by inserting a reversal entry (negative amount)
	followed by the corrected entry.

	period_id references erp_accounting_period.id from the GL plugin, or can
	be a string like "2026-01" when GL plugin is not loaded.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_aa_asset_depreciation"
	__table_args__ = (
		UniqueConstraint(
			"asset_id", "period_id",
			name="uq_erp_aa_depreciation_asset_period",
		),
		Index("ix_erp_aa_depreciation_asset", "asset_id"),
		Index("ix_erp_aa_depreciation_period", "period_id"),
		Index("ix_erp_aa_depreciation_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_aa_fixed_asset.id", ondelete="RESTRICT"),
		nullable=False,
	)
	period_id = Column(
		String(20),
		nullable=False,
		comment="Accounting period identifier e.g. '2026-01'",
	)
	depreciation_amount_cents = Column(
		Integer,
		nullable=False,
		comment="Charge for this period. Negative = reversal/correction.",
	)
	opening_nbv_cents = Column(
		Integer,
		nullable=False,
		comment="Net Book Value at start of period",
	)
	closing_nbv_cents = Column(
		Integer,
		nullable=False,
		comment="Net Book Value at end of period after this charge",
	)
	method_used = Column(
		String(30),
		nullable=False,
		comment="Method applied for this run (snapshot in case class changes)",
	)
	units_consumed = Column(
		Integer,
		nullable=True,
		comment="Units produced this period (UNITS_OF_PRODUCTION only)",
	)
	posted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	asset: FixedAsset = relationship(
		"FixedAsset",
		back_populates="depreciation_entries",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AssetDepreciation asset={self.asset_id!r} period={self.period_id!r} "
			f"amount={self.depreciation_amount_cents}>"
		)


# ---------------------------------------------------------------------------
# AssetImpairment
# ---------------------------------------------------------------------------

class AssetImpairment(AuditMixin, Model):
	"""IAS 36 impairment loss record.

	When the recoverable amount of an asset falls below its carrying amount
	(NBV), an impairment loss is recognised. This record is immutable —
	subsequent reversals are new rows with is_reversal=True.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_aa_asset_impairment"
	__table_args__ = (
		Index("ix_erp_aa_impairment_asset", "asset_id"),
		Index("ix_erp_aa_impairment_date", "impairment_date"),
		Index("ix_erp_aa_impairment_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	asset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_aa_fixed_asset.id", ondelete="RESTRICT"),
		nullable=False,
	)
	impairment_date = Column(Date, nullable=False)
	carrying_amount_cents = Column(
		Integer,
		nullable=False,
		comment="NBV immediately before impairment",
	)
	recoverable_amount_cents = Column(
		Integer,
		nullable=False,
		comment="Higher of fair value less costs to sell and value in use",
	)
	impairment_loss_cents = Column(
		Integer,
		nullable=False,
		comment="carrying_amount - recoverable_amount (always >= 0)",
	)
	reason = Column(Text, nullable=False, comment="IAS 36 impairment trigger description")
	is_reversal = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True = IAS 36 impairment reversal",
	)
	reversal_of_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_aa_asset_impairment.id", ondelete="SET NULL"),
		nullable=True,
	)
	posted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	asset: FixedAsset = relationship(
		"FixedAsset",
		back_populates="impairments",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<AssetImpairment asset={self.asset_id!r} date={self.impairment_date!r} "
			f"loss={self.impairment_loss_cents}>"
		)


__all__ = [
	"AssetClass",
	"FixedAsset",
	"AssetDepreciation",
	"AssetImpairment",
]
