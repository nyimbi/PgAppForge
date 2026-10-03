# PgAppForge Baseline and Audit Method

Audit date: 2026-10-03. Revision audited: `925c90d8` on branch `fix/production-readiness-blockers`.
Scope: the `pgappforge` package at `/Users/nyimbiodero/src/pjs/fab-ext`.

This document fixes the facts the rest of the audit rests on. Every count below was
measured in this working tree; nothing is inherited from documentation.

---

## 1. Size and shape

| Measure | Value |
|---|---|
| Python files under `pgappforge/` | 1,762 |
| Lines of Python under `pgappforge/` | 815,781 |
| Top-level packages under `pgappforge/` | 57 |
| Lines under `pgappforge/plugins/` | 415,174 (1,060 files, 19 plugin trees) |
| Lines under `pgappforge/plugins/erp/` | 309,230 |
| Lines under `pgappforge/plugins/fintech/` | 69,103 |
| SQLAlchemy `Column(` call sites | 15,323 across 322 files |
| Classes matching `*Model` / `*Mixin` | about 1,594 |
| `ModelView` subclasses | 382 (136 files) |
| `BaseView` / `BaseCRUDView` subclasses | 352 |
| `ModelRestApi` / `BaseApi` subclasses | 111 |
| `add_view` / `add_view_no_menu` call sites | 764 |
| `*DashboardView` classes | 102 (96 files) |
| Functions defined | 20,063; 1,197 longer than 80 lines |
| Files over 800 lines | 290 |
| Jinja templates | 355 files, 127,909 lines |
| Shipped JS / CSS | 2.13 MB / 2.91 MB, vendored, no build step |
| Test files under `tests/` | 314 (147 in `tests/ci`), 147,993 lines |

Two files dominate single-file complexity. `pgappforge/widgets/modern_ui.py` is
12,369 lines, of which 247,458 characters are inline HTML/CSS/JS across 72 string
literals rendered through `render_template_string` at 12 sites; lines 2842 to
12,369 (77 percent) define nine widget classes that no other file imports.
`pgappforge/cli/generators/code_headers.py` is 17,499 lines of generated-source
templates held in string constants.

### 1.1 Dead and orphaned weight

| Asset | Lines | Evidence |
|---|---|---|
| `*_old.py`, `*_legacy.py`, `*_mock.py`, `*_demo.py` | 4,379 | five files, zero importers measured |
| `*.bak`, `*.bak2`, `*.bak4`, `*.backup` | 4,955 | four copies of `security/manager.py` and `process/engine/executors.py` |
| `ai_data/` | 5,717 | zero references from `pgappforge/`, `tests/`, `examples/` |
| `devops_automation/` | 5,360 | zero references |
| `security_automation/` | 4,075 | zero references |
| `multi_db/` | 1,083 | zero references |
| `monitoring/health_checks.py` | 764 | no `__init__.py`, zero importers |
| `templates/erd/schema.html`, `create_table.html`, `edit_table.html` | 5,576 | zero references from any `.py`; the live designer is inline at `views/erd_designer.py:1792-2543` |

Roughly 16,200 lines sit in four packages with zero inbound references, and a
further 9,300 in backups and legacy files. `tmp/` holds 61,128 lines of scratch
that duplicates `pgappforge/mixins/`.

---

## 2. Build, dependency and version reality

Four different stacks are declared for the same package.

| Source | Python | SQLAlchemy | Flask-SQLAlchemy |
|---|---|---|---|
| `requirements/base.txt:46,120` (pip-compile, 3.11) | 3.11 | 1.4.49 | 2.5.1 |
| `setup.py:191` | 3.12 or later | any | 2.5 to 4 |
| `uv.lock:3` | 3.14 or later | resolved 2.0.51 | resolved 3.1.1 |
| `.tox/api-sqlite` | 3.14 | 2.0.51 | 3.1.1 |
| `.github/workflows/ci.yml` matrix | 3.9, 3.10, 3.11, 3.12 | via base.txt | via base.txt |

CI installs `requirements/base.txt`, so the tested stack is SQLAlchemy 1.4 on
Python 3.9 to 3.12 while development runs SQLAlchemy 2.0 on 3.14. `CLAUDE.md`
describes SQLAlchemy 2.0.42 and Flask-SQLAlchemy 3.1.1 as the target. Version
reporting disagrees: `pgappforge/__init__.py:2` says `0.90.0`, `telemetry.py:29`
and `CLAUDE.md` say `4.8.0`, and the rename commit tagged `v5.2.1.dev3`.

### 2.1 Five shipped files do not compile

