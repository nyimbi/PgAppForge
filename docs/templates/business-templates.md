# Business Templates

Seven operational templates cover the core back-office modules of most businesses. They share a common design language: UUID primary keys with `gen_random_uuid()`, a `tenant_id` column on every top-level table for multi-tenant partitioning, TIMESTAMPTZ timestamps, and NUMERIC(18,4) for monetary amounts.

Templates are applied independently and can coexist in the same database — each lives in its own PostgreSQL schema (`ar`, `ap`, `gl`, `crm`, `hrm`, `inv`, `ec`). FK references across schemas are intentional: the AR customer record can reference the same entity tracked in CRM.

---

## Accounts Receivable (ar)

**8 tables**: `ar_customer`, `ar_invoice`, `ar_invoice_line`, `ar_payment`, `ar_payment_allocation`, `ar_dunning_run`, `ar_dunning_event`, `ar_aging_snapshot`

Covers the full AR lifecycle from customer master data through invoicing, cash receipt, payment allocation, dunning campaigns, and aging analysis.

Key design points:
- `ar_invoice.balance_due = total_amount - paid_amount - write_off_amount` — maintained by the application layer, not a generated column, so it is portable across PostgreSQL versions
- `ar_payment_allocation` is a many-to-many junction between payments and invoices; `discount_taken` records early-payment discounts applied at allocation time
- `ar_aging_snapshot` is a nightly point-in-time snapshot per customer; it drives dashboards and dunning triggers without hitting the transactional invoice table
- `ar_dunning_run` / `ar_dunning_event` separate the batch run record (one per dunning level per date) from per-customer outcomes (delivery method, contact used, promise-to-pay amount)

```bash
# Apply to a database
flask forge templates apply ar --database-uri postgresql://localhost/mydb

# Generate a complete AR application
flask forge gen all \
  postgresql://localhost/mydb \
  --name MyARApp \
  --output-dir ./ar_app/
```

The generated app has CRUD views for all 8 tables. The `ar_invoice` list view shows `balance_due` highlighted in red for overdue invoices. The `ar_aging_snapshot` view renders aging buckets (0–30, 31–60, 61–90, 90+ days) as a horizontal bar chart.

---

## Accounts Payable (ap)

**10 tables**: `ap_supplier`, `ap_purchase_order`, `ap_po_line`, `ap_goods_receipt`, `ap_grn_line`, `ap_invoice`, `ap_invoice_line`, `ap_invoice_approval`, `ap_payment_run`, `ap_payment`

Covers the procure-to-pay cycle: supplier master, purchase orders, goods receipts (three-way match), supplier invoices with approval workflow, payment runs, and individual payment records.

Key design points:
- Three-way match is enforced at the application layer: `ap_invoice` links back to `ap_purchase_order` and `ap_goods_receipt`; the generated views show all three documents side by side in the invoice detail panel
- `ap_invoice_approval` tracks the approval chain — approver, decision, timestamp, and comment — supporting multi-level approval workflows
- `ap_payment_run` batches individual `ap_payment` records; one run per bank file or cheque run

```bash
flask forge templates apply ap --database-uri postgresql://localhost/mydb

flask forge gen all \
  postgresql://localhost/mydb \
  --name MyAPApp \
  --output-dir ./ap_app/
```

---

## General Ledger (gl)

**9 tables**: `gl_chart_of_accounts`, `gl_cost_center`, `gl_fiscal_year`, `gl_period`, `gl_journal_batch`, `gl_journal_entry`, `gl_journal_line`, `gl_account_balance`, `gl_budget`

Double-entry general ledger compliant with IFRS and GAAP concepts. Journal lines must balance (debits = credits) within a batch; the generated views enforce this constraint via a pre-save validator.

Key design points:
- `gl_chart_of_accounts` uses a `parent_id` self-referential FK to support a hierarchical account tree of arbitrary depth; the generated view renders it as an indented tree
- `gl_period` has a `status` column (`OPEN`, `CLOSED`, `LOCKED`) — posting is blocked to `CLOSED` and `LOCKED` periods
- `gl_account_balance` is a running balance per account per period, updated by the journal posting process; it avoids summing all journal lines on every balance sheet query
- `gl_budget` stores period-level budget figures per account per cost centre for variance reporting

```bash
flask forge templates apply gl --database-uri postgresql://localhost/mydb

flask forge gen all \
  postgresql://localhost/mydb \
  --name MyGLApp \
  --output-dir ./gl_app/
```

To apply AR, AP, and GL together as a complete financial suite:

```bash
for tmpl in ar ap gl; do
  flask forge templates apply $tmpl --database-uri postgresql://localhost/mydb
done

flask forge gen all \
  postgresql://localhost/mydb \
  --name FinanceApp \
  --output-dir ./finance_app/
```

---

## CRM (crm)

**14 tables**: `crm_account`, `crm_contact`, `crm_lead`, `crm_opportunity`, `crm_activity`, `crm_task`, `crm_campaign`, `crm_campaign_member`, `crm_quote`, `crm_quote_line`, `crm_contract`, `crm_contract_line`, `crm_case`, `crm_case_comment`

Full B2B CRM pipeline: account/contact management, lead capture, opportunity pipeline, activity logging, task management, campaign tracking, quoting, contracting, and customer support cases.

