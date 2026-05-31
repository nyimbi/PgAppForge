# Template System Overview

Templates are JSON documents that describe a database schema — tables, columns, types, constraints, and relationships — in a format that pgappforge can apply directly to PostgreSQL, introspect into the ERD Designer, and use to scaffold a complete application. They eliminate the blank-slate problem: instead of designing a schema from scratch you select an industry-standard template and customise it.

## What a Template Is

A template is a single `.json` file with a fixed top-level structure. It carries:

- **Identity metadata** — name, label, description, version, tags, icon, colour
- **Actor config** — the primary business entity the template revolves around (customer, patient, employee, …)
- **Table map** — every table, with ordered column descriptors that encode type, constraints, defaults, and FK references

The column descriptors map directly to PostgreSQL DDL. When you apply a template, pgappforge:

1. Creates a dedicated schema (`ar`, `crm`, `hrm`, …)
2. Issues `CREATE TABLE IF NOT EXISTS` for each table in the descriptor order
3. Wires FK constraints, indexes, and check constraints from the column metadata

Nothing is destructive. Existing tables are left untouched.

## Three Template Sources

Templates are discovered from three directory locations, scanned in this order (later sources win on name conflicts):

| Priority | Location | Purpose |
|----------|----------|---------|
| 1 (lowest) | `pgappforge/templates/bundled/` | Shipped with the package; read-only |
| 2 | `~/.pgappforge/templates/` | User-installed; shared across all projects |
| 3 (highest) | `.pgappforge/templates/` | Project-local; committed to version control |

The `TemplateRegistry` scans lazily on first access and caches results in memory. Call `registry.refresh()` to pick up files added after construction.

## CLI: Managing Templates

All template operations go through `flask forge templates`:

```bash
# List every available template
flask forge templates list

# Filter by tag
flask forge templates list --tag finance

# Show details for one template (tables, columns, source URL)
flask forge templates info ar

# Apply a template's tables to a PostgreSQL database
flask forge templates apply crm --database-uri postgresql://localhost/mydb

# Preview the SQL without executing it
flask forge templates apply fhir-r4 --database-uri postgresql://localhost/mydb --dry-run

# Install a template from a local JSON file
flask forge templates install ~/Downloads/blog.json

# Import a template from the pgappforge GitHub registry (or a custom URL)
flask forge templates import my-template
flask forge templates import my-template --url https://example.com/my-template.json

# Export a template to JSON (stdout or file)
flask forge templates export ar
flask forge templates export ar --output ar-backup.json

# Remove a user-installed template (bundled templates cannot be removed)
flask forge templates remove my-template

# Load reference data for terminology templates (SNOMED CT, LOINC, etc.)
flask forge templates install-data snomed-ct --database-uri postgresql://localhost/mydb --data-dir ~/Downloads/SnomedCT/
```

## Template JSON Format — Annotated Example

```json
{
  "name": "blog",
  "schema": "blog",
  "label": "Blog",
  "description": "Minimal blogging schema — posts, authors, categories, comments.",
  "color": "#3498db",
  "icon": "fa-pencil-alt",
  "version": "1.0.0",
  "source_url": "https://github.com/example/blog-template",
  "tags": ["cms", "publishing"],

  "actor": {
    "role": "author",
    "table": "blog_author",
    "primary": true,
    "display": {
      "singular": "Author",
      "plural": "Authors",
      "icon": "fa-user-edit"
    },
    "field_map": {
      "display_name": "full_name"
    },
    "related_collections": ["blog_post", "blog_comment"],
    "tags": ["cms"]
  },

  "tables": {
    "blog_author": [
      {"name": "id",         "type": "UUID",         "pk": true, "default": "gen_random_uuid()"},
      {"name": "full_name",  "type": "VARCHAR(200)",  "nullable": false},
      {"name": "email",      "type": "VARCHAR(320)",  "unique": true, "nullable": false},
      {"name": "bio",        "type": "TEXT",          "nullable": true},
      {"name": "created_at", "type": "TIMESTAMPTZ",   "default": "now()", "nullable": false}
    ],
    "blog_post": [
      {"name": "id",          "type": "UUID",        "pk": true, "default": "gen_random_uuid()"},
      {"name": "author_id",   "type": "UUID",        "fk": "blog_author.id", "nullable": false, "index": true},
      {"name": "title",       "type": "VARCHAR(400)", "nullable": false},
      {"name": "slug",        "type": "VARCHAR(420)", "unique": true, "nullable": false},
      {"name": "body",        "type": "TEXT",         "nullable": true},
      {"name": "published_at","type": "TIMESTAMPTZ",  "nullable": true},
      {"name": "created_at",  "type": "TIMESTAMPTZ",  "default": "now()", "nullable": false}
    ]
  }
}
```

