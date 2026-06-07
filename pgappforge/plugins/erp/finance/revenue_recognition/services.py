"""
pgappforge/plugins/erp/finance/revenue_recognition/services.py

RevRecService — stateless business logic for the Revenue Recognition plugin.

Implements the ASC 606 / IFRS 15 five-step model:
  1. Identify the contract                → create_contract()
  2. Identify performance obligations     → create_contract() (obligations_data)
  3. Determine the transaction price      → variable consideration handled separately
  4. Allocate to obligations              → _allocate() (Decimal, ROUND_HALF_UP)
  5. Recognize revenue                    → satisfy_obligation(), recognize_period()

All methods receive an explicit SQLAlchemy Session; callers own transaction
boundaries (commit/rollback).  No Flask context assumed — safe for background
jobs, CLI commands, and tests.

Critical invariants:
  - All monetary amounts: integer cents (BigInteger). Never float.
  - Allocation must sum exactly to total_transaction_price_cents (last-item adjust).
  - satisfied_cents never exceeds allocated_transaction_price_cents.
  - GL posting is optional (gl_post=False for dry-run / test scenarios).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

from pgappforge.plugins.erp.finance.revenue_recognition.events import (
	AllocationUpdatedEvent,
	ContractCreatedEvent,
	ContractModifiedEvent,
	PerformanceObligationSatisfiedEvent,
	RevenueRecognizedEvent,
	VariableConsiderationEstimatedEvent,
)
from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RevRecError(Exception):
	"""Base error for Revenue Recognition domain violations."""


class ContractNotFoundError(RevRecError):
	"""No RevRecContract with the given id."""


class ObligationNotFoundError(RevRecError):
	"""No RevRecObligation with the given id."""


class AllocationError(RevRecError):
	"""Transaction price cannot be allocated across the given obligations."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _emit(event: Any, session: Any = None) -> None:
	"""Best-effort event emission — never raises into the calling transaction."""
	try:
		_emit_event(event, session)
	except Exception as exc:
		log.debug("RevRecService event emission failed (non-fatal): %s", exc)


def _parse_period(period: str) -> tuple[int, int]:
	"""Parse 'YYYY-MM' → (year, month).  Raises RevRecError on bad format."""
	try:
		parts = period.split("-")
		return int(parts[0]), int(parts[1])
	except (IndexError, ValueError):
		raise RevRecError(f"Invalid period format {period!r}; expected 'YYYY-MM'")


def _months_between(start: date, end: date) -> int:
	"""Inclusive month count covering the service period.

	e.g. 2025-01-01 → 2025-12-31 = 12 months.
	Minimum 1 to avoid zero-division on single-month obligations.
	"""
	months = (end.year - start.year) * 12 + (end.month - start.month) + 1
	return max(months, 1)


def _period_in_range(period: str, start: date | None, end: date | None) -> bool:
	"""True if the YYYY-MM period falls within [start, end]."""
	if start is None or end is None:
		return True
	year, month = _parse_period(period)
	p_start = date(year, month, 1)
	# period end = last day of month; approximate as first of next month - 1 day
	import calendar
	last_day = calendar.monthrange(year, month)[1]
	p_end = date(year, month, last_day)
	return p_start <= end and p_end >= start


# ---------------------------------------------------------------------------
# Allocation — Step 4 of the five-step model
# ---------------------------------------------------------------------------

def _allocate(total_cents: int, ssps: list[int]) -> list[int]:
	"""Allocate total_cents proportionally to standalone selling prices.

	Uses Decimal ROUND_HALF_UP for each obligation.  The last obligation
	absorbs the rounding residual so the sum always equals total_cents exactly.

	Args:
		total_cents: Total transaction price in integer cents.
		ssps:        List of standalone selling price cents per obligation.

	Returns:
		List of allocated cents, same order as ssps.

	Raises:
		AllocationError: if ssps is empty or all-zero.
	"""
	if not ssps:
		raise AllocationError("No performance obligations provided for allocation")
	total_ssp = sum(ssps)
	if total_ssp == 0:
		raise AllocationError("Sum of standalone selling prices is zero; cannot allocate")

	total_d = Decimal(total_cents)
	total_ssp_d = Decimal(total_ssp)
	allocated: list[int] = []
	running_sum = 0

	for i, ssp in enumerate(ssps):
		if i == len(ssps) - 1:
			# Last item: absorb rounding residual
			allocated.append(total_cents - running_sum)
		else:
			share = (Decimal(ssp) / total_ssp_d * total_d).to_integral_value(ROUND_HALF_UP)
			cents = int(share)
			allocated.append(cents)
			running_sum += cents

	assert sum(allocated) == total_cents, (
		f"Allocation bug: sum={sum(allocated)} != total={total_cents}"
	)
	return allocated


