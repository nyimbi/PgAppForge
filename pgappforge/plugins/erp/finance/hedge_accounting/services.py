"""
pgappforge/plugins/erp/finance/hedge_accounting/services.py

HedgeAccountingService — IFRS 9 / ASC 815 hedge accounting business logic.

All monetary amounts in integer cents. Decimal arithmetic for ratios. No float.

Public API
----------
  designate_hedge(details, session)              -> HedgeRelationship
  run_effectiveness_test(relationship_id, test_date, session) -> HedgeEffectivenessTest
  record_fair_value_movement(relationship_id, valuation_date,
      instrument_fv_cents, session)              -> HedgeFairValueMovement
  reclassify_oci_to_pl(relationship_id, amount_cents, reason, session) -> HedgeFairValueMovement
  discontinue_hedge(relationship_id, date, reason, session) -> HedgeRelationship
  get_hedge_summary(relationship_id, session)    -> dict
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class HedgeAccountingError(Exception):
	"""Base hedge accounting error."""


class HedgeNotFoundError(HedgeAccountingError):
	pass


class HedgeStatusError(HedgeAccountingError):
	pass


class HedgeIneffectiveError(HedgeAccountingError):
	pass


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------

@dataclass
class HedgeDesignationDetails:
	tenant_id: str
	hedge_type: str                     # FAIR_VALUE | CASH_FLOW | NET_INVESTMENT
	instrument_model: str               # e.g. "FXDeal"
	instrument_id: str
	instrument_notional_cents: int
	instrument_currency: str
	hedged_item_model: str              # e.g. "SalesInvoice"
	hedged_item_id: str
	hedged_risk: str                    # e.g. "FX_RISK"
	designation_date: date
	hedge_reference: str | None = None
	maturity_date: date | None = None
	effectiveness_method: str = "DOLLAR_OFFSET"
	lower_bound: Decimal = Decimal("0.80")
	upper_bound: Decimal = Decimal("1.25")
	hedged_item_description: str | None = None
	documentation: str | None = None
	metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# HedgeAccountingService
# ---------------------------------------------------------------------------

class HedgeAccountingService:
	"""Stateless IFRS 9 / ASC 815 hedge accounting service.

	Caller owns session transactions.
	"""

	# ------------------------------------------------------------------ #
	# Designation
	# ------------------------------------------------------------------ #

	def designate_hedge(
		self, details: HedgeDesignationDetails, session: Any
	) -> Any:
		"""Formally designate a hedge relationship per IFRS 9 §6.4.1.

		Creates HedgeRelationship in DESIGNATED status.
		Emits HedgeRelationshipDesignatedEvent.
		"""
		from pgappforge.plugins.erp.finance.hedge_accounting.models import HedgeRelationship
		from pgappforge.plugins.erp.finance.hedge_accounting.events import (
			HedgeRelationshipDesignatedEvent, emit_event,
		)

		assert details.hedge_type in ("FAIR_VALUE", "CASH_FLOW", "NET_INVESTMENT"), \
			f"invalid hedge_type: {details.hedge_type!r}"
		assert details.instrument_notional_cents > 0, "notional must be positive"

		ref = details.hedge_reference or self._generate_hedge_reference(session)

		rel = HedgeRelationship(
			tenant_id=details.tenant_id,
			hedge_reference=ref,
			hedge_type=details.hedge_type,
			designation_date=details.designation_date,
			maturity_date=details.maturity_date,
			instrument_model=details.instrument_model,
			instrument_id=details.instrument_id,
			instrument_notional_cents=details.instrument_notional_cents,
			instrument_currency=details.instrument_currency.upper(),
			hedged_item_model=details.hedged_item_model,
			hedged_item_id=details.hedged_item_id,
			hedged_item_description=details.hedged_item_description,
			hedged_risk=details.hedged_risk,
			effectiveness_method=details.effectiveness_method,
			lower_bound=details.lower_bound,
			upper_bound=details.upper_bound,
			cumulative_gain_loss_oci_cents=0,
			oci_balance_cents=0,
			ineffectiveness_pl_cents=0,
			status="DESIGNATED",
			documentation=details.documentation,
			metadata_=details.metadata or {},
		)
		session.add(rel)
		session.flush()

		emit_event(
			HedgeRelationshipDesignatedEvent(
				aggregate_id=rel.id,
				aggregate_type="HedgeRelationship",
				tenant_id=details.tenant_id,
				relationship_id=rel.id,
				hedge_reference=ref,
				hedge_type=details.hedge_type,
				hedging_instrument_id=details.instrument_id,
				hedged_item_id=details.hedged_item_id,
				designation_date=str(details.designation_date),
			),
			session,
		)
		log.info("Hedge designated %r type=%s", ref, details.hedge_type)
		return rel

	# ------------------------------------------------------------------ #
	# Effectiveness testing
	# ------------------------------------------------------------------ #

	def run_effectiveness_test(
		self,
		relationship_id: str,
		test_date: date,
		session: Any,
		*,
		test_type: str = "RETROSPECTIVE",
		change_in_instrument_cents: int,
		change_in_hedged_item_cents: int,
	) -> Any:
		"""Run a hedge effectiveness test (dollar-offset method).

		ratio = |change_in_instrument| / |change_in_hedged_item|
		Effective if lower_bound ≤ ratio ≤ upper_bound.

		For effective hedges:
		  effective_portion   = min(|instrument_change|, |hedged_item_change|) × sign
		  ineffective_portion = remainder → recognised in P&L immediately.

		Emits EffectivenessTestedEvent. Returns HedgeEffectivenessTest.
		"""
		from pgappforge.plugins.erp.finance.hedge_accounting.models import (
			HedgeRelationship, HedgeEffectivenessTest,
		)
		from pgappforge.plugins.erp.finance.hedge_accounting.events import (
			EffectivenessTestedEvent, emit_event,
		)

		rel = session.get(HedgeRelationship, relationship_id)
		if rel is None:
			raise HedgeNotFoundError(f"HedgeRelationship {relationship_id!r} not found")
		if rel.status == "DISCONTINUED":
			raise HedgeStatusError(
				f"Hedge {rel.hedge_reference!r} is discontinued"
			)

		# Dollar-offset ratio
		denom = abs(change_in_hedged_item_cents)
		if denom == 0:
			ratio = Decimal("0")
		else:
			ratio = (
				Decimal(str(abs(change_in_instrument_cents)))
				/ Decimal(str(denom))
			).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

		lower = Decimal(str(rel.lower_bound))
		upper = Decimal(str(rel.upper_bound))
		is_effective = lower <= ratio <= upper

		# Split effective / ineffective portions
		if is_effective:
			eff_portion = min(abs(change_in_instrument_cents), denom)
			# Preserve sign: OCI should follow instrument direction
			sign = 1 if change_in_instrument_cents >= 0 else -1
			effective_cents = eff_portion * sign
			ineffective_cents = change_in_instrument_cents - effective_cents
		else:
			effective_cents = 0
			ineffective_cents = change_in_instrument_cents

		# Update relationship status
		rel.status = "EFFECTIVE" if is_effective else "INEFFECTIVE"
		rel.ineffectiveness_pl_cents += ineffective_cents
		rel.updated_at = datetime.now(timezone.utc)

		test = HedgeEffectivenessTest(
			tenant_id=rel.tenant_id,
			relationship_id=relationship_id,
			test_date=test_date,
			test_type=test_type,
			change_in_instrument_cents=change_in_instrument_cents,
			change_in_hedged_item_cents=change_in_hedged_item_cents,
			effectiveness_ratio=ratio,
			is_effective=is_effective,
			effective_portion_cents=effective_cents,
			ineffective_portion_cents=ineffective_cents,
			test_method=rel.effectiveness_method,
		)
		session.add(test)
		session.flush()

		emit_event(
			EffectivenessTestedEvent(
				aggregate_id=relationship_id,
				aggregate_type="HedgeRelationship",
				tenant_id=rel.tenant_id,
				relationship_id=relationship_id,
				hedge_reference=rel.hedge_reference,
				test_date=str(test_date),
				test_type=test_type,
				effectiveness_ratio=str(ratio),
				is_effective=is_effective,
			),
			session,
		)
		log.info(
			"Effectiveness test %r date=%s type=%s ratio=%s effective=%s",
			rel.hedge_reference, test_date, test_type, ratio, is_effective,
		)
		return test

	# ------------------------------------------------------------------ #
	# Fair value movement recording
	# ------------------------------------------------------------------ #

	def record_fair_value_movement(
		self,
		relationship_id: str,
		valuation_date: date,
		instrument_fair_value_cents: int,
		session: Any,
	) -> Any:
		"""Record period fair value movement and OCI/P&L split.

		For CASH_FLOW hedges: effective portion → OCI; ineffective → P&L.
		For FAIR_VALUE hedges: all instrument changes → P&L (plus hedged item adjustment).
		For NET_INVESTMENT hedges: effective portion → OCI translation reserve.

		Emits HedgeMtmUpdatedEvent. Returns HedgeFairValueMovement.
		"""
		from pgappforge.plugins.erp.finance.hedge_accounting.models import (
			HedgeRelationship, HedgeFairValueMovement,
		)
		from pgappforge.plugins.erp.finance.hedge_accounting.events import (
			HedgeMtmUpdatedEvent, emit_event,
		)

		rel = session.get(HedgeRelationship, relationship_id)
		if rel is None:
			raise HedgeNotFoundError(f"HedgeRelationship {relationship_id!r} not found")

		# Get previous FV to compute period change
		prev_fv_row = session.execute(
			sa.select(HedgeFairValueMovement)
			.where(HedgeFairValueMovement.relationship_id == relationship_id)
			.order_by(sa.desc(HedgeFairValueMovement.valuation_date))
			.limit(1)
		).scalar_one_or_none()

		prev_fv = prev_fv_row.instrument_fair_value_cents if prev_fv_row else 0
		prev_cumulative_oci = prev_fv_row.cumulative_oci_cents if prev_fv_row else 0
		period_change = instrument_fair_value_cents - prev_fv

		# Split based on hedge type
		if rel.hedge_type == "FAIR_VALUE":
			oci_movement = 0
			pl_movement = period_change
			effective_portion = 0
			ineffective_portion = period_change
		else:
			# CASH_FLOW or NET_INVESTMENT: use latest effectiveness test ratio
			latest_test = session.execute(
				sa.select(HedgeFairValueMovement)
				.where(HedgeFairValueMovement.relationship_id == relationship_id)
				.order_by(sa.desc(HedgeFairValueMovement.valuation_date))
				.limit(1)
			).scalar_one_or_none()

			# Simplified: route 100% to OCI if effective, else split
			if rel.status == "EFFECTIVE":
				oci_movement = period_change
				pl_movement = 0
			else:
				# Ineffective: route all to P&L
				oci_movement = 0
				pl_movement = period_change

			effective_portion = oci_movement
			ineffective_portion = pl_movement

		new_cumulative_oci = prev_cumulative_oci + oci_movement
		rel.cumulative_gain_loss_oci_cents += oci_movement
		rel.oci_balance_cents = new_cumulative_oci
		rel.updated_at = datetime.now(timezone.utc)

		movement = HedgeFairValueMovement(
			relationship_id=relationship_id,
			valuation_date=valuation_date,
			instrument_fair_value_cents=instrument_fair_value_cents,
			instrument_change_cents=period_change,
			oci_movement_cents=oci_movement,
			pl_movement_cents=pl_movement,
			cumulative_oci_cents=new_cumulative_oci,
			reclassified_to_pl_cents=0,
		)
		session.add(movement)
		session.flush()

		emit_event(
			HedgeMtmUpdatedEvent(
				aggregate_id=relationship_id,
				aggregate_type="HedgeRelationship",
				tenant_id=rel.tenant_id,
				relationship_id=relationship_id,
				hedge_reference=rel.hedge_reference,
				valuation_date=str(valuation_date),
				fair_value_cents=instrument_fair_value_cents,
				effective_portion_cents=effective_portion,
				ineffective_portion_cents=ineffective_portion,
			),
			session,
		)
		log.info(
			"FV movement recorded %r date=%s fv=%d oci=%d pl=%d",
			rel.hedge_reference, valuation_date,
			instrument_fair_value_cents, oci_movement, pl_movement,
		)
		return movement

	# ------------------------------------------------------------------ #
	# OCI reclassification
	# ------------------------------------------------------------------ #

	def reclassify_oci_to_pl(
		self,
		relationship_id: str,
		amount_cents: int,
		reason: str,
		session: Any,
	) -> Any:
		"""Reclassify an OCI amount to P&L (e.g. on hedged cash flow affecting P&L).

		Emits OciReclassifiedEvent.
		"""
		from pgappforge.plugins.erp.finance.hedge_accounting.models import (
			HedgeRelationship, HedgeFairValueMovement,
		)
		from pgappforge.plugins.erp.finance.hedge_accounting.events import (
			OciReclassifiedEvent, emit_event,
		)

		rel = session.get(HedgeRelationship, relationship_id)
		if rel is None:
			raise HedgeNotFoundError(f"HedgeRelationship {relationship_id!r} not found")

		assert abs(amount_cents) <= abs(rel.oci_balance_cents), \
			f"Reclassification {amount_cents} exceeds OCI balance {rel.oci_balance_cents}"

		today = date.today()
		rel.oci_balance_cents -= amount_cents
		rel.cumulative_gain_loss_oci_cents -= amount_cents
		rel.updated_at = datetime.now(timezone.utc)

		# Record as a movement row with reclassified_to_pl
		movement = HedgeFairValueMovement(
			relationship_id=relationship_id,
			valuation_date=today,
			instrument_fair_value_cents=0,
			instrument_change_cents=0,
			oci_movement_cents=-amount_cents,
			pl_movement_cents=amount_cents,
			cumulative_oci_cents=rel.oci_balance_cents,
			reclassified_to_pl_cents=amount_cents,
		)
		session.add(movement)
		session.flush()

		emit_event(
			OciReclassifiedEvent(
				aggregate_id=relationship_id,
				aggregate_type="HedgeRelationship",
				tenant_id=rel.tenant_id,
				relationship_id=relationship_id,
				hedge_reference=rel.hedge_reference,
				reclassification_date=str(today),
				amount_cents=amount_cents,
				reclassification_reason=reason,
			),
			session,
		)
		log.info("OCI reclassified %r amount=%d reason=%r", rel.hedge_reference, amount_cents, reason)
		return movement

	# ------------------------------------------------------------------ #
	# Discontinuation
	# ------------------------------------------------------------------ #

	def discontinue_hedge(
		self,
		relationship_id: str,
		discontinuation_date: date,
		reason: str,
		session: Any,
	) -> Any:
		"""Discontinue a hedge relationship (IFRS 9 §6.5.6).

		OCI balance is frozen and reclassified when the hedged item affects P&L.
		Emits HedgeRelationshipDiscontinuedEvent.
		"""
		from pgappforge.plugins.erp.finance.hedge_accounting.models import HedgeRelationship
		from pgappforge.plugins.erp.finance.hedge_accounting.events import (
			HedgeRelationshipDiscontinuedEvent, emit_event,
		)

		rel = session.get(HedgeRelationship, relationship_id)
		if rel is None:
			raise HedgeNotFoundError(f"HedgeRelationship {relationship_id!r} not found")
		if rel.status == "DISCONTINUED":
			raise HedgeStatusError(f"Hedge {rel.hedge_reference!r} already discontinued")

		remaining_oci = rel.oci_balance_cents
		rel.status = "DISCONTINUED"
		rel.discontinuation_date = discontinuation_date
		rel.discontinuation_reason = reason
		rel.updated_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(
			HedgeRelationshipDiscontinuedEvent(
				aggregate_id=relationship_id,
				aggregate_type="HedgeRelationship",
				tenant_id=rel.tenant_id,
				relationship_id=relationship_id,
				hedge_reference=rel.hedge_reference,
				discontinuation_date=str(discontinuation_date),
				reason=reason,
				remaining_oci_cents=remaining_oci,
			),
			session,
		)
		log.info("Hedge discontinued %r date=%s", rel.hedge_reference, discontinuation_date)
		return rel

	# ------------------------------------------------------------------ #
	# Summary
	# ------------------------------------------------------------------ #

	def get_hedge_summary(self, relationship_id: str, session: Any) -> dict[str, Any]:
		"""Return a summary of a hedge relationship including latest test result."""
		from pgappforge.plugins.erp.finance.hedge_accounting.models import (
			HedgeRelationship, HedgeEffectivenessTest,
		)

		rel = session.get(HedgeRelationship, relationship_id)
		if rel is None:
			raise HedgeNotFoundError(f"HedgeRelationship {relationship_id!r} not found")

		latest_test = session.execute(
			sa.select(HedgeEffectivenessTest)
			.where(HedgeEffectivenessTest.relationship_id == relationship_id)
			.order_by(sa.desc(HedgeEffectivenessTest.test_date))
			.limit(1)
		).scalar_one_or_none()

		return {
			"relationship_id": rel.id,
			"hedge_reference": rel.hedge_reference,
			"hedge_type": rel.hedge_type,
			"status": rel.status,
			"designation_date": str(rel.designation_date),
			"oci_balance_cents": rel.oci_balance_cents,
			"cumulative_gain_loss_oci_cents": rel.cumulative_gain_loss_oci_cents,
			"ineffectiveness_pl_cents": rel.ineffectiveness_pl_cents,
			"latest_test": {
				"test_date": str(latest_test.test_date),
				"is_effective": latest_test.is_effective,
				"effectiveness_ratio": str(latest_test.effectiveness_ratio),
			} if latest_test else None,
		}

	# ------------------------------------------------------------------ #
	# Internal helpers
	# ------------------------------------------------------------------ #

	def _generate_hedge_reference(self, session: Any) -> str:
		from pgappforge.plugins.erp.finance.hedge_accounting.models import HedgeRelationship
		year = date.today().year
		count = session.execute(
			sa.select(sa.func.count(HedgeRelationship.id))
		).scalar_one()
		return f"HG-{year}-{count + 1:05d}"


__all__ = [
	"HedgeAccountingService",
	"HedgeAccountingError",
	"HedgeNotFoundError",
	"HedgeStatusError",
	"HedgeIneffectiveError",
	"HedgeDesignationDetails",
]
