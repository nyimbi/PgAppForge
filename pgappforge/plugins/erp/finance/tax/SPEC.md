# Tax Management Plugin — SPEC

## Domain
`finance` — depends on `foundation`

## Entities

### TaxJurisdiction
A geographic/legal tax authority that levies tax.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| code | VARCHAR(20) | e.g. NG-FIRS, DE-VAT, US-CA. Unique per tenant |
| name | VARCHAR(200) | |
| country_code | VARCHAR(2) FK erp_country | ISO 3166-1 alpha-2 |
| region_code | VARCHAR(20) | State/province |
| tax_type | VARCHAR(15) | VAT \| GST \| SALES_TAX \| WHT |
| tax_authority_name | VARCHAR(200) | e.g. FIRS, HMRC, IRS |
| filing_frequency | VARCHAR(20) | MONTHLY \| QUARTERLY \| ANNUALLY |
| tax_authority_reference | VARCHAR(100) | Registered tax ID with authority |
| is_active | BOOLEAN | |
| metadata | JSONB | |

### TaxCode
Tax rate within a jurisdiction, time-effective.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| jurisdiction_id | UUID FK TaxJurisdiction | |
| code | VARCHAR(20) | e.g. STD, ZR, EX, RR, WHT15 |
| description | VARCHAR(200) | |
| rate | NUMERIC(7,4) | e.g. 7.5000 = 7.5%. Never float |
| effective_from | DATE | Start of applicability |
| effective_to | DATE | NULL = currently applicable |
| is_input_tax | BOOLEAN | Claimable as input credit |
| is_output_tax | BOOLEAN | Charged on sales |
| is_zero_rated | BOOLEAN | 0% rate, taxable supply (input credit allowed) |
| is_exempt | BOOLEAN | Exempt supply (no input credit) |
| is_reverse_charge | BOOLEAN | IFRS B2B cross-border reverse charge |
| gl_account | VARCHAR(50) | Tax GL account |
| is_active | BOOLEAN | |
| metadata | JSONB | |

Unique constraint: (jurisdiction_id, code, effective_from)

### TaxReturn (IMMUTABLE after FILED)
Aggregated tax return for a filing period.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| jurisdiction_id | UUID FK TaxJurisdiction | |
| period_start | DATE | First day of period |
| period_end | DATE | Last day of period |
| filing_date | DATE | Date submitted |
| due_date | DATE | Statutory deadline |
| output_tax_cents | INTEGER | Tax charged on sales |
| input_tax_cents | INTEGER | Recoverable input tax |
| net_tax_cents | INTEGER | output - input (positive = payable) |
| taxable_supplies_cents | INTEGER | Total taxable supply value |
| exempt_supplies_cents | INTEGER | Total exempt supply value |
| status | VARCHAR(20) | DRAFT \| FILED \| PAID \| REFUND_CLAIMED |
| reference_number | VARCHAR(100) | Authority submission reference |
| payment_reference | VARCHAR(100) | |
| payment_date | DATE | |
| amended_return_id | UUID FK TaxReturn | FK to return being amended |
| notes | TEXT | |
| metadata | JSONB | |

### TaxTransaction (IMMUTABLE — append-only)
Individual tax line generated from a source document.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| tax_code_id | UUID FK TaxCode | |
| source_document_type | VARCHAR(100) | e.g. 'SalesInvoice' |
| source_document_id | VARCHAR(64) | UUID of source doc |
| taxable_amount_cents | INTEGER | Net base amount |
| tax_amount_cents | INTEGER | Calculated tax. Negative = reversal |
| is_recoverable | BOOLEAN | Input credit eligible |
| posting_date | DATE | Tax point date |
| tax_period | VARCHAR(10) | e.g. "2026-01" |
| currency_code | VARCHAR(3) | |
| exchange_rate | NUMERIC(20,8) | FX rate if multicurrency |
| reporting_tax_amount_cents | INTEGER | In reporting currency |
| is_reversal | BOOLEAN | |
| reversal_of_id | UUID FK TaxTransaction | |
| created_at | TIMESTAMPTZ | |

## Business Rules

