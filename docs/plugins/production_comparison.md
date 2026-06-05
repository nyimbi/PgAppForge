# Production Planning Plugin — Competitive Comparison

Compares the PgAppForge Production Planning (PP) plugin against SAP PP,
Oracle Manufacturing Cloud, and Infor CloudSuite Manufacturing (CSM).

---

## Feature Matrix

| Capability | PgAppForge PP | SAP PP | Oracle Mfg Cloud | Infor CSM |
|---|---|---|---|---|
| **Bill of Materials** | BillOfMaterials + BOMLine, versioned, phantom support | Multi-level BOM with alternative BOMs | Item structure (single/multi-level) | Multi-level BOM with engineering change |
| **BOM versioning** | version string, effective_from/to, DRAFT→ACTIVE→OBSOLETE | Change numbers + validity dates | Effectivity dates per structure | Engineering change orders |
| **Work Centers** | WorkCenter: capacity_units_per_hour, overhead_rate_per_hour_cents, GL cost center | Work center with available capacity formulas | Resource with shift calendars | Work centers with shift patterns |
| **Production Orders** | ProductionOrder: PLANNED→RELEASED→IN_PROGRESS→COMPLETED | Process/production orders (PP-PI/PP-DIS) | Work orders | Production orders |
| **Component reservation** | ProductionOrderLine derived from BOM explosion | Goods reservation on order release | Material reservations | Pick lists from BOM |
| **Routing / Operations** | WorkOrderOperation: setup + run time, labor cost capture | Routing operations per work center | Operations with resources | Routings with operations |
| **BOM explosion** | explode_bom(): single-level with scrap factor, recursive-capable | Multi-level MRP explosion (MD01) | Supply chain planning explosion | Multi-level explosion |
| **MRP / Planning** | DemandForecast model + explode_bom; no MRP net-change engine | Full MRP/MPS (MD01N, MS01) | Oracle ASCP / Planning Cloud | Infor M3 MRP |
| **Production output** | record_production_output(): qty + scrap, GL WIP→FG posting | GR against production order (MIGO 101) | Move transactions | Production reporting |
| **Costing** | calculate_production_cost(): materials + labor + overhead; GL DR FG 1170 CR WIP 1160 | Product cost estimate (CK11N) + actual order settlement | Cost collection + variance analysis | Standard/actual costing |
| **OEE** | get_oee(): Availability × Performance × Quality from op/order data | Plant Maintenance KPIs + OEE add-on | Not native (requires OAC) | Infor EAM OEE |
| **Production schedule** | get_production_schedule(): utilization per work center per date range | Capacity planning (CM01-CM38) | Resource schedule in Gantt | Scheduling board |
| **Demand forecasting** | DemandForecast: STATISTICAL/ML/MANUAL, confidence intervals | Demand Management (MP30/MP38) | Oracle Demantra / Planning Cloud | Infor Demand Planning |
| **Event-driven integration** | Domain events (released/started/completed/cancelled) | IDocs / BAdIs | Business events | ION events |
| **Multi-tenant** | tenant_id on every row | Client-based separation | Business unit separation | Tenant (multi-site) |

---

## Architecture Differences

### PgAppForge vs SAP PP

SAP PP is the benchmark for discrete manufacturing ERP.  Its MRP engine (MD01N) runs
net-change or regenerative planning across the full product structure, considering
stock, open orders, safety stock, and lot sizing rules.  PgAppForge's `explode_bom()`
is single-level; callers build multi-level MRP by calling it recursively, which is
adequate for small to mid-scale manufacturers but not a substitute for SAP's MRP engine.

SAP uses movement types to drive all inventory and WIP postings automatically.
PgAppForge makes GL postings explicit in `record_production_output()` and
`calculate_production_cost()` via the lazy-import GL service — simpler to reason
about, at the cost of requiring the GL plugin.

SAP's production order settlement (KO88) reallocates variances between standard cost
and actual cost to a variance account.  PgAppForge posts actual cost directly to
finished goods (1170) and clears WIP (1160) with no separate variance account;
variance analysis is left to the GL reporting layer.

### PgAppForge vs Oracle Manufacturing Cloud

Oracle Manufacturing Cloud separates discrete manufacturing (work orders), process
manufacturing (batch), and outsourced manufacturing.  PgAppForge's ProductionOrder is
discrete-only; process manufacturing (yield tracking, co-products, by-products) is not
modelled.

Oracle's resource scheduling integrates with Oracle Fusion Supply Chain Planning for
constraint-based scheduling.  PgAppForge provides `get_production_schedule()` for
visibility but has no constraint-based scheduler — the work center utilization metric
is informational.

Oracle captures production exceptions and alerts via a supervisor dashboard in the
Execution module.  PgAppForge exposes this through the domain event bus: consumers
subscribe to `pp.production_order.*` events for alerting.

### PgAppForge vs Infor CloudSuite Manufacturing

Infor CSM targets mid-market to large discrete and mixed-mode manufacturers with deep
shop floor execution (SFE), quality, and engineering change management.  Its strength
is deep industry templates (aerospace, automotive, industrial equipment).

PgAppForge has no engineering change order (ECO) workflow.  BOM version promotion
(DRAFT→ACTIVE) is manual via `activate_bom()`; there is no sign-off or parallel
approval chain.  Adding ECO requires a workflow plugin.

Infor's scheduling board provides visual drag-and-drop scheduling with finite capacity.
PgAppForge's `get_production_schedule()` returns data for a UI to render but provides
no finite-capacity scheduling algorithm.

---

## OEE Calculation Notes

PgAppForge `get_oee()` computes the three OEE factors as follows:

- **Availability** = actual_minutes / planned_minutes (from WorkOrderOperation records).
  Clamped at 100% — overtime is not counted as availability gain.
- **Performance** = produced_qty / planned_qty.  This is a simplified throughput-based
  measure.  True OEE performance should use (ideal_cycle_time × units_produced) /
  actual_run_time; this requires `ideal_cycle_time` on WorkCenter, which is not yet
  modelled.
- **Quality** = produced_qty / (produced_qty + scrapped_qty).  Scrap is read from
  `ProductionOrder.metadata_.scrap_entries` populated by `record_production_output()`.

World-class OEE benchmarks: ≥85% OEE, ≥90% availability, ≥95% performance, ≥99.9% quality.

---

## Gaps vs Enterprise Manufacturing ERP

The following capabilities are absent from the current PgAppForge PP plugin and would
be required for full enterprise deployment:

1. **MRP net-change engine**: compute net requirements across the full product structure
   considering open orders, stock, safety stock, and re-order policies.
2. **Finite capacity scheduling**: assign operations to time slots respecting work center
   calendar and shift capacity.
3. **Engineering Change Orders (ECO)**: versioned BOM changes with approval workflow and
   effectivity management.
4. **Process manufacturing**: batch recipes, co-products, by-products, yield step recording.
5. **Subcontracting**: send components to supplier for an operation and receive back
   semi-finished goods (outside processing).
6. **Variance settlement**: post material/labor/overhead variances to separate GL accounts
   after order close, rather than rolling all costs into finished goods.
7. **Shop floor execution (SFE)**: operator-facing mobile/kiosk UI for operation
   confirmation, quality checks at station, and labor booking.
8. **Ideal cycle time on WorkCenter**: required for accurate OEE Performance factor
   calculation per ISO 22400.
