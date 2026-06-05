# SPEC — Travel & Expense Plugin

**Module**: `pgappforge.plugins.erp.hcm.travel_expense`
**Table prefix**: `te_`
**Plugin key**: `hcm.travel_expense` (registered in `ERP_GROUPS`)
**Depends on**: `foundation`, `finance.gl`, `hcm.personnel`

---

## Overview

End-to-end employee travel and expense management: policy enforcement,
cash advance lifecycle, multi-currency expense claims, mileage tracking,
per-diem subsistence rates, manager approval workflows, PAYE benefit-in-kind
(BIK) flagging, and GL reimbursement posting.

Targets any organisation where employees incur business expenses: professional
services, NGOs, field-operations teams, financial services, government.

---

## Key Entities

### ExpensePolicy
Per-category / per-grade expense spending limits and receipt thresholds.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID PK | |
| `tenant_id` | UUID | Multi-tenant isolation |
| `name` | String(120) | Human-readable policy name |
| `policy_type` | String | `CATEGORY_LIMIT \| DAILY_LIMIT \| PER_DIEM \| MILEAGE` |
| `grade_code` | String(20) | Employee grade this policy targets; NULL = all grades |
| `expense_category` | String(50) | Matches ExpenseLine.expense_category |
| `single_limit_cents` | BigInteger | Max allowed per line (or per day) |
| `requires_receipt_above_cents` | BigInteger | Receipt mandatory above this threshold |
| `requires_approval_above_cents` | BigInteger | Manager approval required above this threshold |
| `currency_code` | String(3) | Default KES |
| `is_active` | Boolean | |

### PerDiemRate
Country/city subsistence rates by effective date range.

| Field | Type | Description |
|-------|------|-------------|
| `country_code` | String(3) | ISO 3166-1 alpha-3 |
| `city_code` | String(10) | Optional city; NULL = country-wide rate |
| `from_date`, `to_date` | Date | Effective date range; `to_date` NULL = open-ended |
| `breakfast_cents` | BigInteger | |
| `lunch_cents` | BigInteger | |
| `dinner_cents` | BigInteger | |
| `accommodation_cents` | BigInteger | |
| `incidentals_cents` | BigInteger | |
| `currency_code` | String(3) | |

City-level rows take precedence over country-level rows (NULL `city_code`).

### ExpenseReport
Header record for a trip or expense claim (one report per business trip or period).

| Field | Type | Description |
|-------|------|-------------|
| `employee_id` | UUID | Soft FK to HCM employee |
| `title` | String(200) | Short descriptive title |
| `trip_purpose` | Text | Business purpose narrative |
| `destination` | String(200) | |
| `trip_start`, `trip_end` | Date | |
| `total_claimed_cents` | BigInteger | Sum of ExpenseLine.base_amount_cents |
| `total_approved_cents` | BigInteger | Set by approver; may differ from claimed |
| `advance_received_cents` | BigInteger | Cash advance already disbursed |
| `reimbursement_due_cents` | BigInteger | `total_claimed - advance_received`; negative = employee refund |
| `status` | String | See state machine |

### ExpenseLine
Individual line item within an ExpenseReport.

| Field | Type | Description |
|-------|------|-------------|
| `expense_category` | String | `MEALS \| ACCOMMODATION \| TRANSPORT \| MILEAGE \| CONFERENCE \| FUEL \| ENTERTAINMENT \| COMMUNICATION \| OTHER` |
| `amount_cents` | BigInteger | Amount in original (line) currency |
| `currency_code` | String(3) | Transaction currency |
| `exchange_rate` | Numeric(12,6) | FX rate to report base currency |
| `base_amount_cents` | BigInteger | `amount_cents × exchange_rate` |
| `is_billable_to_client` | Boolean | If True, linked to a project for pass-through billing |
| `project_id` | UUID | Optional: charge to project for billable expense pass-through |
| `is_paye_bik` | Boolean | True when benefit-in-kind must flow to payroll for PAYE |
| `receipt_url` | String(500) | Storage URL of attached receipt image |
| `policy_breach` | Boolean | Set by `check_policy()` on submission |
| `breach_reason` | Text | Description of which policy was breached |
| `approved_amount_cents` | BigInteger | Approver override; NULL = full amount approved |

### CashAdvance
Cash advance request and settlement lifecycle.

| Field | Type | Description |
|-------|------|-------------|
| `employee_id` | UUID | |
| `request_date` | Date | |
| `amount_cents` | BigInteger | Requested advance amount |
| `status` | String | `REQUESTED → APPROVED → DISBURSED → SETTLED` |
| `disbursed_at` | DateTime | Set when funds transferred |
| `disbursement_ref` | String(100) | Bank / M-Pesa reference |
| `linked_report_id` | UUID FK | ExpenseReport that settles this advance |
| `outstanding_cents` | BigInteger | Remaining unreconciled balance; 0 when settled |

### MileageLog
Mileage claim record (standalone or linked to an ExpenseReport).

| Field | Type | Description |
|-------|------|-------------|
| `distance_km` | Numeric(8,2) | |
| `rate_per_km_cents` | BigInteger | Applicable rate in integer cents per km |
| `total_cents` | BigInteger | `distance_km × rate_per_km_cents`, rounded half-up |
| `project_id` | UUID | Optional: billable mileage on a project |
| `report_id` | UUID FK | If linked, creates a matching MILEAGE ExpenseLine |

