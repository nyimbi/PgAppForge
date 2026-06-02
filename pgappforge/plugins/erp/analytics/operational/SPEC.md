# Operational Analytics Plugin — SPEC

## Domain
`analytics` — sub-plugin of the Analytics domain.

## Purpose
KPI catalogue with point-in-time snapshot tracking, saved parameterised SQL
queries, and scheduled report definitions.

---

## Entities

### KPIDefinition
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | Multi-tenant isolation |
| kpi_code | VARCHAR(100) | Unique per tenant |
| kpi_name | VARCHAR(500) | |
| domain | VARCHAR(100) | e.g. finance, sales, hcm |
| formula | TEXT | Human-readable or engine key |
| unit | VARCHAR(50) | e.g. USD, %, count |
| frequency | VARCHAR(20) | DAILY \| WEEKLY \| MONTHLY \| QUARTERLY |
| target_value | NUMERIC(20,4) | Default target |
| target_direction | VARCHAR(10) | HIGHER \| LOWER |
| owner_id | INT FK ab_user | Accountable owner |
| tags | TEXT[] | Classification tags |
| is_active | BOOLEAN | Default true |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() |

### KPISnapshot
Append-only. Never UPDATE existing rows — insert corrections.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| kpi_id | UUID FK KPIDefinition | CASCADE |
| snapshot_date | DATE | |
| actual_value | NUMERIC(20,4) | |
| target_value | NUMERIC(20,4) | Captured at snapshot time |
| prior_period_value | NUMERIC(20,4) | |
| variance_pct | NUMERIC(7,2) | (actual-target)/target*100 |
| status | VARCHAR(20) | ON_TRACK \| AT_RISK \| OFF_TRACK |
| recorded_at | TIMESTAMPTZ | DEFAULT NOW() |

### AnalyticsQuery
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| name | VARCHAR(500) | |
| description | TEXT | |
| query_sql | TEXT | Named-parameter placeholders (:param) |
| parameters | JSONB | Schema for expected parameters |
| created_by | INT FK ab_user | |
| last_run_at | TIMESTAMPTZ | |
| average_runtime_ms | INT | Rolling average |
| is_public | BOOLEAN | |

### AnalyticsReport
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| name | VARCHAR(500) | |
| category | VARCHAR(100) | Finance, Sales, Operations |
| layout | JSONB | Widget/chart canvas descriptor |
| is_scheduled | BOOLEAN | |
| schedule_cron | VARCHAR(100) | Standard cron expression |
| last_generated_at | TIMESTAMPTZ | |
| recipients | JSONB | `[{"type":"email","address":"x@y.com"}]` |

---

## Business Rules
1. KPI snapshots are immutable — corrections must be new rows.
2. `variance_pct` = `(actual - target) / target * 100`; NULL when target is NULL.
3. `status` thresholds (HIGHER direction): actual ≥ 95% target → ON_TRACK; ≥ 80% → AT_RISK; else OFF_TRACK.
4. LOWER direction inverts thresholds.
5. Saved queries may only use `:param` placeholders — DDL and unbounded DELETE are blocked by Rules Engine.
6. Scheduling a report with no recipients is blocked by Rules Engine.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /analytics/kpis/ | KPI catalogue list (HTML) |
| GET | /analytics/kpis/`<id>` | KPI detail (JSON) |
| POST | /analytics/kpis/ | Create KPI definition (JSON) |
| GET | /analytics/kpi-snapshots/ | Recent snapshots (HTML) |
| POST | /analytics/kpi-snapshots/ | Record snapshot (JSON) |
| GET | /analytics/kpi-snapshots/trend/`<kpi_id>` | Trend data (JSON) |
| GET | /analytics/queries/ | Query list (HTML) |
| POST | /analytics/queries/`<id>`/run | Execute query (JSON) |
| GET | /analytics/reports/ | Report catalogue (HTML) |
| GET | /analytics/reports/kpi_dashboard | KPI dashboard (HTML) |
| GET | /analytics/reports/kpi_status_summary | Status counts (JSON) |
| POST | /analytics/reports/`<id>`/generate | Generate report (JSON) |

---

## Events Emitted
- `analytics.kpi.snapshot_recorded` — new snapshot inserted
- `analytics.kpi.status_changed` — status transitioned (AT_RISK, OFF_TRACK)
- `analytics.report.generated` — report generated
- `analytics.query.executed` — query run

## Events Consumed
- `ar.invoice.paid` — update revenue KPI snapshots
- `hcm.payroll.run` — update payroll cost KPI snapshots

---

## Rules Engine Rulesets (4)
1. `analytics.kpi.alert_off_track` — notify on OFF_TRACK status
2. `analytics.kpi.alert_at_risk` — log warning on AT_RISK
3. `analytics.report.require_recipients_for_schedule` — block scheduling without recipients
4. `analytics.query.block_destructive_sql` — block DDL/unbounded DELETE in saved queries

---

## ReportForge Templates (3)
1. **KPI Dashboard** — on-track/at-risk/off-track card grid per domain
2. **KPI Status Summary** — JSON count by status for charting
3. **Report Catalogue** — scheduled vs on-demand inventory with last-generated timestamps
