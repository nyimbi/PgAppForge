# Lunch Management — World-Class Comparison

## Our Implementation

- `LunchService` with explicit SQLAlchemy session injection; stateless instance methods
- Menu lifecycle: DRAFT → PUBLISHED; blocks publishing of empty menus
- Order placement: validates items against published menu, checks `available` flag per item, resolves names and prices from menu definition
- Subsidy engine: FIXED / PERCENTAGE / CAPPED types with `max_daily_cents` cap; entity-specific policies take priority over general via `entity_id DESC NULLS LAST` ordering
- `employee_pays_cents = max(0, subtotal - subsidy)` — employee cost never goes negative
- Order cancellation guarded to DRAFT/PLACED statuses and ownership-checked by `employee_id`
- `get_daily_summary()`: aggregates by item with qty and revenue breakdowns
- `get_employee_orders()`: date-range query returning order summaries with subsidy breakdown
- BPM action registered: `hcm.lunch.place_order`
- Domain events: `LunchOrderPlacedEvent`, `LunchSubsidyAppliedEvent`, `LunchOrderCancelledEvent`, `LunchSupplierDeliveredEvent`
- Supplier entity modelled (`LunchSupplier`) with delivery event
- Fire-and-forget event emission — missing event bus does not break order placement

## Benchmark: Odoo Lunch

| Feature | Odoo Lunch |
|---|---|
| Daily menu management per location | ✓ |
| Employee self-service order portal | ✓ |
| Supplier / vendor management | ✓ |
| Configurable subsidy (fixed, percentage) | ✓ |
| Order cutoff time enforcement | ✓ |
| Cash account / wallet per employee | ✓ |
| Delivery confirmation by supplier | ✓ |
| Per-location menu segregation | ✓ |
| Reporting: orders by supplier, cost per employee | ✓ |
| Mobile-friendly ordering UI | ✓ |
| Automatic payroll deduction of employee share | ✓ |
| Multi-tenant isolation | ✗ |
| CAPPED subsidy type | ✗ |
| BPM workflow trigger action | ✗ |

## Differentiation

**Gaps vs Odoo Lunch:**
- No order cutoff time — orders can be placed at any point while menu is PUBLISHED
- No employee wallet / cash account; `employee_pays_cents` computed but not debited from a balance
- No payroll deduction integration for employee cost recovery
- No per-location menu segregation within a tenant
- Reporting covers daily summary and per-employee history but no supplier-level cost reports

**Strengths:**
- CAPPED subsidy type (percentage with ceiling) is absent from Odoo Lunch
- Entity-specific subsidy policies allow different subsidiaries to have different rules
- `get_daily_summary()` is a single in-memory aggregation pass — no raw SQL aggregation needed
- Multi-tenant by design; Odoo Lunch is single-company
- Integer-cent arithmetic; Odoo uses float prices throughout
- BPM action enables automated lunch ordering from workflow triggers (e.g., new hire onboarding)
