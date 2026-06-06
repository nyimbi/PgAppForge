# Repair Management — World-Class Comparison

## Our Implementation

- Stateless `RepairService` with explicit SQLAlchemy 2.x session injection; caller owns transactions
- Full state machine: RECEIVED → DIAGNOSING → AWAITING_PARTS → IN_REPAIR → QC → READY_FOR_PICKUP → RETURNED
- Cancellation guard: only pre-repair statuses cancellable (RECEIVED, DIAGNOSING, AWAITING_PARTS)
- Integer-cent monetary invariant enforced at assertion level (no float/Numeric)
- `WarrantyClaim` entity with purchase date, warranty expiry, and repair order linkage
- Collision-safe order reference generation (RPR-XXXXXX) with 5-attempt retry loop
- Domain events on every state transition: `RepairOrderCreatedEvent`, `RepairDiagnosedEvent`, `RepairCompletedEvent`, `RepairReturnedToCustomerEvent`, `WarrantyClaimCreatedEvent`
- `parts_used` stored as JSON list per order; `estimated_cost_cents` vs `actual_cost_cents` tracked separately
- Multi-tenant scoped via `tenant_id` on every query
- No Flask context dependency — pure Python, testable in isolation

## Benchmark: Odoo Repairs / ServiceMax

| Feature | Odoo Repairs | ServiceMax (Salesforce) |
|---|---|---|
| Work order lifecycle (receive → diagnose → repair → return) | ✓ | ✓ |
| Parts / components tracking with inventory deduction | ✓ | ✓ |
| Warranty claim management | ✓ | ✓ |
| Customer portal / self-service RMA | ✓ | ✓ |
| Field service scheduling + GPS dispatch | ✗ | ✓ |
| SLA / promised-by enforcement with alerts | ✓ | ✓ |
| Invoicing and payment linked to repair | ✓ | ✓ |
| Return merchandise authorization (RMA) workflow | ✓ | ✓ |
| IoT / predictive maintenance triggers | ✗ | ✓ |
| Mobile technician app | ✗ | ✓ |
| Multi-tenant isolation | ✗ (single-tenant) | ✓ (Salesforce orgs) |
| Programmatic domain events / event bus | ✗ | ✗ |

## Differentiation

**Gaps vs market leaders:**
- No inventory deduction on parts used — `parts_used` is a JSON snapshot, not linked to stock
- No SLA breach alerting or `promised_by` deadline enforcement at service layer
- No invoicing integration; `actual_cost_cents` stored but billing not triggered
- No customer-facing portal or self-service RMA initiation
- Field service dispatch and mobile technician app absent

**Strengths:**
- Fully headless and session-injectable — embeds cleanly in any Flask/async worker context
- Domain events on every transition enable downstream integrations without polling
- Integer-cent invariant eliminates an entire class of rounding bugs endemic in Odoo's `float` fields
- Multi-tenant by design; Odoo Community is single-tenant
- Warranty claim decoupled from repair order (can exist independently)
