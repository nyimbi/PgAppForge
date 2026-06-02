# ERP Foundation Plugin — Specification

**Version**: 1.0.0  
**Domain**: platform  
**Depends on**: (none — this is the root plugin all others depend on)

---

## Purpose

The Foundation plugin provides the universal shared entities that every other
ERP plugin builds on.  It has no financial logic of its own; it is the
master-data and infrastructure layer.

---

## Entities

### Party
Universal actor entity.  Replaces separate Customer, Supplier, Employee, and
Contact tables found in legacy systems.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | Multi-tenant isolation |
| party_type | VARCHAR(20) | ORGANIZATION \| INDIVIDUAL \| GROUP |
| name | VARCHAR(500) NOT NULL | |
| short_name | VARCHAR(100) | |
| legal_name | VARCHAR(500) | Registered legal name |
| tax_id | VARCHAR(50) | TIN / EIN / UTR |
| vat_number | VARCHAR(50) | |
| registration_number | VARCHAR(100) | Companies house / CAC |
| lei | VARCHAR(20) | ISO 17442 Legal Entity Identifier |
| website | VARCHAR(500) | |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | |
| parent_id | UUID FK self | Corporate hierarchy |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |
| updated_at | TIMESTAMPTZ DEFAULT NOW() | |

Indexes: `(tenant_id, party_type)`, `tax_id`, `lei`, GIN trigram on `name`.

### PartyRole
Temporal role a Party plays.  A single Party can have multiple active roles.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| party_id | UUID FK party | CASCADE delete |
| role_type | VARCHAR(20) | CUSTOMER \| SUPPLIER \| EMPLOYEE \| PARTNER \| OTHER |
| effective_from | TIMESTAMPTZ NOT NULL | |
| effective_to | TIMESTAMPTZ NULL | NULL = currently active |
| attributes | JSONB | credit_limit, payment_terms, employee_number, etc. |

### Address
Physical or postal address.  Supports PostGIS geo_point for proximity searches.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| party_id | UUID FK party | |
| address_type | VARCHAR(20) | BILLING \| SHIPPING \| REGISTERED \| WORK |
| line1..line2 | VARCHAR(500) | |
| city | VARCHAR(200) NOT NULL | |
| state | VARCHAR(200) | State / Province / County |
| postal_code | VARCHAR(20) | |
| country_code | CHAR(2) FK country | |
| geo_point | GEOMETRY(Point,4326) | PostGIS; Text WKT fallback |
| is_default | BOOLEAN NOT NULL DEFAULT FALSE | |
| is_verified | BOOLEAN NOT NULL DEFAULT FALSE | |

### Contact
Communication channel (email, phone, social) for a Party.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| party_id | UUID FK party | |
| contact_type | VARCHAR(20) | EMAIL \| PHONE \| MOBILE \| FAX \| SOCIAL |
| value | VARCHAR(500) NOT NULL | |
| is_primary | BOOLEAN | |
| is_verified | BOOLEAN | |

### Currency
ISO 4217 currency master.  Global (no tenant_id).

| Column | Type | Notes |
|--------|------|-------|
| code | CHAR(3) PK | ISO 4217 e.g. USD, NGN |
| name | VARCHAR(100) NOT NULL | |
| symbol | VARCHAR(10) NOT NULL | |
| decimal_places | INTEGER DEFAULT 2 | 0=JPY, 2=USD, 3=KWD |
| is_active | BOOLEAN DEFAULT TRUE | |

### ExchangeRate
Point-in-time rate between two currencies.  **Append-only** — never UPDATE.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| from_currency | CHAR(3) FK currency | |
| to_currency | CHAR(3) FK currency | |
| rate | NUMERIC(20,8) NOT NULL | Never float |
| rate_date | TIMESTAMPTZ NOT NULL | |
| source | VARCHAR(20) | MANUAL \| ECB \| CENTRAL_BANK \| OPENEXCHANGE |
| expires_at | TIMESTAMPTZ NULL | NULL = never expires |
| created_at | TIMESTAMPTZ DEFAULT NOW() | |

Index: `(from_currency, to_currency, rate_date)`.

### Country
ISO 3166-1 country master.  Global (no tenant_id).

| Column | Type | Notes |
|--------|------|-------|
| iso_alpha2 | CHAR(2) PK | |
| iso_alpha3 | CHAR(3) UNIQUE | |
| name | VARCHAR(200) NOT NULL | |
| phone_prefix | VARCHAR(10) | e.g. +234 |
| currency_code | CHAR(3) FK currency | Default currency |
| is_eu | BOOLEAN DEFAULT FALSE | |
| is_active | BOOLEAN DEFAULT TRUE | |

### CodeTable
Generic configurable lookup replacing dozens of small enum tables.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| domain | VARCHAR(100) NOT NULL | Namespace e.g. payment_terms |
| code | VARCHAR(100) NOT NULL | Unique within domain |
| label | VARCHAR(500) NOT NULL | Display label |
| sort_order | INTEGER DEFAULT 0 | |
| is_active | BOOLEAN DEFAULT TRUE | |
| metadata | JSONB | Domain-specific extra fields |

Unique constraint: `(domain, code)`.

