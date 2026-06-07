# MRP Plugin — Design Comparison

## Scope

Materials Requirements Planning (MRP) for the PgAppForge ERP suite.

Covers: net requirements calculation, planned order generation, purchase requisition
recommendations, production order recommendations, one-level BOM explosion,
safety stock breach detection, and convert-to-PO traceability.

---

## Alternatives Considered

### Option A — Full MRP II with Capacity Planning (Rejected)

Full MRP II includes rough-cut and detailed capacity planning (CRP), shop-floor
scheduling, and work centre load balancing.

**Rejected because:**
- Requires production routing and work centre models not yet in scope.
- CRP adds 3–4× complexity with diminishing returns for the initial release.
- Production scheduling is a separate domain that belongs in a dedicated `production`
  plugin; MRP should remain a pure requirements engine.

**Retained for later:** CRP hook point is preserved via `ProductionOrderRecommendedEvent`
— the production plugin can subscribe and do capacity checks downstream.

### Option B — Safety Stock via Separate Nightly Job (Rejected)

Some MRP systems run safety stock checks as a cron job, separate from the MRP run.

**Rejected because:**
- Adds operational complexity (scheduler config, missed-run risk).
- `check_safety_stock` is a pure query — callers can invoke it on any schedule.
- The BPMActionRegistry pattern already supports timed workflow triggers without
  a separate daemon.

### Option C — Hard FK to Inventory StockLevel (Rejected)

Using a SQLAlchemy ForeignKey from `mrp_planned_order.product_id` to
`inv_product.id` would enforce referential integrity.

**Rejected because:**
- MRP must function when the inventory plugin is not loaded (decoupled deployment).
- Cross-plugin hard FKs create migration ordering problems.
- Soft FK (String product_id) with graceful `_get_current_stock` fallback is the
  established pattern across this codebase (see SCM, Production plugins).

### Option D — Store Planned Qty as Integer Cents (Rejected)

Some quantity fields in this codebase use Integer cents for monetary amounts.

**Rejected because:**
- MRP quantities are not monetary — they are product units (kg, ea, L).
- Fractional UOMs (0.5 kg, 2.75 L) are common in manufacturing.
- `Numeric(15,4)` is the correct type for quantity fields per codebase convention.

---

## Key Design Decisions

### Decision 1 — Session Passed Explicitly (No Flask Context)

All service methods accept `session: Any` — no `db.session` global, no
`current_app`, no Flask application context.

**Rationale:** Enables use in Celery workers, management commands, tests, and
non-Flask contexts without monkeypatching. Consistent with `InventoryService`,
`SCMService`, and all other ERP services in this codebase.

### Decision 2 — One-Level BOM Explosion Only

`run_mrp` explodes BOMs one level deep (finished good → direct components).
Multi-level explosion (components → sub-components) is not performed in the
initial release.

**Rationale:**
- Recursive multi-level explosion requires cycle detection and can produce very
  deep call stacks for complex BOMs.
- One level covers the majority of real-world manufacturing scenarios.
- Second-level components will be picked up in the next MRP run when the
  component planned orders are processed (classic MRP netting behaviour).

### Decision 3 — Planned Orders Retain Run Association

`MRPPlannedOrder.run_id` is a hard FK to `mrp_run.id` with CASCADE DELETE.
Old runs (and their planned orders) can be purged by deleting the run row.

**Rationale:** Historical MRP runs are valuable for plan-vs-actual comparison,
trend analysis, and auditing. The run association also allows reporting by run
without requiring a separate report table.

### Decision 4 — Demand Sources via Graceful Lazy Import

`_get_open_demand` and `_get_current_stock` use try/except ImportError blocks
rather than explicit plugin dependency declarations.

**Rationale:** Preserves independent deployability. An MRP-only deployment
(without inventory or demand planning plugins) still runs — it just sees zero
stock and zero forecast demand, producing safety-stock-driven planned orders.

### Decision 5 — `convert_to_po` Delegates to SCMService

`convert_to_po` calls `SCMService.create_purchase_order` (lazy import) and
falls back to a stub PO ID when SCM is not loaded.

**Rationale:** Avoids duplicating PO creation logic. The stub fallback preserves
testability and decoupled-deployment support.

---

## Schema Choices

| Column | Type | Rationale |
|---|---|---|
| `mrp_run.period` | VARCHAR(20) | Flexible period labels (monthly, weekly, fiscal) |
| `mrp_run.status` | VARCHAR(20) + CHECK | Enum via CHECK constraint, not a PG ENUM type (avoids migration pain) |
| `mrp_config.lot_size_qty` | Numeric(15,4) | Fractional lot sizes supported |
| `mrp_planned_order.required_qty` | Numeric(15,4) | Pre-rounding net requirement retained for audit |
| `mrp_planned_order.planned_qty` | Numeric(15,4) | Post-rounding actual planned quantity |
| `mrp_planned_order.converted_to_id` | VARCHAR(50) | Soft FK — PO or production order may be in a different plugin schema |

---

## Event Design

All events carry `run_id` to enable correlation across planned orders, requisitions,
and production recommendations from the same run. `SafetyStockBreachEvent` is
independent of runs — it can be emitted by `check_safety_stock` at any time.

`MRPRunCompletedEvent.duration_seconds` is a float (not Decimal) — it represents
wall-clock time, not a domain quantity subject to monetary precision rules.
