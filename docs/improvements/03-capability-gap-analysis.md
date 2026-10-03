# PgAppForge Capability Gap Analysis

Revision `925c90d8`. Scope: `pgappforge/plugins/erp/` (309,230 lines, 859 files,
about 728 model classes across 11 domains), `pgappforge/plugins/fintech/`
(69,103 lines, 20 domains), `pgappforge/wallet/`, and the horizontal layers the
verticals depend on. Claims tagged `[V]` were re-verified in this session; the
rest are from auditor code reading of the cited lines.

---

## 1. Two systemic facts that shape everything else

**1.1 There is no shared ledger. `[V]`**
`wallet/` contains no reference to a ledger, journal or GL account. Fintech
modules keep money as integer cents; `wallet` keeps `Numeric(15,2)` Decimals.
`fintech/core_banking/models.py:398` maintains its own journal, bridged to the
ERP general ledger at `plugins/erp/finance/gl/` non-fatally. `fintech/lending`
posts every event to both (`services.py:872` then `:889` on repayment; `:589` and
`:600` on disbursement; `:1371` and `:1391` on write-off; `:1465` and `:1481` on
recovery), and nothing reconciles them.

**1.2 Failure is silent by design.**
57 `except Exception: pass` blocks in the ERP tree (25 in `platform/`, 14 in
`operations/`), 104 in fintech. The ones that matter sit on the general-ledger
posting path: `plugins/erp/crm/commerce/services.py:620` (order placement),
`:699` (payment confirmation), `plugins/fintech/sacco/services.py:1089`.
`plugins/erp/finance/gl/services.py:846-855` returns `None` when no open
accounting period exists, and every caller treats `None` as success. The order
ledger and the GL diverge with nothing raised.

---

## 2. Domain matrix: present, thin, absent

Legend: **P** present, **T** thin or stubbed, **A** absent. Comparator column
names the platform whose shipping depth the cell does not reach.

### 2.1 Fintech domains

| Domain | Present | Thin | Absent | Gap against |
|---|---|---|---|---|
| core_banking | double-entry (`services.py:298, 385, 523`), journal, balance (`:1402`), interest accrual (`:880`), statements (`:1489`), holds (`:1207`), transfers (`:598`), Islamic products (`:3065`), teller (`:332`) | overdraft (an enum value at `models.py:117`, no limit model); statement PDF (a field at `:838`, one CSV renderer) | sweeps, reconciliation, close of books, FX (lives only in `treasury`; `FX_SUSPENSE` string at `services.py:147`) | TigerBeetle (event-sourced ledger), Modern Treasury (netting, sweeps) |
| lending | origination (`:147`), underwriting (`:342`, docstring "simplified" `:364`), disburse (`:505`), schedule (`:674`), servicing (`:764`), write-off (`:1347`), restructure (`:1261`), IFRS 9 (`:1192`) | decisioning (CRB pull-only at `crb_adapter.py:89, 214, 350`; PD hardcoded at `:1210-1229`); collections (`run_daily_aging:990` only); bureau reporting (no submission method) | — | Alloy, Crediteo (decisioning, collections) |
| payments | initiate (`:215`), authorise (`:402`), settle (`:505`), batch settle (`:1236`), reconcile (`:1501`), pain.001 (`:751`), KEPSS pacs.002 (`kepss_adapter.py:223`), PesaLink | mandates (pull by standing order only) | refunds, chargebacks, disputes, 3DS, payout | Stripe, Adyen, Flutterwave |
| treasury | FX only | revaluation is naive mark-to-market: `services.py:886` "book rate approximated as 1.0" | cash position, forecasting, cash pooling, investments (`sasra.py:445` says so) | SAP Treasury, Kyriba |
| swift `[V]` | FIN/MT: MT103 (`:97`), MT900 (`:728`), gpi (`:264`) | — | pacs.009, camt.053, any MX / ISO 20022 (zero occurrences repo-wide `[V]`) | Modern Treasury, any ISO 20022-native bank |
| card_issuing | virtual card lifecycle (`:301-459`), AES-256-GCM PIN (`:514`), BIN (`:51`), Luhn (`:109`) | auth network (one method, `:673`); 3DS (HMAC-TOTP only, `:628`) | physical issuance, disputes, EMV tag data | Marqeta, issuing processors |
| sacco | members, shares, savings, loans, dividends (`:484, 1196, 1270, 568`), FOSA bridge, SAS1/2/3 | regulatory ratios derived from a proxy balance sheet, not the ledger (`sasra.py:173, 243, 246, 445`) | AGM (only a comment at `models.py:486`), board governance (zero governance hits `[V]`) | Fenix, Mambu SACCO modules |
| regulatory | AML (`:217`), sanctions with Jaro-Winkler fuzzy match (`:2074`), SAR/GoAML XML (`:802, 151`), capital adequacy (`:1084`), Basel III stress (`:1281`), IFRS 9 with staging (`:1377`), CBK returns (`:1704-1738`) | KYC: `_get_customer_risk_rating` is a documented stub `[V]` at `services.py:488-492` | FATCA, CRS (two incidental hits, no implementation `[V]`) | ComplyAdvantage, Sardine, persona |
| mobile_money | send, reverse, EOD reconciliation (`services.py:2722`), agent float, idempotency (`models.py:187`, `services.py:541`) | — | dispute handling, float insurance, tiered KYC | M-Pesa, Paga, Cellulant |
| remittance, trade_finance, wealth_management, robo_advisory, insurtech, agency, pswitch_adapter, bnpl, embedded_finance, banking_api | present as state machines with services | — | 12 of 20 domains have no test file `[R]` | — |

