# Warehouse Management Plugin — Specification

**Domain**: operations  
**Plugin name**: warehouse  
**Depends on**: foundation, inventory  
**Table prefix**: `wms_`

---

## Entities

### PickList
Batch of pick instructions for a single outbound order, assignable to a warehouse operative.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| warehouse_id | UUID FK → inv_warehouse | |
| order_type | VARCHAR(20) | SALES_ORDER / TRANSFER / PRODUCTION |
| order_id | UUID | FK to SO, transfer, or production order |
| status | VARCHAR(20) | PENDING → ASSIGNED → IN_PROGRESS → COMPLETED / CANCELLED |
| assigned_to | UUID nullable | FK to ab_user — picker |
| priority | INTEGER | lower = higher priority |
| due_by | TIMESTAMPTZ | |

Status machine: `PENDING → ASSIGNED → IN_PROGRESS → COMPLETED | CANCELLED`

### PickListLine
Individual pick instruction within a PickList. `quantity_picked` is incremented by `record_pick()`.

| status | Meaning |
|--------|---------|
| PENDING | Not started |
| PARTIAL | quantity_picked < quantity_requested |
| COMPLETED | quantity_picked ≥ quantity_requested |
| SKIPPED | Cannot pick (location empty / product unavailable) |

### PutawayTask
Directs received stock from GRN to storage location.

- `suggested_location_id`: system recommendation (PICK first, then BULK)
- `actual_location_id`: where operative placed the stock
- Completing a task creates a TRANSFER StockMovement (RECEIVE location → actual_location)

Status: `PENDING → IN_PROGRESS → COMPLETED | CANCELLED`

### StockCount
Physical inventory count run header.

| count_type | Scope |
|------------|-------|
| FULL | All SKUs in warehouse |
| CYCLE | Rolling subset (e.g. A-class this week) |
| SPOT | Specific products or locations |

Status: `DRAFT → IN_PROGRESS → COMPLETED → APPROVED`

**APPROVED counts are immutable.** To correct post-approval, create a new SPOT count.

`total_variance_value_cents`: aggregate financial impact, integer cents.

### StockCountLine
Expected vs. counted quantity per SKU per location.

`variance = counted_quantity − expected_quantity`  
`variance_value_cents = |variance| × average_cost_cents` (signed: negative = loss)

---

## Business Rules

1. **Pick completion**: All PickListLines must be COMPLETED or SKIPPED before `complete_picklist()` is called.
2. **Stock issuance**: `complete_picklist()` calls `InventoryService.pick_and_ship()` which posts ISSUE StockMovements and decrements StockLevel.
3. **Putaway**: `complete_putaway()` creates a TRANSFER StockMovement from RECEIVE location to `actual_location_id`. Falls back gracefully if no RECEIVE location is configured.
4. **Count lock**: Count lines cannot be recorded (counted_quantity set) once status is COMPLETED or APPROVED.
5. **Count approval**: `InventoryService.approve_stock_count()` posts COUNT_ADJUSTMENT movements for all lines with `variance ≠ 0`. Only COMPLETED counts can be approved.
6. **Auto-putaway**: When `WMS_AUTO_CREATE_PUTAWAY=True`, a PutawayTask is automatically created on every `inventory.stock.received` event (best-effort, non-blocking).
7. **Priority**: PickList with lower `priority` value is worked first. Due-by ordering is secondary sort key.

---

## Service Methods

