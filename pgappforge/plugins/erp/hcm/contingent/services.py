from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.workflow.engine import BPMActionRegistry
from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event

log = logging.getLogger(__name__)

_UTC = timezone.utc


def _emit(event: Any, session: Any = None) -> None:
	"""Fire-and-forget event emission."""
	try:
		_emit_event(event, session)
	except Exception:  # noqa: BLE001
		log.debug("Event bus unavailable; event %s not published", type(event).__name__)


from .events import (
	ContingentSpendEvent,
	ContingentWorkerOnboardedEvent,
	SowCompletedEvent,
	SowCreatedEvent,
	TimesheetApprovedEvent,
)
from .models import (
	ContingentTimesheet,
	ContingentWorker,
	StaffingAgency,
	StatementOfWork,
)

__all__ = [
	"ContingentWorkforceError",
	"WorkerNotFoundError",
	"TimesheetNotFoundError",
	"SowNotFoundError",
	"ContingentWorkforceService",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ContingentWorkforceError(Exception):
	"""Base error for Contingent Workforce service layer."""


class WorkerNotFoundError(ContingentWorkforceError):
	"""Raised when a contingent worker cannot be located."""


class TimesheetNotFoundError(ContingentWorkforceError):
	"""Raised when a timesheet cannot be located."""


class SowNotFoundError(ContingentWorkforceError):
	"""Raised when a Statement of Work cannot be located."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ContingentWorkforceService:
	"""Domain service for Contingent Workforce management."""

	# ------------------------------------------------------------------
	# Worker onboarding
	# ------------------------------------------------------------------

	def onboard_worker(
		self,
		first_name: str,
		last_name: str,
		worker_type: str,
		rate_cents: int,
		rate_unit: str,
		tenant_id: str,
		session: Session,
		*,
		agency_id: str | None = None,
		start_date: date | None = None,
		end_date: date | None = None,
		entity_id: str | None = None,
		email: str | None = None,
	) -> ContingentWorker:
		"""Create a new contingent worker record and emit onboarded event."""
		assert worker_type in ("CONTRACTOR", "FREELANCER", "SOW", "TEMP", "INTERN"), (
			f"Invalid worker_type {worker_type!r}"
		)
		assert rate_unit in ("HOURLY", "DAILY", "WEEKLY", "FIXED"), (
			f"Invalid rate_unit {rate_unit!r}"
		)
		assert rate_cents >= 0, "rate_cents must be non-negative"

		worker = ContingentWorker(
			tenant_id=tenant_id,
			first_name=first_name,
			last_name=last_name,
			email=email,
			worker_type=worker_type,
			agency_id=agency_id,
			rate_cents=rate_cents,
			rate_unit=rate_unit,
			start_date=start_date,
			end_date=end_date,
			entity_id=entity_id,
			status="ACTIVE",
		)
		session.add(worker)
		session.flush()

		_emit(
			ContingentWorkerOnboardedEvent(
				worker_id=worker.id,
				worker_type=worker_type,
				agency_id=agency_id or "",
				tenant_id=tenant_id,
			)
		)
		log.info(
			"Contingent worker onboarded: %s %s (%s) id=%s",
			first_name, last_name, worker_type, worker.id,
		)
		return worker

	# ------------------------------------------------------------------
	# Statement of Work
	# ------------------------------------------------------------------

	def create_sow(
		self,
		worker_id: str,
		title: str,
		budget_cents: int,
		start_date: date,
		end_date: date,
		tenant_id: str,
		session: Session,
		*,
		description: str | None = None,
		deliverables: str | None = None,
	) -> StatementOfWork:
		"""Create a Statement of Work in ACTIVE status and emit SowCreatedEvent."""
		worker = session.execute(
			select(ContingentWorker).where(
				ContingentWorker.id == worker_id,
				ContingentWorker.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if worker is None:
			raise WorkerNotFoundError(f"Worker {worker_id!r} not found in tenant {tenant_id!r}")

		assert budget_cents > 0, "budget_cents must be positive"
		assert start_date <= end_date, "start_date must not be after end_date"

		sow = StatementOfWork(
			tenant_id=tenant_id,
			worker_id=worker_id,
			title=title,
			description=description,
			budget_cents=budget_cents,
			actual_spend_cents=0,
			start_date=start_date,
			end_date=end_date,
			status="ACTIVE",
			milestones=[],
			deliverables=deliverables,
		)
		session.add(sow)
		session.flush()

		_emit(
			SowCreatedEvent(
				sow_id=sow.id,
				worker_id=worker_id,
				budget_cents=budget_cents,
			)
		)
		log.info("SOW %s created for worker %s budget=%d", sow.id, worker_id, budget_cents)
		return sow

	# ------------------------------------------------------------------
	# Timesheet submission
	# ------------------------------------------------------------------

	def submit_timesheet(
		self,
		worker_id: str,
		period: str,
		hours: float | Decimal,
		tenant_id: str,
		session: Session,
		*,
		sow_id: str | None = None,
		notes: str | None = None,
	) -> ContingentTimesheet:
		"""
		Submit a timesheet for a contingent worker.

		amount_cents = ROUND_HALF_UP(hours × rate_cents)
		"""
		worker = session.execute(
			select(ContingentWorker).where(
				ContingentWorker.id == worker_id,
				ContingentWorker.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if worker is None:
			raise WorkerNotFoundError(f"Worker {worker_id!r} not found in tenant {tenant_id!r}")

		hours_dec = Decimal(str(hours))
		rate_dec = Decimal(str(worker.rate_cents))
		amount_cents = int(
			(hours_dec * rate_dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)

		timesheet = ContingentTimesheet(
			tenant_id=tenant_id,
			worker_id=worker_id,
			sow_id=sow_id,
			period=period,
			hours=hours_dec,
			rate_at_time_cents=worker.rate_cents,
			amount_cents=amount_cents,
			status="SUBMITTED",
			notes=notes,
		)
		session.add(timesheet)
		session.flush()

		log.info(
			"Timesheet submitted: worker=%s period=%s hours=%s amount=%d",
			worker_id, period, hours, amount_cents,
		)
		return timesheet

	# ------------------------------------------------------------------
	# Timesheet approval
	# ------------------------------------------------------------------

	def approve_timesheet(
		self,
		timesheet_id: str,
		approver_id: str,
		session: Session,
	) -> ContingentTimesheet:
		"""
		Transition timesheet SUBMITTED→APPROVED, update SOW actual_spend_cents,
		and emit TimesheetApprovedEvent.
		"""
		timesheet = session.execute(
			select(ContingentTimesheet).where(ContingentTimesheet.id == timesheet_id)
		).scalar_one_or_none()
		if timesheet is None:
			raise TimesheetNotFoundError(f"Timesheet {timesheet_id!r} not found")

		assert timesheet.status == "SUBMITTED", (
			f"approve_timesheet requires status=SUBMITTED; got {timesheet.status!r}"
		)

		now = datetime.now(tz=_UTC)
		timesheet.status = "APPROVED"
		timesheet.approved_by = approver_id
		timesheet.approved_at = now

		# Update SOW actual spend
		if timesheet.sow_id is not None:
			sow = session.execute(
				select(StatementOfWork).where(StatementOfWork.id == timesheet.sow_id)
			).scalar_one_or_none()
			if sow is not None:
				sow.actual_spend_cents = (sow.actual_spend_cents or 0) + timesheet.amount_cents

		session.flush()

		_emit(
			TimesheetApprovedEvent(
				timesheet_id=timesheet_id,
				worker_id=timesheet.worker_id,
				hours=str(timesheet.hours),
				period=timesheet.period,
			)
		)
		log.info(
			"Timesheet %s approved by %s: amount=%d",
			timesheet_id, approver_id, timesheet.amount_cents,
		)
		return timesheet

	# ------------------------------------------------------------------
	# SOW completion
	# ------------------------------------------------------------------

	def complete_sow(
		self,
		sow_id: str,
		session: Session,
	) -> StatementOfWork:
		"""Transition SOW ACTIVE→COMPLETED and emit SowCompletedEvent."""
		sow = session.execute(
			select(StatementOfWork).where(StatementOfWork.id == sow_id)
		).scalar_one_or_none()
		if sow is None:
			raise SowNotFoundError(f"SOW {sow_id!r} not found")

		assert sow.status == "ACTIVE", (
			f"complete_sow requires status=ACTIVE; got {sow.status!r}"
		)

		sow.status = "COMPLETED"
		session.flush()

		_emit(
			SowCompletedEvent(
				sow_id=sow_id,
				actual_spend_cents=sow.actual_spend_cents,
				status="COMPLETED",
			)
		)
		log.info("SOW %s completed; actual_spend=%d", sow_id, sow.actual_spend_cents)
		return sow

	# ------------------------------------------------------------------
	# Spend analytics
	# ------------------------------------------------------------------

	def compute_spend(
		self,
		tenant_id: str,
		period: str,
		session: Session,
	) -> dict[str, Any]:
		"""
		Aggregate contingent workforce spend for a YYYY-MM period.

		Returns {period, total_cents, by_type: {CONTRACTOR: n, ...}, worker_count}.
		Emits ContingentSpendEvent.
		"""
		timesheets = session.execute(
			select(ContingentTimesheet, ContingentWorker).join(
				ContingentWorker, ContingentTimesheet.worker_id == ContingentWorker.id
			).where(
				ContingentTimesheet.tenant_id == tenant_id,
				ContingentTimesheet.period == period,
				ContingentTimesheet.status.in_(["APPROVED", "PAID"]),
			)
		).all()

		total_cents = 0
		by_type: dict[str, int] = {}
		worker_ids: set[str] = set()

		for ts, worker in timesheets:
			total_cents += ts.amount_cents
			wtype = worker.worker_type
			by_type[wtype] = by_type.get(wtype, 0) + ts.amount_cents
			worker_ids.add(worker.id)

		result = {
			"period": period,
			"total_cents": total_cents,
			"by_type": by_type,
			"worker_count": len(worker_ids),
		}

		_emit(
			ContingentSpendEvent(
				tenant_id=tenant_id,
				period=period,
				total_cents=total_cents,
			)
		)
		log.info(
			"Contingent spend computed: tenant=%s period=%s total=%d",
			tenant_id, period, total_cents,
		)
		return result

	# ------------------------------------------------------------------
	# Total workforce composition
	# ------------------------------------------------------------------

	def get_total_workforce(
		self,
		entity_id: str,
		tenant_id: str,
		session: Session,
	) -> dict[str, Any]:
		"""
		Return permanent + contingent headcount for an entity.

		Attempts to query Personnel.Employee for permanent headcount;
		falls back to 0 if plugin unavailable.

		Returns {permanent_headcount, contingent_headcount, total_workforce, contingent_pct}.
		"""
		permanent_headcount = 0
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee
			permanent_headcount = len(
				session.execute(
					select(Employee).where(
						Employee.entity_id == entity_id,
						Employee.tenant_id == tenant_id,
						Employee.employment_status == "ACTIVE",
					)
				).scalars().all()
			)
		except (ImportError, Exception) as exc:
			log.debug("Personnel plugin unavailable for headcount query: %s", exc)

		contingent_headcount = len(
			session.execute(
				select(ContingentWorker).where(
					ContingentWorker.entity_id == entity_id,
					ContingentWorker.tenant_id == tenant_id,
					ContingentWorker.status == "ACTIVE",
				)
			).scalars().all()
		)

		total = permanent_headcount + contingent_headcount
		contingent_pct = round(contingent_headcount / total * 100, 2) if total > 0 else 0.0

		return {
			"permanent_headcount": permanent_headcount,
			"contingent_headcount": contingent_headcount,
			"total_workforce": total,
			"contingent_pct": contingent_pct,
		}


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"hcm.contingent.approve_timesheet",
	"Approve contingent worker timesheet",
)
def _bpm_approve_timesheet(
	record_ctx: dict,
	session: Any,
	timesheet_id: str = "",
	approver_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.hcm.contingent.services import ContingentWorkforceService
	except ImportError:
		return {"status": "error", "message": "hcm.contingent plugin not installed"}
	try:
		svc = ContingentWorkforceService()
		ts = svc.approve_timesheet(
			timesheet_id=timesheet_id,
			approver_id=approver_id,
			session=session,
		)
		return {"status": "ok", "timesheet_id": ts.id, "timesheet_status": ts.status}
	except Exception as exc:
		log.warning("bpm hcm.contingent.approve_timesheet failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"hcm.contingent.compute_spend",
	"Compute contingent workforce spend for period",
)
def _bpm_compute_spend(
	record_ctx: dict,
	session: Any,
	tenant_id: str = "",
	period: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.hcm.contingent.services import ContingentWorkforceService
	except ImportError:
		return {"status": "error", "message": "hcm.contingent plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = ContingentWorkforceService()
		result = svc.compute_spend(
			tenant_id=_tenant_id,
			period=period,
			session=session,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm hcm.contingent.compute_spend failed: %s", exc)
		return {"status": "error", "message": str(exc)}
