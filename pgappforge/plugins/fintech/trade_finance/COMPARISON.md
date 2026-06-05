# trade_finance World-Class Comparison
Benchmarks: Finastra Trade Innovation, Bolero, Marco Polo, Komgo, CGI Trade360
Score: 41/100

## Current Capabilities

- Letter of Credit lifecycle: issuance, amendment, presentation examination, accept/reject, settlement (`issue_lc`, `amend_lc`, `examine_presentation`, `accept_or_reject_presentation`, `settle_lc`)
- UCP 600 tolerance enforcement (±tolerance_pct%) on presentation amounts
- Bank Guarantee issuance and claim processing with margin-first payout logic (`issue_guarantee`, `process_guarantee_claim`)
- Documentary Collection registration (`register_collection`) with MT400 SWIFT message generation
- Supply Chain Finance: program creation and receivable funding (`fund_scf_receivable`)
- Margin hold placement and release against core banking accounts (`_place_margin_hold`, `_release_margin_hold`)
- Basic GL posting via lazy import of `erp.finance.gl` (`_post_to_gl`)
- SWIFT message generation for MT700 (LC issuance), MT707 (LC amendment), MT400 (collection)
- Trade finance exposure aggregation per customer (`get_trade_finance_exposure`)
- Charge calculation for LC issuance, amendments, and utilisation fees (`calculate_lc_charges`)
- Event emission pattern with try/except isolation so service never fails on event bus errors (`_emit`)
- Integer-cents monetary arithmetic throughout — no float/Decimal leakage in storage
- BIC validation via shared commons (`validate_bic`)
- Immutable presentation and receivable records via `ImmutableRecordMixin`
- Multi-tenant aware service constructor with `tenant_id` scoping

---

## Gaps

### CRITICAL — Double-Entry GL Journal Completeness
Missing: GL entries are posted via a single `_post_to_gl` call with a raw `list[dict]` — there is no enforced debit/credit balance check, no chart-of-accounts validation, and no journal reversal counterpart.
Impl: Add a `GLJournal` dataclass with `entries: list[GLLine]` where each `GLLine` carries `account_code`, `debit_cents`, `credit_cents`, `cost_centre`, `narrative`; assert `sum(debits) == sum(credits)` before posting; expose `reverse_journal(journal_id)` that posts a mirror entry with `REVERSAL` flag. Add `gl_journal_id` FK on `LetterOfCredit`, `LCPresentation`, `BankGuarantee`, and `DocumentaryCollection`.
Found in: Finastra Trade Innovation, CGI Trade360

### CRITICAL — Fee Engine with Product-Level Tariff Tables
Missing: `calculate_lc_charges` hardcodes rate logic inline; there is no tariff table, tiered pricing, or fee schedule model that operations staff can configure without a code deploy.
Impl: Add a `TariffSchedule` model with fields `product_type` (enum: LC/BG/DC/SCF), `fee_code`, `basis` (FLAT/PCT_NOTIONAL/PCT_DRAWN/TIERED), `rate_bps: int`, `min_cents: int`, `max_cents: int | None`, `currency`, `effective_date`, `expiry_date`; add `TariffTier(schedule_id, lower_bound_cents, upper_bound_cents, rate_bps)`. `calculate_lc_charges` should look up the active schedule for the product and apply tiers. Fee events should be posted to GL automatically.
Found in: Finastra Trade Innovation, Bolero, CGI Trade360

### CRITICAL — Transactional Outbox for Event Durability
Missing: `_emit` wraps event emission in try/except and silently discards failures — events can be lost on broker outage with no replay mechanism.
Impl: Add an `OutboxEvent` model with `id`, `aggregate_type`, `aggregate_id`, `event_type`, `payload_json`, `status` (PENDING/DELIVERED/DEAD), `created_at`, `delivered_at`, `retry_count`; persist to the same DB transaction as the business mutation; run a background `OutboxRelay` job that polls `status=PENDING` and publishes with at-least-once semantics. Only mark DELIVERED after broker ACK.
Found in: Marco Polo, Komgo, Finastra Trade Innovation

### CRITICAL — Limit Management and Utilisation Tracking
Missing: No credit limit, country limit, or counterparty limit model exists; `_place_margin_hold` calls core banking but there is no in-service limit utilisation ledger that can be queried or breached.
Impl: Add `TradeLimit(id, customer_id, limit_type: enum(CUSTOMER/COUNTRY/BANK/PRODUCT), currency, limit_cents, utilised_cents, available_cents, expiry_date)`; add `LimitUtilisation(limit_id, instrument_id, instrument_type, utilised_cents, effective_date, release_date)`. All issuance paths must call `check_and_reserve_limit()` atomically; expose `get_limit_utilisation(customer_id)` for credit dashboard.
Found in: Finastra Trade Innovation, CGI Trade360, Komgo

