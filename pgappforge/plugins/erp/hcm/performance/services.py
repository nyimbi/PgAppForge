"""
pgappforge/plugins/erp/hcm/performance/services.py

PerformanceService — stateless performance review domain service.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Public methods:
  start_cycle(...)              -> PerformanceCycle
  request_reviews(...)          -> list[PerformanceReview]
  submit_review(...)            -> PerformanceReview
  calibrate(...)                -> list[dict]
  create_goal(...)              -> Goal
  update_progress(...)          -> Goal
  give_feedback(...)            -> ContinuousFeedback
  get_employee_performance(...) -> dict
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PerformanceServiceError(Exception):
	"""Base domain error for performance operations."""


class CycleNotFoundError(PerformanceServiceError):
	pass


class ReviewNotFoundError(PerformanceServiceError):
	pass


class GoalNotFoundError(PerformanceServiceError):
	pass


class PerformanceStateError(PerformanceServiceError):
	"""Invalid state transition."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("PerformanceService._emit: could not emit %s: %s", type(event).__name__, exc)


def _decimal(value: Any) -> Decimal:
	return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# BPM registration
# ---------------------------------------------------------------------------

def _register_bpm() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry

		@BPMActionRegistry.register(
			"hcm.performance.request_reviews",
			"Request performance reviews for employee",
		)
		def _bpm_request_reviews(
			record_ctx: dict,
			session: Any,
			employee_id: str = "",
			cycle_id: str = "",
			reviewer_ids: list | None = None,
			review_type: str = "MANAGER",
			**kw: Any,
		) -> dict:
			try:
				svc = PerformanceService()
				reviews = svc.request_reviews(
					employee_id, cycle_id, reviewer_ids or [], review_type, session
				)
				return {"status": "ok", "review_ids": [r.id for r in reviews]}
			except Exception as exc:
				log.warning("bpm performance.request_reviews failed: %s", exc)
				return {"status": "error", "message": str(exc)}

		@BPMActionRegistry.register(
			"hcm.performance.update_goal_progress",
			"Update OKR/goal progress",
		)
		def _bpm_update_progress(
			record_ctx: dict,
			session: Any,
			goal_id: str = "",
			progress_pct: float = 0.0,
			key_result_updates: list | None = None,
			**kw: Any,
		) -> dict:
			try:
				svc = PerformanceService()
				goal = svc.update_progress(
					goal_id, progress_pct, session,
					key_result_updates=key_result_updates,
				)
				return {"status": "ok", "goal_id": goal.id, "progress_pct": float(goal.progress_pct)}
			except Exception as exc:
				log.warning("bpm performance.update_goal_progress failed: %s", exc)
				return {"status": "error", "message": str(exc)}

	except ImportError:
		log.debug("PerformanceService: BPM plugin not available, skipping registration")


# ---------------------------------------------------------------------------
# PerformanceService
# ---------------------------------------------------------------------------

