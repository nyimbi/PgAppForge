# sacco World-Class Comparison
Benchmarks: Apache Fineract/Mifos X, Musoni, KUSCCO BFAAS, Bankers Realm Craft Silicon
Score: 38/100

## Current Capabilities

- Member onboarding with KYC fields, share subscription, and next-of-kin tracking
- Monthly savings contribution posting with integer-cent arithmetic (no float money)
- Loan application with eligibility check (share multiplier, guarantor count, active membership gate)
- Dividend declaration as immutable records with audit trail
- Dividend payout crediting per member proportional to share balance
- Member exit value calculation: shares + deposits − outstanding loans − guarantee exposure
- SACCO-level KPI dashboard: total savings, loan book, NPL ratio, capital adequacy, liquidity ratio
- Chama group formation with founding member roster
- Chama contribution recording to pooled fund
- Merry-go-round rotation disbursement with recipient cycling
- Table banking short-term loan issuance from Chama pool
- Chama statement generation (contributions vs. payouts for a date range)
- Event emission via `emit_event` for major state changes
- Integer-cent monetary arithmetic throughout (money_add / money_multiply / money_divide / percent_of)
- Audit mixin on all core models (created_by, changed_by, created_on, changed_on)

## Gaps

### CRITICAL — Double-Entry General Ledger Posting
Missing: No GL journal entries are written for any monetary transaction.
Impl: Every debit/credit must produce a `JournalEntry` row with `(debit_account_id, credit_account_id, amount_cents, currency, transaction_ref, posting_date, period_id)`. Add `post_journal(session, entries: list[JournalLine], ref: str)` in a `GLService`; call it inside every service method inside the same DB transaction. Chart of accounts must map product types to account codes.
Found in: Apache Fineract, Bankers Realm Craft Silicon, KUSCCO BFAAS

### CRITICAL — Fee and Charge Engine
Missing: No fee calculation, accrual, or collection logic exists anywhere in the plugin.
Impl: Add a `FeeCharge` model with `(product_id, fee_type: Enum[FLAT|PERCENT_DISBURSEMENT|PERCENT_OUTSTANDING|TIERED], amount_or_rate, collection_trigger: Enum[DISBURSEMENT|MONTHLY|ANNUAL|EVENT], waivable: bool)`. `FeeEngine.calculate(loan, trigger)` returns `list[FeeLineItem]`; results post to GL and member ledger. Without this, loan cost is systematically understated.
Found in: Apache Fineract, Musoni, Bankers Realm Craft Silicon

### CRITICAL — Transaction Reversal / Void Workflow
Missing: No method exists to reverse or void a posted transaction.
Impl: Add `reverse_transaction(session, txn_id: str, reason: str, auth_user_id: str) -> ReverseResult` that creates a mirror `LedgerEntry` with negated amounts, sets `original_txn.reversed_by = new_txn.id`, and re-computes running balance. Reversals must be idempotent and themselves immutable.
Found in: Apache Fineract, Musoni, KUSCCO BFAAS, Bankers Realm Craft Silicon

### CRITICAL — Loan Repayment Schedule and Amortisation
Missing: `apply_sacco_loan` has no amortisation schedule generation.
Impl: Add `build_repayment_schedule(principal_cents, rate_bps, term_months, method: Enum[FLAT|REDUCING_BALANCE|RULE_OF_78]) -> list[InstallmentRow]` where each row carries `(due_date, principal_due, interest_due, fees_due, balance_after)`. Store as `LoanRepaymentSchedule` rows; a separate `post_loan_repayment(session, loan_id, payment_cents, value_date)` method allocates payment across fees → interest → principal in that priority order.
Found in: Apache Fineract, Musoni, Bankers Realm Craft Silicon

### HIGH — Standing Orders / Auto-Debit Instructions
Missing: No mechanism to schedule recurring contributions or loan repayments.
Impl: Add `StandingOrder` model `(member_id, instruction_type, amount_cents, frequency: Enum[WEEKLY|MONTHLY|QUARTERLY], next_execution_date, source_account, destination_account, max_failures, failure_count, status)`. A `StandingOrderProcessor.run_due(session, as_of: date) -> BatchResult` selects all due active orders, executes each via the appropriate service method, and marks failed orders after `max_failures` breached.
Found in: Musoni, KUSCCO BFAAS, Bankers Realm Craft Silicon