### HIGH — Reversal and Cancellation Workflow
Missing: No reversal method exists for any instrument; once `settle_lc` or `process_guarantee_claim` posts to GL there is no corrective path short of manual DB edits.
Impl: Add `reverse_settlement(presentation_id, reason: str, authorised_by: str)` that (a) posts a reversing GL journal, (b) releases margin holds, (c) transitions the presentation to `REVERSED` status, (d) emits a `lc.settlement.reversed` event, and (e) writes an immutable `AuditEntry`; guard with a two-signature approval flag for amounts above a configurable threshold.
Found in: Finastra Trade Innovation, Bolero, CGI Trade360

### HIGH — AML / Sanctions Screening Hook
Missing: No AML or sanctions check is invoked at issuance or amendment; the service has no integration point for screening counterparties, goods descriptions, or port-of-loading/discharge.
Impl: Add `AMLScreeningHook` protocol with `async def screen(entity: ScreeningRequest) -> ScreeningResult`; call before persisting `LetterOfCredit` and `BankGuarantee`; add `screening_ref`, `screening_status` (CLEAR/HIT/PENDING/BYPASSED), `screening_bypassed_by` fields to both models; block issuance if result is HIT unless `BYPASS_AML_SCREENING` permission is present.
Found in: Komgo, Marco Polo, Finastra Trade Innovation, CGI Trade360

### HIGH — Fraud Signal / Duplicate Instrument Detection
Missing: No duplicate detection exists; two identical LCs (same applicant, beneficiary, amount, expiry) can be issued in rapid succession with no warning.
Impl: Add `_check_duplicate_lc(applicant_id, beneficiary_id, amount_cents, currency, expiry_date)` that queries for instruments in `ISSUED` or `ACTIVE` state matching all five dimensions within a configurable time window; emit `lc.duplicate_suspected` event and surface a `warnings` list in the response dict rather than hard-blocking so the issuing officer can override with justification.
Found in: Finastra Trade Innovation, CGI Trade360

### HIGH — Standing Instructions / Auto-Renewal
Missing: `LetterOfCredit` has no revolving/evergreen flag; there is no scheduler or standing-order model to auto-renew or auto-extend expiring instruments.
Impl: Add `StandingInstruction(id, instrument_id, instrument_type, action: enum(AUTO_RENEW/AUTO_EXTEND/AUTO_CLOSE), trigger_days_before_expiry: int, renewal_period_days: int, max_renewals: int, renewals_completed: int, active: bool)`; add a `process_standing_instructions()` batch method that a cron job calls daily; each triggered action should run the full business path (amendment for extension, new issuance for renewal) so all downstream effects (GL, limits, events) fire normally.
Found in: Finastra Trade Innovation, CGI Trade360

### HIGH — Batch Maturity and Expiry Processing
Missing: No batch job exists to expire LCs or guarantees on their expiry date; status transitions from `ACTIVE` to `EXPIRED` are not automated and margin holds are not auto-released.
Impl: Add `process_maturities(as_of_date: date) -> BatchResult` that selects all instruments where `expiry_date <= as_of_date` and `status IN (ISSUED, ACTIVE, AMENDED)`; for each: transition status, release margin holds, post GL accrual reversal, emit `*.expired` event, write audit entry. Return `BatchResult(processed: int, failed: list[str], total_margin_released_cents: int)`.
Found in: Finastra Trade Innovation, Bolero, CGI Trade360

### HIGH — Structured Audit Trail Model
Missing: Audit is handled by `AuditMixin` timestamps only; there is no event-sourced audit log capturing who changed what field, from what value, to what value, and under which authorisation.
Impl: Add `TradeAuditEntry(id, instrument_id, instrument_type, event_type, changed_fields: JSONB, old_values: JSONB, new_values: JSONB, performed_by, authorised_by, ip_address, session_id, timestamp)`; write an entry on every state transition and field mutation; expose `get_audit_trail(instrument_id)` returning a chronological list; index on `(instrument_id, timestamp)`.
Found in: Bolero, Komgo, Marco Polo, CGI Trade360

### HIGH — SWIFT MT798 / MT798 Sub-message Support
Missing: Only MT700, MT707, and MT400 are generated; MT798 (trade finance gateway message wrapping MT700/710/720/740/747/760/767/775) used by SWIFT for corporate-to-bank LC and guarantee flows is absent.
Impl: Add `generate_mt798(sub_message_type: str, payload: dict) -> str` that wraps an inner SWIFT block in the MT798 envelope with correct field 12 (sub-message type indicator) and field 77E (proprietary message); add MT760 (guarantee issuance) and MT767 (guarantee amendment) generators alongside existing MT700/707.
Found in: Finastra Trade Innovation, Bolero, CGI Trade360, Komgo

