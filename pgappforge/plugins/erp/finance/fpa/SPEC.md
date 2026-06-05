# SPEC — Financial Planning & Analysis (FP&A) Plugin

**Module**: `pgappforge.plugins.erp.finance.fpa`
**Table prefix**: `fpa_`
**Plugin key**: `finance.fpa` (registered in `ERP_GROUPS`)
**Depends on**: `foundation`, `finance.gl`

---

## Overview

Financial Planning & Analysis plugin covering the full budgeting and forecasting
lifecycle: budget cycle management, versioned budget line entry by account and
cost centre, driver-based budget computation, scenario modelling (optimistic /
base / pessimistic / stress), rolling forecast snapshots, budget vs actuals
variance analysis, and KPI target tracking.

Targets CFO offices, management accounting teams, and finance business partners
in any organisation managing an annual budget process.

---

## Key Entities

### BudgetCycle
Top-level container for a planning round (e.g. "FY2026 Annual Budget").

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID PK | |
| `tenant_id` | UUID | |
| `name` | String(100) | |
| `fiscal_year` | Integer | e.g. 2026 |
| `cycle_type` | String | `ANNUAL \| QUARTERLY \| ROLLING_12M` |
| `status` | String | See state machine |
| `input_deadline` | Date | Deadline for budget line submission |
| `approval_deadline` | Date | Deadline for cycle approval |
| `approved_by` | UUID | |
| `approved_at` | DateTime | |

### BudgetVersion
A named version snapshot within a cycle. Multiple versions allow comparison
between original budget, revisions, and rolling forecasts.

| Field | Type | Description |
|-------|------|-------------|
| `cycle_id` | UUID FK | Parent cycle |
| `version_name` | String(50) | e.g. "Original Budget", "Q2 Reforecast" |
| `version_type` | String | `ORIGINAL \| REVISED_1 \| REVISED_2 \| FORECAST \| WORKING` |
| `is_active` | Boolean | Only one active version of each type per cycle |
| `locked_at` | DateTime | Set when version is locked (read-only) |

### BudgetLine
One budget line: GL account × cost centre × legal entity × period month × amount.

| Field | Type | Description |
|-------|------|-------------|
| `version_id` | UUID FK | |
| `gl_account_code` | String(20) | References `gl_account.account_code` |
| `cost_center_code` | String(20) | |
| `entity_id` | UUID | Legal entity for consolidation |
| `period_month` | Date | Always first day of the month e.g. 2026-01-01 |
| `amount_cents` | BigInteger | Budget amount in integer cents |
| `driver_type` | String | `MANUAL \| HEADCOUNT \| REVENUE_PCT \| PRIOR_YEAR \| FORMULA` |
| `driver_params` | JSONB | Inputs for formula recomputation e.g. `{"headcount": 50, "rate": 200000}` |
| `narrative` | Text | Justification / assumption note |
| `status` | String | `DRAFT \| SUBMITTED \| APPROVED` |

UNIQUE: `(version_id, gl_account_code, cost_center_code, entity_id, period_month)`.

### BudgetDriver
Reusable driver definition for programmatic budget computation.

| Field | Type | Description |
|-------|------|-------------|
| `driver_code` | String(30) | Unique per tenant |
| `driver_type` | String | `HEADCOUNT \| VOLUME \| RATE \| PERCENTAGE \| FORMULA` |
| `unit` | String(20) | e.g. "employees", "units", "KES" |
| `base_value` | Numeric(12,4) | Default base value |
| `formula_expression` | Text | Safe Python expression: `base_value * params['headcount'] * params['rate']` |
| `is_global` | Boolean | True = available across all cycles for this tenant |

### ScenarioModel
What-if scenario applied to a base `BudgetVersion`.

