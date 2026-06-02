# Financial Services Cloud Plugin — SPEC

**Plugin**: `financial_services`
**Domain**: `industry`
**Depends on**: `foundation`
**Version**: 1.0.0

---

## Entities

### FinancialClient (`fin_financial_client`)
Links to `erp_party` for identity. Carries FS-specific compliance state.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | multi-tenant isolation |
| party_id | UUID FK erp_party | RESTRICT |
| client_number | VARCHAR(50) UNIQUE | auto or user-assigned |
| client_type | VARCHAR(20) | INDIVIDUAL \| CORPORATE \| INSTITUTION |
| risk_profile | VARCHAR(15) | LOW \| MEDIUM \| HIGH \| SPECULATIVE |
| kyc_status | VARCHAR(15) | PENDING \| APPROVED \| REJECTED \| EXPIRED |
| kyc_completed_at | TIMESTAMPTZ | nullable |
| aml_score | NUMERIC(5,4) | [0.0000, 1.0000] nullable |
| sanctions_screened_at | TIMESTAMPTZ | nullable |
| relationship_manager_id | INTEGER FK ab_user | nullable |
| onboarded_at | TIMESTAMPTZ | nullable |
| total_aum_cents | INTEGER | never float |
| net_worth_cents | INTEGER | never float |

### PortfolioAccount (`fin_portfolio_account`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| client_id | UUID FK fin_financial_client | RESTRICT |
| account_number | VARCHAR(50) UNIQUE | |
| account_type | VARCHAR(15) | SAVINGS \| CHECKING \| INVESTMENT \| PENSION \| INSURANCE |
| currency_code | VARCHAR(3) FK erp_currency | |
| balance_cents | INTEGER | ledger balance |
| available_balance_cents | INTEGER | after holds |
| status | VARCHAR(10) | ACTIVE \| DORMANT \| FROZEN \| CLOSED |

### FinancialProduct (`fin_financial_product`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| product_code | VARCHAR(50) UNIQUE | |
| product_type | VARCHAR(15) | LOAN \| DEPOSIT \| INSURANCE \| INVESTMENT \| CARD |
| name | VARCHAR(300) | |
| description | TEXT | nullable |
| min_amount_cents | INTEGER | |
| max_amount_cents | INTEGER | 0 = unlimited |
| interest_rate_pct | NUMERIC(8,4) | annual % |
| term_months | INTEGER | nullable |
| risk_category | VARCHAR(50) | nullable |
| regulatory_category | VARCHAR(100) | nullable |
| is_active | BOOLEAN | |

### ClientHolding (`fin_client_holding`)
**Immutable**: each revaluation inserts a new row. Never UPDATE.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| client_id | UUID FK fin_financial_client | RESTRICT |
| instrument_isin | CHAR(12) | ISO 6166 |
| instrument_name | VARCHAR(500) | |
| quantity | NUMERIC(20,8) | fractional shares |
| avg_cost_cents | INTEGER | per unit |
| current_value_cents | INTEGER | total position value |
| unrealized_pnl_cents | INTEGER | current_value - (avg_cost × qty) |
| as_of_date | DATE | snapshot date |

### SanctionsScreeningResult (`fin_sanctions_screening`)
**Immutable**: each screening inserts a new row. Never UPDATE.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| party_id | UUID FK erp_party | RESTRICT |
| screening_date | TIMESTAMPTZ | |
| list_type | VARCHAR(10) | OFAC \| EU \| UN \| UK \| LOCAL |
| match_found | BOOLEAN | |
| match_score | NUMERIC(5,4) | nullable |
| match_details | JSONB | raw evidence |
| cleared_by | INTEGER FK ab_user | nullable |
| cleared_at | TIMESTAMPTZ | nullable |
| status | VARCHAR(20) | CLEAR \| POTENTIAL_MATCH \| CONFIRMED_MATCH |

---

## Relationships

```
erp_party 1──* FinancialClient
FinancialClient 1──* PortfolioAccount
FinancialClient 1──* ClientHolding
erp_party 1──* SanctionsScreeningResult
```

---

## Business Rules

1. **KYC gate**: PortfolioAccount can only be opened for a client with `kyc_status = APPROVED`.
2. **Sanctions block**: `kyc_status` cannot be set to `APPROVED` if the party has a `CONFIRMED_MATCH` sanctions record.
3. **Immutable ledger (holdings)**: ClientHolding rows are never updated. Each revaluation or trade creates a new snapshot row.
4. **Immutable ledger (sanctions)**: SanctionsScreeningResult rows are never updated. Clearance inserts a new CLEAR row referencing the original POTENTIAL_MATCH.
5. **Frozen account**: No debits allowed on `status = FROZEN` accounts.
6. **Insufficient funds**: Debit that would push `available_balance_cents` below zero is rejected with `InsufficientBalanceError`.
7. **Product amount range**: `min_amount_cents` must be ≤ `max_amount_cents` (when max > 0).

---

## API Endpoints

### Clients
| Method | Path | Description |
|--------|------|-------------|
| GET | /finserv/clients/ | List clients (tenant-scoped) |
| GET | /finserv/clients/{id} | Client detail |
| POST | /finserv/clients/ | Onboard client (KYC=PENDING) |
| POST | /finserv/clients/{id}/approve-kyc | Approve KYC |
| POST | /finserv/clients/{id}/risk-profile | Reclassify risk |

### Accounts
| Method | Path | Description |
|--------|------|-------------|
| GET | /finserv/accounts/ | List accounts |
| GET | /finserv/accounts/{id} | Account detail |
| POST | /finserv/accounts/ | Open account |
| POST | /finserv/accounts/{id}/transact | Credit/debit (delta_cents) |

### Products
| Method | Path | Description |
|--------|------|-------------|
| GET | /finserv/products/ | List products |
| POST | /finserv/products/ | Create product |

### Sanctions
| Method | Path | Description |
|--------|------|-------------|
| POST | /finserv/sanctions/screen | Run screening |
| POST | /finserv/sanctions/{id}/clear | Clear POTENTIAL_MATCH |
| GET | /finserv/sanctions/watchlist | AML watchlist |

### Reports
| Method | Path | Description |
|--------|------|-------------|
| GET | /finserv/reports/portfolio/{client_id} | Portfolio summary |
| GET | /finserv/reports/aml-watchlist | AML watchlist report |
| GET | /finserv/reports/product-exposure | Product type exposure |

---

## Events

### Emitted
| Event | Trigger |
|-------|---------|
| `finserv.client.onboarded` | `onboard_client()` |
| `finserv.client.kyc_status_changed` | `approve_kyc()` |
| `finserv.client.risk_profile_changed` | `change_risk_profile()` |
| `finserv.account.opened` | `open_account()` |
| `finserv.account.balance_updated` | `post_account_transaction()` |
| `finserv.holding.revalued` | `record_holding_snapshot()` |
| `finserv.sanctions.screening_completed` | `screen_sanctions()` |
| `finserv.sanctions.match_cleared` | `clear_sanctions_match()` |

### Consumed
| Event | Action |
|-------|--------|
| `party.created` | (optional) pre-create FinancialClient shell |

---

## Cross-plugin Composability

- **Upstream**: `foundation` (Party, Currency, DomainEventLog)
- **Downstream consumers of our events**:
  - `finance.ar` — `finserv.account.balance_updated` → generate AR entries
  - `grc.controls` — `finserv.sanctions.screening_completed` → compliance alerts
  - `analytics.cdp` — `finserv.client.onboarded` → customer profile update
