"""Ledger service tests.

The ledger is PostgreSQL-only (``FOR UPDATE``, ``Numeric``, check constraints),
so the behaviour tests run against a real database and skip cleanly when none is
reachable. Pure-function and model-level tests always run.
"""

import os
import uuid
from decimal import Decimal

import pytest

# AuditMixin declares created_by/changed_by relationships to the security User
# model; register it before any mapper configuration happens.
import pgappforge.security.sqla.models  # noqa: F401
from pgappforge.ledger.models import LedgerAccount, LedgerEntry, LedgerPosting
from pgappforge.ledger.service import (
    AccountNotFoundError,
    DoubleEntryError,
    IdempotencyConflict,
    InsufficientFundsError,
    LedgerService,
    LockedAccount,
    Posting,
    _to_money,
    rebuild_account_balances,
)

DSN_CANDIDATES = [
    dsn
    for dsn in (
        os.environ.get("PGAF_TEST_DATABASE_URI"),
        os.environ.get("SQLALCHEMY_DATABASE_URI"),
        "postgresql+psycopg2:///pgaf_ledger_test",
        "postgresql+psycopg2:///pgaf_test",
        "postgresql+psycopg2://pguser:pguserpassword@127.0.0.1:5432/app",
    )
    if dsn and dsn.startswith("postgresql")
]


def _connect():
    """First reachable PostgreSQL DSN from the candidates, or None."""
    from sqlalchemy import create_engine

    for dsn in DSN_CANDIDATES:
        try:
            engine = create_engine(dsn, pool_pre_ping=True, connect_args={"connect_timeout": 3})
            with engine.connect():
                pass
            return engine
        except Exception:
            continue
    return None


@pytest.fixture(scope="module")
def pg_session():
    from sqlalchemy.orm import Session

    engine = _connect()
    if engine is None:
        pytest.skip(f"no reachable PostgreSQL among {DSN_CANDIDATES}")
    session = Session(engine)
    from pgappforge.models.sqla import Model

    from pgappforge.security.sqla.models import User

    # Start from a clean ledger schema so model changes are exercised.
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS ab_ledger_postings, ab_ledger_entries, ab_ledger_accounts CASCADE"))
    Model.metadata.create_all(
        engine,
        tables=[User.__table__, LedgerAccount.__table__, LedgerEntry.__table__, LedgerPosting.__table__],
        checkfirst=True,
    )
    suffix = uuid.uuid4().hex[:8]
    actor = User(
        username=f"ledger_{suffix}",
        email=f"ledger_{suffix}@example.com",
        first_name="Ledger",
        last_name="Test",
        password="x",
        active=True,
    )
    session.add(actor)
    session.commit()
    actor_id = actor.id
    def _account(code, name, account_type, normal_sign, balance="0.00", **kwargs):
        return LedgerAccount(
            code=f"{code}_{suffix}", name=name, account_type=account_type, normal_sign=normal_sign,
            balance=Decimal(balance), created_by_fk=actor_id, changed_by_fk=actor_id, **kwargs,
        )

    accounts = [
        _account("cash", "Cash", "asset", -1),
        _account("income", "Fee income", "income", 1),
        _account("payable", "Payable", "liability", 1),
        _account("expense", "Expense", "expense", -1),
        _account("usd", "USD income", "income", 1, currency="USD"),
        _account("thin", "Thin cash", "asset", -1),
        _account("od", "Overdraft cash", "asset", -1, overdraft_limit=Decimal("100.00")),
        _account("neg", "Negative allowed", "asset", -1, allow_negative=True),
        _account("liab_debit", "Liability wrongly debited", "liability", 1),
        _account("capital", "Opening capital", "equity", 1),
    ]
    names = ["cash", "income", "payable", "expense", "usd", "thin", "od", "neg", "liab_debit", "capital"]
    session.add_all(accounts)
    session.commit()
    by_name = dict(zip(names, accounts))
    # A balance is only ever the sum of postings: seed opening balances as entries.
    opening = LedgerService(session, actor_id=actor_id)
    opening.post(
        [
            Posting(by_name["cash"], "1000.00"),
            Posting(by_name["capital"], "1000.00"),
        ],
        entry_type="opening", idempotency_key=f"open_cash_{suffix}", description="Opening cash",
    )
    opening.post(
        [
            Posting(by_name["payable"], "500.00", "credit"),
            Posting(by_name["capital"], "500.00", "debit", allow_counter_direction=True),
        ],
        entry_type="opening", idempotency_key=f"open_pay_{suffix}", description="Opening payable",
    )
    session.commit()
    yield session, by_name
    session.rollback()
    session.close()
    engine.dispose()


