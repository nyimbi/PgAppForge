# AR Plugin — Specification

**Domain**: finance  
**Plugin name**: ar  
**Version**: 1.0.0  
**Depends on**: foundation  

---

## 1. Purpose

Full Accounts Receivable lifecycle for a multi-tenant ERP. Covers the
order-to-cash cycle from customer credit profiling through invoice issuance,
payment receipt, allocation, credit notes, dunning, aging, and GL integration.

---

## 2. Entities

### 2.1 ARCustomer

Links to `erp_party` for name/address/contact data. Carries the credit profile
and dunning state. All financial amounts are integer cents.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | multi-tenant key |
| party_id | UUID FK erp_party | name, addresses, contacts |
| account_number | VARCHAR(20) | unique per tenant |
| customer_type | VARCHAR(20) | CUSTOMER / PROSPECT / INTERNAL |
| credit_limit_cents | INTEGER | NULL = unlimited |
| credit_used_cents | INTEGER | maintained by ARService |
| credit_hold | BOOLEAN | blocks invoice issue |
| payment_terms_days | INTEGER | default 30 |
| dunning_level | INTEGER | 0–4 |
| dunning_blocked | BOOLEAN | exclude from dunning runs |
| gl_reconciliation_account | VARCHAR(20) | AR control GL code |
| statement_frequency | VARCHAR(10) | MONTHLY / WEEKLY / NONE |
| last_statement_date | DATE | |
| risk_score | NUMERIC(5,2) | 0–100 |
| status | VARCHAR(20) | ACTIVE / INACTIVE / SUSPENDED |
| billing_address | JSONB | denormalised snapshot |
| contact_email | VARCHAR(255) | primary billing contact |
| contact_phone | VARCHAR(50) | |

**RulesMixin**: credit hold, dunning level, credit limit are rules-engine targets.

### 2.2 ARInvoice

Immutable ledger: once ISSUED, amounts are never updated. Corrections use
ARCreditNote.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| invoice_number | VARCHAR(50) | unique per tenant |
| customer_id | UUID FK ar_customer | |
| invoice_date | DATE | tax point |
| due_date | DATE | drives aging/dunning |
| billing_period_start/end | DATE | subscription periods |
| currency_code | CHAR(3) | ISO 4217 |
| exchange_rate | NUMERIC(15,6) | to functional currency |
| subtotal_cents | INTEGER | sum of line amounts |
| discount_cents | INTEGER | header-level discount |
| tax_cents | INTEGER | sum of line tax |
| total_cents | INTEGER | subtotal − discount + tax |
| paid_cents | INTEGER | sum of allocations |
| balance_due_cents | INTEGER | total − paid − write_off |
| write_off_cents | INTEGER | bad debt written off |
| status | VARCHAR(20) | DRAFT/ISSUED/PARTIAL/PAID/OVERDUE/DISPUTED/WRITTEN_OFF/CANCELLED |
| gl_revenue_account | VARCHAR(20) | |
| gl_ar_account | VARCHAR(20) | |
| po_reference | VARCHAR(100) | customer PO |
| contract_reference | VARCHAR(100) | |
| billing_reference_id | UUID FK ar_invoice | self-ref for credit notes |
| dunning_level | INTEGER | current dunning severity |
| dispute_reason | TEXT | |
| write_off_date | DATE | |
| write_off_reason | TEXT | |
| paid_date | DATE | date of full payment |

**RulesMixin**: status transitions, immutability guards.

### 2.3 ARInvoiceLine

One row per billed item. Amounts computed and stored at creation (immutable).

`line_amount_cents = round(quantity × unit_price_cents × (1 − discount_pct/100))`  
`tax_cents = round(line_amount_cents × tax_rate / 100)`

### 2.4 ARPayment

Cash receipt record before allocation. Append-only after ALLOCATED.

Status transitions: `UNALLOCATED → PARTIAL → ALLOCATED | RETURNED`

### 2.5 ARAllocation

**Append-only, NEVER UPDATE.** Junction between ARPayment and ARInvoice.
Reversals are new rows with negative `allocated_cents`.

`allocated_cents + discount_taken_cents` reduces `invoice.balance_due_cents`.

### 2.6 ARCreditNote

Standalone or linked to an original invoice. `applied_cents` tracks usage.

Status: `OPEN → PARTIAL → APPLIED | CANCELLED`

### 2.7 ARDunningRun

One batch record per dunning level per run date.  
Status: `PENDING → RUNNING → COMPLETED | FAILED`

### 2.8 ARDunningEvent

