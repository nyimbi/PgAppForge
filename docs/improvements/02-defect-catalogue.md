# PgAppForge Defect Catalogue

Revision `925c90d8`. Disjoint from the enhancement list in `01-enhancements.md`:
nothing here is a proposal, and nothing in that document is a defect report.

**Verification tags.** `[V]` marks a finding re-checked in this session against
the cited line or by execution (`py_compile`, `flake8`, a real import, an AST
pass, targeted reads). `[R]` marks a finding reported by an auditor from code
reading but not independently re-checked here; these should be triaged against a
live PostgreSQL instance before scheduling. Severity is impact-based, not CVSS
scored.

**Counts:** 132 findings. Critical 11, High 52, Medium 59, Low 10.

| Section | Theme | Findings |
|---|---|---|
| S | Security and trust | 21 |
| C | Concurrency | 16 |
| V | Data veracity and schema evolution | 17 |
| O | Observability and operability | 13 |
| P | Scalability and data path | 13 |
| A | Architecture, build and maintainability | 17 |
| U | Frontend robustness and accessibility | 12 |
| T | Tests, coverage and build gates | 23 |

---

## S. Security and trust

**S1 CRITICAL `[V]` — The AI permission decorator never denies.**
`pgappforge/ai_governance.py:166-180`. The decorator wraps `sm.has_access(...)`
and `abort(403)` inside `try:`, and the handler catches `Exception`
(`werkzeug.exceptions.Forbidden` is a subclass). On denial it logs at debug and
falls through to `return fn(*args, **kwargs)`. Every AI capability guarded by
`@require_ai_permission` is open. No test asserts a 403.
Fix: remove the `try`; let `Forbidden` propagate.

**S2 CRITICAL `[V]` — Dollar-quote breakout into raw SQL through Cypher.**
`pgappforge/database/graph_manager.py:280-286` builds
`SELECT * FROM cypher('{graph}', $$ {query} $$) as (result agtype)` with an
f-string. A `$$` inside `query` terminates the literal and the remainder executes
as SQL. The query text is attacker-influenced: `database/ai_analytics_assistant.py:366-368`
substitutes quoted spans extracted from user text into a `CONTAINS '...'` clause,
and `views/ai_assistant_view.py:325-332` forwards a client-supplied `cypher_query`.
Fix: `exec_driver_sql` with bound parameters, or an AST allow-list (MATCH/RETURN/WHERE/LIMIT/ORDER BY) inside a read-only transaction.

**S3 HIGH `[R]` — The agent shell allowlists `find`, which can delete files.**
`pgappforge/ai_assistant/tools.py:317` allows the prefix `find `; the block list
(`:320-333`) covers `-exec`/`-execdir` but not `-delete` or `-ok`.
`run_command` is in `READ_TOOL_NAMES` (`:1168`), so any authenticated user can
run `find . -name '*' -delete` inside the project root. Deny-listing flags is
structurally wrong; expose a purpose-built `find_files(glob)` tool with a fixed
argv instead.

**S4 HIGH `[V]` — Raw OAuth access token written to logs.**
`pgappforge/security/manager.py:142` `log.debug("Token Get: %s", token)`.
Duplicated in `manager.py.bak`, `.bak2`, `.bak4`, which ship in the wheel.
Also full M-Pesa payloads at `wallet/mpesa_service.py:146-148` and
`security/wallet/wallet_api.py:953`.
Fix: delete the line and the `.bak` files; add a logging filter that redacts
`token|password|secret|api_key|authorization` and a CI grep.

**S5 HIGH `[V]` — Raw driver error text returned to API clients.**
`pgappforge/api/__init__.py:1599, 1662, 1720` (and three more sites) return
`str(e.orig)` from `IntegrityError`, which for psycopg2 contains the table,
column, constraint name and often the offending value.
Fix: map to a stable code; log the detail with a request id; return the code only.

**S6 HIGH `[V]` — M-Pesa STK callback is unauthenticated and replayable.**
`pgappforge/security/wallet/wallet_api.py:936-967` is the only `@expose` in the
file without `@has_access_api` (17 others have it). `process_stk_callback`
(`wallet/mpesa_service.py:307-442`) performs no signature or IP check, resolves
the transaction by `CheckoutRequestID` with no ownership check (`:331-341`),
calls `transaction.mark_completed(...)` at `:369` before the amount check (the
amount mismatch at `:373-374` only logs a warning), and then calls
`wallet.deposit(...)` at `:377-382`. `mark_completed`
(`wallet/mpesa_models.py:228-230`) sets `status = COMPLETED` with no
`status == PENDING` guard. A replayed or forged callback re-runs the deposit.
Fix: IP allow-list or signed service identity at the proxy; guard
`mark_completed` on PENDING; reject amount or phone mismatch; unique constraint on
`(mpesa_account_id, mpesa_receipt_number)`.

**S7 HIGH `[V]` — Rate limiting is bypassable by a request header.**
`pgappforge/security/rate_limiting.py:73-74`: `if
request.headers.get('X-Internal-Request') == 'true': return True`. Any client can
skip the login limiter. The key itself is `get_remote_address()` (`:59`), which
trusts `X-Forwarded-For` behind an unstripped proxy.
Fix: delete the header check; require the proxy to strip it.

**S8 HIGH `[V]` — Tenant identity is client-selected on any dotted-quad host.**
`pgappforge/models/tenant_context.py:152-165` resolves tenant from
`X-Tenant-ID` or `?tenant_id=` guarded only by `_is_development_host`
(`:133-150`), which accepts any four-part numeric host. Behind a proxy that
preserves Host, or in a pod reached by private IP, any caller selects any
tenant; there is no membership check. `before_request` swallows every resolution
error (`:435-437`).
Fix: remove the override; derive tenant from the authenticated user.

