# PgAppForge Phased Implementation Roadmap

Revision `925c90d8`. Reads with `01-enhancements.md` (proposals P1 to P66),
`02-defect-catalogue.md` (defects D-prefix), and `03-capability-gap-analysis.md`.

The roadmap has one organising idea: **the ledger spine comes first**. Every
money defect in the catalogue is a read-modify-write on a scalar, and every fix
applied to the current design is a per-site patch that the next service will
reintroduce. P1 (event-sourced double-entry ledger) converts that class from
"defect" to "impossible", and it is the prerequisite for seven other proposals.

---

## 1. Phase 0: stop the bleeding (week 1, no prerequisites)

Nothing here needs a design decision. Each item removes a way the platform can
fail silently in production.

| Item | Work | Defects closed |
|---|---|---|
| P61 | `compileall` as the first CI job on `pgappforge/`; fix the five broken files; flake8 with a `select` list; `.coveragerc` and `Makefile` pointed at `pgappforge`; CI check failing on `*_old`, `*_bak*`, zero-reference packages | A1, A14 |
| P59 | One `uv` lockfile for Python 3.14; regenerate `requirements/` from it; CI, tox and Docker all install it; PostgreSQL-only test environments replace the SQLite defaults | A3 |
| S1, S7 | Remove the `except Exception` around `abort(403)` in `ai_governance.py`; remove the `X-Internal-Request` bypass | S1, S7 |
| S4, S5 | Delete the OAuth-token log line and the three `.bak` copies; map `IntegrityError` to a stable code; default `PGAF_API_SHOW_STACKTRACE` to false with a production override | S4, S5, O11 |
| S8, S9 | Delete the `X-Tenant-ID` / `?tenant_id=` dev override; remove the `SYSTEM` sentinel; startup assertion that the dev path is unreachable when `FLASK_ENV=production` | S8, S9 |
| S6 | Guard `mark_completed` on `status == PENDING`; reject amount and phone mismatch; unique constraint on `(mpesa_account_id, mpesa_receipt_number)`; IP allow-list at the proxy | S6 |
| V1, V2 | Forbid last-write-wins on monetary and quantity fields; make conflict detection raise instead of returning "no conflict" | V1, V2 |
| O2, O6 | Mint a request id in one `before_request`; call `setup_telemetry` from the app factory; implement `flask fab worker-status` or replace the healthcheck | O2, O6, O5 |

**Exit criteria:** `python -m compileall pgappforge` clean; CI green; zero
`except Exception` around an `abort`; zero client-visible driver text; one
request id present on every audit row and log line.

---

## 2. Phase 1: the ledger spine (weeks 2 to 7)

Critical path start. Two engineers on P1, one on P3 and P4 in parallel, one on
P18 verification.

| Week | Work |
|---|---|
| 2 to 3 | P1 design: journal schema (`entries`, `accounts`, `postings`, idempotency key unique index), double-entry invariant as a database constraint, `rebuild_balances()`. Dual-write `wallet` alongside the new journal with a reconciliation job comparing the two |
| 4 | P3 idempotency middleware; P4 webhook gateway; both land before any balance moves through the journal |
| 5 | P18: convert `wallet/models.py:214-272` and `:503-512`, `fintech/lending/services.py:790-809`, `core_banking/services.py:508, 685, 1207, 1279, 2030` to conditional statements; add the replay harness from P60 |
| 6 | Migrate the remaining lending, sacco and ERP GL postings; make `fintech/lending/services.py:872/889` write one journal entry instead of two |
| 7 | Flip reads to the journal projection; remove `balance` writes everywhere; make `rebuild_balances()` a test |

**Exit criteria:** the replay harness fires every money request 100 times with
one effect; `SELECT sum(debits) - sum(credits)` is 0 for every account at every
prefix; no module contains `balance +=`.

Defects closed: C1, C2, C3, A1 (lending double-post), A2, A13, A14, A39, A40,
A41, V3, V4.

---

## 3. Phase 2: trust and tenancy (weeks 4 to 11, overlaps Phase 1)

Prerequisite for P10 to P14, P23, P26, P36, P38, P66.

