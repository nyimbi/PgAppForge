"""
pgappforge/plugins/erp/hcm/time/events.py

Domain events for the HCM Time & Attendance plugin.

Events emitted:
  hcm.time.attendance.clocked_in
  hcm.time.attendance.clocked_out
  hcm.time.leave_request.submitted
  hcm.time.leave_request.approved
  hcm.time.leave_request.rejected
  hcm.time.leave_request.cancelled
  hcm.time.timesheet.submitted
  hcm.time.timesheet.approved
  hcm.time.timesheet.rejected

Events consumed:
  hcm.personnel.employee.hired       — initialise leave balance for new hire
  hcm.personnel.employee.terminated  — cancel pending leave requests
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Attendance events
# ---------------------------------------------------------------------------

@dataclass
class ClockedInEvent(DomainEvent):
	"""Emitted when an employee clocks in."""
	event_type: str = "hcm.time.attendance.clocked_in"
	attendance_id: str = ""
	employee_id: str = ""
	attendance_date: str = ""  # ISO date
	clock_in: str = ""         # ISO datetime (UTC)
	location_method: str = ""  # GPS | KIOSK | MANUAL


@dataclass
class ClockedOutEvent(DomainEvent):
	"""Emitted when an employee clocks out."""
	event_type: str = "hcm.time.attendance.clocked_out"
	attendance_id: str = ""
	employee_id: str = ""
	attendance_date: str = ""
	clock_out: str = ""         # ISO datetime (UTC)
	regular_hours: str = ""     # Decimal string — no float
	overtime_hours: str = ""    # Decimal string — no float


# ---------------------------------------------------------------------------
# Leave request events
# ---------------------------------------------------------------------------

@dataclass
class LeaveRequestSubmittedEvent(DomainEvent):
	"""Emitted when an employee submits a leave request."""
	event_type: str = "hcm.time.leave_request.submitted"
	leave_request_id: str = ""
	employee_id: str = ""
	leave_type: str = ""
	start_date: str = ""   # ISO date
	end_date: str = ""     # ISO date
	days_requested: str = ""  # Decimal string


@dataclass
class LeaveRequestApprovedEvent(DomainEvent):
	"""Emitted when a manager approves a leave request."""
	event_type: str = "hcm.time.leave_request.approved"
	leave_request_id: str = ""
	employee_id: str = ""
	leave_type: str = ""
	approver_id: str = ""
	days_approved: str = ""  # Decimal string


@dataclass
class LeaveRequestRejectedEvent(DomainEvent):
	"""Emitted when a manager rejects a leave request."""
	event_type: str = "hcm.time.leave_request.rejected"
	leave_request_id: str = ""
	employee_id: str = ""
	leave_type: str = ""
	approver_id: str = ""
	reason: str = ""


@dataclass
class LeaveRequestCancelledEvent(DomainEvent):
	"""Emitted when a leave request is cancelled."""
	event_type: str = "hcm.time.leave_request.cancelled"
	leave_request_id: str = ""
	employee_id: str = ""
	leave_type: str = ""
	days_returned: str = ""  # Decimal string — returned to balance


# ---------------------------------------------------------------------------
# Timesheet events
# ---------------------------------------------------------------------------

@dataclass
class TimesheetSubmittedEvent(DomainEvent):
	"""Emitted when a timesheet is submitted for approval."""
	event_type: str = "hcm.time.timesheet.submitted"
	timesheet_id: str = ""
	employee_id: str = ""
	week_start: str = ""           # ISO date (Monday)
	total_regular_hours: str = ""  # Decimal string
	total_overtime_hours: str = "" # Decimal string


@dataclass
class TimesheetApprovedEvent(DomainEvent):
	"""Emitted when a timesheet is approved.

	Downstream payroll plugin consumes this to compute hourly pay.
	"""
	event_type: str = "hcm.time.timesheet.approved"
	timesheet_id: str = ""
	employee_id: str = ""
	week_start: str = ""
	approved_by: str = ""
	total_regular_hours: str = ""
	total_overtime_hours: str = ""


@dataclass
class TimesheetRejectedEvent(DomainEvent):
	"""Emitted when a timesheet is rejected."""
	event_type: str = "hcm.time.timesheet.rejected"
	timesheet_id: str = ""
	employee_id: str = ""
	week_start: str = ""
	rejected_by: str = ""


# ---------------------------------------------------------------------------
# Leave accrual events  [CRITICAL gap-fill]
# ---------------------------------------------------------------------------

@dataclass
class LeaveAccruedEvent(DomainEvent):
	"""Emitted after monthly leave accrual for an employee."""
	event_type: str = "hcm.time.leave.accrued"
	employee_id: str = ""
	leave_type: str = ""
	accrual_month: str = ""   # ISO date — first of month
	days_accrued: str = ""    # Decimal string
	balance_after: str = ""   # Decimal string


@dataclass
class LeaveCarryForwardEvent(DomainEvent):
	"""Emitted when year-end carry-forward is processed for an employee."""
	event_type: str = "hcm.time.leave.carry_forward"
	employee_id: str = ""
	old_year: int = 0
	new_year: int = 0
	days_carried: str = ""    # Decimal string
	days_forfeited: str = ""  # Decimal string


# ---------------------------------------------------------------------------
# Overtime events  [CRITICAL gap-fill]
# ---------------------------------------------------------------------------

@dataclass
class OvertimeCalculatedEvent(DomainEvent):
	"""Emitted when an OvertimeRecord is created from an AttendanceRecord."""
	event_type: str = "hcm.time.overtime.calculated"
	overtime_record_id: str = ""
	employee_id: str = ""
	work_date: str = ""         # ISO date
	overtime_type: str = ""     # WEEKDAY | WEEKEND | PUBLIC_HOLIDAY
	overtime_hours: str = ""    # hours as decimal string (hundredths / 100)
	rate_multiplier: str = ""   # e.g. "1.50"


@dataclass
class OvertimePayComputedEvent(DomainEvent):
	"""Emitted when overtime pay is computed for a record."""
	event_type: str = "hcm.time.overtime.pay_computed"
	overtime_record_id: str = ""
	employee_id: str = ""
	work_date: str = ""
	pay_cents: int = 0


# ---------------------------------------------------------------------------
# Biometric import events  [HIGH gap-fill]
# ---------------------------------------------------------------------------

@dataclass
class BiometricImportCompleteEvent(DomainEvent):
	"""Emitted after a batch biometric attendance import."""
	event_type: str = "hcm.time.biometric.import_complete"
	imported: int = 0
	anomalies: int = 0
	errors: int = 0


# ---------------------------------------------------------------------------
# Shift management events  [HIGH gap-fill]
# ---------------------------------------------------------------------------

@dataclass
class ShiftPatternCreatedEvent(DomainEvent):
	"""Emitted when a new ShiftPattern is created."""
	event_type: str = "hcm.time.shift.pattern_created"
	shift_pattern_id: str = ""
	name: str = ""
	tenant_id: str = ""


@dataclass
class EmployeeShiftAssignedEvent(DomainEvent):
	"""Emitted when an employee is assigned to a shift pattern."""
	event_type: str = "hcm.time.shift.employee_assigned"
	assignment_id: str = ""
	employee_id: str = ""
	shift_pattern_id: str = ""
	effective_from: str = ""   # ISO date
	effective_to: str = ""     # ISO date or ""


__all__ = [
	"ClockedInEvent",
	"ClockedOutEvent",
	"LeaveRequestSubmittedEvent",
	"LeaveRequestApprovedEvent",
	"LeaveRequestRejectedEvent",
	"LeaveRequestCancelledEvent",
	"TimesheetSubmittedEvent",
	"TimesheetApprovedEvent",
	"TimesheetRejectedEvent",
	# new gap-fill events
	"LeaveAccruedEvent",
	"LeaveCarryForwardEvent",
	"OvertimeCalculatedEvent",
	"OvertimePayComputedEvent",
	"BiometricImportCompleteEvent",
	"ShiftPatternCreatedEvent",
	"EmployeeShiftAssignedEvent",
]
