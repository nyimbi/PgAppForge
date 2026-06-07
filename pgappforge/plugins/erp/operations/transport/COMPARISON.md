# Transport Management Plugin — Design Comparison

## vs. Odoo (stock.picking / delivery.carrier)

| Dimension | Odoo | This plugin |
|---|---|---|
| Data model | `stock.picking` (movement) + `delivery.carrier` (provider) | `Shipment` (logistics) + `Carrier` + `FreightRate` (rate card) |
| Freight cost | Computed via delivery product price or third-party API call | Computed from zone-pair + weight-bracket rate table; pure SQL |
| Rate types | Carrier-level price list (product variant) | PER_KG / FLAT / PER_UNIT / PER_CBM per zone pair |
| Status FSM | 13-state picking flow tightly coupled to inventory | 6-state: PLANNED→BOOKED→DISPATCHED→IN_TRANSIT→DELIVERED→CANCELLED |
| Multi-tenancy | Company-level isolation | `tenant_id` UUID on every row; hard constraint |
| Tracking | Chatter / mail.thread messages | `tracking_events` JSONB append-only log; no messaging dependency |
| POD | Custom field | First-class `pod_ref` column on Shipment |
| Carrier performance | Third-party module or manual | Computed from delivered shipments; `on_time_delivery_rate_pct` auto-updated |
| BPM integration | Automated actions | `BPMActionRegistry` (`ops.transport.create_shipment`, `ops.transport.dispatch`) |

## vs. SAP TM (Transportation Management)

| Dimension | SAP TM | This plugin |
|---|---|---|
| Granularity | Freight order / freight booking / freight unit | Single `Shipment` row; source document advisory ref |
| Rate engine | Charge calculation engine (complex rules) | `FreightRate` table: zone + weight bracket + rate_type; `compute_freight()` |
| Tendering | Full tendering sub-module | Delegates to Strategic Sourcing plugin |
| Carrier selection | Carrier selection profile + scoring | Manual `book_carrier()` with best-rate lookup |
| Events | SAP event management | Domain events via `foundation.events` + in-process bus |
| Tracking | Event management / visibility server | Append-only JSONB `tracking_events` |

## Design decisions

### Why JSONB tracking_events instead of a separate table?
Tracking events are append-only, never queried individually, and their cardinality is low
(10–50 per shipment). JSONB avoids a JOIN on every shipment fetch and keeps the schema simple.
When analytics are needed, `jsonb_array_elements` can unnest efficiently in PostgreSQL.

### Why advisory FKs for driver_id / vehicle_id?
The Fleet plugin is optional. Storing UUID strings avoids a hard FK constraint that would
prevent transport from loading without fleet. The service layer reads the string for event
payloads; join logic lives in reporting queries, not the core service.

### Why separate FreightRate table instead of carrier-level pricing?
Rate cards are multi-dimensional (zone pair × weight bracket × effective date). A separate
table allows multiple overlapping brackets, effective-date versioning, and rate_type
polymorphism without schema changes. `compute_freight()` picks the tightest bracket.

### Status FSM rationale
PLANNED → BOOKED enforces that cost is computed before dispatch.
BOOKED → DISPATCHED requires an explicit driver assignment.
Both DISPATCHED and IN_TRANSIT can transition to DELIVERED — IN_TRANSIT is set externally
(e.g. by a tracking webhook) and delivery can be recorded from either state.

## Limitations / future work

- No consolidation (LTL grouping of multiple orders into one shipment).
- No multi-leg routing (transshipment points).
- No carrier API integration (FedEx/DHL/Sendcloud) — rate computation is internal only.
- `volume_cbm` is stored but PER_CBM rates fall back to weight when volume is zero.
  A volume-mandatory validation could be added as a config flag.
- Carrier performance does not weight by shipment value or volume.