`python3 -m py_compile` fails on:

- `pgappforge/public_index_view.py:84` (IndentationError), 1,203 lines
- `pgappforge/wallet/mpesa_views.py:445` (open parenthesis never closed)
- `pgappforge/fields/extended_fields.py:933` (unterminated string literal)
- `pgappforge/process/approval/workflow_engine.py:82` (unmatched parenthesis), imported by 30 modules including `process/approval/__init__.py` and `workflow/views.py`
- `pgappforge/testing_framework/generators/e2e_test_generator.py:996`

All five last changed in `53872c3c` (2026-05-30, the `flask_appbuilder` rename),
so they have been uncompilable for four months. The package still imports because
nothing on the `pgappforge/__init__.py` import path reaches them.

### 2.2 The lint gate is structurally inoperative

`flake8 pgappforge` reports 792,898 findings, dominated by whitespace codes
(391,933 `W191`, 291,866 `E101`) that no configured select list excludes, plus
15,065 `E501` and 3,516 `F401`. The CI lint job runs the same command, so it can
never be green, and its five genuine `E999` syntax errors are lost among 792,893
others. `.coveragerc` still names `flask_appbuilder` as the coverage source while
`setup.cfg:4-6` names `pgappforge`. The `Makefile` targets `syntax`, `docs`,
`pipeline` and `security` all pass a `flask_appbuilder` directory that does not
exist. 173 files still reference `flask_appbuilder`, including `init_db.py:15`
and generated code under `tmp/`.

---

## 3. The situation per analytical dimension

### 3.1 Concurrency

40 files spawn threads, 34 use `ThreadPoolExecutor`, 52 use `asyncio`, 50 reference
Redis, 21 reference Celery. Six modules mix blocking `db.session` calls with raw
executors. Only 26 files use a lock and none uses more than one per class, so
there is no intra-module lock-order cycle; the one deadlock found is a
database-level one between two wallet rows locked in arbitrary order
(`wallet/models.py:1086,1112`).

Tenant context lives on `flask.g` (`models/tenant_context.py:81-98`) with no
thread-local or `contextvars` backing, and the two class-level caches
(`_tenant_cache`, `_context_stack`, lines 65-66) are unsynchronised and are not
shared, because a new `TenantContext` is constructed per call site.

### 3.2 Scalability

- List queries use offset pagination (`models/sqla/interface.py:214`) with
  `page_size` uncapped on the HTML path, and a `count(*)` that carries the
  `ORDER BY` (`interface.py:395-396`).
- Per-row lazy loads: `models/base.py:75-81` resolves a dotted list column with
  `reduce(getattr, col.split("."), item)`, and `models/mixins.py:67-88` declares
  `created_by` and `changed_by` with the default `lazy="select"`.
- Boot: `security/sqla/manager.py` commits inside `add_permission` (:715, :743),
  `add_view_menu` (:781, :809) and `add_permission_view_menu` (:879), three
  commits per permission per view.
- Per-request authorization: `has_access_for_user` (:240) and `is_item_public`
  (:220) query per menu item and per endpoint; `get_user_roles_permissions` (:635)
  is the batched form and is not used on the request path.
- Pooling: no default `SQLALCHEMY_ENGINE_OPTIONS` in `base.py`; only
  `config_example_enhanced.py:30` sets `pool_pre_ping`; `plugins/reports/sql_editor.py:389`
  creates a pool per request.
- Realtime: `plugins/realtime/views.py:69` holds a worker thread per server-sent
  event client, capped at 1,000; `collaboration/websocket_manager.py:292` does a
  user lookup per broadcast event.

### 3.3 Observability

| Signal | Count |
|---|---|
| Files using stdlib `logging.getLogger` | 1,047 |
| Files using `print()` | 153 |
| Files referencing OpenTelemetry | 12 |
| Files referencing Prometheus | 8 |
| Files referencing `structlog` | 1 |
| Call sites of `setup_telemetry` outside its own module | 0 (tests only) |
| Call sites of `setup_audit_listeners` / `create_audit_table` | 0 |
| Call sites of `initialize_security_system` / `get_audit_logger` | 0 |
| Call sites of `start_monitoring()` outside views | 0 |
| CLI `worker-status`, probed by the compose healthcheck | does not exist |

No request id is minted anywhere: `audit.py:225-231` reads `g.request_id`, which
is never set. `api/__init__.py:117` gates stack traces on
`PGAF_API_SHOW_STACKTRACE`, a key with one occurrence in the repository and no
default.

### 3.4 Security

