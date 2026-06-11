# Getting Started — PgAppForge ERP + Fintech Platform

## Overview

PgAppForge is a comprehensive enterprise platform built on Flask-AppBuilder (FAB) covering:

- **ERP** — Finance, HCM (8-country payroll), CRM, Operations, GRC, Analytics (120+ modules)
- **Fintech** — Core banking, Lending (IFRS 9), Mobile Money, SACCO + Chama, Trade Finance, SWIFT, Card Issuing, Banking REST API
- **Industry** — Real estate (property management, commercial, portfolio), Clubs, and more
- **Auth** — Pluggable: FAB built-in, Keycloak, Clerk, BetterAuth, or SpiceDB for fine-grained authz

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (the only supported database)
- `uv` (recommended) or `pip`

---

## Local Setup (5 minutes)

### 1. Clone and install

```bash
git clone <repo-url> && cd fab-ext
uv venv && source .venv/bin/activate
uv pip install -r requirements/base.txt -r requirements/postgres.txt

# Optional: PDF reports and JWT validation
uv pip install reportlab PyJWT cryptography
```

### 2. Configure environment

```bash
cp .env.example .env   # or create .env manually
```

Minimum `.env`:

```env
SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://pguser:pguserpassword@localhost:5432/app
SECRET_KEY=change-this-to-a-random-32-char-string-minimum
FLASK_APP=app
```

### 3. Start PostgreSQL

```bash
docker compose up -d postgres
```

### 4. Run migrations and create admin

```bash
flask db upgrade       # or: flask fab create-db
flask fab create-admin
```

### 5. Start the app

```bash
flask run              # or: gunicorn "app:create_app()"
```

Open http://localhost:5000 — you'll see the landing page.

---

## Docker Compose (full stack)

```bash
cp .env.example .env   # fill in SECRET_KEY
docker compose up -d
docker compose exec app flask fab create-admin
docker compose exec app flask db upgrade
```

App: http://localhost:8080 | Admin: http://localhost:8080/admin

---

## Activating Plugins

All plugins are opt-in via `PGAPPFORGE_PLUGINS` in your config:

```python
# config.py
PGAPPFORGE_PLUGINS = [
    # ERP foundation (required first)
    "pgappforge.plugins.erp.foundation",

    # Finance
    "pgappforge.plugins.erp.finance.gl",
    "pgappforge.plugins.erp.finance.ap",
    "pgappforge.plugins.erp.finance.ar",
    "pgappforge.plugins.erp.finance.revenue_recognition",
    # ... add any from pgappforge/plugins/erp/finance/

    # HCM
    "pgappforge.plugins.erp.hcm.payroll",    # Kenya payroll default
    "pgappforge.plugins.erp.hcm.benefits",
    "pgappforge.plugins.erp.hcm.performance",

    # Platform
    "pgappforge.plugins.erp.platform.scheduler",         # batch jobs
    "pgappforge.plugins.erp.platform.notifications",     # event notifications
    "pgappforge.plugins.erp.platform.analytics_engine",  # analytics cubes
    "pgappforge.plugins.erp.platform.landing",           # editable landing page
]
```

### Fintech stack (single call)

```python
from pgappforge.plugins.fintech import install_all
# In your app factory:
install_all(appbuilder, configs={
    "core_banking": {"CB_DEFAULT_CURRENCY": "KES"},
})
```

Or selectively:

```python
PGAPPFORGE_PLUGINS += [
    "pgappforge.plugins.fintech.core_banking",
    "pgappforge.plugins.fintech.lending",
    "pgappforge.plugins.fintech.mobile_money",
    "pgappforge.plugins.fintech.sacco",
    "pgappforge.plugins.fintech.banking_api",   # REST API at /api/v1/banking
]
```

---

## Authentication

Default auth uses FAB's built-in (username/password). Switch providers in config:

```python
# Keycloak OIDC
AUTH_PROVIDER = "keycloak"
KEYCLOAK_SERVER_URL = "https://keycloak.example.com"
KEYCLOAK_REALM = "myrealm"
KEYCLOAK_CLIENT_ID = "pgappforge"
KEYCLOAK_CLIENT_SECRET = "..."

# Clerk
AUTH_PROVIDER = "clerk"
CLERK_SECRET_KEY = "sk_live_..."
CLERK_JWKS_URL = "https://YOUR_DOMAIN.clerk.accounts.dev/.well-known/jwks.json"

# BetterAuth (self-hosted Node.js)
AUTH_PROVIDER = "better_auth"
BETTER_AUTH_URL = "http://localhost:3000"
BETTER_AUTH_SECRET = "..."

# SpiceDB (layered fine-grained authz, any auth above)
AUTHZ_PROVIDER = "spicedb"
SPICEDB_ENDPOINT = "localhost:8443"
SPICEDB_TOKEN = "..."
```

