"""
pgappforge/plugins/connectors/etims/client.py

KRA eTIMS — Kenya Revenue Authority Electronic Tax Invoice Management System.

Mandatory from January 2024.  All VAT-registered businesses must submit every
invoice to KRA before issuing it to the customer.  KRA returns a Control Unit
Invoice Number (CUIN) and a fiscal signature that must appear on the invoice.

Penalties for non-compliance: up to KES 1 M or 10 % of tax involved.

Config (Flask app.config or environment):
    ETIMS_PIN            KRA PIN of the taxpayer, e.g. "P000000000A"
    ETIMS_BRANCH_ID      Branch identifier, default "00"
    ETIMS_BASE_URL       API base, default "https://etims-api.kra.go.ke"
    ETIMS_DEVICE_SERIAL  Control unit serial number
    ETIMS_TIMEOUT        HTTP timeout in seconds, default 30
    ETIMS_ENABLED        Set False to skip submission (dev/test), default True

Sandbox / test mode:
    Set ETIMS_BASE_URL = "https://etims-sbx.kra.go.ke" for the KRA sandbox.
    Use PIN "A000000000A" for sandbox tests.

CLI test helper:
    python -m pgappforge.plugins.connectors.etims.client --test
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

log = logging.getLogger(__name__)

_SANDBOX_BASE_URL = "https://etims-sbx.kra.go.ke"
_PROD_BASE_URL = "https://etims-api.kra.go.ke"
_SANDBOX_PIN = "A000000000A"


class ETIMSError(Exception):
	"""Base error for all eTIMS client errors."""


class ETIMSValidationError(ETIMSError):
	"""Invoice data failed local validation before submission."""


class ETIMSSubmissionError(ETIMSError):
	"""KRA API returned an error or the HTTP request failed."""


class ETIMSClient:
	"""KRA eTIMS API client.

	Submits invoices to KRA and returns the CUIN (Control Unit Invoice Number)
	and fiscal signatures required on printed/digital invoices.

	Example::

		client = ETIMSClient.from_config()
		result = client.submit_invoice(
		    invoice_number="INV-2024-001",
		    customer_pin="A000000000Z",
		    customer_name="Acme Ltd",
		    items=[
		        {"description": "Consulting", "quantity": 1,
		         "unit_price_kes": 100000, "vat_rate_pct": 16},
		    ],
		)
		if result["success"]:
		    print("CUIN:", result["control_unit_invoice_number"])
	"""

	def __init__(
		self,
		pin: str = "",
		branch_id: str = "00",
		base_url: str = _PROD_BASE_URL,
		device_serial: str = "",
		timeout: int = 30,
		enabled: bool = True,
	) -> None:
		self.pin = pin
		self.branch_id = branch_id
		self.base_url = base_url.rstrip("/")
		self.device_serial = device_serial
		self.timeout = timeout
		self.enabled = enabled

	@classmethod
	def from_config(cls) -> "ETIMSClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			return cls(
				pin=cfg.get("ETIMS_PIN", ""),
				branch_id=cfg.get("ETIMS_BRANCH_ID", "00"),
				base_url=cfg.get("ETIMS_BASE_URL", _PROD_BASE_URL),
				device_serial=cfg.get("ETIMS_DEVICE_SERIAL", ""),
				timeout=int(cfg.get("ETIMS_TIMEOUT", 30)),
				enabled=cfg.get("ETIMS_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	@classmethod
	def sandbox(cls, pin: str = _SANDBOX_PIN) -> "ETIMSClient":
		"""Convenience factory for KRA sandbox environment."""
		return cls(pin=pin, base_url=_SANDBOX_BASE_URL, enabled=True)

	# ------------------------------------------------------------------ #
	# Public API
	# ------------------------------------------------------------------ #

	def submit_invoice(
		self,
		invoice_number: str,
		customer_pin: str,
		customer_name: str,
		items: list[dict[str, Any]],
		invoice_date: str | None = None,
		invoice_type: str = "ORIGINAL",
		payment_type_code: str = "01",
	) -> dict[str, Any]:
		"""Submit an invoice to KRA eTIMS.

		Args:
			invoice_number:    Your internal invoice number (unique per branch).
			customer_pin:      KRA PIN of the buyer.  Use "000000000" for
			                   non-registered individuals.
			customer_name:     Buyer name (truncated to 100 chars).
			items:             List of line items.  Each dict accepts:
			                     description      str
			                     quantity         float
			                     unit_price_kes   float  (KES, including VAT)
			                     vat_rate_pct     float  (0 | 8 | 16, default 16)
			                     item_code        str    (optional)
			                     class_code       str    (KRA item classification, optional)
			invoice_date:      ISO date string (YYYY-MM-DD).  Defaults to today.
			invoice_type:      "ORIGINAL" | "CREDIT" | "DEBIT"
			payment_type_code: "01" = Cash, "02" = Bank, "16" = M-Pesa

		Returns:
			{
			  success: bool,
			  control_unit_invoice_number: str,
			  invoice_signature: str,
			  fiscal_element_signature: str,
			  error: str | None,
			}
		"""
		if not self.enabled:
			log.debug("eTIMS disabled — skipping submission of %s", invoice_number)
			return {
				"success": True,
				"control_unit_invoice_number": "",
				"invoice_signature": "",
				"fiscal_element_signature": "",
				"error": None,
				"skipped": True,
			}

		if not self.pin:
			return {"success": False, "error": "ETIMS_PIN not configured", "control_unit_invoice_number": "", "invoice_signature": "", "fiscal_element_signature": ""}

		if not items:
			return {"success": False, "error": "Invoice must have at least one line item", "control_unit_invoice_number": "", "invoice_signature": "", "fiscal_element_signature": ""}

		if not invoice_date:
			invoice_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

		# Map invoice_type to eTIMS receipt type code
		_type_map = {"ORIGINAL": "S", "CREDIT": "C", "DEBIT": "D"}
		rcpt_type_cd = _type_map.get(invoice_type.upper(), "S")

		payload: dict[str, Any] = {
			"tpin": self.pin,
			"bhfId": self.branch_id,
			"orgInvcNo": str(invoice_number),
			"custTpin": customer_pin,
			"custNm": customer_name[:100],
			"salesTyCd": "N",             # N = Normal sale
			"rcptTyCd": rcpt_type_cd,
			"pmtTyCd": payment_type_code,
			"salesSttsCd": "02",           # 02 = Approved
			"cfmDt": invoice_date.replace("-", ""),
			"salesDt": invoice_date.replace("-", ""),
			"itemList": [],
		}

		total_vatable = Decimal("0")
		total_vat = Decimal("0")
		total_exempt = Decimal("0")
		total_amount = Decimal("0")

		for i, item in enumerate(items):
			unit_price = Decimal(str(item.get("unit_price_kes", 0)))
			quantity = Decimal(str(item.get("quantity", 1)))
			vat_rate_pct = Decimal(str(item.get("vat_rate_pct", 16)))
			vat_rate = vat_rate_pct / 100

			line_total = (unit_price * quantity).quantize(Decimal("0.01"), ROUND_HALF_UP)

			if vat_rate > 0:
				# unit_price is VAT-inclusive
				vat_amount = (line_total * vat_rate / (1 + vat_rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
				vatable_amount = line_total - vat_amount
				tax_type_cd = "A"   # Standard-rated
				total_vatable += vatable_amount
				total_vat += vat_amount
			else:
				vat_amount = Decimal("0")
				vatable_amount = Decimal("0")
				tax_type_cd = "E"   # VAT-exempt
				total_exempt += line_total

			total_amount += line_total

			payload["itemList"].append({
				"itemSeq": i + 1,
				"itemCd": item.get("item_code", f"ITM{i+1:03d}"),
				"itemClsCd": item.get("class_code", "5020230602"),
				"itemNm": str(item.get("description", ""))[:100],
				"qty": float(quantity),
				"qtyUnitCd": "U",
				"prc": float(unit_price),
				"splyAmt": float(line_total),
				"dcRt": 0,
				"dcAmt": 0,
				"taxblAmt": float(vatable_amount),
				"taxTyCd": tax_type_cd,
				"taxAmt": float(vat_amount),
				"totAmt": float(line_total),
			})

		payload["taxblAmtA"] = float(total_vatable)       # standard-rated net
		payload["taxRtA"] = 16.0
		payload["taxAmtA"] = float(total_vat)
		payload["taxblAmtE"] = float(total_exempt)         # exempt
		payload["totTaxblAmt"] = float(total_vatable + total_exempt)
		payload["totTaxAmt"] = float(total_vat)
		payload["totAmt"] = float(total_amount)

		try:
			result = self._post("/api/method/saveSales", payload)
			data = result.get("data", {})
			return {
				"success": True,
				"control_unit_invoice_number": data.get("rcptNo", ""),
				"invoice_signature": data.get("intrlData", ""),
				"fiscal_element_signature": data.get("rcptSign", ""),
				"error": None,
			}
		except ETIMSSubmissionError as exc:
			log.warning("eTIMS submission failed for %s: %s", invoice_number, exc)
			return {
				"success": False,
				"control_unit_invoice_number": "",
				"invoice_signature": "",
				"fiscal_element_signature": "",
				"error": str(exc),
			}

	def ping(self) -> dict[str, Any]:
		"""Check connectivity to the eTIMS API."""
		try:
			self._post("/api/method/selectInitOsdcInfo", {
				"tpin": self.pin or _SANDBOX_PIN,
				"bhfId": self.branch_id,
			})
			return {"reachable": True, "error": None}
		except ETIMSSubmissionError as exc:
			return {"reachable": False, "error": str(exc)}

	# ------------------------------------------------------------------ #
	# Internal
	# ------------------------------------------------------------------ #

	def _post(self, path: str, payload: dict) -> dict:
		url = f"{self.base_url}{path}"
		data = json.dumps(payload).encode()
		req = urllib.request.Request(
			url,
			data=data,
			method="POST",
			headers={
				"Content-Type": "application/json",
				"tpin": self.pin,
				"bhfId": self.branch_id,
				"cmcKey": self.device_serial,
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				body = resp.read()
				result = json.loads(body)
				if result.get("resultCd") not in ("000", 0, "0"):
					raise ETIMSSubmissionError(
						f"eTIMS error {result.get('resultCd')}: {result.get('resultMsg', '')}"
					)
				return result
		except urllib.error.HTTPError as exc:
			body_text = exc.read().decode(errors="replace")[:300]
			raise ETIMSSubmissionError(f"eTIMS HTTP {exc.code}: {body_text}") from exc
		except ETIMSSubmissionError:
			raise
		except Exception as exc:
			raise ETIMSSubmissionError(f"eTIMS request failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test() -> None:
	"""Quick sandbox smoke test.  Run: python -m pgappforge.plugins.connectors.etims.client --test"""
	logging.basicConfig(level=logging.INFO)
	client = ETIMSClient.sandbox()
	print(f"eTIMS sandbox client: PIN={client.pin}  URL={client.base_url}")

	result = client.submit_invoice(
		invoice_number="TEST-001",
		customer_pin="000000000",
		customer_name="Test Customer",
		items=[
			{
				"description": "Software Licence",
				"quantity": 1,
				"unit_price_kes": 11600,  # 10 000 + 16 % VAT
				"vat_rate_pct": 16,
			},
			{
				"description": "Exempt Service",
				"quantity": 2,
				"unit_price_kes": 5000,
				"vat_rate_pct": 0,
			},
		],
	)
	import pprint
	pprint.pprint(result)


if __name__ == "__main__":
	import sys
	if "--test" in sys.argv:
		_cli_test()


__all__ = ["ETIMSClient", "ETIMSError", "ETIMSValidationError", "ETIMSSubmissionError"]
