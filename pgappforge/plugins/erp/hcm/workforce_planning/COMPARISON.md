# Workforce Planning Plugin — Competitive Comparison

## Overview

The Workforce Planning plugin provides strategic annual headcount budgeting:
plan creation (DRAFT → SUBMITTED → APPROVED → CLOSED), position-level FTE
and cost tracking, what-if scenario modelling with global FTE/cost adjustment
multipliers, and actual-vs-budget variance analysis with monthly cost projection.

---

## Feature Matrix

| Feature | PgAppForge Workforce Planning | SAP SuccessFactors WFP | Workday Adaptive Planning | Oracle HCM Workforce Mgmt | Sage People |
|---|---|---|---|---|---|
| Annual headcount plan | Yes (plan_year + entity_id) | Yes | Yes | Yes | Yes |
| Plan state machine | DRAFT/SUBMITTED/APPROVED/CLOSED | Yes (configurable) | Yes | Yes | Draft/Approved only |
| Position-level FTE tracking | Yes (planned_fte Numeric(6,2)) | Yes | Yes | Yes | Headcount integers only |
| Part-time FTE (e.g. 0.5) | Yes | Yes | Yes | Yes | No |
| Department grouping | Yes (get_fte_by_department) | Yes | Yes | Yes | Yes |
| Grade/level assignment | Yes (grade_level VARCHAR) | Yes | Yes | Yes | Partial |
| Headcount change types | NEW/BACKFILL/EXISTING/REDUCTION | Yes | Yes | Yes | NEW/EXISTING only |
| What-if scenarios | Yes (6 types + CUSTOM, JSONB snapshot) | Yes (separate module) | Yes (native) | Yes | No |
| Scenario FTE/cost adjustment | Yes (global pct multiplier) | Position-level | Yes | Yes | No |
| Actual vs budget analysis | Yes (with analytics plugin fallback) | Yes | Yes | Yes | Basic |
| Monthly cost projection | Yes (start-date aware, 12-month) | Yes | Yes | Yes | No |
| GL cost centre link | Yes (gl_cost_center VARCHAR) | Yes | Yes | Yes | No |
| BPM action hooks | Yes (approve_plan) | Workflow engine | No | Configurable | No |
| Rules Engine guardrails | Yes (5 idempotent rulesets) | Partial | No | No | No |
| Domain events (CDC) | Yes (5 events, durable DomainEventLog) | Webhook only | Webhook only | Webhook only | No |
| Multi-tenant | Yes (tenant_id on all tables) | Separate orgs | Separate orgs | Separate orgs | No |
| Open source / self-hosted | Yes (MIT) | No (SaaS) | No (SaaS) | No (SaaS) | No (SaaS) |

---

## Design Decisions

### Running totals on WorkforcePlan
`total_planned_fte` and `total_budget_cents` are maintained as running totals
on `WorkforcePlan` by `add_position()`. This avoids an aggregate query on every
dashboard load. The tradeoff is that bulk-delete of positions requires a manual
recalculation — acceptable given that plan mutations are low-frequency and
always go through the service layer.

### JSONB scenario snapshot vs live query
`WorkforceScenario.scenario_data` stores a full adjusted-positions snapshot at
creation time rather than recomputing on read. This makes scenario comparison
O(1) regardless of position count and preserves historical what-if states even
if the base plan is later modified. The cost is storage: ~2-5 KB per scenario
for typical plans (< 500 positions).

### Fractional FTE as Numeric(6,2), not integer headcount
Workday, SAP, and Oracle all support fractional FTE. Modelling as
`Numeric(6, 2)` in PostgreSQL avoids the integer-headcount trap that makes
part-time and contractor planning awkward. The service uses `Decimal` arithmetic
internally to prevent float drift on accumulation.

### Analytics plugin fallback in actual_vs_budget
`actual_vs_budget()` first attempts to load actuals from `HCMAnalyticsService`.
If that import fails (plugin not installed), it falls back to summing APPROVED
positions as a proxy. This makes the method useful without a full analytics
stack while providing accurate numbers when the analytics plugin is present.

### No position uniqueness constraint
`wfp_position` has no unique constraint on `(plan_id, position_code)` because
real plans routinely carry multiple instances of the same job code at different
grades, departments, or start dates. Deduplication is a UI/reporting concern,
not a data integrity one.

---

## Gaps vs Enterprise Products

1. **Position-level approval workflow** — `PlannedPosition.approval_status`
   is stored but there is no dedicated approval flow. Wire to the BPM plugin
   for manager-by-manager position approval chains.

2. **Skills/competency mapping** — no link between planned positions and
   required skill profiles. Join to the talent plugin's `SkillProfile` table
   via `position_code`.

3. **Rolling forecast** — plans are annual snapshots. Quarterly re-forecasting
   requires either a new plan per quarter or a versioned `WorkforcePlanRevision`
   table that preserves baseline vs revised totals.

4. **Headcount vs FTE distinction** — some jurisdictions distinguish headcount
   (person count) from FTE (weighted hours). Add a `headcount_integer` column
   alongside `planned_fte` if both metrics are needed.

5. **External HR system sync** — no connector to import actuals from
   Workday/SAP via API. Build an event handler on `hcm.employee.hired`
   and `hcm.employee.terminated` that calls `actual_vs_budget()` and persists
   the result to a `wfp_actuals_snapshot` table for trend analysis.
