"""
pgappforge/plugins/connectors/paystack/client.py

Paystack — leading payment gateway in Nigeria, Ghana, Kenya, and South Africa.

Supported payment methods:
  - Card (Visa, Mastercard, Verve, Amex)
  - Bank transfer
  - USSD
  - Mobile money (Ghana)
  - QR
  - Saved card (authorization codes)

Amount convention:
  All amounts are in the currency's smallest unit (kobo for NGN, pesewas for GHS,
  cents for ZAR / USD).  For KES the API uses whole shillings — but this client
  accepts kobo-style integers throughout for consistency (pass amount * 100 for KES).
  Verify this matches your Paystack account's currency setting.

  Summary:  amount_kobo = amount_in_currency_units * 100

Config (Flask app.config):
  PAYSTACK_SECRET_KEY   sk_live_... or sk_test_... from Paystack dashboard
  PAYSTACK_BASE_URL     Default "https://api.paystack.co"
  PAYSTACK_TIMEOUT      HTTP timeout seconds (default 30)
  PAYSTACK_ENABLED      Set False to skip in dev (default True)

Sandbox:
  Use sk_test_* keys — no separate base URL needed.

CLI test helper:
  python -m pgappforge.plugins.connectors.paystack.client --test
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_URL = "https://api.paystack.co"


class PaystackError(Exception):
	"""Base error for Paystack API failures."""


class PaystackClient:
	"""Paystack REST API client.

	All amounts in kobo (smallest currency unit × 100).  E.g. NGN 100 = 10000 kobo,
	KES 100 = 10000 kobo.

	Example::

		client = PaystackClient.from_config()

		# Start a hosted checkout:
		init = client.initialize_transaction(
		    email="customer@example.com",
		    amount_kobo=50000,       # NGN 500
		    reference="ORD-001",
		    callback_url="https://myapp.com/payment/callback",
		)
		# Redirect user to init["data"]["authorization_url"]

		# Verify after callback:
		result = client.verify_transaction("ORD-001")
		if result["data"]["status"] == "success":
		    # fulfil order
		    pass
	"""

	def __init__(
		self,
		secret_key: str = "",
		base_url: str = _BASE_URL,
		timeout: int = 30,
		enabled: bool = True,
	) -> None:
		self.secret_key = secret_key
		self.base_url = base_url.rstrip("/")
		self.timeout = timeout
		self.enabled = enabled

	@classmethod
	def from_config(cls) -> "PaystackClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			return cls(
				secret_key=cfg.get("PAYSTACK_SECRET_KEY", ""),
				base_url=cfg.get("PAYSTACK_BASE_URL", _BASE_URL),
				timeout=int(cfg.get("PAYSTACK_TIMEOUT", 30)),
				enabled=cfg.get("PAYSTACK_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	@classmethod
	def sandbox(cls, secret_key: str = "sk_test_PLACEHOLDER") -> "PaystackClient":
		"""Convenience factory using Paystack test key.
		Replace PLACEHOLDER with your actual sk_test_* key from dashboard.paystack.com.
		"""
		return cls(secret_key=secret_key, enabled=True)

	# ------------------------------------------------------------------ #
	# Transactions
	# ------------------------------------------------------------------ #

	def initialize_transaction(
		self,
		email: str,
		amount_kobo: int,
		reference: str | None = None,
		callback_url: str = "",
		metadata: dict | None = None,
	) -> dict[str, Any]:
		"""Create a new transaction and return a hosted payment page URL.

		Args:
			email:        Customer email address.
			amount_kobo:  Amount in kobo (currency × 100).
			reference:    Unique transaction reference.  Paystack auto-generates
			              if omitted.
			callback_url: URL to redirect after payment.
			metadata:     Optional metadata dict (stored with transaction).

		Returns:
			Paystack API response.  Key: data.authorization_url (redirect here).
		"""
		if not self.enabled:
			return {"status": True, "message": "skipped", "data": {"authorization_url": ""}, "skipped": True}

		if not self.secret_key:
			return {"status": False, "message": "PAYSTACK_SECRET_KEY not configured", "data": {}}

		payload: dict[str, Any] = {
			"email": email,
			"amount": int(amount_kobo),
		}
		if reference:
			payload["reference"] = reference
		if callback_url:
			payload["callback_url"] = callback_url
		if metadata:
			payload["metadata"] = metadata

		return self._post("/transaction/initialize", payload)

	def verify_transaction(self, reference: str) -> dict[str, Any]:
		"""Verify a transaction by reference.

		Args:
			reference: The transaction reference used in initialize_transaction().

		Returns:
			Paystack API response.  Key: data.status ("success" | "failed" | "abandoned").
		"""
		return self._get(f"/transaction/verify/{urllib.parse.quote(reference, safe='')}")

	def charge_authorization(
		self,
		authorization_code: str,
		email: str,
		amount_kobo: int,
		reference: str | None = None,
	) -> dict[str, Any]:
		"""Charge a saved card using a reusable authorization code.

		Args:
			authorization_code: From a previous successful transaction
			                    (data.authorization.authorization_code).
			email:              Customer email (must match original transaction).
			amount_kobo:        Amount in kobo.
			reference:          Unique reference for this charge.

		Returns:
			Paystack charge response.
		"""
		if not self.enabled:
			return {"status": True, "message": "skipped", "data": {}, "skipped": True}

		if not self.secret_key:
			return {"status": False, "message": "PAYSTACK_SECRET_KEY not configured", "data": {}}

		payload: dict[str, Any] = {
			"authorization_code": authorization_code,
			"email": email,
			"amount": int(amount_kobo),
		}
		if reference:
			payload["reference"] = reference

		return self._post("/transaction/charge_authorization", payload)

	def list_transactions(
		self,
		per_page: int = 50,
		page: int = 1,
		status: str | None = None,
	) -> dict[str, Any]:
		"""List transactions with optional status filter.

		Args:
			per_page: Results per page (max 100).
			page:     Page number (1-based).
			status:   "success" | "failed" | "abandoned" | None (all).

		Returns:
			Paystack paginated response with data list.
		"""
		params: dict[str, Any] = {"perPage": per_page, "page": page}
		if status:
			params["status"] = status
		qs = urllib.parse.urlencode(params)
		return self._get(f"/transaction?{qs}")

	def get_transaction(self, transaction_id: str) -> dict[str, Any]:
		"""Get a single transaction by ID.

		Args:
			transaction_id: Paystack transaction ID (integer string).

		Returns:
			Paystack transaction object.
		"""
		return self._get(f"/transaction/{transaction_id}")

	# ------------------------------------------------------------------ #
	# Transfers (payouts)
	# ------------------------------------------------------------------ #

	def initiate_transfer(
		self,
		amount: int,
		recipient_code: str,
		reference: str,
		reason: str = "",
	) -> dict[str, Any]:
		"""Send money to a transfer recipient.

		Args:
			amount:         Amount in kobo.
			recipient_code: Recipient code from create_transfer_recipient().
			reference:      Unique reference for this transfer.
			reason:         Optional transfer narration.

		Returns:
			Paystack transfer response.
		"""
		if not self.enabled:
			return {"status": True, "message": "skipped", "data": {}, "skipped": True}

		if not self.secret_key:
			return {"status": False, "message": "PAYSTACK_SECRET_KEY not configured", "data": {}}

		payload: dict[str, Any] = {
			"source": "balance",
			"amount": int(amount),
			"recipient": recipient_code,
			"reference": reference,
		}
		if reason:
			payload["reason"] = reason[:100]

		return self._post("/transfer", payload)

	def create_transfer_recipient(
		self,
		type: str,
		name: str,
		account_number: str,
		bank_code: str,
		currency: str = "NGN",
	) -> dict[str, Any]:
		"""Create a transfer recipient (bank account or mobile money).

		Args:
			type:           "nuban" (Nigeria bank) | "ghipss" (Ghana) |
			                "mobile_money" | "basa" (South Africa).
			name:           Account holder name.
			account_number: Account number or phone number.
			bank_code:      Bank code from list_banks().
			currency:       ISO 4217 code matching the recipient's currency.

		Returns:
			Paystack response with data.recipient_code for transfers.
		"""
		payload: dict[str, Any] = {
			"type": type,
			"name": name,
			"account_number": account_number,
			"bank_code": bank_code,
			"currency": currency,
		}
		return self._post("/transferrecipient", payload)

	# ------------------------------------------------------------------ #
	# Banks & account resolution
	# ------------------------------------------------------------------ #

	def list_banks(self, country: str = "nigeria") -> dict[str, Any]:
		"""Get list of supported banks for a country.

		Args:
			country: "nigeria" | "ghana" | "kenya" | "south africa"

		Returns:
			Paystack response with data list of banks.
		"""
		qs = urllib.parse.urlencode({"country": country, "perPage": 100})
		return self._get(f"/bank?{qs}")

	def resolve_account(self, account_number: str, bank_code: str) -> dict[str, Any]:
		"""Verify a bank account number and retrieve the account name.

		Args:
			account_number: Bank account number.
			bank_code:      Bank code from list_banks().

		Returns:
			{data: {account_number, account_name}} or error.
		"""
		qs = urllib.parse.urlencode({"account_number": account_number, "bank_code": bank_code})
		return self._get(f"/bank/resolve?{qs}")

	# ------------------------------------------------------------------ #
	# Customers
	# ------------------------------------------------------------------ #

	def create_customer(
		self,
		email: str,
		first_name: str = "",
		last_name: str = "",
		phone: str = "",
	) -> dict[str, Any]:
		"""Create a Paystack customer record.

		Args:
			email:      Customer email (primary key).
			first_name: Optional first name.
			last_name:  Optional last name.
			phone:      Optional phone number in E.164 format.

		Returns:
			Paystack customer object with data.customer_code.
		"""
		payload: dict[str, Any] = {"email": email}
		if first_name:
			payload["first_name"] = first_name
		if last_name:
			payload["last_name"] = last_name
		if phone:
			payload["phone"] = phone

		return self._post("/customer", payload)

	# ------------------------------------------------------------------ #
	# Internal
	# ------------------------------------------------------------------ #

	def _headers(self) -> dict[str, str]:
		return {
			"Authorization": f"Bearer {self.secret_key}",
			"Content-Type": "application/json",
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
			raise PaystackError(f"Paystack HTTP {exc.code}: {body}") from exc
		except PaystackError:
			raise
		except Exception as exc:
			raise PaystackError(f"Paystack request failed: {exc}") from exc

	def _get(self, path: str) -> dict:
		url = f"{self.base_url}{path}"
		req = urllib.request.Request(url, method="GET", headers=self._headers())
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")[:300]
			raise PaystackError(f"Paystack HTTP {exc.code}: {body}") from exc
		except PaystackError:
			raise
		except Exception as exc:
			raise PaystackError(f"Paystack request failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test() -> None:
	"""Sandbox smoke test.
	Run: python -m pgappforge.plugins.connectors.paystack.client --test
	Requires PAYSTACK_SECRET_KEY env var (sk_test_*).
	"""
	import os
	logging.basicConfig(level=logging.INFO)

	secret_key = os.environ.get("PAYSTACK_SECRET_KEY", "")
	if not secret_key:
		print("Set PAYSTACK_SECRET_KEY to your sk_test_* key from dashboard.paystack.com")
		return

	client = PaystackClient(secret_key=secret_key)
	print(f"Paystack client: key={secret_key[:12]}…")

	banks = client.list_banks("nigeria")
	data = banks.get("data", [])
	print(f"Nigeria banks ({len(data)} found):", [b.get("name") for b in data[:3]])

	init = client.initialize_transaction(
		email="test@example.com",
		amount_kobo=10000,  # NGN 100
		reference="TEST-PSK-001",
	)
	import pprint
	pprint.pprint(init)


if __name__ == "__main__":
	import sys
	if "--test" in sys.argv:
		_cli_test()


__all__ = ["PaystackClient", "PaystackError"]