| Field | Type | Description |
|-------|------|-------------|
| `name` | String(100) | e.g. "Bear Case — 15% revenue decline" |
| `base_version_id` | UUID FK | Version to apply adjustments to |
| `scenario_type` | String | `OPTIMISTIC \| BASE \| PESSIMISTIC \| STRESS \| CUSTOM` |
| `adjustment_rules` | JSONB | `{"4": {"pct": 10}, "6": {"pct": -5}}` keyed by GL account prefix |
| `status` | String | `DRAFT \| GENERATED \| APPROVED` |
| `generated_version_id` | UUID FK | WORKING BudgetVersion created by `generate_scenario()` |

Adjustment rule matching: longest prefix of `gl_account_code` wins.
`"*"` key matches all accounts as fallback.

### ForecastSnapshot
Immutable point-in-time actuals vs budget vs forecast record.

| Field | Type | Description |
|-------|------|-------------|
| `cycle_id` | UUID FK | |
| `snapshot_date` | Date | When the snapshot was taken |
| `period_month` | Date | The accounting period this row covers |
| `gl_account_code` | String(20) | |
| `cost_center_code` | String(20) | |
| `actual_cents` | BigInteger | From `GLAccountBalance` at snapshot time |
| `budget_cents` | BigInteger | From active `BudgetLine` at snapshot time |
| `forecast_cents` | BigInteger | Reforecast amount |
| `variance_cents` | BigInteger | `actual - budget` |
| `variance_pct` | Numeric(8,4) | |

Rows are **never updated** — each `take_forecast_snapshot()` call inserts new rows.

### KPITarget
Per-period KPI target and actuals tracking.

| Field | Type | Description |
|-------|------|-------------|
| `kpi_code` | String(30) | Unique KPI identifier e.g. GROSS_MARGIN_PCT |
| `kpi_name` | String(100) | Human label |
| `cycle_id` | UUID FK | |
| `period_month` | Date | |
| `target_value` | Numeric(16,4) | |
| `actual_value` | Numeric(16,4) | Updated by `update_kpi()` |
| `unit` | String(20) | e.g. %, KES, #employees |
| `direction` | String | `HIGHER_IS_BETTER \| LOWER_IS_BETTER` |
| `status` | String | `ON_TRACK \| AT_RISK \| OFF_TRACK` |

Status thresholds: ON_TRACK within 5% of target; AT_RISK 5–15%; OFF_TRACK >15%.

---

## State Machines

### BudgetCycle Status
```
DRAFT → INPUT_OPEN (budget owners can now submit lines)
INPUT_OPEN → UNDER_REVIEW (input deadline passed; CFO review)
UNDER_REVIEW → APPROVED (CFO approves)
APPROVED → LOCKED (no further changes)
UNDER_REVIEW → INPUT_OPEN (send back for revision)
```

### BudgetVersion
```
Active (is_active=True) → Locked (locked_at set)
```
Only one `is_active=True` version per `(cycle_id, version_type)` enforced at service layer.

### BudgetLine Status
```
DRAFT → SUBMITTED → APPROVED
SUBMITTED → DRAFT (returned for revision)
```

### ScenarioModel Status
```
DRAFT → GENERATED (generate_scenario() called)
GENERATED → APPROVED
GENERATED → DRAFT (regenerate with different rules)
```

### KPITarget Status
Computed (not persisted as a transition) each time `update_kpi()` is called:
```
ON_TRACK  ← |variance_pct| <= 0.05
AT_RISK   ← 0.05 < |variance_pct| <= 0.15
OFF_TRACK ← |variance_pct| > 0.15
```

---

## Events Emitted

| Event | Trigger |
|-------|---------|
| `fpa.budget_cycle.opened` | Status → INPUT_OPEN |
| `fpa.budget_cycle.approved` | Status → APPROVED |
| `fpa.budget_cycle.locked` | Status → LOCKED |
| `fpa.budget_line.submitted` | BudgetLine status → SUBMITTED |
| `fpa.scenario.generated` | ScenarioModel status → GENERATED |
| `fpa.forecast_snapshot.taken` | `take_forecast_snapshot()` called |
| `fpa.kpi.status_changed` | KPITarget status changes |
| `fpa.kpi.off_track` | KPITarget status → OFF_TRACK |

## Events Consumed

