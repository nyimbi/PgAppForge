"""
pgappforge/plugins/erp/finance/hedge_accounting/models.py

IFRS 9 / ASC 815 Hedge Accounting models.

Design rules:
  - All PKs: UUID v4 via gen_random_uuid()
  - All monetary amounts: INTEGER cents — never float
  - All rates/ratios: NUMERIC(20,8)
  - Table prefix: erp_ha_

Key entities:
  HedgeRelationship    — formal hedge designation (IFRS 9 §6.4)
  HedgeEffectivenessTest — periodic effectiveness test results (§6.4.1)
  HedgeFairValueMovement — per-period fair value changes (OCI / P&L split)
  HedgeDisclosure        — IFRS 7 disclosure aggregation view data
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
# HedgeRelationship
# ---------------------------------------------------------------------------

class HedgeRelationship(RulesMixin, AuditMixin, Model):
	"""Formal hedge relationship designation per IFRS 9 Section 6.

	hedge_type:
	  FAIR_VALUE      — hedges changes in fair value of a recognised asset/liability
	  CASH_FLOW       — hedges variability in cash flows (e.g. floating rate debt)
	  NET_INVESTMENT  — hedges net investment in a foreign operation

	status:
	  DESIGNATED | EFFECTIVE | INEFFECTIVE | DISCONTINUED | EXPIRED

	Hedge object references are logical FKs — the hedging instrument and hedged
	item may reside in different ERP modules (FXDeal, Loan, Invoice, etc.).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_ha_relationship"
	__table_args__ = (
		UniqueConstraint("tenant_id", "hedge_reference", name="uq_erp_ha_rel_ref"),
		Index("ix_erp_ha_rel_tenant", "tenant_id"),
		Index("ix_erp_ha_rel_status", "status"),
		Index("ix_erp_ha_rel_type", "hedge_type"),
		{"extend_existing": True},
	)

	_rules_mutable_fields = frozenset({"status", "oci_balance_cents"})

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	hedge_reference = Column(String(50), nullable=False,
							 comment="Human-readable hedge ID e.g. HG-2026-00001")
	hedge_type = Column(String(20), nullable=False,
						comment="FAIR_VALUE | CASH_FLOW | NET_INVESTMENT")
	designation_date = Column(Date, nullable=False)
	maturity_date = Column(Date, nullable=True)

	# Hedging instrument (e.g. FX forward, interest rate swap)
	instrument_model = Column(String(100), nullable=False,
							  comment="Model name e.g. 'FXDeal', 'InterestRateSwap'")
	instrument_id = Column(UUID(as_uuid=False), nullable=False)
	instrument_notional_cents = Column(Integer, nullable=False)
	instrument_currency = Column(String(3), ForeignKey("erp_currency.code"), nullable=False)

	# Hedged item (e.g. forecast transaction, recognised liability)
	hedged_item_model = Column(String(100), nullable=False,
							   comment="Model name e.g. 'SalesInvoice', 'Loan'")
	hedged_item_id = Column(UUID(as_uuid=False), nullable=False)
	hedged_item_description = Column(String(500), nullable=True)
	hedged_risk = Column(String(100), nullable=False,
						 comment="E.g. FX_RISK, INTEREST_RATE_RISK, COMMODITY_PRICE_RISK")

	# Effectiveness parameters
	effectiveness_method = Column(String(30), nullable=False, default="DOLLAR_OFFSET",
								  comment="DOLLAR_OFFSET | REGRESSION | HYPOTHETICAL_DERIVATIVE")
	lower_bound = Column(Numeric(20, 8), nullable=False, default="0.8",
						 comment="Lower effectiveness threshold (typically 0.80)")
	upper_bound = Column(Numeric(20, 8), nullable=False, default="1.25",
						 comment="Upper effectiveness threshold (typically 1.25)")

	# Running balances
	cumulative_gain_loss_oci_cents = Column(Integer, nullable=False, default=0,
											comment="Cumulative OCI balance (Cash Flow hedges)")
	oci_balance_cents = Column(Integer, nullable=False, default=0,
							   comment="Current OCI reserve balance to be reclassified")
	ineffectiveness_pl_cents = Column(Integer, nullable=False, default=0,
									  comment="Cumulative ineffectiveness recognised in P&L")

	status = Column(String(20), nullable=False, default="DESIGNATED")
	discontinuation_date = Column(Date, nullable=True)
	discontinuation_reason = Column(Text, nullable=True)
	documentation = Column(Text, nullable=True,
						   comment="Hedge documentation narrative per IFRS 9 §6.4.1(b)")
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						onupdate=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	effectiveness_tests: list[HedgeEffectivenessTest] = relationship(
		"HedgeEffectivenessTest", back_populates="relationship",
		lazy="select", order_by="HedgeEffectivenessTest.test_date",
	)
	fair_value_movements: list[HedgeFairValueMovement] = relationship(
		"HedgeFairValueMovement", back_populates="relationship",
		lazy="select", order_by="HedgeFairValueMovement.valuation_date",
	)

	def __repr__(self) -> str:
		return (
			f"<HedgeRelationship {self.hedge_reference!r} "
			f"type={self.hedge_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# HedgeEffectivenessTest
# ---------------------------------------------------------------------------

class HedgeEffectivenessTest(AuditMixin, Model):
	"""Result of a hedge effectiveness test (prospective or retrospective).

	Per IFRS 9 §6.4.1(c): the hedge relationship must pass both a prospective
	assessment (going forward) and a retrospective quantitative test each period.

	ratio = change_in_hedging_instrument / change_in_hedged_item
	Effective range: 0.80 ≤ ratio ≤ 1.25 (dollar-offset method).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_ha_effectiveness_test"
	__table_args__ = (
		Index("ix_erp_ha_eff_relationship", "relationship_id"),
		Index("ix_erp_ha_eff_date", "test_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	relationship_id = Column(UUID(as_uuid=False),
							 ForeignKey("erp_ha_relationship.id", ondelete="RESTRICT"),
							 nullable=False)
	test_date = Column(Date, nullable=False)
	test_type = Column(String(20), nullable=False, comment="PROSPECTIVE | RETROSPECTIVE")
	change_in_instrument_cents = Column(Integer, nullable=False,
										comment="Fair value change in hedging instrument")
	change_in_hedged_item_cents = Column(Integer, nullable=False,
										 comment="Fair value change in hedged item (hypothetical)")
	effectiveness_ratio = Column(Numeric(20, 8), nullable=False,
								 comment="ratio = instrument_change / hedged_item_change")
	is_effective = Column(Boolean, nullable=False)
	effective_portion_cents = Column(Integer, nullable=False, default=0,
									 comment="Portion recognised in OCI")
	ineffective_portion_cents = Column(Integer, nullable=False, default=0,
									   comment="Portion recognised immediately in P&L")
	test_method = Column(String(30), nullable=False, default="DOLLAR_OFFSET")
	notes = Column(Text, nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	relationship: HedgeRelationship = relationship(
		"HedgeRelationship", back_populates="effectiveness_tests", lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<HedgeEffectivenessTest rel={self.relationship_id!r} "
			f"date={self.test_date!r} effective={self.is_effective!r} "
			f"ratio={self.effectiveness_ratio!r}>"
		)


# ---------------------------------------------------------------------------
# HedgeFairValueMovement
# ---------------------------------------------------------------------------

class HedgeFairValueMovement(Model):
	"""Per-period fair value movement on a hedge relationship.

	Captures the split between OCI (effective portion) and P&L (ineffectiveness).
	Immutable — each period creates a new row.

	For Fair Value hedges: both instrument and hedged item changes go to P&L.
	For Cash Flow hedges:  effective portion → OCI; ineffective → P&L.
	For Net Investment:    effective portion → OCI translation reserve.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_ha_fair_value_movement"
	__table_args__ = (
		Index("ix_erp_ha_fvm_relationship", "relationship_id"),
		Index("ix_erp_ha_fvm_date", "valuation_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	relationship_id = Column(UUID(as_uuid=False),
							 ForeignKey("erp_ha_relationship.id", ondelete="RESTRICT"),
							 nullable=False)
	valuation_date = Column(Date, nullable=False)
	instrument_fair_value_cents = Column(Integer, nullable=False,
										 comment="Current fair value of hedging instrument")
	instrument_change_cents = Column(Integer, nullable=False,
									 comment="Period change in instrument fair value")
	oci_movement_cents = Column(Integer, nullable=False, default=0,
								comment="OCI credit/(debit) this period (effective portion)")
	pl_movement_cents = Column(Integer, nullable=False, default=0,
							   comment="P&L charge/(income) this period (ineffective + FV hedges)")
	cumulative_oci_cents = Column(Integer, nullable=False, default=0,
								  comment="Running OCI reserve at this date")
	reclassified_to_pl_cents = Column(Integer, nullable=False, default=0,
									  comment="OCI reclassified to P&L this period")
	gl_journal_id = Column(UUID(as_uuid=False), nullable=True)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	relationship: HedgeRelationship = relationship(
		"HedgeRelationship", back_populates="fair_value_movements", lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<HedgeFairValueMovement rel={self.relationship_id!r} "
			f"date={self.valuation_date!r} oci={self.oci_movement_cents} "
			f"pl={self.pl_movement_cents}>"
		)


__all__ = [
	"HedgeRelationship",
	"HedgeEffectivenessTest",
	"HedgeFairValueMovement",
]
