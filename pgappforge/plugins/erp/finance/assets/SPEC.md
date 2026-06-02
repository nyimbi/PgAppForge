# Asset Accounting (AA) Plugin — SPEC

## Domain
`finance` — depends on `foundation`

## Entities

### AssetClass
Defines the accounting treatment for a category of fixed assets.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | Multi-tenant isolation |
| code | VARCHAR(20) | e.g. BLDG, MACH, FURN, VEHICLE. Unique per tenant |
| name | VARCHAR(200) | |
| useful_life_years | NUMERIC(5,2) | Default life for assets in this class |
| depreciation_method | VARCHAR(30) | STRAIGHT_LINE \| DECLINING \| UNITS_OF_PRODUCTION |
| gl_asset_account | VARCHAR(50) | Asset cost account |
| gl_accumulated_depreciation_account | VARCHAR(50) | Contra-asset |
| gl_depreciation_expense_account | VARCHAR(50) | P&L charge |
| gl_disposal_gain_account | VARCHAR(50) | Optional — disposal gain credit |
| gl_disposal_loss_account | VARCHAR(50) | Optional — disposal loss debit |
| is_active | BOOLEAN | |
| metadata | JSONB | |

### FixedAsset
The fixed asset register entry. One row per physical/intangible asset.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| asset_number | VARCHAR(50) | Unique per tenant — auto-generated FA-YYYY-NNNNN |
| asset_class_id | UUID FK AssetClass | |
| description | VARCHAR(500) | |
| acquisition_date | DATE | |
| acquisition_cost_cents | INTEGER | Never float |
| residual_value_cents | INTEGER | Salvage value |
| useful_life_years | NUMERIC(5,2) | May override class default |
| depreciation_method | VARCHAR(30) | May override class default |
| current_book_value_cents | INTEGER | Net Book Value (NBV) |
| accumulated_depreciation_cents | INTEGER | |
| location | VARCHAR(200) | |
| custodian_id | UUID | FK to erp_party.id |
| serial_number | VARCHAR(100) | |
| status | VARCHAR(25) | ACTIVE \| DISPOSED \| IMPAIRED \| FULLY_DEPRECIATED |
| last_depreciation_date | DATE | |
| disposal_date | DATE | |
| disposal_proceeds_cents | INTEGER | |
| disposal_gain_loss_cents | INTEGER | Positive=gain, negative=loss |
| expected_total_units | INTEGER | UNITS_OF_PRODUCTION only |
| metadata | JSONB | |

### AssetDepreciation (IMMUTABLE)
Periodic depreciation charge. One row per (asset, period). Append-only.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| asset_id | UUID FK FixedAsset | |
| period_id | VARCHAR(20) | e.g. "2026-01" |
| depreciation_amount_cents | INTEGER | Negative = reversal |
| opening_nbv_cents | INTEGER | |
| closing_nbv_cents | INTEGER | |
| method_used | VARCHAR(30) | Snapshot of method at run time |
| units_consumed | INTEGER | UNITS_OF_PRODUCTION only |
| posted_at | TIMESTAMPTZ | |

Unique constraint: (asset_id, period_id)

### AssetImpairment (IMMUTABLE)
IAS 36 impairment loss record.

| Field | Type | Notes |
|-------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| asset_id | UUID FK FixedAsset | |
| impairment_date | DATE | |
| carrying_amount_cents | INTEGER | NBV before impairment |
| recoverable_amount_cents | INTEGER | Higher of FVLCTS and VIU |
| impairment_loss_cents | INTEGER | carrying - recoverable |
| reason | TEXT | IAS 36 trigger description |
| is_reversal | BOOLEAN | IAS 36 §117 reversal |
| reversal_of_id | UUID FK AssetImpairment | |
| posted_at | TIMESTAMPTZ | |

## Business Rules

1. `acquisition_cost_cents > 0`
2. `residual_value_cents < acquisition_cost_cents`
3. Depreciation is idempotent per period (unique constraint enforces)
4. `status = DISPOSED` is terminal — no further depreciation
5. Impairment reduces NBV; reversal may increase it up to original depreciated cost (IAS 36)
6. All monetary amounts: INTEGER cents (never float)
7. Correction pattern: insert negative AssetDepreciation rows (never UPDATE)

## Depreciation Methods

| Method | Formula (monthly) |
|--------|-------------------|
| STRAIGHT_LINE | (cost - residual) / (life_years * 12) |
| DECLINING | (NBV * 2 / life_years) / 12 |
| UNITS_OF_PRODUCTION | (cost - residual) / total_units * units_this_period |

## API Endpoints

| Method | Path | Action |
|--------|------|--------|
| GET | /assets/classes/ | List asset classes |
| POST | /assets/classes/ | Create asset class |
| GET | /assets/register/ | List fixed assets |
| POST | /assets/register/ | Capitalise new asset |
| GET | /assets/register/<id> | Asset detail |
| POST | /assets/register/<id>/dispose | Record disposal |
| POST | /assets/register/<id>/impair | Record impairment |
| GET | /assets/depreciation/ | List depreciation entries |
| POST | /assets/depreciation/run | Run depreciation for period |
| GET | /assets/reports/register | Fixed Asset Register (HTML) |
| GET | /assets/reports/depreciation-schedule/<id> | Depreciation schedule (HTML) |
| GET | /assets/reports/nbv-summary | NBV by asset class (HTML) |

## Events

### Emitted
- `asset.capitalised` — new asset capitalised
- `asset.depreciation_run` — batch depreciation completed
- `asset.disposed` — asset removed from register
- `asset.impaired` — impairment loss recognised
- `asset.impairment_reversed` — impairment reversed

### Consumed
- `exchange_rate.updated` — trigger FX revaluation for foreign-currency assets

## Reports

1. **Fixed Asset Register** (`/assets/reports/register`) — all assets with cost, accumulated depreciation, NBV, status. Filterable by status. Print-ready.
2. **Depreciation Schedule** (`/assets/reports/depreciation-schedule/<id>`) — full period-by-period depreciation history for a single asset.
3. **NBV Summary** (`/assets/reports/nbv-summary`) — aggregated NBV by asset class with totals.

## Rules Engine Rulesets (pre-configured)

1. `asset.positive_cost` — acquisition_cost_cents must be > 0
2. `asset.residual_lt_cost` — residual_value_cents < acquisition_cost_cents
3. `asset.no_dispose_already_disposed` — status cannot be set DISPOSED twice
4. `asset.impairment_positive_loss` — impairment_loss_cents must be > 0
