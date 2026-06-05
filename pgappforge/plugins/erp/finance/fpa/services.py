"""
pgappforge/plugins/erp/finance/fpa/services.py

FPAService — stateless business logic for the FP&A plugin.

All methods receive an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

Critical invariants:
  - All monetary amounts: integer cents (BigInteger). Never float.
  - BudgetLine rows for locked versions are NEVER updated — lock prevents it.
  - ForecastSnapshot rows are NEVER updated — each snapshot is immutable.
  - GL integration is via lazy import (try/except) — FP&A can run without GL.
  - driver formula evaluation uses a restricted namespace (no builtins exec).
"""
from __future__ import annotations

import ast
import logging
import math
import operator as _op
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.finance.fpa.models import (
	BudgetCycle,
	BudgetDriver,
	BudgetLine,
	BudgetVersion,
	ForecastSnapshot,
	KPITarget,
	ScenarioModel,
)
from pgappforge.plugins.erp.finance.fpa.events import (
	BudgetApprovedEvent,
	BudgetCycleOpenedEvent,
	ForecastSnapshotTakenEvent,
	KPIStatusChangedEvent,
	ScenarioGeneratedEvent,
	VarianceAlertEvent,
	emit_event,
)

log = logging.getLogger(__name__)

# Variance thresholds for KPI auto-status
_KPI_AT_RISK_PCT: float = 5.0
_KPI_OFF_TRACK_PCT: float = 15.0

# Default variance alert threshold
_VARIANCE_ALERT_PCT: float = 15.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class FPAServiceError(Exception):
	"""Base error for FP&A domain violations."""


class CycleNotFoundError(FPAServiceError):
	"""No BudgetCycle with the given id."""


class VersionNotFoundError(FPAServiceError):
	"""No BudgetVersion with the given id."""


class DriverNotFoundError(FPAServiceError):
	"""No BudgetDriver with the given code."""


class ScenarioNotFoundError(FPAServiceError):
	"""No ScenarioModel with the given id."""


class VersionLockedError(FPAServiceError):
	"""Version is locked — no modifications allowed."""


class CycleStatusError(FPAServiceError):
	"""Operation not permitted in the current cycle status."""


# ---------------------------------------------------------------------------
# Safe formula evaluator (replaces eval())
# ---------------------------------------------------------------------------

_SAFE_OPS = {
	ast.Add: _op.add,
	ast.Sub: _op.sub,
	ast.Mult: _op.mul,
	ast.Div: _op.truediv,
	ast.Pow: _op.pow,
	ast.USub: _op.neg,
	ast.UAdd: _op.pos,
}


def _safe_eval_formula(expr: str, context: dict[str, float]) -> float:
	"""Evaluate a simple arithmetic formula with named variables.

	No builtins, no attribute access, no arbitrary code execution.
	Allowed nodes: numeric constants, named variables from context,
	binary arithmetic ops (+, -, *, /, **), and unary +/-.
	"""
	try:
		tree = ast.parse(expr, mode='eval')
	except SyntaxError as exc:
		raise ValueError(f"Invalid formula syntax: {expr!r}") from exc

	def _eval(node):
		if isinstance(node, ast.Expression):
			return _eval(node.body)
		elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
			return float(node.value)
		elif isinstance(node, ast.Name):
			if node.id not in context:
				raise ValueError(f"Unknown variable {node.id!r} in formula")
			return float(context[node.id])
		elif isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
			return _SAFE_OPS[type(node.op)](_eval(node.left), _eval(node.right))
		elif isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
			return _SAFE_OPS[type(node.op)](_eval(node.operand))
		else:
			raise ValueError(f"Formula contains disallowed operation: {ast.dump(node)}")

	return _eval(tree)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_cycle(session: Session, cycle_id: str, tenant_id: str) -> BudgetCycle:
	cycle = session.execute(
		select(BudgetCycle).where(
			BudgetCycle.id == cycle_id,
			BudgetCycle.tenant_id == tenant_id,
		)
	).scalar_one_or_none()
	if cycle is None:
		raise CycleNotFoundError(f"BudgetCycle {cycle_id!r} not found for tenant {tenant_id!r}")
	return cycle


def _require_version(session: Session, version_id: str, tenant_id: str) -> BudgetVersion:
	version = session.execute(
		select(BudgetVersion).where(
			BudgetVersion.id == version_id,
			BudgetVersion.tenant_id == tenant_id,
		)
	).scalar_one_or_none()
	if version is None:
		raise VersionNotFoundError(f"BudgetVersion {version_id!r} not found for tenant {tenant_id!r}")
	return version


def _assert_version_unlocked(version: BudgetVersion) -> None:
	if version.locked_at is not None:
		raise VersionLockedError(
			f"BudgetVersion {version.id!r} ({version.version_name!r}) is locked."
		)