| Method | Description |
|--------|-------------|
| `create_picklist(order_id, order_type, lines, warehouse_id, session)` | Create PickList + PickListLines |
| `assign_picklist(picklist_id, user_id, session)` | PENDING → ASSIGNED |
| `record_pick(picklist_id, line_id, qty_picked, session)` | Record quantity picked; advances to IN_PROGRESS |
| `complete_picklist(picklist_id, session)` | Validate completion, call InventoryService.pick_and_ship |
| `create_putaway_task(grn_id, product_id, qty, session)` | Create task with suggested location |
| `complete_putaway(task_id, actual_location_id, completed_by, session)` | Create TRANSFER movement, mark task COMPLETED |
| `suggest_putaway_location(product_id, warehouse_id, session)` | Return best available PICK/BULK location ID |
| `start_stock_count(warehouse_id, count_type, session)` | Delegates to InventoryService.run_stock_count |
| `record_count(count_id, line_id, counted_qty, session)` | Record physical count, compute variance |
| `complete_stock_count(count_id, session)` | Validate all lines counted, set COMPLETED |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/wms/picklists/` | List pick lists (filters: warehouse, status, assigned_to, order_type) |
| GET | `/wms/picklists/<id>` | Pick list detail with lines |
| POST | `/wms/picklists/` | Create pick list |
| POST | `/wms/picklists/<id>/assign` | Assign to operative |
| POST | `/wms/picklists/<id>/lines/<lid>/pick` | Record quantity picked |
| POST | `/wms/picklists/<id>/complete` | Complete and issue stock |
| POST | `/wms/picklists/<id>/cancel` | Cancel pick list |
| GET | `/wms/putaway/` | List putaway tasks |
| GET | `/wms/putaway/<id>` | Task detail |
| POST | `/wms/putaway/` | Create putaway task |
| POST | `/wms/putaway/<id>/complete` | Complete with actual location |
| GET | `/wms/counts/` | List stock counts |
| GET | `/wms/counts/<id>` | Count detail with lines |
| POST | `/wms/counts/` | Start new count |
| POST | `/wms/counts/<id>/lines/<lid>/record` | Record operative's count |
| POST | `/wms/counts/<id>/complete` | Mark COMPLETED (pending approval) |
| POST | `/wms/counts/<id>/approve` | Approve and post COUNT_ADJUSTMENT movements |
| GET | `/wms/reports/picking-throughput` | Completed pick lists per day |
| GET | `/wms/reports/putaway-backlog` | Pending putaway tasks by warehouse |
| GET | `/wms/reports/count-variance` | Variance summary for a count |

---

## Events

### Emitted
| Event | Trigger |
|-------|---------|
| `wms.picklist.created` | New PickList created |
| `wms.picklist.completed` | All lines picked, stock issued |
| `wms.putaway.completed` | Stock directed to final location |
| `wms.stock_count.started` | Count moved to IN_PROGRESS |
| `wms.stock_count.ready` | Count COMPLETED, pending approval |

### Consumed
| Event | Handler |
|-------|---------|
| `inventory.stock.received` | Auto-create PutawayTask (if WMS_AUTO_CREATE_PUTAWAY=True) |
| `inventory.stock.low` | Optional pick priority escalation |

---

## Reports

1. **Picking Throughput** (`/wms/reports/picking-throughput?warehouse_id=…&days=30`)  
   Completed pick lists grouped by day and order type. Measures warehouse throughput velocity.

2. **Putaway Backlog** (`/wms/reports/putaway-backlog?warehouse_id=…`)  
   PENDING + IN_PROGRESS putaway tasks grouped by warehouse and status. Identifies receiving bottlenecks.

3. **Stock Count Variance** (`/wms/reports/count-variance?count_id=…`)  
   Lines with non-zero variance for a specific count. Shows SKU, expected, counted, variance quantity and financial impact in cents. Grand total variance value at bottom.

---

## Rules Engine Rulesets (pre-configured)

| Ruleset | Model | Trigger | Action |
|---------|-------|---------|--------|
| `wms.picklist.require_warehouse` | PickList | on_before_create | raise_error if warehouse_id is NULL |
| `wms.picklist.valid_order_type` | PickList | on_before_create | raise_error if order_type not in valid set |
| `wms.stock_count.no_reopen_approved` | StockCount | on_before_update | raise_error if APPROVED → any other status |
| `wms.putaway.positive_quantity` | PutawayTask | on_before_create | raise_error if quantity ≤ 0 |

---

## Cross-Plugin Composability

```
AP Plugin                    Inventory Plugin           Warehouse Plugin
─────────────────────────    ──────────────────────     ────────────────────────
APGoodsReceipt (CONFIRMED) → receive_stock()          → StockReceivedEvent
                                                        ↓ (subscribed)
                                                        PutawayTask created
                                                        ↓ complete_putaway()
                                                        TRANSFER StockMovement
                                                        ↓
                                                        StockLevel updated

Sales order placed         → allocate_stock()
                           → PickList created          → assign → pick → complete
                                                        ↓ complete_picklist()
                                                        ISSUE StockMovements
                                                        ↓ StockIssuedEvent
```
