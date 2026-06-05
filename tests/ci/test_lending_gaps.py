"""
tests/ci/test_lending_gaps.py

Unit tests for CRITICAL and HIGH gap implementations in the lending plugin.

Strategy
--------
- Pure-logic tests with MagicMock sessions — no real DB, no Flask context.
- Tests exercise the service methods directly, asserting:
    - correct DB insertions (session.add called with right model type)
    - correct GL entry pairs (DR + CR legs, event_type, account codes)
    - idempotency guards (BatchJobRun lock)
    - dual-control enforcement
    - fee computation across all calculation bases
    - AML and fraud signal branching
    - outbox event writes
    - standing order amount strategies
    - credit facility limit / optimistic locking
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers — lightweight fakes that avoid Flask / SQLAlchemy bootstrap
# ---------------------------------------------------------------------------

def _make_loan(**kwargs) -> MagicMock:
	loan = MagicMock()
	loan.id = str(uuid.uuid4())
	loan.tenant_id = "t-001"
	loan.loan_number = "LN-20260101-AABBCC"
	loan.borrower_id = str(uuid.uuid4())
	loan.product_id = str(uuid.uuid4())
	loan.principal_cents = 100_000_00  # 100,000 KES
	loan.outstanding_principal_cents = 100_000_00
	loan.outstanding_interest_cents = 0
	loan.accrued_interest_cents = 0
	loan.arrears_principal_cents = 0
	loan.arrears_interest_cents = 0
	loan.penalty_cents = 0
	loan.days_past_due = 0
	loan.npa_classification = "PERFORMING"
	loan.provision_rate_pct = Decimal("1")
	loan.provision_amount_cents = 1_000_00
	loan.status = "ACTIVE"
	loan.interest_rate_pa = Decimal("18")
	loan.tenor_months = 12
	loan.next_installment_date = date.today() + timedelta(days=30)
	loan.next_installment_amount_cents = 9_168_00
	loan.disbursement_date = date.today()
	loan.first_repayment_date = date.today() + timedelta(days=30)
	loan.maturity_date = date.today() + timedelta(days=365)
	loan.currency = "KES"
	for k, v in kwargs.items():
		setattr(loan, k, v)
	return loan


def _make_session(loan: MagicMock | None = None) -> MagicMock:
	session = MagicMock()
	session.get.return_value = loan
	session.execute.return_value.scalar_one_or_none.return_value = None
	session.execute.return_value.scalars.return_value.all.return_value = []
	session.execute.return_value.scalar.return_value = False
	session.execute.return_value.rowcount = 0
	session.flush.return_value = None
	return session


def _bootstrap_stubs() -> None:
	"""Install all module stubs needed to import lending services/models
	without triggering Flask / flask_appbuilder bootstrap.

	Called once; subsequent calls are no-ops because sys.modules is checked.
	"""
	import sys
	import types

	# ---- Ensure pgappforge package itself is a stub (not the real one that
	#      imports Flask in __init__.py).
	# We DON'T replace it if already loaded; instead we just ensure sub-paths.
	# The trick: pre-populate every sub-package so Python never tries to exec
	# pgappforge/__init__.py for them.

	def _ensure(dotted: str, **attrs):
		if dotted not in sys.modules:
			mod = types.ModuleType(dotted)
			for k, v in attrs.items():
				setattr(mod, k, v)
			sys.modules[dotted] = mod
		else:
			mod = sys.modules[dotted]
			for k, v in attrs.items():
				if not hasattr(mod, k):
					setattr(mod, k, v)
		return sys.modules[dotted]

	# Top-level pgappforge — stub out to avoid Flask bootstrap
	if "pgappforge" not in sys.modules:
		_ensure("pgappforge")
	else:
		# Already loaded (possibly the real package) — that's OK only if Flask
		# is available.  If we got here Flask isn't available so we patch __init__
		# to not re-run:
		pass  # pgappforge already in sys.modules, sub-stubs below will cover it

	# Immutable record mixin
	class _IMR:
		@classmethod
		def _register_immutability(cls):
			pass

	# commons
	commons = _ensure(
		"pgappforge.plugins.erp.foundation.commons",
		ImmutableRecordMixin=_IMR,
		money_add=lambda a, b: a + b,
		money_multiply=lambda a, b: int(Decimal(str(a)) * Decimal(str(b))),
		money_divide=lambda a, b: int(Decimal(str(a)) / Decimal(str(b))),
		percent_of=lambda amount, pct: int(Decimal(str(amount)) * Decimal(str(pct)) / 100),
		format_currency=lambda *a, **kw: str(a[0]) if a else "",
		emit_event=lambda *a, **kw: None,
	)

	_ensure("pgappforge.plugins.erp")
	_ensure("pgappforge.plugins.erp.foundation")

	# Load the REAL pgappforge.models.sqla (has SQLAlchemy declarative Model).
	# It only depends on sqlalchemy + flask_sqlalchemy which are in the venv.
	# We must stub pgappforge top-level BEFORE loading it so it doesn't trigger
	# pgappforge/__init__.py's Flask imports.
	import importlib.util as _ilu
	from pathlib import Path as _P
	_root = _P(__file__).parent.parent.parent

	def _load_real(dotted: str, rel: str):
		if dotted in sys.modules and hasattr(sys.modules[dotted], "__spec__"):
			return sys.modules[dotted]
		spec = _ilu.spec_from_file_location(dotted, _root / rel)
		mod = _ilu.module_from_spec(spec)
		sys.modules[dotted] = mod
		spec.loader.exec_module(mod)
		return mod

	_ensure("pgappforge.models")
	_load_real("pgappforge.models.sqla", "pgappforge/models/sqla/__init__.py")
	_ensure("pgappforge.models.sqla.interface")

	# AuditMixin — load real one if possible, else stub
	try:
		_load_real("pgappforge.plugins.audit", "pgappforge/plugins/audit/__init__.py")
	except Exception:
		_ensure("pgappforge.plugins.audit", AuditMixin=object)

	# fintech sub-packages (so import resolution doesn't exec __init__s)
	# NOTE: do NOT stub lending.models here — it's loaded from file in _make_lms
	_ensure("pgappforge.plugins")
	_ensure("pgappforge.plugins.fintech")
	_ensure("pgappforge.plugins.fintech.lending")
	_ensure("pgappforge.plugins.fintech.core_banking")
	_ensure("pgappforge.plugins.fintech.core_banking.services")

	# api stub (pgappforge/__init__.py imports this)
	_ensure("pgappforge.api")

	# security stub
	_ensure("pgappforge.security")


def _load_file_module(dotted: str, path: str):
	"""Load a .py file as a module without executing any package __init__."""
	import importlib.util
	import sys

	if dotted in sys.modules:
		return sys.modules[dotted]
	spec = importlib.util.spec_from_file_location(dotted, path)
	mod = importlib.util.module_from_spec(spec)
	sys.modules[dotted] = mod
	spec.loader.exec_module(mod)
	return mod


def _make_lms():
	"""Load LoanManagementService directly from file, bypassing __init__.py chain."""
	import sys
	from pathlib import Path

	_bootstrap_stubs()

	root = Path(__file__).parent.parent.parent  # fab-ext/

	# Load models.py directly and register under canonical name so that lazy
	# `from pgappforge.plugins.fintech.lending.models import X` in services works.
	models_direct = "pgappforge.plugins.fintech.lending.models"
	# Remove any empty stub that _bootstrap_stubs may have pre-created
	existing = sys.modules.get(models_direct)
	if existing is None or not hasattr(existing, "Loan"):
		# Remove stale stub so _load_file_module can register the real module
		sys.modules.pop(models_direct, None)
		_load_file_module(models_direct, str(root / "pgappforge/plugins/fintech/lending/models.py"))

	# Load services.py directly
	svc_direct = "pgappforge.plugins.fintech.lending.services_direct"
	if svc_direct not in sys.modules:
		_load_file_module(svc_direct, str(root / "pgappforge/plugins/fintech/lending/services.py"))

	svc_mod = sys.modules[svc_direct]
	return svc_mod.LoanManagementService()


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def lms():
	return _make_lms()


# ===========================================================================
# CRITICAL 1 — GL double-entry posting
# ===========================================================================

class TestPostGLEntries:
	def test_posts_two_legs(self, lms):
		loan = _make_loan()
		session = _make_session(loan)
		vdate = date(2026, 6, 1)

		event_id = lms._post_gl_entries(
			session,
			loan_id=loan.id,
			event_type="disbursement",
			amount_cents=100_000_00,
			dr_account_code="LOAN_RECEIVABLE",
			cr_account_code="CASH",
			value_date=vdate,
			tenant_id=loan.tenant_id,
		)

		assert event_id is not None
		assert len(event_id) == 36  # UUID string
		# session.add called twice (DR + CR)
		assert session.add.call_count == 2
		added = [c.args[0] for c in session.add.call_args_list]
		legs = {e.leg for e in added}
		assert legs == {"DR", "CR"}
		event_ids = {e.event_id for e in added}
		assert len(event_ids) == 1  # same event_id on both legs

	def test_uses_provided_event_id(self, lms):
		loan = _make_loan()
		session = _make_session(loan)
		fixed_eid = str(uuid.uuid4())

		returned = lms._post_gl_entries(
			session,
			loan_id=loan.id,
			event_type="repayment",
			amount_cents=5_000_00,
			dr_account_code="CASH",
			cr_account_code="LOAN_RECEIVABLE",
			value_date=date.today(),
			event_id=fixed_eid,
			tenant_id=loan.tenant_id,
		)

		assert returned == fixed_eid

	def test_period_id_defaults_to_year_month(self, lms):
		loan = _make_loan()
		session = _make_session(loan)
		vdate = date(2026, 6, 15)

		lms._post_gl_entries(
			session,
			loan_id=loan.id,
			event_type="accrual",
			amount_cents=100,
			dr_account_code="INTEREST_RECEIVABLE",
			cr_account_code="INTEREST_INCOME",
			value_date=vdate,
			tenant_id=loan.tenant_id,
		)

		added = [c.args[0] for c in session.add.call_args_list]
		assert all(e.period_id == "2026-06" for e in added)


# ===========================================================================
# CRITICAL 2 — Fee engine
# ===========================================================================

class TestFeeEngine:
	def _make_fee(self, fee_type, basis, rate_or_amount):
		fee = MagicMock()
		fee.fee_type = fee_type
		fee.calculation_basis = basis
		fee.rate_or_amount_cents = rate_or_amount
		fee.is_active = True
		fee.gl_account_code = "ORIGINATION_FEE_INCOME"
		return fee

	def test_flat_fee(self, lms):
		fee = self._make_fee("origination", "flat", 50_000)  # 500 KES flat
		result = lms._compute_fee_cents(fee, 100_000_00, 100_000_00)
		assert result == 50_000

	def test_percent_principal(self, lms):
		# 1.5% of principal — stored as 150 basis-points (150 = 1.50%)
		fee = self._make_fee("processing", "percent_principal", 150)
		result = lms._compute_fee_cents(fee, 100_000_00, 100_000_00)
		# 1.5% of 10,000,000 cents = 150,000 cents
		assert result == 150_000

	def test_percent_outstanding(self, lms):
		# 2.0% of outstanding
		fee = self._make_fee("late", "percent_outstanding", 200)
		result = lms._compute_fee_cents(fee, 100_000_00, 50_000_00)
		# 2.0% of 5,000,000 = 100,000 cents
		assert result == 100_000

	def test_unknown_basis_raises(self, lms):
		fee = self._make_fee("annual", "unknown_basis", 100)
		with pytest.raises(ValueError, match="Unknown fee calculation_basis"):
			lms._compute_fee_cents(fee, 100_000_00, 100_000_00)

	def test_charge_loan_fees_inserts_fee_charge(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		fee_def = self._make_fee("origination", "flat", 50_000)
		fee_def.id = str(uuid.uuid4())
		fee_def.product_id = loan.product_id

		session.execute.return_value.scalars.return_value.all.return_value = [fee_def]
		# _post_gl_entries will call session.add, so we count them
		today = date.today()

		charges = lms._charge_loan_fees(session, loan, ["origination"], today)

		# At minimum one LoanFeeCharge added
		assert len(charges) >= 1
		assert session.add.called

	def test_waive_fee_dual_control(self, lms):
		with pytest.raises(ValueError, match="Dual-control"):
			lms.waive_fee(
				MagicMock(), "loan-1", "fee-1", "bad data", "user-A", "user-A"
			)


# ===========================================================================
# CRITICAL 3 — Interest accrual engine
# ===========================================================================

class TestInterestAccrual:
	def test_accrues_daily_interest(self, lms):
		loan = _make_loan(interest_rate_pa=Decimal("18"), outstanding_principal_cents=100_000_00)
		session = _make_session(loan)
		session.execute.return_value.scalar_one_or_none.return_value = None  # no existing accrual

		today = date(2026, 6, 1)
		entry = lms._accrue_interest(session, loan, today)

		assert entry is not None
		# 18% / 365 * 10,000,000 cents = ~493,150 cents per day (4,931.50 KES)
		# daily_rate = 18/365 = 0.04931...%; percent_of(10M, 4.931) = 493,150
		assert entry.accrued_interest_cents > 0
		assert entry.accrued_interest_cents < 600_000  # sanity cap (~6,000 KES/day)
		assert entry.status == "accrued"
		assert entry.accrual_date == today

	def test_accrual_is_idempotent(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		# Simulate existing accrual
		existing = MagicMock()
		session.execute.return_value.scalar_one_or_none.return_value = existing

		result = lms._accrue_interest(session, loan, date.today())
		assert result is existing
		# Should NOT add a new entry
		session.add.assert_not_called()

	def test_npa_loan_accrual_status_is_suspended(self, lms):
		loan = _make_loan(npa_classification="SUBSTANDARD")
		session = _make_session(loan)
		session.execute.return_value.scalar_one_or_none.return_value = None

		entry = lms._accrue_interest(session, loan, date.today())

		assert entry is not None
		assert entry.status == "suspended"

	def test_npa_transition_reverses_accruals(self, lms):
		loan = _make_loan(npa_classification="SUBSTANDARD")
		session = _make_session(loan)

		# Simulate 2 existing accrued entries
		acc1 = MagicMock(id=str(uuid.uuid4()), accrued_interest_cents=5_000, status="accrued",
						  outstanding_principal_cents=100_000_00, annual_rate=Decimal("18"))
		acc2 = MagicMock(id=str(uuid.uuid4()), accrued_interest_cents=5_000, status="accrued",
						  outstanding_principal_cents=100_000_00, annual_rate=Decimal("18"))
		session.execute.return_value.scalars.return_value.all.return_value = [acc1, acc2]

		total = lms._reverse_accruals_to_suspense(session, loan, date.today())

		assert total == 10_000
		# Two reversal InterestAccrualEntry rows + 2 GL entry pairs (DR+CR each) = 6 adds
		# At minimum the 2 reversal entries must be present
		assert session.add.call_count >= 2
		from pgappforge.plugins.fintech.lending.models import InterestAccrualEntry
		added_types = [type(c.args[0]).__name__ for c in session.add.call_args_list]
		reversal_entries = [t for t in added_types if t == "InterestAccrualEntry"]
		assert len(reversal_entries) == 2


# ===========================================================================
# CRITICAL 4 — Reversal / void workflow
# ===========================================================================

class TestReversalWorkflow:
	def test_reverse_repayment_dual_control(self, lms):
		with pytest.raises(ValueError, match="Dual-control"):
			lms.reverse_repayment(
				MagicMock(), "rep-1", "reason", "user-A", "user-A"
			)

	def test_reverse_repayment_creates_mirror_entry(self, lms):
		loan = _make_loan(status="ACTIVE")
		session = _make_session(loan)

		original = MagicMock()
		original.id = str(uuid.uuid4())
		original.loan_id = loan.id
		original.payment_date = date(2026, 5, 1)
		original.amount_cents = 9_168_00
		original.principal_applied_cents = 7_000_00
		original.interest_applied_cents = 2_168_00
		original.penalty_applied_cents = 0
		original.fees_applied_cents = 0
		original.reference_number = "REF-001"
		original.repayment_type = "normal"
		session.get.side_effect = lambda model, pk: loan if pk == loan.id else original

		# No paid schedules to reopen
		session.execute.return_value.scalars.return_value.all.return_value = []

		reversal = lms.reverse_repayment(
			session, original.id, "data entry error", "user-A", "user-B"
		)

		assert reversal.repayment_type == "reversal"
		assert reversal.reversed_repayment_id == original.id
		assert reversal.amount_cents == original.amount_cents
		# Loan balances unwound
		assert loan.outstanding_principal_cents == 100_000_00 + 7_000_00

	def test_cannot_reverse_a_reversal(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		rev_rep = MagicMock()
		rev_rep.id = str(uuid.uuid4())
		rev_rep.loan_id = loan.id
		rev_rep.repayment_type = "reversal"
		session.get.side_effect = lambda model, pk: loan if pk == loan.id else rev_rep

		with pytest.raises(ValueError, match="Cannot reverse a reversal"):
			lms.reverse_repayment(
				session, rev_rep.id, "mistake", "user-A", "user-B"
			)

	def test_void_disbursement_dual_control(self, lms):
		with pytest.raises(ValueError, match="Dual-control"):
			lms.void_disbursement(
				MagicMock(), "loan-1", "reason", "user-A", "user-A"
			)

	def test_void_disbursement_sets_voided_status(self, lms):
		loan = _make_loan(status="ACTIVE")
		session = _make_session(loan)

		app = MagicMock()
		app.status = "DISBURSED"

		def _get(model, pk):
			from pgappforge.plugins.fintech.lending.models import Loan, LoanApplication
			if pk == loan.id:
				return loan
			return app

		session.get.side_effect = _get
		session.execute.return_value.scalar.return_value = False  # no repayments
		session.execute.return_value.scalars.return_value.all.return_value = []

		result = lms.void_disbursement(
			session, loan.id, "wrong account", "ops-A", "ops-B"
		)

		assert result.status == "VOIDED"
		assert app.status == "APPROVED"


# ===========================================================================
# HIGH 1 — Standing orders
# ===========================================================================

class TestStandingOrders:
	def _make_order(self, strategy="scheduled_emi", **kwargs):
		order = MagicMock()
		order.id = str(uuid.uuid4())
		order.tenant_id = "t-001"
		order.loan_id = str(uuid.uuid4())
		order.status = "active"
		order.amount_strategy = strategy
		order.fixed_amount_cents = 9_168_00
		order.execution_day = date.today().day
		order.currency = "KES"
		order.valid_from = date.today() - timedelta(days=1)
		order.valid_to = None
		order.failure_retry_count = 0
		order.max_retries = 3
		order.next_retry_date = None
		order.last_failure_reason = None
		for k, v in kwargs.items():
			setattr(order, k, v)
		return order

	def test_fixed_strategy_uses_fixed_amount(self, lms):
		loan = _make_loan()
		order = self._make_order(strategy="fixed", fixed_amount_cents=5_000_00)
		session = _make_session(loan)

		session.execute.return_value.scalars.return_value.all.return_value = [order]
		session.get.return_value = loan

		with patch.object(lms, "apply_repayment", return_value={}) as mock_apply:
			result = lms.execute_standing_orders(session, as_of_date=date.today())

		mock_apply.assert_called_once()
		call_kwargs = mock_apply.call_args
		assert call_kwargs.kwargs.get("amount_cents") == 5_000_00 or call_kwargs.args[2] == 5_000_00

	def test_scheduled_emi_uses_next_installment(self, lms):
		loan = _make_loan(next_installment_amount_cents=9_168_00)
		order = self._make_order(strategy="scheduled_emi")
		session = _make_session(loan)

		session.execute.return_value.scalars.return_value.all.return_value = [order]
		session.get.return_value = loan

		with patch.object(lms, "apply_repayment", return_value={}) as mock_apply:
			lms.execute_standing_orders(session, as_of_date=date.today())

		mock_apply.assert_called_once()

	def test_failure_increments_retry_count(self, lms):
		loan = _make_loan()
		order = self._make_order(strategy="fixed", fixed_amount_cents=5_000_00)
		session = _make_session(loan)
		session.execute.return_value.scalars.return_value.all.return_value = [order]
		session.get.return_value = loan

		with patch.object(lms, "apply_repayment", side_effect=Exception("bank down")):
			result = lms.execute_standing_orders(session, as_of_date=date.today())

		assert order.failure_retry_count == 1
		assert order.next_retry_date is not None
		assert result["failed"] == 1

	def test_max_retries_cancels_order(self, lms):
		loan = _make_loan()
		order = self._make_order(strategy="fixed", fixed_amount_cents=5_000_00)
		order.failure_retry_count = 2  # one away from max
		session = _make_session(loan)
		session.execute.return_value.scalars.return_value.all.return_value = [order]
		session.get.return_value = loan

		with patch.object(lms, "apply_repayment", side_effect=Exception("still down")):
			lms.execute_standing_orders(session, as_of_date=date.today())

		assert order.status == "cancelled"


# ===========================================================================
# HIGH 2 — Batch job idempotency
# ===========================================================================

class TestBatchJobIdempotency:
	def test_acquire_creates_new_job_run(self, lms):
		session = _make_session()
		session.execute.return_value.scalar_one_or_none.return_value = None

		job_run = lms._acquire_batch_job(session, "daily_aging", date.today(), "t-001")

		assert session.add.called
		assert job_run.status == "running"

	def test_acquire_raises_if_already_completed(self, lms):
		session = _make_session()
		existing = MagicMock()
		existing.status = "completed"
		existing.id = str(uuid.uuid4())
		session.execute.return_value.scalar_one_or_none.return_value = existing

		with pytest.raises(RuntimeError, match="already completed"):
			lms._acquire_batch_job(session, "daily_aging", date.today(), "t-001")

	def test_acquire_raises_if_running(self, lms):
		session = _make_session()
		existing = MagicMock()
		existing.status = "running"
		existing.id = str(uuid.uuid4())
		session.execute.return_value.scalar_one_or_none.return_value = existing

		with pytest.raises(RuntimeError, match="currently running"):
			lms._acquire_batch_job(session, "daily_aging", date.today(), "t-001")

	def test_complete_marks_completed(self, lms):
		session = _make_session()
		job_run = MagicMock()

		lms._complete_batch_job(session, job_run, records_processed=42, records_failed=0)

		assert job_run.status == "completed"
		assert job_run.records_processed == 42

	def test_complete_marks_failed_on_error(self, lms):
		session = _make_session()
		job_run = MagicMock()

		lms._complete_batch_job(session, job_run, 10, error_detail="boom")

		assert job_run.status == "failed"
		assert job_run.error_detail == "boom"


# ===========================================================================
# HIGH 3 — Credit facility limit checking
# ===========================================================================

class TestCreditFacility:
	def _make_facility(self, **kwargs):
		fac = MagicMock()
		fac.id = str(uuid.uuid4())
		fac.tenant_id = "t-001"
		fac.customer_id = "cust-1"
		fac.approved_limit_cents = 500_000_00
		fac.available_balance_cents = 300_000_00
		fac.utilised_cents = 200_000_00
		fac.status = "active"
		fac.expiry_date = None
		fac.version = 1
		for k, v in kwargs.items():
			setattr(fac, k, v)
		return fac

	def test_check_limit_allows_within_balance(self, lms):
		fac = self._make_facility()
		session = _make_session()
		session.execute.return_value.scalar_one_or_none.return_value = fac

		result = lms.check_limit(session, fac.id, 100_000_00)

		assert result["allowed"] is True
		assert result["available_balance_cents"] == 300_000_00

	def test_check_limit_raises_on_excess(self, lms):
		from pgappforge.plugins.fintech.lending.services_direct import LimitExceededError

		fac = self._make_facility(available_balance_cents=50_000_00)
		session = _make_session()
		session.execute.return_value.scalar_one_or_none.return_value = fac

		with pytest.raises(LimitExceededError):
			lms.check_limit(session, fac.id, 100_000_00)

	def test_check_limit_raises_on_expired_facility(self, lms):
		fac = self._make_facility(expiry_date=date(2020, 1, 1))
		session = _make_session()
		session.execute.return_value.scalar_one_or_none.return_value = fac

		with pytest.raises(ValueError, match="expired"):
			lms.check_limit(session, fac.id, 1_00)

	def test_drawdown_decrements_available(self, lms):
		fac = self._make_facility()
		session = _make_session()
		session.execute.return_value.scalar_one_or_none.return_value = fac
		session.execute.return_value.scalar_one.return_value = fac

		with patch.object(lms, "check_limit", return_value={"allowed": True}):
			lms.drawdown_facility(session, fac.id, 100_000_00)

		assert fac.available_balance_cents == 300_000_00 - 100_000_00
		assert fac.utilised_cents == 200_000_00 + 100_000_00
		assert fac.version == 2

	def test_repay_restores_available(self, lms):
		fac = self._make_facility()
		session = _make_session()
		session.execute.return_value.scalar_one_or_none.return_value = fac

		lms.repay_facility(session, fac.id, 50_000_00)

		assert fac.available_balance_cents == 300_000_00 + 50_000_00
		assert fac.utilised_cents == 200_000_00 - 50_000_00
		assert fac.version == 2


# ===========================================================================
# HIGH 4 — AML screening
# ===========================================================================

class TestAMLScreening:
	def test_clear_result_returns_screening(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		with patch.object(lms, "_call_aml_provider", return_value={"status": "clear", "risk_score": 0.0, "hits": []}):
			result = lms.aml_screen(session, loan.id, "cust-1", 100_000_00)

		assert result.status == "clear"
		session.add.assert_called_once()

	def test_blocked_raises_aml_error(self, lms):
		from pgappforge.plugins.fintech.lending.services_direct import AMLBlockedError

		loan = _make_loan()
		session = _make_session(loan)

		with patch.object(lms, "_call_aml_provider", return_value={"status": "blocked", "risk_score": 95.0, "hits": []}):
			with pytest.raises(AMLBlockedError):
				lms.aml_screen(session, loan.id, "cust-1", 100_000_00)

	def test_review_sets_pending_aml_review(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		with patch.object(lms, "_call_aml_provider", return_value={"status": "review", "risk_score": 55.0, "hits": []}):
			result = lms.aml_screen(session, loan.id, "cust-1", 100_000_00)

		assert loan.status == "PENDING_AML_REVIEW"
		assert result.status == "review"

	def test_release_aml_hold_restores_approved(self, lms):
		loan = _make_loan(status="PENDING_AML_REVIEW")
		session = _make_session(loan)
		# No existing review record to update
		session.execute.return_value.scalar_one_or_none.return_value = None

		lms.release_aml_hold(session, loan.id, "compliance-officer-1")

		assert loan.status == "APPROVED"

	def test_release_aml_hold_wrong_status_raises(self, lms):
		loan = _make_loan(status="ACTIVE")
		session = _make_session(loan)

		with pytest.raises(ValueError, match="PENDING_AML_REVIEW"):
			lms.release_aml_hold(session, loan.id, "officer-1")


# ===========================================================================
# HIGH 5 — Fraud signal capture
# ===========================================================================

class TestFraudSignal:
	def test_allow_action_below_threshold(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		sig = lms.capture_fraud_signal(
			session, loan.id, "provider-x", "velocity",
			score=Decimal("20"), threshold=Decimal("60"),
		)

		assert sig.action == "allow"

	def test_step_up_between_70pct_and_threshold(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		# 70% of 60 = 42; score=50 → step_up
		sig = lms.capture_fraud_signal(
			session, loan.id, "provider-x", "velocity",
			score=Decimal("50"), threshold=Decimal("60"),
		)

		assert sig.action == "step_up"

	def test_decline_above_threshold(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		sig = lms.capture_fraud_signal(
			session, loan.id, "provider-x", "synthetic_identity",
			score=Decimal("90"), threshold=Decimal("60"),
		)

		assert sig.action == "decline"


# ===========================================================================
# HIGH 6 — Transactional outbox
# ===========================================================================

class TestTransactionalOutbox:
	def test_write_outbox_creates_pending_event(self, lms):
		session = _make_session()

		event = lms._write_outbox(
			session,
			aggregate_type="Loan",
			aggregate_id="loan-123",
			event_type="ln.loan.disbursed",
			payload={"amount": 100},
			tenant_id="t-001",
		)

		assert event.status == "pending"
		assert event.event_type == "ln.loan.disbursed"
		assert event.aggregate_type == "Loan"
		# Does NOT flush — caller owns transaction
		session.flush.assert_not_called()

	def test_relay_publishes_pending_events(self, lms):
		session = _make_session()

		ev1 = MagicMock()
		ev1.id = str(uuid.uuid4())
		ev1.event_type = "ln.loan.disbursed"
		ev1.aggregate_type = "Loan"
		ev1.aggregate_id = "loan-1"
		ev1.payload_json = {}
		ev1.tenant_id = "t-001"
		ev1.retry_count = 0

		session.execute.return_value.scalars.return_value.all.return_value = [ev1]

		result = lms.relay_outbox_events(session, batch_size=10)

		assert result["published"] == 1
		assert ev1.status == "published"
		assert ev1.published_at is not None

	def test_relay_marks_failed_after_3_retries(self, lms):
		session = _make_session()

		ev1 = MagicMock()
		ev1.id = str(uuid.uuid4())
		ev1.event_type = "ln.loan.disbursed"
		ev1.aggregate_type = "Loan"
		ev1.aggregate_id = "loan-1"
		ev1.payload_json = {}
		ev1.tenant_id = "t-001"
		ev1.retry_count = 2  # already at 2; next failure → status=failed

		session.execute.return_value.scalars.return_value.all.return_value = [ev1]

		with patch("pgappforge.plugins.fintech.lending.services_direct.emit_event", side_effect=Exception("broker down")):
			result = lms.relay_outbox_events(session, batch_size=10)

		assert result["failed"] == 1
		assert ev1.status == "failed"


# ===========================================================================
# HIGH 7 — Notification scheduling
# ===========================================================================

class TestNotificationScheduling:
	def test_schedule_notification_creates_pending_record(self, lms):
		loan = _make_loan()
		session = _make_session(loan)

		notif = lms.schedule_notification(
			session,
			loan_id=loan.id,
			notification_type="repayment.due_soon_3",
			channel="sms",
			recipient="+254700000000",
			payload={"amount_cents": 9_168_00},
			tenant_id=loan.tenant_id,
		)

		assert notif.status == "pending"
		assert notif.channel == "sms"
		assert notif.notification_type == "repayment.due_soon_3"
		session.add.assert_called_once()

	def test_due_soon_notifications_scheduled_for_t1_and_t3(self, lms):
		today = date.today()
		loan_t1 = _make_loan(next_installment_date=today + timedelta(days=1))
		loan_t3 = _make_loan(next_installment_date=today + timedelta(days=3))
		session = _make_session()
		session.execute.return_value.scalars.return_value.all.return_value = [loan_t1, loan_t3]

		with patch.object(lms, "schedule_notification", return_value=MagicMock()) as mock_sched:
			result = lms.send_due_soon_notifications(
				session, as_of_date=today, channels=["sms", "email"]
			)

		# 2 loans × 2 channels = 4 calls
		assert mock_sched.call_count == 4
		assert result["scheduled"] == 4
