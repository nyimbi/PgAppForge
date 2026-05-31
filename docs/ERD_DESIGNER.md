# ERD Designer Plugin

ERD Designer is the interactive schema design canvas for pgappforge. It provides a Cytoscape.js-powered visual editor with ERP module templates, bidirectional DDL execution, AI-assisted schema generation, real-time collaboration via SSE, and one-click app codegen from the live database schema.

---

## Quick start

### View registration

```python
# app.py or factory
from pgappforge.views.erd_designer import ERDDesignerView

appbuilder.add_view(
    ERDDesignerView,
    "ERD Designer",
    icon="fa-sitemap",
    category="Tools",
)
```

The view mounts at `/erd-designer/` with all API sub-routes beneath it.

### Read-only live ERD (no editing)

```python
from pgappforge.views.erd_view import ERDView

appbuilder.add_view(ERDView, "Live ERD", icon="fa-project-diagram", category="Tools")
```

`ERDView` mounts at `/erd/` and renders a Mermaid diagram generated live from the database. It has no write endpoints and requires no additional config.

### Enabling DDL mutations

DDL endpoints are **disabled by default** and return HTTP 403 with `{"code": "ddl_disabled"}` until you opt in:

```python
# config.py
FAB_ERD_DDL_ENABLED = True   # required for any schema mutation
SECRET_KEY = "..."            # must be set for CSRF
```

Only users with the **Admin** role can call mutating endpoints once `FAB_ERD_DDL_ENABLED` is set.

### Creating the persistence tables

`ErdDesign` and `ErdMigrationLog` are SQLAlchemy models registered on the shared `Model` base. Run your usual migration step (Alembic or `db.create_all()`) to create `erd_design` and `erd_migration_log`.

---

## Configuration keys

| Key | Default | Description |
|-----|---------|-------------|
| `FAB_ERD_DDL_ENABLED` | `False` | Set `True` to unlock all schema-mutation endpoints. **Keep `False` on production databases you do not want the designer to touch.** |
| `FAB_ERD_DDL_TIMEOUT_MS` | `30000` | PostgreSQL `statement_timeout` applied to every DDL batch via `SET LOCAL`. Prevents runaway `ALTER TABLE` on large tables. Value is in milliseconds. |
| `FAB_CODEGEN_OUTPUT_ROOT` | `"/tmp/pgaf_generated"` | Root directory for the app-generation endpoint. All `output_dir` values are validated against this root to prevent path traversal — any path that is not under this directory is rejected with HTTP 400. |

---

## Security model

### Role check

Every mutating endpoint calls `_require_schema_admin()` which enforces two conditions in order:

1. `FAB_ERD_DDL_ENABLED` must be `True` — fails with JSON `{"code": "ddl_disabled"}` and HTTP 403.
2. The authenticated user must have the **Admin** (or **admin**) role — fails with JSON `{"code": "admin_required"}` and HTTP 403.
3. The user must be authenticated — fails with JSON `{"code": "login_required"}` and HTTP 403.

Read-only endpoints (list, export, AI suggestions) require `@has_access` only — any authenticated user with a role that has view permission may call them.

### CSRF protection

All JSON POST endpoints that mutate schema call `_validate_csrf()`. This reads the `X-CSRFToken` request header (set by the designer JS from the `<meta name="csrf-token">` tag) and validates it via `flask_wtf.csrf.validate_csrf`. If `flask-wtf` is not installed the endpoint returns HTTP 500 with a clear installation hint. Requests without a valid token receive HTTP 400.

### Per-design ACL

Saved designs enforce owner-based access:

- `GET /api/designs/<id>` — accessible to the owner **or** if `is_public=True`.
- `PUT /api/designs/<id>` — owner only.
- `DELETE /api/designs/<id>` — owner only.
- `GET /api/events/<id>` (SSE stream) — accessible to the owner or if `is_public=True`.

Admin users can apply DDL regardless of design ownership.

### Share tokens

Share tokens are created via `POST /api/designs/<id>/share` and reuse the `ReportForge` token infrastructure (`pgappforge.plugins.reports.acl.generate_token`). Tokens are:

- Time-limited (`expires_hours`, default 48 h).
- Optionally quota-limited (`max_uses`).
- Validated atomically on each access (`UPDATE … WHERE uses_remaining > 0 RETURNING id`) to prevent race conditions on view-once tokens.
- Embedded in the URL `/erd-designer/view/<token>` which serves a read-only, login-free Cytoscape canvas.

