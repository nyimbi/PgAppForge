# Inventory Plugin — Specification

**Domain**: operations  
**Plugin name**: inventory  
**Depends on**: foundation  
**Table prefix**: `inv_`

---

## Entities

### ProductCategory
Hierarchical product taxonomy via self-referencing `parent_id`. Supports unlimited nesting. Each category carries an optional `gl_account` that routes inventory valuation journal entries.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | multi-tenant partition key |
| code | VARCHAR(30) | unique per tenant |
| name | VARCHAR(200) | |
| parent_id | UUID nullable FK → self | NULL = root |
| gl_account | VARCHAR(20) | inventory asset account |
| is_active | BOOLEAN | |

### Product
SKU master record. Monetary fields (`base_price_cents`, `cost_price_cents`, `standard_cost_cents`) are **integer cents — never float**. Physical dimensions stored as JSONB to avoid column sprawl. Tracking flags (`is_lot_tracked`, `is_serial_tracked`, `is_batch_managed`) enforce validation on every StockMovement.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| sku | VARCHAR(100) | unique per tenant |
| barcode | VARCHAR(50) | unique per tenant when set |
| name | VARCHAR(255) | |
| description | TEXT | |
| category_id | UUID FK → ProductCategory | |
| brand | VARCHAR(100) | |
| uom | VARCHAR(20) | EACH, KG, L, M, BOX, … |
| weight_grams | INTEGER | grams, not kg |
| dimensions_cm | JSONB | {length, width, height} |
| base_price_cents | INTEGER | published list price |
| cost_price_cents | INTEGER | last known purchase cost |
| currency_code | CHAR(3) | ISO 4217 |
| reorder_point | NUMERIC(15,4) | triggers replenishment |
| reorder_quantity | NUMERIC(15,4) | default order quantity |
| lead_time_days | INTEGER | supplier lead time |
| is_lot_tracked | BOOLEAN | lot_number required on movement |
| is_serial_tracked | BOOLEAN | serial_number required |
| is_batch_managed | BOOLEAN | lots grouped by batch |
| is_hazardous | BOOLEAN | |
| shelf_life_days | INTEGER | drives expiry validation |
| valuation_method | VARCHAR(20) | FIFO / LIFO / WEIGHTED_AVG / STANDARD_COST |
| standard_cost_cents | INTEGER | used when valuation_method=STANDARD_COST |
| gl_inventory_account | VARCHAR(20) | balance-sheet asset account |
| gl_cogs_account | VARCHAR(20) | P&L expense account |
| is_active | BOOLEAN | |

### Warehouse
Physical or virtual storage facility.

| warehouse_type | Description |
|----------------|-------------|
| OWNED | Company-owned facility |
| 3PL | Third-party logistics provider |
| CONSIGNMENT | Supplier-owned stock held at company site |
| VIRTUAL | In-transit, notional, or drop-ship tracking |

### WarehouseLocation
Sub-location within a warehouse (aisle/rack/bin).

| location_type | Description |
|---------------|-------------|
| BULK | Full-pallet storage |
| PICK | Forward pick face |
| RECEIVE | Inbound staging |
| SHIP | Outbound dispatch bay |
| QC | Quality inspection hold |
| QUARANTINE | Blocked / rejected stock |
| STAGING | Cross-dock staging |

### StockLevel
Aggregated position per product / warehouse / location. For lot-tracked products, one row per (product, warehouse, location, lot). Maintains:
- `quantity_on_hand` — physical quantity
- `quantity_reserved` — allocated to unfulfilled orders
- `quantity_available` = `quantity_on_hand` − `quantity_reserved`
- `quantity_in_transit` — supplier-shipped, not yet received
- `average_cost_cents` — weighted average unit cost (integer cents)

### StockMovement (IMMUTABLE)
Event-sourced ledger of every inventory transaction. **Never update rows.** To correct an error, insert a compensating movement.

| movement_type | direction | Description |
|---------------|-----------|-------------|
| RECEIPT | +1 | Goods received from supplier |
| ISSUE | -1 | Stock issued to order |
| TRANSFER | +1 | Internal location transfer |
| ADJUSTMENT | ±1 | Manual quantity correction |
| RETURN | +1 | Customer return to stock |
| WRITE_OFF | -1 | Damaged / expired write-off |
| COUNT_ADJUSTMENT | ±1 | Posted after approved stock count |

`reference_type` links to source document: `PO` / `SO` / `TRANSFER` / `MANUAL`.

---

## Business Rules

