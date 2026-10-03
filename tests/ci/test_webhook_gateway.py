"""Tests for the webhook gateway: verification, replay window, deduplication.

Pure unit tests; no database, no Flask request context required (a minimal
request double is used).
"""

import json
import time

import pytest

from pgappforge.webhooks.gateway import (
    InMemoryWebhookEventStore,
    TrustedProxy,
    VerifiedEvent,
    WebhookRejected,
    WebhookReplayDetected,
    WebhookSignatureInvalid,
    WebhookStoreUnavailable,
    _ip_allowed,
    canonical_payload,
    configure_event_store,
    hmac_sha256_hex,
    verify_hmac_sha256,
    verify_stk_push,
)


class FakeRequest:
    def __init__(self, payload: dict, headers: dict | None = None, raw: bytes | None = None):
        self._raw = raw if raw is not None else json.dumps(payload).encode("utf-8")
        self.headers = _Headers(headers or {})
        self.remote_addr = "203.0.113.10"

    def get_data(self, cache: bool = True) -> bytes:
        return self._raw


class _Headers(dict):
    def getlist(self, key: str):
        value = self.get(key)
        return [value] if value else []

    def items(self):
        return super().items()


def _callback(checkout_id="ws_CO_TEST01", result=0, receipt="QJG7RT9ABC", amount=1000.0, phone="254712345678"):
    return {
        "Body": {
            "stkCallback": {
                "CheckoutRequestID": checkout_id,
                "MerchantRequestID": "mr-1",
                "ResultCode": result,
                "ResultDesc": "Accepted",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "MpesaReceiptNumber", "Value": receipt},
                        {"Name": "Amount", "Value": amount},
                        {"Name": "PhoneNumber", "Value": phone},
                        {"Name": "TransactionDate", "Value": time.strftime("%Y%m%d%H%M%S", time.gmtime())},
                    ]
                },
            }
        }
    }


def test_canonical_payload_is_key_order_independent():
    a = canonical_payload(b'{"a":1,"b":{"y":2,"x":3}}')
    b = canonical_payload(b'{"b":{"x":3,"y":2},"a":1}')
    assert a == b


def test_hmac_round_trip_and_tamper_detection():
    secret = "s3cr3t"
    body = b'{"x":1}'
    sig = hmac_sha256_hex(secret, body)
    assert verify_hmac_sha256(secret, body, sig)
    assert not verify_hmac_sha256(secret, body, hmac_sha256_hex("other", body))
    assert not verify_hmac_sha256(secret, body, None)
    assert not verify_hmac_sha256(secret, b'{"x":2}', sig)


def test_hmac_rejects_timestamp_outside_window():
    secret = "s3cr3t"
    body = b'{"x":1}'
    ts = str(time.time() - 3600)
    sig = hmac_sha256_hex(secret, body, ts)
    assert not verify_hmac_sha256(secret, body, sig, ts)
    fresh_ts = str(time.time())
    fresh_sig = hmac_sha256_hex(secret, body, fresh_ts)
    assert verify_hmac_sha256(secret, body, fresh_sig, fresh_ts)


def test_ip_allowlist():
    assert _ip_allowed("203.0.113.10", ["203.0.113.0/24"])
    assert not _ip_allowed("198.51.100.1", ["203.0.113.0/24"])
    assert _ip_allowed("203.0.113.10", ["203.0.113.10"])
    assert not _ip_allowed(None, ["203.0.113.0/24"])


def test_trusted_proxy_from_env_ignores_garbage():
    proxy = TrustedProxy.from_env("10.0.0.0/8, not-a-cidr, 192.168.0.0/16")
    assert len(proxy.networks) == 2


def test_store_dedup():
    store = InMemoryWebhookEventStore()
    event = VerifiedEvent("mpesa", "e1", {}, time.time())
    assert store.accept(event) is True
    assert store.accept(event) is False
    assert store.seen("e1")


def test_verify_accepts_well_formed_callback_and_rejects_replay():
    configure_event_store(InMemoryWebhookEventStore())
    req = FakeRequest(_callback())
    event = verify_stk_push(req, trusted_ips=["203.0.113.0/24"])
    assert event.provider == "mpesa" and event.event_id.startswith("mpesa:")
    # The same payload a second time is a replay, not a second payment.
    with pytest.raises(WebhookReplayDetected):
        verify_stk_push(FakeRequest(_callback()), trusted_ips=["203.0.113.0/24"])


def test_verify_rejects_bad_source_and_missing_checkout_id():
    configure_event_store(InMemoryWebhookEventStore())
    req = FakeRequest(_callback(checkout_id="ws_X"))
    req.remote_addr = "198.51.100.1"
    with pytest.raises(WebhookRejected):
        verify_stk_push(req, trusted_ips=["203.0.113.0/24"])
    with pytest.raises(WebhookRejected):
        verify_stk_push(FakeRequest({"Body": {"stkCallback": {}}}), trusted_ips=["203.0.113.0/24"])


def test_verify_requires_valid_signature_when_secret_configured():
    configure_event_store(InMemoryWebhookEventStore())
    payload = _callback()
    req = FakeRequest(payload)
    with pytest.raises(WebhookSignatureInvalid):
        verify_stk_push(req, secret="s3cr3t", trusted_ips=["203.0.113.0/24"])
    good = FakeRequest(payload, {"X-Safaricom-Signature": hmac_sha256_hex("s3cr3t", canonical_payload(req.get_data()))})
    event = verify_stk_push(good, secret="s3cr3t", trusted_ips=["203.0.113.0/24"])
    assert event.event_id


def test_verify_requires_secret_when_configured_to():
    configure_event_store(InMemoryWebhookEventStore())
    with pytest.raises(WebhookRejected):
        verify_stk_push(FakeRequest(_callback()), secret=None, trusted_ips=None, require_secret=True)


def test_verify_rejects_oversized_and_non_json():
    configure_event_store(InMemoryWebhookEventStore())
    with pytest.raises(WebhookRejected):
        verify_stk_push(FakeRequest({}, raw=b"x" * (64 * 1024 + 1)))
    with pytest.raises(WebhookRejected):
        verify_stk_push(FakeRequest({}, raw=b"not json"))


def test_store_outage_fails_closed():
    class BrokenStore:
        def accept(self, event):
            raise RuntimeError("redis down")

        def seen(self, event_id):
            return False

        def mark_out_of_order(self, event_id, sequence):
            pass

    configure_event_store(BrokenStore())
    with pytest.raises(WebhookStoreUnavailable):
        verify_stk_push(FakeRequest(_callback(checkout_id="ws_Y")), trusted_ips=["203.0.113.0/24"])
    configure_event_store(InMemoryWebhookEventStore())
