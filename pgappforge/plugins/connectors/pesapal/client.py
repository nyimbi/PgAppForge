"""
pgappforge/plugins/connectors/pesapal/client.py

Pesapal — multi-payment gateway covering Kenya, Uganda, Tanzania, Rwanda,
Malawi, Zimbabwe, and Zambia.

Accepted payment methods (single integration):
  - M-Pesa (Kenya, Tanzania)
  - Airtel Money (Kenya, Uganda, Tanzania, Malawi, Zambia)
  - MTN MoMo (Uganda)
  - Visa / Mastercard
  - Bank transfers
  - Equity Bank EazzyPay

Flow:
  1. get_access_token()      → Bearer token (5 min TTL — refresh before each call)
  2. register_ipn_url()      → notification_id (save to DB for reuse)
  3. submit_order()          → order_tracking_id + redirect_url
  4. Redirect customer to redirect_url
  5. Customer pays → Pesapal POSTs to your IPN URL
  6. get_transaction_status(order_tracking_id) → payment_status_description

Config (Flask app.config):
  PESAPAL_CONSUMER_KEY     From Pesapal merchant portal
  PESAPAL_CONSUMER_SECRET  From Pesapal merchant portal
  PESAPAL_BASE_URL         Sandbox: "https://cybqa.pesapal.com/pesapalv3"
                           Production: "https://pay.pesapal.com/v3"
  PESAPAL_TIMEOUT          HTTP timeout seconds (default 30)
  PESAPAL_ENABLED          Set False to skip in dev (default True)

Sandbox:
  Register at https://developer.pesapal.com/
  Use PESAPAL_BASE_URL = "https://cybqa.pesapal.com/pesapalv3"

CLI test helper:
  python -m pgappforge.plugins.connectors.pesapal.client --test
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_SANDBOX_BASE_URL = "https://cybqa.pesapal.com/pesapalv3"
_PROD_BASE_URL = "https://pay.pesapal.com/v3"


class PesapalError(Exception):
	"""Base error for all Pesapal client failures."""


class PesapalClient:
	"""Pesapal v3 API client.

	Example::

		client = PesapalClient.from_config()

		# Register IPN once and persist the notification_id:
		ipn = client.register_ipn_url("https://myapp.com/pesapal/ipn")
		notification_id = ipn["ipn_id"]

		# Submit a payment order:
		order = client.submit_order(
		    id="ORD-001",
		    currency="KES",
		    amount=5000.0,
		    description="Invoice #42",
		    callback_url="https://myapp.com/pesapal/callback",
		    redirect_mode="PARENT_WINDOW",
		    notification_id=notification_id,
		    branch="HQ",
		    billing_address={
		        "email_address": "customer@example.com",
		        "phone_number": "+254712345678",
		        "first_name": "Jane",
		        "last_name": "Doe",
		    },
		)
		# Redirect user to order["redirect_url"]

		# Poll or IPN callback:
		status = client.get_transaction_status(order["order_tracking_id"])
		print(status["payment_status_description"])  # "Completed" | "Failed" | "Pending"
	"""

	def __init__(
		self,
		consumer_key: str = "",
		consumer_secret: str = "",
		base_url: str = _PROD_BASE_URL,
		timeout: int = 30,
		enabled: bool = True,
	) -> None:
		self.consumer_key = consumer_key
		self.consumer_secret = consumer_secret
		self.base_url = base_url.rstrip("/")
		self.timeout = timeout
		self.enabled = enabled
		self._access_token: str = ""

	@classmethod
	def from_config(cls) -> "PesapalClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			return cls(
				consumer_key=cfg.get("PESAPAL_CONSUMER_KEY", ""),
				consumer_secret=cfg.get("PESAPAL_CONSUMER_SECRET", ""),
				base_url=cfg.get("PESAPAL_BASE_URL", _PROD_BASE_URL),
				timeout=int(cfg.get("PESAPAL_TIMEOUT", 30)),
				enabled=cfg.get("PESAPAL_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	@classmethod
	def sandbox(cls, consumer_key: str = "", consumer_secret: str = "") -> "PesapalClient":
		"""Convenience factory for Pesapal sandbox environment."""
		return cls(
			consumer_key=consumer_key,
			consumer_secret=consumer_secret,
			base_url=_SANDBOX_BASE_URL,
			enabled=True,
		)

	# ------------------------------------------------------------------ #
	# Auth
	# ------------------------------------------------------------------ #

	def get_access_token(self) -> str:
		"""Request a Pesapal OAuth token (5 minute TTL).

		The token is cached per instance.  For long-running processes, construct
		a new client or clear _access_token before each request batch.

		Returns:
			Bearer token string.
		"""
		if self._access_token:
			return self._access_token

		url = f"{self.base_url}/api/Auth/RequestToken"
		payload = json.dumps({
			"consumer_key": self.consumer_key,
			"consumer_secret": self.consumer_secret,
		}).encode()

		req = urllib.request.Request(
			url,
			data=payload,
			method="POST",
			headers={
				"Content-Type": "application/json",
				"Accept": "application/json",
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				result = json.loads(resp.read())
				token = result.get("token", "")
				if token:
					self._access_token = token
				elif result.get("error"):
					raise PesapalError(f"Pesapal auth error: {result.get('error')}")
				return token
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise PesapalError(f"get_access_token HTTP {exc.code}: {body}") from exc
		except PesapalError:
			raise
		except Exception as exc:
			raise PesapalError(f"get_access_token failed: {exc}") from exc

	# ------------------------------------------------------------------ #
	# IPN registration
	# ------------------------------------------------------------------ #

	def register_ipn_url(
		self,
		url: str,
		ipn_notification_type: str = "POST",
	) -> dict[str, Any]:
		"""Register an Instant Payment Notification (IPN / webhook) URL.

		Pesapal will POST payment status updates to this URL.  Register once
		and persist the returned ipn_id.

		Args:
			url:                    HTTPS URL Pesapal will POST to.
			ipn_notification_type:  "POST" | "GET" (default "POST").

		Returns:
			{url, created_date, ipn_id, ipn_status, ipn_status_description, error}
		"""
		payload = {
			"url": url,
			"ipn_notification_type": ipn_notification_type,
		}
		try:
			return self._post("/api/URLSetup/RegisterIPN", payload)
		except PesapalError as exc:
			return {"error": str(exc), "ipn_id": ""}

	def get_merchant_ipn_list(self) -> list[dict[str, Any]]:
		"""Get all IPN URLs registered for this merchant account.

		Returns:
			List of IPN registration objects.
		"""
		try:
			result = self._get("/api/URLSetup/GetIpnList")
			if isinstance(result, list):
				return result
			return result.get("data", []) if isinstance(result, dict) else []
		except PesapalError as exc:
			log.warning("get_merchant_ipn_list failed: %s", exc)
			return []

	# ------------------------------------------------------------------ #
	# Orders
	# ------------------------------------------------------------------ #

	def submit_order(
		self,
		id: str,
		currency: str,
		amount: float,
		description: str,
		callback_url: str,
		redirect_mode: str,
		notification_id: str,
		branch: str = "",
		billing_address: dict | None = None,
	) -> dict[str, Any]:
		"""Submit a payment order to Pesapal.

		Args:
			id:               Your unique order/merchant reference.
			currency:         ISO 4217 code: KES, UGX, TZS, RWF, MWK, ZWL, ZMW.
			amount:           Payment amount (face value, not minor units).
			description:      Payment description shown to customer.
			callback_url:     URL Pesapal redirects to after payment.
			redirect_mode:    "PARENT_WINDOW" | "TOP_WINDOW" | "IFRAME".
			notification_id:  IPN ID from register_ipn_url().
			branch:           Optional branch name for multi-branch merchants.
			billing_address:  Dict with keys: email_address, phone_number,
			                  first_name, last_name, country_code (all optional
			                  but recommended for better payment success rate).

		Returns:
			{
			  order_tracking_id: str,   # Use to check status
			  merchant_reference: str,  # Echo of your id
			  redirect_url: str,        # Send customer here
			  error: str | None,
			}
		"""
		if not self.enabled:
			return {
				"order_tracking_id": "",
				"merchant_reference": id,
				"redirect_url": "",
				"error": None,
				"skipped": True,
			}

		if not self.consumer_key:
			return {
				"order_tracking_id": "",
				"merchant_reference": id,
				"redirect_url": "",
				"error": "PESAPAL_CONSUMER_KEY not configured",
			}

		payload: dict[str, Any] = {
			"id": id,
			"currency": currency,
			"amount": amount,
			"description": description[:100],
			"callback_url": callback_url,
			"redirect_mode": redirect_mode,
			"notification_id": notification_id,
			"branch": branch or "Main",
			"billing_address": billing_address or {},
		}
		try:
			result = self._post("/api/Transactions/SubmitOrderRequest", payload)
			return {
				"order_tracking_id": result.get("order_tracking_id", ""),
				"merchant_reference": result.get("merchant_reference", id),
				"redirect_url": result.get("redirect_url", ""),
				"error": result.get("error"),
			}
		except PesapalError as exc:
			return {
				"order_tracking_id": "",
				"merchant_reference": id,
				"redirect_url": "",
				"error": str(exc),
			}

	def get_transaction_status(self, order_tracking_id: str) -> dict[str, Any]:
		"""Get the payment status for an order.

		Args:
			order_tracking_id: From submit_order() response.

		Returns:
			{
			  payment_method: str,
			  amount: float,
			  created_date: str,
			  confirmation_code: str,
			  payment_status_description: str,  # "Completed" | "Failed" | "Pending"
			  description: str,
			  message: str,
			  payment_account: str,
			  call_back_url: str,
			  status_code: int,
			  merchant_reference: str,
			  payment_status_code: str,
			  currency: str,
			  error: None | dict,
			}
		"""
		try:
			return self._get(f"/api/Transactions/GetTransactionStatus?orderTrackingId={order_tracking_id}")
		except PesapalError as exc:
			return {"payment_status_description": "Error", "error": str(exc)}

	# ------------------------------------------------------------------ #
	# Internal
	# ------------------------------------------------------------------ #

	def _headers(self) -> dict[str, str]:
		token = self.get_access_token()
		return {
			"Authorization": f"Bearer {token}",
			"Content-Type": "application/json",
			"Accept": "application/json",
		}

	def _post(self, path: str, payload: dict) -> dict:
		url = f"{self.base_url}{path}"
		req = urllib.request.Request(
			url,
			data=json.dumps(payload).encode(),
			method="POST",
			headers=self._headers(),
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise PesapalError(f"Pesapal HTTP {exc.code}: {body}") from exc
		except PesapalError:
			raise
		except Exception as exc:
			raise PesapalError(f"Pesapal request failed: {exc}") from exc

	def _get(self, path: str) -> Any:
		url = f"{self.base_url}{path}"
		req = urllib.request.Request(url, method="GET", headers=self._headers())
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise PesapalError(f"Pesapal HTTP {exc.code}: {body}") from exc
		except PesapalError:
			raise
		except Exception as exc:
			raise PesapalError(f"Pesapal request failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test() -> None:
	"""Sandbox smoke test.
	Run: python -m pgappforge.plugins.connectors.pesapal.client --test
	Requires PESAPAL_CONSUMER_KEY and PESAPAL_CONSUMER_SECRET env vars.
	"""
	import os
	logging.basicConfig(level=logging.INFO)

	key = os.environ.get("PESAPAL_CONSUMER_KEY", "")
	secret = os.environ.get("PESAPAL_CONSUMER_SECRET", "")
	if not key:
		print("Set PESAPAL_CONSUMER_KEY and PESAPAL_CONSUMER_SECRET from developer.pesapal.com")
		return

	client = PesapalClient.sandbox(consumer_key=key, consumer_secret=secret)
	print(f"Pesapal sandbox client: base_url={client.base_url}")

	token = client.get_access_token()
	print(f"  access_token = {token[:20]}…")

	ipns = client.get_merchant_ipn_list()
	print(f"  Registered IPNs: {len(ipns)}")

	import pprint
	pprint.pprint(ipns[:2])


if __name__ == "__main__":
	import sys
	if "--test" in sys.argv:
		_cli_test()


__all__ = ["PesapalClient", "PesapalError"]