### 2.2 ERP domains

| Domain | Present | Thin or stubbed | Absent |
|---|---|---|---|
| finance | GL, AR, AP, tax, FPA, treasury | `grc/compliance/models.py` is an empty stub (`__all__ = []`, TODO at line 3); `views.py:147` prints `TODO:` as a table row to the user | — |
| hcm | payroll, personnel, travel, performance, talent (2,076 lines) | `hcm/recruiting/services.py` is 127 lines with a no-op `session` bug (`:23, 43, 62`) and is fully shadowed by `hcm/talent`; payroll has no immutability lock on a paid run; `TaxWithholding` is an effective-rate record, not a statutory bracket table (`payroll/services.py:146`) | — |
| crm | contacts, leads, pipeline, commerce, subscriptions | two subscription engines (`crm/subscriptions` 1,107 lines vs `crm/commerce` 1,165); `crm/loyalty` service 53 lines; `crm/territory_management` service 38 lines with a JSONB rule DSL (`models.py:16`) never evaluated | — |
| operations | fleet, manufacturing, maintenance | `operations/lean` is 4 models and a 101-line service | — |
| industry (26 plugins, 71,344 lines) | one template instantiated 26 times: `__init__.py`/`models.py`/`services.py`/`views.py`/`events.py`, 2.0 to 2.9k lines each, identical class shapes (`XService`, `XNotFoundError`, 4 to 7 CRUD views) | — | — |

### 2.3 Horizontal layers the verticals depend on

Scored on presence, depth and whether the enforcement is real. Zero is the
score for anything with a docstring claim and no code.

| Layer | Score | State |
|---|---|---|
| Workflow engine | 8/10 | versioned definitions (`workflow/engine.py:140` snapshots the version at instance start, `:540` creates a new one); no lease claim, so double escalation under two pollers |
| Event log | 7/10 | `erp/foundation/models.py:716` append-only with correlation and causation; `events/worker.py` has `SKIP LOCKED`, backoff and a dead-letter queue; no sequence number and no consumer offsets (`replay`/`sequence`/`ordering` → 0 hits), so no projection can be rebuilt |
| Job scheduler | 7/10 | three unconnected mechanisms: `events/worker.py` (368 lines), `erp/platform/scheduler/` (1,117 lines), Celery under `process/async/`; one bare in-process thread at `workflow/__init__.py:414-441` that is not safe under multiple gunicorn workers |
| Audit ledger | 7/10 | real hash chain at `plugins/audit/__init__.py:84-86`; "append-only" is a docstring with no database trigger; three competing `AuditLog` models (`pgappforge/audit.py:87`, `plugins/audit/models.py:10`, `wallet/models.py:1721`) and neither of the first two is wired |
| Rules engine | 7/10 | real evaluator (`plugins/rules/engine.py`) with a YAML DSL and compile/decompile (`dsl.py:247, 353`); `Rule` has no version, no `tenant_id`, no `effective_from` `[V]`; type mismatches on money comparisons are swallowed (`engine.py:389-393`) |
| Double-entry ledger | 5/10 | a good ledger exists in `core_banking`; it is not the shared primitive (see 1.1) |
| Reconciliation | 4/10 | 11 `def *reconcil*` implementations `[V]`, no shared match/tolerance/break contract |
| Policy engine | 4/10 | `PolicyEngine`, `Oso`, `rego` → 0 hits. Authorization is role-permission plus an opt-in row-scoping mixin |
| Document store | 3/10 | three unrelated paths, no antivirus scan, no signed URLs, no retention |
| Idempotency | 3/10 | done correctly in `mobile_money` (`models.py:187`, `services.py:541`); absent from `wallet`, from `core_banking.transfer` (free-text `reference`, `models.py:493`), from `banking_api`'s transfer endpoint (`api.py:776`) |
| Feature flags | 3/10 | a JSON blob on the tenant row (`models/tenant_models.py:199`) |
| Anti-fraud scoring | 3/10 | five independent signal tables (`lending/models.py:1501`, `sacco/models.py:1629`, `regulatory/models.py:1001`, `mobile_money/models.py:1054`) and one private scorer; `regulatory/services.py:293` leaves `fraud_score` `None` and `:334` silently skips the AML rule |
| Settlement and netting | 3/10 | `netting` → 0 occurrences repo-wide `[V]`; nine unrelated settlement state machines (payments, pswitch_adapter, bnpl, material_ledger, swift, treasury, mobile_money, sacco, trade_finance) |
| Tenancy isolation | 3/10 | `plugins/tenancy/__init__.py` docstrings describe row-level isolation and RLS; the file has no enforcement code `[V]`; the real machinery is opt-in per model (`mixins/rls_mixin.py`, `multitenancy/rls.py`) and bypassable (`models/tenant_context.py:155`, `multitenancy/rls.py:79`) |
| Notification bus | 2/10 | three `NotificationManager` classes `[V]` (`collaborative/communication/notification_manager.py`, `database/collaboration_system.py`, `mixins/statemachine_mixin.py`); templates in a process-local dict; `email_queue` → 0 hits; no retry, no dead-letter, no delivery-attempt durability |
| Data hub / canonical entity | 2/10 | 552 lines, `ImportJob` and `ExportJob` only; no canonical customer or entity model |

