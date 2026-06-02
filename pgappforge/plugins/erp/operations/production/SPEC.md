# Production Planning (PP) Plugin — Specification

## Domain
`operations` — depends on `foundation`

## Entities

### BillOfMaterials (`pp_bom`)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | multi-tenant isolation |
| product_id | UUID NOT NULL | FK to product master (app-managed) |
| version | VARCHAR(20) | e.g. "1", "2", "1.1" |
| effective_from | DATE NOT NULL | first valid date |
| effective_to | DATE | NULL = open-ended |
| status | VARCHAR(10) | DRAFT / ACTIVE / OBSOLETE |
| is_phantom | BOOL | collapse into parent during MRP explosion |
| uom | VARCHAR(20) | output unit of measure |
| yield_pct | NUMERIC(5,2) | expected yield (100 = no loss) |

**Business rules:**
- Only one ACTIVE BOM per product per tenant at any time
- Activating a BOM obsoletes the current ACTIVE version
- Production orders cannot be RELEASED without an ACTIVE BOM

### BOMLine (`pp_bom_line`)
| Column | Type | Notes |
|---|---|---|
| bom_id | UUID FK | CASCADE DELETE |
| component_product_id | UUID NOT NULL | FK to product master |
| quantity | NUMERIC(15,4) | base quantity per parent unit |
| uom | VARCHAR(20) | component UOM |
| position | INTEGER | sort order; unique per BOM |
| scrap_factor | NUMERIC(5,4) | 0.05 = 5% scrap; gross = qty × (1 + scrap) |
| is_critical | BOOL | shortage blocks order release |

### WorkCenter (`pp_work_center`)
| Column | Type | Notes |
|---|---|---|
| code | VARCHAR(50) | unique per tenant |
| name | VARCHAR(200) | |
| capacity_units_per_hour | NUMERIC(8,2) | throughput in output UOM/hr |
| overhead_rate_per_hour_cents | INTEGER | absorption rate; integer cents |
| gl_cost_center | VARCHAR(20) | GL cost centre code |
| is_active | BOOL | |

### ProductionOrder (`pp_production_order`)
| Column | Type | Notes |
|---|---|---|
| order_number | VARCHAR(50) | unique per tenant |
| product_id | UUID NOT NULL | |
| bom_id | UUID FK | BOM revision used |
| work_center_id | UUID FK | primary work center |
| planned_quantity | NUMERIC(15,4) | |
| produced_quantity | NUMERIC(15,4) DEFAULT 0 | |
| start_date / end_date | DATE | planned |
| actual_start_date / actual_end_date | DATE | |
| status | VARCHAR(15) | PLANNED→RELEASED→IN_PROGRESS→COMPLETED\|CANCELLED |
| planned_cost_cents | INTEGER | from BOM explosion |
| actual_cost_cents | INTEGER DEFAULT 0 | rolling actual |

### ProductionOrderLine (`pp_production_order_line`)
Component material requirements from BOM explosion.
`required_quantity` includes scrap allowance.
`issued_quantity` updated as stock is physically issued.
Status: PENDING → ISSUED → COMPLETE

### WorkOrderOperation (`pp_work_order_operation`)
Routing step: setup_time_minutes + run_time_minutes.
`actual_time_minutes` recorded on completion.
`labor_cost_cents` rolled into `ProductionOrder.actual_cost_cents`.
Status: PENDING → IN_PROGRESS → COMPLETED | SKIPPED

### DemandForecast (`pp_demand_forecast`)
| Column | Type | Notes |
|---|---|---|
| product_id | UUID NOT NULL | |
| warehouse_id | UUID | NULL = all warehouses |
| forecast_date | DATE NOT NULL | |
| forecast_quantity | NUMERIC(15,4) | |
| forecast_method | VARCHAR(15) | STATISTICAL / ML / MANUAL |
| confidence_interval | JSONB | {"lower": qty, "upper": qty} |
| created_by_model | VARCHAR(100) | model name/version |
| is_active | BOOL | False = superseded |

## Business Rules
1. BOM must be ACTIVE to release a production order
2. BOM scrap_factor ∈ [0, 1]
3. All quantities positive; amounts in integer cents
4. `produced_quantity` only set on COMPLETED transition
5. Operation `labor_cost_cents` accumulates into order `actual_cost_cents`
6. Phantom BOMs are never produced; components collapse into parent

## API Endpoints
| Method | Path | Action |
|---|---|---|
| GET | /pp/bom/ | list BOMs |
| POST | /pp/bom/ | create BOM |
| GET | /pp/bom/{id} | detail + lines |
| POST | /pp/bom/{id}/activate | DRAFT → ACTIVE |
| GET | /pp/work-centers/ | list work centers |
| POST | /pp/work-centers/ | create |
| GET | /pp/orders/ | list production orders |
| POST | /pp/orders/ | create with lines + operations |
| GET | /pp/orders/{id} | detail |
| POST | /pp/orders/{id}/release | PLANNED → RELEASED |
| POST | /pp/orders/{id}/start | RELEASED → IN_PROGRESS |
| POST | /pp/orders/{id}/complete | IN_PROGRESS → COMPLETED |
| POST | /pp/orders/{id}/cancel | → CANCELLED |
| POST | /pp/orders/{id}/issue-component | issue material |
| GET | /pp/forecasts/ | list forecasts |
| POST | /pp/forecasts/ | create forecast |
| GET | /pp/reports/schedule | Production Schedule |
| GET | /pp/reports/bom-cost-rollup | BOM Cost Roll-up |
| GET | /pp/reports/forecast-accuracy | Forecast Accuracy |

## Events Emitted
- `pp.bom.activated` / `pp.bom.obsoleted`
- `pp.production_order.released` / `started` / `completed` / `cancelled`
- `pp.component.issued`
- `pp.operation.completed`
- `pp.forecast.updated`

## Events Consumed
- `scm.shipment.delivered` — material availability refresh
- `qc.inspection.failed` — may block release of critical-component order