Key design points:
- `crm_lead` is separate from `crm_account`/`crm_contact` — leads are unqualified prospects; the conversion process creates account and contact records and sets `crm_lead.converted = true`
- `crm_opportunity.stage` uses a controlled vocabulary (`PROSPECTING`, `QUALIFICATION`, `PROPOSAL`, `NEGOTIATION`, `CLOSED_WON`, `CLOSED_LOST`); the list view renders stage as a progress bar
- `crm_activity` covers calls, emails, meetings, and demos in a single table with an `activity_type` discriminator
- `crm_quote` → `crm_quote_line` → `crm_contract` → `crm_contract_line` models the quote-to-contract progression with line-level detail

```bash
flask forge templates apply crm --database-uri postgresql://localhost/mydb

flask forge gen all \
  postgresql://localhost/mydb \
  --name MyCRMApp \
  --output-dir ./crm_app/
```

See [Tutorial 03](../tutorials/03_using_templates.md) for a full walkthrough of generating and running the CRM app.

---

## HRM (hrm)

**15 tables**: `hrm_legal_entity`, `hrm_organization`, `hrm_job_catalog`, `hrm_person`, `hrm_employment`, `hrm_compensation`, `hrm_payrun`, `hrm_payslip`, `hrm_payslip_line`, `hrm_leave_policy`, `hrm_leave_balance`, `hrm_leave_request`, `hrm_timesheet`, `hrm_time_entry`, `hrm_performance_review`

Full HR lifecycle from legal entity and org structure through to payroll, leave management, timesheets, and performance reviews. Designed for multi-entity (holding company) deployments where employees may work across legal entities.

Key design points:
- `hrm_legal_entity` → `hrm_organization` → `hrm_employment` hierarchy supports matrix org structures; an employee (`hrm_person`) can have multiple simultaneous employment records in different legal entities
- `hrm_compensation` separates base salary, allowances, and benefits into separate rows with effective dates, enabling full compensation history without overwriting records
- `hrm_payrun` → `hrm_payslip` → `hrm_payslip_line` models a payroll run: one run per pay period per legal entity; payslip lines store earnings, deductions, and employer contributions
- `hrm_leave_balance` is recalculated by the leave accrual job; `hrm_leave_request` records actual leave taken with approval status

```bash
flask forge templates apply hrm --database-uri postgresql://localhost/mydb

flask forge gen all \
  postgresql://localhost/mydb \
  --name MyHRApp \
  --output-dir ./hr_app/
```

---

## Inventory Management (inventory)

**13 tables**: `inv_product_category`, `inv_product`, `inv_supplier`, `inv_warehouse`, `inv_location`, `inv_stock_level`, `inv_stock_movement`, `inv_purchase_order`, `inv_po_line`, `inv_goods_receipt`, `inv_grn_line`, `inv_stock_count`, `inv_count_line`

Full warehouse inventory: product master with category hierarchy, multi-warehouse and multi-location stock levels, movement ledger, purchasing, goods receipt, and periodic stock counting.

Key design points:
- `inv_stock_level` stores the current on-hand quantity per product per location; it is updated by the stock movement posting process rather than derived from summing all movements — O(1) balance query
- `inv_stock_movement` is the append-only movement ledger (receipts, issues, transfers, adjustments, write-offs); the `movement_type` column uses a controlled vocabulary
- `inv_location` is a child of `inv_warehouse` — supports bin/rack/shelf addressing with a `location_code` string
- `inv_stock_count` / `inv_count_line` records the physical count process: count is initiated (creating count lines with expected quantities), physical quantities are entered, and variances are posted as adjustments

```bash
flask forge templates apply inventory --database-uri postgresql://localhost/mydb

flask forge gen all \
  postgresql://localhost/mydb \
  --name MyInventoryApp \
  --output-dir ./inv_app/
```

---

## E-Commerce (ecommerce)

**17 tables**: `ec_customer`, `ec_address`, `ec_category`, `ec_product`, `ec_product_variant`, `ec_cart`, `ec_cart_item`, `ec_order`, `ec_order_item`, `ec_payment_transaction`, `ec_shipment`, `ec_shipment_item`, `ec_return_request`, `ec_return_item`, `ec_coupon`, `ec_coupon_usage`, `ec_review`

Full-stack e-commerce operational schema from product catalogue through to orders, payments, fulfilment, returns, coupons, and customer reviews.

Key design points:
- `ec_product` / `ec_product_variant` separates the base product (name, category, description) from variants (SKU, colour, size, price, stock) — standard Product/SKU split
- `ec_cart` / `ec_cart_item` is ephemeral (soft-deleted on order creation); the generated views allow admin browsing of abandoned carts
- `ec_payment_transaction` supports multiple payment methods per order (split payment) via a one-to-many relationship with `ec_order`
- `ec_coupon` tracks discount codes with `discount_type` (`PERCENT`, `FIXED`), `min_order_value`, `max_uses`, and expiry; `ec_coupon_usage` records each redemption
- `ec_return_request` / `ec_return_item` models the RMA process: line-level return reasons, condition assessment, and resolution (`REFUND`, `EXCHANGE`, `STORE_CREDIT`)

```bash
flask forge templates apply ecommerce --database-uri postgresql://localhost/mydb

flask forge gen all \
  postgresql://localhost/mydb \
  --name MyShopApp \
  --output-dir ./shop_app/
```

Combining inventory with e-commerce:

```bash
for tmpl in inventory ecommerce; do
  flask forge templates apply $tmpl --database-uri postgresql://localhost/mydb
done

flask forge gen all \
  postgresql://localhost/mydb \
  --name MyShopApp \
  --output-dir ./shop_app/
```

The generator detects the FK relationship between `ec_product_variant` and `inv_product` (via `sku`) and generates a unified stock-on-hand panel in the product detail view.
