# Commerce Plugin — SPEC

## Domain
`crm` / `commerce`

## Purpose
Extend ecommerce infrastructure with subscription billing, carrier shipping
configuration, jurisdiction tax rules, and subscription revenue analytics (MRR/ARR).

## Entities

| Model | Table | Key Fields |
|---|---|---|
| ShippingMethod | com_shipping_method | name+carrier (unique/tenant), service_level, cost_cents, free_threshold_cents, delivery_days_min/max, is_active |
| TaxRule | com_tax_rule | jurisdiction_code + product_category (unique/tenant), tax_rate NUMERIC(5,4), tax_name, is_inclusive |
| SubscriptionPlan | com_subscription_plan | name (unique/tenant), description, amount_cents, currency_code, interval_months, trial_days, features JSONB |
| Subscription | com_subscription | customer_id, plan_id FK, status, start_date, next_billing_date, billing_interval, amount_cents (snapshot), currency_code, payment_method_id, cancelled_at, cancellation_reason |

## Relationships
- SubscriptionPlan →(many) Subscription
- Subscription → SubscriptionPlan (RESTRICT on delete)

## Monetary Fields (all integer cents)
- ShippingMethod: cost_cents, free_threshold_cents
- SubscriptionPlan: amount_cents
- Subscription: amount_cents (immutable snapshot at creation)

## Business Rules
1. Subscription amount_cents is immutable once ACTIVE — cancel and create new for plan changes.
2. CANCELLED subscriptions cannot be renewed.
3. tax_rate is NUMERIC(5,4): must be 0–1 (e.g. 0.2000 = 20%).
4. Shipping cost_cents >= 0; free_threshold_cents = NULL means never free.
5. Tax lookup: exact jurisdiction+category match first, then wildcard category '*'.
6. Inclusive tax: tax = subtotal × rate / (1 + rate).
7. Exclusive tax: tax = subtotal × rate.
8. MRR normalisation: ANNUAL ÷ 12, QUARTERLY ÷ 3, WEEKLY × 4.
9. Trial period: status = TRIALING; next_billing_date = start_date + trial_days.

## Billing Interval Values
MONTHLY | QUARTERLY | ANNUAL | WEEKLY

## Status Transitions
```
Subscription: ACTIVE ↔ PAUSED
              TRIALING → ACTIVE (after trial ends + payment)
              ACTIVE/TRIALING/PAST_DUE → CANCELLED
              ACTIVE → PAST_DUE (failed billing)
              PAST_DUE → ACTIVE (successful retry)
```

## API Endpoints
| Method | Path | Description |
|---|---|---|
| GET | /commerce/shipping-methods/ | List shipping methods |
| POST | /commerce/shipping-methods/ | Create method |
| POST | /commerce/shipping-methods/<id>/apply-cost | Compute shipping for order subtotal |
| GET | /commerce/tax-rules/ | List tax rules |
| POST | /commerce/tax-rules/compute | Compute tax for line item |
| GET | /commerce/plans/ | List subscription plans |
| GET | /commerce/subscriptions/ | List subscriptions |
| POST | /commerce/subscriptions/ | Create subscription |
| POST | /commerce/subscriptions/<id>/cancel | Cancel |
| POST | /commerce/subscriptions/<id>/pause | Pause |
| POST | /commerce/subscriptions/<id>/resume | Resume |
| POST | /commerce/subscriptions/<id>/renew | Process renewal (after payment) |
| GET | /commerce/reports/mrr-arr | MRR / ARR by status |
| GET | /commerce/reports/subscription-churn | Churn rate by plan |
| GET | /commerce/reports/shipping-usage | Active shipping methods |

## Events
**Emitted:** subscription.activated, subscription.renewed,
subscription.cancelled, subscription.past_due

**Consumed:** ar.invoice.paid (confirm renewal), marketing.lead.responded
(trial conversion hook)

## Rules Engine Rulesets (4)
1. `com.subscription.amount_immutable` — block amount change on ACTIVE subscription
2. `com.subscription.no_renew_cancelled` — block renewal of CANCELLED subscription
3. `com.tax_rule.rate_range` — validate tax_rate ≤ 1
4. `com.shipping.cost_non_negative` — validate cost_cents ≥ 0

## ReportForge Templates
- **MRR / ARR** — monthly and annual recurring revenue with subscriber counts by status
- **Subscription Churn** — cancelled / total per plan with churn rate %
- **Shipping Usage** — active shipping methods with cost and delivery window

## Dependencies
- `foundation` (DomainEventLog, Party)
- `ar` (invoice generation for subscription billing — depends_on includes ar)
- `marketing` (optional: lead.responded event for trial conversion)
