# HCM Time & Attendance Plugin — SPEC

## Domain
`hcm` | Plugin name: `hcm.time` | Depends on: `foundation`, `hcm.org`, `hcm.personnel`

## Entities

### ShiftDefinition (`hcm_time_shift_definition`)
Named shift template. `days_of_week` is a PostgreSQL integer array (0=Monday, 6=Sunday).

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| shift_code | VARCHAR(20) | Unique per tenant |
| name | VARCHAR(100) | |
| start_time | TIME | Local time — application applies TZ offset |
| end_time | TIME | |
| break_minutes | INTEGER | Unpaid break duration |
| is_overnight | BOOLEAN | True when shift spans midnight |
| days_of_week | INTEGER[] | [0=Mon..6=Sun] |
| created_at / updated_at | TIMESTAMPTZ | |

### AttendanceRecord (`hcm_time_attendance_record`)
Daily attendance per employee. Unique constraint on `(employee_id, attendance_date)`.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| employee_id | UUID FK → hcm_per_employee | |
| attendance_date | DATE NOT NULL | |
| clock_in | TIMESTAMPTZ | UTC |
| clock_out | TIMESTAMPTZ | UTC |
| scheduled_hours | NUMERIC(5,2) | From shift definition |
| regular_hours | NUMERIC(5,2) | Computed from clock_in/clock_out vs scheduled |
| overtime_hours | NUMERIC(5,2) | max(0, total - standard) |
| status | VARCHAR(20) | PRESENT \| ABSENT \| LATE \| HALF_DAY |
| location | JSONB | {lat, lng, address, method: GPS\|KIOSK\|MANUAL} |
| created_at / updated_at | TIMESTAMPTZ | |

### LeavePolicy (`hcm_time_leave_policy`)
Leave entitlement rules per entity + leave type. Unique on `(entity_id, leave_type)`.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| entity_id | UUID FK → hcm_org_legal_entity | |
| leave_type | VARCHAR(50) | ANNUAL \| SICK \| MATERNITY \| PATERNITY \| BEREAVEMENT \| OTHER |
| days_per_year | NUMERIC(6,2) | Total entitlement |
| accrual_frequency | VARCHAR(20) | MONTHLY \| UPFRONT |
| carry_over_max | NUMERIC(6,2) | 0 = no carry-over |
| requires_approval | BOOLEAN | DEFAULT true |
| is_active | BOOLEAN | |
| created_at / updated_at | TIMESTAMPTZ | |

### LeaveBalance (`hcm_time_leave_balance`)
Running balance per employee per year. Unique on `(employee_id, leave_type, balance_year)`.

`remaining = accrued - taken - pending`

Recomputed nightly and on every leave action.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| employee_id | UUID FK → hcm_per_employee | |
| leave_type | VARCHAR(50) | |
| balance_year | INTEGER | Calendar year |
| accrued | NUMERIC(6,2) | Days accrued to date |
| taken | NUMERIC(6,2) | Days of approved+completed leave |
| pending | NUMERIC(6,2) | Days in PENDING/APPROVED not yet taken |
| remaining | NUMERIC(6,2) | accrued - taken - pending |
| created_at / updated_at | TIMESTAMPTZ | |

### LeaveRequest (`hcm_time_leave_request`)
Employee leave application.

Status machine: `PENDING → APPROVED | REJECTED | CANCELLED`

`days_requested` computed by `TimeService.working_days()` excluding weekends. Public holiday exclusion is extension-point (override `working_days`).

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| employee_id | UUID FK → hcm_per_employee | |
| leave_type | VARCHAR(50) | |
| start_date | DATE NOT NULL | |
| end_date | DATE NOT NULL | Inclusive |
| days_requested | NUMERIC(6,2) | Working days (computed) |
| status | VARCHAR(20) | PENDING \| APPROVED \| REJECTED \| CANCELLED |
| approver_id | UUID | FK to hcm_per_employee (manager) |
| actioned_at | TIMESTAMPTZ | |
| reason | TEXT | Employee notes |
| created_at / updated_at | TIMESTAMPTZ | |

### Timesheet (`hcm_time_timesheet`)
Weekly timesheet header. Unique on `(employee_id, week_start)`. `week_start` must be a Monday.

Status machine: `DRAFT → SUBMITTED → APPROVED | REJECTED`

Approved hours feed payrun processing for hourly employees (consumed by payroll plugin).

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| employee_id | UUID FK → hcm_per_employee | |
| week_start | DATE | Monday date of the ISO week |
| total_regular_hours | NUMERIC(6,2) | Sum of entries |
| total_overtime_hours | NUMERIC(6,2) | Sum of entries |
| status | VARCHAR(20) | DRAFT \| SUBMITTED \| APPROVED \| REJECTED |
| approved_by | UUID | FK to hcm_per_employee |
| created_at / updated_at | TIMESTAMPTZ | |

