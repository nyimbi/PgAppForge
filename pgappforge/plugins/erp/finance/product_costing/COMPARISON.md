# Product Costing Plugin — Competitive Comparison

## vs SAP Product Cost Planning (CO-PC-PCP) and Cost Object Controlling (CO-PC-OBJ)

### SAP CO-PC overview

SAP Product Cost Planning is a submodule of Controlling (CO). It operates through:
- **Cost estimates** (CK11N): multilevel BOM/routing explosion with quantity structure
- **Standard cost release** (CK24): marks one cost estimate as "legal" cost for a period
- **Material ledger** (ML): actual cost layering with parallel currencies
- **Variance categories**: price, quantity, resource-usage, mixed-price, lot-size, scrap, other

SAP CO-PC integrates deeply with PP (production planning), MM (materials management),
and FI-CO (financial accounting / controlling) via cost component splits and
reconciliation ledger entries.

### PgAppForge ProductCostingPlugin: capabilities

| Capability | SAP CO-PC | PgAppForge |
|---|---|---|
| Cost version types | Standard / Planned / Actual | STANDARD / PLANNED / ACTUAL |
| BOM explosion | Multilevel, automatic via MRP | Soft FK; caller provides exploded elements |
| Cost element types | 50+ cost component categories | MATERIAL / LABOR / OVERHEAD / SUBCONTRACTING / SETUP |
| Overhead rates | Cost sheet with percentage/quantity bases | `overhead_rate` Numeric on CostElement |
| Standard cost release | CK24 with period-end lock | `release_standard_cost()` — archives prior active |
| Actual cost computation | Material ledger (ML) with actual layers | `compute_actual_cost()` with bucket-level variance |
| Variance categories | Price, Qty, Resource, Mixed, Lot-size, Scrap | PRICE / QTY decomposition (extensible) |
| GL posting | Automatic via FI-CO account determination | `_post_variance_gl()` to account 5990; threshold-gated |
| Parallel currencies | Up to 3 (company/group/transaction) | Single currency per version |
| Cost component split | Full breakdown to lowest component | Bucket-level (material/labor/overhead) |
| Multi-plant | Native (plant/company code separation) | tenant_id scoping; plant = separate tenant or tag |
| Period-end lock | Costing run locks period | No period lock; effective_from date versioning |
| Work-in-process (WIP) | WIP calculation CO-PC-OBJ | WIP account 1410 in GL posting stub |

### Key design differences

**Intentional simplifications:**
- No multilevel BOM auto-explosion. Elements are provided by the caller (production planning
  domain). This keeps the costing plugin decoupled from inventory/BOM structure.
- Variance decomposition at bucket level (material/labor/overhead), not the full 7-category
  SAP model. The `price_variance_cents` and `qty_variance_cents` fields can be extended
  by subclassing `ProductionOrderActualCost` or populating them from an external calculator.
- Single active standard per product (no parallel valuation). Multi-currency use cases
  can store separate `CostVersion` records per currency.

**PgAppForge advantages:**
- Event-driven: `CostRollUpCompletedEvent`, `StandardCostReleasedEvent` feed downstream
  inventory revaluation and margin analytics without coupling.
- BPM-registered: `finance.costing.compute_actual` is callable from any workflow engine.
- Rules Engine pre-configured with 5 rulesets covering DRAFT-only element changes,
  empty version release guard, zero-cost warnings, unfavourable variance threshold,
  and HISTORICAL immutability — no custom ABAP required.
- PostgreSQL-native: JSONB-ready extension points, gen_random_uuid() PKs, TIMESTAMPTZ throughout.
- Full Python, testable with pytest-httpserver + real SA sessions; no SAP transport required.

---

## vs Oracle Cost Management Cloud (CMC)

### Oracle CMC overview

Oracle Cost Management Cloud is part of Oracle Fusion SCM. Key components:
- **Standard cost update**: mass update of frozen standard costs per inventory org
- **Cost accounting**: subledger accounting (SLA) integration with Oracle GL
- **Manufacturing variance**: production transaction-level variance calculation
- **Cost rollup**: BOM/routing rollup with optional simulation

### Comparison

| Capability | Oracle CMC | PgAppForge |
|---|---|---|
| Standard cost freeze | Per inventory org + period | Per tenant + effective_from date |
| BOM rollup | Automatic multilevel | Manual element addition; caller-driven |
| Subledger accounting | Oracle SLA with 5 transfer-type mappings | Direct GL journal stub (account 5990/1410) |
| Costing methods | Standard, Average, FIFO, FIFO layers | Standard only (Actual is variance-based) |
| Item cost components | Unlimited component splits | 5 types: MATERIAL/LABOR/OVERHEAD/SUBCONTRACTING/SETUP |
| Period close | Controlled by Inventory Period | Date-based effective_from versioning |
| Reporting | OTBI/BI Publisher | Custom via `get_cost_history()` + any renderer |
| API | REST v3 (Oracle) | Python service layer + BPM actions |
| Deployment | SaaS only | Self-hosted PostgreSQL |

### Key design differences

Oracle CMC's subledger accounting layer provides full double-entry for every cost
transaction type. PgAppForge posts a single DR/CR GL stub — adequate for ERP
implementations that route all accounting through a central GL service (e.g., the
`pgappforge.plugins.erp.finance.gl` plugin). Implementations requiring full SLA-style
event logs should extend `_post_variance_gl()` to emit an `AccountingEvent` consumed
by the GL plugin's journal engine.

Oracle's costing methods (Average, FIFO layers) are not supported in this plugin.
For moving-average or FIFO inventory costing, implement a separate `InventoryCostingPlugin`
that consumes `CostRollUpCompletedEvent` and maintains its own layer table.
