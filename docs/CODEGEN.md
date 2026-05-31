# Code Generation (`flask fab gen`)

## Overview

pgappforge can generate complete Flask web apps, React Native mobile apps, and
Electron/PyWebView desktop app shells directly from your PostgreSQL schema. The
generators introspect your live database, derive model structure, relationships,
and column types, then emit production-ready code with security defaults applied.

All generators share the same introspection pipeline (`EnhancedDatabaseInspector`)
and write files atomically through `GenerationTransaction` — either every file lands
or none do, with full rollback on error.

---

## Quick Start

### Flask Web App

```bash
flask fab gen app \
  --uri postgresql://user:pass@localhost/mydb \
  --name MyApp \
  --output ./my-app

cd my-app
cp .env.example .env        # edit credentials before proceeding
python scripts/init_db.py   # creates admin user, prints generated password
flask run
```

### React Native Mobile App

```bash
flask fab gen mobile \
  --uri postgresql://user:pass@localhost/mydb \
  --name MyApp \
  --api-url https://api.myapp.com \
  --output ./my-mobile

cd my-mobile
npm install
npx expo start
```

### Desktop App (PyWebView / PySide6)

```bash
flask fab gen desktop \
  --name MyApp \
  --backend-url http://localhost:8080 \
  --output ./my-desktop

cd my-desktop
make setup
make run
```

### All Platforms in One Pass

```bash
flask fab gen all \
  --uri postgresql://user:pass@localhost/mydb \
  --name MyApp \
  --output ./my-project
```

---

## Subcommand Reference

| Command | Produces | Key Options |
|---------|----------|-------------|
| `gen model` | SQLAlchemy models + Pydantic schemas | `--uri`, `--output` |
| `gen view` | FAB `ModelView` classes + charts + master-detail | `--uri`, `--theme` |
| `gen app` | Complete Flask web application | `--uri`, `--name`, `--output` |
| `gen api` | REST API `ModelRestApi` classes | `--uri`, `--output` |
| `gen mobile` | React Native / Expo mobile app | `--uri`, `--api-url`, `--features` |
| `gen desktop` | PyWebView / PySide6 desktop wrapper | `--name`, `--backend-url` |
| `gen all` | All platforms | `--uri`, `--name`, `--platforms` |
| `gen inspect` | Schema analysis report (JSON or text) | `--uri` |

Run `flask fab gen <subcommand> --help` for the full option list of any subcommand.

---

## Configuration

Application-level settings (set in `config.py` or environment):

| Key | Default | Description |
|-----|---------|-------------|
| `FAB_CODEGEN_OUTPUT_ROOT` | `/tmp/pgaf_generated` | Sandbox root for ERD-driven generation |
| `FAB_CODEGEN_CUSTOM_TEMPLATES` | `None` | Directory of `.py.j2` template overrides |
| `FAB_CODEGEN_PRESERVE_CUSTOM` | `True` | Keep `app/custom/` across re-runs |

---

## Plugin Auto-Detection

The mobile generator inspects your schema and conditionally emits plugin scaffolding.
No flags are required — presence of specific tables or columns triggers generation:

| Plugin | Trigger | Generated Artifacts |
|--------|---------|---------------------|
| `bpm` | Tables prefixed `bpm_` | BPM workflow screens, task list, step transitions |
| `approval` | Tables prefixed `approval_` | Approval action buttons, status badge component |
| `icd10` | Table named `icd10_code` | ICD-10 search picker field with typeahead |
| `snomed` | Table named `snomed_concept` | SNOMED CT search picker with hierarchy browser |
| `wallet` | Tables prefixed `wallet_` | Wallet balance card, transaction list, top-up flow |
| `offline` | Columns: `updated_at`, `deleted_at`, or `synced_at` | WatermelonDB sync infrastructure, conflict resolver |
| `voice` | Pass `--features voice` | TTS hook, microphone input button, transcript display |

To explicitly include or exclude plugins:

```bash
flask fab gen mobile \
  --uri postgresql://... \
  --features wallet,offline \
  --exclude-features bpm
```

---

## Generated App Structure

### Flask Web App (`gen app`)

```
my-app/
├── app/
│   ├── generated/          # Overwritten on each gen run
│   │   ├── models.py
│   │   ├── views.py
│   │   └── api.py
│   ├── custom/             # Your code — preserved across re-runs
│   │   └── .gitkeep
│   ├── __init__.py
│   └── config.py
├── scripts/
│   └── init_db.py
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

### React Native App (`gen mobile`)

```
my-mobile/
├── src/
│   ├── screens/            # One screen per database table
│   ├── components/         # Shared field widgets
│   ├── api/                # Generated API client
│   └── plugins/            # Auto-detected plugin modules
├── app.json
├── package.json
└── tsconfig.json
```

### Desktop App (`gen desktop`)

```
my-desktop/
├── main.py                 # PyWebView entry point
├── assets/
├── Makefile
└── requirements.txt
```

---

## Naming Conventions

All generators use the centralized helpers in `pgappforge.cli.generators._naming`:

| Function | Input | Output |
|----------|-------|--------|
| `pascal(s)` | `user_account` | `UserAccount` |
| `camel(s)` | `user_account` | `userAccount` |
| `kebab(s)` | `user_account` | `user-account` |
| `snake(s)` | `UserAccount` | `user_account` |
| `label(s)` | `user_account` | `User Account` |

These are exposed at package level as `pgappforge.cli.generators._naming`.

---

## Programmatic Use

Generators can be driven from Python without the CLI:

```python
from pathlib import Path
from pgappforge.cli.generators import (
    FullAppGenerator,
    AppGenerationConfig,
    ModelGenerationConfig,
    EnhancedModelGenerator,
    _naming as naming,
)

