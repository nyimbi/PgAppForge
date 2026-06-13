"""
pgappforge/plugins/connectors/africas_talking/client.py

Africa's Talking — SMS, USSD, Voice, and Airtime across 18 African countries.

Supports: Kenya, Uganda, Tanzania, Nigeria, Ghana, Ethiopia, Rwanda, Zambia,
          Ivory Coast, Senegal, South Africa, Zimbabwe, Malawi, Cameroon,
          Mozambique, Sudan, Egypt, and more.

pip install africastalking   (optional — enables SDK-based sending)
OR uses direct HTTPS API (no SDK dependency).

Config (Flask app.config):
    AT_API_KEY       Africa's Talking API key (mandatory)
    AT_USERNAME      AT username; use "sandbox" for testing
    AT_SENDER_ID     Alphanumeric sender ID (e.g. "MYAPP")
    AT_TIMEOUT       HTTP timeout seconds (default 30)
    AT_ENABLED       Set False to skip in dev (default True)

Sandbox:
    Set AT_USERNAME = "sandbox" (Africa's Talking sandbox environment).
    Use Simulator at https://simulator.africastalking.com for USSD testing.

CLI test helper:
    python -m pgappforge.plugins.connectors.africas_talking.client --test +254712345678
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_SMS_URL = "https://api.africastalking.com/version1/messaging"
_SANDBOX_SMS_URL = "https://api.sandbox.africastalking.com/version1/messaging"


class AfricasTalkingError(Exception):
	"""Base error for Africa's Talking API failures."""


