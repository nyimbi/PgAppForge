# regulatory World-Class Comparison
Benchmarks: Wolters Kluwer OneSumX, AxiomSL ControllerView, Moody Analytics RiskFoundation
Score: 41/100

## Current Capabilities

- AML rule engine with configurable rules stored in `AMLRule` model; supports threshold, velocity, geographic, PEP, and structuring typologies
- Transaction screening via `screen_transaction()` evaluating all active rules per transaction with match scoring and alert generation
- PEP list management (`PEPList` model) with customer lookups via `_is_pep()` supporting multiple PEP categories
- AML alert lifecycle: generate → investigate → escalate → close with analyst assignment and state machine enforcement in `AMLAlert`
- Suspicious Activity Report filing via `file_sar()` with FRC Kenya submission stub (`_submit_to_frc_kenya()`)
- Immutable audit record pattern for SAR, CapitalAdequacyReport, IFRS9ProvisionRun — INSERT-ONLY, corrections via new records
- Basel III standard approach capital adequacy via `calculate_capital_adequacy()` computing CET1, Tier 1, Total Capital ratios against RWA
- IFRS 9 ECL provisioning via `run_ifrs9_provision()` with three-stage classification (Stage 1: 12m PD×LGD×EAD; Stage 2: lifetime; Stage 3: LGD×EAD)
- CBK prudential returns generation: BS1 (balance sheet), BS3 (provisions), BS6 (capital) via `generate_cbk_returns()`
- Single-borrower large exposure check via `check_large_exposure()` enforcing CBK 25% core capital limit (CBK PG 3)
- Compliance dashboard aggregation via `generate_compliance_dashboard()` summarising open alerts, SAR counts, capital ratios, and ECL movements
- All monetary arithmetic in integer cents via `money_*` helpers — no float rounding errors
- Event emission decoupled from business transactions (try/except wrap) — alert and breach events published to internal bus
- Velocity counting via `_count_recent_transactions()` with configurable lookback windows for structuring detection
- Customer risk rating retrieval via `_get_customer_risk_rating()` feeding rule threshold calibration

## Gaps

### CRITICAL — Regulatory Reporting Scheduler / Automated Submission
Missing: No automated periodic scheduler drives CBK return generation and submission; everything is on-demand only.
Impl: Add a `RegulatorySchedule` model with `report_type`, `frequency` (daily/monthly/quarterly), `next_run_at`, `last_run_id`, and `submission_status`. A `SchedulerService.tick()` method queries overdue schedules, calls the appropriate generator, persists the output, and posts to the regulator endpoint. Retry logic with exponential backoff and a `submission_log` JSONB column for response payloads.
Found in: Wolters Kluwer OneSumX, AxiomSL ControllerView

### CRITICAL — GL Double-Entry Posting for Regulatory Provisions
Missing: IFRS 9 ECL runs compute provision amounts but never post corresponding debit/credit journal entries to the GL.
Impl: After `run_ifrs9_provision()` persists the `IFRS9ProvisionRun`, call `gl_service.post_journal(entries=[JournalLine(account=PROVISION_EXPENSE_ACCT, dr=delta_ecl), JournalLine(account=LOAN_LOSS_RESERVE_ACCT, cr=delta_ecl)])` where `delta_ecl = new_run.total_ecl_cents - prior_run.total_ecl_cents`. Use a two-phase commit flag (`gl_posted: bool`) on the run model so a crash between ECL write and GL post is recoverable on next startup.
Found in: Wolters Kluwer OneSumX, Moody Analytics RiskFoundation

### CRITICAL — Sanctions List Integration and Real-Time Screening
Missing: No OFAC SDN, UN Consolidated, EU Consolidated, or HMT sanctions list ingestion or matching.
Impl: Add a `SanctionsList` model (`list_source`, `listed_name`, `aliases: JSONB`, `entity_type`, `listed_at`, `delisted_at`) with a bulk-upsert loader. `screen_transaction()` must invoke `sanctions_service.fuzzy_match(name, threshold=0.85)` using trigram similarity (pg_trgm) before evaluating AML rules. A breach returns HTTP 403 to the transaction endpoint with a `SanctionsHitEvent`.
Found in: Wolters Kluwer OneSumX, AxiomSL ControllerView, Moody Analytics RiskFoundation

### HIGH — Regulatory Capital Stress Testing
Missing: Capital adequacy calculation is point-in-time only; no scenario/stress test framework exists.
Impl: Add `StressScenario` model (`scenario_name`, `macro_shock_params: JSONB`, `pd_multiplier`, `lgd_multiplier`, `haircut_pct`). `calculate_capital_adequacy(scenario_id=...)` applies scenario shocks to RWA and ECL inputs, producing stressed CET1/T1/Total ratios alongside base-case. Store results in `CapitalAdequacyReport.stress_results: JSONB`. AxiomSL runs 200+ scenarios per overnight batch.
Found in: AxiomSL ControllerView, Moody Analytics RiskFoundation

