# Changelog

All notable changes to PgAppForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.90.0] - 2026-05-31

### Added

#### Code Generation

- `flask forge gen all` — introspects a live PostgreSQL database and emits a complete web application (models, views, APIs, templates, permissions) in a single command
- `flask forge gen model` — generates SQLAlchemy 2.x model classes with full type annotation from PostgreSQL schema
- `flask forge gen view` — generates ModelView/RestCRUDView classes with field lists, search columns, and label overrides
- `flask forge gen api` — generates OpenAPI-annotated `ModelRestApi` classes with schema validation
- `flask forge gen mobile` — scaffolds a React Native application with offline sync (WatermelonDB), voice input, ICD-10/SNOMED CT pickers, and biometric auth hooks
- `flask forge gen desktop` — scaffolds an Electron application with native menu, auto-update, and tray integration
- Database introspection engine: full PostgreSQL type coverage (JSONB, HSTORE, LTREE, INET, UUID, TSVECTOR, range types, arrays, enums, composites), automatic detection of 1-1, 1-N, N-N, and self-referential relationships, partition/view/materialized-view awareness
- Actor pattern detection from PostgreSQL table comments (`@actor`, `@party`, `@role` annotations); drives `ActorMixin`, `ActorConfig`, and `ActorRegistry` codegen
- `ActorRegistry` — runtime catalog of all actor-pattern entities; supports `resolve_party()`, `assign_role()`, and `get_relationships()` for dynamic schema traversal
- Generated applications include ERD Designer and Security Designer provisioned out of the box with zero extra configuration

#### Visual Designers

- **ERD Designer** — browser-based schema editor (Cytoscape.js) backed by an `apply_changes()` DDL execution engine; supports create/alter/drop table and column operations, constraint management, index management, and enum type editing; migrations written atomically via `AtomicFileWriter`; undo/redo with 50-step history; real-time collaboration via PostgreSQL LISTEN/NOTIFY
- **Security Designer** — RBAC visual editor (Cytoscape.js) with drag-and-drop permission assignment; built-in role templates (Admin, Editor, Viewer, API Consumer, Tenant Admin); YAML export/import for GitOps workflows; snapshot and diff comparison between RBAC states; health check that uses SQL anti-joins to surface orphaned permissions and unreachable roles; `_require_security_admin()` and `_validate_csrf()` guards on all 15 endpoints
- **Visual Form Builder** — drag-and-drop canvas with 91 field types (26 curated types + 65 auto-discovered from the widget library); conditional logic (show/hide/require rules); multi-step wizard mode; public share tokens for unauthenticated form submission; scoring and assessment mode with weighted fields and threshold-based outcomes; `register_field_type()` API for third-party field extensions

#### Plugins

- **Audit Trail** (`AuditMixin`) — per-row cryptographic hash chain (SHA-256, each record signs its predecessor) providing tamper-evident logs; PII field masking via `@pii_field` column annotation; GDPR `anonymize_subject()` bulk operation; configurable retention policies with automatic archival; timeline viewer UI with diff rendering between versions
- **Data Hub** — import pipeline for CSV, Excel (xlsx/xls), JSON, NDJSON, and Parquet; fuzzy column mapping (Levenshtein + semantic similarity) auto-suggests target schema columns; chunked async processing for files up to 10 GB; streaming export with server-sent progress events; duplicate detection and merge strategies (skip, overwrite, append); schema inference for unstructured sources
- **Real-Time Collaboration** — PostgreSQL LISTEN/NOTIFY message bus; presence sessions tracking active users per resource; field-level locking with TTL-based lock expiry; SSE fan-out to connected clients; conflict detection and three-way merge for concurrent edits; awareness cursors for collaborative ERD and form editing
- **Form Builder** — 91-type field palette with server-driven registry; `FieldTypeSpec` dataclass defining renderer, validator, serializer, and widget metadata; `register_field_type()` public API for plugin-contributed field types; auto-discovery scans installed packages for `pgappforge.field_types` entry points; form versioning with published/draft states
- **Integration Hub** — OAuth 2.0 client with PKCE for external service authorization; inbound and outbound webhook registry with per-endpoint secret management; AES-256-GCM credential vault (keys stored outside the database); Slack connector with block-kit message builder; `BaseConnector` ABC for implementing custom integrations; HMAC-SHA256 webhook signature verification; SSRF protection on all outbound HTTP calls

#### Schema Templates

