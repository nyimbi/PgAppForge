# Treasury Management Plugin — SPEC

## Domain
`finance` — depends on `foundation`

## Entities

### BankAccount
Bank account master record with real-time balance tracking.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| account_number | VARCHAR(50) | Unique per tenant |
| bank_name | VARCHAR(200) | |
| bank_bic | VARCHAR(11) | SWIFT/BIC code |
| iban | VARCHAR(34) | |
| currency_code | VARCHAR(3) FK erp_currency | ISO 4217 |
| account_type | VARCHAR(20) | CURRENT \| SAVINGS \| OVERDRAFT |
| gl_account | VARCHAR(50) | Chart of accounts code |
| balance_cents | INTEGER | Confirmed ledger balance |
| available_balance_cents | INTEGER | Net of holds/uncleared |
| overdraft_limit_cents | INTEGER | OVERDRAFT accounts only |
| last_reconciled_date | DATE | |
| is_active | BOOLEAN | |
| is_default | BOOLEAN | |
| metadata | JSONB | |

### CashPosition (append-only daily snapshot)
Daily cash position per bank account. Corrections insert a new row.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| bank_account_id | UUID FK BankAccount | |
| position_date | DATE | |
| opening_balance_cents | INTEGER | |
| receipts_cents | INTEGER | |
| payments_cents | INTEGER | |
| closing_balance_cents | INTEGER | opening + receipts - payments |
| forecast_balance_cents | INTEGER | Forecast model output |
| created_at | TIMESTAMPTZ | |

### FXDeal
Foreign exchange deal with IFRS 9 hedge designation support.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| deal_reference | VARCHAR(50) | Unique per tenant, auto FX-YYYY-NNNNN |
| deal_type | VARCHAR(10) | SPOT \| FORWARD \| SWAP |
| buy_currency | VARCHAR(3) FK erp_currency | |
| sell_currency | VARCHAR(3) FK erp_currency | |
| buy_amount_cents | INTEGER | Amount received |
| sell_amount_cents | INTEGER | Amount paid |
| contracted_rate | NUMERIC(20,8) | Never float |
| market_rate | NUMERIC(20,8) | At deal booking |
| settlement_date | DATE | |
| trade_date | DATE | |
| counterparty_id | UUID | FK to erp_party.id |
| buy_bank_account_id | UUID FK BankAccount | |
| sell_bank_account_id | UUID FK BankAccount | |
| hedge_designation | VARCHAR(20) | FAIR_VALUE \| CASH_FLOW \| NET_INVESTMENT \| NONE |
| hedged_item_id | UUID | Logical FK to hedged exposure |
| hedged_item_type | VARCHAR(100) | e.g. 'SalesInvoice' |
| status | VARCHAR(15) | OPEN \| SETTLED \| CANCELLED |
| mtm_value_cents | INTEGER | Mark-to-market fair value |
| metadata | JSONB | |

### BankStatement
Imported bank statement header.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| bank_account_id | UUID FK BankAccount | |
| statement_date | DATE | |
| opening_balance_cents | INTEGER | |
| closing_balance_cents | INTEGER | |
| status | VARCHAR(15) | IMPORTED \| RECONCILED |
| import_reference | VARCHAR(100) | |

### BankStatementLine
Individual transaction line from an imported bank statement.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| statement_id | UUID FK BankStatement | CASCADE DELETE |
| transaction_date | DATE | |
| value_date | DATE | |
| description | VARCHAR(500) | |
| amount_cents | INTEGER | Always positive |
| is_debit | BOOLEAN | Bank's perspective (debit = money out) |
| bank_reference | VARCHAR(100) | |
| match_status | VARCHAR(15) | UNMATCHED \| MATCHED \| EXCEPTION |
| matched_document_type | VARCHAR(100) | |
| matched_document_id | VARCHAR(64) | |
| matched_at | TIMESTAMPTZ | |
| exception_reason | TEXT | |

## Business Rules

