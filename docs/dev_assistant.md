# PgAppForge Developer Assistant Guide

This guide covers the ERP module conventions and the embedded
`pgappforge.ai_assistant` developer/admin assistant. It is based on the current
codebase layout under `pgappforge/plugins/erp/` and `pgappforge/ai_assistant/`.

## 1. ERP Module Structure

Most ERP modules use this package pattern:

```text
pgappforge/plugins/erp/<domain>/<module>/
  __init__.py
  models.py
  services.py
  views.py
  events.py
```

The same shape appears across finance, HCM, CRM, operations, GRC, platform, and
industry modules. Some packages add local files such as `SPEC.md`,
`COMPARISON.md`, `semantic.yaml`, country-specific payroll calculator packages,
or assembly helpers, but the core contract remains the same.

Use the files this way:

| File | Responsibility |
|---|---|
| `models.py` | SQLAlchemy model definitions, table names, indexes, columns, and model-level constants. |
| `services.py` | Business operations, validation, state transitions, calculations, event emission, and integrations. |
| `views.py` | Flask-AppBuilder views, dashboards, forms, JSON endpoints, and thin request handling. |
| `events.py` | Domain event dataclasses that inherit the foundation `DomainEvent` pattern. |
| `__init__.py` | Plugin metadata, dependencies, permission lists, activation/registration logic, and exports. |

The shared foundation layer lives in `pgappforge/plugins/erp/foundation/` and
provides common models, services, events, views, commons, and view helpers.
`pgappforge/plugins/erp/foundation/events.py` defines `DomainEvent`,
`emit_event()`, `subscribe()`, and `unsubscribe()`.

## 2. Adding A New ERP Module

1. Choose the domain directory that matches the business capability, for
   example `finance`, `hcm`, `crm`, `operations`, `industry`, `platform`, `grc`,
   `procurement`, or `analytics`.
2. Create a package under that domain with the standard files:
   `__init__.py`, `models.py`, `services.py`, `views.py`, and `events.py`.
3. Define SQLAlchemy models in `models.py`. Follow local naming conventions for
   table prefixes, tenant scoping, integer-cent monetary columns, timestamps,
   and JSON fields.
4. Put business behavior in a service class in `services.py`. Service methods
   should accept an explicit SQLAlchemy session where surrounding modules do so;
   callers normally own commit/rollback.
5. Add event dataclasses in `events.py` for durable business facts. Emit them
   from service methods with `emit_event(event, session)` so the event log row
   is part of the same transaction as the business mutation.
6. Add FAB views in `views.py`. Use `BaseERPModelView` for CRUD views and
   `BaseERPView` for dashboard/custom views when the module needs ERP widgets.
7. Add plugin metadata and permissions in `__init__.py`. Existing plugins such
   as `hcm/payroll` define `name`, `domain`, `depends_on`, `metadata`,
   `get_events()`, `subscribe_to()`, and lifecycle hooks.
8. Add tests under `tests/ci/`. Keep tests close to business invariants: service
   methods, arithmetic, event emission, permissions, and view routing.
9. Run the focused test file first, then the broader CI subset:

```bash
uv run pytest tests/ci/<new_or_changed_test>.py
uv run pytest tests/ci
flake8
```

## 3. Finance Arithmetic Standards

Financial code must be deterministic and auditable.

- Use `Decimal` for rates, percentages, allocation ratios, quantities, and
  intermediate monetary arithmetic.
- Store money as integer cents in persisted models and event payloads.
- Do not use binary floats for money. Convert external numeric inputs with
  `Decimal(str(value))` at the boundary.
- Use `ROUND_HALF_UP` where a business amount must be rounded to the nearest
  cent.
- Preserve exact-sum invariants. For allocations, use largest-remainder or an
  equivalent deterministic correction so allocated cents sum exactly to the
  source cents.
- Represent event monetary payloads as integer cents, and Decimal-like rates as
  strings when JSON serialization is needed.

Reference tests:

- `tests/ci/test_finance_arithmetic.py`
- `tests/ci/test_tax_gap_close.py`
- `tests/ci/test_clm_plugin.py`
- `tests/ci/test_assets_plugin.py`

Reference modules:

- `pgappforge/plugins/erp/finance/lease_accounting/`
- `pgappforge/plugins/erp/finance/hedge_accounting/`
- `pgappforge/plugins/erp/finance/material_ledger/`
- `pgappforge/plugins/erp/finance/joint_venture/`
- `pgappforge/plugins/erp/finance/revenue_recognition/`

## 4. Testing Patterns

Use `tests/ci/` for ERP regression tests. The current suite contains focused
plugin tests, finance arithmetic tests, assistant tests, and integration-style
coverage for cross-module behavior.

Patterns to follow:

- Prefer real service calls and real SQLAlchemy fixtures when database behavior
  is the subject of the test.
- Avoid mocks for database behavior when transaction boundaries, persistence,
  relationships, queries, or event rows matter.
- Mocks are acceptable for external services and infrastructure boundaries,
  such as Ollama HTTP calls in `tests/ci/test_ai_assistant.py`.
- Keep tests invariant-driven: exact cents, final balances, event types,
  permission gating, status transitions, and validation errors.
- Put reusable test helpers in the test file or an existing fixture module; do
  not add ad hoc scripts outside `tests/`.

Run:

```bash
uv run pytest tests/ci
```

## 5. AI Assistant Tool Development

The assistant package is:

```text
pgappforge/ai_assistant/
  __init__.py
  _db.py
  agent.py
  context.py
  embeddings.py
  session_service.py
  tools.py
  views.py
```

The runtime flow is:

```text
DevAssistantView
  -> build_system_prompt()
  -> build_tool_registry(user_roles)
  -> run_agent_stream()
  -> Ollama /api/chat
  -> tool dispatch from tools.py
```

