# PgAppForge Developer Guide

## 1. Module Anatomy

Standard ERP modules use this layout:

```text
pgappforge/plugins/erp/<domain>/<module>/
  models.py
  services.py
  views.py
  events.py
  __init__.py
```

| File | Purpose |
|---|---|
| `models.py` | Defines SQLAlchemy tables, columns, indexes, relationships, tenant fields, and persisted business state. |
| `services.py` | Holds business logic, validation, calculations, state transitions, integration calls, and event emission. |
| `views.py` | Registers Flask-AppBuilder CRUD views, dashboards, custom endpoints, forms, and thin request handlers. |
| `events.py` | Defines durable domain event dataclasses for audit trails and cross-module subscribers. |
| `__init__.py` | Exposes plugin metadata, permissions, dependency declarations, view/model registration, and module exports. |

## 2. Adding a New ERP Module — 5-Step Checklist

1. Create a package directory under `pgappforge/plugins/erp/<domain>/<module>/`.
2. Define SQLAlchemy models in `models.py`; keep money as integer cents and tenant-aware records scoped consistently with nearby modules.
3. Implement business logic in `services.py`; service methods should accept an explicit SQLAlchemy session when persistence is involved.
4. Register views in `views.py` using `BaseERPModelView` for CRUD views and `BaseERPView` for dashboard or custom widget pages.
5. Register blueprints in `__init__.py` and add the module to `INSTALLED_MODULES`.

## 3. Finance Arithmetic Standards

- Decimal only: never use `float` for money, rates, allocation ratios, or intermediate financial calculations.
- Use `ROUND_HALF_UP` for all rounding that creates a persisted or displayed financial amount.
- Store money as integer cents in the database and surface it as `Decimal` in Python service and view code.
- Add a regression test in `tests/ci/finance/` for every formula change.

## 4. BaseERPView / BaseERPModelView Patterns

Use `BaseERPModelView` for SQLAlchemy model CRUD screens:

```python
class InvoiceView(BaseERPModelView):
    datamodel = SQLAInterface(Invoice)
    list_columns = ["invoice_no", "customer_id", "status", "total_cents"]
    show_columns = ["invoice_no", "customer_id", "status", "total_cents", "metadata_"]
    search_columns = ["invoice_no", "customer_id", "status"]
    label_columns = {
        "invoice_no": "Invoice No",
        "total_cents": "Total",
    }
```

- `label_columns`: dict mapping model attributes to human-readable column labels.
- `show_columns`: list of fields displayed on the record detail page.
- `list_columns`: list of fields displayed in table/list views.
- `search_columns`: list of searchable fields exposed by the view.

Use `BaseERPView` for dashboards and custom pages. Its KPI helper signature is:

```python
def kpi_cards(self, kpis: list[dict]) -> Markup:
    ...
```

`kpi_cards()` returns a `markupsafe.Markup` HTML fragment. Each KPI dict accepts `label`, `value`, `format`, `color`, `icon`, and optional `trend` / `compare` keys.

## 5. BPM Action Registration

Register workflow-callable actions with the `BPMActionRegistry.register()` decorator:

```python
from pgappforge.plugins.workflow.engine import BPMActionRegistry


@BPMActionRegistry.register("domain.module.action", "Human-readable action description")
def _bpm_action(record_ctx, session, required_arg, **kw):
    return ModuleService().run(required_arg, session=session)
```

Transition handlers should stay thin: read values from `record_ctx`, normalize primitive inputs, call the module service, and return a JSON-safe result. They should not own transaction commits unless the workflow engine contract for that action explicitly requires it.

State machine integration is handled by the workflow engine and state-machine mixins. BPM transitions load `bpm_process_transition` rows, evaluate conditions in priority order, advance the process instance, and write a `ProcessEvent` audit row for every transition.

## 6. Testing Standards

- All ERP tests live in `tests/ci/`.
- Use a real PostgreSQL connection for persistence behavior; do not use mocks or SQLite for database, transaction, JSONB, row-security, or finance arithmetic coverage.
- Put shared fixtures in `tests/fixtures/`.
- Run:

```bash
pytest tests/ci -vxs
```

## 7. AI Assistant — Adding a New Tool

The assistant uses `pgappforge/ai_assistant/tools.py` for callable tools and `pgappforge/ai_assistant/agent.py` for the Ollama ReAct loop.

The current codebase does not define a standalone `@tool` decorator. The supported tool signature is a JSON-schema-registered function that accepts JSON-serializable arguments and returns a string:

```python
def my_tool(path: str, limit: int = 50) -> str:
    ...
```

Add the tool schema to `TOOL_SCHEMAS`, add the callable to `_TOOL_FN_MAP`, and add the tool name to either `READ_TOOL_NAMES` or `WRITE_TOOL_NAMES`.

Use the RBAC gate pattern already in `build_tool_registry(user_roles)`:

```python
has_write = bool(user_roles & WRITE_ROLES)
allowed_names = READ_TOOL_NAMES | (WRITE_TOOL_NAMES if has_write else frozenset())
schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in allowed_names]
registry = {name: fn for name, fn in _TOOL_FN_MAP.items() if name in allowed_names}
```

Registering in the tool registry means all three pieces are present: JSON schema, `_TOOL_FN_MAP` entry, and read/write tool-name classification. Mutating tools must call `_audit()` and must enforce project confinement with `safe_path()` when touching the filesystem.

Test the tool through the ReAct loop by exercising `run_agent_blocking()` or `run_agent_stream()` with an RBAC-filtered registry from `build_tool_registry()`. Tests should prove schema exposure, role gating, successful tool execution, and tool-result handling in the assistant loop.
