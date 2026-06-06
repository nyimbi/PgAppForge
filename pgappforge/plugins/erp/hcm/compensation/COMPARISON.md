# Compensation Management — World-Class Comparison

## Our Implementation

- **Immutable salary ledger**: packages are never mutated after insert; superseding a package closes the prior record (`effective_to = new_effective_from - 1 day`) and inserts a new row — full history preserved
- **Full compensation breakdown**: `compute_total_package` resolves base salary, all active allowances (flat or %-of-basic), and ordered deductions into a structured dict with gross salary and CTC; all arithmetic via `Decimal(ROUND_HALF_UP)`
- **Allowance and deduction lifecycle**: assign/revoke with effective-date ranges; deduction priority ordering for cascaded deduction processing
- **Budget-gated review cycles**: `approve_review_cycle` enforces `committed_cents <= budget_pool_cents` before approval; raises `CompensationBudgetError` otherwise
- **BPM integration**: `hcm.compensation.assign_package` and `hcm.compensation.approve_review` as BPM actions; events emitted for package create/revise, allowance assign/revoke, deduction assign, and review cycle approval

Kenya/Africa-specific features:
- `currency_code` defaults to `KES`; field is present on every package row enabling multi-currency orgs (NGOs, multinationals)
- Allowance taxonomy (`allowance_type`, `is_taxable`, `is_pensionable`) maps directly onto KRA PAYE taxability rules and NSSF pensionable earnings definitions
- Pre-tax deduction flag (`is_pre_tax`) supports Kenya's Affordable Housing Levy and mortgage interest deduction treatment

Integration points:
- **Payroll**: `compute_total_package` is the canonical input to the payroll computation engine; taxable/pensionable flags feed PAYE and NSSF calculations
- **GL**: `CompensationPackageRevisedEvent` carries old/new salary delta for GL salary-cost re-mapping
- **BPM / Approvals**: review cycle BPM action enables manager → HR → Finance approval chains

---

## Benchmark: Workday / SAP SuccessFactors

| Feature | Status |
|---|---|
| Salary ledger with full history (no in-place mutation) | ✓ |
| Allowance/deduction effective-date ranges | ✓ |
| Budget pool enforcement on merit cycles | ✓ |
| Decimal-safe monetary arithmetic | ✓ |
| Grade / pay-band range validation (min/mid/max) | ✗ |
| Market pricing and compa-ratio reporting | ✗ |
| Equity / long-term incentive (LTI) administration | ✗ |
| Variable pay / bonus plan modelling | ✗ |
| Total rewards statement generation | ✗ |
| Pay equity analysis and gap reporting | ✗ |
| Merit matrix (performance × position-in-range) | ✗ |
| Compensation benchmarking (external survey data) | ✗ |

---

## Benchmark: Darwinbox (African market leader)

Darwinbox Compensation covers basic salary revision workflows, payroll integration, and a merit cycle UI. Its Africa differentiator is mobile-first access and local statutory compliance.

| Feature | Status |
|---|---|
| Salary revision with approval workflow | ✓ (we match via BPM) |
| Allowance/deduction management | ✓ (we match) |
| Effective-date-based history | ✓ (we exceed — full immutable ledger) |
| Mobile salary slip access | ✗ |
| Configurable approval matrix | ✗ (we rely on BPM engine; no built-in matrix UI) |
| Local statutory allowance pre-sets (transport, housing) | ✗ (generic codes; no pre-seeded KE/NG/GH definitions) |
| CTC modeller for offer letters | ✗ |

---

## Differentiation

Where we exceed the benchmark:
- Immutable ledger pattern is architecturally superior to Darwinbox's in-place salary update; point-in-time reconstruction is O(1) with correct `effective_from/to` query
- `compute_total_package` produces a fully decomposed, audit-ready breakdown that most mid-market systems only expose in payroll (not HR)
- Deduction priority ordering enables legally correct sequencing (e.g. garnishments before voluntary deductions)

Remaining gaps:
- No grade/pay-band range validation — the system accepts any `base_salary_cents` without checking against grade min/max
- No compa-ratio, market pricing, or benchmarking
- No variable pay or bonus plan model
- No total rewards statement
- No pre-seeded Kenyan statutory allowance/deduction definitions (transport KES 4,000 exemption, housing, etc.)