Per-customer outcome within a dunning run. `invoice_ids` is JSONB array.

### 2.9 ARAging

**Append-only by convention.** Nightly snapshot of aging buckets per customer.
Drives dashboards and dunning triggers without hitting transactional tables.

Buckets (days overdue from snapshot_date):
- `current_cents`: not yet due
- `days_1_30`, `days_31_60`, `days_61_90`, `days_91_120`, `over_120`

---

## 3. Business Rules

### 3.1 Monetary invariant
All amounts stored as **integer cents**. Float is never used. Exchange rate
multiplication uses `Decimal` then rounds to `int`.

### 3.2 Immutable ledger
- `ARAllocation`: no UPDATE ever. Reversals via new negative rows.
- `ARInvoice`: amounts immutable after ISSUED. Corrections via `ARCreditNote`.
- `ARAging`: no UPDATE. New snapshots inserted daily.

### 3.3 Credit hold
- If `ARCustomer.credit_hold = true`, `ARService.issue_invoice` raises `ARValidationError`.
- Credit hold is set/released via `ARCustomerView.set_credit_hold`.
- Emits `CreditHoldPlacedEvent` / `CreditHoldReleasedEvent`.

### 3.4 Credit limit
- `credit_used_cents` incremented on invoice issue.
- Decremented on full payment or write-off.
- `ARService.credit_check(customer_id, amount_cents)` returns bool.

### 3.5 Aging buckets
Computed by `ARService.run_aging(as_of_date, tenant_id)`:
- `days_overdue = as_of_date − invoice.due_date`
- Bucket assignment uses closed integer intervals (≤ 30, ≤ 60, ≤ 90, ≤ 120, > 120).

### 3.6 Dunning escalation
- `run_dunning(level)` selects customers with overdue invoices not `dunning_blocked`.
- `ARCustomer.dunning_level` is escalated to `max(current, level)`.
- Per-invoice `dunning_level` and `last_dunning_date` are updated.
- Emits `CustomerOverdueEvent` per customer.

### 3.7 Write-off
- Posts GL journal: DR Bad Debt Expense / CR AR Control.
- Sets `balance_due_cents = 0`, `status = WRITTEN_OFF`.
- Reduces `customer.credit_used_cents`.

---

## 4. API Endpoints

### Customers `/ar/customers/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ar/customers/` | Paginated list (HTML) |
| GET | `/ar/customers/<id>` | Detail (JSON) |
| POST | `/ar/customers/` | Create customer |
| PUT | `/ar/customers/<id>` | Update customer |
| POST | `/ar/customers/<id>/credit-hold` | Place / release hold |
| GET | `/ar/customers/<id>/credit-check?amount=<cents>` | Credit availability |

### Invoices `/ar/invoices/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ar/invoices/` | List (HTML) |
| GET | `/ar/invoices/<id>` | Detail + lines (JSON) |
| POST | `/ar/invoices/` | Create DRAFT |
| POST | `/ar/invoices/<id>/lines` | Add line |
| POST | `/ar/invoices/<id>/issue` | DRAFT → ISSUED |
| POST | `/ar/invoices/<id>/dispute` | Mark DISPUTED |
| POST | `/ar/invoices/<id>/write-off` | Write off bad debt |
| POST | `/ar/invoices/<id>/cancel` | Cancel DRAFT |

### Payments `/ar/payments/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ar/payments/` | List (HTML) |
| GET | `/ar/payments/<id>` | Detail + allocations (JSON) |
| POST | `/ar/payments/` | Create payment record |
| POST | `/ar/payments/<id>/allocate` | Apply to invoices |
| POST | `/ar/payments/<id>/return` | Mark RETURNED |

### Credit Notes `/ar/credit-notes/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ar/credit-notes/` | List (JSON) |
| GET | `/ar/credit-notes/<id>` | Detail (JSON) |
| POST | `/ar/credit-notes/` | Create credit note |
| POST | `/ar/credit-notes/<id>/apply` | Apply to invoice |

### Dunning `/ar/dunning/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ar/dunning/runs` | List runs (JSON) |
| POST | `/ar/dunning/runs` | Trigger dunning run |
| GET | `/ar/dunning/runs/<id>/events` | Events for a run |
| POST | `/ar/dunning/update-overdue` | Mark overdue invoices |

### Reports `/ar/reports/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ar/reports/aging` | AR Aging Report (HTML, printable) |
| GET | `/ar/reports/statement/<customer_id>` | Customer Statement (HTML, printable) |
| GET | `/ar/reports/overdue` | Overdue Invoices Report (HTML, printable) |
| POST | `/ar/reports/aging-snapshot` | Compute and store aging snapshot |

