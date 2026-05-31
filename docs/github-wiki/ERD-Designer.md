# ERD Designer

[Home](Home) > ERD Designer

The ERD Designer is a Cytoscape.js-powered visual schema editor embedded in pgappforge. It provides a live canvas for creating and modifying PostgreSQL schemas, executing DDL, tracking migrations, and generating application code — all from the browser.

---

## Accessing the Designer

Register the view in your app factory:

```python
from pgappforge.views.erd_designer import ERDDesignerView

appbuilder.add_view(
    ERDDesignerView,
    "ERD Designer",
    icon="fa-sitemap",
    category="Tools",
)
```

Navigate to `/erd-designer/`. Requires Admin role.

For a **read-only** live ERD (Mermaid diagram, no editing):

```python
from pgappforge.views.erd_view import ERDView

appbuilder.add_view(ERDView, "Live ERD", icon="fa-project-diagram", category="Tools")
```

Mounts at `/erd/`.

---

## Enabling DDL Mutations

Schema mutations (CREATE TABLE, ALTER TABLE, DROP) are **disabled by default** and return HTTP 403 until you opt in:

```python
# config.py
FAB_ERD_DDL_ENABLED = True
FAB_ERD_DDL_TIMEOUT_MS = 30000   # statement_timeout per DDL batch, ms
```

Only users with the **Admin** role can call mutating endpoints once enabled.

---

## Creating Tables

1. Click **+ Table** in the toolbar.
2. Enter a table name (snake\_case recommended).
3. Add columns via the column editor panel — choose name, type, nullable, default.
4. Click **Apply DDL** to execute `CREATE TABLE` against the live database.

The `erd_design` table persists the canvas state. `erd_migration_log` records every executed DDL statement with timestamp, actor, and SQL text.

---

## Adding Columns

Select an existing table node on the canvas. The right panel shows current columns. Click **+ Column**, fill in name/type/constraints, then **Apply**. This executes `ALTER TABLE ... ADD COLUMN`.

---

## Setting Foreign Keys

Drag from the source column chip to the target table. A directed edge (FK arrow) appears. Click **Apply DDL** to create the constraint.

---

## Actor Pattern Detection

If a table's PostgreSQL comment contains a `pgaf_actor` JSON fragment, the designer renders that table with a distinct actor icon and substitutes canonical field labels (e.g. "Patient Name" instead of "full_name"). See [Actor Pattern](Actor-Pattern).

---

## Migrations

Every DDL batch is logged in `erd_migration_log`:

| Column | Description |
|---|---|
| `id` | UUID primary key |
| `executed_at` | Timestamp |
| `actor_id` | User who triggered the migration |
| `ddl_text` | Full SQL executed |
| `success` | Boolean |
| `error_message` | Set on failure |

---

## Configuration Reference

| Key | Default | Description |
|---|---|---|
| `FAB_ERD_DDL_ENABLED` | `False` | Enable schema-mutation endpoints |
| `FAB_ERD_DDL_TIMEOUT_MS` | `30000` | `SET LOCAL statement_timeout` per DDL batch (ms) |
| `FAB_CODEGEN_OUTPUT_ROOT` | `"/tmp/pgaf_generated"` | Root for app-generation output; paths outside this root are rejected |

---

## Further Reading

Full technical reference: [docs/ERD_DESIGNER.md](../ERD_DESIGNER.md)

---

## See also

- [Architecture](Architecture)
- [Code Generator](Code-Generator)
- [Security Designer](Security-Designer)
- [Actor Pattern](Actor-Pattern)
- [Configuration Reference](../api/configuration.md)