**S9 HIGH `[V]` — A string sentinel disables every row-level-security policy.**
`pgappforge/multitenancy/rls.py:79` `_SYSTEM_SENTINEL = "SYSTEM"`; policies at
`:109-113` and the initializer at `:241` grant every row when
`current_setting('app.tenant_id')` equals it. Any path that can run
`set_config('app.tenant_id','SYSTEM',true)` sees everything, and combined with S8
the sentinel is reachable pre-authentication.
Fix: replace with a SECURITY DEFINER function gated on role membership.

**S10 HIGH `[R]` — Stored report SQL runs without the editor's read-only guard.**
`pgappforge/plugins/reports/engine.py:918-928` executes
`report.data_source` verbatim inside a sub-select; `designer.py:1035-1037` does
the same. `sql_editor.py:539` accepts a first word of `SELECT`, `WITH` or
`EXPLAIN`, and a `WITH ... DELETE` CTE passes. `api_execute`
(`sql_editor.py:449`) sets `default_transaction_read_only = on`; the run and
designer paths do not. ACL is opt-in (`acl.py:41`).
Fix: set the read-only GUC on every report session; re-validate at run time.

**S11 MEDIUM `[R]` — f-string SQL at request-reachable sites.**
`plugins/erp/industry/agritech/views.py:174` (`farm_id` into
`agri_field.farm_id = '...'`; guarded by an ORM `session.get` that would 404 most
payloads, but the guard is not validation), `agritech/services.py:742`,
`views/erd_designer.py`, `cli/migration_tools.py`, `ai_assistant/session_service.py:7`
sites. `security/sql_utils.py:39` already provides an identifier validator; none
of these call it.
Fix: bind parameters; route DDL through the existing `SafeDDLExecutor`.

**S12 MEDIUM `[R]` — Static PBKDF2 salt and 100,000 iterations.**
`security/config_encryption.py:74` default salt `'fab-tenant-config-salt-v1'`,
`:81` `iterations=100000`. All deployments share one salt; OWASP's 2023 floor
for PBKDF2-HMAC-SHA256 is 600,000. `is_encrypted()` (`:161-184`) is a base64
heuristic, and no associated data binds a ciphertext to its row.
Fix: per-tenant random salt stored with the ciphertext; raise iterations; use
AAD.

**S13 MEDIUM `[R]` — OIDC nonce issued and never verified.**
`security/integrations/__init__.py:454-456` stores `session["oidc_nonce"]`;
the callback (`:471-529`) validates `state` but never reads the nonce or checks
the `id_token` claim.
Fix: verify the `id_token` against JWKS and assert the nonce.

**S14 MEDIUM `[V]` — Content security policy allows inline and eval script.**
`security/security_headers.py:80` ships `script-src 'self' 'unsafe-inline'
'unsafe-eval'` with a TODO still attached; `img-src ... https:` (`:83`) is an
exfiltration channel. The nonce macro at `templates/appbuilder/baselib.html:130-132`
guards on `csp_nonce is defined`, but `csp_nonce` is defined nowhere in Python, so
all 27 nonces render empty.
Fix: wire the nonce, remove `unsafe-inline`, then remove `unsafe-eval`.

**S15 MEDIUM `[R]` — Stored JSONB rendered unescaped into a script block.**
`templates/process/designer.html:594` `var processGraph = {{ process_graph|safe }};`
where `process_graph` is a JSONB column validated only for shape
(`process/models/process_models.py:155-185`); a node `type` of `"};alert(1);//`
reaches the page verbatim. Same shape at `templates/erd/error.html:141,151`.
Fix: `tojson` and a strict node validator.

**S16 MEDIUM `[R]` — Row-level filter cache never expires without `cachetools`.**
`mixins/rls_mixin.py:96-121` `_SimpleTTLCache` ignores its `ttl` argument; cached
filter expressions persist until FIFO eviction at 1,000 entries, so a revoked
role keeps its filter set indefinitely.
Fix: implement expiry, or make `cachetools` a hard dependency.

**S17 MEDIUM `[R]` — `pickle.loads` on cache reads.**
`mixins/cache_mixin.py:116, 266, 397`. Any writer to the shared cache keyspace
(`fabcache:query:{hash}`) reaches code execution.
Fix: JSON payloads, or `itsdangerous` signing for opaque blobs.

**S18 MEDIUM `[R]` — `eval`/`exec` on workflow definitions, defaulting to allow.**
`pgappforge/workflow/engine.py:368` (`eval` of a condition with `__builtins__`
stripped) and `:393` (`exec` of a script task). On failure `:369-371` swallows the
error and returns `True`. The correct pattern already exists in this codebase:
`plugins/workflow/engine.py:1257-1274` (AST allow-list) and
`process/engine/executors.py:647-655` (`_safe_eval`).
Fix: adopt the allow-list; fail closed.

**S19 LOW `[R]` — Placeholder `SECRET_KEY` accepted at boot.**
`config_example_enhanced.py:24`; no startup assertion rejects it.
`process/approval/crypto_config.py:53-79` has a real validator that is not wired.

**S20 LOW `[R]` — Regex HTML sanitizer.**
`security/input_validation.py:75-81`; `<svg/onload=>`, `<details ontoggle=>` and
entity-encoded schemes pass. `sanitize_search_query` (`:133-148`) strips SQL
keywords from search terms so "update settings" becomes "settings". The module
has no importers.

**S21 LOW `[R]` — CSV `delimiter` interpolated into `COPY`.**
`mixins/import_export_mixin.py:1272-1274`; no caller passes user input.

