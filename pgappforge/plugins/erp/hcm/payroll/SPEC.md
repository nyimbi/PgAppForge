# HCM Payroll Plugin — Specification

**Domain**: hcm  
**Module**: payroll  
**Version**: 1.0.0  
**Depends on**: foundation

---

## Entities & Relationships

```
PayrollCalendar (1) ──< PayrollRun (1) ──< Payslip (1) ──< PayslipLine
                                                   │
                                            TaxWithholding (per employee/jurisdiction)
```

### PayrollCalendar
Defines the pay schedule for a legal entity.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK, gen_random_uuid() | |
| tenant_id | UUID | NOT NULL | |
| entity_id | UUID | NOT NULL | Legal entity / cost centre |
| name | VARCHAR(100) | NOT NULL | e.g. "Monthly 2026" |
| pay_frequency | VARCHAR(20) | NOT NULL | WEEKLY\|BIWEEKLY\|SEMIMONTHLY\|MONTHLY |
| periods | JSONB | NOT NULL, default=[] | [{period_start, period_end, pay_date, label}] |
| fiscal_year | INTEGER | NOT NULL | Calendar year |
| is_active | BOOLEAN | NOT NULL, default=True | |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

**Unique**: (tenant_id, entity_id, name)

### PayrollRun
One run per pay period per entity. Aggregate counters are set by `calculate_payrun()`.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| tenant_id | UUID | NOT NULL | |
| entity_id | UUID | NOT NULL | |
| calendar_id | UUID | FK pay_calendar.id | Nullable |
| period_start | DATE | NOT NULL | |
| period_end | DATE | NOT NULL | |
| pay_date | DATE | NOT NULL | Bank value date |
| payroll_type | VARCHAR(20) | NOT NULL | REGULAR\|OFF_CYCLE\|BONUS\|TERMINATION |
| status | VARCHAR(20) | NOT NULL | DRAFT\|CALCULATED\|APPROVED\|PAID |
| employee_count | INTEGER | NOT NULL, default=0 | |
| total_gross_cents | INTEGER | NOT NULL, default=0 | |
| total_employee_tax_cents | INTEGER | NOT NULL, default=0 | |
| total_employer_tax_cents | INTEGER | NOT NULL, default=0 | |
| total_net_cents | INTEGER | NOT NULL, default=0 | |
| calculated_at | TIMESTAMPTZ | | |
| approved_by | UUID | | FK to ab_user |
| approved_at | TIMESTAMPTZ | | |
| paid_at | TIMESTAMPTZ | | |
| gl_journal_id | VARCHAR(50) | | Set by post_to_gl() |

**Unique**: (tenant_id, entity_id, period_start, period_end, payroll_type)  
**Immutable ledger**: once PAID, amounts must not change. Use OFF_CYCLE correction run.

### Payslip
Individual employee payslip within a run. IMMUTABLE after status=PAID.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK | |
| tenant_id | UUID | NOT NULL | |
| payrun_id | UUID | FK pay_run.id CASCADE | |
| employee_id | UUID | NOT NULL | Soft FK to employee master |
| gross_pay_cents | INTEGER | NOT NULL | Sum of earnings lines |
| income_tax_cents | INTEGER | NOT NULL | PAYE / withholding tax |
| national_insurance_cents | INTEGER | NOT NULL | Employee NI / social security |
| pension_employee_cents | INTEGER | NOT NULL | Employee pension contribution |
| pension_employer_cents | INTEGER | NOT NULL | Employer pension cost (not deducted from net) |
| other_deductions_cents | INTEGER | NOT NULL | Loans, garnishments, etc. |
| net_pay_cents | INTEGER | NOT NULL | gross - taxes - pension_emp - other |
| bank_account_iban | VARCHAR(34) | | Snapshot at calculation time |
| currency_code | CHAR(3) | NOT NULL | ISO 4217 |
| payment_reference | VARCHAR(100) | | End-to-end bank reference |
| status | VARCHAR(20) | NOT NULL | CALCULATED\|APPROVED\|PAID\|REVERSED |

**Unique**: (payrun_id, employee_id)

### PayslipLine
Detailed earnings/deduction line. Supports cost-centre GL coding.

| Column | Type | Notes |
|--------|------|-------|
| line_type | VARCHAR(20) | BASIC\|OVERTIME\|BONUS\|COMMISSION\|ALLOWANCE\|DEDUCTION\|TAX |
| units | NUMERIC(10,4) | Hours, days, or 1 for lump sums |
| rate_cents | INTEGER | Per-unit rate in cents |
| amount_cents | INTEGER | units × rate_cents; negative for deductions |
| is_employer_cost | BOOLEAN | True = employer-side (NI, pension_er) |
| gl_account | VARCHAR(20) | GL expense/liability account code |
| cost_center | VARCHAR(20) | |

### TaxWithholding
Employee tax configuration per jurisdiction. Latest-row-wins by `effective_from`.

