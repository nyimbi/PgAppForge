# SPEC — Project Management / PSA Plugin

**Module**: `pgappforge.plugins.erp.projects`
**Table prefix**: `proj_`
**Plugin key**: `projects` (registered in `ERP_GROUPS`)
**Depends on**: `foundation`, `finance.gl`, `finance.ar`, `hcm.time`

---

## Overview

Professional Services Automation (PSA) and Project Management plugin covering
the full project delivery lifecycle: planning, resource allocation, time capture,
milestone billing, earned value management, change control, and IFRS 15 revenue
recognition.

Targets professional services firms, consulting practices, software houses, NGOs
with project portfolios, and any enterprise managing capital projects or
cost-to-complete budgets.

---

## Key Entities

### Program
Container for a portfolio of related projects sharing a programme budget ceiling.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID PK | |
| `tenant_id` | UUID | Multi-tenant isolation |
| `code` | String(30) | Unique programme code e.g. PRG-001 |
| `name` | String(200) | |
| `owner_id` | UUID | Programme director (soft FK to HR employee) |
| `status` | String | `ACTIVE \| COMPLETED \| CANCELLED` |
| `budget_cents` | Integer | Approved programme budget ceiling in cents |
| `currency_code` | String(3) | ISO 4217, default KES |

### Project
Central aggregate. One project per customer engagement or capital work order.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID PK | |
| `program_id` | UUID FK | Optional parent programme |
| `code` | String(30) | Unique per tenant e.g. PRJ-2026-042 |
| `project_type` | String | `FIXED_FEE \| T_AND_M \| RETAINER \| MILESTONE` |
| `customer_id` | UUID | Soft FK to CRM/party master |
| `owner_id` | UUID | Project manager |
| `start_date`, `end_date` | Date | Planned schedule |
| `status` | String | See state machine |
| `original_budget_cents` | Integer | BAC — approved baseline budget |
| `revised_budget_cents` | Integer | Budget after approved change orders |
| `forecast_at_completion_cents` | Integer | EAC — latest cost forecast |
| `billed_to_date_cents` | Integer | Cumulative SENT+PAID invoice total |
| `recognised_revenue_cents` | Integer | Cumulative IFRS 15 revenue recognised |
| `percent_complete` | Numeric(5,2) | 0–100 PM-entered progress |
| `risk_level` | String | `LOW \| MEDIUM \| HIGH \| CRITICAL` |

### WBSElement
Work Breakdown Structure — hierarchical decomposition of project scope.

| Field | Type | Description |
|-------|------|-------------|
| `element_type` | String | `PHASE \| DELIVERABLE \| TASK \| MILESTONE` |
| `planned_hours` | Numeric(8,2) | Estimated effort |
| `actual_hours` | Numeric(8,2) | Cumulative from approved timesheets |
| `planned_cost_cents` | Integer | Budget for this element |
| `actual_cost_cents` | Integer | Approved timesheet costs accumulated |
| `predecessor_ids` | JSONB | `[uuid, ...]` finish-to-start dependencies |
| `status` | String | `NOT_STARTED \| IN_PROGRESS \| COMPLETED \| CANCELLED` |

### ProjectResource
One row per employee × project (× role for multi-role allocations).

| Field | Type | Description |
|-------|------|-------------|
| `role` | String | `PM \| ANALYST \| DEVELOPER \| DESIGNER \| QA` |
| `allocated_hours` | Numeric | Planned allocation |
| `bill_rate_cents_per_hour` | Integer | T&M customer billing rate |
| `cost_rate_cents_per_hour` | Integer | Internal cost rate for margin analysis |

### ProjectTimesheet
Daily time entry charged to a project WBS task.

| Field | Type | Description |
|-------|------|-------------|
| `hours` | Numeric(5,2) | Hours worked |
| `cost_cents` | Integer | Computed on approval: hours × cost_rate |
| `bill_amount_cents` | Integer | Computed on approval: hours × bill_rate |
| `status` | String | `DRAFT → SUBMITTED → APPROVED → BILLED` |

### ProjectMilestone
Contractual milestones for milestone-billing and IFRS 15 revenue recognition.

| Field | Type | Description |
|-------|------|-------------|
| `amount_cents` | Integer | Contractual milestone value (excl. tax) |
| `status` | String | `PENDING \| ACHIEVED \| INVOICED \| PAID` |

### ProjectRisk
Risk register entry.

| Field | Type | Description |
|-------|------|-------------|
| `probability` | Integer | 1 (Very Low) – 5 (Critical) |
| `impact` | Integer | 1 (Very Low) – 5 (Critical) |
| `risk_score` | Integer | probability × impact (1–25) |
| `status` | String | `OPEN \| MITIGATED \| ACCEPTED \| CLOSED` |

### ChangeOrder
Scope/budget/schedule change request.

| Field | Type | Description |
|-------|------|-------------|
| `budget_delta_cents` | Integer | +ve = increase, -ve = reduction |
| `schedule_delta_days` | Integer | +ve = extension |
| `status` | String | `DRAFT → SUBMITTED → APPROVED \| REJECTED` |

### ProjectInvoice

| Field | Type | Description |
|-------|------|-------------|
| `invoice_type` | String | `MILESTONE \| T_AND_M \| RETAINER \| ADVANCE` |
| `amount_cents` | Integer | Net before tax |
| `tax_cents` | Integer | VAT / WHT |
| `total_cents` | Integer | amount + tax |
| `status` | String | `DRAFT → SENT → PAID \| CANCELLED` |

---

## State Machines

