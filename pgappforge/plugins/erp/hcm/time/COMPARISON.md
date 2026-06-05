# time — World-Class HCM Comparison
Score: 34/100

## Current Capabilities

- `ShiftDefinition` model with shift name, start/end times
- `AttendanceRecord` with clock-in/clock-out, hours worked, status
- `LeavePolicy` model (leave type, days entitlement, carry-forward flag)
- `LeaveBalance` tracking per employee per leave type per year
- `LeaveRequest` with submit/approve/reject/cancel workflow
- `Timesheet` + `TimeEntry` with submit/approve/reject workflow
- `recompute_leave_balance` — recalculates balance from approved requests
- `working_days(start, end)` helper (simple calendar day diff, no holiday awareness)
- Stateless `TimeService` with explicit session injection
- Decimal arithmetic for hours (not float)
- Basic audit trail via `AuditMixin`

---

## Gaps

### [CRITICAL] No leave accrual engine
**Missing:** Monthly accrual computation that credits leave balances on a schedule (e.g., annual leave at 1.75 days/month, sick at 0.83/month).
**Impl:** Add an `AccrualPolicy` model with `accrual_rate`, `accrual_frequency` (monthly/bi-weekly), `max_balance`, and `proration_rule`. `TimeService.run_monthly_accrual(year, month, session)` iterates active employees, computes pro-rated credit based on hire date and hours worked in period, appends an `AccrualLedger` row, and updates `LeaveBalance`. Trigger via APScheduler or Celery beat on the 1st of each month.
**Found in:** SAP SuccessFactors (Time Off Accrual Profiles), Workday (Accrual Frequency Plans), Oracle HCM (Accrual Plan rules)

### [CRITICAL] Kenya Employment Act entitlements not enforced
**Missing:** Statutory minimums — 21 days annual leave, 90 days maternity leave, 14 days paternity leave — are not modelled or validated.
**Impl:** Add a `KenyaStatutoryEntitlement` enum/constant file. In `LeavePolicy.validate()` (Pydantic `AfterValidator`), assert that annual leave entitlement >= 21 and maternity >= 90 and paternity >= 14 for `country='KE'`. Add a migration that back-fills existing policies with statutory floor values on first run.
**Found in:** Sage HR (Kenya localisation), ADP Workforce Now (country compliance packs), Oracle HCM Cloud (Statutory Leave)

### [CRITICAL] No Kenya public holiday calendar
**Missing:** `working_days()` ignores public holidays, making leave day counts incorrect for statutory compliance.
**Impl:** Add a `PublicHoliday` model (`date`, `name`, `country`, `company_id`, `is_active`). Seed a migration with all Kenya public holidays (New Year, Good Friday, Easter Monday, Labour Day 1 May, Madaraka Day 1 Jun, Utamaduni Day 10 Oct, Mashujaa Day 20 Oct, Jamhuri Day 12 Dec, Christmas, Boxing Day) plus the floating holidays (Idd ul Fitr, Idd ul Adha — computed from Islamic calendar). Rewrite `working_days()` to query this table and exclude matches.
**Found in:** SAP SuccessFactors (Holiday Calendars), Workday (Holiday Calendars), BambooHR (country packs)

### [CRITICAL] No overtime calculation
**Missing:** No overtime detection or premium pay computation (1.5x for weekday hours >8, 2x for public holidays per Kenya Employment Act s.27).
**Impl:** Add `OvertimeRule` model with `threshold_hours`, `weekday_multiplier` (1.5), `holiday_multiplier` (2.0), `rest_day_multiplier` (2.0). In `TimeService.clock_out()`, after computing `hours_worked`, call `_compute_overtime(record, session)` which queries the holiday calendar and shift schedule to split regular vs. overtime hours, persisting them in `AttendanceRecord.regular_hours` and `AttendanceRecord.overtime_hours`. Expose a `get_overtime_summary(employee_id, period, session)` for payroll integration.
**Found in:** SAP SuccessFactors, Workday, ADP Workforce Now, Oracle HCM Cloud

### [CRITICAL] Leave balance carry-forward rules absent
**Missing:** `LeavePolicy.carry_forward` is a boolean flag only — no maximum carry-forward cap, no auto-forfeiture date, no lapse-to-cash-out option.
**Impl:** Extend `LeavePolicy` with `max_carry_days: Decimal`, `forfeiture_date: date | None` (e.g., 31 March of following year), `lapse_policy: Literal['forfeit', 'pay_out', 'carry']`. Add `TimeService.process_year_end_carry(year, session)` that iterates all balances, applies caps, records forfeiture as a negative `AccrualLedger` row with reason `'forfeiture'`, or queues a payroll journal for lapsed-to-cash days.
**Found in:** Workday (Accrual Limits), SAP SuccessFactors (Carry-Forward Rules), Oracle HCM (Ceiling and Forfeiture)

