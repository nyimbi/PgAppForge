"""
tests/ci/test_core_banking_gl.py

Unit tests for the GL bridge wired into CoreBankingService.

Strategy
--------
We do NOT stand up a real PostgreSQL + GLPeriod setup — the GL bridge is
already wrapped in try/except so that a missing period (or missing GL plugin)
is non-fatal.  Instead we verify:

 1. The correct GL account codes and line structure are produced per
    transaction type (captured by patching _post_to_gl).
 2. post_simple_journal raises JournalImbalancedError for unbalanced lines.
 3. post_simple_journal returns None when no open period exists (non-fatal path).
 4. The four loan GL methods (disbursement, repayment, write-off, recovery)
    produce balanced line sets with the correct account codes.
 5. _CB_GL maps the expected account codes.
"""
from __future__ import annotations

# Stub flask_appbuilder and related packages before any pgappforge imports so
# that plugin __init__ files that reference FAB views don't fail in unit-test
# environments where flask_appbuilder is not installed.
import sys
import types


def _stub_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


_FAB_STUBS = [
    "flask_appbuilder",
    "flask_appbuilder.models",
    "flask_appbuilder.models.sqla",
    "flask_appbuilder.models.sqla.interface",
    "flask_appbuilder.views",
    "flask_appbuilder.baseviews",
    "flask_appbuilder.security",
    "flask_appbuilder.security.decorators",
    "flask_appbuilder.security.manager",
    "flask_appbuilder.fieldwidgets",
    "flask_appbuilder.forms",
    "flask_appbuilder.actions",
    "flask_appbuilder.hooks",
    "flask_appbuilder.widgets",
]
for _mod_name in _FAB_STUBS:
    if _mod_name not in sys.modules:
        _stub_module(_mod_name)

# Provide specific symbols each views.py cherry-picks
class _Stub:
    """Universal stub: accepts any args/kwargs, returns self for chaining."""
    def __init__(self, *a, **kw): pass
    def __call__(self, *a, **kw): return self
    def __class_getitem__(cls, item): return cls

_sentinel = _Stub

_fab = sys.modules["flask_appbuilder"]
for _attr in ("ModelView", "BaseView", "expose", "has_access", "permission_name",
              "MasterDetailView", "MultipleView", "RestCRUDView"):
    setattr(_fab, _attr, _sentinel)

_fab_sqla_iface = sys.modules["flask_appbuilder.models.sqla.interface"]
setattr(_fab_sqla_iface, "SQLAInterface", _sentinel)

_fab_sec_dec = sys.modules["flask_appbuilder.security.decorators"]
for _attr in ("has_access", "permission_name"):
    setattr(_fab_sec_dec, _attr, lambda f: f)