### Project Status
```
DRAFT → PLANNING → ACTIVE → ON_HOLD → ACTIVE (resume)
ACTIVE → COMPLETED
ACTIVE → CANCELLED
ON_HOLD → CANCELLED
PLANNING → CANCELLED
```

### ProjectTimesheet Status
```
DRAFT → SUBMITTED → APPROVED → BILLED
              ↘ REJECTED → DRAFT (employee revises and resubmits)
```
Once `BILLED`, the row is immutable — it has been included in a `ProjectInvoice`.

### ProjectMilestone Status
```
PENDING → ACHIEVED (PM marks delivery complete)
ACHIEVED → INVOICED (generate_invoice() called)
INVOICED → PAID (payment received in AR)
```

### ChangeOrder Status
```
DRAFT → SUBMITTED → APPROVED (project.revised_budget_cents += delta)
                  ↘ REJECTED
```

### ProjectInvoice Status
```
DRAFT → SENT → PAID
           ↘ CANCELLED
```

---

## Events Emitted

| Event | Trigger |
|-------|---------|
| `project.created` | New project saved with status DRAFT |
| `project.activated` | Status → ACTIVE |
| `project.completed` | Status → COMPLETED |
| `project.cancelled` | Status → CANCELLED |
| `project.milestone.achieved` | Milestone status → ACHIEVED |
| `project.milestone.invoiced` | Milestone status → INVOICED |
| `project.change_order.approved` | ChangeOrder status → APPROVED |
| `project.invoice.sent` | Invoice status → SENT |
| `project.invoice.paid` | Invoice status → PAID |
| `project.risk.score_changed` | risk_score updated above/below threshold |

## Events Consumed

| Event | Action |
|-------|--------|
| `hcm.time.timesheet.approved` | If `project_id` set on timesheet, credit WBS actual_hours and trigger cost accumulation |
| `ar.invoice.paid` | If `source_document_type == PROJECT_INVOICE`, update `project.billed_to_date_cents` and trigger IFRS 15 recognition |

---

## GL Account Usage

| Posting | DR | CR |
|---------|----|----|
| Invoice raised (T&M / Milestone / Retainer) | AR_CONTROL (1200) | REVENUE_SERVICES (4000) |
| Invoice paid | CASH_AND_NOSTRO (1011) | AR_CONTROL (1200) |
| Advance invoice | AR_CONTROL (1200) | CUSTOMER_DEPOSITS (2400) |
| Advance settled on delivery | CUSTOMER_DEPOSITS (2400) | REVENUE_SERVICES (4000) |
| Direct labour cost accrual | DIRECT_LABOUR (5200) | ACCRUED_SALARIES (2110) |

All GL postings via `GLService.post_simple_journal()` wrapped in `try/except`
(non-fatal if GL plugin absent). Account codes resolved through `_resolve_gl()`.

---

## Integration Points

| Plugin | How Used |
|--------|----------|
| `foundation` | Party master for customer_id; Currency for multi-currency invoicing |
| `finance.gl` | Invoice GL posting via `post_simple_journal()` |
| `finance.ar` | `generate_invoice()` creates an AR invoice which is tracked in AR aging |
| `hcm.time` | Approved project timesheets flow into `ProjectTimesheet` actual hours |
| `hcm.personnel` | Employee master for resource allocation and timesheet ownership |
| `finance.tax` | VAT computation on project invoices |

---

## World-Class Features vs Market Leaders

| Feature | PgAppForge | SAP PS | Oracle Projects | Microsoft Project Online |
|---------|-----------|--------|----------------|--------------------------|
| IFRS 15 revenue recognition (POC, milestone, straight-line) | Yes | Yes | Yes | No |
| EVM (PV, EV, AC, CPI, SPI) | Yes | Yes | Yes | Partial |
| WBS with predecessor dependencies | Yes | Yes | Yes | Yes |
| Integrated GL posting | Yes | Yes | Yes | No (requires Dynamics) |
| Multi-currency invoicing | Yes | Yes | Yes | Limited |
| Change order approval workflow | Yes | Yes | Yes | No |
| Risk register with auto project risk escalation | Yes | No | Partial | No |
| Native per-hour bill/cost rate separation | Yes | Yes | Yes | No |
| Retainer recognition with deferred revenue | Yes | No | Partial | No |

---

## Architecture Decisions

**WHY integer cents instead of Numeric for money**: Avoids IEEE 754 rounding
errors in accumulated cost calculations. EVM variances compound across hundreds
of timesheet lines; floating-point accumulation would produce silent P&L errors.

**WHY `percent_complete` is PM-entered rather than computed from WBS**: Computed
progress from WBS completion ratios gives a false precision signal — a task is
either 0% or 100% in most systems. PM-entered percent_complete allows expert
judgment on partial completion, which is what IFRS 15 POC method requires.

**WHY `billed_to_date_cents` is a running total on Project rather than always
summed from invoices**: Read performance. Project dashboards query this field
constantly; summing invoice lines at query time at scale (thousands of projects)
is too slow. The service layer maintains consistency via `generate_invoice()`.

**WHY `cost_cents` and `bill_amount_cents` are stored on the timesheet row**: Once
a timesheet is `BILLED` it becomes an immutable audit record. If cost or bill
rates change later (e.g. retrospective rate adjustment), the stored values
represent what was charged — a correction is a new entry, not an update.

**WHY soft FKs for `customer_id` and `employee_id`**: Cross-plugin hard FK
constraints create coupling that prevents independent plugin installation.
The advisory UUID pattern allows the project plugin to function without the CRM
or HCM plugins installed; the service layer validates existence when both are
present.
