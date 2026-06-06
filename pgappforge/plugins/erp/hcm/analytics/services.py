"""
pgappforge/plugins/erp/hcm/analytics/services.py

HrAnalyticsService — stateless HR analytics business logic.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Monetary invariants:
  - All cost amounts stored and returned as integer cents
  - Rates and percentages returned as Decimal strings — never float

Key methods:
  compute_headcount(tenant_id, as_of_date, session, *, entity_id=None) -> dict
  compute_turnover(tenant_id, period_start, period_end, session, *, entity_id=None) -> dict
  compute_diversity(tenant_id, as_of_date, session) -> dict
  compute_flight_risk(employee_id, tenant_id, session) -> HrFlightRiskScore
  get_cost_per_hire(tenant_id, period_start, period_end, session) -> dict
  generate_snapshot(tenant_id, snapshot_type, period, session, *, entity_id=None) -> HrAnalyticsSnapshot
  get_dashboard(tenant_id, session, *, entity_id=None) -> dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.hcm.analytics.events import (
	AnalyticsReportGeneratedEvent,
	FlightRiskAlertEvent,
	HeadcountChangedEvent,
	TurnoverAlertEvent,
)
from pgappforge.plugins.erp.foundation.events import emit_event

log = logging.getLogger(__name__)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

# Flight risk score thresholds
_RISK_THRESHOLDS = {
	"LOW": (0, 30),
	"MEDIUM": (31, 60),
	"HIGH": (61, 80),
	"CRITICAL": (81, 100),
}

# Turnover alert threshold (%) — configurable via app config; default 15%
_DEFAULT_TURNOVER_ALERT_PCT = Decimal("15.0")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AnalyticsServiceError(Exception):
	"""Base domain error for analytics operations."""


class AnalyticsNotFoundError(AnalyticsServiceError):
	"""Raised when a required analytics record is not found."""


class AnalyticsStateError(AnalyticsServiceError):
	"""Raised when an operation is not valid for the current state."""


# BPM action registration — must happen at import time
try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMActionRegistry
	_bpm_available = True
except ImportError:
	_bpm_available = False
	_BPMActionRegistry = None  # type: ignore[assignment]


def _register_bpm(name: str, description: str):
	"""Decorator shim — no-op when BPM engine is not loaded."""
	def decorator(fn):
		if _bpm_available and _BPMActionRegistry is not None:
			_BPMActionRegistry.register(name, description)(fn)
		return fn
	return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_level_for_score(score: int) -> str:
	if score <= 30:
		return "LOW"
	if score <= 60:
		return "MEDIUM"
	if score <= 80:
		return "HIGH"
	return "CRITICAL"


def _period_label(period_start: date, period_end: date) -> str:
	"""Derive a coarse period label from a date range."""
	if period_start.month == 1 and period_end.month == 12:
		return str(period_start.year)
	# Quarter detection
	quarter_map = {1: "Q1", 2: "Q1", 3: "Q1", 4: "Q2", 5: "Q2", 6: "Q2",
				   7: "Q3", 8: "Q3", 9: "Q3", 10: "Q4", 11: "Q4", 12: "Q4"}
	if quarter_map[period_start.month] == quarter_map[period_end.month]:
		return f"{period_start.year}-{quarter_map[period_start.month]}"
	return f"{period_start.year}-{period_start.month:02d}"


# ---------------------------------------------------------------------------
# HrAnalyticsService
# ---------------------------------------------------------------------------

class HrAnalyticsService:
	"""Stateless HR analytics service.

	All public methods accept an explicit ``session`` argument and do NOT
	commit — transaction management belongs to the caller.
	"""

	# ------------------------------------------------------------------
	# compute_headcount
	# ------------------------------------------------------------------

	@staticmethod
	def compute_headcount(
		tenant_id: str,
		as_of_date: date,
		session: Any,
		*,
		entity_id: str | None = None,
	) -> dict:
		"""Compute headcount as of a given date.

		Queries the HCM employee/personnel table for active employees at the
		specified date.  Groups by department, employment_type, and gender.

		Returns:
		  {
		    total: int,
		    by_department: {dept_id: count, ...},
		    by_type: {FULL_TIME: n, PART_TIME: n, CONTRACT: n, ...},
		    by_gender: {M: n, F: n, OTHER: n, UNSPECIFIED: n},
		    as_of: "YYYY-MM-DD",
		    entity_id: str | None,
		  }
		"""
		assert tenant_id, "tenant_id is required"
		assert as_of_date is not None, "as_of_date is required"

		# Attempt to import the personnel model — graceful degradation if absent
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee  # type: ignore[import]
		except ImportError:
			log.warning("compute_headcount: HCM personnel model not available; returning empty result")
			return {
				"total": 0,
				"by_department": {},
				"by_type": {},
				"by_gender": {},
				"as_of": as_of_date.isoformat(),
				"entity_id": entity_id,
			}

		stmt = (
			sa.select(Employee)
			.where(Employee.tenant_id == tenant_id)
			.where(Employee.employment_status == "ACTIVE")
			.where(Employee.start_date <= as_of_date)
			.where(
				sa.or_(
					Employee.termination_date.is_(None),
					Employee.termination_date > as_of_date,
				)
			)
		)
		if entity_id:
			stmt = stmt.where(Employee.department_id == entity_id)

		rows = session.execute(stmt).scalars().all()

		by_dept: dict[str, int] = {}
		by_type: dict[str, int] = {}
		by_gender: dict[str, int] = {}

		for emp in rows:
			dept = str(emp.department_id) if emp.department_id else "UNASSIGNED"
			by_dept[dept] = by_dept.get(dept, 0) + 1

			etype = str(emp.employment_type) if emp.employment_type else "UNSPECIFIED"
			by_type[etype] = by_type.get(etype, 0) + 1

			gender = str(emp.gender).upper() if emp.gender else "UNSPECIFIED"
			if gender not in ("M", "F", "OTHER"):
				gender = "UNSPECIFIED"
			by_gender[gender] = by_gender.get(gender, 0) + 1

		result = {
			"total": len(rows),
			"by_department": by_dept,
			"by_type": by_type,
			"by_gender": by_gender,
			"as_of": as_of_date.isoformat(),
			"entity_id": entity_id,
		}

		log.debug(
			"compute_headcount: tenant=%s as_of=%s total=%d",
			tenant_id, as_of_date, result["total"],
		)
		return result

	# ------------------------------------------------------------------
	# compute_turnover
	# ------------------------------------------------------------------

	@staticmethod
	def compute_turnover(
		tenant_id: str,
		period_start: date,
		period_end: date,
		session: Any,
		*,
		entity_id: str | None = None,
	) -> dict:
		"""Compute turnover metrics for a date range.

		Counts terminations in the period and computes the turnover rate
		against average headcount (headcount at period_start + period_end) / 2.

		Voluntary vs involuntary split uses the ``termination_type`` field:
		  VOLUNTARY → voluntary count
		  INVOLUNTARY | REDUNDANCY | DISMISSAL → involuntary count

		Returns:
		  {
		    period: "YYYY-MM-DD/YYYY-MM-DD",
		    period_start: "YYYY-MM-DD",
		    period_end: "YYYY-MM-DD",
		    total_terminations: int,
		    voluntary: int,
		    involuntary: int,
		    avg_headcount: int,
		    turnover_rate_pct: "18.50",       # Decimal string
		    annualized_rate_pct: "74.00",      # Decimal string — rate * (365/days_in_period)
		    entity_id: str | None,
		  }
		"""
		assert tenant_id, "tenant_id is required"
		assert period_start <= period_end, "period_start must be <= period_end"

		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee  # type: ignore[import]
		except ImportError:
			log.warning("compute_turnover: HCM personnel model not available; returning empty result")
			empty_rate = "0.00"
			return {
				"period": f"{period_start.isoformat()}/{period_end.isoformat()}",
				"period_start": period_start.isoformat(),
				"period_end": period_end.isoformat(),
				"total_terminations": 0,
				"voluntary": 0,
				"involuntary": 0,
				"avg_headcount": 0,
				"turnover_rate_pct": empty_rate,
				"annualized_rate_pct": empty_rate,
				"entity_id": entity_id,
			}

		# Active employees at period start
		def _headcount_at(dt: date) -> int:
			stmt = (
				sa.select(sa.func.count())
				.select_from(Employee)
				.where(Employee.tenant_id == tenant_id)
				.where(Employee.employment_status == "ACTIVE")
				.where(Employee.start_date <= dt)
				.where(
					sa.or_(
						Employee.termination_date.is_(None),
						Employee.termination_date > dt,
					)
				)
			)
			if entity_id:
				stmt = stmt.where(Employee.department_id == entity_id)
			return session.execute(stmt).scalar_one() or 0

		hc_start = _headcount_at(period_start)
		hc_end = _headcount_at(period_end)
		avg_hc = (hc_start + hc_end) // 2

		# Terminations in the period
		term_stmt = (
			sa.select(Employee)
			.where(Employee.tenant_id == tenant_id)
			.where(Employee.employment_status == "TERMINATED")
			.where(Employee.termination_date >= period_start)
			.where(Employee.termination_date <= period_end)
		)
		if entity_id:
			term_stmt = term_stmt.where(Employee.department_id == entity_id)

		terminated = session.execute(term_stmt).scalars().all()

		voluntary = 0
		involuntary = 0
		for emp in terminated:
			ttype = str(emp.termination_type or "").upper()
			if ttype == "VOLUNTARY":
				voluntary += 1
			else:
				involuntary += 1

		total_terminations = len(terminated)

		# Turnover rate
		if avg_hc > 0:
			rate = Decimal(total_terminations) / Decimal(avg_hc) * _HUNDRED
		else:
			rate = _ZERO

		# Annualise: rate * (365 / days_in_period)
		days_in_period = (period_end - period_start).days + 1
		if days_in_period > 0:
			annualized = rate * Decimal(365) / Decimal(days_in_period)
		else:
			annualized = _ZERO

		rate_str = str(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
		annualized_str = str(annualized.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

		result = {
			"period": f"{period_start.isoformat()}/{period_end.isoformat()}",
			"period_start": period_start.isoformat(),
			"period_end": period_end.isoformat(),
			"total_terminations": total_terminations,
			"voluntary": voluntary,
			"involuntary": involuntary,
			"avg_headcount": avg_hc,
			"turnover_rate_pct": rate_str,
			"annualized_rate_pct": annualized_str,
			"entity_id": entity_id,
		}

		# Emit alert if turnover exceeds threshold
		if rate >= _DEFAULT_TURNOVER_ALERT_PCT:
			emit_event(
				TurnoverAlertEvent(
					aggregate_id=tenant_id,
					aggregate_type="Tenant",
					tenant_id=tenant_id,
					entity_id=entity_id or "",
					rate_pct=rate_str,
					period=f"{period_start.isoformat()}/{period_end.isoformat()}",
				),
				session,
			)

		log.debug(
			"compute_turnover: tenant=%s period=%s/%s terminations=%d rate=%s%%",
			tenant_id, period_start, period_end, total_terminations, rate_str,
		)
		return result

	# ------------------------------------------------------------------
	# compute_diversity
	# ------------------------------------------------------------------

	@staticmethod
	def compute_diversity(
		tenant_id: str,
		as_of_date: date,
		session: Any,
	) -> dict:
		"""Compute workforce diversity metrics as of a date.

		Gender distribution and age bracket breakdown.
		representation_index: normalised Shannon entropy [0,1] across gender buckets
		  — 1.0 = perfectly equal, 0.0 = single category dominates.

		Returns:
		  {
		    as_of: "YYYY-MM-DD",
		    total: int,
		    gender: {M: n, F: n, OTHER: n, UNSPECIFIED: n},
		    age_brackets: {"18-25": n, "26-35": n, "36-45": n, "46-55": n, "56+": n},
		    representation_index: "0.87",   # Decimal string [0,1]
		  }
		"""
		assert tenant_id, "tenant_id is required"

		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee  # type: ignore[import]
		except ImportError:
			log.warning("compute_diversity: HCM personnel model not available; returning empty result")
			return {
				"as_of": as_of_date.isoformat(),
				"total": 0,
				"gender": {"M": 0, "F": 0, "OTHER": 0, "UNSPECIFIED": 0},
				"age_brackets": {"18-25": 0, "26-35": 0, "36-45": 0, "46-55": 0, "56+": 0},
				"representation_index": "0.00",
			}

		stmt = (
			sa.select(Employee)
			.where(Employee.tenant_id == tenant_id)
			.where(Employee.employment_status == "ACTIVE")
			.where(Employee.start_date <= as_of_date)
			.where(
				sa.or_(
					Employee.termination_date.is_(None),
					Employee.termination_date > as_of_date,
				)
			)
		)
		rows = session.execute(stmt).scalars().all()

		gender_counts: dict[str, int] = {"M": 0, "F": 0, "OTHER": 0, "UNSPECIFIED": 0}
		age_brackets: dict[str, int] = {"18-25": 0, "26-35": 0, "36-45": 0, "46-55": 0, "56+": 0}

		for emp in rows:
			# Gender
			g = str(emp.gender or "").upper()
			if g not in ("M", "F", "OTHER"):
				g = "UNSPECIFIED"
			gender_counts[g] = gender_counts.get(g, 0) + 1

			# Age bracket
			dob = getattr(emp, "date_of_birth", None)
			if dob is not None:
				age = (as_of_date - dob).days // 365
				if age < 26:
					age_brackets["18-25"] += 1
				elif age < 36:
					age_brackets["26-35"] += 1
				elif age < 46:
					age_brackets["36-45"] += 1
				elif age < 56:
					age_brackets["46-55"] += 1
				else:
					age_brackets["56+"] += 1

		total = len(rows)

		# Shannon entropy representation index (gender buckets)
		import math
		entropy = Decimal("0")
		if total > 0:
			for count in gender_counts.values():
				if count > 0:
					p = Decimal(count) / Decimal(total)
					entropy -= p * Decimal(str(math.log(float(p))))
			# Normalise: H / ln(k) where k = number of non-empty categories
			non_empty = sum(1 for c in gender_counts.values() if c > 0)
			if non_empty > 1:
				max_entropy = Decimal(str(math.log(non_empty)))
				representation_index = entropy / max_entropy
			else:
				representation_index = Decimal("0")
		else:
			representation_index = Decimal("0")

		rep_str = str(representation_index.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

		return {
			"as_of": as_of_date.isoformat(),
			"total": total,
			"gender": gender_counts,
			"age_brackets": age_brackets,
			"representation_index": rep_str,
		}

	# ------------------------------------------------------------------
	# compute_flight_risk
	# ------------------------------------------------------------------

	@staticmethod
	def compute_flight_risk(
		employee_id: str,
		tenant_id: str,
		session: Any,
	) -> "HrFlightRiskScore":
		"""Compute and persist a flight risk score for an employee.

		Scoring model (additive; capped at 100):
		  +30  tenure < 1 year (honeymoon period — high attrition risk)
		  +20  no promotion in last 3 years
		  +25  engagement_score < 3 (on 1-5 scale)
		  +15  current manager tenure < 6 months (new-manager instability)
		  +10  market salary gap flagged in personnel metadata

		Risk levels:
		   0–30  → LOW
		  31–60  → MEDIUM
		  61–80  → HIGH
		  81–100 → CRITICAL

		Side effects:
		  - Sets is_current=False on all prior scores for this employee.
		  - Inserts new HrFlightRiskScore with is_current=True.
		  - Emits FlightRiskAlertEvent if level is HIGH or CRITICAL.

		Returns the newly inserted HrFlightRiskScore.
		"""
		assert employee_id, "employee_id is required"
		assert tenant_id, "tenant_id is required"

		from pgappforge.plugins.erp.hcm.analytics.models import HrFlightRiskScore

		score_total = 0
		factors: list[dict[str, Any]] = []
		today = date.today()

		# ------------------------------------------------------------------
		# Gather employee data (best-effort; graceful when model absent)
		# ------------------------------------------------------------------
		emp = None
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee  # type: ignore[import]
			emp = session.execute(
				sa.select(Employee).where(Employee.id == employee_id)
			).scalar_one_or_none()
		except ImportError:
			log.debug("compute_flight_risk: personnel model not available; using defaults")

		# Factor 1: tenure < 1 year
		if emp is not None and emp.start_date is not None:
			tenure_days = (today - emp.start_date).days
			if tenure_days < 365:
				score_total += 30
				factors.append({
					"factor": "short_tenure",
					"weight": 30,
					"value": tenure_days,
					"description": f"Tenure {tenure_days} days < 1 year",
				})

		# Factor 2: no promotion in 3 years
		no_promo = True
		if emp is not None:
			last_promo = getattr(emp, "last_promotion_date", None)
			if last_promo is not None:
				months_since_promo = (today - last_promo).days / 30.44
				if months_since_promo <= 36:
					no_promo = False
		if no_promo:
			score_total += 20
			factors.append({
				"factor": "no_promotion_3yr",
				"weight": 20,
				"value": True,
				"description": "No promotion recorded in last 3 years",
			})

		# Factor 3: low engagement score
		if emp is not None:
			engagement = getattr(emp, "engagement_score", None)
			if engagement is not None and float(engagement) < 3.0:
				score_total += 25
				factors.append({
					"factor": "low_engagement",
					"weight": 25,
					"value": float(engagement),
					"description": f"Engagement score {engagement} < 3",
				})

		# Factor 4: manager tenure < 6 months
		if emp is not None:
			manager_id = getattr(emp, "manager_id", None)
			if manager_id is not None:
				try:
					from pgappforge.plugins.erp.hcm.personnel.models import Employee as _Emp  # type: ignore[import]
					manager = session.execute(
						sa.select(_Emp).where(_Emp.id == str(manager_id))
					).scalar_one_or_none()
					if manager is not None and manager.start_date is not None:
						mgr_tenure_days = (today - manager.start_date).days
						if mgr_tenure_days < 183:
							score_total += 15
							factors.append({
								"factor": "new_manager",
								"weight": 15,
								"value": mgr_tenure_days,
								"description": f"Manager tenure {mgr_tenure_days} days < 6 months",
							})
				except Exception as exc:
					log.debug("compute_flight_risk: manager lookup failed: %s", exc)

		# Factor 5: market salary gap from metadata
		if emp is not None:
			metadata = getattr(emp, "metadata_", None) or {}
			if isinstance(metadata, dict) and metadata.get("market_salary_gap_flagged"):
				score_total += 10
				factors.append({
					"factor": "market_salary_gap",
					"weight": 10,
					"value": True,
					"description": "Market salary gap flagged in personnel metadata",
				})

		# Cap score at 100
		score_total = min(score_total, 100)
		risk_level = _risk_level_for_score(score_total)

		# ------------------------------------------------------------------
		# Retire previous scores
		# ------------------------------------------------------------------
		session.execute(
			sa.update(HrFlightRiskScore)
			.where(HrFlightRiskScore.employee_id == employee_id)
			.where(HrFlightRiskScore.is_current.is_(True))
			.values(is_current=False, updated_at=datetime.now(timezone.utc))
		)

		# ------------------------------------------------------------------
		# Insert new score
		# ------------------------------------------------------------------
		new_score = HrFlightRiskScore(
			tenant_id=tenant_id,
			employee_id=employee_id,
			score=score_total,
			risk_level=risk_level,
			factors=factors,
			computed_at=datetime.now(timezone.utc),
			is_current=True,
		)
		session.add(new_score)
		session.flush()

		log.info(
			"compute_flight_risk: employee=%s score=%d level=%s",
			employee_id, score_total, risk_level,
		)

		# ------------------------------------------------------------------
		# Emit alert for HIGH / CRITICAL
		# ------------------------------------------------------------------
		if risk_level in ("HIGH", "CRITICAL"):
			emit_event(
				FlightRiskAlertEvent(
					aggregate_id=employee_id,
					aggregate_type="Employee",
					tenant_id=tenant_id,
					employee_id=employee_id,
					risk_score=score_total,
					risk_level=risk_level,
					factors=factors,
				),
				session,
			)

		assert new_score.id, "HrFlightRiskScore must have an id after flush"
		return new_score

	# ------------------------------------------------------------------
	# get_cost_per_hire
	# ------------------------------------------------------------------

	@staticmethod
	def get_cost_per_hire(
		tenant_id: str,
		period_start: date,
		period_end: date,
		session: Any,
	) -> dict:
		"""Compute cost-per-hire for a date range.

		Sums recruitment cost metadata from employee records where
		``metadata_['recruitment_cost_cents']`` is present and hire date falls
		within the period.

		Returns:
		  {
		    period: "YYYY-MM-DD/YYYY-MM-DD",
		    period_start: "YYYY-MM-DD",
		    period_end: "YYYY-MM-DD",
		    total_cost_cents: int,
		    total_hires: int,
		    cost_per_hire_cents: int,   # 0 if no hires
		  }
		"""
		assert tenant_id, "tenant_id is required"
		assert period_start <= period_end, "period_start must be <= period_end"

		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee  # type: ignore[import]
		except ImportError:
			log.warning("get_cost_per_hire: HCM personnel model not available; returning empty result")
			return {
				"period": f"{period_start.isoformat()}/{period_end.isoformat()}",
				"period_start": period_start.isoformat(),
				"period_end": period_end.isoformat(),
				"total_cost_cents": 0,
				"total_hires": 0,
				"cost_per_hire_cents": 0,
			}

		stmt = (
			sa.select(Employee)
			.where(Employee.tenant_id == tenant_id)
			.where(Employee.start_date >= period_start)
			.where(Employee.start_date <= period_end)
		)
		hires = session.execute(stmt).scalars().all()

		total_cost_cents = 0
		for emp in hires:
			meta = getattr(emp, "metadata_", None) or {}
			if isinstance(meta, dict):
				cost = meta.get("recruitment_cost_cents")
				if cost is not None:
					total_cost_cents += int(cost)

		total_hires = len(hires)
		cost_per_hire = total_cost_cents // total_hires if total_hires > 0 else 0

		return {
			"period": f"{period_start.isoformat()}/{period_end.isoformat()}",
			"period_start": period_start.isoformat(),
			"period_end": period_end.isoformat(),
			"total_cost_cents": total_cost_cents,
			"total_hires": total_hires,
			"cost_per_hire_cents": cost_per_hire,
		}

	# ------------------------------------------------------------------
	# generate_snapshot
	# ------------------------------------------------------------------

	@staticmethod
	def generate_snapshot(
		tenant_id: str,
		snapshot_type: str,
		period: str,
		session: Any,
		*,
		entity_id: str | None = None,
		period_start: date | None = None,
		period_end: date | None = None,
	) -> "HrAnalyticsSnapshot":
		"""Compute and persist an HrAnalyticsSnapshot.

		Dispatches to the appropriate compute_ method based on snapshot_type.
		Emits AnalyticsReportGeneratedEvent after storing.

		Args:
		  tenant_id:     Tenant UUID string.
		  snapshot_type: HEADCOUNT | TURNOVER | DIVERSITY | COST_PER_HIRE.
		  period:        Period label e.g. "2025-Q1".
		  session:       SQLAlchemy session.
		  entity_id:     Optional department/cost-centre UUID.
		  period_start:  Required for TURNOVER / COST_PER_HIRE.
		  period_end:    Required for TURNOVER / COST_PER_HIRE.

		Returns the newly inserted HrAnalyticsSnapshot.
		"""
		assert tenant_id, "tenant_id is required"
		assert snapshot_type, "snapshot_type is required"
		assert period, "period is required"

		from pgappforge.plugins.erp.hcm.analytics.models import HrAnalyticsSnapshot

		today = date.today()
		as_of = period_end or today

		valid_types = {"HEADCOUNT", "TURNOVER", "DIVERSITY", "COST_PER_HIRE", "TIME_TO_FILL", "ENGAGEMENT"}
		if snapshot_type not in valid_types:
			raise AnalyticsStateError(
				f"Unknown snapshot_type {snapshot_type!r}; "
				f"must be one of {sorted(valid_types)}"
			)

		# Dispatch
		if snapshot_type == "HEADCOUNT":
			data = HrAnalyticsService.compute_headcount(
				tenant_id, as_of, session, entity_id=entity_id
			)
		elif snapshot_type == "TURNOVER":
			if period_start is None or period_end is None:
				raise AnalyticsServiceError("period_start and period_end are required for TURNOVER snapshot")
			data = HrAnalyticsService.compute_turnover(
				tenant_id, period_start, period_end, session, entity_id=entity_id
			)
		elif snapshot_type == "DIVERSITY":
			data = HrAnalyticsService.compute_diversity(tenant_id, as_of, session)
		elif snapshot_type == "COST_PER_HIRE":
			if period_start is None or period_end is None:
				raise AnalyticsServiceError("period_start and period_end are required for COST_PER_HIRE snapshot")
			data = HrAnalyticsService.get_cost_per_hire(
				tenant_id, period_start, period_end, session
			)
		else:
			# TIME_TO_FILL / ENGAGEMENT — placeholder; return empty data
			log.info("generate_snapshot: snapshot_type=%s not yet implemented; storing empty data", snapshot_type)
			data = {"snapshot_type": snapshot_type, "period": period, "note": "not_yet_implemented"}

		snapshot = HrAnalyticsSnapshot(
			tenant_id=tenant_id,
			snapshot_type=snapshot_type,
			period=period,
			entity_id=entity_id,
			data=data,
			computed_at=datetime.now(timezone.utc),
			period_start=period_start,
			period_end=period_end,
		)
		session.add(snapshot)
		session.flush()

		emit_event(
			AnalyticsReportGeneratedEvent(
				aggregate_id=snapshot.id,
				aggregate_type="HrAnalyticsSnapshot",
				tenant_id=tenant_id,
				report_id=snapshot.id,
				report_type=snapshot_type,
				period=period,
				entity_id=entity_id or "",
			),
			session,
		)

		log.info(
			"generate_snapshot: tenant=%s type=%s period=%s id=%s",
			tenant_id, snapshot_type, period, snapshot.id,
		)
		assert snapshot.id, "HrAnalyticsSnapshot must have an id after flush"
		return snapshot

	# ------------------------------------------------------------------
	# get_dashboard
	# ------------------------------------------------------------------

	@staticmethod
	def get_dashboard(
		tenant_id: str,
		session: Any,
		*,
		entity_id: str | None = None,
	) -> dict:
		"""Return a consolidated HR analytics dashboard dict.

		Combines:
		  - Current headcount (as of today)
		  - YTD turnover
		  - Count of HIGH/CRITICAL flight risk employees
		  - Open position count (if recruitment model available)
		  - Latest stored snapshots (one per type)

		Returns:
		  {
		    headcount: {total, by_department, by_type, by_gender, as_of},
		    turnover_ytd: {period, total_terminations, turnover_rate_pct, ...},
		    flight_risk_high_count: int,
		    open_positions: int,
		    latest_snapshots: {HEADCOUNT: {...}, TURNOVER: {...}, ...},
		  }
		"""
		assert tenant_id, "tenant_id is required"

		from pgappforge.plugins.erp.hcm.analytics.models import HrAnalyticsSnapshot, HrFlightRiskScore

		today = date.today()
		year_start = date(today.year, 1, 1)

		# Headcount today
		headcount = HrAnalyticsService.compute_headcount(
			tenant_id, today, session, entity_id=entity_id
		)

		# YTD turnover
		turnover_ytd = HrAnalyticsService.compute_turnover(
			tenant_id, year_start, today, session, entity_id=entity_id
		)

		# Flight risk HIGH/CRITICAL count
		fr_stmt = (
			sa.select(sa.func.count())
			.select_from(HrFlightRiskScore)
			.where(HrFlightRiskScore.tenant_id == tenant_id)
			.where(HrFlightRiskScore.is_current.is_(True))
			.where(HrFlightRiskScore.risk_level.in_(["HIGH", "CRITICAL"]))
		)
		flight_risk_high_count = session.execute(fr_stmt).scalar_one() or 0

		# Open positions (best-effort)
		open_positions = 0
		try:
			from pgappforge.plugins.erp.hcm.recruitment.models import JobOpening  # type: ignore[import]
			op_stmt = (
				sa.select(sa.func.count())
				.select_from(JobOpening)
				.where(JobOpening.tenant_id == tenant_id)
				.where(JobOpening.status == "OPEN")
			)
			open_positions = session.execute(op_stmt).scalar_one() or 0
		except ImportError:
			pass
		except Exception as exc:
			log.debug("get_dashboard: open_positions lookup failed: %s", exc)

		# Latest snapshots — one per type
		snapshot_types = ["HEADCOUNT", "TURNOVER", "DIVERSITY", "COST_PER_HIRE", "TIME_TO_FILL", "ENGAGEMENT"]
		latest_snapshots: dict[str, Any] = {}
		for stype in snapshot_types:
			snap_stmt = (
				sa.select(HrAnalyticsSnapshot)
				.where(HrAnalyticsSnapshot.tenant_id == tenant_id)
				.where(HrAnalyticsSnapshot.snapshot_type == stype)
				.order_by(HrAnalyticsSnapshot.computed_at.desc())
				.limit(1)
			)
			if entity_id:
				snap_stmt = snap_stmt.where(HrAnalyticsSnapshot.entity_id == entity_id)
			snap = session.execute(snap_stmt).scalar_one_or_none()
			if snap is not None:
				latest_snapshots[stype] = {
					"id": snap.id,
					"period": snap.period,
					"computed_at": snap.computed_at.isoformat(),
					"data": snap.data,
				}

		return {
			"headcount": headcount,
			"turnover_ytd": turnover_ytd,
			"flight_risk_high_count": flight_risk_high_count,
			"open_positions": open_positions,
			"latest_snapshots": latest_snapshots,
		}


# ---------------------------------------------------------------------------
# BPM action registration
# ---------------------------------------------------------------------------

@_register_bpm("hcm.analytics.compute_flight_risk", "Compute employee flight risk score")
def _bpm_compute_flight_risk(
	record_ctx: dict,
	session: Any,
	employee_id: str = "",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	"""BPM-callable wrapper for HrAnalyticsService.compute_flight_risk().

	Resolves tenant_id from record_ctx if not supplied explicitly.
	Returns the persisted score record id and risk level.
	"""
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	_employee_id = employee_id or record_ctx.get("employee_id", "") or record_ctx.get("aggregate_id", "")
	if not _employee_id:
		return {"status": "error", "message": "employee_id is required"}
	if not _tenant_id:
		return {"status": "error", "message": "tenant_id is required"}
	try:
		score = HrAnalyticsService.compute_flight_risk(
			employee_id=_employee_id,
			tenant_id=_tenant_id,
			session=session,
		)
		return {
			"status": "ok",
			"score_id": score.id,
			"employee_id": score.employee_id,
			"score": score.score,
			"risk_level": score.risk_level,
		}
	except Exception as exc:
		log.warning("bpm hcm.analytics.compute_flight_risk failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"HrAnalyticsService",
	"AnalyticsServiceError",
	"AnalyticsNotFoundError",
	"AnalyticsStateError",
]
