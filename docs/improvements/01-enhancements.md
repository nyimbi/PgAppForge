# PgAppForge Enhancement Set: 50 Non-Incremental Proposals

Revision `925c90d8`. Companion documents: `00-baseline-and-method.md` (measured
facts), `02-defect-catalogue.md` (defects, disjoint from this list),
`03-capability-gap-analysis.md` (domain gaps), `04-roadmap.md` (phasing).

## Admission rule

A proposal is admitted only if it changes the asymptotic class or the trust
model of a subsystem, or opens an operational paradigm the platform cannot
express today. Cosmetic restyling, localised refactoring, added configuration
knobs, and features that a competent engineer could add to the current design in
under a week are excluded by construction. Every proposal below replaces a
pattern the codebase already contains rather than sitting beside it.

## Scoring

Impact (1 to 5) is the magnitude of the change in the metric named in the
proposal, weighted by how much of the platform it touches. Effort is in
engineer-weeks for a two-person team familiar with the code, including
migration. Priority is Impact × 5 / Effort, rounded.

| Band | Priority | Reading |
|---|---|---|
| A | ≥ 12 | start here |
| B | 6 to 11.9 | schedule within two phases |
| C | < 6 | do it when the prerequisite lands |

---

## 1. Correctness and trust foundations (the ledger spine)

### P1. Event-sourced double-entry ledger with derived balances `[P]`
Replaces every `balance += x` in roughly 40 service modules with an append-only
journal. Today `wallet` keeps `Numeric(15,2)`, fintech keeps integer cents, ERP
keeps a third GL, and `fintech/lending` posts each event to two of them
(`services.py:872` and `:889`). A balance becomes the fold of entries; the stored
column is a rebuildable cache. Eliminated by construction: the lost update on
`wallet/models.py:214-272`, the unlocked two-wallet transfer at `:503-512`, the
clamping subtraction at `erp/foundation/commons.py:48-50`, the negative-balance
accrual at `core_banking/services.py:1002`, and the silent divergence when no GL
period is open (`erp/finance/gl/services.py:846-855`).
**Target:** balance defects 0; any balance at any past instant reconstructible in
one query; rebuild as a test rather than a reconciliation script.
Impact 5, Effort 20, Priority 1.3 (A). Blocked by nothing; blocks P2, P3, P4.

### P2. Bitemporal kernel as the framework's default history primitive `[P]`
`tstzrange` valid-time and `recorded_at` system-time on every regulated model,
with `EXCLUDE USING gist` preventing overlap. Replaces `versioning_mixin.py`
(valid time only, wall clock, evicted history) and `version_control_mixin.py`
(nothing). Makes "what did we believe at T about X" one join; makes restatement
an insert. The `restructure_loan` defect at `lending/services.py:1297`, which
strands the old loan's interest and resets the new loan to PERFORMING, becomes
inexpressible.
**Target:** restatement queries from a week of archaeology to one SQL statement;
history eviction illegal on regulated objects.
Impact 5, Effort 12, Priority 2.1 (A).

### P3. Transactional outbox and idempotency-key middleware `[P]`
One `Idempotency-Key` on every money endpoint, a unique constraint, and an
outbox table written in the same transaction as the state change. Today only
`mobile_money` has this (`models.py:187`, `services.py:541`); `core_banking.
transfer` takes free-text `reference` (`models.py:493`); `banking_api`'s
transfer endpoint has no key (`api.py:776`); the M-Pesa callback
(`wallet/mpesa_service.py:307-395`) double-credits on redelivery.
**Target:** duplicate postings 0, proven by replaying every request 100 times.
Impact 5, Effort 6, Priority 4.2 (A).

### P4. Webhook gateway with verification, replay window and ordering `[P]`
The Stripe webhook already verifies correctly (`plugins/tenancy/__init__.py:593-622`);
the M-Pesa one (`security/wallet/wallet_api.py:936`, the only expose in the file
without `@has_access_api`) verifies nothing, resolves by `CheckoutRequestID` with
no ownership check, calls `mark_completed` before checking the amount, and
deposits `transaction.amount` rather than the amount paid
(`mpesa_service.py:372-379`). One gateway: signature verification, nonce window,
deduplication on provider event id, ordering by provider sequence, dead-letter.
**Target:** forged-callback acceptance 0; provider onboarding 1 day per adapter.
Impact 5, Effort 5, Priority 5.0 (A).

### P5. Expand-contract schema evolution engine with lock analysis `[P]`
Replaces `database/erd_manager.py:1056-1100` and
`views/erd_schema_manager.py:752-815`, which emit `ADD COLUMN ... NOT NULL` before
`DEFAULT` (table rewrite on a populated ledger), `DROP COLUMN ... CASCADE`
(`:767`), and `ALTER COLUMN ... TYPE` with no rewrite guard (`:776-781`). Every
change becomes add-nullable, backfill in chunks, `NOT VALID` then `VALIDATE`,
contract in a later deploy; `lock_timeout` probing in a throwaway transaction
refuses any `ALTER` that would block.
**Target:** zero `ACCESS EXCLUSIVE` on tables above 1M rows.
Impact 4, Effort 8, Priority 2.5 (A).

### P6. Bitemporal event log with sequence and consumer offsets `[P]`
`erp/foundation/models.py:716` is already append-only with causation; `events/
worker.py` already does `SKIP LOCKED`, backoff and dead-letter. It has no
sequence number and no offsets, so no projection can be rebuilt. Add
`(stream_id, sequence)` with a uniqueness constraint plus a projection checkpoint
table. Every read model in 31 domains becomes rebuildable.
**Target:** "how did this balance get here" from SQL archaeology to a projection
replay.
Impact 4, Effort 8, Priority 2.5 (A). Depends on P1.