def _eval_driver_formula(
	formula: str,
	base_value: Decimal,
	params: dict[str, Any],
) -> Decimal:
	"""Evaluate a driver formula using the restricted AST-based evaluator.

	Context variables available in formula:
	  base_value  — the driver's base_value as float
	  Any key in params whose value is numeric (int/float/Decimal) is also available.

	Returns Decimal result.  Any exception propagates as FPAServiceError.
	"""
	context: dict[str, float] = {"base_value": float(base_value)}
	for k, v in (params or {}).items():
		if isinstance(v, (int, float, Decimal)):
			context[k] = float(v)
	try:
		result = _safe_eval_formula(formula, context)
		return Decimal(str(result))
	except Exception as exc:
		raise FPAServiceError(f"Driver formula evaluation failed: {exc}") from exc


def _month_range(cycle: BudgetCycle) -> list[date]:
	"""Return list of period_month dates (first of month) for the cycle.

	ANNUAL      → 12 months starting Jan 1 of fiscal_year
	QUARTERLY   → 3 months starting Jan 1
	ROLLING_12M → 12 months starting today's month
	"""
	import calendar
	from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]

	if cycle.cycle_type == "QUARTERLY":
		n = 3
		start = date(cycle.fiscal_year, 1, 1)
	elif cycle.cycle_type == "ROLLING_12M":
		n = 12
		today = date.today()
		start = date(today.year, today.month, 1)
	else:  # ANNUAL default
		n = 12
		start = date(cycle.fiscal_year, 1, 1)

	return [start + relativedelta(months=i) for i in range(n)]


def _compute_driver_amount_cents(
	driver: BudgetDriver,
	params: dict[str, Any] | None,
) -> int:
	"""Compute integer cents from a driver for one period-month.

	HEADCOUNT   → base_value * params['headcount'] * params.get('rate', 1)
	VOLUME      → base_value * params['volume']
	RATE        → base_value (already a rate; params may scale it)
	PERCENTAGE  → base_value / 100 * params['base_amount_cents']
	FORMULA     → eval formula_expression
	"""
	p: dict[str, Any] = params or {}
	bv = driver.base_value  # Decimal

	if driver.driver_type == "HEADCOUNT":
		headcount = Decimal(str(p.get("headcount", 1)))
		rate = Decimal(str(p.get("rate", 1)))
		result = bv * headcount * rate
	elif driver.driver_type == "VOLUME":
		volume = Decimal(str(p.get("volume", 1)))
		result = bv * volume
	elif driver.driver_type == "RATE":
		scale = Decimal(str(p.get("scale", 1)))
		result = bv * scale
	elif driver.driver_type == "PERCENTAGE":
		base_amount = Decimal(str(p.get("base_amount_cents", 0)))
		result = (bv / Decimal("100")) * base_amount
	elif driver.driver_type == "FORMULA" and driver.formula_expression:
		result = _eval_driver_formula(driver.formula_expression, bv, p)
	else:
		result = bv

	return int(result.quantize(Decimal("1")))


# ---------------------------------------------------------------------------
# FPAService
# ---------------------------------------------------------------------------

