# SPEC — Contract Lifecycle Management (CLM) Plugin

**Module**: `pgappforge.plugins.erp.crm.contracts`
**Table prefix**: `clm_`
**Plugin key**: `crm.contracts` (registered in `ERP_GROUPS`)
**Depends on**: `foundation`, `finance.gl`, `crm.sales`

---

## Overview

End-to-end contract lifecycle management: template and clause library, contract
authoring with tracked versioning, sequential multi-role approval workflow,
e-signature integration (DocuSign, Adobe Sign, in-app, manual/wet ink),
obligation tracking with recurring rules, expiry and renewal alerting, and
IFRS 16 lease recognition schedule generation.

Targets legal, commercial, procurement, and finance teams managing NDAs, MSAs,
SLAs, employment agreements, property leases, loan agreements, and supplier
contracts.

---

## Key Entities

### ContractTemplate
Reusable template that seeds the body and standard clause list of new contracts.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID PK | |
| `tenant_id` | UUID | |
| `code` | String(30) | Unique per tenant; programmatic lookup key |
| `name` | String(200) | |
| `contract_type` | String | `NDA \| MSA \| SLA \| PURCHASE \| EMPLOYMENT \| LEASE \| LOAN \| PARTNERSHIP \| SERVICE \| OTHER` |
| `template_body` | Text | Markdown or HTML body with placeholder tokens |
| `standard_clauses` | JSONB | Ordered list of `clause_code` strings from ClauseLibrary |
| `jurisdiction` | String(10) | Default KE |
| `is_active` | Boolean | |

### ClauseLibrary
Organisation-managed library of reusable contract clauses.

| Field | Type | Description |
|-------|------|-------------|
| `clause_code` | String(30) | Unique per tenant |
| `clause_name` | String(200) | |
| `clause_type` | String(30) | e.g. LIMITATION_OF_LIABILITY, PAYMENT_TERMS, CONFIDENTIALITY |
| `clause_text` | Text | Standard clause wording |
| `is_standard` | Boolean | True = part of organisation standard; locked by legal |
| `risk_level` | String | `LOW \| MEDIUM \| HIGH` — drives approval routing |
| `approved_by`, `approved_at` | UUID / DateTime | Legal sign-off |

### Contract
Central CLM aggregate — the full lifecycle of a legal contract.

| Field | Type | Description |
|-------|------|-------------|
| `contract_number` | String(30) | Unique per tenant |
| `title` | String(300) | |
| `template_id` | UUID FK | Source template (nullable; contract may be bespoke) |
| `contract_type` | String | See ContractTemplate.contract_type |
| `counterparty_id` | UUID | Soft FK to Party master |
| `internal_owner_id` | UUID | Contract owner (employee) |
| `status` | String | See state machine |
| `effective_date`, `expiry_date` | Date | |
| `termination_notice_days` | Integer | Required notice period (default 30) |
| `auto_renew` | Boolean | |
| `renewal_notice_days` | Integer | Alert N days before auto-renewal kicks in (default 60) |
| `contract_value_cents` | BigInteger | Total contract value (nullable for open-ended contracts) |
| `currency_code` | String(3) | Default KES |
| `payment_terms_days` | Integer | Net payment days |
| `governing_law` | String(10) | Jurisdiction code e.g. KE, US_CA |
| `confidentiality_level` | String | `PUBLIC \| INTERNAL \| CONFIDENTIAL \| RESTRICTED` |
| `signed_at` | DateTime | When fully executed |
| `terminated_at`, `termination_reason` | DateTime / Text | |

### ContractVersion
Immutable snapshot of a contract body at a point in negotiation.

| Field | Type | Description |
|-------|------|-------------|
| `contract_id` | UUID FK | |
| `version_number` | Integer | Sequential per contract |
| `body` | Text | Full contract text at this version |
| `change_summary` | Text | Summary of changes from prior version |
| `created_by` | UUID | Employee who created this version |
| `status` | String | `DRAFT \| NEGOTIATING \| FINAL \| SUPERSEDED` |
| `changes_tracked` | JSONB | List of `{op, path, value}` JSON-Patch entries |

Rows are never deleted or body-updated — they are the immutable audit trail of
negotiation. A new version is created for every material change.

### ContractObligation
A trackable obligation arising from the contract terms.

| Field | Type | Description |
|-------|------|-------------|
| `obligation_type` | String | `PAYMENT \| DELIVERY \| REPORTING \| COMPLIANCE \| RENEWAL \| NOTICE \| OTHER` |
| `description` | Text | |
| `due_date` | Date | Specific due date; NULL for recurring obligations |
| `recurring_rule` | String(50) | iCalendar RRULE string e.g. `FREQ=MONTHLY;BYDAY=1` |
| `amount_cents` | BigInteger | Non-null for PAYMENT obligations |
| `responsible_party` | String | `OUR_COMPANY \| COUNTERPARTY` |
| `status` | String | `PENDING \| FULFILLED \| OVERDUE \| WAIVED` |
| `fulfilled_at` | DateTime | |
| `alert_days_before` | Integer | Days before due_date to trigger alert (default 14) |

