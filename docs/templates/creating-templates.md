# Creating Your Own Templates

A template is a JSON file you write once and reuse across projects, teams, and databases. This guide covers the complete JSON format, all column descriptor fields, how to install locally, and how to share via GitHub.

## Complete JSON Format Reference

```json
{
  "name": "blog",
  "schema": "blog",
  "label": "Blog",
  "description": "Minimal blogging schema — posts, authors, categories, and comments.",
  "color": "#3498db",
  "icon": "fa-pencil-alt",
  "version": "1.0.0",
  "source_url": "https://github.com/yourorg/blog-template",
  "tags": ["cms", "publishing"],
  "extensions": [],

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
      "display_name": "full_name",
      "external_ids": {
        "username": "username"
      }
    },
    "related_collections": ["blog_post", "blog_comment"],
    "tags": ["cms"]
  },

  "table_notes": {
    "blog_post": "One row per published article. slug must be globally unique."
  },

  "tables": {
    "blog_author": [
      {"name": "id",         "type": "UUID",         "pk": true,  "default": "gen_random_uuid()", "description": "Surrogate PK"},
      {"name": "full_name",  "type": "VARCHAR(200)",  "nullable": false,  "description": "Display name"},
      {"name": "username",   "type": "VARCHAR(60)",   "unique": true, "nullable": false},
      {"name": "email",      "type": "VARCHAR(320)",  "unique": true, "nullable": false},
      {"name": "bio",        "type": "TEXT",          "nullable": true},
      {"name": "avatar_url", "type": "VARCHAR(2048)", "nullable": true},
      {"name": "created_at", "type": "TIMESTAMPTZ",   "default": "now()", "nullable": false}
    ],
    "blog_category": [
      {"name": "id",        "type": "UUID",         "pk": true, "default": "gen_random_uuid()"},
      {"name": "name",      "type": "VARCHAR(100)",  "unique": true, "nullable": false},
      {"name": "slug",      "type": "VARCHAR(110)",  "unique": true, "nullable": false},
      {"name": "parent_id", "type": "UUID",          "fk": "blog_category.id", "nullable": true, "index": true,
       "description": "Self-referential FK for nested categories"}
    ],
    "blog_post": [
      {"name": "id",           "type": "UUID",         "pk": true, "default": "gen_random_uuid()"},
      {"name": "author_id",    "type": "UUID",         "fk": "blog_author.id", "nullable": false, "index": true},
      {"name": "category_id",  "type": "UUID",         "fk": "blog_category.id", "nullable": true, "index": true},
      {"name": "title",        "type": "VARCHAR(400)",  "nullable": false},
      {"name": "slug",         "type": "VARCHAR(420)",  "unique": true, "nullable": false},
      {"name": "body",         "type": "TEXT",          "nullable": true},
      {"name": "word_count",   "type": "INTEGER",       "default": "0", "nullable": false},
      {"name": "status",       "type": "VARCHAR(20)",   "default": "'DRAFT'", "nullable": false,
       "check": "status IN ('DRAFT','PUBLISHED','ARCHIVED')"},
      {"name": "published_at", "type": "TIMESTAMPTZ",  "nullable": true},
      {"name": "created_at",   "type": "TIMESTAMPTZ",  "default": "now()", "nullable": false}
    ],
    "blog_comment": [
      {"name": "id",         "type": "UUID",    "pk": true, "default": "gen_random_uuid()"},
      {"name": "post_id",    "type": "UUID",    "fk": "blog_post.id", "nullable": false, "index": true},
      {"name": "author_id",  "type": "UUID",    "fk": "blog_author.id", "nullable": true, "index": true},
      {"name": "body",       "type": "TEXT",    "nullable": false},
      {"name": "is_approved","type": "BOOLEAN", "default": "false", "nullable": false},
      {"name": "created_at", "type": "TIMESTAMPTZ", "default": "now()", "nullable": false}
    ]
  }
}
```

## Top-Level Field Reference

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | Machine identifier. Must be unique across all sources. Use lowercase with hyphens. |
| `schema` | string | no | PostgreSQL schema name. Defaults to `name` with `-` replaced by `_`. |
| `label` | string | yes | Human-readable display name shown in the UI and CLI. |
| `description` | string | no | One paragraph summary. Shown by `flask forge templates info <name>`. |
| `color` | string | no | Hex colour string. Used in the ERD Designer module legend. Defaults to `#3498db`. |
| `icon` | string | no | FontAwesome 5 class, e.g. `fa-pencil-alt`, `fa-heartbeat`, `fa-truck`. Defaults to `fa-database`. |
| `version` | string | no | SemVer string. Informational only — not parsed by the registry. |
| `source_url` | string | no | URL to the upstream standard, spec, or repository this schema is derived from. |
| `tags` | list[str] | no | Used for `--tag` filtering and domain classification in the ERD Designer. See the tag → domain map in `registry.py`. |
| `extensions` | list[str] | no | PostgreSQL extensions to `CREATE EXTENSION IF NOT EXISTS` before table creation. E.g. `["uuid-ossp", "postgis"]`. |
| `actor` | object | no | Declares the primary business entity (see Actor Reference below). |
| `actors` | list[object] | no | Array form for templates with multiple actor roles. Use `"primary": true` to mark the main one. |
| `table_notes` | object | no | Map of `table_name → "human readable note"`. Shown in `templates info`. Not written to the database. |
| `tables` | object | yes | Map of `table_name → [column_descriptor, …]`. Tables are created in iteration order. |