### Path traversal prevention

The `api_generate_app` endpoint validates that the caller-supplied `output_dir` is under `FAB_CODEGEN_OUTPUT_ROOT` using `Path.relative_to()`. Any path outside the root is rejected with HTTP 400.

### DDL identifier safety

All table names, column names, and schema names passed through the schema manager are validated by `_qi()` against the pattern `^[A-Za-z_][A-Za-z0-9_]{0,62}$` and then double-quoted. Column types are validated by `_PG_TYPE_RE`. Default values are passed through `_quote_default()` which single-quotes plain strings and passes SQL expressions through unchanged. Predicate expressions (CHECK constraints, RLS policies) are validated by `_validate_pred_expr()` which blocks semicolons and a regex of banned DDL keywords.

---

## The `ops[]` schema for `POST /api/schema/apply`

The endpoint accepts a JSON array of operation objects. All operations in a single call run in one transaction — any error rolls back all.

Add `?dry_run=1` to preview SQL without executing. The response will contain `{"dry_run": true, "sql": [...], "would_apply": N}`.

### 1. `create_table`

Create a new table. FK constraints are deferred to `ALTER TABLE ADD CONSTRAINT` to avoid ordering issues.

```json
{
  "op": "create_table",
  "table": "orders",
  "schema": "public",
  "columns": [
    {"name": "id",          "type": "SERIAL",       "pk": true},
    {"name": "customer_id", "type": "INTEGER",       "nullable": false, "fk": "customers.id"},
    {"name": "status",      "type": "VARCHAR(20)",   "default": "'draft'"},
    {"name": "total",       "type": "NUMERIC(19,4)", "nullable": true}
  ]
}
```

| Column field | Required | Description |
|---|---|---|
| `name` | yes | Identifier, validated by `_qi()` |
| `type` | yes | PostgreSQL type string, validated by `_PG_TYPE_RE` |
| `pk` | no | `true` → `PRIMARY KEY` |
| `nullable` | no | `false` → `NOT NULL` (default: `true`) |
| `unique` | no | `true` → `UNIQUE` (skipped if `pk: true`) |
| `default` | no | SQL expression or plain string (auto-quoted) |
| `fk` | no | `"other_table.col"` or `"other_table"` — emits `ADD CONSTRAINT … FOREIGN KEY` |
| `schema` | no | Schema-qualifies the table reference |

### 2. `drop_table`

```json
{"op": "drop_table", "table": "orders"}
```

Emits `DROP TABLE IF EXISTS "orders" CASCADE`. No rollback SQL is generated for this op.

### 3. `add_column`

```json
{
  "op": "add_column",
  "table": "orders",
  "column": {"name": "notes", "type": "TEXT", "nullable": true}
}
```

Emits `ALTER TABLE "orders" ADD COLUMN IF NOT EXISTS "notes" TEXT`.

### 4. `drop_column`

```json
{"op": "drop_column", "table": "orders", "column": "notes"}
```

Emits `ALTER TABLE "orders" DROP COLUMN IF EXISTS "notes" CASCADE`.

### 5. `alter_column`

Change type, nullability, or default independently. Only fields present in the op are applied.

```json
{
  "op": "alter_column",
  "table": "orders",
  "column": "status",
  "new_type": "TEXT",
  "nullable": false,
  "default": "'pending'"
}
```

| Field | Required | Description |
|---|---|---|
| `column` | yes | Column name |
| `new_type` | no | New PostgreSQL type; emits `TYPE … USING col::new_type` |
| `nullable` | no | `true` → `DROP NOT NULL`; `false` → `SET NOT NULL` |
| `default` | no | New default value; `null` → `DROP DEFAULT` |

### 6. `add_fk`

```json
{
  "op": "add_fk",
  "table": "orders",
  "column": "customer_id",
  "ref_table": "customers",
  "ref_column": "id",
  "constraint_name": "orders_customer_id_customers_fkey"
}
```

`constraint_name` is optional — defaults to `{table}_{column}_{ref_table}_fkey`. Auto-generated names longer than 63 characters are truncated with an MD5 suffix.

### 7. `drop_fk`

```json
{"op": "drop_fk", "table": "orders", "constraint_name": "orders_customer_id_customers_fkey"}
```

### 8. `rename_table`

