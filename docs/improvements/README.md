# PgAppForge Codebase Audit, 2026-10-03

Audit of revision `925c90d8` on branch `fix/production-readiness-blockers`.
Method: ten parallel auditors, one per analytical dimension, each citing
`path:line`; every headline claim then re-verified in-session by compilation,
import, AST, grep or targeted read.

| Document | Contents |
|---|---|
| `00-baseline-and-method.md` | Measured facts: scale, dependency reality, dead code, per-dimension situation |
| `01-enhancements.md` | 50 non-incremental proposals (P1 to P50) plus 16 supporting (P51 to P66), scored Impact × 5 / Effort |
| `02-defect-catalogue.md` | 132 findings (S, C, V, O, P, A, U, T), disjoint from the proposals, with verification tags |
| `03-capability-gap-analysis.md` | ERP and fintech domain matrix, horizontal-layer scores, prior assertion to close gaps |
| `04-roadmap.md` | Eight phases, dependency graph, critical path, resource allocation |

## Verdict

The platform has the breadth of a Tier-1 ERP on paper and the defects of a
prototype in the money path. Eleven critical findings, fifty-two high. The ones
that matter most:

- **The wallet loses money under concurrency.** The debit path reads a balance,
   checks it in Python, mutates the ORM attribute and commits; the
   `SELECT FOR UPDATE` helper that exists in the same file is never called from
   it (`wallet/models.py:214-272`).
- **The M-Pesa callback is unauthenticated and replayable** and credits the
   requested amount even when the collected amount differs
   (`wallet/mpesa_service.py:307-395`).
- **The AI permission decorator cannot deny** because `abort(403)` is caught
   (`ai_governance.py:166-180`), and the agent shell allowlists `find` without
   blocking `-delete` (`ai_assistant/tools.py:317`).
- **Cypher is interpolated into dollar-quoted SQL** (`database/graph_manager.py:280-286`).
- **Tenant identity is client-selected** on any dotted-quad host
   (`models/tenant_context.py:152-165`), and a string sentinel
   (`multitenancy/rls.py:79`) disables every row-level-security policy.
- **Nothing is observable.** Telemetry is never initialised, the alerting
   monitor is never started, no request id is ever minted, and the worker
   healthcheck runs a CLI command that does not exist.
- **Five shipped files have not compiled since 2026-05-30** and `flake8`
   reports 792,898 findings, so CI lint can never be green.
- **Four dependency stacks** are declared for the same package; CI tests
   SQLAlchemy 1.4 while development runs 2.0.

None of these was introduced recently; all were invisible because the gates that
should have caught them (lint, coverage, drift detection, alerting, audit) are
themselves unwired.

## The one idea

Every money defect is a read-modify-write on a scalar, and there are five
different balance representations. Fixing them per site will not hold. The
roadmap therefore starts with an event-sourced double-entry ledger (P1) and
makes everything else either depend on it or immune through it. Second path: one
event log with sequence numbers (P6) feeding read models (P20), which is what
makes boot, lists, dashboards and replay cheap. Everything in between is
trust and build integrity that must be done first because each is a way the
platform fails silently.

## Reading order for an engineer

1. `02-defect-catalogue.md` sections S, C and V are the ones with money or
   access consequences; A1 to A3 determine whether any of it can be reproduced.
2. `04-roadmap.md` Phase 0 is one week and needs no decisions.
3. `01-enhancements.md` P1, P3, P4, P8, P18 are the five items in band A with no
   prerequisites.