### Top-level fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | Machine identifier; must be unique across sources |
| `schema` | string | no | PostgreSQL schema name; defaults to `name` with `-` → `_` |
| `label` | string | yes | Human-readable display name |
| `description` | string | no | One-paragraph summary shown in `templates info` |
| `color` | string | no | Hex colour used in the ERD Designer module legend |
| `icon` | string | no | FontAwesome class (e.g. `fa-heartbeat`) |
| `version` | string | no | SemVer string; informational only |
| `source_url` | string | no | URL to the upstream standard or repository |
| `tags` | list[str] | no | Used for `list --tag` filtering and domain classification |
| `actor` | object | no | Primary business-entity declaration (see below) |
| `actors` | list[object] | no | Alternative array form when multiple actors are declared |
| `extensions` | list[str] | no | PostgreSQL extensions to `CREATE EXTENSION IF NOT EXISTS` before apply |
| `tables` | object | yes | Map of `table_name → [column_descriptor, …]` |

### Actor fields

| Field | Notes |
|-------|-------|
| `role` | Semantic role name (e.g. `"customer"`, `"patient"`) |
| `table` | Table that represents this actor |
| `primary` | `true` marks the primary actor when using the array `actors` form |
| `display.singular/plural/icon` | UI display hints |
| `field_map.display_name` | Column to use as the entity's display label |
| `related_collections` | Tables that belong to this actor (shown in actor detail views) |

### Column descriptor fields

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Column name (required) |
| `type` | string | PostgreSQL type string, e.g. `UUID`, `VARCHAR(255)`, `TIMESTAMPTZ`, `JSONB`, `NUMERIC(18,4)` |
| `pk` | bool | `true` → PRIMARY KEY |
| `nullable` | bool | `false` → NOT NULL (defaults to `true`) |
| `unique` | bool | `true` → UNIQUE constraint |
| `index` | bool | `true` → CREATE INDEX |
| `fk` | string | Foreign key target, e.g. `"other_table.id"` |
| `default` | string | SQL default expression, e.g. `"gen_random_uuid()"`, `"now()"`, `"0"` |
| `check` | string | CHECK constraint expression, e.g. `"amount >= 0"` |
| `description` | string | Column-level comment (written as `COMMENT ON COLUMN`) |

## Integration with the ERD Designer

When the ERD Designer loads it calls `TemplateRegistry.load_all()` and makes every template available as a module in the domain panel. Clicking a template in the UI:

1. Renders its tables and relationships in the visual canvas
2. Lets you drag individual tables into your working schema
3. Lets you apply the full template to your connected database via the Apply button (equivalent to `flask forge templates apply`)

Templates are classified into domain groups (Finance & Banking, Healthcare & Life Sciences, HR & Education, …) by tag matching. The ERD Designer's left-side domain panel uses these groups to organise the template library.

## TemplateRegistry Python API

```python
from pgappforge.templates import TemplateRegistry, TemplateNotFoundError

registry = TemplateRegistry()

# List all available templates (returns list of metadata dicts)
for t in registry.list():
    print(t["name"], t["label"], t["table_count"], "tables", t["source"])

# Get a single template's full definition
ar = registry.get("ar")
print(list(ar["tables"].keys()))
# ['ar_customer', 'ar_invoice', 'ar_invoice_line', ...]

# Get all templates in ERD-Designer-compatible format
modules = registry.load_all()
# {"ar": {"label": "Accounts Receivable", "color": ..., "tables": {...}}, ...}

# Group by domain (for UI panels)
domains = registry.load_by_domain()
# {"Finance & Banking": [...], "HR & Education": [...], ...}

# Install from a local file (writes to ~/.pgappforge/templates/)
name = registry.install_from_file("/path/to/blog.json")

# Install from a dict
name = registry.install_from_dict({"name": "blog", "label": "Blog", "tables": {...}})

# Remove a user-installed template
registry.remove("blog")

# Force rescan after adding files on disk
registry.refresh()

# Actor helpers
actor = registry.get_actor_config("ar")       # primary ActorConfig
actors = registry.get_template_actors("crm")  # all ActorConfig objects
registry.register_actors()                    # register all actors at app startup
```

`TemplateNotFoundError` is raised by `get()` when the requested name is not in any of the three source directories. The error message lists available template names to aid typo correction.