| Weeks | Work | Depends on |
|---|---|---|
| 4 to 6 | P8: `FORCE ROW LEVEL SECURITY` mandatory for every `tenant_id` column; boot-time assertion against `pg_policies`; P9 `ContextVar` tenant with the work-item envelope | — |
| 6 to 8 | P12 session-version revocation; P36 declarative integrity constraints (needs P35's single migration authority for the FK `ondelete` sweep) | P35 |
| 8 to 11 | P10 permission-graph compiler; P11 relationship policy engine for the approval path | P8 |
| 9 to 11 | P15 hash-chained audit ledger with signed checkpoints; P3 already guarantees no dropped events | P6 or a direct P15 build |

**Exit criteria:** cross-tenant findings 0 in the security suite; revocation
effective within one request; audit coverage of mutating paths 100 percent;
`jsonb_typeof` checks on every dict-intended JSONB column.

---

## 4. Phase 3: build integrity and schema truth (weeks 2 to 10, parallel)

Runs alongside Phases 1 and 2 because it is mostly deletion and constraint work.

| Weeks | Work |
|---|---|
| 2 to 5 | P35: Alembic as the only migration path; generate the initial revision from existing metadata; CI drift job comparing `information_schema` to `Base.metadata` in report mode, then enforcing; `create_all` 22 → 0 |
| 4 to 7 | P5 expand-contract engine replacing `erd_manager.py:1056-1100` and `erd_schema_manager.py:752-815` |
| 6 to 9 | P34 error taxonomy; delete `exceptions.py` (shadowed by the package) and collapse 945 classes to about 15 |
| 8 to 10 | P62 upstream fork retirement: remove the remaining `flask_appbuilder` imports from shipped plugin views, declare the plugin entry-point group, one version string |

**Exit criteria:** `alembic check` clean on every PR; no `ADD COLUMN NOT NULL`
without a backfill plan in the tree; one error envelope at the API boundary; zero
upstream imports.

---

## 5. Phase 4: execution and observability (weeks 8 to 16)

| Weeks | Work | Depends on |
|---|---|---|
| 8 to 11 | P39 zero-touch telemetry; P40 structured logging; P43 metrics backend; P42 dependency-graph health with synthetic transactions | — |
| 9 to 13 | P16 single-writer execution engine (workers never touch `db.session` or `flask.g`); P25 structured concurrency; P17 durable job queue with leases | P9 |
| 13 to 16 | P41 SLOs and error budgets; P45 alert routing; P44 request journal for replay | P39, P6 |
| 14 to 16 | P19 query budget interceptor; P24 vectorised batch paths; P18 retarget at any N+1 the interceptor catches | P19 |

**Exit criteria:** ≥ 95 percent of requests traced; every log line structured
and redacted; `run_daily_aging` safe on two workers and retried; every list
endpoint under 5 queries; alerting fires and is routed.

---

## 6. Phase 5: the event spine (weeks 10 to 22)

The second critical path. Starts only after Phase 1's journal is the source of
truth, because the event log is the journal's generalisation.

| Weeks | Work | Depends on |
|---|---|---|
| 10 to 14 | P6 event log with `(stream_id, sequence)` and consumer offsets; the existing `events/worker.py` becomes the only dispatcher | P1 |
| 14 to 18 | P20 CQRS read models for lists, menus, permission sets and dashboards; P21 continuous aggregates; boot stops committing per permission | P6 |
| 16 to 20 | P22 logical-decoding CDC for cache invalidation and read replicas; P37 contract-first API with keyset cursors | P6, P20 |
| 18 to 22 | P55 time-travel debugging; P7 deterministic replay and simulation; P64 notification bus | P2, P6, P44 |

**Exit criteria:** boot under 3 s with 1,000 views; list p95 under 80 ms at
100M rows; any balance or read model rebuildable from the log.

---

## 7. Phase 6: kernel consolidation (weeks 12 to 26, parallel tail)

| Weeks | Work | Depends on |
|---|---|---|
| 12 to 16 | P31 single capability kernel: one manifest, one resolver, one hook registry; `plugin_hot_reload` becomes dev-only | — |
| 16 to 22 | P32 build-time generation for the 110 dashboards, the 26 industry plugins and the mixin library; CI regeneration check | P31 |
| 20 to 24 | P33 type-erase the core, pyright at the boundary | P31 |
| 22 to 26 | P51 compile-to-UI from the ERD; P53 virtual-scrolling grid; P52 command palette | P32, P35, P20, P37 |
| 24 to 26 | P58 accessibility and i18n gates; P57 design tokens and real CSP | P32 |

**Exit criteria:** `flask_appbuilder` import 0; one registration path; new
dashboard under 5 minutes; new entity from graph edit to working screen in two
clicks.

---

## 8. Phase 7: verticals and applied AI (weeks 18 to 34)

| Weeks | Work | Depends on |
|---|---|---|
| 18 to 24 | P30 unified reconciliation engine; P29 netting and settlement engine | P1 |
| 20 to 26 | P13 capability-token sandbox; P46 agentic SQL under a read-only role | P31 |
| 24 to 30 | P47 citation-enforced generation; P48 evaluation harness; P49 hybrid retrieval; P50 model routing | P47 |
| 28 to 34 | P56 zero-to-production app synthesis; P14 verifiable tenant identity; P23 Citus partitioning | P1, P11, P32, P51 |

**Exit criteria:** every money endpoint safe against double submission; every
AI answer carries a verified citation or refuses; a new SACCO exists as a spec.

---

## 9. Dependency graph

```
Phase 0: P61, P59  (no prerequisites; gate everything)

P1 ledger ──┬─► P18 atomic mutations ──► P60 property tests
            ├─► P3 outbox/idempotency ──► P4 webhook gateway
            ├─► P6 event log ──► P20 CQRS ──► P37 contract API ──► P53 grid
            │        │                     └─► P52 palette
            │        ├─► P7 replay/simulation
            │        ├─► P15 audit chain ──► P44 request journal ──► P55 time travel
            │        ├─► P21 aggregates
            │        ├─► P22 CDC
            │        └─► P64 notification bus
            ├─► P29 netting
            ├─► P30 reconciliation
            └─► P56 app synthesis

P8 RLS invariant ──► P9 ContextVar ──► P16 single-writer ──► P25 structured concurrency
        │                    └─► P26 tenant sharding         └─► P27 race harness ──► P63
        ├─► P10 permission compiler
        ├─► P12 instant revocation
        ├─► P11 policy engine ──► P56
        ├─► P14 tenant attestation
        ├─► P23 Citus
        ├─► P36 integrity constraints (also needs P35)
        ├─► P38 policy pushdown (also needs P35)
        └─► P66 feature flags

P35 migration truth ──► P36, P38, P51, P5 expand-contract
P31 capability kernel ──► P32 codegen ──► P51, P56, P58
                           └─► P33 pyright, P13 sandbox
P39 telemetry ──► P40 logging ──► P45 alerting
           ├─► P43 metrics
           ├─► P42 health
           └─► P41 SLOs
P47 grounded generation ──► P48 evals ──► P49 retrieval ──► P50 routing
```

## 10. Critical path

```
P0 (week 1)
 └─► P1 ledger design (wk 2-3)
      └─► dual-write + reconciliation (wk 4-7)
           └─► P6 event log (wk 10-14)
                └─► P20 CQRS read models (wk 14-18)
                     └─► P37 contract API (wk 16-20)
                          └─► P53 grid / P51 compile-to-UI (wk 22-26)
                               └─► P56 synthesis (wk 28-34)
```

Length: about 34 weeks. The two levers that shorten it are P59 (one stack by
week 1, so nothing is built against the wrong SQLAlchemy) and P35 (one schema
authority by week 5, so P5, P36, P38 and P51 are not each re-deriving what a
table is). Slipping either by more than three weeks moves the tail past two
quarters.

## 11. Resource allocation

Assumes a team of six: two backend engineers on the ledger, one on tenancy and
policy, one on build and schema, one on execution and observability, one on the
kernel and frontend. Adjust effort in engineer-weeks from the matrix in
`01-enhancements.md`.

| Phase | Duration | People | Engineer-weeks | Parallel with |
|---|---|---|---|---|
| 0 | 1 week | 3 | 3 | — |
| 1 | 6 weeks | 3 | 18 | 2, 3 |
| 2 | 8 weeks | 3 | 24 | 1, 3 |
| 3 | 9 weeks | 2 | 18 | 1, 2 |
| 4 | 9 weeks | 3 | 27 | 3, 5 |
| 5 | 13 weeks | 3 | 39 | 4, 6 |
| 6 | 15 weeks | 3 | 45 | 5, 7 |
| 7 | 17 weeks | 3 | 51 | 6 |
| **Total** | **34 weeks** | **6 peak** | **225** | |

Review gates at the end of each phase: the exit criteria above are the gate.
Phase 1 and Phase 0 gates are non-negotiable; the rest may slip one phase
without compounding, except P35 and P31 which gate four and three downstream
items respectively.

## 12. What is explicitly not in the plan

- **Cosmetic frontend work.** The 4,379 lines of legacy templates and 5,576 lines
  of dead ERD templates are deleted, not restyled.
- **Adding a sixth notification manager or a seventh plugin registration path.**
  Both are replaced (P64, P31).
- **Per-site patches for the wallet concurrency class.** P18 converts the
  pattern; patching `add_transaction` alone would leave `transfer_to`,
  `withdraw`, `place_hold`, `release_hold` and `expire_stale_holds` with the same
  defect.
- **Keeping the current upgrade path.** P62 either finishes the fork or vendors
  upstream deliberately; the middle state (dozens of upstream imports, two
  versions, a runtime shim) is what produced the five uncompilable files.