### Note
Polymorphic free-text note attached to any ERP entity.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| entity_type | VARCHAR(100) NOT NULL | Model class name |
| entity_id | VARCHAR(64) NOT NULL | String PK of target entity |
| note_type | VARCHAR(20) | INTERNAL \| CUSTOMER \| SYSTEM |
| body | TEXT NOT NULL | |
| is_pinned | BOOLEAN | |
| author_id | INTEGER FK ab_user | |
| created_at, updated_at | TIMESTAMPTZ | |

### Attachment
Binary file attachment for any ERP entity.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| entity_type, entity_id | VARCHAR | Polymorphic FK |
| filename | VARCHAR(500) | |
| mime_type | VARCHAR(200) | |
| size_bytes | INTEGER | Quota enforcement |
| storage_url | VARCHAR(2000) | S3 / GCS / local path |
| checksum_sha256 | CHAR(64) | Integrity verification |
| uploaded_by | INTEGER FK ab_user | |

### DomainEventLog
Durable, **append-only** event store.  Never update or delete rows.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| event_id | VARCHAR(36) UNIQUE | UUID from DomainEvent |
| event_type | VARCHAR(200) | e.g. party.created |
| aggregate_type | VARCHAR(100) | Model class name |
| aggregate_id | VARCHAR(64) | PK of aggregate root |
| tenant_id | UUID | |
| payload | JSONB | Domain-specific fields |
| published_at | TIMESTAMPTZ DEFAULT NOW() | BRIN indexed |
| correlation_id | VARCHAR(36) | Groups events in one transaction |
| causation_id | VARCHAR(36) | Parent event that caused this one |

---

## Business Rules

1. **Party uniqueness**: Within a tenant, (tax_id) must be unique among active
   parties.  Enforcement is at the service layer (not DB constraint) to allow
   soft-delete workflows.

2. **Role temporality**: `effective_to = NULL` means the role is currently
   active.  Terminating a role sets `effective_to = NOW()`.

3. **Exchange rate immutability**: ExchangeRate rows are never updated.  To
   correct a rate, insert a new row with the same (from, to) pair and a later
   `rate_date`.  FoundationService.get_exchange_rate() returns the most recent
   row for the requested date.

4. **Amount encoding**: All downstream financial plugins must store amounts as
   integer cents (kobo, fils, etc.) using `INTEGER` or `BIGINT` columns.
   `ExchangeRate.rate` is `NUMERIC(20,8)`.  Floats are prohibited.

5. **AuditMixin**: All mutable entities (Party, PartyRole, Address, Contact,
   Note, Attachment) carry AuditMixin for automatic field-diff audit logging.

6. **DomainEventLog append-only**: The table has no UPDATE path in the ORM or
   service layer.  Compensating events (e.g. `party.merged`) represent
   corrections.

7. **Tenant isolation**: All entity tables carry `tenant_id UUID NOT NULL`.
   Lookup tables (Currency, Country, CodeTable with global domains) are
   tenant-agnostic; tenant-local code domains use a naming convention
   e.g. `"acme.payment_terms"`.

---

## Domain Events

| Event | Emitted by | Consumed by |
|-------|-----------|-------------|
| `party.created` | PartyView.create | CRM, HCM, Finance |
| `party.updated` | PartyView.update | CRM, HCM, Finance |
| `party.merged` | PartyView.merge / FoundationService.merge_parties | All plugins holding party refs |
| `exchange_rate.updated` | ExchangeRateView.create | Finance, Procurement |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /foundation/parties/ | Party list (HTML, filterable) |
| GET | /foundation/parties/`<id>` | Party detail (JSON) |
| POST | /foundation/parties/ | Create party |
| PUT | /foundation/parties/`<id>` | Update party |
| POST | /foundation/parties/`<id>`/roles | Add party role |
| POST | /foundation/parties/merge | Merge duplicate party |
| GET | /foundation/fx/rates | List exchange rates |
| POST | /foundation/fx/rates | Create exchange rate |
| GET | /foundation/fx/convert | Convert amount between currencies |
| GET | /foundation/fx/sheet | FX rate sheet (HTML report) |
| GET | /foundation/codes/`<domain>` | List codes for domain |
| POST | /foundation/codes/ | Create code |
| PUT | /foundation/codes/`<id>` | Update code |
| GET | /foundation/events/ | Event log (JSON, paginated) |
| GET | /foundation/events/`<event_id>` | Single event detail |
| GET | /foundation/reports/party-directory | Party directory report (HTML) |
| GET | /foundation/reports/fx-rate-sheet | FX rate sheet redirect |
| GET | /foundation/reports/code-listing | Code table listing (HTML) |

---

## Reports

1. **Party Directory** (`/foundation/reports/party-directory`)  
   Filterable by type (Customer / Supplier / Employee / All), print-friendly.
   Shows: type, name, legal name, tax ID, VAT number, primary email, website.

2. **FX Rate Sheet** (`/foundation/reports/fx-rate-sheet` → `/foundation/fx/sheet`)  
   Current exchange rates grouped by from_currency.  Shows latest rate per pair.

3. **Code Table Listing** (`/foundation/reports/code-listing`)  
   All active CodeTable entries grouped by domain, sortable, print-friendly.

---

## Plugin Events

**Emits**: `party.created`, `party.updated`, `party.merged`,
`exchange_rate.updated`

**Consumes**: nothing (root plugin)

---

## Seed Data

`FoundationPlugin.setup_seed_data()` calls:
- `FoundationService.seed_major_currencies()` — 22 G20+Africa currencies
- `FoundationService.seed_major_countries()` — 23 countries with phone prefixes