@pytest.fixture
def ledger(pg_session):
    session, accounts = pg_session
    service = LedgerService(session, actor_id=accounts["cash"].created_by_fk)
    service.accounts = accounts
    service.key = lambda name: f"{name}:{uuid.uuid4().hex}"
    yield service
    session.rollback()


# --------------------------------------------------------------------- pure helpers
def test_money_quantised_half_up():
    assert _to_money("1.005") == Decimal("1.01")
    assert _to_money("1.004") == Decimal("1.00")
    assert _to_money(10) == Decimal("10.00")
    assert _to_money(Decimal("2.675")) == Decimal("2.68")


def test_money_rejects_non_numbers_and_non_finite():
    for bad in ("abc", None, "NaN", "Infinity", object()):
        with pytest.raises(DoubleEntryError):
            _to_money(bad)


def test_locked_account_direction_from_normal_sign():
    debit_asset = LockedAccount(1, "cash", "asset", "KES", -1, False, Decimal("0"), Decimal("0"))
    credit_income = LockedAccount(2, "income", "income", "KES", 1, False, Decimal("0"), Decimal("0"))
    assert debit_asset.sign_for("asset") == "debit"
    assert credit_income.sign_for("income") == "credit"
    with pytest.raises(DoubleEntryError):
        debit_asset.sign_for("nonsense")


def test_locked_account_available():
    acc = LockedAccount(1, "cash", "asset", "KES", -1, False, Decimal("25.00"), Decimal("10.00"))
    assert acc.available == Decimal("35.00")


def test_model_validators():
    with pytest.raises(ValueError):
        LedgerAccount(code="x", name="x", account_type="asset", normal_sign=0)
    with pytest.raises(ValueError):
        LedgerPosting(entry_id="e", account_id=1, direction="sideways", amount=Decimal("1"))
    for bad in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError):
            LedgerPosting(entry_id="e", account_id=1, direction="debit", amount=bad)


def test_posting_signed_amount():
    posting = LedgerPosting(entry_id="e", account_id=1, direction="debit", amount=Decimal("10.00"))
    assert posting.signed_amount == Decimal("10.00")
    posting.direction = "credit"
    assert posting.signed_amount == Decimal("-10.00")


# --------------------------------------------------------------------- behaviour (PostgreSQL)
def test_post_moves_balances(ledger):
    # Convention: a debit adds to a debit-normal account (asset, expense) and a
    # credit adds to a credit-normal one (liability, income, equity). Cash was
    # opened with a 1000 debit; recognising fee income debits cash again.
    entry = ledger.post_simple(ledger.accounts["cash"], ledger.accounts["income"], "250.50", idempotency_key=ledger.key("k"))
    session = ledger.session
    session.expire_all()
    assert entry.total_amount == Decimal("250.50")
    assert ledger.balance_of(ledger.accounts["cash"].id) == Decimal("1250.50")
    assert ledger.balance_of(ledger.accounts["income"].id) == Decimal("250.50")
    assert Decimal(ledger.accounts["cash"].balance) == Decimal("1250.50")


def test_unbalanced_entry_rejected_and_nothing_moves(ledger):
    before = ledger.balance_of(ledger.accounts["cash"].id)
    with pytest.raises(DoubleEntryError):
        ledger.post([Posting(ledger.accounts["cash"], "100.00", "debit"), Posting(ledger.accounts["income"], "90.00", "credit")])
    ledger.session.rollback()
    assert ledger.balance_of(ledger.accounts["cash"].id) == before


def test_direction_follows_normal_sign(ledger):
    ledger.post([Posting(ledger.accounts["expense"], "500.00"), Posting(ledger.accounts["payable"], "500.00")])
    ledger.session.commit()
    assert ledger.balance_of(ledger.accounts["expense"].id) == Decimal("500.00")
    # payable was opened at 500 (credit) and the entry credits it again
    assert ledger.balance_of(ledger.accounts["payable"].id) == Decimal("1000.00")


def test_debiting_a_liability_is_refused(ledger):
    with pytest.raises(DoubleEntryError):
        ledger.post([Posting(ledger.accounts["liab_debit"], "10.00", "debit"), Posting(ledger.accounts["income"], "10.00", "credit")])
    ledger.session.rollback()