# Generate models only
model_cfg = ModelGenerationConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    output_dir=Path("./generated"),
)
gen = EnhancedModelGenerator(model_cfg)
gen.write()

# Generate full app
app_cfg = AppGenerationConfig(
    database_url="postgresql://user:pass@localhost/mydb",
    app_name="MyApp",
    output_dir=Path("./my-app"),
)
FullAppGenerator(app_cfg).write()

# Naming utilities
print(naming.pascal("invoice_line_item"))  # InvoiceLineItem
print(naming.camel("invoice_line_item"))   # invoiceLineItem
```

### Extending with a Custom Generator

Subclass `BaseGenerator` to plug into the same atomic-write and disk-space-check
infrastructure:

```python
from pathlib import Path
from pgappforge.cli.generators._base import BaseGenerator

class MyReportGenerator(BaseGenerator):
    def __init__(self, tables: list[str], output_dir: Path) -> None:
        self.tables = tables
        self.output_dir = output_dir

    def render(self) -> dict[str, str]:
        return {
            "report.txt": "\n".join(self.tables),
        }

MyReportGenerator(["users", "orders"], Path("/tmp/out")).write()
```

`render()` must be pure — return a `{relative_path: content}` dict without touching
disk. `write()` handles disk-space validation, path-traversal protection, and atomic
commit via `GenerationTransaction`.

---

## Security Requirements

Before deploying any generated application, operators **must**:

1. Set `SECRET_KEY` to a random string of at least 20 characters — never leave the
   generated placeholder in place.
2. Set `CORS_ALLOWED_ORIGINS` to your actual domain — never `*` in production.
3. Set `ADMIN_PASSWORD` or retrieve the auto-generated password printed by
   `python scripts/init_db.py` and rotate it immediately.
4. Enable HTTPS and set `POSTGRES_PASSWORD` via environment variable, not in
   committed config files.
5. Review `docker-compose.yml` and remove any hardcoded credentials before committing.
6. Run `flask fab security-check` to confirm no default credentials remain active.

---

## Template Customization

Pass `--custom-templates /path/to/templates` to override individual Jinja2 templates.
The directory must contain `.py.j2` files whose names match the built-in template names
(inspect `pgappforge/cli/generators/code_templates.py` for the full list).

Only the templates you provide are overridden — the rest fall back to built-ins.

```bash
flask fab gen app \
  --uri postgresql://... \
  --name MyApp \
  --custom-templates ./my-templates \
  --output ./my-app
```

---

## Re-running the Generator

The generator is designed to be idempotent:

- Files under `app/generated/` (and the equivalent in mobile/desktop targets) are
  **always overwritten**.
- Files under `app/custom/` are **never touched** — this is where you put business
  logic, custom validators, and override hooks.
- Database migrations are **not** re-run automatically; use `flask db migrate` after
  re-generation if your schema changed.

Always commit or stash your working tree before re-running — `GenerationTransaction`
rolls back on error, but having a clean git state makes recovery trivial.

---

## Troubleshooting

### `OSError: Insufficient disk space`

The generator pre-checks that at least `(estimated output size × 2) + 50 MB` is
available before writing anything. Free space in the output directory and retry.

### `FileOperationError: Insecure path rejected`

A rendered file path contained `..` or an absolute component. This is a bug in a
custom generator or template — `render()` must return relative paths only.

### `PathTraversalError` from `SecurePathValidator`

Same root cause as above. All paths are validated against the output root before any
disk I/O occurs.

### Import errors after `gen`

Run `flask fab gen inspect --uri postgresql://...` to confirm the schema was read
correctly. Check that the database user has `SELECT` on `information_schema`.

### Mobile app missing plugin screens

Confirm the trigger table or column exists in the schema:
```bash
flask fab gen inspect --uri postgresql://... | grep -E "bpm_|wallet_|synced_at"
```
If the table is present but the plugin was not generated, pass `--features <plugin>`
explicitly.

---

## Version History

| Version | Change |
|---------|--------|
| 1.0.0 | Initial release: Flask, mobile (Expo), desktop generators |
| 1.1.0 | Added `BaseGenerator` ABC, `_naming` helpers, `GenerationTransaction` |
| 1.2.0 | Plugin auto-detection: BPM, approval, ICD-10, SNOMED, wallet, offline, voice |