### HIGH — Batch Job / End-of-Day Processing
Missing: No scheduled batch runner for interest accrual, fee charging, or dormancy checks.
Impl: Add `BatchJobService` with discrete steps: `accrue_savings_interest(session, run_date)`, `accrue_loan_interest(session, run_date)`, `charge_overdue_penalties(session, run_date)`, `check_dormancy(session, run_date)`. Each step must be idempotent (keyed on `run_date + job_type` in a `BatchRunLog` table) to allow safe re-runs after failure.
Found in: Apache Fineract, KUSCCO BFAAS, Bankers Realm Craft Silicon

### HIGH — Transactional Limits and Controls
Missing: No per-member, per-product, or per-day transaction limit enforcement.
Impl: Add `LimitConfig` model `(scope: Enum[MEMBER|PRODUCT|SACCO], limit_type: Enum[DAILY_WITHDRAWAL|MIN_BALANCE|MAX_LOAN_EXPOSURE|SINGLE_TXN], amount_cents, currency)`. `LimitEngine.check(session, member_id, txn_type, amount_cents) -> LimitCheckResult` raises `LimitBreachError` with breach details before any posting occurs.
Found in: Musoni, KUSCCO BFAAS, Bankers Realm Craft Silicon

### HIGH — Notification and Alert Dispatch
Missing: `emit_event` is called but there is no outbound notification handler wired to SMS/email/push.
Impl: Add a `NotificationService` that consumes events from the outbox table and dispatches via `AfricasTalking / Twilio / FCM` adapters. Each `NotificationTemplate` row holds `(event_type, channel, body_template, locale)`. Members must receive confirmation SMS/email on every debit, credit, loan disbursement, and repayment.
Found in: Musoni, KUSCCO BFAAS

### HIGH — AML / Sanctions Screening Hooks
Missing: No Anti-Money Laundering check, CTR threshold, or sanctions list screen at any entry point.
Impl: Add `AMLService.screen_transaction(member_id, amount_cents, txn_type) -> AMLDecision` that checks cumulative daily volume against CTR threshold (configurable, default 1 000 000 KES), flags structuring patterns (multiple transactions just below threshold within 24 h), and queries a local `SanctionsList` cache. Suspicious transactions must be written to `SuspiciousActivityReport` and blocked pending compliance review.
Found in: KUSCCO BFAAS, Bankers Realm Craft Silicon

### HIGH — Fraud Signal Generation
Missing: No velocity checks, device fingerprinting hooks, or anomaly flags on transactions.
Impl: Add `FraudSignalService.evaluate(session, member_id, txn: PendingTransaction) -> RiskScore` that scores on: unusual hour, atypical amount vs. 90-day average, new device/IP, rapid successive transactions, and geography mismatch. Score ≥ threshold blocks transaction and raises `FraudAlertEvent`; score in mid-range flags for manual review. Store raw signals in `FraudSignal` table for model retraining.
Found in: Bankers Realm Craft Silicon, Musoni

### HIGH — Durable Event Outbox
Missing: `emit_event` fires in-process with no persistence; events are lost on crash.
Impl: Replace `emit_event` with a transactional outbox: write `OutboxEvent(id, aggregate_type, aggregate_id, event_type, payload_json, status=PENDING, created_at)` inside the same DB transaction as the business write. A separate `OutboxRelay` worker polls `status=PENDING`, publishes to Kafka/Redis Streams, and marks `status=PUBLISHED`. This guarantees at-least-once delivery without distributed transactions.
Found in: Apache Fineract, Bankers Realm Craft Silicon

### MEDIUM — Product Configuration Engine
Missing: Loan and savings products have hardcoded business rules mixed into service methods.
Impl: Extract all product parameters into `SACCOLoanProduct` and `SACCOSavingsProduct` model fields: `min_principal_cents`, `max_principal_cents`, `interest_rate_bps`, `interest_method`, `grace_period_days`, `penalty_rate_bps`, `max_tenor_months`, `guarantors_required`, `insurance_required`. Service methods must read these at runtime; no magic numbers in code.
Found in: Apache Fineract, Musoni, Bankers Realm Craft Silicon