### [HIGH] No biometric / RFID attendance import
**Missing:** No mechanism to ingest raw attendance events from time-clock hardware (ZKTeco, Anviz, etc.) common in Kenyan enterprises.
**Impl:** Add a `RawAttendanceEvent` staging model (`device_id`, `employee_biometric_id`, `event_time`, `event_type` [IN/OUT/BREAK], `raw_payload: JSONB`, `processed: bool`). Add `TimeService.process_raw_events(session)` that maps `employee_biometric_id` → `employee_id` via an `EmployeeBiometricMapping` table, deduplicates within a 5-minute window, and calls `clock_in`/`clock_out` accordingly. Expose a POST endpoint `/api/time/raw-events` for device push and a CSV import path for bulk upload.
**Found in:** SAP SuccessFactors (Time Collector), Oracle HCM (Time Device), ADP (Timeclocks integration)

### [HIGH] No compensatory time-off (CTO) management
**Missing:** When overtime is worked, no mechanism to grant equivalent compensatory leave instead of cash payment.
**Impl:** Add `CompensatoryLeaveCredit` model (`employee_id`, `source_attendance_record_id`, `hours_credited`, `expires_on`, `status`). In `_compute_overtime()`, if the employee's contract or shift rule has `overtime_treatment='CTO'`, create a `CompensatoryLeaveCredit` instead of flagging paid overtime. Add `TimeService.expire_cto_credits(session)` for credits past their `expires_on` date. CTO credits should feed into the employee's `LeaveBalance` for the CTO leave type.
**Found in:** SAP SuccessFactors (Time Off in Lieu), Workday (Compensatory Time Plan), Oracle HCM (Comp Time)

### [HIGH] No roster / schedule management
**Missing:** `ShiftDefinition` defines a single shift pattern but there is no employee-to-shift assignment, rotation schedule, or roster publication workflow.
**Impl:** Add `ShiftAssignment` model (`employee_id`, `shift_id`, `effective_from`, `effective_to`, `rotation_type` [fixed/rotating]). Add `Roster` model (`department_id`, `period_start`, `period_end`, `published_at`) with child `RosterEntry` rows. `TimeService.get_expected_shift(employee_id, date, session)` resolves the active assignment and returns the expected `ShiftDefinition`. This feeds attendance deviation detection (late arrival, early departure, absent).
**Found in:** SAP SuccessFactors (Work Schedule), Workday (Schedule Patterns), Oracle HCM (Work Patterns)

### [HIGH] No absence management / disciplinary trigger
**Missing:** Unapproved absences are not detected, not tracked, and cannot trigger disciplinary workflows.
**Impl:** Add `AbsenceRecord` model (`employee_id`, `absence_date`, `absence_type` [AWOL/late/early_departure], `minutes`, `notified_at`, `disciplinary_case_id`). Add `TimeService.detect_absences(date, session)` — for each employee with a scheduled shift that day, cross-check `AttendanceRecord`; if no clock-in by `shift_start + grace_period`, create an `AbsenceRecord` with type `AWOL`. Emit a domain event `employee.absence.detected` that the disciplinary module can subscribe to.
**Found in:** SAP SuccessFactors, Workday (Absence Management), Oracle HCM (Absence Management), ADP

### [HIGH] No flexi-time / remote work tracking
**Missing:** No model distinguishes remote vs. office attendance or supports flexible start/end windows.
**Impl:** Extend `AttendanceRecord` with `work_location: Literal['office', 'remote', 'field', 'travel']` and `location_verified: bool`. Add `FlexiTimePolicy` model (`core_hours_start`, `core_hours_end`, `daily_target_hours`, `weekly_target_hours`). In `clock_in()`, record `work_location` from request payload; in `clock_out()`, validate against `FlexiTimePolicy.daily_target_hours` rather than fixed shift boundaries. Add GPS coordinate fields (`lat`, `lon`) for geo-fenced office detection (relevant for Nairobi CBD companies).
**Found in:** Workday (Flexible Work Arrangements), SAP SuccessFactors (Flexible Working), BambooHR (Remote Work)

### [HIGH] No leave encashment / payout on separation
**Missing:** When an employee is terminated, unused leave balance is not automatically computed for cash payout per Kenya Employment Act.
**Impl:** Add `TimeService.compute_separation_leave_payout(employee_id, termination_date, session) -> Decimal` that fetches `LeaveBalance` for annual leave, pro-rates any partial-year accrual up to `termination_date`, deducts approved leave taken in the year, and returns outstanding days. The result feeds the Payroll module's final settlement computation. Store the computation snapshot in a `SeparationLeaveSnapshot` model for audit.
**Found in:** SAP SuccessFactors (Termination Payouts), Oracle HCM (Final Pay), ADP Workforce Now

### [MEDIUM] `working_days()` ignores weekends
**Missing:** Current implementation appears to be a naive calendar-day diff with no weekend or weekend-pattern awareness.
**Impl:** Rewrite to use `numpy.busday_count` or a pure-Python equivalent that iterates the date range, checks `date.weekday() < 5`, then subtracts `PublicHoliday` matches for the given `country`/`company`. Accept an optional `work_schedule` parameter for non-standard weeks (e.g., Sunday–Thursday for some Kenyan industries).
**Found in:** All benchmark systems handle non-standard work weeks