1. `rate >= 0` and `rate <= 100` (percentage points)
2. A TaxCode cannot be both `is_exempt=True` AND `is_zero_rated=True`
3. `effective_to > effective_from` (when effective_to is set)
4. For non-reversal TaxTransactions: `taxable_amount_cents >= 0`
5. A PAID TaxReturn cannot be modified — create an amended return
6. net_tax_cents = output_tax_cents - input_tax_cents (calculated, not stored independently)
7. All monetary amounts: INTEGER cents (never float)
8. Correction pattern: insert reversal TaxTransaction (never UPDATE)

## Tax Type Semantics

| Tax Type | Input Credit | Output Charge | Withholding |
|----------|-------------|---------------|-------------|
| VAT | Yes (is_input_tax) | Yes (is_output_tax) | No |
| GST | Yes | Yes | No |
| SALES_TAX | No | Yes | No |
| WHT | N/A | N/A | Yes (deducted at source) |

## VAT Return Generation Algorithm
1. Aggregate `output_tax_cents`: SUM(tax_amount_cents) WHERE tax_code.is_output_tax = True AND posting_date IN period
2. Aggregate `input_tax_cents`: SUM(tax_amount_cents) WHERE tax_code.is_input_tax = True AND is_recoverable = True AND posting_date IN period
3. `net_tax_cents` = output - input
4. Upsert DRAFT TaxReturn (idempotent on period re-generation)

## Tax Code Lookup
Finds the applicable rate for a given date:
```sql
WHERE jurisdiction.code = :code
  AND tax_code.code = :tax_code
  AND effective_from <= :as_of_date
  AND (effective_to IS NULL OR effective_to >= :as_of_date)
ORDER BY effective_from DESC LIMIT 1
```

## API Endpoints

| Method | Path | Action |
|--------|------|--------|
| GET | /tax/jurisdictions/ | List jurisdictions |
| POST | /tax/jurisdictions/ | Create jurisdiction |
| PUT | /tax/jurisdictions/<id> | Update jurisdiction |
| GET | /tax/codes/ | List tax codes |
| POST | /tax/codes/ | Create tax code |
| GET | /tax/codes/lookup | Rate lookup by jurisdiction+code+date |
| GET | /tax/transactions/ | List tax transactions |
| POST | /tax/transactions/ | Post tax transaction |
| POST | /tax/transactions/calculate | Calculate tax (dry run, no posting) |
| GET | /tax/returns/ | List tax returns |
| GET | /tax/returns/<id> | Return detail |
| POST | /tax/returns/generate | Generate draft return for period |
| POST | /tax/returns/<id>/file | Submit return |
| POST | /tax/returns/<id>/pay | Mark return paid |
| GET | /tax/reports/vat-return/<id> | VAT Return printable (HTML) |
| GET | /tax/reports/tax-liability | Outstanding liabilities (HTML) |
| GET | /tax/reports/input-tax-credit | Input tax credit analysis (HTML) |

## Events

### Emitted
- `tax.transaction_posted` — tax line created
- `tax.return_generated` — draft return aggregated
- `tax.return_filed` — return submitted to authority
- `tax.return_paid` — tax payment confirmed
- `tax.rate_expired` — TaxCode effective_to date passed

### Consumed
- `invoice.posted` — triggers automatic tax calculation (when TAX_AUTO_POST_ON_INVOICE=True)
- `payment.posted` — triggers WHT deduction creation
- `exchange_rate.updated` — multicurrency tax restatement

## Reports

1. **VAT Return Detail** (`/tax/reports/vat-return/<id>`) — printable VAT return form with Box 1 (output), Box 2 (input), Box 3 (net), filing status and reference. Print-ready for submission.
2. **Tax Liability Summary** (`/tax/reports/tax-liability`) — all outstanding DRAFT/FILED returns with net payable amounts, due dates, total exposure across jurisdictions.
3. **Input Tax Credit Analysis** (`/tax/reports/input-tax-credit`) — aggregated input tax by period, jurisdiction, tax code, and recoverability status. Identifies blocked input credit.

## Rules Engine Rulesets (pre-configured)

1. `tax_code.positive_rate` — rate must be >= 0 and <= 100
2. `tax_code.exempt_and_zero_rated_exclusive` — cannot be both exempt and zero-rated
3. `tax_code.effective_date_order` — effective_to must be after effective_from
4. `tax_transaction.positive_taxable_amount` — non-negative for non-reversals
5. `tax_return.no_amend_paid` — PAID returns are immutable
