# mobile_money World-Class Comparison
Benchmarks: M-Pesa, Airtel Money, MTN MoMo, Wave Africa, Orange Money
Score: 54/100

## Current Capabilities

- Wallet registration with KYC tier system (TIER_1/2/3) enforcing CBK Mobile Money Regulations 2021 balance and daily limits
- SHA-256 PIN hashing with 3-attempt lockout and 30-minute cooling period
- Peer-to-peer send_money with balance, daily limit, and max-balance guards
- Agent cash-out (withdraw_at_agent) and cash-in (deposit_at_agent) with float balance management
- Merchant pay (buy_goods) and bill payment (pay_bill) flows
- STK Push initiation and C2B callback processing (M-Pesa Daraja-style)
- Agent commission calculation and bulk commission settlement
- Merchant till settlement with configurable settlement date
- Single-step transaction reversal (reverse_transaction) with confirmation-code lookup
- Lazy GL posting via erp.finance.gl integration — non-fatal on absence
- M-Pesa-style transaction IDs (MP + 15 alphanum) and confirmation codes (2L + 6 alphanum)
- Immutable transaction records via ImmutableRecordMixin — no in-place mutation
- Event emission on every major flow, wrapped in try/except so events never crash the service
- Agent float top-up from operator (top_up_agent_float)
- KYC tier upgrade path (upgrade_kyc_tier)

## Gaps

### CRITICAL: Double-Entry General Ledger Posting
Missing: Every debit/credit leg must post a balanced GL entry atomically with the transaction — not lazily or optionally.
Impl: Add `GLPostingService.post(txn_id, entries: list[GLEntry])` called inside the same DB transaction as wallet mutation. `GLEntry` needs `account_code`, `dr_cents`, `cr_cents`, `cost_centre`, `narration`. `_try_post_gl` must raise on failure and roll back the whole unit of work, not silently swallow errors. M-Pesa and MTN MoMo maintain a full double-entry subledger; Wave Africa publishes every event to a ledger bus before ACKing the payment.
Found in: M-Pesa, MTN MoMo, Wave Africa, Orange Money

### CRITICAL: Idempotency / Outbox Durability
Missing: No transactional outbox — events emitted after commit can be lost on process crash; no client-supplied idempotency key deduplication.
Impl: Add `OutboxEvent` table written in the same transaction as wallet mutation; a background worker (or Postgres LISTEN/NOTIFY) delivers events and marks `delivered_at`. Accept `idempotency_key: str` on every public method; store in `MobileTransaction.idempotency_key` with a unique index and return the existing txn on replay.
Found in: M-Pesa (SafariCom Daraja idempotency headers), MTN MoMo, Wave Africa

### CRITICAL: Fee Engine
Missing: Fee schedule is hard-coded per method; no configurable fee product table.
Impl: Add `FeeSchedule` model with `(product_code, tier, channel, band_min_cents, band_max_cents, flat_fee_cents, pct_bps, effective_date, expiry_date)`. `MobileMoneyService._calculate_fee(product_code, tier, amount_cents, channel)` queries the live schedule and returns `(fee_cents, vat_cents, excise_cents)`. Fee must be posted to a suspense GL account until settlement. M-Pesa publishes a tariff table with 14 bands; MTN MoMo supports country-level fee overrides.
Found in: M-Pesa, Airtel Money, MTN MoMo, Orange Money

### CRITICAL: Transaction Reversal — Partial and Time-Gated
Missing: reverse_transaction operates on full amount only and has no time-window or reason-code enforcement.
Impl: Add `reversal_window_seconds: int` to product config (M-Pesa: 24h, Wave: 30min). Accept `reversal_type: Literal["full","partial"]`, `partial_amount_cents: int | None`, `reason_code: str`. Post a reversal GL entry pair. Create a linked `MobileTransaction` with `txn_type=REVERSAL` and `original_txn_id`. Enforce that the original txn is not already reversed (idempotency on reversals).
Found in: M-Pesa, MTN MoMo, Airtel Money

### HIGH: Standing Orders / Scheduled Payments
Missing: No recurring payment or standing-order capability.
Impl: Add `StandingOrder(wallet_id, beneficiary_msisdn_or_till, amount_cents, frequency: Literal["daily","weekly","monthly"], next_execution_at, max_executions, executions_done, status)`. A scheduler job calls `MobileMoneyService.execute_standing_order(order_id)` which runs `send_money` or `pay_bill` and updates `next_execution_at`. Failure increments `retry_count`; after 3 failures the order moves to `SUSPENDED`. Orange Money and MTN MoMo both expose standing-order APIs as first-class products.
Found in: MTN MoMo, Orange Money, Airtel Money