---

## C. Concurrency

**C1 CRITICAL `[V]` — Lost update on the wallet debit path.**
`wallet/models.py:214-272` `add_transaction` calls `can_transact` (`:224`, which
reads `available_balance` at `:187`), then `_apply_transaction_to_balance`
(`:314-329`) does Python arithmetic on ORM attributes, then commits at `:270`.
SQLAlchemy emits `SET available_balance = <absolute>`, so two concurrent debits
against one balance both pass and the second overwrites the first; the final
balance is negative. `_lock_wallet_for_transaction` (`:274-302`, `SELECT FOR
UPDATE`) is called only from `approve_transaction` (`:1090, :1108, :1171, :1196`),
never from this path.
Fix: `UPDATE user_wallet SET available_balance = available_balance - :amt WHERE
id = :id AND available_balance >= :amt`, check row count.

**C2 CRITICAL `[V]` — `transfer_to` mutates two wallets with no lock.**
`wallet/models.py:503-512`; both wallets are read unlocked in
`wallet/services.py:489-497`. The `balance >= 0` CheckConstraint (`:90-91`) then
raises mid-transfer, leaving the incoming leg applied.
Fix: lock both rows in ascending id order in one statement; compensate on failure.

**C3 HIGH `[R]` — Nested wallet locks in arbitrary order.**
`wallet/models.py:1086` then `:1112`; two reciprocal approvals lock in opposite
orders and PostgreSQL aborts one after `deadlock_timeout`.

**C4 HIGH `[R]` — `db.session` committed inside a raw `ThreadPoolExecutor`.**
`workflow/performance.py:486` creates the executor; `:536, :541` commit and roll
back the Flask-SQLAlchemy scoped session on a pool thread with no app context.
The `except` at `:539-541` logs and continues, so failures are silent.

**C5 HIGH `[R]` — `current_app` and `flask.g` read from a daemon thread.**
`process/ml/smart_triggers.py:379-383` starts the loop; `:405` reads config,
`:415` reads tenant context, `:418` queries; every iteration raises and is caught
at `:408`. The ML trigger monitor never does anything.

**C6 HIGH `[R]` — Live ORM instance mutated from another thread.**
`mixins/replication_mixin.py:315` starts a thread that mutates the instance at
`:333-334, :350-351` while the originating thread flushes.

**C7 HIGH `[V]` — Tenant context lives only on `flask.g`.**
`models/tenant_context.py:81-98`; no `threading.local` or `contextvars`. The
class-level caches (`:65-66`) are unsynchronised and per-instance, so the two
caches diverge.
Fix: `ContextVar` plus a `work_item(tenant_id, fn)` envelope.

**C8 HIGH `[R]` — `run_until_complete` inside ORM flush hooks.**
`mixins/event_disptach_mixin.py:497-530`; `_get_or_create_loop` (`:537-548`)
creates a new loop per row per flush when none is running, and raises
`RuntimeError` when one is.
Fix: move to `after_commit` and a bounded queue drained by one thread.

**C9 MEDIUM `[R]` — One global lock serialises all tenants.**
`tenants/resource_isolation.py:303` (RLock held through `:440`) and
`tenants/scalability.py:82` (lock held across `redis.hset`/`expire` at
`:115-120`).

**C10 MEDIUM `[R]` — Unlocked mutation loop over shared state.**
`tenants/scalability.py:363-377` collects under lock then mutates without it.

**C11 MEDIUM `[R]` — A fresh event loop per Celery task.**
`process/tasks.py:48-49, 88-89`; DB access inside the coroutine without an app
context.

**C12 MEDIUM `[R]` — `asyncio.run` per request from a sync endpoint.**
`collaborative/utils/async_bridge.py:46`.

**C13 MEDIUM `[V]` — Conflict detection is check-then-act.**
`collaboration/sync_engine.py:216` reads the last `ModelChangeLog` row (`:409-413`)
and writes at `:236` with no lock and no version check.
Fix: compare-and-swap on `(record_id, field_name, last_version)` or
`pg_advisory_xact_lock`.

**C14 MEDIUM `[R]` — Background loops never join on shutdown.**
`database/monitoring_system.py:144, 549`; `schema_evolution/schema_monitor.py:140`.
`events/worker.py:223` is the correct pattern and should be the template.

**C15 MEDIUM `[R]` — `__del__` performs blocking shutdown on the GC thread.**
`security_automation/core/audit_engine.py:976-981`;
`collaboration/collaboration_manager.py:495-500`.

**C16 LOW `[R]` — Event worker holds row locks across handler dispatch.**
`events/worker.py:237-283` locks up to 50 rows `FOR UPDATE SKIP LOCKED`, then runs
arbitrary handler code inside the transaction, and the docstring's exactly-once
claim (`:14-16`) is contradicted by at-least-once behaviour.

---

## V. Data veracity and schema evolution

**V1 CRITICAL `[V]` — Last-write-wins discards the local value on any field.**
`collaboration/sync_engine.py:437-450` returns `remote_value` unconditionally.
Applied to a ledger amount, a concurrent debit vanishes with no audit trail.
Fix: forbid auto-resolution on monetary and quantity fields.

**V2 CRITICAL `[V]` — Conflict detection fails open.**
`collaboration/sync_engine.py:433-434` returns `None` ("no conflict") on any
exception, so a database hiccup converts a conflict into a blind overwrite.

**V3 HIGH `[R]` — Bulk import is not transactional and reports phantom inserts.**
`mixins/import_export_mixin.py:697-717`: `session.rollback()` on a batch failure
unwinds every earlier flushed batch while `result.inserted` keeps their counts.
Fix: per-batch `session.begin_nested()`.

