# Supplier Portal Plugin — Design Comparison

## vs. Odoo Vendor Management

| Dimension | Odoo | This plugin |
|---|---|---|
| Supplier model | `res.partner` with `supplier_rank` flag | Dedicated `SupplierProfile` with full KYC lifecycle |
| KYC | No native KYC workflow | PENDING → APPROVED / REJECTED / SUSPENDED with approver + timestamp |
| Bank details | `res.partner.bank` child records | Inline on `SupplierProfile` + `bank_verified` flag |
| Performance | No built-in scorecard | `SupplierPerformanceCard` per period; weighted composite |
| Suspension | Archive (hide) | Explicit `kyc_status=SUSPENDED`; separate from physical deletion |
| Multi-tenancy | Company-level | `tenant_id` UUID on every row |
| Events | Log note / activity | Domain events via `foundation.events` |
| Self-registration | Not available (internal record) | `register_supplier()` can be exposed via portal endpoint |

## vs. SAP SRM / Ariba Supplier Lifecycle Management

| Dimension | SAP Ariba SLM | This plugin |
|---|---|---|
| Registration | Full self-service portal with questionnaire | `register_supplier()` + `submit_kyc_documents()` |
| KYC tiers | Multiple document categories + risk scoring | `kyc_documents` JSONB array + manual `approve_kyc()` |
| Performance | Supplier scorecard with KPIs | `SupplierPerformanceCard` with 4 KPIs + weighted composite |
| Bank verification | ERP / treasury integration | `verify_bank_details()` with `bank_verified` flag; external verification advisory |
| Preferred supplier | Preferred supplier list | `is_preferred` Boolean flag + `get_approved_suppliers()` query |
| Suspension / blacklist | Supplier debarment module | `suspend_supplier()` with reason; `SUSPENDED` terminal state |
| Category management | Commodity codes / UNSPSC | `primary_category` string (GOODS/SERVICES/WORKS) |

## Design decisions

### Performance composite formula
```
composite = 0.4 * on_time_delivery_pct
          + 0.3 * quality_acceptance_pct
          + 0.2 * invoice_accuracy_pct
          + 0.1 * responsiveness_score
```
Weights are hard-coded in the service but exposed in `SUPPLIER_PORTAL_PERFORMANCE_WEIGHTS`
config for future configurability. On-time delivery (40%) is dominant because it directly
affects downstream production and customer commitments.

### Rolling overall_score
`_compute_overall_score()` runs `AVG(composite_score)` across all `SupplierPerformanceCard`
rows for the supplier. This is recomputed on every `rate_supplier()` call — no cache.
For suppliers with many periods (>20), consider maintaining a running average in the
application rather than querying all history.

### Why inline bank details vs. separate table?
A supplier has one primary bank account for payment purposes. A dedicated table would be
appropriate if multiple bank accounts (multi-currency, regional) are needed. The `bank_swift`
field handles international wires; a future enhancement could add `bank_iban`.

### KYC document JSONB vs. child table
KYC documents are uploaded once, reviewed once, and rarely queried individually.
JSONB keeps the schema simpler. If document-level lifecycle (individual document approval,
expiry tracking) is needed, a `SupplierDocument` child table should be introduced.

### Suspension vs. deletion
Suppliers with historical POs must never be deleted — they remain reference data.
`kyc_status=SUSPENDED` blocks them from appearing in approved-supplier queries and
sourcing invitations while preserving audit history. Hard delete is not exposed.

### `get_approved_suppliers()` returns only APPROVED
Procurement workflows (RFQ invitations, PO creation) should only see APPROVED suppliers.
PENDING suppliers may be invited to RFQs manually by passing their IDs directly to
`SourcingService.publish_rfq()`, which accepts advisory string IDs without KYC validation.

## Limitations / future work

- No document-level expiry tracking (certificate renewals).
- No multi-bank-account support.
- No risk scoring integration (credit checks, sanctions screening).
- `primary_category` is a free-form string constrained to GOODS/SERVICES/WORKS;
  sub-category (commodity code, UNSPSC) not yet modelled.
- KYC rejection reason is not stored — only the status transition.
  A `kyc_rejection_reason` column could be added without breaking the API.
- No email notifications on KYC status change (requires notification plugin).
- Performance card weights are hard-coded; a future `PerformanceWeightConfig` table
  would allow per-tenant or per-category weight customisation.
