# Variable Pay Plugin — Competitive Comparison

## Overview

The Variable Pay plugin covers the full incentive compensation lifecycle:
tiered commission plans with accelerators, per-employee quota assignment,
cumulative attainment tracking, tier-by-tier commission calculation,
and a PENDING → APPROVED → PAID payout state machine.

---

## Feature Matrix

| Feature | PgAppForge Variable Pay | SAP SuccessFactors Incentive Mgmt | Salesforce Spiff | Xactly Incent | Commissionly |
|---|---|---|---|---|---|
| Tiered commission rates | Yes (JSONB tiers, unlimited) | Yes | Yes | Yes | Yes (3-tier max on base plan) |
| Accelerator above threshold | Yes (multiplier on above-threshold portion) | Yes | Yes | Yes | No (paid add-on) |
| Multi-plan types | SALES_COMMISSION / BONUS / PROFIT_SHARE / RETENTION / SPOT_AWARD | Yes | Sales only | Yes | Sales only |
| Per-period quota assignment | Yes (flexible period strings: Q1, monthly, H1) | Yes (fiscal period) | Yes | Yes | Monthly only |
| Cumulative attainment | Yes (additive record_attainment calls) | Yes | Yes | Yes | Yes |
| Calculation breakdown audit | Yes (full tier-by-tier JSONB) | Partial (summary) | Yes | Yes | No |
| Payout approval workflow | Yes (PENDING → APPROVED → PAID) | Yes (configurable) | Yes | Yes | Manual |
| Payrun integration | Yes (payrun_id link on CommissionPayout) | Yes (payroll connector) | Export only | Export only | Export only |
| BPM action hooks | Yes (calculate_commission, approve_payout) | Workflow engine | No | No | No |
| Rules Engine guardrails | Yes (5 idempotent rulesets) | Partial | No | No | No |
| Domain events (CDC) | Yes (6 events, durable DomainEventLog) | Webhook only | Webhook only | Webhook only | No |
| Multi-tenant | Yes (tenant_id on all tables) | Separate orgs | Separate orgs | Separate orgs | No |
| PostgreSQL JSONB storage | Yes | Proprietary | Proprietary | Proprietary | MySQL |
| Open source / self-hosted | Yes (MIT) | No (SaaS) | No (SaaS) | No (SaaS) | No (SaaS) |

---

## Design Decisions

### Tiers as JSONB, not rows
Storing plan tiers in JSONB rather than a separate `vp_plan_tier` table
eliminates N+1 loads and makes plan cloning O(1). The tradeoff is that
tier queries are not directly SQL-indexable, but attainment analytics are
served from `vp_quota.attainment_pct` (a stored numeric column), not from
tier boundaries.

### Cumulative attainment, not snapshot
`record_attainment()` adds to `attained_cents` rather than replacing it.
This matches real-world sales ops where attainment is reported incrementally
(weekly pipeline closes, monthly revenue recognition). A full overwrite API
can be built on top by passing `actual - quota.attained_cents`.

### Accelerator on above-threshold portion only
The accelerator bonus is computed only on the portion of quota above
`accelerator_threshold_pct`, multiplied by `(multiplier - 1)`. This matches
the industry-standard "kicker" model where reps earn their normal tier rate
plus an increment. Applying the full multiplier to the entire commission
(SAP model) creates a discontinuity at the threshold that incentivises
quota sandbagging.

### Calculation → Payout auto-created
`calculate_commission()` always creates a `CommissionPayout` in PENDING status
so downstream approvers have an immediate action item. Recalculation requires
cancelling the existing payout first — enforced by the unique constraint on
`vp_payout.calculation_id`.

---

## Gaps vs Enterprise Products

1. **Draw against commission** — recoverable draws (advance payments offset
   against future earnings) are not modelled. Add a `vp_draw` table with a
   `balance_cents` that is netted in `calculate_commission()`.

2. **Territory / team splits** — quota splits between multiple reps on the same
   deal require a `vp_quota_split` table (employee_id, quota_id, split_pct).

3. **Multi-currency conversion** — `IncentivePlan.currency_code` is stored but
   no FX conversion is applied at calculation time. Integrate with the treasury
   plugin's `ExchangeRate` table.

4. **Clawback** — commission recovery on reversed deals is not implemented.
   Model as a negative `record_attainment()` call followed by a
   recalculation.

5. **Real-time quota progress API** — no WebSocket / SSE endpoint. Wire
   `AttainmentRecordedEvent` to the Realtime plugin for live dashboards.