| Column | Type | Notes |
|--------|------|-------|
| employee_id | UUID | Soft FK to employee master |
| jurisdiction_code | VARCHAR(20) | ISO 3166-2 or local e.g. US-CA, GB |
| filing_status | VARCHAR(40) | SINGLE\|MARRIED\|MARRIED_FILING_SEPARATELY\|HEAD_OF_HOUSEHOLD |
| allowances | INTEGER | W-4 allowances (US) |
| additional_withholding_cents | INTEGER | default=0 |
| effective_from | DATE | NOT NULL |

---

## Business Rules

1. **Immutable ledger**: PayrollRun amounts and Payslip amounts are never updated after PAID. Corrections use a new OFF_CYCLE run with negative PayslipLines.
2. **Monotone status**: DRAFT → CALCULATED → APPROVED → PAID (no skipping).
3. **Calculate only in DRAFT**: `calculate_payrun()` raises `PayrollStateError` if not DRAFT.
4. **net_pay formula**: `gross - income_tax - national_insurance - pension_employee - other_deductions`.
5. **Employer costs excluded from net**: `pension_employer_cents` tracks employer cost but does not reduce employee net pay.
6. **Integer cents only**: Never store or return floats for monetary amounts.
7. **Tax withholding override**: Per-employee `TaxWithholding.additional_withholding_cents` adds flat amount on top of computed tax.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /payroll/calendars/ | List pay calendars |
| POST | /payroll/calendars/ | Create calendar |
| GET | /payroll/runs/ | List payroll runs |
| POST | /payroll/runs/ | Create DRAFT run |
| GET | /payroll/runs/<id> | Run detail |
| POST | /payroll/runs/<id>/calculate | Gross→net calculation |
| POST | /payroll/runs/<id>/approve | Approve run |
| POST | /payroll/runs/<id>/pay | Mark PAID |
| GET | /payroll/runs/<id>/bank-file | ISO 20022 PAIN.001 XML |
| POST | /payroll/runs/<id>/post-gl | Post GL journal |
| GET | /payroll/payslips/ | List payslips |
| GET | /payroll/payslips/<id> | Payslip detail with lines |
| POST | /payroll/payslips/<id>/reverse | Reverse a PAID payslip |
| GET | /payroll/tax-withholding/ | List withholding configs |
| POST | /payroll/tax-withholding/ | Create withholding config |
| GET | /payroll/reports/summary | Payroll Run Summary |
| GET | /payroll/reports/register | Payslip Register (per run) |
| GET | /payroll/reports/statutory | Statutory Annual Summary |

---

## Events

### Emitted
| Event | Trigger |
|-------|---------|
| hcm.payroll.run.calculated | `calculate_payrun()` succeeded |
| hcm.payroll.run.approved | `approve_payrun()` succeeded |
| hcm.payroll.run.paid | `mark_paid()` succeeded |
| hcm.payroll.payslip.reversed | `reverse_payslip()` succeeded |
| hcm.payroll.gl.posted | `post_to_gl()` succeeded |
| hcm.payroll.statutory.filed | Statutory return submitted |

### Consumed
| Event | Handler |
|-------|---------|
| hcm.employee.salary_changed | Trigger recalculation checks |
| hcm.employee.terminated | Trigger TERMINATION payroll run creation |

---

## GL Journal — Payroll Posting

```
DR  5000  Salary & Wages Expense       total_gross_cents
DR  5010  Employer NI / Social Security total_employer_tax_cents
  CR  1100  Net Pay — Bank Clearing       total_net_cents
  CR  2100  PAYE / Income Tax Payable     total_employee_tax_cents
  CR  2200  Pension Contributions Payable pension_employee + pension_employer
```

---

## Reports

| Report | Endpoint | Key Fields |
|--------|----------|------------|
| Payroll Run Summary | /payroll/reports/summary | Period, type, employees, gross, tax, net, status |
| Payslip Register | /payroll/reports/register?payrun_id=X | Employee, gross, income_tax, NI, pension, net |
| Statutory Annual Summary | /payroll/reports/statutory?entity_id=X&year=Y | Annual roll-up of all PAID runs; government submission format |

---

## Rules Engine Pre-configuration (5 rulesets)

| Ruleset | Model | Trigger | Action |
|---------|-------|---------|--------|
| payroll.run.draft_only_calculate | PayrollRun | on_before_update | Reject calculate on non-DRAFT run |
| payroll.run.approve_requires_calculated | PayrollRun | on_before_update | Reject approval if not CALCULATED |
| payroll.payslip.positive_gross | Payslip | on_before_create | Reject non-positive gross (non-reversal) |
| payroll.payslip.immutable_after_paid | Payslip | on_before_update | Block mutation of PAID payslips |
| payroll.tax_withholding.additional_non_negative | TaxWithholding | on_before_create | Reject negative additional withholding |