| Signal | Files |
|---|---|
| `eval(` / `exec(` | 17 / 13 |
| `pickle` / `yaml.load` | 5 |
| `subprocess` / `os.system` | 26 |
| f-string SQL literals | 25 |
| `Markup(` or `|safe` | 389 |
| Hardcoded password-like literals | 65 |

Confirmed specifics: a raw OAuth token is logged at `security/manager.py:142`;
`str(e.orig)` is returned to API clients at six sites in `api/__init__.py` (first
at :1599); `ai_governance.py:166-180` catches `Exception` around `abort(403)`, so
the AI permission decorator never denies; `database/graph_manager.py:280-286`
interpolates Cypher into dollar-quoted SQL; `ai_assistant/tools.py:317` allowlists
`find` while the blocklist covers `-exec` but not `-delete`;
`models/tenant_context.py:133-165` resolves tenant from a request header or query
parameter on any dotted-quad host; `multitenancy/rls.py:79` defines a `SYSTEM`
sentinel that disables every row-level-security policy.

### 3.5 Data veracity and schema evolution

Ten distinct migration mechanisms, one Alembic revision
(`migrations/versions/001_collaborative_features_initial.py`) plus two orphan
scripts outside `versions/`, 74 `CREATE TABLE` and 92 `ALTER TABLE` literals
across 23 files, and 22 `create_all()` call sites. No drift check exists.
1,265 foreign keys, 600 with `ondelete`. Zero `jsonb_typeof` checks in the tree.
`versioning_mixin.py` records valid time from application wall clock only and
never re-verifies its own hashes; `version_control_mixin.py` is weaker.
`collaboration/sync_engine.py:433` returns "no conflict" on any exception, and
:437-450 discards the local value unconditionally under last-write-wins.

### 3.6 Architecture

`pgappforge/exceptions.py` is shadowed by the `pgappforge/exceptions/` package
(confirmed by import: `__file__` resolves to `exceptions/__init__.py`), so the
module's 12 classes are unreachable. 945 exception classes exist outside tests.
Seven registration paths exist for views and plugins; `base.py:242-249` builds a
`PluginManager` inside a bare `try` and `base.py:467` overwrites it.
`mixins/__init__.py:14-22` swallows every import error into `log.debug`, so
28,911 lines of mixins are best-effort. `views/__init__.py:11-20` loads `views.py`
under the synthetic module name `fab_views`, giving `RestCRUDView` two identities,
and on failure substitutes `ModelView = BaseView` at line 52. Two classes named
`EnhancedModelView` and two named `ApprovalWorkflowMixin` are both exported.

### 3.7 Frontend and cognitive efficacy

700 view classes across 72 menu categories, no command palette, no global
search, and no bulk operations beyond the legacy hidden form. 124
`location.reload` calls in templates and no `WebSocket` or `EventSource` use in
templates. The content security policy ships `script-src 'self' 'unsafe-inline'
'unsafe-eval'` (`security/security_headers.py:80`) with the removal note still a
TODO, so every `innerHTML` sink is unguarded; the nonce macro at
`baselib.html:130-132` renders empty because `csp_nonce` is never defined in
Python. 334 `render_template` call sites name 258 templates that do not exist on
disk, all of them exception handlers. 5,452 hex literals sit in templates and
3,149 in Python while the token layer they could use is consumed zero times.
About 9 percent of UI strings are wrapped for translation.

### 3.8 Maintainability and testability

34.4 percent of functions carry no annotations (6,901 of 20,063); `baseviews.py`
is 60 of 62 unannotated. `setup.cfg:14-33` runs mypy on three modules and there is
no `pyrightconfig.json` despite the CLAUDE.md mandate. Test-to-code ratio is
148k against 816k lines, but the plugin tree has no matching test tree, and the
CI default environments in `tox.ini` are SQLite, not PostgreSQL.

---

## 4. Method

Ten auditors were dispatched in parallel, each owning one dimension and a disjoint
file slice, each required to cite `path:line` and to separate confirmed defects
from speculative ones. Every headline claim in the resulting catalogues was then
re-verified directly in this session against the cited lines or by execution:
`py_compile` on the package, `flake8`, an actual `import pgappforge.exceptions`,
an AST pass over all 1,762 files, a reference scan for every top-level package,
and targeted reads of the lines cited for the top-severity findings. Findings that
could not be re-verified are marked as reported-only.

Scoring for the enhancement matrix is in `01-enhancements.md`; defects are in
`02-defect-catalogue.md`; capability gaps in `03-capability-gap-analysis.md`; the
phased plan in `04-roadmap.md`.