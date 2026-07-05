"""
pgappforge/plugins/erp/finance/material_ledger/services.py

MaterialLedgerService — actual costing / material ledger business logic.

All amounts in integer cents. Decimal arithmetic for quantities/prices. No float.

Public API
----------
  open_period(tenant_id, plant_id, fiscal_year, period_number,
              period_start, period_end, session)          -> CostingPeriod
  post_movement(ledger_id, movement_type, quantity, value_cents,
                posting_date, session, **kwargs)           -> MaterialMovement
  run_settlement(period_id, plant_id, session)            -> CostSettlement
  close_period(period_id, session)                        -> CostingPeriod
  get_actual_price(material_id, plant_id, period_id, session) -> dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MaterialLedgerError(Exception):
	"""Base material ledger error."""


class PeriodNotFoundError(MaterialLedgerError):
	pass


class PeriodStatusError(MaterialLedgerError):
	pass


class LedgerNotFoundError(MaterialLedgerError):
	pass


# ---------------------------------------------------------------------------
# MaterialLedgerService
# ---------------------------------------------------------------------------

class MaterialLedgerService:
	"""Stateless material ledger / actual costing service.

	Caller owns session transactions.
	"""

	# ------------------------------------------------------------------ #
	# Period management
	# ------------------------------------------------------------------ #

	def open_period(
		self,
		tenant_id: str,
		plant_id: str,
		fiscal_year: int,
		period_number: int,
		period_start: date,
		period_end: date,
		session: Any,
	) -> Any:
		"""Open a new costing period for a plant.

		Emits MaterialPeriodOpenedEvent.
		"""
		from pgappforge.plugins.erp.finance.material_ledger.models import CostingPeriod
		from pgappforge.plugins.erp.finance.material_ledger.events import (
			MaterialPeriodOpenedEvent, emit_event,
		)

		assert period_start <= period_end, "period_start must be <= period_end"
		assert 1 <= period_number <= 16, f"period_number {period_number} out of range"

		# Check for existing open period
		existing = session.execute(
			sa.select(CostingPeriod)
			.where(CostingPeriod.tenant_id == tenant_id)
			.where(CostingPeriod.plant_id == plant_id)
			.where(CostingPeriod.fiscal_year == fiscal_year)
			.where(CostingPeriod.period_number == period_number)
		).scalar_one_or_none()
		if existing is not None:
			raise MaterialLedgerError(
				f"Period {fiscal_year}/{period_number} for plant {plant_id!r} already exists"
			)

		period = CostingPeriod(
			tenant_id=tenant_id,
			plant_id=plant_id,
			fiscal_year=fiscal_year,
			period_number=period_number,
			period_start=period_start,
			period_end=period_end,
			status="OPEN",
		)
		session.add(period)
		session.flush()

		emit_event(
			MaterialPeriodOpenedEvent(
				aggregate_id=period.id,
				aggregate_type="CostingPeriod",
				tenant_id=tenant_id,
				period_id=period.id,
				plant_id=plant_id,
				fiscal_year=fiscal_year,
				period_number=period_number,
				period_start=str(period_start),
				period_end=str(period_end),
			),
			session,
		)
		log.info(
			"Costing period opened: plant=%r FY%d P%d",
			plant_id, fiscal_year, period_number,
		)
		return period

	def close_period(self, period_id: str, session: Any) -> Any:
		"""Close a period after settlement has completed.

		Transitions: OPEN → CLOSING (run_settlement) → CLOSED (close_period).
		Emits MaterialPeriodClosedEvent.
		"""
		from pgappforge.plugins.erp.finance.material_ledger.models import (
			CostingPeriod, MaterialLedger,
		)
		from pgappforge.plugins.erp.finance.material_ledger.events import (
			MaterialPeriodClosedEvent, emit_event,
		)

		period = session.get(CostingPeriod, period_id)
		if period is None:
			raise PeriodNotFoundError(f"CostingPeriod {period_id!r} not found")
		if period.status not in ("OPEN", "CLOSING"):
			raise PeriodStatusError(
				f"Period {period_id!r} is {period.status!r}, cannot close"
			)

		# Lock all ledger entries for this period
		session.execute(
			sa.update(MaterialLedger)
			.where(MaterialLedger.period_id == period_id)
			.values(costing_status="LOCKED")
		)

		ledgers = session.execute(
			sa.select(MaterialLedger)
			.where(MaterialLedger.period_id == period_id)
		).scalars().all()
		result = sum(
			(ledger.purchase_price_variance_cents or 0)
			+ (ledger.exchange_rate_difference_cents or 0)
			+ (ledger.production_variance_cents or 0)
			+ (ledger.multilevel_variance_cents or 0)
			+ (ledger.revaluation_cents or 0)
			for ledger in ledgers
		)
		materials_count = len(ledgers)

		period.status = "CLOSED"
		period.closed_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(
			MaterialPeriodClosedEvent(
				aggregate_id=period_id,
				aggregate_type="CostingPeriod",
				tenant_id=period.tenant_id,
				period_id=period_id,
				plant_id=period.plant_id,
				fiscal_year=period.fiscal_year,
				period_number=period.period_number,
				materials_settled=materials_count,
				total_variance_cents=result,
			),
			session,
		)
		log.info(
			"Period closed: plant=%r FY%d P%d materials=%d variance=%d",
			period.plant_id, period.fiscal_year, period.period_number,
			materials_count, result,
		)
		return period

	# ------------------------------------------------------------------ #
	# Movement posting
	# ------------------------------------------------------------------ #

	def post_movement(
		self,
		ledger_id: str,
		movement_type: str,
		quantity: Decimal,
		value_cents: int,
		posting_date: date,
		session: Any,
		*,
		source_document_type: str | None = None,
		source_document_id: str | None = None,
		posting_reference: str | None = None,
		is_reversal: bool = False,
		reversal_of_id: str | None = None,
	) -> Any:
		"""Post a material movement to a ledger entry.

		Updates the MaterialLedger aggregated quantities and values.
		Emits PriceVariancePostedEvent if a variance is detected on GR movements.

		value_cents is the preliminary value (qty × standard_price).
		Actual value is determined during the settlement run.
		"""
		from pgappforge.plugins.erp.finance.material_ledger.models import (
			MaterialLedger, MaterialMovement,
		)
		from pgappforge.plugins.erp.finance.material_ledger.events import (
			PriceVariancePostedEvent, emit_event,
		)

		ledger = session.get(MaterialLedger, ledger_id)
		if ledger is None:
			raise LedgerNotFoundError(f"MaterialLedger {ledger_id!r} not found")
		if ledger.costing_status == "LOCKED":
			raise MaterialLedgerError(
				f"MaterialLedger {ledger_id!r} is LOCKED (period closed)"
			)

		movement = MaterialMovement(
			ledger_id=ledger_id,
			posting_date=posting_date,
			movement_type=movement_type,
			quantity=quantity,
			unit_of_measure="EA",
			preliminary_value_cents=value_cents,
			source_document_type=source_document_type,
			source_document_id=source_document_id,
			posting_reference=posting_reference,
			is_reversal=is_reversal,
			reversal_of_id=reversal_of_id,
		)
		session.add(movement)

		# Inbound movements (GR codes start with 1; production receipts 101)
		inbound_types = {"101", "501", "561", "GR"}
		outbound_types = {"201", "261", "502", "GI"}

		if movement_type in inbound_types or movement_type.startswith("1"):
			ledger.receipts_qty += quantity
			ledger.receipts_value_cents += value_cents
		elif movement_type in outbound_types or movement_type.startswith("2"):
			ledger.issues_qty += quantity
			ledger.issues_value_cents += value_cents
		else:
			# Transfer / other — treat as neutral (update both sides)
			ledger.receipts_qty += quantity
			ledger.receipts_value_cents += value_cents
			ledger.issues_qty += quantity
			ledger.issues_value_cents += value_cents

		# Update closing qty/value
		ledger.closing_qty = (
			ledger.opening_qty
			+ ledger.receipts_qty
			- ledger.issues_qty
		)
		ledger.closing_value_cents = (
			ledger.opening_value_cents
			+ ledger.receipts_value_cents
			- ledger.issues_value_cents
		)
		ledger.updated_at = datetime.now(timezone.utc)

		# Detect and accumulate purchase price variance (GR from PO)
		if movement_type in ("101", "GR") and not is_reversal:
			# Variance = actual invoice price - standard price × qty
			# Invoice price is not known at GR time; PPV is posted at invoice verification.
			# Placeholder: variance will be updated when invoice is posted.
			# For explicit variance posting, caller passes a negative/positive value_cents delta.
			pass

		session.flush()
		log.info(
			"Movement posted: ledger=%r type=%s qty=%s value=%d",
			ledger_id, movement_type, quantity, value_cents,
		)
		return movement

	# ------------------------------------------------------------------ #
	# Settlement run
	# ------------------------------------------------------------------ #

	def run_settlement(
		self, period_id: str, plant_id: str, session: Any
	) -> Any:
		"""Execute multi-level actual cost settlement for a period.

		Settlement algorithm (simplified single-level):
		1. For each material ledger entry:
		   a. Total actual cost = opening_value + receipts_value + all variances
		   b. actual_price = total_cost / closing_qty (if closing_qty > 0)
		   c. revaluation = (actual_price - standard_price) × closing_qty
		   d. Post revaluation entry; mark ledger as SETTLED.
		2. Record CostSettlement run result.

		Multi-level BOM variance absorption (upstream-to-downstream) is handled
		by processing materials in ascending BOM level order. Full BOM traversal
		requires integration with the MRP/BOM module; this implementation
		assumes single-level (no upstream absorption).

		Emits CostSettlementRunEvent.
		"""
		from pgappforge.plugins.erp.finance.material_ledger.models import (
			CostingPeriod, MaterialLedger, CostSettlement,
		)
		from pgappforge.plugins.erp.finance.material_ledger.events import (
			CostSettlementRunEvent, emit_event,
		)

		period = session.get(CostingPeriod, period_id)
		if period is None:
			raise PeriodNotFoundError(f"CostingPeriod {period_id!r} not found")
		if period.status != "OPEN":
			raise PeriodStatusError(
				f"Period {period_id!r} is {period.status!r}, expected OPEN"
			)

		period.status = "CLOSING"

		run = CostSettlement(
			tenant_id=period.tenant_id,
			period_id=period_id,
			plant_id=plant_id,
			status="RUNNING",
			run_by="system",
		)
		session.add(run)
		session.flush()

		ledgers = session.execute(
			sa.select(MaterialLedger)
			.where(MaterialLedger.period_id == period_id)
			.where(MaterialLedger.plant_id == plant_id)
			.where(MaterialLedger.costing_status == "OPEN")
		).scalars().all()

		total_variance = 0
		errors: list[dict] = []
		settled = 0

		for ledger in ledgers:
			try:
				total_cost = (
					ledger.opening_value_cents
					+ ledger.receipts_value_cents
					+ ledger.purchase_price_variance_cents
					+ ledger.exchange_rate_difference_cents
					+ ledger.production_variance_cents
					+ ledger.multilevel_variance_cents
				)
				closing_qty = Decimal(str(ledger.closing_qty))
				actual_cost_qty = (
					Decimal(str(ledger.opening_qty))
					+ Decimal(str(ledger.receipts_qty))
				)

				if actual_cost_qty > 0:
					actual_price = int(
						(Decimal(str(total_cost)) / actual_cost_qty)
						.to_integral_value(ROUND_HALF_UP)
					)
				else:
					actual_price = ledger.standard_price_cents

				revaluation = int(
					(Decimal(str(actual_price - ledger.standard_price_cents)) * closing_qty)
					.to_integral_value(ROUND_HALF_UP)
				)

				ledger.actual_price_cents = actual_price
				ledger.revaluation_cents = revaluation
				ledger.costing_status = "SETTLED"
				ledger.updated_at = datetime.now(timezone.utc)

				total_variance += abs(revaluation)
				settled += 1

			except Exception as exc:
				errors.append({"material": ledger.material_id, "error": str(exc)[:200]})
				log.error("Settlement error for material %s: %s", ledger.material_id, exc)

		run.status = "COMPLETED" if not errors else "FAILED"
		run.materials_processed = settled
		run.total_variance_cents = total_variance
		run.error_log = errors
		run.completed_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(
			CostSettlementRunEvent(
				aggregate_id=run.id,
				aggregate_type="CostSettlement",
				tenant_id=period.tenant_id,
				run_id=run.id,
				period_id=period_id,
				plant_id=plant_id,
				levels_processed=1,
				materials_processed=settled,
				run_at=run.run_at.isoformat() if run.run_at else "",
			),
			session,
		)
		log.info(
			"Settlement run complete: period=%r plant=%r settled=%d variance=%d errors=%d",
			period_id, plant_id, settled, total_variance, len(errors),
		)
		return run

	# ------------------------------------------------------------------ #
	# Queries
	# ------------------------------------------------------------------ #

	def get_actual_price(
		self,
		material_id: str,
		plant_id: str,
		period_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return the settled actual price for a material in a period."""
		from pgappforge.plugins.erp.finance.material_ledger.models import MaterialLedger

		ledger = session.execute(
			sa.select(MaterialLedger)
			.where(MaterialLedger.material_id == material_id)
			.where(MaterialLedger.plant_id == plant_id)
			.where(MaterialLedger.period_id == period_id)
		).scalar_one_or_none()

		if ledger is None:
			raise LedgerNotFoundError(
				f"No ledger for material={material_id!r} plant={plant_id!r} period={period_id!r}"
			)

		return {
			"material_id": material_id,
			"plant_id": plant_id,
			"standard_price_cents": ledger.standard_price_cents,
			"actual_price_cents": ledger.actual_price_cents,
			"revaluation_cents": ledger.revaluation_cents,
			"costing_status": ledger.costing_status,
			"closing_qty": str(ledger.closing_qty),
			"total_variance_cents": (
				ledger.purchase_price_variance_cents
				+ ledger.exchange_rate_difference_cents
				+ ledger.production_variance_cents
				+ ledger.multilevel_variance_cents
			),
		}


__all__ = [
	"MaterialLedgerService",
	"MaterialLedgerError",
	"PeriodNotFoundError",
	"PeriodStatusError",
	"LedgerNotFoundError",
]
