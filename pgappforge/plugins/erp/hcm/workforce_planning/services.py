"""
pgappforge/plugins/erp/hcm/workforce_planning/services.py

WorkforcePlanningService — stateless business logic for the HCM Workforce Planning plugin.

All methods accept an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by caller.

Monetary invariants:
  - All cost amounts as integer cents
  - FTE as Decimal/float (supports 0.5 FTE part-time positions)
  - total_annual_cost_cents = round(planned_fte × annual_base_cost_cents)

Public methods:
  create_plan(name, entity_id, plan_year, tenant_id, session, *, gl_cost_center)  -> WorkforcePlan
  add_position(plan_id, position_code, position_title, planned_fte,
               annual_base_cost_cents, session, *, department, grade_level,
               headcount_change_type, planned_start_date, notes)                   -> PlannedPosition
  approve_plan(plan_id, approver_id, session)                                      -> WorkforcePlan
  create_scenario(plan_id, scenario_type, name, session, *,
                  fte_adjustment_pct, cost_adjustment_pct)                         -> WorkforceScenario
  actual_vs_budget(plan_id, period, session)                                       -> dict
  get_fte_by_department(plan_id, session)                                          -> dict
  get_cost_projection(entity_id, plan_year, tenant_id, session)                   -> dict

BPM-registered actions:
  hcm.workforce_planning.approve_plan
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

class WorkforcePlanningError(Exception):
	"""Base domain error for workforce planning operations."""


class PlanNotFoundError(WorkforcePlanningError):
	pass


class WorkforcePlanStateError(WorkforcePlanningError):
	"""Invalid state transition."""


class WorkforcePlanningValidationError(WorkforcePlanningError):
	"""Business rule violation."""


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
		log.debug("workforce_planning._emit: could not emit %s", type(event).__name__, exc_info=True)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class WorkforcePlanningService:
	"""Stateless workforce planning service.

	All methods are synchronous; async wrappers can be added by the caller.
	"""

	# ------------------------------------------------------------------
	# Plan lifecycle
	# ------------------------------------------------------------------

	@staticmethod
	def create_plan(
		name: str,
		entity_id: str,
		plan_year: int,
		tenant_id: str,
		session: Any,
		*,
		gl_cost_center: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> Any:
		"""Create a new workforce plan in DRAFT status.

		Raises WorkforcePlanningError if a plan for (tenant_id, entity_id, plan_year)
		already exists.
		Emits HeadcountPlanCreatedEvent.
		"""
		from pgappforge.plugins.erp.hcm.workforce_planning.models import WorkforcePlan
		from pgappforge.plugins.erp.hcm.workforce_planning.events import HeadcountPlanCreatedEvent

		assert name, "name must not be empty"
		assert entity_id, "entity_id must not be empty"
		assert plan_year > 2000, "plan_year must be a valid 4-digit year"

		existing = session.execute(
			sa.select(WorkforcePlan).where(
				WorkforcePlan.tenant_id == tenant_id,
				WorkforcePlan.entity_id == entity_id,
				WorkforcePlan.plan_year == plan_year,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise WorkforcePlanningError(
				f"WorkforcePlan already exists for entity={entity_id!r} year={plan_year}"
			)

		plan = WorkforcePlan(
			tenant_id=tenant_id,
			name=name,
			entity_id=entity_id,
			plan_year=plan_year,
			status="DRAFT",
			total_planned_fte=Decimal("0"),
			total_budget_cents=0,
			gl_cost_center=gl_cost_center,
			metadata_=metadata or {},
		)
		session.add(plan)
		session.flush()

		_emit(HeadcountPlanCreatedEvent(
			aggregate_id=plan.id,
			aggregate_type="WorkforcePlan",
			tenant_id=tenant_id,
			plan_id=plan.id,
			entity_id=entity_id,
			period=str(plan_year),
		), session)

		log.info(
			"WorkforcePlanningService.create_plan: plan=%s entity=%s year=%d",
			plan.id, entity_id, plan_year,
		)
		return plan

	@staticmethod
	def add_position(
		plan_id: str,
		position_code: str,
		position_title: str,
		planned_fte: float,
		annual_base_cost_cents: int,
		session: Any,
		*,
		department: str | None = None,
		grade_level: str | None = None,
		headcount_change_type: str = "EXISTING",
		planned_start_date: date | None = None,
		notes: str | None = None,
	) -> Any:
		"""Add a planned position to a workforce plan.

		Computes total_annual_cost_cents = planned_fte × annual_base_cost_cents.
		Updates plan.total_planned_fte and plan.total_budget_cents.
		Emits PositionPlannedEvent.

		Plan must be in DRAFT or SUBMITTED status.
		"""
		from pgappforge.plugins.erp.hcm.workforce_planning.models import (
			PlannedPosition,
			WorkforcePlan,
		)
		from pgappforge.plugins.erp.hcm.workforce_planning.events import PositionPlannedEvent

		assert planned_fte > 0, "planned_fte must be positive"
		assert annual_base_cost_cents >= 0, "annual_base_cost_cents must be non-negative"
		assert headcount_change_type in {"NEW", "BACKFILL", "EXISTING", "REDUCTION"}, (
			f"Invalid headcount_change_type: {headcount_change_type!r}"
		)

		plan = session.execute(
			sa.select(WorkforcePlan).where(WorkforcePlan.id == plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise PlanNotFoundError(f"WorkforcePlan {plan_id!r} not found")
		if plan.status not in {"DRAFT", "SUBMITTED"}:
			raise WorkforcePlanStateError(
				f"Cannot add position to plan {plan_id!r} with status={plan.status!r}"
			)

		fte_decimal = Decimal(str(planned_fte))
		total_cost = _round_cents(fte_decimal * Decimal(annual_base_cost_cents))

		position = PlannedPosition(
			tenant_id=plan.tenant_id,
			plan_id=plan_id,
			position_code=position_code,
			position_title=position_title,
			department=department,
			grade_level=grade_level,
			planned_fte=fte_decimal,
			annual_base_cost_cents=annual_base_cost_cents,
			total_annual_cost_cents=total_cost,
			planned_start_date=planned_start_date,
			headcount_change_type=headcount_change_type,
			approval_status="PENDING",
			notes=notes,
		)
		session.add(position)

		# Update plan running totals
		plan.total_planned_fte = Decimal(str(plan.total_planned_fte)) + fte_decimal
		plan.total_budget_cents = (plan.total_budget_cents or 0) + total_cost
		session.flush()

		_emit(PositionPlannedEvent(
			aggregate_id=position.id,
			aggregate_type="PlannedPosition",
			tenant_id=plan.tenant_id,
			plan_id=plan_id,
			position_code=position_code,
			fte_count=planned_fte,
			cost_cents=total_cost,
		), session)

		log.info(
			"WorkforcePlanningService.add_position: plan=%s position=%s fte=%.2f cost=%d",
			plan_id, position.id, planned_fte, total_cost,
		)
		return position

	@staticmethod
	def approve_plan(
		plan_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Transition plan SUBMITTED → APPROVED.

		Raises WorkforcePlanStateError if current status is not SUBMITTED.
		Emits HeadcountBudgetApprovedEvent.
		"""
		from pgappforge.plugins.erp.hcm.workforce_planning.models import WorkforcePlan
		from pgappforge.plugins.erp.hcm.workforce_planning.events import HeadcountBudgetApprovedEvent

		plan = session.execute(
			sa.select(WorkforcePlan).where(WorkforcePlan.id == plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise PlanNotFoundError(f"WorkforcePlan {plan_id!r} not found")
		if plan.status != "SUBMITTED":
			raise WorkforcePlanStateError(
				f"Plan {plan_id!r} is {plan.status!r}; must be SUBMITTED to approve"
			)

		plan.status = "APPROVED"
		plan.approved_by = approver_id
		plan.approved_at = _now()
		session.flush()

		_emit(HeadcountBudgetApprovedEvent(
			aggregate_id=plan.id,
			aggregate_type="WorkforcePlan",
			tenant_id=plan.tenant_id,
			plan_id=plan.id,
			approved_by=approver_id,
			total_fte=float(plan.total_planned_fte),
			total_cost_cents=plan.total_budget_cents,
		), session)

		log.info(
			"WorkforcePlanningService.approve_plan: plan=%s approver=%s fte=%.2f budget=%d",
			plan.id, approver_id, float(plan.total_planned_fte), plan.total_budget_cents,
		)
		return plan

	@staticmethod
	def submit_plan(plan_id: str, session: Any) -> Any:
		"""Transition plan DRAFT → SUBMITTED for approval.

		Raises WorkforcePlanStateError if not in DRAFT.
		"""
		from pgappforge.plugins.erp.hcm.workforce_planning.models import WorkforcePlan

		plan = session.execute(
			sa.select(WorkforcePlan).where(WorkforcePlan.id == plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise PlanNotFoundError(f"WorkforcePlan {plan_id!r} not found")
		if plan.status != "DRAFT":
			raise WorkforcePlanStateError(
				f"Plan {plan_id!r} is {plan.status!r}; must be DRAFT to submit"
			)

		plan.status = "SUBMITTED"
		session.flush()
		log.info("WorkforcePlanningService.submit_plan: plan=%s", plan.id)
		return plan

	# ------------------------------------------------------------------
	# Scenario planning
	# ------------------------------------------------------------------

	@staticmethod
	def create_scenario(
		plan_id: str,
		scenario_type: str,
		name: str,
		session: Any,
		*,
		fte_adjustment_pct: float = 0.0,
		cost_adjustment_pct: float = 0.0,
	) -> Any:
		"""Generate a what-if scenario from an existing plan.

		Clones all plan positions into scenario_data JSONB, applying global
		fte_adjustment_pct and cost_adjustment_pct multipliers.

		e.g. fte_adjustment_pct=10.0 → each position's planned_fte × 1.10
		     cost_adjustment_pct=-5.0 → each position's cost × 0.95

		Emits WorkforceScenarioCreatedEvent.
		"""
		from pgappforge.plugins.erp.hcm.workforce_planning.models import (
			PlannedPosition,
			WorkforcePlan,
			WorkforceScenario,
		)
		from pgappforge.plugins.erp.hcm.workforce_planning.events import WorkforceScenarioCreatedEvent

		valid_types = {"BASE", "OPTIMISTIC", "PESSIMISTIC", "GROWTH_10PCT", "GROWTH_25PCT", "CUSTOM"}
		assert scenario_type in valid_types, f"Invalid scenario_type: {scenario_type!r}"

		plan = session.execute(
			sa.select(WorkforcePlan).where(WorkforcePlan.id == plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise PlanNotFoundError(f"WorkforcePlan {plan_id!r} not found")

		positions: list[Any] = list(session.execute(
			sa.select(PlannedPosition).where(PlannedPosition.plan_id == plan_id)
		).scalars().all())

		fte_mult = Decimal("1") + Decimal(str(fte_adjustment_pct)) / Decimal("100")
		cost_mult = Decimal("1") + Decimal(str(cost_adjustment_pct)) / Decimal("100")

		adjusted_positions = []
		total_adj_fte = Decimal("0")
		total_adj_cost = 0

		for pos in positions:
			adj_fte = Decimal(str(pos.planned_fte)) * fte_mult
			adj_cost = _round_cents(Decimal(pos.annual_base_cost_cents) * cost_mult)
			adj_total = _round_cents(adj_fte * Decimal(adj_cost))

			total_adj_fte += adj_fte
			total_adj_cost += adj_total

			adjusted_positions.append({
				"position_id": pos.id,
				"position_code": pos.position_code,
				"position_title": pos.position_title,
				"department": pos.department,
				"grade_level": pos.grade_level,
				"headcount_change_type": pos.headcount_change_type,
				"original_planned_fte": float(pos.planned_fte),
				"adjusted_fte": float(adj_fte.quantize(Decimal("0.0001"))),
				"original_annual_base_cost_cents": pos.annual_base_cost_cents,
				"adjusted_annual_base_cost_cents": adj_cost,
				"adjusted_total_annual_cost_cents": adj_total,
			})

		scenario_data = {
			"base_plan_id": plan_id,
			"base_plan_year": plan.plan_year,
			"fte_adjustment_pct": fte_adjustment_pct,
			"cost_adjustment_pct": cost_adjustment_pct,
			"total_adjusted_fte": float(total_adj_fte.quantize(Decimal("0.0001"))),
			"total_adjusted_cost_cents": total_adj_cost,
			"positions": adjusted_positions,
		}

		scenario = WorkforceScenario(
			tenant_id=plan.tenant_id,
			plan_id=plan_id,
			scenario_type=scenario_type,
			name=name,
			fte_adjustment_pct=Decimal(str(fte_adjustment_pct)),
			cost_adjustment_pct=Decimal(str(cost_adjustment_pct)),
			scenario_data=scenario_data,
		)
		session.add(scenario)
		session.flush()

		_emit(WorkforceScenarioCreatedEvent(
			aggregate_id=scenario.id,
			aggregate_type="WorkforceScenario",
			tenant_id=plan.tenant_id,
			scenario_id=scenario.id,
			plan_id=plan_id,
			scenario_type=scenario_type,
		), session)

		log.info(
			"WorkforcePlanningService.create_scenario: scenario=%s type=%s plan=%s",
			scenario.id, scenario_type, plan_id,
		)
		return scenario

	# ------------------------------------------------------------------
	# Analytics
	# ------------------------------------------------------------------

	@staticmethod
	def actual_vs_budget(
		plan_id: str,
		period: str,
		session: Any,
	) -> dict[str, Any]:
		"""Compare planned headcount/cost to actuals for a plan period.

		Actuals are loaded from hcm analytics if available; otherwise
		the plan's own approved positions are used as a proxy for actuals
		(useful before the analytics plugin is wired in).

		Returns dict with keys:
		  planned_fte, actual_fte, variance_fte,
		  planned_cost_cents, actual_cost_cents, variance_cost_cents, variance_pct

		Emits ActualVsBudgetAnalyzedEvent.
		"""
		from pgappforge.plugins.erp.hcm.workforce_planning.models import (
			PlannedPosition,
			WorkforcePlan,
		)
		from pgappforge.plugins.erp.hcm.workforce_planning.events import ActualVsBudgetAnalyzedEvent

		plan = session.execute(
			sa.select(WorkforcePlan).where(WorkforcePlan.id == plan_id)
		).scalar_one_or_none()
		if plan is None:
			raise PlanNotFoundError(f"WorkforcePlan {plan_id!r} not found")

		planned_fte = float(plan.total_planned_fte)
		planned_cost_cents = plan.total_budget_cents or 0

		# Attempt to load actuals from analytics plugin
		actual_fte: float = 0.0
		actual_cost_cents: int = 0
		actuals_source = "plan_proxy"

		try:
			from pgappforge.plugins.erp.hcm.analytics.services import HCMAnalyticsService  # type: ignore[import]
			actuals = HCMAnalyticsService.get_headcount_actuals(
				entity_id=plan.entity_id,
				plan_year=plan.plan_year,
				tenant_id=plan.tenant_id,
				session=session,
			)
			actual_fte = actuals.get("total_fte", 0.0)
			actual_cost_cents = actuals.get("total_cost_cents", 0)
			actuals_source = "analytics"
		except Exception:
			# Fallback: use APPROVED positions as actuals proxy
			approved_positions: list[Any] = list(session.execute(
				sa.select(PlannedPosition).where(
					PlannedPosition.plan_id == plan_id,
					PlannedPosition.approval_status == "APPROVED",
				)
			).scalars().all())
			actual_fte = sum(float(p.planned_fte) for p in approved_positions)
			actual_cost_cents = sum(p.total_annual_cost_cents for p in approved_positions)

		variance_fte = actual_fte - planned_fte
		variance_cost_cents = actual_cost_cents - planned_cost_cents
		variance_pct = (
			round((variance_cost_cents / planned_cost_cents) * 100, 4)
			if planned_cost_cents != 0 else 0.0
		)

		_emit(ActualVsBudgetAnalyzedEvent(
			aggregate_id=plan.id,
			aggregate_type="WorkforcePlan",
			tenant_id=plan.tenant_id,
			plan_id=plan_id,
			period=period,
			variance_fte=variance_fte,
			variance_cost_cents=variance_cost_cents,
		), session)

		log.info(
			"WorkforcePlanningService.actual_vs_budget: plan=%s period=%s "
			"planned_fte=%.2f actual_fte=%.2f variance_fte=%.2f source=%s",
			plan_id, period, planned_fte, actual_fte, variance_fte, actuals_source,
		)

		return {
			"plan_id": plan_id,
			"period": period,
			"actuals_source": actuals_source,
			"planned_fte": planned_fte,
			"actual_fte": actual_fte,
			"variance_fte": round(variance_fte, 4),
			"planned_cost_cents": planned_cost_cents,
			"actual_cost_cents": actual_cost_cents,
			"variance_cost_cents": variance_cost_cents,
			"variance_pct": variance_pct,
		}

	@staticmethod
	def get_fte_by_department(
		plan_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Group planned positions by department, summing FTE and cost.

		Returns dict keyed by department name (None → "__unassigned__"):
		  {
		    "Engineering": {"fte": 12.5, "total_cost_cents": 125000000,
		                    "position_count": 13, "change_type_breakdown": {...}},
		    ...
		  }
		"""
		from pgappforge.plugins.erp.hcm.workforce_planning.models import PlannedPosition

		positions: list[Any] = list(session.execute(
			sa.select(PlannedPosition).where(PlannedPosition.plan_id == plan_id)
		).scalars().all())

		result: dict[str, Any] = {}
		for pos in positions:
			dept = pos.department or "__unassigned__"
			if dept not in result:
				result[dept] = {
					"fte": 0.0,
					"total_cost_cents": 0,
					"position_count": 0,
					"change_type_breakdown": {},
				}
			result[dept]["fte"] = round(result[dept]["fte"] + float(pos.planned_fte), 4)
			result[dept]["total_cost_cents"] += pos.total_annual_cost_cents
			result[dept]["position_count"] += 1

			ct = pos.headcount_change_type
			ctb = result[dept]["change_type_breakdown"]
			ctb[ct] = ctb.get(ct, 0) + 1

		return result

	@staticmethod
	def get_cost_projection(
		entity_id: str,
		plan_year: int,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Monthly cost projection for a full plan year (12 months).

		Distributes total_budget_cents evenly across 12 months.
		Positions with a planned_start_date only contribute from that month onwards.

		Returns:
		  {
		    "entity_id": ...,
		    "plan_year": ...,
		    "total_annual_cost_cents": ...,
		    "months": [
		      {"month": 1, "month_label": "Jan 2025", "projected_cost_cents": ...},
		      ...
		    ]
		  }
		"""
		from pgappforge.plugins.erp.hcm.workforce_planning.models import (
			PlannedPosition,
			WorkforcePlan,
		)

		plan = session.execute(
			sa.select(WorkforcePlan).where(
				WorkforcePlan.tenant_id == tenant_id,
				WorkforcePlan.entity_id == entity_id,
				WorkforcePlan.plan_year == plan_year,
			)
		).scalar_one_or_none()
		if plan is None:
			return {
				"entity_id": entity_id,
				"plan_year": plan_year,
				"total_annual_cost_cents": 0,
				"months": [],
			}

		positions: list[Any] = list(session.execute(
			sa.select(PlannedPosition).where(PlannedPosition.plan_id == plan.id)
		).scalars().all())

		# Monthly buckets: month index 1..12
		monthly: dict[int, int] = {m: 0 for m in range(1, 13)}

		for pos in positions:
			monthly_cost = _round_cents(Decimal(pos.total_annual_cost_cents) / Decimal("12"))
			start_month = 1
			if pos.planned_start_date and pos.planned_start_date.year == plan_year:
				start_month = pos.planned_start_date.month
			elif pos.planned_start_date and pos.planned_start_date.year > plan_year:
				continue  # starts after this plan year

			for m in range(start_month, 13):
				monthly[m] += monthly_cost

		month_labels = [
			"Jan", "Feb", "Mar", "Apr", "May", "Jun",
			"Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
		]
		months_out = [
			{
				"month": m,
				"month_label": f"{month_labels[m - 1]} {plan_year}",
				"projected_cost_cents": monthly[m],
			}
			for m in range(1, 13)
		]

		return {
			"entity_id": entity_id,
			"plan_year": plan_year,
			"plan_id": plan.id,
			"total_annual_cost_cents": plan.total_budget_cents,
			"months": months_out,
		}


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

def _register_bpm_actions() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry
	except ImportError:
		log.debug("WorkforcePlanningService: BPMActionRegistry not available, skipping")
		return

	@BPMActionRegistry.register(
		"hcm.workforce_planning.approve_plan",
		"Approve headcount plan",
	)
	def _bpm_approve_plan(
		record_ctx: dict,
		session: Any,
		plan_id: str = "",
		approver_id: str = "",
		**kw: Any,
	) -> dict:
		try:
			plan = WorkforcePlanningService.approve_plan(
				plan_id=plan_id,
				approver_id=approver_id,
				session=session,
			)
			return {
				"status": "ok",
				"plan_id": plan.id,
				"total_planned_fte": float(plan.total_planned_fte),
				"total_budget_cents": plan.total_budget_cents,
			}
		except WorkforcePlanningError as exc:
			return {"status": "error", "message": str(exc)}


try:
	_register_bpm_actions()
except Exception:
	log.debug("WorkforcePlanningService: BPM action registration deferred", exc_info=True)


__all__ = [
	"WorkforcePlanningService",
	"WorkforcePlanningError",
	"PlanNotFoundError",
	"WorkforcePlanStateError",
	"WorkforcePlanningValidationError",
]
