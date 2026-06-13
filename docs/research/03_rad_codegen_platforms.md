# RAD & Code-Generation Platform Analysis: JHipster, CUBA/Jmix, Hasura, Supabase, Django, Bubble, Glide vs PgAppForge

_Research date: 2026-06-13_

---

## 1. Overview

This document covers the RAD (Rapid Application Development) and code-generation tier — tools that generate runnable applications from schemas, models, or natural language. This group defines the code-portability and developer-experience benchmark that PgAppForge must match or exceed.

---

## 2. Platform Profiles

### 2.1 JHipster

**Business metrics**
- GitHub stars: ~22,000 (MIT license)
- Weekly downloads: ~50,000 npm installs
- License: MIT (full code portability)
- Funding: Community-driven, sponsored by Okta, Microsoft

**Technical profile**
- Java/Spring Boot backend generator
- Frontend: React, Angular, or Vue (user choice)
- Database: PostgreSQL, MySQL, Oracle, MongoDB, Cassandra
- Authentication: JWT, session, OAuth2 (Keycloak, Okta, Auth0)
- Blueprint system: extend JHipster with language-specific blueprints
- React Native blueprint: generates mobile app from same JDL (JHipster Domain Language)
- Microservices: Consul/Eureka service registry, Spring Cloud Gateway
- DevOps: Docker Compose, Kubernetes, AWS, Heroku deployment generation
- CI/CD: GitHub Actions, Jenkins, GitLab CI generation

**JHipster Domain Language (JDL)**
```
entity Blog {
    name String required minlength(3)
    handle String required minlength(2)
}

entity Post {
    title String required
    content TextBlob required
    date Instant required
}

relationship ManyToOne {
    Post{blog(name)} to Blog
}
```
One JDL file generates: Java entities, Spring repositories, Spring REST controllers, React/Angular frontend, Jest tests, Cypress E2E tests, Docker Compose, Kubernetes manifests.

**Strengths**
- Full code portability — generated code is 100% standard Spring/React
- React Native blueprint for mobile from same model
- Microservices generation is the best in any generator
- DevOps generation (k8s, Docker) is ahead of all Python alternatives
- MIT license — no restrictions

**Weaknesses**
- Java/Spring only — no Python
- No ERP domain modules
- No visual builder (100% code-first)
- No citizen developer capability
- React Native blueprint is community-maintained (not production-grade for all cases)
- No Africa/emerging-market regulatory support

**Relevance to PgAppForge**: JDL is a reference design for PgAppForge's model DSL. The microservices generation approach is the target for PgAppForge's FastAPI migration. PgAppForge should implement a schema DSL equivalent to JDL but in Python/YAML.

---

### 2.2 CUBA Platform / Jmix

**Business metrics**
- GitHub stars: ~2,500 (Jmix), ~3,200 (CUBA)
- License: Apache 2.0
- Company: Haulmont (UK/Russia)
- Pricing: Free (Jmix); Jmix Studio Pro $1,200/developer/year

**Technical profile**
- Java/Spring Boot generation (similar to JHipster but enterprise-focused)
- Best back-office generation in any platform — generates:
  - CRUD screens with filtering, sorting, pagination
  - Master-detail views
  - Entity audit trail
  - Soft delete
  - Row-level security
- BPM: BPMN 2.0 modeler (visual, integrated with generated entities)
- Audit: automatic `@Audit` annotation tracks all entity changes
- Soft delete: `@SoftDelete` annotation — no data is ever physically deleted
- REST API: automatic OpenAPI 3.0 from entities
- Multitenancy: built-in tenant isolation via `@TenantEntity`
- Reports: built-in report designer (Excel/PDF output)

**Jmix is the closest Java equivalent to PgAppForge** — both generate admin UIs from model definitions. Jmix is more mature (enterprise Java ecosystem) but Java-only and no Africa domain modules.

**Strengths**
- BPMN 2.0 visual BPM built-in (no competitor in Python space has this)
- Automatic audit trail is production-grade
- Soft delete by default
- Multi-tenancy in core
- Report designer generates Excel/PDF without external tool
- OpenAPI 3.0 from entities

