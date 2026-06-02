# HCM Org Management Plugin — SPEC

## Domain
`hcm` | Plugin name: `hcm.org` | Depends on: `foundation`

## Entities

### LegalEntity (`hcm_org_legal_entity`)
Employer legal entity that runs payroll. One tenant can operate multiple legal entities in different countries.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | Multi-tenant partition key |
| entity_code | VARCHAR(20) | Unique per tenant |
| entity_name | VARCHAR(255) | Full registered legal name |
| tax_id | VARCHAR(50) | EIN, ABN, etc. |
| payroll_currency | CHAR(3) | ISO 4217, default USD |
| country_code | CHAR(2) | ISO 3166-1 alpha-2 |
| fiscal_year_start_month | INTEGER | 1–12 |
| address | JSONB | {line1,line2,city,state,postal_code,country} |
| is_active | BOOLEAN | DEFAULT true |
| created_at / updated_at | TIMESTAMPTZ | DEFAULT NOW() |

### OrgUnit (`hcm_org_unit`)
Org chart node. Self-referencing `parent_id` builds the hierarchy.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| entity_id | UUID FK → hcm_org_legal_entity | |
| org_code | VARCHAR(20) | Unique per tenant |
| org_name | VARCHAR(255) | |
| org_type | VARCHAR(30) | DIVISION \| DEPARTMENT \| TEAM \| UNIT |
| parent_id | UUID FK → hcm_org_unit (self) | NULL = root |
| cost_center_code | VARCHAR(20) | GL cost centre |
| manager_id | UUID (soft FK) | FK to hcm_org_position.id |
| headcount_budget | INTEGER | Approved headcount |
| is_active | BOOLEAN | |

### JobCatalog (`hcm_org_job_catalog`)
Centralised job architecture library. `flsa_status` drives overtime eligibility.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| job_code | VARCHAR(30) | Unique per tenant |
| job_title | VARCHAR(200) | |
| job_family | VARCHAR(100) | e.g. Engineering, Finance |
| job_function | VARCHAR(100) | Sub-grouping |
| grade_level | VARCHAR(20) | e.g. L3, IC4, Manager |
| flsa_status | VARCHAR(20) | EXEMPT \| NON_EXEMPT |
| is_active | BOOLEAN | |

### CompensationGrade (`hcm_org_compensation_grade`)
Effective-dated salary band. **IMMUTABLE LEDGER** — INSERT new rows with updated `effective_from`, never UPDATE.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| grade_code | VARCHAR(20) | e.g. G5, IC3, M2 |
| grade_label | VARCHAR(100) | e.g. Senior Engineer |
| min_cents | INTEGER | Minimum annual salary (cents) |
| mid_cents | INTEGER | Midpoint / target (cents) |
| max_cents | INTEGER | Maximum annual salary (cents) |
| currency_code | CHAR(3) | ISO 4217 |
| effective_from | DATE | Band activation date |

Active grade = row with highest `effective_from <= today`.

### Position (`hcm_org_position`)
Budgeted slot in the org chart. `is_filled` maintained by PersonnelPlugin via events.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| position_code | VARCHAR(30) | Unique per tenant |
| entity_id | UUID FK → hcm_org_legal_entity | |
| org_unit_id | UUID FK → hcm_org_unit | |
| job_code | UUID FK → hcm_org_job_catalog | |
| position_title | VARCHAR(200) | |
| employment_type | VARCHAR(20) | FULL_TIME \| PART_TIME \| CONTRACT \| CASUAL |
| is_filled | BOOLEAN | DEFAULT false |
| graded_salary_min_cents | INTEGER | Position-specific floor |
| graded_salary_max_cents | INTEGER | Position-specific ceiling |
| is_active | BOOLEAN | |

## Business Rules

1. `graded_salary_min_cents <= graded_salary_max_cents` (enforced by Rules Engine)
2. Cannot fill an `is_active=False` position
3. `CompensationGrade.min_cents <= mid_cents <= max_cents`
4. One position may only be filled by one employee at a time
5. `org_type` must be one of: DIVISION, DEPARTMENT, TEAM, UNIT
6. `country_code` must be ISO 3166-1 alpha-2
7. `payroll_currency` must be ISO 4217 (3 chars)

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /hcm/org/entities/ | List legal entities |
| GET | /hcm/org/entities/{id} | Entity detail |
| POST | /hcm/org/entities/ | Create entity |
| PUT | /hcm/org/entities/{id} | Update entity |
| POST | /hcm/org/entities/{id}/deactivate | Deactivate |
| GET | /hcm/org/units/ | List org units |
| GET | /hcm/org/units/{id} | Unit detail |
| POST | /hcm/org/units/ | Create unit |
| POST | /hcm/org/units/{id}/restructure | Change parent/manager |
| GET | /hcm/org/units/tree/{entity_id} | Flat org tree |
| GET | /hcm/org/positions/ | List positions |
| GET | /hcm/org/positions/{id} | Position detail |
| POST | /hcm/org/positions/ | Create position |
| POST | /hcm/org/positions/{id}/fill | Fill position |
| POST | /hcm/org/positions/{id}/vacate | Vacate position |
| GET | /hcm/org/jobs/ | List job catalog |
| POST | /hcm/org/jobs/ | Create job |
| PUT | /hcm/org/jobs/{id} | Update job |
| GET | /hcm/org/grades/ | List all comp grade bands |
| POST | /hcm/org/grades/ | Publish new band (immutable) |
| GET | /hcm/org/reports/headcount | Headcount by org unit |
| GET | /hcm/org/reports/open-positions | Unfilled positions |
| GET | /hcm/org/reports/grade-distribution | Comp grade span analysis |

## Events Emitted
- `hcm.org.legal_entity.created`
- `hcm.org.legal_entity.deactivated`
- `hcm.org.unit.created`
- `hcm.org.unit.restructured`
- `hcm.org.position.created`
- `hcm.org.position.filled`
- `hcm.org.position.vacated`
- `hcm.org.job_catalog.created`
- `hcm.org.compensation_grade.published`

## Events Consumed
- `hcm.personnel.employee.assigned` — mark position filled
- `hcm.personnel.employee.terminated` — vacate position

## Rules Engine Rulesets (pre-configured)
1. `hcm.org.position.salary_within_grade` — min <= max on Position
2. `hcm.org.position.no_fill_inactive` — block filling inactive position
3. `hcm.org.compensation_grade.positive_amounts` — min_cents > 0

## Reports
1. **Headcount by Org Unit** — active employee count per unit with budget vs actual
2. **Open Positions** — unfilled active positions with salary band
3. **Compensation Grade Distribution** — employee count per grade with avg/min/max salary