### ContractApproval
One step in the sequential approval workflow.

| Field | Type | Description |
|-------|------|-------------|
| `approver_id` | UUID | |
| `approval_role` | String | `LEGAL \| FINANCE \| COMMERCIAL \| EXECUTIVE \| COMPLIANCE` |
| `status` | String | `PENDING \| APPROVED \| REJECTED \| SKIPPED` |
| `comments` | Text | |
| `decided_at` | DateTime | |
| `sequence_order` | Integer | Determines routing order |

### ESignatureRequest
Tracks one signatory's e-signature request.

| Field | Type | Description |
|-------|------|-------------|
| `signatory_id` | UUID | Party or employee UUID |
| `signatory_name`, `signatory_email` | String | |
| `signatory_role` | String(50) | e.g. Director, Authorised Signatory |
| `provider` | String | `DOCUSIGN \| ADOBE_SIGN \| LOCAL \| MANUAL` |
| `provider_envelope_id` | String(100) | DocuSign / Adobe Sign envelope reference |
| `status` | String | `SENT \| VIEWED \| SIGNED \| DECLINED \| EXPIRED` |
| `sent_at`, `signed_at` | DateTime | |

### LeaseSchedule
IFRS 16 lease recognition data for LEASE-type contracts.

| Field | Type | Description |
|-------|------|-------------|
| `contract_id` | UUID FK | UNIQUE — one per contract |
| `lease_type` | String | `FINANCE \| OPERATING` |
| `asset_description` | Text | Description of leased asset |
| `commencement_date` | Date | |
| `lease_term_months` | Integer | |
| `monthly_payment_cents` | BigInteger | |
| `discount_rate_pa` | Numeric(8,4) | Annual discount rate e.g. 0.1200 = 12% |
| `rou_asset_cents` | BigInteger | Right-of-use asset at commencement |
| `lease_liability_cents` | BigInteger | Present value of future lease payments |
| `initial_recognition_date` | Date | |

---

## State Machines

### Contract Status
```
DRAFT → UNDER_REVIEW → NEGOTIATION → PENDING_SIGNATURE → ACTIVE
                     ↘ (any stage) → CANCELLED
ACTIVE → SUSPENDED (force majeure / dispute)
SUSPENDED → ACTIVE (resolution)
ACTIVE → EXPIRED (expiry_date passed; automated by scheduler)
ACTIVE → TERMINATED (early termination; termination_reason required)
```

### ContractVersion Status
```
DRAFT → NEGOTIATING → FINAL → SUPERSEDED (when newer FINAL version created)
```

### ContractApproval Status
```
PENDING → APPROVED → (next step PENDING)
PENDING → REJECTED → (contract returns to UNDER_REVIEW or DRAFT)
PENDING → SKIPPED (if approver's role not required for this contract type)
```
All steps must be APPROVED (or SKIPPED) before the contract transitions to
`PENDING_SIGNATURE`.

### ESignatureRequest Status
```
SENT → VIEWED → SIGNED
     ↘ DECLINED (new request or manual intervention required)
     ↘ EXPIRED (provider timeout; resend required)
```
Contract transitions to `ACTIVE` when all `ESignatureRequest` rows are `SIGNED`.

---

## Events Emitted

| Event | Trigger |
|-------|---------|
| `clm.contract.created` | New contract saved |
| `clm.contract.submitted_for_approval` | Status → UNDER_REVIEW |
| `clm.contract.approved` | All ContractApproval rows APPROVED/SKIPPED |
| `clm.contract.rejected` | Any ContractApproval REJECTED |
| `clm.contract.signed` | All ESignatureRequests SIGNED; status → ACTIVE |
| `clm.contract.activated` | Status → ACTIVE |
| `clm.contract.expiring` | Expiry within 60 days (configurable) |
| `clm.contract.expired` | Status automatically → EXPIRED |
| `clm.contract.renewed` | Auto-renewal executed |
| `clm.contract.terminated` | Status → TERMINATED |
| `clm.obligation.due` | Obligation `due_date` within `alert_days_before` |
| `clm.obligation.overdue` | Obligation past `due_date` and still PENDING |
| `clm.lease.schedule_calculated` | LeaseSchedule created or recalculated |

## Events Consumed

| Event | Action |
|-------|--------|
| `crm.opportunity.won` | Auto-create contract stub from winning quote's CPQ template if configured |
| `ap.invoice.matched` | If invoice references a PAYMENT obligation, mark obligation FULFILLED |
| `ar.invoice.paid` | If invoice references a PAYMENT obligation on counterparty side, mark FULFILLED |