**V4 HIGH `[R]` — Import has no idempotency key and no validation.**
`import_export_mixin.py:657-682`: `filter_by(...).first()` then `setattr`, with no
unique constraint, no `ON CONFLICT`, and no `validate` function anywhere in the
file. `import_from_csv_pg_copy` (`:1270-1291`) bypasses the ORM and does not set
`app.tenant_id` for RLS-protected tables.

**V5 HIGH `[R]` — Backup restore reports success after partial failure.**
`database/migration_manager.py:636-643` catches per-statement exceptions, warns,
and returns `True` at `:645`.

**V6 HIGH `[R]` — Version history is evicted and not tamper-evident.**
`mixins/versioning_mixin.py:567-579` deletes history when `__max_versions__ > 0`;
`data_hash` (`:493`) is written but never re-verified, and there is no parent
hash.

**V7 HIGH `[R]` — 665 of 1,265 foreign keys have no `ondelete`; soft delete is
adopted by 7 of about 262 model classes.** Clusters at `models/tenant_models.py:300-301`,
`models/profiles.py:197`, `models/mixins.py:63,78,106`,
`plugins/fintech/regulatory/models.py:205-207`.

**V8 HIGH `[V]` — ERD `ADD COLUMN` emits `NOT NULL` before `DEFAULT` with no
backfill.** `database/erd_manager.py:1062-1067`. On a populated table this
rewrites the table under `ACCESS EXCLUSIVE` or fails.
Fix: expand, backfill in chunks, `VALIDATE CONSTRAINT`, contract.

**V9 HIGH `[R]` — `DROP COLUMN ... CASCADE` in the ERD apply path.**
`views/erd_schema_manager.py:767`; the generated rollback (`:174`) re-adds an
empty column and does not restore the dropped constraint.

**V10 HIGH `[R]` — No system time in the versioning mixin.**
`mixins/versioning_mixin.py:226-249` uses application wall clock; a fast app
server writes future versions that a `valid_from <= now()` query mis-selects.

**V11 HIGH `[R]` — JSONB columns accept anything and are trusted later.**
`models/tenant_models.py:161, 167, 310, 311, 358, 501, 587` and
`models/profiles.py:71, 155, 156, 211, 265`; zero `jsonb_typeof` checks in the
tree. A scalar in `permissions_override` raises or grants during a permission
check.

**V12 MEDIUM `[R]` — Money stored or compared as `Float`.**
`models/alert_models.py:96, 174, 284`; `fastapi_services/mpesa_webhook.py:110`
does `int(float(TransAmount) * 100)`; `analytics/dashboard.py:502-640` and
`mixins/specialized_mixins.py:252` render amounts from floats.

**V13 MEDIUM `[R]` — Ten migration mechanisms, none authoritative.**
One Alembic revision, two orphan scripts outside `versions/`, 74 `CREATE TABLE`
and 92 `ALTER TABLE` literals across 23 files, 22 `create_all()` sites, and two
mutually-blind version ledgers (`db_schema_versions` at
`database/migration_manager.py:265`; `alembic_version` excluded at
`cli/migration_tools.py:116`). No drift check exists.

**V14 MEDIUM `[R]` — Three money representations.**
`pdl/schema.py:22` `money` = `BigInteger` cents; `models/tenant_models.py:496`
`Numeric(10,2)`; `plugins/fintech/regulatory/models.py:436` `Numeric(6,2)`.
`tenants/billing.py:141` divides in float before `Decimal(str(...))`; no write
path calls `quantize`.

**V15 MEDIUM `[R]` — `ALTER COLUMN ... TYPE` has no rewrite guard.**
`views/erd_schema_manager.py:776-781`; `database/erd_manager.py:_modify_column_postgresql`.
A 30-second `statement_timeout` (`:638-640`) converts a rewrite into an outage.

**V16 MEDIUM `[R]` — No `CREATE INDEX CONCURRENTLY` outside echo strings.**
49 `CREATE INDEX` literals; `cli/data_loaders.py:249-251` only prints the
phrase.

**V17 MEDIUM `[R]` — Tenant isolation is opt-in at the ORM layer.**
`models/tenant_context.py:358-372` `filter_by_tenant` warns and returns the
unfiltered query for a model without `tenant_id`; RLS itself is opt-in
(`multitenancy/__init__.py:83`).

---

## O. Observability and operability

**O1 CRITICAL `[R]` — Audit events are discarded when the buffer fills.**
`security/audit_logging.py:272-278` drops the oldest 20%; `:567` returns without
re-adding. A load spike destroys the compliance trail with one WARNING line.

**O2 HIGH `[V]` — No request id is minted.**
`audit.py:225-231` reads `g.request_id`, which is never set, so the `request_id`
column is permanently null. The only `before_request` registration is the
security manager (`base.py:277`). `process/approval/api_response_formatter.py:96`
mints 8 hex characters per response.

**O3 HIGH `[V]` — Neither the threshold monitor nor the metrics collector is
started.** `alerting/manager.py:38-52` constructs both into `app.extensions` and
never calls `start_monitoring()` (`threshold_monitor.py:89-103`) or
`initialize_monitoring()` (`database/monitoring_system.py:1095`); the only start
call is inside a view at `alerting/alert_views.py:377`.

**O4 HIGH `[R]` — The error-rate collector has no data source.**
`database/monitoring_system.py:331-374`; returns a hardcoded `0.1` on the empty
path (`:370`) and `1.0` on exception (`:374`). An app serving only 500s reports
0.1 percent.

**O5 HIGH `[V]` — The worker healthcheck runs a command that does not exist.**
`docker-compose.prod.yml:72-77` runs `flask fab worker-status`; zero occurrences
in `pgappforge/cli/`.

