"""
tests/ci/test_mobile_money.py

CI tests for the Mobile Money + Agency Banking plugin.

Covers:
  - MobileMoneyService: wallet registration, send_money, withdraw/deposit at agent,
    buy_goods, pay_bill, top_up_agent_float, calculate_agent_commission,
    settle_merchant, reverse_transaction, upgrade_kyc_tier, set_pin.
  - Error paths: insufficient balance, daily limit, max balance, PIN lockout,
    inactive wallet, insufficient float, duplicate commission.
  - Model immutability: MobileTransaction and AgentCommission block UPDATE.
  - __all__ completeness: every exported symbol enumerated via AST.
  - Fee lookup helper correctness.
  - Confirmation code and transaction ID format.

No mocks — uses SQLite in-memory via SQLAlchemy directly.
Plain sync functions (service layer is sync).
"""
from __future__ import annotations

import ast
import os
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Direct imports — pgappforge is installed in the project venv
# ---------------------------------------------------------------------------
from pgappforge.plugins.fintech.mobile_money.models import (
	Agent,
	AgentCommission,
	MerchantTill,
	MobileTransaction,
	MobileWallet,
)
from pgappforge.plugins.fintech.mobile_money.services import (
	InsufficientFloatError,
	LimitExceededError,
	MobileMoneyError,
	MobileMoneyService,
	PINError,
	WalletStatusError,
	_generate_confirmation_code,
	_generate_transaction_id,
	_hash_pin,
	_lookup_fee,
	_SEND_FEE_TIERS,
	_TIER_LIMITS,
	_WITHDRAWAL_FEE_TIERS,
)
from pgappforge.plugins.fintech.mobile_money.events import (
	AgentCommissionCalculatedEvent,
	AgentDepositEvent,
	AgentFloatToppedUpEvent,
	AgentWithdrawalEvent,
	BuyGoodsEvent,
	KYCUpgradedEvent,
	MerchantSettledEvent,
	MoneyTransferredEvent,
	PayBillEvent,
	TransactionReversedEvent,
	WalletRegisteredEvent,
	emit_mm_event,
)


# ---------------------------------------------------------------------------
# SQLite in-memory engine — session-scoped so each pytest session gets a
# fresh database; avoids "index already exists" from prior aborted runs.
# ---------------------------------------------------------------------------