### MEDIUM — Notification and Alert Dispatch
Missing: No notification model or dispatch exists; trade officers, applicants, and beneficiaries receive no system-generated alerts for expiry warnings, document discrepancies, or settlement confirmations.
Impl: Add `NotificationRule(id, event_type, recipient_role, channel: enum(EMAIL/SMS/IN_APP/WEBHOOK), template_id, lead_days: int)` and a `NotificationDispatcher` that subscribes to the event bus or polls `OutboxEvent`; render templates with instrument context; record delivery in `NotificationLog(id, rule_id, instrument_id, recipient_id, channel, status, sent_at, error)`.
Found in: Finastra Trade Innovation, Bolero, CGI Trade360

### MEDIUM — Reconciliation Engine
Missing: No reconciliation process exists to match GL postings against core banking account movements or SWIFT confirmations; breaks surface only when auditors manually compare ledgers.
Impl: Add `ReconciliationRun(id, run_date, scope: enum(GL/NOSTRO/SWIFT), status, matched_count, unmatched_count, report_json)`; add `reconcile_gl(run_date: date)` that joins `GLJournal` entries against core banking transaction feed, marks matched pairs, and flags unmatched items as `ReconciliationBreak(run_id, side, reference, amount_cents, break_reason)`; expose `get_open_breaks()` for operations dashboard.
Found in: Finastra Trade Innovation, CGI Trade360, Komgo

### MEDIUM — Product Configuration Registry
Missing: LC, BG, DC, and SCF products have no configurable parameter store; business rules such as max tenor, allowed currencies, margin percentage, and document checklist are hardcoded or absent.
Impl: Add `TradeProduct(id, product_code, product_type, max_tenor_days: int, allowed_currencies: list[str], default_margin_pct_bps: int, document_checklist: JSONB, ucp_rule_version: str, active: bool)`; `issue_lc` and `issue_guarantee` should load the applicable product config at runtime and validate against it rather than accepting raw `details: dict` without schema enforcement.
Found in: Finastra Trade Innovation, CGI Trade360, Bolero

### MEDIUM — Accrual and Income Recognition
Missing: Commission and fee income is posted as lump-sum on issuance; there is no daily accrual engine to spread income recognition over the LC tenor, which violates IFRS 15 / IAS 18 requirements.
Impl: Add `FeeAccrual(id, instrument_id, fee_code, total_fee_cents, accrued_cents, start_date, end_date, daily_accrual_cents)` and `accrue_daily_fees(as_of_date: date)` batch method that posts a GL entry per accrual record for the day's portion; mark fully accrued records as `COMPLETE`; integrate with the maturity batch so early termination triggers accelerated recognition.
Found in: Finastra Trade Innovation, CGI Trade360

### MEDIUM — Dormancy Detection and Escalation
Missing: No logic identifies instruments that have been issued but show no activity (no amendments, no presentations, no draws) beyond a configurable inactivity window.
Impl: Add `dormancy_check(threshold_days: int) -> list[str]` that queries instruments in `ISSUED`/`ACTIVE` state with `last_activity_date < today - threshold_days`; emit `instrument.dormant` event per hit; add `last_activity_date` timestamp updated on every service mutation so the query is index-efficient.
Found in: Finastra Trade Innovation, CGI Trade360

### MEDIUM — Discrepancy Workflow for Presentations
Missing: `examine_presentation` returns a discrepancy list but there is no model tracking each discrepancy's lifecycle — whether it was waived by the applicant, corrected by the beneficiary, or upheld.
Impl: Add `PresentationDiscrepancy(id, presentation_id, discrepancy_code, description, status: enum(OPEN/WAIVED/CORRECTED/UPHELD), raised_by, raised_at, resolved_by, resolved_at, waiver_reference)`; `accept_or_reject_presentation` should require all OPEN discrepancies to be resolved or explicitly waived before acceptance; add `waive_discrepancy(discrepancy_id, waiver_ref, authorised_by)`.
Found in: Bolero, Finastra Trade Innovation, CGI Trade360

### MEDIUM — Multi-Bank / Correspondent Bank Routing
Missing: No correspondent bank or advising bank model exists; all LC issuance assumes a single bank, with no routing table for choosing the advising/confirming/reimbursing bank by corridor.
Impl: Add `CorrespondentBank(id, bic, name, country_iso2, supported_products: list[str], nostro_account_id, active)` and `CorridorRoute(id, issuing_bank_bic, beneficiary_country, product_type, correspondent_bank_id, preferred: bool)`; `issue_lc` should call `resolve_advising_bank(beneficiary_country, product_type)` to populate `advising_bank_bic` from the routing table rather than accepting it as a raw free-text field.
Found in: Finastra Trade Innovation, Bolero, Komgo, CGI Trade360