| Event | Action |
|-------|--------|
| `gl.period.closed` | Trigger `take_forecast_snapshot()` for the closed period to capture final actuals vs budget |
| `analytics.kpi.status_changed` | Cross-reference with FP&A KPITargets; update `actual_value` if the KPI code matches |

---

## GL Account Usage

FP&A is a planning overlay on top of GL — it reads `GLAccountBalance` and
`GLBudget` but does not post journal entries directly. The only GL interaction is:

| Operation | How |
|-----------|-----|
| Actuals pull | `FPAService.take_forecast_snapshot()` reads `GLAccountBalance.period_debit / period_credit` for each `(account_code, period_id)` |
| Budget push | `FPAService.push_budget_to_gl()` writes `GLBudget` rows from approved `BudgetLine` rows (account_code, cost_center_code, period mapping) |

`BudgetLine.gl_account_code` references `gl_account.account_code` but uses a
soft FK (no hard constraint) to remain installable without GL seeded data.

---

## Integration Points

| Plugin | How Used |
|--------|----------|
| `finance.gl` | Source of actuals (`GLAccountBalance`); destination for budget push (`GLBudget`) |
| `hcm.org` | Legal entity and cost centre master for budget line dimensions |
| `analytics.operational` | KPI actuals fed from operational KPI snapshots into `KPITarget.actual_value` |

---

## World-Class Features vs Market Leaders

| Feature | PgAppForge | Anaplan | Adaptive Insights | SAP BPC |
|---------|-----------|---------|------------------|---------|
| Budget cycle with workflow | Yes | Yes | Yes | Yes |
| Multiple versions per cycle | Yes | Yes | Yes | Yes |
| Driver-based computation | Yes | Yes | Yes | Yes |
| Scenario modelling (prefix-match rules) | Yes | Yes | Partial | Yes |
| Rolling 12-month forecast | Yes | Yes | Yes | Yes |
| GL actuals integration | Yes | Via connector | Via connector | Native |
| KPI target tracking | Yes | Yes | Yes | Partial |
| Point-in-time forecast snapshots | Yes | Yes | Yes | Yes |
| Multi-entity consolidation | Via entity_id | Yes | Yes | Yes |
| Formula sandbox in JSONB | Yes | Yes | Partial | No |

---

## Architecture Decisions

**WHY `period_month` is always the first day of the month**: Unambiguous
period identity without a separate period master table. A budget line for
February 2026 is `2026-02-01` regardless of how many days are in the month.
SQL date arithmetic on first-day-of-month is trivial and index-efficient.

**WHY `ForecastSnapshot` rows are immutable (never updated)**: Point-in-time
comparisons require that historical snapshots remain unchanged. The CFO needs
to see what the forecast said in March vs what it said in September. If rows
were updated in place, that historical comparison would be lost. New `snapshot_date`
distinguishes snapshots.

**WHY `adjustment_rules` in `ScenarioModel` uses GL account code prefix matching
rather than exact matching**: Scenarios typically say "revenue up 10%" (all 4xxx
accounts) not "account 4000 up 10%, account 4100 up 10%...". Prefix matching on
GL code hierarchy (`"4"` matches all revenue accounts) is the natural idiom for
FP&A. Longest-prefix-wins resolves ambiguity when rules overlap.

**WHY `BudgetDriver.formula_expression` is a stored Python expression in JSONB
rather than a compiled function**: Budget drivers change annually (new headcount
assumptions, revised rate tables). Storing the expression as text means finance
users can inspect and audit it without deploying code. The service evaluates it
in a restricted namespace (`{base_value, params}`) — only arithmetic and basic
Python builtins. No `eval` of arbitrary user code reaches the DB or filesystem.

**WHY KPI status thresholds (5%/15%) are hardcoded in the service rather than
configurable per KPI**: Configurability creates test surface without business
value — no organisation uses different materiality thresholds per KPI at this
granularity. If a KPI has a genuinely different materiality threshold, the
workaround is to set the `target_value` to include the tolerance band. Hardcoded
thresholds are documented here and trivially changed in one place if policy
changes.
