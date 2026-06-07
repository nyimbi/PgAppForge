# Credit Management Plugin — Competitive Comparison

## vs SAP Credit Management (FIN-FSCM-CR)

### SAP FIN-FSCM-CR overview

SAP Financial Supply Chain Management — Credit Management (FIN-FSCM-CR) is the modern
credit management module introduced in ECC 6.0 EhP3 and carried into S/4HANA. It
replaces the older FD32/FD33 credit control area approach with a more flexible,
event-driven model:

- **Credit segments**: organisational units that replace credit control areas;
  a customer can have different limits in different segments
- **Credit exposure**: aggregated from FI (open items), SD (open orders, deliveries,
  billing documents), and treasury (payment behaviour scoring)
- **Credit rules**: SAP Business Rules Framework plus (BRFplus) evaluates exposure
  against limit and triggers automatic/manual holds
- **Credit case**: workflow case created on breach for credit analyst review
- **Scoring**: formula-based credit score derived from payment history, overdue days,
  years as customer, external ratings
- **Integration**: SD credit check at order entry (VBAK), delivery (LIKP), and billing

### PgAppForge CreditManagementPlugin: capabilities

| Capability | SAP FIN-FSCM-CR | PgAppForge |
|---|---|---|
| Credit segments | Multiple per customer | Single profile per customer per tenant |
| Credit limit | Per segment, currency, validity period | Single `credit_limit_cents` per profile |
| Exposure sources | FI open items + SD open orders + deliveries + billing | `CreditExposureComponent` (INVOICE / SALES_ORDER / DELIVERY) |
| Exposure update | Real-time via SD integration / batch rebuild | `update_exposure()` recomputes from components |
| Credit check trigger | Order entry, delivery, billing (SD exits) | `check_credit()` callable; BPM action `finance.credit.check` |
| Credit hold | Automatic or manual; SD delivery block | `place_hold()` / `release_hold()`; BPM `finance.credit.place_hold` |
| Credit case / workflow | BRFplus + workflow; credit analyst dashboard | Event-driven: `CreditLimitBreachEvent` → external workflow |
| Scoring | Formula with 8+ factors | `credit_rating` field (AAA–D); score computed externally |
| Payment terms | Per customer master | `payment_terms_days` on profile |
| Dispute integration | FIN-FSCM-DM dispute cases | No native dispute module; integrate via AR dispute events |
| Reporting | SAP Fiori credit overview tiles | `get_overdue_customers()` + custom views |
| External credit agencies | D&B, Euler Hermes via FSCM connectors | `credit_rating` populated by external service; no native connector |
| Multi-currency | Per segment currency | Single `currency_code` per profile |

### Key design differences

**Intentional simplifications:**
- Single credit profile per customer per tenant, not multi-segment. Segment-level
  separation (e.g., domestic vs. export) can be modelled by using distinct
  `customer_id` namespacing or extending the model with a `segment` column.
- No native scoring engine. The `credit_rating` field is populated by the caller
  (external bureau connector, internal payment-history scorer, or manual entry).
  A scoring microservice emitting `CreditRatingUpdatedEvent` is the recommended extension.
- `update_exposure()` is a synchronous recompute from stored `CreditExposureComponent`
  rows rather than a real-time trigger. In high-throughput systems, integrate with
  the AR plugin's `ar.invoice.issued` / `ar.invoice.paid` events to call
  `register_exposure_component()` / `remove_exposure_component()` automatically.

**PgAppForge advantages:**
- Event-driven breach detection: `CreditLimitBreachEvent` feeds any workflow engine
  (BPM, Temporal, Celery) without coupling to the credit management plugin itself.
- Component-level exposure tracking: each `CreditExposureComponent` row is individually
  traceable by `(source_type, source_id)` — auditable and reversible.
- Rules Engine pre-configured with 5 rulesets: auto-hold flag, zero-limit warning,
  hold-release audit trail, negative exposure guard, D-rated customer escalation.
- BPM-registered actions: `finance.credit.check` and `finance.credit.place_hold`
  are first-class workflow steps — no ABAP coding, no BRFplus configuration.
- Full pytest coverage without SAP system: all logic runs against an in-memory
  PostgreSQL session (pytest-httpserver + SQLAlchemy).

---

## vs Oracle Credit Management Cloud

### Oracle Credit Management Cloud overview

Oracle Credit Management is part of Oracle Fusion Financials. Key features:
- **Credit review cycle**: scheduled or event-triggered review workflow
- **Credit case**: case management for analyst review with scoring workbench
- **Multi-currency limits**: limits defined per currency with real-time FX conversion
- **Exposure calculation**: aggregates from AR open items, OTC order management
- **Scoring**: configurable scoring model with weighted attributes
- **Recommendations**: system recommends limit changes based on score

### Comparison

| Capability | Oracle Credit Management Cloud | PgAppForge |
|---|---|---|
| Credit review cycle | Automated scoring + review case | Manual via `set_credit_limit()` + BPM workflow |
| Scoring workbench | UI with weighted attribute scoring | External service populates `credit_rating` |
| Multi-currency limits | Native, with FX | Single currency; multi-currency via separate profiles |
| Exposure sources | AR + OTC orders + receivables | `CreditExposureComponent` (extensible source_type) |
| Hold automation | Rule-based auto-hold on score/limit breach | `CreditLimitBreachEvent` → BPM `finance.credit.place_hold` |
| Collector assignment | Automatic by territory/segment | Not included; integrate with CRM assignment |
| SLA notifications | Oracle Notifications / UMS | Event bus → notification service |
| API | Oracle REST API (SOAP legacy) | Python service layer + BPM actions |
| Deployment | SaaS only | Self-hosted PostgreSQL |
| Analytics | OTBI reports | `get_overdue_customers()` + custom dashboards |

### Key design differences

Oracle's scoring workbench and review cycle are the headline differentiators — they
automate the credit analyst's workflow end-to-end. PgAppForge's approach is to fire
`CreditLimitBreachEvent` and let the host application route to the appropriate
analyst workflow (Camunda, Temporal, Airflow, or a simple Flask approval view).

Oracle's multi-currency limit support requires FX rate maintenance and periodic
revaluation. PgAppForge stores limits in a single `currency_code` — adequate for
single-currency or multi-entity deployments where each tenant represents one currency
entity. For multi-currency in a single tenant, extend `CustomerCreditProfile` with a
`limit_cents_local` column and carry an exchange rate.