def _pay_from(ledger, account, amount, **kwargs):
    """Money leaving an account: credit the account, debit the counter-account."""
    return ledger.post(
        [
            Posting(account, amount, "credit", allow_counter_direction=True),
            Posting(ledger.accounts["expense"], amount, "debit"),
        ],
        **kwargs,
    )


def test_insufficient_funds(ledger):
    with pytest.raises(InsufficientFundsError):
        _pay_from(ledger, ledger.accounts["thin"], "0.01")
    ledger.session.rollback()


def test_overdraft_limit_is_bounded(ledger):
    _pay_from(ledger, ledger.accounts["od"], "100.00")
    ledger.session.commit()
    assert ledger.balance_of(ledger.accounts["od"].id) == Decimal("-100.00")
    with pytest.raises(InsufficientFundsError):
        _pay_from(ledger, ledger.accounts["od"], "0.01")
    ledger.session.rollback()


def test_allow_negative_never_blocks(ledger):
    _pay_from(ledger, ledger.accounts["neg"], "1000000.00")
    ledger.session.commit()
    assert ledger.balance_of(ledger.accounts["neg"].id) == Decimal("-1000000.00")


def test_cross_currency_entry_refused(ledger):
    with pytest.raises(DoubleEntryError):
        ledger.post_simple(ledger.accounts["cash"], ledger.accounts["usd"], "10.00")
    ledger.session.rollback()


def test_missing_account(ledger):
    with pytest.raises(AccountNotFoundError):
        ledger.post([Posting(10**9, "10.00"), Posting(ledger.accounts["income"], "10.00")])
    ledger.session.rollback()


def test_replaying_the_same_idempotency_key_100_times_moves_money_once(ledger):
    key = ledger.key("mpesa")
    first = ledger.post_simple(ledger.accounts["cash"], ledger.accounts["income"], "10.00", idempotency_key=key)
    ledger.session.commit()
    balance = ledger.balance_of(ledger.accounts["cash"].id)
    for _ in range(100):
        replay = ledger.post_simple(ledger.accounts["cash"], ledger.accounts["income"], "10.00", idempotency_key=key)
        assert replay.id == first.id
    ledger.session.commit()
    assert ledger.balance_of(ledger.accounts["cash"].id) == balance


def test_same_key_different_amount_conflicts(ledger):
    key = ledger.key("k")
    ledger.post_simple(ledger.accounts["cash"], ledger.accounts["income"], "10.00", idempotency_key=key)
    ledger.session.commit()
    with pytest.raises(IdempotencyConflict):
        ledger.post_simple(ledger.accounts["cash"], ledger.accounts["income"], "11.00", idempotency_key=key)
    ledger.session.rollback()


def test_reversal_is_compensating_not_rewriting(ledger):
    before = ledger.balance_of(ledger.accounts["cash"].id)
    entry = ledger.post_simple(ledger.accounts["cash"], ledger.accounts["income"], "40.00", idempotency_key=ledger.key("r"))
    ledger.session.commit()
    assert ledger.balance_of(ledger.accounts["cash"].id) == before + Decimal("40.00")
    reversal = ledger.reverse(entry.id, reason="chargeback")
    ledger.session.commit()
    assert reversal.reversal_of_id == entry.id
    assert ledger.balance_of(ledger.accounts["cash"].id) == before
    # Re-reversing returns the same compensating entry.
    again = ledger.reverse(entry.id)
    assert again.id == reversal.id
    ledger.session.commit()


def test_rebuild_matches_postings_after_a_random_sequence(ledger):
    keys = [ledger.key("seq") for _ in range(25)]
    for i, key in enumerate(keys):
        ledger.post_simple(ledger.accounts["cash"], ledger.accounts["income"], f"{i + 1}.00", idempotency_key=key)
    ledger.session.commit()
    ids = [ledger.accounts["cash"].id, ledger.accounts["income"].id]
    derived = ledger.balance_of_many(ids)
    rebuilt = rebuild_account_balances(ledger.session, ids, actor_id=ledger.actor_id)
    ledger.session.commit()
    assert derived == rebuilt


def test_balance_query_agrees_with_rebuild(ledger):
    ledger.post(
        [
            Posting(ledger.accounts["expense"], "5.00", "debit"),
            Posting(ledger.accounts["cash"], "5.00", "credit", allow_counter_direction=True),
        ],
        idempotency_key=ledger.key("q"),
    )
    ledger.session.commit()
    ids = [ledger.accounts["cash"].id, ledger.accounts["expense"].id]
    assert ledger.balance_of_many(ids) == rebuild_account_balances(ledger.session, ids, actor_id=ledger.actor_id)
    ledger.session.commit()