**O6 HIGH `[V]` — Telemetry is never initialised, so `OTEL_ENABLED` is inert.**
`setup_telemetry` has no caller outside `tests/ci/test_telemetry.py`;
`docker-compose.prod.yml:28, 68` set the variable for a code path that never runs.

**O7 HIGH `[V]` — Two audit systems, neither wired.**
`audit.py` (`setup_audit_listeners`, `create_audit_table`) and
`security/audit_logging.py` (`initialize_security_system` `:962`,
`get_audit_logger` `:952`) have zero call sites. `audit.py:51` imports `hashlib`
and never uses it, so there is no chain despite the tamper-evidence docstring
(`:18-20`).

**O8 HIGH `[R]` — Metrics live in a per-process deque.**
`database/monitoring_system.py:116` `deque(maxlen=1000)` behind four gunicorn
workers; invisible to the other workers, lost on restart.

**O9 MEDIUM `[R]` — `/health` returns the driver exception string.**
`health.py:31-32` in an unauthenticated response; no liveness/readiness split.

**O10 MEDIUM `[V]` — 153 files print to stdout in library code**, including a
53-print self-test CLI in `process/approval/security_validation.py`, which
interleaves with gunicorn's log stream in the container.

**O11 MEDIUM `[V]` — `PGAF_API_SHOW_STACKTRACE` has one occurrence.**
`api/__init__.py:117`; no default, no config example, no documentation. When set,
`traceback.format_exc()` is returned to every client.

**O12 MEDIUM `[R]` — Blocking webhook dispatch without timeout.**
`alerting/notification_service.py:280-295` `requests.post` with no timeout inside
the evaluation loop.

**O13 LOW `[R]` — Log injection.** User-controlled strings interpolated raw into
log lines at `wallet/services.py:457, 544, 823` and
`workflow/collaboration.py:308, 335, 403`; no central sanitiser exists.

---

## P. Scalability and data path

**P1 HIGH `[V]` — Three commits per permission per view at boot.**
`security/sqla/manager.py:715, 743` (`add_permission`), `:781, 809`
(`add_view_menu`), `:879` (`add_permission_view_menu`). With 382 `ModelView`
subclasses this is thousands of round-trips and fsyncs on every worker start.
Fix: bulk upsert, one commit.

**P2 HIGH `[V]` — Per-request authorization queries.**
`security/sqla/manager.py:220-249` (`is_item_public`, `has_access_for_user`) each
issue queries; a page with 30 menu items and 3 roles costs on the order of 90
queries plus 30 `find_role` calls. `get_user_roles_permissions` (`:635-682`) is
the batched form and is not on the request path.
Fix: memoise per request in `g`; invalidate on role change.

**P3 HIGH `[V]` — Lazy load per related list column per row.**
`models/base.py:75-81` `reduce(getattr, col.split("."), item)`; `models/mixins.py:67-88`
declares `created_by` and `changed_by` with default `lazy="select"`.
Fix: `selectinload` for the relations named in `list_columns`.

**P4 MEDIUM `[R]` — Offset pagination and an ordered `count(*)`.**
`models/sqla/interface.py:214` (`OFFSET`), `:395-396` (count carries `ORDER BY`);
`page_size` uncapped on the HTML path (`urltools.py:89-94`).
Fix: keyset seek; count from an unordered sub-select.

**P5 MEDIUM `[R]` — One worker thread per server-sent-event client.**
`plugins/realtime/views.py:69-105`, capped at 1,000 clients; `broadcast_to_clients`
(`:295-320`) iterates all clients under a global lock.

**P6 MEDIUM `[R]` — Database lookup per broadcast event.**
`collaboration/websocket_manager.py:292-300` resolves the user by id on every
`field_change` and `cursor_move`.

**P7 MEDIUM `[R]` — Two queries per related-view widget.**
`baseviews.py:1069-1085` chain; a page with R related views costs `2R+1` queries.
Fix: defer behind `<details>` or batch with `selectinload`.

**P8 MEDIUM `[R]` — Full-table `count(*)` per related field in API metadata.**
`api/__init__.py:1931-1968` `_get_list_related_field`.

**P9 MEDIUM `[R]` — A connection pool per SQL-editor request.**
`plugins/reports/sql_editor.py:389-392`.

**P10 MEDIUM `[R]` — No connection-pool defaults.** `base.py` sets no
`SQLALCHEMY_ENGINE_OPTIONS`; `tenants/performance.py:145-155` mutates config
after engine creation (its own log warns this needs a restart).

**P11 MEDIUM `[R]` — Two to seven counts and two full scans per dashboard card.**
`plugins/analytics_dashboard.py:280-316, 325-380`.

**P12 MEDIUM `[R]` — An extra round trip per query for RLS context.**
`mixins/rls_mixin.py:371` `SELECT set_config(...)` on each `query_rls` call;
`:588-616` recomputes the organisation hierarchy per call.

**P13 LOW `[R]` — Cache stampede and pickle on every hit.**
`mixins/cache_mixin.py:99-120` (`hash(sql)` per query compile, `pickle.loads` per
hit, no single-flight).

---

## A. Architecture, build and maintainability

**A1 CRITICAL `[V]` — Five shipped files do not compile and the lint gate cannot
see them.** `py_compile` fails on `public_index_view.py:84`,
`wallet/mpesa_views.py:445`, `fields/extended_fields.py:933`,
`process/approval/workflow_engine.py:82` (imported by 30 modules) and
`testing_framework/generators/e2e_test_generator.py:996`; all last changed in
`53872c3c` (2026-05-30). `flake8 pgappforge` reports 792,898 findings, so the CI
lint job is permanently red and the five `E999` errors are invisible.
Fix: a `compileall` step on `pgappforge/` as the first CI job, ahead of flake8;
then configure flake8 with a `select` list.

