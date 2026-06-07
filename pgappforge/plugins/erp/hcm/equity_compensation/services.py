"""
pgappforge/plugins/erp/hcm/equity_compensation/services.py

EquityService — stateless business logic for the HCM Equity Compensation plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents (BigInteger)
  - Decimal arithmetic used internally; results rounded ROUND_HALF_UP to int
  - Never pass floats to monetary columns

Public methods:
  create_plan(...)            -> EquityPlan
  create_grant(...)           -> EquityGrant
  process_vesting(...)        -> list[VestingEvent]
  exercise_options(...)       -> EquityExercise
  forfeit_grant(...)          -> EquityGrant
  get_equity_summary(...)     -> dict
  run_vesting_cycle(...)      -> dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class EquityServiceError(Exception):
	"""Base domain error for equity compensation operations."""


class EquityPlanNotFoundError(EquityServiceError):
	pass


class EquityGrantNotFoundError(EquityServiceError):
	pass


class EquityStateError(EquityServiceError):
	"""Invalid state transition."""


class EquityCalculationError(EquityServiceError):
	"""Business rule violation during equity calculation."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today() -> date:
	return datetime.now(timezone.utc).date()


def _round_cents(d: Decimal) -> int:
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("EquityService._emit: could not emit %s: %s", type(event).__name__, exc)


# ---------------------------------------------------------------------------
# BPM process registration
# ---------------------------------------------------------------------------

def _register_bpm() -> None:
	try:
		from pgappforge.plugins.bpm import register

		@register("hcm.equity.process_vesting", "Process equity vesting events for period")
		def _bpm_process_vesting(grant_id: str, as_of_date: str, session: Any) -> dict:
			svc = EquityService()
			d = date.fromisoformat(as_of_date)
			events = svc.process_vesting(grant_id, d, session)
			return {"events_processed": len(events)}

		@register("hcm.equity.exercise_options", "Exercise employee stock options")
		def _bpm_exercise_options(
			grant_id: str,
			shares_to_exercise: int,
			fmv_cents: int,
			session: Any,
			exercise_price_override: int | None = None,
		) -> dict:
			svc = EquityService()
			ex = svc.exercise_options(
				grant_id,
				shares_to_exercise,
				fmv_cents,
				session,
				exercise_price_override=exercise_price_override,
			)
			return {"exercise_id": ex.id, "gain_cents": ex.gain_cents}

	except ImportError:
		log.debug("EquityService: BPM plugin not available, skipping process registration")


# ---------------------------------------------------------------------------
# EquityService
# ---------------------------------------------------------------------------

