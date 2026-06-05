"""
pgappforge/plugins/erp/hcm/time/models.py

SQLAlchemy models for the HCM Time & Attendance plugin.

Design invariants:
  - ALL PKs: UUID v4 string
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - Hours: NUMERIC(5,2) or NUMERIC(6,2) — stored as Numeric, NOT cents
    (hours are not monetary; use Decimal arithmetic throughout)
  - Money / pay amounts: INTEGER CENTS (multiplier * hours * rate)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - LeaveBalance: recomputed nightly + on every leave action; remaining = accrued - taken - pending
  - lazy='select' throughout

Table prefix: hcm_time_

New models (CRITICAL/HIGH gap-fill):
  PublicHoliday        — Kenya public holiday calendar
  LeaveAccrual         — monthly accrual ledger rows
  OvertimeRecord       — overtime calculation & pay
  BiometricAttendance  — raw biometric/RFID event staging
  ShiftPattern         — named shift template (replaces ShiftDefinition for roster use)
  EmployeeShift        — employee-to-shift assignment
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	Time,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ShiftDefinition
# ---------------------------------------------------------------------------

class ShiftDefinition(AuditMixin, Model):
	"""Named shift template defining working hours and eligible days.

	days_of_week: PostgreSQL integer array [0..6] where 0=Monday, 6=Sunday.
	is_overnight: True when end_time < start_time (spans midnight).
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_shift_definition"
	__table_args__ = (
		Index("ix_hcm_shift_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "shift_code", name="uq_hcm_shift_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	shift_code = Column(String(20), nullable=False)
	name = Column(String(100), nullable=False)
	start_time = Column(Time, nullable=False, comment="Shift start time (local tz — application applies offset)")
	end_time = Column(Time, nullable=False, comment="Shift end time")
	break_minutes = Column(Integer, nullable=False, default=0, comment="Total unpaid break duration in minutes")
	is_overnight = Column(Boolean, nullable=False, default=False, comment="True when shift spans midnight")
	days_of_week = Column(ARRAY(Integer), nullable=False, default=list, comment="[0=Mon..6=Sun] applicable weekdays")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<ShiftDefinition {self.shift_code!r} {self.start_time}-{self.end_time}>"


# ---------------------------------------------------------------------------
# AttendanceRecord
# ---------------------------------------------------------------------------

class AttendanceRecord(AuditMixin, Model):
	"""Daily attendance record per employee.

	clock_in / clock_out are TIMESTAMPTZ — store in UTC, display in local tz.
	regular_hours and overtime_hours are computed by the service layer from
	clock_in/clock_out vs. the scheduled shift.
	location: {lat, lng, address, method} for geo-fenced clock-in.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_attendance_record"
	__table_args__ = (
		Index("ix_hcm_att_employee", "employee_id"),
		Index("ix_hcm_att_date", "attendance_date"),
		Index("ix_hcm_att_tenant", "tenant_id"),
		UniqueConstraint("employee_id", "attendance_date", name="uq_hcm_att_emp_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	attendance_date = Column(Date, nullable=False)
	clock_in = Column(DateTime(timezone=True), nullable=True)
	clock_out = Column(DateTime(timezone=True), nullable=True)
	scheduled_hours = Column(Numeric(5, 2), nullable=True, comment="Expected hours from shift definition")
	regular_hours = Column(Numeric(5, 2), nullable=True, comment="Standard hours worked at regular rate")
	overtime_hours = Column(Numeric(5, 2), nullable=False, default=0)
	status = Column(
		String(20),
		nullable=False,
		default="PRESENT",
		comment="PRESENT | ABSENT | LATE | HALF_DAY",
	)
	location = Column(JSONB, nullable=False, default=dict, comment="{lat, lng, address, method}")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<AttendanceRecord emp={self.employee_id!r} date={self.attendance_date} status={self.status!r}>"


# ---------------------------------------------------------------------------
# LeavePolicy
# ---------------------------------------------------------------------------

class LeavePolicy(AuditMixin, Model):
	"""Leave entitlement rules per legal entity and leave type."""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_leave_policy"
	__table_args__ = (
		Index("ix_hcm_lp_entity", "entity_id"),
		Index("ix_hcm_lp_tenant", "tenant_id"),
		UniqueConstraint("entity_id", "leave_type", name="uq_hcm_lp_entity_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_legal_entity.id"), nullable=False, index=True)
	leave_type = Column(
		String(50),
		nullable=False,
		comment="ANNUAL | SICK | MATERNITY | PATERNITY | BEREAVEMENT | OTHER",
	)
	days_per_year = Column(Numeric(6, 2), nullable=False)
	accrual_frequency = Column(
		String(20),
		nullable=False,
		comment="MONTHLY | UPFRONT",
	)
	carry_over_max = Column(Numeric(6, 2), nullable=False, default=0, comment="0 = no carry-over")
	requires_approval = Column(Boolean, nullable=False, default=True)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<LeavePolicy entity={self.entity_id!r} type={self.leave_type!r} days={self.days_per_year}>"


# ---------------------------------------------------------------------------
# LeaveBalance
# ---------------------------------------------------------------------------

class LeaveBalance(AuditMixin, Model):
	"""Running leave balance per employee per year.

	remaining = accrued + carried_over - taken - pending
	Recomputed nightly and on every leave action by TimeService.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_leave_balance"
	__table_args__ = (
		Index("ix_hcm_lb_employee", "employee_id"),
		Index("ix_hcm_lb_tenant", "tenant_id"),
		UniqueConstraint("employee_id", "leave_type", "balance_year", name="uq_hcm_lb_emp_type_year"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	leave_type = Column(String(50), nullable=False)
	balance_year = Column(Integer, nullable=False)
	accrued = Column(Numeric(6, 2), nullable=False, default=0)
	taken = Column(Numeric(6, 2), nullable=False, default=0)
	pending = Column(Numeric(6, 2), nullable=False, default=0, comment="Days in PENDING or APPROVED requests not yet taken")
	remaining = Column(Numeric(6, 2), nullable=False, default=0, comment="accrued - taken - pending")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<LeaveBalance emp={self.employee_id!r} type={self.leave_type!r} year={self.balance_year} rem={self.remaining}>"


# ---------------------------------------------------------------------------
# LeaveRequest
# ---------------------------------------------------------------------------

class LeaveRequest(AuditMixin, Model):
	"""Employee leave application.

	days_requested is computed by TimeService from start_date/end_date,
	excluding weekends and public holidays.
	Status machine: PENDING → APPROVED | REJECTED | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_leave_request"
	__table_args__ = (
		Index("ix_hcm_lr_employee", "employee_id"),
		Index("ix_hcm_lr_approver", "approver_id"),
		Index("ix_hcm_lr_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	leave_type = Column(String(50), nullable=False)
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False, comment="Last day of leave (inclusive)")
	days_requested = Column(Numeric(6, 2), nullable=False, comment="Working days; computed by service excluding weekends/holidays")
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | APPROVED | REJECTED | CANCELLED",
	)
	approver_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to hcm_per_employee.id — manager who actioned this")
	actioned_at = Column(DateTime(timezone=True), nullable=True)
	reason = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<LeaveRequest emp={self.employee_id!r} type={self.leave_type!r} {self.start_date}→{self.end_date} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Timesheet
# ---------------------------------------------------------------------------

class Timesheet(AuditMixin, Model):
	"""Weekly timesheet header per employee.

	Status machine: DRAFT → SUBMITTED → APPROVED | REJECTED
	Approved hours feed payrun processing for hourly employees.
	week_start must always be a Monday (ISO week start).
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_timesheet"
	__table_args__ = (
		Index("ix_hcm_ts_employee", "employee_id"),
		Index("ix_hcm_ts_week_start", "week_start"),
		Index("ix_hcm_ts_tenant_status", "tenant_id", "status"),
		UniqueConstraint("employee_id", "week_start", name="uq_hcm_ts_emp_week"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	week_start = Column(Date, nullable=False, index=True, comment="Monday date of the ISO week")
	total_regular_hours = Column(Numeric(6, 2), nullable=False, default=0)
	total_overtime_hours = Column(Numeric(6, 2), nullable=False, default=0)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | APPROVED | REJECTED",
	)
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to hcm_per_employee.id — approving manager")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	entries: list[TimeEntry] = relationship(
		"TimeEntry",
		back_populates="timesheet",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Timesheet emp={self.employee_id!r} week={self.week_start} status={self.status!r}>"


# ---------------------------------------------------------------------------
# TimeEntry
# ---------------------------------------------------------------------------

class TimeEntry(AuditMixin, Model):
	"""Daily time entry within a timesheet.

	project_code and cost_center enable project-based cost allocation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_entry"
	__table_args__ = (
		Index("ix_hcm_te_timesheet", "timesheet_id"),
		Index("ix_hcm_te_tenant", "tenant_id"),
		Index("ix_hcm_te_project", "project_code"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	timesheet_id = Column(UUID(as_uuid=False), ForeignKey("hcm_time_timesheet.id", ondelete="CASCADE"), nullable=False, index=True)
	entry_date = Column(Date, nullable=False)
	project_code = Column(String(50), nullable=True)
	cost_center = Column(String(20), nullable=True)
	regular_hours = Column(Numeric(5, 2), nullable=False, default=0)
	overtime_hours = Column(Numeric(5, 2), nullable=False, default=0)
	description = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	timesheet: Timesheet = relationship("Timesheet", back_populates="entries", lazy="select")

	def __repr__(self) -> str:
		return f"<TimeEntry ts={self.timesheet_id!r} date={self.entry_date} reg={self.regular_hours}h ot={self.overtime_hours}h>"


# ---------------------------------------------------------------------------
# PublicHoliday  [CRITICAL gap-fill: Kenya public holiday calendar]
# ---------------------------------------------------------------------------

class PublicHoliday(AuditMixin, Model):
	"""Public holiday calendar entry.

	Seeded for Kenya (country_code='KE') via
	TimeService.seed_kenya_public_holidays(session, year).
	is_statutory=True means it is a statutory/gazetted holiday.
	Floating holidays (Good Friday, Easter Monday) are computed and seeded
	per-year by the service layer.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_public_holiday"
	__table_args__ = (
		Index("ix_hcm_ph_date_country", "holiday_date", "country_code"),
		Index("ix_hcm_ph_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "country_code", "holiday_date", name="uq_hcm_ph_tenant_country_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True, default="00000000-0000-0000-0000-000000000000")
	country_code = Column(String(2), nullable=False, default="KE", comment="ISO 3166-1 alpha-2")
	holiday_date = Column(Date, nullable=False)
	name = Column(String(100), nullable=False)
	is_statutory = Column(Boolean, nullable=False, default=True, comment="True = gazetted statutory holiday")
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<PublicHoliday {self.country_code} {self.holiday_date} {self.name!r}>"


# ---------------------------------------------------------------------------
# LeaveAccrual  [CRITICAL gap-fill: monthly accrual ledger]
# ---------------------------------------------------------------------------

class LeaveAccrual(AuditMixin, Model):
	"""Immutable ledger row written each time a leave balance is accrued.

	accrual_month is the first day of the month being accrued (e.g. 2026-06-01).
	balance_before / balance_after are snapshotted at accrual time for auditability.
	days_accrued may be negative for forfeiture rows (reason='forfeiture').
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_leave_accrual"
	__table_args__ = (
		Index("ix_hcm_la_employee", "employee_id"),
		Index("ix_hcm_la_tenant", "tenant_id"),
		Index("ix_hcm_la_month", "accrual_month"),
		UniqueConstraint(
			"employee_id", "leave_type", "accrual_month", "reason",
			name="uq_hcm_la_emp_type_month_reason",
		),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	leave_type = Column(String(50), nullable=False, comment="ANNUAL | SICK | MATERNITY | PATERNITY | …")
	accrual_month = Column(Date, nullable=False, comment="First day of the accrual month, e.g. 2026-06-01")
	days_accrued = Column(Numeric(6, 2), nullable=False, comment="Positive=credit, negative=forfeiture")
	balance_before = Column(Numeric(6, 2), nullable=False, default=0)
	balance_after = Column(Numeric(6, 2), nullable=False, default=0)
	reason = Column(String(50), nullable=False, default="monthly_accrual", comment="monthly_accrual | hire_grant | forfeiture | carry_forward | adjustment")
	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<LeaveAccrual emp={self.employee_id!r} type={self.leave_type!r} month={self.accrual_month} days={self.days_accrued}>"


# ---------------------------------------------------------------------------
# OvertimeRecord  [CRITICAL gap-fill: Kenya Employment Act overtime]
# ---------------------------------------------------------------------------

class OvertimeRecord(AuditMixin, Model):
	"""Overtime calculation record per employee per work date.

	Hours are stored as INTEGER HUNDREDTHS (1 hour = 100) to avoid
	floating-point drift — consistent with the INTEGER CENTS money convention.
	rate_multiplier is Numeric(4,2): 1.50 for weekday/weekend, 2.00 for public holiday.
	pay_cents is computed: overtime_hours_hundredths / 100 * hourly_rate_cents * rate_multiplier
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_overtime_record"
	__table_args__ = (
		Index("ix_hcm_ot_employee", "employee_id"),
		Index("ix_hcm_ot_date", "work_date"),
		Index("ix_hcm_ot_tenant", "tenant_id"),
		UniqueConstraint("employee_id", "work_date", name="uq_hcm_ot_emp_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	attendance_record_id = Column(UUID(as_uuid=False), ForeignKey("hcm_time_attendance_record.id"), nullable=True, index=True)
	work_date = Column(Date, nullable=False)
	regular_hours_hundredths = Column(Integer, nullable=False, default=0, comment="Regular hours * 100 (e.g. 800 = 8.00 h)")
	overtime_hours_hundredths = Column(Integer, nullable=False, default=0, comment="Overtime hours * 100")
	overtime_type = Column(
		String(20), nullable=False, default="WEEKDAY",
		comment="WEEKDAY | WEEKEND | PUBLIC_HOLIDAY",
	)
	rate_multiplier = Column(Numeric(4, 2), nullable=False, default="1.50", comment="1.50 for weekday/weekend OT, 2.00 for PH")
	pay_cents = Column(Integer, nullable=True, comment="Computed overtime pay in currency subunits (cents)")
	is_approved = Column(Boolean, nullable=False, default=False)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<OvertimeRecord emp={self.employee_id!r} date={self.work_date} "
			f"type={self.overtime_type!r} ot_h={self.overtime_hours_hundredths/100:.2f}>"
		)


# ---------------------------------------------------------------------------
# BiometricAttendance  [HIGH gap-fill: biometric/RFID import staging]
# ---------------------------------------------------------------------------

class BiometricAttendance(AuditMixin, Model):
	"""Staging table for raw biometric clock events.

	source: BIOMETRIC (hardware device), MANUAL (web/mobile), SYSTEM (auto).
	duration_minutes is computed by the service layer on import; NULL if
	clock_out is absent or the record is anomalous.
	is_anomaly is flagged when duration > 720 min (12 h) or clock_out missing.
	anomaly_reason captures a machine-readable tag for HR triage.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_biometric_attendance"
	__table_args__ = (
		Index("ix_hcm_bio_employee", "employee_id"),
		Index("ix_hcm_bio_tenant", "tenant_id"),
		Index("ix_hcm_bio_device", "device_id"),
		Index("ix_hcm_bio_anomaly", "is_anomaly"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	clock_in = Column(DateTime(timezone=True), nullable=False, comment="TIMESTAMPTZ — store in UTC")
	clock_out = Column(DateTime(timezone=True), nullable=True, comment="NULL if employee has not clocked out yet")
	source = Column(
		String(20), nullable=False, default="BIOMETRIC",
		comment="BIOMETRIC | MANUAL | SYSTEM",
	)
	device_id = Column(String(100), nullable=True, comment="Hardware device identifier (ZKTeco serial, etc.)")
	duration_minutes = Column(Integer, nullable=True, comment="Computed: (clock_out - clock_in) in whole minutes")
	is_anomaly = Column(Boolean, nullable=False, default=False)
	anomaly_reason = Column(String(100), nullable=True, comment="MISSING_CLOCK_OUT | DURATION_EXCEEDED | DUPLICATE")
	linked_attendance_id = Column(
		UUID(as_uuid=False),
		ForeignKey("hcm_time_attendance_record.id"),
		nullable=True,
		index=True,
		comment="Set after the staging record is reconciled into AttendanceRecord",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<BiometricAttendance emp={self.employee_id!r} in={self.clock_in} "
			f"anomaly={self.is_anomaly}>"
		)


# ---------------------------------------------------------------------------
# ShiftPattern  [HIGH gap-fill: roster management]
# ---------------------------------------------------------------------------

class ShiftPattern(AuditMixin, Model):
	"""Named shift pattern for roster assignment.

	days_of_week: PostgreSQL integer array [0..6] where 0=Monday, 6=Sunday.
	Complements ShiftDefinition (which tracks break_minutes, is_overnight,
	shift_code); ShiftPattern is the roster-facing template.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_shift_pattern"
	__table_args__ = (
		Index("ix_hcm_sp_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "name", name="uq_hcm_sp_tenant_name"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	start_time = Column(Time, nullable=False)
	end_time = Column(Time, nullable=False)
	days_of_week = Column(ARRAY(Integer), nullable=False, default=list, comment="[0=Mon..6=Sun] applicable weekdays")
	break_minutes = Column(Integer, nullable=False, default=0)
	is_overnight = Column(Boolean, nullable=False, default=False)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	assignments: list[EmployeeShift] = relationship(
		"EmployeeShift",
		back_populates="shift_pattern",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ShiftPattern {self.name!r} {self.start_time}-{self.end_time}>"


# ---------------------------------------------------------------------------
# EmployeeShift  [HIGH gap-fill: roster management]
# ---------------------------------------------------------------------------

class EmployeeShift(AuditMixin, Model):
	"""Assignment of an employee to a ShiftPattern for a date range.

	effective_to=NULL means the assignment is open-ended (current).
	Only one active assignment per employee at any time is enforced by
	the service layer (overlapping intervals are rejected).
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_time_employee_shift"
	__table_args__ = (
		Index("ix_hcm_es_employee", "employee_id"),
		Index("ix_hcm_es_pattern", "shift_pattern_id"),
		Index("ix_hcm_es_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	shift_pattern_id = Column(UUID(as_uuid=False), ForeignKey("hcm_time_shift_pattern.id"), nullable=False, index=True)
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True, comment="NULL = open-ended / current assignment")
	department_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="Optional — for roster dept filtering")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	shift_pattern: ShiftPattern = relationship("ShiftPattern", back_populates="assignments", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<EmployeeShift emp={self.employee_id!r} "
			f"pattern={self.shift_pattern_id!r} "
			f"{self.effective_from}→{self.effective_to or 'now'}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ShiftDefinition",
	"AttendanceRecord",
	"LeavePolicy",
	"LeaveBalance",
	"LeaveRequest",
	"Timesheet",
	"TimeEntry",
	# new gap-fill models
	"PublicHoliday",
	"LeaveAccrual",
	"OvertimeRecord",
	"BiometricAttendance",
	"ShiftPattern",
	"EmployeeShift",
]