# ---------------------------------------------------------------------------
# RevRecService
# ---------------------------------------------------------------------------

class RevRecService:
	"""Stateless service for Revenue Recognition operations.

	All methods accept a SQLAlchemy Session; callers own commit/rollback.
	Instantiate once per app or once per request — no state is stored.
	"""

	# ------------------------------------------------------------------
	# create_contract — Steps 1, 2, 4
	# ------------------------------------------------------------------

	def create_contract(
		self,
		customer_id: str,
		contract_ref: str | None,
		total_cents: int,
		obligations_data: list[dict[str, Any]],
		session: Any,
		*,
		tenant_id: str,
		contract_date: date | None = None,
		source_module: str | None = None,
		source_record_id: str | None = None,
	) -> Any:
		"""Create a new revenue recognition contract with performance obligations.

		obligations_data is a list of dicts:
		  - description (str, required)
		  - standalone_selling_price_cents (int, required)
		  - satisfaction_type (str, required): POINT_IN_TIME | OVER_TIME
		  - recognition_method (str, optional, default STRAIGHT_LINE)
		  - start_date (date | None)
		  - end_date   (date | None)

		Allocation: allocated_i = total * (ssp_i / sum_ssp), Decimal ROUND_HALF_UP,
		last obligation absorbs rounding residual so sum == total exactly.

		Emits: ContractCreatedEvent
		"""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import (
			RevRecContract,
			RevRecObligation,
		)

		if not obligations_data:
			raise RevRecError("At least one performance obligation is required")
		if total_cents <= 0:
			raise RevRecError(f"total_cents must be positive; got {total_cents}")

		effective_date = contract_date or date.today()

		# Step 1: Create the contract
		contract = RevRecContract(
			tenant_id=tenant_id,
			customer_id=customer_id,
			contract_ref=contract_ref,
			contract_date=effective_date,
			total_transaction_price_cents=total_cents,
			variable_consideration_cents=0,
			contract_mod_number=0,
			status="OPEN",
			source_module=source_module,
			source_record_id=source_record_id,
			metadata_={},
		)
		session.add(contract)
		session.flush()  # Obtain contract.id

		# Step 4: Allocate transaction price across obligations
		ssps = [int(o["standalone_selling_price_cents"]) for o in obligations_data]
		allocations = _allocate(total_cents, ssps)

		for odata, alloc in zip(obligations_data, allocations):
			obligation = RevRecObligation(
				tenant_id=tenant_id,
				contract_id=contract.id,
				description=str(odata["description"]),
				standalone_selling_price_cents=int(odata["standalone_selling_price_cents"]),
				allocated_transaction_price_cents=alloc,
				satisfied_cents=0,
				remaining_cents=alloc,
				satisfaction_type=str(odata["satisfaction_type"]),
				recognition_method=str(odata.get("recognition_method", "STRAIGHT_LINE")),
				start_date=odata.get("start_date"),
				end_date=odata.get("end_date"),
				status="UNSATISFIED",
				metadata_={},
			)
			session.add(obligation)

		session.flush()

		_emit(
			ContractCreatedEvent(
				aggregate_id=contract.id,
				aggregate_type="RevRecContract",
				tenant_id=tenant_id,
				contract_id=contract.id,
				customer_id=customer_id,
				total_value_cents=total_cents,
			),
			session,
		)

		log.info(
			"RevRecService.create_contract: contract=%s customer=%s total=%d obligations=%d",
			contract.id, customer_id, total_cents, len(obligations_data),
		)
		return contract

	# ------------------------------------------------------------------
	# satisfy_obligation — Step 5 (POINT_IN_TIME or manual partial)
	# ------------------------------------------------------------------

	def satisfy_obligation(
		self,
		obligation_id: str,
		satisfied_cents: int,
		period: str,
		session: Any,
		*,
		gl_post: bool = True,
	) -> Any:
		"""Satisfy (fully or partially) a performance obligation.

		Steps:
		  1. Load obligation; assert satisfied_cents <= remaining_cents.
		  2. Update obligation.satisfied_cents += satisfied_cents; recompute status.
		  3. Update obligation.remaining_cents.
		  4. Create RevRecJournalEntry.
		  5. If gl_post: post DR Deferred Revenue / CR Revenue via GLService.
		  6. Emit PerformanceObligationSatisfiedEvent, RevenueRecognizedEvent.
		  7. Recompute contract status.

		Returns: RevRecJournalEntry
		"""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import (
			RevRecContract,
			RevRecJournalEntry,
			RevRecObligation,
		)

		if satisfied_cents <= 0:
			raise RevRecError(f"satisfied_cents must be positive; got {satisfied_cents}")

		obligation = session.execute(
			select(RevRecObligation).where(RevRecObligation.id == obligation_id)
		).scalar_one_or_none()

		if obligation is None:
			raise ObligationNotFoundError(f"RevRecObligation {obligation_id!r} not found")

		if satisfied_cents > obligation.remaining_cents:
			raise RevRecError(
				f"satisfied_cents={satisfied_cents} exceeds remaining_cents="
				f"{obligation.remaining_cents} for obligation {obligation_id!r}"
			)

		# Update obligation
		obligation.satisfied_cents += satisfied_cents
		obligation.remaining_cents = (
			obligation.allocated_transaction_price_cents - obligation.satisfied_cents
		)

		if obligation.remaining_cents == 0:
			obligation.status = "FULLY_SATISFIED"
		elif obligation.satisfied_cents > 0:
			obligation.status = "PARTIALLY"

		session.flush()

		# Create revenue recognition journal entry
		entry = RevRecJournalEntry(
			tenant_id=obligation.tenant_id,
			obligation_id=obligation_id,
			contract_id=obligation.contract_id,
			period=period,
			recognized_cents=satisfied_cents,
			gl_journal_id=None,
			deferred_revenue_account="2500",
			revenue_account="4000",
		)
		session.add(entry)
		session.flush()

		# Post to GL if requested
		if gl_post:
			gl_journal_id = self._post_to_gl(
				obligation=obligation,
				recognized_cents=satisfied_cents,
				period=period,
				session=session,
			)
			if gl_journal_id:
				entry.gl_journal_id = gl_journal_id
				session.flush()

		# Update contract status
		contract = session.get(RevRecContract, obligation.contract_id)
		if contract is not None:
			self._recompute_contract_status(contract, session)

		# Emit events
		_emit(
			PerformanceObligationSatisfiedEvent(
				aggregate_id=obligation_id,
				aggregate_type="RevRecObligation",
				tenant_id=obligation.tenant_id,
				obligation_id=obligation_id,
				contract_id=obligation.contract_id,
				recognized_cents=satisfied_cents,
				period=period,
			),
			session,
		)
		_emit(
			RevenueRecognizedEvent(
				aggregate_id=obligation.contract_id,
				aggregate_type="RevRecContract",
				tenant_id=obligation.tenant_id,
				contract_id=obligation.contract_id,
				period=period,
				amount_cents=satisfied_cents,
				method=obligation.recognition_method,
			),
			session,
		)

		log.info(
			"RevRecService.satisfy_obligation: obligation=%s period=%s recognized=%d",
			obligation_id, period, satisfied_cents,
		)
		return entry

	# ------------------------------------------------------------------
	# recognize_period — Step 5 (OVER_TIME, systematic allocation)
	# ------------------------------------------------------------------

	def recognize_period(
		self,
		contract_id: str,
		period: str,
		session: Any,
	) -> list[Any]:
		"""Run period revenue recognition for all OVER_TIME obligations in a contract.

		For each OVER_TIME obligation:
		  - STRAIGHT_LINE: allocated / months(start_date, end_date) for the period
		  - COMPLETED_CONTRACT: 0 until remaining_cents == 0, then full remaining
		  - OUTPUT / INPUT: period_revenue must be passed via satisfy_obligation
		    directly; this method returns 0 for those methods (caller-driven).

		Only processes obligations in status UNSATISFIED or PARTIALLY.
		Skips obligations whose service period does not include the requested period.

		Returns: list of RevRecJournalEntry created this run.
		"""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import (
			RevRecContract,
			RevRecObligation,
		)

		contract = session.execute(
			select(RevRecContract).where(RevRecContract.id == contract_id)
		).scalar_one_or_none()

		if contract is None:
			raise ContractNotFoundError(f"RevRecContract {contract_id!r} not found")

		if contract.status in ("FULLY_SATISFIED", "CANCELLED"):
			log.info(
				"RevRecService.recognize_period: contract=%s status=%s; nothing to do",
				contract_id, contract.status,
			)
			return []

		obligations = session.execute(
			select(RevRecObligation).where(
				RevRecObligation.contract_id == contract_id,
				RevRecObligation.satisfaction_type == "OVER_TIME",
				RevRecObligation.status.in_(["UNSATISFIED", "PARTIALLY"]),
			)
		).scalars().all()

		entries: list[Any] = []

		for obligation in obligations:
			# Skip if period is outside the obligation's service window
			if not _period_in_range(period, obligation.start_date, obligation.end_date):
				log.debug(
					"RevRecService.recognize_period: obligation=%s period=%s outside service window; skipping",
					obligation.id, period,
				)
				continue

			period_revenue = self._compute_period_revenue(obligation, period)

			if period_revenue <= 0:
				continue

			# Cap at remaining to avoid over-recognition
			period_revenue = min(period_revenue, obligation.remaining_cents)

			entry = self.satisfy_obligation(
				obligation_id=obligation.id,
				satisfied_cents=period_revenue,
				period=period,
				session=session,
				gl_post=True,
			)
			entries.append(entry)

		log.info(
			"RevRecService.recognize_period: contract=%s period=%s entries=%d",
			contract_id, period, len(entries),
		)
		return entries

	# ------------------------------------------------------------------
	# modify_contract — contract modification accounting
	# ------------------------------------------------------------------

	def modify_contract(
		self,
		contract_id: str,
		new_total_cents: int,
		session: Any,
		*,
		add_obligations: list[dict[str, Any]] | None = None,
		modification_type: str = "CUMULATIVE_CATCH_UP",
	) -> Any:
		"""Modify a contract per ASC 606-10-25-18 / IFRS 15.18.

		modification_type:
		  PROSPECTIVE       — apply new allocation only to future periods
		  CUMULATIVE_CATCH_UP — restate allocation as if new terms existed from inception

		Steps:
		  1. Load contract and existing unsatisfied/partially satisfied obligations.
		  2. Add any new obligations (add_obligations).
		  3. Recompute SSP sum and reallocate new_total_cents.
		  4. For CUMULATIVE_CATCH_UP: update all obligations' allocated amounts
		     and recompute remaining_cents based on already-recognized amounts.
		  5. For PROSPECTIVE: update only future-facing (unsatisfied) obligations.
		  6. Increment contract_mod_number and update total_transaction_price_cents.
		  7. Emit ContractModifiedEvent, AllocationUpdatedEvent.

		Returns: updated RevRecContract
		"""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import (
			RevRecContract,
			RevRecObligation,
		)

		if new_total_cents <= 0:
			raise RevRecError(f"new_total_cents must be positive; got {new_total_cents}")
		if modification_type not in ("PROSPECTIVE", "CUMULATIVE_CATCH_UP"):
			raise RevRecError(
				f"modification_type must be PROSPECTIVE or CUMULATIVE_CATCH_UP; "
				f"got {modification_type!r}"
			)

		contract = session.execute(
			select(RevRecContract).where(RevRecContract.id == contract_id)
		).scalar_one_or_none()

		if contract is None:
			raise ContractNotFoundError(f"RevRecContract {contract_id!r} not found")

		if contract.status == "CANCELLED":
			raise RevRecError(f"Cannot modify a CANCELLED contract {contract_id!r}")

		# Load all non-fully-satisfied obligations
		existing_obligations: list[Any] = session.execute(
			select(RevRecObligation).where(
				RevRecObligation.contract_id == contract_id,
				RevRecObligation.status != "FULLY_SATISFIED",
			)
		).scalars().all()

		# Add new obligations if provided
		new_obligations: list[Any] = []
		if add_obligations:
			for odata in add_obligations:
				obligation = RevRecObligation(
					tenant_id=contract.tenant_id,
					contract_id=contract_id,
					description=str(odata["description"]),
					standalone_selling_price_cents=int(odata["standalone_selling_price_cents"]),
					allocated_transaction_price_cents=0,  # placeholder; set below
					satisfied_cents=0,
					remaining_cents=0,
					satisfaction_type=str(odata["satisfaction_type"]),
					recognition_method=str(odata.get("recognition_method", "STRAIGHT_LINE")),
					start_date=odata.get("start_date"),
					end_date=odata.get("end_date"),
					status="UNSATISFIED",
					metadata_={},
				)
				session.add(obligation)
				new_obligations.append(obligation)
			session.flush()

		all_obligations = existing_obligations + new_obligations
		if not all_obligations:
			raise RevRecError(
				f"Contract {contract_id!r} has no unsatisfied obligations to reallocate"
			)

		# Reallocate new total across all obligations by SSP
		ssps = [o.standalone_selling_price_cents for o in all_obligations]
		allocations = _allocate(new_total_cents, ssps)

		for obligation, new_alloc in zip(all_obligations, allocations):
			if modification_type == "CUMULATIVE_CATCH_UP":
				# Restate: remaining = new_alloc - already_recognized
				obligation.allocated_transaction_price_cents = new_alloc
				obligation.remaining_cents = max(new_alloc - obligation.satisfied_cents, 0)
			else:
				# PROSPECTIVE: only update the unsatisfied portion
				# Keep satisfied as-is; allocate new_alloc to cover remaining exposure
				old_alloc = obligation.allocated_transaction_price_cents
				delta = new_alloc - old_alloc
				obligation.allocated_transaction_price_cents = new_alloc
				obligation.remaining_cents = max(obligation.remaining_cents + delta, 0)

			# Recompute status
			if obligation.remaining_cents == 0 and obligation.satisfied_cents > 0:
				obligation.status = "FULLY_SATISFIED"
			elif obligation.satisfied_cents > 0:
				obligation.status = "PARTIALLY"
			else:
				obligation.status = "UNSATISFIED"

		# Update contract
		contract.total_transaction_price_cents = new_total_cents
		contract.contract_mod_number += 1
		self._recompute_contract_status(contract, session)
		session.flush()

		_emit(
			ContractModifiedEvent(
				aggregate_id=contract_id,
				aggregate_type="RevRecContract",
				tenant_id=contract.tenant_id,
				contract_id=contract_id,
				modification_type=modification_type,
				new_value_cents=new_total_cents,
			),
			session,
		)
		_emit(
			AllocationUpdatedEvent(
				aggregate_id=contract_id,
				aggregate_type="RevRecContract",
				tenant_id=contract.tenant_id,
				contract_id=contract_id,
				obligation_count=len(all_obligations),
			),
			session,
		)

		log.info(
			"RevRecService.modify_contract: contract=%s new_total=%d type=%s obligations=%d",
			contract_id, new_total_cents, modification_type, len(all_obligations),
		)
		return contract

	# ------------------------------------------------------------------
	# estimate_variable_consideration
	# ------------------------------------------------------------------

	def estimate_variable_consideration(
		self,
		contract_id: str,
		estimation_method: str,
		estimated_cents: int,
		constrained_cents: int,
		session: Any,
		*,
		constraint_applied: bool = True,
		basis: str | None = None,
	) -> Any:
		"""Create or update the variable consideration estimate for a contract.

		estimation_method: EXPECTED_VALUE | MOST_LIKELY_AMOUNT
		constrained_cents must be <= estimated_cents when constraint_applied=True.

		Updates contract.variable_consideration_cents to constrained_cents.
		Emits VariableConsiderationEstimatedEvent.
		"""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import (
			RevRecContract,
			VariableConsideration,
		)

		if estimation_method not in ("EXPECTED_VALUE", "MOST_LIKELY_AMOUNT"):
			raise RevRecError(
				f"estimation_method must be EXPECTED_VALUE or MOST_LIKELY_AMOUNT; "
				f"got {estimation_method!r}"
			)
		if constraint_applied and constrained_cents > estimated_cents:
			raise RevRecError(
				f"constrained_cents={constrained_cents} cannot exceed "
				f"estimated_cents={estimated_cents} when constraint is applied"
			)

		contract = session.execute(
			select(RevRecContract).where(RevRecContract.id == contract_id)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"RevRecContract {contract_id!r} not found")

		# Upsert VariableConsideration
		vc: Any = session.execute(
			select(VariableConsideration).where(VariableConsideration.contract_id == contract_id)
		).scalar_one_or_none()

		now = datetime.now(timezone.utc)

		if vc is None:
			vc = VariableConsideration(
				tenant_id=contract.tenant_id,
				contract_id=contract_id,
				estimation_method=estimation_method,
				constraint_applied=constraint_applied,
				estimated_cents=estimated_cents,
				constrained_cents=constrained_cents,
				last_estimated_at=now,
				basis=basis,
			)
			session.add(vc)
		else:
			vc.estimation_method = estimation_method
			vc.constraint_applied = constraint_applied
			vc.estimated_cents = estimated_cents
			vc.constrained_cents = constrained_cents
			vc.last_estimated_at = now
			vc.basis = basis

		# Reflect constrained amount in contract transaction price
		contract.variable_consideration_cents = constrained_cents
		session.flush()

		_emit(
			VariableConsiderationEstimatedEvent(
				aggregate_id=contract_id,
				aggregate_type="RevRecContract",
				tenant_id=contract.tenant_id,
				contract_id=contract_id,
				estimated_cents=estimated_cents,
				method=estimation_method,
			),
			session,
		)
		return vc

	# ------------------------------------------------------------------
	# get_deferred_revenue_balance
	# ------------------------------------------------------------------

	def get_deferred_revenue_balance(
		self,
		tenant_id: str,
		session: Any,
		*,
		as_of_date: date | None = None,
	) -> dict[str, Any]:
		"""Compute deferred revenue balance across open contracts.

		Returns:
		  {
		    "total_deferred_cents": int,
		    "by_customer": {customer_id: deferred_cents},
		    "by_contract": [
		        {
		            "contract_id": str,
		            "customer_id": str,
		            "status": str,
		            "deferred_cents": int,
		        }
		    ],
		  }

		Deferred = sum(allocated_transaction_price_cents - satisfied_cents)
		across all obligations for OPEN/PARTIALLY_SATISFIED contracts.
		"""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import (
			RevRecContract,
			RevRecObligation,
		)

		# Contracts in scope
		contract_stmt = select(RevRecContract).where(
			RevRecContract.tenant_id == tenant_id,
			RevRecContract.status.in_(["OPEN", "PARTIALLY_SATISFIED"]),
		)
		if as_of_date is not None:
			contract_stmt = contract_stmt.where(RevRecContract.contract_date <= as_of_date)

		contracts: list[Any] = session.execute(contract_stmt).scalars().all()

		if not contracts:
			return {
				"total_deferred_cents": 0,
				"by_customer": {},
				"by_contract": [],
			}

		contract_ids = [c.id for c in contracts]
		contract_map = {c.id: c for c in contracts}

		# Aggregate remaining_cents per contract
		rows = session.execute(
			select(
				RevRecObligation.contract_id,
				func.sum(RevRecObligation.remaining_cents).label("deferred"),
			).where(
				RevRecObligation.contract_id.in_(contract_ids),
				RevRecObligation.status != "FULLY_SATISFIED",
			).group_by(RevRecObligation.contract_id)
		).all()

		by_contract: list[dict] = []
		by_customer: dict[str, int] = {}
		total = 0

		for row in rows:
			cid = row.contract_id
			deferred = int(row.deferred or 0)
			c = contract_map[cid]
			by_contract.append({
				"contract_id": cid,
				"customer_id": c.customer_id,
				"status": c.status,
				"deferred_cents": deferred,
			})
			by_customer[c.customer_id] = by_customer.get(c.customer_id, 0) + deferred
			total += deferred

		return {
			"total_deferred_cents": total,
			"by_customer": by_customer,
			"by_contract": by_contract,
		}

	# ------------------------------------------------------------------
	# get_revenue_waterfall
	# ------------------------------------------------------------------

	def get_revenue_waterfall(
		self,
		tenant_id: str,
		session: Any,
		*,
		from_period: str,
		to_period: str,
	) -> dict[str, Any]:
		"""Period-by-period scheduled recognition amounts.

		Returns:
		  {
		    "from_period": str,
		    "to_period": str,
		    "periods": {
		        "YYYY-MM": {
		            "recognized_cents": int,
		            "entry_count": int,
		        }
		    },
		    "total_recognized_cents": int,
		  }

		Reads from RevRecJournalEntry — reflects what has already been
		recognized, not future scheduled amounts.  For forecasting, call
		recognize_period() in simulation mode (gl_post=False) first.
		"""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import (
			RevRecJournalEntry,
		)

		# Validate period format
		_parse_period(from_period)
		_parse_period(to_period)

		rows = session.execute(
			select(
				RevRecJournalEntry.period,
				func.sum(RevRecJournalEntry.recognized_cents).label("recognized"),
				func.count(RevRecJournalEntry.id).label("count"),
			).where(
				RevRecJournalEntry.tenant_id == tenant_id,
				RevRecJournalEntry.period >= from_period,
				RevRecJournalEntry.period <= to_period,
			).group_by(RevRecJournalEntry.period)
			.order_by(RevRecJournalEntry.period)
		).all()

		periods: dict[str, dict] = {}
		total = 0

		for row in rows:
			recognized = int(row.recognized or 0)
			periods[row.period] = {
				"recognized_cents": recognized,
				"entry_count": int(row.count or 0),
			}
			total += recognized

		return {
			"from_period": from_period,
			"to_period": to_period,
			"periods": periods,
			"total_recognized_cents": total,
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _compute_period_revenue(
		self,
		obligation: Any,
		period: str,
	) -> int:
		"""Compute the period revenue for an OVER_TIME obligation.

		Returns integer cents (0 if method is OUTPUT/INPUT — caller-driven).
		"""
		method = obligation.recognition_method

		if method == "STRAIGHT_LINE":
			if obligation.start_date is None or obligation.end_date is None:
				log.warning(
					"STRAIGHT_LINE obligation %s has no start/end date; returning 0",
					obligation.id,
				)
				return 0
			total_months = _months_between(obligation.start_date, obligation.end_date)
			# Per-period amount: allocated / months, Decimal round
			per_period = Decimal(obligation.allocated_transaction_price_cents) / Decimal(total_months)
			return int(per_period.to_integral_value(ROUND_HALF_UP))

		elif method == "COMPLETED_CONTRACT":
			# Recognize nothing until fully delivered; then recognize full remaining
			# "Fully delivered" is signalled externally by a satisfy_obligation call
			# covering the full amount.  During period runs we return 0.
			return 0

		elif method in ("OUTPUT", "INPUT"):
			# Percentage-of-completion methods require externally provided metrics.
			# recognize_period() cannot determine the period completion fraction;
			# callers must use satisfy_obligation() directly with the measured amount.
			log.debug(
				"RevRecService: obligation %s uses %s method; skipping automatic recognition",
				obligation.id, method,
			)
			return 0

		else:
			log.warning(
				"RevRecService: unknown recognition_method %r for obligation %s",
				method, obligation.id,
			)
			return 0

	def _recompute_contract_status(self, contract: Any, session: Any) -> None:
		"""Recompute contract status based on obligation statuses."""
		from pgappforge.plugins.erp.finance.revenue_recognition.models import RevRecObligation

		statuses = session.execute(
			select(RevRecObligation.status).where(
				RevRecObligation.contract_id == contract.id
			)
		).scalars().all()

		if not statuses:
			return

		if all(s == "FULLY_SATISFIED" for s in statuses):
			contract.status = "FULLY_SATISFIED"
		elif any(s in ("PARTIALLY", "FULLY_SATISFIED") for s in statuses):
			contract.status = "PARTIALLY_SATISFIED"
		else:
			contract.status = "OPEN"

	def _post_to_gl(
		self,
		obligation: Any,
		recognized_cents: int,
		period: str,
		session: Any,
	) -> str | None:
		"""Post DR Deferred Revenue / CR Revenue to the General Ledger.

		Returns the GL journal entry id on success, None on failure.
		Failures are logged but never propagate — rev rec integrity is paramount.
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
		except ImportError:
			log.debug("RevRecService._post_to_gl: GL plugin not available; skipping GL post")
			return None

		try:
			year_str, month_str = period.split("-")
			posting_date = date(int(year_str), int(month_str), 1)

			svc = GLService()
			# Build a minimal journal batch dict for GL posting
			# Actual implementation depends on GLService.create_batch() API;
			# we call the lower-level method that accepts pre-validated line data.
			result = svc.post_auto_entry(
				session=session,
				tenant_id=obligation.tenant_id,
				posting_date=posting_date,
				description=(
					f"Rev rec: obligation {obligation.id} period {period} "
					f"amount={recognized_cents}"
				),
				lines=[
					{
						"account_code": "2500",  # Deferred Revenue
						"debit_amount": recognized_cents,
						"credit_amount": 0,
					},
					{
						"account_code": "4000",  # Revenue
						"debit_amount": 0,
						"credit_amount": recognized_cents,
					},
				],
				source_document_type="REV_REC_OBLIGATION",
				source_document_id=obligation.id,
			)
			return result.get("entry_id") if isinstance(result, dict) else None

		except Exception as exc:
			log.warning(
				"RevRecService._post_to_gl: GL posting failed for obligation=%s "
				"period=%s amount=%d — %s",
				obligation.id, period, recognized_cents, exc,
			)
			return None


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"finance.rev_rec.recognize_period",
	"Run period revenue recognition for a contract",
)
def _bpm_recognize_period(
	record_ctx: dict,
	session: Any,
	contract_id: str = "",
	period: str = "",
	**kw: Any,
) -> dict:
	"""BPM-callable: recognize revenue for a contract in the given period."""
	try:
		svc = RevRecService()
		entries = svc.recognize_period(contract_id, period, session)
		return {
			"status": "ok",
			"entries_created": len(entries),
			"total_recognized_cents": sum(e.recognized_cents for e in entries),
		}
	except (ContractNotFoundError, RevRecError) as exc:
		log.warning("bpm rev_rec.recognize_period failed: %s", exc)
		return {"status": "error", "message": str(exc)}
	except Exception as exc:
		log.exception("bpm rev_rec.recognize_period unexpected error: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"finance.rev_rec.satisfy_obligation",
	"Satisfy a performance obligation",
)
def _bpm_satisfy_obligation(
	record_ctx: dict,
	session: Any,
	obligation_id: str = "",
	satisfied_cents: int = 0,
	period: str = "",
	gl_post: bool = True,
	**kw: Any,
) -> dict:
	"""BPM-callable: satisfy a specific performance obligation."""
	try:
		svc = RevRecService()
		entry = svc.satisfy_obligation(
			obligation_id=obligation_id,
			satisfied_cents=satisfied_cents,
			period=period,
			session=session,
			gl_post=gl_post,
		)
		return {
			"status": "ok",
			"journal_entry_id": entry.id,
			"recognized_cents": entry.recognized_cents,
		}
	except (ObligationNotFoundError, RevRecError) as exc:
		log.warning("bpm rev_rec.satisfy_obligation failed: %s", exc)
		return {"status": "error", "message": str(exc)}
	except Exception as exc:
		log.exception("bpm rev_rec.satisfy_obligation unexpected error: %s", exc)
		return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"RevRecService",
	"RevRecError",
	"ContractNotFoundError",
	"ObligationNotFoundError",
	"AllocationError",
]