```json
{"op": "rename_table", "table": "orders", "new_name": "purchase_orders"}
```

No rollback SQL is generated.

### 9. `rename_column`

```json
{"op": "rename_column", "table": "orders", "column": "amt", "new_name": "amount"}
```

No rollback SQL is generated.

### 10. `add_index`

```json
{
  "op": "add_index",
  "table": "orders",
  "columns": ["customer_id", "status"],
  "unique": false,
  "name": "ix_orders_customer_status"
}
```

`name` is optional — defaults to `ix_{table}_{col1}_{col2}`. Emits `CREATE [UNIQUE] INDEX IF NOT EXISTS`.

### 11. `drop_index`

```json
{"op": "drop_index", "name": "ix_orders_customer_status"}
```

### 12. `create_enum`

```json
{"op": "create_enum", "name": "order_status_t", "values": ["draft", "active", "closed"], "schema": "public"}
```

### 13. `drop_enum`

```json
{"op": "drop_enum", "name": "order_status_t", "schema": "public"}
```

### 14. `add_check_constraint`

The `expression` is validated by `_validate_pred_expr()` — semicolons and DDL keywords are blocked.

```json
{
  "op": "add_check_constraint",
  "table": "orders",
  "expression": "total >= 0",
  "name": "chk_orders_total_positive"
}
```

`name` is optional — defaults to `chk_{table}_{hash(expression) % 10000}`.

### 15. `drop_check_constraint`

```json
{"op": "drop_check_constraint", "table": "orders", "name": "chk_orders_total_positive"}
```

### 16. `set_composite_pk`

Drops the existing primary key (if any) and adds a new composite one atomically via a `DO $$ … END $$` block.

```json
{"op": "set_composite_pk", "table": "order_lines", "columns": ["order_id", "line_num"]}
```

### 17. (module apply)

Not sent to `/api/schema/apply` directly — use `POST /api/apply-module/<key>` to apply a full ERP module. Internally translates all module tables into `create_table` ops and calls `apply_changes`.

---

## Template catalog

Templates are accessed via the left sidebar template palette and the `/api/triggers/templates` and `/api/objects/templates` endpoints.

### Trigger templates (18)

Accessed via `GET /api/triggers/templates`. Apply via `POST /api/triggers/apply-template` with `{"template_key": "...", ...params}`.

**Timestamps category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `updated_at` | Auto-update `updated_at` timestamp | `table`, `schema` |
| `created_at_auto` | Auto-set `created_at` on INSERT | `table`, `schema` |

**Audit category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `audit_log` | Audit log (INSERT/UPDATE/DELETE → `audit_log` table) | `table` |
| `version_history` | Append-only version history | `table`, `schema` |

**Validation category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `validate_email` | Validate email format (RFC-5322 pattern) | `table`, `schema`, `email_column` |
| `immutable_field` | Protect immutable field after creation | `table`, `schema`, `guard_column` |
| `jsonb_schema_validate` | Validate JSONB against required keys | `table`, `schema`, `json_column`, `required_keys` |
| `quota_guard` | Enforce row-count quota per parent | `table`, `schema`, `parent_column`, `max_rows` |

**Security category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `row_level_security_tenant` | Enable Row Level Security for multi-tenant table | `table` |
| `encrypt_column` | Encrypt sensitive column (pgcrypto) | `table`, `schema`, `column` |

**Integration category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `notify_on_change` | Send `pg_notify` on INSERT/UPDATE | `table`, `schema`, `channel` |

**Search category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `tsvector_search` | Full-text search column (`tsvector`) | `table`, `schema`, `search_columns` |

**Derived category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `slugify` | Auto-generate URL slug from title/name | `table`, `schema`, `source_column`, `slug_column` |

**Identity category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `uuid_pk` | Auto-generate UUID primary key | `table`, `schema` |

**Finance category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `ledger_balance` | Running balance for financial ledger | `table`, `schema`, `account_column`, `amount_column` |

**Workflow category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `publish_lock` | Lock row after published/finalized status | `table`, `schema`, `status_column`, `locked_status` |

**Performance category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `refresh_summary` | Refresh materialized view on data change | `table`, `schema`, `view_name` |

**Soft-delete category**

| Key | Label | Required params |
|-----|-------|-----------------|
| `soft_delete_guard` | Prevent hard DELETE on soft-delete table | `table`, `schema` |

### Object templates (25)