### TimeEntry (`hcm_time_entry`)
Daily time entry within a timesheet.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| timesheet_id | UUID FK → hcm_time_timesheet (CASCADE) | |
| entry_date | DATE NOT NULL | |
| project_code | VARCHAR(50) | For project-based billing |
| cost_center | VARCHAR(20) | Override for cost allocation |
| regular_hours | NUMERIC(5,2) | Standard hours at regular rate |
| overtime_hours | NUMERIC(5,2) | Hours beyond standard daily limit |
| description | TEXT | Free-text work notes |
| created_at / updated_at | TIMESTAMPTZ | |

## Business Rules

1. Cannot clock in twice on the same attendance_date (unique constraint)
2. `clock_out` must be after `clock_in`
3. Leave `start_date` cannot be in the past
4. Leave `end_date >= start_date`
5. Days requested must have sufficient balance (`remaining >= days_requested`)
6. Timesheet `week_start` must be a Monday (`weekday() == 0`)
7. Cannot add TimeEntry to APPROVED or SUBMITTED timesheet
8. Hours values are Decimal (NUMERIC) — not cents, not float
9. On leave rejection/cancellation, days are returned to `remaining` balance
10. On leave approval, days move from `pending` → `taken` in LeaveBalance

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /hcm/time/shifts/ | List shift definitions |
| GET | /hcm/time/shifts/{id} | Shift detail |
| POST | /hcm/time/shifts/ | Create shift |
| PUT | /hcm/time/shifts/{id} | Update shift |
| POST | /hcm/time/attendance/clock-in | Clock in (with optional location) |
| POST | /hcm/time/attendance/clock-out | Clock out (computes hours) |
| GET | /hcm/time/attendance/{employee_id} | List attendance records |
| POST | /hcm/time/leave/ | Submit leave request |
| GET | /hcm/time/leave/{employee_id} | List requests for employee |
| POST | /hcm/time/leave/{request_id}/approve | Approve |
| POST | /hcm/time/leave/{request_id}/reject | Reject |
| POST | /hcm/time/leave/{request_id}/cancel | Cancel |
| GET | /hcm/time/leave/balance/{employee_id} | Leave balances by type/year |
| POST | /hcm/time/timesheets/ | Create DRAFT timesheet |
| GET | /hcm/time/timesheets/{id} | Detail + entries |
| POST | /hcm/time/timesheets/{id}/entries | Add time entry |
| POST | /hcm/time/timesheets/{id}/submit | Submit for approval |
| POST | /hcm/time/timesheets/{id}/approve | Approve |
| POST | /hcm/time/timesheets/{id}/reject | Reject → DRAFT |
| GET | /hcm/time/timesheets/employee/{employee_id} | List for employee |
| GET | /hcm/time/reports/overtime | Overtime summary |
| GET | /hcm/time/reports/leave-balances | Leave balance snapshot |
| GET | /hcm/time/reports/attendance | Attendance status summary |

## Events Emitted
- `hcm.time.attendance.clocked_in`
- `hcm.time.attendance.clocked_out`
- `hcm.time.leave_request.submitted`
- `hcm.time.leave_request.approved`
- `hcm.time.leave_request.rejected`
- `hcm.time.leave_request.cancelled`
- `hcm.time.timesheet.submitted`
- `hcm.time.timesheet.approved` ← consumed by payroll plugin
- `hcm.time.timesheet.rejected`

## Events Consumed
- `hcm.personnel.employee.hired` — initialise leave balance for new hire
- `hcm.personnel.employee.terminated` — cancel pending leave requests

## Rules Engine Rulesets (pre-configured)
1. `hcm.time.leave_request.no_past_dates` — start_date not in past
2. `hcm.time.leave_request.end_after_start` — end >= start
3. `hcm.time.timesheet.week_start_monday` — week_start is Monday
4. `hcm.time.timesheet.no_edit_approved` — no entries on locked timesheet
5. `hcm.time.attendance.no_double_clockin` — one clock-in per day

## Reports
1. **Overtime Summary** — total overtime hours per employee over N days (approved timesheets)
2. **Leave Balance Report** — all employee balances for a year with accrued/taken/pending/remaining
3. **Attendance Summary** — status bucket counts (PRESENT/ABSENT/LATE/HALF_DAY) for a date range

## Cross-Plugin Composability
- Emits `hcm.time.timesheet.approved` → consumed by `hcm.payroll` to compute hourly gross pay
- Consumes `hcm.personnel.employee.hired` → creates initial LeaveBalance rows
- Consumes `hcm.personnel.employee.terminated` → cancels PENDING leave requests
- LeavePolicy is scoped to `entity_id` from `hcm.org` — leave entitlements vary per country/entity
