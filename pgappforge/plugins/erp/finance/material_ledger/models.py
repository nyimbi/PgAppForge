"""
pgappforge/plugins/erp/finance/material_ledger/models.py

Material Ledger / Actual Costing models (SAP ML-equivalent).

Design rules:
  - All PKs: UUID v4 via gen_random_uuid()
  - All monetary amounts: INTEGER cents — never float
  - All rates/quantities: NUMERIC(20,8)
  - Table prefix: erp_ml_

Key entities:
  CostingPeriod      — fiscal period for which actual costs are settled
  MaterialLedger     — per-material, per-plant, per-period cost accumulation
  MaterialMovement   — individual stock movement with preliminary/actual price
  CostSettlement     — multi-level actual cost settlement run result
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
# CostingPeriod
# ---------------------------------------------------------------------------

class CostingPeriod(AuditMixin, Model):
	"""Fiscal costing period for a plant.

	status:
	  OPEN    — accepting postings
	  CLOSING — settlement run in progress
	  CLOSED  — actual costs settled; no further postings

	One period per (tenant_id, plant_id, fiscal_year, period_number).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_ml_costing_period"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "plant_id", "fiscal_year", "period_number",
			name="uq_erp_ml_costing_period",
		),
		Index("ix_erp_ml_cp_tenant", "tenant_id"),
		Index("ix_erp_ml_cp_plant", "plant_id"),
		Index("ix_erp_ml_cp_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	plant_id = Column(String(20), nullable=False, comment="Plant / valuation area code")
	fiscal_year = Column(Integer, nullable=False)
	period_number = Column(Integer, nullable=False, comment="1–12 (or 1–13 for 4-4-5)")
	period_start = Column(Date, nullable=False)
	period_end = Column(Date, nullable=False)
	status = Column(String(10), nullable=False, default="OPEN",
					comment="OPEN | CLOSING | CLOSED")
	closed_at = Column(DateTime(timezone=True), nullable=True)
	closed_by = Column(String(100), nullable=True)
	notes = Column(Text, nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	ledger_entries: list[MaterialLedger] = relationship(
		"MaterialLedger", back_populates="period",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CostingPeriod plant={self.plant_id!r} "
			f"FY{self.fiscal_year}P{self.period_number} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# MaterialLedger
# ---------------------------------------------------------------------------

class MaterialLedger(AuditMixin, Model):
	"""Per-material, per-plant accumulation of actual costs for one period.

	The material ledger tracks:
	  - Preliminary valuation (at standard price) for all movements
	  - Price variances from purchasing and production
	  - Exchange-rate differences for foreign-currency purchases
	  - Multi-level variance absorption from upstream cost objects

	After period close, actual_price_cents is computed and the balance
	sheet inventory is revalued if the actual price differs from standard.

	costing_status:
	  OPEN        — period open; accumulating
	  SETTLED     — actual price determined; inventory revalued
	  LOCKED      — prior period, read-only
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_ml_material_ledger"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "material_id", "plant_id", "period_id",
			name="uq_erp_ml_ledger_material_period",
		),
		Index("ix_erp_ml_ml_tenant", "tenant_id"),
		Index("ix_erp_ml_ml_material", "material_id"),
		Index("ix_erp_ml_ml_plant", "plant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	material_id = Column(String(50), nullable=False, comment="Material / SKU code")
	plant_id = Column(String(20), nullable=False)
	period_id = Column(UUID(as_uuid=False),
					   ForeignKey("erp_ml_costing_period.id", ondelete="RESTRICT"),
					   nullable=False)
	currency_code = Column(String(3), ForeignKey("erp_currency.code"), nullable=False)

	# Opening balances
	opening_qty = Column(Numeric(20, 8), nullable=False, default=0)
	opening_value_cents = Column(Integer, nullable=False, default=0)
	standard_price_cents = Column(Integer, nullable=False,
								  comment="Standard price per unit in cents (from cost estimate)")

	# Receipts (inbound movements)
	receipts_qty = Column(Numeric(20, 8), nullable=False, default=0)
	receipts_value_cents = Column(Integer, nullable=False, default=0)

	# Issues (outbound movements)
	issues_qty = Column(Numeric(20, 8), nullable=False, default=0)
	issues_value_cents = Column(Integer, nullable=False, default=0)

	# Variance accumulation
	purchase_price_variance_cents = Column(Integer, nullable=False, default=0,
										   comment="PPV: actual invoice price - PO price")
	exchange_rate_difference_cents = Column(Integer, nullable=False, default=0,
											comment="FX difference on foreign-currency purchases")
	production_variance_cents = Column(Integer, nullable=False, default=0,
									   comment="Variance from production order settlement")
	multilevel_variance_cents = Column(Integer, nullable=False, default=0,
									   comment="Absorbed from upstream materials / cost centres")

	# Closing / actual
	closing_qty = Column(Numeric(20, 8), nullable=False, default=0)
	closing_value_cents = Column(Integer, nullable=False, default=0)
	actual_price_cents = Column(Integer, nullable=True,
								comment="Computed at period close: total cost / total qty")
	revaluation_cents = Column(Integer, nullable=True,
							   comment="Inventory revaluation posted at period close")

	costing_status = Column(String(10), nullable=False, default="OPEN",
							comment="OPEN | SETTLED | LOCKED")
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						onupdate=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	period: CostingPeriod = relationship(
		"CostingPeriod", back_populates="ledger_entries", lazy="select",
	)
	movements: list[MaterialMovement] = relationship(
		"MaterialMovement", back_populates="ledger",
		lazy="select", order_by="MaterialMovement.posting_date",
	)

	def __repr__(self) -> str:
		return (
			f"<MaterialLedger material={self.material_id!r} plant={self.plant_id!r} "
			f"period={self.period_id!r} status={self.costing_status!r}>"
		)


# ---------------------------------------------------------------------------
# MaterialMovement
# ---------------------------------------------------------------------------

class MaterialMovement(Model):
	"""Individual stock movement contributing to the material ledger.

	Each goods receipt, goods issue, transfer, or production confirmation
	creates one row. preliminary_value_cents is posted at standard price;
	actual_value_cents is determined at period close during settlement.

	movement_type follows SAP/standard ERP convention:
	  101 GR purchase order       501 GI to production order
	  102 GR reversal             502 GI reversal
	  201 GI to cost centre       261 GI for production order
	  311 Transfer posting        ...

	variance_type:
	  PURCHASE | EXCHANGE_RATE | PRODUCTION | NONE
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_ml_movement"
	__table_args__ = (
		Index("ix_erp_ml_mov_ledger", "ledger_id"),
		Index("ix_erp_ml_mov_date", "posting_date"),
		Index("ix_erp_ml_mov_type", "movement_type"),
		Index("ix_erp_ml_mov_document", "source_document_type", "source_document_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	ledger_id = Column(UUID(as_uuid=False),
					   ForeignKey("erp_ml_material_ledger.id", ondelete="RESTRICT"),
					   nullable=False)
	posting_date = Column(Date, nullable=False)
	movement_type = Column(String(10), nullable=False)
	quantity = Column(Numeric(20, 8), nullable=False)
	unit_of_measure = Column(String(10), nullable=False, default="EA")
	preliminary_value_cents = Column(Integer, nullable=False,
									 comment="Quantity × standard_price (at time of posting)")
	actual_value_cents = Column(Integer, nullable=True,
								comment="Set at period close during settlement run")
	variance_cents = Column(Integer, nullable=True,
							comment="actual - preliminary; populated post-settlement")
	variance_type = Column(String(20), nullable=True,
						   comment="PURCHASE | EXCHANGE_RATE | PRODUCTION | NONE")
	source_document_type = Column(String(50), nullable=True,
								  comment="E.g. PurchaseOrder, ProductionOrder, StockTransfer")
	source_document_id = Column(String(64), nullable=True)
	is_reversal = Column(Boolean, nullable=False, default=False)
	reversal_of_id = Column(UUID(as_uuid=False), nullable=True,
							comment="FK to the original movement being reversed")
	posting_reference = Column(String(100), nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	ledger: MaterialLedger = relationship(
		"MaterialLedger", back_populates="movements", lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<MaterialMovement type={self.movement_type!r} "
			f"qty={self.quantity} prelim={self.preliminary_value_cents} "
			f"date={self.posting_date!r}>"
		)


# ---------------------------------------------------------------------------
# CostSettlement  (settlement run result — one row per run)
# ---------------------------------------------------------------------------

class CostSettlement(AuditMixin, Model):
	"""Result of a multi-level actual cost settlement run.

	Settlement processes materials from lowest to highest BOM level,
	absorbing upstream variances into downstream materials and cost objects.

	status:
	  PENDING | RUNNING | COMPLETED | FAILED
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_ml_cost_settlement"
	__table_args__ = (
		Index("ix_erp_ml_cs_period", "period_id"),
		Index("ix_erp_ml_cs_plant", "plant_id"),
		Index("ix_erp_ml_cs_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	period_id = Column(UUID(as_uuid=False),
					   ForeignKey("erp_ml_costing_period.id", ondelete="RESTRICT"),
					   nullable=False)
	plant_id = Column(String(20), nullable=False)
	run_at = Column(DateTime(timezone=True), nullable=False,
					default=lambda: datetime.now(timezone.utc))
	run_by = Column(String(100), nullable=True)
	status = Column(String(20), nullable=False, default="PENDING",
					comment="PENDING | RUNNING | COMPLETED | FAILED")
	levels_processed = Column(Integer, nullable=False, default=0)
	materials_processed = Column(Integer, nullable=False, default=0)
	total_variance_cents = Column(Integer, nullable=False, default=0)
	error_log: list[dict] = Column(JSONB, nullable=False, default=list)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<CostSettlement period={self.period_id!r} plant={self.plant_id!r} "
			f"status={self.status!r} materials={self.materials_processed}>"
		)


__all__ = [
	"CostingPeriod",
	"MaterialLedger",
	"MaterialMovement",
	"CostSettlement",
]
