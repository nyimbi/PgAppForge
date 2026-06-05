# Designing Your Schema with the ERD Designer

The ERD Designer is a Cytoscape.js-powered visual schema canvas built into
PgAppForge. It lets you create tables, wire foreign keys, apply trigger
templates, and push DDL changes to your PostgreSQL database — all without
leaving the browser.

---

## 1. Accessing the ERD Designer

Register the view in your app factory or `app.py`:

```python
from pgappforge.views.erd_designer import ERDDesignerView

appbuilder.add_view(
    ERDDesignerView,
    "ERD Designer",
    icon="fa-sitemap",
    category="Tools",
)
```

Enable DDL mutations in `config.py` (off by default — safe to leave `False`
on read-only databases):

```python
FAB_ERD_DDL_ENABLED = True
SECRET_KEY = "your-secret-key-here"   # required for CSRF
```

Navigate to `/erd-designer/` while logged in as an **Admin** user. The page
has three zones:

- **Left sidebar** — template palette (ERP modules, trigger templates, object
  templates), plus Matrix and Designs tabs.
- **Canvas** — Cytoscape.js graph; nodes are tables, edges are foreign keys.
- **Right panel** — context-sensitive actions for the selected node or edge.

If you only need a read-only live diagram, `ERDView` mounts at `/erd/` and
requires no config changes.

---

## 2. Loading Your Current Schema

When the designer loads it calls `GET /erd-designer/api/live-schema`, which
queries the PostgreSQL information schema and returns all tables as Cytoscape
compound nodes. You will see one node per table, edges for every FK
constraint, and compound containers grouping tables by schema.

To refresh after an out-of-band migration, click the **Reload Schema** button
in the toolbar. The canvas merges the updated nodes without losing your manual
node positions.

---

## 3. Creating a New Table

Click **+ Add Table** in the toolbar. A dialog opens with a table name field
and a column editor.

As a concrete example, create a `projects` table:

1. Enter table name: `projects`
2. Add columns using the column editor:

| Name | Type | Flags |
|------|------|-------|
| `id` | `UUID` | PK, default `gen_random_uuid()` |
| `name` | `VARCHAR(120)` | NOT NULL |
| `status` | `VARCHAR(30)` | NOT NULL, default `'draft'` |
| `due_date` | `DATE` | nullable |
| `owner_id` | `UUID` | FK → `users.id`, NOT NULL |

3. Click **Save Table**.

The designer translates this into a `create_table` op and (if you already
clicked **Apply Changes**) a `add_fk` op for the `owner_id` constraint:

```json
[
  {
    "op": "create_table",
    "table": "projects",
    "schema": "public",
    "columns": [
      {"name": "id",       "type": "UUID",         "pk": true, "default": "gen_random_uuid()"},
      {"name": "name",     "type": "VARCHAR(120)",  "nullable": false},
      {"name": "status",   "type": "VARCHAR(30)",   "nullable": false, "default": "'draft'"},
      {"name": "due_date", "type": "DATE",           "nullable": true},
      {"name": "owner_id", "type": "UUID",           "nullable": false}
    ]
  },
  {
    "op": "add_fk",
    "table": "projects",
    "column": "owner_id",
    "ref_table": "users",
    "ref_column": "id"
  }
]
```

FK constraints are deferred to `ALTER TABLE ADD CONSTRAINT` so table creation
order does not matter.

---

## 4. Modifying an Existing Table

Select a table node on the canvas. The right panel shows the column list and
a set of actions.

**Add a column** — click **+ Add Column**, fill in name, type, and nullability.
This generates an `add_column` op:

```json
{"op": "add_column", "table": "projects", "column": {"name": "budget", "type": "NUMERIC(19,4)", "nullable": true}}
```

**Change a column type** — right-click the column row and choose **Alter
Column**. Supply `new_type` and, optionally, new nullability or a new default.
Only the fields you fill in are applied:

```json
{"op": "alter_column", "table": "projects", "column": "status", "new_type": "TEXT", "nullable": false}
```

**Add an index** — right-click the table node and choose **Add Index**. Pick
the columns and whether it should be unique. The generated op:

```json
{"op": "add_index", "table": "projects", "columns": ["owner_id", "status"], "unique": false}
```

All ops are batched in a staging list visible in the **Pending Changes** strip
at the bottom of the canvas. Nothing runs until you click **Apply Changes**.

---

## 5. Setting Foreign Keys

To draw a FK graphically: hover over the source column row in a table node
until the drag handle appears, then drag to the target table. The designer
creates an `add_fk` op and renders an annotated edge on the canvas. The edge
label shows the constraint name (auto-generated as
`{table}_{column}_{ref_table}_fkey`; names longer than 63 characters get an
MD5 suffix).

You can also set a FK in the column editor dialog by entering
`other_table.column` in the **Foreign Key** field.

---

## 6. Applying Changes