## Column Descriptor Reference

Every column descriptor is a JSON object in the columns array for a table.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | string | — | Column name. Required. Use `snake_case`. |
| `type` | string | `"TEXT"` | PostgreSQL type string. Any valid PG type is accepted: `UUID`, `VARCHAR(n)`, `TEXT`, `INTEGER`, `BIGINT`, `BOOLEAN`, `NUMERIC(p,s)`, `TIMESTAMPTZ`, `DATE`, `TIME`, `JSONB`, `JSON`, `BYTEA`, `INET`, `CIDR`, `MACADDR`, `LTREE`, `TSVECTOR`, `INT4RANGE`, `INT8RANGE`, `NUMRANGE`, `TSTZRANGE`, `DATERANGE`, array types (`TEXT[]`, `UUID[]`). |
| `pk` | bool | `false` | `true` → `PRIMARY KEY`. Use on exactly one column per table. |
| `nullable` | bool | `true` | `false` → `NOT NULL` constraint. |
| `unique` | bool | `false` | `true` → `UNIQUE` constraint. |
| `index` | bool | `false` | `true` → `CREATE INDEX` on this column (non-unique). Set on FK columns and frequently-filtered columns. |
| `fk` | string | — | Foreign key target as `"table.column"`. The referenced table must exist before this table is created — ensure correct ordering in the `tables` map. Self-referential FKs are supported. |
| `default` | string | — | SQL default expression. Written verbatim into DDL. Examples: `"gen_random_uuid()"`, `"now()"`, `"0"`, `"'DRAFT'"` (note the extra quotes for string literals), `"true"`. |
| `check` | string | — | CHECK constraint expression. Written verbatim. Example: `"amount >= 0"`, `"status IN ('DRAFT','PUBLISHED')"`. |
| `description` | string | — | Written as a `COMMENT ON COLUMN` statement after table creation. Also shown in `templates info`. |

## Actor Field Reference

The `actor` (or each element of `actors`) describes the primary business entity the template revolves around. It drives the actor-pattern views and search in the generated app.

| Field | Type | Notes |
|-------|------|-------|
| `role` | string | Semantic role, e.g. `"customer"`, `"patient"`, `"employee"`. |
| `table` | string | The table that represents this actor. |
| `primary` | bool | `true` in the array form to mark the primary actor. Ignored in the singular `actor` form. |
| `display.singular` | string | Singular display name shown in UI labels. |
| `display.plural` | string | Plural display name for list headings. |
| `display.icon` | string | FontAwesome class for actor-list icons. |
| `field_map.display_name` | string | Column name to use as the entity's display label in search results and FK pickers. |
| `field_map.external_ids` | object | Map of `logical_name → column_name` for alternate identifier columns. |
| `related_collections` | list[str] | Tables shown as sub-panels in the actor detail view. |
| `tags` | list[str] | Actor-level tags, used for actor registry classification. |

## How to Install a Template

**From a local file** — installs to `~/.pgappforge/templates/` (shared across all projects on this machine):

```bash
flask forge templates install ~/Downloads/blog.json
```

Verify:

```bash
flask forge templates list
flask forge templates info blog
```

**Project-local** — copy the JSON file to `.pgappforge/templates/` in your project root. It takes highest priority (overrides bundled and user-installed templates with the same name) and is committed to version control with the project:

```bash
mkdir -p .pgappforge/templates/
cp ~/Downloads/blog.json .pgappforge/templates/
flask forge templates list  # blog appears with source "user"
```

**From a URL** (once the registry is published):

```bash
flask forge templates import blog \
  --url https://raw.githubusercontent.com/yourorg/templates/main/blog.json
```

## Sharing Templates via GitHub

1. Create a public repository (e.g. `yourorg/pgappforge-templates`)
2. Add your template JSON files at the root or in a `templates/` directory
3. Share the raw URL:

   ```
   https://raw.githubusercontent.com/yourorg/pgappforge-templates/main/blog.json
   ```

4. Anyone can import it:

   ```bash
   flask forge templates import blog \
     --url https://raw.githubusercontent.com/yourorg/pgappforge-templates/main/blog.json
   ```

For discoverability, add the GitHub topic `pgappforge-template` to your repository.

## Exporting an Existing Template

Export any registered template to JSON for editing or sharing:

```bash
# Print to stdout
flask forge templates export ar

# Write to a file
flask forge templates export ar --output ar-v1.1.0.json
```

This is the fastest way to start a new template based on an existing one: export the closest match, rename, edit, and install.

## Validation Tips

The registry loads templates with a lenient parser — it does not enforce a JSON Schema. Common mistakes:

- **Wrong `fk` target**: the referenced table must appear before the referencing table in the `tables` map, or the `CREATE TABLE` will fail with a missing-table error. Re-order or use `--dry-run` to check.
- **String literal defaults**: SQL string defaults need nested quotes: `"default": "'DRAFT'"` not `"default": "DRAFT"`.
- **Missing `nullable: false` on required columns**: omitting it allows NULLs even if the column semantically should not permit them.
- **Duplicate `name`**: if two templates have the same `name`, the later source (project > user > bundled) wins silently. Check with `flask forge templates info <name>` to see which file was loaded.

Use `--dry-run` to print the generated DDL and catch errors before touching the database:

```bash
flask forge templates apply blog \
  --database-uri postgresql://localhost/testdb \
  --dry-run
```
