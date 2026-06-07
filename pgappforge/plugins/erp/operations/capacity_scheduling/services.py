"""
pgappforge/plugins/erp/operations/capacity_scheduling/services.py

CapacityScheduler — stateless finite capacity scheduling domain service.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Scheduling algorithm: backward finite-capacity scheduling.
  - Start from required_date, walk backward one working day at a time.
  - Schedule on the first date with sufficient remaining available hours.
  - Update CapacityLoad.loaded_hours and utilization_pct atomically.

BPM registrations:
  ops.capacity.schedule_order    — Schedule production order on work center
  ops.capacity.detect_bottleneck — Detect manufacturing bottlenecks

Public API:
  schedule_order(production_order_id, work_center_id, required_hours,
                 required_date, tenant_id, session) -> ProductionSchedule
  run_capacity_leveling(entity_id, from_date, to_date, tenant_id, session) -> dict
  get_load_report(from_date, to_date, tenant_id, session) -> list[dict]
  detect_bottleneck(from_date, to_date, tenant_id, session) -> list[dict]
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

# Maximum backward-scheduling horizon (working days to search before giving up)
_MAX_SCHEDULING_HORIZON_DAYS = 90


# ---------------------------------------------------------------------------
# BPM action registry
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry
	_bpm_available = True
except Exception:
	_bpm_available = False

	class _FakeBPMRegistry:
		@staticmethod
		def register(action_id: str, description: str):
			def decorator(fn):
				return fn
			return decorator

	BPMActionRegistry = _FakeBPMRegistry()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CapacitySchedulingError(Exception):
	"""Base domain error for capacity scheduling operations."""


class WorkCenterNotFoundError(CapacitySchedulingError):
	pass


class ScheduleNotFoundError(CapacitySchedulingError):
	pass


class InsufficientCapacityError(CapacitySchedulingError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("CapacityScheduler._emit: non-fatal event emission failure: %s", exc)


# ---------------------------------------------------------------------------
# CapacityScheduler
# ---------------------------------------------------------------------------

class CapacityScheduler:
	"""Stateless finite capacity scheduling domain service.

	Instantiate once per application (no instance state).
	All public methods accept an explicit SQLAlchemy Session.
	"""

	# ------------------------------------------------------------------
	# _get_available_hours
	# ------------------------------------------------------------------

	def _get_available_hours(self, work_center: Any, target_date: date) -> Decimal:
		"""Compute net available hours for work_center on target_date.

		Returns Decimal("0") if target_date is not a working day per calendar.
		Net hours = capacity_hours_per_day × efficiency_pct − setup_time_hours.
		"""
		calendar: list[int] = work_center.calendar or [0, 1, 2, 3, 4]
		if target_date.weekday() not in calendar:
			return Decimal("0")

		capacity = _d(work_center.capacity_hours_per_day)
		efficiency = _d(work_center.efficiency_pct)
		setup = _d(work_center.setup_time_hours)

		net = (capacity * efficiency - setup).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
		return max(net, Decimal("0"))

	# ------------------------------------------------------------------
	# _get_or_create_load
	# ------------------------------------------------------------------

	def _get_or_create_load(
		self,
		work_center: Any,
		target_date: date,
		available_hours: Decimal,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Get or create a CapacityLoad row for (work_center, target_date)."""
		from pgappforge.plugins.erp.operations.capacity_scheduling.models import CapacityLoad

		load = session.execute(
			sa.select(CapacityLoad).where(
				CapacityLoad.work_center_id == work_center.id,
				CapacityLoad.load_date == target_date,
			)
		).scalar_one_or_none()

		if load is None:
			load = CapacityLoad(
				tenant_id=tenant_id,
				work_center_id=work_center.id,
				load_date=target_date,
				loaded_hours=Decimal("0"),
				available_hours=available_hours,
				utilization_pct=Decimal("0"),
			)
			session.add(load)
			session.flush()

		return load

	# ------------------------------------------------------------------
	# schedule_order
	# ------------------------------------------------------------------

	def schedule_order(
		self,
		production_order_id: str,
		work_center_id: str,
		required_hours: Any,
		required_date: date,
		tenant_id: str,
		session: Any,
		*,
		priority: int = 5,
	) -> Any:
		"""Schedule a production order using backward finite-capacity scheduling.

		Walks backward from required_date to find the latest date with sufficient
		remaining capacity, then books the order and updates CapacityLoad.

		Args:
			production_order_id: Soft FK to production order.
			work_center_id: UUID of the WorkCenter to schedule on.
			required_hours: Hours needed to complete this order (Decimal-coercible).
			required_date: Latest acceptable completion date.
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session (caller commits).
			priority: Scheduling priority 1–10 (1=highest).

		Returns:
			The created ProductionSchedule.

		Raises:
			WorkCenterNotFoundError: work_center_id not found.
			InsufficientCapacityError: no slot found within horizon.
		"""
		from pgappforge.plugins.erp.operations.capacity_scheduling.models import (
			WorkCenter, ProductionSchedule,
		)
		from pgappforge.plugins.erp.operations.capacity_scheduling.events import (
			ProductionScheduledEvent,
			CapacityOverloadDetectedEvent,
		)

		wc = session.execute(
			sa.select(WorkCenter).where(WorkCenter.id == work_center_id)
		).scalar_one_or_none()

		if wc is None:
			raise WorkCenterNotFoundError(f"WorkCenter {work_center_id!r} not found")

		required_hours_d = _d(required_hours)
		assert required_hours_d > 0, "required_hours must be positive"

		# Backward scheduling: start at required_date, search backward
		candidate_date = required_date
		for _ in range(_MAX_SCHEDULING_HORIZON_DAYS):
			available = self._get_available_hours(wc, candidate_date)
			if available <= 0:
				candidate_date -= timedelta(days=1)
				continue

			load = self._get_or_create_load(wc, candidate_date, available, tenant_id, session)

			remaining = _d(load.available_hours) - _d(load.loaded_hours)
			if remaining >= required_hours_d:
				# Found a suitable slot — book it
				new_loaded = _d(load.loaded_hours) + required_hours_d
				util_pct = (new_loaded / _d(load.available_hours) * Decimal("100")).quantize(
					Decimal("0.0001"), rounding=ROUND_HALF_UP
				)
				load.loaded_hours = new_loaded
				load.utilization_pct = util_pct

				# Build schedule datetimes: start = 08:00 UTC on candidate_date
				start_dt = datetime(
					candidate_date.year, candidate_date.month, candidate_date.day,
					8, 0, 0, tzinfo=timezone.utc,
				)
				duration_secs = int(
					(required_hours_d * Decimal("3600")).to_integral_value(rounding=ROUND_HALF_UP)
				)
				end_dt = datetime.fromtimestamp(
					start_dt.timestamp() + duration_secs, tz=timezone.utc
				)

				schedule = ProductionSchedule(
					tenant_id=tenant_id,
					production_order_id=production_order_id,
					work_center_id=work_center_id,
					start_datetime=start_dt,
					end_datetime=end_dt,
					required_hours=required_hours_d,
					status="PLANNED",
					priority=priority,
				)
				session.add(schedule)
				session.flush()

				log.info(
					"CapacityScheduler.schedule_order: order=%s wc=%s date=%s hours=%s util=%s%%",
					production_order_id, work_center_id, candidate_date,
					required_hours_d, util_pct,
				)

				_emit(
					ProductionScheduledEvent(
						aggregate_id=schedule.id,
						aggregate_type="ProductionSchedule",
						tenant_id=tenant_id,
						order_id=production_order_id,
						work_center_id=work_center_id,
						start_datetime=start_dt.isoformat(),
						end_datetime=end_dt.isoformat(),
					),
					session,
				)

				# Emit overload event if utilization > 100%
				if util_pct > Decimal("100"):
					_emit(
						CapacityOverloadDetectedEvent(
							aggregate_id=wc.id,
							aggregate_type="WorkCenter",
							tenant_id=tenant_id,
							work_center_id=wc.id,
							date=candidate_date.isoformat(),
							utilization_pct=str(util_pct),
						),
						session,
					)

				return schedule

			candidate_date -= timedelta(days=1)

		raise InsufficientCapacityError(
			f"No capacity slot found for order {production_order_id!r} on work center "
			f"{work_center_id!r} within {_MAX_SCHEDULING_HORIZON_DAYS} working days of "
			f"{required_date}"
		)

	# ------------------------------------------------------------------
	# run_capacity_leveling
	# ------------------------------------------------------------------

	def run_capacity_leveling(
		self,
		entity_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Level capacity for all PLANNED schedules in the date range.

		Re-schedules each order using earliest-due-date-first rule, which may
		shift orders to earlier dates to balance load across working days.

		Args:
			entity_id: Multi-entity scoping (matched to work center entity_id).
			from_date: Start of leveling window (inclusive).
			to_date: End of leveling window (inclusive).
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session (caller commits).

		Returns:
			Dict: {orders_processed, orders_shifted, max_utilization_pct}.
		"""
		from pgappforge.plugins.erp.operations.capacity_scheduling.models import (
			WorkCenter, ProductionSchedule, CapacityLoad,
		)
		from pgappforge.plugins.erp.operations.capacity_scheduling.events import ScheduleLeveledEvent

		# Load PLANNED schedules for work centers in this entity
		wc_ids_query = sa.select(WorkCenter.id).where(
			WorkCenter.tenant_id == tenant_id,
			WorkCenter.entity_id == entity_id,
		)
		wc_ids = [r[0] for r in session.execute(wc_ids_query).all()]

		if not wc_ids:
			log.info(
				"CapacityScheduler.run_capacity_leveling: no work centers for entity=%s", entity_id
			)
			return {"orders_processed": 0, "orders_shifted": 0, "max_utilization_pct": "0"}

		# Load all PLANNED schedules in range, sorted by (end_datetime ASC, priority ASC)
		schedules = session.execute(
			sa.select(ProductionSchedule)
			.where(
				ProductionSchedule.tenant_id == tenant_id,
				ProductionSchedule.work_center_id.in_(wc_ids),
				ProductionSchedule.status == "PLANNED",
				sa.cast(ProductionSchedule.start_datetime, sa.Date) >= from_date,
				sa.cast(ProductionSchedule.start_datetime, sa.Date) <= to_date,
			)
			.order_by(
				ProductionSchedule.end_datetime.asc(),
				ProductionSchedule.priority.asc(),
			)
		).scalars().all()

		orders_processed = len(schedules)
		orders_shifted = 0

		# Reset existing capacity loads in range for these work centers
		session.execute(
			sa.delete(CapacityLoad).where(
				CapacityLoad.tenant_id == tenant_id,
				CapacityLoad.work_center_id.in_(wc_ids),
				CapacityLoad.load_date >= from_date,
				CapacityLoad.load_date <= to_date,
			)
		)
		session.flush()

		# Delete existing schedules (we'll re-create them)
		original_dates: dict[str, date] = {
			s.id: s.start_datetime.date() for s in schedules
		}
		for sched in schedules:
			session.delete(sched)
		session.flush()

		max_util = Decimal("0")

		for sched in schedules:
			required_date = sched.end_datetime.date()
			if required_date > to_date:
				required_date = to_date

			new_sched = self.schedule_order(
				production_order_id=sched.production_order_id,
				work_center_id=sched.work_center_id,
				required_hours=sched.required_hours,
				required_date=required_date,
				tenant_id=tenant_id,
				session=session,
				priority=sched.priority,
			)

			new_date = new_sched.start_datetime.date()
			if new_date != original_dates.get(sched.id):
				orders_shifted += 1

			# Track max utilization
			load_row = session.execute(
				sa.select(CapacityLoad).where(
					CapacityLoad.work_center_id == new_sched.work_center_id,
					CapacityLoad.load_date == new_date,
				)
			).scalar_one_or_none()
			if load_row:
				util = _d(load_row.utilization_pct)
				if util > max_util:
					max_util = util

		log.info(
			"CapacityScheduler.run_capacity_leveling: entity=%s processed=%d shifted=%d max_util=%s%%",
			entity_id, orders_processed, orders_shifted, max_util,
		)

		_emit(
			ScheduleLeveledEvent(
				aggregate_id=entity_id,
				aggregate_type="Entity",
				tenant_id=tenant_id,
				entity_id=entity_id,
				from_date=from_date.isoformat(),
				to_date=to_date.isoformat(),
				orders_shifted=orders_shifted,
			),
			session,
		)

		return {
			"orders_processed": orders_processed,
			"orders_shifted": orders_shifted,
			"max_utilization_pct": str(max_util),
		}

	# ------------------------------------------------------------------
	# get_load_report
	# ------------------------------------------------------------------

	def get_load_report(
		self,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Return capacity load rows with work center details and overload/underload flags.

		Args:
			from_date: Start of reporting window (inclusive).
			to_date: End of reporting window (inclusive).
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session.

		Returns:
			List of dicts sorted by (work_center_code, load_date):
			  [{work_center_id, code, name, load_date, loaded_hours, available_hours,
			    utilization_pct, is_overloaded, is_underloaded}]
		"""
		from pgappforge.plugins.erp.operations.capacity_scheduling.models import (
			WorkCenter, CapacityLoad,
		)

		rows = session.execute(
			sa.select(CapacityLoad, WorkCenter)
			.join(WorkCenter, CapacityLoad.work_center_id == WorkCenter.id)
			.where(
				CapacityLoad.tenant_id == tenant_id,
				CapacityLoad.load_date >= from_date,
				CapacityLoad.load_date <= to_date,
			)
			.order_by(WorkCenter.code.asc(), CapacityLoad.load_date.asc())
		).all()

		result = []
		for load, wc in rows:
			util = _d(load.utilization_pct)
			result.append({
				"work_center_id": wc.id,
				"code": wc.code,
				"name": wc.name,
				"load_date": load.load_date.isoformat(),
				"loaded_hours": str(load.loaded_hours),
				"available_hours": str(load.available_hours),
				"utilization_pct": str(util),
				"is_overloaded": util > Decimal("100"),
				"is_underloaded": util < Decimal("50"),
			})

		return result

	# ------------------------------------------------------------------
	# detect_bottleneck
	# ------------------------------------------------------------------

	def detect_bottleneck(
		self,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Identify bottleneck work centers by average utilization over the period.

		Top 3 work centers by avg utilization are returned.
		Emits BottleneckDetectedEvent for each with avg util > 80%.

		Args:
			from_date: Start of analysis window (inclusive).
			to_date: End of analysis window (inclusive).
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session.

		Returns:
			List of dicts (up to 3) sorted by avg_utilization_pct desc:
			  [{work_center_id, code, name, avg_utilization_pct, peak_date}]
		"""
		from pgappforge.plugins.erp.operations.capacity_scheduling.models import (
			WorkCenter, CapacityLoad,
		)
		from pgappforge.plugins.erp.operations.capacity_scheduling.events import BottleneckDetectedEvent

		# Aggregate avg utilization per work center
		avg_util_subq = (
			sa.select(
				CapacityLoad.work_center_id,
				sa.func.avg(CapacityLoad.utilization_pct).label("avg_util"),
				sa.func.max(CapacityLoad.utilization_pct).label("peak_util"),
				sa.func.max(CapacityLoad.load_date).label("peak_date"),  # approx peak date
			)
			.where(
				CapacityLoad.tenant_id == tenant_id,
				CapacityLoad.load_date >= from_date,
				CapacityLoad.load_date <= to_date,
				CapacityLoad.available_hours > 0,
			)
			.group_by(CapacityLoad.work_center_id)
			.order_by(sa.text("avg_util DESC"))
			.limit(3)
			.subquery()
		)

		rows = session.execute(
			sa.select(avg_util_subq, WorkCenter)
			.join(WorkCenter, avg_util_subq.c.work_center_id == WorkCenter.id)
		).all()

		period_str = f"{from_date.isoformat()}/{to_date.isoformat()}"
		result = []

		for row in rows:
			avg_util = _d(row.avg_util).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
			peak_date = row.peak_date

			result.append({
				"work_center_id": row.work_center_id,
				"code": row.WorkCenter.code,
				"name": row.WorkCenter.name,
				"avg_utilization_pct": str(avg_util),
				"peak_date": peak_date.isoformat() if peak_date else None,
			})

			if avg_util > Decimal("80"):
				_emit(
					BottleneckDetectedEvent(
						aggregate_id=row.work_center_id,
						aggregate_type="WorkCenter",
						tenant_id=tenant_id,
						work_center_id=row.work_center_id,
						avg_utilization_pct=str(avg_util),
						period=period_str,
					),
					session,
				)

		log.info(
			"CapacityScheduler.detect_bottleneck: found %d bottlenecks in %s",
			len(result), period_str,
		)

		return result


__all__ = [
	"CapacityScheduler",
	"CapacitySchedulingError",
	"WorkCenterNotFoundError",
	"ScheduleNotFoundError",
	"InsufficientCapacityError",
]

# BPM action wrappers — use module-level functions so BPMActionRegistry.call() has no self
@BPMActionRegistry.register("ops.capacity.schedule_order", "Schedule production order on work center")
def _bpm_schedule_order(record_ctx, session, production_order_id, work_center_id, required_hours,
                         required_date_str, tenant_id, **kw):
	from datetime import date as _date
	req_date = _date.fromisoformat(str(required_date_str))
	return CapacityScheduler().schedule_order(
		production_order_id, work_center_id, required_hours, req_date, tenant_id, session)

@BPMActionRegistry.register("ops.capacity.detect_bottleneck", "Detect manufacturing bottlenecks")
def _bpm_detect_bottleneck(record_ctx, session, from_date_str, to_date_str, tenant_id, **kw):
	from datetime import date as _date
	return CapacityScheduler().detect_bottleneck(
		_date.fromisoformat(str(from_date_str)), _date.fromisoformat(str(to_date_str)), tenant_id, session)