Wire into FAB:

```python
from pgappforge.security.providers import get_security_manager_class

appbuilder = AppBuilder(app, db.session,
    security_manager_class=get_security_manager_class())
```

---

## Banking REST API

Interactive docs: http://localhost:8080/api/v1/banking/docs

Authenticate via API key header:

```bash
curl -H "X-API-Key: $YOUR_KEY" http://localhost:8080/api/v1/banking/accounts/ACC001/balance
```

Configure keys:

```python
BANKING_API_KEYS = {
    "my-api-key-here": {"tenant_id": "tenant-001", "customer_id": "cust-001"},
}
BANKING_API_MASTER_KEY = "dev-master-key"  # admin access in development
```

---

## Landing Page

Customise at `/landing/edit` (admin only):

| Config key | Default | Description |
|---|---|---|
| `LANDING_TITLE` | "PgAppForge ERP" | Page title |
| `LANDING_TAGLINE` | "Intelligent Enterprise Platform" | Hero subtitle |
| `LANDING_LOGO_URL` | (none) | URL to your logo image |
| `LANDING_ACCENT_COLOR` | "#1a56db" | Hero gradient colour |
| `LANDING_MODULES_FILTER` | (all) | Comma-separated domain names to show |
| `LANDING_ENV_LABEL` | (none) | "Production" / "Staging" badge |

---

## Key Configuration Reference

| Key | Default | Description |
|---|---|---|
| `SQLALCHEMY_DATABASE_URI` | — | PostgreSQL connection string (required) |
| `SECRET_KEY` | — | Flask secret, min 32 chars (required) |
| `AUTH_PROVIDER` | `"fab"` | Auth backend: fab/keycloak/clerk/better_auth |
| `AUTHZ_PROVIDER` | (none) | Optional: `"spicedb"` for fine-grained authz |
| `CB_DEFAULT_CURRENCY` | `"KES"` | Default currency for core banking |
| `CB_TENANT_ID` | `"default"` | Tenant ID for core banking operations |
| `CRB_PROVIDER` | `"MOCK"` | Kenya CRB: MOCK/TRANSUNION_KE/METROPOL |
| `NOTIFY_CHANNELS` | `["email"]` | Notification channels |
| `ANALYTICS_SEED_CUBES` | `True` | Auto-seed 5 standard analytics cubes |
| `FRC_GOAML_ENABLED` | `False` | Enable live SASRA/goAML SAR submission |

---

## Running Tests

```bash
uv run pytest tests/ci/ -q           # full CI suite (~300 tests)
uv run pytest tests/ci/ -k fintech   # fintech tests only
uv run pytest tests/ci/ -k auth      # auth provider tests only
```

---

## Project Structure

```
pgappforge/
  plugins/
    erp/                  # ERP modules (120+)
      finance/            # GL, AP, AR, tax, treasury, RevRec...
      hcm/                # Payroll (8 countries), benefits, performance...
      crm/                # Sales, subscriptions, loyalty, events...
      operations/         # MRP, WMS, quality, transport...
      grc/                # SoD, ERM, ethics hotline, anti-bribery...
      industry/           # Real estate, clubs, health, education...
      platform/           # Analytics, scheduler, notifications, landing...
    fintech/              # Financial services (12 plugins)
      core_banking/       # Accounts, ledger, KYC, teller, FX, tiered rates
      lending/            # LOS, LMS, IFRS 9, ECL, NPA aging
      mobile_money/       # M-Pesa clone, agents, disbursements
      sacco/              # Members, loans, SASRA returns, FOSA bridge
      banking_api/        # REST API + OpenAPI/Swagger
      card_issuing/       # Virtual cards, PIN, 3DS OTP
  security/
    providers/            # Auth providers: FAB, Keycloak, Clerk, BetterAuth
    managers/             # FAB SecurityManager subclasses per provider
    providers/spicedb.py  # Fine-grained authz (AUTHZ_PROVIDER=spicedb)
```