### MEDIUM — Dormancy Detection and Reactivation
Missing: No dormancy classification, freeze logic, or reactivation workflow.
Impl: Add `DormancyPolicy(inactivity_days_warn, inactivity_days_freeze, inactivity_days_escheat)` to `SACCO` config. `BatchJobService.check_dormancy(session, run_date)` sets `Member.status = DORMANT` after `inactivity_days_freeze` of no debit/credit, blocks withdrawals, and triggers a notification. Reactivation requires compliance officer sign-off recorded in `MemberStatusLog`.
Found in: KUSCCO BFAAS, Bankers Realm Craft Silicon

### MEDIUM — Reconciliation and Settlement
Missing: No end-of-day reconciliation, inter-bank settlement, or mobile money float tracking.
Impl: Add `ReconciliationService.run_eod(session, run_date) -> ReconReport` that cross-checks: sum of all member ledger balances vs. GL control account, total loan book vs. loan schedule outstanding, mobile money float account vs. provider statement totals. Discrepancies are written to `ReconException` rows requiring manual clearance.
Found in: KUSCCO BFAAS, Bankers Realm Craft Silicon

### MEDIUM — Comprehensive Audit Trail
Missing: `AuditMixin` captures who changed a record but not what changed or why.
Impl: Add `AuditLog(table_name, record_id, action: Enum[INSERT|UPDATE|DELETE], old_values_json, new_values_json, changed_by, changed_at, ip_address, session_id, reason)`. Use a SQLAlchemy `event.listen(Session, 'before_flush', ...)` hook to capture diffs automatically. Financial adjustments must require a mandatory `reason` string that is stored verbatim and is immutable.
Found in: Apache Fineract, KUSCCO BFAAS, Bankers Realm Craft Silicon

### MEDIUM — Interest Accrual on Savings
Missing: Savings contributions earn no interest; no accrual model or rate schedule exists.
Impl: Add `SavingsInterestPolicy(product_id, rate_bps, accrual_basis: Enum[DAILY|MONTHLY], compounding: Enum[SIMPLE|COMPOUND], credit_day_of_month)` and `SavingsAccrual(member_id, accrual_date, accrued_cents, posted: bool)`. `BatchJobService.accrue_savings_interest` computes daily accrual on end-of-day balance; month-end job aggregates and posts to member ledger with GL entries.
Found in: Apache Fineract, Musoni

### MEDIUM — Guarantor Lifecycle Management
Missing: `apply_sacco_loan` counts guarantors but has no guarantor commitment, release, or substitution workflow.
Impl: Add `LoanGuarantor(loan_id, guarantor_member_id, guaranteed_amount_cents, status: Enum[COMMITTED|RELEASED|CALLED], committed_at, released_at, called_at)`. On loan closure, `release_guarantors(session, loan_id)` sets all to RELEASED and un-encumbers their shares. If loan goes default, `call_guarantee(session, loan_id)` triggers debit from guarantor shares with full GL posting and notification.
Found in: Apache Fineract, Musoni, KUSCCO BFAAS

### MEDIUM — Penalty and Write-Off Workflow
Missing: Overdue loans accrue no penalties and have no formal write-off or provision path.
Impl: Add `LoanClassification(loan_id, classification: Enum[CURRENT|WATCH|SUBSTANDARD|DOUBTFUL|LOSS], classified_at, provision_rate_bps)` updated by the batch job based on days-past-due buckets (0/1–30/31–90/91–180/180+). `write_off_loan(session, loan_id, auth_user_id, reason)` moves outstanding balance to `LoanWriteOff`, posts GL entries to bad debt expense and contra asset, and preserves collection rights.
Found in: Apache Fineract, KUSCCO BFAAS, Bankers Realm Craft Silicon

### MEDIUM — Multi-Currency and Forex
Missing: All amounts implicitly assume a single currency with no ISO 4217 currency code stored.
Impl: Add `currency: str` (ISO 4217, default "KES") to every monetary model. Add `FxRate(base_currency, quote_currency, rate_bps, effective_date, source)` and `FxService.convert(amount_cents, from_ccy, to_ccy, as_of: date) -> int`. Cross-currency transactions must post separate GL lines for the FX gain/loss account.
Found in: Bankers Realm Craft Silicon, Apache Fineract
