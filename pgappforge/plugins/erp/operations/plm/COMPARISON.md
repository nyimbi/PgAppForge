# Product Lifecycle Management — World-Class Comparison

## Our Implementation

- Stateless `PlmService` with explicit SQLAlchemy 2.x session injection
- Product lifecycle stage: CONCEPT (initial); `lifecycle_stage` field on `PlmProduct`
- Version state machine: DRAFT → REVIEW → APPROVED → RELEASED
- `approve_version()` also updates `product.current_version` atomically
- BOM management: `create_bom()` auto-increments revision number per product+version
- BOM release: DRAFT|REVIEW → RELEASED with `BomReleasedEvent`
- Engineering Change Orders (ECO) with typed categories: DEFECT_FIX, DESIGN_CHANGE, COST_REDUCTION, SAFETY, REGULATORY
- ECO priorities: LOW, MEDIUM, HIGH, CRITICAL
- ECO approval accepts both SUBMITTED and REVIEW status (direct approval shortcut)
- Stage gate tracking stored in `product.metadata_["stage_gates"]` as timestamped audit log
- Domain events: `ProductVersionCreatedEvent`, `BomReleasedEvent`, `EcoSubmittedEvent`, `EcoApprovedEvent`, `StageGatePassedEvent`
- Product code uniqueness enforced per tenant

## Benchmark: Odoo PLM / PTC Windchill

| Feature | Odoo PLM | PTC Windchill |
|---|---|---|
| Product version control (draft → approved → released) | ✓ | ✓ |
| Bill of Materials with revision history | ✓ | ✓ |
| Engineering Change Orders (ECO) with approval workflow | ✓ | ✓ |
| Stage gate / phase-gate reviews | ✓ | ✓ |
| CAD / document file attachment and check-in/check-out | ✓ | ✓ |
| Component where-used analysis | ✓ | ✓ |
| Multi-level BOM explosion | ✓ | ✓ |
| Compliance / regulatory document tracking | ✓ | ✓ |
| Digital twin / IoT integration | ✗ | ✓ |
| MCAD/ECAD native integration | ✗ | ✓ |
| Parallel approval workflows | ✗ | ✓ |
| BOM comparison / diff across versions | ✗ | ✓ |
| Multi-tenant isolation | ✗ | Enterprise-only |
| Programmatic domain events | ✗ | ✗ |

## Differentiation

**Gaps vs market leaders:**
- No file/document attachment (CAD, drawings, specs) — a fundamental PLM capability
- BOM items stored as JSON; no relational component linkage or where-used queries
- No multi-level BOM explosion or indented BOM view
- Single-approver only; no parallel or sequential approval chains for ECO
- No compliance document tracking or REACH/RoHS attribute fields
- Stage gates stored in metadata JSON rather than a first-class entity

**Strengths:**
- ECO typed categories and priorities give structured change classification out of the box
- Stage gate audit trail is append-only and timestamped — safe for regulatory evidence
- BOM auto-revision numbering prevents manual revision conflicts
- `pass_stage_gate()` is idempotent-safe: appends rather than overwrites
- Lightweight enough to embed in non-manufacturing verticals (software product versioning)
- Integer-cent pricing fields avoid the float precision issues in Odoo's BOM cost rollup
