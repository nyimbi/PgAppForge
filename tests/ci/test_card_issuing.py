"""
tests/ci/test_card_issuing.py

Unit tests for the card_issuing plugin.

Strategy
--------
- Pure-logic tests: Luhn, PAN generation, PIN crypto, 3DS OTP, auth checks.
- No real DB or Flask context needed — service methods that hit the DB are
  tested with MagicMock sessions or monkey-patched _get_card helpers.
- conftest.py already stubs flask_appbuilder at session scope so all
  plugin imports (including views) succeed.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import struct
import time
from unittest.mock import MagicMock, patch

import pytest

from pgappforge.plugins.fintech.card_issuing.models import (
	CardAuthorizationLog,
	CardBIN,
	IssuedCard,
	PINBlock,
)
from pgappforge.plugins.fintech.card_issuing.events import (
	ALL_CI_EVENT_TYPES,
	CardActivatedEvent,
	CardAuthorizationEvent,
	CardBlockedEvent,
	CardIssuedEvent,
	CardPINSetEvent,
	CardReplacedEvent,
)
from pgappforge.plugins.fintech.card_issuing.services import (
	CardIssuingError,
	CardIssuingService,
	CardNotFoundError,
	CardStatusError,
	PINError,
	PINMasterKeyNotConfiguredError,
)

_MASTER_KEY = "test-master-key-for-card-issuing-unit-tests"


def _svc() -> CardIssuingService:
	return CardIssuingService()


def _set_key():
	os.environ["CARD_PIN_MASTER_KEY"] = _MASTER_KEY


def _clear_key():
	os.environ.pop("CARD_PIN_MASTER_KEY", None)


# ---------------------------------------------------------------------------
# Model sanity
# ---------------------------------------------------------------------------

class TestModels:
	def test_table_names(self):
		assert CardBIN.__tablename__ == "ci_card_bin"
		assert IssuedCard.__tablename__ == "ci_issued_card"
		assert PINBlock.__tablename__ == "ci_pin_block"
		assert CardAuthorizationLog.__tablename__ == "ci_auth_log"

	def test_immutable_flag(self):
		assert getattr(PINBlock, "_immutable", False) is True
		assert getattr(CardAuthorizationLog, "_immutable", False) is True

	def test_issued_card_column_defaults(self):
		# SQLAlchemy Column(default=...) fires at INSERT, not at __init__.
		# Verify the declared defaults on the Column objects themselves.
		tbl = IssuedCard.__table__
		assert tbl.c.status.default.arg == "INACTIVE"
		assert tbl.c.is_virtual.default.arg is True
		assert tbl.c.daily_limit_cents.default.arg == 0
		assert tbl.c.pin_attempts.default.arg == 0

	def test_card_bin_column_defaults(self):
		tbl = CardBIN.__table__
		assert tbl.c.card_type.default.arg == "DEBIT"
		assert tbl.c.is_active.default.arg is True

	def test_pin_block_column_defaults(self):
		tbl = PINBlock.__table__
		assert tbl.c.algorithm.default.arg == "AES256GCM"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEvents:
	def test_all_event_types(self):
		assert ALL_CI_EVENT_TYPES == [
			"card.issued",
			"card.activated",
			"card.blocked",
			"card.pin_set",
			"card.authorized",
			"card.replaced",
		]

	def test_event_defaults(self):
		ev = CardIssuedEvent()
		assert ev.event_type == "card.issued"
		assert ev.card_id == ""
		assert ev.is_virtual is True

	def test_event_fields(self):
		ev = CardIssuedEvent(card_id="c1", account_id="a1", bin_code="424242")
		assert ev.card_id == "c1"
		assert ev.bin_code == "424242"

	def test_auth_event_defaults(self):
		ev = CardAuthorizationEvent()
		assert ev.event_type == "card.authorized"
		assert ev.amount_cents == 0
		assert ev.result == ""

	def test_all_event_classes_have_correct_type(self):
		assert CardActivatedEvent().event_type == "card.activated"
		assert CardBlockedEvent().event_type == "card.blocked"
		assert CardPINSetEvent().event_type == "card.pin_set"
		assert CardReplacedEvent().event_type == "card.replaced"


# ---------------------------------------------------------------------------
# Luhn algorithm
# ---------------------------------------------------------------------------

class TestLuhn:
	def test_visa_check_digit(self):
		# 4111111111111 → check digit 1 (well-known test PAN 4111111111111111)
		assert CardIssuingService._luhn_check_digit("411111111111111") == "1"

	def test_visa_test_pan(self):
		# 4242424242424 → check digit 2 (4242424242424242)
		assert CardIssuingService._luhn_check_digit("424242424242424") == "2"

	def test_mastercard_check_digit(self):
		# 515658108 → verify a known MC partial
		assert CardIssuingService._luhn_check_digit("510510510510510") == "0"

	def test_single_zero(self):
		assert CardIssuingService._luhn_check_digit("0") == "0"

	def test_generated_pan_luhn_valid(self):
		svc = _svc()
		for _ in range(20):
			pan = svc._generate_pan("424242", 16)
			digits = [int(d) for d in reversed(pan)]
			total = sum(
				(d * 2 - 9 if d * 2 > 9 else d * 2) if i % 2 != 0 else d
				for i, d in enumerate(digits)
			)
			assert total % 10 == 0, f"Luhn invalid for generated PAN {pan}"


# ---------------------------------------------------------------------------
# PAN generation
# ---------------------------------------------------------------------------

class TestPANGeneration:
	def test_length_16(self):
		pan = _svc()._generate_pan("424242", 16)
		assert len(pan) == 16

	def test_length_19(self):
		pan = _svc()._generate_pan("424242", 19)
		assert len(pan) == 19

	def test_bin_prefix_preserved(self):
		pan = _svc()._generate_pan("545454", 16)
		assert pan.startswith("545454")

	def test_all_digits(self):
		pan = _svc()._generate_pan("424242", 16)
		assert pan.isdigit()

	def test_randomness(self):
		svc = _svc()
		pans = {svc._generate_pan("424242", 16) for _ in range(50)}
		# With 10^9 combinations even 50 draws should all be unique
		assert len(pans) > 1, "PAN generation is not random"


# ---------------------------------------------------------------------------
# PIN key derivation
# ---------------------------------------------------------------------------

class TestPINKeyDerivation:
	def setup_method(self):
		_set_key()

	def teardown_method(self):
		_clear_key()

	def test_key_is_32_bytes(self):
		key = CardIssuingService._get_pin_key("card-123")
		assert len(key) == 32

	def test_key_deterministic(self):
		key1 = CardIssuingService._get_pin_key("card-abc")
		key2 = CardIssuingService._get_pin_key("card-abc")
		assert key1 == key2

	def test_different_cards_different_keys(self):
		k1 = CardIssuingService._get_pin_key("card-aaa")
		k2 = CardIssuingService._get_pin_key("card-bbb")
		assert k1 != k2

	def test_raises_when_key_missing(self):
		_clear_key()
		with pytest.raises(PINMasterKeyNotConfiguredError):
			CardIssuingService._get_pin_key("card-x")

	def test_env_fallback(self):
		# Key read from env (no Flask context in test)
		key = CardIssuingService._get_pin_key("card-env-test")
		assert isinstance(key, bytes) and len(key) == 32


# ---------------------------------------------------------------------------
# PIN encrypt / decrypt
# ---------------------------------------------------------------------------

class TestPINEncryption:
	def setup_method(self):
		_set_key()

	def teardown_method(self):
		_clear_key()

	def test_round_trip_4_digits(self):
		enc, nonce = CardIssuingService._encrypt_pin("c1", "1234")
		assert CardIssuingService._verify_pin("c1", "1234", enc, nonce)

	def test_round_trip_6_digits(self):
		enc, nonce = CardIssuingService._encrypt_pin("c2", "123456")
		assert CardIssuingService._verify_pin("c2", "123456", enc, nonce)

	def test_wrong_pin_rejected(self):
		enc, nonce = CardIssuingService._encrypt_pin("c3", "1234")
		assert not CardIssuingService._verify_pin("c3", "9999", enc, nonce)

	def test_wrong_length_rejected(self):
		enc, nonce = CardIssuingService._encrypt_pin("c4", "1234")
		assert not CardIssuingService._verify_pin("c4", "12345", enc, nonce)

	def test_cross_card_aad_binding(self):
		# ciphertext encrypted for card-A must not verify against card-B
		enc, nonce = CardIssuingService._encrypt_pin("card-A", "5678")
		assert not CardIssuingService._verify_pin("card-B", "5678", enc, nonce)

	def test_enc_and_nonce_are_base64_strings(self):
		enc, nonce = CardIssuingService._encrypt_pin("c5", "0000")
		import base64
		base64.b64decode(enc)   # must not raise
		base64.b64decode(nonce) # must not raise

	def test_nonces_are_unique(self):
		encs = {CardIssuingService._encrypt_pin("c6", "1234")[1] for _ in range(20)}
		assert len(encs) > 1, "Nonces must be unique (os.urandom)"


# ---------------------------------------------------------------------------
# 3DS OTP (RFC 6238 TOTP)
# ---------------------------------------------------------------------------

class TestOTP:
	def setup_method(self):
		_set_key()

	def teardown_method(self):
		_clear_key()

	def _expected_otp(self, card_id: str) -> str:
		key = CardIssuingService._get_pin_key(card_id)[:20]
		t = int(time.time()) // 30
		msg = struct.pack(">Q", t)
		h = hmac.new(key, msg, hashlib.sha1).digest()
		offset = h[-1] & 0x0F
		code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
		return str(code % 1_000_000).zfill(6)

	def test_otp_is_6_digits(self):
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: MagicMock()
		otp = svc.generate_3ds_otp("card-1", "default", MagicMock())
		assert len(otp) == 6 and otp.isdigit()

	def test_otp_matches_rfc6238(self):
		card_id = "card-otp-test"
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: MagicMock()
		otp = svc.generate_3ds_otp(card_id, "default", MagicMock())
		assert otp == self._expected_otp(card_id)

	def test_card_not_found_raises(self):
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: (_ for _ in ()).throw(
			CardNotFoundError("not found")
		)
		with pytest.raises(CardNotFoundError):
			svc.generate_3ds_otp("missing", "t", MagicMock())


# ---------------------------------------------------------------------------
# authorize_transaction
# ---------------------------------------------------------------------------

class TestAuthorizeTransaction:
	def _make_card(self, **kwargs):
		defaults = dict(
			id="card-auth-1",
			status="ACTIVE",
			expiry_month=12,
			expiry_year=2099,
			daily_limit_cents=0,
			last_used_at=None,
		)
		defaults.update(kwargs)
		card = MagicMock(**defaults)
		for k, v in defaults.items():
			setattr(card, k, v)
		return card

	def _make_session(self, card, daily_spent=0):
		session = MagicMock()
		session.get.return_value = card
		# scalar_one() for daily spend query
		session.execute.return_value.scalar_one.return_value = daily_spent
		return session

	def test_approved_active_card(self):
		card = self._make_card()
		session = self._make_session(card)
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		result = svc.authorize_transaction(
			card_id="card-auth-1",
			amount_cents=1000,
			auth_type="PURCHASE",
			tenant_id="default",
			session=session,
		)
		assert result["result"] == "APPROVED"
		assert len(result["authorization_code"]) == 6
		assert result["decline_reason"] == ""
		assert len(result["rrn"]) == 12

	def test_declined_blocked_card(self):
		card = self._make_card(status="BLOCKED")
		session = self._make_session(card)
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		result = svc.authorize_transaction(
			card_id="card-auth-1",
			amount_cents=500,
			auth_type="PURCHASE",
			tenant_id="default",
			session=session,
		)
		assert result["result"] == "DECLINED"
		assert result["decline_reason"] == "CARD_BLOCKED"
		assert result["authorization_code"] == ""

	def test_declined_expired_card(self):
		from datetime import datetime, timezone
		now = datetime.now(timezone.utc)
		card = self._make_card(expiry_year=now.year - 1, expiry_month=1)
		session = self._make_session(card)
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		result = svc.authorize_transaction(
			card_id="card-auth-1",
			amount_cents=500,
			auth_type="PURCHASE",
			tenant_id="default",
			session=session,
		)
		assert result["result"] == "DECLINED"
		assert result["decline_reason"] == "EXPIRED_CARD"

	def test_declined_daily_limit_exceeded(self):
		card = self._make_card(daily_limit_cents=10_000)
		# Already spent 9500; new txn of 1000 would exceed 10000
		session = self._make_session(card, daily_spent=9_500)
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		result = svc.authorize_transaction(
			card_id="card-auth-1",
			amount_cents=1_000,
			auth_type="PURCHASE",
			tenant_id="default",
			session=session,
		)
		assert result["result"] == "DECLINED"
		assert result["decline_reason"] == "DAILY_LIMIT_EXCEEDED"

	def test_approved_within_daily_limit(self):
		card = self._make_card(daily_limit_cents=10_000)
		session = self._make_session(card, daily_spent=5_000)
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		result = svc.authorize_transaction(
			card_id="card-auth-1",
			amount_cents=4_000,
			auth_type="PURCHASE",
			tenant_id="default",
			session=session,
		)
		assert result["result"] == "APPROVED"

	def test_auth_log_added_to_session(self):
		card = self._make_card()
		session = self._make_session(card)
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		svc.authorize_transaction(
			card_id="card-auth-1",
			amount_cents=100,
			auth_type="PURCHASE",
			tenant_id="default",
			session=session,
		)
		session.add.assert_called_once()
		added = session.add.call_args[0][0]
		assert isinstance(added, CardAuthorizationLog)
		assert added.amount_cents == 100

	def test_last_used_at_updated_on_approval(self):
		card = self._make_card()
		session = self._make_session(card)
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		svc.authorize_transaction(
			card_id="card-auth-1",
			amount_cents=100,
			auth_type="PURCHASE",
			tenant_id="default",
			session=session,
		)
		assert card.last_used_at is not None

	def test_last_used_at_not_updated_on_decline(self):
		card = self._make_card(status="BLOCKED", last_used_at=None)
		session = self._make_session(card)
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		svc.authorize_transaction(
			card_id="card-auth-1",
			amount_cents=100,
			auth_type="PURCHASE",
			tenant_id="default",
			session=session,
		)
		assert card.last_used_at is None


# ---------------------------------------------------------------------------
# activate_card / block_card
# ---------------------------------------------------------------------------

class TestCardLifecycle:
	def test_activate_inactive_card(self):
		card = MagicMock(status="INACTIVE")
		session = MagicMock()
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		svc.activate_card("c1", "t", session)
		assert card.status == "ACTIVE"
		assert card.activated_at is not None

	def test_activate_already_active_raises(self):
		card = MagicMock(status="ACTIVE")
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		with pytest.raises(CardStatusError):
			svc.activate_card("c1", "t", MagicMock())

	def test_activate_blocked_raises(self):
		card = MagicMock(status="BLOCKED")
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		with pytest.raises(CardStatusError):
			svc.activate_card("c1", "t", MagicMock())

	def test_block_card(self):
		card = MagicMock(status="ACTIVE")
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		svc.block_card("c1", "FRAUD", "t", MagicMock())
		assert card.status == "BLOCKED"
		assert card.block_reason == "FRAUD"

	def test_block_reason_truncated_to_50(self):
		card = MagicMock(status="ACTIVE")
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		long_reason = "X" * 100
		svc.block_card("c1", long_reason, "t", MagicMock())
		assert len(card.block_reason) == 50

	def test_get_card_not_found(self):
		session = MagicMock()
		session.get.return_value = None
		svc = _svc()
		with pytest.raises(CardNotFoundError):
			svc._get_card("missing-id", "t", session)


# ---------------------------------------------------------------------------
# set_pin / verify_pin
# ---------------------------------------------------------------------------

class TestPINManagement:
	def setup_method(self):
		_set_key()

	def teardown_method(self):
		_clear_key()

	def _card(self):
		c = MagicMock()
		c.pin_attempts = 0
		c.pin_set_at = None
		return c

	def _session_no_existing_pin(self):
		sess = MagicMock()
		sess.execute.return_value.scalar_one_or_none.return_value = None
		return sess

	def test_set_pin_rejects_non_digits(self):
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: self._card()
		with pytest.raises(PINError, match="numeric"):
			svc.set_pin("c1", "abcd", "t", self._session_no_existing_pin())

	def test_set_pin_rejects_too_short(self):
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: self._card()
		with pytest.raises(PINError):
			svc.set_pin("c1", "123", "t", self._session_no_existing_pin())

	def test_set_pin_rejects_too_long(self):
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: self._card()
		with pytest.raises(PINError):
			svc.set_pin("c1", "1234567", "t", self._session_no_existing_pin())

	def test_set_pin_accepts_4_digits(self):
		svc = _svc()
		card = self._card()
		svc._get_card = lambda cid, tid, sess: card
		session = self._session_no_existing_pin()
		svc.set_pin("c1", "1234", "t", session)
		session.add.assert_called_once()
		added = session.add.call_args[0][0]
		assert isinstance(added, PINBlock)
		assert card.pin_attempts == 0
		assert card.pin_set_at is not None

	def test_set_pin_accepts_6_digits(self):
		svc = _svc()
		card = self._card()
		svc._get_card = lambda cid, tid, sess: card
		session = self._session_no_existing_pin()
		svc.set_pin("c1", "123456", "t", session)
		session.add.assert_called_once()

	def test_verify_pin_no_pin_set_raises(self):
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: self._card()
		session = MagicMock()
		session.execute.return_value.scalar_one_or_none.return_value = None
		with pytest.raises(PINError, match="No PIN"):
			svc.verify_pin("c1", "1234", "t", session)

	def test_verify_pin_increments_attempts_on_failure(self):
		card = self._card()
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		# Return a PINBlock encrypted for a *different* card so verify returns False
		enc, nonce = CardIssuingService._encrypt_pin("other-card", "9999")
		pin_block = MagicMock(encrypted_pin=enc, pin_nonce=nonce)
		session = MagicMock()
		session.execute.return_value.scalar_one_or_none.return_value = pin_block
		result = svc.verify_pin("c1", "1234", "t", session)
		assert result is False
		assert card.pin_attempts == 1

	def test_verify_pin_blocks_card_at_3_failures(self):
		card = self._card()
		card.pin_attempts = 2  # one more failure should block
		svc = _svc()
		svc._get_card = lambda cid, tid, sess: card
		enc, nonce = CardIssuingService._encrypt_pin("other-card", "0000")
		pin_block = MagicMock(encrypted_pin=enc, pin_nonce=nonce)
		session = MagicMock()
		session.execute.return_value.scalar_one_or_none.return_value = pin_block
		result = svc.verify_pin("c1", "9999", "t", session)
		assert result is False
		assert card.status == "BLOCKED"
		assert card.block_reason == "PIN_LOCKED"