### HIGH — Transaction Reversal and Correction Audit Trail
Missing: No reversal mechanism exists; a mis-screened or mis-filed record cannot be formally corrected without direct DB mutation.
Impl: Add `ReversalRecord` model (`original_record_id`, `original_record_type`, `reason_code`, `reversed_by`, `reversed_at`, `replacement_record_id`). Expose `regulatory_service.reverse_sar(original_sar_id, reason, analyst_id)` which creates a superseding SAR with `supersedes_id` FK and writes a `ReversalRecord`. Immutable models gain a `superseded_by_id: str | None` column.
Found in: Wolters Kluwer OneSumX, AxiomSL ControllerView

### HIGH — Fraud Signal Ingestion and ML Score Integration
Missing: AML rules are purely rule-based; no fraud/ML score channel exists to feed behavioral anomaly signals.
Impl: Add `FraudSignal` model (`customer_id`, `signal_source`, `score: int` 0-1000, `features: JSONB`, `model_version`, `created_at`). `screen_transaction()` queries the latest signal for the customer and adds `fraud_score_weight` to the composite alert score when score > configurable threshold. `AMLRule` gains a `require_fraud_score_above: int | None` column so high-risk typologies can gate on ML confidence.
Found in: Wolters Kluwer OneSumX, Moody Analytics RiskFoundation

### HIGH — Transactional Outbox for Event Durability
Missing: `emit_event()` calls are fire-and-forget wrapped in try/except — events are silently dropped on broker failure.
Impl: Replace bare `emit_event()` with an outbox pattern: insert an `OutboxEvent` row (`aggregate_id`, `event_type`, `payload: JSONB`, `published_at: datetime | None`) in the same DB transaction as the business write. A background `OutboxRelay` polls for `published_at IS NULL`, publishes to the broker, then stamps `published_at`. Guarantees at-least-once delivery without two-phase commit overhead.
Found in: AxiomSL ControllerView, Moody Analytics RiskFoundation

### HIGH — Limit Management Engine
Missing: No pre-transaction limit check framework; large exposure is checked post-fact only.
Impl: Add `RegulatoryLimit` model (`limit_type` e.g. single_borrower/sector_concentration/fx_open_position, `entity_id`, `limit_amount_cents`, `breach_action` block|alert|report, `effective_from`, `effective_to`). `LimitService.check_and_enforce(entity_id, limit_type, proposed_amount)` queries the current utilisation, compares against the limit, and raises `LimitBreachException` (for block) or emits `LimitBreachedEvent` (for alert/report). Wire into transaction approval flow.
Found in: Wolters Kluwer OneSumX, AxiomSL ControllerView

### HIGH — Regulatory Notification and Escalation SLA Tracking
Missing: Alert lifecycle has no SLA clock; breached investigation deadlines are invisible.
Impl: Add `sla_due_at: datetime` to `AMLAlert` computed at creation from `AMLRule.investigation_sla_hours`. Add `sla_breached_at: datetime | None` stamped by a scheduled `SLAMonitor.check()` that queries `sla_due_at < now() AND closed_at IS NULL`. Emit `AlertSLABreachedEvent` triggering supervisor notification. CBK requires SAR filing within 3 days of suspicion formation — add `sar_filing_deadline` to `AMLAlert` with the same pattern.
Found in: Wolters Kluwer OneSumX, AxiomSL ControllerView

### HIGH — Reconciliation Framework
Missing: No reconciliation between regulatory report figures and GL balances; submitted numbers are not independently verified.
Impl: Add `ReconciliationRun` model (`report_type`, `period`, `report_value_cents`, `gl_value_cents`, `variance_cents`, `variance_pct`, `status` matched|warned|failed, `run_at`). `ReconciliationService.reconcile(report_type, period)` fetches the filed report value and the corresponding GL trial-balance node, computes variance, and flags anything outside a configurable tolerance (e.g. 0.01%). Gate CBK return submission on clean reconciliation status.
Found in: Wolters Kluwer OneSumX, Moody Analytics RiskFoundation

### MEDIUM — Product Configuration Registry
Missing: IFRS 9 PD/LGD parameters and Basel RWA weights are hardcoded in service methods; no product-level configuration.
Impl: Add `ProductRegulatoryConfig` model (`product_code`, `asset_class`, `pd_12m`, `pd_lifetime`, `lgd`, `ead_ccf`, `rwa_weight`, `effective_from`, `effective_to`). `run_ifrs9_provision()` and `_fetch_risk_weighted_assets()` query the config table filtered by `effective_from <= run_date <= effective_to` instead of using literal constants. Supports regulatory parameter changes without code deployments.
Found in: Moody Analytics RiskFoundation, Wolters Kluwer OneSumX

