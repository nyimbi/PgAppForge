"""
pgappforge/plugins/fintech/robo_advisory/services.py

RoboAdvisoryService — automated goal-based investing.

Design rules
------------
- All monetary amounts are INTEGER cents.
- Future-value projections use simple compound interest:
    FV = PV * (1 + r)^n + PMT * ((1 + r)^n - 1) / r
  where r = monthly rate, n = months, PV = current_amount, PMT = monthly_contribution.
- _check_suitability requires kyc_verified=True AND investment_horizon_years >= 1.
- Drift threshold for rebalance recommendation: 5 absolute percentage points.
- seed_model_portfolios is idempotent: skips existing name+tenant combos.
- Event emission is always wrapped in try/except — never blocks a business transaction.
- execute_auto_investment attempts wealth_management plugin first, then falls back to
  incrementing current_amount_cents directly (simulating a core banking transfer credit).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, update, func

from pgappforge.plugins.erp.foundation.commons import emit_event

from pgappforge.plugins.fintech.robo_advisory.models import (
	ModelPortfolio,
	RoboDriftReport,
	RoboGoal,
	RoboInvestorProfile,
)
from pgappforge.plugins.fintech.robo_advisory.events import (
	AutoInvestmentExecutedEvent,
	DriftDetectedEvent,
	GoalAchievedEvent,
	GoalCreatedEvent,
	RebalanceTriggeredEvent,
)

log = logging.getLogger(__name__)

# Drift threshold in absolute percentage points
_DRIFT_THRESHOLD_PCT = Decimal("5.0")

# Default model portfolio seed data:
# (name, risk_level, allocation, expected_return_pct, expected_volatility_pct)
_DEFAULT_MODEL_PORTFOLIOS: list[tuple[str, str, dict[str, int], float, float]] = [
	("Conservative Portfolio", "CONSERVATIVE", {"EQUITY": 20, "BOND": 70, "CASH": 10}, 5.0, 4.0),
	("Moderate Portfolio", "MODERATE", {"EQUITY": 40, "BOND": 50, "CASH": 10}, 8.0, 7.0),
	("Balanced Portfolio", "BALANCED", {"EQUITY": 60, "BOND": 30, "CASH": 10}, 11.0, 10.0),
	("Growth Portfolio", "GROWTH", {"EQUITY": 80, "BOND": 15, "CASH": 5}, 14.0, 14.0),
	("Aggressive Portfolio", "AGGRESSIVE", {"EQUITY": 95, "BOND": 0, "CASH": 5}, 18.0, 20.0),
]


class RoboAdvisoryError(Exception):
	"""Base error for robo advisory service failures."""


class ProfileNotFoundError(RoboAdvisoryError):
	"""Raised when the requested RoboInvestorProfile does not exist."""


class GoalNotFoundError(RoboAdvisoryError):
	"""Raised when the requested RoboGoal does not exist."""


class SuitabilityError(RoboAdvisoryError):
	"""Raised when profile fails suitability check (KYC / horizon)."""


class RoboAdvisoryService:
	"""All robo-advisory business logic.

	Every public method accepts `session` (SQLAlchemy Session) and `tenant_id`
	as explicit parameters — no global state.
	"""

	# ------------------------------------------------------------------
	# Profile management
	# ------------------------------------------------------------------

	def create_profile(
		self,
		customer_id: str,
		risk_tolerance: str,
		investment_horizon_years: int,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	) -> RoboInvestorProfile:
		"""Create a RoboInvestorProfile for a customer.

		One profile per (tenant_id, customer_id) — enforced by UNIQUE constraint.

		Args:
			customer_id:              UUID of the core banking customer.
			risk_tolerance:           LOW | MEDIUM | HIGH
			investment_horizon_years: Target horizon (>= 1 required for suitability).
			tenant_id:                Tenant identifier.
			session:                  SQLAlchemy session.
			**kwargs:                 monthly_investment_cents, automation_enabled,
			                          automation_cadence, kyc_verified.

		Returns:
			Newly created and flushed RoboInvestorProfile.
		"""
		profile = RoboInvestorProfile(
			customer_id=customer_id,
			risk_tolerance=risk_tolerance.upper(),
			investment_horizon_years=investment_horizon_years,
			tenant_id=tenant_id,
			monthly_investment_cents=kwargs.get("monthly_investment_cents", 0),
			automation_enabled=kwargs.get("automation_enabled", False),
			automation_cadence=kwargs.get("automation_cadence", "MONTHLY"),
			kyc_verified=kwargs.get("kyc_verified", False),
		)
		profile.suitability_completed = self._check_suitability(profile)
		session.add(profile)
		session.flush()
		log.info("RoboAdvisoryService.create_profile: created profile %s", profile.id)
		return profile

	def _check_suitability(self, profile: RoboInvestorProfile) -> bool:
		"""Suitability requires KYC verification and investment horizon >= 1 year."""
		return profile.kyc_verified and profile.investment_horizon_years >= 1

	# ------------------------------------------------------------------
	# Goal management
	# ------------------------------------------------------------------

	def create_goal(
		self,
		profile_id: str,
		goal_type: str,
		goal_name: str,
		target_amount_cents: int,
		tenant_id: str,
		session: Any,
		*,
		target_date: Any = None,
		monthly_contribution: int = 0,
	) -> RoboGoal:
		"""Create an investment goal linked to a profile.

		Validates that the profile has passed suitability.
		Assigns the nearest matching ModelPortfolio based on risk_tolerance.

		Args:
			profile_id:            RoboInvestorProfile.id
			goal_type:             RETIREMENT | EDUCATION | HOME | WEALTH_GROWTH | INCOME | EMERGENCY
			goal_name:             Human-readable goal name.
			target_amount_cents:   Target balance to achieve in cents.
			tenant_id:             Tenant identifier.
			session:               SQLAlchemy session.
			target_date:           Optional target date (datetime.date).
			monthly_contribution:  Monthly contribution in cents.

		Returns:
			Newly created and flushed RoboGoal.

		Raises:
			ProfileNotFoundError: if profile not found.
			SuitabilityError:     if profile has not completed suitability.
		"""
		profile = session.execute(
			select(RoboInvestorProfile).where(
				RoboInvestorProfile.id == profile_id,
				RoboInvestorProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if profile is None:
			raise ProfileNotFoundError(f"RoboInvestorProfile {profile_id!r} not found")

		if not profile.suitability_completed:
			raise SuitabilityError(
				f"Profile {profile_id!r} has not completed suitability "
				f"(kyc_verified={profile.kyc_verified}, horizon={profile.investment_horizon_years})"
			)

		# Assign model portfolio
		model_portfolio = self._recommend_model_portfolio(profile.risk_tolerance, tenant_id, session)

		goal = RoboGoal(
			profile_id=profile_id,
			goal_type=goal_type.upper(),
			goal_name=goal_name,
			target_amount_cents=target_amount_cents,
			current_amount_cents=0,
			target_date=target_date,
			monthly_contribution_cents=monthly_contribution,
			assigned_portfolio_id=model_portfolio.id if model_portfolio else None,
			status="ACTIVE",
			tenant_id=tenant_id,
		)
		session.add(goal)
		session.flush()

		try:
			emit_event(
				GoalCreatedEvent(
					goal_id=goal.id,
					profile_id=profile_id,
					goal_type=goal_type.upper(),
					goal_name=goal_name,
					target_amount_cents=target_amount_cents,
					monthly_contribution_cents=monthly_contribution,
					model_portfolio_id=model_portfolio.id if model_portfolio else "",
					tenant_id=tenant_id,
				),
				session=session,
			)
		except Exception as exc:
			log.warning("create_goal: event emit failed (non-fatal): %s", exc)

		log.info("RoboAdvisoryService.create_goal: created goal %s type=%s", goal.id, goal_type)
		return goal

	def _recommend_model_portfolio(
		self,
		risk_tolerance: str,
		tenant_id: str,
		session: Any,
	) -> ModelPortfolio | None:
		"""Find active ModelPortfolio whose risk_level matches risk_tolerance.

		Maps: LOW→CONSERVATIVE, MEDIUM→BALANCED, HIGH→AGGRESSIVE.
		Falls back to exact match if mapping not found.
		"""
		_RISK_MAP = {
			"LOW": "CONSERVATIVE",
			"MEDIUM": "BALANCED",
			"HIGH": "AGGRESSIVE",
		}
		risk_level = _RISK_MAP.get(risk_tolerance.upper(), risk_tolerance.upper())

		return session.execute(
			select(ModelPortfolio).where(
				ModelPortfolio.risk_level == risk_level,
				ModelPortfolio.tenant_id == tenant_id,
				ModelPortfolio.is_active == True,  # noqa: E712
			).limit(1)
		).scalar_one_or_none()

	# ------------------------------------------------------------------
	# Model portfolio seeding
	# ------------------------------------------------------------------

	def seed_model_portfolios(
		self,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Create 5 default model portfolios if they don't already exist.

		Idempotent: skips any (tenant_id, name) that already exists.

		Returns:
			Number of newly inserted model portfolios.
		"""
		inserted = 0
		for name, risk_level, allocation, exp_return, exp_vol in _DEFAULT_MODEL_PORTFOLIOS:
			existing = session.execute(
				select(ModelPortfolio).where(
					ModelPortfolio.tenant_id == tenant_id,
					ModelPortfolio.name == name,
				)
			).scalar_one_or_none()
			if existing is not None:
				continue

			mp = ModelPortfolio(
				tenant_id=tenant_id,
				name=name,
				risk_level=risk_level,
				allocation=allocation,
				expected_return_pct=Decimal(str(exp_return)),
				expected_volatility_pct=Decimal(str(exp_vol)),
				is_active=True,
			)
			session.add(mp)
			inserted += 1

		if inserted:
			session.flush()
			log.info(
				"RoboAdvisoryService.seed_model_portfolios: inserted %d portfolios",
				inserted,
			)
		return inserted

	# ------------------------------------------------------------------
	# Recommendation engine
	# ------------------------------------------------------------------

	def generate_recommendation(
		self,
		goal_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Generate an investment recommendation for a goal.

		Returns:
			{
			  goal_id, goal_name, target_amount_cents,
			  model_portfolio: {id, name, risk_level, allocation},
			  suggested_monthly_cents: int,
			  projected_value_cents: int,
			  years_to_goal: float,
			  on_track: bool
			}

		Projection uses compound interest + PMT:
		  FV = PV * (1+r)^n + PMT * ((1+r)^n - 1) / r
		  where r = expected_monthly_rate, n = horizon_months, PV = current_amount,
		        PMT = monthly_contribution.

		Raises:
			GoalNotFoundError: if goal not found.
		"""
		goal = session.execute(
			select(RoboGoal).where(
				RoboGoal.id == goal_id,
				RoboGoal.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if goal is None:
			raise GoalNotFoundError(f"RoboGoal {goal_id!r} not found")

		profile = session.execute(
			select(RoboInvestorProfile).where(
				RoboInvestorProfile.id == goal.profile_id,
			)
		).scalar_one_or_none()

		model_portfolio: ModelPortfolio | None = None
		if goal.assigned_portfolio_id:
			model_portfolio = session.execute(
				select(ModelPortfolio).where(
					ModelPortfolio.id == goal.assigned_portfolio_id,
				)
			).scalar_one_or_none()

		# Determine horizon and rates
		horizon_years = (
			profile.investment_horizon_years
			if profile
			else 5
		)
		horizon_months = horizon_years * 12

		expected_annual_return = Decimal(
			str(model_portfolio.expected_return_pct if model_portfolio else "8.0")
		)
		monthly_rate = expected_annual_return / 100 / 12

		pv = Decimal(str(goal.current_amount_cents))
		pmt = Decimal(str(goal.monthly_contribution_cents))
		n = Decimal(str(horizon_months))

		# FV formula
		if monthly_rate > 0:
			growth_factor = (1 + monthly_rate) ** n
			projected_value = pv * growth_factor + pmt * (growth_factor - 1) / monthly_rate
		else:
			projected_value = pv + pmt * n

		projected_value_cents = int(projected_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
		target = goal.target_amount_cents

		# Suggested monthly to hit target
		if monthly_rate > 0 and horizon_months > 0:
			growth_factor_f = float(1 + monthly_rate) ** int(horizon_months)
			pv_fv = float(pv) * growth_factor_f
			shortfall = max(target - pv_fv, 0)
			if growth_factor_f > 1:
				suggested_monthly = shortfall / ((growth_factor_f - 1) / float(monthly_rate))
			else:
				suggested_monthly = shortfall / max(horizon_months, 1)
		else:
			shortfall = max(target - float(pv), 0)
			suggested_monthly = shortfall / max(horizon_months, 1)

		on_track = projected_value_cents >= target

		# Estimate years to goal at current trajectory
		if pmt > 0 and monthly_rate > 0:
			# Solve FV = target numerically (limited iteration)
			years_to_goal = float(horizon_years)
			for months_check in range(1, 600):
				gf = (1 + monthly_rate) ** months_check
				fv_check = pv * gf + pmt * (gf - 1) / monthly_rate
				if fv_check >= target:
					years_to_goal = months_check / 12.0
					break
		else:
			years_to_goal = float(horizon_years)

		return {
			"goal_id": goal.id,
			"goal_name": goal.goal_name,
			"target_amount_cents": target,
			"current_amount_cents": goal.current_amount_cents,
			"model_portfolio": {
				"id": model_portfolio.id if model_portfolio else None,
				"name": model_portfolio.name if model_portfolio else None,
				"risk_level": model_portfolio.risk_level if model_portfolio else None,
				"allocation": model_portfolio.allocation if model_portfolio else {},
				"expected_return_pct": float(model_portfolio.expected_return_pct) if model_portfolio else 0,
			},
			"suggested_monthly_cents": int(suggested_monthly),
			"projected_value_cents": projected_value_cents,
			"years_to_goal": round(years_to_goal, 2),
			"on_track": on_track,
		}

	# ------------------------------------------------------------------
	# Drift detection
	# ------------------------------------------------------------------

	def detect_drift(
		self,
		goal_id: str,
		current_allocation: dict[str, Any],
		tenant_id: str,
		session: Any,
	) -> RoboDriftReport:
		"""Compare current_allocation vs model portfolio target.

		Computes max absolute drift per asset class.
		If drift > 5%: rebalance_recommended=True, emits DriftDetectedEvent.

		Args:
			goal_id:             RoboGoal.id
			current_allocation:  {asset_class: pct} — observed allocation.
			tenant_id:           Tenant identifier.
			session:             SQLAlchemy session.

		Returns:
			Newly created RoboDriftReport.

		Raises:
			GoalNotFoundError: if goal not found.
		"""
		goal = session.execute(
			select(RoboGoal).where(
				RoboGoal.id == goal_id,
				RoboGoal.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if goal is None:
			raise GoalNotFoundError(f"RoboGoal {goal_id!r} not found")

		model_portfolio: ModelPortfolio | None = None
		target_allocation: dict[str, Any] = {}
		if goal.assigned_portfolio_id:
			model_portfolio = session.execute(
				select(ModelPortfolio).where(
					ModelPortfolio.id == goal.assigned_portfolio_id,
				)
			).scalar_one_or_none()
			if model_portfolio:
				target_allocation = dict(model_portfolio.allocation or {})

		# Compute max drift
		all_classes = set(target_allocation.keys()) | set(current_allocation.keys())
		max_drift = Decimal("0")
		for ac in all_classes:
			target_pct = Decimal(str(target_allocation.get(ac, 0)))
			current_pct = Decimal(str(current_allocation.get(ac, 0)))
			drift = abs(target_pct - current_pct)
			if drift > max_drift:
				max_drift = drift

		rebalance_recommended = max_drift > _DRIFT_THRESHOLD_PCT

		report = RoboDriftReport(
			goal_id=goal_id,
			model_portfolio_id=model_portfolio.id if model_portfolio else None,
			target_allocation=target_allocation,
			current_allocation=current_allocation,
			max_drift_pct=max_drift,
			rebalance_recommended=rebalance_recommended,
			tenant_id=tenant_id,
		)
		session.add(report)
		session.flush()

		if rebalance_recommended:
			try:
				emit_event(
					DriftDetectedEvent(
						goal_id=goal_id,
						drift_report_id=report.id,
						max_drift_pct=float(max_drift),
						rebalance_recommended=True,
						tenant_id=tenant_id,
					),
					session=session,
				)
			except Exception as exc:
				log.warning("detect_drift: event emit failed (non-fatal): %s", exc)

		log.info(
			"RoboAdvisoryService.detect_drift: goal=%s max_drift=%.2f%% rebalance=%s",
			goal_id,
			max_drift,
			rebalance_recommended,
		)
		return report

	# ------------------------------------------------------------------
	# Auto-investment
	# ------------------------------------------------------------------

	def execute_auto_investment(
		self,
		profile_id: str,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""For each ACTIVE goal with automation_enabled, execute the monthly contribution.

		Attempts wealth_management place_order first; falls back to directly
		incrementing current_amount_cents (simulates a CB transfer credit).

		Args:
			profile_id: RoboInvestorProfile.id
			tenant_id:  Tenant identifier.
			session:    SQLAlchemy session.

		Returns:
			List of results: [{goal_id, goal_name, amount_cents, method, success}]

		Raises:
			ProfileNotFoundError: if profile not found.
		"""
		profile = session.execute(
			select(RoboInvestorProfile).where(
				RoboInvestorProfile.id == profile_id,
				RoboInvestorProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if profile is None:
			raise ProfileNotFoundError(f"RoboInvestorProfile {profile_id!r} not found")

		if not profile.automation_enabled:
			log.debug(
				"execute_auto_investment: profile %s automation_enabled=False — skipping",
				profile_id,
			)
			return []

		# Load active goals
		goals = session.execute(
			select(RoboGoal).where(
				RoboGoal.profile_id == profile_id,
				RoboGoal.tenant_id == tenant_id,
				RoboGoal.status == "ACTIVE",
				RoboGoal.monthly_contribution_cents > 0,
			)
		).scalars().all()

		results: list[dict[str, Any]] = []
		for goal in goals:
			amount = goal.monthly_contribution_cents
			method, success = self._invest_in_goal(goal, amount, tenant_id, session)

			try:
				emit_event(
					AutoInvestmentExecutedEvent(
						profile_id=profile_id,
						goal_id=goal.id,
						goal_name=goal.goal_name,
						amount_cents=amount,
						method=method,
						tenant_id=tenant_id,
					),
					session=session,
				)
			except Exception as exc:
				log.warning("execute_auto_investment: event emit failed (non-fatal): %s", exc)

			results.append({
				"goal_id": goal.id,
				"goal_name": goal.goal_name,
				"amount_cents": amount,
				"method": method,
				"success": success,
			})

		log.info(
			"RoboAdvisoryService.execute_auto_investment: profile=%s invested=%d goals",
			profile_id,
			len(results),
		)
		return results

	def _invest_in_goal(
		self,
		goal: RoboGoal,
		amount_cents: int,
		tenant_id: str,
		session: Any,
	) -> tuple[str, bool]:
		"""Attempt to invest via wealth_management plugin; fall back to direct credit.

		Returns:
			(method_name, success_bool)
		"""
		# Try wealth_management place_order
		if goal.assigned_portfolio_id:
			try:
				from pgappforge.plugins.fintech.wealth_management.services import (
					WealthManagementService,
				)
				wm_svc = WealthManagementService()
				wm_svc.place_order(
					portfolio_id=str(goal.assigned_portfolio_id),
					asset_code="AUTO_INVEST",
					asset_name="Robo Auto-Investment",
					order_side="BUY",
					order_type="MARKET",
					tenant_id=tenant_id,
					session=session,
					amount_cents=amount_cents,
				)
				goal.current_amount_cents = (goal.current_amount_cents or 0) + amount_cents
				goal.updated_at = datetime.now(timezone.utc)
				session.flush()
				return ("wealth_management", True)
			except Exception as exc:
				log.debug(
					"_invest_in_goal: wealth_management order failed (%s); falling back",
					exc,
				)

		# Fallback: direct balance credit
		goal.current_amount_cents = (goal.current_amount_cents or 0) + amount_cents
		goal.updated_at = datetime.now(timezone.utc)
		session.flush()
		return ("core_banking_transfer", True)

	# ------------------------------------------------------------------
	# Goal achievement check
	# ------------------------------------------------------------------

	def check_goal_achievement(
		self,
		goal_id: str,
		tenant_id: str,
		session: Any,
	) -> bool:
		"""Check whether current_amount >= target_amount; mark ACHIEVED if so.

		Emits GoalAchievedEvent on achievement.

		Args:
			goal_id:   RoboGoal.id
			tenant_id: Tenant identifier.
			session:   SQLAlchemy session.

		Returns:
			True if goal is now ACHIEVED, False otherwise.

		Raises:
			GoalNotFoundError: if goal not found.
		"""
		goal = session.execute(
			select(RoboGoal).where(
				RoboGoal.id == goal_id,
				RoboGoal.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if goal is None:
			raise GoalNotFoundError(f"RoboGoal {goal_id!r} not found")

		if goal.current_amount_cents >= goal.target_amount_cents:
			goal.status = "ACHIEVED"
			goal.updated_at = datetime.now(timezone.utc)
			session.flush()

			try:
				emit_event(
					GoalAchievedEvent(
						goal_id=goal.id,
						profile_id=goal.profile_id,
						goal_name=goal.goal_name,
						target_amount_cents=goal.target_amount_cents,
						achieved_amount_cents=goal.current_amount_cents,
						tenant_id=tenant_id,
					),
					session=session,
				)
			except Exception as exc:
				log.warning("check_goal_achievement: event emit failed (non-fatal): %s", exc)

			log.info(
				"RoboAdvisoryService.check_goal_achievement: goal %s ACHIEVED (amount=%d)",
				goal_id,
				goal.current_amount_cents,
			)
			return True

		return False

	# ------------------------------------------------------------------
	# Batch drift checks
	# ------------------------------------------------------------------

	def run_all_drift_checks(
		self,
		tenant_id: str,
		session: Any,
		*,
		current_allocations: dict[str, dict[str, Any]] | None = None,
	) -> int:
		"""Run drift detection for all ACTIVE goals in the tenant.

		Args:
			tenant_id:            Tenant identifier.
			session:              SQLAlchemy session.
			current_allocations:  Optional dict keyed by goal_id → {asset_class: pct}.
			                      If not supplied, defaults to the model portfolio target
			                      (i.e. zero drift — useful for unit testing scaffolding).

		Returns:
			Count of goals where rebalance_recommended=True.
		"""
		goals = session.execute(
			select(RoboGoal).where(
				RoboGoal.tenant_id == tenant_id,
				RoboGoal.status == "ACTIVE",
			)
		).scalars().all()

		rebalance_count = 0
		for goal in goals:
			alloc = (current_allocations or {}).get(goal.id, {})
			try:
				report = self.detect_drift(
					goal_id=goal.id,
					current_allocation=alloc,
					tenant_id=tenant_id,
					session=session,
				)
				if report.rebalance_recommended:
					rebalance_count += 1
			except Exception as exc:
				log.warning(
					"run_all_drift_checks: detect_drift failed for goal %s (non-fatal): %s",
					goal.id,
					exc,
				)

		log.info(
			"RoboAdvisoryService.run_all_drift_checks: tenant=%s checked=%d rebalance=%d",
			tenant_id,
			len(goals),
			rebalance_count,
		)
		return rebalance_count


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry

	@BPMActionRegistry.register(
		"robo.create_goal",
		"Create a robo-advisory investment goal for an investor profile",
	)
	def _bpm_robo_create_goal(
		record_ctx: dict,
		session: Any,
		profile_id: str = "",
		goal_type: str = "WEALTH_GROWTH",
		goal_name: str = "",
		target_amount_cents: int = 0,
		monthly_contribution: int = 0,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = RoboAdvisoryService()
			goal = svc.create_goal(
				profile_id=profile_id,
				goal_type=goal_type,
				goal_name=goal_name,
				target_amount_cents=target_amount_cents,
				tenant_id=tenant_id,
				session=session,
				monthly_contribution=monthly_contribution,
			)
			return {"status": "ok", "goal_id": goal.id, "goal_status": goal.status}
		except RoboAdvisoryError as exc:
			return {"status": "error", "message": str(exc)}
		except Exception as exc:
			log.warning("bpm robo.create_goal failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"robo.execute_auto_investment",
		"Execute automated monthly investments for all active robo goals",
	)
	def _bpm_robo_auto_invest(
		record_ctx: dict,
		session: Any,
		profile_id: str = "",
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = RoboAdvisoryService()
			results = svc.execute_auto_investment(
				profile_id=profile_id,
				tenant_id=tenant_id,
				session=session,
			)
			return {"status": "ok", "invested_goals": len(results), "results": results}
		except RoboAdvisoryError as exc:
			return {"status": "error", "message": str(exc)}
		except Exception as exc:
			log.warning("bpm robo.execute_auto_investment failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"robo.detect_drift",
		"Detect portfolio drift against model target for a robo goal",
	)
	def _bpm_robo_detect_drift(
		record_ctx: dict,
		session: Any,
		goal_id: str = "",
		current_allocation: dict | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = RoboAdvisoryService()
			report = svc.detect_drift(
				goal_id=goal_id,
				current_allocation=current_allocation or {},
				tenant_id=tenant_id,
				session=session,
			)
			return {
				"status": "ok",
				"report_id": report.id,
				"max_drift_pct": float(report.max_drift_pct),
				"rebalance_recommended": report.rebalance_recommended,
			}
		except RoboAdvisoryError as exc:
			return {"status": "error", "message": str(exc)}
		except Exception as exc:
			log.warning("bpm robo.detect_drift failed: %s", exc)
			return {"status": "error", "message": str(exc)}

except ImportError:
	log.debug("RoboAdvisory BPM: workflow engine not installed — BPM actions skipped")


__all__ = [
	"RoboAdvisoryService",
	"RoboAdvisoryError",
	"ProfileNotFoundError",
	"GoalNotFoundError",
	"SuitabilityError",
]
