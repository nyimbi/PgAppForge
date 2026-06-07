# Revenue Recognition Module — Competitive Comparison

## ASC 606 / IFRS 15 Five-Step Model Coverage

| Step | Standard Requirement | PgAppForge RevRec | SAP RAR | Oracle RevPro | Zuora Revenue |
|------|---------------------|-------------------|---------|---------------|---------------|
| 1 | Identify contract | RevRecContract | ✓ | ✓ | ✓ |
| 2 | Identify obligations | RevRecObligation | ✓ | ✓ | ✓ |
| 3 | Determine transaction price | VariableConsideration | ✓ | ✓ | ✓ |
| 4 | Allocate to obligations | `_allocate()` SSP-based | ✓ | ✓ | ✓ |
| 5 | Recognize when satisfied | satisfy_obligation / recognize_period | ✓ | ✓ | ✓ |

---

## Feature Comparison

### SAP Revenue Accounting and Reporting (RAR)

**Architecture**: Bolt-on to SAP SD/FI. Requires RVIC (Revenue Integration Component), separate RAR system, and BAPI/IDoc integration pipelines to pull contract data from SD sales orders.

**Deployment**: On-premise SAP ERP or S/4HANA. Cloud variant (SAP RAR in BTP) still requires formal transport landscape.

**Integration lag**: SD → RAR synchronization is near-real-time via application jobs but introduces a separate system of record. Any CRM event (e.g., subscription activation) requires a multi-hop integration: CRM → SD → RAR.

**Configuration overhead**: Condition types, revenue types, POB (Performance Obligation) determination rules, and account determination all require Basis/FI-CO consultant involvement. Typical implementation: 6–18 months.

**Modification accounting**: Supported via RVIC events but the UI for reviewing catch-up adjustments is notoriously opaque; auditors frequently request manual reconciliation.

**Variable consideration**: Supported via constraint tables; updating estimates requires re-running batch jobs.

**Strengths**: Battle-tested on Fortune 500 deal complexity; native FI posting; strong disclosure reporting.

**Weaknesses**: No native SaaS/subscription event sourcing; requires SD orders even for pure-software contracts; $500K+ implementation costs common; painful to extend.

---

### Oracle Revenue Management and Billing (RMB) / RevPro

**Architecture**: Standalone cloud application (acquired from Softrax). Integrates with Oracle EBS, Fusion Cloud, and third-party ERP via flat-file or REST API feeds.

**Deployment**: SaaS (Oracle Cloud) or on-premise. Integration with non-Oracle ERPs requires custom ETL.

**Integration model**: Contract data flows in via Revenue Basis Document (RBD) API. CRM events require an intermediate integration layer (OIC or MuleSoft) to produce RBDs — another hop.

**SSP allocation**: Supports VSOE-era residual method and ASC 606 SSP; configurable via allocation rules UI. Solid but requires a separate RevPro admin to maintain rule sets.

**Performance**: Known to be slow on portfolios >100K contracts without dedicated tuning. Query performance degrades without careful partition strategy.

**Variable consideration**: Full support including probability-weighted expected value and most-likely-amount; constraint tracking with audit trail.

**Modification accounting**: Both prospective and cumulative catch-up supported; catch-up postings can be reviewed before GL transfer.

**Strengths**: Purpose-built for complex multi-element arrangements; strong audit trail; Oracle-native GL posting.

**Weaknesses**: $200K–$1M+ license + implementation; SaaS lock-in; integration to non-Oracle ERPs is always project work; no open-source extension points.

---

### Zuora Revenue (formerly Leeyo RevPro)

**Architecture**: SaaS-native, designed for subscription businesses. Contract data ingested via Zuora Billing → Zuora Revenue linkage or via standalone REST API.

**Integration model**: Best-in-class for Zuora Billing customers — subscription events (activate, amend, cancel, renew) flow directly into revenue contracts. For non-Zuora billing stacks, requires the Revenue Basis API plus middleware.

**Allocation**: SSP-based allocation engine with VSOE, BESP, and ASC 606 methods. SSP libraries maintained in UI.

**Modification accounting**: Prospective and cumulative catch-up; Zuora's "amendment waterfall" UI is genuinely good for subscription amendment scenarios.

**Variable consideration**: Supported; constraint toggle available.

**Disclosure reporting**: Strong ASC 606 disclosure package (disaggregated revenue, remaining performance obligations, etc.).

**Weaknesses**: Designed around Zuora Billing; without it, you're paying for a platform you can't fully exploit. Pricing is per-contract or per-revenue-line, which gets expensive at scale. No open extension model — customizations require Professional Services engagements.

