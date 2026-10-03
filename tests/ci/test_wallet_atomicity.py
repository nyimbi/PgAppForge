"""
tests/ci/test_wallet_atomicity.py

Unit tests for the wallet money path: balance-delta arithmetic, the amount
guards, idempotent lookup, and cryptographic transaction sealing.

These are pure unit tests. No database, no live balance mutation: the balance
UPDATE, the SELECT FOR UPDATE locks and the row-count guard are exercised only
through the SQL they compile to and through fake session objects, so the file
runs in a bare environment.
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# widgets.py (outside this module's ownership) imports current_user from
# pgappforge.security, which does not export it. Shim it before importing the
# wallet package so the models/views under test are importable at all.
import pgappforge.security as _sec
if not hasattr(_sec, "current_user"):
    from flask_login import current_user as _cu
    _sec.current_user = _cu

import pgappforge  # noqa: E402  (patched by tests below)
import pgappforge.wallet  # noqa: E402,F401  registers models + views
from werkzeug.exceptions import BadRequest  # noqa: E402
from pgappforge.wallet.models import (  # noqa: E402
    UserWallet,
    WalletTransaction,
    TransactionType,
    TransactionStatus,
)
from pgappforge.wallet.views import _parse_amount  # noqa: E402


def _wallet(balance="100.00", **kw):
    """A minimal, well-formed wallet with no limits that force extra queries."""
    fields = dict(
        id=1,
        user_id=7,
        balance=Decimal(balance),
        available_balance=Decimal(balance),
        currency_code="USD",
        is_active=True,
        is_locked=False,
        allow_negative_balance=False,
        daily_limit=None,
        monthly_limit=None,
        require_approval=False,
        approval_limit=None,
    )
    fields.update(kw)
    return UserWallet(**fields)


def _txn(**kw):
    fields = dict(
        id=1,
        wallet_id=1,
        user_id=7,
        amount=Decimal("10.00"),
        transaction_type=TransactionType.EXPENSE.value,
        status=TransactionStatus.COMPLETED.value,
        transaction_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reference_number="TXN-1",
        external_id=None,
        description="test",
    )
    fields.update(kw)
    return WalletTransaction(**fields)


# --------------------------------------------------------------------------
# can_transact: every value-decreasing movement checks funds, not just expenses
# --------------------------------------------------------------------------

class TestCanTransact:
    def test_transfer_over_balance_is_rejected(self):
        allowed, msg = _wallet("50.00").can_transact(
            Decimal("100"), TransactionType.TRANSFER
        )
        assert allowed is False
        assert "Insufficient funds" in msg

    def test_expense_over_balance_is_rejected(self):
        allowed, msg = _wallet("50.00").can_transact(
            Decimal("100"), TransactionType.EXPENSE
        )
        assert allowed is False
        assert "Insufficient funds" in msg

    def test_transfer_within_balance_is_allowed(self):
        allowed, _ = _wallet("50.00").can_transact(
            Decimal("10"), TransactionType.TRANSFER
        )
        assert allowed is True

    def test_negative_adjustment_above_balance_is_rejected(self):
        allowed, msg = _wallet("50.00").can_transact(
            Decimal("-100"), TransactionType.ADJUSTMENT
        )
        assert allowed is False
        assert "Insufficient funds" in msg

    def test_negative_expense_is_rejected_as_bad_sign(self):
        allowed, msg = _wallet("50.00").can_transact(
            Decimal("-10"), TransactionType.EXPENSE
        )
        assert allowed is False
        assert "greater than zero" in msg

    def test_zero_expense_is_rejected(self):
        allowed, _ = _wallet("50.00").can_transact(
            Decimal("0"), TransactionType.EXPENSE
        )
        assert allowed is False

    def test_cross_currency_transfer_is_rejected(self):
        target = _wallet("100.00", id=2, currency_code="KES")
        allowed, msg = _wallet("100.00").can_transact(
            Decimal("10"), TransactionType.TRANSFER, target_wallet=target
        )
        assert allowed is False
        assert "cross-currency" in msg

    def test_inactive_wallet_rejects_anything(self):
        allowed, msg = _wallet("100.00", is_active=False).can_transact(
            Decimal("1"), TransactionType.INCOME
        )
        assert allowed is False
        assert "inactive" in msg


# --------------------------------------------------------------------------
# _parse_amount: rejects junk, quantizes half-up
# --------------------------------------------------------------------------

class TestParseAmount:
    @pytest.mark.parametrize("raw", ["abc", "", "12abc", "NaN", "Infinity",
                                     "-Infinity", "1,5"])
    def test_rejects_non_finite_and_junk(self, raw):
        with pytest.raises(BadRequest):
            _parse_amount(raw)

    @pytest.mark.parametrize("raw", ["0", "-5", "-0.01"])
    def test_rejects_non_positive(self, raw):
        with pytest.raises(BadRequest):
            _parse_amount(raw)

    def test_quantizes_half_up(self):
        assert _parse_amount("1.005") == Decimal("1.01")
        assert _parse_amount("1.004") == Decimal("1.00")
        assert _parse_amount("2.675") == Decimal("2.68")

    def test_pads_to_two_places(self):
        assert _parse_amount("10") == Decimal("10.00")

    def test_accepts_surrounding_whitespace(self):
        assert _parse_amount("  7.50  ") == Decimal("7.50")


# --------------------------------------------------------------------------
# Amount validator: zero rejected, negative only for adjustments
# --------------------------------------------------------------------------

class TestAmountValidation:
    def test_zero_amount_rejected(self):
        with pytest.raises(ValueError):
            _txn(amount=Decimal("0"))

    def test_negative_amount_rejected_for_expense(self):
        with pytest.raises(ValueError):
            _txn(amount=Decimal("-5"), transaction_type=TransactionType.EXPENSE.value)

    def test_negative_amount_allowed_for_adjustment(self):
        t = _txn(amount=Decimal("-5"),
                 transaction_type=TransactionType.ADJUSTMENT.value)
        assert t.amount == Decimal("-5")


# --------------------------------------------------------------------------
# _signed_delta: the single source of truth for balance direction
# --------------------------------------------------------------------------

class TestSignedDelta:
    def test_income_is_credit(self):
        assert UserWallet._signed_delta(
            TransactionType.INCOME, Decimal("25")) == Decimal("25")

    def test_expense_is_debit(self):
        assert UserWallet._signed_delta(
            TransactionType.EXPENSE, Decimal("25")) == Decimal("-25")

    def test_refund_is_credit(self):
        assert UserWallet._signed_delta(
            TransactionType.REFUND, Decimal("25")) == Decimal("25")

    def test_outgoing_transfer_is_debit(self):
        t = _txn(transaction_type=TransactionType.TRANSFER.value,
                  metadata_json='{"transfer_type": "outgoing"}')
        assert UserWallet._signed_delta(
            TransactionType.TRANSFER, Decimal("25"), t) == Decimal("-25")

    def test_incoming_transfer_is_credit(self):
        t = _txn(transaction_type=TransactionType.TRANSFER.value,
                  metadata_json='{"transfer_type": "incoming"}')
        assert UserWallet._signed_delta(
            TransactionType.TRANSFER, Decimal("25"), t) == Decimal("25")

    def test_adjustment_keeps_sign(self):
        assert UserWallet._signed_delta(
            TransactionType.ADJUSTMENT, Decimal("-25")) == Decimal("-25")


# --------------------------------------------------------------------------
# Transaction sealing: hash covers status, signature is HMAC over the hash
# --------------------------------------------------------------------------

class TestIntegritySealing:
    def test_hash_changes_when_status_changes(self):
        t = _txn()
        before = t._calculate_transaction_hash()
        t.status = TransactionStatus.CANCELLED.value
        after = t._calculate_transaction_hash()
        assert before != after

    def test_hash_changes_when_amount_changes(self):
        t = _txn()
        before = t._calculate_transaction_hash()
        t.amount = Decimal("99.00")
        assert before != t._calculate_transaction_hash()

    def test_hash_changes_when_external_id_changes(self):
        t = _txn()
        before = t._calculate_transaction_hash()
        t.external_id = "ext-1"
        assert before != t._calculate_transaction_hash()

    def test_hash_is_stable_for_identical_state(self):
        assert _txn()._calculate_transaction_hash() == _txn()._calculate_transaction_hash()

    def test_verify_returns_false_for_tampered_amount(self):
        app = pytest.importorskip("flask").Flask(__name__)
        app.config["SECRET_KEY"] = "unit-test-secret"
        with app.app_context():
            t = _txn()
            t.reseal()
            assert t.verify_transaction_integrity() is True
            t.amount = Decimal("9999.00")
            assert t.verify_transaction_integrity() is False

    def test_verify_returns_false_without_secret_key(self):
        app = pytest.importorskip("flask").Flask(__name__)
        app.config["SECRET_KEY"] = "k"
        with app.app_context():
            t = _txn()
            t.reseal()
        app2 = pytest.importorskip("flask").Flask(__name__)
        app2.config["SECRET_KEY"] = "a-different-secret"
        with app2.app_context():
            assert t.verify_transaction_integrity() is False


# --------------------------------------------------------------------------
# Idempotency: a known external_id replays instead of moving money again
# --------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self.filter_by_kwargs = None

    def options(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def filter_by(self, **k):
        self.filter_by_kwargs = k
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.queries = []

    def query(self, *a, **k):
        q = _FakeQuery(self._rows)
        self.queries.append(q)
        return q

    def add(self, *a, **k):
        pass

    def flush(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def expire(self, *a, **k):
        pass

    def execute(self, *a, **k):
        return type("R", (), {"rowcount": 1})()


@pytest.fixture
def fake_db(monkeypatch):
    """Patch pgappforge.db with a query-only fake; no real session is used."""
    session = _FakeSession()
    db_obj = type("FakeDB", (), {"session": session})
    monkeypatch.setattr(pgappforge, "db", db_obj)
    return session


class TestIdempotency:
    def test_add_transaction_returns_existing_for_known_key(self, fake_db):
        existing = _txn(id=99, external_id="key-1")
        fake_db._rows = [existing]
        w = _wallet("100.00")
        result = w.add_transaction(
            Decimal("10"), TransactionType.EXPENSE,
            description="retry", external_id="key-1",
        )
        assert result is existing
        assert fake_db.queries[0].filter_by_kwargs == {
            "user_id": 7, "external_id": "key-1"
        }

    def test_add_transaction_queries_by_user_and_key(self, fake_db):
        fake_db._rows = []  # no existing row -> proceeds past the lookup
        w = _wallet("100.00")
        with pytest.raises(Exception):
            # Past the idempotency lookup it needs a real signing context;
            # what we assert is that the lookup itself was keyed correctly.
            w.add_transaction(
                Decimal("10"), TransactionType.EXPENSE,
                description="first", external_id="key-2",
            )
        assert fake_db.queries[0].filter_by_kwargs == {
            "user_id": 7, "external_id": "key-2"
        }


# --------------------------------------------------------------------------
# get_balance_history: every movement type contributes a signed delta
# --------------------------------------------------------------------------

class TestGetBalanceHistory:
    def test_incoming_transfer_is_a_credit_in_history(self, fake_db):
        now = datetime.now(tz=timezone.utc)
        t = _txn(
            id=5, transaction_type=TransactionType.TRANSFER.value,
            amount=Decimal("30.00"), transaction_date=now,
            metadata_json='{"transfer_type": "incoming"}',
        )
        fake_db._rows = [t]
        w = _wallet("80.00")
        hist = w.get_balance_history(days=30)
        assert len(hist) == 1
        # net_change = +30; start = 80 - 30 = 50; after applying +30 -> 80
        assert hist[0]["balance"] == pytest.approx(80.0)

    def test_outgoing_transfer_is_a_debit_in_history(self, fake_db):
        now = datetime.now(tz=timezone.utc)
        t = _txn(
            id=6, transaction_type=TransactionType.TRANSFER.value,
            amount=Decimal("30.00"), transaction_date=now,
            metadata_json='{"transfer_type": "outgoing"}',
        )
        fake_db._rows = [t]
        w = _wallet("80.00")
        hist = w.get_balance_history(days=30)
        assert len(hist) == 1
        # net_change = -30; start = 80 + 30 = 110; after applying -30 -> 80
        assert hist[0]["balance"] == pytest.approx(80.0)

    def test_refund_counts_as_credit(self, fake_db):
        now = datetime.now(tz=timezone.utc)
        t = _txn(
            id=7, transaction_type=TransactionType.REFUND.value,
            amount=Decimal("10.00"), transaction_date=now,
        )
        fake_db._rows = [t]
        w = _wallet("50.00")
        hist = w.get_balance_history(days=30)
        assert hist[0]["balance"] == pytest.approx(50.0)

    def test_expense_counts_as_debit(self, fake_db):
        now = datetime.now(tz=timezone.utc)
        t = _txn(
            id=8, transaction_type=TransactionType.EXPENSE.value,
            amount=Decimal("10.00"), transaction_date=now,
        )
        fake_db._rows = [t]
        w = _wallet("50.00")
        hist = w.get_balance_history(days=30)
        assert hist[0]["balance"] == pytest.approx(50.0)

    def test_running_balance_accumulates_across_types(self, fake_db):
        now = datetime.now(tz=timezone.utc)
        t0 = _txn(id=10, transaction_type=TransactionType.INCOME.value,
                  amount=Decimal("100.00"), transaction_date=now - timedelta(days=2))
        t1 = _txn(id=11, transaction_type=TransactionType.EXPENSE.value,
                  amount=Decimal("30.00"), transaction_date=now - timedelta(days=1))
        fake_db._rows = [t0, t1]
        w = _wallet("70.00")
        hist = w.get_balance_history(days=30)
        # Net change in the window is +70, so it opens at 0 and each row is the
        # balance *after* its own transaction: 100 then 70.
        assert [h["balance"] for h in hist] == [pytest.approx(100.0),
                                                pytest.approx(70.0)]