# GL Plugin Specification

**Domain**: finance  
**Plugin name**: gl  
**Version**: 1.0.0  
**Depends on**: foundation

---

## 1. Purpose

Double-entry General Ledger providing:
- Hierarchical chart of accounts with IFRS/GAAP concept mapping
- Fiscal year and accounting period management
- Journal batch / entry / line workflow with approval gates
- Immutable posted-transaction ledger (correction via reversal only)
- Period account balance snapshots for fast reporting
- Budget vs actual tracking per account/cost-centre/period
- Cost centre management reporting dimension

---

## 2. Entities

### GLAccount (gl_account)

| Column | Type | Notes |
|--------|------|-------|
| account_code | VARCHAR(20) PK | Natural key e.g. "1000", "1000.10" |
| tenant_id | UUID NOT NULL | Multi-tenant isolation |
| account_name | VARCHAR(255) NOT NULL | |
| account_type | VARCHAR(20) NOT NULL | ASSET\|LIABILITY\|EQUITY\|REVENUE\|EXPENSE\|STATISTICAL |
| account_subtype | VARCHAR(50) | Current/Non-current, Operating/Non-operating, etc. |
| normal_balance | VARCHAR(6) NOT NULL | DEBIT\|CREDIT — derived from account_type |
| parent_code | VARCHAR(20) FK→self | Hierarchy root has NULL |
| is_posting_account | BOOLEAN | False = summary/header, no journal lines |
| is_reconciliation_account | BOOLEAN | Requires periodic bank/sub-ledger reconciliation |
| currency_code | CHAR(3) FK→erp_currency | NULL = multi-currency |
| ifrs_concept | VARCHAR(100) | e.g. ifrs-full:Cash |
| gaap_concept | VARCHAR(100) | US GAAP taxonomy ref |
| is_active | BOOLEAN | Inactive accounts: warn on posting |
| description | TEXT | |
| attributes | JSONB | Extensible metadata |

### GLCostCenter (gl_cost_center)

Organisational dimension for management reporting.  
Self-referential hierarchy via `parent_code` (soft FK — no DB FK to avoid cross-tenant leaks).

### GLFiscalYear (gl_fiscal_year)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| year_code | VARCHAR(20) | e.g. FY2025 |
| fiscal_year | INTEGER | Calendar year integer |
| start_date / end_date | DATE | |
| status | VARCHAR(20) | OPEN\|CLOSED\|LOCKED |

### GLPeriod (gl_period)

One period per calendar month (period_number 1–12, or up to 13 for 13-period calendars).

| Status | Meaning |
|--------|---------|
| OPEN | Accepts new journal postings |
| CLOSED | Soft close — management reports, still editable by super-user |
| LOCKED | Hard lock — no new postings, ever |

### GLJournalBatch (gl_journal_batch)

Container for atomic set of entries.

| Status flow | |
|------------|--|
| DRAFT → SUBMITTED → APPROVED → POSTED | Normal workflow |
| POSTED → REVERSED | Via reversal entry only |

`total_debits` / `total_credits` maintained by application code.  
`is_balanced` = (total_debits == total_credits).  
All amounts: **BigInteger (integer cents)**. Never Numeric/float.

### GLJournalEntry (gl_journal_entry)

Groups lines that together balance.  
`reversal_of_entry_id` self-FK links reversal to origin.  
`auto_reverse` + `auto_reverse_date` for accrual auto-reversal.

### GLJournalLine (gl_journal_line)

Atomic debit or credit movement.

| Column | Notes |
|--------|-------|
| debit_amount / credit_amount | Transaction-currency integer cents |
| base_debit / base_credit | Functional-currency integer cents after FX |
| fx_rate | NUMERIC(15,6) — never float |
| cost_center_code | Management dimension |
| project_code | Project tracking |
| party_id | FK→erp_party (customer/supplier on GL line) |
| tax_code | For tax reporting |

**Immutable once entry is POSTED.**

### GLAccountBalance (gl_account_balance)

Period snapshot maintained by `GLService.post_journal()`.  
Unique constraint: (tenant_id, account_code, period_id).  
All amounts: BigInteger cents.

For authoritative balances in an OPEN period, recompute from `gl_journal_line`.

### GLBudget (gl_budget)

| Version | Meaning |
|---------|---------|
| ORIGINAL | Initial approved budget |
| REVISED | Mid-year amendment |
| FORECAST | Rolling forecast |

---

## 3. Business Rules