---

## 5. Domain Events

All events extend `DomainEvent` from `pgappforge.plugins.erp.foundation.events`.
All amounts are integer cents. All dates are ISO strings.

| Event type | Trigger | Key payload fields |
|------------|---------|-------------------|
| `ar.invoice.issued` | issue_invoice() | invoice_id, total_cents, currency_code, due_date |
| `ar.invoice.paid` | apply_payment() | invoice_id, total_cents, paid_date |
| `ar.invoice.written_off` | write_off() | invoice_id, write_off_cents, reason |
| `ar.invoice.disputed` | dispute endpoint | invoice_id, dispute_reason |
| `ar.payment.received` | payment create | payment_id, amount_cents, payment_method |
| `ar.payment.allocated` | apply_payment() | payment_id, allocated_cents, invoice_ids |
| `ar.customer.overdue` | run_dunning() | customer_id, overdue_cents, dunning_level |
| `ar.customer.credit_hold_placed` | set_credit_hold() | customer_id, credit_used_cents |
| `ar.customer.credit_hold_released` | set_credit_hold() | customer_id |
| `ar.credit_note.issued` | create_credit_note() | credit_note_id, total_cents |
| `ar.dunning.run_completed` | run_dunning() | dunning_run_id, customers_contacted |
| `ar.aging.snapshot_created` | run_aging() | snapshot_date, total_outstanding_cents |

---

## 6. Rules Engine Rulesets (pre-configured)

| Ruleset name | Model | Trigger | Action |
|---|---|---|---|
| `ar.invoice.credit_limit` | ARInvoice | on_before_update (status→ISSUED) | raise_error if credit_hold |
| `ar.invoice.immutability` | ARInvoice | on_before_update | raise_error if amounts change post-issue |
| `ar.payment.positive_amount` | ARPayment | on_before_create | raise_error if amount_cents ≤ 0 |
| `ar.customer.dunning_block` | ARCustomer | on_update | log_warning if dunning escalated on blocked customer |
| `ar.invoice.write_off_threshold` | ARInvoice | on_before_update | log_warning if write_off_cents > 500,000 |

---

## 7. GL Integration

ARService calls `_post_gl_journal()` for:

| Business event | DR | CR |
|----------------|----|----|
| Invoice issued | AR Control | Revenue |
| Invoice written off | Bad Debt Expense | AR Control |

GL plugin import is optional — if `pgappforge.plugins.erp.finance.gl` is not
installed, journal posting is silently skipped (logged at DEBUG).

---

## 8. Cross-Plugin Composability

```
foundation.party.created  ──→  AR (subscribe, create customer shell)
foundation.party.updated  ──→  AR (sync billing address)
AR.ar.invoice.paid        ──→  GL (post receipt entry)
AR.ar.customer.overdue    ──→  CRM (flag for account manager)
AR.ar.dunning.run_completed ──→ Analytics (dunning effectiveness dashboard)
```

---

## 9. Report Design

### Report 1: AR Aging (Bootstrap HTML, printable)
- Latest snapshot per customer from `ar_aging`.
- Columns: Customer | Current | 1–30 | 31–60 | 61–90 | 91–120 | >120 | Total.
- Footer row with grand totals.
- Print/PDF button (browser `window.print()`).

### Report 2: Customer Statement (Bootstrap HTML, printable)
- Period-selectable via `?from=YYYY-MM-DD&to=YYYY-MM-DD`.
- Opening balance + invoices + payments + closing balance.
- Two tables: invoices and payments in period.

### Report 3: Overdue Invoices (Bootstrap HTML, printable)
- All invoices where `balance_due_cents > 0` and `due_date < today`.
- Columns: Customer | Invoice # | Invoice Date | Due Date | Days Late | Status | Total | Balance Due | Dunning Level.
- Grand total overdue in footer.

---

## 10. Development Notes

- `lazy='select'` everywhere (SA 2.x removed `lazy='dynamic'`).
- UUID columns use `UUID(as_uuid=False)` (strings, not Python uuid objects).
- All server defaults are explicit (`server_default=sa.text("NOW()")` etc.).
- `AuditMixin` provides `created_by` / `updated_by` on mutable entities.
- `ARAllocation` intentionally has no `updated_at` — it is append-only.
- `ARAging` has no `updated_at` — append-only by convention.
- `extend_existing=True` in all `__table_args__` for safe hot-reload.
