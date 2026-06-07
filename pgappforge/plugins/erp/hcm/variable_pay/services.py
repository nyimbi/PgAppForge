"""
pgappforge/plugins/erp/hcm/variable_pay/services.py

VariablePayService — stateless business logic for the HCM Variable Pay plugin.

All methods accept an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents
  - Decimal arithmetic used internally for tier/rate computations
  - attainment_pct stored as Numeric(8,4): e.g. 105.2500 = 105.25%

Public methods:
  assign_quota(employee_id, plan_id, period, quota_cents, tenant_id, session) -> EmployeeQuota
  record_attainment(quota_id, actual_cents, session)                          -> EmployeeQuota
  calculate_commission(quota_id, session)                                     -> CommissionCalculation
  create_payout(calculation_id, session)                                      -> CommissionPayout
  approve_payout(payout_id, approver_id, session)                             -> CommissionPayout
  mark_paid(payout_id, payrun_id, session)                                    -> CommissionPayout
  get_employee_dashboard(employee_id, period, tenant_id, session)             -> dict
  get_plan_analytics(plan_id, period, session)                                -> dict

BPM-registered actions:
  hcm.variable_pay.calculate_commission
  hcm.variable_pay.approve_payout
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class VariablePayError(Exception):
	"""Base domain error for variable pay operations."""


class QuotaNotFoundError(VariablePayError):
	pass


class PayoutNotFoundError(VariablePayError):
	pass


class VariablePayStateError(VariablePayError):
	"""Invalid state transition."""


class CommissionCalculationError(VariablePayError):
	"""Business rule violation during commission computation."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(timezone.utc)


def _round_cents(d: Decimal) -> int:
	return int(d.to_integral_value(rounding=ROUND_HALF_UP))


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception:
		log.debug("variable_pay._emit: could not emit %s", type(event).__name__, exc_info=True)


