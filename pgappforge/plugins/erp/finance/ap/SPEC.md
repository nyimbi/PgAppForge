# AP Plugin Specification

**Domain**: finance  
**Plugin name**: ap  
**Version**: 1.0.0  
**Depends on**: foundation  

## Overview

Full procure-to-pay lifecycle for a multi-tenant ERP. Covers supplier master
management, purchase orders, goods receipt/inspection, supplier invoice
processing (2-way and 3-way matching), multi-level approval workflows, and
ISO 20022 payment run generation.

## Entities & Relationships

```
APSupplier (party_id → erp_party [soft FK])
  └── APPurchaseOrder
        └── APPOLine
              └── APGRNLine ←── APGoodsReceipt (po_id → APPurchaseOrder)
              └── APInvoiceLine ←── APInvoice (po_id, grn_id)
                                       └── APApprovalWorkflow
                                       └── APPayment ←── APPaymentRun
```

## Models

### APSupplier (`ap_supplier`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | partition key |
| party_id | UUID | soft FK to erp_party |
| account_number | VARCHAR(20) | unique per tenant |
| name | VARCHAR(255) NOT NULL | denormalized for queries |
| supplier_type | VARCHAR(20) | GOODS/SERVICES/SUBCONTRACTOR/INTERCOMPANY/OTHER |
| status | VARCHAR(20) | active/inactive/blocked/under_review |
| payment_terms_days | INTEGER DEFAULT 30 | |
| payment_method | VARCHAR(20) | WIRE/ACH/SEPA/CHECK/BACS |
| currency_code | CHAR(3) DEFAULT 'USD' | |
| bank_account_iban | VARCHAR(34) | ISO 13616 |
| bank_bic | VARCHAR(11) | ISO 9362 |
| bank_account_name | VARCHAR(255) | |
| bank_details | JSONB | extra fields: sort_code, routing_number |
| tax_id | VARCHAR(50) | TIN/EIN |
| vat_number | VARCHAR(50) | |
| w9_on_file | BOOLEAN DEFAULT false | |
| reporting_1099 | BOOLEAN DEFAULT false | |
| gl_payable_account | VARCHAR(20) | AP control account |
| approved_supplier | BOOLEAN DEFAULT true | |
| credit_rating | VARCHAR(10) | internal rating |
| dynamic_discounting_eligible | BOOLEAN DEFAULT false | |
| early_payment_discount_pct | NUMERIC(5,2) DEFAULT 0 | |
| early_payment_days | INTEGER DEFAULT 0 | |
| contact_email | VARCHAR(255) | |
| contact_phone | VARCHAR(50) | |
| address | JSONB | {line1,line2,city,state,postal_code,country} |

**Indexes**: tenant_id, party_id, account_number, (tenant_id, status)  
**Constraints**: UNIQUE(tenant_id, account_number)

### APPurchaseOrder (`ap_purchase_order`)

Running match totals (received_cents, invoiced_cents, paid_cents) are
denormalized integers updated by service methods to avoid aggregation joins.

**Status machine**: DRAFT → PENDING_APPROVAL → APPROVED → SENT → PARTIAL → RECEIVED → CLOSED | CANCELLED

**Monetary columns**: ALL INTEGER CENTS (subtotal_cents, tax_cents, total_cents, received_cents, invoiced_cents, paid_cents)

### APPOLine (`ap_po_line`)

quantity_received and quantity_invoiced updated by GRN posting and invoice
matching respectively. unit_cost_cents × quantity (Decimal) rounded half-up
to int gives line_amount_cents.

**Constraints**: UNIQUE(po_id, line_number)

### APGoodsReceipt (`ap_goods_receipt`)

**Status machine**: DRAFT → CONFIRMED → QUALITY_HOLD → POSTED

Posting updates APPOLine.quantity_received and APPurchaseOrder.received_cents
via APService.post_grn().

### APGRNLine (`ap_grn_line`)

Invariant: quantity_accepted + quantity_rejected == quantity_received.
rejection_reason is required when quantity_rejected > 0.
unit_cost_cents locked at receipt time for inventory valuation.

### APInvoice (`ap_invoice`)

**match_status**: UNMATCHED | 2WAY | 3WAY | EXCEPTION  
**approval_status**: PENDING | APPROVED | REJECTED  
**status**: RECEIVED | MATCHING | APPROVED | PAYMENT_SCHEDULED | PAID | DISPUTED | CANCELLED

paid_cents: append-only via payment application (immutable ledger).
exchange_rate: Numeric(15,6) at invoice date — always convert to Decimal, never float.

**Constraints**: UNIQUE(tenant_id, supplier_id, invoice_number_supplier)

### APApprovalWorkflow (`ap_approval_workflow`)