### MEDIUM — Batch Job Management and Monitoring
Missing: Long-running jobs (IFRS 9, capital adequacy) run synchronously within the request; no job queue, progress tracking, or failure recovery.
Impl: Add `RegulatoryJob` model (`job_type`, `status` pending|running|succeeded|failed, `started_at`, `completed_at`, `progress_pct`, `error_message`, `result_record_id`). Heavy methods enqueue a `RegulatoryJob` row and return immediately; a worker (Celery task or asyncio background task) executes and updates progress. Callers poll `GET /regulatory/jobs/{id}`. Failed jobs are retryable with idempotency keys.
Found in: AxiomSL ControllerView, Moody Analytics RiskFoundation

### MEDIUM — AML Typology Library and Rule Versioning
Missing: AML rules are flat records without versioning; rule changes destroy prior screening history context.
Impl: Add `rule_version: int` to `AMLRule` with a unique constraint on `(rule_code, rule_version)`. Mutations create a new version row rather than updating in place (same immutable pattern as SAR). Add `typology_category` enum (structuring, layering, integration, trade_based, cyber_enabled) and `fatf_reference: str` columns for audit evidence. `screen_transaction()` records `rule_version` on each `AMLAlert` match so historical alerts reference the exact rule definition active at screening time.
Found in: Wolters Kluwer OneSumX, AxiomSL ControllerView

### MEDIUM — Dormancy Detection and Regulatory Handling
Missing: No dormancy classification; regulatory requirements for dormant accounts (CBK Guideline on Dormant Accounts) are unimplemented.
Impl: Add `DormancyRecord` model (`account_id`, `dormant_since`, `last_activity_at`, `notified_at`, `escheatment_due_at`, `status` active|pre_dormant|dormant|escheated). `DormancyService.classify()` batch-queries accounts with no debit/credit activity for > 365 days, creates `DormancyRecord` rows, triggers customer notification events, and schedules escheatment at the CBK-mandated 5-year mark.
Found in: Wolters Kluwer OneSumX

### MEDIUM — Enhanced Customer Due Diligence (ECDD) Workflow
Missing: PEP detection flags a customer but no structured EDD workflow or documentation requirement is triggered.
Impl: Add `EDDCase` model (`customer_id`, `trigger_type` pep|high_risk_country|adverse_media|large_cash, `assigned_to`, `due_date`, `documents_required: JSONB`, `documents_received: JSONB`, `status` open|pending_docs|under_review|approved|rejected, `decision_rationale`). `screen_customer()` auto-creates an `EDDCase` when PEP or country-risk triggers fire. `EDDService.complete_review()` gates account activation/continuation on case closure. FATF R.12 and CBK AML Guidelines require documented EDD for PEPs.
Found in: Wolters Kluwer OneSumX, AxiomSL ControllerView

### MEDIUM — Regulatory Data Lineage and Provenance
Missing: CBK return figures are computed at call time with no traceable link from submitted number back to source transactions.
Impl: Add `ReportLineage` model (`report_id`, `report_line_code`, `source_table`, `source_filter: JSONB`, `computed_value_cents`, `row_count`, `snapshot_at`). Each `_build_bs*()` method writes lineage rows alongside the report payload. Auditors and regulators can query `GET /regulatory/reports/{id}/lineage/{line_code}` to see exactly which GL entries or loan records drove a specific figure. AxiomSL's core differentiator is full drill-through lineage.
Found in: AxiomSL ControllerView, Moody Analytics RiskFoundation

### MEDIUM — Adverse Media and Negative News Screening
Missing: Customer risk rating relies solely on internal data; no external adverse media feed integration.
Impl: Add `AdverseMediaRecord` model (`entity_name`, `entity_id: str | None`, `source_url`, `headline`, `risk_categories: list[str]`, `sentiment_score`, `screened_at`, `matched_customer_id: str | None`). Integrate a webhook receiver for Refinitiv World-Check or Dow Jones RiskCenter feeds. `screen_customer()` queries unresolved adverse media hits for the customer and escalates risk rating when `risk_categories` overlaps configured watchlist categories.
Found in: Wolters Kluwer OneSumX, AxiomSL ControllerView

### MEDIUM — Currency and FX Revaluation for Regulatory Reporting
Missing: All monetary values assumed to be in local currency (KES); multi-currency positions are not revalued for capital and exposure calculations.
Impl: Add `FXRate` model (`currency_pair`, `rate`, `rate_date`, `source` CBK|ECB|custom). `calculate_capital_adequacy()` and `check_large_exposure()` call `fx_service.convert_to_base(amount_cents, currency, as_of_date)` before summing positions. `CapitalAdequacyReport` gains `fx_translation_adjustment_cents` and `open_fx_position_cents` columns for Pillar 1 market risk RWA.
Found in: Wolters Kluwer OneSumX, Moody Analytics RiskFoundation