---

## GL Account Usage

| Posting | DR | CR | Notes |
|---------|----|----|-------|
| IFRS 16 initial recognition — operating lease | FIXED_ASSETS_COST (1600) | LEASE_LIABILITY (2500) | ROU asset and lease liability at commencement |
| Monthly lease payment | LEASE_LIABILITY (2500) + FINANCE_CHARGES (5600) | CASH_AND_NOSTRO (1011) | Principal reduction + interest |
| Depreciation of ROU asset | DEPRECIATION_EXPENSE (6400) | ACCUMULATED_DEPRECIATION (1610) | Monthly; managed by finance.assets plugin |
| Contract penalty paid | ACCRUED_EXPENSES (2100) | CASH_AND_NOSTRO (1011) | After AP invoice |

All GL postings via `GLService.post_simple_journal()` wrapped in `try/except`.

---

## Integration Points

| Plugin | How Used |
|--------|----------|
| `foundation` | Party master for counterparty_id; Currency |
| `crm.sales` | `opportunity.won` event triggers contract creation from CPQ output |
| `crm.cpq` | Quote template maps to ContractTemplate; CPQ line items become obligations |
| `finance.ap` | AP invoice matched to PAYMENT obligations marks them FULFILLED |
| `finance.ar` | AR invoice paid marks receivable PAYMENT obligations FULFILLED |
| `finance.gl` | IFRS 16 lease postings |
| `finance.assets` | ROU asset depreciation managed by fixed assets plugin |
| `hcm.personnel` | Employee lookup for `internal_owner_id` and approver IDs |

---

## World-Class Features vs Market Leaders

| Feature | PgAppForge | DocuSign CLM | Ironclad | SAP Ariba Contracts |
|---------|-----------|-------------|----------|---------------------|
| Clause library with risk levels | Yes | Yes | Yes | Yes |
| Template seeding with standard clauses | Yes | Yes | Yes | Yes |
| Sequential multi-role approval | Yes | Yes | Yes | Yes |
| DocuSign / Adobe Sign / in-app e-sig | Yes (advisory) | Native | Yes | Partial |
| Version tracking with JSON-Patch diffs | Yes | Yes | Yes | No |
| Obligation tracking with RRULE recurring | Yes | No | Partial | Yes |
| IFRS 16 lease schedule computation | Yes | No | No | No |
| Auto-renewal with configurable notice | Yes | Yes | Partial | Yes |
| GL posting on lease activation | Yes | No | No | Yes (via FI) |
| Expiry / obligation alerting | Yes | Yes | Yes | Yes |

---

## Architecture Decisions

**WHY `ContractVersion.body` stores the full text rather than diffs only**:
Legal enforceability requires that the exact text of the signed version is
retrievable without reconstruction. Diffs are stored additionally (`changes_tracked`)
for review tooling, but the authoritative record is the complete text. Storage
cost for contract text (typically 5–50KB) is trivial.

**WHY `ESignatureRequest.provider` includes `MANUAL`**: Not all counterparties
accept electronic signatures (government bodies, regulated industries). `MANUAL`
records wet-ink execution without blocking the digital workflow. The contract
can advance to `ACTIVE` once the manual row is marked `SIGNED` by an internal
administrator.

**WHY `ContractObligation.recurring_rule` uses iCalendar RRULE format**: RRULE is
the ISO-standard format for recurring event specifications (RFC 5545). It can
express monthly payment obligations, quarterly reporting deadlines, annual renewal
notices, and arbitrary complex schedules. Re-inventing this format would produce
something worse. The `icalendar` Python package parses RRULE strings for the
obligation scheduler.

**WHY `LeaseSchedule` is a separate table rather than columns on `Contract`**:
Most contracts are not leases. Adding 8+ IFRS 16 columns to `clm_contract` would
pollute the schema for every non-lease contract. The 1:1 relationship via
`UNIQUE(contract_id)` gives full normalisation without a `NOT NULL` constraint
forcing non-lease contracts to carry NULL columns.

**WHY `governing_law` is a free-form `String(10)` rather than an enum**: Legal
jurisdiction identifiers are not standardised across ERP systems. Using ISO 3166
country codes plus optional state codes (`US_CA`, `KE`, `GB_ENG`) gives a compact
and practical identification scheme without maintaining a taxonomy of all possible
legal systems. The alternative (an enum) would require a migration every time a
new jurisdiction is needed.

**WHY approval `sequence_order` starts at 0 and is an integer rather than using
insertion order**: Approval workflows are configurable per contract type. Finance
approval may need to run before Legal for low-value contracts but after Legal for
high-risk ones. Explicit `sequence_order` allows reordering without deleting and
recreating rows. Insertion order is fragile under concurrent edits.
