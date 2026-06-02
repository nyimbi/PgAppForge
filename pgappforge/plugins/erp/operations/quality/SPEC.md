# Quality Management (QC) Plugin — Specification

## Domain
`operations` — depends on `foundation`

## Entities

### InspectionPlan (`qc_inspection_plan`)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | |
| product_id | UUID NOT NULL | FK to product master |
| inspection_type | VARCHAR(15) | INCOMING / IN_PROCESS / OUTGOING |
| name | VARCHAR(200) NOT NULL | plan title |
| sampling_pct | NUMERIC(5,2) | 0.01-100.00; 100 = 100% inspection |
| acceptance_criteria | JSONB | dimensions, visual, AQL config |
| is_active | BOOL | |
| version | VARCHAR(20) | plan revision |

**Unique constraint:** `(tenant_id, product_id, inspection_type)` — one active plan per product per type.

**acceptance_criteria schema example:**
```json
{
  "dimensions": [{"attr": "length_mm", "min": 99.5, "max": 100.5}],
  "visual": ["no_scratches", "no_dents"],
  "aql": {"level": "II", "acceptable_quality_limit": 1.0},
  "auto_ncr": true
}
```
`auto_ncr: true` causes `record_results()` to auto-open an NCR on failure.

### QualityInspection (`qc_inspection`)
| Column | Type | Notes |
|---|---|---|
| reference_type | VARCHAR(100) NOT NULL | e.g. APGoodsReceipt, ProductionOrder |
| reference_id | VARCHAR(64) NOT NULL | ID of triggering document |
| plan_id | UUID FK | NULL = ad-hoc |
| inspected_quantity | NUMERIC(15,4) | sample pulled (≤ lot qty) |
| accepted_quantity | NUMERIC(15,4) DEFAULT 0 | |
| rejected_quantity | NUMERIC(15,4) DEFAULT 0 | |
| inspector_id | UUID | FK to ab_user |
| inspection_date | DATE NOT NULL | |
| status | VARCHAR(15) | PENDING→IN_PROGRESS→PASSED\|FAILED |
| findings | JSONB | [{criterion, measured, result, note}] |
| overall_result | VARCHAR(10) | PASS / FAIL / CONDITIONAL |
| disposition | VARCHAR(20) | ACCEPT / REJECT / REWORK / USE_AS_IS |

**Constraint:** `accepted_quantity + rejected_quantity ≤ inspected_quantity`

### NonConformanceReport (`qc_ncr`)
| Column | Type | Notes |
|---|---|---|
| ncr_number | VARCHAR(50) | unique per tenant; auto-generated NCR-YYYYMMDD-HHMMSS |
| source_type | VARCHAR(15) | SUPPLIER / PRODUCTION / CUSTOMER |
| source_reference_id | VARCHAR(64) | triggering document ID |
| inspection_id | UUID FK | linked inspection (optional) |
| product_id | UUID NOT NULL | |
| quantity_affected | NUMERIC(15,4) NOT NULL | |
| batch_lot_number | VARCHAR(100) | |
| severity | VARCHAR(10) | CRITICAL / MAJOR / MINOR |
| description | TEXT NOT NULL | |
| status | VARCHAR(15) | OPEN→ANALYSIS→CORRECTION→CLOSED |
| root_cause | TEXT | set in ANALYSIS phase |
| corrective_action | TEXT | set in CORRECTION phase |
| preventive_action | TEXT | systemic prevention |
| owner_id | UUID | FK to ab_user |
| due_date | DATE | required for CRITICAL |
| closed_at | TIMESTAMPTZ | set on CLOSED transition |
| supplier_claim_value_cents | INTEGER | integer cents; SUPPLIER source only |

**CAPA state machine:** OPEN → ANALYSIS → CORRECTION → CLOSED (strict sequential)
**Immutability:** CLOSED NCRs are not re-edited; reopen by emitting NCRReopenedEvent

## Business Rules
1. One active InspectionPlan per (product, inspection_type) per tenant
2. `accepted + rejected ≤ inspected` (enforced by Rules Engine)
3. `inspected_quantity > 0`
4. NCR description must not be blank
5. CRITICAL NCRs must have `due_date` set
6. `root_cause` required before NCR can be CLOSED
7. NCR status transitions are strictly sequential (OPEN→ANALYSIS→CORRECTION→CLOSED)
8. `auto_ncr: true` in acceptance_criteria triggers automatic NCR creation on FAILED inspection

## API Endpoints
| Method | Path | Action |
|---|---|---|
| GET | /qc/plans/ | list inspection plans |
| POST | /qc/plans/ | create |
| GET | /qc/plans/{id} | detail |
| PUT | /qc/plans/{id} | update |
| GET | /qc/inspections/ | list |
| POST | /qc/inspections/ | create (auto-computes sample qty) |
| GET | /qc/inspections/{id} | detail |
| POST | /qc/inspections/{id}/start | PENDING → IN_PROGRESS |
| POST | /qc/inspections/{id}/record-results | record findings → PASSED/FAILED |
| GET | /qc/ncrs/ | list NCRs |
| POST | /qc/ncrs/ | open NCR |
| GET | /qc/ncrs/{id} | detail |
| POST | /qc/ncrs/{id}/advance | advance status with CAPA data |
| GET | /qc/reports/inspection-summary | Inspection pass/fail rates |
| GET | /qc/reports/ncr-aging | Open NCR aging by severity |
| GET | /qc/reports/supplier-quality | Supplier quality trend |

## Events Emitted
- `qc.inspection.created` / `started` / `passed` / `failed`
- `qc.ncr.opened` / `analysis_started` / `correction_issued` / `closed` / `reopened`

## Events Consumed
- `ap.grn.posted` — triggers INCOMING inspection if plan exists
- `pp.production_order.completed` — triggers OUTGOING inspection if plan exists
- `scm.shipment.delivered` — may trigger INCOMING inspection