class PerformanceService:
	"""Stateless performance review domain service.

	Instantiate once per application (no instance state).
	All public methods accept a SQLAlchemy Session as an explicit argument.
	"""

	# ------------------------------------------------------------------
	# start_cycle
	# ------------------------------------------------------------------

	def start_cycle(
		self,
		name: str,
		cycle_type: str,
		start_date: Any,
		end_date: Any,
		tenant_id: str,
		session: Any,
		*,
		entity_id: str | None = None,
		review_form: dict | None = None,
	) -> Any:
		"""Create and activate a performance review cycle.

		Args:
			name: Human-readable cycle name, e.g. "2025 Annual Review".
			cycle_type: ANNUAL | QUARTERLY | CONTINUOUS.
			start_date: date — cycle opens.
			end_date: date — cycle closes.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			Persisted PerformanceCycle with status=ACTIVE.
		"""
		from pgappforge.plugins.erp.hcm.performance.models import PerformanceCycle
		from pgappforge.plugins.erp.hcm.performance.events import PerformanceCycleStartedEvent

		default_form = {
			"competencies": [
				{"name": "Execution", "description": "Delivers on commitments", "max_rating": 5},
				{"name": "Collaboration", "description": "Works effectively with others", "max_rating": 5},
				{"name": "Innovation", "description": "Generates and implements new ideas", "max_rating": 5},
				{"name": "Leadership", "description": "Guides and develops others", "max_rating": 5},
				{"name": "Communication", "description": "Communicates clearly and effectively", "max_rating": 5},
			],
			"weights": {"self": 20, "manager": 60, "peer": 20},
		}

		cycle = PerformanceCycle(
			tenant_id=tenant_id,
			name=name,
			cycle_type=cycle_type,
			start_date=start_date,
			end_date=end_date,
			status="ACTIVE",
			review_form=review_form or default_form,
			entity_id=entity_id,
		)
		session.add(cycle)
		session.flush()

		_emit(
			PerformanceCycleStartedEvent(
				aggregate_id=cycle.id,
				aggregate_type="PerformanceCycle",
				tenant_id=tenant_id,
				cycle_id=cycle.id,
				cycle_type=cycle_type,
			),
			session,
		)
		log.info(
			"PerformanceService.start_cycle: cycle=%s name=%r type=%s tenant=%s",
			cycle.id, name, cycle_type, tenant_id,
		)
		return cycle

	# ------------------------------------------------------------------
	# request_reviews
	# ------------------------------------------------------------------

	def request_reviews(
		self,
		employee_id: str,
		cycle_id: str,
		reviewer_ids: list[str],
		review_type: str,
		session: Any,
	) -> list[Any]:
		"""Create PENDING review forms for each reviewer.

		Args:
			employee_id: The employee being reviewed.
			cycle_id: UUID of the PerformanceCycle.
			reviewer_ids: List of reviewer employee IDs.
			review_type: SELF | MANAGER | PEER | 360_UPWARD.
			session: SQLAlchemy session.

		Returns:
			List of persisted PerformanceReview objects.
		"""
		from pgappforge.plugins.erp.hcm.performance.models import PerformanceCycle, PerformanceReview

		cycle: Any = session.get(PerformanceCycle, cycle_id)
		if cycle is None:
			raise CycleNotFoundError(f"PerformanceCycle {cycle_id!r} not found")
		if cycle.status not in ("ACTIVE", "CALIBRATING"):
			raise PerformanceStateError(
				f"PerformanceCycle {cycle_id!r} is {cycle.status!r}; must be ACTIVE to request reviews"
			)

		reviews: list[Any] = []
		for reviewer_id in reviewer_ids:
			review = PerformanceReview(
				tenant_id=cycle.tenant_id,
				cycle_id=cycle_id,
				employee_id=employee_id,
				reviewer_id=reviewer_id,
				review_type=review_type,
				status="PENDING",
			)
			session.add(review)
			reviews.append(review)

		session.flush()
		log.info(
			"PerformanceService.request_reviews: cycle=%s employee=%s type=%s count=%d",
			cycle_id, employee_id, review_type, len(reviews),
		)
		return reviews

	# ------------------------------------------------------------------
	# submit_review
	# ------------------------------------------------------------------

	def submit_review(
		self,
		review_id: str,
		overall_rating: float,
		competency_scores: dict[str, float],
		session: Any,
		*,
		strengths: str | None = None,
		dev_areas: str | None = None,
		development_notes: str | None = None,
	) -> Any:
		"""Submit a performance review form.

		Args:
			review_id: UUID of the PerformanceReview.
			overall_rating: 1.00–5.00.
			competency_scores: {competency_name: score}.
			session: SQLAlchemy session.

		Returns:
			Updated PerformanceReview with status=SUBMITTED.
		"""
		from pgappforge.plugins.erp.hcm.performance.models import PerformanceReview
		from pgappforge.plugins.erp.hcm.performance.events import ReviewSubmittedEvent

		review: Any = session.get(PerformanceReview, review_id)
		if review is None:
			raise ReviewNotFoundError(f"PerformanceReview {review_id!r} not found")
		if review.status == "SUBMITTED":
			raise PerformanceStateError(f"PerformanceReview {review_id!r} already SUBMITTED")

		rating_d = _decimal(overall_rating)
		assert Decimal("1.00") <= rating_d <= Decimal("5.00"), (
			f"overall_rating must be 1.00–5.00, got {overall_rating}"
		)

		now = _now()
		review.status = "SUBMITTED"
		review.overall_rating = rating_d
		review.competency_scores = competency_scores
		review.strengths = strengths
		review.development_areas = dev_areas
		review.development_notes = development_notes
		review.submitted_at = now
		review.updated_at = now
		session.flush()

		_emit(
			ReviewSubmittedEvent(
				aggregate_id=review.id,
				aggregate_type="PerformanceReview",
				tenant_id=review.tenant_id,
				review_id=review.id,
				employee_id=review.employee_id,
				reviewer_id=review.reviewer_id,
				review_type=review.review_type,
				rating=float(rating_d),
			),
			session,
		)
		log.info(
			"PerformanceService.submit_review: review=%s employee=%s rating=%s",
			review_id, review.employee_id, rating_d,
		)
		return review

	# ------------------------------------------------------------------
	# calibrate
	# ------------------------------------------------------------------

	def calibrate(
		self,
		cycle_id: str,
		entity_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Compute calibration stats for all manager reviews in an entity.

		Loads all SUBMITTED manager reviews for entity employees in this cycle.
		Cross-references with talent 9-box if available.

		Returns:
		  [
		    {
		      employee_id, manager_rating, suggested_9box_position,
		      peers_above, peers_below, percentile
		    }
		  ]
		  Sorted descending by manager_rating.
		"""
		from pgappforge.plugins.erp.hcm.performance.models import PerformanceCycle, PerformanceReview

		cycle: Any = session.get(PerformanceCycle, cycle_id)
		if cycle is None:
			raise CycleNotFoundError(f"PerformanceCycle {cycle_id!r} not found")

		rows = session.execute(
			sa.select(
				PerformanceReview.employee_id,
				PerformanceReview.overall_rating,
			)
			.where(sa.and_(
				PerformanceReview.cycle_id == cycle_id,
				PerformanceReview.review_type == "MANAGER",
				PerformanceReview.status == "SUBMITTED",
				PerformanceReview.overall_rating.isnot(None),
			))
		).all()

		if not rows:
			return []

		ratings = [float(r.overall_rating) for r in rows]
		avg_rating = statistics.mean(ratings)
		std_rating = statistics.stdev(ratings) if len(ratings) > 1 else 0.0

		# Try talent 9-box integration (best-effort)
		ninebox_map: dict[str, str] = {}
		try:
			from pgappforge.plugins.erp.hcm.talent.services import TalentService
			svc = TalentService()
			for r in rows:
				box = svc.get_ninebox_position(r.employee_id, cycle_id, session)
				if box:
					ninebox_map[r.employee_id] = box
		except Exception:
			pass

		results: list[dict[str, Any]] = []
		for idx, row in enumerate(sorted(rows, key=lambda x: float(x.overall_rating), reverse=True)):
			emp_rating = float(row.overall_rating)
			z = (emp_rating - avg_rating) / std_rating if std_rating > 0 else 0.0

			# Suggest 9-box performance axis: High/Medium/Low
			if z >= 1.0:
				suggested = "HIGH_PERFORMANCE"
			elif z >= -1.0:
				suggested = "MEDIUM_PERFORMANCE"
			else:
				suggested = "LOW_PERFORMANCE"

			peers_above = sum(1 for r in ratings if r > emp_rating)
			peers_below = sum(1 for r in ratings if r < emp_rating)
			percentile = round((peers_below / len(ratings)) * 100, 1)

			results.append({
				"employee_id": row.employee_id,
				"manager_rating": emp_rating,
				"suggested_9box_position": ninebox_map.get(row.employee_id, suggested),
				"peers_above": peers_above,
				"peers_below": peers_below,
				"percentile": percentile,
				"avg_rating": round(avg_rating, 2),
				"std_dev": round(std_rating, 2),
			})

		log.info(
			"PerformanceService.calibrate: cycle=%s entity=%s employees=%d",
			cycle_id, entity_id, len(results),
		)
		return results

	# ------------------------------------------------------------------
	# create_goal
	# ------------------------------------------------------------------

	def create_goal(
		self,
		employee_id: str,
		title: str,
		goal_type: str,
		period: str,
		tenant_id: str,
		session: Any,
		*,
		key_results: list[dict] | None = None,
		weight_pct: float = 0,
		cycle_id: str | None = None,
		description: str | None = None,
	) -> Any:
		"""Create a new goal / OKR for an employee.

		Args:
			employee_id: Employee owner.
			title: Goal title.
			goal_type: OKR | SMART | STRETCH | OPERATIONAL.
			period: e.g. "2025-Q1" or "2025".
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			Persisted Goal with status=ACTIVE.
		"""
		from pgappforge.plugins.erp.hcm.performance.models import Goal
		from pgappforge.plugins.erp.hcm.performance.events import GoalCreatedEvent

		goal = Goal(
			tenant_id=tenant_id,
			employee_id=employee_id,
			title=title,
			description=description,
			goal_type=goal_type,
			key_results=key_results or [],
			weight_pct=_decimal(weight_pct),
			progress_pct=_decimal(0),
			period=period,
			status="ACTIVE",
			cycle_id=cycle_id,
		)
		session.add(goal)
		session.flush()

		_emit(
			GoalCreatedEvent(
				aggregate_id=goal.id,
				aggregate_type="Goal",
				tenant_id=tenant_id,
				goal_id=goal.id,
				employee_id=employee_id,
				type=goal_type,
				period=period,
			),
			session,
		)
		log.info(
			"PerformanceService.create_goal: goal=%s employee=%s type=%s period=%s",
			goal.id, employee_id, goal_type, period,
		)
		return goal

	# ------------------------------------------------------------------
	# update_progress
	# ------------------------------------------------------------------

	def update_progress(
		self,
		goal_id: str,
		progress_pct: float,
		session: Any,
		*,
		key_result_updates: list[dict] | None = None,
	) -> Any:
		"""Update progress on a goal (and optionally individual KRs).

		Args:
			goal_id: UUID of the Goal.
			progress_pct: New overall progress percentage (0–100).
			session: SQLAlchemy session.
			key_result_updates: Optional list of KR updates [{index, current}].

		Returns:
			Updated Goal.
		"""
		from pgappforge.plugins.erp.hcm.performance.models import Goal
		from pgappforge.plugins.erp.hcm.performance.events import GoalProgressUpdatedEvent

		goal: Any = session.get(Goal, goal_id)
		if goal is None:
			raise GoalNotFoundError(f"Goal {goal_id!r} not found")

		pct = _decimal(progress_pct)
		assert Decimal("0") <= pct <= Decimal("100"), (
			f"progress_pct must be 0–100, got {progress_pct}"
		)

		goal.progress_pct = pct
		goal.updated_at = _now()

		if key_result_updates:
			krs = list(goal.key_results or [])
			for upd in key_result_updates:
				idx = upd.get("index")
				if idx is not None and 0 <= idx < len(krs):
					krs[idx] = {**krs[idx], "current": upd.get("current", krs[idx].get("current"))}
			goal.key_results = krs

		# Auto-complete goal if fully done
		if pct >= Decimal("100") and goal.status == "ACTIVE":
			goal.status = "COMPLETED"

		session.flush()

		_emit(
			GoalProgressUpdatedEvent(
				aggregate_id=goal.id,
				aggregate_type="Goal",
				tenant_id=goal.tenant_id,
				goal_id=goal.id,
				employee_id=goal.employee_id,
				progress_pct=float(pct),
			),
			session,
		)
		log.info(
			"PerformanceService.update_progress: goal=%s employee=%s progress=%s%%",
			goal_id, goal.employee_id, pct,
		)
		return goal

	# ------------------------------------------------------------------
	# give_feedback
	# ------------------------------------------------------------------

	def give_feedback(
		self,
		from_id: str,
		to_id: str,
		text: str,
		tenant_id: str,
		session: Any,
		*,
		visibility: str = "PRIVATE",
		tags: list[str] | None = None,
		context: str | None = None,
	) -> Any:
		"""Submit continuous feedback from one employee to another.

		Args:
			from_id: Giver employee ID.
			to_id: Recipient employee ID.
			text: Feedback text.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			Persisted ContinuousFeedback.
		"""
		from pgappforge.plugins.erp.hcm.performance.models import ContinuousFeedback
		from pgappforge.plugins.erp.hcm.performance.events import FeedbackGivenEvent

		fb = ContinuousFeedback(
			tenant_id=tenant_id,
			from_employee_id=from_id,
			to_employee_id=to_id,
			feedback_text=text,
			visibility=visibility,
			tags=tags or [],
			context=context,
		)
		session.add(fb)
		session.flush()

		_emit(
			FeedbackGivenEvent(
				aggregate_id=fb.id,
				aggregate_type="ContinuousFeedback",
				tenant_id=tenant_id,
				from_id=from_id,
				to_id=to_id,
				tags=tags or [],
			),
			session,
		)
		log.info(
			"PerformanceService.give_feedback: from=%s to=%s visibility=%s",
			from_id, to_id, visibility,
		)
		return fb

	# ------------------------------------------------------------------
	# get_employee_performance
	# ------------------------------------------------------------------

	def get_employee_performance(
		self,
		employee_id: str,
		cycle_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Aggregate performance data for an employee in a cycle.

		Returns:
		  {
		    employee_id, cycle_id,
		    reviews: [{id, review_type, status, overall_rating, reviewer_id}],
		    goals: [{id, title, goal_type, period, progress_pct, status}],
		    feedback: [{id, from_id, text, tags, visibility}],
		    avg_manager_rating: float | None,
		    avg_peer_rating: float | None,
		    self_rating: float | None,
		    goal_completion_pct: float,
		  }
		"""
		from pgappforge.plugins.erp.hcm.performance.models import (
			PerformanceReview,
			Goal,
			ContinuousFeedback,
		)

		reviews: list[Any] = session.execute(
			sa.select(PerformanceReview)
			.where(sa.and_(
				PerformanceReview.cycle_id == cycle_id,
				PerformanceReview.employee_id == employee_id,
			))
		).scalars().all()

		goals: list[Any] = session.execute(
			sa.select(Goal)
			.where(sa.and_(
				Goal.employee_id == employee_id,
				Goal.cycle_id == cycle_id,
			))
		).scalars().all()

		feedback: list[Any] = session.execute(
			sa.select(ContinuousFeedback)
			.where(ContinuousFeedback.to_employee_id == employee_id)
			.order_by(ContinuousFeedback.created_at.desc())
			.limit(50)
		).scalars().all()

		# Rating aggregates
		manager_ratings = [
			float(r.overall_rating)
			for r in reviews
			if r.review_type == "MANAGER" and r.overall_rating is not None
		]
		peer_ratings = [
			float(r.overall_rating)
			for r in reviews
			if r.review_type == "PEER" and r.overall_rating is not None
		]
		self_ratings = [
			float(r.overall_rating)
			for r in reviews
			if r.review_type == "SELF" and r.overall_rating is not None
		]

		# Goal completion
		active_goals = [g for g in goals if g.status != "CANCELLED"]
		goal_completion = (
			round(
				sum(float(g.progress_pct) for g in active_goals) / len(active_goals), 1
			)
			if active_goals else 0.0
		)

		return {
			"employee_id": employee_id,
			"cycle_id": cycle_id,
			"reviews": [
				{
					"id": r.id,
					"review_type": r.review_type,
					"status": r.status,
					"overall_rating": float(r.overall_rating) if r.overall_rating else None,
					"reviewer_id": r.reviewer_id,
					"submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
				}
				for r in reviews
			],
			"goals": [
				{
					"id": g.id,
					"title": g.title,
					"goal_type": g.goal_type,
					"period": g.period,
					"progress_pct": float(g.progress_pct),
					"status": g.status,
					"weight_pct": float(g.weight_pct),
				}
				for g in goals
			],
			"feedback": [
				{
					"id": f.id,
					"from_id": f.from_employee_id,
					"text": f.feedback_text,
					"tags": f.tags or [],
					"visibility": f.visibility,
					"context": f.context,
				}
				for f in feedback
			],
			"avg_manager_rating": round(statistics.mean(manager_ratings), 2) if manager_ratings else None,
			"avg_peer_rating": round(statistics.mean(peer_ratings), 2) if peer_ratings else None,
			"self_rating": self_ratings[0] if self_ratings else None,
			"goal_completion_pct": goal_completion,
		}


# ---------------------------------------------------------------------------
# Best-effort BPM registration at import time
# ---------------------------------------------------------------------------

try:
	_register_bpm()
except Exception as _exc:
	log.debug("PerformanceService: BPM registration failed: %s", _exc)


__all__ = [
	"PerformanceService",
	"PerformanceServiceError",
	"CycleNotFoundError",
	"ReviewNotFoundError",
	"GoalNotFoundError",
	"PerformanceStateError",
]
