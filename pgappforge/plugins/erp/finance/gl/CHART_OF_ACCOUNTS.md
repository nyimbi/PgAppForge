# Chart of Accounts — PgAppForge ERP

Standard GL account codes used across all plugins in this suite.
These are **default** codes. Override per-tenant via the `cb_gl_mapping` table.
Import constants from `pgappforge.plugins.erp.finance.gl.constants` rather than
using string literals directly in plugin services.

## Override Mechanism

Each plugin that posts to GL calls `_resolve_gl(code, session, tenant_id)`, which:
1. Looks up `cb_gl_mapping` for a tenant-specific override of the given default code.
2. Falls back to the default code if no mapping exists.
3. Returns the resolved account code string.

This means a tenant can redirect any system posting to a different account code
without modifying plugin code.

---

## Account Codes

| Code | Account Name | Account Type | Normal Balance | Usage |
|------|-------------|--------------|---------------|-------|
| **ASSETS — Cash & Liquid** | | | | |
| 1011 | Cash and Nostro Accounts | ASSET | DEBIT | Primary cash / bank clearing accounts; core banking settlement ledger, treasury bank accounts |
| 1013 | Petty Cash Float | ASSET | DEBIT | Petty cash advances, small cash disbursements |
| **ASSETS — Receivables** | | | | |
| 1200 | Accounts Receivable Control | ASSET | DEBIT | AR sub-ledger control; project invoices (DR 1200 / CR 4000), customer billing |
| 1300 | Advance Receivable | ASSET | DEBIT | Travel cash advances disbursed to employees; settled when expense report is approved |
| 1400 | Intercompany Receivable | ASSET | DEBIT | Amounts owed by related entities; intercompany eliminations |
| **ASSETS — Inventory** | | | | |
| 1140 | Inventory — Raw Materials | ASSET | DEBIT | Goods received into stock; inventory receipt postings |
| 1150 | Inventory in Transit | ASSET | DEBIT | Goods on shipment not yet received at destination warehouse |
| 1160 | Work in Progress (WIP) | ASSET | DEBIT | Production orders in-progress; materials issued to production floor |
| 1170 | Finished Goods | ASSET | DEBIT | Completed production orders transferred from WIP |
| **ASSETS — Other Current** | | | | |
| 1500 | Prepaid Expenses | ASSET | DEBIT | Prepaid insurance, rent, subscriptions |
| 1510 | Prepaid Tax | ASSET | DEBIT | Withholding tax credits, instalment tax prepayments |
| 1520 | VAT Recoverable | ASSET | DEBIT | Input VAT claimable; VAT on purchases |
| 1560 | Accrued Income | ASSET | DEBIT | Revenue earned but not yet invoiced; accrual reversals |
| **ASSETS — Non-Current** | | | | |
| 1600 | Property, Plant & Equipment (Cost) | ASSET | DEBIT | Asset capitalisation; finance lease ROU assets |
| 1610 | Accumulated Depreciation | ASSET | CREDIT | Contra-asset; depreciation runs (IFRS / straight-line / declining balance) |
| **LIABILITIES — Current** | | | | |
| 2000 | Accounts Payable Control | LIABILITY | CREDIT | AP sub-ledger control; supplier invoices, 3-way match |
| 2100 | Accrued Expenses | LIABILITY | CREDIT | Period-end accruals not yet invoiced |
| 2110 | Accrued Salaries & Wages | LIABILITY | CREDIT | Payroll accrual; unpaid payroll at period end |
| 2120 | Accrued Leave Liability | LIABILITY | CREDIT | Annual leave balance liability |
| 2200 | VAT Payable | LIABILITY | CREDIT | Output VAT collected; VAT returns |
| 2250 | Withholding Tax Payable | LIABILITY | CREDIT | WHT deducted from suppliers; remittance to KRA |
| 2300 | PAYE Payable | LIABILITY | CREDIT | Employee income tax withheld; monthly PAYE remittance |
| 2310 | NSSF / SHIF Payable | LIABILITY | CREDIT | Statutory pension and health deductions; employer and employee portions |
| 2400 | Customer Deposits / Advances | LIABILITY | CREDIT | Advance payments received from customers before service delivery |
| 2500 | Lease Liability | LIABILITY | CREDIT | IFRS 16 lease liability; present value of future lease payments |
| **EQUITY** | | | | |
| 3200 | Retained Earnings | EQUITY | CREDIT | Period close transfers; cumulative net income |
| **REVENUE** | | | | |
| 4000 | Revenue — Services | REVENUE | CREDIT | Primary service revenue; T&M and fixed-fee project invoices, retainer recognition |
| 4100 | Revenue — Goods | REVENUE | CREDIT | Product sales revenue; goods invoiced |
| 4150 | Revenue — Subscriptions | REVENUE | CREDIT | Recurring subscription revenue; straight-line recognition |
| 4200 | Interest Income | REVENUE | CREDIT | Bank interest earned; treasury income on deposits and nostro balances |
| 4300 | FX Gain | REVENUE | CREDIT | Foreign exchange revaluation gains; FX deal settlements |
| 4500 | Other Income | REVENUE | CREDIT | Miscellaneous income; grants, penalties received |
| **EXPENSES — Cost of Sales** | | | | |
| 5100 | Cost of Goods Sold | EXPENSE | DEBIT | Inventory consumption matched to goods revenue |
| 5200 | Direct Labour Cost | EXPENSE | DEBIT | Labour cost applied to projects and production orders |
| 5500 | FX Loss | EXPENSE | DEBIT | Foreign exchange revaluation losses |
| 5600 | Finance Charges | EXPENSE | DEBIT | Loan interest, bank charges, IFRS 16 interest on lease liability |
| **EXPENSES — Operating** | | | | |
| 6100 | Salaries and Wages | EXPENSE | DEBIT | Net pay posted by payroll run |
| 6200 | Statutory Contributions — Employer | EXPENSE | DEBIT | Employer NSSF, Housing Levy, NITA |
| 6300 | Travel and Entertainment | EXPENSE | DEBIT | Approved expense reports; per-diem and accommodation |
| 6350 | Mileage Claims | EXPENSE | DEBIT | Vehicle mileage reimbursements |
| 6400 | Depreciation Expense | EXPENSE | DEBIT | Periodic depreciation run; charged to P&L |