class FPAService:
	"""Stateless service for FP&A operations.

	Instantiate once per app (or per request).  All methods accept a
	SQLAlchemy Session; callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# 1. open_budget_cycle
	# ------------------------------------------------------------------

	def open_budget_cycle(
		self,
		session: Session,
		data: dict[str, Any],
		tenant_id: str,
	) -> BudgetCycle:
		"""Create and open a new BudgetCycle.

		data keys (required): name, fiscal_year
		data keys (optional): cycle_type, input_deadline, approval_deadline

		Returns the persisted BudgetCycle with status=INPUT_OPEN.
		Emits BudgetCycleOpenedEvent.
		"""
		cycle = BudgetCycle(
			tenant_id=tenant_id,
			name=data["name"],
			fiscal_year=int(data["fiscal_year"]),
			cycle_type=data.get("cycle_type", "ANNUAL"),
			status="INPUT_OPEN",
			input_deadline=data.get("input_deadline"),
			approval_deadline=data.get("approval_deadline"),
		)
		session.add(cycle)
		session.flush()

		emit_event(
			BudgetCycleOpenedEvent(
				aggregate_id=cycle.id,
				aggregate_type="BudgetCycle",
				tenant_id=tenant_id,
				cycle_id=cycle.id,
				cycle_name=cycle.name,
				fiscal_year=cycle.fiscal_year,
				cycle_type=cycle.cycle_type,
				input_deadline=str(cycle.input_deadline) if cycle.input_deadline else "",
			),
			session,
		)

		log.info(
			"FPAService.open_budget_cycle: cycle=%r fy=%d type=%s tenant=%r",
			cycle.id, cycle.fiscal_year, cycle.cycle_type, tenant_id,
		)
		return cycle

	# ------------------------------------------------------------------
	# 2. create_version
	# ------------------------------------------------------------------

	def create_version(
		self,
		session: Session,
		cycle_id: str,
		version_name: str,
		version_type: str,
		copy_from_version_id: str | None = None,
		tenant_id: str = "",
	) -> BudgetVersion:
		"""Create a new BudgetVersion within a cycle.

		If copy_from_version_id is provided, all BudgetLine rows from that
		version are cloned into the new version (deep copy).

		Returns the new BudgetVersion (unflushed if no lines; flushed if lines copied).
		"""
		cycle = _require_cycle(session, cycle_id, tenant_id)

		version = BudgetVersion(
			tenant_id=tenant_id,
			cycle_id=cycle_id,
			version_name=version_name,
			version_type=version_type,
			is_active=True,
		)
		session.add(version)
		session.flush()  # need version.id for line FKs

		if copy_from_version_id:
			source = _require_version(session, copy_from_version_id, tenant_id)
			source_lines: list[BudgetLine] = session.execute(
				select(BudgetLine).where(
					BudgetLine.version_id == source.id,
					BudgetLine.tenant_id == tenant_id,
				)
			).scalars().all()

			for src in source_lines:
				clone = BudgetLine(
					tenant_id=tenant_id,
					version_id=version.id,
					gl_account_code=src.gl_account_code,
					cost_center_code=src.cost_center_code,
					entity_id=src.entity_id,
					period_month=src.period_month,
					amount_cents=src.amount_cents,
					driver_type=src.driver_type,
					driver_params=src.driver_params,
					narrative=src.narrative,
					status="DRAFT",
				)
				session.add(clone)

			log.info(
				"FPAService.create_version: cloned %d lines from version=%r → new=%r",
				len(source_lines), copy_from_version_id, version.id,
			)

		return version

	# ------------------------------------------------------------------
	# 3. seed_budget_from_actuals
	# ------------------------------------------------------------------

	def seed_budget_from_actuals(
		self,
		session: Session,
		version_id: str,
		prior_year_offset_months: int = 12,
		growth_pct: float = 5.0,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Seed BudgetLine rows from GL actuals of the prior period.

		Pulls GLAccountBalance rows for the period prior_year_offset_months
		before each target month, applies growth_pct, and inserts BudgetLine
		rows.  Skips months that already have a BudgetLine for the account.

		Returns: {lines_seeded: int, total_budget_cents: int}
		"""
		from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]

		version = _require_version(session, version_id, tenant_id)
		_assert_version_unlocked(version)
		cycle = _require_cycle(session, version.cycle_id, tenant_id)
		months = _month_range(cycle)

		# Lazy GL import
		try:
			from pgappforge.plugins.erp.finance.gl.models import (
				GLAccountBalance,
				GLPeriod,
			)
			gl_available = True
		except ImportError:
			gl_available = False
			log.warning(
				"FPAService.seed_budget_from_actuals: GL plugin not available, "
				"cannot pull actuals — returning empty seed."
			)
			return {"lines_seeded": 0, "total_budget_cents": 0}

		growth_factor = Decimal(str(1 + growth_pct / 100))

		# Build the set of prior months we need GL periods for — ONE query
		prior_months = [
			target_month - relativedelta(months=prior_year_offset_months)
			for target_month in months
		]
		prior_month_min = min(prior_months)
		prior_month_max = max(prior_months)

		period_rows = session.execute(
			select(GLPeriod).where(
				GLPeriod.tenant_id == tenant_id,
				GLPeriod.start_date <= prior_month_max,
				GLPeriod.end_date >= prior_month_min,
			)
		).scalars().all()

		# Build lookup: prior_month → GLPeriod
		prior_month_to_period: dict[date, Any] = {}
		for pr in period_rows:
			for pm in prior_months:
				if pr.start_date <= pm <= pr.end_date:
					prior_month_to_period[pm] = pr

		relevant_period_ids = list({str(pr.id) for pr in prior_month_to_period.values()})

		if not relevant_period_ids:
			log.info(
				"FPAService.seed_budget_from_actuals: version=%r no GL periods found, seeded=0",
				version_id,
			)
			return {"lines_seeded": 0, "total_budget_cents": 0}

		# Load ALL GL balances for relevant periods — ONE query
		all_balances: list[GLAccountBalance] = session.execute(
			select(GLAccountBalance).where(
				GLAccountBalance.tenant_id == tenant_id,
				GLAccountBalance.period_id.in_(relevant_period_ids),
			)
		).scalars().all()

		# Build lookup: (account_code, period_id) → balance row
		balance_by_acct_period: dict[tuple[str, str], GLAccountBalance] = {
			(str(b.account_code), str(b.period_id)): b
			for b in all_balances
		}

		# Load existing BudgetLine keys for this version — ONE query
		existing_keys: set[tuple[str, date]] = set(
			session.execute(
				select(BudgetLine.gl_account_code, BudgetLine.period_month).where(
					BudgetLine.version_id == version_id,
					BudgetLine.tenant_id == tenant_id,
				)
			).all()
		)

		# Build candidate inserts in Python — zero DB calls
		import uuid as _uuid
		candidate_dicts: list[dict[str, Any]] = []
		for target_month, prior_month in zip(months, prior_months):
			period_row = prior_month_to_period.get(prior_month)
			if period_row is None:
				continue
			period_id = str(period_row.id)

			# Find all accounts that have a balance for this period
			for (acct_code, pid), bal in balance_by_acct_period.items():
				if pid != period_id:
					continue
				if (acct_code, target_month) in existing_keys:
					continue

				net_prior = bal.closing_debit - bal.closing_credit
				budgeted = int(Decimal(str(net_prior)) * growth_factor)
				candidate_dicts.append({
					"id": str(_uuid.uuid4()),
					"tenant_id": tenant_id,
					"version_id": version_id,
					"gl_account_code": acct_code,
					"period_month": target_month,
					"amount_cents": budgeted,
					"driver_type": "PRIOR_YEAR",
					"driver_params": {
						"prior_period_id": period_id,
						"prior_net_cents": net_prior,
						"growth_pct": growth_pct,
					},
					"status": "DRAFT",
				})

		lines_seeded = len(candidate_dicts)
		total_budget_cents = sum(d["amount_cents"] for d in candidate_dicts)

		if candidate_dicts:
			session.execute(sa.insert(BudgetLine), candidate_dicts)

		log.info(
			"FPAService.seed_budget_from_actuals: version=%r seeded=%d total=%d cents",
			version_id, lines_seeded, total_budget_cents,
		)
		return {"lines_seeded": lines_seeded, "total_budget_cents": total_budget_cents}

	# ------------------------------------------------------------------
	# 4. apply_driver
	# ------------------------------------------------------------------

	def apply_driver(
		self,
		session: Session,
		version_id: str,
		gl_account_code: str,
		driver_code: str,
		tenant_id: str,
		cost_center_code: str | None = None,
	) -> list[BudgetLine]:
		"""Apply a BudgetDriver formula to all months in the cycle for one account.

		Upserts (insert-or-update) BudgetLine rows: if a line already exists for
		(version, account, cost_centre, month) it is updated; otherwise inserted.

		Returns the list of affected BudgetLine rows.
		"""
		version = _require_version(session, version_id, tenant_id)
		_assert_version_unlocked(version)
		cycle = _require_cycle(session, version.cycle_id, tenant_id)

		driver = session.execute(
			select(BudgetDriver).where(
				BudgetDriver.tenant_id == tenant_id,
				BudgetDriver.driver_code == driver_code,
			)
		).scalar_one_or_none()
		if driver is None:
			raise DriverNotFoundError(
				f"BudgetDriver {driver_code!r} not found for tenant {tenant_id!r}"
			)

		months = _month_range(cycle)
		affected: list[BudgetLine] = []

		for month in months:
			amount_cents = _compute_driver_amount_cents(driver, None)

			line = session.execute(
				select(BudgetLine).where(
					BudgetLine.version_id == version_id,
					BudgetLine.tenant_id == tenant_id,
					BudgetLine.gl_account_code == gl_account_code,
					BudgetLine.cost_center_code == cost_center_code,
					BudgetLine.period_month == month,
				).limit(1)
			).scalar_one_or_none()

			if line is None:
				line = BudgetLine(
					tenant_id=tenant_id,
					version_id=version_id,
					gl_account_code=gl_account_code,
					cost_center_code=cost_center_code,
					period_month=month,
					status="DRAFT",
				)
				session.add(line)

			line.amount_cents = amount_cents
			line.driver_type = driver.driver_type if driver.driver_type in (
				"HEADCOUNT", "REVENUE_PCT", "PRIOR_YEAR", "FORMULA"
			) else "FORMULA"
			line.driver_params = {
				"driver_code": driver_code,
				"driver_id": str(driver.id),
				"computed_cents": amount_cents,
			}
			affected.append(line)

		session.flush()
		log.info(
			"FPAService.apply_driver: version=%r acct=%r driver=%r → %d lines",
			version_id, gl_account_code, driver_code, len(affected),
		)
		return affected

	# ------------------------------------------------------------------
	# 5. generate_scenario
	# ------------------------------------------------------------------

	def generate_scenario(
		self,
		session: Session,
		scenario_id: str,
		tenant_id: str,
	) -> ScenarioModel:
		"""Generate a scenario by applying adjustment_rules to the base version.

		adjustment_rules format:
		    {"<account_prefix>": {"pct": <float>}, ...}
		    Use "*" as a catch-all.  Longest matching prefix wins.
		    pct=10 means +10%; pct=-5 means -5%.

		Creates a new WORKING BudgetVersion with adjusted lines.
		Sets scenario.generated_version_id and scenario.status=GENERATED.
		Emits ScenarioGeneratedEvent.
		"""
		scenario = session.execute(
			select(ScenarioModel).where(
				ScenarioModel.id == scenario_id,
				ScenarioModel.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if scenario is None:
			raise ScenarioNotFoundError(
				f"ScenarioModel {scenario_id!r} not found for tenant {tenant_id!r}"
			)

		base_version = _require_version(session, scenario.base_version_id, tenant_id)

		# Build sorted rules list (longest prefix first for matching)
		rules: dict[str, dict[str, Any]] = scenario.adjustment_rules or {}
		sorted_prefixes = sorted(
			(k for k in rules if k != "*"),
			key=len,
			reverse=True,
		)

		def _get_pct(account_code: str) -> float:
			for prefix in sorted_prefixes:
				if account_code.startswith(prefix):
					return float(rules[prefix].get("pct", 0))
			return float(rules.get("*", {}).get("pct", 0))

		# Clone base version lines with adjustments
		source_lines: list[BudgetLine] = session.execute(
			select(BudgetLine).where(
				BudgetLine.version_id == base_version.id,
				BudgetLine.tenant_id == tenant_id,
			)
		).scalars().all()

		new_version = BudgetVersion(
			tenant_id=tenant_id,
			cycle_id=base_version.cycle_id,
			version_name=f"{scenario.name} — {scenario.scenario_type}",
			version_type="WORKING",
			is_active=False,
			notes=f"Auto-generated from scenario {scenario.id}",
		)
		session.add(new_version)
		session.flush()

		lines_generated = 0
		for src in source_lines:
			pct = _get_pct(src.gl_account_code)
			factor = Decimal(str(1 + pct / 100))
			adjusted_cents = int(Decimal(str(src.amount_cents)) * factor)

			clone = BudgetLine(
				tenant_id=tenant_id,
				version_id=new_version.id,
				gl_account_code=src.gl_account_code,
				cost_center_code=src.cost_center_code,
				entity_id=src.entity_id,
				period_month=src.period_month,
				amount_cents=adjusted_cents,
				driver_type="FORMULA",
				driver_params={
					"scenario_id": scenario_id,
					"base_version_id": str(base_version.id),
					"adjustment_pct": pct,
					"original_cents": src.amount_cents,
				},
				narrative=f"Scenario adjustment: {pct:+.1f}%",
				status="DRAFT",
			)
			session.add(clone)
			lines_generated += 1

		scenario.generated_version_id = new_version.id
		scenario.status = "GENERATED"
		session.flush()

		emit_event(
			ScenarioGeneratedEvent(
				aggregate_id=scenario.id,
				aggregate_type="ScenarioModel",
				tenant_id=tenant_id,
				scenario_id=scenario.id,
				scenario_name=scenario.name,
				scenario_type=scenario.scenario_type,
				base_version_id=str(base_version.id),
				generated_version_id=str(new_version.id),
				lines_generated=lines_generated,
			),
			session,
		)

		log.info(
			"FPAService.generate_scenario: scenario=%r → version=%r lines=%d",
			scenario_id, new_version.id, lines_generated,
		)
		return scenario

	# ------------------------------------------------------------------
	# 6. approve_budget
	# ------------------------------------------------------------------

	def approve_budget(
		self,
		session: Session,
		version_id: str,
		approved_by: str,
		tenant_id: str,
	) -> BudgetVersion:
		"""Approve a BudgetVersion: lock all lines and mark the cycle APPROVED.

		Transitions:
		  - All DRAFT/SUBMITTED BudgetLines → APPROVED
		  - BudgetVersion.locked_at set to now()
		  - BudgetCycle.status → APPROVED
		  - BudgetCycle.approved_by, approved_at set

		Emits BudgetApprovedEvent.
		"""
		version = _require_version(session, version_id, tenant_id)
		if version.locked_at is not None:
			raise VersionLockedError(
				f"BudgetVersion {version_id!r} is already locked."
			)

		cycle = _require_cycle(session, version.cycle_id, tenant_id)
		if cycle.status == "LOCKED":
			raise CycleStatusError(
				f"BudgetCycle {cycle.id!r} is already LOCKED."
			)

		now = datetime.now(timezone.utc)

		# Lock all lines
		lines: list[BudgetLine] = session.execute(
			select(BudgetLine).where(
				BudgetLine.version_id == version_id,
				BudgetLine.tenant_id == tenant_id,
			)
		).scalars().all()

		total_budget_cents = 0
		for line in lines:
			line.status = "APPROVED"
			total_budget_cents += line.amount_cents

		version.locked_at = now
		cycle.status = "APPROVED"
		cycle.approved_by = approved_by
		cycle.approved_at = now
		session.flush()

		emit_event(
			BudgetApprovedEvent(
				aggregate_id=version.id,
				aggregate_type="BudgetVersion",
				tenant_id=tenant_id,
				cycle_id=str(cycle.id),
				version_id=version.id,
				version_name=version.version_name,
				approved_by=approved_by,
				total_budget_cents=total_budget_cents,
			),
			session,
		)

		log.info(
			"FPAService.approve_budget: version=%r locked, cycle=%r APPROVED, "
			"lines=%d total=%d",
			version_id, cycle.id, len(lines), total_budget_cents,
		)
		return version

	# ------------------------------------------------------------------
	# 7. take_forecast_snapshot
	# ------------------------------------------------------------------

	def take_forecast_snapshot(
		self,
		session: Session,
		cycle_id: str,
		snapshot_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Capture a point-in-time actuals vs budget vs forecast snapshot.

		For each (account, cost_centre, period_month) combination found in
		BudgetLine rows for the APPROVED/active version of cycle_id:
		  - actual_cents: pulled from GLAccountBalance (0 if GL unavailable)
		  - budget_cents: from BudgetLine
		  - forecast_cents: actual if period_month <= snapshot_date, else budget
		  - variance_cents: actual_cents - budget_cents
		  - variance_pct: variance / budget * 100 (0 if budget == 0)

		Inserts ForecastSnapshot rows (never updates existing ones).
		Emits ForecastSnapshotTakenEvent.
		Emits VarianceAlertEvent for any account exceeding _VARIANCE_ALERT_PCT.

		Returns:
		    {accounts_processed, total_actual_cents, total_budget_cents,
		     total_variance_cents, variance_pct}
		"""
		cycle = _require_cycle(session, cycle_id, tenant_id)

		# Find the active approved version for this cycle
		active_version = session.execute(
			select(BudgetVersion).where(
				BudgetVersion.cycle_id == cycle_id,
				BudgetVersion.tenant_id == tenant_id,
				BudgetVersion.is_active == True,  # noqa: E712
			).order_by(BudgetVersion.locked_at.desc().nullslast())
			.limit(1)
		).scalar_one_or_none()

		if active_version is None:
			log.warning(
				"FPAService.take_forecast_snapshot: no active version for cycle=%r",
				cycle_id,
			)
			return {
				"accounts_processed": 0,
				"total_actual_cents": 0,
				"total_budget_cents": 0,
				"total_variance_cents": 0,
				"variance_pct": 0.0,
			}

		# Lazy GL import for actuals
		gl_available = False
		try:
			from pgappforge.plugins.erp.finance.gl.models import (
				GLAccountBalance,
				GLPeriod,
			)
			gl_available = True
		except ImportError:
			log.warning(
				"FPAService.take_forecast_snapshot: GL plugin not available, "
				"actuals will be 0."
			)

		# Pull all budget lines for the active version — ONE query
		budget_lines: list[BudgetLine] = session.execute(
			select(BudgetLine).where(
				BudgetLine.version_id == active_version.id,
				BudgetLine.tenant_id == tenant_id,
			)
		).scalars().all()

		total_actual = 0
		total_budget = 0
		total_variance = 0
		accounts_processed = 0

		# Build lookup structures for GL data — zero DB calls in the loop below
		# {period_month: period_id}, {(account_code, period_id): actual_cents}
		month_to_period: dict[date, str] = {}
		actual_by_acct_period: dict[tuple[str, str], int] = {}

		if gl_available and budget_lines:
			unique_months: set[date] = {bl.period_month for bl in budget_lines}
			unique_account_codes: set[str] = {bl.gl_account_code for bl in budget_lines}

			# ONE query: all GL periods that cover any of our months
			period_rows = session.execute(
				select(GLPeriod).where(
					GLPeriod.tenant_id == tenant_id,
					GLPeriod.start_date <= max(unique_months),
					GLPeriod.end_date >= min(unique_months),
				)
			).scalars().all()

			# Build month → period_id lookup (a month may span one period)
			month_to_period: dict[date, str] = {}
			for pr in period_rows:
				for m in unique_months:
					if pr.start_date <= m <= pr.end_date:
						month_to_period[m] = str(pr.id)

			relevant_period_ids = list(set(month_to_period.values()))

			if relevant_period_ids and unique_account_codes:
				# ONE query: all GL balances for relevant accounts × periods
				gl_balances = session.execute(
					select(GLAccountBalance).where(
						GLAccountBalance.tenant_id == tenant_id,
						GLAccountBalance.account_code.in_(unique_account_codes),
						GLAccountBalance.period_id.in_(relevant_period_ids),
					)
				).scalars().all()

				for gb in gl_balances:
					key = (str(gb.account_code), str(gb.period_id))
					actual_by_acct_period[key] = gb.closing_debit - gb.closing_credit

		# Pure-Python loop — zero DB calls
		for bl in budget_lines:
			actual_cents = 0

			if gl_available:
				period_id = month_to_period.get(bl.period_month)
				if period_id is not None:
					actual_cents = actual_by_acct_period.get(
						(str(bl.gl_account_code), period_id), 0
					)

			budget_cents = bl.amount_cents
			is_past = bl.period_month <= snapshot_date
			forecast_cents = actual_cents if is_past else budget_cents
			variance_cents = actual_cents - budget_cents
			variance_pct: Decimal
			if budget_cents != 0:
				variance_pct = (Decimal(str(variance_cents)) / Decimal(str(budget_cents)) * 100).quantize(Decimal("0.0001"))
			else:
				variance_pct = Decimal("0")

			snap = ForecastSnapshot(
				tenant_id=tenant_id,
				cycle_id=cycle_id,
				snapshot_date=snapshot_date,
				period_month=bl.period_month,
				gl_account_code=bl.gl_account_code,
				cost_center_code=bl.cost_center_code,
				actual_cents=actual_cents,
				budget_cents=budget_cents,
				forecast_cents=forecast_cents,
				variance_cents=variance_cents,
				variance_pct=variance_pct,
			)
			session.add(snap)

			total_actual += actual_cents
			total_budget += budget_cents
			total_variance += variance_cents
			accounts_processed += 1

			# Emit alert if variance exceeds threshold
			if budget_cents != 0 and abs(float(variance_pct)) > _VARIANCE_ALERT_PCT:
				emit_event(
					VarianceAlertEvent(
						aggregate_id=cycle_id,
						aggregate_type="BudgetCycle",
						tenant_id=tenant_id,
						cycle_id=cycle_id,
						period_month=str(bl.period_month),
						gl_account_code=bl.gl_account_code,
						cost_center_code=bl.cost_center_code or "",
						actual_cents=actual_cents,
						budget_cents=budget_cents,
						variance_cents=variance_cents,
						variance_pct=float(variance_pct),
						alert_threshold_pct=_VARIANCE_ALERT_PCT,
					),
					session,
				)

		overall_variance_pct = 0.0
		if total_budget != 0:
			overall_variance_pct = round((total_variance / total_budget) * 100, 4)

		session.flush()

		emit_event(
			ForecastSnapshotTakenEvent(
				aggregate_id=cycle_id,
				aggregate_type="BudgetCycle",
				tenant_id=tenant_id,
				cycle_id=cycle_id,
				snapshot_date=str(snapshot_date),
				accounts_processed=accounts_processed,
				total_actual_cents=total_actual,
				total_budget_cents=total_budget,
				total_variance_cents=total_variance,
				variance_pct=overall_variance_pct,
			),
			session,
		)

		log.info(
			"FPAService.take_forecast_snapshot: cycle=%r snap=%s "
			"accounts=%d actual=%d budget=%d variance=%d (%.2f%%)",
			cycle_id, snapshot_date, accounts_processed,
			total_actual, total_budget, total_variance, overall_variance_pct,
		)
		return {
			"accounts_processed": accounts_processed,
			"total_actual_cents": total_actual,
			"total_budget_cents": total_budget,
			"total_variance_cents": total_variance,
			"variance_pct": overall_variance_pct,
		}

	# ------------------------------------------------------------------
	# 8. get_variance_analysis
	# ------------------------------------------------------------------

	def get_variance_analysis(
		self,
		session: Session,
		cycle_id: str,
		period_month: date,
		tenant_id: str = "",
	) -> list[dict[str, Any]]:
		"""Return variance analysis for a single period_month.

		Reads the most recent ForecastSnapshot rows for (cycle_id, period_month).
		If no snapshots exist yet, returns an empty list.

		Also attempts to enrich rows with gl_account_code→account_name from GL.

		Returns list of dicts:
		    [{gl_account_code, account_name, actual_cents, budget_cents,
		      variance_cents, variance_pct}]
		Sorted descending by abs(variance_cents).
		"""
		# Find the most recent snapshot_date for this cycle+period
		latest_snap_date = session.execute(
			select(func.max(ForecastSnapshot.snapshot_date)).where(
				ForecastSnapshot.cycle_id == cycle_id,
				ForecastSnapshot.tenant_id == tenant_id,
				ForecastSnapshot.period_month == period_month,
			)
		).scalar_one_or_none()

		if latest_snap_date is None:
			return []

		rows: list[ForecastSnapshot] = session.execute(
			select(ForecastSnapshot).where(
				ForecastSnapshot.cycle_id == cycle_id,
				ForecastSnapshot.tenant_id == tenant_id,
				ForecastSnapshot.period_month == period_month,
				ForecastSnapshot.snapshot_date == latest_snap_date,
			)
		).scalars().all()

		# Try to build account name lookup from GL
		account_names: dict[str, str] = {}
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLAccount
			acct_codes = {r.gl_account_code for r in rows}
			gl_accounts: list[GLAccount] = session.execute(
				select(GLAccount).where(
					GLAccount.account_code.in_(acct_codes),
					GLAccount.tenant_id == tenant_id,
				)
			).scalars().all()
			account_names = {a.account_code: a.account_name for a in gl_accounts}
		except ImportError:
			pass

		result = [
			{
				"gl_account_code": r.gl_account_code,
				"account_name": account_names.get(r.gl_account_code, ""),
				"actual_cents": r.actual_cents,
				"budget_cents": r.budget_cents,
				"variance_cents": r.variance_cents,
				"variance_pct": float(r.variance_pct),
			}
			for r in rows
		]

		result.sort(key=lambda x: abs(x["variance_cents"]), reverse=True)
		return result

	# ------------------------------------------------------------------
	# 9. compute_rolling_forecast
	# ------------------------------------------------------------------

	def compute_rolling_forecast(
		self,
		session: Session,
		cycle_id: str,
		as_of_date: date,
		horizon_months: int = 12,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Compute a rolling forecast from as_of_date over horizon_months.

		For each of the next horizon_months:
		  - If period_month <= as_of_date: use latest actual_cents from snapshots
		  - If period_month > as_of_date: use budget_cents from active BudgetVersion

		Returns:
		    {
		      months: [
		        {period_month, actual_cents, budget_cents, forecast_cents,
		         is_actual: bool}
		      ],
		      total_forecast_cents: int,
		    }
		"""
		from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]

		cycle = _require_cycle(session, cycle_id, tenant_id)

		# Build the month range: start from first day of as_of_date month
		start = date(as_of_date.year, as_of_date.month, 1)
		month_list = [start + relativedelta(months=i) for i in range(horizon_months)]

		# Get the active version
		active_version = session.execute(
			select(BudgetVersion).where(
				BudgetVersion.cycle_id == cycle_id,
				BudgetVersion.tenant_id == tenant_id,
				BudgetVersion.is_active == True,  # noqa: E712
			).order_by(BudgetVersion.locked_at.desc().nullslast())
			.limit(1)
		).scalar_one_or_none()

		# Pre-fetch budget lines keyed by (account_code, period_month)
		budget_by_month: dict[date, int] = {}
		if active_version:
			budget_lines: list[BudgetLine] = session.execute(
				select(BudgetLine).where(
					BudgetLine.version_id == active_version.id,
					BudgetLine.tenant_id == tenant_id,
					BudgetLine.period_month.in_(month_list),
				)
			).scalars().all()
			for bl in budget_lines:
				budget_by_month[bl.period_month] = (
					budget_by_month.get(bl.period_month, 0) + bl.amount_cents
				)

		# Pre-fetch latest actual snapshots for past months
		past_months = [m for m in month_list if m <= as_of_date]
		actual_by_month: dict[date, int] = {}
		if past_months:
			for pm in past_months:
				latest_snap = session.execute(
					select(func.max(ForecastSnapshot.snapshot_date)).where(
						ForecastSnapshot.cycle_id == cycle_id,
						ForecastSnapshot.tenant_id == tenant_id,
						ForecastSnapshot.period_month == pm,
					)
				).scalar_one_or_none()

				if latest_snap:
					agg = session.execute(
						select(func.sum(ForecastSnapshot.actual_cents)).where(
							ForecastSnapshot.cycle_id == cycle_id,
							ForecastSnapshot.tenant_id == tenant_id,
							ForecastSnapshot.period_month == pm,
							ForecastSnapshot.snapshot_date == latest_snap,
						)
					).scalar_one_or_none()
					actual_by_month[pm] = int(agg or 0)

		months_result = []
		total_forecast_cents = 0

		for month in month_list:
			is_actual = month <= as_of_date
			actual_cents = actual_by_month.get(month, 0)
			budget_cents = budget_by_month.get(month, 0)
			forecast_cents = actual_cents if is_actual else budget_cents

			months_result.append({
				"period_month": str(month),
				"actual_cents": actual_cents,
				"budget_cents": budget_cents,
				"forecast_cents": forecast_cents,
				"is_actual": is_actual,
			})
			total_forecast_cents += forecast_cents

		return {
			"months": months_result,
			"total_forecast_cents": total_forecast_cents,
		}

	# ------------------------------------------------------------------
	# 10. update_kpi
	# ------------------------------------------------------------------

	def update_kpi(
		self,
		session: Session,
		kpi_code: str,
		period_month: date,
		actual_value: Decimal | float | int,
		cycle_id: str,
		tenant_id: str,
	) -> KPITarget:
		"""Update actual_value for a KPITarget and auto-compute status.

		Status rules (based on abs(variance_pct) from target):
		    <= 5%   → ON_TRACK
		    5–15%   → AT_RISK
		    > 15%   → OFF_TRACK

		For LOWER_IS_BETTER KPIs, a positive variance (actual > target) is bad.
		Emits KPIStatusChangedEvent if status changes.

		Raises FPAServiceError if no KPITarget exists for (kpi_code, period_month, cycle_id).
		"""
		kpi = session.execute(
			select(KPITarget).where(
				KPITarget.tenant_id == tenant_id,
				KPITarget.kpi_code == kpi_code,
				KPITarget.cycle_id == cycle_id,
				KPITarget.period_month == period_month,
			)
		).scalar_one_or_none()

		if kpi is None:
			raise FPAServiceError(
				f"KPITarget kpi_code={kpi_code!r} period={period_month} "
				f"cycle={cycle_id!r} not found for tenant {tenant_id!r}"
			)

		old_status = kpi.status
		actual_dec = Decimal(str(actual_value))
		kpi.actual_value = actual_dec

		# Compute variance %
		if kpi.target_value and kpi.target_value != 0:
			raw_variance_pct = float(
				(actual_dec - kpi.target_value) / kpi.target_value * 100
			)
		else:
			raw_variance_pct = 0.0

		# For LOWER_IS_BETTER, positive variance (over target) is bad
		if kpi.direction == "LOWER_IS_BETTER":
			# worse = actual > target → positive variance
			severity_pct = raw_variance_pct  # positive = bad
		else:
			# HIGHER_IS_BETTER: worse = actual < target → negative variance
			severity_pct = -raw_variance_pct  # positive = bad (shortfall)

		# Classify
		abs_severity = abs(severity_pct)
		if abs_severity <= _KPI_AT_RISK_PCT:
			new_status = "ON_TRACK"
		elif abs_severity <= _KPI_OFF_TRACK_PCT:
			new_status = "AT_RISK"
		else:
			new_status = "OFF_TRACK"

		kpi.status = new_status
		session.flush()

		if old_status != new_status:
			emit_event(
				KPIStatusChangedEvent(
					aggregate_id=kpi.id,
					aggregate_type="KPITarget",
					tenant_id=tenant_id,
					kpi_target_id=kpi.id,
					kpi_code=kpi_code,
					cycle_id=cycle_id,
					period_month=str(period_month),
					old_status=old_status,
					new_status=new_status,
					target_value=float(kpi.target_value),
					actual_value=float(actual_dec),
					variance_pct=round(raw_variance_pct, 4),
				),
				session,
			)

		log.info(
			"FPAService.update_kpi: kpi=%r period=%s actual=%s "
			"target=%s status=%s→%s",
			kpi_code, period_month, actual_dec, kpi.target_value,
			old_status, new_status,
		)
		return kpi


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
	"FPAService",
	"FPAServiceError",
	"CycleNotFoundError",
	"VersionNotFoundError",
	"DriverNotFoundError",
	"ScenarioNotFoundError",
	"VersionLockedError",
	"CycleStatusError",
]
