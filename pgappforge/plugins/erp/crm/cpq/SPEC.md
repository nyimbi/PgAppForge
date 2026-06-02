# Configure-Price-Quote (CPQ) Plugin — SPEC.md

**Plugin**: `cpq`  
**Domain**: `crm`  
**Version**: 1.0.0  
**Depends on**: `foundation`, `sales`

---

## Entities & Relationships

```
ProductCatalog ──────── PricingRule (many)

inventory.Product ───── ConfigurableProduct (1:1, optional)

ProductBundle ─────────── BundleLine (many)
                               │
                               └── product_id → inventory.Product

crm.SalesAccount ──────────────────────────────┐
crm.Opportunity (optional) ────────────────────┤
                                               ▼
                                            Quote
                                               │
                                        QuoteLine (many)
                                               │
                                     product_id (optional)
```

### ProductCatalog
Versioned price catalog scoped to tenant + currency. `effective_from`/`effective_to` drive date-range lookups. Multiple catalogs can exist; CPQService resolves the active one at quote time.

### PricingRule
Rule within a catalog defining how list price is modified:
- **FIXED**: override price to `fixed_price_cents`
- **PERCENT**: apply `discount_pct` to list price
- **TIERED**: quantity-tier discounts from `conditions` JSONB
- **VOLUME_DISCOUNT**: discount based on total line quantity

`conditions` JSONB evaluated by CPQService at line pricing time.

### ConfigurableProduct
CPQ extension for products with option sets. `config_rules` JSONB defines:
- `options`: `[{name, values[], required}]`
- `constraints`: `[{if: {opt: val}, then: {opt: [vals]}}]`

`min_price_cents` / `max_price_cents` enforce price bounds on configurations.

### ProductBundle
Bundle of products with FIXED or CONFIGURABLE type. FIXED bundles price as a unit; CONFIGURABLE bundles allow optional lines. `discount_pct` is a bundle-level discount applied after summing components.

### Quote
Header record linking to Opportunity and SalesAccount. Amounts in integer cents. `approval_status` drives the approval workflow. Amounts are immutable once status = SENT.

### QuoteLine
One line on a quote. `net_price_cents` = `list_price_cents × qty × (1 − discount_pct/100)`, computed by CPQService and stored immutably. `configuration` JSONB snapshots selected options at quote time.

---

## Business Rules

1. **Approval threshold**: quotes with discount > 20% require `approval_status = APPROVED` before `send_quote()`.
2. **Quote immutability**: amounts cannot change after status = SENT.
3. **Negative price guard**: `net_price_cents` cannot be negative (Rules Engine).
4. **Catalog overlap warning**: warn when a new active catalog overlaps date range of existing active catalog.
5. **Expired quote**: EXPIRED quotes cannot be accepted; create a new quote.
6. **Configurable product validation**: all required options must be provided; constraint rules checked.
7. **Pricing rule priority**: FIXED rules take immediate precedence; among PERCENT/TIERED rules, highest discount wins; lower `priority` number = higher priority.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /cpq/catalogs/ | List catalogs (JSON) |
| GET | /cpq/catalogs/`<id>` | Catalog detail (JSON) |
| POST | /cpq/catalogs/ | Create catalog |
| PUT | /cpq/catalogs/`<id>` | Update catalog |
| GET | /cpq/pricing-rules/ | List rules (JSON, filter by catalog_id) |
| POST | /cpq/pricing-rules/ | Create rule |
| PUT | /cpq/pricing-rules/`<id>` | Update rule |
| DELETE | /cpq/pricing-rules/`<id>` | Deactivate rule |
| GET | /cpq/bundles/ | List bundles (JSON) |
| GET | /cpq/bundles/`<id>` | Bundle detail with lines (JSON) |
| POST | /cpq/bundles/ | Create bundle |
| POST | /cpq/bundles/`<id>`/lines | Add bundle line |
| GET | /cpq/quotes/ | List quotes (HTML) |
| GET | /cpq/quotes/`<id>` | Quote detail with lines (JSON) |
| POST | /cpq/quotes/ | Generate quote (JSON body with line_items) |
| POST | /cpq/quotes/`<id>`/lines | Add line to DRAFT quote |
| POST | /cpq/quotes/`<id>`/send | DRAFT → SENT |
| POST | /cpq/quotes/`<id>`/accept | Customer accepts (SENT → ACCEPTED) |
| POST | /cpq/quotes/`<id>`/reject | Customer rejects (SENT → REJECTED) |
| POST | /cpq/quotes/`<id>`/submit-approval | Submit for approval |
| POST | /cpq/quotes/`<id>`/approve | Approver approves |
| POST | /cpq/quotes/`<id>`/reject-approval | Approver rejects |
| POST | /cpq/quotes/expire | Expire stale SENT quotes (batch) |
| POST | /cpq/quotes/configure-product | Validate product configuration |
| GET | /cpq/reports/quote-summary | Quote Status Summary (HTML) |
| GET | /cpq/reports/win-rate | Win Rate by Month (HTML) |
| GET | /cpq/reports/discount-analysis | Discount Analysis (HTML) |

---

## Events

### Emitted
| Event | Trigger |
|-------|---------|
| `crm.quote.created` | New DRAFT quote created |
| `crm.quote.sent` | Quote sent to customer |
| `crm.quote.accepted` | Customer accepts (SENT → ACCEPTED) |
| `crm.quote.rejected` | Customer rejects |
| `crm.quote.expired` | Past valid_until |
| `crm.quote.approval_requested` | Submitted for approval |
| `crm.quote.approved` | Approver approves |
| `crm.quote.approval_rejected` | Approver rejects |

### Consumed
| Event | Action |
|-------|--------|
| `crm.opportunity.won` | Stub: could auto-accept linked quotes |

---

## Reports

1. **Quote Status Summary** (`/cpq/reports/quote-summary`): quote count and total value by status (DRAFT/SENT/ACCEPTED/REJECTED/EXPIRED).
2. **Win Rate by Month** (`/cpq/reports/win-rate`): monthly ACCEPTED vs REJECTED+EXPIRED quote counts and win rate %.
3. **Discount Analysis** (`/cpq/reports/discount-analysis`): per-rep average discount %, total discount value, net revenue.

---

## Rules Engine Rulesets (5)

1. `cpq.quote.approval_required_high_discount` — block SENT without approval when discount > 20%
2. `cpq.quote.immutable_after_sent` — block amount changes after SENT
3. `cpq.quote_line.no_negative_price` — block negative net_price_cents
4. `cpq.catalog.date_overlap_check` — warn on active catalog date range overlap
5. `cpq.quote.no_accept_expired` — block EXPIRED → ACCEPTED transition

---

## CPQService Key Methods

| Method | Description |
|--------|-------------|
| `generate_quote(opportunity_id, account_id, line_items, session)` | Create DRAFT quote with pricing rule application |
| `price_line(product_id, quantity, list_price_cents, ...)` | Compute net_price_cents for a line |
| `configure_product(product_id, config, session)` | Validate configurable product options and constraints |
| `send_quote(quote_id, session)` | DRAFT → SENT; checks approval threshold |
| `accept_quote(quote_id, session)` | Customer accepts; emits QuoteAcceptedEvent |
| `reject_quote(quote_id, reason, session)` | Customer rejects |
| `submit_for_approval(quote_id, session)` | Sets approval_status = PENDING |
| `approve_quote(quote_id, approver_id, notes, session)` | Approver approves |
| `reject_approval(quote_id, approver_id, reason, session)` | Approver rejects |
| `expire_quotes(tenant_id, as_of_date, session)` | Batch expire stale SENT quotes |
