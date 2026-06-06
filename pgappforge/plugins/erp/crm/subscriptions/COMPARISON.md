# Subscriptions & Recurring Billing — World-Class Comparison

## Our Implementation
- Subscription statuses: TRIALING → ACTIVE → PAST_DUE / CANCELLED / EXPIRED
- Billing intervals: WEEKLY, MONTHLY, QUARTERLY, ANNUALLY with `interval_count` multiplier
- Trial period support with `trial_days` override at subscription creation
- Proration on plan change: day-accurate credit invoice (negative amount) for unused period
- Upgrade/downgrade detection via `monthly_equivalent_cents()` comparison
- Batch renewal job: `process_renewals()` iterates due ACTIVE subs, catches per-subscription errors without aborting the batch
- MRR / ARR computation: normalises all billing intervals to per-month equivalent; includes churn rate (30-day window) and new MRR
- Metered usage: upsert `SubscriptionUsage` records by `(sub_id, metric_name, period)` for consumption-based billing
- Sequential invoice references: `INV-{tenant_prefix}-{seq:06d}`
- BPM actions: `crm.subscriptions.create`, `crm.subscriptions.cancel`, `crm.subscriptions.change_plan`

**Integration points:** BPM workflow engine, GL (invoice line items), CRM contacts, domain event bus

---

## Benchmark: Stripe Billing

| Feature | Ours | Stripe Billing |
|---|---|---|
| Trial periods | ✓ | ✓ |
| Multiple billing intervals | ✓ | ✓ |
| Plan changes with proration | ✓ | ✓ |
| Metered usage billing | ✓ (record_usage) | ✓ |
| Cancel at period end | ✓ | ✓ |
| Immediate cancellation | ✓ | ✓ |
| MRR / ARR analytics | ✓ | ✓ |
| Payment processing | ✗ (_attempt_charge stub) | ✓ |
| Dunning / retry logic | ✗ (PAST_DUE only) | ✓ |
| Tax calculation | ✗ | ✓ |
| Invoice PDF generation | ✗ | ✓ |
| Customer portal | ✗ | ✓ |
| Webhook delivery | ✗ (events in DB only) | ✓ |
| ERP/BPM integration | ✓ native | ✗ (API) |

## Benchmark: Chargebee

| Feature | Ours | Chargebee |
|---|---|---|
| Plan change with proration | ✓ | ✓ |
| Trial management | ✓ | ✓ |
| MRR analytics | ✓ | ✓ |
| Dunning management | ✗ | ✓ |
| Coupons / discounts | ✓ (discount_pct) | ✓ (multi-type) |
| Multi-currency | ✓ (per-plan) | ✓ |
| Revenue recognition | ✗ | ✓ |
| ERP integration | ✓ native | ✗ (connector) |

## Benchmark: Odoo Subscriptions

| Feature | Ours | Odoo |
|---|---|---|
| Recurring billing | ✓ | ✓ |
| Plan upgrades/downgrades | ✓ | ✓ |
| Proration | ✓ | ✓ |
| MRR dashboard | ✓ | ✓ |
| Upsell / cross-sell automation | ✗ | ✓ |
| Health score / churn prediction | ✗ | ✓ |
| BPM workflow integration | ✓ (deeper) | limited |

---

## Differentiation

**Where we exceed:**
- MRR normalisation handles all four billing intervals correctly using `Fraction` arithmetic — no floating-point rounding errors on weekly or annual plans
- Proration uses day-accurate credit invoices with negative `amount_cents` — compatible with the same `SubscriptionInvoice` model, no separate credit note entity
- `process_renewals()` is batch-safe: errors on individual subscriptions are collected, not raised, so a single bad subscription cannot block the entire renewal run
- Metered usage upsert is idempotent per `(sub_id, metric_name, period)` — safe to call multiple times

**Remaining gaps:**
- `_attempt_charge()` always returns `True` — no payment gateway wired; production use requires override or event-bus handler on `crm.subscriptions.charge_requested`
- No dunning workflow (automatic retry schedule for PAST_DUE)
- No tax calculation or jurisdiction-aware invoicing
- `expansion_mrr_cents` in `get_mrr()` is a placeholder (returns 0)
- No customer self-service portal for plan changes or payment method updates