Tool definitions live in `pgappforge/ai_assistant/tools.py`.

To add a new tool:

1. Implement the function in `tools.py`. Enforce path confinement with
   `safe_path()` for any filesystem access. Keep outputs bounded.
2. Add a JSON schema entry to `TOOL_SCHEMAS`.
3. Add the function to `_TOOL_FN_MAP`.
4. Add the tool name to `READ_TOOL_NAMES` or `WRITE_TOOL_NAMES`.
5. If the tool mutates files, Git, indexes, or runtime state, call `_audit()`
   with the action and important details.
6. Add tests in `tests/ci/test_ai_assistant.py` proving registration, RBAC
   exposure, and the tool behavior.

`build_tool_registry(user_roles)` returns the schema list and callable map
visible to the current user. Read tools are available to authenticated users.
Write tools are exposed only when the user's role intersects
`WRITE_ROLES`, which is derived from `DEV_ASSISTANT_WRITE_ROLES` and defaults
to `Admin,Developer`.

Current assistant capabilities include:

- Read tools: file read/list/search, Git status/diff/log, whitelisted commands,
  logs, environment inspection with secret masking, route discovery, Ollama
  model listing, database schema reflection, Alembic status, dependency
  inspection, audit-log readback, semantic search, SearXNG web search, CI
  status, usage lookup, and coverage reporting.
- Write tools: `write_file`, `patch_file`, `run_tests`, `git_commit`,
  `git_create_branch`, `rollback_changes`, and `reindex_codebase`.

The view layer is in `pgappforge/ai_assistant/views.py` and exposes:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/dev-assistant/` | Chat UI |
| `POST` | `/dev-assistant/chat` | SSE stream endpoint |
| `GET` | `/dev-assistant/models` | Ollama model list |
| `GET` | `/dev-assistant/sessions` | List saved sessions |
| `POST` | `/dev-assistant/sessions` | Create a session |
| `GET` | `/dev-assistant/sessions/<id>` | Load a session |
| `PUT` | `/dev-assistant/sessions/<id>` | Save/update a session |
| `DELETE` | `/dev-assistant/sessions/<id>` | Delete a session |

Register the assistant through the FAB addon manager:

```python
ADDON_MANAGERS = [
	"pgappforge.ai_assistant.DevAssistantPlugin",
]
```

Useful environment variables:

| Variable | Purpose |
|---|---|
| `OLLAMA_URL` | Ollama base URL; defaults to `http://localhost:11434`. |
| `DEV_ASSISTANT_MODEL` | Default chat model. |
| `PGAF_DEV_ASSISTANT_ROOT` | Project root for path confinement and repository mapping. |
| `DEV_ASSISTANT_WRITE_ROLES` | Comma-separated role names that unlock write tools. |
| `SQLALCHEMY_DATABASE_URI` | Enables session persistence and semantic search storage. |
| `DEV_ASSISTANT_EMBED_MODEL` | Ollama embedding model for semantic search. |
| `DEV_ASSISTANT_EMBED_DIM` | Embedding vector dimension. |
| `SEARXNG_URL` | Enables the `search_web` tool. |

## 6. BaseERPView And BaseERPModelView

`pgappforge/plugins/erp/base_view.py` defines two common view bases.

`BaseERPView` extends `pgappforge.baseviews.BaseView` and provides widget
helpers for ERP dashboards:

- `kpi_cards(kpis)` renders stat cards.
- `chart(rows, chart_type, x_col, y_col, title, height, group_col)` renders
  Chart.js-backed charts.
- `approval_buttons(obj, advance_url, reject_url, ...)` renders workflow action
  buttons.
- `data_grid(rows, columns, save_url, rows_per_page)` renders an editable data
  grid.
- `_session()` returns the FAB SQLAlchemy session.
- `_count(model, session=None, **filters)` safely counts rows and returns 0 on
  error.

Use `BaseERPView` for dashboards, custom endpoints, and pages that compose
widgets or service summaries.

`BaseERPModelView` extends `pgappforge.ModelView` and centralizes CRUD defaults:

```python
class BaseERPModelView(_ModelView):
	_AUDIT = ("id", "created_on", "changed_on", "created_at", "updated_at")
	add_exclude_columns = list(_AUDIT)
	edit_exclude_columns = list(_AUDIT)
	page_size = 50
```

Use `BaseERPModelView` for model CRUD views and override `list_columns`,
`show_columns`, `search_columns`, labels, permissions, and form behavior in the
module view class.

## 7. BPM Action Registration

BPM action registration is implemented by importing
`BPMActionRegistry` from `pgappforge.plugins.workflow.engine` and decorating
callables in a module-local `_register_bpm_actions()` function.

Current examples:

- `pgappforge/plugins/erp/crm/appointments/services.py` registers
  `crm.appointments.book`.
- `pgappforge/plugins/erp/crm/sign/services.py` registers
  `crm.sign.create_request` and `crm.sign.check_status`.

Pattern:

```python
def _register_bpm_actions() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry
	except ImportError:
		return

	@BPMActionRegistry.register(
		"domain.module.action",
		"Human-readable action description",
	)
	def _bpm_action(record_ctx: dict, session: Any, **kwargs: Any) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			# Call the module service with the supplied session.
			return {"status": "ok"}
		except Exception as exc:
			log.warning("bpm domain.module.action failed: %s", exc)
			return {"status": "error", "message": str(exc)}


_register_bpm_actions()
```

Keep BPM actions thin. They should translate workflow context into service
arguments, call the service, and return a small JSON-safe status dict. They
should not own commits unless the surrounding workflow engine explicitly
requires it.
