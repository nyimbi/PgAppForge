"""Verified, replay-resistant webhook gateway.

One gateway for every inbound provider callback: signature verification where
the provider supports it, a monotonic replay window, deduplication on a provider
event id, ordering by provider sequence, and a dead-letter table. Provider
handlers become pure functions over a ``VerifiedEvent``.

Usage in an endpoint::

    from pgappforge.webhooks import verify_stk_push, WebhookRejected

    @app.post("/mpesa/callback")
    def mpesa_callback():
        try:
            event = verify_stk_push(request)
        except WebhookRejected as exc:
            log.warning("mpesa callback rejected: %s", exc)
            return jsonify({"ResultCode": 1, "ResultDesc": "Rejected"}), 200
        service.process_stk_callback(event.payload)
        return jsonify({"ResultCode": 0, "ResultDesc": "OK"}), 200
"""

from .gateway import (
	REPLAY_WINDOW_SECONDS,
	TrustedProxy,
	VerifiedEvent,
	WebhookEventStore,
	WebhookRejected,
	WebhookReplayDetected,
	WebhookSignatureInvalid,
	WebhookStoreUnavailable,
	client_ip_from_request,
	hmac_sha256_hex,
	verify_hmac_sha256,
	verify_stk_callback,
	verify_stk_push,
)

__all__ = [
	"REPLAY_WINDOW_SECONDS",
	"TrustedProxy",
	"VerifiedEvent",
	"WebhookEventStore",
	"WebhookRejected",
	"WebhookReplayDetected",
	"WebhookSignatureInvalid",
	"WebhookStoreUnavailable",
	"client_ip_from_request",
	"hmac_sha256_hex",
	"verify_hmac_sha256",
	"verify_stk_callback",
	"verify_stk_push",
]
