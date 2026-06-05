# lending World-Class Comparison
Benchmarks: nCino, Finastra Fusion Lender, Temenos Lending, ACBS FIS, Blend
Score: 41/100

## Current Capabilities

- Full loan lifecycle state machine: origination → underwriting → approval/rejection → disbursement → repayment → write-off/recovery
- Reducing-balance EMI schedule generation with correct compound interest formula
- CBK NPA classification (DPD buckets: Performing / Watch / Substandard / Doubtful / Loss) with provision rates
- IFRS 9 ECL three-stage provisioning (Stage 1 12-month ECL, Stage 2/3 lifetime ECL) via `calculate_ecl_provision`
- Credit-bureau integration stub in `run_credit_check` (decision score + flags)
- Rule-based underwriting in `underwrite` (DTI, LTV, minimum score gating)
- Loan restructuring: term extension, rate change, capitalisation of arrears via `restructure_loan`
- Write-off and partial/full recovery with NPA status transitions
- PAR (Portfolio at Risk) report by bucket and product
- Loan aging report (DPD distribution across the book)
- Daily aging batch job `run_daily_aging` with automated NPA reclassification
- Integer-cents arithmetic throughout (money_add / money_multiply / money_divide — no float)
- Event emission via `emit_event` on key state transitions
- Six core models: LoanProduct, LoanApplication, Collateral, Loan, RepaymentSchedule, LoanRepayment
- AuditMixin on all mutable models; ImmutableRecordMixin on schedule and repayment lines

## Gaps

### CRITICAL — General Ledger Double-Entry Posting
Missing: Every monetary event (disbursement, repayment, accrual, write-off, provision) must post balanced GL journal entries in real time.
Impl: Add `GLJournalEntry` model with fields `(id, loan_id, event_type, dr_account_code, cr_account_code, amount_cents, currency, value_date, period_id, posted_by, reversed_by)`. Add `_post_gl_entries(loan, event_type, amount_cents)` to LoanManagementService; call it inside disburse, apply_repayment, write_off, recover, and daily accrual. Entries must be idempotent (unique constraint on event_id + leg) and replayable.
Found in: Temenos Lending, ACBS FIS, Finastra Fusion Lender

### CRITICAL — Fee Engine (Origination, Processing, Late, Prepayment, Insurance)
Missing: No structured fee schedule — fees are hard-coded scalars at best and absent at worst.
Impl: Add `LoanFee` model `(id, product_id, fee_type: Enum[origination|processing|late|prepayment|insurance|annual], calculation_basis: Enum[flat|percent_principal|percent_outstanding], rate_or_amount_cents, capitalisable: bool, waivable: bool, gl_account_code)`. In `disburse`, compute and post origination/processing fees; in `apply_repayment`, compute late fees when DPD > 0; expose `waive_fee(loan_id, fee_id, reason, approver_id)` with audit trail.
Found in: nCino, Finastra Fusion Lender, Temenos Lending, Blend

### CRITICAL — Interest Accrual Engine (Daily Accrual, Deferred Income)
Missing: `run_daily_aging` reclassifies NPA status but does not accrue interest or move it to suspense on NPA.
Impl: Add `InterestAccrualEntry` model `(id, loan_id, accrual_date, days, outstanding_principal_cents, rate, accrued_interest_cents, status: Enum[accrued|suspended|reversed])`. Daily job must call `_accrue_interest(loan, as_of)`, post GL debit Interest Receivable / credit Interest Income; on NPA transition, reverse unposted accruals into suspense (debit Suspense / credit Interest Receivable). Cash-basis recognition on actual receipt.
Found in: Temenos Lending, ACBS FIS, Finastra Fusion Lender

### CRITICAL — Reversal / Void Workflow
Missing: No mechanism to reverse a posted repayment, disbursement, or GL entry.
Impl: Add `reverse_repayment(repayment_id, reason, reversed_by)` method: create a mirror `LoanRepayment` with `repayment_type='reversal'` and `reversed_repayment_id` FK, re-open the source schedule lines, post offsetting GL entries, and re-run aging. Disbursement voids before settlement cutoff must set loan back to APPROVED state. All reversals require dual-control approval (`approver_id != initiator_id`).
Found in: ACBS FIS, Temenos Lending, Finastra Fusion Lender

