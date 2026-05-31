# Contributing to PgAppForge

Contributions are welcome. This document covers everything you need to go from zero to a merged pull request.

## Table of Contents

- [Quick Start](#quick-start)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Adding a Plugin](#adding-a-plugin)
- [Adding a Schema Template](#adding-a-schema-template)
- [Registering a Custom Form Field Type](#registering-a-custom-form-field-type)
- [Pull Request Process](#pull-request-process)
- [Commit Message Format](#commit-message-format)
- [Security Vulnerabilities](#security-vulnerabilities)

---

## Quick Start

```bash
# Fork the repo on GitHub, then:
git clone https://github.com/<your-handle>/pgappforge.git
cd pgappforge

# Create a virtualenv (Python 3.12+ required)
python3.12 -m venv .venv
source .venv/bin/activate

# Install the package in editable mode with all dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Spin up PostgreSQL via Docker
docker-compose up -d

# Verify the test suite is green before making changes
export SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://pguser:pguserpassword@localhost/app
pytest tests/ci/ -q
```

All 628 CI tests should pass in roughly 80 seconds on modern hardware. If any are red on a fresh clone, open an issue before proceeding.

---

## Development Setup

### Prerequisites

| Requirement | Minimum version | Notes |
|---|---|---|
| Python | 3.12 | `python3.12 --version` to confirm |
| PostgreSQL | 14 | Extensions `uuid-ossp`, `pgcrypto`, `ltree` must be available |
| Docker + Docker Compose | any recent | Used to run PostgreSQL locally |
| Node.js | 20 LTS | Only required if working on the ERD/Security Designer or React Native codegen |

### Full setup

```bash
# Base + dev + extras
pip install -e ".[dev,extras]"

# If you need to work on the frontend designers
cd pgappforge/static/designers
npm install
npm run build   # produces compiled JS consumed by Flask templates

# If you need to work on the React Native codegen output
cd pgappforge/codegen/templates/mobile
npm install
```

### Environment variables

| Variable | Example | Purpose |
|---|---|---|
| `SQLALCHEMY_DATABASE_URI` | `postgresql+psycopg2://pguser:pguserpassword@localhost/app` | Required for all tests |
| `SECRET_KEY` | any 32+ char string | Required for Flask session |
| `PGAPPFORGE_VAULT_KEY` | base64-encoded 32 bytes | Required for Integration Hub credential vault tests |
| `OPENAI_API_KEY` | `sk-...` | Optional; only for AI augmentation integration tests |

Copy `.env.example` to `.env` and fill in the values; `pytest` loads it automatically via `python-dotenv`.

### PostgreSQL extensions

```sql
-- Run once against the test database
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "ltree";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
```

The `docker-compose.yml` in the repo root runs these automatically via the `init-scripts/` directory.

---

## Running Tests

### Fast CI suite (recommended during development)

```bash
pytest tests/ci/ -q
```

628 tests, ~80 seconds. These run against a live PostgreSQL instance. Each test gets an isolated schema via `CREATE SCHEMA test_<uuid>` / `DROP SCHEMA` teardown, so tests are safe to parallelize:

```bash
pytest tests/ci/ -q -n auto   # requires pytest-xdist
```

### Full suite (nose2)

```bash
nose2 -c setup.cfg -v tests
```

### Single test file

```bash
pytest tests/ci/test_erd_designer.py -v
pytest tests/ci/test_security_designer.py -v -k "test_csrf"
```

### Single nose2 test

```bash
nose2 -v tests.test_api.APITestCase.test_get_item_dotted_mo_notation
```

### Tox environments

```bash
tox -e api-sqlite    # legacy SQLite tests (compatibility only)
tox -e postgres      # full PostgreSQL suite via tox
```

---

## Code Style

All code is formatted with **black** (line length 90) and linted with **flake8** (Google import order style). Pre-commit handles both automatically on `git commit`.

```bash
# Format
black --line-length 90 pgappforge tests

# Lint
flake8 pgappforge tests

# Type check (mypy configured in setup.cfg for core modules)
mypy pgappforge/core pgappforge/api pgappforge/plugins
```

Style rules that are not mechanically enforced:

- Use `str | None` union syntax (PEP 604), not `Optional[str]`
- Prefer `list[str]` and `dict[str, Any]` over `List` / `Dict` from `typing`
- Async functions throughout new plugin code; synchronous Flask view handlers are acceptable in the view layer where Flask's WSGI model applies
- Runtime assertions at the start of public functions for invariant checking; use `assert` in tests, `raise ValueError` in library code

---

## Adding a Plugin

Plugins live under `pgappforge/plugins/<name>/`. The minimal structure is:

```
pgappforge/plugins/myfeature/
    __init__.py          # exports MyFeaturePlugin
    models.py            # SQLAlchemy models
    views.py             # Flask views / REST APIs
    services.py          # business logic
    templates/           # Jinja2 templates (optional)
```

Every plugin extends `BasePlugin` and declares a `PluginPriority`:

```python
from pgappforge.plugins.base import BasePlugin, PluginPriority

class MyFeaturePlugin(BasePlugin):
    name = "my_feature"
    label = "My Feature"
    version = "0.1.0"
    priority = PluginPriority.NORMAL   # CRITICAL | HIGH | NORMAL | LOW

    def initialize(self, app, db, security_manager):
        """Called once during AppBuilder.init_app(). Register models, run
        create_all for plugin tables, set up background tasks."""
        db.create_all(tables=[MyModel.__table__], checkfirst=True)

    def register_views(self, appbuilder):
        """Called after initialize(). Register views and menu items."""
        appbuilder.add_view(
            MyFeatureView,
            "My Feature",
            icon="fa-star",
            category="Tools",
        )
```

Then register the plugin in the app factory:

```python
from pgappforge.plugins.myfeature import MyFeaturePlugin

appbuilder = AppBuilder(app, db.engine, plugins=[MyFeaturePlugin()])
```

Use `pgappforge/plugins/audit/` as the reference implementation — it demonstrates model definition, view registration, background task setup, and integration with the security manager. Read `pgappforge/plugins/base.py` for the full `BasePlugin` interface.

Tests for new plugins go in `tests/ci/test_<name>.py`. The `pg_schema` fixture in `tests/conftest.py` provides an isolated PostgreSQL schema and a bound `Session`; use it for all plugin model tests.

---

## Adding a Schema Template

Templates are JSON files describing a complete database schema. Drop a new file in `pgappforge/templates/bundled/` or install it to `~/.pgappforge/templates/` for user-local discovery.

### Minimal template structure

```json
{
  "name": "my_domain",
  "label": "My Domain",
  "description": "One sentence describing the domain.",
  "version": "1.0.0",
  "color": "#4f46e5",
  "icon": "fa-building",
  "tags": ["finance", "operational"],
  "actor": false,
  "tables": [
    {
      "name": "accounts",
      "label": "Accounts",
      "columns": [
        {"name": "id", "type": "UUID", "primary_key": true, "default": "gen_random_uuid()"},
        {"name": "tenant_id", "type": "UUID", "nullable": false},
        {"name": "code", "type": "VARCHAR(20)", "nullable": false, "unique": true},
        {"name": "name", "type": "VARCHAR(255)", "nullable": false},
        {"name": "created_at", "type": "TIMESTAMPTZ", "default": "now()", "nullable": false},
        {"name": "updated_at", "type": "TIMESTAMPTZ", "default": "now()", "nullable": false}
      ],
      "indexes": [
        {"columns": ["tenant_id", "code"], "unique": true}
      ]
    }
  ]
}
```

All tables must include `id` (UUID, PK), `tenant_id` (UUID), `created_at`, and `updated_at`. The `apply` command validates this before executing DDL. See `pgappforge/templates/bundled/ar.json` for a complete multi-table example with foreign keys, indexes, check constraints, and PostgreSQL-specific types.

After adding a template, add a test in `tests/ci/test_templates.py` that calls `flask forge templates apply <name>` against a fresh schema and asserts the expected table count.

---

## Registering a Custom Form Field Type

The Form Builder exposes a public registration API. Call `register_field_type()` at import time in your plugin's `initialize()` method:

```python
from pgappforge.plugins.forms.registry import register_field_type, FieldTypeSpec
from pgappforge.plugins.forms.validators import BaseValidator

register_field_type(FieldTypeSpec(
    name="color_picker",
    label="Color Picker",
    category="input",
    widget="ColorPickerWidget",            # JS widget class name
    renderer="render_color_picker",        # Jinja2 macro name in your templates
    validators=[BaseValidator],            # list of validator classes
    serializer=lambda v: str(v),           # value -> JSON-serializable
    deserializer=lambda v: v,             # JSON -> Python value
    icon="fa-palette",
    description="Hex color picker with swatches.",
    pg_types=["VARCHAR", "CHAR"],          # compatible PostgreSQL column types
))
```

`FieldTypeSpec` is a dataclass defined in `pgappforge/plugins/forms/registry.py`. The full field type catalog lives there; read it before adding to avoid naming conflicts. Auto-discovery also scans installed packages for the `pgappforge.field_types` entry point group — package-distributed field types do not need to call `register_field_type()` manually.

---

## Pull Request Process

1. **Branch from `main`**: `git checkout -b feat/my-feature main`
2. **One PR per feature or fix**: keep scope tight; large PRs stall in review
3. **Tests must pass**: `pytest tests/ci/ -q` green before opening the PR; CI will also run on push
4. **Update `CHANGELOG.md`**: add an entry under `[Unreleased]` with the appropriate subsection (`Added`, `Changed`, `Fixed`, `Deprecated`, `Removed`, `Security`)
5. **Document new public APIs**: docstrings on all public classes and functions; update `docs/` RST files if the feature has user-facing behavior
6. **No breaking changes without a deprecation cycle**: mark old behavior deprecated for at least one minor release before removing it; add a `DeprecationWarning` and document the replacement
7. **PR title follows conventional commits format** (see below)
8. Request review from a maintainer; expect feedback within 5 business days

---

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <short imperative summary>

[optional body]

[optional footer: BREAKING CHANGE: ..., Closes #123]
```

Valid types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`, `ci`, `build`

Examples:

```
feat(forms): add color_picker field type with hex validation
fix(erd-designer): prevent duplicate index error on re-apply
docs(templates): add usage examples for ar and ap templates
test(audit): add chain verification test for tampered records
refactor(security-designer): extract _require_security_admin decorator
```

Scope is the plugin or subsystem name: `erd-designer`, `security-designer`, `forms`, `audit`, `data-hub`, `realtime`, `integration-hub`, `rules-engine`, `bpm`, `codegen`, `templates`, `mfa`, `multitenant`, `api`, `security`, `cli`.

---

## Security Vulnerabilities

Do not open GitHub Issues for security vulnerabilities — that publicizes the flaw before a fix ships. Email `nyimbi+pgaf@gmail.com` with a description, reproduction steps, and your assessment of impact. We aim to acknowledge within 48 hours and ship a patch release within 14 days for confirmed vulnerabilities. You will be credited in the release notes unless you prefer otherwise.
