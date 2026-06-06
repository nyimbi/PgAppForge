# Benefits Administration — World-Class Comparison

## Our Implementation

- **Full enrollment lifecycle**: PENDING → ACTIVE → TERMINATED / WAIVED state machine with duplicate-active-enrollment guard
- **Claims adjudication**: SUBMITTED → UNDER_REVIEW → APPROVED / DENIED / PARTIALLY_APPROVED with partial-approval amount support
- **Tiered payroll deductions**: resolves employee and employer premium cents from coverage-tier map (SINGLE/FAMILY/etc.) or flat-rate fallback; idempotent per-period generation guarded by UNIQUE constraint
- **YTD summary**: aggregates active enrollments, claims, and deductions per employee in a single structured dict
- **BPM integration**: `hcm.benefits.enroll` and `hcm.benefits.terminate` registered as BPM actions; domain events emitted on every lifecycle transition (enroll, terminate, claim submitted/adjudicated, deductions generated)

Kenya/Africa-specific features:
- KES-first currency handling (default in upstream compensation package)
- NHIF / NSSF deduction codes map naturally onto the flat-rate and tiered premium model
- Multi-tenant isolation on all queries (`tenant_id` on every row and every query)

Integration points:
- **Payroll / GL**: `generate_deductions` + `mark_deductions_processed` feed payrun pipeline; `BenefitDeductionsGeneratedEvent` carries total cents for GL posting
- **BPM / Workflow**: actions registered in `BPMActionRegistry`; events consumable by process engine listeners
- **Event bus**: `BenefitEnrolledEvent`, `BenefitTerminatedEvent`, `BenefitClaimSubmittedEvent`, `BenefitClaimAdjudicatedEvent`, `BenefitDeductionsGeneratedEvent`

---

## Benchmark: Workday / SAP SuccessFactors

| Feature | Status |
|---|---|
| Plan catalogue with eligibility rules (age, grade, FTE %) | ✗ |
| Life-event-triggered open enrolment windows | ✗ |
| ACA / regulatory compliance reporting | ✗ |
| EOB (Explanation of Benefits) document generation | ✗ |
| Carrier EDI 834 / 820 feed generation | ✗ |
| Dependent / beneficiary management | ✗ |
| FSA / HSA / COBRA administration | ✗ |
| Enrollment self-service portal for employees | ✗ |
| State machine + multi-tenant isolation | ✓ |
| Payroll deduction generation with idempotency | ✓ |
| Claims adjudication with partial approval | ✓ |
| Audit trail via domain events | ✓ |

---

## Benchmark: Darwinbox (African market leader)

Darwinbox offers a benefits module with flexible plan configuration, employee self-enrollment, and basic claims. Its Africa footprint is strong in Nigeria and East Africa.

| Feature | Status |
|---|---|
| Tiered premium model (SINGLE/FAMILY etc.) | ✓ (we match) |
| Multi-tenant SaaS architecture | ✓ (we match) |
| Mobile self-enrollment interface | ✗ (we lack front-end layer) |
| NHIF/NSSF statutory compliance pre-built | ✗ (our codes are generic; no pre-built statutory plan templates) |
| Claims pre-authorization workflow | ✗ |
| Panel (preferred provider) network management | ✗ |
| Automated broker / insurer portal integration | ✗ |

---

## Differentiation

Where we exceed the benchmark:
- Tighter BPM integration — benefit actions are first-class BPM nodes, enabling no-code process design around enrollment approvals
- Decimal-safe monetary arithmetic and idempotent deduction generation are more rigorous than typical mid-market systems
- Open event bus means GL, payroll, and audit consumers decouple cleanly; Workday's equivalents are proprietary

Remaining gaps:
- No eligibility rule engine (grade, age, FTE %-based plan eligibility)
- No dependent/beneficiary data model
- No statutory plan templates for NHIF, NSSF, SHA (Kenya 2024 health reform)
- No open-enrollment window concept or life-event trigger
- No employee-facing self-service enrollment UI
- No carrier or insurer integration layer