**A2 HIGH `[V]` — `exceptions.py` is shadowed by the `exceptions/` package.**
Importing `pgappforge.exceptions` resolves to
`pgappforge/exceptions/__init__.py`, which redefines the same 13 classes as
`exceptions.py:4-92` and a third `FABException` at `exceptions/base.py:11`.
The module file is unreachable by name.
Fix: delete `exceptions.py`; keep one definition per class.

**A3 HIGH `[V]` — Four dependency stacks.** See baseline section 2. CI tests
SQLAlchemy 1.4 on Python 3.9 to 3.12; development runs 2.0 on 3.14.
Fix: one lockfile generated by `uv` for the supported Python, used by CI, tox and
Docker.

**A4 HIGH `[V]` — The plugin manager is constructed twice and the first registry
is discarded.** `base.py:242-249` inside a bare `try`; `base.py:467`
unconditionally overwrites `self.plugin_manager`.

**A5 HIGH `[V]` — `views/__init__.py` loads `views.py` under a second module
identity.** `views/__init__.py:11-20` uses
`spec_from_file_location("fab_views", views_file)`, so `RestCRUDView`
(`views.py:186`) has two classes depending on import path; on failure it
substitutes `ModelView = BaseView` (line 52), which imports cleanly and fails at
request time.
Fix: move the classes into the package.

**A6 HIGH `[V]` — Every mixin import can fail silently.**
`mixins/__init__.py:14-22` `_try_import` swallows any exception into
`log.debug`; 28,911 lines across 36 files are best-effort, and a missing mixin
surfaces as `AttributeError` far from its cause.
Fix: hard imports in the package; a guarded variant only in `pgappforge.extra`.

**A7 HIGH `[R]` — `add_view` deduplicates by class identity.**
`base.py:1000-1004` compares `__class__`; a second view of the same class is
skipped (`:670-689`) but its menu link is still added (`:679`).

**A8 MEDIUM `[R]` — 945 exception classes outside tests**, with `ValidationError`
defined eight times and `InvalidStatusTransitionError` ten; `exceptions.py` plus
`exceptions/standardized.py:32, 50, 58` duplicate `ErrorCategory`,
`ErrorSeverity` and `ErrorContext`.

**A9 MEDIUM `[R]` — Four `WorkflowMixin` and two `ApprovalWorkflowMixin`
definitions** (`mixins/workflow_mixin.py:89`, `mixins/business_mixins.py:40, 207`,
`mixins/approval_workflow_mixin.py:240`, `workflow/mixins.py:26, 192`) and five
engines.

**A10 MEDIUM `[R]` — `ModelVersion` and `ModelBranch` are mapped twice to the
same tables.** `mixins/versioning_mixin.py:176, 261` and
`mixins/version_control_mixin.py:60, 99`; both are exported from
`mixins/__init__.py:26-27`, so importing both registers two mappers on one table.

**A11 MEDIUM `[R]` — Two `EnhancedModelView` classes** (`mixins/view_mixins.py:23`
and `models/enhanced_modelview.py:571`, the latter with a base class that depends
on an optional import).

**A12 MEDIUM `[V]` — 16,235 lines in four packages with zero references**
(`ai_data`, `devops_automation`, `security_automation`, `multi_db`) plus
`monitoring/health_checks.py` (764) and `templates/erd/schema.html` (3,359).

**A13 MEDIUM `[R]` — 77 percent of `modern_ui.py` is unreachable.**
Lines 2842 to 12,369 define nine widget classes no other file imports;
`widgets/__init__.py:53-63` imports seven of seventeen inside a `try`.

**A14 MEDIUM `[V]` — 9,334 lines of legacy and backup files ship in the wheel**,
including three copies of the file that logs the OAuth token.

**A15 MEDIUM `[R]` — 34.4 percent of functions are unannotated**
(6,901 of 20,063); `baseviews.py` is 60 of 62. `setup.cfg:14-33` runs mypy on
three modules; no `pyrightconfig.json` exists despite the CLAUDE.md mandate.

**A16 MEDIUM `[V]` — Seven registration seams for plugins** (`ADDON_MANAGERS`,
`PGAF_PLUGINS`, `PluginLoader`, `SecurePluginLoader`, `PluginManager`,
`plugin_hot_reload.py:221`, and two separate hook registries in `hooks.py:153`
and `plugins/hooks.py:120`); `setup.py:41-44` declares no plugin entry-point
group, so the entry-points claim at `base.py:527` is unimplemented.

**A17 MEDIUM `[R]` — Dozens of shipped plugin modules still import upstream
`flask_appbuilder`** (`plugins/fintech/insurtech/views.py:17-19`,
`remittance/views.py:16-18`, `embedded_finance/views.py:18-20`,
`robo_advisory/views.py:24-26`, `bnpl/views.py:16-18`,
`terminal_management/views.py:18`), so the fork ships a hard dependency on the
package it replaces.

---

## U. Frontend robustness and accessibility

**U1 HIGH `[R]` — 258 templates referenced by `render_template` do not exist.**
334 call sites name them; every one is inside an exception handler
(`views/graph_view.py:126, 149, 197, 244`, `monitoring_view.py:135`,
`ai_assistant_view.py:174`, and 15 more modules), so the failure is a
`TemplateNotFound` inside a 500. `templates/graph/` holds only `index.html` and
`visualizer.html`.

