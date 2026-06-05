"""
pgappforge/plugins/erp/hcm/time/services.py

TimeService — stateless business logic for the HCM Time & Attendance plugin.

All public methods accept an explicit SQLAlchemy session.
Transaction boundaries owned by the caller.

Hours are stored as Decimal / Numeric — NOT cents (hours are not monetary).
Overtime pay is stored as INTEGER CENTS (consistent with money convention).
All Decimal arithmetic uses explicit quantisation.

Kenya Employment Act 2007 references:
  s.28  — annual leave: 21 working days per year
  s.30  — sick leave: 7 days full pay + 7 days half pay (= 14 days entitlement block),
           statutory minimum 10 days treated here as two separate balances
  s.29  — maternity: 90 calendar days
  s.29A — paternity: 14 calendar days
  s.27  — overtime: weekday >8h = 1.5x, rest day = 1.5x, public holiday = 2.0x
  s.35  — separation: unused annual leave paid out at daily rate

Key public methods (original):
  clock_in / clock_out / submit_leave_request / approve_leave_request
  reject_leave_request / cancel_leave_request / recompute_leave_balance
  submit_timesheet / approve_timesheet / reject_timesheet
  add_time_entry / working_days

New methods (CRITICAL/HIGH gap-fill):
  # Leave accrual engine
  accrue_monthly(session, employee_id, accrual_month, tenant_id) -> dict
  get_leave_balance(session, employee_id, leave_type, as_of_date=None) -> dict
  initialise_statutory_entitlements(session, employee_id, hire_date, tenant_id) -> dict

  # Carry-forward
  process_year_end_carryforward(session, carry_date, tenant_id='') -> dict

  # Public holiday calendar
  is_public_holiday(session, d, tenant_id='', country_code='KE') -> bool
  get_working_days(session, from_date, to_date, tenant_id='', country_code='KE') -> int
  seed_kenya_public_holidays(session, year, tenant_id='') -> int

  # Overtime
  calculate_overtime(session, employee_id, attendance_record_id, tenant_id,
                     standard_hours=8) -> OvertimeRecord
  calculate_overtime_pay(session, overtime_record_id, hourly_rate_cents) -> int

  # Biometric import
  import_attendance(session, records, tenant_id='') -> dict

  # Shift / roster
  create_shift_pattern(session, data) -> ShiftPattern
  assign_shift(session, data) -> EmployeeShift
  get_roster(session, from_date, to_date, tenant_id='', dept_id=None) -> list
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
# Kenya Employment Act 2007 statutory constants
# ---------------------------------------------------------------------------

# Annual leave: 21 working days / year → 1.75 days / month
_KE_ANNUAL_DAYS_PER_YEAR = Decimal("21")
_KE_ANNUAL_ACCRUAL_RATE = Decimal("1.75")  # per month

# Sick leave: 7 days full + 7 days half = effectively 10 productive days modelled
# For accrual we credit 10 days/year → 0.83/month (rounded to 2dp)
_KE_SICK_DAYS_PER_YEAR = Decimal("10")
_KE_SICK_ACCRUAL_RATE = Decimal("0.83")  # per month (10 / 12, rounded)

# Statutory grants on hire (granted upfront, not accrued monthly)
_KE_MATERNITY_DAYS = Decimal("90")   # calendar days
_KE_PATERNITY_DAYS = Decimal("14")   # calendar days

# Carry-forward cap: maximum 10 days annual leave may roll over
_KE_ANNUAL_MAX_CARRY = Decimal("10")

# Overtime multipliers
_OT_WEEKDAY_RATE = Decimal("1.50")
_OT_WEEKEND_RATE = Decimal("1.50")
_OT_PUBLIC_HOLIDAY_RATE = Decimal("2.00")

# Biometric anomaly threshold
_BIO_MAX_DURATION_MINUTES = 720  # 12 hours

# Fixed Kenya public holidays (month, day, name)
_KE_FIXED_HOLIDAYS: list[tuple[int, int, str]] = [
	(1, 1, "New Year's Day"),
	(5, 1, "Labour Day"),
	(6, 1, "Madaraka Day"),
	(10, 20, "Mashujaa Day"),
	(12, 12, "Jamhuri Day"),
	(12, 25, "Christmas Day"),
	(12, 26, "Boxing Day"),
]


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


# ---------------------------------------------------------------------------
# Easter calculation (Gregorian / Anonymous algorithm)
# ---------------------------------------------------------------------------

def _easter_date(year: int) -> date:
	"""Return Easter Sunday for the given Gregorian year."""
	a = year % 19
	b, c = divmod(year, 100)
	d, e = divmod(b, 4)
	f = (b + 8) // 25
	g = (b - f + 1) // 3
	h = (19 * a + b - d - g + 15) % 30
	i, k = divmod(c, 4)
	l = (32 + 2 * e + 2 * i - h - k) % 7
	m = (a + 11 * h + 22 * l) // 451
	month, day = divmod(h + l - 7 * m + 114, 31)
	return date(year, month, day + 1)


# ---------------------------------------------------------------------------
# Public Holiday helpers  [CRITICAL]
# ---------------------------------------------------------------------------

def is_public_holiday(
	session: Any,
	d: date,
	tenant_id: str = "",
	country_code: str = "KE",
) -> bool:
	"""Return True if *d* is an active public holiday for the given tenant/country."""
	from pgappforge.plugins.erp.hcm.time.models import PublicHoliday

	q = (
		sa.select(sa.func.count())
		.select_from(PublicHoliday)
		.where(PublicHoliday.holiday_date == d)
		.where(PublicHoliday.country_code == country_code)
		.where(PublicHoliday.is_active.is_(True))
	)
	# Tenant-aware: match rows with this tenant OR the global empty-string tenant
	q = q.where(PublicHoliday.tenant_id.in_([tenant_id, "00000000-0000-0000-0000-000000000000"]))
	return bool(session.execute(q).scalar() or 0)


def get_working_days(
	session: Any,
	from_date: date,
	to_date: date,
	tenant_id: str = "",
	country_code: str = "KE",
) -> int:
	"""Count working days (Mon-Fri, excluding public holidays) from_date..to_date inclusive.

	Replaces the naive `working_days()` helper for holiday-aware calculations.
	"""
	if to_date < from_date:
		return 0
	count = 0
	current = from_date
	while current <= to_date:
		if current.weekday() < 5:  # Mon-Fri
			if not is_public_holiday(session, current, tenant_id=tenant_id, country_code=country_code):
				count += 1
		current += timedelta(days=1)
	return count


def seed_kenya_public_holidays(
	session: Any,
	year: int,
	tenant_id: str = "",
) -> int:
	"""Insert Kenya public holidays for *year* if they don't already exist.

	Returns the count of rows inserted (0 if all already present).
	"""
	from pgappforge.plugins.erp.hcm.time.models import PublicHoliday

	_tid = tenant_id or "00000000-0000-0000-0000-000000000000"

	easter = _easter_date(year)
	floating: list[tuple[date, str]] = [
		(easter - timedelta(days=2), "Good Friday"),
		(easter + timedelta(days=1), "Easter Monday"),
	]

	holidays: list[tuple[date, str, bool]] = [
		(date(year, m, d), name, True) for m, d, name in _KE_FIXED_HOLIDAYS
	]
	holidays += [(d, name, True) for d, name in floating]

	inserted = 0
	for hdate, hname, is_stat in holidays:
		exists = session.execute(
			sa.select(sa.func.count())
			.select_from(PublicHoliday)
			.where(PublicHoliday.tenant_id == _tid)
			.where(PublicHoliday.country_code == "KE")
			.where(PublicHoliday.holiday_date == hdate)
		).scalar()
		if exists:
			continue
		session.add(PublicHoliday(
			tenant_id=_tid,
			country_code="KE",
			holiday_date=hdate,
			name=hname,
			is_statutory=is_stat,
			is_active=True,
		))
		inserted += 1

	if inserted:
		session.flush()
	log.info("seed_kenya_public_holidays: year=%d inserted=%d", year, inserted)
	return inserted


# ---------------------------------------------------------------------------
# Leave accrual engine  [CRITICAL]
# ---------------------------------------------------------------------------

def accrue_monthly(
	session: Any,
	employee_id: str,
	accrual_month: date,
	tenant_id: str,
) -> dict[str, Any]:
	"""Credit monthly leave accrual for one employee.

	accrual_month should be the first day of the month (e.g. date(2026, 6, 1)).
	Accrues ANNUAL at 1.75 days/month and SICK at 0.83 days/month per
	Kenya Employment Act 2007 s.28 and s.30.

	Returns dict with keys: employee_id, accrual_month, entries (list of dicts).

	Raises TimeServiceError if accrual for this month already exists for both types.
	"""
	from pgappforge.plugins.erp.hcm.time.models import LeaveAccrual, LeaveBalance

	# Normalise to first-of-month
	month_start = accrual_month.replace(day=1)
	year = month_start.year

	accrual_rates = {
		"ANNUAL": _KE_ANNUAL_ACCRUAL_RATE,
		"SICK": _KE_SICK_ACCRUAL_RATE,
	}

	entries = []
	for leave_type, rate in accrual_rates.items():
		# Idempotent: skip if this month already accrued
		existing = session.execute(
			sa.select(LeaveAccrual)
			.where(LeaveAccrual.employee_id == employee_id)
			.where(LeaveAccrual.leave_type == leave_type)
			.where(LeaveAccrual.accrual_month == month_start)
			.where(LeaveAccrual.reason == "monthly_accrual")
		).scalar_one_or_none()
		if existing is not None:
			log.debug(
				"accrue_monthly: skip emp=%s type=%s month=%s (already accrued)",
				employee_id, leave_type, month_start,
			)
			entries.append({
				"leave_type": leave_type,
				"days_accrued": str(existing.days_accrued),
				"skipped": True,
			})
			continue

		# Get or create balance row
		balance = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.employee_id == employee_id)
			.where(LeaveBalance.leave_type == leave_type)
			.where(LeaveBalance.balance_year == year)
		).scalar_one_or_none()

		if balance is None:
			balance = LeaveBalance(
				tenant_id=tenant_id,
				employee_id=employee_id,
				leave_type=leave_type,
				balance_year=year,
				accrued=Decimal(0),
				taken=Decimal(0),
				pending=Decimal(0),
				remaining=Decimal(0),
			)
			session.add(balance)
			session.flush()

		balance_before = Decimal(str(balance.accrued)).quantize(Decimal("0.01"), rounding=_HALF_UP)
		balance_after = (balance_before + rate).quantize(Decimal("0.01"), rounding=_HALF_UP)

		balance.accrued = balance_after
		balance.remaining = (
			balance_after
			- Decimal(str(balance.taken))
			- Decimal(str(balance.pending))
		).quantize(Decimal("0.01"), rounding=_HALF_UP)
		balance.updated_at = _now_utc()

		ledger = LeaveAccrual(
			tenant_id=tenant_id,
			employee_id=employee_id,
			leave_type=leave_type,
			accrual_month=month_start,
			days_accrued=rate,
			balance_before=balance_before,
			balance_after=balance_after,
			reason="monthly_accrual",
		)
		session.add(ledger)
		entries.append({
			"leave_type": leave_type,
			"days_accrued": str(rate),
			"balance_before": str(balance_before),
			"balance_after": str(balance_after),
			"skipped": False,
		})

	session.flush()
	log.info("accrue_monthly: emp=%s month=%s entries=%d", employee_id, month_start, len(entries))
	return {
		"employee_id": employee_id,
		"accrual_month": month_start.isoformat(),
		"entries": entries,
	}


def get_leave_balance(
	session: Any,
	employee_id: str,
	leave_type: str,
	as_of_date: date | None = None,
) -> dict[str, Any]:
	"""Return the current leave balance snapshot for an employee + leave type.

	as_of_date defaults to today. Uses balance_year = as_of_date.year.
	Returns dict with: employee_id, leave_type, year, accrued, taken, pending, remaining.
	"""
	from pgappforge.plugins.erp.hcm.time.models import LeaveBalance

	target_date = as_of_date or _today_utc()
	year = target_date.year

	balance = session.execute(
		sa.select(LeaveBalance)
		.where(LeaveBalance.employee_id == employee_id)
		.where(LeaveBalance.leave_type == leave_type)
		.where(LeaveBalance.balance_year == year)
	).scalar_one_or_none()

	if balance is None:
		return {
			"employee_id": employee_id,
			"leave_type": leave_type,
			"year": year,
			"accrued": "0.00",
			"taken": "0.00",
			"pending": "0.00",
			"remaining": "0.00",
		}

	return {
		"employee_id": employee_id,
		"leave_type": leave_type,
		"year": year,
		"accrued": str(Decimal(str(balance.accrued)).quantize(Decimal("0.01"))),
		"taken": str(Decimal(str(balance.taken)).quantize(Decimal("0.01"))),
		"pending": str(Decimal(str(balance.pending)).quantize(Decimal("0.01"))),
		"remaining": str(Decimal(str(balance.remaining)).quantize(Decimal("0.01"))),
	}


def initialise_statutory_entitlements(
	session: Any,
	employee_id: str,
	hire_date: date,
	tenant_id: str,
) -> dict[str, Any]:
	"""Grant statutory leave entitlements on hire per Kenya Employment Act 2007.

	Grants:
	  ANNUAL    — 21 days (upfront for first year; accrual takes over in subsequent years)
	  SICK      — 10 days
	  MATERNITY — 90 calendar days (upfront; female employees only — caller filters)
	  PATERNITY — 14 calendar days (upfront; male employees only — caller filters)

	All grants recorded as LeaveAccrual rows with reason='hire_grant'.
	Idempotent: skips any leave_type that already has a hire_grant row.
	Returns dict with employee_id, granted (list).
	"""
	from pgappforge.plugins.erp.hcm.time.models import LeaveAccrual, LeaveBalance

	year = hire_date.year
	month_start = hire_date.replace(day=1)

	grants: dict[str, Decimal] = {
		"ANNUAL": _KE_ANNUAL_DAYS_PER_YEAR,
		"SICK": _KE_SICK_DAYS_PER_YEAR,
		"MATERNITY": _KE_MATERNITY_DAYS,
		"PATERNITY": _KE_PATERNITY_DAYS,
	}

	granted = []
	for leave_type, days in grants.items():
		existing = session.execute(
			sa.select(LeaveAccrual)
			.where(LeaveAccrual.employee_id == employee_id)
			.where(LeaveAccrual.leave_type == leave_type)
			.where(LeaveAccrual.reason == "hire_grant")
		).scalar_one_or_none()
		if existing is not None:
			continue

		balance = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.employee_id == employee_id)
			.where(LeaveBalance.leave_type == leave_type)
			.where(LeaveBalance.balance_year == year)
		).scalar_one_or_none()

		if balance is None:
			balance = LeaveBalance(
				tenant_id=tenant_id,
				employee_id=employee_id,
				leave_type=leave_type,
				balance_year=year,
				accrued=Decimal(0),
				taken=Decimal(0),
				pending=Decimal(0),
				remaining=Decimal(0),
			)
			session.add(balance)
			session.flush()

		balance_before = Decimal(str(balance.accrued)).quantize(Decimal("0.01"), rounding=_HALF_UP)
		balance_after = (balance_before + days).quantize(Decimal("0.01"), rounding=_HALF_UP)

		balance.accrued = balance_after
		balance.remaining = (
			balance_after
			- Decimal(str(balance.taken))
			- Decimal(str(balance.pending))
		).quantize(Decimal("0.01"), rounding=_HALF_UP)
		balance.updated_at = _now_utc()

		session.add(LeaveAccrual(
			tenant_id=tenant_id,
			employee_id=employee_id,
			leave_type=leave_type,
			accrual_month=month_start,
			days_accrued=days,
			balance_before=balance_before,
			balance_after=balance_after,
			reason="hire_grant",
			notes=f"Statutory hire grant — Kenya Employment Act 2007 (hired {hire_date})",
		))
		granted.append({"leave_type": leave_type, "days": str(days)})

	session.flush()
	log.info("initialise_statutory_entitlements: emp=%s granted=%d types", employee_id, len(granted))
	return {"employee_id": employee_id, "granted": granted}


# ---------------------------------------------------------------------------
# Leave carry-forward  [CRITICAL]
# ---------------------------------------------------------------------------

def process_year_end_carryforward(
	session: Any,
	carry_date: date,
	tenant_id: str = "",
) -> dict[str, Any]:
	"""Apply carry-forward rules for ANNUAL leave at year-end.

	For every employee with an ANNUAL balance in the year prior to carry_date:
	  1. Carry forward min(remaining, _KE_ANNUAL_MAX_CARRY=10) days.
	  2. Forfeit any days above the carry cap (record as negative LeaveAccrual).
	  3. Create a carry_forward LeaveAccrual row in the new year.

	carry_date is typically date(year, 1, 1) — first day of the new year.
	Returns dict with: carry_date, processed (count), forfeited_total (Decimal),
	                   carried_total (Decimal), details (list).
	"""
	from pgappforge.plugins.erp.hcm.time.models import LeaveAccrual, LeaveBalance

	old_year = carry_date.year - 1
	new_year = carry_date.year
	new_month = carry_date.replace(day=1)

	if tenant_id:
		old_balances = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.leave_type == "ANNUAL")
			.where(LeaveBalance.balance_year == old_year)
			.where(LeaveBalance.tenant_id == tenant_id)
		).scalars().all()
	else:
		old_balances = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.leave_type == "ANNUAL")
			.where(LeaveBalance.balance_year == old_year)
		).scalars().all()

	carried_total = Decimal(0)
	forfeited_total = Decimal(0)
	details = []

	for old_bal in old_balances:
		remaining = Decimal(str(old_bal.remaining)).quantize(Decimal("0.01"), rounding=_HALF_UP)
		if remaining <= Decimal(0):
			continue

		carry = min(remaining, _KE_ANNUAL_MAX_CARRY).quantize(Decimal("0.01"), rounding=_HALF_UP)
		forfeit = (remaining - carry).quantize(Decimal("0.01"), rounding=_HALF_UP)

		# Zero out old year remaining (balance is now historical)
		old_bal.remaining = Decimal(0)
		old_bal.updated_at = _now_utc()

		# Forfeit ledger row if any days lapse
		if forfeit > Decimal(0):
			_existing_forfeit = session.execute(
				sa.select(LeaveAccrual)
				.where(LeaveAccrual.employee_id == old_bal.employee_id)
				.where(LeaveAccrual.leave_type == "ANNUAL")
				.where(LeaveAccrual.accrual_month == new_month)
				.where(LeaveAccrual.reason == "forfeiture")
			).scalar_one_or_none()
			if _existing_forfeit is None:
				session.add(LeaveAccrual(
					tenant_id=old_bal.tenant_id,
					employee_id=old_bal.employee_id,
					leave_type="ANNUAL",
					accrual_month=new_month,
					days_accrued=-forfeit,
					balance_before=remaining,
					balance_after=carry,
					reason="forfeiture",
					notes=f"Year-end forfeiture: {forfeit} days above {_KE_ANNUAL_MAX_CARRY}-day carry cap",
				))

		if carry > Decimal(0):
			# Carry into new year balance
			new_bal = session.execute(
				sa.select(LeaveBalance)
				.where(LeaveBalance.employee_id == old_bal.employee_id)
				.where(LeaveBalance.leave_type == "ANNUAL")
				.where(LeaveBalance.balance_year == new_year)
			).scalar_one_or_none()

			if new_bal is None:
				new_bal = LeaveBalance(
					tenant_id=old_bal.tenant_id,
					employee_id=old_bal.employee_id,
					leave_type="ANNUAL",
					balance_year=new_year,
					accrued=carry,
					taken=Decimal(0),
					pending=Decimal(0),
					remaining=carry,
				)
				session.add(new_bal)
			else:
				new_bal.accrued = (Decimal(str(new_bal.accrued)) + carry).quantize(Decimal("0.01"), rounding=_HALF_UP)
				new_bal.remaining = (Decimal(str(new_bal.remaining)) + carry).quantize(Decimal("0.01"), rounding=_HALF_UP)
				new_bal.updated_at = _now_utc()

			_existing_carry = session.execute(
				sa.select(LeaveAccrual)
				.where(LeaveAccrual.employee_id == old_bal.employee_id)
				.where(LeaveAccrual.leave_type == "ANNUAL")
				.where(LeaveAccrual.accrual_month == new_month)
				.where(LeaveAccrual.reason == "carry_forward")
			).scalar_one_or_none()
			if _existing_carry is None:
				session.add(LeaveAccrual(
					tenant_id=old_bal.tenant_id,
					employee_id=old_bal.employee_id,
					leave_type="ANNUAL",
					accrual_month=new_month,
					days_accrued=carry,
					balance_before=Decimal(0),
					balance_after=carry,
					reason="carry_forward",
					notes=f"Year-end carry-forward from {old_year}",
				))

		carried_total += carry
		forfeited_total += forfeit
		details.append({
			"employee_id": old_bal.employee_id,
			"carried": str(carry),
			"forfeited": str(forfeit),
		})

	session.flush()
	log.info(
		"process_year_end_carryforward: carry_date=%s processed=%d "
		"carried=%s forfeited=%s",
		carry_date, len(details), carried_total, forfeited_total,
	)
	return {
		"carry_date": carry_date.isoformat(),
		"processed": len(details),
		"carried_total": str(carried_total.quantize(Decimal("0.01"))),
		"forfeited_total": str(forfeited_total.quantize(Decimal("0.01"))),
		"details": details,
	}


# ---------------------------------------------------------------------------
# Overtime  [CRITICAL]
# ---------------------------------------------------------------------------

def calculate_overtime(
	session: Any,
	employee_id: str,
	attendance_record_id: str,
	tenant_id: str,
	standard_hours: int = 8,
) -> Any:
	"""Derive and persist an OvertimeRecord from an AttendanceRecord.

	Determines overtime_type from the work_date:
	  - PUBLIC_HOLIDAY → 2.0x
	  - WEEKEND (Sat/Sun) → 1.5x
	  - WEEKDAY (Mon-Fri) → 1.5x for hours beyond standard_hours

	Hours stored as INTEGER HUNDREDTHS (1 h = 100 units).
	Returns the OvertimeRecord (unsaved on error, flushed on success).
	Idempotent: returns existing record if one already exists for the employee/date.
	"""
	from pgappforge.plugins.erp.hcm.time.models import AttendanceRecord, OvertimeRecord

	try:
		att = session.get(AttendanceRecord, attendance_record_id)
		if att is None:
			raise TimeServiceError(f"AttendanceRecord {attendance_record_id!r} not found")
		if att.clock_in is None or att.clock_out is None:
			raise TimeServiceError(
				f"AttendanceRecord {attendance_record_id!r} missing clock_in or clock_out"
			)

		# Idempotent check
		existing = session.execute(
			sa.select(OvertimeRecord)
			.where(OvertimeRecord.employee_id == employee_id)
			.where(OvertimeRecord.work_date == att.attendance_date)
		).scalar_one_or_none()
		if existing is not None:
			return existing

		elapsed_seconds = (att.clock_out - att.clock_in).total_seconds()
		total_hours_dec = Decimal(str(elapsed_seconds / 3600)).quantize(Decimal("0.01"), rounding=_HALF_UP)
		total_hundredths = int((total_hours_dec * 100).to_integral_value(rounding=_HALF_UP))
		standard_hundredths = standard_hours * 100

		work_date = att.attendance_date
		is_ph = is_public_holiday(session, work_date, tenant_id=tenant_id)
		is_weekend = work_date.weekday() >= 5  # Sat=5, Sun=6

		if is_ph:
			ot_type = "PUBLIC_HOLIDAY"
			rate = _OT_PUBLIC_HOLIDAY_RATE
			# On a public holiday the entire shift is at 2x; regular = 0
			regular_hundredths = 0
			ot_hundredths = total_hundredths
		elif is_weekend:
			ot_type = "WEEKEND"
			rate = _OT_WEEKEND_RATE
			regular_hundredths = 0
			ot_hundredths = total_hundredths
		else:
			ot_type = "WEEKDAY"
			rate = _OT_WEEKDAY_RATE
			regular_hundredths = min(total_hundredths, standard_hundredths)
			ot_hundredths = max(0, total_hundredths - standard_hundredths)

		rec = OvertimeRecord(
			tenant_id=tenant_id,
			employee_id=employee_id,
			attendance_record_id=attendance_record_id,
			work_date=work_date,
			regular_hours_hundredths=regular_hundredths,
			overtime_hours_hundredths=ot_hundredths,
			overtime_type=ot_type,
			rate_multiplier=rate,
			is_approved=False,
		)
		session.add(rec)
		session.flush()
		log.info(
			"calculate_overtime: emp=%s date=%s type=%s ot_h=%.2f",
			employee_id, work_date, ot_type, ot_hundredths / 100,
		)
		return rec

	except TimeServiceError:
		raise
	except Exception as exc:
		log.exception("calculate_overtime unexpected error: %s", exc)
		raise TimeServiceError(f"Overtime calculation failed: {exc}") from exc


def calculate_overtime_pay(
	session: Any,
	overtime_record_id: str,
	hourly_rate_cents: int,
) -> int:
	"""Compute and persist overtime pay in cents for an OvertimeRecord.

	pay_cents = (overtime_hours_hundredths / 100) * hourly_rate_cents * rate_multiplier
	Result is rounded to nearest whole cent.
	Returns pay_cents (int).
	"""
	from pgappforge.plugins.erp.hcm.time.models import OvertimeRecord

	try:
		rec = session.get(OvertimeRecord, overtime_record_id)
		if rec is None:
			raise TimeServiceError(f"OvertimeRecord {overtime_record_id!r} not found")

		ot_hours = Decimal(str(rec.overtime_hours_hundredths)) / Decimal("100")
		rate = Decimal(str(rec.rate_multiplier))
		pay = (ot_hours * Decimal(str(hourly_rate_cents)) * rate).quantize(
			Decimal("1"), rounding=_HALF_UP
		)
		pay_cents = int(pay)

		rec.pay_cents = pay_cents
		rec.updated_at = _now_utc()
		session.flush()
		return pay_cents

	except TimeServiceError:
		raise
	except Exception as exc:
		log.exception("calculate_overtime_pay unexpected error: %s", exc)
		raise TimeServiceError(f"Overtime pay calculation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Biometric attendance import  [HIGH]
# ---------------------------------------------------------------------------

def import_attendance(
	session: Any,
	records: list[dict[str, Any]],
	tenant_id: str = "",
) -> dict[str, Any]:
	"""Ingest raw biometric/manual clock events into BiometricAttendance staging.

	Each record dict must contain:
	  employee_id    (str, UUID)
	  clock_in_iso   (str, ISO 8601 datetime with tz or naive UTC)
	  clock_out_iso  (str or None)
	  device_id      (str or None)
	  source         (str: BIOMETRIC | MANUAL | SYSTEM; default BIOMETRIC)

	Anomaly flags:
	  MISSING_CLOCK_OUT  — clock_out_iso is None or empty
	  DURATION_EXCEEDED  — duration > 720 minutes (12 h)

	Returns dict: imported, anomalies, errors.
	"""
	from pgappforge.plugins.erp.hcm.time.models import BiometricAttendance

	imported = 0
	anomalies = 0
	errors: list[dict[str, Any]] = []

	for i, raw in enumerate(records):
		try:
			emp_id = raw["employee_id"]
			clock_in_iso = raw["clock_in_iso"]
			clock_out_iso = raw.get("clock_out_iso") or None
			device_id = raw.get("device_id")
			source = raw.get("source", "BIOMETRIC").upper()

			# Parse datetimes — assume UTC if naive
			def _parse_dt(s: str) -> datetime:
				dt = datetime.fromisoformat(s)
				if dt.tzinfo is None:
					dt = dt.replace(tzinfo=timezone.utc)
				return dt

			clock_in_dt = _parse_dt(clock_in_iso)
			clock_out_dt = _parse_dt(clock_out_iso) if clock_out_iso else None

			# Compute duration
			duration_minutes: int | None = None
			is_anomaly = False
			anomaly_reason: str | None = None

			if clock_out_dt is None:
				is_anomaly = True
				anomaly_reason = "MISSING_CLOCK_OUT"
			else:
				duration_minutes = int((clock_out_dt - clock_in_dt).total_seconds() / 60)
				if duration_minutes > _BIO_MAX_DURATION_MINUTES:
					is_anomaly = True
					anomaly_reason = "DURATION_EXCEEDED"

			session.add(BiometricAttendance(
				tenant_id=tenant_id or "00000000-0000-0000-0000-000000000000",
				employee_id=emp_id,
				clock_in=clock_in_dt,
				clock_out=clock_out_dt,
				source=source,
				device_id=device_id,
				duration_minutes=duration_minutes,
				is_anomaly=is_anomaly,
				anomaly_reason=anomaly_reason,
			))
			imported += 1
			if is_anomaly:
				anomalies += 1

		except Exception as exc:
			log.warning("import_attendance: record[%d] error: %s raw=%s", i, exc, raw)
			errors.append({"index": i, "error": str(exc), "raw": raw})

	if imported:
		session.flush()

	log.info(
		"import_attendance: imported=%d anomalies=%d errors=%d",
		imported, anomalies, len(errors),
	)
	return {
		"imported": imported,
		"anomalies": anomalies,
		"errors": errors,
	}


# ---------------------------------------------------------------------------
# Shift pattern & roster  [HIGH]
# ---------------------------------------------------------------------------

def create_shift_pattern(session: Any, data: dict[str, Any]) -> Any:
	"""Create a ShiftPattern.

	data keys: tenant_id, name, start_time (time or HH:MM str),
	           end_time, days_of_week ([int]), break_minutes (opt, default 0).
	"""
	from pgappforge.plugins.erp.hcm.time.models import ShiftPattern

	try:
		def _parse_time(v: Any) -> Any:
			if isinstance(v, str):
				from datetime import time as dt_time
				parts = v.split(":")
				return dt_time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
			return v

		start = _parse_time(data["start_time"])
		end = _parse_time(data["end_time"])
		is_overnight = end < start

		pattern = ShiftPattern(
			tenant_id=data["tenant_id"],
			name=data["name"],
			start_time=start,
			end_time=end,
			days_of_week=list(data.get("days_of_week", [0, 1, 2, 3, 4])),
			break_minutes=int(data.get("break_minutes", 0)),
			is_overnight=is_overnight,
			is_active=bool(data.get("is_active", True)),
		)
		session.add(pattern)
		session.flush()
		log.info("create_shift_pattern: id=%s name=%r", pattern.id, pattern.name)
		return pattern

	except KeyError as exc:
		raise TimeServiceError(f"create_shift_pattern: missing required field {exc}") from exc
	except Exception as exc:
		log.exception("create_shift_pattern error: %s", exc)
		raise TimeServiceError(f"create_shift_pattern failed: {exc}") from exc


def assign_shift(session: Any, data: dict[str, Any]) -> Any:
	"""Assign an employee to a ShiftPattern.

	data keys: tenant_id, employee_id, shift_pattern_id,
	           effective_from (date or ISO str),
	           effective_to (date or ISO str, opt),
	           department_id (opt).

	Rejects overlapping open-ended assignments for the same employee.
	"""
	from pgappforge.plugins.erp.hcm.time.models import EmployeeShift, ShiftPattern

	try:
		emp_id = data["employee_id"]
		pattern_id = data["shift_pattern_id"]

		pattern = session.get(ShiftPattern, pattern_id)
		if pattern is None:
			raise TimeServiceError(f"ShiftPattern {pattern_id!r} not found")

		eff_from = data["effective_from"]
		if isinstance(eff_from, str):
			eff_from = date.fromisoformat(eff_from)

		eff_to_raw = data.get("effective_to")
		eff_to: date | None = None
		if eff_to_raw:
			eff_to = date.fromisoformat(eff_to_raw) if isinstance(eff_to_raw, str) else eff_to_raw
			if eff_to < eff_from:
				raise TimeServiceError("effective_to must be >= effective_from")

		# Check for open-ended overlap: any current assignment (effective_to is NULL) overlaps
		existing_open = session.execute(
			sa.select(EmployeeShift)
			.where(EmployeeShift.employee_id == emp_id)
			.where(EmployeeShift.effective_to.is_(None))
		).scalar_one_or_none()
		if existing_open is not None:
			raise TimeServiceError(
				f"Employee {emp_id!r} has an open-ended shift assignment "
				f"(id={existing_open.id!r}) — close it before assigning a new shift"
			)

		assignment = EmployeeShift(
			tenant_id=data["tenant_id"],
			employee_id=emp_id,
			shift_pattern_id=pattern_id,
			effective_from=eff_from,
			effective_to=eff_to,
			department_id=data.get("department_id"),
		)
		session.add(assignment)
		session.flush()
		log.info(
			"assign_shift: emp=%s pattern=%s from=%s to=%s",
			emp_id, pattern_id, eff_from, eff_to,
		)
		return assignment

	except TimeServiceError:
		raise
	except Exception as exc:
		log.exception("assign_shift error: %s", exc)
		raise TimeServiceError(f"assign_shift failed: {exc}") from exc


def get_roster(
	session: Any,
	from_date: date,
	to_date: date,
	tenant_id: str = "",
	dept_id: str | None = None,
) -> list[dict[str, Any]]:
	"""Return roster entries for all employees with active shift assignments
	in the [from_date, to_date] window, optionally filtered by department.

	Each entry dict contains:
	  employee_id, shift_pattern_id, shift_name,
	  effective_from, effective_to, days_of_week,
	  start_time, end_time, department_id.
	"""
	from pgappforge.plugins.erp.hcm.time.models import EmployeeShift, ShiftPattern

	try:
		q = (
			sa.select(EmployeeShift, ShiftPattern)
			.join(ShiftPattern, EmployeeShift.shift_pattern_id == ShiftPattern.id)
			.where(EmployeeShift.effective_from <= to_date)
			.where(
				sa.or_(
					EmployeeShift.effective_to.is_(None),
					EmployeeShift.effective_to >= from_date,
				)
			)
			.where(ShiftPattern.is_active.is_(True))
		)
		if tenant_id:
			q = q.where(EmployeeShift.tenant_id == tenant_id)
		if dept_id:
			q = q.where(EmployeeShift.department_id == dept_id)

		rows = session.execute(q).all()

		return [
			{
				"employee_id": es.employee_id,
				"shift_pattern_id": es.shift_pattern_id,
				"shift_name": sp.name,
				"effective_from": es.effective_from.isoformat(),
				"effective_to": es.effective_to.isoformat() if es.effective_to else None,
				"days_of_week": sp.days_of_week,
				"start_time": sp.start_time.isoformat(),
				"end_time": sp.end_time.isoformat(),
				"break_minutes": sp.break_minutes,
				"department_id": es.department_id,
			}
			for es, sp in rows
		]

	except Exception as exc:
		log.exception("get_roster error: %s", exc)
		raise TimeServiceError(f"get_roster failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Also add new methods to TimeService class for consistency
# ---------------------------------------------------------------------------

# Attach module-level helpers as methods on TimeService so callers can use
# either the stateless functions or the service instance interchangeably.

TimeService.accrue_monthly = staticmethod(accrue_monthly)  # type: ignore[attr-defined]
TimeService.get_leave_balance = staticmethod(get_leave_balance)  # type: ignore[attr-defined]
TimeService.initialise_statutory_entitlements = staticmethod(initialise_statutory_entitlements)  # type: ignore[attr-defined]
TimeService.process_year_end_carryforward = staticmethod(process_year_end_carryforward)  # type: ignore[attr-defined]
TimeService.is_public_holiday = staticmethod(is_public_holiday)  # type: ignore[attr-defined]
TimeService.get_working_days = staticmethod(get_working_days)  # type: ignore[attr-defined]
TimeService.seed_kenya_public_holidays = staticmethod(seed_kenya_public_holidays)  # type: ignore[attr-defined]
TimeService.calculate_overtime = staticmethod(calculate_overtime)  # type: ignore[attr-defined]
TimeService.calculate_overtime_pay = staticmethod(calculate_overtime_pay)  # type: ignore[attr-defined]
TimeService.import_attendance = staticmethod(import_attendance)  # type: ignore[attr-defined]
TimeService.create_shift_pattern = staticmethod(create_shift_pattern)  # type: ignore[attr-defined]
TimeService.assign_shift = staticmethod(assign_shift)  # type: ignore[attr-defined]
TimeService.get_roster = staticmethod(get_roster)  # type: ignore[attr-defined]


__all__ = [
	"TimeService",
	"TimeServiceError",
	"AttendanceError",
	"LeaveError",
	"TimesheetError",
	"working_days",
	# new gap-fill functions
	"accrue_monthly",
	"get_leave_balance",
	"initialise_statutory_entitlements",
	"process_year_end_carryforward",
	"is_public_holiday",
	"get_working_days",
	"seed_kenya_public_holidays",
	"calculate_overtime",
	"calculate_overtime_pay",
	"import_attendance",
	"create_shift_pattern",
	"assign_shift",
	"get_roster",
	# constants
	"_KE_ANNUAL_DAYS_PER_YEAR",
	"_KE_ANNUAL_ACCRUAL_RATE",
	"_KE_SICK_DAYS_PER_YEAR",
	"_KE_SICK_ACCRUAL_RATE",
	"_KE_MATERNITY_DAYS",
	"_KE_PATERNITY_DAYS",
	"_KE_ANNUAL_MAX_CARRY",
	"_OT_WEEKDAY_RATE",
	"_OT_WEEKEND_RATE",
	"_OT_PUBLIC_HOLIDAY_RATE",
]
