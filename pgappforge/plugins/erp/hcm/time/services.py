"""
pgappforge/plugins/erp/hcm/time/services.py

TimeService — stateless business logic for the HCM Time & Attendance plugin.

All public methods accept an explicit SQLAlchemy session.
Transaction boundaries owned by the caller.

Hours are stored as Decimal / Numeric — NOT cents (hours are not monetary).
All Decimal arithmetic uses explicit quantisation.

Key public methods:
  clock_in(employee_id, session)                  -> AttendanceRecord
  clock_out(employee_id, session)                 -> AttendanceRecord
  submit_leave_request(data, session)             -> LeaveRequest
  approve_leave_request(request_id, approver_id, session) -> LeaveRequest
  reject_leave_request(request_id, approver_id, reason, session) -> LeaveRequest
  cancel_leave_request(request_id, session)       -> LeaveRequest
  recompute_leave_balance(employee_id, leave_type, year, session) -> LeaveBalance
  submit_timesheet(timesheet_id, session)         -> Timesheet
  approve_timesheet(timesheet_id, approver_id, session) -> Timesheet
  reject_timesheet(timesheet_id, approver_id, session)  -> Timesheet
  add_time_entry(data, session)                   -> TimeEntry
  working_days(start_date, end_date)              -> Decimal
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

_HALF_UP = ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TimeServiceError(Exception):
	"""Base domain error for Time & Attendance operations."""


class AttendanceError(TimeServiceError):
	pass


class LeaveError(TimeServiceError):
	pass


class TimesheetError(TimeServiceError):
	pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_utc() -> date:
	return datetime.now(timezone.utc).date()


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def working_days(start: date, end: date) -> Decimal:
	"""Count working days (Mon-Fri) between start and end inclusive.

	Returns Decimal for consistency with leave balance fields.
	Does not account for public holidays — extend as needed.
	"""
	if end < start:
		return Decimal(0)
	count = 0
	current = start
	while current <= end:
		if current.weekday() < 5:  # Mon=0, Fri=4
			count += 1
		current += timedelta(days=1)
	return Decimal(count)


# ---------------------------------------------------------------------------
# TimeService
# ---------------------------------------------------------------------------

class TimeService:
	"""Stateless Time & Attendance domain service."""

	# ------------------------------------------------------------------
	# Attendance
	# ------------------------------------------------------------------

	def clock_in(
		self,
		employee_id: str,
		session: Any,
		location: dict | None = None,
		clock_in_time: datetime | None = None,
	) -> Any:
		"""Record clock-in for today.

		Creates or updates AttendanceRecord for the employee's today.
		Raises AttendanceError if already clocked in today.
		"""
		from pgappforge.plugins.erp.hcm.time.models import AttendanceRecord
		from pgappforge.plugins.erp.hcm.time.events import ClockedInEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		from pgappforge.plugins.erp.hcm.personnel.models import Employee

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise TimeServiceError(f"Employee {employee_id!r} not found")

		today = _today_utc()
		clock_ts = clock_in_time or _now_utc()

		existing = session.execute(
			sa.select(AttendanceRecord)
			.where(AttendanceRecord.employee_id == employee_id)
			.where(AttendanceRecord.attendance_date == today)
		).scalar_one_or_none()

		if existing is not None and existing.clock_in is not None:
			raise AttendanceError(
				f"Employee {employee_id!r} has already clocked in on {today}"
			)

		if existing is None:
			record = AttendanceRecord(
				tenant_id=employee.tenant_id,
				employee_id=employee_id,
				attendance_date=today,
				clock_in=clock_ts,
				status="PRESENT",
				location=location or {},
			)
			session.add(record)
		else:
			existing.clock_in = clock_ts
			existing.status = "PRESENT"
			existing.location = location or {}
			existing.updated_at = _now_utc()
			record = existing

		session.flush()

		emit_event(
			ClockedInEvent(
				aggregate_id=record.id,
				aggregate_type="AttendanceRecord",
				tenant_id=employee.tenant_id,
				attendance_id=record.id,
				employee_id=employee_id,
				attendance_date=today.isoformat(),
				clock_in=clock_ts.isoformat(),
				location_method=(location or {}).get("method", "MANUAL"),
			),
			session,
		)
		return record

	def clock_out(
		self,
		employee_id: str,
		session: Any,
		clock_out_time: datetime | None = None,
		standard_hours: Decimal = Decimal("8"),
	) -> Any:
		"""Record clock-out and compute regular/overtime hours.

		overtime = max(0, total_hours - standard_hours)
		"""
		from pgappforge.plugins.erp.hcm.time.models import AttendanceRecord
		from pgappforge.plugins.erp.hcm.time.events import ClockedOutEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		from pgappforge.plugins.erp.hcm.personnel.models import Employee

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise TimeServiceError(f"Employee {employee_id!r} not found")

		today = _today_utc()
		clock_ts = clock_out_time or _now_utc()

		record = session.execute(
			sa.select(AttendanceRecord)
			.where(AttendanceRecord.employee_id == employee_id)
			.where(AttendanceRecord.attendance_date == today)
		).scalar_one_or_none()

		if record is None or record.clock_in is None:
			raise AttendanceError(
				f"No clock-in found for employee {employee_id!r} on {today}"
			)

		# Compute hours
		elapsed_seconds = (clock_ts - record.clock_in).total_seconds()
		total_hours = Decimal(str(elapsed_seconds / 3600)).quantize(
			Decimal("0.01"), rounding=_HALF_UP
		)
		regular = min(total_hours, standard_hours).quantize(Decimal("0.01"), rounding=_HALF_UP)
		overtime = max(Decimal(0), total_hours - standard_hours).quantize(
			Decimal("0.01"), rounding=_HALF_UP
		)

		record.clock_out = clock_ts
		record.regular_hours = regular
		record.overtime_hours = overtime
		record.updated_at = _now_utc()

		emit_event(
			ClockedOutEvent(
				aggregate_id=record.id,
				aggregate_type="AttendanceRecord",
				tenant_id=employee.tenant_id,
				attendance_id=record.id,
				employee_id=employee_id,
				attendance_date=today.isoformat(),
				clock_out=clock_ts.isoformat(),
				regular_hours=str(regular),
				overtime_hours=str(overtime),
			),
			session,
		)
		return record

	# ------------------------------------------------------------------
	# Leave requests
	# ------------------------------------------------------------------

	def submit_leave_request(self, data: dict[str, Any], session: Any) -> Any:
		"""Submit a leave request.

		Validates balance availability if leave policy requires it.
		Sets status=PENDING and updates LeaveBalance.pending.

		Args:
			data: dict with keys: tenant_id, employee_id, leave_type,
			      start_date, end_date, reason (opt).
		"""
		from pgappforge.plugins.erp.hcm.time.models import LeaveRequest, LeaveBalance
		from pgappforge.plugins.erp.hcm.time.events import LeaveRequestSubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "employee_id", "leave_type", "start_date", "end_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise LeaveError(f"Missing required fields: {missing}")

		start = date.fromisoformat(data["start_date"]) if isinstance(data["start_date"], str) else data["start_date"]
		end = date.fromisoformat(data["end_date"]) if isinstance(data["end_date"], str) else data["end_date"]

		if end < start:
			raise LeaveError("end_date must be >= start_date")

		days = working_days(start, end)
		if days == 0:
			raise LeaveError("No working days in the requested leave period")

		year = start.year
		balance = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.employee_id == data["employee_id"])
			.where(LeaveBalance.leave_type == data["leave_type"])
			.where(LeaveBalance.balance_year == year)
		).scalar_one_or_none()

		if balance is not None:
			available = Decimal(str(balance.remaining))
			if days > available:
				raise LeaveError(
					f"Insufficient leave balance: requested {days} days, available {available}"
				)
			balance.pending = Decimal(str(balance.pending)) + days
			balance.remaining = Decimal(str(balance.remaining)) - days
			balance.updated_at = _now_utc()

		req = LeaveRequest(
			tenant_id=data["tenant_id"],
			employee_id=data["employee_id"],
			leave_type=data["leave_type"],
			start_date=start,
			end_date=end,
			days_requested=days,
			status="PENDING",
			reason=data.get("reason"),
		)
		session.add(req)
		session.flush()

		emit_event(
			LeaveRequestSubmittedEvent(
				aggregate_id=req.id,
				aggregate_type="LeaveRequest",
				tenant_id=data["tenant_id"],
				leave_request_id=req.id,
				employee_id=data["employee_id"],
				leave_type=data["leave_type"],
				start_date=start.isoformat(),
				end_date=end.isoformat(),
				days_requested=str(days),
			),
			session,
		)
		log.info(
			"TimeService.submit_leave_request: emp=%s type=%s days=%s",
			data["employee_id"], data["leave_type"], days,
		)
		return req

	def approve_leave_request(
		self,
		request_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Approve a pending leave request.

		Moves days from pending → taken in LeaveBalance.
		"""
		from pgappforge.plugins.erp.hcm.time.models import LeaveRequest, LeaveBalance
		from pgappforge.plugins.erp.hcm.time.events import LeaveRequestApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		req = session.get(LeaveRequest, request_id)
		if req is None:
			raise LeaveError(f"LeaveRequest {request_id!r} not found")
		if req.status != "PENDING":
			raise LeaveError(f"LeaveRequest is {req.status!r}; must be PENDING to approve")

		req.status = "APPROVED"
		req.approver_id = approver_id
		req.actioned_at = _now_utc()
		req.updated_at = _now_utc()

		# Move pending → taken
		year = req.start_date.year
		balance = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.employee_id == req.employee_id)
			.where(LeaveBalance.leave_type == req.leave_type)
			.where(LeaveBalance.balance_year == year)
		).scalar_one_or_none()

		if balance is not None:
			days = Decimal(str(req.days_requested))
			balance.pending = max(Decimal(0), Decimal(str(balance.pending)) - days)
			balance.taken = Decimal(str(balance.taken)) + days
			balance.updated_at = _now_utc()

		emit_event(
			LeaveRequestApprovedEvent(
				aggregate_id=request_id,
				aggregate_type="LeaveRequest",
				tenant_id=req.tenant_id,
				leave_request_id=request_id,
				employee_id=req.employee_id,
				leave_type=req.leave_type,
				approver_id=approver_id,
				days_approved=str(req.days_requested),
			),
			session,
		)
		return req

	def reject_leave_request(
		self,
		request_id: str,
		approver_id: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Reject a pending leave request. Returns days to available balance."""
		from pgappforge.plugins.erp.hcm.time.models import LeaveRequest, LeaveBalance
		from pgappforge.plugins.erp.hcm.time.events import LeaveRequestRejectedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		req = session.get(LeaveRequest, request_id)
		if req is None:
			raise LeaveError(f"LeaveRequest {request_id!r} not found")
		if req.status != "PENDING":
			raise LeaveError(f"LeaveRequest is {req.status!r}; must be PENDING to reject")

		req.status = "REJECTED"
		req.approver_id = approver_id
		req.actioned_at = _now_utc()
		req.updated_at = _now_utc()

		# Return pending days to remaining
		year = req.start_date.year
		balance = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.employee_id == req.employee_id)
			.where(LeaveBalance.leave_type == req.leave_type)
			.where(LeaveBalance.balance_year == year)
		).scalar_one_or_none()

		if balance is not None:
			days = Decimal(str(req.days_requested))
			balance.pending = max(Decimal(0), Decimal(str(balance.pending)) - days)
			balance.remaining = Decimal(str(balance.remaining)) + days
			balance.updated_at = _now_utc()

		emit_event(
			LeaveRequestRejectedEvent(
				aggregate_id=request_id,
				aggregate_type="LeaveRequest",
				tenant_id=req.tenant_id,
				leave_request_id=request_id,
				employee_id=req.employee_id,
				leave_type=req.leave_type,
				approver_id=approver_id,
				reason=reason,
			),
			session,
		)
		return req

	def cancel_leave_request(self, request_id: str, session: Any) -> Any:
		"""Cancel a PENDING or APPROVED leave request. Returns days to balance."""
		from pgappforge.plugins.erp.hcm.time.models import LeaveRequest, LeaveBalance
		from pgappforge.plugins.erp.hcm.time.events import LeaveRequestCancelledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		req = session.get(LeaveRequest, request_id)
		if req is None:
			raise LeaveError(f"LeaveRequest {request_id!r} not found")
		if req.status not in ("PENDING", "APPROVED"):
			raise LeaveError(f"Cannot cancel LeaveRequest in status {req.status!r}")

		was_approved = req.status == "APPROVED"
		days = Decimal(str(req.days_requested))

		req.status = "CANCELLED"
		req.updated_at = _now_utc()

		year = req.start_date.year
		balance = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.employee_id == req.employee_id)
			.where(LeaveBalance.leave_type == req.leave_type)
			.where(LeaveBalance.balance_year == year)
		).scalar_one_or_none()

		if balance is not None:
			if was_approved:
				balance.taken = max(Decimal(0), Decimal(str(balance.taken)) - days)
			else:
				balance.pending = max(Decimal(0), Decimal(str(balance.pending)) - days)
			balance.remaining = Decimal(str(balance.remaining)) + days
			balance.updated_at = _now_utc()

		emit_event(
			LeaveRequestCancelledEvent(
				aggregate_id=request_id,
				aggregate_type="LeaveRequest",
				tenant_id=req.tenant_id,
				leave_request_id=request_id,
				employee_id=req.employee_id,
				leave_type=req.leave_type,
				days_returned=str(days),
			),
			session,
		)
		return req

	def recompute_leave_balance(
		self,
		employee_id: str,
		leave_type: str,
		year: int,
		session: Any,
	) -> Any:
		"""Recompute LeaveBalance.remaining = accrued - taken - pending.

		Creates balance row if it doesn't exist.
		"""
		from pgappforge.plugins.erp.hcm.time.models import LeaveBalance, LeaveRequest
		from pgappforge.plugins.erp.hcm.personnel.models import Employee

		employee = session.get(Employee, employee_id)
		if employee is None:
			raise TimeServiceError(f"Employee {employee_id!r} not found")

		balance = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.employee_id == employee_id)
			.where(LeaveBalance.leave_type == leave_type)
			.where(LeaveBalance.balance_year == year)
		).scalar_one_or_none()

		if balance is None:
			balance = LeaveBalance(
				tenant_id=employee.tenant_id,
				employee_id=employee_id,
				leave_type=leave_type,
				balance_year=year,
				accrued=Decimal(0),
				taken=Decimal(0),
				pending=Decimal(0),
				remaining=Decimal(0),
			)
			session.add(balance)

		# Recount from approved/pending requests in this year
		taken = Decimal(str(session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(LeaveRequest.days_requested), 0))
			.where(LeaveRequest.employee_id == employee_id)
			.where(LeaveRequest.leave_type == leave_type)
			.where(sa.extract("year", LeaveRequest.start_date) == year)
			.where(LeaveRequest.status == "APPROVED")
		).scalar() or 0))

		pending = Decimal(str(session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(LeaveRequest.days_requested), 0))
			.where(LeaveRequest.employee_id == employee_id)
			.where(LeaveRequest.leave_type == leave_type)
			.where(sa.extract("year", LeaveRequest.start_date) == year)
			.where(LeaveRequest.status == "PENDING")
		).scalar() or 0))

		balance.taken = taken
		balance.pending = pending
		balance.remaining = Decimal(str(balance.accrued)) - taken - pending
		balance.updated_at = _now_utc()
		return balance

	# ------------------------------------------------------------------
	# Timesheets
	# ------------------------------------------------------------------

	def create_timesheet(self, data: dict[str, Any], session: Any) -> Any:
		"""Create a DRAFT timesheet for a week.

		Args:
			data: dict with keys: tenant_id, employee_id, week_start (ISO date Monday).
		"""
		from pgappforge.plugins.erp.hcm.time.models import Timesheet

		week_start = data["week_start"]
		if isinstance(week_start, str):
			week_start = date.fromisoformat(week_start)
		if week_start.weekday() != 0:
			raise TimesheetError("week_start must be a Monday (weekday=0)")

		ts = Timesheet(
			tenant_id=data["tenant_id"],
			employee_id=data["employee_id"],
			week_start=week_start,
			total_regular_hours=Decimal(0),
			total_overtime_hours=Decimal(0),
			status="DRAFT",
		)
		session.add(ts)
		session.flush()
		return ts

	def add_time_entry(self, data: dict[str, Any], session: Any) -> Any:
		"""Add a TimeEntry to a DRAFT timesheet and update totals.

		Args:
			data: dict with keys: tenant_id, timesheet_id, entry_date,
			      regular_hours (Decimal-compatible), overtime_hours (opt),
			      project_code (opt), cost_center (opt), description (opt).
		"""
		from pgappforge.plugins.erp.hcm.time.models import Timesheet, TimeEntry

		ts = session.get(Timesheet, data.get("timesheet_id", ""))
		if ts is None:
			raise TimesheetError(f"Timesheet {data.get('timesheet_id')!r} not found")
		if ts.status != "DRAFT":
			raise TimesheetError(f"Cannot add entries to timesheet in status {ts.status!r}")

		entry_date = data["entry_date"]
		if isinstance(entry_date, str):
			entry_date = date.fromisoformat(entry_date)

		reg = Decimal(str(data.get("regular_hours", 0))).quantize(Decimal("0.01"), rounding=_HALF_UP)
		ot = Decimal(str(data.get("overtime_hours", 0))).quantize(Decimal("0.01"), rounding=_HALF_UP)

		if reg < 0 or ot < 0:
			raise TimesheetError("Hours must be non-negative")

		entry = TimeEntry(
			tenant_id=data["tenant_id"],
			timesheet_id=ts.id,
			entry_date=entry_date,
			project_code=data.get("project_code"),
			cost_center=data.get("cost_center"),
			regular_hours=reg,
			overtime_hours=ot,
			description=data.get("description"),
		)
		session.add(entry)

		ts.total_regular_hours = Decimal(str(ts.total_regular_hours)) + reg
		ts.total_overtime_hours = Decimal(str(ts.total_overtime_hours)) + ot
		ts.updated_at = _now_utc()

		session.flush()
		return entry

	def submit_timesheet(self, timesheet_id: str, session: Any) -> Any:
		"""Submit a DRAFT timesheet for manager approval."""
		from pgappforge.plugins.erp.hcm.time.models import Timesheet
		from pgappforge.plugins.erp.hcm.time.events import TimesheetSubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		ts = session.get(Timesheet, timesheet_id)
		if ts is None:
			raise TimesheetError(f"Timesheet {timesheet_id!r} not found")
		if ts.status != "DRAFT":
			raise TimesheetError(f"Timesheet must be DRAFT to submit; got {ts.status!r}")

		ts.status = "SUBMITTED"
		ts.updated_at = _now_utc()

		emit_event(
			TimesheetSubmittedEvent(
				aggregate_id=timesheet_id,
				aggregate_type="Timesheet",
				tenant_id=ts.tenant_id,
				timesheet_id=timesheet_id,
				employee_id=ts.employee_id,
				week_start=ts.week_start.isoformat(),
				total_regular_hours=str(ts.total_regular_hours),
				total_overtime_hours=str(ts.total_overtime_hours),
			),
			session,
		)
		return ts

	def approve_timesheet(
		self,
		timesheet_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Approve a SUBMITTED timesheet."""
		from pgappforge.plugins.erp.hcm.time.models import Timesheet
		from pgappforge.plugins.erp.hcm.time.events import TimesheetApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		ts = session.get(Timesheet, timesheet_id)
		if ts is None:
			raise TimesheetError(f"Timesheet {timesheet_id!r} not found")
		if ts.status != "SUBMITTED":
			raise TimesheetError(f"Timesheet must be SUBMITTED to approve; got {ts.status!r}")

		ts.status = "APPROVED"
		ts.approved_by = approver_id
		ts.updated_at = _now_utc()

		emit_event(
			TimesheetApprovedEvent(
				aggregate_id=timesheet_id,
				aggregate_type="Timesheet",
				tenant_id=ts.tenant_id,
				timesheet_id=timesheet_id,
				employee_id=ts.employee_id,
				week_start=ts.week_start.isoformat(),
				approved_by=approver_id,
				total_regular_hours=str(ts.total_regular_hours),
				total_overtime_hours=str(ts.total_overtime_hours),
			),
			session,
		)
		log.info("TimeService.approve_timesheet: %s approved by %s", timesheet_id, approver_id)
		return ts

	def reject_timesheet(
		self,
		timesheet_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Reject a SUBMITTED timesheet, returning it to DRAFT."""
		from pgappforge.plugins.erp.hcm.time.models import Timesheet
		from pgappforge.plugins.erp.hcm.time.events import TimesheetRejectedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		ts = session.get(Timesheet, timesheet_id)
		if ts is None:
			raise TimesheetError(f"Timesheet {timesheet_id!r} not found")
		if ts.status != "SUBMITTED":
			raise TimesheetError(f"Timesheet must be SUBMITTED to reject; got {ts.status!r}")

		ts.status = "REJECTED"
		ts.updated_at = _now_utc()

		emit_event(
			TimesheetRejectedEvent(
				aggregate_id=timesheet_id,
				aggregate_type="Timesheet",
				tenant_id=ts.tenant_id,
				timesheet_id=timesheet_id,
				employee_id=ts.employee_id,
				week_start=ts.week_start.isoformat(),
				rejected_by=approver_id,
			),
			session,
		)
		return ts


__all__ = [
	"TimeService",
	"TimeServiceError",
	"AttendanceError",
	"LeaveError",
	"TimesheetError",
	"working_days",
]