class EquityService:
	"""Stateless equity compensation domain service.

	Instantiate once per application (no instance state).
	All public methods accept a SQLAlchemy Session as an explicit argument.

	Default withholding rate: 30% of gain.  Override via
	plan.metadata_['withholding_rate'] as a string decimal e.g. "0.25".
	"""

	DEFAULT_WITHHOLDING_RATE = Decimal("0.30")

	# ------------------------------------------------------------------
	# create_plan
	# ------------------------------------------------------------------

	def create_plan(
		self,
		name: str,
		plan_type: str,
		total_shares: int,
		tenant_id: str,
		session: Any,
		*,
		vesting_period_months: int = 48,
		cliff_months: int = 12,
		exercise_price_cents: int = 0,
		vesting_schedule_type: str = "GRADED",
		expiry_years: int = 10,
		entity_id: str | None = None,
		plan_currency: str = "USD",
	) -> Any:
		"""Create and persist a new equity plan.

		Args:
			name: Human-readable plan name.
			plan_type: STOCK_OPTION | RSU | ESPP | SAR.
			total_shares: Maximum shares the plan may issue.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session (caller commits).
			vesting_period_months: Total vesting period in months (default 48).
			cliff_months: Months before first vesting event (default 12).
			exercise_price_cents: Per-share exercise price in cents (0 for RSUs).
			vesting_schedule_type: CLIFF | GRADED | IMMEDIATE (default GRADED).
			expiry_years: Options expire this many years after grant date (default 10).
			entity_id: Legal entity scope; None = global plan.
			plan_currency: ISO 4217 currency code (default USD).

		Returns:
			Persisted EquityPlan.

		Raises:
			EquityCalculationError: Invalid plan_type or vesting_schedule_type.
		"""
		from pgappforge.plugins.erp.hcm.equity_compensation.models import EquityPlan
		from pgappforge.plugins.erp.hcm.equity_compensation.events import EquityPlanCreatedEvent

		valid_types = {"STOCK_OPTION", "RSU", "ESPP", "SAR"}
		if plan_type not in valid_types:
			raise EquityCalculationError(f"plan_type must be one of {valid_types}; got {plan_type!r}")
		valid_schedules = {"CLIFF", "GRADED", "IMMEDIATE"}
		if vesting_schedule_type not in valid_schedules:
			raise EquityCalculationError(
				f"vesting_schedule_type must be one of {valid_schedules}; got {vesting_schedule_type!r}"
			)

		plan = EquityPlan(
			tenant_id=tenant_id,
			entity_id=entity_id,
			name=name,
			plan_type=plan_type,
			total_shares_authorized=total_shares,
			total_shares_issued=0,
			vesting_schedule_type=vesting_schedule_type,
			vesting_period_months=vesting_period_months,
			cliff_months=cliff_months,
			exercise_price_cents=exercise_price_cents,
			plan_currency=plan_currency,
			expiry_years=expiry_years,
			is_active=True,
		)
		session.add(plan)
		session.flush()

		_emit(
			EquityPlanCreatedEvent(
				aggregate_id=plan.id,
				aggregate_type="EquityPlan",
				tenant_id=tenant_id,
				plan_id=plan.id,
				plan_type=plan_type,
			),
			session,
		)
		log.info(
			"EquityService.create_plan: plan=%s type=%s shares=%d",
			plan.id, plan_type, total_shares,
		)
		return plan

	# ------------------------------------------------------------------
	# create_grant
	# ------------------------------------------------------------------

	def create_grant(
		self,
		employee_id: str,
		plan_id: str,
		grant_date: date,
		shares: int,
		tenant_id: str,
		session: Any,
		*,
		grant_fmv_cents: int | None = None,
		approved_by: str | None = None,
	) -> Any:
		"""Issue an equity grant to an employee and generate the vesting schedule.

		Vesting schedule is generated according to plan.vesting_schedule_type:
		  IMMEDIATE: one VestingEvent on grant_date with all shares.
		  CLIFF: one VestingEvent on grant_date + cliff_months with all shares.
		  GRADED: cliff event + monthly events after cliff proportionally.

		For GRADED:
		  cliff_shares = shares × (cliff_months / vesting_period_months) — rounded half-up.
		  monthly_shares = (shares - cliff_shares) / (vesting_period_months - cliff_months)
		    per month — last month absorbs rounding remainder.

		Args:
			employee_id: Employee identifier.
			plan_id: UUID of the EquityPlan.
			grant_date: Date the grant is issued.
			shares: Number of shares granted.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.
			grant_fmv_cents: FMV per share on grant date (for tax purposes).
			approved_by: User who approved the grant.

		Returns:
			Persisted EquityGrant (vesting schedule is flushed to session).

		Raises:
			EquityPlanNotFoundError: Plan not found.
			EquityCalculationError: Plan inactive or insufficient shares.
		"""
		from pgappforge.plugins.erp.hcm.equity_compensation.models import (
			EquityGrant,
			EquityPlan,
			VestingEvent,
		)
		from pgappforge.plugins.erp.hcm.equity_compensation.events import EquityGrantCreatedEvent

		plan: Any = session.get(EquityPlan, plan_id)
		if plan is None:
			raise EquityPlanNotFoundError(f"EquityPlan {plan_id!r} not found")
		if not plan.is_active:
			raise EquityCalculationError(f"EquityPlan {plan_id!r} is not active")
		remaining = plan.total_shares_authorized - plan.total_shares_issued
		if shares > remaining:
			raise EquityCalculationError(
				f"Plan {plan_id!r} has {remaining} shares remaining; requested {shares}"
			)

		expiry_date = grant_date + timedelta(days=plan.expiry_years * 365)

		grant = EquityGrant(
			tenant_id=tenant_id,
			employee_id=employee_id,
			plan_id=plan_id,
			grant_date=grant_date,
			shares_granted=shares,
			vested_shares=0,
			unvested_shares=shares,
			status="ACTIVE",
			grant_fmv_cents=grant_fmv_cents,
			expiry_date=expiry_date,
			approved_by=approved_by,
		)
		session.add(grant)
		session.flush()

		# Update plan issued count
		plan.total_shares_issued = plan.total_shares_issued + shares
		plan.updated_at = datetime.now(timezone.utc)

		# Generate vesting schedule
		schedule_type = plan.vesting_schedule_type
		vesting_period = plan.vesting_period_months
		cliff = plan.cliff_months

		if schedule_type == "IMMEDIATE":
			session.add(VestingEvent(
				tenant_id=tenant_id,
				grant_id=grant.id,
				vest_date=grant_date,
				shares_vested=shares,
				is_cliff=False,
				is_processed=False,
			))

		elif schedule_type == "CLIFF":
			cliff_date = _add_months(grant_date, cliff)
			session.add(VestingEvent(
				tenant_id=tenant_id,
				grant_id=grant.id,
				vest_date=cliff_date,
				shares_vested=shares,
				is_cliff=True,
				is_processed=False,
			))

		elif schedule_type == "GRADED":
			cliff_shares = _round_cents(
				Decimal(shares) * Decimal(cliff) / Decimal(vesting_period)
			)
			post_cliff_shares = shares - cliff_shares
			post_cliff_months = vesting_period - cliff

			# Cliff event
			cliff_date = _add_months(grant_date, cliff)
			session.add(VestingEvent(
				tenant_id=tenant_id,
				grant_id=grant.id,
				vest_date=cliff_date,
				shares_vested=cliff_shares,
				is_cliff=True,
				is_processed=False,
			))

			# Monthly events after cliff
			if post_cliff_months > 0 and post_cliff_shares > 0:
				monthly_shares = _round_cents(
					Decimal(post_cliff_shares) / Decimal(post_cliff_months)
				)
				# Ensure all shares are accounted for; last event absorbs remainder
				distributed = 0
				for month_offset in range(1, post_cliff_months + 1):
					vest_date = _add_months(cliff_date, month_offset)
					if month_offset == post_cliff_months:
						# Last event: absorb remainder
						month_shares = post_cliff_shares - distributed
					else:
						month_shares = monthly_shares
					if month_shares <= 0:
						continue
					session.add(VestingEvent(
						tenant_id=tenant_id,
						grant_id=grant.id,
						vest_date=vest_date,
						shares_vested=month_shares,
						is_cliff=False,
						is_processed=False,
					))
					distributed += month_shares

		session.flush()

		_emit(
			EquityGrantCreatedEvent(
				aggregate_id=grant.id,
				aggregate_type="EquityGrant",
				tenant_id=tenant_id,
				grant_id=grant.id,
				employee_id=employee_id,
				shares=shares,
				plan_type=plan.plan_type,
			),
			session,
		)
		log.info(
			"EquityService.create_grant: grant=%s employee=%s shares=%d schedule=%s",
			grant.id, employee_id, shares, schedule_type,
		)
		return grant

	# ------------------------------------------------------------------
	# process_vesting
	# ------------------------------------------------------------------

	def process_vesting(
		self,
		grant_id: str,
		as_of_date: date,
		session: Any,
	) -> list[Any]:
		"""Process all pending vesting events up to as_of_date for a grant.

		For each unprocessed VestingEvent where vest_date <= as_of_date:
		  - Increments grant.vested_shares
		  - Decrements grant.unvested_shares
		  - Marks the event processed with processed_at timestamp
		  - Emits SharesVestedEvent

		Args:
			grant_id: UUID of the EquityGrant.
			as_of_date: Process events up to and including this date.
			session: SQLAlchemy session.

		Returns:
			List of processed VestingEvent rows.

		Raises:
			EquityGrantNotFoundError: Grant not found.
		"""
		from pgappforge.plugins.erp.hcm.equity_compensation.models import EquityGrant, VestingEvent
		from pgappforge.plugins.erp.hcm.equity_compensation.events import SharesVestedEvent

		grant: Any = session.get(EquityGrant, grant_id)
		if grant is None:
			raise EquityGrantNotFoundError(f"EquityGrant {grant_id!r} not found")
		if grant.status == "FORFEITED":
			raise EquityStateError(f"EquityGrant {grant_id!r} is FORFEITED; cannot process vesting")

		pending = session.execute(
			sa.select(VestingEvent)
			.where(VestingEvent.grant_id == grant_id)
			.where(VestingEvent.vest_date <= as_of_date)
			.where(VestingEvent.is_processed == False)  # noqa: E712
			.order_by(VestingEvent.vest_date)
		).scalars().all()

		processed: list[Any] = []
		now = datetime.now(timezone.utc)

		for event in pending:
			assert event.shares_vested > 0, f"VestingEvent {event.id} has non-positive shares"
			grant.vested_shares = grant.vested_shares + event.shares_vested
			grant.unvested_shares = grant.unvested_shares - event.shares_vested
			assert grant.unvested_shares >= 0, "unvested_shares went negative — data integrity error"

			event.is_processed = True
			event.processed_at = now
			event.updated_at = now

			_emit(
				SharesVestedEvent(
					aggregate_id=grant_id,
					aggregate_type="EquityGrant",
					tenant_id=grant.tenant_id,
					grant_id=grant_id,
					employee_id=grant.employee_id,
					shares_vested=event.shares_vested,
					vest_date=event.vest_date.isoformat(),
				),
				session,
			)
			processed.append(event)

		grant.updated_at = now
		session.flush()

		log.info(
			"EquityService.process_vesting: grant=%s as_of=%s events=%d",
			grant_id, as_of_date, len(processed),
		)
		return processed

	# ------------------------------------------------------------------
	# exercise_options
	# ------------------------------------------------------------------

	def exercise_options(
		self,
		grant_id: str,
		shares_to_exercise: int,
		fmv_cents: int,
		session: Any,
		*,
		exercise_price_override: int | None = None,
	) -> Any:
		"""Exercise vested stock options or RSUs.

		Computes gain and withholding tax, creates an EquityExercise record,
		and decrements grant.vested_shares.

		gain_cents = (fmv_cents - exercise_price) × shares_to_exercise
		withholding_tax = ROUND_HALF_UP(gain × withholding_rate)
		  where withholding_rate defaults to 30% but can be overridden via
		  plan.metadata_['withholding_rate'] (string decimal e.g. "0.25").
		net_proceeds = gain_cents - withholding_tax_cents

		Args:
			grant_id: UUID of the EquityGrant.
			shares_to_exercise: Number of vested shares to exercise.
			fmv_cents: Fair market value per share on exercise date (cents).
			session: SQLAlchemy session.
			exercise_price_override: Override plan exercise price (cents per share).

		Returns:
			Persisted EquityExercise.

		Raises:
			EquityGrantNotFoundError: Grant not found.
			EquityStateError: Grant not ACTIVE or insufficient vested shares.
		"""
		from pgappforge.plugins.erp.hcm.equity_compensation.models import (
			EquityGrant,
			EquityPlan,
			EquityExercise,
		)
		from pgappforge.plugins.erp.hcm.equity_compensation.events import OptionsExercisedEvent

		grant: Any = session.get(EquityGrant, grant_id)
		if grant is None:
			raise EquityGrantNotFoundError(f"EquityGrant {grant_id!r} not found")
		if grant.status not in ("ACTIVE",):
			raise EquityStateError(
				f"EquityGrant {grant_id!r} is {grant.status!r}; must be ACTIVE to exercise"
			)
		if grant.vested_shares < shares_to_exercise:
			raise EquityStateError(
				f"Insufficient vested shares: {grant.vested_shares} vested, "
				f"{shares_to_exercise} requested"
			)

		plan: Any = session.get(EquityPlan, grant.plan_id)
		assert plan is not None, f"EquityPlan {grant.plan_id!r} not found for grant {grant_id!r}"

		exercise_price = exercise_price_override if exercise_price_override is not None else (
			plan.exercise_price_cents or 0
		)

		gain = (fmv_cents - exercise_price) * shares_to_exercise
		assert isinstance(gain, int), "gain must be integer"

		# Withholding rate from plan metadata or default
		wh_rate_str = (plan.metadata_ or {}).get("withholding_rate", None)
		wh_rate = Decimal(wh_rate_str) if wh_rate_str else self.DEFAULT_WITHHOLDING_RATE
		withholding_tax = _round_cents(Decimal(gain) * wh_rate)
		net_proceeds = gain - withholding_tax

		exercise = EquityExercise(
			tenant_id=grant.tenant_id,
			employee_id=grant.employee_id,
			grant_id=grant_id,
			exercise_date=_today(),
			shares_exercised=shares_to_exercise,
			exercise_price_cents=exercise_price,
			fmv_cents=fmv_cents,
			gain_cents=gain,
			withholding_tax_cents=withholding_tax,
			net_proceeds_cents=net_proceeds,
		)
		session.add(exercise)

		grant.vested_shares = grant.vested_shares - shares_to_exercise
		if grant.vested_shares == 0 and grant.unvested_shares == 0:
			grant.status = "EXERCISED"
		grant.updated_at = datetime.now(timezone.utc)

		session.flush()

		_emit(
			OptionsExercisedEvent(
				aggregate_id=exercise.id,
				aggregate_type="EquityExercise",
				tenant_id=grant.tenant_id,
				exercise_id=exercise.id,
				grant_id=grant_id,
				employee_id=grant.employee_id,
				shares=shares_to_exercise,
				gain_cents=gain,
			),
			session,
		)
		log.info(
			"EquityService.exercise_options: grant=%s employee=%s shares=%d gain=%d¢",
			grant_id, grant.employee_id, shares_to_exercise, gain,
		)
		return exercise

	# ------------------------------------------------------------------
	# forfeit_grant
	# ------------------------------------------------------------------

	def forfeit_grant(
		self,
		grant_id: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Forfeit an equity grant — unvested shares returned to the plan pool.

		Sets grant.status = FORFEITED.  Returns shares to plan.total_shares_issued
		counter for the unvested portion only (vested shares already belong to
		the employee).

		Args:
			grant_id: UUID of the EquityGrant.
			reason: Human-readable reason for forfeiture.
			session: SQLAlchemy session.

		Returns:
			Updated EquityGrant.

		Raises:
			EquityGrantNotFoundError: Grant not found.
			EquityStateError: Grant already forfeited or exercised.
		"""
		from pgappforge.plugins.erp.hcm.equity_compensation.models import EquityGrant, EquityPlan
		from pgappforge.plugins.erp.hcm.equity_compensation.events import GrantForfeitedEvent

		grant: Any = session.get(EquityGrant, grant_id)
		if grant is None:
			raise EquityGrantNotFoundError(f"EquityGrant {grant_id!r} not found")
		if grant.status in ("FORFEITED", "EXERCISED"):
			raise EquityStateError(
				f"EquityGrant {grant_id!r} is already {grant.status!r}"
			)

		unvested = grant.unvested_shares
		grant.status = "FORFEITED"
		grant.notes = (grant.notes or "") + f"\n[FORFEITED] {reason}"
		grant.updated_at = datetime.now(timezone.utc)

		# Return unvested shares to plan pool
		if unvested > 0:
			plan: Any = session.get(EquityPlan, grant.plan_id)
			if plan is not None:
				plan.total_shares_issued = max(0, plan.total_shares_issued - unvested)
				plan.updated_at = datetime.now(timezone.utc)

		session.flush()

		_emit(
			GrantForfeitedEvent(
				aggregate_id=grant_id,
				aggregate_type="EquityGrant",
				tenant_id=grant.tenant_id,
				grant_id=grant_id,
				employee_id=grant.employee_id,
				unvested_shares=unvested,
			),
			session,
		)
		log.info(
			"EquityService.forfeit_grant: grant=%s employee=%s unvested=%d reason=%r",
			grant_id, grant.employee_id, unvested, reason,
		)
		return grant

	# ------------------------------------------------------------------
	# get_equity_summary
	# ------------------------------------------------------------------

	def get_equity_summary(
		self,
		employee_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return equity portfolio summary for an employee.

		Returns:
		  {
		    employee_id,
		    total_vested_shares,
		    total_unvested_shares,
		    grants: [
		      {grant_id, plan_id, plan_type, shares_granted, vested_shares,
		       unvested_shares, status, grant_date, expiry_date}
		    ],
		  }
		"""
		from pgappforge.plugins.erp.hcm.equity_compensation.models import EquityGrant, EquityPlan

		grants = session.execute(
			sa.select(EquityGrant)
			.where(EquityGrant.tenant_id == tenant_id)
			.where(EquityGrant.employee_id == employee_id)
			.where(EquityGrant.status == "ACTIVE")
			.order_by(EquityGrant.grant_date)
		).scalars().all()

		total_vested = sum(g.vested_shares for g in grants)
		total_unvested = sum(g.unvested_shares for g in grants)

		grant_summaries: list[dict[str, Any]] = []
		for g in grants:
			plan: Any = session.get(EquityPlan, g.plan_id)
			grant_summaries.append({
				"grant_id": g.id,
				"plan_id": g.plan_id,
				"plan_type": plan.plan_type if plan else None,
				"shares_granted": g.shares_granted,
				"vested_shares": g.vested_shares,
				"unvested_shares": g.unvested_shares,
				"status": g.status,
				"grant_date": g.grant_date.isoformat() if g.grant_date else None,
				"expiry_date": g.expiry_date.isoformat() if g.expiry_date else None,
				"grant_fmv_cents": g.grant_fmv_cents,
			})

		return {
			"employee_id": employee_id,
			"total_vested_shares": total_vested,
			"total_unvested_shares": total_unvested,
			"grants": grant_summaries,
		}

	# ------------------------------------------------------------------
	# run_vesting_cycle
	# ------------------------------------------------------------------

	def run_vesting_cycle(
		self,
		tenant_id: str,
		session: Any,
		*,
		as_of_date: date | None = None,
	) -> dict[str, Any]:
		"""Process all pending vesting events for a tenant up to as_of_date.

		Iterates all ACTIVE grants with unprocessed VestingEvents and calls
		process_vesting() for each.

		Args:
			tenant_id: Tenant UUID.
			session: SQLAlchemy session (caller commits).
			as_of_date: Process events up to this date (default: today).

		Returns:
		  {
		    grants_processed: int,
		    events_vested: int,
		    total_shares_vested: int,
		  }
		"""
		from pgappforge.plugins.erp.hcm.equity_compensation.models import EquityGrant, VestingEvent

		effective_date = as_of_date or _today()

		# Find grant_ids that have pending events up to effective_date
		grant_ids = session.execute(
			sa.select(sa.distinct(VestingEvent.grant_id))
			.join(EquityGrant, VestingEvent.grant_id == EquityGrant.id)
			.where(EquityGrant.tenant_id == tenant_id)
			.where(EquityGrant.status == "ACTIVE")
			.where(VestingEvent.vest_date <= effective_date)
			.where(VestingEvent.is_processed == False)  # noqa: E712
		).scalars().all()

		grants_processed = 0
		events_vested = 0
		total_shares_vested = 0

		for grant_id in grant_ids:
			try:
				processed = self.process_vesting(grant_id, effective_date, session)
				if processed:
					grants_processed += 1
					events_vested += len(processed)
					total_shares_vested += sum(e.shares_vested for e in processed)
			except Exception as exc:
				log.warning(
					"EquityService.run_vesting_cycle: failed for grant %s: %s",
					grant_id, exc,
				)

		log.info(
			"EquityService.run_vesting_cycle: tenant=%s as_of=%s grants=%d events=%d shares=%d",
			tenant_id, effective_date, grants_processed, events_vested, total_shares_vested,
		)
		return {
			"grants_processed": grants_processed,
			"events_vested": events_vested,
			"total_shares_vested": total_shares_vested,
		}


# ---------------------------------------------------------------------------
# Month arithmetic helper
# ---------------------------------------------------------------------------

def _add_months(d: date, months: int) -> date:
	"""Add *months* calendar months to date *d*, clamping to end-of-month."""
	month = d.month - 1 + months
	year = d.year + month // 12
	month = month % 12 + 1
	import calendar
	day = min(d.day, calendar.monthrange(year, month)[1])
	return date(year, month, day)


# Attempt BPM registration at import time (best-effort)
try:
	_register_bpm()
except Exception as _exc:
	log.debug("EquityService: BPM registration failed: %s", _exc)


__all__ = [
	"EquityService",
	"EquityServiceError",
	"EquityPlanNotFoundError",
	"EquityGrantNotFoundError",
	"EquityStateError",
	"EquityCalculationError",
]
