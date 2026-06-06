# Rental Management — World-Class Comparison

## Our Implementation

- Stateless `RentalService` with explicit SQLAlchemy 2.x session injection
- Asset availability conflict detection: SQL overlap query on PENDING/ACTIVE orders before booking
- State machine: PENDING → ACTIVE → COMPLETED (cancel: PENDING only)
- Rental amount computed as `days × daily_rate_cents` (integer cents, min 1 day)
- Prorated refund calculation on early return — stored in notes (informational)
- Damage charge event (`DamageDepositChargedEvent`) emitted when `damage_charge_cents > 0`
- Asset condition rating auto-decremented on damage
- `get_availability()` returns contiguous free date-ranges by subtracting blocked windows
- Domain events: `RentalOrderCreatedEvent`, `RentalStartedEvent`, `RentalReturnedEvent`, `DamageDepositChargedEvent`
- Multi-tenant scoped; deposit tracked separately (`deposit_amount_cents`, `deposit_status`)

## Benchmark: Odoo Rental / Rentman

| Feature | Odoo Rental | Rentman |
|---|---|---|
| Asset / equipment catalogue with daily rates | ✓ | ✓ |
| Availability calendar and conflict detection | ✓ | ✓ |
| Rental order lifecycle (quote → confirm → pickup → return) | ✓ | ✓ |
| Deposit management (hold, release, forfeit) | ✓ | ✓ |
| Damage assessment and charge | ✓ | ✓ |
| Prorated billing on early return | ✓ | ✓ |
| Recurring / long-term rental pricing tiers | ✓ | ✓ |
| Customer portal self-service booking | ✓ | ✓ |
| Online payment integration | ✓ | ✓ |
| Maintenance scheduling for assets | ✓ | ✓ |
| Barcode / RFID asset tracking | ✗ | ✓ |
| GPS / telemetry for tracked assets | ✗ | ✓ |
| Multi-tenant isolation | ✗ | SaaS-only |
| Domain event bus | ✗ | ✗ |

## Differentiation

**Gaps vs market leaders:**
- Deposit lifecycle is tracked by status field only; no hold/release/forfeit financial flow
- No pricing tiers (weekly, monthly discount rates); flat `daily_rate_cents` only
- Prorated refund is informational (notes string) — not linked to billing/credit note
- No asset maintenance scheduling or blackout dates
- No customer self-service portal or online booking

**Strengths:**
- `get_availability()` returns machine-readable date-range list, suitable for calendar API responses
- Integer-cent arithmetic throughout; Odoo Rental uses float-based `price_unit`
- Conflict detection is a single indexed SQL query — no application-level locking needed
- Asset condition rating provides a degradation signal for maintenance decisions
- Fully embeddable: no Celery, no ORM magic, no Flask globals