Accessed via `GET /api/objects/templates[?type=<domain|event_trigger|materialized_view|view|policy>]`. Apply via `POST /api/objects/apply-template`.

**Domains (6)**

| Key | Label | Category |
|-----|-------|----------|
| `domain_email` | Email address domain | validation |
| `domain_positive_int` | Positive integer domain | validation |
| `domain_money` | Non-negative money domain | finance |
| `domain_phone` | International phone number domain | validation |
| `domain_percentage` | Percentage domain (0–100) | validation |
| `domain_uuid` | UUID domain with auto-default | identity |
| `domain_status` | Status domain (enumerated TEXT) | workflow |

**Event triggers (3)**

| Key | Label | Category |
|-----|-------|----------|
| `event_trigger_log_ddl` | Log all DDL changes | audit |
| `event_trigger_prevent_drop` | Prevent DROP on protected tables | security |
| `event_trigger_notify_ddl` | Notify on DDL change (`pg_notify`) | integration |

**Materialized views (4)**

| Key | Label | Category |
|-----|-------|----------|
| `matview_aggregate_summary` | Aggregate summary | analytics |
| `matview_daily_rollup` | Daily time-series rollup | analytics |
| `matview_latest_per_group` | Latest row per group (`DISTINCT ON`) | analytics |
| `matview_cross_join_report` | Denormalised report (JOIN two tables) | reporting |

**Views (5)**

| Key | Label | Category |
|-----|-------|----------|
| `view_active_records` | Active records (soft-delete filter) | soft-delete |
| `view_tenant_scoped` | Tenant-scoped view | multi-tenant |
| `view_recent_records` | Recent records (LIMIT N) | convenience |
| `view_joined_report` | Joined report view | reporting |
| `view_audit_readable` | Human-readable audit log view | audit |

**RLS Policies (6)**

| Key | Label | Category |
|-----|-------|----------|
| `policy_tenant_isolation` | Multi-tenant row isolation | multi-tenant |
| `policy_owner_only` | Owner-only access | ownership |
| `policy_public_read` | Public read, authenticated write | public-data |
| `policy_admin_bypass` | Admin bypass + user filter | admin |
| `policy_time_locked` | Read-only after expiry timestamp | temporal |
| `policy_column_masked` | Column masking for non-privileged users | security |

---

## API reference

All endpoints are under the `ERDDesignerView` blueprint at `/erd-designer`. Every endpoint requires `@has_access` (authenticated session). Endpoints that mutate schema additionally require Admin role and `FAB_ERD_DDL_ENABLED=True`.

### Schema — read

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/live-schema` | Live DB schema as Cytoscape compound nodes (`{elements: [...]}`) |
| `GET` | `/api/schema-list` | List PostgreSQL schemas visible to the connection |
| `POST` | `/api/schema/diff` | Dry-run diff: compute SQL for proposed ops without executing. Body: `{"ops": [...]}` |

### Schema — mutate (Admin + DDL enabled)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/schema/apply[?dry_run=1]` | Apply ops array. Add `dry_run=1` to preview SQL only |
| `POST` | `/api/apply-module/<key>` | Create all tables for an ERP module template |
| `POST` | `/api/schema/import-sql` | Import DDL from raw SQL (CREATE TABLE, ALTER TABLE, CREATE INDEX only). Body: `{"sql": "...", "dry_run": false}` |

### ERP templates

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/all-templates` | All built-in and registered ERP modules as Cytoscape elements |
| `GET` | `/api/module/<key>` | Elements for a single ERP module key |

### Designs — CRUD

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/designs` | List designs (own + public), last 100 by `changed_on` |
| `POST` | `/api/designs` | Create design. Body: `{name, canvas_json, schema_json, description?, is_public?}` |
| `GET` | `/api/designs/<id>` | Load design (owner or public) |
| `PUT` | `/api/designs/<id>` | Auto-save. Body: any subset of `{name, description, is_public, canvas_json, schema_json}` |
| `DELETE` | `/api/designs/<id>` | Delete (owner only) |

### Collaboration & sharing

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/events/<design_id>` | SSE stream for real-time canvas sync. Returns `text/event-stream` |
| `POST` | `/api/designs/<id>/share` | Create share token. Body: `{expires_hours?, max_uses?}`. Returns `{url, expires_hours}` |
| `GET` | `/view/<token>` | Read-only shared canvas (no login required) |

### Migration log

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/migration-log` | Last 50 DDL log entries (Admin only) |
| `POST` | `/api/migration-log/<id>/rollback` | Execute rollback SQL for a log entry (Admin only) |