---

## GL Mapping Table

```sql
-- cb_gl_mapping: tenant-level account code overrides
CREATE TABLE cb_gl_mapping (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    default_code VARCHAR(20) NOT NULL,   -- key from constants.py
    mapped_code  VARCHAR(20) NOT NULL,   -- replacement in this tenant's CoA
    description  TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, default_code)
);
```

## _resolve_gl() Pattern

```python
# In core_banking/services.py and any plugin that posts to GL
def _resolve_gl(self, default_code: str, session, tenant_id: str) -> str:
    """Return tenant-specific GL code if mapped, else the default."""
    from pgappforge.plugins.erp.finance.gl.models import GLAccount
    mapping = session.execute(
        select(CBGLMapping.mapped_code).where(
            CBGLMapping.tenant_id == tenant_id,
            CBGLMapping.default_code == default_code,
            CBGLMapping.is_active == True,
        )
    ).scalar_one_or_none()
    return mapping or default_code
```

Import the constants rather than embedding string literals:

```python
from pgappforge.plugins.erp.finance.gl.constants import (
    CASH_AND_NOSTRO, AR_CONTROL, REVENUE_SERVICES,
    SALARIES_AND_WAGES, PAYE_PAYABLE,
)
```

---

## Notes

- All amounts posted against these accounts are **integer cents** (BigInteger). Never float.
- Accounts 1600 and 1610 are managed by the `finance.assets` plugin; other plugins
  reference them via `_resolve_gl()` but do not own the account master data.
- Accounts 2300 and 2310 are populated by `hcm.payroll`; the posting uses
  `GLService.post_simple_journal()` after a payroll run is approved.
- Account 1300 is debited by `hcm.travel_expense` when a cash advance is disbursed
  and credited when the corresponding expense report is approved and the advance settled.
- Accounts 4000–4500 are credited by AR, Projects, and Commerce plugins; the specific
  account depends on the invoice type and project type.
