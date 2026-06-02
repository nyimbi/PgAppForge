# GRC Sustainability Plugin — SPEC

## Domain
`grc` — governance, risk & compliance

## Purpose
GHG Protocol Scopes 1/2/3 emission tracking with activity-based calculations,
and ESG metric management aligned to GRI, SASB, TCFD, and CDP frameworks.

## Entities

### EmissionSource
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| source_name | VARCHAR(300) | |
| scope | INT | 1 (direct) \| 2 (purchased energy) \| 3 (value chain) |
| emission_category | VARCHAR(200) | e.g. 'Stationary Combustion' |
| activity_type | VARCHAR(200) | e.g. 'natural_gas_combustion' |
| unit_of_measure | VARCHAR(50) | kWh \| litres \| km \| tonne |
| emission_factor | NUMERIC(15,8) | kgCO2e per unit (never float) |
| emission_factor_source | VARCHAR(200) | IPCC_AR6 \| DEFRA_2024 \| EPA_2024 |
| effective_from | DATE | use most recent factor ≤ activity date |
| created_at / updated_at | TIMESTAMPTZ | |

### EmissionRecord *(immutable after verification)*
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| source_id | UUID FK EmissionSource | |
| period_date | DATE | activity period (month-start recommended) |
| activity_quantity | NUMERIC(15,4) | measured activity amount |
| uom | VARCHAR(50) | copied from source at recording time |
| co2e_tonnes | NUMERIC(15,4) | calculated/measured tCO2e (never float) |
| method | VARCHAR(15) | CALCULATED \| MEASURED \| ESTIMATED |
| verified | BOOL DEFAULT false | |
| verified_by | VARCHAR(200) | verifier name/org |
| data_quality | VARCHAR(6) | HIGH \| MEDIUM \| LOW |
| notes | TEXT | |
| created_at / updated_at | TIMESTAMPTZ | |

Calculation: `co2e_tonnes = activity_quantity × emission_factor ÷ 1000`

### ESGMetric
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| metric_code | VARCHAR(100) | unique per tenant |
| metric_name | VARCHAR(300) | |
| pillar | VARCHAR(15) | ENVIRONMENTAL \| SOCIAL \| GOVERNANCE |
| unit | VARCHAR(100) | tCO2e \| % \| kWh/unit |
| target_value | NUMERIC(20,4) | aspirational goal |
| target_year | INT | |
| reporting_framework | VARCHAR(10) | GRI \| SASB \| TCFD \| CDP |
| description | TEXT | |
| created_at / updated_at | TIMESTAMPTZ | |

UNIQUE (tenant_id, metric_code)

### ESGSnapshot
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| metric_id | UUID FK ESGMetric | |
| snapshot_year | INT | |
| actual_value | NUMERIC(20,4) | |
| target_value | NUMERIC(20,4) | snapshot-time target (may differ from metric target) |
| improvement_pct | NUMERIC(7,2) | YoY: (actual - prior) / prior × 100 |
| notes | TEXT | |
| verified_by | VARCHAR(200) | third-party assurance |
| verified_at | TIMESTAMPTZ | |
| created_at / updated_at | TIMESTAMPTZ | |

UNIQUE (tenant_id, metric_id, snapshot_year) — one snapshot per metric per year

## Business Rules
1. scope must be 1, 2, or 3 (GHG Protocol Scopes).
2. emission_factor must be positive.
3. co2e_tonnes always stored as NUMERIC, never float.
4. Verified EmissionRecord rows are immutable; insert correction records instead.
5. One ESGSnapshot per metric per year per tenant.
6. improvement_pct computed by service: (actual − prior_year) ÷ prior_year × 100.
7. ESGTargetMissedEvent emitted when ENVIRONMENTAL actual > target.

## Events Emitted
- `sustainability.emission.recorded`
- `sustainability.emission.verified`
- `sustainability.esg_metric.target_set`
- `sustainability.esg_snapshot.captured`
- `sustainability.esg_snapshot.target_missed`

## Events Consumed
- `operations.production.completed` — auto-record scope 1 emissions
- `finance.ap.invoice_approved` — capture scope 3 spend-based emissions

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /sustainability/emission-sources/ | List emission sources |
| POST | /sustainability/emission-sources/ | Create source |
| GET | /sustainability/emission-records/ | List records |
| POST | /sustainability/emission-records/ | Record emission |
| POST | /sustainability/emission-records/{id}/verify | Verify record |
| GET | /sustainability/esg-metrics/ | List metrics |
| POST | /sustainability/esg-metrics/ | Create metric |
| GET | /sustainability/esg-snapshots/ | List snapshots |
| POST | /sustainability/esg-snapshots/ | Capture snapshot |
| GET | /sustainability/reports/ghg-scope-rollup | tCO2e by scope for period |
| GET | /sustainability/reports/esg-dashboard | All metrics with latest snapshot |
| GET | /sustainability/reports/emission-trend | Monthly CO2e trend |

## Rules Engine Rulesets (5)
1. `emission_source.scope_valid` — scope ∈ {1, 2, 3}
2. `emission_source.positive_factor` — emission_factor > 0
3. `emission_record.verified_immutable` — block update on verified records
4. `esg_snapshot.unique_per_year` — one snapshot per metric per year
5. `esg_metric.pillar_valid` — pillar ∈ {ENVIRONMENTAL, SOCIAL, GOVERNANCE}

## Cross-plugin Composability
- **Upstream**: foundation, operations.production, finance.ap
- **Downstream**: analytics (ESG dashboard), reporting