class AfricasTalkingClient:
	"""Africa's Talking API client for SMS and USSD.

	Uses the direct HTTPS REST API — no SDK dependency required.
	Install the official SDK for Voice and Airtime:  pip install africastalking

	Example::

		client = AfricasTalkingClient.from_config()
		result = client.send_sms("+254712345678", "Hello from PgAppForge!")
		print(result)
	"""

	def __init__(
		self,
		api_key: str = "",
		username: str = "sandbox",
		sender_id: str = "",
		timeout: int = 30,
		enabled: bool = True,
	) -> None:
		self.api_key = api_key
		self.username = username
		self.sender_id = sender_id
		self.timeout = timeout
		self.enabled = enabled
		self._is_sandbox = (username == "sandbox")

	@classmethod
	def from_config(cls) -> "AfricasTalkingClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			return cls(
				api_key=cfg.get("AT_API_KEY", ""),
				username=cfg.get("AT_USERNAME", "sandbox"),
				sender_id=cfg.get("AT_SENDER_ID", ""),
				timeout=int(cfg.get("AT_TIMEOUT", 30)),
				enabled=cfg.get("AT_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	@classmethod
	def sandbox(cls, api_key: str = "test_api_key") -> "AfricasTalkingClient":
		"""Convenience factory for AT sandbox environment."""
		return cls(api_key=api_key, username="sandbox", enabled=True)

	# ------------------------------------------------------------------ #
	# SMS
	# ------------------------------------------------------------------ #

	def send_sms(
		self,
		to: str | list[str],
		message: str,
		sender_id: str | None = None,
	) -> dict[str, Any]:
		"""Send an SMS to one or more recipients.

		Args:
			to:        Phone number(s) in E.164 format, e.g. "+254712345678".
			           Accepts a string (single) or list (bulk, up to 1000).
			message:   SMS body (max 1600 chars, multi-part auto-handled by AT).
			sender_id: Override the default sender ID for this message.

		Returns:
			AT API response dict with SMSMessageData.Recipients list.
		"""
		if not self.enabled:
			log.debug("AT SMS disabled — skipping send to %s", to)
			return {"skipped": True, "recipients": []}

		if not self.api_key:
			return {"error": "AT_API_KEY not configured"}

		if isinstance(to, list):
			recipients = ",".join(to)
		else:
			recipients = to

		body: dict[str, str] = {
			"username": self.username,
			"to": recipients,
			"message": message[:1600],
		}
		sid = sender_id or self.sender_id
		if sid:
			body["from"] = sid

		return self._post_form(_SMS_URL, body)

	def send_bulk_sms(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
		"""Send personalised SMS messages in bulk.

		Args:
			messages: List of {to: str, message: str} dicts.

		Returns:
			List of AT API response dicts, one per message.
		"""
		results = []
		for msg in messages:
			result = self.send_sms(msg.get("to", ""), msg.get("message", ""))
			result["_to"] = msg.get("to")
			results.append(result)
		return results

	def send_otp(self, phone: str, otp: str, app_name: str = "PgAppForge") -> dict[str, Any]:
		"""Send a one-time password via SMS.

		Args:
			phone:    Recipient phone in E.164 format.
			otp:      6-digit OTP string.
			app_name: Application name used in the message body.

		Returns:
			send_sms response dict.
		"""
		message = f"Your {app_name} verification code is: {otp}. Valid for 10 minutes. Do not share."
		return self.send_sms(phone, message)

	# ------------------------------------------------------------------ #
	# USSD
	# ------------------------------------------------------------------ #

	def handle_ussd_request(
		self,
		session_id: str,
		service_code: str,
		phone_number: str,
		text: str,
		menu_handler: Any | None = None,
	) -> str:
		"""Build a USSD response string for an incoming AT USSD request.

		Africa's Talking sends USSD requests to your webhook URL as POST form data.
		Your handler must return a plain-text response prefixed with:
		  "CON "  — continue (show next menu)
		  "END "  — end session (final message)

		Args:
			session_id:    AT-assigned session identifier.
			service_code:  USSD short code, e.g. "*384*1#".
			phone_number:  User's phone number in E.164 format.
			text:          Accumulated user input (empty for first request,
			               "1" after selecting option 1, "1*2" after option 2, etc.)
			menu_handler:  Optional callable(session_id, phone, text) -> str.
			               If not provided, returns a default welcome menu.

		Returns:
			USSD response string starting with "CON " or "END ".
		"""
		if menu_handler is not None:
			try:
				return menu_handler(session_id, phone_number, text)
			except Exception as exc:
				log.error("USSD menu_handler failed: %s", exc, exc_info=True)
				return "END Service temporarily unavailable. Please try again."

		# Default demo menu
		if not text:
			return (
				"CON Welcome to PgAppForge\n"
				"1. Check Balance\n"
				"2. Make Payment\n"
				"3. Get Statement\n"
				"0. Exit"
			)
		parts = text.split("*")
		choice = parts[0]
		if choice == "0":
			return "END Thank you. Goodbye."
		if choice == "1":
			return "END Your balance is: KES 0.00\n(Demo mode)"
		if choice == "2":
			return "END Payment feature not configured.\n(Demo mode)"
		if choice == "3":
			return "END Statement feature not configured.\n(Demo mode)"
		return "END Invalid option. Please try again."

	# ------------------------------------------------------------------ #
	# Airtime (SDK required)
	# ------------------------------------------------------------------ #

	def send_airtime(
		self,
		recipients: list[dict[str, Any]],
	) -> dict[str, Any]:
		"""Send airtime to recipients.  Requires: pip install africastalking

		Args:
			recipients: List of {phoneNumber: str, amount: str, currencyCode: str}
			            e.g. [{"phoneNumber": "+254712345678", "amount": "KES 50"}]

		Returns:
			AT SDK response dict.
		"""
		try:
			import africastalking as _at  # type: ignore[import]
			_at.initialize(self.username, self.api_key)
			airtime = _at.Airtime.send(recipients=recipients)
			return airtime
		except ImportError:
			return {"error": "africastalking SDK not installed — pip install africastalking"}
		except Exception as exc:
			log.error("AT airtime send failed: %s", exc)
			return {"error": str(exc)}

	# ------------------------------------------------------------------ #
	# Internal
	# ------------------------------------------------------------------ #

	def _post_form(self, url: str, body: dict[str, str]) -> dict[str, Any]:
		"""POST application/x-www-form-urlencoded and return parsed JSON."""
		data = urllib.parse.urlencode(body).encode()
		req = urllib.request.Request(
			url,
			data=data,
			method="POST",
			headers={
				"Accept": "application/json",
				"apiKey": self.api_key,
				"Content-Type": "application/x-www-form-urlencoded",
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				return json.loads(resp.read())
		except urllib.error.HTTPError as exc:
			body_text = exc.read().decode(errors="replace")[:300]
			raise AfricasTalkingError(f"AT API HTTP {exc.code}: {body_text}") from exc
		except Exception as exc:
			raise AfricasTalkingError(f"AT API request failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test(phone: str) -> None:
	"""Sandbox smoke test.
	Run: python -m pgappforge.plugins.connectors.africas_talking.client --test +254712345678
	"""
	logging.basicConfig(level=logging.INFO)
	client = AfricasTalkingClient.sandbox()
	print(f"AT sandbox client: username={client.username}")

	result = client.send_sms(phone, "PgAppForge AT connector test message.")
	print("SMS result:", json.dumps(result, indent=2))

	otp_result = client.send_otp(phone, "123456")
	print("OTP result:", json.dumps(otp_result, indent=2))


if __name__ == "__main__":
	import sys
	args = sys.argv[1:]
	if "--test" in args:
		idx = args.index("--test")
		phone_arg = args[idx + 1] if idx + 1 < len(args) else "+254700000000"
		_cli_test(phone_arg)


__all__ = ["AfricasTalkingClient", "AfricasTalkingError"]
