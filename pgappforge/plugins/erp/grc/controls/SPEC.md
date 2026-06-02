# GRC Controls Plugin — SPEC

## Domain
`grc` — governance, risk & compliance

## Purpose
Manages internal control frameworks (SOX, ISO 27001, NIST, GDPR, HIPAA,
PCI DSS), periodic control testing with evidence tracking, and the
segregation-of-duties (SoD) conflict matrix.

## Entities

### ControlFramework
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| name | VARCHAR(20) | SOX \| ISO27001 \| NIST \| GDPR \| HIPAA \| PCI_DSS |
| version | VARCHAR(20) | e.g. '2022' |
| description | TEXT | |
| is_active | BOOL | |
| created_at / updated_at | TIMESTAMPTZ | |

UNIQUE (tenant_id, name, version)

### Control
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| framework_id | UUID FK ControlFramework | |
| control_code | VARCHAR(50) | unique per tenant; e.g. SOX-CC6.1 |
| control_name | VARCHAR(500) | |
| control_objective | TEXT | |
| control_type | VARCHAR(20) | PREVENTIVE \| DETECTIVE \| CORRECTIVE |
| frequency | VARCHAR(20) | CONTINUOUS \| DAILY \| MONTHLY \| QUARTERLY \| ANNUAL |
| automated | BOOL | |
| owner_id | UUID FK erp_party | employee responsible |
| status | VARCHAR(10) | ACTIVE \| INACTIVE |
| created_at / updated_at | TIMESTAMPTZ | |

UNIQUE (tenant_id, control_code)

### ControlTest *(immutable after completion)*
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| control_id | UUID FK Control | |
| test_date | DATE | |
| tester_id | UUID FK erp_party | |
| test_result | VARCHAR(15) | EFFECTIVE \| INEFFECTIVE \| NOT_TESTED |
| evidence_urls | JSONB | list of storage URLs |
| deficiencies_noted | TEXT | |
| remediation_due | DATE | required if deficiencies_noted set |
| created_at / updated_at | TIMESTAMPTZ | |

### SegregationOfDuties
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| role_a | VARCHAR(200) | |
| role_b | VARCHAR(200) | |
| conflict_type | VARCHAR(200) | human-readable description |
| risk_level | VARCHAR(10) | LOW \| MEDIUM \| HIGH \| CRITICAL |
| is_active | BOOL | |
| created_at / updated_at | TIMESTAMPTZ | |

UNIQUE (tenant_id, role_a, role_b) — bidirectional; (A,B) implies (B,A)

## Business Rules
1. control_type: PREVENTIVE | DETECTIVE | CORRECTIVE only.
2. frequency: CONTINUOUS | DAILY | MONTHLY | QUARTERLY | ANNUAL only.
3. test_result: EFFECTIVE | INEFFECTIVE | NOT_TESTED only.
4. remediation_due requires deficiencies_noted to be non-empty.
5. SoD pairs are bidirectional; check both (A,B) and (B,A).
6. role_a ≠ role_b (a role cannot conflict with itself).
7. ControlTest rows are immutable after recording.

## Events Emitted
- `grc.control.created`
- `grc.control.status_changed`
- `grc.control_test.completed`
- `grc.control_test.deficiency_noted`
- `grc.sod.conflict_detected`

## Events Consumed
- `identity.policy.changed` — re-evaluate SoD when roles change
- `party.created` — populate control ownership candidates

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /grc/controls/frameworks/ | List frameworks |
| POST | /grc/controls/frameworks/ | Create framework |
| GET | /grc/controls/ | List controls |
| POST | /grc/controls/ | Create control |
| POST | /grc/controls/{id}/status | Activate/deactivate |
| GET | /grc/controls/{id}/tests | List tests for control |
| POST | /grc/controls/{id}/tests | Record test result |
| GET | /grc/controls/sod/ | List SoD rules |
| POST | /grc/controls/sod/ | Register SoD rule |
| GET | /grc/controls/sod/check | Check role pair conflict |
| GET | /grc/controls/reports/effectiveness | Control effectiveness summary |
| GET | /grc/controls/reports/deficiencies | Open deficiencies |
| GET | /grc/controls/reports/sod-matrix | Full SoD matrix |

## Rules Engine Rulesets (4)
1. `control.type_valid` — control_type validation
2. `control_test.result_valid` — test_result validation
3. `control_test.remediation_requires_deficiency` — data integrity
4. `sod.bidirectional_uniqueness` — role_a ≠ role_b

## Cross-plugin Composability
- **Upstream**: foundation, platform.identity
- **Downstream**: grc.privacy (consent controls), grc.sustainability (ESG governance)