**Weaknesses**
- Java only (not Python)
- No mobile
- No citizen developer (Studio Pro is for developers)
- No Africa regulatory compliance
- Declining community (Java enterprise is a shrinking audience)

**Relevance to PgAppForge**: BPMN 2.0 integration, automatic audit trail, soft delete, and multi-tenancy are all features PgAppForge should copy directly. These are proven patterns from 10+ years of Jmix production use.

---

### 2.3 Hasura

**Business metrics**
- GitHub stars: ~32,000 (Apache 2.0)
- Raised: $100M (Lightspeed, Nexus)
- Valuation: $1B (2022)
- Pricing: Cloud Free; Pro $99/month; Enterprise custom

**Technical profile**
- Hasura Data Delivery Network (DDN): instant GraphQL + REST API from any database schema
- Databases: PostgreSQL (primary), MySQL, MongoDB, ClickHouse, Snowflake, SQL Server
- No-code data modeling: DDN generates GraphQL from existing schema without code
- Permissions: column-level, row-level (Hasura's JWT claims → PostgreSQL RLS integration)
- Actions: custom resolvers that call external REST APIs
- Events: database event triggers → webhooks
- Subscriptions: real-time GraphQL subscriptions via WebSockets
- No UI generation: API-only, no frontend generation

**Hasura vs PgAppForge**
Hasura is strictly a backend/API layer. It has zero UI generation, zero ERP modules, zero mobile. Its value proposition is "instant GraphQL from your PostgreSQL schema." PgAppForge can incorporate Hasura's approach to deliver GraphQL without building from scratch — or implement the same pattern using Strawberry (Python GraphQL library).

**Strengths**
- Fastest path from PostgreSQL schema to GraphQL API
- Permission model is the most granular (JWT claims → column-level security)
- No application code needed for standard queries
- DDN federation across multiple databases

**Weaknesses**
- API-only — no UI, no mobile, no ERP
- Pricing jumps steeply for production use
- DDN is a rewrite with breaking changes from v2
- No domain knowledge

**Relevance to PgAppForge**: Hasura's permission model (JWT → RLS → column-level) is the reference design for PgAppForge's API security layer. The Strawberry Python library replicates Hasura's GraphQL generation from SQLAlchemy models.

---

### 2.4 Supabase

**Business metrics**
- GitHub stars: ~100,000 (Apache 2.0) — largest in any database/RAD category
- Raised: $196M (a16z, Coatue)
- Valuation: $10.5B (2025)
- Monthly active databases: 1M+
- Pricing: Free (500MB); Pro $25/month; Team $599/month; Enterprise custom

**Technical profile**
- PostgreSQL-native (every Supabase project is a dedicated PostgreSQL instance)
- Auth: built-in authentication (email, social, phone, anonymous) with RLS integration
- Storage: S3-compatible file storage with RLS policies
- Edge Functions: Deno runtime for serverless functions at the edge
- Realtime: PostgreSQL logical replication → WebSocket subscriptions
- pgvector: built-in vector extension for AI/semantic search
- Row Level Security: generated RLS policies from auth rules
- AI tools: 60%+ of new Supabase databases are created by AI tools (Cursor, Claude, v0.dev) — Supabase is AI-native infrastructure

**Critical finding: 60%+ new DBs via AI tools**
Supabase is the de facto PostgreSQL backend for AI-generated applications. When Claude Code, v0.dev, Cursor, or Bolt.new generates a full-stack app, it uses Supabase for the database. PgAppForge must position as the "Supabase for ERP" — providing the same frictionless PostgreSQL experience but with 120 pre-built domain modules.

**Strengths**
- 100K GitHub stars — largest mindshare in developer tools
- AI-native: AI coding assistants generate Supabase projects by default
- pgvector + RLS combo is uniquely powerful for AI apps with security
- Zero DevOps: managed PostgreSQL with instant setup
- Edge Functions for custom logic
- Excellent documentation and DX

**Weaknesses**
- No ERP domain modules — blank-slate database
- No UI generation
- No mobile builder
- No offline support
- Enterprise tier is expensive ($599+/month)
- Managed-only (no true self-hosted for free tier features)

**Competitive threat to PgAppForge**: HIGH as complementary infrastructure. LOW as direct competitor (no domain modules). Strategic opportunity: "PgAppForge on Supabase" as an installation path.

**Relevance to PgAppForge**: The AI-native positioning is critical. PgAppForge must be the preferred platform when AI assistants generate ERP applications. This requires:
1. A documented PgAppForge "prompt" for Claude/GPT ("how to generate a PgAppForge app")
2. Supabase compatibility layer (deploy PgAppForge against a Supabase PostgreSQL instance)
3. Example apps in Cursor, Claude Code, v0.dev galleries

---

### 2.5 Django

**Business metrics**
- GitHub stars: ~82,000 (BSD license) — most starred Python web framework
- Django REST Framework: ~29,000 stars
- Weekly downloads: ~10M (PyPI)
- Foundation: Django Software Foundation (non-profit)

**Technical profile**
- Python/PostgreSQL natural fit
- Django Admin: auto-generated admin interface from models — the gold standard for back-office Python UIs
- ORM: Django ORM (mature, not SQLAlchemy — different ecosystem)
- DRF (Django REST Framework): serializer-based REST API generation
- GraphQL: Graphene-Django or Strawberry for Django
- Migrations: automatic schema migration from model changes
- Multi-tenancy: django-tenants (PostgreSQL schemas), django-pgschemas
- Authentication: built-in auth + django-allauth for OAuth
- Async: ASGI support, async views (Django 4.1+)

**Django Admin vs PgAppForge**
Django Admin is the 25-year-old gold standard for auto-generated admin UIs. PgAppForge's ModelView is conceptually the same (model → CRUD UI). The differences:
- PgAppForge generates a full end-user application, not just an admin panel
- PgAppForge has domain modules; Django Admin is blank-slate
- PgAppForge uses SQLAlchemy (not Django ORM)
- Django Admin has inline editing, filter by related objects, custom admin actions

PgAppForge should study Django Admin's UX patterns for the citizen dev config layer.

**Strengths**
- Django ORM migrations are the benchmark for schema evolution
- Admin is the gold standard for rapid back-office UI
- Largest Python web ecosystem
- Multi-tenancy via postgres schemas is production-grade
- async/ASGI support is mature

**Weaknesses**
- No visual builder
- No code generation beyond admin
- No mobile
- Django ORM vs SQLAlchemy ecosystem split (migration cost is high)
- No domain ERP modules
- No Africa regulatory compliance

**Relevance to PgAppForge**: Django's migration system and multi-tenancy patterns are the reference implementations. **DO NOT migrate PgAppForge to Django** — the SQLAlchemy abandon cost is prohibitive (see Flask-AppBuilder analysis).

---

### 2.6 Bubble

**Business metrics**
- Users: 2M+ registered creators
- Revenue: ~$100M ARR (estimated)
- Pricing: Free (Bubble domain); Starter $29/month; Growth $119/month; Team $349/month

**Technical profile**
- Visual drag-and-drop builder for web apps
- Built-in database (proprietary, not PostgreSQL)
- Logic: visual workflow editor (no code option)
- AI: AI app generation from description (2024 launch)
- Mobile: responsive web only (no native mobile)
- API: REST API connector (consume external APIs, not auto-generate)
- Deployment: Bubble cloud only

**Critical weakness: No code export**
Bubble apps cannot be exported as code. The app is permanently locked to Bubble's proprietary runtime and database. This is the most severe vendor lock-in of any platform reviewed.

**Competitive threat to PgAppForge**: ZERO for technical users. MEDIUM for citizen developers who don't know or care about lock-in. The 2M users demonstrate massive demand for no-code ERP-type applications from non-developers — PgAppForge should build a citizen dev tier to capture this audience.

---

### 2.7 Glide

**Business metrics**
- Users: 100K+ businesses
- Revenue: ~$20M ARR
- Pricing: Free (basic); Maker $49/month; Business $249/month; Enterprise custom

**Technical profile**
- PWA generation from Google Sheets, Airtable, Excel, PostgreSQL, MySQL
- AI columns: AI-computed fields (classify, extract, translate, generate) without code
- Real-time sync: bidirectional sync between Glide app and data source
- Mobile: PWA optimized for mobile — feels like native
- No code export (Glide proprietary runtime)
- Offline: limited (read-only cached data)
- Actions: simple automations (send email, create row, webhook)

**Key insight: AI columns**
Glide's AI columns let non-technical users add AI-powered computed fields to any table. "Summarize this support ticket" or "Classify this expense" as a column value. This is a pattern PgAppForge should implement — AI-powered computed columns on SQLAlchemy models.

**Competitive threat to PgAppForge**: LOW for enterprise. MEDIUM for Africa SME data collection use cases. PWA + offline-first approach is directly relevant.

---

## 3. Feature Matrix

| Feature | JHipster | Jmix | Hasura | Supabase | Django | Bubble | Glide | **PgAppForge** |
|---|---|---|---|---|---|---|---|---|
| Visual UI builder | ❌ | ✅ Jmix Studio | ❌ | ❌ | ✅ Admin | ✅ | ✅ | ❌ |
| AI app generation | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | 🔶 | ❌ |
| AI computed columns | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Native mobile | ✅ RN blueprint | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ PWA | 🔶 CLI |
| GraphQL auto-gen | ❌ | ❌ | ✅ (best) | ✅ | ✅ Strawberry | ❌ | ❌ | ❌ |
| REST API auto-gen | ✅ | ✅ OpenAPI | ✅ | ✅ | ✅ DRF | ❌ | ❌ | 🔶 partial |
| Visual BPM | ❌ | ✅ BPMN 2.0 | ❌ | ❌ | ❌ | ✅ | 🔶 | ❌ |
| Automatic audit log | ❌ | ✅ | ❌ | ❌ | 🔶 | ❌ | ❌ | 🔶 partial |
| Soft delete | ❌ | ✅ | ❌ | ❌ | 🔶 | ❌ | ❌ | ❌ |
| Multi-tenancy | ❌ | ✅ | ❌ | ✅ RLS | ✅ schemas | ❌ | ❌ | ❌ |
| pgvector / AI-ready | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | 🔶 SQLAlchemy |
| Schema migration | ✅ Liquibase | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ Alembic |
| Code portability | ✅ (full) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Microservices gen | ✅ (best) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| AI-native (by AI tools) | ❌ | ❌ | ❌ | ✅ (60%+ DBs) | 🔶 | ❌ | ❌ | ❌ |
| ERP domain modules | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 120+ |
| Africa fintech | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 20 plugins |
| Open-source | ✅ MIT | ✅ Apache | ✅ Apache | ✅ Apache | ✅ BSD | ❌ | ❌ | ✅ |
| PostgreSQL-native | ✅ | ✅ | ✅ | ✅ (is PG) | ✅ | ❌ proprietary | ❌ | ✅ |

---

## 4. PgAppForge Unique Position

**PgAppForge is the ONLY tool that is simultaneously**:
1. Database-first (schema → app, like Supabase/Hasura)
2. Multi-platform generation (web/mobile/desktop, like JHipster)
3. Python-native (like Django, unlike JHipster/Jmix)
4. ERP domain modules (120+ pre-built, unlike every competitor)
5. Open-source without enterprise paywall
6. Africa regulatory compliance
7. PostgreSQL-native (unlike ERPNext/MariaDB)

No single competitor occupies this intersection. This is the moat.

---

## 5. Key Patterns to Copy

### From Jmix
- **BPMN 2.0 integration**: Jmix uses Flowable (Java BPMN engine). PgAppForge should use SpiffWorkflow (Python BPMN) or build on top of the existing `rules/dsl.py`.
- **Automatic audit trail**: `@Audit` annotation pattern → SQLAlchemy event listener equivalent.
- **Soft delete**: `@SoftDelete` → SQLAlchemy `deleted_at` timestamp + query filter mixin.
- **Multi-tenancy**: `@TenantEntity` → PostgreSQL RLS policy generation per model.

### From Supabase
- **AI-native positioning**: publish prompt templates for "generate a PgAppForge app" in Claude/GPT/Cursor.
- **Zero-DevOps install**: `docker run pgappforge/pgappforge` → working app in 60 seconds.
- **DX focus**: sub-5-minute time to first working CRUD app.

### From Hasura
- **Column-level permissions**: integrate with SQLAlchemy query filtering to enforce column-level access control.
- **Database event triggers**: PostgreSQL NOTIFY → webhook dispatch for async workflows.

### From JHipster
- **Schema DSL**: define a PgAppForge Domain Language (PDL) in YAML/Python that generates models, views, migrations, tests, and OpenAPI specs.
- **Microservices generation**: FastAPI service generation from PDL (Phase 2 of the FastAPI migration).

### From Glide
- **AI computed columns**: AI-powered field generation (summarize, classify, extract) as a first-class SQLAlchemy model feature.
- **PWA offline**: Glide's offline read-cache pattern is the target for PgAppForge's offline mode.

### From Django Admin
- **Inline editing**: edit related objects without leaving the parent form.
- **Custom admin actions**: bulk actions on list views with confirmation dialogs.
- **Filter by related**: multi-hop filter (e.g., "orders where customer.country = Kenya").

---

## 6. The "Supabase for ERP" Positioning

Supabase's 100K GitHub stars and AI-native traction demonstrate that developers want:
1. Zero-config PostgreSQL (no DevOps)
2. Instant APIs from schema
3. Built-in auth + RLS
4. AI tool compatibility (Claude, Cursor generate Supabase by default)

PgAppForge should position as "Supabase for ERP":
- **Zero-config**: `pip install pgappforge && pgappforge init` → working ERP in 5 minutes
- **Instant APIs**: REST + GraphQL from any SQLAlchemy model
- **Built-in auth + RLS**: PostgreSQL RLS generated from role definitions
- **AI-native**: Claude Code, Cursor, v0.dev templates for generating PgAppForge apps

This positions PgAppForge not as "Django Admin with more features" but as "the AI-native ERP platform built on PostgreSQL."

---

## 7. Strategic Recommendations

### Immediate (< 30 days)
1. **Publish "Supabase for ERP" positioning document** — white paper targeting developers who know Supabase but need ERP domain modules.
2. **Soft delete mixin** — implement `SoftDeleteMixin` on SQLAlchemy models. Copy Jmix's `@SoftDelete` pattern. Estimated: 2 days.
3. **Column-level RLS generation** — generate PostgreSQL RLS policies from FAB permission definitions. Estimated: 1 week.

### Short-term (1–3 months)
4. **Schema DSL (PDL)** — PgAppForge Domain Language in YAML. One YAML file generates: SQLAlchemy models, Alembic migration, REST endpoints, OpenAPI spec, test fixtures. Follow JHipster JDL pattern.
5. **BPMN workflow engine** — integrate SpiffWorkflow (pure Python BPMN 2.0). Generate workflow instances from SQLAlchemy model lifecycle events.
6. **Automatic audit trail** — SQLAlchemy event listener mixin. `@audited` decorator generates audit table and logs all CUD operations.

### Medium-term (3–6 months)
7. **AI computed columns** — follow Glide's pattern. Annotate SQLAlchemy columns with `ai_computed=True, prompt="summarize {field}"`. Compute via local Ollama or OpenAI API.
8. **Claude Code template** — publish `pgappforge-project` template for Claude Code. When a developer asks Claude "create an ERP app", Claude uses PgAppForge. Follow Supabase's AI-native playbook.
9. **GraphQL layer** — Strawberry + SQLAlchemy integration. Auto-generate GraphQL schema from SQLAlchemy models. Similar to Hasura DDN but in Python.

---

## 8. Sources

- JHipster JDL: jhipster.tech/jdl/
- Jmix audit/soft-delete: docs.jmix.io/jmix/audit/
- Hasura DDN: hasura.io/ddn
- Supabase $10.5B valuation: TechCrunch 2025
- Supabase AI tools stat: supabase.com/blog/ai-tools-2025 (60%+ new DBs via AI)
- Django multi-tenancy: django-tenants.readthedocs.io
- Bubble lock-in: bubble.io/terms (data export limitations)
- Glide AI columns: glide.page/docs/computed-columns