One row per approver per invoice. approval_level determines sequence (1, 2, 3…).
amount_threshold_cents: NULL = unlimited authority.

### APPaymentRun (`ap_payment_run`)

iso20022_xml: Generated pain.001.001.03 XML. Blanked after transmission.
IMMUTABLE once status=TRANSMITTED.

**Status machine**: DRAFT → APPROVED → TRANSMITTED → CONFIRMED | FAILED

### APPayment (`ap_payment`)

IMMUTABLE after status=CONFIRMED. Reversal via negative amount_cents + GL correction.
uetr: SWIFT gpi UUID for cross-border tracking.

## Business Rules

1. **Supplier approval gate**: Invoices cannot be created for suppliers where `approved_supplier=False`.
2. **Wire/ACH IBAN requirement**: Suppliers with payment_method WIRE/ACH/SEPA must have bank_account_iban set.
3. **2-way match tolerance**: ±5% OR ±500 cents on unit_cost (whichever is greater). Quantity ≤ ordered × 1.05.
4. **3-way match tolerance**: Invoice quantity ≤ GRN accepted quantity × 1.02. GRN must be CONFIRMED/POSTED.
5. **Approval threshold**: Approver cannot approve invoice exceeding their amount_threshold_cents.
6. **Payment run gate**: Must be APPROVED status before TRANSMITTED.
7. **Immutable ledger**: paid_cents only increases. paid_cents at invoice level never decremented; use negative payment + GL correction entry.
8. **Integer cents**: ALL monetary amounts stored as INTEGER CENTS. Never float, never Numeric at the Python layer for money.
9. **Early payment discount**: Only applies if supplier.dynamic_discounting_eligible=True AND days_elapsed ≤ early_payment_days AND discount not already taken.
10. **GRN posting idempotency**: A GRN in status=POSTED cannot be re-posted.

## API Endpoints

### Suppliers

| Method | Path | Description |
|--------|------|-------------|
| GET | /ap/suppliers/ | List (HTML or ?format=json) |
| GET | /ap/suppliers/<id> | Detail (JSON) |
| POST | /ap/suppliers/ | Create |
| PUT | /ap/suppliers/<id> | Update |
| POST | /ap/suppliers/<id>/approve | Set approved_supplier=True |
| POST | /ap/suppliers/<id>/block | Set status=blocked |

### Purchase Orders

| Method | Path | Description |
|--------|------|-------------|
| GET | /ap/purchase-orders/ | List |
| GET | /ap/purchase-orders/<id> | Detail with lines |
| POST | /ap/purchase-orders/ | Create with lines |
| POST | /ap/purchase-orders/<id>/approve | DRAFT → APPROVED |
| POST | /ap/purchase-orders/<id>/send | APPROVED → SENT |
| POST | /ap/purchase-orders/<id>/cancel | → CANCELLED |

### Goods Receipts

| Method | Path | Description |
|--------|------|-------------|
| GET | /ap/grn/ | List |
| GET | /ap/grn/<id> | Detail with lines |
| POST | /ap/grn/ | Create with lines |
| POST | /ap/grn/<id>/post | Post GRN (updates PO quantities) |

### Invoices

| Method | Path | Description |
|--------|------|-------------|
| GET | /ap/invoices/ | List (HTML or ?format=json) |
| GET | /ap/invoices/<id> | Detail with lines |
| POST | /ap/invoices/ | Create with lines |
| POST | /ap/invoices/<id>/match | Run 2-way/3-way matching |
| POST | /ap/invoices/<id>/approve | Record approval decision |
| POST | /ap/invoices/<id>/dispute | Set status=DISPUTED |
| POST | /ap/invoices/<id>/post-gl | Post DR Expense / CR AP to GL |

### Payment Runs

| Method | Path | Description |
|--------|------|-------------|
| GET | /ap/payment-runs/ | List |
| GET | /ap/payment-runs/<id> | Detail + payments (?xml=1 for ISO XML) |
| POST | /ap/payment-runs/ | Create run for supplier_ids + value_date |
| POST | /ap/payment-runs/<id>/approve | DRAFT → APPROVED |
| POST | /ap/payment-runs/<id>/transmit | APPROVED → TRANSMITTED |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| GET | /ap/reports/aging | AP Aging (current/30/60/90+ day buckets) |
| GET | /ap/reports/payment-history | Supplier payment history (?days=90) |
| GET | /ap/reports/matching-status | Invoice match/approval status summary |

All report endpoints support `?format=json` for API consumption.

## Domain Events

