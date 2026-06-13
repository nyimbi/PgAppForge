"""
pgappforge/plugins/connectors/mtn_momo/client.py

MTN Mobile Money (MoMo) API — 63 M monthly active users across 13 African countries.

Three product lines:
  COLLECTIONS   — customer pays business (request-to-pay / STK-push equivalent)
  DISBURSEMENTS — business pays customer (payout / transfer out)
  REMITTANCE    — international money transfer

Sandbox workflow:
  1. create_api_user(callback_host)  → api_user_id (uuid)
  2. get_api_key(api_user_id)        → api_key
  3. get_access_token(product)       → Bearer token (1 hour TTL)
  4. request_to_pay / transfer / ...

Production workflow:
  Skip steps 1-2 — provision MTN_MOMO_API_USER / MTN_MOMO_API_KEY via
  MTN MoMo developer portal.

Config (Flask app.config or environment):
  MTN_MOMO_SUBSCRIPTION_KEY   Ocp-Apim-Subscription-Key from developer portal
  MTN_MOMO_API_USER           UUID of the provisioned API user
  MTN_MOMO_API_KEY            API key for the API user
  MTN_MOMO_BASE_URL           Default "https://sandbox.momoapi.mtn.com"
  MTN_MOMO_ENVIRONMENT        "sandbox" | "production" (default "sandbox")
  MTN_MOMO_CURRENCY           ISO 4217 code (default "EUR" for sandbox,
                              "UGX" / "GHS" / "ZMW" / etc. for production)
  MTN_MOMO_TIMEOUT            HTTP timeout seconds (default 30)
  MTN_MOMO_ENABLED            Set False to skip in dev (default True)

CLI test helper:
  python -m pgappforge.plugins.connectors.mtn_momo.client --test
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_SANDBOX_BASE_URL = "https://sandbox.momoapi.mtn.com"
_PROD_BASE_URL = "https://momoapi.mtn.com"

# Product path segments
_PRODUCT_PATH: dict[str, str] = {
	"collection": "collection",
	"disbursement": "disbursement",
	"remittance": "remittance",
}


class MTNMoMoError(Exception):
	"""Base error for all MTN MoMo client failures."""


class MTNMoMoClient:
	"""MTN Mobile Money REST API client.

	Supports Collections, Disbursements, and Remittance product lines.

	Example (sandbox setup)::

		client = MTNMoMoClient(
		    subscription_key="...",
		    base_url="https://sandbox.momoapi.mtn.com",
		    environment="sandbox",
		    currency="EUR",
		)
		api_user = client.create_api_user("https://myapp.example.com")
		api_key = client.get_api_key(api_user)
		client.api_user = api_user
		client.api_key = api_key

		token = client.get_access_token("collection")
		result = client.request_to_pay(
		    amount="5", currency="EUR", msisdn="46733123454",
		    external_id="ext-001", payer_message="Invoice 1", payee_note="Ref 1",
		)

	Example (production)::

		client = MTNMoMoClient.from_config()
		result = client.request_to_pay(
		    amount="10000", currency="UGX", msisdn="256700000000",
		    external_id="ORD-001", payer_message="Order payment", payee_note="ORD-001",
		)
	"""

	def __init__(
		self,
		subscription_key: str = "",
		api_user: str = "",
		api_key: str = "",
		base_url: str = _SANDBOX_BASE_URL,
		environment: str = "sandbox",
		currency: str = "EUR",
		timeout: int = 30,
		enabled: bool = True,
	) -> None:
		self.subscription_key = subscription_key
		self.api_user = api_user
		self.api_key = api_key
		self.base_url = base_url.rstrip("/")
		self.environment = environment
		self.currency = currency
		self.timeout = timeout
		self.enabled = enabled
		# Per-product token cache: {"collection": "Bearer xxx", ...}
		self._token_cache: dict[str, str] = {}

	@classmethod
	def from_config(cls) -> "MTNMoMoClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			env = cfg.get("MTN_MOMO_ENVIRONMENT", "sandbox")
			default_url = _SANDBOX_BASE_URL if env == "sandbox" else _PROD_BASE_URL
			default_currency = "EUR" if env == "sandbox" else "UGX"
			return cls(
				subscription_key=cfg.get("MTN_MOMO_SUBSCRIPTION_KEY", ""),
				api_user=cfg.get("MTN_MOMO_API_USER", ""),
				api_key=cfg.get("MTN_MOMO_API_KEY", ""),
				base_url=cfg.get("MTN_MOMO_BASE_URL", default_url),
				environment=env,
				currency=cfg.get("MTN_MOMO_CURRENCY", default_currency),
				timeout=int(cfg.get("MTN_MOMO_TIMEOUT", 30)),
				enabled=cfg.get("MTN_MOMO_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	# ------------------------------------------------------------------ #
	# Sandbox provisioning
	# ------------------------------------------------------------------ #

	def create_api_user(self, callback_host: str) -> str:
		"""Create a sandbox API user and return the generated UUID.

		Only needed in sandbox.  In production, API users are provisioned
		through the MTN MoMo developer portal.

		Args:
			callback_host: Base URL of your application (used for IPN callbacks).

		Returns:
			UUID string of the created API user.
		"""
		api_user_id = str(uuid.uuid4())
		payload = {"providerCallbackHost": callback_host}
		url = f"{self.base_url}/v1_0/apiuser"
		req = urllib.request.Request(
			url,
			data=json.dumps(payload).encode(),
			method="POST",
			headers={
				"Content-Type": "application/json",
				"X-Reference-Id": api_user_id,
				"Ocp-Apim-Subscription-Key": self.subscription_key,
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				if resp.status not in (200, 201):
					raise MTNMoMoError(f"create_api_user failed: HTTP {resp.status}")
			return api_user_id
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise MTNMoMoError(f"create_api_user HTTP {exc.code}: {body}") from exc
		except MTNMoMoError:
			raise
		except Exception as exc:
			raise MTNMoMoError(f"create_api_user failed: {exc}") from exc

	def get_api_key(self, api_user_id: str) -> str:
		"""Get the API key for a sandbox API user.

		Args:
			api_user_id: UUID returned by create_api_user().

		Returns:
			API key string.
		"""
		url = f"{self.base_url}/v1_0/apiuser/{api_user_id}/apikey"
		req = urllib.request.Request(
			url,
			data=b"",
			method="POST",
			headers={
				"Ocp-Apim-Subscription-Key": self.subscription_key,
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				result = json.loads(resp.read())
				return result.get("apiKey", "")
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise MTNMoMoError(f"get_api_key HTTP {exc.code}: {body}") from exc
		except Exception as exc:
			raise MTNMoMoError(f"get_api_key failed: {exc}") from exc

	# ------------------------------------------------------------------ #
	# OAuth2 token
	# ------------------------------------------------------------------ #

	def get_access_token(self, product: str = "collection") -> str:
		"""Obtain an OAuth2 Bearer token for a product (cached per instance).

		Args:
			product: "collection" | "disbursement" | "remittance"

		Returns:
			Bearer token string (without "Bearer " prefix).
		"""
		product = product.lower()
		if product in self._token_cache:
			return self._token_cache[product]

		product_path = _PRODUCT_PATH.get(product, product)
		url = f"{self.base_url}/{product_path}/token/"

		credentials = base64.b64encode(
			f"{self.api_user}:{self.api_key}".encode()
		).decode()

		req = urllib.request.Request(
			url,
			data=b"grant_type=client_credentials",
			method="POST",
			headers={
				"Authorization": f"Basic {credentials}",
				"Content-Type": "application/x-www-form-urlencoded",
				"Ocp-Apim-Subscription-Key": self.subscription_key,
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				result = json.loads(resp.read())
				token = result.get("access_token", "")
				if token:
					self._token_cache[product] = token
				return token
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise MTNMoMoError(f"get_access_token HTTP {exc.code}: {body}") from exc
		except Exception as exc:
			raise MTNMoMoError(f"get_access_token failed: {exc}") from exc

	# ------------------------------------------------------------------ #
	# Collections — customer pays business
	# ------------------------------------------------------------------ #

	def request_to_pay(
		self,
		amount: str,
		currency: str,
		msisdn: str,
		external_id: str,
		payer_message: str,
		payee_note: str,
	) -> dict[str, Any]:
		"""Initiate a collection request (customer pays business).

		The payer receives an STK-push notification (where supported).
		Poll get_transaction_status() until status is SUCCESSFUL or FAILED.

		Args:
			amount:        Amount as string, e.g. "1000".
			currency:      ISO 4217 code.  Use "EUR" in sandbox.
			msisdn:        Payer phone number (no + prefix, e.g. "256700000000").
			external_id:   Your unique transaction reference.
			payer_message: Message shown to payer on their phone.
			payee_note:    Note stored with transaction for payee.

		Returns:
			{success, transaction_id, status, error}
		"""
		if not self.enabled:
			return {"success": True, "transaction_id": "", "status": "skipped", "error": None, "skipped": True}

		if not self.subscription_key:
			return {"success": False, "error": "MTN_MOMO_SUBSCRIPTION_KEY not configured", "transaction_id": "", "status": "failed"}

		transaction_id = str(uuid.uuid4())
		payload: dict[str, Any] = {
			"amount": str(amount),
			"currency": currency or self.currency,
			"externalId": external_id,
			"payer": {
				"partyIdType": "MSISDN",
				"partyId": msisdn,
			},
			"payerMessage": payer_message[:160],
			"payeeNote": payee_note[:160],
		}

		try:
			token = self.get_access_token("collection")
			url = f"{self.base_url}/collection/v1_0/requesttopay"
			req = urllib.request.Request(
				url,
				data=json.dumps(payload).encode(),
				method="POST",
				headers={
					"Authorization": f"Bearer {token}",
					"Content-Type": "application/json",
					"X-Reference-Id": transaction_id,
					"X-Target-Environment": self.environment,
					"Ocp-Apim-Subscription-Key": self.subscription_key,
				},
			)
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				# 202 Accepted = request received, poll for status
				if resp.status in (200, 201, 202):
					return {"success": True, "transaction_id": transaction_id, "status": "PENDING", "error": None}
				raise MTNMoMoError(f"request_to_pay: unexpected status {resp.status}")
		except MTNMoMoError:
			raise
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise MTNMoMoError(f"request_to_pay HTTP {exc.code}: {body}") from exc
		except Exception as exc:
			raise MTNMoMoError(f"request_to_pay failed: {exc}") from exc

	# ------------------------------------------------------------------ #
	# Transaction status (Collections + Disbursements)
	# ------------------------------------------------------------------ #

	def get_transaction_status(self, transaction_id: str, product: str = "collection") -> dict[str, Any]:
		"""Check the status of a transaction.

		Args:
			transaction_id: UUID returned by request_to_pay() or transfer().
			product:        "collection" | "disbursement" | "remittance"

		Returns:
			MoMo API transaction object.  Key field: status (PENDING | SUCCESSFUL | FAILED).
		"""
		product_path = _PRODUCT_PATH.get(product.lower(), product.lower())
		try:
			token = self.get_access_token(product.lower())
			url = f"{self.base_url}/{product_path}/v1_0/requesttopay/{transaction_id}"
			req = urllib.request.Request(
				url,
				method="GET",
				headers={
					"Authorization": f"Bearer {token}",
					"X-Target-Environment": self.environment,
					"Ocp-Apim-Subscription-Key": self.subscription_key,
				},
			)
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise MTNMoMoError(f"get_transaction_status HTTP {exc.code}: {body}") from exc
		except MTNMoMoError:
			raise
		except Exception as exc:
			raise MTNMoMoError(f"get_transaction_status failed: {exc}") from exc

	# ------------------------------------------------------------------ #
	# Disbursements — business pays customer
	# ------------------------------------------------------------------ #

	def transfer(
		self,
		amount: str,
		currency: str,
		msisdn: str,
		external_id: str,
		payee_note: str,
	) -> dict[str, Any]:
		"""Send money to a subscriber (business-to-customer payout).

		Args:
			amount:      Amount as string.
			currency:    ISO 4217 code.
			msisdn:      Recipient phone (no + prefix).
			external_id: Your unique reference.
			payee_note:  Note shown to recipient.

		Returns:
			{success, transaction_id, status, error}
		"""
		if not self.enabled:
			return {"success": True, "transaction_id": "", "status": "skipped", "error": None, "skipped": True}

		if not self.subscription_key:
			return {"success": False, "error": "MTN_MOMO_SUBSCRIPTION_KEY not configured", "transaction_id": "", "status": "failed"}

		transaction_id = str(uuid.uuid4())
		payload: dict[str, Any] = {
			"amount": str(amount),
			"currency": currency or self.currency,
			"externalId": external_id,
			"payee": {
				"partyIdType": "MSISDN",
				"partyId": msisdn,
			},
			"payerMessage": payee_note[:160],
			"payeeNote": payee_note[:160],
		}

		try:
			token = self.get_access_token("disbursement")
			url = f"{self.base_url}/disbursement/v1_0/transfer"
			req = urllib.request.Request(
				url,
				data=json.dumps(payload).encode(),
				method="POST",
				headers={
					"Authorization": f"Bearer {token}",
					"Content-Type": "application/json",
					"X-Reference-Id": transaction_id,
					"X-Target-Environment": self.environment,
					"Ocp-Apim-Subscription-Key": self.subscription_key,
				},
			)
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				if resp.status in (200, 201, 202):
					return {"success": True, "transaction_id": transaction_id, "status": "PENDING", "error": None}
				raise MTNMoMoError(f"transfer: unexpected status {resp.status}")
		except MTNMoMoError:
			raise
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise MTNMoMoError(f"transfer HTTP {exc.code}: {body}") from exc
		except Exception as exc:
			raise MTNMoMoError(f"transfer failed: {exc}") from exc

	# ------------------------------------------------------------------ #
	# Account balance
	# ------------------------------------------------------------------ #

	def get_account_balance(self, product: str = "collection") -> dict[str, Any]:
		"""Check the float balance for a product.

		Args:
			product: "collection" | "disbursement" | "remittance"

		Returns:
			{availableBalance, currency} dict from the MoMo API.
		"""
		product_path = _PRODUCT_PATH.get(product.lower(), product.lower())
		try:
			token = self.get_access_token(product.lower())
			url = f"{self.base_url}/{product_path}/v1_0/account/balance"
			req = urllib.request.Request(
				url,
				method="GET",
				headers={
					"Authorization": f"Bearer {token}",
					"X-Target-Environment": self.environment,
					"Ocp-Apim-Subscription-Key": self.subscription_key,
				},
			)
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise MTNMoMoError(f"get_account_balance HTTP {exc.code}: {body}") from exc
		except MTNMoMoError:
			raise
		except Exception as exc:
			raise MTNMoMoError(f"get_account_balance failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test() -> None:
	"""Sandbox smoke test.
	Run: python -m pgappforge.plugins.connectors.mtn_momo.client --test
	Requires MTN_MOMO_SUBSCRIPTION_KEY env var.
	"""
	import os
	logging.basicConfig(level=logging.INFO)

	sub_key = os.environ.get("MTN_MOMO_SUBSCRIPTION_KEY", "")
	if not sub_key:
		print("Set MTN_MOMO_SUBSCRIPTION_KEY to your sandbox subscription key.")
		return

	client = MTNMoMoClient(
		subscription_key=sub_key,
		base_url=_SANDBOX_BASE_URL,
		environment="sandbox",
		currency="EUR",
	)
	print("Creating sandbox API user…")
	api_user = client.create_api_user("https://myapp.example.com")
	print(f"  api_user_id = {api_user}")

	api_key = client.get_api_key(api_user)
	print(f"  api_key = {api_key}")

	client.api_user = api_user
	client.api_key = api_key

	token = client.get_access_token("collection")
	print(f"  access_token = {token[:20]}…")

	result = client.request_to_pay(
		amount="5",
		currency="EUR",
		msisdn="46733123454",
		external_id="test-ext-001",
		payer_message="Test payment",
		payee_note="Test ref",
	)
	import pprint
	pprint.pprint(result)


if __name__ == "__main__":
	import sys
	if "--test" in sys.argv:
		_cli_test()


__all__ = ["MTNMoMoClient", "MTNMoMoError"]
