"""
pgappforge/plugins/connectors/efris/client.py

URA EFRIS — Uganda Revenue Authority E-Fiscal Receipts and Invoices Solution.

Mandatory for all registered taxpayers in Uganda.  URA returns a Fiscal Receipt
Number (FRN) and QR code data that must appear on every receipt/invoice.

Uganda VAT rate: 18 % (standard).  Exempt and zero-rated goods also supported.

Config (Flask app.config):
    EFRIS_TIN            Uganda TIN number, e.g. "1000000000"
    EFRIS_DEVICE_ID      Fiscal device identifier (from URA portal)
    EFRIS_BASE_URL       API base, default "https://efris.ura.go.ug"
    EFRIS_TIMEOUT        HTTP timeout seconds, default 30
    EFRIS_ENABLED        Set False to skip in dev (default True)

Sandbox:
    Set EFRIS_BASE_URL = "https://efristest.ura.go.ug" for the URA sandbox.
    Use TIN "1000000000" and device ID "99999" for sandbox tests.

CLI test helper:
    python -m pgappforge.plugins.connectors.efris.client --test
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

_SANDBOX_BASE_URL = "https://efristest.ura.go.ug"
_PROD_BASE_URL = "https://efris.ura.go.ug"
_SANDBOX_TIN = "1000000000"
_SANDBOX_DEVICE_ID = "99999"
_UGANDA_VAT_RATE = Decimal("0.18")


class EFRISError(Exception):
	"""Base error for all EFRIS client errors."""


class EFRISSubmissionError(EFRISError):
	"""URA API returned an error or the HTTP request failed."""


class EFRISClient:
	"""URA EFRIS API client for Uganda fiscal receipt/invoice submission.

	Example::

		client = EFRISClient.from_config()
		result = client.submit_invoice(
		    invoice_number="INV-2024-001",
		    customer_tin="1000000001",
		    customer_name="Kampala Traders Ltd",
		    items=[
		        {"description": "Goods", "quantity": 10,
		         "unit_price_ugx": 50000, "vat_rate_pct": 18},
		    ],
		)
		if result["success"]:
		    print("FRN:", result["fiscal_receipt_number"])
	"""

	def __init__(
		self,
		tin: str = "",
		device_id: str = "",
		base_url: str = _PROD_BASE_URL,
		timeout: int = 30,
		enabled: bool = True,
	) -> None:
		self.tin = tin
		self.device_id = device_id
		self.base_url = base_url.rstrip("/")
		self.timeout = timeout
		self.enabled = enabled

	@classmethod
	def from_config(cls) -> "EFRISClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			return cls(
				tin=cfg.get("EFRIS_TIN", ""),
				device_id=cfg.get("EFRIS_DEVICE_ID", ""),
				base_url=cfg.get("EFRIS_BASE_URL", _PROD_BASE_URL),
				timeout=int(cfg.get("EFRIS_TIMEOUT", 30)),
				enabled=cfg.get("EFRIS_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	@classmethod
	def sandbox(cls, tin: str = _SANDBOX_TIN, device_id: str = _SANDBOX_DEVICE_ID) -> "EFRISClient":
		"""Convenience factory for URA sandbox."""
		return cls(tin=tin, device_id=device_id, base_url=_SANDBOX_BASE_URL, enabled=True)

	# ------------------------------------------------------------------ #
	# Public API
	# ------------------------------------------------------------------ #

	def submit_invoice(
		self,
		invoice_number: str,
		customer_tin: str,
		customer_name: str,
		items: list[dict[str, Any]],
		invoice_date: str | None = None,
		invoice_type: str = "ORIGINAL",
		currency: str = "UGX",
		exchange_rate: float = 1.0,
	) -> dict[str, Any]:
		"""Submit an invoice/receipt to URA EFRIS.

		Args:
			invoice_number:  Your internal invoice number.
			customer_tin:    Buyer TIN.  Use "0000000000" for walk-in customers.
			customer_name:   Buyer name.
			items:           List of line items.  Each dict accepts:
			                   description      str
			                   quantity         float
			                   unit_price_ugx   float  (UGX, VAT-inclusive)
			                   vat_rate_pct     float  (0 | 18, default 18)
			                   item_code        str    (optional)
			invoice_date:    ISO date (YYYY-MM-DD).  Defaults to today.
			invoice_type:    "ORIGINAL" | "CREDIT" | "DEBIT"
			currency:        "UGX" (default) or forex code
			exchange_rate:   UGX equivalent rate (1.0 for UGX)

		Returns:
			{
			  success: bool,
			  fiscal_receipt_number: str,
			  qr_code_data: str,
			  verification_url: str,
			  error: str | None,
			}
		"""
		if not self.enabled:
			return {
				"success": True,
				"fiscal_receipt_number": "",
				"qr_code_data": "",
				"verification_url": "",
				"error": None,
				"skipped": True,
			}

		if not self.tin:
			return {"success": False, "error": "EFRIS_TIN not configured", "fiscal_receipt_number": "", "qr_code_data": "", "verification_url": ""}

		if not items:
			return {"success": False, "error": "Invoice must have at least one line item", "fiscal_receipt_number": "", "qr_code_data": "", "verification_url": ""}

		if not invoice_date:
			invoice_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

		_type_map = {"ORIGINAL": "1", "CREDIT": "3", "DEBIT": "4"}
		invoice_type_code = _type_map.get(invoice_type.upper(), "1")

		line_items: list[dict] = []
		total_net = Decimal("0")
		total_vat = Decimal("0")
		total_amount = Decimal("0")

		for i, item in enumerate(items):
			unit_price = Decimal(str(item.get("unit_price_ugx", 0)))
			quantity = Decimal(str(item.get("quantity", 1)))
			vat_rate_pct = Decimal(str(item.get("vat_rate_pct", 18)))
			vat_rate = vat_rate_pct / 100

			line_total = (unit_price * quantity).quantize(Decimal("1"), ROUND_HALF_UP)  # UGX has no cents

			if vat_rate > 0:
				vat_amount = (line_total * vat_rate / (1 + vat_rate)).quantize(Decimal("1"), ROUND_HALF_UP)
				net_amount = line_total - vat_amount
				tax_category = "A"   # Standard-rated
			else:
				vat_amount = Decimal("0")
				net_amount = line_total
				tax_category = "E"   # Exempt

			total_net += net_amount
			total_vat += vat_amount
			total_amount += line_total

			line_items.append({
				"lineNo": i + 1,
				"itemCode": item.get("item_code", f"ITM{i+1:03d}"),
				"itemDescription": str(item.get("description", ""))[:200],
				"quantity": float(quantity),
				"unitPrice": float(unit_price),
				"lineTotal": float(line_total),
				"netAmount": float(net_amount),
				"vatAmount": float(vat_amount),
				"vatRate": float(vat_rate_pct),
				"taxCategory": tax_category,
			})

		payload = {
			"tin": self.tin,
			"deviceNo": self.device_id,
			"invoiceNo": str(invoice_number),
			"invoiceType": invoice_type_code,
			"invoiceDate": invoice_date,
			"currency": currency,
			"exchangeRate": exchange_rate,
			"buyerTin": customer_tin,
			"buyerName": customer_name[:200],
			"lineItems": line_items,
			"totalNet": float(total_net),
			"totalVat": float(total_vat),
			"totalAmount": float(total_amount),
		}

		try:
			result = self._post("/efrisws/ws/taClientService/uploadInvoice", payload)
			data = result.get("data", result)
			return {
				"success": True,
				"fiscal_receipt_number": data.get("fiscalReceiptNumber", data.get("frn", "")),
				"qr_code_data": data.get("qrCode", ""),
				"verification_url": data.get("verificationUrl", ""),
				"error": None,
			}
		except EFRISSubmissionError as exc:
			log.warning("EFRIS submission failed for %s: %s", invoice_number, exc)
			return {
				"success": False,
				"fiscal_receipt_number": "",
				"qr_code_data": "",
				"verification_url": "",
				"error": str(exc),
			}

	def ping(self) -> dict[str, Any]:
		"""Check connectivity to the EFRIS API."""
		try:
			self._post("/efrisws/ws/taClientService/getClientStatus", {
				"tin": self.tin or _SANDBOX_TIN,
				"deviceNo": self.device_id or _SANDBOX_DEVICE_ID,
			})
			return {"reachable": True, "error": None}
		except EFRISSubmissionError as exc:
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
				"tin": self.tin,
				"deviceNo": self.device_id,
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				body = resp.read()
				result = json.loads(body)
				# EFRIS uses returnCode: "00" for success
				return_code = str(result.get("returnCode", result.get("code", "99")))
				if return_code not in ("00", "0", "000"):
					raise EFRISSubmissionError(
						f"EFRIS error {return_code}: {result.get('returnMessage', result.get('message', ''))}"
					)
				return result
		except urllib.error.HTTPError as exc:
			body_text = exc.read().decode(errors="replace")[:300]
			raise EFRISSubmissionError(f"EFRIS HTTP {exc.code}: {body_text}") from exc
		except EFRISSubmissionError:
			raise
		except Exception as exc:
			raise EFRISSubmissionError(f"EFRIS request failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test() -> None:
	"""Sandbox smoke test.  Run: python -m pgappforge.plugins.connectors.efris.client --test"""
	logging.basicConfig(level=logging.INFO)
	client = EFRISClient.sandbox()
	print(f"EFRIS sandbox client: TIN={client.tin}  DeviceID={client.device_id}  URL={client.base_url}")

	result = client.submit_invoice(
		invoice_number="TEST-001",
		customer_tin="0000000000",
		customer_name="Walk-in Customer",
		items=[
			{
				"description": "Electronic Goods",
				"quantity": 2,
				"unit_price_ugx": 118000,   # 100 000 + 18 % VAT
				"vat_rate_pct": 18,
			},
			{
				"description": "Exempt Agricultural Input",
				"quantity": 50,
				"unit_price_ugx": 2000,
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


__all__ = ["EFRISClient", "EFRISError", "EFRISSubmissionError"]