### P7. Deterministic replay and simulation of the money path `[P]`
Because P1 makes every money event an immutable, totally ordered fact, the
history can be re-executed against a modified rules set and the resulting
balances diffed. Today `fpa.generate_scenario` (`services.py:623`) multiplies
budget lines by a percentage. Property-based invariants ("sum of debits equals
sum of credits after any prefix", "no negative balance without an overdraft
authorisation") replace the 12 untested fintech domains.
**Target:** what-if simulation of the loan book at 3× NPL becomes a parameter;
production bugs reproducible on demand.
Impact 4, Effort 10, Priority 2.0 (A). Depends on P1, P6.

---

## 2. Identity, tenancy and trust

### P8. Row-level security as a non-bypassable framework invariant `[P]`
`enable_rls_all_tenant_tables` (`multitenancy/rls.py:138-162`) exists and is
opt-in (`multitenancy/__init__.py:83`); the ORM layer is an optional wrapper
(`models/tenant_context.py:358-372`); the `SYSTEM` sentinel
(`multitenancy/rls.py:79`) disables every policy; the dev-mode override
(`tenant_context.py:152-165`) lets a caller pick any tenant by header on any
dotted-quad host. Make `FORCE ROW LEVEL SECURITY` mandatory for every
`tenant_id` column, assert it at boot against `pg_policies`, and delete the
sentinel and the header path.
**Target:** cross-tenant findings 0 in the security suite, verified per request.
Impact 5, Effort 8, Priority 3.1 (A).

### P9. Tenant context as a ContextVar with a work-item envelope `[P]`
`flask.g` cannot cross a thread (`models/tenant_context.py:81-98`); six modules
mix blocking `db.session` with raw executors (`workflow/performance.py:486`,
`process/ml/smart_triggers.py:379`, and others); 40 files spawn threads. One
`ContextVar` set in `before_request`, copied into every executor submission,
serialised into every job payload.
**Target:** background jobs with `tenant_id IS NULL` 0, by construction.
Impact 4, Effort 4, Priority 5.0 (A).

### P10. Permission-graph compiler: RBAC as database policies `[P]`
Authorization exists four times (ORM `query_rls`, PG policies, the admin
sentinel, `MultiTenancyMixin._evt_before_insert`). A compiler reads FAB
roles/permissions and emits `CREATE POLICY` per table, so raw SQL, `psql`, batch
jobs and the SQL editor are covered by the same policy.
**Target:** 0 ORM-side tenant filters; new-model onboarding with zero developer
action.
Impact 4, Effort 10, Priority 2.0 (A). Depends on P8.

### P11. Relationship-based policy engine (Cedar or OpenFGA tuples) `[P]`
`HasRole`/`HasPermission` (`security/policies.py:70-104`) cannot express "approver
for this loan at this stage below this amount", so `process/approval/
security_validator.py:199, 211` hand-rolls each rule. A tuple store
`(subject, relation, object, condition)` with conditions compiled to SQL makes
approval rules data.
**Target:** ≥ 80 percent of approval rules authored as data (currently about 0);
new approval workflow in under a day.
Impact 4, Effort 12, Priority 1.7 (B).

### P12. Continuous authorization with instant revocation `[P]`
FAB sessions are long-lived; a revoked role stays effective for the 300-second
cache TTL (`rls_mixin.py:463`) or forever without `cachetools`
(`rls_mixin.py:96-121`). A session-version counter checked on every request kills
every token for a user the moment a role changes; step-up MFA on owner actions.
**Target:** revocation effective within one request; stale-permission window 0.
Impact 4, Effort 5, Priority 4.0 (A). Depends on P8.

### P13. Capability-token sandbox for the AI agent `[P]`
`require_ai_permission` never denies because `abort(403)` is caught
(`ai_governance.py:166-180`); `run_command` is in the read tier and allowlists
`find` without blocking `-delete` (`tools.py:317`); `write_file`, `patch_file`
and `git_commit` run with no per-call check (`agent.py:52-59`). Mint a signed,
short-lived, argument-scoped capability token per tool at session start;
verify signature, scope and shape before dispatch; require out-of-band
confirmation for write tokens.
**Target:** unauthorized tool invocations 0; injection-driven repository writes 0.
Impact 5, Effort 6, Priority 4.2 (A).

### P14. Verifiable tenant identity `[P]`
Tenant identity is a row in `ab_tenants` plus the dev override. Prove domain
control by DNS TXT or a hosted `.well-known` file, registration by a signed
document hash, ownership by a verifiable credential; enable RLS only after the
attestation verifies.
**Target:** tenants activated without an attestation 0; cross-tenant
impersonation detected at registration.
Impact 3, Effort 10, Priority 1.5 (B). Depends on P8.

### P15. Append-only, hash-chained audit ledger with external checkpoint `[P]`
`audit.py` imports `hashlib` (`:51`) and never chains; `security/audit_logging.py`
drops the oldest 20 percent of events when its buffer fills (`:272-278`); neither
is wired; a third `AuditLog` lives at `wallet/models.py:1721`. One table, one
chain, `prev_hash`/`entry_hash`, a signed checkpoint, WORM export, and a
`dropped_total` counter that pages.
**Target:** tamper detectable within one checkpoint; dropped events 0; one
authoritative trail.
Impact 5, Effort 8, Priority 3.1 (A). Depends on P6.

---

## 3. Compute, concurrency and execution

### P16. Single-writer execution engine with a strict work-item contract `[P]`
40 files spawn threads with no contract about sessions, context or shutdown. All
become worker actors that never touch `db.session` or `flask.g` and receive
`(tenant_id, app_context, payload)`. `events/worker.py:223` is the correct
pattern and becomes the template for every background path.
**Target:** `RuntimeError: Working outside of application context` in production
0; background-task p99 variance down about 10× by removing borrowed sessions.
Impact 4, Effort 10, Priority 2.0 (A). Depends on P9.

### P17. Durable job queue with leases, retries and dead-letter `[P]`
Three unconnected mechanisms today (`events/worker.py`, `erp/platform/scheduler/`,
Celery under `process/async/`), one bare thread (`workflow/__init__.py:414-441`)
that is not safe under four gunicorn workers, and hand-rolled batch locks
(`fintech/lending/models.py:1174`, `services.py:2226`) whose `IntegrityError`
propagates out of `run_daily_aging`. One job model with lease expiry, attempt
counters and declared idempotency per job type.
**Target:** daily aging safe to retry and to run on two workers; `run_daily_aging`
stops reporting "completed" after a swallowed rollback error.
Impact 5, Effort 10, Priority 2.5 (A).

### P18. Money-mutating operations as atomic conditional statements `[P]`
Replace the read-modify-write pattern in `wallet/models.py:214-272`, `:503-512`,
`fintech/lending/services.py:790-809`, `core_banking/services.py:508, 685,
1207, 1279, 2030`, and `sacco/services.py:988` with single statements:
`UPDATE ... SET balance = balance ± :amt WHERE id = :id AND balance >= :amt`,
row count checked, `FOR UPDATE` only where a read is genuinely needed, lock
order fixed by ascending id.
**Target:** lost updates and double-spends 0 under a replay harness; the
`deadlock_timeout` cycle at `wallet/models.py:1086, 1112` becomes impossible.
Impact 5, Effort 4, Priority 6.3 (A). Depends on P1.

### P19. Query budget enforcement at the ORM layer `[P]`
Every N+1 in the catalogue is invisible until production: the list widget's
`reduce(getattr, col.split("."), item)` (`models/base.py:75-81`), the
`_get_related_views_widgets` chain (`baseviews.py:1069-1085`), the per-field full
count in API metadata (`api/__init__.py:1931`), the per-card dashboard counts
(`plugins/analytics_dashboard.py:280-316`). A statement-count and
`statement_timeout` interceptor turns each into a development-time error.
**Target:** 0 list endpoints above 5 queries, enforced in CI.
Impact 4, Effort 4, Priority 5.0 (A).

### P20. CQRS read models maintained by the event log `[P]`
Lists, dashboards, menus and permission sets are projections over P6 rather than
live queries. Boot stops issuing three commits per permission per view
(`security/sqla/manager.py:715-879`, thousands of round-trips across 382 view
classes) and pages stop issuing per-request authorization queries
(`manager.py:220-249`, on the order of 90 per page).
**Target:** boot under 3 s with 1,000 views; menu render one query; list p95
under 80 ms at 100M rows.
Impact 5, Effort 16, Priority 1.6 (B). Depends on P6.

### P21. Incremental view maintenance for operational dashboards `[P]`
`analytics/dashboard.py` and `plugins/analytics_dashboard.py` compute
per-tenant and per-card aggregates at request time. Continuous aggregates or
projection tables maintained by the outbox; dashboards become point lookups on
rollups.
**Target:** dashboard p95 under 100 ms at 1B usage rows; write path +2 to 3
percent.
Impact 4, Effort 8, Priority 2.5 (B). Depends on P6.

### P22. Logical-decoding CDC for cache invalidation and replicas `[P]`
TTL-based cache invalidation is stale by construction and stampedes at expiry
(`mixins/cache_mixin.py:99-120`). Logical decoding turns invalidation into an
event, moves read traffic to replicas, and feeds P20.
**Target:** read-model lag under 1 s p99; 80 percent of read traffic off the
primary.
Impact 4, Effort 12, Priority 1.7 (B). Depends on P6.

### P23. PostgreSQL-native horizontal partitioning (Citus) on organisation id `[P]`
`tenants/scalability.py:95-173` simulates multi-instance placement in-process
with Redis while the database remains one instance. A real distribution key
replaces the simulation.
**Target:** write throughput scaling O(nodes) rather than O(1); single-writer
ceiling removed.
Impact 3, Effort 16, Priority 0.9 (C). Depends on P8.

### P24. Vectorised batch paths: COPY, bulk upsert, set-based DML `[P]`
`mixins/import_export_mixin.py` commits per batch, rollbacks unwind earlier
batches, and rows are `setattr` one at a time; `process/tasks.py:212-241`
materialises every expired row before deleting. COPY with `ON CONFLICT`,
`executemany`, and set-based statements replace row-at-a-time work.
**Target:** 100k-row import under 3 s; batch write paths O(1) round trips.
Impact 4, Effort 6, Priority 3.3 (A).

### P25. Structured concurrency: one owner loop per process `[P]`
`mixins/event_disptach_mixin.py:497-548` creates an event loop per row per flush;
`process/tasks.py:48-49` creates one per Celery task;
`collaborative/utils/async_bridge.py:46` runs a loop per request. ORM events move
to `after_commit` feeding a bounded queue; all loops become owner-scoped and
lint-enforced.
**Target:** leaked loops 0; flush latency independent of handler latency.
Impact 4, Effort 5, Priority 4.0 (A). Depends on P16.

### P26. Tenant-sharded state instead of global-lock registries `[P]`
One `RLock` per registry serialises every tenant (`tenants/resource_isolation.py:303`,
`tenants/scalability.py:82`, and five more modules), and one tenant's Redis
timeout stalls every other tenant's registration.
**Target:** lock-contention p99.9 minus p50 down about 10×; per-tenant fault
isolation.
Impact 3, Effort 5, Priority 3.0 (A). Depends on P9.

### P27. Deterministic race-testing harness `[P]`
Every concurrency defect in the catalogue (P18's class, the lock-order cycle,
`sync_engine.py:216`, `scalability.py:363`) is a race a conventional suite will
not reproduce. A seeded scheduler with instrumented yield points replays a fixed
interleaving, and each lock-order cycle becomes a regression test.
**Target:** p100 reproducibility for concurrency defects; currently the detection
rate for this class is effectively zero.
Impact 4, Effort 6, Priority 3.3 (B). Depends on P16.

### P28. Declarative lock-order and lock-scope analysis `[P]`
Nested locks on two instances of the same class, locks held across network I/O
(`scalability.py:115-120`), locks acquired in `__del__`
(`security_automation/core/audit_engine.py:976`), and `asyncio.run` outside
worker-init are all statically detectable.
**Target:** new lock-order cycles blocked at CI rather than at
`deadlock_timeout`; locks held across I/O driven to 0.
Impact 3, Effort 4, Priority 3.8 (B).

### P29. Settlement and netting engine `[P]`
`netting` has zero occurrences in the repository. Nine unrelated settlement
state machines exist (payments, pswitch_adapter, bnpl, material_ledger, swift,
treasury, mobile_money, sacco, trade_finance). One position model
(`instruct → expected value date → netting position → settle window → break`)
with per-rail adapters.
**Target:** nine code paths become one; multi-party flows (two banks, three
merchants, one instruction) become expressible.
Impact 5, Effort 20, Priority 1.3 (A). Depends on P1.

### P30. Unified reconciliation engine `[P]`
11 reconciliation implementations with copy-pasted tolerance matching and break
escalation. One declarative match rule (key fields, tolerance, date window,
amount basis), immutable break records, escalation policy; per-domain rules only.
**Target:** 10 paths become 1; a new reconciliation is a rule, not 400 lines.
Impact 4, Effort 10, Priority 2.0 (B). Depends on P1.

---

## 4. Schema, API and contract surface

### P31. Single capability kernel: one declarative plugin manifest `[P]`
Seven registration seams (`base.py:242-249` constructs a `PluginManager` that
`:467` then overwrites; `ADDON_MANAGERS`; `PGAF_PLUGINS`; `PluginLoader`;
`SecurePluginLoader`; `plugin_hot_reload.py:221`; two hook registries in
`hooks.py:153` and `plugins/hooks.py:120`); `add_view` deduplicates by class
identity (`base.py:1000-1004`) so registration is order-dependent; each plugin is
instantiated twice (`base.py:500, 543, 553, 565`). One Pydantic manifest
(`models`, `views`, `permissions`, `menu`, `migrations`, `events`, `priority`,
`depends_on`) and one topological resolver.
**Target:** idempotent by construction, deterministic order, boot in one pass.
Impact 4, Effort 10, Priority 2.0 (A).

### P32. Build-time code generation for views, dashboards and mixin plumbing `[P]`
110 `*DashboardView` classes and roughly 110 industry plugin view files
(2.0 to 2.9k lines each) share one boilerplate shape; `code_headers.py` holds
17,499 lines of generated-source templates; `mixins/__init__.py:14-22` swallows
every import error, making 28,911 lines best-effort. Generate from the same
declarative spec, commit the output, and gate regeneration in CI.
**Target:** about 200k lines of hand-written plugin views leave the wheel; the
ERD becomes the only artifact a new entity needs.
Impact 5, Effort 16, Priority 1.6 (A). Depends on P31.

### P33. Type-erase the core, enforce pyright at the boundary `[P]`
310 `appbuilder.sm` string-keyed lookups across 59 files, no Protocol for the
appbuilder or security manager, 34.4 percent of functions unannotated, mypy on
three modules, no `pyrightconfig.json`. Declare `AppBuilderProtocol`,
`SecurityManagerProtocol`, `ViewProtocol`, `MigrationProtocol`; type the kernel;
quarantine the rest with a ratchet.
**Target:** pyright error count on the kernel 0; the untyped surface becomes a
documented boundary rather than an invisible one.
Impact 4, Effort 10, Priority 2.0 (B). Depends on P31.

### P34. One error taxonomy with stable codes `[P]`
945 exception classes outside tests; `exceptions.py` shadowed by the
`exceptions/` package (verified by import); `InvalidStatusTransitionError`
defined ten times; `str(e.orig)` returned to clients at six sites
(`api/__init__.py:1599`); `PGAF_API_SHOW_STACKTRACE` with one occurrence
(`:117`). One `ErrorCode` enum, one `ErrorEnvelope(code, message, request_id,
trace_id)`, HTTP mapping in one place, and a CI assertion that every 4xx/5xx
emits an enum member.
**Target:** runbook-able errors; no driver text at the boundary.
Impact 4, Effort 6, Priority 3.3 (A).

### P35. One migration authority with a live-catalog drift gate `[P]`
Ten mechanisms: one Alembic revision, two orphan scripts, 74 `CREATE TABLE` and
92 `ALTER TABLE` literals across 23 files, 22 `create_all()` sites, two
version ledgers that exclude each other, `PDL` money as `BigInteger` cents
against ORM `Numeric(10,2)` and `Numeric(6,2)`, ERD edits applied as raw DDL
that never touch ORM metadata. Alembic only; a CI job compares
`information_schema` against `Base.metadata` and fails on any delta.
**Target:** drift is a red build, not a production incident; `create_all` 22 → 0.
Impact 5, Effort 8, Priority 3.1 (A). Depends on P5.

### P36. Declarative integrity constraints as the only way to declare them `[P]`
665 of 1,265 foreign keys have no `ondelete`; zero `jsonb_typeof` checks on
JSONB columns that are later trusted (`models/tenant_models.py:310`
`permissions_override` is the dangerous one); soft delete on 7 of about 262
model classes. A `Base.__init_subclass__` assertion enforces `ondelete`,
`NOT NULL` with default or backfill plan, and `jsonb_typeof` on dict-intended
JSONB, raising at model-definition time.
**Target:** zero foreign keys without `ondelete`; JSONB shape violations
impossible to write.
Impact 4, Effort 6, Priority 3.3 (A). Depends on P35.

### P37. Contract-first API with generated client and conformance suite `[P]`
The OpenAPI spec exists (`api/__init__.py:467-503`) but pagination is offset
(`models/sqla/interface.py:214`) with `page_size` uncapped on the HTML path, and
every list metadata endpoint counts whole related tables (`api/__init__.py:1931`).
The schema becomes the contract: keyset cursors, bounded page size everywhere,
generated TypeScript client, and a conformance suite that runs the client
against a live server.
**Target:** list p95 under 200 ms at depth 10,000 (from an O(offset) scan);
client drift caught at build time.
Impact 4, Effort 10, Priority 2.0 (B). Depends on P20.

### P38. Policy pushdown: row-level and column-level security in query planning `[P]`
`security/sql_utils.py` exists (`SafeDDLExecutor`, identifier validation) but the
ERD, migration and report managers (`erd_manager.py:979-1210`,
`migration_manager.py:517`) interpolate identifiers freely. Postgres row-level
security is pushed into every query plan and identifier handling goes through
one quoting layer.
**Target:** SQL injection surface in library code 0, structurally.
Impact 4, Effort 6, Priority 3.3 (A). Depends on P8, P35.

---

## 5. Observability and operations

### P39. Zero-touch telemetry: instrument at import, not by opt-in `[P]`
`setup_telemetry` has no caller outside tests; `OTEL_ENABLED` in
`docker-compose.prod.yml:28` is inert; a request id is never minted
(`audit.py:225`); no `dictConfig` exists so all 1,047 `getLogger` files emit
unstructured strings. An entry-point-loaded instrumentation package, one
`before_request` that mints a UUID7 and honours inbound `traceparent`, and a
logging filter that injects it into every record.
**Target:** ≥ 95 percent of requests traced; 100 percent of log lines carrying a
request id.
Impact 4, Effort 4, Priority 5.0 (A).

### P40. One logging pipeline: structured, redacted, sampled, shipped `[P]`
A raw OAuth token is logged at `security/manager.py:142` (and in three `.bak`
copies); full M-Pesa payloads at `mpesa_service.py:146-148`; user-controlled
strings are interpolated raw into log lines in at least six places, so log
forging is possible. One `dictConfig` with JSON output, a redaction filter, a
control-character stripper, and template-keyed sampling.
**Target:** 100 percent machine-parseable logs; zero secret or PII occurrences,
enforced by CI grep and a runtime filter; log volume down 60 to 90 percent.
Impact 4, Effort 4, Priority 5.0 (A).

### P41. SLOs and error budgets over the semantic layer `[P]`
Zero occurrences of SLO, SLI or burn rate in the package; the error-rate
collector returns a hardcoded `0.1` (`database/monitoring_system.py:370`).
`pgappforge/semantic.py:65-130` already holds a `SemanticMetric` registry.
Business SLIs (`loan.disbursal_success_ratio`, `mpesa_stk_push_latency_p99`,
`approval_cycle_time`) with multi-window burn-rate alerts.
**Target:** ≥ 5 business SLIs; user-impact lead time under 30 minutes at 14.4×
burn.
Impact 4, Effort 6, Priority 3.3 (A). Depends on P39.

### P42. Dependency-graph health with synthetic transactions `[P]`
`health.py:24-32` is `SELECT 1`; the compose worker healthcheck runs a CLI
command that does not exist (`docker-compose.prod.yml:72`); nginx checks its own
`/health` (`:100-103`); the threshold monitor is never started
(`alerting/manager.py:38-52`). Liveness and readiness split, dependency graph
(migration head, broker, Redis, plugin registry, webhook reachability), and a
scheduled synthetic "log in and post a one-cent ledger entry".
**Target:** MTTD for a broken broker under 60 s; MTTR under 15 minutes because
the failing component is named.
Impact 4, Effort 5, Priority 4.0 (A). Depends on P39.

### P43. Metrics as a real backend, not a per-process deque `[P]`
`MetricsCollector` stores 1,000 values per metric in process memory behind four
gunicorn workers (`database/monitoring_system.py:116`); each worker sees a
quarter of the traffic; restarts erase history. Prometheus client with a
`/metrics` endpoint, per-worker labels, and OTel OTLP as the alternative.
**Target:** dashboards correct across workers; RED metrics available per route.
Impact 4, Effort 4, Priority 5.0 (A). Depends on P39.

### P44. Deterministic replay from a request journal `[P]`
`events/worker.py` already persists every dispatch. Journal every mutating
request with its inputs, its `after_flush` deltas and its outbound calls; a
`/replay/{id}` endpoint re-executes against a scratch database and diffs.
**Target:** customer-reported bugs reproducible on demand; converts the audit
trail from a compliance artefact into a debugging instrument.
Impact 4, Effort 8, Priority 2.5 (B). Depends on P6, P15.

### P45. Alerting with fingerprint dedup, routing and silences `[P]`
Two alert engines (`alerting/alert_manager.py` and `monitoring_system.py:429`),
a 653-line dead clone (`alert_manager_old.py`), per-rule cooldowns only
(`:580-592`), and a blocking webhook with no timeout
(`notification_service.py:280`). Fingerprint dedup, global rate limits,
maintenance silences, escalation to a real on-call path.
**Target:** one alert per incident; pager fatigue down ≥ 80 percent.
Impact 3, Effort 5, Priority 3.0 (B). Depends on P40.

---

## 6. Applied AI with evidence

### P46. Agentic SQL over the live catalog under a read-only role `[P]`
`get_db_schema` (`tools.py:416`) hands the model a text dump; there is no query
tool. A dedicated role with `default_transaction_read_only=on`,
`statement_timeout` 2 s, row cap, mandatory parameter binding, `EXPLAIN`
validation, and denial of `pgaf_*` and `ab_*` for non-admins. Separately, the
Cypher path (`database/graph_manager.py:280-286`) currently breaks out of its
dollar-quote; it becomes parameterised or AST-validated.
**Target:** business questions answerable from data rather than described;
write-capable credentials unreachable from the model.
Impact 5, Effort 8, Priority 3.1 (A). Depends on P13.

### P47. Citation-enforced grounded generation `[P]`
`rag_engine.py:1197-1275` attaches `sources` beside an unverified answer;
`confidence` (`:1322-1333`) is cosine similarity in disguise. Require every claim
to carry a resolvable source marker; drop unresolved claims; refuse when all
fail; derive confidence from verification rate.
**Target:** ungrounded claim fraction under 2 percent on a golden set (currently
unmeasured and structurally unbounded); over 95 percent of answers with a
verified citation.
Impact 5, Effort 6, Priority 4.2 (A).

### P48. Evaluation harness with golden sets and a CI gate `[P]`
No eval infrastructure exists; `tests/ci/test_ai_*` tests plumbing. Per-tenant
question sets scoring recall@5, citation precision, tool-call accuracy, refusal
correctness and cross-tenant memory isolation, run on every prompt, model or
chunking change, with an adversarial prompt-injection subset.
**Target:** every AI change ships with a measured delta; the P13 and P47 defects
would have been caught pre-merge.
Impact 4, Effort 6, Priority 3.3 (A). Depends on P47.

### P49. Hybrid retrieval with reranking `[P]`
Vector-only search (`ai_assistant/embeddings.py`) with an ivfflat index; the
keyword half exists and is unused (`mixins/full_text_search_mixin.py:316`
weighted `ts_rank_cd`). Reciprocal-rank fusion over both plus a cross-encoder
rerank of the top 50. Two embedding stores with different dimensions
(768 in `ai_assistant`, 1536 in `agent_memory.py:213`) become one, with a
model-version column and a mandatory reindex on model change.
**Target:** measurable recall@5 and MRR@10 on the golden set, with the largest
gain on identifier queries where vector search is weakest.
Impact 4, Effort 6, Priority 3.3 (A). Depends on P48.

### P50. Model-agnostic routing under cost and latency policy `[P]`
`LLMClient` distinguishes a strong and a fast model and routes between neither;
there is no retry, backoff or circuit breaker anywhere on the LLM path
(`nlp/client.py:120-132`); `ai/pipeline.py:189` calls `litellm.completion` with
no timeout; the RAG fallback (`plugins/erp/platform/rag/services.py:449-457`)
substitutes a chunk as the answer and labels it `fallback`; every default base
URL is `localhost:4000` while the platform gateway is elsewhere, and the default
embedding model is retired. Classification, per-route SLOs, per-tenant cost
ceilings, gateway failover, token and latency accounting persisted to the audit
table.
**Target:** cost per task down 40 to 70 percent; p95 within a declared SLO per
route; gateway availability measured rather than assumed.
Impact 4, Effort 8, Priority 2.5 (B).

---

## 7. Operator cognition: compile-to-UI, palette, grid, time travel

### P51. Compile-to-UI: the ERD emits the application `[P]`
Designing a schema crosses four menu entries (ERD designer, 57 routes and 751
lines of inline HTML at `views/erd_designer.py:1792-2543`; schema manager;
wizard builder; code generators) with no shared state, and the live designer is
one of three implementations (the 3,359-line `templates/erd/schema.html` is
dead). Every table becomes model, views, form validation, REST route, OpenAPI
entry and menu entry in one transaction.
**Target:** clicks-to-first-working-screen from about 15 to 2; codegen drift
structurally impossible.
Impact 5, Effort 16, Priority 1.6 (A). Depends on P32, P35.

### P52. Semantic command palette over the whole app `[P]`
700 view classes across 72 menu categories, no palette, no global search
(`command_palette`, `cmdk`, `Cmd+K` → 0 hits). One index built at runtime from
the SQLAlchemy registry, `appbuilder.baseviews` and permission names, ranked by
`pgappforge/semantic.py`, executing navigate, saved filter, open-by-UUID7 and
grant-permission.
**Target:** time-to-locate an arbitrary admin function from about 20 seconds to
under 1; pages per task 6 → 2.
Impact 4, Effort 6, Priority 3.3 (A). Depends on P20.

### P53. One virtual-scrolling data grid `[P]`
The list view is a 25-row table behind a GET form with `location.reload` in 124
templates; filters rebuild the page per column; select2 slave fields submit and
discard unsaved edits (`ab.js:75`); scroll and filter state are lost on every
navigation. One grid component with server keyset pagination, virtual windowing,
persisted column state and server-side bulk selection reusing the existing
`action_form` transport.
**Target:** rows rendered per second from 25 to thousands with O(1) DOM nodes;
time-to-first-row on a million-row table under 200 ms; bulk operations from N
round trips to 1.
Impact 4, Effort 14, Priority 1.4 (B). Depends on P37, P20.

### P54. Offline-first with real conflict resolution `[P]`
The service worker precaches `/` (`pwa.py:183`) and never invalidates
(`cache_name` literal at `:180`); background sync reads a queue nothing writes
(`:195-205`); offline edits are discarded server-side with HTTP 200
(`plugins/offline/sync_mixin.py:199-215`); the collaboration client 404s
(`templates/appbuilder/collaboration/widgets/collaborative_form.html:150`);
`flask_socketio` is an optional dependency with a mock fallback
(`collaboration/websocket_manager.py:14, 352`). Versioned rows with
`sync_version`, an IndexedDB operation log, 409 with the server row, and
field-level three-way merge using the model's own field set.
**Target:** offline edits lost 0 (currently all of them, silently); real-time
features actually initialising.
Impact 4, Effort 12, Priority 1.7 (B). Depends on P2.

### P55. Time-travel debugging for data and rules `[P]`
"Explain this value" is the dominant operator question and there is no answer:
three ERD implementations, error paths spread across 258 missing templates,
rules evaluated with no record of why they did or did not fire
(`plugins/rules/engine.py:389-393` swallows type mismatches; `RuleExecution`
has no version or tenant). With P2 and P6: an `AS OF <timestamp>` query surface,
a rule debugger replaying a decision against past state, and a per-record
provenance panel.
**Target:** time to diagnose a wrong computed value from hours to under a
minute; rule changes reviewed with their historical effect.
Impact 4, Effort 10, Priority 2.0 (B). Depends on P2, P6, P44.

### P56. Zero-to-production app synthesis from a declarative spec `[P]`
The 26 industry plugins are one template instantiated 26 times; the CLI
generators already hold 17,499 lines of templates. An operator describes a
business (parties, products, ledger accounts, approval chains, regulatory
regime) and the engine emits models, services, views, GL mappings, event schemas
and tests using the existing rules DSL, workflow model and chart of accounts.
**Target:** standing up a new SACCO or lender as configuration rather than 6,000
cloned lines.
Impact 5, Effort 20, Priority 1.3 (A). Depends on P1, P11, P32, P51.

### P57. Design tokens actually consumed, and a real content security policy `[P]`
`theming/__init__.py:48-57` generates `:root` tokens that zero templates use;
5,452 hex literals sit in templates and 3,149 in Python; CSP is
`unsafe-inline 'unsafe-eval'` with the nonce macro rendering empty
(`security_headers.py:80`, `baselib.html:130`). Promote the 23 working `--erp-*`
tokens to a real layer with a CI check on new literals, wire the nonce, then
remove both `unsafe-*`.
**Target:** theme change becomes a one-token edit; dark mode on every surface;
CSP that actually blocks stored XSS.
Impact 4, Effort 8, Priority 2.5 (B).

### P58. Accessibility and internationalisation as build gates `[P]`
No `lang` on the shell (`templates/appbuilder/init.html:8`); no `role="alert"`
on flash messages (`flash.html:5-9`); invalid `role="header"`; 43
`outline: none`; `<th>` inside `<div>` (`general/lib.html:265`); 275 native
`alert()` calls; about 9 percent of strings translated. A template linter and a
Playwright a11y gate on the CI suite.
**Target:** zero WCAG 2.4.7 and 4.1.2 violations on the 20 core screens;
translation coverage measurable per template.
Impact 3, Effort 6, Priority 2.5 (B). Depends on P32.

---

## 8. Testability and build integrity

### P59. In-process PostgreSQL for every test `[P]`
The CI default environments in `tox.ini` are SQLite while the product is
PostgreSQL-only; `requirements/base.txt` pins SQLAlchemy 1.4 while development
runs 2.0 on 3.14; `uv.lock` requires 3.14. One lockfile, one Python, one
database for tests, development and CI.
**Target:** SQLite-only defects (recent commits) become impossible; the tested
stack is the shipped stack.
Impact 5, Effort 4, Priority 6.3 (A).

### P60. Continuous verification with mutation testing on the money path `[P]`
`run_daily_aging` marks itself complete after swallowing a rollback error
(`fintech/lending/services.py:1104`); GL posting failures are `log.debug`
(`sacco/services.py:1089`); 12 of 20 fintech domains have no test file. Property
tests over ledger invariants (P1) plus mutation testing gated on the money path
and the tenant boundary.
**Target:** surviving mutants on the ledger and tenancy paths 0; every "silently
swallowed" path asserted.
Impact 4, Effort 10, Priority 2.0 (B). Depends on P1, P59.

### P61. Compile gate and real lint policy `[P]`
Five shipped files have not compiled since 2026-05-30; `flake8` reports 792,898
findings so the CI lint job can never be green; `.coveragerc` names a package
that does not exist; four `Makefile` targets pass a directory that does not
exist; 173 files still reference the upstream package. A `compileall` step first,
then a selected flake8 rule set, then the dead-code scan (`*_old`, `*.bak*`,
zero-reference packages) as a failing check.
**Target:** an uncompilable file cannot reach a release; dead-code count 0.
Impact 4, Effort 3, Priority 6.7 (A).

### P62. Upstream fork retirement `[P]`
`setup.py` declares no plugin entry-point group; dozens of shipped plugin views
import `flask_appbuilder` directly; 80 `FAB_*` config keys are rewritten by a
runtime shim (`base.py:170-183`); only three `DeprecationWarning` sites exist;
`__version__` says 0.90.0 while documentation says 4.8.0. Either finish the fork
(remove the last upstream imports, declare the entry points, one version) or
vendor upstream deliberately with a recorded base commit.
**Target:** zero upstream imports in shipped code; one version string; one
supported upgrade path.
Impact 4, Effort 8, Priority 2.5 (A). Depends on P31.

### P63. Structured concurrency test harness for background work `[P]`
`tests/test_concurrency_and_locking.py` and six sibling files exist against
modules that do not compile. Deterministic scheduler (P27) plus an in-process
broker and clock so worker, queue and lease behaviour are testable without a
distributed system.
**Target:** every lease, retry and dead-letter path covered by a test that fails
deterministically.
Impact 3, Effort 6, Priority 2.5 (B). Depends on P17, P27, P59.

---

## 9. Notification, document and feature-flag primitives

### P64. Durable notification bus `[P]`
Three `NotificationManager` classes, process-local templates, no retry, no
dead-letter, no delivery record; `email_queue` → 0 hits. One outbox-backed bus
with per-channel adapters, persisted templates and versioned preferences, so the
150+ `DomainEvent` classes become subscribable.
**Target:** every vertical can notify a customer without reimplementing or
omitting it; delivery attempts recorded.
Impact 3, Effort 8, Priority 1.9 (B). Depends on P6.

### P65. Document store with signed URLs, scanning and retention `[P]`
Three unrelated upload paths (`pgappforge/upload.py`, `filemanager.py`,
`mixins/doc_mixin.py`), no antivirus scan, no signed URL, no retention.
One store keyed by content hash with signed access, malware scanning at write,
and retention policy by document class.
**Target:** upload path count 3 → 1; every stored document scannable and
retention-enforced.
Impact 3, Effort 6, Priority 2.5 (B).

### P66. Feature flags as a first-class, tenant-scoped service `[P]`
A JSON blob on the tenant row (`models/tenant_models.py:199`). Flag definitions
with typed payloads, evaluation history, per-tenant overrides and kill switches
for any P-series capability.
**Target:** every rollout in this document shippable behind a flag with a
measured kill rate; no `if config.get(...)` scattered across the tree.
Impact 3, Effort 5, Priority 3.0 (B). Depends on P8.

### P67. Coverage as an SLO with per-risk-tier gates `[P]`
Coverage today measures a package that does not exist and gates nothing
(`.coveragerc` → `fail_under: 0.0`). Four tiers with different floors (money
movement 90, authorization 90, tenant isolation 95, plugin aggregate 60), line
and branch, gating the diff rather than the codebase: new code in a tier-1 module
without coverage fails the build.
**Target:** tier-1 coverage measured rather than asserted; zero regressions on
any pull request touching `plugins/fintech`, `plugins/erp/finance`, `tenants`,
`security`.
Impact 4, Effort 4, Priority 5.0 (A). Depends on P59.

### P68. Schema round-trip harness with a golden catalog `[P]`
One Alembic revision, zero executed migrations; `test_pdl.py:271` checks that the
string `def upgrade()` exists. A harness applies `base → head → base → head`
against PostgreSQL, snapshots `information_schema`, and diffs against a committed
golden file, so every revision is proven reversible and an upgrade from the
previous release converges on a fresh install.
**Target:** upgrade-from-previous-release proven identical to a fresh install.
Impact 4, Effort 5, Priority 4.0 (B). Depends on P35, P59.

### P69. Declarative-registry isolation fixture and mapper smoke gate `[P]`
One broken relationship in `plugins/erp/industry/clubs` failed
`configure_mappers()` and turned into 668 `InvalidRequestError` failures across
60 unrelated files; the whole CI run additionally executes against a permissive
`flask_appbuilder` stub installed by `tests/ci/conftest.py:25-49` with no
teardown. An autouse fixture snapshots and restores the registry and
`Base.metadata` per file, a subprocess smoke test calls `configure_mappers()` on
every plugin model, and the stub is deleted.
**Target:** one broken mapper fails exactly one test; every plugin model proven
mapper-valid; plugin tests exercising the real framework.
Impact 4, Effort 4, Priority 5.0 (A). Depends on P59.

---

## 10. Scored matrix

| # | Proposal | Impact | Effort (eng-weeks) | Priority | Band | Blocked by |
|---|---|---|---|---|---|---|
| P61 | Compile gate and real lint policy | 4 | 3 | 6.7 | A | — |
| P3 | Outbox and idempotency middleware | 5 | 6 | 4.2 | A | — |
| P4 | Webhook gateway | 5 | 5 | 5.0 | A | P3 |
| P9 | Tenant context as ContextVar | 4 | 4 | 5.0 | A | — |
| P18 | Atomic money mutations | 5 | 4 | 6.3 | A | P1 |
| P19 | Query budget interceptor | 4 | 4 | 5.0 | A | — |
| P39 | Zero-touch telemetry | 4 | 4 | 5.0 | A | — |
| P40 | Structured logging pipeline | 4 | 4 | 5.0 | A | — |
| P43 | Metrics as a real backend | 4 | 4 | 5.0 | A | P39 |
| P59 | In-process PostgreSQL for every test | 5 | 4 | 6.3 | A | — |
| P25 | Structured concurrency | 4 | 5 | 4.0 | A | P16 |
| P12 | Continuous authorization | 4 | 5 | 4.0 | A | P8 |
| P42 | Dependency-graph health | 4 | 5 | 4.0 | A | P39 |
| P13 | Capability-token sandbox | 5 | 6 | 4.2 | A | — |
| P47 | Citation-enforced generation | 5 | 6 | 4.2 | A | — |
| P8 | RLS as a framework invariant | 5 | 8 | 3.1 | A | — |
| P15 | Hash-chained audit ledger | 5 | 8 | 3.1 | A | P6 |
| P35 | One migration authority with drift gate | 5 | 8 | 3.1 | A | P5 |
| P46 | Agentic SQL under read-only role | 5 | 8 | 3.1 | A | P13 |
| P5 | Expand-contract schema evolution | 4 | 8 | 2.5 | A | — |
| P24 | Vectorised batch paths | 4 | 6 | 3.3 | A | — |
| P26 | Tenant-sharded state | 3 | 5 | 3.0 | A | P9 |
| P31 | Single capability kernel | 4 | 10 | 2.0 | A | — |
| P45 | Alerting with dedup and routing | 3 | 5 | 3.0 | B | P40 |
| P34 | One error taxonomy | 4 | 6 | 3.3 | A | — |
| P36 | Declarative integrity constraints | 4 | 6 | 3.3 | A | P35 |
| P38 | Policy pushdown | 4 | 6 | 3.3 | A | P8, P35 |
| P48 | AI evaluation harness | 4 | 6 | 3.3 | A | P47 |
| P49 | Hybrid retrieval with reranking | 4 | 6 | 3.3 | A | P48 |
| P27 | Deterministic race harness | 4 | 6 | 3.3 | B | P16 |
| P52 | Semantic command palette | 4 | 6 | 3.3 | A | P20 |
| P62 | Upstream fork retirement | 4 | 8 | 2.5 | A | P31 |
| P44 | Deterministic replay from a journal | 4 | 8 | 2.5 | B | P6, P15 |
| P41 | SLOs and error budgets | 4 | 6 | 3.3 | A | P39 |
| P2 | Bitemporal kernel | 5 | 12 | 2.1 | A | — |
| P6 | Event log with sequence and offsets | 4 | 8 | 2.5 | A | P1 |
| P21 | Incremental view maintenance | 4 | 8 | 2.5 | B | P6 |
| P50 | Model-agnostic routing | 4 | 8 | 2.5 | B | — |
| P57 | Design tokens and real CSP | 4 | 8 | 2.5 | B | — |
| P58 | Accessibility and i18n gates | 3 | 6 | 2.5 | B | P32 |
| P63 | Background-work test harness | 3 | 6 | 2.5 | B | P17, P27 |
| P65 | Document store | 3 | 6 | 2.5 | B | — |
| P66 | Feature-flag service | 3 | 5 | 3.0 | B | P8 |
| P64 | Durable notification bus | 3 | 8 | 1.9 | B | P6 |
| P1 | Event-sourced double-entry ledger | 5 | 20 | 1.3 | A | — |
| P29 | Settlement and netting engine | 5 | 20 | 1.3 | A | P1 |
| P56 | Zero-to-production app synthesis | 5 | 20 | 1.3 | A | P1, P11, P32, P51 |
| P11 | Relationship-based policy engine | 4 | 12 | 1.7 | B | P8 |
| P14 | Verifiable tenant identity | 3 | 10 | 1.5 | B | P8 |
| P54 | Offline-first with real conflicts | 4 | 12 | 1.7 | B | P2 |
| P10 | Permission-graph compiler | 4 | 10 | 2.0 | A | P8 |
| P16 | Single-writer execution engine | 4 | 10 | 2.0 | A | P9 |
| P17 | Durable job queue with leases | 5 | 10 | 2.5 | A | — |
| P20 | CQRS read models | 5 | 16 | 1.6 | B | P6 |
| P22 | Logical-decoding CDC | 4 | 12 | 1.7 | B | P6 |
| P30 | Unified reconciliation engine | 4 | 10 | 2.0 | B | P1 |
| P32 | Build-time code generation | 5 | 16 | 1.6 | A | P31 |
| P33 | Type-erase the core | 4 | 10 | 2.0 | B | P31 |
| P37 | Contract-first API | 4 | 10 | 2.0 | B | P20 |
| P51 | Compile-to-UI from the ERD | 5 | 16 | 1.6 | A | P32, P35 |
| P53 | Virtual-scrolling data grid | 4 | 14 | 1.4 | B | P20, P37 |
| P55 | Time-travel debugging | 4 | 10 | 2.0 | B | P2, P6, P44 |
| P60 | Continuous verification with mutation testing | 4 | 10 | 2.0 | B | P1, P59 |
| P7 | Deterministic replay and simulation | 4 | 10 | 2.0 | A | P1, P6 |
| P28 | Lock-order analysis | 3 | 4 | 3.8 | B | — |
| P67 | Coverage as an SLO with per-tier gates | 4 | 4 | 5.0 | A | P59 |
| P69 | Registry isolation fixture and mapper smoke gate | 4 | 4 | 5.0 | A | P59 |
| P68 | Schema round-trip harness with golden catalog | 4 | 5 | 4.0 | B | P35, P59 |
| P23 | Citus partitioning | 3 | 16 | 0.9 | C | P8 |

Sixty-nine proposals are recorded; the fifty required are P1 to P50. P51 to P69
are included because the roadmap's later phases depend on them.

---

## 11. Cross-cutting measurable outcomes

| Metric | Today | Target after the set |
|---|---|---|
| Lost updates and double-spends under concurrency | unbounded | 0, by construction (P1, P18, P3) |
| Background jobs losing tenant context | unbounded | 0 (P9, P16) |
| Unauthenticated money callbacks accepted | any POST | 0 (P4) |
| Cross-tenant reads via dev override or sentinel | possible | 0 (P8, P14) |
| Cross-tenant authorization logic expressed as code | about 100 percent | under 20 percent (P11) |
| Ungrounded AI claims | unbounded | under 2 percent (P47, P48) |
| List endpoint p95 at 100M rows | seconds | under 80 ms (P20, P37) |
| Boot with 1,000 views | minutes (thousands of commits) | under 3 s (P20, P31) |
| Traced requests | 0 | over 95 percent (P39) |
| Structured log lines | 0 | 100 percent (P40) |
| Days to stand up a new vertical | weeks of cloned code | under 1 hour (P32, P56) |
| Clicks to first working screen for a new entity | about 15 | 2 (P51) |
| Uncompilable shipped files | 5 | 0 (P61) |