### HIGH: Batch Disbursement (B2C / Bulk Pay)
Missing: No bulk disbursement — only single-recipient pay flows.
Impl: Add `DisbursementBatch(initiator_id, total_recipients, total_amount_cents, status, approved_by, approved_at)` and `DisbursementLine(batch_id, msisdn, amount_cents, narration, status, txn_id)`. `MobileMoneyService.process_batch(batch_id)` streams lines in chunks of 500, calls `send_money` per line inside a savepoint, collects successes/failures, and writes a `BatchResult`. M-Pesa B2C and MTN MoMo Disbursement are high-volume payroll/pension pipelines; Wave Africa's core use-case is bulk merchant payouts.
Found in: M-Pesa, MTN MoMo, Wave Africa

### HIGH: AML / Transaction Monitoring Hooks
Missing: No structuring detection, velocity checks, or SAR filing hooks.
Impl: Add `AMLCheckpoint.evaluate(wallet_id, amount_cents, counterparty_id, txn_type) -> AMLDecision(action: Literal["allow","review","block"], rule_ids: list[str])`. Plug into every public method before mutation. Rules minimum: 24h cumulative threshold, rapid round-trip detection (A→B then B→A within 10 min), new-account large-credit flag. `AMLDecision.review` moves txn to a `PENDING_REVIEW` queue. M-Pesa reports to CBK FIU; MTN MoMo GOIP feeds FATF-compliant monitoring systems.
Found in: M-Pesa, MTN MoMo, Airtel Money, Orange Money

### HIGH: Fraud Signals and Real-Time Scoring
Missing: No fraud scoring or device/SIM-swap detection.
Impl: Add `FraudSignal(wallet_id, signal_type, score, metadata_json, created_at)` written on every transaction. Signal types: `SIM_SWAP_RECENT` (block if SIM changed < 48h), `NEW_DEVICE_FINGERPRINT`, `VELOCITY_BREACH`, `GEO_ANOMALY`. `FraudEngine.score(context: TransactionContext) -> int` returns 0-100; score ≥ 80 blocks, 50-79 requires OTP re-auth. Store `fraud_score` on `MobileTransaction`. Wave Africa and M-Pesa use ML-based real-time scoring with sub-50ms SLA.
Found in: M-Pesa, Wave Africa, MTN MoMo

### HIGH: Notification / Message Orchestration
Missing: Transaction confirmation notifications are not modelled — no SMS, push, or USSD callback abstraction.
Impl: Add `NotificationRequest(recipient_msisdn, channel: Literal["sms","push","ussd"], template_code, context_json, priority, scheduled_at)` written transactionally. A delivery worker resolves the template, renders it, and dispatches via pluggable `NotificationAdapter`. Every public service method should enqueue a notification in the same DB transaction via `self._enqueue_notification(...)`. M-Pesa sends dual SMS (debit confirmation + credit advice) within 2 seconds; Wave Africa sends WhatsApp receipts.
Found in: M-Pesa, Wave Africa, MTN MoMo, Orange Money, Airtel Money

### HIGH: Dormancy Management
Missing: No dormancy detection, fee application, or reactivation workflow.
Impl: Add `last_transaction_at` to `MobileWallet`. A nightly job queries wallets where `last_transaction_at < now() - interval '6 months'` (CBK threshold) and sets `status=DORMANT`. Apply `dormancy_fee_cents` monthly from balance (floored at zero). On next customer-initiated transaction, run `MobileMoneyService.reactivate_wallet(msisdn)` which clears status, logs a `REACTIVATION` event, and notifies compliance. MTN MoMo and Airtel Money comply with Central Bank dormancy regulations in every market.
Found in: MTN MoMo, Airtel Money, Orange Money

### HIGH: Reconciliation Engine
Missing: No end-of-day reconciliation between wallet ledger positions and GL balances.
Impl: Add `ReconciliationRun(run_date, status, total_wallets_checked, breaks_found, breaks_resolved_at)` and `ReconciliationBreak(run_id, wallet_id, expected_balance_cents, actual_balance_cents, gl_balance_cents, break_type)`. `ReconciliationService.run_eod(date)` aggregates all txns for the day, sums debits/credits per wallet, compares against `MobileWallet.balance_cents`, and posts to `ReconciliationBreak`. Auto-resolves timing differences; escalates residual breaks to ops. M-Pesa runs intraday recs every 30 minutes; Wave Africa reconciles against float accounts at partner banks.
Found in: M-Pesa, Wave Africa, MTN MoMo, Orange Money

