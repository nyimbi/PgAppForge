"""
pgappforge/plugins/fintech/payments/pesalink_adapter.py

PESALINK — KBA (Kenya Bankers Association) interbank mobile transfer rail.

Handles individual retail transfers, status queries, and inbound webhooks
from the PESALINK gateway.  Uses OAuth2 client_credentials for auth with
in-process token caching.

Config keys (all in Flask app.config):
  PESALINK_BASE_URL      — default "https://api.pesalink.co.ke/v2"
  PESALINK_API_KEY       — OAuth2 client_id
  PESALINK_API_SECRET    — OAuth2 client_secret
  PESALINK_MEMBER_CODE   — KBA-assigned member code
  PESALINK_ENABLED       — bool, default False (mock mode when False)
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# Status mapping: PESALINK transfer status → internal PaymentOrder status
_PESALINK_STATUS_MAP: dict[str, str] = {
	"COMPLETED": "SETTLED",
	"SETTLED": "SETTLED",
	"FAILED": "RETURNED",
	"REJECTED": "RETURNED",
	"REVERSED": "RETURNED",
	"PENDING": "PROCESSING",
	"PROCESSING": "PROCESSING",
	"ACCEPTED": "PROCESSING",
}


class PESALINKError(Exception):
	"""Raised when PESALINK API returns an error or is misconfigured."""
	pass


class PESALINKAdapter:
	"""Adapter for the KBA PESALINK interbank mobile transfer gateway.

	All HTTP calls use urllib (stdlib only — no extra dependencies).
	OAuth2 client_credentials token is cached in-process; a new token is
	fetched whenever the cached one is absent or expired.

	When PESALINK_ENABLED is False the adapter runs in mock mode.
	"""

	def __init__(self) -> None:
		self._token: str | None = None
		self._token_expires_at: float = 0.0

	# ── Config ──────────────────────────────────────────────────────────────────

	def _get_config(self) -> dict[str, Any]:
		"""Read Flask app.config; fall back to empty dict outside app context."""
		try:
			from flask import current_app
			return current_app.config  # type: ignore[return-value]
		except RuntimeError:
			return {}

	# ── OAuth2 Token ────────────────────────────────────────────────────────────

	def _get_token(self, cfg: dict[str, Any]) -> str:
		"""Return a valid OAuth2 bearer token, fetching a new one if needed.

		Uses client_credentials grant with HTTP Basic auth (api_key:api_secret).
		Token is cached for the duration reported by the server (expires_in),
		with a 60-second safety margin.
		"""
		import time

		now = time.monotonic()
		if self._token and now < self._token_expires_at:
			return self._token

		base_url: str = cfg.get("PESALINK_BASE_URL", "https://api.pesalink.co.ke/v2")
		api_key: str = cfg.get("PESALINK_API_KEY", "")
		api_secret: str = cfg.get("PESALINK_API_SECRET", "")

		token_url = f"{base_url.rstrip('/')}/oauth/token"

		credentials = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
		body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()

		req = urllib.request.Request(
			token_url,
			data=body,
			method="POST",
			headers={
				"Authorization": f"Basic {credentials}",
				"Content-Type": "application/x-www-form-urlencoded",
				"Accept": "application/json",
			},
		)

		try:
			with urllib.request.urlopen(req, timeout=30) as resp:
				raw = resp.read().decode("utf-8", errors="replace")
		except urllib.error.HTTPError as exc:
			raw = exc.read().decode("utf-8", errors="replace")
			raise PESALINKError(f"PESALINK token request failed HTTP {exc.code}: {raw}") from exc
		except urllib.error.URLError as exc:
			raise PESALINKError(f"PESALINK token connection error: {exc.reason}") from exc

		try:
			data = json.loads(raw)
		except json.JSONDecodeError as exc:
			raise PESALINKError(f"PESALINK token response not JSON: {raw[:200]}") from exc

		token = data.get("access_token")
		if not token:
			raise PESALINKError(f"PESALINK token response missing access_token: {data}")

		expires_in = int(data.get("expires_in", 3600))
		self._token = token
		self._token_expires_at = now + max(expires_in - 60, 0)
		log.debug("PESALINKAdapter: obtained OAuth2 token (expires_in=%ds)", expires_in)
		return token

	# ── Public API ──────────────────────────────────────────────────────────────

	def send_transfer(
		self,
		payment_order_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Submit a single PaymentOrder as a PESALINK interbank transfer.

		Loads the PaymentOrder from the database, then POSTs to the PESALINK
		/transfers endpoint.  The returned pesalink_ref is stored on the order
		via ``external_ref`` (if the attribute exists) and the session is flushed.

		Args:
			payment_order_id: PaymentOrder.id (UUID string).
			session:          Active SQLAlchemy session.

		Returns:
			dict with keys: status, pesalink_ref, payment_order_id, pesalink_enabled.
		"""
		from pgappforge.plugins.fintech.payments.models import PaymentOrder

		order: PaymentOrder | None = session.get(PaymentOrder, payment_order_id)
		if order is None:
			raise PESALINKError(f"PaymentOrder not found: {payment_order_id}")

		cfg = self._get_config()
		enabled: bool = bool(cfg.get("PESALINK_ENABLED", False))

		if not enabled:
			log.info("PESALINKAdapter.send_transfer: mock mode order_id=%s", payment_order_id)
			mock_ref = "MOCK-" + payment_order_id[:8]
			_set_external_ref(order, mock_ref)
			session.flush()
			return {
				"status": "ACCEPTED",
				"pesalink_ref": mock_ref,
				"payment_order_id": payment_order_id,
				"pesalink_enabled": False,
			}

		base_url: str = cfg.get("PESALINK_BASE_URL", "https://api.pesalink.co.ke/v2")
		member_code: str = cfg.get("PESALINK_MEMBER_CODE", "")
		token = self._get_token(cfg)

		sender_account = str(getattr(order, "debtor_account_id", "") or "")
		amount_decimal = f"{(order.amount_cents or 0) / 100:.2f}"

		payload = {
			"amount": amount_decimal,
			"currency": order.currency_code or "KES",
			"sender_account": sender_account,
			"beneficiary_account": order.creditor_account_number or "",
			"beneficiary_bank_code": order.creditor_bank_code or "",
			"reference": order.payment_reference or payment_order_id,
			"member_code": member_code,
		}
		body = json.dumps(payload).encode("utf-8")

		url = f"{base_url.rstrip('/')}/transfers"
		req = urllib.request.Request(
			url,
			data=body,
			method="POST",
			headers={
				"Authorization": f"Bearer {token}",
				"Content-Type": "application/json",
				"Accept": "application/json",
			},
		)

		try:
			with urllib.request.urlopen(req, timeout=30) as resp:
				raw = resp.read().decode("utf-8", errors="replace")
				status_code = resp.status
		except urllib.error.HTTPError as exc:
			raw = exc.read().decode("utf-8", errors="replace")
			raise PESALINKError(
				f"PESALINK send_transfer failed HTTP {exc.code} order={payment_order_id}: {raw}"
			) from exc
		except urllib.error.URLError as exc:
			raise PESALINKError(
				f"PESALINK connection error order={payment_order_id}: {exc.reason}"
			) from exc

		try:
			data = json.loads(raw)
		except json.JSONDecodeError:
			data = {"raw_response": raw}

		pesalink_ref = data.get("pesalink_ref", data.get("transaction_id", ""))

		_set_external_ref(order, pesalink_ref)
		session.flush()

		log.info(
			"PESALINKAdapter.send_transfer: HTTP %s order=%s pesalink_ref=%s",
			status_code, payment_order_id, pesalink_ref,
		)

		return {
			"status": data.get("status", "ACCEPTED"),
			"pesalink_ref": pesalink_ref,
			"payment_order_id": payment_order_id,
			"pesalink_enabled": True,
		}

	def query_transfer(self, pesalink_ref: str) -> dict[str, Any]:
		"""Poll PESALINK for the status of a prior transfer.

		Args:
			pesalink_ref: Reference returned by :meth:`send_transfer`.

		Returns:
			dict with keys: pesalink_ref, status, timestamp, pesalink_enabled.
		"""
		cfg = self._get_config()
		enabled: bool = bool(cfg.get("PESALINK_ENABLED", False))

		if not enabled:
			log.debug("PESALINKAdapter.query_transfer: mock mode ref=%s", pesalink_ref)
			return {
				"pesalink_ref": pesalink_ref,
				"status": "COMPLETED",
				"timestamp": _utcnow_iso(),
				"pesalink_enabled": False,
			}

		base_url: str = cfg.get("PESALINK_BASE_URL", "https://api.pesalink.co.ke/v2")
		token = self._get_token(cfg)

		url = f"{base_url.rstrip('/')}/transfers/{urllib.parse.quote(pesalink_ref, safe='')}"
		req = urllib.request.Request(
			url,
			method="GET",
			headers={
				"Authorization": f"Bearer {token}",
				"Accept": "application/json",
			},
		)

		try:
			with urllib.request.urlopen(req, timeout=30) as resp:
				raw = resp.read().decode("utf-8", errors="replace")
				status_code = resp.status
		except urllib.error.HTTPError as exc:
			raw = exc.read().decode("utf-8", errors="replace")
			raise PESALINKError(
				f"PESALINK query_transfer failed HTTP {exc.code} ref={pesalink_ref}: {raw}"
			) from exc
		except urllib.error.URLError as exc:
			raise PESALINKError(
				f"PESALINK connection error querying {pesalink_ref}: {exc.reason}"
			) from exc

		try:
			data = json.loads(raw)
		except json.JSONDecodeError:
			data = {"raw_response": raw}

		log.debug(
			"PESALINKAdapter.query_transfer: HTTP %s ref=%s status=%s",
			status_code, pesalink_ref, data.get("status", "—"),
		)

		return {
			"pesalink_ref": pesalink_ref,
			"status": data.get("status", "UNKNOWN"),
			"timestamp": data.get("timestamp", _utcnow_iso()),
			"pesalink_enabled": True,
		}

	def process_webhook(
		self,
		payload: dict[str, Any],
		session: Any,
	) -> dict[str, Any]:
		"""Handle an inbound PESALINK status webhook.

		The webhook body must contain:
		  pesalink_ref — transfer reference (matches PaymentOrder.external_ref)
		  status       — COMPLETED | FAILED | … (see _PESALINK_STATUS_MAP)
		  reason       — (optional) failure reason string

		The matching PaymentOrder is updated and the session is flushed.
		The caller is responsible for committing.

		Args:
			payload: Parsed JSON dict from the webhook body.
			session: Active SQLAlchemy session.

		Returns:
			dict with keys: payment_order_id, pesalink_ref, new_status, previous_status.
		"""
		from pgappforge.plugins.fintech.payments.models import PaymentOrder

		pesalink_ref: str = payload.get("pesalink_ref", "")
		raw_status: str = payload.get("status", "")
		reason: str = payload.get("reason", "")

		if not pesalink_ref:
			raise PESALINKError("process_webhook: payload missing pesalink_ref")

		new_status = _PESALINK_STATUS_MAP.get(raw_status.upper())
		if new_status is None:
			log.warning(
				"PESALINKAdapter.process_webhook: unknown status=%r ref=%s — ignored",
				raw_status, pesalink_ref,
			)
			new_status = "PROCESSING"

		# Locate PaymentOrder by external_ref attribute
		order: PaymentOrder | None = None
		try:
			order = (
				session.query(PaymentOrder)
				.filter(PaymentOrder.external_ref == pesalink_ref)
				.first()
			)
		except Exception:
			# external_ref column may not exist in older schema versions; fall back
			for o in session.query(PaymentOrder).all():
				if getattr(o, "external_ref", None) == pesalink_ref:
					order = o
					break

		if order is None:
			log.warning(
				"PESALINKAdapter.process_webhook: no PaymentOrder with external_ref=%r",
				pesalink_ref,
			)
			return {
				"payment_order_id": None,
				"pesalink_ref": pesalink_ref,
				"new_status": new_status,
				"previous_status": None,
				"matched": False,
			}

		previous_status = order.status
		order.status = new_status
		session.flush()

		log.info(
			"PESALINKAdapter.process_webhook: ref=%s order=%s %s → %s reason=%r",
			pesalink_ref, order.id, previous_status, new_status, reason,
		)

		return {
			"payment_order_id": str(order.id),
			"pesalink_ref": pesalink_ref,
			"new_status": new_status,
			"previous_status": previous_status,
			"matched": True,
		}


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _utcnow_iso() -> str:
	return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_external_ref(order: Any, ref: str) -> None:
	"""Set order.external_ref if the attribute exists; no-op otherwise."""
	if hasattr(order, "external_ref"):
		order.external_ref = ref


__all__ = ["PESALINKAdapter", "PESALINKError"]
