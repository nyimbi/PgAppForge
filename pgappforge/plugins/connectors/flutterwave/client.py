"""
pgappforge/plugins/connectors/flutterwave/client.py

Flutterwave — Africa's leading payment gateway.

Supports 34 African countries.  Payment methods:
  - Card (Visa, Mastercard, Verve)
  - Mobile Money (M-Pesa KE, MTN MoMo, Airtel Money, Zamtel)
  - USSD
  - Bank transfer (Nigeria, Ghana, South Africa, Kenya, Uganda, Tanzania)
  - Barter / QR

All amounts in the currency's minor unit (kobo for NGN, cents for USD, etc.).
For KES, UGX, GHS the API accepts the face value (no minor unit scaling).

pip install requests   (optional — enables connection pooling)
Uses stdlib urllib.request as fallback.

Config (Flask app.config):
    FLW_PUBLIC_KEY   Flutterwave public key (pk_live_... or pk_test_...)
    FLW_SECRET_KEY   Flutterwave secret key (sk_live_... or sk_test_...)
    FLW_BASE_URL     API base (default "https://api.flutterwave.com/v3")
    FLW_ENABLED      Set False to skip in dev (default True)

Sandbox:
    Use pk_test_* / sk_test_* keys from the Flutterwave dashboard.
    No separate base URL needed — test keys auto-route to sandbox.

CLI test helper:
    python -m pgappforge.plugins.connectors.flutterwave.client --test
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_URL = "https://api.flutterwave.com/v3"


class FlutterwaveError(Exception):
	"""Base error for Flutterwave API failures."""


class FlutterwaveClient:
	"""Flutterwave REST API client.

	Example::

		client = FlutterwaveClient.from_config()

		# Standard checkout redirect:
		result = client.initiate_payment(
		    amount=5000, currency="KES",
		    email="john@example.com", phone="+254712345678",
		    name="John Doe", reference="ORD-001",
		    redirect_url="https://myapp.com/payment/callback",
		)
		if result["success"]:
		    # Redirect user to result["payment_link"]
		    pass
	"""

	def __init__(
		self,
		public_key: str = "",
		secret_key: str = "",
		base_url: str = _BASE_URL,
		enabled: bool = True,
	) -> None:
		self.public_key = public_key
		self.secret_key = secret_key
		self.base_url = base_url.rstrip("/")
		self.enabled = enabled

	@classmethod
	def from_config(cls) -> "FlutterwaveClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			return cls(
				public_key=cfg.get("FLW_PUBLIC_KEY", ""),
				secret_key=cfg.get("FLW_SECRET_KEY", ""),
				base_url=cfg.get("FLW_BASE_URL", _BASE_URL),
				enabled=cfg.get("FLW_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	@classmethod
	def sandbox(cls, public_key: str = "pk_test_PLACEHOLDER", secret_key: str = "sk_test_PLACEHOLDER") -> "FlutterwaveClient":
		"""Convenience factory for Flutterwave test environment.
		Replace PLACEHOLDER with your actual test keys from dashboard.flutterwave.com.
		"""
		return cls(public_key=public_key, secret_key=secret_key, enabled=True)

	# ------------------------------------------------------------------ #
	# Standard checkout
	# ------------------------------------------------------------------ #

	def initiate_payment(
		self,
		amount: float,
		currency: str,
		email: str,
		phone: str,
		name: str,
		reference: str,
		redirect_url: str,
		meta: dict | None = None,
	) -> dict[str, Any]:
		"""Create a standard payment link (Flutterwave hosted checkout).

		Args:
			amount:       Payment amount in the currency's face value.
			currency:     ISO 4217 code: KES, UGX, NGN, GHS, ZAR, USD, etc.
			email:        Customer email.
			phone:        Customer phone in E.164 format.
			name:         Customer full name.
			reference:    Your unique transaction reference.
			redirect_url: URL Flutterwave redirects to after payment.
			meta:         Optional extra metadata dict attached to the transaction.

		Returns:
			{success, payment_link, transaction_reference, error}
		"""
		if not self.enabled:
			return {"success": True, "payment_link": "", "transaction_reference": reference, "error": None, "skipped": True}

		if not self.secret_key:
			return {"success": False, "error": "FLW_SECRET_KEY not configured", "payment_link": "", "transaction_reference": ""}

		payload: dict[str, Any] = {
			"tx_ref": reference,
			"amount": amount,
			"currency": currency,
			"redirect_url": redirect_url,
			"customer": {
				"email": email,
				"phonenumber": phone,
				"name": name,
			},
		}
		if meta:
			payload["meta"] = meta

		try:
			result = self._post("/payments", payload)
			return {
				"success": True,
				"payment_link": result.get("data", {}).get("link", ""),
				"transaction_reference": reference,
				"error": None,
			}
		except FlutterwaveError as exc:
			return {"success": False, "error": str(exc), "payment_link": "", "transaction_reference": reference}

	# ------------------------------------------------------------------ #
	# Payment verification
	# ------------------------------------------------------------------ #

	def verify_payment(self, transaction_id: str | int) -> dict[str, Any]:
		"""Verify a completed transaction by ID.

		Args:
			transaction_id: Flutterwave transaction ID returned in callback.

		Returns:
			{success, status, amount, currency, reference, customer, error}
		"""
		try:
			result = self._get(f"/transactions/{transaction_id}/verify")
			data = result.get("data", {})
			return {
				"success": result.get("status") == "success",
				"status": data.get("status", ""),
				"amount": data.get("amount", 0),
				"currency": data.get("currency", ""),
				"reference": data.get("tx_ref", ""),
				"customer": data.get("customer", {}),
				"flw_ref": data.get("flw_ref", ""),
				"error": None,
			}
		except FlutterwaveError as exc:
			return {"success": False, "error": str(exc), "status": "failed", "amount": 0, "currency": "", "reference": ""}

	# ------------------------------------------------------------------ #
	# Mobile Money
	# ------------------------------------------------------------------ #

	def initiate_mobile_money(
		self,
		amount: float,
		currency: str,
		phone: str,
		network: str,
		reference: str,
		email: str = "",
		name: str = "",
	) -> dict[str, Any]:
		"""Initiate a Mobile Money charge (M-Pesa, MTN MoMo, Airtel).

		Supported currency/network combinations:
		  KES + MPESA   → Safaricom M-Pesa Kenya (STK push)
		  UGX + MTN     → MTN MoMo Uganda
		  UGX + AIRTEL  → Airtel Money Uganda
		  GHS + MTN     → MTN MoMo Ghana
		  ZMW + MTN     → MTN MoMo Zambia
		  TZS + VODACOM → Vodacom M-Pesa Tanzania

		Args:
			amount:    Amount in face value.
			currency:  ISO 4217 code.
			phone:     Customer phone in E.164 format.
			network:   "MPESA" | "MTN" | "AIRTEL" | "VODACOM" | "ZAMTEL"
			reference: Unique transaction reference.
			email:     Customer email (optional but recommended).
			name:      Customer name (optional).

		Returns:
			{success, status, flw_ref, error}
		"""
		if not self.enabled:
			return {"success": True, "status": "skipped", "flw_ref": "", "error": None, "skipped": True}

		if not self.secret_key:
			return {"success": False, "error": "FLW_SECRET_KEY not configured", "status": "failed", "flw_ref": ""}

		payload: dict[str, Any] = {
			"amount": amount,
			"currency": currency,
			"tx_ref": reference,
			"phone_number": phone,
			"network": network.upper(),
			"email": email or f"customer_{reference}@placeholder.local",
			"fullname": name or "Customer",
		}

		try:
			result = self._post("/charges?type=mobile_money_kenya" if currency == "KES" else "/charges?type=mobile_money_uganda", payload)
			data = result.get("data", {})
			return {
				"success": result.get("status") in ("success", "pending"),
				"status": data.get("status", result.get("status", "")),
				"flw_ref": data.get("flw_ref", ""),
				"error": None,
			}
		except FlutterwaveError as exc:
			return {"success": False, "error": str(exc), "status": "failed", "flw_ref": ""}

	# ------------------------------------------------------------------ #
	# Banks
	# ------------------------------------------------------------------ #

	def get_banks(self, country: str) -> list[dict[str, Any]]:
		"""Get list of banks available for bank transfer in a country.

		Args:
			country: ISO 3166-1 alpha-2 code.  Supported: KE, NG, GH, ZA, UG, TZ.

		Returns:
			List of {id, code, name} dicts.
		"""
		try:
			result = self._get(f"/banks/{country.upper()}")
			banks = result.get("data", [])
			return [
				{"id": b.get("id"), "code": b.get("code", ""), "name": b.get("name", "")}
				for b in banks
			]
		except FlutterwaveError as exc:
			log.warning("get_banks(%s) failed: %s", country, exc)
			return []

	# ------------------------------------------------------------------ #
	# Bank transfer (payout)
	# ------------------------------------------------------------------ #

	def initiate_bank_transfer(
		self,
		amount: float,
		currency: str,
		bank_code: str,
		account_number: str,
		account_name: str,
		reference: str,
		narration: str = "PgAppForge payment",
	) -> dict[str, Any]:
		"""Send money to a bank account (payout / disbursement).

		Args:
			amount:         Amount to send.
			currency:       ISO 4217 code.
			bank_code:      Bank code from get_banks().
			account_number: Recipient account number.
			account_name:   Recipient account name.
			reference:      Unique reference for this transfer.
			narration:      Payment narration (appears on bank statement).

		Returns:
			{success, status, reference, error}
		"""
		if not self.enabled:
			return {"success": True, "status": "skipped", "reference": reference, "error": None}

		if not self.secret_key:
			return {"success": False, "error": "FLW_SECRET_KEY not configured", "status": "failed", "reference": reference}

		payload: dict[str, Any] = {
			"account_bank": bank_code,
			"account_number": account_number,
			"amount": amount,
			"currency": currency,
			"narration": narration[:100],
			"reference": reference,
			"beneficiary_name": account_name[:100],
		}

		try:
			result = self._post("/transfers", payload)
			data = result.get("data", {})
			return {
				"success": result.get("status") == "success",
				"status": data.get("status", ""),
				"reference": data.get("reference", reference),
				"transfer_id": data.get("id"),
				"error": None,
			}
		except FlutterwaveError as exc:
			return {"success": False, "error": str(exc), "status": "failed", "reference": reference}

	# ------------------------------------------------------------------ #
	# Internal
	# ------------------------------------------------------------------ #

	def _post(self, path: str, payload: dict) -> dict:
		return self._request("POST", path, payload)

	def _get(self, path: str) -> dict:
		return self._request("GET", path, None)

	def _request(self, method: str, path: str, payload: dict | None) -> dict:
		url = f"{self.base_url}{path}"
		data = json.dumps(payload).encode() if payload is not None else None
		req = urllib.request.Request(
			url,
			data=data,
			method=method,
			headers={
				"Authorization": f"Bearer {self.secret_key}",
				"Content-Type": "application/json",
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=30) as resp:
				result = json.loads(resp.read())
				if result.get("status") not in ("success", "pending"):
					message = result.get("message", "Unknown error")
					raise FlutterwaveError(f"Flutterwave error: {message}")
				return result
		except urllib.error.HTTPError as exc:
			body_text = exc.read().decode(errors="replace")[:300]
			raise FlutterwaveError(f"Flutterwave HTTP {exc.code}: {body_text}") from exc
		except FlutterwaveError:
			raise
		except Exception as exc:
			raise FlutterwaveError(f"Flutterwave request failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test() -> None:
	"""Test mode smoke test.
	Run: python -m pgappforge.plugins.connectors.flutterwave.client --test
	Requires FLW_SECRET_KEY environment variable to be set with a test key.
	"""
	import os
	logging.basicConfig(level=logging.INFO)

	secret_key = os.environ.get("FLW_SECRET_KEY", "")
	public_key = os.environ.get("FLW_PUBLIC_KEY", "")
	if not secret_key:
		print("Set FLW_SECRET_KEY env var to a test key from dashboard.flutterwave.com")
		return

	client = FlutterwaveClient(public_key=public_key, secret_key=secret_key)
	print(f"Flutterwave client: key={secret_key[:12]}...")

	# List Kenya banks
	banks = client.get_banks("KE")
	print(f"Kenya banks ({len(banks)} found):", banks[:3])

	# Initiate a test payment link
	result = client.initiate_payment(
		amount=100,
		currency="KES",
		email="test@example.com",
		phone="+254700000000",
		name="Test User",
		reference="TEST-001",
		redirect_url="https://example.com/callback",
	)
	import pprint
	pprint.pprint(result)


if __name__ == "__main__":
	import sys
	if "--test" in sys.argv:
		_cli_test()


__all__ = ["FlutterwaveClient", "FlutterwaveError"]
