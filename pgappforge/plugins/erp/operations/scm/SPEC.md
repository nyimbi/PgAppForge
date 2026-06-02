# Supply Chain Management (SCM) Plugin — Specification

## Domain
`operations` — depends on `foundation`

## Entities

### Supplier (`scm_supplier`)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | |
| party_id | UUID | soft FK to erp_party.id |
| supplier_code | VARCHAR(50) | unique per tenant |
| name | VARCHAR(255) | denormalized from Party |
| rating | NUMERIC(3,1) | composite 0.0-10.0 |
| on_time_delivery_pct | NUMERIC(5,2) | rolling 12-month OTD % |
| quality_score | NUMERIC(5,2) | rolling 12-month acceptance % |
| lead_time_days | INTEGER DEFAULT 14 | default replenishment LT |
| minimum_order_value_cents | INTEGER | integer cents; PO below triggers warning |
| preferred | BOOL | preferred/approved source flag |
| payment_terms_days | INTEGER DEFAULT 30 | |
| currency_code | VARCHAR(3) | ISO 4217 |
| is_active | BOOL | |

**KPI computation:** `refresh_supplier_kpis()` derives OTD from `scm_shipment_tracking` history and quality score from `qc_inspection` history (soft dep). Composite rating = (OTD + quality) / 2 / 10.

### SupplierProduct (`scm_supplier_product`)
| Column | Type | Notes |
|---|---|---|
| supplier_id | UUID FK | CASCADE DELETE |
| product_id | UUID NOT NULL | FK to product master |
| supplier_sku | VARCHAR(100) | supplier's part number |
| lead_time_days | INTEGER | supplier-specific LT |
| minimum_quantity | NUMERIC(15,4) | MOQ |
| price_cents | INTEGER | unit price; integer cents; NEVER float |
| currency_code | VARCHAR(3) | |
| valid_from | DATE NOT NULL | price effective from |
| valid_to | DATE | NULL = open |
| is_preferred | BOOL | preferred source for this product |

**Unique constraint:** `(supplier_id, product_id, valid_from)`

### ShipmentTracking (`scm_shipment_tracking`)
| Column | Type | Notes |
|---|---|---|
| supplier_id | UUID FK | soft FK to scm_supplier |
| purchase_order_id | UUID | soft FK to ap_purchase_order |
| carrier | VARCHAR(100) NOT NULL | |
| tracking_number | VARCHAR(200) NOT NULL | unique per tenant+carrier |
| carrier_service | VARCHAR(100) | EXPRESS, OCEAN_FCL, etc. |
| origin_warehouse_id / destination_warehouse_id | UUID | app-managed |
| origin_address / destination_address | JSONB | {city, country_code, port} |
| shipped_at | TIMESTAMPTZ | |
| estimated_arrival | DATE | carrier ETA |
| actual_arrival | DATE | date received at destination |
| status | VARCHAR(15) | IN_TRANSIT→DELIVERED\|EXCEPTION\|RETURNED |
| events | JSONB | append-only milestone array |
| declared_value_cents | INTEGER | customs value; integer cents |
| incoterms | VARCHAR(10) | FOB, CIF, DDP, EXW |

**Immutability:** once DELIVERED, header is immutable. Corrections appended to `events` array.

## Business Rules
1. `price_cents` ≥ 0 (never negative)
2. `valid_to` ≥ `valid_from` when set
3. `supplier_code` unique per tenant, non-empty
4. Preferred supplier selection: preferred=True first, then lowest price_cents
5. OTD = on-time DELIVERED shipments / total DELIVERED shipments in period
6. Shipment events array is append-only (service reassigns list, never in-place mutate)

## API Endpoints
| Method | Path | Action |
|---|---|---|
| GET | /scm/suppliers/ | list |
| POST | /scm/suppliers/ | create |
| GET | /scm/suppliers/{id} | detail |
| PUT | /scm/suppliers/{id} | update |
| POST | /scm/suppliers/{id}/approve | set preferred=True |
| POST | /scm/suppliers/{id}/refresh-kpis | recompute KPIs |
| GET | /scm/supplier-products/ | list |
| POST | /scm/supplier-products/ | create |
| GET | /scm/supplier-products/{id} | detail |
| GET | /scm/shipments/ | list |
| POST | /scm/shipments/ | create |
| GET | /scm/shipments/{id} | detail + events |
| POST | /scm/shipments/{id}/add-event | append milestone |
| GET | /scm/reports/scorecard | Supplier Scorecard |
| GET | /scm/reports/overdue-shipments | Overdue Shipments |
| GET | /scm/reports/price-comparison | Price Comparison |

## Events Emitted
- `scm.supplier.created` / `approved` / `kpi_updated`
- `scm.supplier_product.created`
- `scm.shipment.created` / `status_changed` / `delivered` / `exception`

## Events Consumed
- `ap.invoice.approved` — trigger KPI refresh
- `pp.production_order.released` — may trigger replenishment PO
- `qc.inspection.failed` — feeds quality_score recalculation
