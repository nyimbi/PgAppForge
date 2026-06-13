"""
pgappforge/plugins/connectors/airtel_money/client.py

Airtel Money API — 44 M users across 14 African countries.

Countries: Kenya, Uganda, Tanzania, Rwanda, Zambia, Malawi, Congo DRC,
           Niger, Madagascar, Gabon, Seychelles, Chad, Republic of Congo,
           Sierra Leone.

Two product lines:
  Collections   — customer pays business (request-to-pay)
  Disbursements — business pays customer (payout)

Auth: OAuth2 client_credentials — Bearer token from POST /auth/oauth2/token.

Config (Flask app.config):
  AIRTEL_CLIENT_ID      OAuth2 client ID from Airtel Money developer portal
  AIRTEL_CLIENT_SECRET  OAuth2 client secret
  AIRTEL_BASE_URL       API base (default "https://openapi.airtel.africa")
  AIRTEL_COUNTRY        ISO 3166-1 alpha-2, e.g. "KE" | "UG" | "TZ"
  AIRTEL_CURRENCY       ISO 4217 code, e.g. "KES" | "UGX" | "TZS"
  AIRTEL_TIMEOUT        HTTP timeout seconds (default 30)
  AIRTEL_ENABLED        Set False to skip in dev (default True)

Sandbox:
  Use AIRTEL_BASE_URL = "https://openapiuat.airtel.africa"
  Test credentials are issued per country on the Airtel Developer Portal.

CLI test helper:
  python -m pgappforge.plugins.connectors.airtel_money.client --test
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_PROD_BASE_URL = "https://openapi.airtel.africa"
_SANDBOX_BASE_URL = "https://openapiuat.airtel.africa"


class AirtelMoneyError(Exception):
	"""Base error for Airtel Money API failures."""


class AirtelMoneyClient:
	"""Airtel Money REST API client.

	Example (collections)::

		client = AirtelMoneyClient.from_config()

		# Request payment from customer:
		result = client.collections_request(
		    amount=500, msisdn="254712345678",
		    transaction_id="TXN-001", reference="Invoice-42",
		)
		# Poll status:
		status = client.collections_enquiry("TXN-001")

	Example (disbursements)::

		result = client.disburse(
		    amount=1000, msisdn="254712345678",
		    transaction_id="DIS-001", reference="Salary-May",
		)
	"""

	def __init__(
		self,
		client_id: str = "",
		client_secret: str = "",
		base_url: str = _PROD_BASE_URL,
		country: str = "KE",
		currency: str = "KES",
		timeout: int = 30,
		enabled: bool = True,
	) -> None:
		self.client_id = client_id
		self.client_secret = client_secret
		self.base_url = base_url.rstrip("/")
		self.country = country.upper()
		self.currency = currency.upper()
		self.timeout = timeout
		self.enabled = enabled
		self._access_token: str = ""

	@classmethod
	def from_config(cls) -> "AirtelMoneyClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			return cls(
				client_id=cfg.get("AIRTEL_CLIENT_ID", ""),
				client_secret=cfg.get("AIRTEL_CLIENT_SECRET", ""),
				base_url=cfg.get("AIRTEL_BASE_URL", _PROD_BASE_URL),
				country=cfg.get("AIRTEL_COUNTRY", "KE"),
				currency=cfg.get("AIRTEL_CURRENCY", "KES"),
				timeout=int(cfg.get("AIRTEL_TIMEOUT", 30)),
				enabled=cfg.get("AIRTEL_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	@classmethod
	def sandbox(cls, client_id: str = "", client_secret: str = "") -> "AirtelMoneyClient":
		"""Convenience factory for Airtel UAT (sandbox) environment."""
		return cls(
			client_id=client_id,
			client_secret=client_secret,
			base_url=_SANDBOX_BASE_URL,
			enabled=True,
		)

	# ------------------------------------------------------------------ #
	# Auth
	# ------------------------------------------------------------------ #

	def get_access_token(self) -> str:
		"""Obtain an OAuth2 Bearer token (cached per instance).

		Returns:
			Bearer token string (without "Bearer " prefix).
		"""
		if self._access_token:
			return self._access_token

		url = f"{self.base_url}/auth/oauth2/token"
		payload = json.dumps({
			"client_id": self.client_id,
			"client_secret": self.client_secret,
			"grant_type": "client_credentials",
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
				token = result.get("access_token", "")
				if token:
					self._access_token = token
				return token
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise AirtelMoneyError(f"get_access_token HTTP {exc.code}: {body}") from exc
		except Exception as exc:
			raise AirtelMoneyError(f"get_access_token failed: {exc}") from exc

	# ------------------------------------------------------------------ #
	# Collections — customer pays business
	# ------------------------------------------------------------------ #

	def collections_request(
		self,
		amount: float,
		msisdn: str,
		transaction_id: str,
		reference: str,
	) -> dict[str, Any]:
		"""Request a payment from a customer (STK-push equivalent).

		Args:
			amount:         Amount in the configured currency.
			msisdn:         Customer phone number (no + prefix), e.g. "254712345678".
			transaction_id: Your unique transaction ID.
			reference:      Readable reference shown to customer.

		Returns:
			{success, transaction_id, status, data, error}
		"""
		if not self.enabled:
			return {"success": True, "transaction_id": transaction_id, "status": "skipped", "error": None, "skipped": True}

		if not self.client_id:
			return {"success": False, "error": "AIRTEL_CLIENT_ID not configured", "transaction_id": transaction_id, "status": "failed"}

		payload = {
			"reference": reference[:50],
			"subscriber": {
				"country": self.country,
				"currency": self.currency,
				"msisdn": msisdn,
			},
			"transaction": {
				"amount": amount,
				"country": self.country,
				"currency": self.currency,
				"id": transaction_id,
			},
		}
		try:
			result = self._post("/merchant/v2/payments/", payload)
			return {
				"success": result.get("status", {}).get("code") in ("200", 200, "DP00800001001"),
				"transaction_id": transaction_id,
				"status": result.get("status", {}).get("message", ""),
				"data": result.get("data", {}),
				"error": None,
			}
		except AirtelMoneyError as exc:
			return {"success": False, "error": str(exc), "transaction_id": transaction_id, "status": "failed"}

	def collections_enquiry(self, transaction_id: str) -> dict[str, Any]:
		"""Check the status of a collection transaction.

		Args:
			transaction_id: The ID used in collections_request().

		Returns:
			Airtel API transaction status object.
		"""
		try:
			return self._get(f"/standard/v1/payments/{transaction_id}")
		except AirtelMoneyError as exc:
			return {"success": False, "error": str(exc)}

	# ------------------------------------------------------------------ #
	# Disbursements — business pays customer
	# ------------------------------------------------------------------ #

	def disburse(
		self,
		amount: float,
		msisdn: str,
		transaction_id: str,
		reference: str,
	) -> dict[str, Any]:
		"""Transfer money to a subscriber (business-to-customer payout).

		Args:
			amount:         Amount to disburse.
			msisdn:         Recipient phone (no + prefix).
			transaction_id: Your unique transaction ID.
			reference:      Payment reference / narration.

		Returns:
			{success, transaction_id, status, data, error}
		"""
		if not self.enabled:
			return {"success": True, "transaction_id": transaction_id, "status": "skipped", "error": None, "skipped": True}

		if not self.client_id:
			return {"success": False, "error": "AIRTEL_CLIENT_ID not configured", "transaction_id": transaction_id, "status": "failed"}

		payload = {
			"payee": {
				"msisdn": msisdn,
			},
			"reference": reference[:50],
			"pin": "",          # server-side PIN configured on the merchant account
			"transaction": {
				"amount": amount,
				"id": transaction_id,
				"type": "B2C",
			},
		}
		try:
			result = self._post("/standard/v1/disbursements/", payload)
			return {
				"success": result.get("status", {}).get("code") in ("200", 200),
				"transaction_id": transaction_id,
				"status": result.get("status", {}).get("message", ""),
				"data": result.get("data", {}),
				"error": None,
			}
		except AirtelMoneyError as exc:
			return {"success": False, "error": str(exc), "transaction_id": transaction_id, "status": "failed"}

	def disburse_enquiry(self, transaction_id: str) -> dict[str, Any]:
		"""Check the status of a disbursement.

		Args:
			transaction_id: The ID used in disburse().

		Returns:
			Airtel API disbursement status object.
		"""
		try:
			return self._get(f"/standard/v1/disbursements/{transaction_id}")
		except AirtelMoneyError as exc:
			return {"success": False, "error": str(exc)}

	# ------------------------------------------------------------------ #
	# Balance
	# ------------------------------------------------------------------ #

	def get_balance(self) -> dict[str, Any]:
		"""Get the merchant account float balance.

		Returns:
			{balance, currency, error} or raw Airtel response.
		"""
		try:
			result = self._get("/standard/v1/users/balance")
			data = result.get("data", {})
			return {
				"balance": data.get("balance", 0),
				"currency": self.currency,
				"raw": data,
				"error": None,
			}
		except AirtelMoneyError as exc:
			return {"balance": 0, "currency": self.currency, "error": str(exc)}

	# ------------------------------------------------------------------ #
	# Internal
	# ------------------------------------------------------------------ #

	def _headers(self) -> dict[str, str]:
		token = self.get_access_token()
		return {
			"Authorization": f"Bearer {token}",
			"Content-Type": "application/json",
			"Accept": "application/json",
			"X-Country": self.country,
			"X-Currency": self.currency,
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
			raise AirtelMoneyError(f"Airtel HTTP {exc.code}: {body}") from exc
		except AirtelMoneyError:
			raise
		except Exception as exc:
			raise AirtelMoneyError(f"Airtel request failed: {exc}") from exc

	def _get(self, path: str) -> dict:
		url = f"{self.base_url}{path}"
		req = urllib.request.Request(url, method="GET", headers=self._headers())
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise AirtelMoneyError(f"Airtel HTTP {exc.code}: {body}") from exc
		except AirtelMoneyError:
			raise
		except Exception as exc:
			raise AirtelMoneyError(f"Airtel request failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test() -> None:
	"""Sandbox smoke test.
	Run: python -m pgappforge.plugins.connectors.airtel_money.client --test
	Requires AIRTEL_CLIENT_ID and AIRTEL_CLIENT_SECRET env vars.
	"""
	import os
	logging.basicConfig(level=logging.INFO)

	client_id = os.environ.get("AIRTEL_CLIENT_ID", "")
	client_secret = os.environ.get("AIRTEL_CLIENT_SECRET", "")
	if not client_id:
		print("Set AIRTEL_CLIENT_ID and AIRTEL_CLIENT_SECRET env vars.")
		return

	client = AirtelMoneyClient.sandbox(client_id=client_id, client_secret=client_secret)
	print(f"Airtel Money sandbox client: country={client.country}")

	token = client.get_access_token()
	print(f"  access_token = {token[:20]}…")

	balance = client.get_balance()
	import pprint
	pprint.pprint(balance)


if __name__ == "__main__":
	import sys
	if "--test" in sys.argv:
		_cli_test()


__all__ = ["AirtelMoneyClient", "AirtelMoneyError"]