1. **Lot tracking**: If `Product.is_lot_tracked=True`, every StockMovement must supply `lot_number`. Service raises `InventoryServiceError` otherwise.
2. **Serial tracking**: If `Product.is_serial_tracked=True`, every movement must supply `serial_number`.
3. **No negative stock**: `issue_stock()` raises `InsufficientStockError` if `quantity_on_hand < requested`.
4. **Immutable movements**: StockMovement rows are never updated or deleted.
5. **Weighted average cost**: On RECEIPT, `average_cost_cents` is recomputed as `(old_qty × old_avg + delta × unit_cost) / new_qty`, rounded half-up to integer cents.
6. **Reorder alerts**: After every ISSUE, if `quantity_available ≤ reorder_point`, `StockLowEvent` is emitted.
7. **Stock count approval**: COUNT_ADJUSTMENT movements are only posted after an authorised approver calls `approve_stock_count()`. APPROVED counts are immutable.
8. **Standard cost**: When `valuation_method=STANDARD_COST`, `standard_cost_cents` is used for ISSUE valuation instead of average cost.

---

## Service Methods

| Method | Description |
|--------|-------------|
| `receive_stock(grn_id, session)` | Post RECEIPT movements from confirmed GRN, update StockLevel |
| `allocate_stock(order_id, order_type, lines, session)` | Reserve stock (increment quantity_reserved) |
| `issue_stock(order_id, order_type, lines, session)` | Post ISSUE movements, decrement quantity_on_hand |
| `pick_and_ship(picklist_id, session)` | Convenience façade: calls issue_stock for completed pick lines |
| `run_stock_count(warehouse_id, session)` | Freeze StockLevel snapshot into new StockCount + lines |
| `approve_stock_count(count_id, approved_by, session)` | Post COUNT_ADJUSTMENT movements, set count APPROVED |
| `get_stock_valuation(warehouse_id, as_of_date, session)` | Return total value (current or historical reconstruction) |
| `calculate_reorder_suggestions(tenant_id, session)` | Return products below reorder_point |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/inv/categories/` | List product categories |
| POST | `/inv/categories/` | Create category |
| PUT | `/inv/categories/<id>` | Update category |
| GET | `/inv/products/` | List products (search, category, active filter) |
| GET | `/inv/products/<id>` | Product detail |
| POST | `/inv/products/` | Create product |
| PUT | `/inv/products/<id>` | Update product |
| POST | `/inv/products/<id>/deactivate` | Deactivate product |
| GET | `/inv/warehouses/` | List warehouses |
| GET | `/inv/warehouses/<id>` | Warehouse detail with locations |
| POST | `/inv/warehouses/` | Create warehouse |
| PUT | `/inv/warehouses/<id>` | Update warehouse |
| GET | `/inv/warehouses/<id>/locations` | List locations |
| POST | `/inv/warehouses/<id>/locations` | Add location |
| GET | `/inv/stock/` | Stock positions (filters: tenant, warehouse, location, low_stock) |
| GET | `/inv/stock/<product_id>` | All positions for a product |
| GET | `/inv/movements/` | Movement log (filters: product, warehouse, type, date range) |
| GET | `/inv/movements/<id>` | Movement detail |
| GET | `/inv/reports/valuation` | Stock Valuation report |
| GET | `/inv/reports/reorder` | Reorder Suggestions report |
| GET | `/inv/reports/movement-history` | Product Movement History report |

---

## Events

### Emitted
| Event | Trigger |
|-------|---------|
| `inventory.stock.received` | GRN posted via `receive_stock()` |
| `inventory.stock.issued` | Order fulfilled via `issue_stock()` |
| `inventory.stock.transferred` | Internal transfer movement created |
| `inventory.stock.adjusted` | Manual ADJUSTMENT movement posted |
| `inventory.stock.count_approved` | Stock count approved |
| `inventory.stock.low` | Product crossed reorder_point |
| `inventory.product.created` | New product registered |
| `inventory.product.deactivated` | Product marked inactive |

### Consumed
| Event | Handler |
|-------|---------|
| `ap.invoice.matched` | Updates in-transit quantity for PO-linked stock |

---

## Reports

1. **Stock Valuation** (`/inv/reports/valuation?warehouse_id=…`)  
   Total inventory value by product/location. Supports `as_of` date for historical reconstruction from StockMovement log.

2. **Reorder Suggestions** (`/inv/reports/reorder?tenant_id=…`)  
   Products with `quantity_available ≤ reorder_point`, sorted by SKU. Includes estimated replenishment cost.

3. **Movement History** (`/inv/reports/movement-history?product_id=…&days=90`)  
   Chronological movement log for a product with cost impact per movement.

---

## Rules Engine Rulesets (pre-configured)

| Ruleset | Model | Trigger | Action |
|---------|-------|---------|--------|
| `inv.product.require_uom` | Product | on_before_create | raise_error if uom empty |
| `inv.product.positive_costs` | Product | on_before_create | raise_error if cost_price_cents < 0 |
| `inv.product.reorder_consistency` | Product | on_before_create | raise_error if reorder_point > 0 and reorder_quantity ≤ 0 |
| `inv.stock_movement.positive_quantity` | StockMovement | on_before_create | raise_error if quantity ≤ 0 |
| `inv.stock_movement.direction_constraint` | StockMovement | on_before_create | raise_error if direction ∉ {1, -1} |