| # | Rule | Where enforced |
|---|------|----------------|
| R1 | Batch must balance (total_debits == total_credits) before posting | `GLService.post_journal()` + Rules Engine ruleset `gl.journal_batch.balance_check` |
| R2 | Cannot post to CLOSED or LOCKED period | `GLService.post_journal()` + `GLService.reverse_journal()` |
| R3 | Cannot post to inactive account | `GLService.post_journal()` |
| R4 | Cannot post to summary/header account (is_posting_account=False) | `GLService.post_journal()` |
| R5 | Posted journal lines are immutable — use reversal | Immutable ledger pattern; Rules Engine `gl.journal_batch.no_draft_modification` |
| R6 | LOCKED period cannot be re-opened | Rules Engine `gl.period.no_open_after_lock` |
| R7 | Cannot close period with unposted batches | `GLService.close_period()` |
| R8 | All amounts: integer cents — never float | Enforced via BigInteger column type |

---

## 4. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /gl/accounts/ | List chart of accounts |
| GET | /gl/accounts/\<code\> | Account detail |
| POST | /gl/accounts/ | Create account |
| PUT | /gl/accounts/\<code\> | Update account metadata |
| GET | /gl/periods/ | List periods |
| POST | /gl/periods/ | Create period |
| POST | /gl/periods/\<id\>/close | Lock period |
| GET | /gl/batches/ | List batches |
| POST | /gl/batches/ | Create batch |
| POST | /gl/batches/\<id\>/entries | Add entry + lines to batch |
| POST | /gl/batches/\<id\>/submit | Submit for approval |
| POST | /gl/batches/\<id\>/approve | Approve batch |
| POST | /gl/batches/\<id\>/post | Post batch (validates balance) |
| GET | /gl/entries/\<id\> | Entry detail with lines |
| POST | /gl/entries/\<id\>/reverse | Create reversal entry |
| GET | /gl/budgets/ | List budgets |
| POST | /gl/budgets/ | Create budget line |
| GET | /gl/reports/ | Report index |
| GET | /gl/reports/trial-balance/\<period_id\> | Trial balance |
| GET | /gl/reports/budget-vs-actual/\<period_id\> | Budget vs actual |
| GET | /gl/reports/account-ledger/\<account_code\> | Transaction history |

---

## 5. Domain Events

### Emitted

| Event type | Trigger | Key payload fields |
|-----------|---------|-------------------|
| `gl.journal.posted` | Per line in `post_journal()` | entry_id, account_code, amount (cents), debit_credit, currency_code, posting_date |
| `gl.batch.posted` | Batch transitions to POSTED | batch_id, batch_number, total_debits, total_credits, period_id |
| `gl.journal.reversed` | Reversal entry created | original_entry_id, reversal_entry_id, reversal_date |
| `gl.period.closed` | Period locked | period_id, fiscal_year, period_number, closed_by |

### Consumed

None in v1.  Planned:
- `ap.invoice.approved` → auto-generate AP accrual journal
- `ar.payment.received` → auto-generate AR receipt journal

---

## 6. Rules Engine Rulesets (5 pre-configured)

| Ruleset name | Model | Trigger | Action |
|-------------|-------|---------|--------|
| `gl.journal_batch.balance_check` | GLJournalBatch | on_before_update (→POSTED) | raise_error if not balanced |
| `gl.journal_entry.no_post_to_closed_period` | GLJournalEntry | on_before_update | (service layer primary guard) |
| `gl.account.warn_inactive_posting` | GLJournalLine | on_before_create | log WARNING |
| `gl.journal_batch.no_draft_modification` | GLJournalBatch | on_before_update | raise_error on status regression |
| `gl.period.no_open_after_lock` | GLPeriod | on_before_update | raise_error if LOCKED→OPEN |

---

## 7. Reports

| Report | Description | Key columns |
|--------|-------------|-------------|
| Trial Balance | Closing debit/credit per account for a period | account_code, account_name, closing_debit, closing_credit, net |
| Budget vs Actual | Budget compared to posted actuals per account/period | account_code, budget, actual, variance, variance_pct |
| Account Ledger | Posted transaction history for one account | posting_date, entry_number, description, debit, credit, running_balance |

---

## 8. Cross-Plugin Composability

```
foundation  →  gl  →  ap (Accounts Payable, planned)
                   →  ar (Accounts Receivable, planned)
                   →  fa (Fixed Assets, planned)
```

The GL plugin subscribes to upstream events from AP/AR to auto-generate journal entries.  
Downstream plugins subscribe to `gl.journal.posted` for sub-ledger reconciliation.

---

## 9. Immutable Ledger Pattern

Financial records MUST follow these rules:

1. **Never UPDATE posted gl_journal_entry or gl_journal_line rows.**
2. To correct an error: call `GLService.reverse_journal()` which creates a mirror entry.
3. Then post a new corrected entry.
4. The audit trail is complete and tamper-evident.

This is enforced by:
- Rules Engine ruleset `gl.journal_batch.no_draft_modification`
- Application-level guards in `GLService.post_journal()`
- No `updated_at` column on `gl_journal_line` (immutable design signal)