### HIGH — Standing Orders / Auto-Debit Mandates
Missing: No recurring payment instruction model or execution engine.
Impl: Add `StandingOrder` model `(id, loan_id, linked_account_id, amount_strategy: Enum[fixed|scheduled_emi|minimum_due], execution_day, currency, valid_from, valid_to, status, failure_retry_count, max_retries)`. Add `execute_standing_orders(as_of_date)` batch method that queries active mandates due today, calls the payments rail adapter, posts the result via `apply_repayment`, and handles failures with exponential-backoff retry scheduling. Emit `standing_order.failed` event for notifications.
Found in: Temenos Lending, Finastra Fusion Lender, nCino

### HIGH — Batch Job Orchestration & Idempotency
Missing: `run_daily_aging` has no idempotency guard — double-runs on the same date will double-classify and double-post.
Impl: Add `BatchJobRun` model `(id, job_name, run_date, status: Enum[running|completed|failed], started_at, completed_at, records_processed, error_detail)`. At the start of each batch method, `SELECT FOR UPDATE` on `(job_name, run_date)` and abort if status is completed. Wrap entire batch in a single DB transaction with savepoints per record so one bad loan does not abort the full book run.
Found in: ACBS FIS, Temenos Lending, Finastra Fusion Lender

### HIGH — Credit Limits & Revolving Facilities
Missing: No utilisation tracking for revolving credit lines, overdrafts, or credit card-style limits.
Impl: Add `CreditFacility` model `(id, customer_id, product_id, approved_limit_cents, available_balance_cents, utilised_cents, expiry_date, review_date, currency)`. On each drawdown, decrement `available_balance_cents` atomically (optimistic lock on version). Add `check_limit(facility_id, requested_amount_cents)` raising `LimitExceededError` before disbursement. Daily job must sweep expired facilities.
Found in: nCino, Finastra Fusion Lender, ACBS FIS

### HIGH — Notification & Alert Engine
Missing: Events are emitted via `emit_event` but there is no consumer that delivers borrower or ops-team notifications.
Impl: Add `LoanNotification` model `(id, loan_id, notification_type, channel: Enum[sms|email|push|in_app], recipient, payload_json, scheduled_at, sent_at, status, provider_ref)`. Register async consumers for events: `loan.disbursed`, `repayment.due_soon` (T-3, T-1), `repayment.missed`, `loan.npa_classified`, `standing_order.failed`. Use a transactional outbox so notifications survive process crashes.
Found in: nCino, Blend, Temenos Lending

### HIGH — AML / Sanctions Screening Hooks
Missing: No AML screening at origination or at disbursement; no PEP/sanctions list check.
Impl: Add `aml_screen(customer_id, amount_cents, counterparty_account)` coroutine called before `disburse` completes. Result model: `AMLScreeningResult(id, loan_id, screened_at, provider, status: Enum[clear|review|blocked], risk_score, hit_details_json)`. If status is `review`, hold disbursement in a `PENDING_AML_REVIEW` state requiring compliance officer release. Log all screening results immutably. Wire into `create_application` as well for KYC gate.
Found in: nCino, Finastra Fusion Lender, ACBS FIS, Temenos Lending

### HIGH — Fraud Signal Integration
Missing: No fraud score or device/behavioural signal capture at application or repayment stage.
Impl: Add `FraudSignal` model `(id, loan_id, signal_source, signal_type: Enum[device_fingerprint|velocity|synthetic_identity|account_takeover], score, threshold, action: Enum[allow|step_up|decline], captured_at, raw_payload_json)`. Call fraud provider in `create_application` and `apply_repayment`; if score exceeds threshold, trigger step-up authentication before proceeding. Store raw provider payload for dispute resolution.
Found in: nCino, Blend, Finastra Fusion Lender

### HIGH — Transactional Outbox / Event Durability
Missing: `emit_event` is a fire-and-forget call with no durability guarantee — events are lost on process crash.
Impl: Add `OutboxEvent` model `(id, aggregate_type, aggregate_id, event_type, payload_json, created_at, published_at, status: Enum[pending|published|failed])`. In every service method, write the outbox record inside the same DB transaction as the state change. A separate relay process polls `WHERE status='pending'` and publishes to the message broker, marking records published. This is the standard transactional outbox pattern.
Found in: ACBS FIS, Temenos Lending, Finastra Fusion Lender