### 2.4 Duplication that is a gap in disguise

Standing orders are implemented four times (`sacco/services.py:902`,
`payments/services.py:785`, `mobile_money/services.py:2224`,
`lending/services.py:2777`). Two ECL implementations (`lending:1192`,
`regulatory:1377`). Two agent/float models about 80 percent identical
(`mobile_money`, `agency`). `FleetService` declared twice in
`operations/fleet/services.py`. Eight ERP modules have no `views.py` at all
(`hcm/analytics`, `finance/entities`, `crm/contracts`, `platform/documents`,
`platform/whatsapp`, `crm/pos`) and so have no way to express per-record authority.

---

## 3. What this costs the operator

- **A lender cannot answer an IFRS 9 restatement question.** ECL is computed and
  then overwritten by a second method (`lending/services.py:1092` sets
  `provision_amount_cents` from a percentage table at `:76`; `:1192`
  `calculate_ecl_provision` overwrites the same two columns with PD × LGD × EAD
  where PD and LGD are hardcoded constants). Neither books an expense or an
  allowance, so there is no provision to restate.
- **Interest is counted twice and cannot be reconciled.** Daily accrual
  (`lending/services.py:1917`) adds to `accrued_interest_cents`, but the
  repayment waterfall (`:802`) debits `outstanding_interest_cents`, which is only
  set to zero at disbursement. Accrued interest grows without bound and the
  waterfall's interest step always sees zero.
- **A defaulting borrower is charged a flat late fee on every payment for the
  life of the default.** `product.penalty_rate_per_day` exists
  (`lending/models.py:108`) but no code accrues `loan.penalty_cents`;
  `services.py:941` adds an unconditional late fee whenever days past due exceeds
  zero, and days past due is cleared only when a schedule line is fully paid
  (`:833`).
- **A regulator cannot be shown the ledger.** There is no netting engine, no
  ISO 20022 MX support, no FATFA or CRS, an AGM module that is a comment, a
  KYC risk rating that is a stub, and SACCO ratios computed from a proxy balance
  sheet rather than the journal.
- **Nothing a user does reaches them by email reliably.** With no durable
  notification bus, each domain either reimplements dispatch or omits it.

---

## 4. Prioritised gap closure order

Ranked by how many downstream gaps each closes per unit of work. Items marked
**[P]** also appear as numbered proposals in `01-enhancements.md`.

1. **One shared event-sourced double-entry ledger [P]** closes the two-ledger
   split, the two interest columns, the clamped subtraction
   (`erp/foundation/commons.py:48-50` `max(0, a - b)` destroys reversals), the
   negative-balance accrual, the hold double-refund, the mutable journal line,
   and the four concurrency defects that are all read-modify-write on a scalar.
2. **Bitemporal history as the framework default [P]** makes restatement and
   point-in-time queries one join instead of data archaeology, and makes the
   `restructure_loan` defect (`lending/services.py:1297` strands the old loan's
   interest and arrears and resets the new loan to PERFORMING) inexpressible.
3. **Durable job queue with leases [P]** makes `run_daily_aging` safe to retry
   and stops it reporting "completed" after a swallowed `PendingRollbackError`
   (`lending/services.py:1104`, same pattern at `:1113, 1889, 1939, 1666, 852,
   946, 594, 606`).
4. **Netting and settlement engine [P]** is the single largest gap against
   every comparator; `netting` has zero occurrences in the repository.
5. **Policy engine [P]** turns the eight view-less modules into shippable
   products and makes row-level authority expressible as data.
6. **Shared reconciliation engine [P]** collapses 11 implementations into one
   rule language.
7. **Shared idempotency middleware [P]** makes every money endpoint
   double-submission-safe by construction rather than per domain.
8. **Capability-based plugin system with synthesis [P]** turns the 26 identical
   industry plugins and the 102 dashboard classes into generated bundles.