1. `buy_amount_cents > 0` and `sell_amount_cents > 0` for all FX deals
2. `contracted_rate > 0` (NUMERIC, never float)
3. `hedge_designation` must be one of: FAIR_VALUE, CASH_FLOW, NET_INVESTMENT, NONE
4. A CANCELLED deal cannot be SETTLED
5. Statement reconciliation is idempotent — already-RECONCILED statements are rejected
6. `balance_cents` and `available_balance_cents` on BankAccount are maintained by service layer
7. CashPosition rows are append-only; service queries MAX(created_at) for current position

## FX Deal Lifecycle
```
OPEN → SETTLED  (via settle_fx_deal)
OPEN → CANCELLED
```
SETTLED and CANCELLED are terminal.

## Reconciliation Strategy
1. Exact amount + bank_reference match → MATCHED
2. Exact amount + date proximity (±2 days) → MATCHED
3. No match found → EXCEPTION (manual review)
All EXCEPTION lines prevent RECONCILED status on the statement header.

## Cash Flow Forecast
- Opening balance: latest confirmed CashPosition.closing_balance_cents
- Receipts: pending FX deal buy_amount_cents on settlement_date within horizon
- Payments: AP due-date schedule (hook for AP plugin integration)
- Returns N daily forecast rows for `days_ahead` days

## Mark-to-Market (MTM)
- Queries latest ExchangeRate for each open deal's currency pair
- MTM = (market_rate - contracted_rate) * notional_sell_amount_cents
- Updates FXDeal.mtm_value_cents (signed: positive = gain, negative = loss)
- Non-destructive: original contracted_rate never modified

## API Endpoints

| Method | Path | Action |
|--------|------|--------|
| GET | /treasury/accounts/ | List bank accounts |
| POST | /treasury/accounts/ | Create bank account |
| GET | /treasury/accounts/<id> | Account detail |
| GET | /treasury/fx-deals/ | List FX deals |
| POST | /treasury/fx-deals/ | Book FX deal |
| POST | /treasury/fx-deals/<id>/settle | Settle deal |
| POST | /treasury/fx-deals/mtm | Mark-to-market all open deals |
| GET | /treasury/statements/ | List statements |
| POST | /treasury/statements/ | Import statement + lines |
| POST | /treasury/statements/<id>/reconcile | Run reconciliation |
| GET | /treasury/statements/<id>/lines | List statement lines |
| GET | /treasury/reports/cash-position | Daily cash position (HTML) |
| GET | /treasury/reports/fx-exposure | Open FX exposure (HTML) |
| GET | /treasury/reports/bank-balances | Bank balances summary (HTML) |

## Events

### Emitted
- `treasury.bank_account_created`
- `treasury.fx_deal_booked`
- `treasury.fx_deal_settled`
- `treasury.bank_reconciliation_done`
- `treasury.cash_position_updated`

### Consumed
- `exchange_rate.updated` — triggers MTM revaluation (when TREASURY_MTM_AUTO_ON_RATE_UPDATE=True)
- `party.created` — auto-link counterparties

## Reports

1. **Cash Position** (`/treasury/reports/cash-position`) — daily closing balance, receipts, payments, forecast. Last 30 days per account.
2. **FX Exposure** (`/treasury/reports/fx-exposure`) — all open FX deals with contracted rate, MTM value, settlement date, hedge designation.
3. **Bank Balances** (`/treasury/reports/bank-balances`) — all active bank accounts with current balance, available balance, last reconciliation date.

## Rules Engine Rulesets (pre-configured)

1. `bank_account.valid_account_type` — must be CURRENT, SAVINGS, or OVERDRAFT
2. `fx_deal.positive_amounts` — buy and sell amounts must be positive
3. `fx_deal.valid_hedge_designation` — must be a valid IFRS 9 value
4. `fx_deal.no_settle_cancelled` — cannot settle a cancelled deal
5. `bank_statement.balance_check` — log on import for reconciliation