def _build_schema_ddl() -> list[str]:
	"""Return CREATE TABLE / CREATE INDEX IF NOT EXISTS DDL for mm_* tables.

	We emit raw DDL so we're not at the mercy of SA's index-existence tracking
	against the shared MetaData singleton.  Each statement uses IF NOT EXISTS.
	"""
	return [
		# FK stub tables
		"CREATE TABLE IF NOT EXISTS foundation_party (id TEXT PRIMARY KEY)",
		"CREATE TABLE IF NOT EXISTS cb_account (id TEXT PRIMARY KEY)",
		# Domain event log (written by emit_event inside the same session)
		"""CREATE TABLE IF NOT EXISTS erp_domain_event_log (
			id TEXT PRIMARY KEY,
			event_id TEXT NOT NULL,
			event_type TEXT NOT NULL,
			aggregate_type TEXT,
			aggregate_id TEXT,
			tenant_id TEXT,
			payload TEXT NOT NULL DEFAULT '{}',
			published_at TEXT NOT NULL,
			correlation_id TEXT,
			causation_id TEXT
		)""",
		# mm_wallet
		"""CREATE TABLE IF NOT EXISTS mm_wallet (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			msisdn TEXT NOT NULL UNIQUE,
			customer_id TEXT NOT NULL,
			linked_account_id TEXT,
			wallet_type TEXT NOT NULL DEFAULT 'STANDARD',
			kyc_tier TEXT NOT NULL DEFAULT 'TIER_1',
			balance_cents INTEGER NOT NULL DEFAULT 0,
			max_balance_cents INTEGER NOT NULL DEFAULT 10000000,
			daily_limit_cents INTEGER NOT NULL DEFAULT 3000000,
			daily_used_cents INTEGER NOT NULL DEFAULT 0,
			pin_hash TEXT,
			pin_attempts INTEGER NOT NULL DEFAULT 0,
			pin_locked_until TEXT,
			status TEXT NOT NULL DEFAULT 'ACTIVE',
			last_transaction_at TEXT,
			device_imei TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_wallet_msisdn ON mm_wallet (msisdn)",
		"CREATE INDEX IF NOT EXISTS ix_mm_wallet_customer_id ON mm_wallet (customer_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_wallet_tenant_id ON mm_wallet (tenant_id)",
		# mm_agent (created before mm_transaction due to FK)
		"""CREATE TABLE IF NOT EXISTS mm_agent (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			agent_code TEXT NOT NULL UNIQUE,
			party_id TEXT NOT NULL,
			agent_type TEXT NOT NULL DEFAULT 'SUBAGENT',
			parent_agent_id TEXT,
			float_account_id TEXT NOT NULL,
			min_float_cents INTEGER NOT NULL DEFAULT 500000,
			max_float_cents INTEGER NOT NULL DEFAULT 100000000,
			current_float_cents INTEGER NOT NULL DEFAULT 0,
			commission_rate_pct NUMERIC NOT NULL DEFAULT 0,
			location TEXT,
			operating_hours TEXT,
			status TEXT NOT NULL DEFAULT 'ACTIVE',
			total_transactions INTEGER NOT NULL DEFAULT 0,
			total_volume_cents INTEGER NOT NULL DEFAULT 0,
			last_float_top_up_at TEXT,
			rating NUMERIC,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_agent_agent_code ON mm_agent (agent_code)",
		"CREATE INDEX IF NOT EXISTS ix_mm_agent_party_id ON mm_agent (party_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_agent_parent ON mm_agent (parent_agent_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_agent_tenant_id ON mm_agent (tenant_id)",
		# mm_transaction
		"""CREATE TABLE IF NOT EXISTS mm_transaction (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			transaction_id TEXT NOT NULL UNIQUE,
			transaction_type TEXT NOT NULL,
			sender_msisdn TEXT,
			recipient_msisdn TEXT,
			recipient_name TEXT,
			merchant_code TEXT,
			amount_cents INTEGER NOT NULL,
			fee_cents INTEGER NOT NULL DEFAULT 0,
			sender_balance_before_cents INTEGER,
			sender_balance_after_cents INTEGER,
			channel TEXT NOT NULL DEFAULT 'USSD',
			status TEXT NOT NULL DEFAULT 'COMPLETED',
			initiated_at TEXT NOT NULL,
			completed_at TEXT,
			failure_reason TEXT,
			stk_push_request_id TEXT,
			confirmation_code TEXT,
			agent_id TEXT,
			original_transaction_id TEXT,
			idempotency_key TEXT UNIQUE,
			fraud_score INTEGER,
			reversal_amount_cents INTEGER,
			reversal_reason_code TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_txn_transaction_id ON mm_transaction (transaction_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_txn_sender ON mm_transaction (sender_msisdn)",
		"CREATE INDEX IF NOT EXISTS ix_mm_txn_recipient ON mm_transaction (recipient_msisdn)",
		"CREATE INDEX IF NOT EXISTS ix_mm_txn_agent_id ON mm_transaction (agent_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_txn_tenant_id ON mm_transaction (tenant_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_txn_initiated_at ON mm_transaction (initiated_at)",
		# mm_agent_commission
		"""CREATE TABLE IF NOT EXISTS mm_agent_commission (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			agent_id TEXT NOT NULL,
			period_start TEXT NOT NULL,
			period_end TEXT NOT NULL,
			transaction_count INTEGER NOT NULL,
			transaction_volume_cents INTEGER NOT NULL,
			commission_earned_cents INTEGER NOT NULL,
			commission_paid_cents INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT 'PENDING',
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_agent_comm_agent_id ON mm_agent_commission (agent_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_agent_comm_tenant_id ON mm_agent_commission (tenant_id)",
		# mm_merchant_till
		"""CREATE TABLE IF NOT EXISTS mm_merchant_till (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			till_number TEXT NOT NULL UNIQUE,
			business_name TEXT NOT NULL,
			merchant_id TEXT NOT NULL,
			settlement_account_id TEXT NOT NULL,
			till_type TEXT NOT NULL DEFAULT 'BUY_GOODS',
			paybill_number TEXT UNIQUE,
			category TEXT,
			status TEXT NOT NULL DEFAULT 'ACTIVE',
			daily_settlement INTEGER NOT NULL DEFAULT 1,
			last_settlement_at TEXT,
			total_received_cents INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_till_merchant_id ON mm_merchant_till (merchant_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_till_tenant_id ON mm_merchant_till (tenant_id)",
		# mm_fee_schedule (CRITICAL: configurable fee engine)
		"""CREATE TABLE IF NOT EXISTS mm_fee_schedule (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			product_code TEXT NOT NULL,
			tier TEXT NOT NULL DEFAULT '*',
			channel TEXT NOT NULL DEFAULT '*',
			band_min_cents INTEGER NOT NULL DEFAULT 0,
			band_max_cents INTEGER NOT NULL,
			flat_fee_cents INTEGER NOT NULL DEFAULT 0,
			pct_bps INTEGER NOT NULL DEFAULT 0,
			vat_bps INTEGER NOT NULL DEFAULT 1600,
			excise_bps INTEGER NOT NULL DEFAULT 0,
			effective_date TEXT NOT NULL,
			expiry_date TEXT,
			status TEXT NOT NULL DEFAULT 'ACTIVE',
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_fee_product_tier ON mm_fee_schedule (product_code, tier, channel)",
		"CREATE INDEX IF NOT EXISTS ix_mm_fee_tenant ON mm_fee_schedule (tenant_id)",
		# mm_outbox_event (CRITICAL: transactional outbox)
		"""CREATE TABLE IF NOT EXISTS mm_outbox_event (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			event_type TEXT NOT NULL,
			aggregate_id TEXT NOT NULL,
			aggregate_type TEXT NOT NULL,
			payload TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			delivered_at TEXT,
			attempts INTEGER NOT NULL DEFAULT 0,
			last_error TEXT
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_outbox_tenant ON mm_outbox_event (tenant_id)",
		# mm_gl_journal_line (CRITICAL: double-entry GL subledger)
		"""CREATE TABLE IF NOT EXISTS mm_gl_journal_line (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			journal_id TEXT NOT NULL,
			mm_transaction_id TEXT,
			account_code TEXT NOT NULL,
			cost_centre TEXT,
			dr_cents INTEGER NOT NULL DEFAULT 0,
			cr_cents INTEGER NOT NULL DEFAULT 0,
			narration TEXT NOT NULL DEFAULT '',
			currency TEXT NOT NULL DEFAULT 'KES',
			posted_at TEXT NOT NULL DEFAULT (datetime('now')),
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_gl_journal_id ON mm_gl_journal_line (journal_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_gl_txn_id ON mm_gl_journal_line (mm_transaction_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_gl_tenant ON mm_gl_journal_line (tenant_id)",
		# mm_standing_order (HIGH: recurring payments)
		"""CREATE TABLE IF NOT EXISTS mm_standing_order (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			wallet_id TEXT NOT NULL,
			beneficiary_msisdn TEXT,
			beneficiary_till TEXT,
			payment_type TEXT NOT NULL DEFAULT 'SEND_MONEY',
			account_reference TEXT,
			amount_cents INTEGER NOT NULL,
			frequency TEXT NOT NULL,
			next_execution_at TEXT NOT NULL,
			max_executions INTEGER,
			executions_done INTEGER NOT NULL DEFAULT 0,
			retry_count INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT 'ACTIVE',
			last_executed_at TEXT,
			last_txn_id TEXT,
			suspension_reason TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_so_wallet_id ON mm_standing_order (wallet_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_so_tenant ON mm_standing_order (tenant_id)",
		# mm_disbursement_batch (HIGH: B2C bulk pay)
		"""CREATE TABLE IF NOT EXISTS mm_disbursement_batch (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			initiator_id TEXT NOT NULL,
			batch_reference TEXT NOT NULL DEFAULT '',
			description TEXT,
			total_recipients INTEGER NOT NULL DEFAULT 0,
			total_amount_cents INTEGER NOT NULL DEFAULT 0,
			processed_count INTEGER NOT NULL DEFAULT 0,
			success_count INTEGER NOT NULL DEFAULT 0,
			failure_count INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT 'DRAFT',
			approved_by TEXT,
			approved_at TEXT,
			started_at TEXT,
			completed_at TEXT,
			result_summary TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_batch_tenant ON mm_disbursement_batch (tenant_id)",
		# mm_disbursement_line (HIGH: B2C bulk pay)
		"""CREATE TABLE IF NOT EXISTS mm_disbursement_line (
			id TEXT PRIMARY KEY,
			batch_id TEXT NOT NULL,
			msisdn TEXT NOT NULL,
			amount_cents INTEGER NOT NULL,
			narration TEXT,
			status TEXT NOT NULL DEFAULT 'PENDING',
			txn_id TEXT,
			failure_reason TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			processed_at TEXT
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_dline_batch_id ON mm_disbursement_line (batch_id)",
		# mm_fraud_signal (HIGH: fraud scoring)
		"""CREATE TABLE IF NOT EXISTS mm_fraud_signal (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			wallet_id TEXT NOT NULL,
			mm_transaction_id TEXT,
			signal_type TEXT NOT NULL,
			score INTEGER NOT NULL DEFAULT 0,
			metadata_json TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_fraud_wallet_id ON mm_fraud_signal (wallet_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_fraud_tenant ON mm_fraud_signal (tenant_id)",
		# mm_notification_request (HIGH: notifications)
		"""CREATE TABLE IF NOT EXISTS mm_notification_request (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			recipient_msisdn TEXT NOT NULL,
			channel TEXT NOT NULL DEFAULT 'SMS',
			template_code TEXT NOT NULL,
			context_json TEXT NOT NULL DEFAULT '{}',
			priority INTEGER NOT NULL DEFAULT 2,
			scheduled_at TEXT NOT NULL DEFAULT (datetime('now')),
			sent_at TEXT,
			status TEXT NOT NULL DEFAULT 'PENDING',
			failure_reason TEXT,
			attempts INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_notif_tenant ON mm_notification_request (tenant_id)",
		# mm_reconciliation_run (HIGH: EOD reconciliation)
		"""CREATE TABLE IF NOT EXISTS mm_reconciliation_run (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			run_date TEXT NOT NULL,
			status TEXT NOT NULL DEFAULT 'RUNNING',
			total_wallets_checked INTEGER NOT NULL DEFAULT 0,
			breaks_found INTEGER NOT NULL DEFAULT 0,
			breaks_auto_resolved INTEGER NOT NULL DEFAULT 0,
			started_at TEXT NOT NULL DEFAULT (datetime('now')),
			completed_at TEXT,
			error_message TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now')),
			UNIQUE (tenant_id, run_date)
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_recon_tenant ON mm_reconciliation_run (tenant_id)",
		# mm_reconciliation_break (HIGH: EOD reconciliation)
		"""CREATE TABLE IF NOT EXISTS mm_reconciliation_break (
			id TEXT PRIMARY KEY,
			run_id TEXT NOT NULL,
			wallet_id TEXT,
			break_type TEXT NOT NULL,
			expected_balance_cents INTEGER NOT NULL DEFAULT 0,
			actual_balance_cents INTEGER NOT NULL DEFAULT 0,
			gl_balance_cents INTEGER NOT NULL DEFAULT 0,
			variance_cents INTEGER NOT NULL DEFAULT 0,
			resolution_status TEXT NOT NULL DEFAULT 'OPEN',
			resolved_at TEXT,
			resolution_note TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_recon_break_run ON mm_reconciliation_break (run_id)",
		# mm_wallet_audit_event (HIGH: immutable audit trail)
		"""CREATE TABLE IF NOT EXISTS mm_wallet_audit_event (
			id TEXT PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			wallet_id TEXT NOT NULL,
			event_type TEXT NOT NULL,
			actor_id TEXT,
			actor_type TEXT NOT NULL DEFAULT 'SYSTEM',
			ip_address TEXT,
			device_fingerprint TEXT,
			before_state_json TEXT,
			after_state_json TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		)""",
		"CREATE INDEX IF NOT EXISTS ix_mm_audit_wallet_id ON mm_wallet_audit_event (wallet_id)",
		"CREATE INDEX IF NOT EXISTS ix_mm_audit_tenant ON mm_wallet_audit_event (tenant_id)",
	]


@pytest.fixture(scope="session")
def db_engine():
	"""One SQLite :memory: engine per pytest session."""
	engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

	@sa_event.listens_for(engine, "connect")
	def _no_fk(dbapi_conn, _):
		dbapi_conn.execute("PRAGMA foreign_keys=OFF")

	# Register FK stubs in shared MetaData so SA can resolve FK references
	# at ORM query time (needed for relationship resolution even on SQLite).
	meta = MobileWallet.metadata
	if "foundation_party" not in meta.tables:
		sa.Table("foundation_party", meta, sa.Column("id", sa.String(36), primary_key=True))
	if "cb_account" not in meta.tables:
		sa.Table("cb_account", meta, sa.Column("id", sa.String(36), primary_key=True))

	# Use raw DDL with IF NOT EXISTS — bypasses SA index-tracking collision.
	with engine.connect() as conn:
		for stmt in _build_schema_ddl():
			conn.execute(sa.text(stmt))
		conn.commit()

	return engine


@pytest.fixture()
def session(db_engine):
	"""Per-test function-scoped session; rolls back after each test."""
	conn = db_engine.connect()
	trans = conn.begin()
	sess = Session(bind=conn)
	yield sess
	sess.close()
	trans.rollback()
	conn.close()


# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

TENANT = "test-tenant"


def _pid() -> str:
	return str(uuid.uuid4())


def _acct() -> str:
	return str(uuid.uuid4())


@pytest.fixture()
def svc(session):
	return MobileMoneyService(session, TENANT)


MSISDN_A = "254712345678"
MSISDN_B = "254798765432"


@pytest.fixture()
def wallet_a(svc):
	w = svc.register_wallet(MSISDN_A, _pid(), "TIER_1")
	svc.set_pin(MSISDN_A, "1234")
	return w


@pytest.fixture()
def wallet_b(svc):
	w = svc.register_wallet(MSISDN_B, _pid(), "TIER_1")
	svc.set_pin(MSISDN_B, "5678")
	return w


def _make_agent(session, float_cents: int = 5_000_000) -> Agent:
	agent = Agent(
		tenant_id=TENANT,
		agent_code=f"AGT{uuid.uuid4().hex[:6].upper()}",
		party_id=_pid(),
		float_account_id=_acct(),
		agent_type="SUBAGENT",
		min_float_cents=500_000,
		max_float_cents=100_000_000,
		current_float_cents=float_cents,
		commission_rate_pct=Decimal("1.50"),
		status="ACTIVE",
	)
	session.add(agent)
	session.flush()
	return agent


def _make_till(session, till_type: str = "BUY_GOODS") -> MerchantTill:
	num = str(100000 + (uuid.uuid4().int % 900000))
	paybill = str(200000 + (uuid.uuid4().int % 800000)) if till_type == "PAY_BILL" else None
	till = MerchantTill(
		tenant_id=TENANT,
		till_number=num,
		business_name="Test Shop",
		merchant_id=_pid(),
		settlement_account_id=_acct(),
		till_type=till_type,
		paybill_number=paybill,
		status="ACTIVE",
	)
	session.add(till)
	session.flush()
	return till


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
	def test_hash_pin_deterministic(self):
		assert _hash_pin("1234") == _hash_pin("1234")
		assert _hash_pin("1234") != _hash_pin("1235")
		assert len(_hash_pin("1234")) == 64

	def test_generate_transaction_id_format(self):
		alphanum = string.ascii_uppercase + string.digits
		for _ in range(20):
			tid = _generate_transaction_id()
			assert tid.startswith("MP"), tid
			assert len(tid) == 17, tid
			assert all(c in alphanum for c in tid[2:]), tid

	def test_generate_confirmation_code_format(self):
		for _ in range(20):
			code = _generate_confirmation_code()
			assert len(code) == 8, code
			assert code[:2].isalpha() and code[:2].isupper()

	def test_lookup_fee_send_tiers(self):
		assert _lookup_fee(5_000, _SEND_FEE_TIERS) == 0        # below first break
		assert _lookup_fee(10_000, _SEND_FEE_TIERS) == 0       # at first break
		assert _lookup_fee(10_001, _SEND_FEE_TIERS) == 500     # second tier
		assert _lookup_fee(50_000, _SEND_FEE_TIERS) == 500
		last_fee = _SEND_FEE_TIERS[-1][1]
		assert _lookup_fee(999_999_999, _SEND_FEE_TIERS) == last_fee

	def test_tier_limits_structure(self):
		assert set(_TIER_LIMITS) == {"TIER_1", "TIER_2", "TIER_3"}
		for tier, (max_bal, daily) in _TIER_LIMITS.items():
			assert isinstance(max_bal, int) and isinstance(daily, int)
			assert max_bal > daily, tier


# ---------------------------------------------------------------------------
# Tests: wallet registration
# ---------------------------------------------------------------------------

class TestWalletRegistration:
	def test_register_creates_row(self, svc):
		w = svc.register_wallet(MSISDN_A, _pid(), "TIER_1")
		assert w.id is not None
		assert w.msisdn == MSISDN_A
		assert w.kyc_tier == "TIER_1"
		assert w.status == "ACTIVE"
		assert w.balance_cents == 0
		assert w.max_balance_cents == _TIER_LIMITS["TIER_1"][0]
		assert w.daily_limit_cents == _TIER_LIMITS["TIER_1"][1]

	def test_register_duplicate_raises(self, svc):
		svc.register_wallet(MSISDN_A, _pid(), "TIER_1")
		with pytest.raises(MobileMoneyError, match="already has a wallet"):
			svc.register_wallet(MSISDN_A, _pid(), "TIER_1")

	def test_register_bad_tier_raises(self, svc):
		with pytest.raises(MobileMoneyError, match="Unknown KYC tier"):
			svc.register_wallet("254700000001", _pid(), "TIER_99")

	def test_set_pin_stores_hash(self, svc):
		svc.register_wallet(MSISDN_A, _pid(), "TIER_1")
		svc.set_pin(MSISDN_A, "9876")
		w = svc._get_wallet(MSISDN_A)
		assert w.pin_hash == _hash_pin("9876")

	def test_set_pin_non_digit_raises(self, svc):
		svc.register_wallet(MSISDN_A, _pid(), "TIER_1")
		with pytest.raises(PINError):
			svc.set_pin(MSISDN_A, "12X4")

	def test_set_pin_too_short_raises(self, svc):
		svc.register_wallet(MSISDN_A, _pid(), "TIER_1")
		with pytest.raises(PINError):
			svc.set_pin(MSISDN_A, "123")

	def test_upgrade_kyc_tier(self, svc):
		svc.register_wallet(MSISDN_A, _pid(), "TIER_1")
		w = svc.upgrade_kyc_tier(MSISDN_A, "TIER_2", "officer-1")
		assert w.kyc_tier == "TIER_2"
		assert w.max_balance_cents == _TIER_LIMITS["TIER_2"][0]
		assert w.daily_limit_cents == _TIER_LIMITS["TIER_2"][1]

	def test_upgrade_kyc_downgrade_raises(self, svc):
		svc.register_wallet(MSISDN_A, _pid(), "TIER_2")
		with pytest.raises(MobileMoneyError, match="upgrade only"):
			svc.upgrade_kyc_tier(MSISDN_A, "TIER_1", "officer-1")

	def test_upgrade_kyc_same_tier_raises(self, svc):
		svc.register_wallet(MSISDN_A, _pid(), "TIER_2")
		with pytest.raises(MobileMoneyError, match="upgrade only"):
			svc.upgrade_kyc_tier(MSISDN_A, "TIER_2", "officer-1")


# ---------------------------------------------------------------------------
# Tests: send_money
# ---------------------------------------------------------------------------

class TestSendMoney:
	def test_send_money_success(self, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 1_000_000
		session.flush()

		txn = svc.send_money(MSISDN_A, MSISDN_B, 500_000, "1234")

		assert txn.status == "COMPLETED"
		assert txn.transaction_type == "SEND_MONEY"
		assert txn.amount_cents == 500_000
		assert txn.fee_cents > 0
		assert txn.confirmation_code is not None and len(txn.confirmation_code) == 8
		assert txn.transaction_id.startswith("MP") and len(txn.transaction_id) == 17

		sender = svc._get_wallet(MSISDN_A)
		recip = svc._get_wallet(MSISDN_B)
		assert sender.balance_cents == 1_000_000 - 500_000 - txn.fee_cents
		assert recip.balance_cents == 500_000

	def test_send_money_balance_snapshot(self, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		txn = svc.send_money(MSISDN_A, MSISDN_B, 100_000, "1234")
		assert txn.sender_balance_before_cents == 2_000_000
		assert txn.sender_balance_after_cents == 2_000_000 - 100_000 - txn.fee_cents

	def test_send_money_wrong_pin(self, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 1_000_000
		session.flush()
		with pytest.raises(PINError):
			svc.send_money(MSISDN_A, MSISDN_B, 100_000, "0000")

	def test_send_money_pin_lockout(self, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 1_000_000
		session.flush()
		for _ in range(3):
			try:
				svc.send_money(MSISDN_A, MSISDN_B, 100_000, "0000")
			except PINError:
				pass
		with pytest.raises(PINError, match="locked"):
			svc.send_money(MSISDN_A, MSISDN_B, 100_000, "1234")

	def test_send_money_insufficient_balance(self, svc, wallet_a, wallet_b):
		with pytest.raises(MobileMoneyError, match="Insufficient balance"):
			svc.send_money(MSISDN_A, MSISDN_B, 500_000, "1234")

	def test_send_money_daily_limit_exhausted(self, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 50_000_000
		wallet_a.daily_used_cents = wallet_a.daily_limit_cents
		session.flush()
		with pytest.raises(LimitExceededError, match="Daily limit"):
			svc.send_money(MSISDN_A, MSISDN_B, 100_000, "1234")

	def test_send_money_zero_raises(self, svc, wallet_a, wallet_b):
		with pytest.raises(MobileMoneyError, match="positive"):
			svc.send_money(MSISDN_A, MSISDN_B, 0, "1234")

	def test_send_money_suspended_sender_raises(self, session, svc, wallet_a, wallet_b):
		wallet_a.status = "SUSPENDED"
		wallet_a.balance_cents = 1_000_000
		session.flush()
		with pytest.raises(WalletStatusError):
			svc.send_money(MSISDN_A, MSISDN_B, 100_000, "1234")

	def test_send_money_recipient_max_balance(self, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 20_000_000
		wallet_b.balance_cents = wallet_b.max_balance_cents
		session.flush()
		with pytest.raises(LimitExceededError, match="max balance"):
			svc.send_money(MSISDN_A, MSISDN_B, 1_000, "1234")


# ---------------------------------------------------------------------------
# Tests: agent withdraw / deposit
# ---------------------------------------------------------------------------

class TestAgentTransactions:
	def test_withdraw_success(self, session, svc, wallet_a):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		agent = _make_agent(session, float_cents=5_000_000)

		txn = svc.withdraw_at_agent(MSISDN_A, agent.agent_code, 500_000, "1234")

		assert txn.status == "COMPLETED"
		assert txn.transaction_type == "AGENT_WITHDRAWAL"
		assert txn.fee_cents > 0
		assert txn.agent_id == agent.id

		w = svc._get_wallet(MSISDN_A)
		assert w.balance_cents == 2_000_000 - 500_000 - txn.fee_cents
		assert agent.current_float_cents == 4_500_000

	def test_withdraw_insufficient_float(self, session, svc, wallet_a):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		agent = _make_agent(session, float_cents=100_000)
		with pytest.raises(InsufficientFloatError):
			svc.withdraw_at_agent(MSISDN_A, agent.agent_code, 500_000, "1234")

	def test_withdraw_inactive_agent_raises(self, session, svc, wallet_a):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		agent = _make_agent(session, float_cents=5_000_000)
		agent.status = "SUSPENDED"
		session.flush()
		with pytest.raises(MobileMoneyError, match="not active"):
			svc.withdraw_at_agent(MSISDN_A, agent.agent_code, 100_000, "1234")

	def test_deposit_success(self, session, svc, wallet_a):
		agent = _make_agent(session, float_cents=5_000_000)
		txn = svc.deposit_at_agent(MSISDN_A, agent.agent_code, 200_000)

		assert txn.status == "COMPLETED"
		assert txn.transaction_type == "AGENT_DEPOSIT"
		assert txn.fee_cents == 0

		w = svc._get_wallet(MSISDN_A)
		assert w.balance_cents == 200_000
		assert agent.current_float_cents == 4_800_000

	def test_deposit_float_too_low(self, session, svc, wallet_a):
		agent = _make_agent(session, float_cents=50_000)
		with pytest.raises(InsufficientFloatError):
			svc.deposit_at_agent(MSISDN_A, agent.agent_code, 200_000)

	def test_deposit_exceeds_wallet_max_balance(self, session, svc, wallet_a):
		wallet_a.balance_cents = wallet_a.max_balance_cents
		session.flush()
		agent = _make_agent(session, float_cents=5_000_000)
		with pytest.raises(LimitExceededError):
			svc.deposit_at_agent(MSISDN_A, agent.agent_code, 1_000)

	def test_agent_stats_updated(self, session, svc, wallet_a):
		wallet_a.balance_cents = 5_000_000
		session.flush()
		agent = _make_agent(session, float_cents=50_000_000)
		svc.withdraw_at_agent(MSISDN_A, agent.agent_code, 100_000, "1234")
		assert agent.total_transactions == 1
		assert agent.total_volume_cents == 100_000


# ---------------------------------------------------------------------------
# Tests: buy_goods / pay_bill
# ---------------------------------------------------------------------------

class TestMerchantPayments:
	def test_buy_goods_success(self, session, svc, wallet_a):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		till = _make_till(session, till_type="BUY_GOODS")

		txn = svc.buy_goods(MSISDN_A, till.till_number, 100_000, "1234")

		assert txn.status == "COMPLETED"
		assert txn.transaction_type == "BUY_GOODS"
		assert txn.merchant_code == till.till_number
		assert till.total_received_cents == 100_000

	def test_buy_goods_wrong_type_raises(self, session, svc, wallet_a):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		till = _make_till(session, till_type="PAY_BILL")
		with pytest.raises(MobileMoneyError, match="not BUY_GOODS"):
			svc.buy_goods(MSISDN_A, till.till_number, 100_000, "1234")

	def test_buy_goods_unknown_till_raises(self, svc, wallet_a):
		with pytest.raises(MobileMoneyError, match="not found"):
			svc.buy_goods(MSISDN_A, "999999", 100_000, "1234")

	def test_pay_bill_success(self, session, svc, wallet_a):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		till = _make_till(session, till_type="PAY_BILL")

		txn = svc.pay_bill(MSISDN_A, till.paybill_number, "ACC001", 150_000, "1234")

		assert txn.status == "COMPLETED"
		assert txn.transaction_type == "PAY_BILL"
		assert txn.merchant_code == till.paybill_number
		assert till.total_received_cents == 150_000

	def test_pay_bill_unknown_paybill_raises(self, svc, wallet_a):
		with pytest.raises(MobileMoneyError, match="not registered"):
			svc.pay_bill(MSISDN_A, "999999", "ACC001", 100_000, "1234")

	def test_pay_bill_wrong_pin_raises(self, session, svc, wallet_a):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		till = _make_till(session, till_type="PAY_BILL")
		with pytest.raises(PINError):
			svc.pay_bill(MSISDN_A, till.paybill_number, "ACC001", 100_000, "9999")


# ---------------------------------------------------------------------------
# Tests: float top-up
# ---------------------------------------------------------------------------

class TestFloatTopUp:
	def test_top_up_success(self, session, svc):
		agent = _make_agent(session, float_cents=1_000_000)
		result = svc.top_up_agent_float(agent.agent_code, 2_000_000, _acct())
		assert result["float_after_cents"] == 3_000_000
		assert result["float_before_cents"] == 1_000_000
		assert agent.current_float_cents == 3_000_000
		assert agent.last_float_top_up_at is not None

	def test_top_up_exceeds_max_raises(self, session, svc):
		agent = _make_agent(session, float_cents=99_000_000)
		with pytest.raises(LimitExceededError, match="max float"):
			svc.top_up_agent_float(agent.agent_code, 5_000_000, _acct())

	def test_top_up_zero_raises(self, session, svc):
		agent = _make_agent(session)
		with pytest.raises(MobileMoneyError, match="positive"):
			svc.top_up_agent_float(agent.agent_code, 0, _acct())

	def test_top_up_unknown_agent_raises(self, svc):
		with pytest.raises(MobileMoneyError, match="not found"):
			svc.top_up_agent_float("NOSUCHAGENT", 1_000_000, _acct())


# ---------------------------------------------------------------------------
# Tests: commission calculation
# ---------------------------------------------------------------------------

class TestCommission:
	def _seed_txns(self, session, agent: Agent, count: int, amount: int = 100_000):
		now = datetime.now(timezone.utc)
		for _ in range(count):
			session.add(MobileTransaction(
				tenant_id=TENANT,
				transaction_id=_generate_transaction_id(),
				transaction_type="AGENT_WITHDRAWAL",
				sender_msisdn=MSISDN_A,
				amount_cents=amount,
				fee_cents=3_500,
				channel="AGENT",
				status="COMPLETED",
				initiated_at=now,
				completed_at=now,
				confirmation_code=_generate_confirmation_code(),
				agent_id=agent.id,
			))
		session.flush()

	def test_calculate_commission(self, session, svc):
		agent = _make_agent(session)
		self._seed_txns(session, agent, 3)
		period = date.today()
		comm = svc.calculate_agent_commission(agent.id, period, period)

		assert comm.transaction_count == 3
		assert comm.transaction_volume_cents == 300_000
		# rate=1.50% → 300_000 * 0.015 = 4_500
		assert comm.commission_earned_cents == 4_500
		assert comm.status == "PENDING"

	def test_calculate_commission_no_transactions(self, session, svc):
		agent = _make_agent(session)
		period = date.today()
		comm = svc.calculate_agent_commission(agent.id, period, period)
		assert comm.transaction_count == 0
		assert comm.commission_earned_cents == 0

	def test_duplicate_period_raises(self, session, svc):
		agent = _make_agent(session)
		period = date.today()
		svc.calculate_agent_commission(agent.id, period, period)
		with pytest.raises(MobileMoneyError, match="already calculated"):
			svc.calculate_agent_commission(agent.id, period, period)

	def test_unknown_agent_raises(self, svc):
		with pytest.raises(MobileMoneyError, match="not found"):
			svc.calculate_agent_commission(str(uuid.uuid4()), date.today(), date.today())


# ---------------------------------------------------------------------------
# Tests: merchant settlement
# ---------------------------------------------------------------------------

class TestMerchantSettlement:
	def test_settle_no_transactions(self, session, svc):
		till = _make_till(session, till_type="BUY_GOODS")
		result = svc.settle_merchant(till.till_number, date.today())
		assert result["amount_cents"] == 0

	def test_settle_with_transactions(self, session, svc, wallet_a):
		till = _make_till(session, till_type="BUY_GOODS")
		today = date.today()
		ts = datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc)
		for _ in range(2):
			session.add(MobileTransaction(
				tenant_id=TENANT,
				transaction_id=_generate_transaction_id(),
				transaction_type="BUY_GOODS",
				sender_msisdn=MSISDN_A,
				merchant_code=till.till_number,
				amount_cents=200_000,
				fee_cents=1_000,
				channel="USSD",
				status="COMPLETED",
				initiated_at=ts,
				completed_at=ts,
				confirmation_code=_generate_confirmation_code(),
			))
		session.flush()

		result = svc.settle_merchant(till.till_number, today)
		assert result["amount_cents"] == 400_000

	def test_settle_inactive_till_raises(self, session, svc):
		till = _make_till(session, till_type="BUY_GOODS")
		till.status = "SUSPENDED"
		session.flush()
		with pytest.raises(MobileMoneyError, match="Cannot settle"):
			svc.settle_merchant(till.till_number, date.today())

	def test_settle_unknown_till_raises(self, svc):
		with pytest.raises(MobileMoneyError, match="not found"):
			svc.settle_merchant("NOTILL", date.today())


# ---------------------------------------------------------------------------
# Tests: reversal
# ---------------------------------------------------------------------------

class TestReversal:
	def test_reverse_success(self, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		txn = svc.send_money(MSISDN_A, MSISDN_B, 200_000, "1234")

		rev = svc.reverse_transaction(txn.transaction_id, "Customer dispute")

		assert rev.transaction_type == "REVERSAL"
		assert rev.original_transaction_id == txn.transaction_id
		assert rev.status == "COMPLETED"
		# Original row must be UNTOUCHED
		orig = session.get(MobileTransaction, txn.id)
		assert orig.status == "COMPLETED"
		assert orig.transaction_type == "SEND_MONEY"

	def test_reverse_nonexistent_raises(self, svc):
		with pytest.raises(MobileMoneyError, match="not found"):
			svc.reverse_transaction("MP99999999999999999", "test")

	def test_reverse_reversal_raises(self, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		txn = svc.send_money(MSISDN_A, MSISDN_B, 100_000, "1234")
		rev = svc.reverse_transaction(txn.transaction_id, "test")
		with pytest.raises(MobileMoneyError, match="Cannot reverse a reversal"):
			svc.reverse_transaction(rev.transaction_id, "double reverse")

	def test_reverse_non_completed_raises(self, session, svc):
		# Insert a PENDING transaction directly
		txn = MobileTransaction(
			tenant_id=TENANT,
			transaction_id=_generate_transaction_id(),
			transaction_type="SEND_MONEY",
			sender_msisdn=MSISDN_A,
			amount_cents=100_000,
			fee_cents=1_000,
			channel="USSD",
			status="PENDING",
			initiated_at=datetime.now(timezone.utc),
			confirmation_code=_generate_confirmation_code(),
		)
		session.add(txn)
		session.flush()
		with pytest.raises(MobileMoneyError, match="COMPLETED"):
			svc.reverse_transaction(txn.transaction_id, "reversal of pending")


# ---------------------------------------------------------------------------
# Tests: STK Push stub
# ---------------------------------------------------------------------------

class TestSTKPush:
	def test_stk_push_creates_pending_txn(self, session, svc, wallet_a):
		result = svc.initiate_stk_push(MSISDN_A, 500_000, "123456", "INV-001")
		assert result["status"] == "PENDING"
		assert result["checkout_request_id"] is not None
		assert result["transaction_id"].startswith("MP")

	def test_stk_push_zero_raises(self, svc, wallet_a):
		with pytest.raises(MobileMoneyError, match="positive"):
			svc.initiate_stk_push(MSISDN_A, 0, "123456", "INV-001")


# ---------------------------------------------------------------------------
# Tests: model immutability
# ---------------------------------------------------------------------------

class TestImmutability:
	def test_mobile_transaction_blocks_update(self, db_engine, session, svc, wallet_a, wallet_b):
		wallet_a.balance_cents = 2_000_000
		session.flush()
		txn = svc.send_money(MSISDN_A, MSISDN_B, 100_000, "1234")
		session.commit()

		from sqlalchemy.orm import Session as SA_Session
		with SA_Session(db_engine) as s2:
			t = s2.get(MobileTransaction, txn.id)
			t.amount_cents = 1
			with pytest.raises(RuntimeError, match="immutable"):
				s2.flush()

	def test_agent_commission_blocks_update(self, db_engine, session, svc):
		agent = _make_agent(session)
		comm = svc.calculate_agent_commission(agent.id, date.today(), date.today())
		session.commit()

		from sqlalchemy.orm import Session as SA_Session
		with SA_Session(db_engine) as s2:
			c = s2.get(AgentCommission, comm.id)
			c.commission_earned_cents = 999
			with pytest.raises(RuntimeError, match="immutable"):
				s2.flush()


# ---------------------------------------------------------------------------
# Tests: __all__ completeness (AST-based, no import needed)
# ---------------------------------------------------------------------------

_PLUGIN_BASE = os.path.normpath(
	os.path.join(os.path.dirname(__file__), "../../pgappforge/plugins/fintech/mobile_money")
)


def _get_all(filename: str) -> list[str]:
	path = os.path.join(_PLUGIN_BASE, filename)
	tree = ast.parse(open(path).read())
	for node in ast.walk(tree):
		if isinstance(node, ast.Assign):
			for t in node.targets:
				if isinstance(t, ast.Name) and t.id == "__all__":
					return [
						elt.value
						for elt in node.value.elts
						if isinstance(elt, ast.Constant)
					]
	return []


class TestAllExports:
	def test_models_all(self):
		exports = set(_get_all("models.py"))
		# Original models must still be present
		required_original = {
			"MobileWallet", "MobileTransaction", "Agent",
			"AgentCommission", "MerchantTill",
		}
		assert required_original.issubset(exports), (
			f"Missing original models: {required_original - exports}"
		)
		# New models (CRITICAL + HIGH gaps) must also be present
		required_new = {
			"FeeSchedule", "MMOutboxEvent", "MMGLJournalLine",
			"MMStandingOrder", "DisbursementBatch", "DisbursementLine",
			"FraudSignal", "NotificationRequest",
			"MMReconciliationRun", "ReconciliationBreak", "WalletAuditEvent",
		}
		assert required_new.issubset(exports), (
			f"Missing new models: {required_new - exports}"
		)

	def test_services_all(self):
		exports = set(_get_all("services.py"))
		required = {
			"MobileMoneyService", "MobileMoneyError", "InsufficientFloatError",
			"LimitExceededError", "PINError", "WalletStatusError",
		}
		assert required.issubset(exports)

	def test_events_all(self):
		exports = set(_get_all("events.py"))
		required = {
			"WalletRegisteredEvent", "MoneyTransferredEvent", "AgentDepositEvent",
			"AgentWithdrawalEvent", "BuyGoodsEvent", "PayBillEvent",
			"STKPushInitiatedEvent", "C2BNotificationEvent", "TransactionReversedEvent",
			"AgentFloatToppedUpEvent", "AgentFloatLowEvent", "AgentCommissionCalculatedEvent",
			"MerchantSettledEvent", "KYCUpgradedEvent", "WalletStatusChangedEvent",
			"emit_mm_event",
		}
		assert required.issubset(exports)

	def test_views_all(self):
		exports = set(_get_all("views.py"))
		required = {
			"WalletView", "TransactionView", "AgentView",
			"MerchantView", "AgentNetworkMapView", "FloatDashboard",
		}
		assert required.issubset(exports)

	def test_init_all_completeness(self):
		exports = _get_all("__init__.py")
		assert len(exports) >= 30
		# Spot-check cross-module re-exports
		exports_set = set(exports)
		assert "MobileMoneyPlugin" in exports_set
		assert "MobileMoneyService" in exports_set
		assert "MobileWallet" in exports_set
		assert "WalletView" in exports_set
		assert "WalletRegisteredEvent" in exports_set
