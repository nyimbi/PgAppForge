# CLI Reference

All pgappforge CLI commands are invoked via `flask forge`. Set `FLASK_APP` to your application module before running.

```bash
export FLASK_APP=app.py
```

---

## Code Generation

### `flask forge gen all`

Generate a complete application (models + views + API) from a live PostgreSQL schema.

**Flags:**

| Flag | Required | Description |
|---|---|---|
| `--uri URI` | Yes | PostgreSQL connection URI (`postgresql://user:pass@host/db`) |
| `--name NAME` | No | Application name used in generated class names and titles |
| `--output-dir DIR` | No | Output directory (created if absent; default: `./generated`) |

**Example:**

```bash
flask forge gen all \
  --uri postgresql://user:pass@localhost/mydb \
  --name "Warehouse" \
  --output-dir warehouse/
```

**Output:**

```
warehouse/app.py
warehouse/config.py
warehouse/models.py
warehouse/views.py
warehouse/api/__init__.py
```

---

### `flask forge gen model`

Generate SQLAlchemy model classes only.

**Flags:**

| Flag | Required | Description |
|---|---|---|
| `--uri URI` | Yes | PostgreSQL connection URI |
| `--output FILE` | No | Output file path (default: `models.py`) |

**Example:**

```bash
flask forge gen model \
  --uri postgresql://user:pass@localhost/mydb \
  --output myapp/models.py
```

---

### `flask forge gen view`

Generate `ModelView` subclasses for every model.

**Flags:**

| Flag | Required | Description |
|---|---|---|
| `--uri URI` | Yes | PostgreSQL connection URI |
| `--output-dir DIR` | No | Output directory (default: `views/`) |

**Example:**

```bash
flask forge gen view \
  --uri postgresql://user:pass@localhost/mydb \
  --output-dir myapp/views/
```

---

### `flask forge gen mobile`

Generate React Native screen components (list, detail, form) for every table.

**Flags:**

| Flag | Required | Description |
|---|---|---|
| `--uri URI` | Yes | PostgreSQL connection URI |
| `--output-dir DIR` | No | Output directory (default: `mobile/screens/`) |

**Example:**

```bash
flask forge gen mobile \
  --uri postgresql://user:pass@localhost/mydb \
  --output-dir mobile/screens/
```

---

### `flask forge gen desktop`

Generate an Electron or Tauri application shell wrapping the generated web app.

**Flags:**

| Flag | Required | Description |
|---|---|---|
| `--uri URI` | Yes | PostgreSQL connection URI |
| `--output-dir DIR` | No | Output directory (default: `desktop/`) |

**Example:**

```bash
flask forge gen desktop \
  --uri postgresql://user:pass@localhost/mydb \
  --output-dir desktop/
```

---

## Template Management

### `flask forge templates list`

List all available schema templates.

**Flags:**

| Flag | Description |
|---|---|
| `--tag TAG` / `-t TAG` | Filter templates by tag (e.g. `healthcare`, `finance`, `iot`) |

**Example:**

```bash
flask forge templates list
flask forge templates list --tag healthcare
```

**Output columns:** NAME, SCHEMA, TABLES, SOURCE, TAGS

---

### `flask forge templates info NAME`

Show detailed information about a named template: label, version, description, source URL, tags, PostgreSQL extensions required, and a table/column summary.

**Example:**

```bash
flask forge templates info fhir-r4
flask forge templates info ecommerce
```

---

### `flask forge templates apply NAME`

Apply a template to the current database, creating all declared tables in the target schema.

**Flags:**

| Flag | Description |
|---|---|
| `--schema SCHEMA` | PostgreSQL schema to create tables in (default: template's own schema name) |

**Example:**

```bash
flask forge templates apply fhir-r4
flask forge templates apply fhir-r4 --schema clinical
flask forge templates apply ecommerce --schema store
```

Note: requires `FAB_ERD_DDL_ENABLED = True` or a direct database connection with DDL rights.

---

### `flask forge templates import NAME_OR_URL`

Import a named template from the pgappforge online registry, or from a custom URL.

**Flags:**

| Flag | Description |
|---|---|
| `--url URL` | Custom URL to fetch the template JSON from instead of the default registry |

**Example:**

```bash
# Import a known built-in template by name
flask forge templates import fhir-r4

# Import from a custom URL
flask forge templates import my-template \
  --url https://example.com/templates/my-template.json
```

---

### `flask forge templates export NAME`

Export a template definition to JSON.

**Flags:**

| Flag | Description |
|---|---|
| `--output FILE` / `-o FILE` | Output file path (default: `<NAME>.json` in the current directory) |

**Example:**

```bash
flask forge templates export fhir-r4
flask forge templates export fhir-r4 --output backup/fhir-r4.json
```

---

### `flask forge templates remove NAME`

Remove a user-installed template. Bundled templates cannot be removed.

**Example:**

```bash
flask forge templates remove my-custom-template
```

Raises an error if the template is bundled or not found in the user templates directory.