Click **Apply Changes** in the toolbar. The designer POSTs the accumulated
`ops[]` array to `POST /erd-designer/api/schema/apply`. The server runs all
operations in a single transaction behind a `SET LOCAL statement_timeout =
30000` guard (tunable via `FAB_ERD_DDL_TIMEOUT_MS`):

1. Validates each identifier against `^[A-Za-z_][A-Za-z0-9_]{0,62}$`.
2. Validates each column type against the PostgreSQL type allow-list.
3. Executes DDL statements in dependency order.
4. On success, writes an `ErdMigrationLog` row in the same transaction.
5. On any error, rolls back the entire batch — the database is untouched.

A typical migration log entry stored in `erd_migration_log`:

```json
{
  "id": 42,
  "applied_at": "2026-06-01T09:14:07Z",
  "status": "success",
  "ops_json": [{"op": "create_table", "table": "projects", ...}],
  "sql_json": [
    "CREATE TABLE \"projects\" (\"id\" UUID PRIMARY KEY DEFAULT gen_random_uuid(), ...)",
    "ALTER TABLE \"projects\" ADD CONSTRAINT \"projects_owner_id_users_fkey\" FOREIGN KEY (\"owner_id\") REFERENCES \"users\" (\"id\")"
  ],
  "rollback_sql": ["DROP TABLE IF EXISTS \"projects\" CASCADE"]
}
```

**Before committing** you can preview without executing by appending
`?dry_run=1` to the apply URL, or by clicking **Preview SQL** in the toolbar.
The response includes `{"dry_run": true, "sql": [...], "would_apply": N}`.

**If you cancel mid-apply** (close the browser, network drops): the
transaction was not yet committed, so the database reverts automatically.
Partially-written log entries with `status = "error"` record the exception.

**Rolling back a successful migration** — navigate to
`GET /erd-designer/api/migration-log` or click **Migrations** in the sidebar
to see the last 50 log entries. Click **Rollback** on any entry that has
stored `rollback_sql` to execute the inverse DDL. Note: `drop_table`,
`rename_table`, `alter_column`, and `rename_column` have no safe deterministic
inverse and produce no rollback SQL.

---

## 7. Actor Pattern Detection

PgAppForge uses a `pgaf_actor` table comment to mark tables that participate
in the actor/role pattern (multi-user ownership, row-level audit trails,
etc.). Tables carrying this comment render on the canvas with an **amber
border** so they stand out visually.

To configure actor metadata for a table in the designer:

1. Select the table node.
2. In the right panel, open **Table Settings → Actor Config**.
3. Toggle **Is Actor Table** and optionally fill in `actor_id_column` and
   `tenant_column`.
4. Click **Save** — the designer issues a `COMMENT ON TABLE` statement setting
   `pgaf_actor` JSON on the table.

```sql
COMMENT ON TABLE "projects" IS '{"pgaf_actor": {"actor_id_column": "owner_id", "tenant_column": "org_id"}}';
```

On the next canvas reload the node renders with the amber border, and
codegen picks up the actor config when generating views.

---

## 8. Exporting to a Template

After designing a schema you want to reuse (for example, a standard
multi-tenant project structure), export it for future deployments.

Click **Export → Template JSON** in the toolbar. The download contains the
`canvas_json` and `schema_json` saved in the current design. To load it on
another deployment:

1. Open the ERD Designer on the target instance.
2. Click **Import Template JSON** and select the file.
3. Review the tables on the canvas.
4. Click **Apply Changes** to create the tables in the target database.

For team-wide reuse, register a custom ERP module so the template appears in
the left sidebar palette:

```python
from pgappforge.templates.registry import TemplateRegistry

TemplateRegistry.register("MYMODULE", {
    "label": "My Module",
    "tables": [
        {
            "name": "projects",
            "columns": [
                {"name": "id",     "type": "UUID",        "pk": True},
                {"name": "name",   "type": "VARCHAR(120)", "nullable": False},
                {"name": "status", "type": "VARCHAR(30)",  "nullable": False},
            ]
        }
    ]
})
```

Once registered, **My Module** appears in the sidebar under ERP Templates. Drag
it to the canvas and click **Apply** to create all tables via
`POST /erd-designer/api/apply-module/MYMODULE`.

---

## Summary

| Task | How |
|------|-----|
| Preview DDL before executing | Add `?dry_run=1` or click **Preview SQL** |
| View migration history | `/erd-designer/api/migration-log` or Migrations sidebar |
| Roll back a migration | **Rollback** button in migration log (where rollback SQL exists) |
| Read-only schema view | Register `ERDView` — mounts at `/erd/`, no DDL config needed |
| Disable DDL on production | `FAB_ERD_DDL_ENABLED = False` (default) |
| Tune DDL timeout | `FAB_ERD_DDL_TIMEOUT_MS = 10000` (milliseconds) |