- 62 bundled schema templates covering vertical domains: FHIR-R4, GTFS, ISO 20022, UBL Invoice, XBRL/IFRS, HR-Open, TM Forum SID, GS1, ARTS Retail, HL7 v2, ACORD insurance, MISMO mortgage, FIX protocol, OpenTravel, PEPPOL, OAGIS, Semantic Web/RDF, GeoJSON, Dublin Core, Schema.org, and more
- **7 operational templates** — production-ready schemas covering 84 total tables:
  - `ar.json` — Accounts Receivable (8 tables: customers, invoices, line items, payments, credit memos, aging buckets, dunning history, cash receipts)
  - `ap.json` — Accounts Payable (10 tables: vendors, purchase orders, PO lines, receipts, invoices, payment runs, bank accounts, 1099 tracking, early payment discounts, hold codes)
  - `gl.json` — General Ledger (9 tables: chart of accounts, journals, journal lines, periods, budgets, budget lines, cost centers, allocations, trial balance snapshots)
  - `crm.json` — Customer Relationship Management (12 tables: contacts, organizations, opportunities, activities, tasks, notes, campaigns, leads, pipeline stages, quotes, products, territories)
  - `hrm.json` — Human Resource Management (15 tables: employees, positions, departments, org chart, time entries, leave requests, performance reviews, goals, competencies, salary history, benefits, training, certifications, disciplinary actions, offboarding)
  - `inventory.json` — Inventory Management (13 tables: items, item variants, warehouses, locations, stock levels, movements, purchase orders, transfers, cycle counts, lot tracking, serial tracking, reorder rules, suppliers)
  - `ecommerce.json` — E-commerce (17 tables: products, variants, categories, price lists, carts, orders, order lines, shipments, returns, reviews, promotions, discount codes, gift cards, wishlists, storefronts, tax rates, digital assets)
- `flask forge templates list` — list available templates with tag filtering
- `flask forge templates info <name>` — show template metadata, table count, and ER summary
- `flask forge templates apply <name>` — apply template DDL to the target database with pre-flight conflict check
- `flask forge templates import <file>` — register a local JSON template file
- `flask forge templates export <name> <file>` — export a template to portable JSON
- `TemplateRegistry` — discovery layer for bundled, user-home (`~/.pgappforge/templates/`), and project-local (`.pgappforge/templates/`) template paths; supports priority ordering and override semantics

#### Framework Enhancements