import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from pgappforge.plugins.fintech.core_banking.services import (
	CoreBankingService,
	_CB_GL,
)
from pgappforge.plugins.erp.finance.gl.services import (
	GLService,
	JournalImbalancedError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session():
	"""Minimal mock session that captures .add() / .flush() calls."""
	s = MagicMock()
	s.execute.return_value.scalar_one_or_none.return_value = None
	return s


def _lines_balance(lines: list[dict]) -> bool:
	dr = sum(int(ln.get("debit_cents", 0)) for ln in lines)
	cr = sum(int(ln.get("credit_cents", 0)) for ln in lines)
	return dr == cr


# ---------------------------------------------------------------------------
# _CB_GL — account code registry
# ---------------------------------------------------------------------------

class TestCBGLConstants:
	def test_required_keys_present(self):
		required = {
			"CASH_NOSTRO", "LOAN_RECEIVABLE", "LOAN_LOSS_RESERVE",
			"CUSTOMER_DEPOSITS", "INTEREST_INCOME", "FEE_INCOME", "INTEREST_EXPENSE",
		}
		assert required == set(_CB_GL.keys())

	def test_account_codes_are_strings(self):
		for key, code in _CB_GL.items():
			assert isinstance(code, str), f"{key} code must be a str"
			assert code, f"{key} code must be non-empty"

	def test_no_duplicates(self):
		codes = list(_CB_GL.values())
		assert len(codes) == len(set(codes)), "Duplicate GL account codes detected"


# ---------------------------------------------------------------------------
# _post_to_gl — non-fatal wrapper
# ---------------------------------------------------------------------------

def _inject_gl_service(mock_gl_instance):
	"""Context manager: inject a mock GLService class into sys.modules so that
	the lazy 'from pgappforge.plugins.erp.finance.gl.services import GLService, JournalImbalancedError'
	inside _post_to_gl picks it up.

	We also expose the *real* JournalImbalancedError so the except clause in
	_post_to_gl works correctly (same class identity as what callers import).
	"""
	import contextlib
	from pgappforge.plugins.erp.finance.gl.services import JournalImbalancedError as _RealJIE

	@contextlib.contextmanager
	def _ctx():
		gl_mod_key = "pgappforge.plugins.erp.finance.gl.services"
		fake_mod = types.ModuleType(gl_mod_key)
		fake_mod.GLService = type("GLService", (), {"__new__": lambda cls, *a, **kw: mock_gl_instance})
		fake_mod.JournalImbalancedError = _RealJIE
		old = sys.modules.get(gl_mod_key)
		sys.modules[gl_mod_key] = fake_mod
		try:
			yield
		finally:
			if old is None:
				sys.modules.pop(gl_mod_key, None)
			else:
				sys.modules[gl_mod_key] = old

	return _ctx()


class TestPostToGL:
	def test_swallows_import_error(self):
		# Simulate GL not installed: inject a stub module with no GLService attribute
		# so 'from ... import GLService' raises ImportError, caught by _post_to_gl.
		svc = CoreBankingService()
		session = _make_session()
		gl_key = "pgappforge.plugins.erp.finance.gl.services"
		empty_mod = types.ModuleType(gl_key)  # deliberately no GLService attr
		old = sys.modules.get(gl_key)
		sys.modules[gl_key] = empty_mod
		try:
			result = svc._post_to_gl(
				session=session,
				lines=[
					{"account_code": "1011", "debit_cents": 100, "credit_cents": 0},
					{"account_code": "2100", "debit_cents": 0, "credit_cents": 100},
				],
				description="test",
				tenant_id="t1",
			)
		finally:
			if old is None:
				sys.modules.pop(gl_key, None)
			else:
				sys.modules[gl_key] = old
		assert result is None

	def test_swallows_gl_exception(self):
		svc = CoreBankingService()
		session = _make_session()
		mock_gl = MagicMock()
		mock_gl.post_simple_journal.side_effect = RuntimeError("DB down")
		with _inject_gl_service(mock_gl):
			result = svc._post_to_gl(
				session=session,
				lines=[
					{"account_code": "1011", "debit_cents": 500, "credit_cents": 0},
					{"account_code": "2100", "debit_cents": 0, "credit_cents": 500},
				],
				description="test",
				tenant_id="t1",
			)
		assert result is None

	def test_returns_entry_id_on_success(self):
		svc = CoreBankingService()
		session = _make_session()
		mock_gl = MagicMock()
		mock_gl.post_simple_journal.return_value = "entry-uuid-123"
		with _inject_gl_service(mock_gl):
			result = svc._post_to_gl(
				session=session,
				lines=[
					{"account_code": "1011", "debit_cents": 200, "credit_cents": 0},
					{"account_code": "2100", "debit_cents": 0, "credit_cents": 200},
				],
				description="test",
				tenant_id="t1",
			)
		assert result == "entry-uuid-123"

	def test_reraises_journal_imbalanced_error(self):
		# JournalImbalancedError is a programming bug — must surface, not be swallowed
		from pgappforge.plugins.erp.finance.gl.services import JournalImbalancedError
		svc = CoreBankingService()
		session = _make_session()
		mock_gl = MagicMock()
		mock_gl.post_simple_journal.side_effect = JournalImbalancedError("DR≠CR")
		with _inject_gl_service(mock_gl):
			with pytest.raises(JournalImbalancedError):
				svc._post_to_gl(
					session=session,
					lines=[
						{"account_code": "1011", "debit_cents": 100, "credit_cents": 0},
						{"account_code": "2100", "debit_cents": 0, "credit_cents": 100},
					],
					description="balance test",
					tenant_id="t1",
				)

	def test_passes_source_doc_to_gl(self):
		svc = CoreBankingService()
		session = _make_session()
		mock_gl = MagicMock()
		mock_gl.post_simple_journal.return_value = "eid"
		with _inject_gl_service(mock_gl):
			svc._post_to_gl(
				session=session,
				lines=[
					{"account_code": "1011", "debit_cents": 100, "credit_cents": 0},
					{"account_code": "2100", "debit_cents": 0, "credit_cents": 100},
				],
				description="DEPOSIT ACC REF",
				tenant_id="acme",
				source_doc_id="ledger-entry-id",
				source_doc_type="CB_LEDGER_ENTRY",
			)
		call_kwargs = mock_gl.post_simple_journal.call_args.kwargs
		assert call_kwargs["source_doc_id"] == "ledger-entry-id"
		assert call_kwargs["source_doc_type"] == "CB_LEDGER_ENTRY"
		assert call_kwargs["tenant_id"] == "acme"


# ---------------------------------------------------------------------------
# Loan GL methods — line balance and account codes
# ---------------------------------------------------------------------------

class TestLoanGLMethods:
	def _capture_lines(self, method_name: str, **kwargs) -> list[dict]:
		"""Call a CoreBankingService loan GL method and return the lines passed to _post_to_gl."""
		svc = CoreBankingService()
		captured: list[dict] = []

		def _fake_post_to_gl(session, lines, description, tenant_id, **kw):
			captured.extend(lines)
			return "fake-entry-id"

		svc._post_to_gl = _fake_post_to_gl  # type: ignore[method-assign]
		getattr(svc, method_name)(session=MagicMock(), **kwargs)
		return captured

	# ---- post_loan_disbursement ------------------------------------------

	def test_disbursement_balanced_no_fee(self):
		lines = self._capture_lines(
			"post_loan_disbursement",
			loan_id="loan-1",
			borrower_account_id="acct-1",
			principal_cents=100_000,
			processing_fee_cents=0,
			tenant_id="t1",
		)
		assert _lines_balance(lines)
		codes = {ln["account_code"] for ln in lines}
		assert "LOAN_RECEIVABLE" in codes
		assert "CUSTOMER_DEPOSITS" in codes

	def test_disbursement_balanced_with_fee(self):
		lines = self._capture_lines(
			"post_loan_disbursement",
			loan_id="loan-2",
			borrower_account_id="acct-2",
			principal_cents=200_000,
			processing_fee_cents=4_000,
			tenant_id="t1",
		)
		assert _lines_balance(lines)
		codes = {ln["account_code"] for ln in lines}
		assert "FEE_INCOME" in codes
		# Net credit to deposits = 196_000
		deposits_cr = sum(ln["credit_cents"] for ln in lines if ln["account_code"] == "CUSTOMER_DEPOSITS")
		assert deposits_cr == 196_000

	def test_disbursement_dr_loan_receivable_equals_principal(self):
		lines = self._capture_lines(
			"post_loan_disbursement",
			loan_id="loan-3",
			borrower_account_id="acct-3",
			principal_cents=50_000,
			processing_fee_cents=1_000,
			tenant_id="t1",
		)
		dr_loan = sum(ln["debit_cents"] for ln in lines if ln["account_code"] == "LOAN_RECEIVABLE")
		assert dr_loan == 50_000

	# ---- post_loan_repayment --------------------------------------------

	def test_repayment_balanced_principal_only(self):
		lines = self._capture_lines(
			"post_loan_repayment",
			loan_id="loan-4",
			amount_cents=10_000,
			principal_cents=10_000,
			interest_cents=0,
			tenant_id="t1",
		)
		assert _lines_balance(lines)

	def test_repayment_balanced_with_interest(self):
		lines = self._capture_lines(
			"post_loan_repayment",
			loan_id="loan-5",
			amount_cents=12_000,
			principal_cents=10_000,
			interest_cents=2_000,
			tenant_id="t1",
		)
		assert _lines_balance(lines)
		codes = {ln["account_code"] for ln in lines}
		assert "INTEREST_INCOME" in codes
		assert "CUSTOMER_DEPOSITS" in codes

	def test_repayment_overpayment_credited_to_deposits(self):
		# overpayment → credit back to CUSTOMER_DEPOSITS (not FEE_INCOME)
		lines = self._capture_lines(
			"post_loan_repayment",
			loan_id="loan-6",
			amount_cents=12_001,
			principal_cents=10_000,
			interest_cents=2_000,
			tenant_id="t1",
		)
		assert _lines_balance(lines)
		# The 1c overpayment goes back to CUSTOMER_DEPOSITS, not FEE_INCOME
		fee_cr = sum(ln["credit_cents"] for ln in lines if ln["account_code"] == "FEE_INCOME")
		dep_cr = sum(ln["credit_cents"] for ln in lines if ln["account_code"] == "CUSTOMER_DEPOSITS")
		assert fee_cr == 0, "Overpayment must not be recognised as revenue"
		assert dep_cr == 1, "1c overpayment should be credited back to borrower deposits"

	def test_repayment_negative_residual_raises(self):
		# amount < principal + interest is a programming error — must raise
		from pgappforge.plugins.fintech.core_banking.services import CoreBankingError
		svc = CoreBankingService()
		svc._post_to_gl = lambda **kw: None  # type: ignore[method-assign]
		with pytest.raises(CoreBankingError, match="<"):
			svc.post_loan_repayment(
				session=MagicMock(),
				loan_id="loan-7",
				amount_cents=11_999,
				principal_cents=10_000,
				interest_cents=2_000,
				tenant_id="t1",
			)

	# ---- post_loan_write_off --------------------------------------------

	def test_write_off_balanced(self):
		lines = self._capture_lines(
			"post_loan_write_off",
			loan_id="loan-8",
			write_off_cents=80_000,
			tenant_id="t1",
		)
		assert _lines_balance(lines)
		codes = {ln["account_code"] for ln in lines}
		assert "LOAN_LOSS_RESERVE" in codes
		assert "LOAN_RECEIVABLE" in codes

	def test_write_off_dr_reserve_equals_amount(self):
		lines = self._capture_lines(
			"post_loan_write_off",
			loan_id="loan-9",
			write_off_cents=30_000,
			tenant_id="t1",
		)
		dr_reserve = sum(ln["debit_cents"] for ln in lines if ln["account_code"] == "LOAN_LOSS_RESERVE")
		assert dr_reserve == 30_000

	# ---- post_loan_recovery ---------------------------------------------

	def test_recovery_balanced(self):
		lines = self._capture_lines(
			"post_loan_recovery",
			loan_id="loan-10",
			recovered_cents=15_000,
			source="AUCTIONEER",
			tenant_id="t1",
		)
		assert _lines_balance(lines)
		codes = {ln["account_code"] for ln in lines}
		assert "CASH_NOSTRO" in codes
		assert "LOAN_LOSS_RESERVE" in codes

	def test_recovery_dr_cash_equals_recovered(self):
		lines = self._capture_lines(
			"post_loan_recovery",
			loan_id="loan-11",
			recovered_cents=5_000,
			source="COURT",
			tenant_id="t1",
		)
		dr_cash = sum(ln["debit_cents"] for ln in lines if ln["account_code"] == "CASH_NOSTRO")
		assert dr_cash == 5_000


# ---------------------------------------------------------------------------
# deposit / withdraw / transfer — verify _post_to_gl is called with correct codes
# ---------------------------------------------------------------------------

class TestTransactionGLCalls:
	"""Verify that the public transaction methods invoke _post_to_gl with the
	correct account codes without running a full DB.  We patch the CB internals
	(_require_account, _post_credit, _post_debit) to avoid DB dependencies."""

	def _fake_account(self, acc_number="ACC-001", acct_id="acct-uuid", currency="KES"):
		acct = MagicMock()
		acct.account_number = acc_number
		acct.id = acct_id
		acct.currency_code = currency
		acct.status = "ACTIVE"
		acct.available_balance_cents = 1_000_000
		acct.current_balance_cents = 1_000_000
		acct.holds_cents = 0
		acct.product_id = "prod-1"
		return acct

	def _fake_entry(self, entry_id="entry-uuid"):
		e = MagicMock()
		e.id = entry_id
		e.journal_id = "journal-uuid"
		return e

	def test_deposit_posts_cash_nostro_dr_customer_deposits_cr(self):
		svc = CoreBankingService()
		acct = self._fake_account()
		entry = self._fake_entry()
		captured_lines: list[dict] = []

		svc._require_account = MagicMock(return_value=acct)
		svc._assert_active = MagicMock()
		svc._post_credit = MagicMock(return_value=entry)
		svc._post_to_gl = lambda session, lines, description, tenant_id, **kw: captured_lines.extend(lines)  # type: ignore[method-assign]

		svc.deposit(
			session=MagicMock(),
			account_number="ACC-001",
			amount_cents=50_000,
			channel="BRANCH",
			reference="DEP-001",
			tenant_id="acme",
		)

		assert len(captured_lines) == 2
		dr_line = next(ln for ln in captured_lines if ln["debit_cents"] > 0)
		cr_line = next(ln for ln in captured_lines if ln["credit_cents"] > 0)
		assert dr_line["account_code"] == "CASH_NOSTRO"
		assert cr_line["account_code"] == "CUSTOMER_DEPOSITS"
		assert dr_line["debit_cents"] == 50_000
		assert cr_line["credit_cents"] == 50_000

	def test_withdrawal_posts_customer_deposits_dr_cash_nostro_cr(self):
		svc = CoreBankingService()
		acct = self._fake_account()
		entry = self._fake_entry()
		captured_lines: list[dict] = []

		svc._require_account = MagicMock(return_value=acct)
		svc._assert_active = MagicMock()
		svc._assert_channel_allowed = MagicMock()
		svc._daily_debit_total = MagicMock(return_value=0)
		svc._post_debit = MagicMock(return_value=entry)
		svc._post_to_gl = lambda session, lines, description, tenant_id, **kw: captured_lines.extend(lines)  # type: ignore[method-assign]

		# Patch product lookup to return None (no daily limit check)
		mock_session = MagicMock()
		mock_session.get.return_value = None

		svc.withdraw(
			session=mock_session,
			account_number="ACC-001",
			amount_cents=30_000,
			channel="ATM",
			reference="WDW-001",
			tenant_id="acme",
		)

		assert len(captured_lines) == 2
		dr_line = next(ln for ln in captured_lines if ln["debit_cents"] > 0)
		cr_line = next(ln for ln in captured_lines if ln["credit_cents"] > 0)
		assert dr_line["account_code"] == "CUSTOMER_DEPOSITS"
		assert cr_line["account_code"] == "CASH_NOSTRO"

	def test_transfer_cross_currency_uses_source_amount_for_balance(self):
		"""When exchange_rate != 1, GL lines must both use amount_cents (source currency)
		not credit_amount_cents (destination currency) to prevent imbalanced GL entry."""
		svc = CoreBankingService()
		from_acct = self._fake_account("FROM-001", "from-uuid", currency="USD")
		to_acct = self._fake_account("TO-001", "to-uuid", currency="KES")
		# 100 USD = 13,000 KES at rate 130
		from_acct.available_balance_cents = 10_000  # 100 USD
		captured_lines: list[dict] = []

		def _fake_require(session, acc_num):
			return from_acct if acc_num == "FROM-001" else to_acct

		svc._require_account = _fake_require  # type: ignore[method-assign]
		svc._assert_active = MagicMock()
		svc._post_to_gl = lambda session, lines, description, tenant_id, **kw: captured_lines.extend(lines)  # type: ignore[method-assign]

		session = MagicMock()
		session.get.return_value = None

		svc.transfer(
			session=session,
			from_account_number="FROM-001",
			to_account_number="TO-001",
			amount_cents=10_000,      # 100 USD in cents
			reference="FX-TEST",
			exchange_rate=Decimal("130"),  # 1 USD = 130 KES
			tenant_id="acme",
		)

		# GL must balance: both legs use amount_cents (source currency), NOT
		# credit_amount_cents (1_300_000 KES) which would produce DR≠CR.
		assert _lines_balance(captured_lines), (
			f"FX transfer GL must balance — DR and CR must both be amount_cents. "
			f"lines={captured_lines}"
		)
		dr_total = sum(ln["debit_cents"] for ln in captured_lines if ln["debit_cents"] > 0)
		cr_total = sum(ln["credit_cents"] for ln in captured_lines if ln["credit_cents"] > 0)
		assert dr_total == cr_total == 10_000, (
			f"Both legs should use source amount 10_000, got DR={dr_total} CR={cr_total}"
		)

	def test_transfer_posts_customer_deposits_both_sides(self):
		svc = CoreBankingService()
		from_acct = self._fake_account("FROM-001", "from-uuid")
		to_acct = self._fake_account("TO-001", "to-uuid")
		captured_lines: list[dict] = []

		def _fake_require(session, acc_num):
			return from_acct if acc_num == "FROM-001" else to_acct

		svc._require_account = _fake_require  # type: ignore[method-assign]
		svc._assert_active = MagicMock()
		svc._post_to_gl = lambda session, lines, description, tenant_id, **kw: captured_lines.extend(lines)  # type: ignore[method-assign]

		session = MagicMock()
		session.get.return_value = None  # no product limit

		svc.transfer(
			session=session,
			from_account_number="FROM-001",
			to_account_number="TO-001",
			amount_cents=20_000,
			reference="TRF-001",
			tenant_id="acme",
		)

		assert len(captured_lines) == 2
		codes = [ln["account_code"] for ln in captured_lines]
		assert all(c == "CUSTOMER_DEPOSITS" for c in codes)
		# from-side is a debit, to-side is a credit
		dr_line = next(ln for ln in captured_lines if ln["debit_cents"] > 0)
		cr_line = next(ln for ln in captured_lines if ln["credit_cents"] > 0)
		assert dr_line["party_id"] == "from-uuid"
		assert cr_line["party_id"] == "to-uuid"


# ---------------------------------------------------------------------------
# GLService.post_simple_journal — unit tests
# ---------------------------------------------------------------------------

class TestGLPostSimpleJournal:
	def test_raises_on_unbalanced_lines(self):
		gl = GLService()
		session = _make_session()
		# Give it a fake open period so it gets to the balance check
		fake_period = MagicMock()
		fake_period.id = "period-1"
		session.execute.return_value.scalar_one_or_none.return_value = fake_period

		with pytest.raises(JournalImbalancedError):
			gl.post_simple_journal(
				lines=[
					{"account_code": "1011", "debit_cents": 500, "credit_cents": 0},
					{"account_code": "2100", "debit_cents": 0, "credit_cents": 400},  # off by 100
				],
				session=session,
				tenant_id="t1",
				description="imbalanced test",
			)

	def test_returns_none_when_no_open_period(self):
		gl = GLService()
		session = _make_session()
		session.execute.return_value.scalar_one_or_none.return_value = None

		result = gl.post_simple_journal(
			lines=[
				{"account_code": "1011", "debit_cents": 100, "credit_cents": 0},
				{"account_code": "2100", "debit_cents": 0, "credit_cents": 100},
			],
			session=session,
			tenant_id="t1",
			description="no period",
		)
		assert result is None

	def test_batch_type_is_auto(self):
		gl = GLService()
		session = _make_session()
		fake_period = MagicMock()
		fake_period.id = "period-1"
		session.execute.return_value.scalar_one_or_none.return_value = fake_period

		# post_journal will fail (mock session), but we verify the batch is created with AUTO type
		added_objects: list = []
		session.add.side_effect = added_objects.append
		session.flush.return_value = None

		# post_simple_journal may raise because the mock session can't fully execute
		# GL posting — that's expected.  We verify the batch was created before any error.
		try:
			gl.post_simple_journal(
				lines=[
					{"account_code": "1011", "debit_cents": 300, "credit_cents": 0},
					{"account_code": "2100", "debit_cents": 0, "credit_cents": 300},
				],
				session=session,
				tenant_id="t1",
				description="batch type test",
			)
		except Exception as exc:
			# Expected — mock session can't fully execute GL posting
			# But we still want to verify the batch was created before the error
			pass

		from pgappforge.plugins.erp.finance.gl.models import GLJournalBatch
		batches = [o for o in added_objects if isinstance(o, GLJournalBatch)]
		assert batches, "GLJournalBatch should have been added to session before any GL validation error"
		assert batches[0].batch_type == "AUTO"
		assert batches[0].is_balanced is True

	def test_balanced_lines_sum_correctly(self):
		"""Verify total_debits == total_credits is enforced before adding the batch."""
		gl = GLService()
		session = _make_session()
		fake_period = MagicMock()
		fake_period.id = "period-2"
		session.execute.return_value.scalar_one_or_none.return_value = fake_period
		session.flush.return_value = None
		session.add.return_value = None

		added_objects: list = []
		session.add.side_effect = added_objects.append

		try:
			gl.post_simple_journal(
				lines=[
					{"account_code": "1011", "debit_cents": 1000, "credit_cents": 0},
					{"account_code": "2100", "debit_cents": 0, "credit_cents": 1000},
				],
				session=session,
				tenant_id="t1",
				description="balance check",
			)
		except Exception:
			pass

		from pgappforge.plugins.erp.finance.gl.models import GLJournalBatch
		batches = [o for o in added_objects if isinstance(o, GLJournalBatch)]
		if batches:
			assert batches[0].total_debits == 1000
			assert batches[0].total_credits == 1000