---

## State Machines

### ExpenseReport Status
```
DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED → PAID
                                 ↘ REJECTED → DRAFT (employee revises)
DRAFT | SUBMITTED | UNDER_REVIEW → CANCELLED
APPROVED → CANCELLED (before payment)
```

### CashAdvance Status
```
REQUESTED → APPROVED → DISBURSED → SETTLED
REQUESTED | APPROVED → CANCELLED
```

On `SETTLED`: `outstanding_cents` set to 0 (or residual if advance exceeded claim).
If employee overspent, `outstanding_cents` remains 0 but `ExpenseReport.reimbursement_due_cents`
is positive (organisation reimburses employee for the overage).
If employee underspent, `reimbursement_due_cents` is negative (employee returns the surplus).

---

## Events Emitted

| Event | Trigger |
|-------|---------|
| `expense.report.submitted` | Status → SUBMITTED |
| `expense.report.approved` | Status → APPROVED |
| `expense.report.rejected` | Status → REJECTED |
| `expense.report.paid` | Status → PAID |
| `expense.advance.disbursed` | CashAdvance status → DISBURSED |
| `expense.advance.settled` | CashAdvance status → SETTLED |
| `expense.policy_breach.flagged` | `check_policy()` finds a breach on submission |
| `expense.bik.flagged` | ExpenseLine with `is_paye_bik=True` submitted |

## Events Consumed

| Event | Action |
|-------|--------|
| `hcm.personnel.employee.terminated` | Auto-reject any DRAFT/SUBMITTED reports; flag outstanding advances for urgent settlement |

---

## GL Account Usage

| Posting | DR | CR | Notes |
|---------|----|----|-------|
| Cash advance disbursed | ADVANCE_RECEIVABLE (1300) | CASH_AND_NOSTRO (1011) | |
| Expense report approved | TRAVEL_AND_ENTERTAINMENT (6300) | ADVANCE_RECEIVABLE (1300) | For amount covered by advance |
| Expense report approved — mileage | MILEAGE_CLAIMS (6350) | ADVANCE_RECEIVABLE (1300) | |
| Reimbursement due to employee | TRAVEL_AND_ENTERTAINMENT (6300) | ACCRUED_EXPENSES (2100) | Net excess over advance |
| Reimbursement paid | ACCRUED_EXPENSES (2100) | CASH_AND_NOSTRO (1011) | |
| Surplus advance refunded | CASH_AND_NOSTRO (1011) | ADVANCE_RECEIVABLE (1300) | Employee returns unused advance |
| Billable expense on project | ADVANCE_RECEIVABLE (1300) | AR_CONTROL (1200) | Pass-through billing only |

---

## Integration Points

| Plugin | How Used |
|--------|----------|
| `foundation` | Party / employee identity; Currency for FX rates |
| `hcm.personnel` | Employee grade code for policy lookups; termination event handling |
| `finance.gl` | `post_simple_journal()` for all postings above |
| `projects` | `project_id` on billable lines passes cost through to project actual costs |
| `hcm.payroll` | BIK-flagged lines (`is_paye_bik=True`) are picked up by payroll service to add to taxable income for the relevant pay period |

---

## World-Class Features vs Market Leaders

| Feature | PgAppForge | SAP Concur | Expensify | Workday Expenses |
|---------|-----------|------------|-----------|-----------------|
| Policy enforcement at submission | Yes | Yes | Partial | Yes |
| Per diem by country and city | Yes | Yes | No | Yes |
| PAYE BIK auto-flagging | Yes | Partial | No | Yes |
| Cash advance lifecycle with settlement | Yes | Yes | No | Yes |
| Multi-currency with FX rate per line | Yes | Yes | Yes | Yes |
| Mileage rate tables | Yes | Yes | Yes | Yes |
| Project billable pass-through | Yes | No | No | Partial |
| GL posting at approval | Yes | Via ERP | No | Yes |
| Grade-based policy limits | Yes | Partial | No | Yes |

---

## Architecture Decisions

**WHY separate `amount_cents` (transaction currency) and `base_amount_cents`
(report base currency)**: Multi-currency travel is the norm in East Africa. An
employee travelling Nairobi → Kampala → Kigali may incur expenses in KES, UGX,
and RWF on a single trip. FX rate is captured at claim time (not at approval),
which is the authoritative exchange rate for reimbursement. Storing both values
avoids recomputing the FX rate after-the-fact.

**WHY `reimbursement_due_cents` can be negative**: Negative means the employee
owes a refund (underspent advance). This is a legal obligation in most
jurisdictions. The service raises an alert and creates a payroll deduction
request rather than blocking the approval — it does not raise an error.

**WHY `policy_breach` is a flag rather than a hard block**: Blocking submission
creates friction that causes employees to game the system (split claims, edit
amounts). Flagging breaches for manager visibility and optional override is the
standard pattern in Concur/Workday. The approval workflow enforces the policy;
the data model records it.

**WHY `is_paye_bik` is on the line rather than the report**: PAYE treatment is
per-expense-category (e.g. ENTERTAINMENT above certain limits is BIK; MILEAGE
is not). Granularity at line level is required for correct tax treatment.