### MEDIUM: Product Configuration Model
Missing: Fee rates, limits, channels, and tier thresholds are hard-coded constants — not data-driven.
Impl: Add `MobileMoneyProduct(code, name, currency, tier_limits_json, channels_enabled_json, fee_schedule_id, min_txn_cents, max_txn_cents, active)`. `MobileMoneyService` loads product config at construction time (cached with a 60s TTL). This enables multi-product wallets (standard, diaspora, merchant, savings) within a single plugin instance. MTN MoMo and Orange Money deploy 5-10 product variants per country.
Found in: MTN MoMo, Orange Money, Airtel Money

### MEDIUM: Multi-Currency and FX Conversion
Missing: All amounts are implicitly KES; no FX or cross-currency send support.
Impl: Add `currency: str` to `MobileWallet` and `MobileTransaction`. Add `FXRate(from_currency, to_currency, rate_bps, provider, fetched_at, expires_at)`. `send_money` accepts optional `target_currency`; if different from source wallet currency, call `FXService.convert(amount_cents, from_ccy, to_ccy)` which locks a rate snapshot and records `fx_rate` and `fx_fee_cents` on the txn. Wave Africa's cross-border Senegal↔Ivory Coast corridors and MTN MoMo's international transfers depend on this.
Found in: Wave Africa, MTN MoMo, Orange Money

### MEDIUM: Audit Trail — Immutable Event Sourcing
Missing: `ImmutableRecordMixin` prevents mutation but there is no append-only event log capturing every state transition with actor, IP, and device.
Impl: Add `WalletAuditEvent(wallet_id, event_type, actor_id, actor_type, ip_address, device_fingerprint, before_state_json, after_state_json, created_at)` with no UPDATE/DELETE permissions granted at DB level. Emit on every status change, PIN change, KYC upgrade, limit override, and transaction. Orange Money and Airtel Money submit audit logs to Central Bank portals on demand.
Found in: M-Pesa, Orange Money, Airtel Money, MTN MoMo

### MEDIUM: Limit Override and Exemption Framework
Missing: Tier limits are absolute with no operator override, exemption, or exception workflow.
Impl: Add `LimitOverride(wallet_id, limit_type: Literal["daily","balance","single_txn"], override_value_cents, reason, approved_by, valid_from, valid_until, status)`. `_check_daily_limit` and `_check_max_balance` must query active overrides before rejecting. M-Pesa Lipa na M-Pesa accounts for large merchants and MTN MoMo enterprise clients routinely hold exemptions from retail tier caps.
Found in: M-Pesa, MTN MoMo, Airtel Money

### MEDIUM: USSD Session State Management
Missing: No USSD menu/session model — STK Push is present but USSD session continuity is absent.
Impl: Add `UssdSession(session_id, msisdn, menu_state, context_json, created_at, expires_at, completed)`. `UssdService.handle(session_id, msisdn, input_text) -> UssdResponse(text, action: Literal["continue","end"])` drives a state machine for the standard USSD menu tree (send money, withdraw, pay bill, check balance, change PIN). Session TTL = 90 seconds per GSMA spec. USSD is the primary channel for unbanked users across all five benchmarks.
Found in: M-Pesa, Airtel Money, MTN MoMo, Orange Money

### MEDIUM: Interoperability / Switching Layer
Missing: No inter-scheme routing — payments are confined to wallets within the same tenant.
Impl: Add `InteropRoute(destination_scheme: str, routing_prefix: str, endpoint_url, auth_header_secret, timeout_ms, active)`. `send_money` checks whether `recipient_msisdn` matches a registered route prefix; if so, delegates to `InteropClient.send(route, payload)` and records `txn.channel=INTEROP`. Supports PesaLink (Kenya), GhIPSS (Ghana), and GSMA Mobile Money API. Wave Africa's cross-operator sends and MTN MoMo's Pan-African corridor both rely on an interop switching layer.
Found in: Wave Africa, MTN MoMo, Orange Money

### MEDIUM: Savings / Interest-Bearing Sub-Wallet
Missing: No savings pocket, interest accrual, or lock-up period within the wallet.
Impl: Add `SavingsPocket(wallet_id, product_code, balance_cents, locked_until, interest_rate_bps, accrued_interest_cents, maturity_action: Literal["credit_wallet","rollover"])`. Nightly job calls `SavingsService.accrue_interest(date)` which posts interest credits as `MobileTransaction(txn_type=INTEREST_CREDIT)` and a matching GL credit to the interest expense account. MTN MoMo Savings and Orange Money Épargne are marketed as primary savings products in francophone Africa.
Found in: MTN MoMo, Orange Money, Airtel Money
