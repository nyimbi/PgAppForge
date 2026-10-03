"""Webhook verification primitives. Pure functions plus one store protocol."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from flask import has_app_context, request

log = logging.getLogger(__name__)

REPLAY_WINDOW_SECONDS = 300
MAX_PAYLOAD_BYTES = 64 * 1024


class WebhookRejected(Exception):
	"""Base class: the callback did not pass verification. Never retry it."""

	code = "REJECTED"


class WebhookSignatureInvalid(WebhookRejected):
	code = "SIGNATURE_INVALID"


class WebhookReplayDetected(WebhookRejected):
	code = "REPLAY"

	def __init__(self, event_id: str) -> None:
		super().__init__(f"event {event_id} already accepted or outside the replay window")
		self.event_id = event_id


class WebhookStoreUnavailable(Exception):
	"""The dedup store could not be reached: fail closed, but distinctly."""


@dataclass(frozen=True)
class TrustedProxy:
	"""Resolve the client address only through explicitly trusted proxies."""

	networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
	hops: int = 1

	@classmethod
	def from_env(cls, raw: str | None, hops: int = 1) -> TrustedProxy:
		nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
		for part in (raw or "").split(","):
			part = part.strip()
			if not part:
				continue
			try:
				nets.append(ipaddress.ip_network(part, strict=False))
			except ValueError:
				log.warning("Ignoring unparseable trusted proxy CIDR %r", part)
		return cls(tuple(nets), hops=max(1, hops))

	def client_ip(self) -> str | None:
		if not has_app_context():
			return None
		peer = request.remote_addr
		if not peer:
			return None
		try:
			peer_addr = ipaddress.ip_address(peer)
		except ValueError:
			return None
		if not self.networks or not any(peer_addr in net for net in self.networks):
			return peer
		for value in reversed(request.headers.getlist("X-Forwarded-For")):
			for candidate in reversed(value.split(",")):
				candidate = candidate.strip()
				if not candidate:
					continue
				try:
					addr = ipaddress.ip_address(candidate)
				except ValueError:
					continue
				if not any(addr in net for net in self.networks):
					return candidate
		return None


def client_ip_from_request(proxy: TrustedProxy | None = None) -> str | None:
	if proxy is not None:
		return proxy.client_ip()
	if has_app_context():
		return request.remote_addr
	return None


def canonical_payload(payload: bytes) -> bytes:
	"""Normalise JSON so key order or whitespace never changes the signature."""
	try:
		parsed = json.loads(payload.decode("utf-8"))
	except (UnicodeDecodeError, json.JSONDecodeError):
		return payload
	return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hmac_sha256_hex(secret: str, payload: bytes, timestamp: str | None = None) -> str:
	key = secret.encode("utf-8")
	if timestamp is not None:
		payload = f"{timestamp}.".encode("utf-8") + payload
	return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_hmac_sha256(
	secret: str,
	payload: bytes,
	signature: str | None,
	timestamp: str | None = None,
	tolerance: int = REPLAY_WINDOW_SECONDS,
	now: float | None = None,
) -> bool:
	if not signature or not secret:
		return False
	expected = hmac_sha256_hex(secret, payload, timestamp)
	ok = hmac.compare_digest(expected, signature.strip())
	if not ok and timestamp is None:
		# Providers differ on whether the timestamp is inside the signed body.
		ok = hmac.compare_digest(hmac_sha256_hex(secret, payload, ""), signature.strip())
	if ok and timestamp is not None:
		try:
			age = abs(float(timestamp) - (now if now is not None else time.time()))
		except (TypeError, ValueError):
			return False
		if age > tolerance:
			log.warning("Webhook signature valid but timestamp is %.0fs old", age)
			return False
	return ok


@dataclass
class VerifiedEvent:
	provider: str
	event_id: str
	payload: dict[str, Any]
	received_at: float
	sequence: int | None = None
	client_ip: str | None = None
	headers: dict[str, str] = field(default_factory=dict)


class WebhookEventStore(Protocol):
	def accept(self, event: VerifiedEvent) -> bool: ...
	def seen(self, event_id: str) -> bool: ...
	def mark_out_of_order(self, event_id: str, sequence: int) -> None: ...


class InMemoryWebhookEventStore:
	"""Development fallback. Not shared across workers; a Redis or database
	store must be wired in production (see ``SQLAlchemyWebhookEventStore``)."""

	def __init__(self, window: int = REPLAY_WINDOW_SECONDS * 4) -> None:
		self._window = window
		self._seen: dict[str, float] = {}

	def _prune(self, now: float) -> None:
		for key in [k for k, ts in self._seen.items() if now - ts > self._window]:
			self._seen.pop(key, None)

	def seen(self, event_id: str) -> bool:
		return event_id in self._seen

	def accept(self, event: VerifiedEvent) -> bool:
		now = time.time()
		self._prune(now)
		if event.event_id in self._seen:
			return False
		self._seen[event.event_id] = now
		return True

	def mark_out_of_order(self, event_id: str, sequence: int) -> None:
		log.warning("Webhook %s arrived with out-of-order sequence %s", event_id, sequence)


_STORE: WebhookEventStore | None = None


def configure_event_store(store: WebhookEventStore) -> None:
	global _STORE
	_STORE = store


def get_event_store() -> WebhookEventStore:
	if _STORE is None:
		configure_event_store(InMemoryWebhookEventStore())
	return _STORE  # type: ignore[return-value]


def _stk_callback(payload: dict[str, Any]) -> dict[str, Any]:
	body = payload.get("Body")
	if isinstance(body, dict) and isinstance(body.get("stkCallback"), dict):
		return body["stkCallback"]
	if "stkCallback" in payload:
		return payload["stkCallback"]
	return {}


def _metadata_item(callback: dict[str, Any], name: str) -> Any:
	items = callback.get("CallbackMetadata", {}).get("Item", [])
	for item in items:
		if item.get("Name") == name:
			return item.get("Value")
	return None


def _store_config(key: str, default: Any = None) -> Any:
	if has_app_context():
		return current_config().get(key, default)
	return default


def current_config() -> Any:
	from flask import current_app

	return current_app.config


def verify_stk_push(
	flask_request: Any = None,
	*,
	secret: str | None = None,
	trusted_ips: Iterable[str] | None = None,
	require_secret: bool | None = None,
	now: float | None = None,
) -> VerifiedEvent:
	"""Verify a Safaricom Daraja STK Push callback.

	Controls, in order: payload size, content type, IP allow-list against the
	configured Daraja ranges, optional HMAC signature over the canonical body,
	a monotonic timestamp inside the replay window, and deduplication on a
	derived event id. Raises ``WebhookRejected`` on any failure.
	"""
	req = flask_request or request
	raw = req.get_data(cache=True) or b""
	if len(raw) > MAX_PAYLOAD_BYTES:
		raise WebhookRejected("payload too large")
	content_type = (req.headers.get("Content-Type") or "").split(";")[0].strip().lower()
	if content_type and content_type != "application/json":
		raise WebhookRejected(f"unsupported content type {content_type!r}")
	try:
		payload = json.loads(raw.decode("utf-8"))
	except (UnicodeDecodeError, json.JSONDecodeError) as exc:
		raise WebhookRejected("malformed JSON") from exc
	if not isinstance(payload, dict):
		raise WebhookRejected("payload must be an object")

	callback = _stk_callback(payload)
	checkout_id = callback.get("CheckoutRequestID")
	if not checkout_id:
		raise WebhookRejected("missing CheckoutRequestID")

	secret = secret if secret is not None else _store_config("MPESA_WEBHOOK_SECRET")
	ip_ranges = trusted_ips if trusted_ips is not None else _store_config("MPESA_TRUSTED_IPS")
	must_have_secret = (
		require_secret if require_secret is not None else bool(_store_config("MPESA_REQUIRE_WEBHOOK_SECRET", False))
	)
	proxy = TrustedProxy.from_env(_store_config("PGAF_TRUSTED_PROXIES"), int(_store_config("PGAF_TRUSTED_PROXY_HOPS", 1)))
	if has_app_context():
		client_ip = proxy.client_ip()
	else:
		# No Flask context (unit tests, background verification): fall back to
		# the request object's peer address.
		client_ip = getattr(req, "remote_addr", None)

	if ip_ranges:
		if not _ip_allowed(client_ip, ip_ranges):
			raise WebhookRejected(f"source address {client_ip} is not an allowed Safaricom source")
	elif must_have_secret and not secret:
		raise WebhookRejected("no webhook secret configured and no source allow-list")

	if must_have_secret and not secret:
		raise WebhookRejected("MPESA_REQUIRE_WEBHOOK_SECRET is set but MPESA_WEBHOOK_SECRET is empty")
	if secret:
		signature = req.headers.get("X-Safaricom-Signature") or req.headers.get("X-MPESA-Signature")
		timestamp = req.headers.get("X-MPESA-Timestamp")
		if not verify_hmac_sha256(secret, canonical_payload(raw), signature, timestamp, now=now):
			raise WebhookSignatureInvalid("HMAC signature missing or invalid")

	callback_time = _metadata_item(callback, "TransactionDate")
	received = now if now is not None else time.time()
	if callback_time and str(callback_time).isdigit() and len(str(callback_time)) == 14:
		import datetime as _dt

		issued = _dt.datetime.strptime(str(callback_time), "%Y%m%d%H%M%S").replace(tzinfo=_dt.timezone.utc).timestamp()
		if abs(issued - received) > REPLAY_WINDOW_SECONDS * 24:
			raise WebhookReplayDetected(checkout_id)

	event_id = "mpesa:" + hmac.new(
		b"pgappforge.stk.push", f"{checkout_id}|{callback.get('ResultCode')}|{_metadata_item(callback, 'MpesaReceiptNumber')}".encode(),
		hashlib.sha256,
	).hexdigest()
	event = VerifiedEvent(
		provider="mpesa",
		event_id=event_id,
		payload=payload,
		received_at=received,
		client_ip=client_ip,
		headers={k: v for k, v in req.headers.items() if k.lower().startswith("x-")},
	)
	store = get_event_store()
	try:
		fresh = store.accept(event)
	except Exception as exc:  # fail closed: never process an unverifiable callback
		raise WebhookStoreUnavailable(str(exc)) from exc
	if not fresh:
		raise WebhookReplayDetected(event_id)
	log.info("Verified STK push callback %s from %s", checkout_id, client_ip)
	return event


def _ip_allowed(client_ip: str | None, ranges: Iterable[str]) -> bool:
	if not client_ip:
		return False
	try:
		addr = ipaddress.ip_address(client_ip)
	except ValueError:
		return False
	for entry in ranges:
		entry = str(entry).strip()
		if not entry:
			continue
		try:
			if "/" in entry:
				if addr in ipaddress.ip_network(entry, strict=False):
					return True
			elif addr == ipaddress.ip_address(entry):
				return True
		except ValueError:
			continue
	return False


def new_event_id(prefix: str) -> str:
	return f"{prefix}:{uuid.uuid4().hex}"


#: Endpoint-facing alias. ``verify_stk_callback`` reads better in Flask views.
verify_stk_callback = verify_stk_push
