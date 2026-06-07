"""
pgappforge/plugins/erp/hcm/position_management/services.py

PositionManagementService — stateless position / establishment register service.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Public methods:
  create_position(...)           -> Position
  fill_position(...)             -> Position
  vacate_position(...)           -> Position
  check_headcount_variance(...)  -> dict
  get_org_chart_positions(...)   -> list[dict]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PositionManagementError(Exception):
	"""Base domain error for position management operations."""


class PositionNotFoundError(PositionManagementError):
	pass


class PositionStateError(PositionManagementError):
	"""Invalid position state transition."""


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
		log.debug("PositionManagementService._emit: could not emit %s: %s", type(event).__name__, exc)


# ---------------------------------------------------------------------------
# BPM registration
# ---------------------------------------------------------------------------

def _register_bpm() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry

		@BPMActionRegistry.register(
			"hcm.positions.fill",
			"Fill a position with an employee",
		)
		def _bpm_fill_position(
			record_ctx: dict,
			session: Any,
			position_id: str = "",
			employee_id: str = "",
			**kw: Any,
		) -> dict:
			try:
				svc = PositionManagementService()
				pos = svc.fill_position(position_id, employee_id, session)
				return {"status": "ok", "position_id": pos.id, "position_status": pos.status}
			except Exception as exc:
				log.warning("bpm positions.fill failed: %s", exc)
				return {"status": "error", "message": str(exc)}

		@BPMActionRegistry.register(
			"hcm.positions.vacate",
			"Vacate a position",
		)
		def _bpm_vacate_position(
			record_ctx: dict,
			session: Any,
			position_id: str = "",
			trigger: str = "RESIGNATION",
			**kw: Any,
		) -> dict:
			try:
				svc = PositionManagementService()
				pos = svc.vacate_position(position_id, trigger, session)
				return {"status": "ok", "position_id": pos.id, "position_status": pos.status}
			except Exception as exc:
				log.warning("bpm positions.vacate failed: %s", exc)
				return {"status": "error", "message": str(exc)}

	except ImportError:
		log.debug("PositionManagementService: BPM plugin not available, skipping registration")


# ---------------------------------------------------------------------------
# PositionManagementService
# ---------------------------------------------------------------------------

class PositionManagementService:
	"""Stateless position management domain service.

	Instantiate once per application (no instance state).
	All public methods accept a SQLAlchemy Session as an explicit argument.
	"""

	# ------------------------------------------------------------------
	# create_position
	# ------------------------------------------------------------------

	def create_position(
		self,
		position_code: str,
		title: str,
		tenant_id: str,
		session: Any,
		*,
		department_id: str | None = None,
		entity_id: str | None = None,
		grade_level: str | None = None,
		budget_salary_cents: int | None = None,
		employment_type: str = "FULL_TIME",
		headcount_budget: float = 1.0,
	) -> Any:
		"""Create a new position slot in the establishment register.

		Args:
			position_code: Unique position code within the tenant.
			title: Position title.
			tenant_id: Tenant UUID.
			session: SQLAlchemy session.

		Returns:
			Persisted Position with status=VACANT.
		"""
		from pgappforge.plugins.erp.hcm.position_management.models import Position
		from pgappforge.plugins.erp.hcm.position_management.events import PositionCreatedEvent

		pos = Position(
			tenant_id=tenant_id,
			position_code=position_code,
			title=title,
			department_id=department_id,
			entity_id=entity_id,
			grade_level=grade_level,
			employment_type=employment_type,
			status="VACANT",
			budget_salary_cents=budget_salary_cents,
			headcount_budget=Decimal(str(headcount_budget)),
		)
		session.add(pos)
		session.flush()

		_emit(
			PositionCreatedEvent(
				aggregate_id=pos.id,
				aggregate_type="Position",
				tenant_id=tenant_id,
				position_id=pos.id,
				position_code=position_code,
				entity_id=entity_id or "",
			),
			session,
		)
		log.info(
			"PositionManagementService.create_position: pos=%s code=%r title=%r tenant=%s",
			pos.id, position_code, title, tenant_id,
		)
		return pos

	# ------------------------------------------------------------------
	# fill_position
	# ------------------------------------------------------------------

	def fill_position(
		self,
		position_id: str,
		employee_id: str,
		session: Any,
	) -> Any:
		"""Assign an employee to a vacant position.

		Raises:
			PositionNotFoundError: Position not found.
			PositionStateError: Position is not VACANT.

		Side effects:
		  - Sets incumbent_employee_id and status=FILLED.
		  - Emits PositionFilledEvent.
		  - Calls check_headcount_variance for the entity.

		Returns:
			Updated Position.
		"""
		from pgappforge.plugins.erp.hcm.position_management.models import Position
		from pgappforge.plugins.erp.hcm.position_management.events import PositionFilledEvent

		pos: Any = session.get(Position, position_id)
		if pos is None:
			raise PositionNotFoundError(f"Position {position_id!r} not found")
		if pos.status != "VACANT":
			raise PositionStateError(
				f"Position {position_id!r} is {pos.status!r}; only VACANT positions can be filled"
			)

		previous = pos.incumbent_employee_id or ""
		pos.incumbent_employee_id = employee_id
		pos.status = "FILLED"
		pos.updated_at = _now()
		session.flush()

		_emit(
			PositionFilledEvent(
				aggregate_id=pos.id,
				aggregate_type="Position",
				tenant_id=pos.tenant_id,
				position_id=pos.id,
				employee_id=employee_id,
				previous_incumbent=previous,
			),
			session,
		)

		# Variance check (best-effort)
		if pos.entity_id:
			try:
				self.check_headcount_variance(pos.entity_id, pos.tenant_id, session)
			except Exception as exc:
				log.debug("PositionManagementService.fill_position: variance check failed: %s", exc)

		log.info(
			"PositionManagementService.fill_position: pos=%s employee=%s",
			position_id, employee_id,
		)
		return pos

	# ------------------------------------------------------------------
	# vacate_position
	# ------------------------------------------------------------------

	def vacate_position(
		self,
		position_id: str,
		trigger: str,
		session: Any,
	) -> Any:
		"""Mark a position as vacant and optionally trigger a replacement requisition.

		Args:
			position_id: UUID of the Position.
			trigger: RESIGNATION | TERMINATION | TRANSFER.
			session: SQLAlchemy session.

		Returns:
			Updated Position with status=VACANT.
		"""
		from pgappforge.plugins.erp.hcm.position_management.models import Position
		from pgappforge.plugins.erp.hcm.position_management.events import PositionVacatedEvent

		pos: Any = session.get(Position, position_id)
		if pos is None:
			raise PositionNotFoundError(f"Position {position_id!r} not found")

		vacated_by = pos.incumbent_employee_id or ""
		pos.status = "VACANT"
		pos.incumbent_employee_id = None
		pos.updated_at = _now()
		session.flush()

		_emit(
			PositionVacatedEvent(
				aggregate_id=pos.id,
				aggregate_type="Position",
				tenant_id=pos.tenant_id,
				position_id=pos.id,
				vacated_by=vacated_by,
				trigger=trigger,
			),
			session,
		)

		# Auto-trigger replacement requisition (best-effort)
		try:
			from pgappforge.plugins.erp.hcm.recruiting.services import RecruitingService
			RecruitingService().post_requisition(
				title=pos.title,
				tenant_id=pos.tenant_id,
				session=session,
				department_id=pos.department_id,
				entity_id=pos.entity_id,
				grade_level=pos.grade_level,
				employment_type=pos.employment_type,
				salary_min_cents=pos.budget_salary_cents,
			)
			log.info(
				"PositionManagementService.vacate_position: auto-created requisition for pos=%s",
				position_id,
			)
		except Exception as exc:
			log.debug(
				"PositionManagementService.vacate_position: auto-requisition not created: %s", exc
			)

		log.info(
			"PositionManagementService.vacate_position: pos=%s trigger=%r vacated_by=%s",
			position_id, trigger, vacated_by,
		)
		return pos

	# ------------------------------------------------------------------
	# check_headcount_variance
	# ------------------------------------------------------------------

	def check_headcount_variance(
		self,
		entity_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Compare budgeted FTE against actual filled positions for an entity.

		Emits HeadcountVarianceAlertEvent when |variance| > 0.

		Returns:
		  {
		    entity_id,
		    budgeted: float,   # sum of headcount_budget for all entity positions
		    actual: int,       # count of FILLED positions
		    variance: float,   # actual - budgeted
		    variance_pct: float,
		  }
		"""
		from pgappforge.plugins.erp.hcm.position_management.models import Position
		from pgappforge.plugins.erp.hcm.position_management.events import HeadcountVarianceAlertEvent

		budgeted_row = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(Position.headcount_budget), 0))
			.where(sa.and_(
				Position.tenant_id == tenant_id,
				Position.entity_id == entity_id,
				Position.status.notin_(["PROPOSED"]),
			))
		).scalar_one()
		budgeted = float(budgeted_row)

		actual: int = session.execute(
			sa.select(sa.func.count())
			.select_from(Position)
			.where(sa.and_(
				Position.tenant_id == tenant_id,
				Position.entity_id == entity_id,
				Position.status == "FILLED",
			))
		).scalar_one()

		variance = actual - budgeted
		variance_pct = round(variance / budgeted * 100, 2) if budgeted != 0 else 0.0

		if abs(variance) > 0:
			_emit(
				HeadcountVarianceAlertEvent(
					aggregate_id=entity_id,
					aggregate_type="Entity",
					tenant_id=tenant_id,
					entity_id=entity_id,
					budgeted=budgeted,
					actual=actual,
					variance=variance,
				),
				session,
			)

		log.info(
			"PositionManagementService.check_headcount_variance: entity=%s budgeted=%s actual=%d variance=%s",
			entity_id, budgeted, actual, variance,
		)
		return {
			"entity_id": entity_id,
			"budgeted": budgeted,
			"actual": actual,
			"variance": variance,
			"variance_pct": variance_pct,
		}

	# ------------------------------------------------------------------
	# get_org_chart_positions
	# ------------------------------------------------------------------

	def get_org_chart_positions(
		self,
		entity_id: str,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Return all positions for an entity with fill status and incumbent info.

		Returns:
		  [
		    {
		      id, position_code, title, department_id, grade_level,
		      employment_type, status, headcount_budget,
		      incumbent_employee_id, budget_salary_cents,
		    }
		  ]
		  Ordered by position_code.
		"""
		from pgappforge.plugins.erp.hcm.position_management.models import Position

		positions: list[Any] = session.execute(
			sa.select(Position)
			.where(sa.and_(
				Position.tenant_id == tenant_id,
				Position.entity_id == entity_id,
			))
			.order_by(Position.position_code)
		).scalars().all()

		return [
			{
				"id": p.id,
				"position_code": p.position_code,
				"title": p.title,
				"department_id": p.department_id,
				"grade_level": p.grade_level,
				"employment_type": p.employment_type,
				"status": p.status,
				"headcount_budget": float(p.headcount_budget),
				"incumbent_employee_id": p.incumbent_employee_id,
				"budget_salary_cents": p.budget_salary_cents,
			}
			for p in positions
		]


# ---------------------------------------------------------------------------
# Best-effort BPM registration at import time
# ---------------------------------------------------------------------------

try:
	_register_bpm()
except Exception as _exc:
	log.debug("PositionManagementService: BPM registration failed: %s", _exc)


__all__ = [
	"PositionManagementService",
	"PositionManagementError",
	"PositionNotFoundError",
	"PositionStateError",
]