**U2 HIGH `[R]` — Bootstrap 5 markup on Bootstrap 3 assets.**
`templates/appbuilder/embedded/base_embedded.html:33, 117` load
`bootstrap.min.js` 3.4.1 and `:100` renders `class="btn-close"
data-bs-dismiss="alert"`; 24 templates use `btn-close`.

**U3 HIGH `[R]` — CDN scripts load without `integrity`.**
`widgets_postgresql/_cdn.py`: 18 of 19 script and link tags set `crossorigin`
without `integrity`, including DOMPurify (`:46-48`), the sanitiser the editor
widgets depend on. Only Leaflet (`:12-19`) is correct.

**U4 MEDIUM `[R]` — The service worker caches authenticated HTML and never
invalidates.** `pwa.py:183` precaches `/`; the fetch handler (`:245, 288-296`)
caches every same-origin GET and serves it on failure; `cache_name` is the
literal `pgappforge-v1` (`:180`) so clients never receive a new build. Background
sync (`:195-205`) reads `pgaf-sync-queue`, a cache nothing ever writes.

**U5 MEDIUM `[R]` — Offline edits are discarded with HTTP 200.**
`plugins/offline/sync_mixin.py:199-200` server-wins, "do nothing", and the
endpoint still reports success at `:215`.

**U6 MEDIUM `[R]` — The collaboration client script 404s.**
`templates/appbuilder/collaboration/widgets/collaborative_form.html:150` builds
`filename='appbuilder/js/collaboration/collaboration-manager.js'`, which the
static endpoint resolves to `/static/appbuilder/appbuilder/js/...`.

**U7 MEDIUM `[R]` — Slave select2 fields submit the form on change.**
`static/appbuilder/js/ab.js:75`; unsaved edits in every other field are discarded
and all `_flt_*` query parameters are dropped.

**U8 MEDIUM `[R]` — Design tokens exist and are never used.**
`theming/__init__.py:48-57` defines `--primary`, `--bg` and others; `var(--primary)`
appears in zero templates while 5,452 hex literals sit in templates and 3,149 in
Python.

**U9 MEDIUM `[R]` — Bootstrap 3.4.1 and jQuery 3.6.0 are vendored under
"latest" names** (`static/appbuilder/js/jquery-latest.js` header says 3.6.0) with
no `jquery-migrate`; `jquery-latest.js`, `bootstrap.min.js`, `google_charts.js`
and `swagger-ui-bundle.js` (1.39 MB) load unversioned.

**U10 MEDIUM `[R]` — 334 `innerHTML` sinks in templates and 230 in Python-embedded
JavaScript**, with `widgets/xss_security.py` imported by three files and unused
in all seventeen `modern_ui` classes.

**U11 LOW `[R]` — Accessibility gaps in the default shell.**
`templates/appbuilder/init.html:8` has no `lang`; `flash.html:5-9` has no
`role="alert"` and an unnamed dismiss button; `baselayout.html:9` uses the
invalid role `header`; 43 `outline: none` declarations, five removing focus
indication entirely; `general/lib.html:265-274` emits `<th>` and `<td>` inside
`<div>`.

**U12 LOW `[R]` — Translation coverage about 9 percent.** 598 `_(...)` calls in
45 of 279 templates against roughly 6,083 literal strings; `{% trans %}` used
zero times; 16 locale catalogues ship for the core shell only.

---

## T. Tests, coverage and build gates

Added after the tests auditor ran the suite. The `[V]` findings here were
reproduced in this session (`pytest --collect-only`, `coverage debug config`,
`py_compile`, targeted reads); the full-suite numbers are from the auditor's
15-minute run of `pytest tests/ci -q` against the current tree.

**T1 CRITICAL `[V]` — CI executes 6 of 4,003 tests.** `.github/workflows/ci.yml:85`
runs `nose2 ... tests`; nose2's unittest discovery collects only `unittest.TestCase`
subclasses, and 142 of the 146 files in `tests/ci` are pytest-function-only.
`pytest --collect-only tests/ci` collects 4,003. Every behaviour in the suite is
unverified in CI.
Fix: pytest as the single runner in `ci.yml` and `tox.ini`.

**T2 CRITICAL `[V]` — Coverage measures a package that does not exist and gates
nothing.** `.coveragerc:2` `source = flask_appbuilder`; `coverage debug config`
reports `source: flask_appbuilder`, `fail_under: 0.0`. The `fail_under = 70` in
`pyproject.toml:32` and the `coverage = pgappforge` in `setup.cfg:4-6` are both
overridden.
Fix: delete `.coveragerc`; keep one coverage config.

**T3 CRITICAL `[V]` — The CI command aborts on a syntax error.** With
`setup.cfg:5` `always-on = True`, coverage instruments every module at report
time and nose2 dies on `Couldn't parse 'pgappforge/process/approval/workflow_engine.py'`.
Six shipped files fail `py_compile` (A1 lists five; the sixth is
`process/ml/smart_triggers.py:555`, `'await' outside async function` `[V]`).

**T4 HIGH `[V]` — The whole session runs against a stubbed framework.**
`tests/ci/conftest.py:25-49` installs 13 fake `flask_appbuilder` modules into
`sys.modules` and binds `ModelView`, `BaseView`, `expose`, `has_access`,
`MasterDetailView`, `RestCRUDView`, `SQLAInterface` and others to a `_Stub` whose
`__init__` swallows every argument and returns `self` for every call. Eleven
further `tests/ci` files re-stub. PgAppForge *is* Flask-AppBuilder; the plugin
tests therefore prove that module-level code runs, nothing more. No teardown.
Fix: install the package; delete the stubs.