### Export

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/export/mermaid` | Download live schema as `schema.mmd` (Mermaid `erDiagram`) |
| `GET` | `/api/export/alembic[?ops=<json>]` | Download Alembic migration script (`upgrade` + `downgrade`) |
| `GET` | `/api/export/orm[?format=sqlalchemy|django|prisma&schema=public]` | Download ORM model code |

### App generation (Admin + DDL enabled)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/generate-app` | Trigger pgappforge codegen. Body: `{app_name, output_dir?}` |

### Triggers & functions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/triggers/templates` | List all 18 trigger templates with full metadata |
| `GET` | `/api/triggers/list[?table=<name>]` | List live triggers (all or filtered by table) |
| `POST` | `/api/triggers/apply-template` | Apply a trigger template. Body: `{template_key, ...params}` (Admin) |
| `POST` | `/api/triggers/drop` | Drop a trigger. Body: `{table, trigger_name}` (Admin) |
| `GET` | `/api/functions/list[?schema=public]` | List user-defined functions and procedures |
| `GET` | `/api/functions/source[?name=&schema=]` | Return source code of a function |
| `POST` | `/api/functions/create` | Create/replace a function. Body: `{name, body, args?, returns?, language?, schema?}` (Admin) |
| `POST` | `/api/functions/drop` | Drop a function. Body: `{name, args?, schema?}` (Admin) |

### Database objects

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/objects/templates[?type=<type>]` | List all 25 object templates (optionally filtered by type) |
| `POST` | `/api/objects/apply-template` | Apply an object template. Body: `{template_key, ...params}` (Admin) |
| `GET` | `/api/domains/list[?schema=public]` | List domains |
| `POST` | `/api/domains/drop` | Drop a domain. Body: `{name, schema?, cascade?}` (Admin) |
| `GET` | `/api/event-triggers/list` | List event triggers |
| `POST` | `/api/event-triggers/drop` | Drop an event trigger. Body: `{name}` (Admin) |
| `POST` | `/api/event-triggers/toggle` | Enable/disable event trigger. Body: `{name, enable}` (Admin) |
| `GET` | `/api/matviews/list[?schema=public]` | List materialized views with size |
| `POST` | `/api/matviews/refresh` | Refresh a mat view. Body: `{name, schema?, concurrently?}` (Admin) |
| `POST` | `/api/matviews/drop` | Drop a mat view. Body: `{name, schema?}` (Admin) |
| `GET` | `/api/views/list[?schema=public]` | List views |
| `GET` | `/api/views/definition[?name=&schema=&materialized=]` | Get view SQL definition |
| `POST` | `/api/views/create` | Create/replace a view. Body: `{name, query, schema?, materialized?}` (Admin) |
| `POST` | `/api/views/drop` | Drop a view. Body: `{name, schema?, materialized?}` (Admin) |
| `GET` | `/api/policies/list[?table=&schema=]` | List RLS policies |
| `POST` | `/api/policies/create` | Create RLS policy. Body: `{table, name, using_expr, command?, check_expr?, schema?}` (Admin) |
| `POST` | `/api/policies/drop` | Drop RLS policy. Body: `{table, name, schema?}` (Admin) |

### AI

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ai/generate-schema` | Generate `create_table` ops from a description. Body: `{description}` |
| `GET` | `/api/ai/suggest-fks` | Suggest FK relationships from `_id` column naming conventions |
| `GET` | `/api/analysis/normalize` | Detect 1NF/2NF normalization issues in live schema |
| `GET` | `/api/analysis/recommend-indexes` | Recommend missing indexes from FK columns and naming patterns |

**Total: 52 endpoints**

### `ERDView` endpoints (read-only live ERD at `/erd/`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/erd/` | Interactive Mermaid ERD diagram |
| `GET` | `/erd/data.json` | ERD as structured JSON |
| `GET` | `/erd/export/mermaid` | Download `erd.mmd` |
| `GET` | `/erd/export/sql` | Download reconstructed `CREATE TABLE` SQL |
| `GET` | `/erd/export/graphml` | Download ERD as GraphML (tables=nodes, FK=edges) |

---

## Persistence models

