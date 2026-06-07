# Assembly Management — Competitive Comparison

## vs Microsoft Dynamics 365 Business Central (NAV) Assembly Management

| Dimension | NAV Assembly Management | PgAppForge AssemblyPlugin |
|-----------|------------------------|--------------------------|
| **Assembly types** | Assemble-to-Stock (ATS) + Assemble-to-Order (ATO) | ATS (DRAFT/IN_PROGRESS/POSTED); ATO extension via entity_id scoping |
| **BOM structure** | Flat or multi-level (via Production BOM) | Flat BOM via AssemblyLine; multi-level via nested orders |
| **Component reservation** | Reservation system locks component qty pre-posting | Soft: actual_qty set at post time; reservation via InventoryService.allocate_stock() |
| **Cost method** | Standard or FIFO/LIFO/Avg via Item Ledger | Weighted average via InventoryService StockLevel.average_cost_cents |
| **Variance accounting** | Capacity variance + material variance (2 accounts) | Single material variance to GL 5990 (DR/CR) |
| **Finished goods posting** | Item Ledger Entry (positive) + Value Entry | StockMovement (direction=1, type=RECEIPT) via _update_stock_level |
| **Output journal** | Assembly Output Journal | post_assembly() as single atomic session call |
| **Partial posting** | Supported: post qty < planned qty | actual_qty per line; partial posting by setting actual_qty < planned_qty before calling post_assembly |
| **Serial/lot tracking** | Full — lot/serial required on assembly output | Inherits from InventoryService lot tracking; extend AssemblyLine with lot_number field |
| **Subcontracting** | Via Production Order + Routing | Not built-in; model as DRAFT order with external warehouse_id |
| **Capacity planning** | Integrated with Machine/Work Centers | Not in scope; integrate with MRP/EAM plugins |
| **Event model** | Ledger Entry (DB trigger) | DomainEventLog + in-process bus; consumed by downstream plugins |
| **Multi-entity** | Via NAV company isolation | entity_id column; IC mirroring via IntercompanyPlugin |
| **GL integration** | Automatic via posting groups | Soft import of GLService; non-fatal if GL plugin absent |
| **Reversal** | Undo Assembly Posting (creates compensating entries) | cancel_assembly() pre-post; post-post: create new order with negative output (compensating) |

### NAV features not in scope for v1
- Work center / routing (belongs in MRP plugin)
- Capacity variance (material variance only)
- Assembly-to-order ATP (available-to-promise) date calculation
- Kit explosion on sales order lines

---

## vs Odoo Manufacturing (Light / Assembly use case)

| Dimension | Odoo Manufacturing (mrp.production) | PgAppForge AssemblyPlugin |
|-----------|-------------------------------------|--------------------------|
| **Model** | mrp.production + mrp.bom + mrp.bom.line | AssemblyOrder + AssemblyLine (BOM inlined per order) |
| **BOM management** | Separate mrp.bom model with versions | BOM captured at order creation time in AssemblyLine rows; no versioned BOM master |
| **Work orders** | mrp.workorder — per-operation routing | Not modelled; single-step assembly |
| **Scrap** | mrp.scrap model; reduces finished qty | Modelled as AssemblyLine.actual_qty < planned_qty + variance posting |
| **By-products** | mrp.bom.byproduct | Not in v1; extend AssemblyOrder with by_products JSONB |
| **Serial/lot traceability** | stock.lot linked to move lines | Inherits from InventoryService; extend AssemblyLine with lot_number |
| **Manufacturing orders states** | draft → confirmed → progress → to_close → done | DRAFT → IN_PROGRESS → POSTED (maps cleanly) |
| **Real-time qty tracking** | stock.quant updated on production | StockLevel updated via _update_stock_level (same transaction) |
| **Cost computation** | Standard price or average cost (stock.valuation.layer) | Weighted average via StockLevel.average_cost_cents; variance to GL 5990 |
| **Analytic accounting** | analytic.account on production | entity_id scoping; extend with analytic_account_id if needed |
| **Unbuild** | mrp.unbuild model (reverse assembly) | Not in v1; implement as new order consuming the FG product and producing components |
| **Replenishment trigger** | Make-to-order route + reorder rules | InventoryService._check_reorder() on component issue |
| **ORM** | Odoo ORM (Python, custom framework) | SQLAlchemy 2.x + PgAppForge BasePlugin |
| **API** | Odoo JSON-RPC + XML-RPC | PgAppForge REST via ModelRestApi; events via DomainEventLog |
| **Multi-company** | res.company isolation | tenant_id + entity_id; IC via IntercompanyPlugin |

### Odoo features deferred to future iterations
- Versioned Bill of Materials (mrp.bom with version field)
- Routing / Work Centers (mrp.routing.workcenter)
- By-products / co-products
- Unbuild orders
- Flexible consumption (backflushing vs. manual pick)