def _compute_tier_commission(
	quota_cents: int,
	attainment_pct: Decimal,
	tiers: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
	"""Apply tiered commission rates to quota_cents given attainment_pct.

	Returns (base_commission_cents, breakdown_list).

	Each tier dict: {min_pct, max_pct, rate_pct, description?}

	Algorithm: for each tier, clamp attainment_pct into the tier bracket,
	compute what fraction of quota that represents, apply rate_pct.
	"""
	total = Decimal(0)
	breakdown: list[dict[str, Any]] = []
	q = Decimal(quota_cents)

	for tier in sorted(tiers, key=lambda t: t.get("min_pct", 0)):
		t_min = Decimal(str(tier.get("min_pct", 0)))
		t_max = Decimal(str(tier.get("max_pct", 100)))
		rate = Decimal(str(tier.get("rate_pct", 0))) / Decimal("100")

		# How much attainment falls within this tier?
		effective_min = min(attainment_pct, t_min)
		effective_max = min(attainment_pct, t_max)
		tier_attainment_span = max(Decimal(0), effective_max - t_min)

		if tier_attainment_span <= 0:
			continue

		# quota_portion = quota × (tier_span / 100)
		quota_portion = q * (tier_attainment_span / Decimal("100"))
		commission = quota_portion * rate
		commission_cents = _round_cents(commission)
		total += commission

		breakdown.append({
			"tier_min_pct": float(t_min),
			"tier_max_pct": float(t_max),
			"rate_pct": float(tier.get("rate_pct", 0)),
			"attainment_span_pct": float(tier_attainment_span),
			"quota_portion_cents": _round_cents(quota_portion),
			"commission_cents": commission_cents,
			"description": tier.get("description", ""),
		})

	return _round_cents(total), breakdown


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class VariablePayService:
	"""Stateless variable pay service.

	All methods are synchronous; async wrappers can be added by the caller.
	"""

	# ------------------------------------------------------------------
	# Quota management
	# ------------------------------------------------------------------

	@staticmethod
	def assign_quota(
		employee_id: str,
		plan_id: str,
		period: str,
		quota_cents: int,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Assign a quota to an employee for a plan period.

		Raises VariablePayError if a quota for (tenant_id, employee_id, plan_id, period)
		already exists.
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import EmployeeQuota, IncentivePlan
		from pgappforge.plugins.erp.hcm.variable_pay.events import QuotaAssignedEvent

		assert quota_cents > 0, "quota_cents must be positive"

		# Validate plan exists
		plan = session.execute(
			sa.select(IncentivePlan).where(IncentivePlan.id == plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise VariablePayError(f"IncentivePlan {plan_id!r} not found")

		# Check uniqueness
		existing = session.execute(
			sa.select(EmployeeQuota).where(
				EmployeeQuota.tenant_id == tenant_id,
				EmployeeQuota.employee_id == employee_id,
				EmployeeQuota.plan_id == plan_id,
				EmployeeQuota.period == period,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise VariablePayError(
				f"Quota already exists for employee={employee_id!r} "
				f"plan={plan_id!r} period={period!r}"
			)

		quota = EmployeeQuota(
			tenant_id=tenant_id,
			employee_id=employee_id,
			plan_id=plan_id,
			period=period,
			quota_cents=quota_cents,
			attained_cents=0,
			attainment_pct=Decimal("0.0"),
			status="ACTIVE",
		)
		session.add(quota)
		session.flush()

		_emit(QuotaAssignedEvent(
			aggregate_id=quota.id,
			aggregate_type="EmployeeQuota",
			tenant_id=tenant_id,
			quota_id=quota.id,
			employee_id=employee_id,
			amount_cents=quota_cents,
			period=period,
		), session)

		log.info(
			"VariablePayService.assign_quota: quota=%s employee=%s period=%s cents=%d",
			quota.id, employee_id, period, quota_cents,
		)
		return quota

	@staticmethod
	def record_attainment(
		quota_id: str,
		actual_cents: int,
		session: Any,
	) -> Any:
		"""Cumulatively add actual_cents to a quota's attained_cents.

		Recomputes attainment_pct = attained_cents / quota_cents * 100.
		Emits AttainmentRecordedEvent.
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import EmployeeQuota
		from pgappforge.plugins.erp.hcm.variable_pay.events import AttainmentRecordedEvent

		assert actual_cents >= 0, "actual_cents must be non-negative"

		quota = session.execute(
			sa.select(EmployeeQuota).where(EmployeeQuota.id == quota_id)
		).scalar_one_or_none()
		if quota is None:
			raise QuotaNotFoundError(f"EmployeeQuota {quota_id!r} not found")
		if quota.status != "ACTIVE":
			raise VariablePayStateError(
				f"Cannot record attainment on quota {quota_id!r} with status={quota.status!r}"
			)

		quota.attained_cents = quota.attained_cents + actual_cents
		if quota.quota_cents > 0:
			quota.attainment_pct = Decimal(quota.attained_cents) / Decimal(quota.quota_cents) * Decimal("100")
		else:
			quota.attainment_pct = Decimal("0.0")

		session.flush()

		_emit(AttainmentRecordedEvent(
			aggregate_id=quota.id,
			aggregate_type="EmployeeQuota",
			tenant_id=quota.tenant_id,
			quota_id=quota.id,
			actual_cents=quota.attained_cents,
			attainment_pct=float(quota.attainment_pct),
		), session)

		log.info(
			"VariablePayService.record_attainment: quota=%s attained=%d pct=%.4f",
			quota.id, quota.attained_cents, float(quota.attainment_pct),
		)
		return quota

	# ------------------------------------------------------------------
	# Commission calculation
	# ------------------------------------------------------------------

	@staticmethod
	def calculate_commission(
		quota_id: str,
		session: Any,
	) -> Any:
		"""Compute tiered commission for a quota, applying accelerator if applicable.

		Algorithm:
		1. Walk plan.tiers in ascending min_pct order.
		2. For each tier, compute the quota portion within that bracket and apply rate.
		3. If attainment_pct >= accelerator_threshold_pct, compute the above-threshold
		   portion, multiply by (accelerator_multiplier - 1) to get incremental bonus.
		4. Create CommissionCalculation with full breakdown.
		5. Create CommissionPayout in PENDING status.

		Emits CommissionCalculatedEvent and (if accelerator applied) AcceleratorAppliedEvent.
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import (
			CommissionCalculation,
			CommissionPayout,
			EmployeeQuota,
			IncentivePlan,
		)
		from pgappforge.plugins.erp.hcm.variable_pay.events import (
			AcceleratorAppliedEvent,
			CommissionCalculatedEvent,
		)

		quota = session.execute(
			sa.select(EmployeeQuota).where(EmployeeQuota.id == quota_id)
		).scalar_one_or_none()
		if quota is None:
			raise QuotaNotFoundError(f"EmployeeQuota {quota_id!r} not found")

		plan = session.execute(
			sa.select(IncentivePlan).where(IncentivePlan.id == quota.plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise CommissionCalculationError(f"IncentivePlan {quota.plan_id!r} not found")

		tiers: list[dict[str, Any]] = plan.tiers or []
		if not tiers:
			raise CommissionCalculationError(
				f"IncentivePlan {plan.id!r} has no tiers defined"
			)

		attainment_pct = Decimal(str(quota.attainment_pct))
		base_commission_cents, tier_breakdown = _compute_tier_commission(
			quota.quota_cents, attainment_pct, tiers
		)

		# Accelerator bonus
		accelerator_bonus_cents = 0
		accelerator_detail: dict[str, Any] = {"applied": False}
		threshold = plan.accelerator_threshold_pct
		multiplier = Decimal(str(plan.accelerator_multiplier)) if plan.accelerator_multiplier else Decimal("1.0")

		if threshold is not None and attainment_pct >= Decimal(str(threshold)) and multiplier > Decimal("1.0"):
			# Bonus = commission on above-threshold portion × (multiplier - 1)
			above_threshold_pct = attainment_pct - Decimal(str(threshold))
			quota_above = Decimal(quota.quota_cents) * (above_threshold_pct / Decimal("100"))

			# Find the rate for the above-threshold tier
			above_rate = Decimal("0")
			for tier in sorted(tiers, key=lambda t: t.get("min_pct", 0), reverse=True):
				if Decimal(str(tier.get("min_pct", 0))) <= attainment_pct:
					above_rate = Decimal(str(tier.get("rate_pct", 0))) / Decimal("100")
					break

			incremental_bonus = quota_above * above_rate * (multiplier - Decimal("1.0"))
			accelerator_bonus_cents = _round_cents(incremental_bonus)
			accelerator_detail = {
				"applied": True,
				"threshold_pct": float(threshold),
				"multiplier": float(multiplier),
				"above_threshold_pct": float(above_threshold_pct),
				"bonus_cents": accelerator_bonus_cents,
			}

			_emit(AcceleratorAppliedEvent(
				aggregate_id=quota.id,
				aggregate_type="EmployeeQuota",
				tenant_id=quota.tenant_id,
				quota_id=quota.id,
				attainment_pct=float(attainment_pct),
				multiplier=float(multiplier),
			), session)

		total_commission_cents = base_commission_cents + accelerator_bonus_cents

		breakdown = {
			"tiers": tier_breakdown,
			"accelerator": accelerator_detail,
			"quota_cents": quota.quota_cents,
			"attained_cents": quota.attained_cents,
			"attainment_pct": float(attainment_pct),
		}

		calc = CommissionCalculation(
			tenant_id=quota.tenant_id,
			quota_id=quota.id,
			employee_id=quota.employee_id,
			period=quota.period,
			base_commission_cents=base_commission_cents,
			accelerator_bonus_cents=accelerator_bonus_cents,
			total_commission_cents=total_commission_cents,
			calculation_breakdown=breakdown,
			calculated_at=_now(),
		)
		session.add(calc)
		session.flush()

		# Auto-create payout in PENDING
		payout = CommissionPayout(
			tenant_id=quota.tenant_id,
			calculation_id=calc.id,
			employee_id=quota.employee_id,
			period=quota.period,
			amount_cents=total_commission_cents,
			status="PENDING",
		)
		session.add(payout)
		session.flush()

		_emit(CommissionCalculatedEvent(
			aggregate_id=calc.id,
			aggregate_type="CommissionCalculation",
			tenant_id=quota.tenant_id,
			employee_id=quota.employee_id,
			period=quota.period,
			commission_cents=total_commission_cents,
		), session)

		log.info(
			"VariablePayService.calculate_commission: quota=%s calc=%s total_cents=%d",
			quota.id, calc.id, total_commission_cents,
		)
		return calc

	# ------------------------------------------------------------------
	# Payout lifecycle
	# ------------------------------------------------------------------

	@staticmethod
	def approve_payout(
		payout_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Transition payout PENDING → APPROVED.

		Raises VariablePayStateError if current status is not PENDING.
		Emits CommissionApprovedEvent.
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import CommissionPayout
		from pgappforge.plugins.erp.hcm.variable_pay.events import CommissionApprovedEvent

		payout = session.execute(
			sa.select(CommissionPayout).where(CommissionPayout.id == payout_id)
		).scalar_one_or_none()
		if payout is None:
			raise PayoutNotFoundError(f"CommissionPayout {payout_id!r} not found")
		if payout.status != "PENDING":
			raise VariablePayStateError(
				f"Payout {payout_id!r} is {payout.status!r}; must be PENDING to approve"
			)

		payout.status = "APPROVED"
		payout.approved_by = approver_id
		payout.approved_at = _now()
		session.flush()

		_emit(CommissionApprovedEvent(
			aggregate_id=payout.id,
			aggregate_type="CommissionPayout",
			tenant_id=payout.tenant_id,
			payout_id=payout.id,
			employee_id=payout.employee_id,
			amount_cents=payout.amount_cents,
			approved_by=approver_id,
		), session)

		log.info(
			"VariablePayService.approve_payout: payout=%s approved_by=%s",
			payout.id, approver_id,
		)
		return payout

	@staticmethod
	def mark_paid(
		payout_id: str,
		payrun_id: str,
		session: Any,
	) -> Any:
		"""Transition payout APPROVED → PAID.

		Raises VariablePayStateError if current status is not APPROVED.
		Emits CommissionPaidEvent.
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import CommissionPayout
		from pgappforge.plugins.erp.hcm.variable_pay.events import CommissionPaidEvent

		payout = session.execute(
			sa.select(CommissionPayout).where(CommissionPayout.id == payout_id)
		).scalar_one_or_none()
		if payout is None:
			raise PayoutNotFoundError(f"CommissionPayout {payout_id!r} not found")
		if payout.status != "APPROVED":
			raise VariablePayStateError(
				f"Payout {payout_id!r} is {payout.status!r}; must be APPROVED to mark paid"
			)

		payout.status = "PAID"
		payout.payrun_id = payrun_id
		payout.paid_at = _now()
		session.flush()

		_emit(CommissionPaidEvent(
			aggregate_id=payout.id,
			aggregate_type="CommissionPayout",
			tenant_id=payout.tenant_id,
			payout_id=payout.id,
			employee_id=payout.employee_id,
			amount_cents=payout.amount_cents,
			payrun_id=payrun_id,
		), session)

		log.info(
			"VariablePayService.mark_paid: payout=%s payrun=%s",
			payout.id, payrun_id,
		)
		return payout

	# ------------------------------------------------------------------
	# Analytics / dashboards
	# ------------------------------------------------------------------

	@staticmethod
	def get_employee_dashboard(
		employee_id: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return quota + commission summary for one employee in a period.

		Returns dict with keys:
		  quota_cents, attained_cents, attainment_pct,
		  commission_earned_cents, payout_status
		If no quota found, returns zeros with status=None.
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import (
			CommissionCalculation,
			CommissionPayout,
			EmployeeQuota,
		)

		quota = session.execute(
			sa.select(EmployeeQuota).where(
				EmployeeQuota.tenant_id == tenant_id,
				EmployeeQuota.employee_id == employee_id,
				EmployeeQuota.period == period,
				EmployeeQuota.status == "ACTIVE",
			)
		).scalar_one_or_none()

		if quota is None:
			return {
				"employee_id": employee_id,
				"period": period,
				"quota_cents": 0,
				"attained_cents": 0,
				"attainment_pct": 0.0,
				"commission_earned_cents": 0,
				"payout_status": None,
			}

		# Latest calculation
		calc = session.execute(
			sa.select(CommissionCalculation)
			.where(CommissionCalculation.quota_id == quota.id)
			.order_by(CommissionCalculation.calculated_at.desc())
		).scalar_one_or_none()

		commission_cents = calc.total_commission_cents if calc else 0
		payout_status = None
		if calc:
			payout = session.execute(
				sa.select(CommissionPayout).where(CommissionPayout.calculation_id == calc.id)
			).scalar_one_or_none()
			if payout:
				payout_status = payout.status

		return {
			"employee_id": employee_id,
			"period": period,
			"quota_cents": quota.quota_cents,
			"attained_cents": quota.attained_cents,
			"attainment_pct": float(quota.attainment_pct),
			"commission_earned_cents": commission_cents,
			"payout_status": payout_status,
		}

	@staticmethod
	def split_commission(
		calculation_id: str,
		splits: list[dict[str, Any]],
		session: Any,
	) -> list[Any]:
		"""Divide a commission calculation among multiple employees.

		splits: list of {employee_id, split_pct, reason?, notes?}
		  split_pct is a float/str fraction, e.g. 0.30 for 30%.
		  All split_pct values must sum to 1.0 (±0.001 tolerance).

		split_cents for each credit is computed as:
		  round(total_commission_cents × split_pct, HALF_UP)

		Returns list of CommissionCredit rows (not yet committed).
		Raises ValueError if calculation not found or percentages don't sum to 1.
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import (
			CommissionCalculation,
			CommissionCredit,
		)

		calc = session.execute(
			sa.select(CommissionCalculation).where(CommissionCalculation.id == calculation_id)
		).scalar_one_or_none()
		if calc is None:
			raise ValueError(f"CommissionCalculation {calculation_id!r} not found")

		total_pct = sum(Decimal(str(s["split_pct"])) for s in splits)
		if abs(total_pct - Decimal("1")) > Decimal("0.001"):
			raise ValueError(
				f"Split percentages must sum to 1.0, got {total_pct}"
			)

		credits: list[Any] = []
		for s in splits:
			pct = Decimal(str(s["split_pct"]))
			split_cents = _round_cents(Decimal(calc.total_commission_cents) * pct)
			credit = CommissionCredit(
				tenant_id=calc.tenant_id,
				calculation_id=calculation_id,
				credited_to_employee_id=s["employee_id"],
				split_pct=pct,
				split_cents=split_cents,
				reason=s.get("reason", "SPLIT"),
				notes=s.get("notes"),
			)
			session.add(credit)
			credits.append(credit)

		session.flush()
		log.info(
			"VariablePayService.split_commission: calc=%s splits=%d total_pct=%s",
			calculation_id, len(credits), total_pct,
		)
		return credits

	@staticmethod
	def record_clawback(
		payout_id: str,
		amount_cents: int,
		reason: str,
		session: Any,
	) -> Any:
		"""Record a commission clawback against a PAID or APPROVED payout.

		Creates a CommissionClawback in PENDING status.  The actual deduction
		from payroll is tracked via recovery_payrun_id once a payrun processes it.

		Raises ValueError if payout not found or in an ineligible status.
		"""
		from datetime import date as _date
		from pgappforge.plugins.erp.hcm.variable_pay.models import (
			CommissionClawback,
			CommissionPayout,
		)

		assert amount_cents > 0, "amount_cents must be positive"

		payout = session.execute(
			sa.select(CommissionPayout).where(CommissionPayout.id == payout_id)
		).scalar_one_or_none()
		if payout is None:
			raise ValueError(f"CommissionPayout {payout_id!r} not found")
		if payout.status not in ("PAID", "APPROVED"):
			raise ValueError(
				f"Cannot clawback payout in status {payout.status!r}; must be PAID or APPROVED"
			)

		clawback = CommissionClawback(
			tenant_id=payout.tenant_id,
			payout_id=payout_id,
			employee_id=payout.employee_id,
			amount_cents=amount_cents,
			reason=reason,
			clawback_date=_date.today(),
			status="PENDING",
		)
		session.add(clawback)
		session.flush()
		log.info(
			"VariablePayService.record_clawback: payout=%s employee=%s amount=%d",
			payout_id, payout.employee_id, amount_cents,
		)
		return clawback

	@staticmethod
	def get_team_commissions(
		manager_id: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Manager rollup: aggregate commission payouts for direct reports in a period.

		Attempts to resolve direct reports via the HCM org hierarchy.  Falls back
		to an empty list gracefully if the org model is unavailable.

		Returns:
		  {
		    manager_id, period,
		    team_count: int,
		    total_commission_cents: int,
		    payouts: [{employee_id, amount_cents, status}]
		  }
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import CommissionPayout

		# Resolve direct reports — best-effort; degrade gracefully
		direct_reports: list[str] = []
		try:
			from pgappforge.plugins.erp.hcm.org.models import Employee
			rows = session.execute(
				sa.select(Employee.id).where(
					Employee.manager_id == manager_id,
					Employee.tenant_id == tenant_id,
				)
			).all()
			direct_reports = [str(r[0]) for r in rows]
		except Exception as exc:
			log.debug("get_team_commissions: could not load direct reports: %s", exc)

		if not direct_reports:
			return {
				"manager_id": manager_id,
				"period": period,
				"team_count": 0,
				"total_commission_cents": 0,
				"payouts": [],
			}

		payouts: list[Any] = list(session.execute(
			sa.select(CommissionPayout).where(
				CommissionPayout.employee_id.in_(direct_reports),
				CommissionPayout.period == period,
			)
		).scalars().all())

		return {
			"manager_id": manager_id,
			"period": period,
			"team_count": len(direct_reports),
			"total_commission_cents": sum(p.amount_cents for p in payouts),
			"payouts": [
				{
					"employee_id": p.employee_id,
					"amount_cents": p.amount_cents,
					"status": p.status,
				}
				for p in payouts
			],
		}

	@staticmethod
	def get_plan_analytics(
		plan_id: str,
		period: str,
		session: Any,
	) -> dict[str, Any]:
		"""Aggregate stats for a plan in a given period.

		Returns dict with keys:
		  participants, avg_attainment_pct, at_quota_count,
		  over_quota_count, total_commission_cents
		"""
		from pgappforge.plugins.erp.hcm.variable_pay.models import (
			CommissionCalculation,
			EmployeeQuota,
		)

		quotas: list[Any] = list(session.execute(
			sa.select(EmployeeQuota).where(
				EmployeeQuota.plan_id == plan_id,
				EmployeeQuota.period == period,
			)
		).scalars().all())

		participants = len(quotas)
		if participants == 0:
			return {
				"plan_id": plan_id,
				"period": period,
				"participants": 0,
				"avg_attainment_pct": 0.0,
				"at_quota_count": 0,
				"over_quota_count": 0,
				"total_commission_cents": 0,
			}

		total_attainment = sum(float(q.attainment_pct) for q in quotas)
		avg_attainment = total_attainment / participants
		at_quota_count = sum(1 for q in quotas if 95.0 <= float(q.attainment_pct) <= 105.0)
		over_quota_count = sum(1 for q in quotas if float(q.attainment_pct) > 100.0)

		# Sum latest calculation for each quota
		total_commission = 0
		for quota in quotas:
			calc = session.execute(
				sa.select(CommissionCalculation)
				.where(CommissionCalculation.quota_id == quota.id)
				.order_by(CommissionCalculation.calculated_at.desc())
			).scalar_one_or_none()
			if calc:
				total_commission += calc.total_commission_cents

		return {
			"plan_id": plan_id,
			"period": period,
			"participants": participants,
			"avg_attainment_pct": round(avg_attainment, 4),
			"at_quota_count": at_quota_count,
			"over_quota_count": over_quota_count,
			"total_commission_cents": total_commission,
		}


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

def _register_bpm_actions() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry
	except ImportError:
		log.debug("VariablePayService: BPMActionRegistry not available, skipping BPM registration")
		return

	@BPMActionRegistry.register(
		"hcm.variable_pay.calculate_commission",
		"Calculate commission for employee quota period",
	)
	def _bpm_calculate_commission(
		record_ctx: dict,
		session: Any,
		quota_id: str = "",
		**kw: Any,
	) -> dict:
		try:
			calc = VariablePayService.calculate_commission(quota_id=quota_id, session=session)
			return {
				"status": "ok",
				"calculation_id": calc.id,
				"total_commission_cents": calc.total_commission_cents,
			}
		except VariablePayError as exc:
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"hcm.variable_pay.approve_payout",
		"Approve commission payout",
	)
	def _bpm_approve_payout(
		record_ctx: dict,
		session: Any,
		payout_id: str = "",
		approver_id: str = "",
		**kw: Any,
	) -> dict:
		try:
			payout = VariablePayService.approve_payout(
				payout_id=payout_id,
				approver_id=approver_id,
				session=session,
			)
			return {
				"status": "ok",
				"payout_id": payout.id,
				"amount_cents": payout.amount_cents,
			}
		except VariablePayError as exc:
			return {"status": "error", "message": str(exc)}


try:
	_register_bpm_actions()
except Exception:
	log.debug("VariablePayService: BPM action registration deferred", exc_info=True)


__all__ = [
	"VariablePayService",
	"VariablePayError",
	"QuotaNotFoundError",
	"PayoutNotFoundError",
	"VariablePayStateError",
	"CommissionCalculationError",
]