### [MEDIUM] No timesheet approval delegation / escalation
**Missing:** Timesheet approval is single-level with no timeout escalation or delegation chain.
**Impl:** Add `TimesheetApprovalConfig` model (`escalation_days`, `delegate_approver_id`, `escalation_approver_id`). In `submit_timesheet()`, record `pending_since`. Add `TimeService.escalate_stale_timesheets(session)` scheduled daily — any timesheet pending > `escalation_days` is re-assigned to `escalation_approver_id` and the original approver is notified. Mirror the same pattern for `LeaveRequest`.
**Found in:** SAP SuccessFactors, Workday (Delegation), Oracle HCM (Approval Hierarchy)

### [MEDIUM] No partial-day leave support
**Missing:** Leave requests are in whole-day units only; half-day or hourly leave cannot be expressed.
**Impl:** Add `leave_unit: Literal['full_day', 'half_day_am', 'half_day_pm', 'hours']` to `LeaveRequest`. Add `requested_hours: Decimal | None`. Update `recompute_leave_balance()` to convert hours to day-fractions using `LeavePolicy.standard_day_hours` (default 8.0). Kenya Employment Act allows sick leave in partial days for medical appointments.
**Found in:** Workday (Partial Day Leave), SAP SuccessFactors (Part-Day Absence), BambooHR

### [MEDIUM] No leave type linkage to payroll codes
**Missing:** `LeavePolicy` has no payroll code mapping, so approved leave cannot automatically feed payroll with the correct earning/deduction code.
**Impl:** Add `payroll_code: str | None` and `is_paid: bool` (default True) to `LeavePolicy`. When `approve_leave_request()` is called, emit a `leave.approved` domain event carrying `payroll_code`, `days`, `employee_id`, `period`. The Payroll plugin subscribes and inserts the appropriate payroll line. Sick leave beyond the statutory 7 paid days should auto-flip `is_paid=False`.
**Found in:** SAP SuccessFactors, ADP Workforce Now, Oracle HCM

### [MEDIUM] No medical certificate / document attachment on sick leave
**Missing:** Sick leave requests over a threshold (Kenya: >3 days requires medical cert) have no document attachment or verification workflow.
**Impl:** Add `LeaveDocument` model (`leave_request_id`, `document_type: Literal['medical_cert', 'birth_cert', 'other']`, `file_reference`, `verified_by`, `verified_at`). In `approve_leave_request()`, if `leave_type='SICK'` and `requested_days > 3`, require at least one `LeaveDocument` of type `medical_cert` or raise `LeaveServiceError('Medical certificate required')`. Add a `verify_leave_document()` service method for HR officers.
**Found in:** SAP SuccessFactors (Supporting Documents), Workday (Absence Certifications), Oracle HCM

### [MEDIUM] No time-off calendar / team visibility
**Missing:** No aggregated view of who is on leave or out of office across a team for any given date range.
**Impl:** Add `TimeService.get_team_availability(department_id, start_date, end_date, session) -> list[AvailabilitySlot]` that queries `LeaveRequest` (approved) and `AttendanceRecord` (absent) for all employees in the department. Return a sorted list usable as a calendar feed. Expose as a GET endpoint that returns JSON or iCal format for Outlook/Google Calendar integration.
**Found in:** BambooHR (Time-Off Calendar), Workday, SAP SuccessFactors

### [LOW] No NHIF/NSSF statutory leave deduction integration
**Missing:** Absence records are not linked to the statutory deduction adjustment calculations required under Kenyan law (NHIF Act, NSSF Act).
**Impl:** Add `TimeService.get_billable_days(employee_id, month, year, session) -> Decimal` that returns days actually worked (excluding unpaid leave and AWOL days). Payroll uses this to pro-rate NHIF and NSSF contributions for partial-month employees. Store the result in `MonthlyAttendanceSummary` for audit and payroll reconciliation.
**Found in:** Sage HR (Kenya), ADP (Statutory compliance), local Kenyan HRMS vendors

### [LOW] Audit trail insufficient for statutory inspection
**Missing:** `AuditMixin` captures `created_by`/`updated_by` but does not record field-level change history or the reason for changes, which Labour Officer inspections require.
**Impl:** Integrate SQLAlchemy `sqlalchemy-history` or a custom `ChangeLog` model that stores `(table, row_id, field, old_value, new_value, changed_by, changed_at, reason)`. At minimum, enforce this on `LeaveBalance`, `LeaveRequest`, and `AttendanceRecord`. Add an `audit_reason: str | None` parameter to every mutating service method and persist it.
**Found in:** Oracle HCM (Audit Trail), SAP SuccessFactors (Audit Reports), Workday (Audit Logging)
