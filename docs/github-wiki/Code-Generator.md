# Code Generator

[Home](Home) > Code Generator

The `flask forge gen` family of commands introspects a live PostgreSQL database and emits ready-to-run source files. Only PostgreSQL URIs are accepted.

---

## Common Flags

All `gen` subcommands accept:

| Flag | Description |
|---|---|
| `--uri` | PostgreSQL connection URI (required). `postgresql://user:pass@host/db` |
| `--output-dir DIR` | Directory to write generated files (created if absent) |
| `--name NAME` | Application or module name used in generated identifiers |

---

## Commands

### `flask forge gen all`

Generates the full application: models, views, and API in one pass.

```bash
flask forge gen all \
  --uri postgresql://user:pass@localhost/mydb \
  --name "Warehouse" \
  --output-dir warehouse/
```

**Output structure:**

```
warehouse/
  app.py
  config.py
  models.py
  views.py
  api/
    __init__.py
  templates/
    index.html
```

---

### `flask forge gen model`

Generates SQLAlchemy model classes only.

```bash
flask forge gen model \
  --uri postgresql://user:pass@localhost/mydb \
  --output models.py
```

Each table becomes a `Model` subclass. Columns are mapped to their closest SQLAlchemy type. Foreign keys become `relationship()` declarations. Tables whose comment JSON contains `pgaf_actor` are annotated with `ActorMixin`.

---

### `flask forge gen view`

Generates `ModelView` subclasses for every model.

```bash
flask forge gen view \
  --uri postgresql://user:pass@localhost/mydb \
  --output-dir views/
```

Each view includes `list_columns`, `add_columns`, `edit_columns`, `show_columns`, and `search_columns` populated from the introspected column set. Actor-aware tables get human-readable labels substituted for raw field names.

---

### `flask forge gen api`

Generates `ModelRestApi` subclasses and OpenAPI spec stubs.

```bash
flask forge gen api \
  --uri postgresql://user:pass@localhost/mydb \
  --output-dir api/
```

Each table gets a REST endpoint at `/api/v1/<tablename>/` with `GET`, `POST`, `PUT`, `DELETE` and OpenAPI/Swagger documentation auto-generated.

---

### `flask forge gen mobile`

Generates React Native screen components for every table.

```bash
flask forge gen mobile \
  --uri postgresql://user:pass@localhost/mydb \
  --output-dir mobile/screens/
```

Each table produces a list screen, detail screen, and form screen. Screens use the generated REST API as their data source.

---

### `flask forge gen desktop`

Generates an Electron or Tauri application shell.

```bash
flask forge gen desktop \
  --uri postgresql://user:pass@localhost/mydb \
  --output-dir desktop/
```

Wraps the generated web app in a native desktop window with menu bar navigation derived from the view structure.

---

## Template Commands

See [Schema Templates](Schema-Templates) for the full `flask forge templates` reference.

---

## See also

- [Quick Start](Quick-Start)
- [Architecture](Architecture)
- [Schema Templates](Schema-Templates)
- [CLI Reference](../api/cli.md)