| Event | Trigger | Key Payload |
|-------|---------|-------------|
| ap.invoice.matched | match_invoice() success | invoice_id, match_type, total_cents |
| ap.invoice.approved | All approval levels cleared | invoice_id, total_cents, due_date |
| ap.invoice.posted_to_gl | post_to_gl() called | invoice_id, debit_account, credit_account, amount_cents |
| ap.invoice.disputed | dispute endpoint | invoice_id, reason |
| ap.payment.initiated | create_payment_run() | run_number, total_payments, total_amount_cents |
| ap.payment.confirmed | apply_payment() | payment_id, uetr, amount_cents |
| ap.payment.failed | (bank callback) | payment_id, failure_reason |
| ap.supplier.statement_reconciled | reconcile_supplier_statement() | matched_count, disputed_count, net_difference_cents |
| ap.supplier.approved | approve endpoint | supplier_id, account_number |

## Service Methods

### `APService.match_invoice(invoice_id, session) -> APInvoice`

Performs 2-way (PO present) or 3-way (PO + GRN present) matching.
Tolerance: ±5% or ±500 cents on unit cost; quantity ≤ ordered × 1.05.
Sets match_status to 2WAY/3WAY on success, EXCEPTION on failure.
Updates APPOLine.quantity_invoiced on success.

### `APService.create_payment_run(supplier_ids, value_date, session, ...) -> APPaymentRun`

Selects all APPROVED invoices due on or before value_date for the given suppliers.
Applies early payment discounts where eligible.
Generates ISO 20022 pain.001.001.03 XML.
Sets invoice.status=PAYMENT_SCHEDULED and payment_run_id.

### `APService.reconcile_supplier_statement(supplier_id, statement_lines, session) -> dict`

Matches supplier statement lines against AP ledger by invoice_number_supplier.
Tolerance: max(1% of outstanding, 100 cents).
Returns matched / unmatched_statement / unmatched_ledger / disputed / net_difference_cents.

### `APService.early_payment_discount(invoice_id, session) -> int`

Returns discount in cents if: supplier.dynamic_discounting_eligible, within
early_payment_days of invoice_date, and discount not yet taken. Zero otherwise.

### `APService.post_to_gl(invoice_id, session) -> dict`

Constructs DR Expense / CR AP Payable journal dict.
Forwards to GL plugin extension if loaded.
Emits InvoicePostedToGLEvent.

### `APService.post_grn(grn_id, session) -> APGoodsReceipt`

Confirms GRN and updates APPOLine.quantity_received and
APPurchaseOrder.received_cents. Transitions PO to PARTIAL or RECEIVED.

### `APService.approve_invoice(invoice_id, approver_id, session) -> APInvoice`

Records approval decision. When all workflow steps are APPROVED, sets
invoice.approval_status=APPROVED and status=APPROVED, emits InvoiceApprovedEvent.

### `APService.apply_payment(invoice_id, payment_id, session) -> APInvoice`

Applies confirmed payment to invoice (increments paid_cents).
Sets status=PAID when paid_cents >= total_cents. Updates PO.paid_cents.

## Rules Engine Rulesets (5 pre-configured)

1. **ap.supplier.require_bank_for_wire** — WIRE/ACH/SEPA suppliers must have IBAN
2. **ap.invoice.block_unapproved_supplier** — Reject invoices for unapproved suppliers
3. **ap.invoice.positive_amounts** — Invoice total_cents must be > 0
4. **ap.purchase_order.quantity_positive** — PO line quantity must be > 0
5. **ap.payment_run.require_approval** — Payment run must be APPROVED before TRANSMITTED

## Reports (3 canned)

1. **AP Aging** (`/ap/reports/aging`) — Buckets by days overdue: current, 1-30, 31-60, 61-90, 91+. Printable HTML + JSON.
2. **Payment History** (`/ap/reports/payment-history`) — Last N days of payments per supplier with UETR. Filterable by supplier_id and days.
3. **Matching Status** (`/ap/reports/matching-status`) — Count and total per (match_status, approval_status) combination. API-friendly JSON output.

## Cross-Plugin Composability

**Upstream dependencies (soft, resolved at runtime)**:
- `foundation.Party` — supplier party records
- `foundation.ExchangeRate` — currency conversion for multi-currency runs
- `foundation.DomainEventLog` — all events persisted here

**Downstream consumers**:
- `gl` plugin subscribes to `ap.invoice.posted_to_gl` to write GL journal entries
- `treasury` plugin subscribes to `ap.payment.initiated` for cash flow forecasting
- `reporting` plugin subscribes to all AP events for analytics aggregation

## Monetary Conventions

All amounts stored as INTEGER CENTS (or smallest currency unit).
Arithmetic: Decimal throughout; `int(result.to_integral_value(ROUND_HALF_UP))` before storage.
Never: `float`, `Numeric` column for money, arithmetic on raw column values.
Exchange rates: `Numeric(15,6)` columns, always `Decimal(str(row.rate))` in Python.