### `ErdDesign` — table `erd_design`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER` PK | Auto-increment |
| `name` | `VARCHAR(255)` NOT NULL | Human-readable design name |
| `description` | `TEXT` | Optional description |
| `canvas_json` | `JSONB` | Cytoscape.js element list including node positions and module groupings |
| `schema_json` | `JSONB` | Normalised schema snapshot (`{tables: [...], relationships: [...]}`) at last save |
| `is_public` | `BOOLEAN` NOT NULL | If `true`, any authenticated user can view/open the design (but not edit) |
| `owner_id` | `INTEGER` FK → `ab_user.id` | Nullable — designs created by a deleted user remain accessible |
| `created_on` | `TIMESTAMPTZ` NOT NULL | Insert timestamp (UTC) |
| `changed_on` | `TIMESTAMPTZ` NOT NULL | Last-updated timestamp (UTC), auto-set on UPDATE |
| `version` | `INTEGER` NOT NULL | SQLAlchemy optimistic-locking counter (`version_id_col`) |

Indexes: `ix_erd_design_owner (owner_id)`, `ix_erd_design_name (name)`.

### `ErdMigrationLog` — table `erd_migration_log`

Append-only. Never modify existing rows. Written atomically inside the same transaction as the DDL (on success) or in a separate session (on error).

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER` PK | Auto-increment |
| `user_id` | `INTEGER` FK → `ab_user.id` | Nullable — the Admin user who triggered the migration |
| `applied_at` | `TIMESTAMPTZ` NOT NULL | UTC timestamp of the apply attempt |
| `ops_json` | `JSONB` NOT NULL | The original `ops[]` array as sent by the client |
| `sql_json` | `JSONB` NOT NULL | The SQL statements that were (or would have been) executed |
| `status` | `VARCHAR(20)` NOT NULL | `"success"` or `"error"` |
| `error` | `TEXT` | Error message if `status = "error"`, else `NULL` |
| `rollback_sql` | `JSONB` NOT NULL | Auto-generated inverse DDL (see rollback notes below) |

Indexes: `ix_erd_mig_log_user (user_id)`, `ix_erd_mig_log_status (status)`, `ix_erd_mig_log_ts (applied_at)`.

**Rollback SQL notes:** Rollback SQL is auto-generated for `create_table` (→ `DROP TABLE IF EXISTS … CASCADE`), `add_column` (→ `DROP COLUMN`), and `add_fk` (→ `DROP CONSTRAINT`). Operations like `drop_table`, `drop_column`, `alter_column`, `rename_table`, and `rename_column` have no safe deterministic inverse and produce no rollback SQL. The rollback endpoint at `POST /api/migration-log/<id>/rollback` executes the stored rollback statements in a fresh transaction.

---

## Collaboration & sharing

### SSE real-time sync

`GET /api/events/<design_id>` opens a Server-Sent Events stream. The designer JS opens this connection when a saved design is loaded. When another user calls `PUT /api/designs/<id>` with a `canvas_json` update, the server broadcasts a `{"type": "update", "user": "...", "canvas_json": {...}}` message to all connected clients for that design.

**Event types:**

| `type` | When sent | Payload |
|--------|-----------|---------|
| `connected` | On stream open | `{design_id}` |
| `update` | On `PUT /api/designs/<id>` with `canvas_json` | `{user, canvas_json}` |
| `ping` | Every 25 s (keepalive) | `{}` |

Stale queues (inactive > 120 s) are reaped on the next broadcast. Queues are capped at 50 pending messages; clients that fall behind are evicted.

### Deployment notes for SSE

SSE requires the connection to stay open. **You must run with a single Gunicorn worker** (or an async worker like `gevent`/`eventlet`) to avoid cross-worker broadcast failures:

```bash
# Single sync worker
gunicorn -w 1 -b 0.0.0.0:8080 app:app

# Async workers (multi-worker capable)
gunicorn -w 4 -k gevent -b 0.0.0.0:8080 app:app
```

Behind nginx, disable proxy buffering for the SSE route:

```nginx
location /erd-designer/api/events/ {
    proxy_pass         http://app;
    proxy_http_version 1.1;
    proxy_set_header   Connection "";
    proxy_buffering    off;
    proxy_cache        off;
    proxy_read_timeout 3600s;
}
```

**Future:** A PostgreSQL `LISTEN/NOTIFY` backend is planned to allow multi-process deployments without gevent. When implemented, `FAB_ERD_SSE_BACKEND = "pg_notify"` will replace the in-process queue.

### Share tokens

```
POST /api/designs/<design_id>/share
Content-Type: application/json
X-CSRFToken: <token>

