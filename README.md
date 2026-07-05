# PgAppForge

**World-class open-source ERP platform for Africa and emerging markets**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-BSD-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](tests/ci)

## What It Is

PgAppForge is a PostgreSQL-native ERP and application platform built on the
Flask-AppBuilder RAD framework. It combines automatic CRUD, RBAC, REST APIs,
SQLAlchemy models, PostgreSQL-first data services, and an ERP plugin suite in a
single Python codebase that teams can inspect, extend, and run without
proprietary application servers or database lock-in.

The ERP layer contains 170 assessed capability modules across finance, HCM,
CRM, operations, industry verticals, platform services, GRC, procurement,
analytics, projects, and the shared foundation layer. The 10 business domains
below account for the module inventory used by application teams; the shared
`foundation/` package contributes 7 cross-domain files for common models,
events, services, views, and helpers.

PgAppForge is Africa-first by design: 8-country payroll calculators, mobile
money integration surfaces, Kenya eTIMS tax compliance, and NLLB-backed African
language translation sit alongside IFRS/ASC finance, manufacturing, GRC,
industry verticals, and an embedded local AI assistant.

## Module Inventory

| Domain | Modules | Key Capabilities |
|---|---:|---|
| Finance | 23 | GL, AP, AR, assets, consolidation, credit management, entities, FP&A, grants, hedge accounting, intercompany, joint venture, lease accounting, material ledger, multi-book, period close, product costing, profit center, revenue recognition, tax, tax compliance, treasury |
| HCM | 23 | Payroll, personnel, org, time, benefits, compensation, contingent workforce, equity compensation, journeys, LMS, lunch, performance, position management, recruiting, referrals, self-service, skills, talent, travel expense, variable pay, wellness, workforce planning, analytics |
| CRM | 18 | Sales, service, commerce, appointments, contracts, CPQ, customer portal, events, field service, loyalty, marketing, marketing automation, POS, PRM, service contracts, signatures, subscriptions, territory management |
| Operations | 17 | Assembly, capacity scheduling, demand planning, EAM, fleet, inventory, lean, MRP, PLM, process manufacturing, production, quality, rental, repair, SCM, transport, warehouse |
| Industry | 27 | Agritech, clubs, consumer goods, cybersecurity, education, energy, financial contracts, financial services, health, insurance, international aid, legal, life sciences, manufacturing, media, nonprofit, oil and gas, procurement, public sector, real estate, research, smart city, telecoms, track and trace, transit, utilities, water |
| Platform | 36 | Analytics engine, anomaly detection, APG bridge, audit viewer, carbon, credentials, discuss, document intelligence, documents, EDI, education platform, email, events, identity, iPaaS, landing, MES, ML predictions, natural language analytics, NLP, notifications, observability, predictions, process mining, RAG, regulatory reporting, report builder, row security, scheduler, social, surveys, tenant control, versioning, WhatsApp, workflow designer, workflow launcher |
| GRC | 7 | Anti-bribery, controls, enterprise risk management, ethics, privacy, segregation of duties, sustainability |
| Procurement | 4 | Sourcing, spend analytics, supplier portal, trade compliance |
| Analytics | 4 | AI agents, customer data platform, operational analytics, predictive analytics |
| Projects | 4 | Project models, services, views, and domain events for project accounting and delivery control |

## Differentiators

| PgAppForge | SAP / Oracle / Workday comparison |
|---|---|
| Open source core | No ERP licensing fees; source is inspectable and modifiable. |
| Africa-first localization | 8-country payroll packages, mobile money surfaces, KE eTIMS, and NLLB translation for 60 African languages. |
| Embedded AI assistant | Ollama-backed local ReAct assistant with 27 tools, RBAC gating, write audit logs, and session persistence. |
| Single PostgreSQL architecture | No HANA, Oracle DB, or proprietary application database required. |
| Fast deployment path | Clone, configure PostgreSQL, create an admin user, and run a working app in hours instead of months. |

## Quick Start

```bash
git clone https://github.com/nyimbi/fab-ext
cd fab-ext

uv venv
uv pip install -e ".[dev]"

export SQLALCHEMY_DATABASE_URI="postgresql://pgappforge:pgappforge@localhost/pgappforge"
export SECRET_KEY="replace-with-a-long-random-secret"

flask fab create-admin
flask run
```

`SQLALCHEMY_DATABASE_URI` and `SECRET_KEY` are required. Use PostgreSQL for ERP
development and production so JSONB, vector search, row security, and finance
workloads run against the same database family used by the platform.

## Finance Compliance

PgAppForge includes finance modules designed around deterministic arithmetic
and auditable accounting events:

- IFRS 16 / ASC 842 lease accounting with exact amortization schedules and
  final-period liability cleanup.
- IFRS 9 hedge accounting with signed hedge-effectiveness testing, OCI/P&L
  split, and effectiveness thresholds.
- IAS 2 actual costing through the material ledger, including receipt/opening
  quantity denominators and variance settlement.
- ASC 606 / IFRS 15 revenue recognition with obligations, series performance
  obligations, percentage-of-completion methods, and discount allocation.
- Multi-GAAP parallel ledgers through the finance multi-book and GL stack.

Regression coverage for critical finance arithmetic lives in
`tests/ci/test_finance_arithmetic.py`.

## Development

```bash
uv run pytest tests/ci
flake8
```

Project conventions:

- Tests: `uv run pytest tests/ci`
- Linting: `flake8` with a 90-character line limit; this repository uses tabs
  heavily in existing Python modules, so match surrounding style when editing.
- Architecture assessment: [docs/analysis-world-class-assessment.md](docs/analysis-world-class-assessment.md)
- Tier-1 gap analysis: [docs/tier1-gap.md](docs/tier1-gap.md)
- Developer assistant guide: [docs/dev_assistant.md](docs/dev_assistant.md)

ERP modules usually follow the same package shape:
`models.py`, `services.py`, `views.py`, `events.py`, and `__init__.py`.
Business mutations belong in service classes, durable events use the
foundation event log, and FAB views should stay thin.

## AI Assistant

The embedded developer/admin assistant lives in `pgappforge/ai_assistant/`.
It is an Ollama-backed ReAct agent that runs local inference, builds a
code-aware system prompt, streams responses over `/dev-assistant/chat`, and
persists per-user sessions when the database is configured.

The assistant exposes 27 tools: 20 read tools for code, logs, Git, database
schema, dependencies, semantic search, web search via SearXNG, CI status, usage
lookup, and coverage; plus 7 write tools for file writes, patching, tests, Git
commits/branches, rollback by stash, and codebase reindexing. Write tools are
RBAC-gated to roles from `DEV_ASSISTANT_WRITE_ROLES` and every write operation
is audit-logged.

## Contributing

Contributions should preserve PgAppForge's operating principles:

- Prefer existing ERP package patterns before adding new abstractions.
- Use `Decimal` and integer cents for money; do not introduce float-based
  financial arithmetic.
- Add or update focused tests in `tests/ci/` for changed behavior.
- Keep service methods transaction-aware: callers own commit/rollback unless a
  local module already documents a different contract.
- Document new ERP surfaces in `docs/` and keep README claims tied to code.

See [CONTRIBUTING.md](CONTRIBUTING.md) for general project guidance.

## License

PgAppForge is released under the BSD license. See [LICENSE](LICENSE).