### MEDIUM — Product Configuration Engine
Missing: LoanProduct fields cover rate and term ranges but lack a full product-rule DSL for eligibility, pricing tiers, and document checklists.
Impl: Add `ProductRule` model `(id, product_id, rule_type: Enum[eligibility|pricing_tier|doc_checklist|covenant], expression_json, priority, effective_from, effective_to)`. During underwriting, evaluate eligibility and pricing-tier rules in priority order using a simple expression evaluator (e.g. rule-engine or a JSONLogic evaluator). This replaces hard-coded DTI/LTV thresholds in `underwrite` with data-driven configuration.
Found in: nCino, Finastra Fusion Lender, Temenos Lending

### MEDIUM — Covenant Monitoring & Breach Workflow
Missing: No financial covenant tracking (DSCR, leverage ratio, current ratio) for commercial loans.
Impl: Add `LoanCovenant` model `(id, loan_id, covenant_type, metric_name, threshold, frequency: Enum[monthly|quarterly|annual], last_tested_date, last_value, status: Enum[compliant|breach|waived])`. Add `test_covenants(loan_id, as_of_date)` that fetches borrower financials from an integration, evaluates each covenant, records the result, and emits `covenant.breach` event if threshold is violated. Breaches trigger a cure-period workflow with escalation.
Found in: ACBS FIS, nCino, Finastra Fusion Lender

### MEDIUM — Dormancy Detection & Inactive Account Handling
Missing: No dormancy logic — accounts with zero activity for a configurable period are not flagged or fees assessed.
Impl: Add `dormancy_days_threshold` to `LoanProduct`. In the daily batch, identify loans with `last_activity_date < today - threshold` and status ACTIVE, set `is_dormant=True`, emit `loan.dormant` event, and optionally apply a dormancy fee via the fee engine. Add `reactivate_loan(loan_id, triggered_by)` to clear the flag on any new transaction.
Found in: Temenos Lending, ACBS FIS

### MEDIUM — Reconciliation & Settlement Reporting
Missing: No reconciliation between ledger balances and the repayment schedule; no suspense account sweeping.
Impl: Add `run_reconciliation(as_of_date)` that computes, per loan: `expected_principal_balance = original_principal - sum(principal_allocated)` vs `loan.outstanding_principal_cents`, flagging mismatches into a `ReconciliationException` table `(id, loan_id, as_of_date, expected_cents, actual_cents, diff_cents, resolved_at, resolved_by)`. Auto-sweep amounts sitting in suspense > 2 business days to the appropriate income/liability account with GL entries. Report sent to ops dashboard.
Found in: ACBS FIS, Finastra Fusion Lender, Temenos Lending

### MEDIUM — Audit Trail & Immutable Change Log
Missing: AuditMixin records created_by/updated_by but there is no field-level change history for sensitive attributes (rate, limit, status).
Impl: Add `LoanAuditLog` model `(id, loan_id, field_name, old_value, new_value, changed_by, changed_at, change_reason, ip_address, session_id)`. Use a SQLAlchemy event listener (`@event.listens_for(Loan, 'before_update')`) to diff tracked columns and insert audit rows in the same transaction. Tracked columns minimum: `status`, `interest_rate`, `outstanding_principal_cents`, `npa_classification`, `restructure_count`.
Found in: All five benchmarks

### MEDIUM — Multi-Currency & FX Revaluation
Missing: Currency field exists on models but no FX rate table, no revaluation of foreign-currency loan balances to reporting currency.
Impl: Add `FXRate` model `(id, from_currency, to_currency, rate, rate_date, source)`. Add `revalue_fx_loans(as_of_date, reporting_currency)` batch method that fetches end-of-day rates, computes unrealised FX gain/loss for each non-reporting-currency loan, posts GL entries (debit/credit FX Revaluation Reserve), and records `FXRevaluationEntry`. Reporting should show both original-currency and reporting-currency balances.
Found in: ACBS FIS, Finastra Fusion Lender, Temenos Lending

### MEDIUM — Prepayment Penalty & Early Settlement Workflow
Missing: `restructure_loan` and `write_off` do not compute or enforce prepayment penalty on voluntary early closure.
Impl: Add `early_settle(loan_id, settlement_date, requested_by)` method: compute outstanding principal + accrued interest + prepayment penalty (from fee engine, basis: `percent_outstanding` for remaining term discount) + any unpaid fees; generate a settlement quote valid for N days; on confirmation, apply full repayment, close loan, post GL, emit `loan.settled_early`. Store `settlement_quote_id` on the loan for audit.
Found in: nCino, Finastra Fusion Lender, Temenos Lending, Blend