{"expires_hours": 48, "max_uses": null}
```

Response:
```json
{"ok": true, "url": "/erd-designer/view/<token>", "expires_hours": 48}
```

The shared URL at `/erd-designer/view/<token>` renders a minimal read-only Cytoscape canvas with no authentication required. The canvas is rendered using the stored `canvas_json`. Expired or quota-exhausted tokens return HTTP 403.

---

## AI features

All AI endpoints call `pgappforge.plugins.reports.ai_augment.augment_text` which routes to the configured local Ollama model. They degrade gracefully — if Ollama is not running, the endpoint returns an error JSON rather than 500.

### `POST /api/ai/generate-schema`

Sends a natural-language business description to the LLM and returns a ready-to-apply `ops[]` array. The response JSON is stripped of markdown fences and parsed; each table identifier is passed through `_qi()` before returning to the client.

```
POST /api/ai/generate-schema
{"description": "E-commerce store with products, orders, and customers"}
```

Response: `{"ops": [...create_table ops...], "count": N}`

Apply the returned ops directly to `/api/schema/apply`.

### `GET /api/ai/suggest-fks`

Heuristic (no LLM required). Inspects every column ending in `_id`, strips the suffix, and checks if a table named `{prefix}s`, `{prefix}`, or `{prefix}es` exists. Returns suggestions with `"confidence": "high"` (plural match) or `"medium"`.

Response: `{"suggestions": [{"op": "add_fk", "table": ..., "column": ..., "ref_table": ..., "ref_column": "id", "confidence": "high"}]}`

Each suggestion is a valid op object that can be included directly in a `/api/schema/apply` body.

### `GET /api/analysis/normalize`

Inspects the live schema for:
- Tables with no primary key (1NF violation)
- Generic column names (`data`, `info`, `value`, `field`, `col1`, ...) that suggest un-atomised data (1NF)
- Columns appearing in more than 3 tables (excluding `id`, `created_at`, `updated_at`, `is_active`) suggesting a candidate for extraction into a reference table (2NF)

Response: `{"warnings": [{"level": "1NF"|"2NF", "table": ..., "message": ..., "suggestion": ...}]}`

### `GET /api/analysis/recommend-indexes`

Reads live indexes from `pg_indexes` and compares against all FK columns (`.endswith("_id")`) and common query-target patterns (`_at`, `_date`, `_status`, `_type`, `_code`, etc.). Returns recommendations as valid `add_index` op objects.

Response: `{"recommendations": [{"op": "add_index", "table": ..., "columns": [...], "unique": false, "reason": "..."}]}`

---

## Export options

### Mermaid (`GET /api/export/mermaid`)

Downloads `schema.mmd` containing a Mermaid `erDiagram` block. Each entity block lists all columns with `PK` / `FK` annotations. Relationships are deduplicated so composite FKs don't produce duplicate relationship lines.

```
erDiagram
    ORDERS {
        serial id PK
        integer customer_id FK
        varchar_20 status
        numeric_19_4 total
    }
    CUSTOMERS ||--o{ ORDERS : "has"
```

### Alembic migration (`GET /api/export/alembic`)

Pass pending ops as a JSON-encoded `ops` query parameter. Downloads a Python Alembic migration file with `upgrade()` and `downgrade()` functions containing `op.execute()` calls for each DDL statement.

```
GET /api/export/alembic?ops=[{"op":"create_table","table":"orders","columns":[...]}]
```

Downloads `migrate_20260531_142300.py`.

### ORM model code (`GET /api/export/orm`)

| `format` param | Output | Type mapping source |
|---|---|---|
| `sqlalchemy` (default) | SQLAlchemy 2.x `DeclarativeBase` models | `_pg_to_sa_type()` |
| `django` | Django `models.Model` subclasses | `_pg_to_django_type()` |
| `prisma` | Prisma schema models | `_pg_to_prisma_type()` |

```
GET /api/export/orm?format=django&schema=public
```

### App generation (`POST /api/generate-app`)

Triggers the full pgappforge codegen pipeline (`FullAppGenerator`) on the current live schema. Generates views, APIs, templates, and optionally Docker files. Requires Admin + `FAB_ERD_DDL_ENABLED`.

```json
{
  "app_name": "MyShopApp",
  "output_dir": "/tmp/pgaf_generated/myshopapp"
}
```

`output_dir` must be under `FAB_CODEGEN_OUTPUT_ROOT`. If omitted, defaults to `{FAB_CODEGEN_OUTPUT_ROOT}/{safe_app_name}`.

Response: `{"status": "success", "output_dir": "...", "files_generated": N, "next_steps": [...]}`

### SQL import (`POST /api/schema/import-sql`)

Accepts raw DDL from a `pg_dump` output or hand-written SQL. Only `CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX`, and `COMMENT ON` statements are permitted. All other statement types are rejected before execution.

```json
{"sql": "CREATE TABLE foo (id SERIAL PRIMARY KEY);\nALTER TABLE foo ADD COLUMN name TEXT;", "dry_run": false}
```

---

## ERP module templates

Eight built-in ERP modules are included. Each module is a compound node in the designer containing 4–5 pre-wired tables with typed columns and FK relationships.

| Key | Label | Tables |
|-----|-------|--------|
| `AP` | Accounts Payable | `vendors`, `purchase_orders`, `ap_invoices`, `ap_payments`, `payment_terms` |
| `AR` | Accounts Receivable | `customers`, `sales_orders`, `ar_invoices`, `ar_payments`, `credit_notes` |
| `CRM` | Customer Relations | `companies`, `contacts`, `leads`, `opportunities`, `activities` |
| `HR` | Human Resources | `departments`, `positions`, `employees`, `payroll_runs`, `time_attendance` |
| `INV` | Inventory | `product_categories`, `products`, `warehouses`, `stock_levels`, `stock_movements` |
| `GL` | General Ledger | `chart_of_accounts`, `fiscal_periods`, `journal_entries`, `journal_lines`, `budgets` |
| `PROJ` | Projects | `projects`, `project_tasks`, `milestones`, `time_logs`, `project_expenses` |
| `PROC` | Procurement | `suppliers`, `rfq_headers`, `po_headers`, `po_lines`, `goods_receipts` |

Drag a module from the sidebar palette onto the canvas to preview its tables and relationships. Click **Apply** to create all tables via `/api/apply-module/<key>`.

Additional templates can be registered via `pgappforge.templates.registry.TemplateRegistry`.

---

## Optional dependencies

| Package | Purpose | Install | Behaviour when absent |
|---------|---------|---------|----------------------|
| `flask-wtf` | CSRF validation for all mutating endpoints | `pip install flask-wtf` | Mutating endpoints return HTTP 500 with installation hint |
| `ollama` (running service) | AI schema generation via `/api/ai/generate-schema` | Install Ollama, pull a model | AI endpoint returns `{"error": "..."}` with the connection error |
| `alembic` | Alembic export formatting — format-string only, no import | `pip install alembic` | Export endpoint generates the file regardless; `from alembic import op` in the output file requires it at runtime |

---

## Deployment notes

### Single-worker requirement for SSE

The SSE collaboration feature uses an in-process `threading.Queue` per design. Broadcasts only reach clients connected to the **same worker process**. This means:

- Single sync worker: collaboration works fully.
- Multiple sync workers: clients on different workers will not receive each other's updates.
- Async workers (gevent/eventlet): multiple workers are safe because the event loop shares memory within a process.

Use `gunicorn -w 1` for sync deployments, or switch to an async worker class:

```bash
gunicorn -w 4 -k gevent app:app
```

### PostgreSQL `LISTEN/NOTIFY` (future)

A `pg_notify`-based SSE backend is planned. When `FAB_ERD_SSE_BACKEND = "pg_notify"` is set, broadcasts will be routed through PostgreSQL so any number of sync workers can participate. Until then, use the single-worker or async-worker approach above.

### DDL timeout

For production databases with large tables, tune `FAB_ERD_DDL_TIMEOUT_MS` down to prevent accidental long-running `ALTER TABLE` calls from blocking the application:

```python
FAB_ERD_DDL_TIMEOUT_MS = 10_000   # 10 s — fail fast on large table rewrites
```

### Read-only databases

Setting `FAB_ERD_DDL_ENABLED = False` makes the ERD Designer entirely safe on read-only or production databases. The canvas, live schema view, ERP template palette, AI analysis, and all export endpoints remain fully functional. Only the schema-mutation endpoints are blocked.