**T5 HIGH `[R]` — One broken relationship poisons the SQLAlchemy registry for the
process.** 668 of the 781 failures are `InvalidRequestError` from
`MemberStatement.member` not back-referencing `MemberAccount.statements`
(`plugins/erp/industry/clubs`); `configure_mappers()` then fails for every
subsequent test in unrelated files. A production bug camouflaged as 668 test
failures.

**T6 HIGH `[V]` — The suite fails one test in five.** `pytest tests/ci -q`:
781 failed, 3,130 passed, 25 skipped, 2 xfailed, 65 errors in 15m24s
(19.9 percent of 3,977 outcomes). No baseline comparison against `master` was
made, so it is unknown how many are pre-existing.

**T7 HIGH `[V]` — The local gate is SQLite in a PostgreSQL-only project.**
`tox.ini:2` `envlist = flake8, api-sqlite`; `:34` `SQLALCHEMY_DATABASE_URI =
sqlite:///`. RLS, JSONB, arrays and `DISTINCT ON` never run locally, which is why
21 test files patch JSONB to JSON.

**T8 HIGH `[R]` — Test isolation is keyed on collection order and its failures
are silenced.** `tests/ci/conftest.py:76-81, 172-187`: the schema reset fires
only when `request.node.cls.__name__` changes; every exception in the reset is
downgraded to a warning and in the truncate path swallowed with
`except Exception: pass`.

**T9 HIGH `[V]` — mypy runs in CI with errors globally ignored.**
`setup.cfg [mypy] ignore_errors = True`; `.github/workflows/ci.yml:33` runs
`mypy pgappforge`. Three modules opt back in. `pyright`, mandated by CLAUDE.md,
is absent from the repository and the virtualenv.

**T10 HIGH `[V]` — flake8 has 874,121 violations, including 706 undefined names.**
W191 429,490 and E101 315,376 are tab-indentation complaints against a codebase
whose own convention mandates tabs, and the config never ignores them, so
`ci.yml:32` can never pass. The 706 `F821` undefined-name findings are a real
bug class hiding in the noise.

**T11 HIGH `[V]` — The CI matrix cannot install the package on three of four
legs.** `ci.yml:44` tests Python 3.9 to 3.12; `setup.py:191` declares
`python_requires=">=3.12"`.

**T12 HIGH `[V]` — Tenancy is tested by import only.**
`tests/ci/test_multitenancy.py:37-101`: `test_package_imports`,
`test_rls_module_imports`, `test_middleware_module_imports`,
`test_models_module_imports`, `test_exclude_tables_is_frozenset`,
`test_platform_tables_excluded`, `test_app_tables_not_excluded`. No test creates
two tenants and asserts one cannot read the other. Fourteen "cross-tenant"
strings exist repo-wide, all in security tests.

**T13 HIGH `[R]` — The GL test declines to test the ledger.**
`tests/ci/test_core_banking_gl.py:1-16`: "We do NOT stand up a real PostgreSQL +
GLPeriod setup"; the bridge is exercised by patching `_post_to_gl`.

**T14 MEDIUM `[R]` — No migration is ever executed by a test.**
`migrations/versions/` holds one revision; `tests/ci/test_pdl.py:271, 294`
asserts the *string* `"def upgrade()"` appears in source.

**T15 MEDIUM `[R]` — No property or invariant tests.** `hypothesis` is neither
used nor a dependency. No double-entry, non-negativity or rounding property is
asserted anywhere.

**T16 MEDIUM `[R]` — No API contract tests.** No `schemathesis` or `openapi-diff`;
the 15 tests that mention "contract" assert internal decorators.

**T17 MEDIUM `[R]` — Mocks, against an explicit project rule.** 1,137
`MagicMock`/`Mock` instances and 203 `patch()` calls in `tests/ci` alone;
CLAUDE.md states "No mocks (except LLM)".

**T18 MEDIUM `[R]` — Sleeps are the only synchronisation primitive.** 41
`time.sleep` calls across 25 files, 6 of them in
`tests/test_concurrency_and_locking.py`.

**T19 MEDIUM `[V]` — The untested surface is exactly the risky surface.**
Test-to-code ratio 0.18 by lines. With zero tests: `plugins/billing`,
`plugins/forms`, `plugins/realtime`, `plugins/tenancy`, `plugins/classify`,
`plugins/analytics`, `plugins/voice`, `plugins/integrations`, `plugins/chatbot`,
`plugins/data_hub`, `visual_ide`, `ai_data`, `devops_automation`,
`security_automation`, `multi_db`, `migrations`, `monitoring`, `fields`,
`help`. Two to five test files each for `core_banking` (8,654 lines), `sacco`,
`regulatory`, `lending`, `mobile_money`, `payments`, `wallet`.

**T20 MEDIUM `[V]` — `make tests` and the quality-gates workflow run 2 files of
4,003.** `Makefile:62-65`; `.github/workflows/quality-gates.yml:36`. The latter
reports documentation coverage, not code coverage, and reports "NEEDS REVIEW"
rather than failing.

**T21 LOW `[R]` — Async mode is unconfigured.** `pyproject.toml` sets no
`asyncio_mode`; 10 tests carry `@pytest.mark.asyncio` and 14 async tests exist,
so 4 are unmarked and silently warn under the default strict mode.

**T22 LOW `[R]` — Empty test files present as coverage optics.**
`tests/ci/test_supplier_invoice.py` is 0 bytes; `tests/integration/
test_wizard_standalone.py`, `tests/scripts/test_faiss_integration_fixed.py` and
`tests/test_all_models.py` contain no test functions.

**T23 MEDIUM `[V]` — Ratios.** 147,993 test lines against 815,781 source lines
(0.18); `plugins/erp` alone is 309,230 lines against 87 test files; 314 test
files against 1,762 source files.