- **ReportForge** — report designer with visual layout editor; scheduling via APScheduler (cron and interval triggers); dispatch to email, Slack, and S3; output formats: PDF (WeasyPrint), Excel (openpyxl), and HTML; subreport composition; parameterized reports with user-facing prompt dialogs
- **Rules Engine** — `RulesMixin`, `RuleSet`, and `Rule` model classes; conditions expressed as JSONLogic expressions evaluated server-side; actions: field update, status transition, webhook call, email notification; SSRF protection on webhook action URLs; TTL-based rule evaluation cache; `evaluate_rules(instance)` method injected on mixin-bearing models
- **BPM/Workflow Engine** — process definitions with BPMN-inspired JSON DSL; approval chain manager (`ApprovalChainManager`) supporting sequential, parallel, and conditional routing; task queue backed by PostgreSQL `SKIP LOCKED`; human task inbox UI; deadline escalation; process instance audit log integrated with Audit Trail plugin
- **MFA** — TOTP authenticator app integration (RFC 6238); QR code enrollment flow; backup recovery codes; per-user MFA enforcement policy; admin override for locked-out accounts
- **Multi-tenant infrastructure** — row-level tenant isolation via `tenant_id` column on all tenant-scoped models; `TenantMiddleware` injects current tenant from JWT claim or subdomain; `TenantMixin` base class; cross-tenant query guard raises `TenantViolation` on misconfigured queries; tenant provisioning CLI (`flask forge tenant create/list/migrate`)
- **AI augmentation** — LLM-backed suggestions in ERD Designer (table naming, relationship inference, index recommendations) and Security Designer (least-privilege role suggestions, permission anomaly detection); configurable provider (OpenAI, Anthropic, local Ollama); suggestions are advisory only and never auto-applied
- **Offline sync** — WatermelonDB integration for mobile apps; delta sync endpoint (`/api/v1/sync/pull`, `/api/v1/sync/push`); conflict resolution strategies (last-write-wins, server-wins, client-wins, custom); sync status tracking per model
- **Voice input** — speech-to-text widget integration via Web Speech API with server-side fallback (Whisper); supported field types: text, textarea, search; configurable language and continuous mode
- 91 form widget types including: ICD-10 picker, SNOMED CT browser, signature pad (canvas-based), geo/map picker (Leaflet), code editor (CodeMirror), barcode/QR scanner (camera-based), color picker, date range, time range, duration, phone (libphonenumber validation), IBAN, credit card, star rating, slider range, tag input, rich text (Quill), file upload with preview, image crop, address autocomplete (Nominatim), currency with FX rates, Markdown editor, JSON editor with schema validation, diff viewer, kanban column selector, Gantt dependency, network graph node selector
- PostgreSQL-specific widgets for JSONB tree editor, HSTORE key-value grid, LTREE path picker, INET CIDR input, UUID display/copy, TSVECTOR tag cloud, daterange/tsrange/int4range inputs
- All 62 schema templates normalized: UUID v7 primary keys, `tenant_id UUID`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()` on every table; triggers auto-maintain `updated_at`

#### Security

- Security Designer CSRF protection: `_validate_csrf()` called on all 15 state-mutating endpoints; tokens are double-submit cookie pattern
- Security Designer XSS helpers: all user-supplied label and description fields HTML-escaped before storage and output
- Admin role protection: Security Designer blocks deletion or downgrade of the last Admin-role assignment
- `_require_security_admin()` decorator enforces that only users holding the `security-admin` permission can reach Security Designer write endpoints
- AES-256-GCM credential vault in Integration Hub; master key loaded from environment variable, never stored in the database; key rotation operation provided
- HMAC-SHA256 webhook signature verification; signatures included in `X-PgAppForge-Signature-256` header on all outbound webhook calls; inbound webhooks verified before processing
- Audit Trail cryptographic hash chain: each audit record stores `prev_hash` and `row_hash`; `verify_chain(model, pk_range)` utility detects tampering
- SSRF protection in Rules Engine webhook actions: outbound URLs validated against configurable allowlist; RFC 1918 and link-local ranges blocked by default

#### Testing

- 628 CI tests passing in `tests/ci/` pytest suite (Python 3.12, PostgreSQL 14)
- Test modules: `test_erd_designer`, `test_security_designer`, `test_bpm`, `test_realtime`, `test_form_builder`, `test_plugin_system`, `test_audit_trail`, `test_data_hub`, `test_integration_hub`, `test_rules_engine`, `test_multitenant`, `test_codegen`, `test_templates`, `test_report_forge`, `test_mfa`, `test_actor_pattern`
- Pytest fixtures provide isolated PostgreSQL schemas per test via `CREATE SCHEMA` / `DROP SCHEMA` rather than database-level isolation, enabling parallel test execution

### Changed

- SQLAlchemy upgraded to 2.x: all internal query code migrated to `session.execute(select(...))` patterns; `Query` API no longer used internally
- Flask upgraded to 3.x: `before_first_request` removed, blueprint-level `record_once` used instead; `Markup` imported from `markupsafe`
- **PostgreSQL-only**: all non-PostgreSQL database workarounds, dialect guards, and MSSQL/MySQL/Oracle/SQLite compatibility shims removed; `SQLALCHEMY_DATABASE_URI` must use `postgresql+psycopg2://` or `postgresql+psycopg://`
- Package namespace changed from `flask_appbuilder` to `pgappforge`; `flask_appbuilder` remains as a compatibility shim that re-exports the public API with a deprecation warning
- Minimum Python version raised to 3.12
- Security manager session handling refactored to eliminate cross-test contamination via `scoped_session` with explicit scope keys

### Fixed

- N+1 query elimination throughout security designer: role-permission and user-role queries now use `selectinload` eager loading; list endpoints reduced from O(n) queries to O(1)
- Cross-test contamination in `SecurityManager.get_session`: scoped session factory now uses test-specific scope identifiers, preventing session bleed between parallel tests
- Duplicate index errors in rules engine and offline sync models when `create_all()` called on an existing schema; guards added via `checkfirst=True`
- `AtomicFileWriter` race condition on Windows-style temp file rename; now uses `os.replace()` which is atomic on POSIX and best-effort on Windows
- ERD Designer `apply_changes()` DDL engine: column rename and type change in a single operation now emitted as two separate `ALTER TABLE` statements to avoid PostgreSQL parser rejection

## [0.8x] - Historical

Internal development iterations forked from flask-appbuilder 4.8.x. See `git log --oneline v0.80.0..v0.89.0` for details.

---

[Unreleased]: https://github.com/pgappforge/pgappforge/compare/v0.90.0...HEAD
[0.90.0]: https://github.com/pgappforge/pgappforge/releases/tag/v0.90.0