---

## PgAppForge RevRec — Differentiators

### 1. Automatic Contract Creation from CRM Subscription Events

**The core problem with SAP RAR, Oracle RevPro, and Zuora Revenue (for non-Zuora billing)**:
Every one of them requires a separate integration pipeline to get contract data from the CRM or billing system into the rev rec engine. This is a multi-hop, multi-system architecture with inherent lag, reconciliation risk, and integration maintenance burden.

**What PgAppForge does differently**:

```
subscribe_to() → ["crm.subscriptions.activated", "crm.sign.request.completed"]
```

The RevRec plugin is a first-class subscriber to the CRM event bus. When a subscription is activated or a contract is e-signed, a `RevRecContract` is created automatically — same database transaction, no ETL, no message queue latency, no reconciliation gap. The five-step model executes in the same atomic unit as the CRM action.

This eliminates the "integration layer" entirely for in-platform CRM users. No separate bolt-on. No middleware. No batch jobs.

### 2. Integer-Cents Monetary Discipline Throughout

All competing products expose floating-point or Numeric(15,2) at some layer of their API — typically in data exports, flat-file imports, or intermediate calculation steps. Floating-point accumulation errors in multi-year revenue waterfall calculations are a known audit finding.

PgAppForge uses `BigInteger` (integer cents) end-to-end, with `Decimal` + `ROUND_HALF_UP` used only transiently during allocation arithmetic. The allocation invariant (`sum(allocated) == total`) is asserted in code, not just documented.

### 3. Allocation Correctness Guarantee

```python
def _allocate(total_cents, ssps) -> list[int]:
    # last obligation absorbs residual
    # sum(result) == total_cents, asserted
```

SSP-proportional allocation with last-item residual absorption means the sum of allocated amounts always equals the contract total — no rounding gap to manage, no periodic reconciliation jobs. SAP RAR and Oracle RevPro both have documented rounding reconciliation procedures in their implementation guides.

### 4. Open Extension Model

All three competitors lock customization behind Professional Services engagements or proprietary scripting environments. PgAppForge RevRec is plain Python: subclass `RevRecService`, override `_compute_period_revenue()` for custom recognition methods, add model columns via Alembic migrations, register new BPM actions. No vendor engagement required.

### 5. Unified Rules Engine

Contract cancellation rules, allocation validation, and over-recognition guards are implemented via the shared Rules Engine (`setup_rules()`), using the same rule syntax as every other plugin in the platform. Audit-visible, testable, and modifiable by the platform team without code deployment.

### 6. Postgres-Native Performance

`rev_contract`, `rev_obligation`, and `rev_journal_entry` use JSONB for extensible metadata, composite indexes on the exact query patterns used by `get_deferred_revenue_balance()` and `get_revenue_waterfall()`, and `gen_random_uuid()` PKs. No ORM-level N+1 in the waterfall query — it goes straight to a grouped aggregate.

### 7. Cost

Zero license cost. Implementation time for a standard subscription business: days, not months.

---

## When to Choose Each Product

| Scenario | Recommendation |
|---|---|
| SAP ERP shop, S/4HANA, complex multi-element hardware+software bundles | SAP RAR |
| Oracle Fusion/EBS shop, large enterprise, needs Oracle support contracts | Oracle RevPro |
| Pure Zuora Billing shop, subscription-first, willing to pay per-contract | Zuora Revenue |
| PgAppForge platform user, subscription or project-based revenue, need CRM integration without middleware | **PgAppForge RevRec** |
| Non-SAP/Oracle/Zuora ERP, Python team, open extension required | **PgAppForge RevRec** |

---

## Standards Compliance Notes

- **ASC 606**: FASB Accounting Standards Update 2014-09, effective for public entities fiscal years beginning after December 15, 2017.
- **IFRS 15**: Effective January 1, 2018. Substantially converged with ASC 606; key differences in licenses and variable consideration constraint thresholds.
- **Modification guidance**: ASC 606-10-25-18 through 25-21 / IFRS 15.18–21 — both PROSPECTIVE and CUMULATIVE_CATCH_UP methods implemented.
- **Variable consideration constraint**: ASC 606-10-32-11 / IFRS 15.56 — `constraint_applied` flag with `constrained_cents <= estimated_cents` enforced.
- **Disclosure**: ASC 606-10-50 / IFRS 15.110–128 — `get_deferred_revenue_balance()` and `get_revenue_waterfall()` provide the raw data for required disclosures; formatting to financial statement presentation is left to the reporting layer.
