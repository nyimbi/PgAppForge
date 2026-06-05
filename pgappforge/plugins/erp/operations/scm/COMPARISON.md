# SCM Plugin — Benchmark vs World-Class SCM Platforms

**Date:** 2026-06-04  
**Version benchmarked:** current (models.py + services.py as committed)

---

## Benchmark Peers

| Platform | Scope |
|---|---|
| SAP SCM / Ariba | Full P2P, demand planning, ATP, supplier collaboration portal |
| Oracle SCM Cloud | Procurement, order management, logistics, demand management |
| Blue Yonder (JDA) | Demand forecasting, replenishment, transportation |
| Kinaxis RapidResponse | Concurrent planning, S&OP, risk sensing |
| o9 Solutions | Integrated business planning, ML demand sensing, supply network |

---

## Current State Score: 22 / 100

### What exists

| Area | Status | Notes |
|---|---|---|
| Supplier master | Partial | Missing supplier_type enum, status enum (ACTIVE/QUALIFIED/SUSPENDED/BLACKLISTED), country_code, credit_limit_cents, min_order_qty |
| Supplier product catalogue | Partial | Exists, reasonable structure |
| Shipment tracking | Partial | Milestone events via JSONB; no PO linkage to scm-owned PO model |
| Purchase Requisition | **Missing** | Not present at all |
| Purchase Order + Lines | **Missing** | `purchase_order_id` column exists as soft FK string only |
| Goods Receipt + Lines | **Missing** | Referenced in `refresh_supplier_kpis` but no model |
| Supplier Invoice (3-way match) | **Missing** | No model, no service |
| Demand Forecast | **Missing** | No model, no service |
| GL integration | **Missing** | No DR/CR entries on PO confirmation or GRN |
| `create_supplier()` service | **Missing** | No creation service, only approve/KPI refresh |
| `create_purchase_requisition()` | **Missing** | |
| `approve_requisition()` | **Missing** | |
| `create_purchase_order()` | **Missing** | |
| `receive_goods()` | **Missing** | |
| `match_supplier_invoice()` | **Missing** | 3-way match not present |
| `get_supplier_performance()` | **Missing** | KPI refresh exists but no structured performance report |
| `run_demand_forecast()` | **Missing** | |
| `get_procurement_dashboard()` | **Missing** | |

---

## Gap Analysis by Category

### CRITICAL (blocks core procurement workflow)

1. **No Purchase Order model** — cannot track committed spend, no 3-way match
2. **No Goods Receipt model** — cannot confirm delivery, no inventory DR
3. **No Supplier Invoice model** — no AP matching, no payment trigger
4. **No Purchase Requisition model** — no approval workflow
5. **No POLine / GRNLine models** — no line-level qty tracking
6. **No GL integration** — no `inventory_in_transit` / `AP` / `inventory` entries
7. **Supplier model missing status enum** — cannot suspend/blacklist suppliers
8. **No `create_supplier()` service** — callers must manually construct model

### HIGH (degrades planning and analytics)

9. **No DemandForecast model** — no statistical replenishment
10. **No `run_demand_forecast()` service** — no MRP trigger capability
11. **No `get_procurement_dashboard()`** — no operational visibility
12. **No `get_supplier_performance()`** — structured KPI reporting absent
13. **Supplier missing `supplier_type`, `country_code`, `credit_limit_cents`** — incomplete master data
14. **No `approve_requisition()` service** — approval workflow gap

### MEDIUM (world-class differentiators)

15. **No incoterm on PO** — logistics costs untracked
16. **No payment_terms_days on PO** — AP terms propagation missing
17. **No `rejected_qty` / `lot_number` / `expiry_date` on GRN lines** — quality traceability absent
18. **No `confidence_pct` on DemandForecast** — forecast quality unquantified
19. **No `shipping_terms` on PO** — shipment handoff not modelled

### LOW (nice to have)

20. **No supplier collaboration portal events** — one-way data flow only
21. **No ATP (Available-to-Promise) integration** — no cross-plugin stock check on PO
22. **No multi-currency revaluation** — FX gains/losses not handled

---

## Post-Implementation Target Score: 88 / 100

Remaining gap (12 pts) covers ATP integration, supplier portal, multi-currency revaluation — out of scope for this sprint.
