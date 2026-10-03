"""M-Pesa STK callback state machine: terminal states and idempotency key.

Uses model instances built without a database: SQLAlchemy declarative classes
can be instantiated in memory and their Python-level validators and methods run
as long as no flush occurs.
"""

import pytest

from pgappforge.wallet import mpesa_models as M


def _txn(checkout_request_id="ws_CO_1", amount=1000):
    txn = M.MPESATransaction(
        mpesa_account_id=1,
        transaction_type=M.MPESATransactionType.B2C.value,
        amount=amount,
        phone_number="254712345678",
        checkout_request_id=checkout_request_id,
    )
    return txn


def test_terminal_statuses_cover_every_non_pending_state():
    assert M._TERMINAL_STATUSES == frozenset(
        {s.value for s in M.MPESATransactionStatus if s is not M.MPESATransactionStatus.PENDING}
    )
    assert M.MPESATransactionStatus.PENDING.value not in M._TERMINAL_STATUSES


def test_mark_completed_from_pending_transitions_once():
    txn = _txn()
    assert txn.mark_completed("QJG1") is True
    assert txn.status == M.MPESATransactionStatus.COMPLETED.value
    # Replay: a second completion must not advance anything.
    assert txn.mark_completed("QJG2") is False
    assert txn.mpesa_receipt_number == "QJG1"


@pytest.mark.parametrize(
    "terminal",
    [M.MPESATransactionStatus.COMPLETED, M.MPESATransactionStatus.FAILED,
     M.MPESATransactionStatus.CANCELLED, M.MPESATransactionStatus.TIMEOUT],
)
def test_no_transition_out_of_terminal_states(terminal):
    txn = _txn()
    txn.status = terminal.value
    assert txn.mark_completed("QJG3") is False
    assert txn.mark_failed("late failure") is False
    assert txn.status == terminal.value


def test_mark_failed_from_pending_transitions_once():
    txn = _txn()
    assert txn.mark_failed("Insufficient balance", "1") is True
    assert txn.status == M.MPESATransactionStatus.FAILED.value
    assert txn.mark_failed("another") is False


def test_idempotency_key_is_content_derived_and_stable():
    key_fn = M.MPESATransactionStatus  # placeholder to keep import used
    from pgappforge.wallet.mpesa_service import MPESAService

    a = MPESAService._callback_idempotency_key("ws_1", 0, "Q1")
    b = MPESAService._callback_idempotency_key("ws_1", 0, "Q1")
    c = MPESAService._callback_idempotency_key("ws_1", 0, "Q2")
    assert a == b and a != c and len(a) == 64


def test_callback_record_marks_processed():
    cb = M.MPESACallback(callback_data="{}", checkout_request_id="ws_1")
    # Column defaults apply at INSERT, so a transient instance reads None.
    assert not cb.is_processed
    cb.mark_processed()
    assert cb.is_processed is True
    cb.mark_processed("boom")
    assert cb.processing_error == "boom"
    assert cb.processing_attempts == 1
